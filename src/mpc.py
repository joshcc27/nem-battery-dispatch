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
from .bidding import (
    NEM_TIMETABLE,
    FixedBands,
    Timetable,
    band_prices,
    charge_price_from_value,
    charge_value_from_price,
    discharge_price_from_value,
    discharge_value_from_price,
    execute_tranches,
    rule_limits,
    snap_charge,
    snap_discharge,
)
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
    # The expected stored-energy value at the end of every look-ahead interval,
    # committed or not; used to set a trading day's fixed band prices.
    stored_energy_path: np.ndarray


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

    The first ``shared`` intervals (``committed`` by default) have one charge
    and discharge decision shared by every scenario (non-anticipativity); after
    that each scenario has its own dispatch. Only the first ``committed`` are
    ever implemented, so only they carry exclusivity binaries. ``shared`` longer
    than ``committed`` makes the plan less clairvoyant about the scenarios'
    futures: ``shared == steps`` is one plan for every scenario.
    Where the dominance argument in
    :func:`~battery_dispatch.optimiser.exclusivity_binding_mask` proves a
    binary redundant it is solved as continuous.
    """

    def __init__(
        self,
        asset: BatteryConfig,
        *,
        steps: int,
        committed: int,
        scenarios: int,
        shared: int | None = None,
    ) -> None:
        shared = committed if shared is None else shared
        if not 1 <= committed <= shared <= steps or scenarios < 1:
            raise ValueError("Require 1 <= committed <= shared <= steps and scenarios >= 1")
        self.asset = asset
        self.steps = steps
        self.committed = committed
        self.shared = shared
        self.scenarios = scenarios
        tail = steps - shared
        self._tail_offset = 2 * shared
        self._per_scenario_tail = 2 * tail
        self._soc_offset = self._tail_offset + scenarios * self._per_scenario_tail
        self._mode_offset = self._soc_offset + scenarios * steps
        self.num_col = self._mode_offset + committed

        charge_cols = np.empty((scenarios, steps), dtype=np.int64)
        discharge_cols = np.empty((scenarios, steps), dtype=np.int64)
        for s in range(scenarios):
            charge_cols[s, :shared] = np.arange(shared)
            discharge_cols[s, :shared] = shared + np.arange(shared)
            base = self._tail_offset + s * self._per_scenario_tail
            charge_cols[s, shared:] = base + np.arange(tail)
            discharge_cols[s, shared:] = base + tail + np.arange(tail)
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
        add(mode_rows + committed, shared + np.arange(committed), 1.0)
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
        stored_energy_path = row_dual[self._balance_rows].sum(axis=0)

        def clean(values: np.ndarray) -> np.ndarray:
            values = values.copy()
            values[np.abs(values) < 1e-8] = 0.0
            return np.clip(values, 0.0, asset.power_mw)

        charge = clean(solution[:committed])
        discharge = clean(solution[self.shared : self.shared + committed])
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
            stored_energy_path=stored_energy_path,
        )


EXECUTION_MODES = ("bands", "bid", "committed", "fixed_bands")
PLANNERS = ("optimise", "rule")


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
    headroom as the block is executed interval by interval. This wraps
    :func:`~battery_dispatch.bidding.execute_tranches`.
    """
    offsets = np.zeros(1) if band_offsets is None else np.asarray(band_offsets, dtype=float)
    values = np.asarray(stored_energy_value, dtype=float)[:, np.newaxis] + offsets
    result = execute_tranches(
        realised_rrp,
        planned_charge_mw,
        planned_discharge_mw,
        values,
        values,
        generation_loss_factor,
        load_loss_factor,
        soc_initial,
        asset,
        planned_mode=planned_mode,
        deg_cost=deg_cost,
        throughput_tie_breaker=throughput_tie_breaker,
        tolerance=tolerance,
    )
    return result.charge_mw, result.discharge_mw


