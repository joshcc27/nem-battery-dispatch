"""Forecast-driven rolling dispatch: layers 2 and 3, and the layer-1 oracle.

At each decision point the policy forecasts the look-ahead, optimises it,
commits the first block and settles that block at realised prices later. The
look-ahead is solved over one or more equiprobable price scenarios whose
committed block is shared, so one deterministic forecast (layer 2) is simply
the one-scenario case of the stochastic program (layer 3).

The model is built directly in HiGHS once per (look-ahead, committed block,
scenario count) shape and only re-priced between decisions. Rebuilding it in
linopy costs about 0.2s a solve, which over 720 hourly decisions per policy
per month is most of the run. Its equivalence to
:func:`battery_dispatch.optimiser.solve_window` is tested directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

import highspy
import numpy as np
import pandas as pd

from .battery import soc_path, validate_dispatch_trace
from .config import MARKET_FLOOR_PRICE, BatteryConfig, market_price_cap
from .forecast import ErrorBootstrap, Forecaster
from .horizon import _normalise_prices
from .optimiser import (
    STRICT_SOLVER_POLICY,
    THROUGHPUT_TIE_BREAKER_AUD_PER_MWH,
    SolverPolicy,
    exclusivity_binding_mask,
)
from .settlement import SettlementCoefficients, settlement_coefficients


@dataclass(frozen=True)
class ScenarioSolution:
    """The committed block of one decision and how it was solved."""

    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    objective_value: float
    solver_status: str
    solver_termination: str
    solve_seconds: float
    solver_mip_gap: float
    solver_dual_bound: float
    solver_absolute_gap: float
    exclusivity_binary_count: int
    # Marginal value of one more MWh stored at the end of each committed
    # interval, A$/MWh, summed over scenarios: the dual of its energy balance.
    stored_energy_value: np.ndarray
    # The plan's charge (1) or discharge (0) mode where an exclusivity binary
    # was needed, NaN where the dominance test left the mode free.
    planned_mode: np.ndarray


def _run_to_optimality(highs: highspy.Highs, what: str) -> None:
    """Solve, retrying once from a cold start before failing.

    Re-pricing a warm-started model between decisions is what keeps each solve
    fast, but after an extreme price scenario the carried-over basis can leave
    HiGHS without a verdict ("Unknown"). Discarding it and solving again from
    scratch resolves that; a second failure is a real one.
    """
    highs.run()
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        highs.clearSolver()
        highs.run()
    status = highs.getModelStatus()
    if status != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"HiGHS failed on the {what}: {highs.modelStatusToString(status)}")


class ScenarioDispatchModel:
    """HiGHS model for ``scenarios`` price paths over ``steps`` intervals.

    The first ``committed`` intervals have one charge and discharge decision
    shared by every scenario (non-anticipativity) and carry the exclusivity
    binaries; after that each scenario has its own dispatch. Only the committed
    block is ever implemented, so only it needs to be physically exclusive.
    Where the dominance argument in
    :func:`~battery_dispatch.optimiser.exclusivity_binding_mask` proves a
    binary redundant it is solved as continuous.
    """

    def __init__(
        self, asset: BatteryConfig, *, steps: int, committed: int, scenarios: int
    ) -> None:
        if not 1 <= committed <= steps or scenarios < 1:
            raise ValueError("Require 1 <= committed <= steps and scenarios >= 1")
        self.asset = asset
        self.steps = steps
        self.committed = committed
        self.scenarios = scenarios
        tail = steps - committed
        self._tail_offset = 2 * committed
        self._per_scenario_tail = 2 * tail
        self._soc_offset = self._tail_offset + scenarios * self._per_scenario_tail
        self._mode_offset = self._soc_offset + scenarios * steps
        self.num_col = self._mode_offset + committed

        charge_cols = np.empty((scenarios, steps), dtype=np.int64)
        discharge_cols = np.empty((scenarios, steps), dtype=np.int64)
        for s in range(scenarios):
            charge_cols[s, :committed] = np.arange(committed)
            discharge_cols[s, :committed] = committed + np.arange(committed)
            base = self._tail_offset + s * self._per_scenario_tail
            charge_cols[s, committed:] = base + np.arange(tail)
            discharge_cols[s, committed:] = base + tail + np.arange(tail)
        soc_cols = self._soc_offset + np.arange(scenarios * steps).reshape(scenarios, steps)
        self.charge_cols = charge_cols
        self.discharge_cols = discharge_cols
        self.soc_cols = soc_cols
        self.mode_cols = self._mode_offset + np.arange(committed)

        dt = asset.interval_hours
        rows: list[np.ndarray] = []
        cols: list[np.ndarray] = []
        values: list[np.ndarray] = []

        def add(row: np.ndarray, col: np.ndarray, value: float | np.ndarray) -> None:
            rows.append(np.asarray(row).ravel())
            cols.append(np.asarray(col).ravel())
            values.append(np.broadcast_to(value, np.shape(row)).ravel().astype(float))

        # Energy balance, one row per scenario and interval:
        # soc[t] - soc[t-1] - dt*eta_c*charge[t] + dt/eta_d*discharge[t] = 0,
        # with soc[-1] supplied as the bound of the t = 0 row.
        balance = np.arange(scenarios * steps).reshape(scenarios, steps)
        add(balance, soc_cols, 1.0)
        add(balance[:, 1:], soc_cols[:, :-1], -1.0)
        add(balance, charge_cols, -dt * asset.charge_efficiency)
        add(balance, discharge_cols, dt / asset.discharge_efficiency)
        # Committed-block mode: charge <= P*m and discharge + P*m <= P.
        mode_rows = scenarios * steps + np.arange(committed)
        add(mode_rows, np.arange(committed), 1.0)
        add(mode_rows, self.mode_cols, -asset.power_mw)
        add(mode_rows + committed, committed + np.arange(committed), 1.0)
        add(mode_rows + committed, self.mode_cols, asset.power_mw)
        self.num_row = scenarios * steps + 2 * committed

        row = np.concatenate(rows)
        col = np.concatenate(cols)
        value = np.concatenate(values)
        order = np.lexsort((row, col))
        row, col, value = row[order], col[order], value[order]

        lp = highspy.HighsLp()
        lp.num_col_ = self.num_col
        lp.num_row_ = self.num_row
        lp.sense_ = highspy.ObjSense.kMaximize
        lower = np.zeros(self.num_col)
        upper = np.full(self.num_col, asset.power_mw)
        lower[self._soc_offset : self._mode_offset] = asset.soc_min_mwh
        upper[self._soc_offset : self._mode_offset] = asset.soc_max_mwh
        upper[self._mode_offset :] = 1.0
        lp.col_cost_ = np.zeros(self.num_col)
        lp.col_lower_ = lower
        lp.col_upper_ = upper
        row_lower = np.zeros(self.num_row)
        row_upper = np.zeros(self.num_row)
        row_lower[scenarios * steps :] = -highspy.kHighsInf
        row_upper[scenarios * steps : scenarios * steps + committed] = 0.0
        row_upper[scenarios * steps + committed :] = asset.power_mw
        lp.row_lower_ = row_lower
        lp.row_upper_ = row_upper
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_ = np.searchsorted(col, np.arange(self.num_col + 1)).astype(np.int32)
        lp.a_matrix_.index_ = row.astype(np.int32)
        lp.a_matrix_.value_ = value
        lp.a_matrix_.num_col_ = self.num_col
        lp.a_matrix_.num_row_ = self.num_row

        self.highs = highspy.Highs()
        self.highs.setOptionValue("output_flag", False)
        self.highs.passModel(lp)
        self._balance_rows = balance
        self._initial_rows = balance[:, 0].astype(np.int32)
        self._all_cols = np.arange(self.num_col, dtype=np.int32)

    def solve(
        self,
        charge_value: np.ndarray,
        discharge_value: np.ndarray,
        soc_initial: float,
        *,
        terminal_value_per_mwh: float = 0.0,
        throughput_tie_breaker: float = THROUGHPUT_TIE_BREAKER_AUD_PER_MWH,
        policy: SolverPolicy = STRICT_SOLVER_POLICY,
    ) -> ScenarioSolution:
        """Maximise expected settled value; arrays are (scenarios, steps) per MW."""
        shape = (self.scenarios, self.steps)
        if np.shape(charge_value) != shape or np.shape(discharge_value) != shape:
            raise ValueError(f"Coefficient arrays must have shape {shape}")
        asset = self.asset
        weight = 1.0 / self.scenarios
        tie = asset.interval_hours * throughput_tie_breaker
        cost = np.zeros(self.num_col)
        # Shared columns appear once per scenario, so their weights sum to one.
        np.add.at(cost, self.charge_cols.ravel(), weight * (charge_value - tie).ravel())
        np.add.at(cost, self.discharge_cols.ravel(), weight * (discharge_value - tie).ravel())
        cost[self.soc_cols[:, -1]] += weight * terminal_value_per_mwh

        # The dominance test is linear in the coefficients, so it applies to
        # the expected coefficients of the shared block.
        committed = self.committed
        expected = SettlementCoefficients(
            generation_value_per_mw=np.zeros(committed),
            charge_value_per_mw=charge_value[:, :committed].mean(axis=0),
            degradation_cost_per_mw=np.zeros(committed),
            discharge_value_per_mw=discharge_value[:, :committed].mean(axis=0),
            generation_loss_factor=np.ones(committed),
            load_loss_factor=np.ones(committed),
        )
        binding = exclusivity_binding_mask(expected, asset)
        integrality = np.where(
            binding, highspy.HighsVarType.kInteger, highspy.HighsVarType.kContinuous
        )

        soc0 = float(np.clip(soc_initial, asset.soc_min_mwh, asset.soc_max_mwh))
        highs = self.highs
        highs.changeColsCost(self.num_col, self._all_cols, cost)
        highs.changeRowsBounds(
            self.scenarios,
            self._initial_rows,
            np.full(self.scenarios, soc0),
            np.full(self.scenarios, soc0),
        )
        highs.changeColsIntegrality(committed, self.mode_cols.astype(np.int32), integrality)
        highs.setOptionValue("mip_rel_gap", policy.mip_rel_gap)
        started = perf_counter()
        _run_to_optimality(highs, "dispatch model")
        seconds = perf_counter() - started
        info = highs.getInfo()
        objective = float(info.objective_function_value)
        binary_count = int(binding.sum())
        if binary_count:
            mip_gap = float(info.mip_gap)
            dual_bound = float(info.mip_dual_bound)
            absolute_gap = abs(dual_bound - objective)
        else:
            mip_gap, dual_bound, absolute_gap = 0.0, objective, 0.0
        planned_mode = np.full(committed, np.nan)
        if binary_count:
            # A MIP has no duals. Fixing the binaries at their optimum and
            # re-solving the LP gives the same dispatch and objective, and the
            # stored-energy values conditional on those charge/discharge modes.
            # Modes the dominance test left continuous stay free.
            fixed = self.mode_cols[binding].astype(np.int32)
            modes = np.round(np.asarray(highs.getSolution().col_value)[fixed])
            planned_mode[binding] = modes
            highs.changeColsBounds(binary_count, fixed, modes, modes)
            highs.changeColsIntegrality(
                binary_count,
                fixed,
                np.full(binary_count, highspy.HighsVarType.kContinuous),
            )
            _run_to_optimality(highs, "fixed-mode LP")
        highs_solution = highs.getSolution()
        if not highs_solution.dual_valid:
            raise RuntimeError("HiGHS returned no duals for the dispatch LP")
        # Read before restoring the mode bounds: any model change discards it.
        solution = np.asarray(highs_solution.col_value, dtype=float)
        row_dual = np.asarray(highs_solution.row_dual, dtype=float)
        if binary_count:
            highs.changeColsBounds(
                binary_count, fixed, np.zeros(binary_count), np.ones(binary_count)
            )
        committed_rows = self._balance_rows[:, :committed]
        # Raising a balance row's right-hand side is one more MWh stored at the
        # end of that interval, so its dual is that MWh's marginal value. The
        # sign HiGHS reports for a maximisation is pinned by a hand-worked test.
        stored_energy_value = row_dual[committed_rows].sum(axis=0)

        def clean(values: np.ndarray) -> np.ndarray:
            values = values.copy()
            values[np.abs(values) < 1e-8] = 0.0
            return np.clip(values, 0.0, asset.power_mw)

        charge = clean(solution[:committed])
        discharge = clean(solution[committed : 2 * committed])
        economic = float(
            weight * (charge_value * solution[self.charge_cols]).sum()
            + weight * (discharge_value * solution[self.discharge_cols]).sum()
            + weight * terminal_value_per_mwh * solution[self.soc_cols[:, -1]].sum()
        )
        return ScenarioSolution(
            charge_mw=charge,
            discharge_mw=discharge,
            objective_value=economic,
            solver_status="ok",
            solver_termination="optimal",
            solve_seconds=seconds,
            solver_mip_gap=mip_gap,
            solver_dual_bound=dual_bound,
            solver_absolute_gap=absolute_gap,
            exclusivity_binary_count=binary_count,
            stored_energy_value=stored_energy_value,
            planned_mode=planned_mode,
        )


EXECUTION_MODES = ("bands", "bid", "committed")


def execute_offers(
    realised_rrp: np.ndarray,
    planned_charge_mw: np.ndarray,
    planned_discharge_mw: np.ndarray,
    stored_energy_value: np.ndarray,
    generation_loss_factor: np.ndarray,
    load_loss_factor: np.ndarray,
    soc_initial: float,
    asset: BatteryConfig,
    *,
    band_offsets: np.ndarray | None = None,
    planned_mode: np.ndarray | None = None,
    deg_cost: float = 0.0,
    throughput_tie_breaker: float = THROUGHPUT_TIE_BREAKER_AUD_PER_MWH,
    tolerance: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Dispatch a committed block as price-limited offers against realised prices.

    Each interval is offered at the value ``lam`` the plan puts on stored
    energy, split into ``K = len(band_offsets)`` equal bands of ``P/K`` whose
    stored-energy values are ``lam + band_offsets``. Through band ``k``,
    charging one MWh at the meter is worth ``eta_c*(lam + o_k) - tb - L*p`` and
    discharging one is worth ``G*p - deg - tb - (lam + o_k)/eta_d``. A band
    whose margin is strictly positive clears in full, one whose margin is zero
    clears its share of the planned quantity, and one whose margin is negative
    does not clear.

    With one band at offset zero this is a single price limit per direction:
    the full power rating beyond it and the planned quantity at it. At the
    forecast prices those are exactly the plan's own optimality conditions, so
    a perfect forecast is executed unchanged. Spreading the bands by the
    forecaster's own error quantiles, as a NEM bid spreads quantity over price
    bands, clears progressively more as the price moves further past the
    plan's limit instead of all or nothing at it.

    Charge and discharge are exclusive. Where some band of each would clear the
    planned direction wins, then the plan's exclusivity mode, then the larger
    margin; the mode is what keeps a planned idle interval idle at prices
    negative enough that burning energy pays. Quantities are limited to the SOC
    headroom as the block is executed interval by interval.
    """
    offsets = np.zeros(1) if band_offsets is None else np.asarray(band_offsets, dtype=float)
    band_mw = asset.power_mw / len(offsets)
    modes = np.full(len(realised_rrp), np.nan) if planned_mode is None else planned_mode
    dt = asset.interval_hours
    eta_c = asset.charge_efficiency
    eta_d = asset.discharge_efficiency
    tie = throughput_tie_breaker
    charge = np.zeros(len(realised_rrp))
    discharge = np.zeros(len(realised_rrp))
    soc = float(soc_initial)
    for i, price in enumerate(realised_rrp):
        values = float(stored_energy_value[i]) + offsets
        charge_margins = eta_c * values - tie - load_loss_factor[i] * price
        discharge_margins = generation_loss_factor[i] * price - deg_cost - tie - values / eta_d
        scale = tolerance * max(1.0, float(np.abs(values).max()), abs(price))

        def cleared(margins: np.ndarray, planned: float, scale: float = scale) -> float:
            full = np.count_nonzero(margins > scale)
            at_limit = np.count_nonzero(np.abs(margins) <= scale)
            return band_mw * full + planned * at_limit / len(margins)

        c = cleared(charge_margins, float(planned_charge_mw[i]))
        d = cleared(discharge_margins, float(planned_discharge_mw[i]))
        if charge_margins.max() >= -scale and discharge_margins.max() >= -scale:
            if planned_discharge_mw[i] > 0:
                c = 0.0
            elif planned_charge_mw[i] > 0:
                d = 0.0
            elif modes[i] == 1.0:
                d = 0.0
            elif modes[i] == 0.0:
                c = 0.0
            elif charge_margins.max() >= discharge_margins.max():
                d = 0.0
            else:
                c = 0.0
        c = min(c, max(0.0, (asset.soc_max_mwh - soc) / (dt * eta_c)))
        d = min(d, max(0.0, (soc - asset.soc_min_mwh) * eta_d / dt))
        charge[i] = c
        discharge[i] = d
        soc += dt * (eta_c * c - d / eta_d)
    return charge, discharge


