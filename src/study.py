"""A declared, reproducible study: every policy on one continuous period.

A study is one TOML file (``config/studies/*.toml``). It names the period, the
region and asset, the policies, the executions, the scenario seeds and every
setting of :class:`~battery_dispatch.layers.LayerSettings`. The runner resolves
it, hashes the resolved form into a run identifier, and writes everything under
``runs/<run_id>/``, so two settings never overwrite each other:

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
import math
import platform
import subprocess
import sys
import tomllib
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from .aemo_forecasts import TABLES, ForecastCache, forecast_identity
from .bidding import NEM_TIMETABLE
from .ceiling import audit_ceiling, perfect_foresight_bound
from .config import AEST, BatteryConfig
from .data import MarketDataCache
from .forecast import (
    AemoForecast,
    Forecaster,
    LaggedForecaster,
    PerfectForecast,
    SameTimeProfile,
    ThinnedErrorHistory,
    grid_times,
)
from .layers import LayerSettings
from .mlf import file_sha256, load_loss_factor_schedule
from .mpc import run_forecast_policy
from .settlement import settle
from .validation import (
    assert_audit_passes,
    audit_completed_cycles,
    audit_dispatch,
    audit_prices,
)

STAGES = ("development", "validation", "test")


@dataclass(frozen=True)
class PolicySpec:
    """How one named policy forecasts and plans."""

    forecaster: str | None  # "perfect", "persistence", "profile", "aemo"; None for noop
    planner: str = "optimise"  # "optimise", "rule", "noop" or "ceiling"
    stochastic: bool = False
    description: str = ""


POLICIES: dict[str, PolicySpec] = {
    "ceiling": PolicySpec(
        "perfect", "ceiling", description="whole-period LP, exclusivity relaxed: a ceiling"
    ),
    "oracle": PolicySpec(
        "perfect", description="rolling engine given realised prices: an oracle benchmark"
    ),
    "noop": PolicySpec(None, "noop", description="never trades"),
    "rule_profile": PolicySpec("profile", "rule", description="k cheapest/dearest hours"),
    "rule_aemo": PolicySpec("aemo", "rule", description="k cheapest/dearest hours"),
    "L2_persistence": PolicySpec("persistence", description="point forecast"),
    "L2_profile": PolicySpec("profile", description="point forecast"),
    "L2_aemo": PolicySpec("aemo", description="point forecast"),
    "L3_profile": PolicySpec("profile", stochastic=True, description="error scenarios"),
    "L3_aemo": PolicySpec("aemo", stochastic=True, description="error scenarios"),
}

# Spike and negative-price thresholds for the revenue attribution, A$/MWh.
SPIKE_PRICE = 300.0
# The headline comparison is also reported without the period's N highest-price
# intervals, so a result carried by a handful of spikes is visible.
TOP_N_EXCLUDED = (24, 120)


@dataclass(frozen=True)
class StudyConfig:
    name: str
    stage: str
    start: str
    end: str
    region: str = "SA1"
    connection_point: str = "Hornsdale 275 kV"
    loss_factor_file: str = "config/loss_factors.csv"
    policies: tuple[str, ...] = tuple(POLICIES)
    executions: tuple[str, ...] = ("fixed_bands",)
    seeds: tuple[int, ...] = (20221101,)
    settings: LayerSettings = field(default_factory=LayerSettings)
    # Wrap every forecaster's error pool so it has no history before the
    # evaluation starts (the archive-gap control experiment).
    thin_error_history: bool = False
    # A test-stage study must name the frozen protocol and pin its hash.
    protocol: str | None = None
    protocol_sha256: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        if unknown := set(self.policies).difference(POLICIES):
            raise ValueError(f"Unknown policies: {sorted(unknown)}")
        if pd.Timestamp(self.end) <= pd.Timestamp(self.start):
            raise ValueError("end must be after start")
        if self.stage == "test" and not (self.protocol and self.protocol_sha256):
            raise ValueError("A test-stage study must pin its protocol and its sha256")
        if not self.seeds:
            raise ValueError("At least one seed is required")

    def resolved(self) -> dict[str, object]:
        payload = asdict(self)
        payload["policies"] = list(self.policies)
        payload["executions"] = list(self.executions)
        payload["seeds"] = list(self.seeds)
        return payload

    @property
    def config_sha256(self) -> str:
        encoded = json.dumps(self.resolved(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def run_id(self) -> str:
        return f"{self.name}-{self.config_sha256[:10]}"


def load_study(path: str | Path, **overrides: object) -> StudyConfig:
    """Read a study TOML; ``overrides`` replace top-level or ``settings`` keys."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    settings_raw = dict(raw.pop("settings", {}))
    for key in list(overrides):
        if key in {f.name for f in fields(LayerSettings)}:
            settings_raw[key] = overrides.pop(key)
    raw.update(overrides)
    known = {f.name for f in fields(LayerSettings)}
    if unknown := set(settings_raw).difference(known):
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    settings = LayerSettings(**settings_raw)
    for key in ("policies", "executions", "seeds"):
        if key in raw:
            raw[key] = tuple(raw[key])
    if unknown := set(raw).difference({f.name for f in fields(StudyConfig)}):
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    return StudyConfig(settings=settings, **raw)


