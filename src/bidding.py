"""Offers, their execution against realised prices, and the NEM bidding timetable.

An offer for one five-minute interval is ``K`` equal tranches of ``P/K`` MW in
each direction. Each tranche carries the value of stored energy at which it
stops paying: a charge tranche worth ``v`` buys while
``eta_c*v - tb - L*p > 0`` and a discharge tranche worth ``v`` sells while
``G*p - deg - tb - v/eta_d > 0``. A tranche that is not offered has value NaN.
The same value can be read as a limit on the realised regional price ``p``,
which is how a band price is stated here: band prices are referred to the
regional reference node, so a band clears exactly when the regional price
crosses it.

Three ways of building the tranches are compared. ``bid`` offers the whole
power rating at the plan's own value of stored energy. ``bands`` spreads the
ten tranches by the forecaster's recent errors and re-prices them every hour,
which a NEM participant cannot do. ``fixed_bands`` fixes ten band prices per
direction for each trading day at the day-ahead deadline and, every hour, only
moves quantity between those fixed prices, which is what NEM rebidding allows.

The fixed-band rules, written down before they were coded:

(a) **Band prices.** At the bid deadline for trading day ``D`` the policy
    plans from the deadline to the end of ``D`` with the information
    available then, exactly as at an hourly decision but over the longer
    horizon. The plan's value of stored energy ``lam_t`` for every interval of
    ``D``, shifted by the same error offsets the hourly offers use, gives the
    limit price each tranche would want, in each direction. Seven of the ten
    band prices per direction are the quantiles of those wanted limits at the
    midpoints of seven equal-probability bins. The other three are a ladder
    from the outermost of those towards the market bound, at 5%, 25% and 100%
    of the distance: up to the price cap for discharge, down to the floor for
    charge. All are made strictly increasing.

    The first version used ten quantile bands and no ladder. On the April 2023
    development month that withheld every tranche whose hourly limit rose
    above the day's highest quantile, which is exactly when a spike is
    forecast, and AEMO's point-forecast policy earned A$315k from intervals
    above A$300/MWh against A$566k with hourly re-pricing. A real battery bid
    keeps its outer bands near the market bounds for this reason; the ladder
    was added before any validation or test period was run.
(b) **Hourly quantities.** At each hourly decision the policy computes the
    tranches it would offer with free prices, then moves each into a fixed
    band without ever trading at a worse price than it wanted: a discharge
    tranche goes into the cheapest band at or above its wanted limit and a
    charge tranche into the dearest band at or below it. A tranche with no
    such band is not offered. Quantities are therefore set from information
    at the hourly decision, prices from information at the deadline.

Both rules use only information published before the decision they belong
to, and ``tests/test_bidding.py`` checks that changing later prices or later
forecast runs cannot change a submitted band price.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import AEST, MARKET_FLOOR_PRICE, BatteryConfig

# The NEM trading day runs 04:00 to 04:00 AEST, and daily bids, which fix the
# day's ten price bands, close at 12:30 AEST the day before. Both conventions
# applied unchanged through the study period (Oct 2021 to May 2024): five-minute
# settlement kept the 04:00 trading day, and storage bid as separate generating
# and load units, each with ten bands, until the bidirectional-unit transition
# that began after 3 June 2024. See docs/PROTOCOL.md.
TRADING_DAY_START = pd.Timedelta(hours=4)
# Rule (a): bands set from the day's wanted limits, and a ladder of the rest
# towards the market bound at these fractions of the distance.
CORE_BANDS = 7
LADDER_FRACTIONS = (0.05, 0.25, 1.0)
BID_DEADLINE = pd.Timedelta(hours=12, minutes=30)
BAND_PRICE_STEP = 0.01


@dataclass(frozen=True)
class Timetable:
    """Trading days and daily-bid deadlines on an interval-ending grid."""

    trading_day_start: pd.Timedelta = TRADING_DAY_START
    bid_deadline: pd.Timedelta = BID_DEADLINE

    def trading_day(self, interval_end: pd.Series | pd.DatetimeIndex) -> pd.DatetimeIndex:
        """The trading day (its calendar date, as midnight) of each interval end.

        The interval ending 04:00 belongs to the previous trading day and the
        interval ending 04:05 to the new one.
        """
        index = pd.DatetimeIndex(interval_end).tz_convert(AEST)
        start = index - pd.Timedelta(minutes=5)
        return (start - self.trading_day_start).normalize()

    def deadline(self, day: pd.Timestamp) -> pd.Timestamp:
        """When trading day ``day``'s band prices are fixed: 12:30 the day before."""
        return pd.Timestamp(day) - pd.Timedelta(days=1) + self.bid_deadline


NEM_TIMETABLE = Timetable()


def charge_value_from_price(
    price: np.ndarray, load: np.ndarray, asset: BatteryConfig, tie: float
) -> np.ndarray:
    """Stored-energy value of a charge tranche that clears below regional ``price``."""
    return (load * price + tie) / asset.charge_efficiency


