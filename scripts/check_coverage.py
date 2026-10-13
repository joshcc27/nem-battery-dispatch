"""Report input coverage for every month of a candidate study period.

Downloads any missing prices and AEMO forecasts, then writes one row per month
to ``data/coverage/<region>_<first>_<last>.csv`` with the declared exclusion
rule beside it. Run this, and decide exclusions, before running any policy on
the period.

    uv run python scripts/check_coverage.py --first 2022-11 --last 2024-05
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from battery_dispatch.aemo_forecasts import ForecastCache
from battery_dispatch.coverage import CoverageRule, month_coverage
from battery_dispatch.data import MarketDataCache
from battery_dispatch.mlf import load_loss_factor_schedule


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", required=True, help="First month, YYYY-MM")
    parser.add_argument("--last", required=True, help="Last month, YYYY-MM")
    parser.add_argument("--region", default="SA1")
    parser.add_argument("--connection-point", default="Hornsdale 275 kV")
    parser.add_argument("--loss-factor-file", type=Path, default=Path("config/loss_factors.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--output", type=Path, default=Path("data/coverage"))
    args = parser.parse_args()
    logging.getLogger("nemosis").setLevel(logging.WARNING)

    schedule = load_loss_factor_schedule(
        args.loss_factor_file, region=args.region, connection_point=args.connection_point
    )
    prices = MarketDataCache(args.cache)
    forecasts = ForecastCache(args.cache)
    rule = CoverageRule()
    rows = []
    for month in pd.period_range(args.first, args.last, freq="M"):
        row = month_coverage(month.start_time, args.region, prices, forecasts, schedule.table, rule)
        print(json.dumps(row), flush=True)
        rows.append(row)
    report = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    stem = f"{args.region.lower()}_{args.first}_{args.last}"
    report.to_csv(args.output / f"{stem}.csv", index=False)
    (args.output / f"{stem}_rule.txt").write_text(rule.describe() + "\n", encoding="utf-8")
    print()
    columns = [
        "month",
        "price_complete",
        "loss_factors_configured",
        "predispatch_current_share",
        "p5min_current_share",
        "predispatch_longest_gap_hours",
        "usable",
        "exclusion_reasons",
    ]
    print(report[columns].to_string(index=False))


if __name__ == "__main__":
    main()
