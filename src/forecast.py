"""Price forecasts and forecast-error scenarios for the forecast-driven layers.

Both work on plain arrays on the regular interval grid. ``history`` is every
price that has settled at the decision time and nothing later, so a forecaster
cannot see the future unless it is handed the future explicitly, which only
:class:`PerfectForecast` is, and it says so in its name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from .aemo_forecasts import ForecastRuns


class Forecaster(Protocol):
    name: str

    def forecast(self, history: np.ndarray, steps: int) -> np.ndarray:
        """Return prices for the ``steps`` intervals after ``history`` ends."""
        ...


@dataclass(frozen=True)
class PerfectForecast:
    """The realised prices: the oracle that turns a forecast policy into layer 1.

    It holds the whole price series, so it checks that the history it is given
    is a prefix of that series; otherwise its position would be meaningless.
    """

    actual: np.ndarray
    name: str = "perfect"

    def forecast(self, history: np.ndarray, steps: int) -> np.ndarray:
        position = len(history)
        if not np.array_equal(history, self.actual[:position]):
            raise ValueError("PerfectForecast history is not a prefix of its actual prices")
        if position + steps > len(self.actual):
            raise ValueError("PerfectForecast cannot see past the end of its actual prices")
        return self.actual[position : position + steps].copy()


@dataclass(frozen=True)
class SameTimeProfile:
    """Median price at the same time of day over the last ``days`` days.

    ``days=1`` is persistence: tomorrow repeats today. The history ends exactly
    at the decision time on a regular grid, so the value ``periods_per_day``
    positions before a target interval is the same time of day.
    """

    days: int
    periods_per_day: int = 288

    def __post_init__(self) -> None:
        if self.days < 1 or self.periods_per_day < 1:
            raise ValueError("days and periods_per_day must be positive")

    @property
    def name(self) -> str:
        return "persistence" if self.days == 1 else f"median_{self.days}d"

    @property
    def min_history(self) -> int:
        return self.days * self.periods_per_day

    def forecast(self, history: np.ndarray, steps: int) -> np.ndarray:
        if len(history) < self.min_history:
            raise ValueError(
                f"{self.name} needs {self.min_history} intervals of history, "
                f"got {len(history)}"
            )
        recent = np.asarray(history[-self.min_history :], dtype=float)
        profile = np.median(recent.reshape(self.days, self.periods_per_day), axis=0)
        return profile[np.arange(steps) % self.periods_per_day]


@dataclass(frozen=True)
class AemoForecast:
    """AEMO's own published forecasts, as they stood at the decision time.

    Each interval takes the latest 5-minute pre-dispatch (P5MIN) run where one
    covers it, otherwise the latest half-hourly pre-dispatch run's price for
    the 30-minute period containing it if that is at most
    ``predispatch_hours`` ahead, otherwise the same-time profile. Only runs
    published at or before the decision count, and a run older than its
    ``max_*_age`` is treated as absent, so a gap in AEMO's archive falls back
    to the profile instead of a stale run.

    ``predispatch_hours`` exists because pre-dispatch is sharp for the next few
    hours and poor a day ahead, where it over-forecasts spikes: in both
    reference months its error beyond about four hours is larger than the
    naive profile's. ``None`` uses pre-dispatch to its end.

    Like :class:`PerfectForecast` it needs to know where on the calendar the
    history ends, so it holds the interval-ending timestamps of the whole grid
    as naive UTC ``datetime64[ns]`` (see :func:`grid_times`).
    """

    timestamps: np.ndarray
    predispatch: ForecastRuns
    p5min: ForecastRuns
    fallback: SameTimeProfile
    max_predispatch_age: np.timedelta64 = np.timedelta64(60, "m")
    max_p5min_age: np.timedelta64 = np.timedelta64(15, "m")
    predispatch_hours: float | None = None

    @property
    def name(self) -> str:
        if self.predispatch_hours is None:
            return "aemo"
        return f"aemo_{self.predispatch_hours:g}h"

    @property
    def min_history(self) -> int:
        return self.fallback.min_history

    def covers(self, position: int) -> bool:
        """Whether a pre-dispatch run was current when ``position`` intervals had settled."""
        decision = self.timestamps[position - 1]
        _, _, published = self.predispatch.latest(decision)
        return bool(not np.isnat(published) and decision - published <= self.max_predispatch_age)

    def forecast(self, history: np.ndarray, steps: int) -> np.ndarray:
        position = len(history)
        targets = self.timestamps[position : position + steps]
        if position < 1 or len(targets) != steps:
            raise ValueError("AemoForecast history does not sit inside its timestamp grid")
        decision = self.timestamps[position - 1]
        values = np.array(self.fallback.forecast(history, steps), dtype=float)
        # A 5-minute interval belongs to the 30-minute period ending at or after it.
        half_hour = np.int64(30 * 60 * 10**9)
        ends = targets.astype("datetime64[ns]").astype(np.int64)
        periods = (-(-ends // half_hour) * half_hour).astype("datetime64[ns]")
        # Targets are in time order, so the ones within reach are a prefix and
        # a slice of ``values`` is a view the overlay writes through.
        reach = steps
        if self.predispatch_hours is not None:
            limit = decision + np.timedelta64(int(round(self.predispatch_hours * 60)), "m")
            reach = int(np.count_nonzero(targets <= limit))
        _overlay(
            values[:reach], self.predispatch, decision, periods[:reach], self.max_predispatch_age
        )
        _overlay(values, self.p5min, decision, targets, self.max_p5min_age)
        return values


def _overlay(
    values: np.ndarray,
    runs: ForecastRuns,
    decision: np.datetime64,
    keys: np.ndarray,
    max_age: np.timedelta64,
) -> None:
    """Replace ``values`` wherever the latest current run forecasts that key."""
    run_targets, run_rrp, published = runs.latest(decision)
    if np.isnat(published) or decision - published > max_age or not len(run_targets):
        return
    index = np.minimum(np.searchsorted(run_targets, keys), len(run_targets) - 1)
    hit = run_targets[index] == keys
    values[hit] = run_rrp[index[hit]]


def grid_times(settlementdate: pd.Series) -> np.ndarray:
    """Interval-ending timestamps as naive UTC ``datetime64[ns]``."""
    index = pd.DatetimeIndex(settlementdate).tz_convert("UTC").tz_localize(None)
    return index.as_unit("ns").to_numpy()


@dataclass(frozen=True)
class ErrorBootstrap:
    """A forecaster's own recent errors: layer-3 scenarios and bid-band spread.

    For each lag of ``k`` days, the same forecaster is re-run from the history
    available ``k`` days earlier, over the same horizon and time of day, and its
    realised error recorded. Every error is fully settled before the decision
    time, so nothing leaks, and a whole error path keeps its intraday shape and
    autocorrelation. A forecaster with a ``covers(position)`` method can say it
    was not really running at a past decision, as the AEMO forecaster does over
    an archive gap; those lags are left out rather than filled with another
    forecaster's errors.

    ``winsorize`` caps every error at the pool's ``[w, 1 - w]`` quantiles, so a
    one-off spike in the pool cannot dominate every scenario it is drawn into.

    Scenario lags are drawn from the pool with a generator seeded by
    ``(seed, decision_index)``, so every run is repeatable: without
    replacement when the pool is large enough, with it when an archive gap has
    thinned it, and as the point forecast alone when it is empty.
    """

    count: int = 10
    pool_days: int = 21
    periods_per_day: int = 288
    seed: int = 0
    winsorize: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.count <= self.pool_days:
            raise ValueError("count must be between 1 and pool_days")
        if self.winsorize is not None and not 0 <= self.winsorize < 0.5:
            raise ValueError("winsorize must be in [0, 0.5)")

    def min_history(self, forecaster: Forecaster, steps: int) -> int:
        """History a decision needs for the oldest lag and its own forecast."""
        first_lag = -(-steps // self.periods_per_day)
        oldest = (first_lag + self.pool_days - 1) * self.periods_per_day
        return oldest + int(getattr(forecaster, "min_history", 0))

    def errors(self, forecaster: Forecaster, history: np.ndarray, steps: int) -> np.ndarray:
        """Realised error paths, one row per covered lag, capped if requested."""
        needed = self.min_history(forecaster, steps)
        if len(history) < needed:
            raise ValueError(
                f"Error bootstrap needs {needed} intervals of history, got {len(history)}"
            )
        # A lag is usable only if its whole horizon had settled by now.
        first_lag = -(-steps // self.periods_per_day)
        covers = getattr(forecaster, "covers", None)
        rows: list[np.ndarray] = []
        for lag in range(first_lag, first_lag + self.pool_days):
            origin = len(history) - lag * self.periods_per_day
            if covers is not None and not covers(origin):
                continue
            realised = history[origin : origin + steps]
            rows.append(realised - forecaster.forecast(history[:origin], steps))
        errors = np.array(rows, dtype=float).reshape(len(rows), steps)
        if self.winsorize and len(errors):
            low, high = np.quantile(errors, [self.winsorize, 1.0 - self.winsorize])
            errors = np.clip(errors, low, high)
        return errors

    def scenarios(self, errors: np.ndarray, base: np.ndarray, decision_index: int) -> np.ndarray:
        """``count`` equiprobable price paths: the forecast plus sampled errors."""
        if not len(errors):
            return np.tile(base, (self.count, 1))
        rng = np.random.default_rng([self.seed, decision_index])
        rows = rng.choice(len(errors), size=self.count, replace=len(errors) < self.count)
        return base + errors[rows]

    def band_offsets(self, errors: np.ndarray, bands: int) -> np.ndarray:
        """Error quantiles at the midpoints of ``bands`` equal-probability bands."""
        if not len(errors):
            return np.zeros(bands)
        return np.quantile(errors, (np.arange(bands) + 0.5) / bands)

    def generate(
        self,
        forecaster: Forecaster,
        history: np.ndarray,
        base: np.ndarray,
        decision_index: int,
    ) -> np.ndarray:
        errors = self.errors(forecaster, history, len(base))
        return self.scenarios(errors, base, decision_index)
