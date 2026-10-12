"""Fetch every reference input month and check it against its committed manifest.

The manifest records the identity of the input data, not a description of it.
A change in AEMO's archive, in the ingest contract, or in the intervention or
interval-ending conventions moves the checksum and fails here, before any
result is computed from the changed data. The same holds for the AEMO price
forecasts each month pins, including a month the archive is missing.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from battery_dispatch.aemo_forecasts import TABLES, ForecastCache, forecast_identity
from battery_dispatch.data import MarketDataCache
from battery_dispatch.validation import audit_prices

MANIFEST_DIR = Path("data/manifests")
REGION = "SA1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        help="Check only this manifest; repeat for more. Default: every committed one",
    )
    return parser


def verify(
    manifest_path: Path, cache: MarketDataCache, forecasts: ForecastCache
) -> list[str]:
    """Print each check for one manifest and return the names that failed."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    period = manifest["period"]
    start = period["physical_start_inclusive"]
    end = period["physical_end_exclusive"]
    print(f"{manifest_path}")
    prices = cache.fetch_prices(start, end, [REGION])
    audit = audit_prices(prices, expected_start=start, expected_end=end)
    expected = manifest["validation"]

    fields = [
        ("row_count", "price_row_count"),
        ("duplicate_key_count", "price_duplicate_count"),
        ("missing_interval_count", "price_missing_interval_count"),
        ("unexpected_interval_count", "price_unexpected_interval_count"),
        ("rrp_min_aud_per_mwh", "rrp_min"),
        ("rrp_max_aud_per_mwh", "rrp_max"),
        ("canonical_price_sha256", "price_sha256"),
    ]
    checks = [(name, audit[key], expected[name]) for name, key in fields]
    month = pd.Timestamp(manifest["partitions"][0]["month"])
    for table in TABLES:
        if table not in manifest.get("forecasts", {}):
            continue
        identity = forecast_identity(forecasts.month(table, REGION, month))
        pinned = manifest["forecasts"][table]
        checks += [(f"{table}_{key}", identity[key], pinned[key]) for key in identity]
    failures = [(name, got, want) for name, got, want in checks if got != want]
    for name, got, want in checks:
        status = "OK " if got == want else "BAD"
        detail = "" if got == want else f" != {want}"
        print(f"  {status} {name}: {got}{detail}")
    return [name for name, _, _ in failures]


def main() -> None:
    args = build_parser().parse_args()
    logging.getLogger("nemosis").setLevel(logging.WARNING)
    manifests = args.manifest or sorted(MANIFEST_DIR.glob("*.json"))
    if not manifests:
        raise SystemExit(f"No manifests found in {MANIFEST_DIR}")
    cache = MarketDataCache(args.cache)
    forecasts = ForecastCache(args.cache)
    failed = {
        path: names for path in manifests if (names := verify(path, cache, forecasts))
    }
    if failed:
        raise SystemExit(
            "Reference inputs do not match their committed manifests: "
            + "; ".join(f"{path.name}: {', '.join(names)}" for path, names in failed.items())
        )
    print(f"\nAll {len(manifests)} reference input months match their manifests")


if __name__ == "__main__":
    main()