def asset_for(config: StudyConfig) -> BatteryConfig:
    schedule = load_loss_factor_schedule(
        config.loss_factor_file, region=config.region, connection_point=config.connection_point
    )
    first = next(iter(schedule.table.by_financial_year.values()))
    return BatteryConfig(
        generation_loss_factor=first.generation,
        load_loss_factor=first.load,
        loss_factor_source=schedule.provenance,
        loss_factor_table=schedule.table,
        connection_point=schedule.connection_point,
        region=config.region,
    )


def warm_up_days(config: StudyConfig, asset: BatteryConfig) -> int:
    """Whole days of history the first decision and the first band design need.

    A fixed-band design plans from 12:30 two days before the period's first
    full trading day to the end of that day, about 40 hours, so its error pool
    reaches further back than an hourly decision's.
    """
    settings = config.settings
    per_day = settings.periods_per_day(asset)
    hourly = int(round(settings.horizon_hours * 60 / asset.interval_minutes))
    design = int(round(40 * 60 / asset.interval_minutes))
    steps = max(hourly, design) if "fixed_bands" in config.executions else hourly
    profile = SameTimeProfile(settings.profile_days, per_day)
    lag = settings.latency_minutes // asset.interval_minutes
    needed = settings.error_model(asset).min_history(profile, steps) + lag
    return math.ceil(needed / per_day) + 3


@dataclass(frozen=True)
class Task:
    policy: str
    execution: str
    seed: int | None

    @property
    def key(self) -> str:
        parts = [self.policy, self.execution]
        if self.seed is not None:
            parts.append(f"seed{self.seed}")
        return "__".join(parts)


def tasks_for(config: StudyConfig) -> list[Task]:
    tasks: list[Task] = []
    for policy in config.policies:
        spec = POLICIES[policy]
        if spec.planner in ("ceiling", "noop"):
            tasks.append(Task(policy, "none", None))
            continue
        for execution in config.executions:
            seeds = config.seeds if spec.stochastic else (None,)
            tasks.extend(Task(policy, execution, seed) for seed in seeds)
    return tasks


@dataclass
class _Inputs:
    asset: BatteryConfig
    evaluation: pd.DataFrame
    history: pd.DataFrame
    forecasts: Mapping[str, object]


_INPUTS: dict[str, _Inputs] = {}


def load_inputs(config: StudyConfig, cache: Path) -> _Inputs:
    """Prices for the warm-up and period, and the AEMO runs; cached per process."""
    asset = asset_for(config)
    key = f"{cache}|{config.region}|{config.start}|{config.end}|{warm_up_days(config, asset)}"
    if key not in _INPUTS:
        start = pd.Timestamp(config.start, tz=AEST)
        warm = start - pd.Timedelta(days=warm_up_days(config, asset))
        prices = MarketDataCache(cache).fetch_prices(warm, config.end, [config.region])
        history = prices.loc[prices["settlementdate"] <= start, ["settlementdate", "rrp"]]
        evaluation = prices.loc[prices["settlementdate"] > start, ["settlementdate", "rrp"]]
        forecasts = ForecastCache(cache).fetch(warm, config.end, config.region)
        _INPUTS[key] = _Inputs(
            asset, evaluation.reset_index(drop=True), history.reset_index(drop=True), forecasts
        )
    return _INPUTS[key]


