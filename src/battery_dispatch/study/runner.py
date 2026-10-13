"""A declared, reproducible study: every policy on one continuous period.

A study is one TOML file (``config/studies/*.toml``). It names the period, the
region and asset, the policies, the executions, the scenario seeds and every
setting of :class:`~battery_dispatch.study.layers.LayerSettings`. The runner resolves
it, hashes the resolved form into a run identifier, and writes everything under
``artifacts/artifacts/runs/<run_id>/``, so two settings never overwrite each other:

- ``manifest.json``: the resolved configuration, the source commit and whether
  the working tree was clean, the Python and package versions, the identity of
  every input month (price checksum, forecast checksums, loss-factor file
  hash), each task's audit status and any failure;
- ``summary.csv``: one row per policy, execution and seed over the whole
  period, with the audit evidence and the revenue attribution;
- ``monthly.csv`` and ``daily.csv``: calendar-month and trading-day slices of
  the same continuous traces;
- ``traces/``: one settled interval trace per task, and the fixed band prices
  each trading day was given.

State of charge is carried continuously through the whole period. Every policy
and the ceiling start at minimum SOC and value closing inventory at zero at the
end of the period, so monthly figures are slices of one trace; the ceiling's
monthly slices are not themselves monthly upper bounds.

A solve that fails, or a trace that fails its audit, fails that task: there is
no fallback. The failure is recorded in the manifest, the remaining tasks still
run, and the runner exits non-zero.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from time import perf_counter

import pandas as pd

from battery_dispatch.audit.validation import (
    audit_prices,
)
from battery_dispatch.dispatch.bidding import NEM_TIMETABLE
from battery_dispatch.market.aemo_forecasts import TABLES, ForecastCache, forecast_identity
from battery_dispatch.market.config import AEST, BatteryConfig
from battery_dispatch.market.data import MarketDataCache
from battery_dispatch.market.mlf import file_sha256
from battery_dispatch.study.spec import (
    StudyConfig,
    Task,
    asset_for,
    tasks_for,
    warm_up_days,
)
from battery_dispatch.study.tasks import (
    _run_task_safely,
)


def trading_day_of(settlementdate: pd.Series) -> pd.Series:
    return pd.Series(NEM_TIMETABLE.trading_day(settlementdate), index=settlementdate.index)


def month_of(settlementdate: pd.Series) -> pd.Series:
    start = pd.DatetimeIndex(settlementdate).tz_convert(AEST) - pd.Timedelta(minutes=5)
    return pd.Series(start.strftime("%Y-%m"), index=settlementdate.index)


def slices(
    trace: pd.DataFrame, task: Task, asset: BatteryConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calendar-month and trading-day slices of one continuous settled trace."""
    frame = trace.assign(
        month=month_of(trace["settlementdate"]),
        trading_day=trading_day_of(trace["settlementdate"]),
    )
    sums = [
        "total_revenue",
        "energy_revenue",
        "degradation_cost",
        "generation_revenue",
        "load_cost",
        "charge_mwh",
        "discharge_mwh",
    ]
    monthly = (
        frame.groupby("month")
        .agg(
            **{c: (c, "sum") for c in sums},
            closing_soc_mwh=("soc_mwh", "last"),
            max_rrp=("rrp", "max"),
            intervals=("rrp", "size"),
        )
        .reset_index()
    )
    monthly["equivalent_full_cycles"] = monthly["discharge_mwh"] / asset.energy_mwh
    daily = (
        frame.groupby("trading_day")
        .agg(
            total_revenue=("total_revenue", "sum"),
            intervals=("rrp", "size"),
            closing_soc_mwh=("soc_mwh", "last"),
        )
        .reset_index()
    )
    for table in (monthly, daily):
        table.insert(0, "task", task.key)
        table.insert(1, "policy", task.policy)
        table.insert(2, "execution", task.execution)
        table.insert(3, "seed", task.seed)
    return monthly, daily


def git_state(root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    status = run(
        "status", "--porcelain", "--", "src", "scripts", "config", "pyproject.toml", "uv.lock"
    )
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "source_tree_clean": status == "",
        "source_tree_changes": status.splitlines(),
    }


def environment() -> dict[str, object]:
    packages = {}
    for name in ("battery-dispatch", "highspy", "linopy", "numpy", "pandas", "pyarrow", "nemosis"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
    }


def input_identity(config: StudyConfig, cache: Path, asset: BatteryConfig) -> dict[str, object]:
    """Checksums of every price and forecast month the study reads."""
    start = pd.Timestamp(config.start, tz=AEST) - pd.Timedelta(days=warm_up_days(config, asset))
    end = pd.Timestamp(config.end, tz=AEST)
    prices = MarketDataCache(cache)
    forecasts = ForecastCache(cache)
    months = []
    for month in pd.period_range(
        start.tz_localize(None), (end - pd.Timedelta(minutes=5)).tz_localize(None), freq="M"
    ):
        first = month.start_time
        last = first + pd.offsets.MonthBegin(1)
        frame = prices.fetch_prices(first, last, [config.region])
        audit = audit_prices(
            frame,
            expected_start=pd.Timestamp(first, tz=AEST),
            expected_end=pd.Timestamp(last, tz=AEST),
        )
        row = {
            "month": month.strftime("%Y-%m"),
            "price_rows": audit["price_row_count"],
            "price_sha256": audit["price_sha256"],
        }
        for table in TABLES:
            identity = forecast_identity(forecasts.month(table, config.region, first))
            row[f"{table}_rows"] = identity["row_count"]
            row[f"{table}_sha256"] = identity["canonical_sha256"]
        months.append(row)
    return {
        "warm_up_start": start.isoformat(),
        "evaluation_start": pd.Timestamp(config.start, tz=AEST).isoformat(),
        "evaluation_end": end.isoformat(),
        "loss_factor_file_sha256": file_sha256(config.loss_factor_file),
        "months": months,
    }


