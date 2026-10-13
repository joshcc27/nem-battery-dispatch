# Validation and acceptance gates

The reference run is accepted only if both input and dispatch audits pass.
Failures raise an exception before output is written.

## Runtime gates

- exact expected interval count, unique keys, no gaps or extra timestamps;
- dated RRP floor/cap checks and non-intervention filtering;
- every rolling window reports solver status `ok` and termination `optimal`;
- every window's relative MIP gap is at most `1.01e-6`;
- aggregate and interval-by-interval SOC identities within `1e-6` MWh;
- charge/discharge exclusivity, power limits and SOC bounds;
- independently recomputed settlement components;
- no completed charged-inventory segment discharged below its loss-adjusted
  acquisition and degradation cost;
- the result does not exceed the full-period perfect-foresight ceiling by more
  than A$1 plus 1e-6 of the ceiling.

## Perfect-foresight ceiling

`src/battery_dispatch/dispatch/ceiling.py` solves the entire period as one LP: same asset, prices, dated
loss factors, starting SOC and terminal valuation, but no rolling horizon, no
exclusivity binary and no throughput tie-breaker. Every rolling dispatch is a
feasible point of that LP, so the LP optimum bounds it from above, and the
reported `horizon_gap_aud` is a proven upper limit on what better look-ahead
could add. The LP has no binaries, so a full financial year solves in about 15
seconds. A run above the ceiling beyond solver tolerance fails the audit,
because it can only mean the two formulations disagree.

Adding exclusivity binaries lazily — only where the ceiling LP actually charges
and discharges at once — was tried and rejected. It reproduced the same revenue
with far fewer binaries (26 against 468 at A$25/MWh) but was slower: at A$10/MWh
the November grid took 1,027s one interval at a time and 343s adding whole
negative-price blocks, against 145s for the dominance mask. Fewer binaries gave
the branch-and-bound a harder search, not an easier one.

## Forecast-driven layers

Layers 2 and 3 and the perfect-forecast policy (`src/battery_dispatch/dispatch/rolling.py`) are audited by
the same functions as the perfect-foresight run, with one deliberate
difference:

- **Every layer must stay below the ceiling.** Every forecast-driven
  dispatch is a feasible point of the ceiling LP, so the ceiling gate applies
  unchanged.
- **Physics, exclusivity, solver status and MIP gap are gated unchanged.** Only
  the committed hour of each decision is implemented, so only it carries
  exclusivity binaries; the uncommitted look-ahead is relaxed, which affects
  what the policy plans but never what it does.
- **Loss-making cycles are reported, not gated.** A dispatch made on a wrong
  forecast can legitimately discharge below its purchase cost, so
  `assert_audit_passes(require_cycle_break_even=False)` still demands the key
  but does not fail on it. The oracle keeps the hard gate under every execution
  that reproduces its plan. Under fixed daily bands it is reported instead:
  a band price fixed the day before can make even a perfect plan trade at a
  band rather than at its own limit.

The policies are protected against reading the future by construction and by
test. Forecasters receive only the array of prices settled before the decision.
`tests/test_mpc.py` changes every price after a cut-off and asserts that all
dispatch before it is identical, and the layer-3 bootstrap only draws error
days whose whole horizon had settled.

Bid execution is checked the same way. The offer limits come from the dual of
each committed interval's energy balance. HiGHS returns no duals for a MIP, so
on a decision with exclusivity binaries they are fixed at their optimum and
the LP re-solved; only true binaries are fixed, because a mode the dominance
test left continuous may legitimately be fractional, and fixing it cost
A$15.50 on a test case before that was caught. `tests/test_mpc.py` pins the
dual's sign on a hand-worked case (sell at A$200 now with A$100 next best, so a
stored MWh is worth exactly A$100), checks declined spikes, planned quantities
at the limit, full power beyond it, SOC headroom and the exclusivity mode at
deeply negative prices, and asserts that bidding a perfect forecast executes
the plan exactly on prices that make binaries bind. On the reference data the
perfect-forecast policy reproduces A$3,608,856.15 under bids as well. The first
version of the rule missed one interval there, at −A$207 with the plan idle in
charge mode, where both directions clear; carrying the plan's mode into
execution fixed it.

