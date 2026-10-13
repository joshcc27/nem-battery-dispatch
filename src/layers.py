"""The three-layer revenue comparison for one period.

The ceiling is the whole period as one LP with the exclusivity binary
relaxed: an upper bound under the stated model, which may charge and discharge
at once and need not be attainable by any physical policy. Beside it is the
oracle benchmark, the same rolling engine as layers 2 and 3 fed the realised
prices; a finite rolling horizon does not make it the best policy at that
cadence, only a strong reference for it. Layer 2 dispatches on a point forecast
and layer 3 on forecast-error scenarios around the same forecast, for each of
the naive profile and AEMO's own published forecasts. Every policy is settled
at realised prices by the one settlement function, and every policy is
audited against the bound.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from time import perf_counter

import numpy as np
import pandas as pd

from .aemo_forecasts import ForecastRuns
from .ceiling import audit_ceiling, perfect_foresight_bound
from .config import BatteryConfig
from .forecast import (
    AemoForecast,
    ErrorBootstrap,
    Forecaster,
    PerfectForecast,
    SameTimeProfile,
    grid_times,
)
from .horizon import _normalise_prices
from .mpc import run_forecast_policy
from .settlement import settle
from .validation import assert_audit_passes, audit_completed_cycles, audit_dispatch


@dataclass(frozen=True)
class LayerSettings:
    """One declared configuration shared by every forecast-driven layer.

    Layers 2 and 3 use the same look-ahead, re-solve cadence and execution, so
    the gap between them is the value of planning for uncertainty and nothing
    else.
    """

    deg_cost: float = 25.0
    horizon_hours: float = 24.0
    commit_minutes: int = 60
    profile_days: int = 7
    scenario_count: int = 10
    scenario_pool_days: int = 21
    # Past errors are capped at the pool's 5th and 95th percentiles before they
    # become scenarios or band spread. None keeps them uncapped.
    error_winsorize: float | None = 0.05
    seed: int = 20221101
    # "bands": each committed interval is offered in `bands` price bands spread
    # by the forecaster's error quantiles. "bid": one price limit per
    # direction. "committed": planned quantities dispatched at any price.
    execution: str = "bands"
    bands: int = 10
    # AEMO pre-dispatch is used up to this many hours ahead and the profile
    # beyond; None uses it to its end. See AemoForecast.
    aemo_predispatch_hours: float | None = 4.0
    # Decisions see prices and AEMO runs only up to this many minutes before
    # the decision time. Zero is the idealised instant decision.
    latency_minutes: int = 0
    # Layer 3 shares its decisions across scenarios for this many minutes,
    # still executing only commit_minutes. None shares only the committed
    # block: the two-stage approximation with clairvoyant scenario tails.
    shared_minutes: int | None = None
    # The rule-based baseline charges in this many cheapest forecast hours and
    # discharges in as many dearest.
    rule_hours: int = 2
    # Section 5 extension: bundle layer 3's scenario fan into a tree that
    # splits at these "minutes:branching" points, and plan it as a two-stage
    # problem ("two_stage") or a scenario tree ("tree"). None leaves the fan.
    tree_splits: str | None = None
    nonanticipativity: str = "two_stage"

    def __post_init__(self) -> None:
        if self.latency_minutes < 0 or self.latency_minutes % 5:
            raise ValueError("latency_minutes must be a non-negative multiple of five")

    def periods_per_day(self, asset: BatteryConfig) -> int:
        return 24 * 60 // asset.interval_minutes

    def error_model(self, asset: BatteryConfig) -> ErrorBootstrap:
        return ErrorBootstrap(
            count=self.scenario_count,
            pool_days=self.scenario_pool_days,
            periods_per_day=self.periods_per_day(asset),
            seed=self.seed,
            winsorize=self.error_winsorize,
        )

    def min_history_intervals(self, asset: BatteryConfig) -> int:
        """Settled history the first decision needs, for the error bootstrap."""
        steps = int(round(self.horizon_hours * 60 / asset.interval_minutes))
        profile = SameTimeProfile(self.profile_days, self.periods_per_day(asset))
        return self.error_model(asset).min_history(profile, steps)


@dataclass(frozen=True)
class LayerResults:
    summary: pd.DataFrame
    traces: dict[str, pd.DataFrame]
    bound_dispatch: pd.DataFrame


LAYER_ORDER = (
    "ceiling",
    "oracle",
    "L2_persistence",
    "L2_profile",
    "L2_aemo",
    "L3_profile",
    "L3_aemo",
)


def run_layers(
    prices: pd.DataFrame,
    history: pd.DataFrame,
    asset: BatteryConfig,
    settings: LayerSettings | None = None,
    *,
    aemo_forecasts: Mapping[str, ForecastRuns] | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> LayerResults:
    """Run, settle and audit every layer on ``prices``.

    ``history`` is the settled run of prices before the period, which the
    forecasters and the error bootstrap read. It must be at least
    :meth:`LayerSettings.min_history_intervals` long. ``aemo_forecasts`` holds
    the ``"predispatch"`` and ``"p5min"`` runs from
    :class:`~battery_dispatch.aemo_forecasts.ForecastCache`; without it the
    AEMO layers are left out.
    """
    settings = settings or LayerSettings()
    evaluation = _normalise_prices(prices)
    past = _normalise_prices(history)
    needed = settings.min_history_intervals(asset)
    if len(past) < needed:
        raise ValueError(f"history has {len(past)} intervals, layers need {needed}")
    soc_initial = asset.initial_soc_mwh
    deg_cost = settings.deg_cost
    per_day = settings.periods_per_day(asset)

    started = perf_counter()
    bound, bound_dispatch = perfect_foresight_bound(
        evaluation, asset, soc_initial=soc_initial, deg_cost=deg_cost
    )
    ceiling = {
        "perfect_foresight_ceiling_aud": bound.objective_value,
        "ceiling_solve_seconds": bound.solve_seconds,
    }
    rows: list[dict[str, object]] = [
        {
            "layer": "ceiling",
            "policy": "whole-period LP, exclusivity relaxed",
            "forecaster": "perfect",
            "total_revenue": bound.objective_value,
            "gap_to_bound_aud": 0.0,
            "share_of_bound": 1.0,
            "equivalent_full_cycles": float(bound.discharge_mw.sum())
            * asset.interval_hours
            / asset.energy_mwh,
            "terminal_soc_mwh": bound.soc_final_mwh,
            "decision_count": 1,
            "runtime_seconds": perf_counter() - started,
        }
    ]
    if progress is not None:
        progress("ceiling", rows[0]["runtime_seconds"])

    combined = pd.concat([past, evaluation], ignore_index=True)
    actual = combined["rrp"].to_numpy(dtype=float)
    profile = SameTimeProfile(settings.profile_days, per_day)
    errors = settings.error_model(asset)
    forecasters: list[tuple[str, Forecaster]] = [
        ("perfect_forecast", PerfectForecast(actual)),
        ("persistence", SameTimeProfile(1, per_day)),
        ("profile", profile),
    ]
    if aemo_forecasts is not None:
        aemo = AemoForecast(
            timestamps=grid_times(combined["settlementdate"]),
            predispatch=aemo_forecasts["predispatch"],
            p5min=aemo_forecasts["p5min"],
            fallback=profile,
            predispatch_hours=settings.aemo_predispatch_hours,
        )
        forecasters.append(("aemo", aemo))
    by_label = dict(forecasters)
    policies: list[tuple[str, str, str, bool]] = [
        ("oracle", "rolling, realised prices", "perfect_forecast", False),
        ("L2_persistence", "rolling, point forecast", "persistence", False),
        ("L2_profile", "rolling, point forecast", "profile", False),
        ("L2_aemo", "rolling, point forecast", "aemo", False),
        ("L3_profile", "rolling, forecast-error scenarios", "profile", True),
        ("L3_aemo", "rolling, forecast-error scenarios", "aemo", True),
    ]
    traces: dict[str, pd.DataFrame] = {}
    for layer, policy, label, stochastic in policies:
        if label not in by_label:
            continue
        forecaster = by_label[label]
        started = perf_counter()
        trace = run_forecast_policy(
            evaluation,
            past,
            asset,
            forecaster,
            scenarios=errors if stochastic else None,
            band_errors=errors,
            bands=settings.bands,
            horizon_hours=settings.horizon_hours,
            commit_minutes=settings.commit_minutes,
            deg_cost=deg_cost,
            soc_initial=soc_initial,
            execution=settings.execution,
        )
        revenue = settle(trace, evaluation, asset, deg_cost=deg_cost)
        audit = {
            **audit_dispatch(trace, asset, soc_initial=soc_initial),
            **audit_completed_cycles(
                revenue.intervals, asset, deg_cost=deg_cost, initial_soc_mwh=soc_initial
            ),
            **audit_ceiling(ceiling, revenue),
        }
        assert_audit_passes(audit, require_cycle_break_even=isinstance(forecaster, PerfectForecast))
        # Settlement carries the trace's columns, so these are aligned.
        intervals = revenue.intervals
        forecast_error = intervals["forecast_rrp"] - intervals["rrp"]
        discharged = float(intervals["discharge_mwh"].sum())
        per_decision = trace.drop_duplicates("window_id")
        rows.append(
            {
                "layer": layer,
                "policy": policy,
                "forecaster": forecaster.name,
                "total_revenue": revenue.total_revenue,
                "gap_to_bound_aud": audit["horizon_gap_aud"],
                "share_of_bound": audit["achieved_objective_aud"]
                / audit["perfect_foresight_ceiling_aud"],
                "equivalent_full_cycles": discharged / asset.energy_mwh,
                "terminal_soc_mwh": audit["terminal_soc_mwh"],
                "loss_making_cycle_count": audit["completed_cycle_break_even_violation_count"],
                "loss_making_cycle_aud": audit["completed_cycle_loss_aud"],
                "committed_forecast_mae": float(np.mean(np.abs(forecast_error))),
                "scenario_count": int(trace["scenario_count"].iloc[0]),
                "min_error_pool_days": float(per_decision["error_pool_days"].min()),
                "median_band_spread_aud": float(per_decision["band_spread_aud"].median()),
                "decision_count": audit["solver_window_count"],
                "max_solver_mip_gap": audit["max_solver_mip_gap"],
                "total_exclusivity_binary_count": audit["total_exclusivity_binary_count"],
                "runtime_seconds": perf_counter() - started,
            }
        )
        traces[layer] = intervals
        if progress is not None:
            progress(layer, rows[-1]["runtime_seconds"])

    summary = pd.DataFrame(rows)
    for key, value in asdict(settings).items():
        summary[key] = value
    return LayerResults(summary=summary, traces=traces, bound_dispatch=bound_dispatch)


def layer_gaps(summary: pd.DataFrame) -> dict[str, float]:
    """The headline differences between layers, in A$ over the period.

    These are realised, out-of-sample differences on one period, not the
    expected values that stochastic programming calls VSS (RP - EEV) and EVPI
    (WS - RP) under the model's own distribution. For each forecaster with
    both layers, ``realized_stochastic_uplift`` is layer 3 less layer 2 on the
    same point forecast (it can be negative), ``forecast_cost`` is the oracle
    less layer 2, and ``gap_ceiling_to_l3`` is the ceiling less layer 3.
    """
    revenue = summary.set_index("layer")["total_revenue"]
    gaps = {
        "oracle_gap_to_ceiling": float(revenue["ceiling"] - revenue["oracle"]),
    }
    for label in ("profile", "aemo"):
        point, stochastic = f"L2_{label}", f"L3_{label}"
        if point not in revenue or stochastic not in revenue:
            continue
        gaps[f"forecast_cost_{label}"] = float(revenue["oracle"] - revenue[point])
        gaps[f"realized_stochastic_uplift_{label}"] = float(revenue[stochastic] - revenue[point])
        gaps[f"gap_ceiling_to_l3_{label}"] = float(revenue["ceiling"] - revenue[stochastic])
    return gaps