def run_forecast_policy(
    prices: pd.DataFrame | pd.Series,
    history: pd.DataFrame | pd.Series,
    asset: BatteryConfig,
    forecaster: Forecaster,
    *,
    scenarios: ErrorBootstrap | None = None,
    band_errors: ErrorBootstrap | None = None,
    bands: int = 10,
    horizon_hours: float = 24.0,
    commit_minutes: int = 60,
    deg_cost: float = 0.0,
    terminal_value_per_mwh: float = 0.0,
    soc_initial: float | None = None,
    policy: SolverPolicy = STRICT_SOLVER_POLICY,
    execution: str = "bid",
    progress: Callable[[int, pd.Timestamp], None] | None = None,
) -> pd.DataFrame:
    """Dispatch ``prices`` hour by hour from forecasts.

    ``history`` is the contiguous run of settled prices immediately before
    ``prices``; forecasters and the scenario bootstrap read only it and the
    part of ``prices`` that has settled by each decision. The look-ahead is cut
    at the end of ``prices`` for every policy, so closing inventory is valued
    at ``terminal_value_per_mwh`` exactly as in the layer-1 bound.

    Without ``scenarios`` the policy optimises the single point forecast
    (layer 2). With them it optimises the expected value over the scenario set
    with a shared committed block (layer 3).

    ``execution`` sets how the committed block meets realised prices (see
    :func:`execute_offers`). With ``"bands"`` each interval is offered in
    ``bands`` equal price bands spread by the quantiles of the forecaster's
    recent errors at the committed block's lead times, from ``band_errors``
    (or ``scenarios`` if that is not given).
    With ``"bid"`` it is offered at one price limit per direction. With
    ``"committed"`` the planned quantities are dispatched whatever the price.
    Every decision is made from forecasts alone; the realised price only
    clears the offers.
    """
    if execution not in EXECUTION_MODES:
        raise ValueError(f"execution must be one of {EXECUTION_MODES}")
    error_model = band_errors or scenarios
    if execution == "bands" and error_model is None:
        raise ValueError("Band execution needs band_errors or scenarios to spread the bands")
    if bands < 1:
        raise ValueError("bands must be positive")
    evaluation = _normalise_prices(prices)
    past = _normalise_prices(history)
    step = pd.Timedelta(minutes=asset.interval_minutes)
    if len(past) and past["settlementdate"].iloc[-1] + step != evaluation["settlementdate"].iloc[0]:
        raise ValueError("history must end one interval before prices begin")
    combined = pd.concat([past, evaluation], ignore_index=True)
    if not combined["settlementdate"].diff().iloc[1:].eq(step).all():
        raise ValueError("history and prices must form one regular interval grid")
    if commit_minutes <= 0 or commit_minutes % asset.interval_minutes:
        raise ValueError("commit_minutes must be a positive multiple of the interval")
    steps_ahead = int(round(horizon_hours * 60 / asset.interval_minutes))
    commit = commit_minutes // asset.interval_minutes
    if steps_ahead < commit:
        raise ValueError("horizon_hours must cover at least one committed block")

    actual = combined["rrp"].to_numpy(dtype=float)
    timestamps = combined["settlementdate"]
    # Dated loss factors for every interval, from the authoritative settlement
    # coefficients evaluated at a unit price.
    unit = settlement_coefficients(
        np.ones(len(combined)), asset, settlementdate=timestamps, deg_cost=0.0
    )
    generation = unit.generation_loss_factor
    load = unit.load_loss_factor
    # The cap changes only by financial year, so look it up once per day. Days
    # are keyed by interval start: the interval ending 1 July 00:00 belongs to
    # the financial year that has just ended.
    days = (timestamps - step).dt.normalize()
    daily_cap = {day: market_price_cap(day + step) for day in days.unique()}
    cap = days.map(daily_cap).to_numpy(dtype=float)
    dt = asset.interval_hours

    start = len(past)
    end = len(combined)
    current_soc = asset.initial_soc_mwh if soc_initial is None else float(soc_initial)
    starting_soc = current_soc
    models: dict[tuple[int, int, int], ScenarioDispatchModel] = {}
    # Built once at the end: a DataFrame per decision costs more than the solve.
    intervals: dict[str, list[np.ndarray]] = {}
    decisions: list[dict[str, object]] = []
    decision_lengths: list[int] = []
    position = start
    decision = 0
    while position < end:
        steps = min(steps_ahead, end - position)
        take = min(commit, steps)
        seen = actual[:position]
        base = np.asarray(forecaster.forecast(seen, steps), dtype=float)
        # One pool of past errors per decision serves both the scenarios and
        # the band spread. The bands price only the committed block, so they
        # are spread by the errors at its lead times, where a good forecaster
        # (AEMO's P5MIN) is far sharper than it is a day ahead.
        needs_errors = scenarios is not None or execution == "bands"
        errors = error_model.errors(forecaster, seen, steps) if needs_errors else None
        paths = (
            base[np.newaxis, :]
            if scenarios is None
            else scenarios.scenarios(errors, base, decision)
        )
        offsets = (
            error_model.band_offsets(errors[:, :take], bands)
            if execution == "bands"
            else np.zeros(1)
        )
        window = slice(position, position + steps)
        paths = np.clip(paths, MARKET_FLOOR_PRICE, cap[window])
        charge_value = -dt * load[window] * paths
        discharge_value = dt * (generation[window] * paths - deg_cost)
        key = (steps, take, paths.shape[0])
        if key not in models:
            models[key] = ScenarioDispatchModel(
                asset, steps=steps, committed=take, scenarios=paths.shape[0]
            )
        result = models[key].solve(
            charge_value,
            discharge_value,
            current_soc,
            terminal_value_per_mwh=terminal_value_per_mwh,
            policy=policy,
        )
        block = slice(position, position + take)
        lam = result.stored_energy_value
        tie = THROUGHPUT_TIE_BREAKER_AUD_PER_MWH
        if execution in ("bands", "bid"):
            charge, discharge = execute_offers(
                actual[block],
                result.charge_mw,
                result.discharge_mw,
                lam,
                generation[block],
                load[block],
                current_soc,
                asset,
                band_offsets=offsets,
                planned_mode=result.planned_mode,
                deg_cost=deg_cost,
            )
        else:
            charge, discharge = result.charge_mw, result.discharge_mw
        soc = np.clip(
            soc_path(charge, discharge, current_soc, asset),
            asset.soc_min_mwh,
            asset.soc_max_mwh,
        )
        interval_columns = {
            "charge_mw": charge,
            "discharge_mw": discharge,
            "soc_mwh": soc,
            "forecast_rrp": np.clip(base[:take], MARKET_FLOOR_PRICE, cap[block]),
            "planned_charge_mw": result.charge_mw,
            "planned_discharge_mw": result.discharge_mw,
            "stored_energy_value": lam,
            # The realised prices at which the offers start to clear.
            "charge_limit_rrp": (asset.charge_efficiency * lam - tie) / load[block],
            "discharge_limit_rrp": (lam / asset.discharge_efficiency + deg_cost + tie)
            / generation[block],
        }
        for name, values in interval_columns.items():
            intervals.setdefault(name, []).append(values)
        decisions.append(
            {
                "window_id": decision,
                "solver_status": result.solver_status,
                "solver_termination": result.solver_termination,
                "solve_seconds": result.solve_seconds,
                "solver_mip_gap": result.solver_mip_gap,
                "solver_dual_bound": result.solver_dual_bound,
                "solver_absolute_gap": result.solver_absolute_gap,
                "exclusivity_binary_count": result.exclusivity_binary_count,
                "scenario_count": paths.shape[0],
                "error_pool_days": np.nan if errors is None else len(errors),
                "band_spread_aud": float(offsets[-1] - offsets[0]),
                "window_start": timestamps.iloc[position],
                "window_end": timestamps.iloc[position + steps - 1],
                "window_initial_soc_mwh": current_soc,
            }
        )
        decision_lengths.append(take)
        if progress is not None:
            progress(decision, timestamps.iloc[position])
        current_soc = float(soc[-1])
        position += take
        decision += 1

    per_decision = pd.DataFrame(decisions).loc[
        np.repeat(np.arange(len(decisions)), decision_lengths)
    ]
    trace = pd.concat(
        [
            pd.DataFrame(
                {
                    "settlementdate": timestamps.iloc[start:end].to_numpy(),
                    **{name: np.concatenate(values) for name, values in intervals.items()},
                    "execution": execution,
                }
            ),
            per_decision.reset_index(drop=True),
        ],
        axis=1,
    )
    validate_dispatch_trace(trace, asset, soc_initial=starting_soc)
    return trace