### AEMO forecasts, error pools and bands

- **Publication time, not run time.** A forecaster sees an AEMO run only once
  its last row was published (`LASTCHANGED`). The 00:05 P5MIN run is published
  at about 00:00:27, so a decision at 00:00 uses the 00:00 run.
  `tests/test_aemo_forecasts.py` asserts that a run published one minute after
  the decision is ignored, that P5MIN takes precedence over pre-dispatch, that
  5-minute intervals map to the 30-minute pre-dispatch period ending at or
  after them, and that a run older than its maximum age falls back to the
  profile rather than being used stale.
- **Archive gaps are not filled with another forecaster's errors.** The error
  pool for layer 3 and for the bid bands re-runs the same forecaster at past
  decisions. Where the AEMO forecaster had no current pre-dispatch run (October
  2022), that lag is left out; a thin pool is resampled with replacement and an
  empty one gives the point forecast and a single price limit. Every decision
  records `error_pool_days` and `band_spread_aud` in the trace.
- **Capped errors.** Past errors are winsorized at the pool's 5th and 95th
  percentiles before they become scenarios or band spreads; a test pins the
  cap to the quantile.
- **Bands collapse to the plan under a perfect forecast.** A perfect forecast
  has no errors, so its ten bands sit at one limit and execution equals the
  plan; `tests/test_mpc.py` asserts this on prices that make binaries bind,
  pins band quantities on a hand-worked four-band case, and checks that the
  spread comes from errors at the committed hour's lead times only.
- **Solver retry.** After an extreme price scenario the warm-started basis can
  leave HiGHS without a verdict ("Unknown"). Every solve retries once from a
  cold start and fails on a second non-optimal result; the uncapped-error run
  hit this once before the retry was added.

The direct HiGHS model is built once per shape and only re-priced between
decisions, which takes each solve from about 0.2s in linopy to about 0.01s.
It is a second builder of the same MILP, so `tests/test_mpc.py` asserts that it
reproduces `solve_window`'s objective and binary count on random prices, that
identical scenarios reduce it to the deterministic model, and a hand-worked
case where the shared committed hour hedges between two scenarios. As an
end-to-end check, the perfect-forecast policy reproduces the 48-hour/daily
rolling headline of A$3,608,856.15 to the cent.

### Fixed daily bands

The headline execution fixes ten band prices per direction for each 04:00
trading day at 12:30 the day before. Every hour it may only move quantity
between those prices (`src/battery_dispatch/dispatch/bidding.py`, rules (a) and (b)).
`tests/test_bidding.py` checks the following:

- **Trading day.** The interval ending 04:00 belongs to the previous trading
  day and the one ending 04:05 to the new one. Each day's bands are designed
  exactly at its deadline.
- **Band design.** Band prices are strictly increasing inside the market
  bounds. The laddered outer bands reach the price cap and the floor.
- **Snapping.** A tranche moves to a band no worse than the price it wanted,
  or is withheld, and a withheld tranche never clears.
- **Later prices.** Changing every price after one deadline leaves every band
  designed by then, and every dispatch up to it, unchanged.
- **Later forecasts.** Changing every AEMO run published after one deadline
  leaves every band designed by then unchanged. Changing them does change
  later bands, so the test is not vacuous.
- **Clearing.** Under a perfect forecast, energy is only sold at or above the
  day's lowest discharge band and only bought at or below its highest charge
  band.

### Decision latency, thinned error history and the scenario tree

- **Latency.** `LaggedForecaster` runs the forecaster from the history as it
  stood `lag` intervals before the decision. A test pins that a P5MIN run
  published inside the lag is ignored.
- **Thinned error history.** `ThinnedErrorHistory` drops error-pool lags
  before a chosen decision and changes nothing else.
- **Scenario tree.** The scenario model accepts a decision label per scenario
  and interval. Its tests check:
  - two-stage labels reproduce the default model exactly;
  - a hand-worked case shows that paths diverging late keep their early
    decisions shared, and plan a lower value than the two-stage model;
  - bundling yields a tree that shares a decision exactly when the observed
    histories are equal.

### Solver retry

