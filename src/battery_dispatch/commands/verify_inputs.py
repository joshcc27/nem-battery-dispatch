"""Check that the inputs in the cache are the ones a published result was run on.

    uv run battery-dispatch verify-inputs results/test/report_manifest.json

Every study manifest records, for each month it read, the canonical checksum
of its prices and of both AEMO forecast tables. This re-derives them from the
cache, downloading any month that is missing, and fails on any difference, so
a reproduction is known to start from identical data.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from battery_dispatch.audit.validation import audit_prices
from battery_dispatch.market.aemo_forecasts import TABLES, ForecastCache, forecast_identity
from battery_dispatch.market.config import AEST
from battery_dispatch.market.data import MarketDataCache


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="battery-dispatch verify-inputs",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--region", default="SA1")
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    args = parser.parse_args(argv)
    logging.getLogger("nemosis").setLevel(logging.WARNING)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    prices = MarketDataCache(args.cache)
    forecasts = ForecastCache(args.cache)
    failures = []
    for month in manifest["inputs"]["months"]:
        first = pd.Timestamp(month["month"])
        last = first + pd.offsets.MonthBegin(1)
        frame = prices.fetch_prices(first, last, [args.region])
        audit = audit_prices(frame, expected_start=pd.Timestamp(first, tz=AEST),
                             expected_end=pd.Timestamp(last, tz=AEST))
        checks = {"price_sha256": audit["price_sha256"], "price_rows": audit["price_row_count"]}
        for table in TABLES:
            identity = forecast_identity(forecasts.month(table, args.region, first))
            checks[f"{table}_sha256"] = identity["canonical_sha256"]
            checks[f"{table}_rows"] = identity["row_count"]
        bad = [key for key, value in checks.items() if month[key] != value]
        print(f"{month['month']}: {'OK' if not bad else 'BAD ' + ', '.join(bad)}")
        failures += [f"{month['month']} {key}" for key in bad]
    if failures:
        raise SystemExit("Inputs differ from the published result: " + "; ".join(failures))
    print(f"All {len(manifest['inputs']['months'])} input months match")


if __name__ == "__main__":
    main()
