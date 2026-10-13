"""Run the three-layer revenue comparison on the reference months.

Layer 1 is the perfect-foresight bound, layer 2 dispatches hourly on a point
price forecast, and layer 3 dispatches hourly on forecast-error scenarios
around the same forecast, each for a naive profile and for AEMO's published
pre-dispatch forecasts. By default each committed hour is offered in ten
price bands cleared at realised prices; ``--execution bid`` offers one limit
per direction and ``--execution committed`` dispatches the planned quantities
at any price. Each month's forecasts are warmed up on the preceding calendar
month, which is read but never dispatched or settled.

Every input month is checked against its committed manifest by
``scripts/verify_reference.py`` before this is run in CI.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from battery_dispatch.aemo_forecasts import ForecastCache
from battery_dispatch.config import AEST, BatteryConfig
from battery_dispatch.data import MarketDataCache
from battery_dispatch.layers import LAYER_ORDER, LayerSettings, layer_gaps, run_layers
from battery_dispatch.mlf import load_loss_factor_schedule

REGION = "SA1"
CONNECTION_POINT = "Hornsdale 275 kV"

# (label, warm-up start, evaluation start, evaluation end), physical AEST bounds.
REFERENCE_MONTHS = [
    # The extreme month: 38% of intervals negative-priced.
    ("2022-11", "2022-10-01 00:00", "2022-11-01 00:00", "2022-12-01 00:00"),
    # A typical FY2022-23 month: negative-price share and daily spread near
    # the financial-year median.
    ("2023-04", "2023-03-01 00:00", "2023-04-01 00:00", "2023-05-01 00:00"),
]

REPORT_COLUMNS = [
    "month",
    "layer",
    "forecaster",
    "total_revenue",
    "gap_to_bound_aud",
    "share_of_bound",
    "equivalent_full_cycles",
    "terminal_soc_mwh",
    "loss_making_cycle_count",
    "committed_forecast_mae",
    "decision_count",
    "runtime_seconds",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--output", type=Path, default=Path("analysis"))
    parser.add_argument(
        "--execution",
        choices=["bands", "bid", "committed"],
        default="bands",
        help="How committed hours meet realised prices (default: ten price bands)",
    )
    parser.add_argument(
        "--aemo-predispatch-hours",
        type=float,
        default=LayerSettings.aemo_predispatch_hours,
        help="Use AEMO pre-dispatch this many hours ahead, the profile beyond; 0 for "
        "its whole horizon (default: %(default)s)",
    )
    parser.add_argument(
        "--no-error-cap",
        action="store_true",
        help="Use past forecast errors uncapped instead of winsorized at 5%%/95%%",
    )
    parser.add_argument(
        "--month",
        action="append",
        help="Run only the named reference month (e.g. 2023-04); repeat for more",
    )
    return parser


def reference_asset() -> BatteryConfig:
    schedule = load_loss_factor_schedule(
        "config/loss_factors.csv", region=REGION, connection_point=CONNECTION_POINT
    )
    first = next(iter(schedule.table.by_financial_year.values()))
    return BatteryConfig(
        generation_loss_factor=first.generation,
        load_loss_factor=first.load,
        loss_factor_source=schedule.provenance,
        loss_factor_table=schedule.table,
        connection_point=schedule.connection_point,
        region=REGION,
    )


def main() -> None:
    args = build_parser().parse_args()
    logging.getLogger("linopy").setLevel(logging.WARNING)
    months = REFERENCE_MONTHS
    if args.month:
        known = {label for label, *_ in REFERENCE_MONTHS}
        if unknown := set(args.month).difference(known):
            raise ValueError(f"Unknown months: {sorted(unknown)}")
        months = [row for row in REFERENCE_MONTHS if row[0] in set(args.month)]

    asset = reference_asset()
    cache = MarketDataCache(args.cache)
    forecasts = ForecastCache(args.cache)
    settings = LayerSettings(
        execution=args.execution,
        error_winsorize=None if args.no_error_cap else LayerSettings.error_winsorize,
        aemo_predispatch_hours=args.aemo_predispatch_hours or None,
    )
    trace_dir = args.output / "layer_traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[pd.DataFrame] = []
    gap_rows: list[dict[str, object]] = []
    wall_started = time.perf_counter()
    for label, warm_up, start, end in months:
        prices = cache.fetch_prices(warm_up, end, [REGION])
        boundary = pd.Timestamp(start, tz=AEST)
        history = prices.loc[prices["settlementdate"] <= boundary]
        evaluation = prices.loc[prices["settlementdate"] > boundary]

        def report(layer: str, seconds: float, label: str = label) -> None:
            print(f"{label}  {layer:>20}  {seconds:6.1f}s", flush=True)

        result = run_layers(
            evaluation,
            history,
            asset,
            settings,
            aemo_forecasts=forecasts.fetch(warm_up, end, REGION),
            progress=report,
        )
        summary = result.summary.copy()
        summary.insert(0, "month", label)
        summaries.append(summary)
        gap_rows.append({"month": label, **layer_gaps(result.summary)})
        for layer, trace in result.traces.items():
            trace.to_csv(trace_dir / f"{label}_{layer}.csv", index=False)
        result.bound_dispatch.to_csv(trace_dir / f"{label}_ceiling.csv", index=False)

    results = pd.concat(summaries, ignore_index=True)
    results["layer"] = pd.Categorical(results["layer"], LAYER_ORDER, ordered=True)
    results = results.sort_values(["month", "layer"])
    gaps = pd.DataFrame(gap_rows)
    results.to_csv(args.output / "layers.csv", index=False)
    gaps.to_csv(args.output / "layer_gaps.csv", index=False)
    pd.set_option("display.width", 200)
    print()
    print(results[REPORT_COLUMNS].to_string(index=False, float_format=lambda v: f"{v:,.3f}"))
    print()
    print(gaps.to_string(index=False, float_format=lambda v: f"{v:,.0f}"))
    print(f"\nTotal {time.perf_counter() - wall_started:.1f}s. Wrote {args.output}/layers.csv")


if __name__ == "__main__":
    main()
