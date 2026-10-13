"""One study task: a policy under one execution and seed, run, settled and audited.

A solve that fails, or a trace that fails its audit, fails the task; there is
no fallback to another policy.
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from battery_dispatch.audit.validation import (
    assert_audit_passes,
    audit_completed_cycles,
    audit_dispatch,
)
from battery_dispatch.dispatch.bidding import NEM_TIMETABLE
from battery_dispatch.dispatch.ceiling import audit_ceiling, perfect_foresight_bound
from battery_dispatch.dispatch.forecast import (
    AemoForecast,
    Forecaster,
    LaggedForecaster,
    PerfectForecast,
    SameTimeProfile,
    ThinnedErrorHistory,
    grid_times,
)
from battery_dispatch.dispatch.rolling import run_forecast_policy
from battery_dispatch.dispatch.scenario_tree import parse_splits
from battery_dispatch.market.aemo_forecasts import ForecastCache
from battery_dispatch.market.config import AEST, BatteryConfig
from battery_dispatch.market.data import MarketDataCache
from battery_dispatch.market.settlement import settle
from battery_dispatch.study.layers import LayerSettings
from battery_dispatch.study.spec import (
    POLICIES,
    SPIKE_PRICE,
    TOP_N_EXCLUDED,
    StudyConfig,
    Task,
    asset_for,
    warm_up_days,
)


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
                tree_splits=(
                    None
                    if settings.tree_splits is None
                    else parse_splits(settings.tree_splits, asset.interval_minutes)
                ),
                nonanticipativity=settings.nonanticipativity,
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
        "planned_objective",
        "solve_seconds",
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


