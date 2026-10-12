from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_dispatch.ceiling import perfect_foresight_ceiling
from battery_dispatch.config import AEST, BatteryConfig, LossFactors, LossFactorTable
from battery_dispatch.forecast import ErrorBootstrap, PerfectForecast, SameTimeProfile
from battery_dispatch.mpc import ScenarioDispatchModel, execute_offers, run_forecast_policy
from battery_dispatch.optimiser import solve_window
from battery_dispatch.settlement import settle, settlement_coefficients


def hourly_asset(**changes: float) -> BatteryConfig:
    values = {
        "generation_loss_factor": 1.0,
        "load_loss_factor": 1.0,
        "power_mw": 1.0,
        "energy_mwh": 2.0,
        "round_trip_efficiency": 0.81,
        "soc_min_fraction": 0.0,
        "soc_max_fraction": 1.0,
        "interval_minutes": 60,
    }
    values.update(changes)
    return BatteryConfig(**values)


def hourly_prices(values: np.ndarray, start: str = "2023-01-01 01:00") -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=len(values), freq="h", tz=AEST)
    return pd.DataFrame({"settlementdate": timestamps, "rrp": values})


def split(frame: pd.DataFrame, history_len: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    return frame.iloc[history_len:], frame.iloc[:history_len]


def test_direct_model_matches_the_linopy_window() -> None:
    """Same MILP, two builders: every committed interval is exclusive."""
    reference = BatteryConfig(generation_loss_factor=0.97, load_loss_factor=0.99)
    rng = np.random.default_rng(2)
    for _ in range(3):
        prices = rng.normal(0.0, 200.0, 96)
        expected = solve_window(prices, reference, 60.0, 25.0)
        coefficients = settlement_coefficients(prices, reference, deg_cost=25.0)
        model = ScenarioDispatchModel(reference, steps=96, committed=96, scenarios=1)
        got = model.solve(
            coefficients.charge_value_per_mw[np.newaxis],
            coefficients.discharge_value_per_mw[np.newaxis],
            60.0,
        )
        assert got.objective_value == pytest.approx(expected.objective_value, abs=1e-6)
        assert got.exclusivity_binary_count == expected.exclusivity_binary_count


def test_identical_scenarios_reduce_to_the_deterministic_model() -> None:
    battery = hourly_asset()
    prices = np.array([10.0, -50.0, 80.0, 5.0, 120.0, 30.0])
    coefficients = settlement_coefficients(prices, battery, deg_cost=5.0)
    charge = coefficients.charge_value_per_mw[np.newaxis]
    discharge = coefficients.discharge_value_per_mw[np.newaxis]
    one = ScenarioDispatchModel(battery, steps=6, committed=2, scenarios=1).solve(
        charge, discharge, 0.5
    )
    many = ScenarioDispatchModel(battery, steps=6, committed=2, scenarios=4).solve(
        np.repeat(charge, 4, axis=0), np.repeat(discharge, 4, axis=0), 0.5
    )
    assert many.objective_value == pytest.approx(one.objective_value, abs=1e-9)
    np.testing.assert_allclose(many.charge_mw, one.charge_mw, atol=1e-9)
    np.testing.assert_allclose(many.discharge_mw, one.discharge_mw, atol=1e-9)


def test_shared_commitment_hedges_between_scenarios() -> None:
    """Hand-worked: the committed hour cannot follow each scenario separately.

    One MWh can be bought now at 20 and sold next hour at 100 in one scenario
    or at 0 in the other. Knowing it was in the second, it would not buy; not
    knowing, it buys because the expected margin is (80 - 20) / 2 = 30 > 0.
    """
    battery = hourly_asset(energy_mwh=1.0, round_trip_efficiency=1.0)
    prices = np.array([[20.0, 100.0], [20.0, 0.0]])
    model = ScenarioDispatchModel(battery, steps=2, committed=1, scenarios=2)
    result = model.solve(-prices, prices, 0.0, throughput_tie_breaker=0.0)
    assert result.charge_mw.tolist() == [1.0]
    assert result.objective_value == pytest.approx(30.0)
    # The second scenario alone would stay idle.
    alone = ScenarioDispatchModel(battery, steps=2, committed=1, scenarios=1).solve(
        -prices[1:], prices[1:], 0.0, throughput_tie_breaker=0.0
    )
    assert alone.charge_mw.tolist() == [0.0]


def test_perfect_forecast_policy_reaches_the_bound_on_a_hand_case() -> None:
    battery = hourly_asset(energy_mwh=1.0, round_trip_efficiency=1.0)
    history = hourly_prices(np.zeros(4))
    prices = hourly_prices(np.array([0.0, 100.0, 0.0, 200.0]), start="2023-01-01 05:00")
    actual = np.concatenate([history["rrp"], prices["rrp"]])
    trace = run_forecast_policy(
        prices, history, battery, PerfectForecast(actual), horizon_hours=4, commit_minutes=60
    )
    revenue = settle(trace, prices, battery)
    assert revenue.total_revenue == pytest.approx(300.0)
    assert trace["window_id"].nunique() == 4


def test_a_forecast_policy_never_beats_the_bound_and_cannot_see_ahead() -> None:
    battery = hourly_asset()
    rng = np.random.default_rng(5)
    days = 8
    values = np.tile([10.0, 5.0, 0.0, 20.0, 90.0, 60.0] * 4, days) + rng.normal(0, 15, days * 24)
    frame = hourly_prices(values)
    prices, history = split(frame, 24 * 4)
    policy = {"horizon_hours": 12, "commit_minutes": 120, "deg_cost": 2.0}
    trace = run_forecast_policy(prices, history, battery, SameTimeProfile(3, 24), **policy)
    revenue = settle(trace, prices, battery, deg_cost=2.0)
    ceiling = perfect_foresight_ceiling(prices, battery, soc_initial=0.0, deg_cost=2.0)
    assert revenue.total_revenue <= ceiling["perfect_foresight_ceiling_aud"] + 1e-6

    # Change every price from hour 30 of the evaluation on. Decisions taken at
    # or before hour 30 read only earlier prices, so their dispatch is unchanged.
    cut = 30
    spoiled = prices.copy()
    spoiled.iloc[cut:, spoiled.columns.get_loc("rrp")] = 5_000.0
    again = run_forecast_policy(spoiled, history, battery, SameTimeProfile(3, 24), **policy)
    columns = ["charge_mw", "discharge_mw", "soc_mwh"]
    pd.testing.assert_frame_equal(trace[columns].iloc[:cut], again[columns].iloc[:cut])


def test_stochastic_policy_on_a_perfect_forecast_is_the_deterministic_one() -> None:
    """Every bootstrapped error of a perfect forecast is zero."""
    battery = hourly_asset()
    values = np.tile([10.0, 5.0, 0.0, 20.0, 90.0, 60.0] * 4, 6)
    frame = hourly_prices(values)
    prices, history = split(frame, 24 * 4)
    oracle = PerfectForecast(values)
    policy = {"horizon_hours": 12, "commit_minutes": 60}
    deterministic = run_forecast_policy(prices, history, battery, oracle, **policy)
    stochastic = run_forecast_policy(
        prices,
        history,
        battery,
        oracle,
        scenarios=ErrorBootstrap(count=2, pool_days=3, periods_per_day=24),
        **policy,
    )
    assert stochastic["scenario_count"].iloc[0] == 2
    np.testing.assert_allclose(
        stochastic["soc_mwh"].to_numpy(), deterministic["soc_mwh"].to_numpy(), atol=1e-9
    )


def test_history_must_join_the_period() -> None:
    battery = hourly_asset()
    frame = hourly_prices(np.zeros(48))
    with pytest.raises(ValueError, match="one interval before"):
        run_forecast_policy(
            frame.iloc[30:], frame.iloc[:24], battery, SameTimeProfile(1, 24)
        )


def test_stored_energy_value_is_the_next_best_sale() -> None:
    """Hand-worked, pinning the dual's sign: sell 1 MWh at 200 now, 100 is next best.

    Holding the MWh instead would earn 100 next hour, so a stored MWh is worth
    exactly 100 and discharging clears only above 100.
    """
    battery = hourly_asset(energy_mwh=1.0, round_trip_efficiency=1.0)
    prices = np.array([[200.0, 100.0, 30.0]])
    model = ScenarioDispatchModel(battery, steps=3, committed=1, scenarios=1)
    result = model.solve(-prices, prices, 1.0, throughput_tie_breaker=0.0)
    assert result.discharge_mw.tolist() == [1.0]
    assert result.stored_energy_value.tolist() == pytest.approx([100.0])


def offers(realised, planned_charge, planned_discharge, lam, soc=0.5, **changes):
    battery = hourly_asset(round_trip_efficiency=1.0, **changes)
    n = len(realised)
    return execute_offers(
        np.asarray(realised, float),
        np.asarray(planned_charge, float),
        np.asarray(planned_discharge, float),
        np.full(n, lam),
        np.ones(n),
        np.ones(n),
        soc,
        battery,
        throughput_tie_breaker=0.0,
    )


def test_offers_decline_a_spike_the_plan_would_have_charged_into() -> None:
    # Planned to charge at a forecast of 20 with stored energy worth 60; the
    # interval clears at 15,500 instead, so the offer sells rather than buys,
    # as much as the 0.5 MWh stored allows in the hour.
    charge, discharge = offers([15_500.0], [0.4], [0.0], lam=60.0)
    assert charge.tolist() == [0.0]
    assert discharge.tolist() == [0.5]


def test_offers_clear_the_planned_quantity_at_the_limit_and_full_power_beyond() -> None:
    charge, discharge = offers([60.0, 20.0, 100.0], [0.3, 0.3, 0.0], [0.0, 0.0, 0.2], lam=60.0)
    assert charge.tolist() == [0.3, 1.0, 0.0]
    assert discharge.tolist() == [0.0, 0.0, 1.0]


def test_offers_respect_soc_headroom_across_the_block() -> None:
    # 1.5 MWh of headroom on a 2 MWh asset: full power, then what is left.
    charge, _ = offers([0.0, 0.0, 0.0], [0.0] * 3, [0.0] * 3, lam=60.0, soc=0.5)
    assert charge.tolist() == [1.0, 0.5, 0.0]


def test_bid_execution_of_a_perfect_forecast_is_the_plan() -> None:
    """At the forecast prices the offers are the plan's own optimality conditions."""
    battery = BatteryConfig(
        generation_loss_factor=0.97, load_loss_factor=0.99, interval_minutes=60
    )
    rng = np.random.default_rng(12)
    # Prices below -169 make burning energy pay at A$25/MWh, so binaries bind.
    values = np.tile([30.0, -300.0, -40.0, 20.0, 180.0, 90.0] * 4, 6) + rng.normal(0, 40, 144)
    frame = hourly_prices(values)
    prices, history = split(frame, 48)
    oracle = PerfectForecast(values)
    policy = {"horizon_hours": 24, "commit_minutes": 180, "deg_cost": 25.0}
    bid = run_forecast_policy(prices, history, battery, oracle, execution="bid", **policy)
    committed = run_forecast_policy(
        prices, history, battery, oracle, execution="committed", **policy
    )
    for column in ("charge_mw", "discharge_mw", "soc_mwh"):
        np.testing.assert_allclose(bid[column], committed[column], atol=1e-6)
    with pytest.raises(ValueError, match="execution"):
        run_forecast_policy(prices, history, battery, oracle, execution="other", **policy)


def test_offers_keep_a_planned_idle_interval_idle_where_burning_pays() -> None:
    """At a deeply negative price both directions clear; the plan's mode decides."""
    battery = hourly_asset(round_trip_efficiency=0.81)
    # At p = -300 with stored energy worth -300 and eta = 0.9 each way, charging
    # earns 0.9*-300 + 300 = 30 and discharging -300 + 300/0.9 = 33 per MWh.
    args = (
        np.array([-300.0]),
        np.array([0.0]),
        np.array([0.0]),
        np.array([-300.0]),
        np.ones(1),
        np.ones(1),
        1.0,
        battery,
    )
    charge, discharge = execute_offers(*args, planned_mode=np.array([1.0]))
    assert (charge.tolist(), discharge.tolist()) == ([1.0], [0.0])
    charge, discharge = execute_offers(*args, planned_mode=np.array([0.0]))
    # The 1 MWh stored delivers 0.9 MWh at the meter.
    assert charge.tolist() == [0.0]
    assert discharge.tolist() == pytest.approx([0.9])


def test_forecasts_are_clipped_to_each_intervals_own_price_cap() -> None:
    """The interval ending 1 July 00:00 still carries the old year's cap."""
    unit = LossFactors(1.0, 1.0, "test")
    battery = hourly_asset(
        loss_factor_table=LossFactorTable({"2022-23": unit, "2023-24": unit})
    )
    timestamps = pd.date_range("2023-06-20 01:00", periods=24 * 14, freq="h", tz=AEST)
    frame = pd.DataFrame({"settlementdate": timestamps, "rrp": np.full(len(timestamps), 16_000.0)})
    prices, history = split(frame, 24 * 7)
    trace = run_forecast_policy(prices, history, battery, SameTimeProfile(1, 24), horizon_hours=6)
    forecast = trace.set_index("settlementdate")["forecast_rrp"]
    assert forecast[pd.Timestamp("2023-07-01 00:00", tz=AEST)] == 15_500.0
    assert forecast[pd.Timestamp("2023-07-01 01:00", tz=AEST)] == 16_000.0


def test_bands_clear_progressively_as_the_price_passes_their_limits() -> None:
    """Four quarter-power bands at stored-energy values 40, 50, 70, 80 (eta = 1)."""
    offsets = np.array([-20.0, -10.0, 10.0, 20.0])
    kwargs = {"band_offsets": offsets}
    battery = hourly_asset(round_trip_efficiency=1.0, energy_mwh=10.0)

    def run(price: float) -> tuple[float, float]:
        charge, discharge = execute_offers(
            np.array([price]), np.zeros(1), np.zeros(1), np.array([60.0]),
            np.ones(1), np.ones(1), 5.0, battery, throughput_tie_breaker=0.0, **kwargs,
        )
        return float(charge[0]), float(discharge[0])

    # At 45 three charge bands clear (margin up to 35) and one discharge band
    # (margin 5): the larger margin wins, so it charges three quarters.
    assert run(45.0) == (0.75, 0.0)
    # At 65 two bands each way; selling at 65 energy worth 60 has the larger margin.
    assert run(65.0) == (0.0, 0.5)
    assert run(75.0) == (0.0, 0.75)
    assert run(85.0) == (0.0, 1.0)  # above every discharge band


def test_band_execution_of_a_perfect_forecast_is_the_plan() -> None:
    """A perfect forecast has no errors, so every band sits at the plan's limit."""
    battery = BatteryConfig(
        generation_loss_factor=0.97, load_loss_factor=0.99, interval_minutes=60
    )
    rng = np.random.default_rng(12)
    values = np.tile([30.0, -300.0, -40.0, 20.0, 180.0, 90.0] * 4, 8) + rng.normal(0, 40, 192)
    frame = hourly_prices(values)
    prices, history = split(frame, 96)
    oracle = PerfectForecast(values)
    policy = {"horizon_hours": 24, "commit_minutes": 180, "deg_cost": 25.0}
    bands = run_forecast_policy(
        prices,
        history,
        battery,
        oracle,
        execution="bands",
        band_errors=ErrorBootstrap(count=1, pool_days=2, periods_per_day=24),
        **policy,
    )
    committed = run_forecast_policy(
        prices, history, battery, oracle, execution="committed", **policy
    )
    assert (bands["band_spread_aud"] == 0).all()
    for column in ("charge_mw", "discharge_mw", "soc_mwh"):
        np.testing.assert_allclose(bands[column], committed[column], atol=1e-6)
    with pytest.raises(ValueError, match="band_errors"):
        run_forecast_policy(prices, history, battery, oracle, execution="bands", **policy)


class ExactForAnHour:
    """Exact for the next hour, then badly wrong: like P5MIN followed by a guess."""

    name = "exact_first_hour"
    min_history = 0

    def __init__(self, actual: np.ndarray) -> None:
        self.actual = actual

    def forecast(self, history: np.ndarray, steps: int) -> np.ndarray:
        values = self.actual[len(history) : len(history) + steps].copy()
        values[1:] += 500.0
        return values


def test_bands_are_spread_by_errors_at_the_committed_lead_times() -> None:
    battery = hourly_asset()
    values = np.tile([10.0, 5.0, 0.0, 20.0, 90.0, 60.0] * 4, 6)
    frame = hourly_prices(values)
    prices, history = split(frame, 24 * 4)
    trace = run_forecast_policy(
        prices,
        history,
        battery,
        ExactForAnHour(values),
        execution="bands",
        band_errors=ErrorBootstrap(count=1, pool_days=2, periods_per_day=24),
        horizon_hours=12,
        commit_minutes=60,
    )
    # The committed hour is always forecast exactly, so the bands never spread
    # even though the rest of the look-ahead is out by A$500.
    assert (trace["band_spread_aud"] == 0).all()