A warm-started HiGHS instance can report "Unknown" after an extreme price
scenario. Every solve first retries from a cold start. If the same instance
still reports "Unknown", a fresh instance is built from the identical model and
solved once more; only a third failure fails the decision. The third step was
added after one development run reported "Unknown" at the optimal objective on
an all-continuous decision, which the fresh instance solved to optimality. A
regression test drives a stub instance that never succeeds through the
fallback.

### Study runs

`src/battery_dispatch/study/` runs every task of a declared study, settles and audits each,
and records each audit in the run manifest.

- **Failures.** A failed solve or failed audit fails that task. It is listed
  in the manifest with its traceback, and the run exits non-zero; nothing
  falls back to another policy.
- **Test stage.** A test-stage study refuses to run unless the source tree is
  clean and `docs/PROTOCOL.md` matches the SHA-256 the study pins.
- **Input checks.** `battery-dispatch verify-inputs` re-derives every input month's
  checksums from a published manifest.

A gate whose audit key is absent is treated as a **missing check, not a passing
one**. `assert_audit_passes` asserts every required key is present before
evaluating any of them, so a caller that forgets to merge one of the audit
functions fails loudly instead of silently skipping its gates.

The optimizer includes a non-settled A$0.0001/MWh throughput tie-breaker. This
is a numerical secondary preference that removes economically indifferent
cycling and zero-cost MIP branches; all reported revenue is recomputed without
it by the authoritative settlement function.

For the November 2022 SA1 reference month, 8,640 intervals and 30 daily
committed windows passed in every perfect-foresight scenario.

## Exclusivity is tested in MW, not MW²

The gate on simultaneous charge and discharge tests
`min(charge_mw, discharge_mw)` against a tolerance scaled by the power rating,
`power_mw * 1e-6`, where `1e-6` is the HiGHS integrality tolerance.

An earlier version tested the product `charge_mw * discharge_mw` against a fixed
`1e-6`. That quantity has units of MW², so its sensitivity scaled with the
*square* of the power rating: the same solver slack that passed comfortably on
the 1 MW assets used throughout the test suite failed on the 100 MW reference
asset, a factor of 10,000. The A$10/MWh scenario duly failed on a window where
charge was 100 MW and discharge was 7.5e-8 MW — a hundredth of a microwatt of
integrality residue, not dispatch. Testing `min()` in MW is dimensionally
correct and means the same thing at any asset size.

The lesson generalises: a tolerance on a derived quantity must be checked
against the units and scale of the assets it will actually see, not only the
ones in the tests.

## Solver tolerance and where exclusivity binds

The model forbids simultaneous charge and discharge. Take any solution with
both charge `c` and discharge `d` positive in one interval and shift it by `-a`
on charge and `-a*eta_c*eta_d` on discharge: the stored-energy change, and so
the entire SOC path, is unchanged. The objective moves by
`-a * (A_c + A_d * eta_c * eta_d)` for settled per-MW coefficients
`A_c = -dt * L * p` and `A_d = dt * (G * p - deg)`. Simultaneous operation
therefore only pays when

    p < -deg * eta_c * eta_d / (L - G * eta_c * eta_d)

that is, only at prices below a multiple of the degradation cost. With the
FY2022-23 Hornsdale factors (G 0.9652, L 0.9681, round trip 0.87) the multiple
is 6.776, so the binary genuinely binds only below `-6.776 * deg`. Measured
against the SA1 November 2022 prices by
[`scripts/analyse_exclusivity_binding.py`](../scripts/analyse_exclusivity_binding.py):

| Degradation cost | Binary binds when | Intervals | Share | Days affected | Worst day |
|---|---:|---:|---:|---:|---:|
| A$0/MWh | p < A$0.00 | 3,287 | 38.04% | 28 / 30 | 288 of 288 |
| A$25/MWh | p < A$-169.42 | 234 | 2.71% | 13 / 30 | 48 of 288 |
| A$50/MWh | p < A$-338.85 | 85 | 0.98% | 12 / 30 | 23 of 288 |

### Eliminating the binaries that cannot bind

