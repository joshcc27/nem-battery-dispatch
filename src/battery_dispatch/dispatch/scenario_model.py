"""The HiGHS scenario dispatch model behind every forecast-driven policy.

One model shares the committed block's decisions across equiprobable price
scenarios, or across any labelling of them (a scenario tree), and is built
once per shape and only re-priced between decisions. Its equivalence to
:func:`battery_dispatch.dispatch.optimiser.solve_window` is tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import highspy
import numpy as np

from battery_dispatch.dispatch.optimiser import (
    STRICT_SOLVER_POLICY,
    THROUGHPUT_TIE_BREAKER_AUD_PER_MWH,
    SolverPolicy,
    exclusivity_binding_mask,
)
from battery_dispatch.market.config import BatteryConfig
from battery_dispatch.market.settlement import SettlementCoefficients


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


def _run_to_optimality(highs: highspy.Highs, what: str) -> highspy.Highs:
    """Solve, retrying before failing, and return the instance that succeeded.

    Re-pricing a warm-started model between decisions is what keeps each solve
    fast, but after an extreme price scenario the carried-over basis can leave
    HiGHS without a verdict ("Unknown"). Discarding it and solving again from
    scratch usually resolves that. Rarely the same instance still reports
    "Unknown" at the optimal objective (seen once, on an all-continuous decision
    with every decision shared); a fresh instance built from the identical model
    then solves it. A third failure is a real one.
    """
    highs.run()
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        highs.clearSolver()
        highs.run()
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        fresh = highspy.Highs()
        fresh.setOptionValue("output_flag", False)
        gap = highs.getOptionValue("mip_rel_gap")
        # highspy returns (status, value) here in some versions.
        fresh.setOptionValue("mip_rel_gap", float(gap[1] if isinstance(gap, tuple) else gap))
        fresh.passModel(highs.getLp())
        fresh.run()
        highs = fresh
    status = highs.getModelStatus()
    if status != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"HiGHS failed on the {what}: {highs.modelStatusToString(status)}")
    return highs


class ScenarioDispatchModel:
    """HiGHS model for ``scenarios`` price paths over ``steps`` intervals.

    The first ``shared`` intervals (``committed`` by default) have one charge
    and discharge decision shared by every scenario (non-anticipativity); after
    that each scenario has its own dispatch. Only the first ``committed`` are
    ever implemented, so only they carry exclusivity binaries. ``shared`` longer
    than ``committed`` makes the plan less clairvoyant about the scenarios'
    futures: ``shared == steps`` is one plan for every scenario.

    ``groups`` generalises both. It is an integer label per scenario and
    interval, and scenarios with the same label at an interval share that
    interval's decision. A scenario tree, in which decisions stay shared while
    scenarios have the same observed history, is one such labelling (see
    :mod:`battery_dispatch.dispatch.scenario_tree`). The committed block must be shared
    by every scenario.

    Where the dominance argument in
    :func:`~battery_dispatch.dispatch.optimiser.exclusivity_binding_mask` proves a
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
        groups: np.ndarray | None = None,
    ) -> None:
        shared = committed if shared is None else shared
        if not 1 <= committed <= shared <= steps or scenarios < 1:
            raise ValueError("Require 1 <= committed <= shared <= steps and scenarios >= 1")
        self.asset = asset
        self.steps = steps
        self.committed = committed
        self.shared = shared
        self.scenarios = scenarios
        charge_cols = np.empty((scenarios, steps), dtype=np.int64)
        discharge_cols = np.empty((scenarios, steps), dtype=np.int64)
        if groups is None:
            tail = steps - shared
            tail_offset = 2 * shared
            per_scenario_tail = 2 * tail
            self._soc_offset = tail_offset + scenarios * per_scenario_tail
            for s in range(scenarios):
                charge_cols[s, :shared] = np.arange(shared)
                discharge_cols[s, :shared] = shared + np.arange(shared)
                base = tail_offset + s * per_scenario_tail
                charge_cols[s, shared:] = base + np.arange(tail)
                discharge_cols[s, shared:] = base + tail + np.arange(tail)
        else:
            groups = np.asarray(groups)
            if groups.shape != (scenarios, steps):
                raise ValueError(f"groups must have shape {(scenarios, steps)}")
            if (groups[:, :committed] != groups[:1, :committed]).any():
                raise ValueError("Every scenario must share the committed block")
            decisions = 0
            for t in range(steps):
                _, inverse = np.unique(groups[:, t], return_inverse=True)
                charge_cols[:, t] = decisions + inverse
                decisions += int(inverse.max()) + 1
            discharge_cols = charge_cols + decisions
            self._soc_offset = 2 * decisions
        self._mode_offset = self._soc_offset + scenarios * steps
        self.num_col = self._mode_offset + committed
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
        add(mode_rows, charge_cols[0, :committed], 1.0)
        add(mode_rows, self.mode_cols, -asset.power_mw)
        add(mode_rows + committed, discharge_cols[0, :committed], 1.0)
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
        highs = self.highs = _run_to_optimality(highs, "dispatch model")
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
            highs = self.highs = _run_to_optimality(highs, "fixed-mode LP")
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

        charge = clean(solution[self.charge_cols[0, :committed]])
        discharge = clean(solution[self.discharge_cols[0, :committed]])
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
