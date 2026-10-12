from __future__ import annotations

import numpy as np
import pytest

from battery_dispatch.forecast import ErrorBootstrap, PerfectForecast, SameTimeProfile


def test_persistence_repeats_the_last_day() -> None:
    history = np.arange(8.0)  # two days of four periods
    forecast = SameTimeProfile(1, periods_per_day=4).forecast(history, 6)
    # Tomorrow's periods are yesterday's 4, 5, 6, 7, and it wraps past a day.
    assert forecast.tolist() == [4.0, 5.0, 6.0, 7.0, 4.0, 5.0]
    assert SameTimeProfile(1).name == "persistence"


def test_profile_is_the_median_at_each_time_of_day() -> None:
    history = np.array([0.0, 10.0, 100.0, 10.0, 1.0, 20.0, 2.0, 30.0, 3.0])
    profile = SameTimeProfile(3, periods_per_day=3)
    # Columns are (0, 10, 2), (10, 1, 30), (100, 20, 3).
    assert profile.forecast(history, 3).tolist() == [2.0, 10.0, 20.0]
    assert profile.name == "median_3d"
    with pytest.raises(ValueError, match="history"):
        profile.forecast(history[:-1], 3)


def test_perfect_forecast_only_accepts_its_own_past() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    oracle = PerfectForecast(actual)
    assert oracle.forecast(actual[:2], 2).tolist() == [3.0, 4.0]
    with pytest.raises(ValueError, match="prefix"):
        oracle.forecast(np.array([9.0, 2.0]), 2)
    with pytest.raises(ValueError, match="end"):
        oracle.forecast(actual[:3], 2)


def test_bootstrap_adds_a_past_days_realised_error() -> None:
    """With persistence, a lag-k error is day(-k) minus day(-k-1)."""
    per_day = 4
    days = np.array([[0, 0, 0, 0], [1, 2, 3, 4], [10, 20, 30, 40], [5, 5, 5, 5]], float)
    history = days.ravel()
    persistence = SameTimeProfile(1, per_day)
    base = persistence.forecast(history, per_day)
    bootstrap = ErrorBootstrap(count=2, pool_days=2, periods_per_day=per_day, seed=3)
    scenarios = bootstrap.generate(persistence, history, base, decision_index=0)
    errors = {tuple(row) for row in scenarios - base}
    # Lag 1 is day 3 against day 2's persistence; lag 2 is day 2 against day 1.
    assert errors == {
        tuple(days[3] - days[2]),
        tuple(days[2] - days[1]),
    }


def test_bootstrap_is_repeatable_and_never_reads_ahead() -> None:
    rng = np.random.default_rng(0)
    history = rng.normal(size=24 * 10)
    persistence = SameTimeProfile(1, 24)
    base = persistence.forecast(history, 24)
    bootstrap = ErrorBootstrap(count=3, pool_days=5, periods_per_day=24, seed=11)
    first = bootstrap.generate(persistence, history, base, decision_index=4)
    again = bootstrap.generate(persistence, history, base, decision_index=4)
    np.testing.assert_array_equal(first, again)
    assert bootstrap.min_history(persistence, 24) == (1 + 5 - 1) * 24 + 24
    with pytest.raises(ValueError, match="history"):
        bootstrap.generate(persistence, history[: 24 * 5], base, decision_index=0)


def test_bootstrap_of_a_perfect_forecast_has_no_spread() -> None:
    actual = np.random.default_rng(1).normal(size=24 * 6)
    oracle = PerfectForecast(actual)
    history = actual[: 24 * 5]
    base = oracle.forecast(history, 24)
    bootstrap = ErrorBootstrap(count=3, pool_days=3, periods_per_day=24)
    scenarios = bootstrap.generate(oracle, history, base, decision_index=0)
    np.testing.assert_allclose(scenarios, np.tile(base, (3, 1)))


def test_bootstrap_rejects_more_scenarios_than_its_pool() -> None:
    with pytest.raises(ValueError, match="count"):
        ErrorBootstrap(count=5, pool_days=4)


def test_winsorize_caps_errors_at_the_pool_quantiles() -> None:
    history = np.zeros(24 * 12)
    history[24 * 9 + 5] = 10_000.0  # one spike, nine days ago
    persistence = SameTimeProfile(1, 24)
    capped = ErrorBootstrap(count=2, pool_days=10, periods_per_day=24, winsorize=0.05)
    raw = ErrorBootstrap(count=2, pool_days=10, periods_per_day=24)
    assert raw.errors(persistence, history, 24).max() == 10_000.0
    errors = capped.errors(persistence, history, 24)
    assert errors.max() < 10_000.0
    assert errors.max() == pytest.approx(np.quantile(raw.errors(persistence, history, 24), 0.95))


class CoversEvenDaysOnly:
    """A forecaster that was only running on alternate days, as over an archive gap."""

    name = "gappy"
    min_history = 24

    def covers(self, position: int) -> bool:
        return (position // 24) % 2 == 0

    def forecast(self, history: np.ndarray, steps: int) -> np.ndarray:
        return np.zeros(steps)


def test_bootstrap_leaves_out_days_the_forecaster_did_not_cover() -> None:
    history = np.arange(24 * 12, dtype=float)
    bootstrap = ErrorBootstrap(count=3, pool_days=6, periods_per_day=24)
    errors = bootstrap.errors(CoversEvenDaysOnly(), history, 24)
    assert len(errors) == 3
    # A thin pool is resampled with replacement; an empty one is the forecast.
    assert bootstrap.scenarios(errors[:1], np.zeros(24), 0).shape == (3, 24)
    empty = np.empty((0, 24))
    np.testing.assert_array_equal(bootstrap.scenarios(empty, np.ones(24), 0), np.ones((3, 24)))
    np.testing.assert_array_equal(bootstrap.band_offsets(empty, 4), np.zeros(4))


def test_band_offsets_are_error_quantiles_at_band_midpoints() -> None:
    errors = np.arange(100.0).reshape(4, 25)
    offsets = ErrorBootstrap(count=1, pool_days=4).band_offsets(errors, 4)
    np.testing.assert_allclose(offsets, np.quantile(errors, [0.125, 0.375, 0.625, 0.875]))