The threshold is used, not merely reported. Read the condition the other way
round: wherever `p > -6.776 * deg`, simultaneous operation is *strictly
dominated*, so every optimal solution already has `min(c, d) = 0` and the binary
is redundant rather than merely slack. The argument is purely local, because the
perturbation leaves the entire SOC path unchanged, so no global quantity such as
the shadow value of stored energy can rescue a locally dominated burn.

`exclusivity_binding_mask` in `src/battery_dispatch/dispatch/optimiser.py` therefore evaluates the
bracket `A_c + eta_rt * A_d` per interval and creates a binary only where it is
non-negative. The bracket is evaluated directly rather than through the
rearranged price threshold, so dated loss factors and an adverse sign of
`L - G * eta_rt` are both handled without special cases. In the reference month
this leaves 468 binaries of a possible 17,280 at the headline A$25/MWh cost, and
13 of 30 windows solve as pure LPs whose gap is exactly zero rather than merely
small. Runs report `pure_lp_window_count` and `total_exclusivity_binary_count`
so a reported zero gap is attributable to an LP window instead of an unexplained
claim of exactness.

This is an exact reformulation, and `tests/test_exclusivity_reduction.py`
asserts that the reduced model reproduces the full-binary dispatch, objective
and SOC path. `scripts/run_mutation_checks.py` additionally verifies that a mask
which drops binaries it should have kept turns the exclusivity tests red.

### Why A$0/MWh is out of scope

At A$0/MWh the threshold collapses to `p < 0`. The model is then paid to burn
energy through round-trip losses, so it wants simultaneous operation at every
negative price, and in November 2022 that is 38% of intervals across 28 of 30
days. On 18 and 20 November every one of the 288 intervals is negative-priced,
and the many equivalent charge/discharge interleavings across a whole day leave
a large symmetric search tree that the reduction cannot touch. This is inherent
to the formulation, not a solver defect.

The measured cost of approaching that regime is steep. Solve time scales sharply
with the number of surviving binaries in a window:

| Binaries in window | Solve time |
|---:|---:|
| 2 | 0.17s |
| 74 | 1.64s |
| 154 | 23.8s |
| 284 | 88.1s |

Model construction is flat at about 0.17s across all of these, so the cost is
branch-and-bound, not model building. A$10/MWh already carries 1,988 binaries
across the month and takes ten times longer than the headline case; A$0/MWh
carries an order of magnitude more again and is not tractable at a strict gap.

Rather than declare a looser tolerance for one scenario and then have to defend
it, the zero-degradation case is excluded and the reasoning recorded here.
A$10/MWh serves as the low-degradation bound. Every reported scenario is solved
at a strict `1e-6` relative gap with no time limit and no fallback.

## Automated tests

`pytest` covers hand-worked settlement, loss-factor economics, SOC physics,
rolling-window carry-forward, timestamp boundaries, cache behavior, MLF input
validation, audit-gate completeness, sensitivity behavior, the forecasters and
error bootstrap, the direct HiGHS model, look-ahead leakage and an end-to-end
run of every layer. The deterministic
CI fixture exercises fetch-independent optimization, settlement, metrics and
audits end to end.

`scripts/run_mutation_checks.py` deliberately introduces fifteen high-risk
errors, and each must make its targeted test fail:

- loss-factor removal;
- charge-efficiency removal;
- binary relaxation;
- dropping binaries that can bind;
- skipping the audit-completeness assertion;
- disabling the ceiling gate;
- settlement sign reversal;
- degradation sign reversal;
- wrong intervention selection;
- wrong interval-ending convention;
- SOC reset;
- committing the look-ahead tail;
- designing a day's bands an hour after its deadline;
- snapping a tranche below its wanted price;
- letting the scenario tree see the not-yet-observed block.

CI runs two jobs. The offline job runs tests with coverage, byte-compiles
source/tests/scripts, executes the deterministic fixture and runs all mutation
checks. The reference job downloads real AEMO data, verifies it against the
committed manifest checksums with `battery-dispatch verify-reference` — both
reference months and both warm-up months — and re-runs the three-layer
comparison with `battery-dispatch reference`. Because that takes about 80 seconds,
the published result is continuously verified rather than quoted from a run
nobody can afford to repeat.
