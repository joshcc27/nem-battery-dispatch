"""Run the optional endpoint/degradation grid on the November 2022 month.

This is a secondary analysis of the perfect-foresight rolling dispatch, not
part of the three-layer comparison (``battery-dispatch reference``), and CI does
not run it. The exclusivity reduction in ``exclusivity_binding_mask`` keeps
every scenario at a strict 1e-6 relative gap; the grid takes about 100
seconds, 74 of them in the A$10/MWh case.

The A$0/MWh degradation case is deliberately out of scope: at zero degradation
the model is paid to burn energy through round-trip losses, the exclusivity
binary binds at 38% of intervals instead of 2.7%, and the resulting MILP is
not tractable at a strict gap. See docs/VALIDATION.md.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from battery_dispatch.backtest.sensitivity import EndpointCase, run_sensitivities
from battery_dispatch.dispatch.optimiser import STRICT_SOLVER_POLICY
from battery_dispatch.market.config import BatteryConfig
from battery_dispatch.market.data import MarketDataCache
from battery_dispatch.market.mlf import load_loss_factor_schedule

REFERENCE_START = "2022-11-01 00:00"
REFERENCE_END = "2022-12-01 00:00"
REFERENCE_REGION = "SA1"
REFERENCE_CONNECTION_POINT = "Hornsdale 275 kV"
REFERENCE_FINANCIAL_YEAR = "2022-23"

REPORT_COLUMNS = [
    "scenario_id",
    "endpoint_case",
    "degradation_cost_per_mwh",
    "total_revenue",
    "perfect_foresight_ceiling_aud",
    "horizon_gap_aud",
    "energy_revenue",
    "equivalent_full_cycles",
    "terminal_soc_mwh",
    "solver_all_optimal",
    "max_solver_mip_gap",
    "pure_lp_window_count",
    "total_exclusivity_binary_count",
    "wall_clock_seconds",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/analysis/reference_sensitivities.csv")
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Run only the named scenario; repeat to select more than one",
    )
    return parser


def reference_asset(cache_root: Path) -> tuple[BatteryConfig, pd.DataFrame]:
    schedule = load_loss_factor_schedule(
        "config/loss_factors.csv",
        region=REFERENCE_REGION,
        connection_point=REFERENCE_CONNECTION_POINT,
    )
    factors = schedule.table.for_financial_year(REFERENCE_FINANCIAL_YEAR)
    asset = BatteryConfig(
        generation_loss_factor=factors.generation,
        load_loss_factor=factors.load,
        loss_factor_source=schedule.provenance,
        loss_factor_table=schedule.table,
        connection_point=schedule.connection_point,
        region=REFERENCE_REGION,
    )
    prices = MarketDataCache(cache_root).fetch_prices(
        REFERENCE_START, REFERENCE_END, [REFERENCE_REGION]
    )
    return asset, prices


def main() -> None:
    args = build_parser().parse_args()
    logging.getLogger("linopy").setLevel(logging.WARNING)
    asset, prices = reference_asset(args.cache)

    scenarios = [
        (
            "headline",
            EndpointCase("minimum_no_salvage", asset.soc_min_mwh, 0.0),
            25.0,
        ),
        (
            "degradation_10",
            EndpointCase("minimum_no_salvage", asset.soc_min_mwh, 0.0),
            10.0,
        ),
        (
            "degradation_50",
            EndpointCase("minimum_no_salvage", asset.soc_min_mwh, 0.0),
            50.0,
        ),
        (
            "midpoint_initial_soc",
            EndpointCase("midpoint_no_salvage", asset.energy_mwh / 2.0, 0.0),
            25.0,
        ),
        (
            "lookahead_salvage_400",
            EndpointCase("minimum_with_400_aud_salvage", asset.soc_min_mwh, 400.0),
            25.0,
        ),
    ]
    known = {scenario_id for scenario_id, _, _ in scenarios}
    if args.scenario:
        if unknown := set(args.scenario).difference(known):
            raise ValueError(f"Unknown scenarios: {sorted(unknown)}")
        scenarios = [row for row in scenarios if row[0] in set(args.scenario)]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[pd.DataFrame] = []
    for scenario_id, endpoint, degradation_cost in scenarios:
        started = time.perf_counter()
        result = run_sensitivities(
            prices,
            asset,
            endpoint_cases=[endpoint],
            degradation_costs=[degradation_cost],
            policy=STRICT_SOLVER_POLICY,
        )
        result["wall_clock_seconds"] = time.perf_counter() - started
        result.insert(0, "scenario_id", scenario_id)
        rows.append(result)
        print(
            f"{scenario_id:>22}  {result['wall_clock_seconds'].iloc[0]:6.1f}s"
            f"  net=A${result['total_revenue'].iloc[0]:,.0f}",
            flush=True,
        )

    results = pd.concat(rows, ignore_index=True)
    results.to_csv(args.output, index=False, lineterminator="\n")
    print()
    print(results[REPORT_COLUMNS].to_string(index=False))
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
