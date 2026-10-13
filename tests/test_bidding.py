from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_dispatch.dispatch.bidding import (
    NEM_TIMETABLE,
    Timetable,
    band_prices,
    execute_tranches,
    rule_limits,
    snap_charge,
    snap_discharge,
)
from battery_dispatch.dispatch.ceiling import perfect_foresight_ceiling
from battery_dispatch.dispatch.forecast import (
    AemoForecast,
    ErrorBootstrap,
    LaggedForecaster,
    PerfectForecast,
    SameTimeProfile,
    ThinnedErrorHistory,
    grid_times,
)
from battery_dispatch.dispatch.rolling import run_forecast_policy
from battery_dispatch.dispatch.scenario_model import ScenarioDispatchModel
from battery_dispatch.market.aemo_forecasts import ForecastRuns
from battery_dispatch.market.config import AEST, BatteryConfig
from battery_dispatch.market.settlement import settle


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


# Hourly test grids cannot reach a 12:30 deadline; 12:00 keeps the same shape.
HOURLY_TIMETABLE = Timetable(bid_deadline=pd.Timedelta(hours=12))


def hourly_prices(days: int, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    shape = np.array([20.0, 10.0, 0.0, -10.0, 40.0, 120.0] * 4)
    values = np.tile(shape, days) + rng.normal(0.0, 20.0, days * 24)
    timestamps = pd.date_range("2023-01-01 01:00", periods=len(values), freq="h", tz=AEST)
    return pd.DataFrame({"settlementdate": timestamps, "rrp": values})


def test_trading_day_runs_from_0400_and_its_bands_close_at_1230_the_day_before() -> None:
    ends = pd.DatetimeIndex(
        ["2023-06-02 04:00", "2023-06-02 04:05", "2023-06-03 00:00", "2023-06-03 04:00"]
    ).tz_localize(AEST)
    days = NEM_TIMETABLE.trading_day(ends)
    assert [str(day.date()) for day in days] == [
        "2023-06-01",
        "2023-06-02",
        "2023-06-02",
        "2023-06-02",
    ]
    assert NEM_TIMETABLE.deadline(days[1]) == pd.Timestamp("2023-06-01 12:30", tz=AEST)


def test_band_prices_are_increasing_quantiles_inside_the_market_bounds() -> None:
    wanted = np.array([10.0, 20.0, 30.0, 40.0, np.nan, 50_000.0, -5_000.0])
    prices = band_prices(wanted, 4, cap=15_500.0)
    assert np.all(np.diff(prices) > 0)
    assert prices[0] >= -1_000.0 and prices[-1] <= 15_500.0 + 0.04
    # Ties are separated so the bands stay strictly increasing.
    assert np.all(np.diff(band_prices(np.full(5, 7.0), 3, cap=100.0)) > 0)
    assert np.isnan(band_prices(np.array([np.nan]), 3, cap=100.0)).all()


def test_tranches_snap_to_a_band_no_worse_than_wanted_or_are_withheld() -> None:
    bands = np.array([10.0, 20.0, 30.0])
    # Charging pays at or below the band price: the dearest band at or below.
    np.testing.assert_array_equal(
        snap_charge(np.array([25.0, 5.0, 30.0, np.nan]), bands),
        [20.0, np.nan, 30.0, np.nan],
    )
    # Discharging pays at or above it: the cheapest band at or above.
    np.testing.assert_array_equal(
        snap_discharge(np.array([25.0, 35.0, 10.0]), bands), [30.0, np.nan, 10.0]
    )


def test_withheld_tranches_never_clear() -> None:
    asset = hourly_asset(round_trip_efficiency=1.0, energy_mwh=10.0)
    values = np.array([[60.0, np.nan, np.nan, np.nan]])
    executed = execute_tranches(
        np.array([-500.0]),
        np.zeros(1),
        np.zeros(1),
        values,
        np.full((1, 4), np.nan),
        np.ones(1),
        np.ones(1),
        5.0,
        asset,
        throughput_tie_breaker=0.0,
    )
    # One of four tranches is offered, so a quarter of the rating charges.
    assert executed.charge_mw.tolist() == [0.25]
    assert executed.discharge_mw.tolist() == [0.0]


def test_rule_charges_in_the_cheapest_and_sells_in_the_dearest_hours() -> None:
    asset = hourly_asset(round_trip_efficiency=1.0)
    forecast = np.array([50.0, 10.0, 100.0, 20.0, 90.0, 30.0])
    charge, discharge, buy, sell = rule_limits(
        forecast, 3, asset, hours=1, generation=1.0, load=1.0, deg_cost=0.0
    )
    assert charge.tolist() == [0.0, 1.0, 0.0]
    assert discharge.tolist() == [0.0, 0.0, 1.0]
    np.testing.assert_array_equal(buy, [np.nan, 10.0, np.nan])
    np.testing.assert_array_equal(sell, [np.nan, np.nan, 100.0])
    # Not worth a cycle after losses and degradation: no trade at all.
    flat = np.array([50.0, 49.0, 51.0, 50.0])
    charge, discharge, buy, sell = rule_limits(
        flat, 2, hourly_asset(), hours=1, generation=1.0, load=1.0, deg_cost=5.0
    )
    assert not charge.any() and not discharge.any() and np.isnan(buy).all()


def test_sharing_every_decision_is_the_deterministic_plan_on_the_mean() -> None:
    """With nothing left to adapt, expected value is linear in the scenarios."""
    asset = hourly_asset()
    paths = np.array([[10.0, -50.0, 80.0, 5.0, 120.0, 30.0], [30.0, 20.0, 0.0, 60.0, 40.0, 90.0]])
    shared = ScenarioDispatchModel(asset, steps=6, committed=2, scenarios=2, shared=6).solve(
        -paths, paths, 0.5, throughput_tie_breaker=0.0
    )
    mean = paths.mean(axis=0, keepdims=True)
    single = ScenarioDispatchModel(asset, steps=6, committed=2, scenarios=1).solve(
        -mean, mean, 0.5, throughput_tie_breaker=0.0
    )
    assert shared.objective_value == pytest.approx(single.objective_value, abs=1e-9)
    adaptive = ScenarioDispatchModel(asset, steps=6, committed=2, scenarios=2).solve(
        -paths, paths, 0.5, throughput_tie_breaker=0.0
    )
    # Letting the tail adapt to each scenario can only raise the planned value.
    assert adaptive.objective_value >= shared.objective_value - 1e-9


def test_a_lagged_forecaster_sees_the_history_lag_intervals_earlier() -> None:
    profile = SameTimeProfile(1, 24)
    values = np.arange(72, dtype=float)
    lagged = LaggedForecaster(profile, 2)
    np.testing.assert_array_equal(lagged.forecast(values, 5), profile.forecast(values[:-2], 7)[2:])
    assert (
        LaggedForecaster(profile, 0).forecast(values, 5).tolist()
        == profile.forecast(values, 5).tolist()
    )
    assert lagged.min_history == profile.min_history + 2


def runs_frame(rows: list[tuple[str, str, str, float]]) -> ForecastRuns:
    frame = pd.DataFrame(rows, columns=["run_id", "published", "target", "rrp"])
    frame["published"] = pd.to_datetime(frame["published"]).dt.tz_localize(AEST)
    frame["target"] = pd.to_datetime(frame["target"]).dt.tz_localize(AEST)
    return ForecastRuns.from_frame(frame)


def test_a_lagged_aemo_forecaster_ignores_runs_published_inside_the_lag() -> None:
    timestamps = pd.date_range("2022-12-31 00:05", periods=600, freq="5min", tz=AEST)
    empty = runs_frame([])
    p5min = runs_frame(
        [
            ("a", "2023-01-01 23:50", "2023-01-02 00:05", 100.0),
            ("b", "2023-01-01 23:59", "2023-01-02 00:05", 900.0),
        ]
    )
    forecaster = AemoForecast(
        timestamps=grid_times(pd.Series(timestamps)),
        predispatch=empty,
        p5min=p5min,
        fallback=SameTimeProfile(1, 288),
    )
    history = np.zeros(576)  # the decision is at 2023-01-02 00:00
    assert forecaster.forecast(history, 1)[0] == 900.0
    # Ten minutes of latency: the decision sees what was known at 23:50.
    assert LaggedForecaster(forecaster, 2).forecast(history, 1)[0] == 100.0


def test_thinned_error_history_drops_early_lags_only() -> None:
    profile = SameTimeProfile(1, 24)
    values = np.random.default_rng(1).normal(50.0, 20.0, 24 * 10)
    model = ErrorBootstrap(count=2, pool_days=5, periods_per_day=24)
    full = model.errors(profile, values, 6)
    thin = model.errors(ThinnedErrorHistory(profile, len(values) - 24 * 3), values, 6)
    assert len(full) == 5 and len(thin) == 3
    np.testing.assert_array_equal(thin, full[:3])


def fixed_band_run(frame: pd.DataFrame, forecaster, **changes):
    asset = hourly_asset()
    history_len = 24 * 9
    log: list[dict[str, object]] = []
    options = {
        "band_errors": ErrorBootstrap(count=2, pool_days=3, periods_per_day=24),
        "bands": 4,
        "horizon_hours": 12,
        "deg_cost": 2.0,
        "execution": "fixed_bands",
        "timetable": HOURLY_TIMETABLE,
        "band_log": log,
    }
    options.update(changes)
    trace = run_forecast_policy(
        frame.iloc[history_len:], frame.iloc[:history_len], asset, forecaster, **options
    )
    return trace, pd.DataFrame(log), asset


def test_later_prices_cannot_change_a_submitted_band_price() -> None:
    frame = hourly_prices(14)
    trace, log, asset = fixed_band_run(frame, SameTimeProfile(3, 24))
    assert not log.empty
    # Every evaluated trading day has bands, designed at noon the day before.
    days = set(HOURLY_TIMETABLE.trading_day(trace["settlementdate"]))
    assert days == set(log["trading_day"])
    for row in log.itertuples():
        assert row.designed_at == HOURLY_TIMETABLE.deadline(row.trading_day)

    # Spoil every price after one deadline; bands designed by then are unchanged.
    cut = log["designed_at"].iloc[3]
    spoiled = frame.copy()
    later = spoiled["settlementdate"] > cut
    spoiled.loc[later, "rrp"] = 5_000.0
    again, log_again, _ = fixed_band_run(spoiled, SameTimeProfile(3, 24))
    early = log["designed_at"] <= cut
    band_columns = [c for c in log.columns if "_band_" in c]
    pd.testing.assert_frame_equal(log.loc[early, band_columns], log_again.loc[early, band_columns])
    before = trace["settlementdate"] <= cut
    np.testing.assert_allclose(
        trace.loc[before, "charge_mw"], again.loc[before, "charge_mw"], atol=1e-12
    )

    revenue = settle(trace, frame.iloc[24 * 9 :], asset, deg_cost=2.0)
    bound = perfect_foresight_ceiling(frame.iloc[24 * 9 :], asset, soc_initial=0.0, deg_cost=2.0)
    assert revenue.total_revenue <= bound["perfect_foresight_ceiling_aud"] + 1e-6


def published_runs(frame: pd.DataFrame, noise: float, seed: int) -> dict[str, ForecastRuns]:
    rng = np.random.default_rng(seed)
    rows = []
    for position in range(1, len(frame)):
        published = frame["settlementdate"].iloc[position - 1]
        ahead = frame.iloc[position : position + 12]
        rows.append(
            pd.DataFrame(
                {
                    "run_id": str(position),
                    "published": published,
                    "target": ahead["settlementdate"].to_numpy(),
                    "rrp": ahead["rrp"].to_numpy() + rng.normal(0.0, noise, len(ahead)),
                }
            )
        )
    runs = pd.concat(rows, ignore_index=True)
    empty = runs.iloc[:0]
    return {
        "predispatch": ForecastRuns.from_frame(runs),
        "p5min": ForecastRuns.from_frame(empty),
        "frame": runs,
    }


def test_later_forecast_publications_cannot_change_a_submitted_band_price() -> None:
    frame = hourly_prices(14)
    timestamps = grid_times(frame["settlementdate"])
    runs = published_runs(frame, 10.0, 3)

    def aemo(predispatch: ForecastRuns) -> AemoForecast:
        return AemoForecast(
            timestamps=timestamps,
            predispatch=predispatch,
            p5min=runs["p5min"],
            fallback=SameTimeProfile(3, 24),
            max_predispatch_age=np.timedelta64(60, "m"),
        )

    _, log, _ = fixed_band_run(frame, aemo(runs["predispatch"]))
    cut = log["designed_at"].iloc[2]
    altered = runs["frame"].copy()
    altered.loc[altered["published"] > cut, "rrp"] += 3_000.0
    _, log_again, _ = fixed_band_run(frame, aemo(ForecastRuns.from_frame(altered)))
    early = log["designed_at"] <= cut
    band_columns = [c for c in log.columns if "_band_" in c]
    pd.testing.assert_frame_equal(log.loc[early, band_columns], log_again.loc[early, band_columns])
    assert not log.loc[~early, band_columns].equals(log_again.loc[~early, band_columns])


def test_fixed_band_offers_only_clear_beyond_their_days_band_prices() -> None:
    frame = hourly_prices(14)
    trace, log, _ = fixed_band_run(frame, PerfectForecast(frame["rrp"].to_numpy()))
    bands = log.set_index("trading_day")
    day = HOURLY_TIMETABLE.trading_day(trace["settlementdate"])
    lowest_sell = bands.loc[day, "discharge_band_1"].to_numpy()
    highest_buy = bands.loc[day, "charge_band_4"].to_numpy()
    sold = trace["discharge_mw"].to_numpy() > 1e-9
    bought = trace["charge_mw"].to_numpy() > 1e-9
    rrp = frame["rrp"].to_numpy()[24 * 9 :]
    assert sold.any() and bought.any()
    assert (rrp[sold] >= lowest_sell[sold] - 1e-6).all()
    assert (rrp[bought] <= highest_buy[bought] + 1e-6).all()


def test_the_rule_based_baseline_runs_under_every_execution() -> None:
    frame = hourly_prices(14)
    asset = hourly_asset()
    for execution in ("bid", "bands", "committed", "fixed_bands"):
        trace, _, _ = fixed_band_run(
            frame, SameTimeProfile(3, 24), planner="rule", rule_hours=2, execution=execution
        )
        assert (trace["solve_seconds"] == 0).all()
        settle(trace, frame.iloc[24 * 9 :], asset, deg_cost=2.0)
    with pytest.raises(ValueError, match="rule-based"):
        fixed_band_run(
            frame,
            SameTimeProfile(3, 24),
            planner="rule",
            scenarios=ErrorBootstrap(count=2, pool_days=3, periods_per_day=24),
        )
