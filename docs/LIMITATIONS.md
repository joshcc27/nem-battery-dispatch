# Limitations

This is the complete list of modelling limitations, for the holdout study and
the development months alike. Everything else in this repository that mentions
scope or caveats points here rather than repeating a partial version.

## Scope of revenue

- **Energy arbitrage only.** FCAS, caps, contracts, network support,
  compensation and availability outages are excluded. FCAS is therefore exactly
  0% of *modelled* revenue, not an estimate of its share for a real battery.
- **Not comparable to published battery revenue.** Leaving out income streams
  does not make these figures a lower bound on a real battery's earnings,
  because other assumptions inflate modelled income. The battery is a price
  taker with no market impact, and it executes against realised prices.

## Market behaviour

- **No market impact.** Revenue is settled at the regional reference price
  with dated marginal loss factors. The battery is a price taker, which
  overstates achievable revenue for an asset of this size in a region this
  small. Spikes are where the effect matters most, and they are where both
  forecast-driven policies earn most.
- **No dispatch engine.** Offers clear against historical regional prices.
  Neither the dispatch engine nor network constraints are modelled.
- **Simple, non-strategic offers.** Under the headline execution, band prices
  are fixed for each trading day at 12:30 the day before, and quantities are
  rebid hourly. A real battery can rebid every five minutes. There is no
  strategic withholding.
- **Perfect-foresight schedules.** The ceiling and the backtest choose their
  dispatch directly rather than offering it.

## Forecast-driven policies

- **One band design.** The fixed-band rules in
  `src/battery_dispatch/dispatch/bidding.py` are one simple causal design: seven
  quantile bands and a ladder of three towards the market bounds. A trader
  with better band design and five-minute rebids would do better, perhaps by
  different amounts for each policy. Even the oracle loses 17% of the ceiling
  to fixed band prices. Hourly re-pricing (`bands`) is a labelled idealisation,
  not a NEM-feasible bid.
- **Unsold closing inventory.** A declined discharge late in the period can
  leave energy stored at the end. It is valued at zero, exactly as in the
  ceiling.
- **Forecasters.** Persistence and a 7-day same-time median use nothing but
  the settled price series. The AEMO forecaster uses P5MIN and pre-dispatch as
  published. Its four-hour pre-dispatch cutoff was chosen on the development
  months and frozen before the test.
- **October 2022 archive gap.** AEMO's archive has no every-run pre-dispatch
  file for October 2022. In the November 2022 development month, the AEMO
  forecaster falls back to the profile for the first four hours. Its error
  pool, which supplies layer 3's scenarios and the bands' spread, is empty on
  1 November and full only from 22 November; see
  [DATA_CONTRACT.md](DATA_CONTRACT.md#aemo-forecast-contract). The test and
  validation periods are fully covered.
- **Anticipative scenario tails.** In layer 3 only the committed hour is shared
  across scenarios. After it, each scenario is solved as if its own future
  were known. On the same scenario paths this makes the model expect 2–4% more
  than a scenario tree does. The effect on realised revenue is small and of
  mixed sign; see the extension in [RESEARCH_NOTE.md](RESEARCH_NOTE.md).
- **Ten scenarios from 21 past days.** The scenario set is small, its errors
  are conditioned on nothing but time of day, and they are capped at their 5th
  and 95th percentiles. A conditional error model could change the stochastic
  result.
- **Look-ahead cut at the period end.** Each look-ahead stops at the end of the
  evaluated period, as the ceiling does, so no policy holds energy for prices
  beyond it.

## Period

- **One year in one region.** The test covers June 2023 – May 2024 in SA1.
  Its verdict and bootstrap interval describe day-to-day variation within that
  year. They are not a confidence interval for future revenue, and they say
  nothing direct about other regions or years.
- **Development months are not a distribution.** November 2022 was chosen as
  an extreme month and April 2023 as a typical one. No per-MW-year figure is
  quoted from them.
- **One degradation cost.** Every policy runs at A$25/MWh. A$10 and A$50 were
  run as validation sensitivities. A zero-degradation case is out of scope for
  tractability; see [VALIDATION.md](VALIDATION.md#why-a0mwh-is-out-of-scope).

## Asset

- **Flat degradation.** Degradation is a flat per-MWh charge, not a
  state-of-health model. It does not depend on depth of discharge,
  temperature, rate or age.
- **No ramp constraint.** A grid battery can reverse within a five-minute
  interval.
- **Hypothetical asset.** It is not the Hornsdale Power Reserve; only the
  connection point and its published loss factors are real.