def discharge_value_from_price(
    price: np.ndarray, generation: np.ndarray, deg_cost: float, asset: BatteryConfig, tie: float
) -> np.ndarray:
    """Stored-energy value of a discharge tranche that clears above regional ``price``."""
    return asset.discharge_efficiency * (generation * price - deg_cost - tie)


def charge_price_from_value(
    value: np.ndarray, load: np.ndarray, asset: BatteryConfig, tie: float
) -> np.ndarray:
    return (asset.charge_efficiency * value - tie) / load


def discharge_price_from_value(
    value: np.ndarray, generation: np.ndarray, deg_cost: float, asset: BatteryConfig, tie: float
) -> np.ndarray:
    return (value / asset.discharge_efficiency + deg_cost + tie) / generation


@dataclass(frozen=True)
class FixedBands:
    """One trading day's ten band prices per direction, as regional prices."""

    charge: np.ndarray  # increasing; a charge band clears at or below its price
    discharge: np.ndarray  # increasing; a discharge band clears at or above its price
    designed_at: pd.Timestamp


def band_prices(
    wanted: np.ndarray, bands: int, cap: float, *, direction: str | None = None
) -> np.ndarray:
    """Rule (a): quantiles of the wanted limits, then a ladder to the market bound.

    With ``direction`` of ``"discharge"`` (or ``"charge"``) and at least
    ``CORE_BANDS + len(LADDER_FRACTIONS)`` bands, the last (first) bands are
    the ladder towards the price cap (floor). Without it every band is a
    quantile. Prices are clipped to the market bounds and strictly increasing.
    """
    finite = np.asarray(wanted, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return np.full(bands, np.nan)
    ladder = len(LADDER_FRACTIONS) if direction and bands >= CORE_BANDS + 3 else 0
    core = bands - ladder
    prices = np.clip(np.quantile(finite, (np.arange(core) + 0.5) / core), MARKET_FLOOR_PRICE, cap)
    fractions = np.asarray(LADDER_FRACTIONS)
    if ladder and direction == "discharge":
        top = prices[-1]
        prices = np.concatenate([prices, top + (cap - top) * fractions])
    elif ladder and direction == "charge":
        bottom = prices[0]
        prices = np.concatenate(
            [(bottom - (bottom - MARKET_FLOOR_PRICE) * fractions)[::-1], prices]
        )
    elif direction not in (None, "charge", "discharge"):
        raise ValueError("direction must be 'charge' or 'discharge'")
    # NEM band prices must increase; the tiny step separates tied quantiles.
    prices = prices + BAND_PRICE_STEP * np.arange(bands)
    return np.maximum.accumulate(prices)


def snap_charge(wanted: np.ndarray, bands: np.ndarray) -> np.ndarray:
    """Rule (b), charge: the dearest band at or below each wanted limit, else NaN."""
    wanted = np.asarray(wanted, dtype=float)
    out = np.full(wanted.shape, np.nan)
    if not np.isfinite(bands).any():
        return out
    ok = np.isfinite(wanted)
    index = np.searchsorted(bands, wanted[ok], side="right") - 1
    values = np.where(index >= 0, bands[np.clip(index, 0, None)], np.nan)
    out[ok] = values
    return out


def snap_discharge(wanted: np.ndarray, bands: np.ndarray) -> np.ndarray:
    """Rule (b), discharge: the cheapest band at or above each wanted limit, else NaN."""
    wanted = np.asarray(wanted, dtype=float)
    out = np.full(wanted.shape, np.nan)
    if not np.isfinite(bands).any():
        return out
    ok = np.isfinite(wanted)
    index = np.searchsorted(bands, wanted[ok], side="left")
    values = np.where(index < len(bands), bands[np.clip(index, None, len(bands) - 1)], np.nan)
    out[ok] = values
    return out


@dataclass(frozen=True)
class Execution:
    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    # Intervals where the SOC envelope, not the offer, limited what cleared.
    soc_limited: np.ndarray


def execute_tranches(
    realised_rrp: np.ndarray,
    planned_charge_mw: np.ndarray,
    planned_discharge_mw: np.ndarray,
    charge_values: np.ndarray,
    discharge_values: np.ndarray,
    generation_loss_factor: np.ndarray,
    load_loss_factor: np.ndarray,
    soc_initial: float,
    asset: BatteryConfig,
    *,
    planned_mode: np.ndarray | None = None,
    deg_cost: float = 0.0,
    throughput_tie_breaker: float,
    tolerance: float = 1e-6,
) -> Execution:
    """Clear ``(n, K)`` tranche values against realised prices, interval by interval.

    A tranche with a strictly positive margin clears in full, one at its limit
    clears its share of the planned quantity, and a negative or NaN margin does
    not clear. Where some tranche of each direction would clear, the planned
    direction wins, then the plan's exclusivity mode, then the larger margin.
    Quantities are limited to the SOC headroom as the block plays out.
    """
    charge_values = np.atleast_2d(np.asarray(charge_values, dtype=float))
    discharge_values = np.atleast_2d(np.asarray(discharge_values, dtype=float))
    n = len(realised_rrp)
    tranches = charge_values.shape[1]
    tranche_mw = asset.power_mw / tranches
    modes = np.full(n, np.nan) if planned_mode is None else planned_mode
    dt = asset.interval_hours
    eta_c = asset.charge_efficiency
    eta_d = asset.discharge_efficiency
    tie = throughput_tie_breaker
    charge = np.zeros(n)
    discharge = np.zeros(n)
    limited = np.zeros(n, dtype=bool)
    soc = float(soc_initial)
    for i, price in enumerate(realised_rrp):
        cv = charge_values[i]
        dv = discharge_values[i]
        with np.errstate(invalid="ignore"):
            charge_margins = eta_c * cv - tie - load_loss_factor[i] * price
            discharge_margins = generation_loss_factor[i] * price - deg_cost - tie - dv / eta_d
        finite = np.concatenate([cv[np.isfinite(cv)], dv[np.isfinite(dv)]])
        scale = tolerance * max(
            1.0, float(np.abs(finite).max()) if len(finite) else 0.0, abs(price)
        )

        def cleared(margins: np.ndarray, planned: float, scale: float = scale) -> float:
            valid = np.isfinite(margins)
            full = np.count_nonzero(margins[valid] > scale)
            at_limit = np.count_nonzero(np.abs(margins[valid]) <= scale)
            return tranche_mw * full + planned * at_limit / tranches

        def best(margins: np.ndarray) -> float:
            valid = margins[np.isfinite(margins)]
            return float(valid.max()) if len(valid) else -np.inf

        c = cleared(charge_margins, float(planned_charge_mw[i]))
        d = cleared(discharge_margins, float(planned_discharge_mw[i]))
        best_c, best_d = best(charge_margins), best(discharge_margins)
        if best_c >= -scale and best_d >= -scale:
            if planned_discharge_mw[i] > 0:
                c = 0.0
            elif planned_charge_mw[i] > 0:
                d = 0.0
            elif modes[i] == 1.0:
                d = 0.0
            elif modes[i] == 0.0:
                c = 0.0
            elif best_c >= best_d:
                d = 0.0
            else:
                c = 0.0
        c_room = max(0.0, (asset.soc_max_mwh - soc) / (dt * eta_c))
        d_room = max(0.0, (soc - asset.soc_min_mwh) * eta_d / dt)
        limited[i] = c > c_room + 1e-9 or d > d_room + 1e-9
        c = min(c, c_room)
        d = min(d, d_room)
        charge[i] = c
        discharge[i] = d
        soc += dt * (eta_c * c - d / eta_d)
    return Execution(charge, discharge, limited)


def rule_limits(
    forecast: np.ndarray,
    take: int,
    asset: BatteryConfig,
    *,
    hours: int,
    generation: float,
    load: float,
    deg_cost: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The rule-based baseline's plan for the first ``take`` intervals of ``forecast``.

    The forecast is averaged by hour. The ``hours`` cheapest hours of the
    look-ahead are charging hours and the ``hours`` dearest are discharging
    hours, provided a MWh bought at the dearest charging price and sold at the
    cheapest discharging price clears the loss factors, round-trip losses and
    degradation. A charging hour offers the full rating up to that charging
    price, a discharging hour the full rating down to that discharging price,
    and every other hour offers nothing.

    Returns planned charge and discharge (MW) and charge and discharge limit
    prices (NaN where nothing is offered) for the committed intervals.
    """
    per_hour = 60 // asset.interval_minutes
    planned_charge = np.zeros(take)
    planned_discharge = np.zeros(take)
    charge_limit = np.full(take, np.nan)
    discharge_limit = np.full(take, np.nan)
    count = len(forecast) // per_hour
    if count < 2 * hours or hours < 1:
        return planned_charge, planned_discharge, charge_limit, discharge_limit
    hourly = np.asarray(forecast[: count * per_hour], dtype=float).reshape(count, per_hour)
    hourly = hourly.mean(axis=1)
    order = np.argsort(hourly, kind="stable")
    cheap, dear = order[:hours], order[-hours:]
    buy = float(hourly[cheap].max())
    sell = float(hourly[dear].min())
    eta_rt = asset.charge_efficiency * asset.discharge_efficiency
    if (generation * sell - deg_cost) * eta_rt <= load * buy:
        return planned_charge, planned_discharge, charge_limit, discharge_limit
    hour_of = np.arange(take) // per_hour
    is_charge = np.isin(hour_of, cheap)
    is_discharge = np.isin(hour_of, dear)
    planned_charge[is_charge] = asset.power_mw
    planned_discharge[is_discharge] = asset.power_mw
    charge_limit[is_charge] = buy
    discharge_limit[is_discharge] = sell
    return planned_charge, planned_discharge, charge_limit, discharge_limit