def build_forecaster(
    name: str, inputs: _Inputs, settings: LayerSettings, *, thin: bool
) -> Forecaster:
    combined = pd.concat([inputs.history, inputs.evaluation], ignore_index=True)
    per_day = settings.periods_per_day(inputs.asset)
    profile = SameTimeProfile(settings.profile_days, per_day)
    if name == "perfect":
        return PerfectForecast(combined["rrp"].to_numpy(dtype=float))
    if name == "persistence":
        forecaster: Forecaster = SameTimeProfile(1, per_day)
    elif name == "profile":
        forecaster = profile
    elif name == "aemo":
        forecaster = AemoForecast(
            timestamps=grid_times(combined["settlementdate"]),
            predispatch=inputs.forecasts["predispatch"],
            p5min=inputs.forecasts["p5min"],
            fallback=profile,
            predispatch_hours=settings.aemo_predispatch_hours,
        )
    else:
        raise ValueError(f"Unknown forecaster {name}")
    lag = settings.latency_minutes // inputs.asset.interval_minutes
    if lag:
        forecaster = LaggedForecaster(forecaster, lag)
    if thin:
        forecaster = ThinnedErrorHistory(forecaster, len(inputs.history))
    return forecaster


def _attribution(intervals: pd.DataFrame, asset: BatteryConfig) -> dict[str, float]:
    rrp = intervals["rrp"]
    spike = rrp >= SPIKE_PRICE
    negative = rrp < 0
    order = rrp.sort_values(ascending=False).index
    row = {
        "energy_revenue": float(intervals["energy_revenue"].sum()),
        "degradation_cost": float(intervals["degradation_cost"].sum()),
        "discharge_revenue_aud": float(intervals["generation_revenue"].sum()),
        "charge_cost_aud": float(intervals["load_cost"].sum()),
        "discharged_mwh": float(intervals["discharge_mwh"].sum()),
        "charged_mwh": float(intervals["charge_mwh"].sum()),
        "spike_discharge_revenue_aud": float(intervals.loc[spike, "generation_revenue"].sum()),
        "spike_charge_cost_aud": float(intervals.loc[spike, "load_cost"].sum()),
        "negative_price_charge_income_aud": float(-intervals.loc[negative, "load_cost"].sum()),
        "negative_price_discharge_cost_aud": float(
            -intervals.loc[negative, "generation_revenue"].sum()
        ),
        "soc_limited_intervals": int(intervals.get("soc_limited", pd.Series(0)).sum()),
    }
    for n in TOP_N_EXCLUDED:
        row[f"total_revenue_excl_top{n}"] = float(intervals["total_revenue"].drop(order[:n]).sum())
    return row


_CEILINGS: dict[tuple[int, float], tuple[object, pd.DataFrame]] = {}


