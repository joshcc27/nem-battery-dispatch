"""Input coverage for a candidate study period, checked before any revenue is seen.

A study period is chosen, and months are excluded, on the evidence in this
report alone: whether every five-minute price is present, whether an AEMO
forecast run was current at each decision time, and whether the dated loss
factors and price cap needed to settle each interval are configured. Policy
revenue plays no part, so a difficult month cannot be dropped for being
difficult.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from battery_dispatch.dispatch.forecast import grid_times
from battery_dispatch.market.aemo_forecasts import ForecastCache, ForecastRuns
from battery_dispatch.market.config import AEST, LossFactorTable, financial_year, market_price_cap
from battery_dispatch.market.data import MarketDataCache

# A month is usable only if an AEMO run was current at no fewer than this share
# of its decision times. Below it the "AEMO" policies would mostly be running
# on the profile fallback, and the month would test something else.
MIN_FORECAST_COVERAGE = 0.90
MAX_AGE = {"predispatch": np.timedelta64(60, "m"), "p5min": np.timedelta64(15, "m")}


@dataclass(frozen=True)
class CoverageRule:
    """The declared exclusion rule, recorded with every coverage report."""

    min_forecast_coverage: float = MIN_FORECAST_COVERAGE

    def describe(self) -> str:
        return (
            "exclude a month if any price interval is missing, if any interval has no "
            "configured loss factor or price cap, or if a current AEMO pre-dispatch or "
            f"P5MIN run exists at fewer than {self.min_forecast_coverage:.0%} of its "
            "five-minute decision times"
        )


def current_share(
    runs: ForecastRuns, decisions: np.ndarray, max_age: np.timedelta64
) -> tuple[float, float]:
    """Share of decision times with a run published within ``max_age``, and the
    longest stretch without one, in hours."""
    if not len(runs.published):
        return 0.0, len(decisions) * 5 / 60
    index = np.searchsorted(runs.published, decisions, side="right") - 1
    valid = index >= 0
    age = np.full(len(decisions), np.timedelta64(10**6, "m"))
    age[valid] = decisions[valid] - runs.published[index[valid]]
    current = age <= max_age
    longest = 0
    run = 0
    for flag in current:
        run = 0 if flag else run + 1
        longest = max(longest, run)
    return float(current.mean()), longest * 5 / 60


def month_coverage(
    month: pd.Timestamp,
    region: str,
    prices: MarketDataCache,
    forecasts: ForecastCache,
    loss_factors: LossFactorTable,
    rule: CoverageRule | None = None,
) -> dict[str, object]:
    """Coverage of one calendar month, downloading any missing inputs."""
    rule = rule or CoverageRule()
    start = pd.Timestamp(month).tz_localize(None).to_period("M").start_time
    end = start + pd.offsets.MonthBegin(1)
    row: dict[str, object] = {"month": start.strftime("%Y-%m"), "region": region}
    reasons: list[str] = []
    try:
        frame = prices.fetch_prices(start, end, [region])
        row["price_rows"] = len(frame)
        row["price_complete"] = True
    except ValueError as error:
        row["price_rows"] = 0
        row["price_complete"] = False
        reasons.append(f"prices: {error}")
    expected = pd.date_range(
        pd.Timestamp(start, tz=AEST) + pd.Timedelta(minutes=5),
        pd.Timestamp(end, tz=AEST),
        freq="5min",
    )
    row["expected_price_rows"] = len(expected)
    years = sorted({financial_year(ts) for ts in expected})
    missing_mlf = [fy for fy in years if fy not in loss_factors.by_financial_year]
    row["financial_years"] = ",".join(years)
    row["loss_factors_configured"] = not missing_mlf
    if missing_mlf:
        reasons.append(f"no loss factors for {missing_mlf}")
    try:
        market_price_cap(expected[0])
        market_price_cap(expected[-1])
        row["price_cap_configured"] = True
    except KeyError as error:
        row["price_cap_configured"] = False
        reasons.append(str(error))

    # The pre-dispatch archive is organised by trading day from 04:00, so the
    # first hours of a month sit in the previous month's file.
    runs = forecasts.fetch(start - pd.Timedelta(days=1), end, region)
    decisions = grid_times(pd.Series(expected))
    for table in ("predispatch", "p5min"):
        partition = forecasts.month(table, region, pd.Timestamp(start))
        share, longest = current_share(runs[table], decisions, MAX_AGE[table])
        row[f"{table}_runs"] = int(partition["run_id"].nunique()) if len(partition) else 0
        row[f"{table}_missing_from_archive"] = len(partition) == 0
        row[f"{table}_current_share"] = round(share, 5)
        row[f"{table}_longest_gap_hours"] = round(longest, 3)
        if share < rule.min_forecast_coverage:
            reasons.append(f"{table} current at {share:.1%} of decision times")
    row["usable"] = not reasons
    row["exclusion_reasons"] = "; ".join(reasons)
    return row