def _cap_to_headroom(
    charge: np.ndarray, discharge: np.ndarray, soc: float, asset: BatteryConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Committed quantities, cut back only where the SOC envelope requires it."""
    charge = charge.copy()
    discharge = discharge.copy()
    limited = np.zeros(len(charge), dtype=bool)
    dt = asset.interval_hours
    eta_c, eta_d = asset.charge_efficiency, asset.discharge_efficiency
    for i in range(len(charge)):
        c_room = max(0.0, (asset.soc_max_mwh - soc) / (dt * eta_c))
        d_room = max(0.0, (soc - asset.soc_min_mwh) * eta_d / dt)
        if charge[i] > c_room + 1e-9:
            charge[i], limited[i] = c_room, True
        if discharge[i] > d_room + 1e-9:
            discharge[i], limited[i] = d_room, True
        soc += dt * (eta_c * charge[i] - discharge[i] / eta_d)
    return charge, discharge, limited


@dataclass(frozen=True)
class _Plan:
    """One decision's plan and the tranches it would offer with free prices."""

    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    charge_values: np.ndarray  # (take, K) stored-energy values, NaN = not offered
    discharge_values: np.ndarray
    planned_mode: np.ndarray | None
    stored_energy_value: np.ndarray  # (take,), NaN for the rule planner
    stored_energy_path: np.ndarray  # (steps,), NaN for the rule planner
    forecast: np.ndarray  # (steps,) point forecast clipped to the market bounds
    # The realised prices at which the plan's own offers start to clear, before
    # any band spread; NaN where a direction is not offered.
    charge_limit: np.ndarray
    discharge_limit: np.ndarray
    offsets: np.ndarray
    error_pool_days: float
    scenario_count: int
    solution: ScenarioSolution | None


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
    shared_minutes: int | None = None,
    deg_cost: float = 0.0,
    terminal_value_per_mwh: float = 0.0,
    soc_initial: float | None = None,
    policy: SolverPolicy = STRICT_SOLVER_POLICY,
    execution: str = "bid",
    planner: str = "optimise",
    rule_hours: int = 2,
    timetable: Timetable = NEM_TIMETABLE,
    band_log: list[dict[str, object]] | None = None,
    progress: Callable[[int, pd.Timestamp], None] | None = None,
) -> pd.DataFrame:
    """Dispatch ``prices`` hour by hour from forecasts.

    ``history`` is the contiguous run of settled prices immediately before
    ``prices``; forecasters and the scenario bootstrap read only it and the
    part of ``prices`` that has settled by each decision. The look-ahead is cut
    at the end of ``prices`` for every policy, so closing inventory is valued
    at ``terminal_value_per_mwh`` exactly as in the layer-1 bound.

    ``planner="optimise"`` without ``scenarios`` optimises the single point
    forecast (layer 2); with them it optimises the expected value over the
    scenario set with a shared committed block (layer 3), shared for
    ``shared_minutes`` if that is longer than the committed block.
    ``planner="rule"`` is the rule-based baseline of
    :func:`~battery_dispatch.bidding.rule_limits`.

    ``execution`` sets how the committed block meets realised prices (see
    :mod:`battery_dispatch.bidding`): ``"bands"`` re-prices ``bands`` tranches
    every hour, spread by the quantiles of the forecaster's recent errors at
    the committed block's lead times (from ``band_errors``, or ``scenarios``);
    ``"fixed_bands"`` fixes the band prices for each trading day at its bid
    deadline and only moves quantities hourly; ``"bid"`` offers one price limit
    per direction; ``"committed"`` dispatches the planned quantities whatever
    the price, cut back only where the SOC envelope requires. Every decision is
    made from forecasts alone; the realised price only clears the offers. Each
    fixed-band design is appended to ``band_log``.
    """
    if execution not in EXECUTION_MODES:
        raise ValueError(f"execution must be one of {EXECUTION_MODES}")
    if planner not in PLANNERS:
        raise ValueError(f"planner must be one of {PLANNERS}")
    if planner == "rule" and scenarios is not None:
        raise ValueError("The rule-based planner takes no scenarios")
    error_model = band_errors or scenarios
    spread = execution in ("bands", "fixed_bands")
    if spread and error_model is None:
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
    share = commit
    if shared_minutes is not None:
        share = shared_minutes // asset.interval_minutes
        if shared_minutes % asset.interval_minutes or share < commit:
            raise ValueError(
                "shared_minutes must be a multiple of the interval and >= commit_minutes"
            )
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
    tie = THROUGHPUT_TIE_BREAKER_AUD_PER_MWH

    start = len(past)
    end = len(combined)
    current_soc = asset.initial_soc_mwh if soc_initial is None else float(soc_initial)
    starting_soc = current_soc
    models: dict[tuple[int, int, int, int], ScenarioDispatchModel] = {}

    def plan(position: int, steps: int, take: int, soc: float, key: int) -> _Plan:
        """Forecast, then optimise or apply the rule, and price the tranches.

        Reads only ``actual[:position]``: the prices settled by the decision.
        """
        seen = actual[:position]
        base = np.asarray(forecaster.forecast(seen, steps), dtype=float)
        window = slice(position, position + steps)
        block = slice(position, position + take)
        # One pool of past errors per decision serves both the scenarios and
        # the band spread. The bands price only the committed block, so they
        # are spread by the errors at its lead times, where a good forecaster
        # (AEMO's P5MIN) is far sharper than it is a day ahead.
        needs_errors = scenarios is not None or spread
        errors = error_model.errors(forecaster, seen, steps) if needs_errors else None
        offsets = error_model.band_offsets(errors[:, :take], bands) if spread else np.zeros(1)
        clipped = np.clip(base, MARKET_FLOOR_PRICE, cap[window])
        pool = np.nan if errors is None else float(len(errors))
        if planner == "rule":
            planned_charge, planned_discharge, buy, sell = rule_limits(
                clipped,
                take,
                asset,
                hours=rule_hours,
                generation=float(generation[position]),
                load=float(load[position]),
                deg_cost=deg_cost,
            )
            return _Plan(
                charge_mw=planned_charge,
                discharge_mw=planned_discharge,
                charge_values=charge_value_from_price(
                    buy[:, np.newaxis] + offsets, load[block, np.newaxis], asset, tie
                ),
                discharge_values=discharge_value_from_price(
                    sell[:, np.newaxis] + offsets,
                    generation[block, np.newaxis],
                    deg_cost,
                    asset,
                    tie,
                ),
                planned_mode=None,
                stored_energy_value=np.full(take, np.nan),
                stored_energy_path=np.full(steps, np.nan),
                forecast=clipped,
                charge_limit=buy,
                discharge_limit=sell,
                offsets=offsets,
                error_pool_days=pool,
                scenario_count=1,
                solution=None,
            )
        paths = base[np.newaxis, :] if scenarios is None else scenarios.scenarios(errors, base, key)
        paths = np.clip(paths, MARKET_FLOOR_PRICE, cap[window])
        charge_value = -dt * load[window] * paths
        discharge_value = dt * (generation[window] * paths - deg_cost)
        shared = min(max(share, take), steps)
        shape = (steps, take, paths.shape[0], shared)
        if shape not in models:
            models[shape] = ScenarioDispatchModel(
                asset, steps=steps, committed=take, scenarios=paths.shape[0], shared=shared
            )
        result = models[shape].solve(
            charge_value,
            discharge_value,
            soc,
            terminal_value_per_mwh=terminal_value_per_mwh,
            policy=policy,
        )
        lam = result.stored_energy_value
        values = lam[:, np.newaxis] + offsets
        return _Plan(
            charge_mw=result.charge_mw,
            discharge_mw=result.discharge_mw,
            charge_values=values,
            discharge_values=values.copy(),
            planned_mode=result.planned_mode,
            stored_energy_value=result.stored_energy_value,
            stored_energy_path=result.stored_energy_path,
            forecast=clipped,
            charge_limit=charge_price_from_value(lam, load[block], asset, tie),
            discharge_limit=discharge_price_from_value(
                lam, generation[block], deg_cost, asset, tie
            ),
            offsets=offsets,
            error_pool_days=pool,
            scenario_count=paths.shape[0],
            solution=result,
        )

    # Fixed daily bands: each trading day's prices are set at its deadline.
    trading_day = timetable.trading_day(timestamps)
    fixed: dict[pd.Timestamp, FixedBands] = {}
    pending: list[tuple[int, pd.Timestamp]] = []
    if execution == "fixed_bands":
        position_of = pd.Series(np.arange(len(timestamps)), index=pd.DatetimeIndex(timestamps))
        for day in pd.unique(trading_day[start:end]):
            deadline = timetable.deadline(day)
            if deadline not in position_of.index:
                raise ValueError(f"history does not reach the bid deadline {deadline}")
            # The decision at the deadline has seen the interval ending at it.
            pending.append((int(position_of[deadline]) + 1, pd.Timestamp(day)))
        pending.sort()

    def design(position: int, day: pd.Timestamp, soc: float) -> None:
        """Rule (a): fix ``day``'s band prices from information at ``position``."""
        in_day = np.flatnonzero(trading_day == day)
        first, last = int(in_day[0]), int(min(in_day[-1], end - 1))
        steps = last + 1 - position
        take = min(commit, steps)
        key = 1_000_000 + int(day.toordinal())
        result = plan(position, steps, take, soc, key)
        rel = slice(first - position, last + 1 - position)
        span = slice(first, last + 1)
        if planner == "rule":
            _, _, buy, sell = rule_limits(
                result.forecast[rel],
                last + 1 - first,
                asset,
                hours=rule_hours,
                generation=float(generation[first]),
                load=float(load[first]),
                deg_cost=deg_cost,
            )
            wanted_charge = buy[:, np.newaxis] + result.offsets
            wanted_discharge = sell[:, np.newaxis] + result.offsets
        else:
            values = result.stored_energy_path[rel, np.newaxis] + result.offsets
            wanted_charge = charge_price_from_value(values, load[span, np.newaxis], asset, tie)
            wanted_discharge = discharge_price_from_value(
                values, generation[span, np.newaxis], deg_cost, asset, tie
            )
        day_cap = float(cap[first])
        bands_for_day = FixedBands(
            charge=band_prices(wanted_charge.ravel(), bands, day_cap, direction="charge"),
            discharge=band_prices(wanted_discharge.ravel(), bands, day_cap, direction="discharge"),
            designed_at=timestamps.iloc[position - 1],
        )
        fixed[day] = bands_for_day
        if band_log is not None:
            band_log.append(
                {
                    "trading_day": day,
                    "designed_at": bands_for_day.designed_at,
                    "design_soc_mwh": soc,
                    **{
                        f"charge_band_{k + 1}": value
                        for k, value in enumerate(bands_for_day.charge)
                    },
                    **{
                        f"discharge_band_{k + 1}": value
                        for k, value in enumerate(bands_for_day.discharge)
                    },
                }
            )

    def design_due(upto: int, soc_at: Callable[[int], float]) -> None:
        while pending and pending[0][0] <= upto:
            position, day = pending.pop(0)
            design(position, day, soc_at(position))

    # Days whose deadline falls before the period are designed from the
    # history alone, with the battery at its opening SOC.
    design_due(start, lambda _: starting_soc)

    # Built once at the end: a DataFrame per decision costs more than the solve.
    intervals: dict[str, list[np.ndarray]] = {}
    decisions: list[dict[str, object]] = []
    decision_lengths: list[int] = []
    position = start
    decision = 0
    while position < end:
        steps = min(steps_ahead, end - position)
        take = min(commit, steps)
        block = slice(position, position + take)
        result = plan(position, steps, take, current_soc, decision)
        charge_values, discharge_values = result.charge_values, result.discharge_values
        if execution == "fixed_bands":
            # Rule (b): move each tranche into its trading day's fixed bands.
            charge_values = np.full_like(result.charge_values, np.nan)
            discharge_values = np.full_like(result.discharge_values, np.nan)
            for i in range(take):
                day_bands = fixed[trading_day[position + i]]
                load_i, generation_i = load[position + i], generation[position + i]
                wanted_charge = charge_price_from_value(result.charge_values[i], load_i, asset, tie)
                wanted_discharge = discharge_price_from_value(
                    result.discharge_values[i], generation_i, deg_cost, asset, tie
                )
                charge_values[i] = charge_value_from_price(
                    snap_charge(wanted_charge, day_bands.charge), load_i, asset, tie
                )
                discharge_values[i] = discharge_value_from_price(
                    snap_discharge(wanted_discharge, day_bands.discharge),
                    generation_i,
                    deg_cost,
                    asset,
                    tie,
                )
        if execution == "committed":
            charge, discharge, limited = _cap_to_headroom(
                result.charge_mw, result.discharge_mw, current_soc, asset
            )
        else:
            executed = execute_tranches(
                actual[block],
                result.charge_mw,
                result.discharge_mw,
                charge_values,
                discharge_values,
                generation[block],
                load[block],
                current_soc,
                asset,
                planned_mode=result.planned_mode,
                deg_cost=deg_cost,
                throughput_tie_breaker=tie,
            )
            charge, discharge, limited = (
                executed.charge_mw,
                executed.discharge_mw,
                executed.soc_limited,
            )
        soc = np.clip(
            soc_path(charge, discharge, current_soc, asset),
            asset.soc_min_mwh,
            asset.soc_max_mwh,
        )
        lam = result.stored_energy_value
        interval_columns = {
            "charge_mw": charge,
            "discharge_mw": discharge,
            "soc_mwh": soc,
            "forecast_rrp": result.forecast[:take],
            "planned_charge_mw": result.charge_mw,
            "planned_discharge_mw": result.discharge_mw,
            "stored_energy_value": lam,
            # The realised prices at which the plan's own offers start to clear.
            "charge_limit_rrp": result.charge_limit,
            "discharge_limit_rrp": result.discharge_limit,
            "charge_tranches_offered": np.isfinite(charge_values).sum(axis=1),
            "discharge_tranches_offered": np.isfinite(discharge_values).sum(axis=1),
            "soc_limited": limited,
        }
        for name, values in interval_columns.items():
            intervals.setdefault(name, []).append(values)
        solution = result.solution
        decisions.append(
            {
                "window_id": decision,
                # The rule-based planner makes no solve, so it cannot fail one.
                "solver_status": "ok",
                "solver_termination": "optimal",
                "solve_seconds": 0.0 if solution is None else solution.solve_seconds,
                "solver_mip_gap": 0.0 if solution is None else solution.solver_mip_gap,
                "solver_dual_bound": (np.nan if solution is None else solution.solver_dual_bound),
                "solver_absolute_gap": (0.0 if solution is None else solution.solver_absolute_gap),
                "exclusivity_binary_count": (
                    0 if solution is None else solution.exclusivity_binary_count
                ),
                "scenario_count": result.scenario_count,
                "error_pool_days": result.error_pool_days,
                "band_spread_aud": float(result.offsets[-1] - result.offsets[0]),
                "window_start": timestamps.iloc[position],
                "window_end": timestamps.iloc[position + steps - 1],
                "window_initial_soc_mwh": current_soc,
            }
        )
        decision_lengths.append(take)
        if progress is not None:
            progress(decision, timestamps.iloc[position])
        block_start, block_soc, opening = position, soc, current_soc
        current_soc = float(soc[-1])
        position += take
        decision += 1

        def soc_at(q: int, s: int = block_start, path=block_soc, o: float = opening) -> float:
            # SOC once the interval ending at the deadline has been dispatched.
            return o if q == s else float(path[q - 1 - s])

        # Deadlines that passed during this block are designed with what was
        # known at them, including the SOC the battery had reached by then.
        design_due(position, soc_at)

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