def run_task(
    config: StudyConfig, task: Task, cache: Path, inputs: _Inputs | None = None
) -> dict[str, object]:
    """Run, settle and audit one task. Raises on any failure; no fallback."""
    inputs = inputs or load_inputs(config, cache)
    asset = inputs.asset
    settings = config.settings if task.seed is None else replace(config.settings, seed=task.seed)
    spec = POLICIES[task.policy]
    deg_cost = settings.deg_cost
    soc_initial = asset.initial_soc_mwh
    evaluation = inputs.evaluation
    started = perf_counter()
    # Every task in a process shares one whole-period ceiling solve.
    ceiling_key = (id(inputs), deg_cost)
    if ceiling_key not in _CEILINGS:
        _CEILINGS[ceiling_key] = perfect_foresight_bound(
            evaluation, asset, soc_initial=soc_initial, deg_cost=deg_cost
        )
    bound, bound_dispatch = _CEILINGS[ceiling_key]
    ceiling = {
        "perfect_foresight_ceiling_aud": bound.objective_value,
        "ceiling_solve_seconds": bound.solve_seconds,
    }
    band_log: list[dict[str, object]] = []
    if spec.planner == "ceiling":
        trace = bound_dispatch.assign(soc_limited=False)
        revenue = None
    else:
        if spec.planner == "noop":
            trace = evaluation[["settlementdate"]].assign(
                charge_mw=0.0, discharge_mw=0.0, soc_mwh=soc_initial, soc_limited=False
            )
        else:
            forecaster = build_forecaster(
                spec.forecaster,
                inputs,
                settings,
                thin=config.thin_error_history and spec.forecaster != "perfect",
            )
            errors = settings.error_model(asset)
            trace = run_forecast_policy(
                evaluation,
                inputs.history,
                asset,
                forecaster,
                scenarios=errors if spec.stochastic else None,
                band_errors=errors,
                bands=settings.bands,
                horizon_hours=settings.horizon_hours,
                commit_minutes=settings.commit_minutes,
                shared_minutes=settings.shared_minutes,
                deg_cost=deg_cost,
                soc_initial=soc_initial,
                execution=task.execution,
                planner="rule" if spec.planner == "rule" else "optimise",
                rule_hours=settings.rule_hours,
                timetable=NEM_TIMETABLE,
                band_log=band_log,
            )
        revenue = settle(trace, evaluation, asset, deg_cost=deg_cost)
    if revenue is None:
        # The ceiling's schedule may charge and discharge at once, so it is
        # reported from its own objective, not settled as a dispatch.
        intervals = settle(
            bound_dispatch.assign(charge_mw=0.0, discharge_mw=0.0, soc_mwh=soc_initial),
            evaluation,
            asset,
            deg_cost=deg_cost,
        ).intervals
        dt = asset.interval_hours
        coefficients = intervals[["rrp", "generation_loss_factor", "load_loss_factor"]]
        intervals["charge_mw"] = bound_dispatch["charge_mw"].to_numpy()
        intervals["discharge_mw"] = bound_dispatch["discharge_mw"].to_numpy()
        intervals["soc_mwh"] = bound_dispatch["soc_mwh"].to_numpy()
        intervals["charge_mwh"] = intervals["charge_mw"] * dt
        intervals["discharge_mwh"] = intervals["discharge_mw"] * dt
        intervals["generation_revenue"] = (
            dt
            * coefficients["generation_loss_factor"]
            * coefficients["rrp"]
            * intervals["discharge_mw"]
        )
        intervals["load_cost"] = (
            dt * coefficients["load_loss_factor"] * coefficients["rrp"] * intervals["charge_mw"]
        )
        intervals["energy_revenue"] = intervals["generation_revenue"] - intervals["load_cost"]
        intervals["degradation_cost"] = dt * deg_cost * intervals["discharge_mw"]
        intervals["total_revenue"] = intervals["energy_revenue"] - intervals["degradation_cost"]
        intervals["soc_limited"] = False
        total = float(intervals["total_revenue"].sum())
        if abs(total - bound.objective_value) > 1e-3 + 1e-9 * abs(total):
            raise RuntimeError("Ceiling interval cashflows do not reproduce its objective")
        audit = {"horizon_gap_aud": 0.0, "audit_passed": True}
        row: dict[str, object] = {
            "total_revenue": total,
            "terminal_soc_mwh": bound.soc_final_mwh,
            "decision_count": 1,
            "max_solver_mip_gap": 0.0,
        }
    else:
        intervals = revenue.intervals
        audit = {
            **audit_dispatch(trace, asset, soc_initial=soc_initial),
            **audit_completed_cycles(
                intervals, asset, deg_cost=deg_cost, initial_soc_mwh=soc_initial
            ),
            **audit_ceiling(ceiling, revenue),
        }
        if spec.planner == "noop":
            audit.update(solver_all_optimal=True, max_solver_mip_gap=0.0)
        # A perfect plan executed as planned never completes a loss-making
        # cycle, so that is gated. Fixed daily band prices can force a perfect
        # plan to trade at a band rather than at its own limit, so under them
        # it is reported, like any forecast-driven policy's.
        assert_audit_passes(
            audit,
            require_cycle_break_even=spec.forecaster == "perfect"
            and task.execution != "fixed_bands",
        )
        row = {
            "total_revenue": revenue.total_revenue,
            "terminal_soc_mwh": audit["terminal_soc_mwh"],
            "loss_making_cycle_count": audit["completed_cycle_break_even_violation_count"],
            "loss_making_cycle_aud": audit["completed_cycle_loss_aud"],
            "decision_count": audit["solver_window_count"],
            "max_solver_mip_gap": audit["max_solver_mip_gap"],
            "total_exclusivity_binary_count": audit.get("total_exclusivity_binary_count"),
        }
        if "forecast_rrp" in intervals:
            row["committed_forecast_mae"] = float(
                np.mean(np.abs(intervals["forecast_rrp"] - intervals["rrp"]))
            )
            per_decision = intervals.drop_duplicates("window_id")
            row["min_error_pool_days"] = float(per_decision["error_pool_days"].min())
            row["mean_error_pool_days"] = float(per_decision["error_pool_days"].mean())
            row["median_band_spread_aud"] = float(per_decision["band_spread_aud"].median())
            row["scenario_count"] = int(per_decision["scenario_count"].iloc[0])
            offered = intervals["charge_tranches_offered"] + intervals["discharge_tranches_offered"]
            row["no_offer_interval_share"] = float((offered == 0).mean())
        audit["audit_passed"] = True
    ceiling_value = bound.objective_value
    row.update(
        {
            "task": task.key,
            "policy": task.policy,
            "execution": task.execution,
            "seed": task.seed,
            "description": spec.description,
            "perfect_foresight_ceiling_aud": ceiling_value,
            "gap_to_ceiling_aud": ceiling_value - float(row["total_revenue"]),
            "share_of_ceiling": float(row["total_revenue"]) / ceiling_value
            if ceiling_value > 0
            else np.nan,
            "equivalent_full_cycles": float(intervals["discharge_mwh"].sum()) / asset.energy_mwh,
            **_attribution(intervals, asset),
            "runtime_seconds": perf_counter() - started,
        }
    )
    columns = [
        "settlementdate",
        "rrp",
        "charge_mw",
        "discharge_mw",
        "soc_mwh",
        "charge_mwh",
        "discharge_mwh",
        "generation_revenue",
        "load_cost",
        "energy_revenue",
        "degradation_cost",
        "total_revenue",
        "soc_limited",
        "forecast_rrp",
        "planned_charge_mw",
        "planned_discharge_mw",
        "stored_energy_value",
        "charge_limit_rrp",
        "discharge_limit_rrp",
        "charge_tranches_offered",
        "discharge_tranches_offered",
        "window_id",
        "error_pool_days",
        "band_spread_aud",
    ]
    kept = intervals[[c for c in columns if c in intervals]].copy()
    return {
        "row": row,
        "trace": kept,
        "bands": pd.DataFrame(band_log),
        "audit": {k: _jsonable(v) for k, v in audit.items()},
    }