def text_sha256(path: str | Path) -> str:
    """SHA-256 of a text file with line endings normalised to LF.

    Git may check a text file out with CRLF on Windows and LF elsewhere, so a
    byte hash would refuse the same protocol on one of them.
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def check_protocol(config: StudyConfig, root: Path) -> None:
    if config.protocol is None:
        return
    actual = text_sha256(root / config.protocol)
    if config.protocol_sha256 and actual != config.protocol_sha256:
        raise SystemExit(
            f"{config.protocol} has changed since this study was frozen "
            f"(sha256 {actual} != {config.protocol_sha256})"
        )


def run_study(
    config: StudyConfig,
    *,
    cache: Path = Path("data/cache"),
    output: Path = Path("artifacts/runs"),
    jobs: int = 1,
    root: Path = Path("."),
    report: Callable[[str], None] | None = None,
) -> Path:
    """Run every task of ``config`` and write ``output/<run_id>/``."""
    if report is None:

        def report(message: str) -> None:
            print(message, flush=True)

    check_protocol(config, root)
    source = git_state(root)
    if config.stage == "test" and not source["source_tree_clean"]:
        raise SystemExit(
            "A test-stage study runs only from a clean source tree, so its result is "
            "attributable to one commit: " + ", ".join(source["source_tree_changes"])
        )
    asset = asset_for(config)
    directory = output / config.run_id
    (directory / "traces").mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    wall = perf_counter()
    identity = input_identity(config, cache, asset)
    tasks = tasks_for(config)
    report(f"{config.run_id}: {len(tasks)} tasks, warm-up {warm_up_days(config, asset)} days")
    results: list[dict[str, object]] = []
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(_run_task_safely, config, task, cache) for task in tasks]
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                _progress(result, report)
    else:
        for task in tasks:
            result = _run_task_safely(config, task, cache)
            results.append(result)
            _progress(result, report)

    rows, monthly, daily, audits, failures = [], [], [], {}, []
    for result in sorted(results, key=lambda r: tasks.index(r["task"])):
        task = result["task"]
        if not result["ok"]:
            failures.append(
                {"task": task.key, "error": result["error"], "traceback": result["traceback"]}
            )
            continue
        rows.append(result["row"])
        audits[task.key] = result["audit"]
        trace = result["trace"]
        trace.to_parquet(directory / "traces" / f"{task.key}.parquet", index=False)
        if len(result["bands"]):
            result["bands"].to_parquet(
                directory / "traces" / f"{task.key}__bands.parquet", index=False
            )
        month, day = slices(trace, task, asset)
        monthly.append(month)
        daily.append(day)
    summary = pd.DataFrame(rows)
    if len(summary):
        first = [
            "task",
            "policy",
            "execution",
            "seed",
            "total_revenue",
            "share_of_ceiling",
            "gap_to_ceiling_aud",
        ]
        summary = summary[first + [c for c in summary.columns if c not in first]]
    summary.to_csv(directory / "summary.csv", index=False, lineterminator="\n")
    if monthly:
        pd.concat(monthly, ignore_index=True).to_csv(
            directory / "monthly.csv", index=False, lineterminator="\n"
        )
        pd.concat(daily, ignore_index=True).to_csv(
            directory / "daily.csv", index=False, lineterminator="\n"
        )
    manifest = {
        "run_id": config.run_id,
        "config_sha256": config.config_sha256,
        "config": config.resolved(),
        "started_utc": started.isoformat(),
        "wall_seconds": perf_counter() - wall,
        "jobs": jobs,
        "warm_up_days": warm_up_days(config, asset),
        "source": source,
        "environment": environment(),
        "inputs": identity,
        "asset": {
            "power_mw": asset.power_mw,
            "energy_mwh": asset.energy_mwh,
            "round_trip_efficiency": asset.round_trip_efficiency,
            "soc_min_mwh": asset.soc_min_mwh,
            "soc_max_mwh": asset.soc_max_mwh,
            "initial_soc_mwh": asset.initial_soc_mwh,
            "terminal_value_per_mwh": 0.0,
            "connection_point": asset.connection_point,
        },
        "tasks": [task.key for task in tasks],
        "audits": audits,
        "failures": failures,
        "all_audits_passed": not failures,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8", newline="\n"
    )
    report(f"Wrote {directory} in {manifest['wall_seconds']:.0f}s")
    if failures:
        for failure in failures:
            report(f"FAILED {failure['task']}: {failure['error']}")
    return directory


def _progress(result: dict[str, object], report: Callable[[str], None]) -> None:
    task = result["task"]
    if result["ok"]:
        row = result["row"]
        report(
            f"  {task.key:<45} {row['total_revenue']:>14,.0f}  "
            f"{row['share_of_ceiling']:7.1%}  {row['runtime_seconds']:6.1f}s"
        )
    else:
        report(f"  {task.key:<45} FAILED {result['error']}")
