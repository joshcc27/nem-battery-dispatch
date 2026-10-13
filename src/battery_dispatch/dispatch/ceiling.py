"""Full-period perfect-foresight revenue ceiling for a rolling-horizon run."""

from __future__ import annotations

import pandas as pd

from battery_dispatch.dispatch.optimiser import DispatchWindow, solve_window
from battery_dispatch.market.config import BatteryConfig
from battery_dispatch.market.data import normalise_prices
from battery_dispatch.market.settlement import RevenueResult


def perfect_foresight_bound(
    prices: pd.DataFrame | pd.Series,
    asset: BatteryConfig,
    *,
    soc_initial: float,
    deg_cost: float = 0.0,
    terminal_value_per_mwh: float = 0.0,
) -> tuple[DispatchWindow, pd.DataFrame]:
    """Solve the whole period as one LP with the exclusivity binary removed.

    Removing the rolling look-ahead limit and the exclusivity constraint can
    only raise the optimum, and the throughput tie-breaker is excluded, so the
    value bounds every feasible dispatch of the same asset, prices, starting SOC
    and terminal valuation from above. This is layer 1, the theoretical maximum.
    The binaries are what make the MILP expensive; the LP solves a month in
    about two seconds, and the exact whole-month MILP did not finish in ten
    minutes.

    The returned dispatch may charge and discharge in the same interval where
    burning energy pays, so it is the bound's schedule, not a settleable one.
    """
    frame = normalise_prices(prices)
    result = solve_window(
        frame["rrp"].to_numpy(dtype=float),
        asset,
        soc_initial,
        deg_cost=deg_cost,
        settlementdate=frame["settlementdate"].to_numpy(),
        terminal_value_per_mwh=terminal_value_per_mwh,
        enforce_exclusivity=False,
        throughput_tie_breaker=0.0,
    )
    return result, result.to_frame(frame["settlementdate"].to_numpy())


def perfect_foresight_ceiling(
    prices: pd.DataFrame | pd.Series,
    asset: BatteryConfig,
    *,
    soc_initial: float,
    deg_cost: float = 0.0,
    terminal_value_per_mwh: float = 0.0,
) -> dict[str, float]:
    """The layer-1 bound as the audit fields every run is gated against."""
    result, _ = perfect_foresight_bound(
        prices,
        asset,
        soc_initial=soc_initial,
        deg_cost=deg_cost,
        terminal_value_per_mwh=terminal_value_per_mwh,
    )
    return {
        "perfect_foresight_ceiling_aud": result.objective_value,
        "ceiling_solve_seconds": result.solve_seconds,
    }


def audit_ceiling(
    ceiling: dict[str, float],
    revenue: RevenueResult,
    *,
    terminal_value_per_mwh: float = 0.0,
) -> dict[str, float]:
    """Compare a settled run with its ceiling on the ceiling's own objective.

    The ceiling values closing SOC at ``terminal_value_per_mwh``, so the
    achieved side adds the same valuation to settled cash revenue.
    """
    terminal_soc = float(revenue.intervals["soc_mwh"].iloc[-1])
    achieved = revenue.total_revenue + terminal_value_per_mwh * terminal_soc
    bound = float(ceiling["perfect_foresight_ceiling_aud"])
    gap = bound - achieved
    return {
        **ceiling,
        "achieved_objective_aud": achieved,
        "horizon_gap_aud": gap,
        "horizon_gap_fraction": gap / bound if bound > 0 else 0.0,
    }