def _jsonable(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _run_task_safely(config: StudyConfig, task: Task, cache: Path) -> dict[str, object]:
    try:
        return {"task": task, "ok": True, **run_task(config, task, cache)}
    except Exception as error:  # noqa: BLE001 - every failure is reported, then fails the run
        return {
            "task": task,
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }


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


def check_protocol(config: StudyConfig, root: Path) -> None:
    if config.protocol is None:
        return
    actual = file_sha256(root / config.protocol)
    if config.protocol_sha256 and actual != config.protocol_sha256:
        raise SystemExit(
            f"{config.protocol} has changed since this study was frozen "
            f"(sha256 {actual} != {config.protocol_sha256})"
        )


def run_study(
    config: StudyConfig,
    *,
    cache: Path = Path("data/cache"),
    output: Path = Path("runs"),
    jobs: int = 1,
    root: Path = Path("."),
    report: Callable[[str], None] = print,
) -> Path:
    """Run every task of ``config`` and write ``output/<run_id>/``."""
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
    summary.to_csv(directory / "summary.csv", index=False)
    if monthly:
        pd.concat(monthly, ignore_index=True).to_csv(directory / "monthly.csv", index=False)
        pd.concat(daily, ignore_index=True).to_csv(directory / "daily.csv", index=False)
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
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
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
