# Evaluation protocol

This file fixes the study design before results that could tempt it to move.
It was committed in two steps. Sections 1 to 6 were written before any
validation run. Section 7 records what validation selected, and was completed
before the test period was run. `config/studies/test.toml` pins this file's
SHA-256. The study runner refuses to run the test if the file has changed
since then, or if the source tree is not clean.

## 1. Question

How much of the perfect-foresight energy-arbitrage value survives imperfect
price forecasts? When does planning for forecast uncertainty improve the
realised dispatch outcome? An unfavourable stochastic result is a valid
answer.

## 2. Periods

All boundaries are 00:00 AEST and physical, `[start, end)`. Prices are
interval-ending, so the evaluated intervals are `(start, end]`.

| Stage | Period | Use |
|---|---|---|
| Development | November 2022 and April 2023, with October 2022 and March 2023 read as warm-up | Every earlier design choice was made by looking at these. They include the 4-hour pre-dispatch cutoff, the band spread and the error cap. The fixed-band rules were also built here. Nothing measured on them is evidence for the final claim. |
| Validation | `[2022-12-01, 2023-03-01)` | The sensitivity study and the selection rule in section 6. |
| Test | `[2023-06-01, 2024-06-01)`, twelve consecutive months | Run once, after section 7 is complete. |

Each stage is one continuous run. SOC is carried through the whole period,
and calendar months are slices of that trace. The warm-up before each period
is read by the forecasters and error pools but never dispatched or settled.
Its length is set by `warm_up_days` in `src/study.py`: 32 days with the
default settings.

**Why this test period.** The completion plan proposed FY2022-23 for
development, a few FY2023-24 months for validation, and twelve later months for
test. The test period was instead chosen together with the bidding rules, as
the plan also requires.

- **Rule change.** AEMO's integrating-energy-storage rule took full effect on
  3 June 2024. Under it a battery can bid as one bidirectional unit, and
  existing batteries moved to that from mid-July 2024 to March 2025.
  AEMO's May 2024 bid-validation fact sheet keeps ten bands per direction for
  such a unit, and adds a check that its effective consumption and generation
  bands do not overlap.
- **Archive format.** The MMSDM archive also changed its file naming and
  layout from August 2024.
- **Choice.** June 2023 to May 2024 sits wholly before both changes. In that
  period a battery bid as separate generating and load units, each with ten
  bands, which is exactly what is modelled. The archive format is also the
  one the ingest already reads.
- **Cost of the choice.** Twelve consecutive months wholly after June 2024
  would need a new archive parser, and the bidirectional unit's no-overlap
  rule.
- **Validation.** Validation therefore uses FY2022-23 months that no earlier
  choice looked at.

**Coverage, checked before any policy was run on these months.**
`scripts/check_coverage.py --first 2022-11 --last 2024-05` wrote
[`data/coverage/sa1_2022-11_2024-05.csv`](../data/coverage/sa1_2022-11_2024-05.csv).
Every month from December 2022 to May 2024 has every price interval. Each also
has a loss factor and a price cap configured, and a current AEMO pre-dispatch
and P5MIN run at 100% of decision times. November 2022 is a warm-up month
only; its first four hours fall back to the profile after the October gap. The
declared exclusion rule is in the `_rule.txt` file beside the CSV. **No month
is excluded**, and no missing forecast is replaced with hindsight data.

## 3. Asset, settlement and inventory

- **Asset.** A hypothetical 100 MW / 200 MWh battery with 87% round-trip
  efficiency and a 5–95% SOC envelope. It sits at the Hornsdale 275 kV
  connection point in SA1. Its dated loss factors are HPRG1/HPRL1 for FY2022-23
  and FY2023-24, from AEMO's MLF reports, page 34 in both.
- **Degradation.** A$25 per discharged MWh.
- **Inventory.** Every policy and the ceiling start at minimum SOC and value
  closing inventory at zero at the end of the period.
- **Ceiling.** The whole period is solved once as an LP with exclusivity
  relaxed. It is a ceiling under the stated model; its monthly slices are not
  monthly upper bounds.
- **Settlement.** Revenue is energy-only, settled at the regional price with
  dated loss factors. The battery is a price taker, and clearing against
  historical prices does not model the dispatch engine, network constraints
  or market impact.

## 4. Policies and execution

| Policy | Forecast | Plan |
|---|---|---|
| `ceiling` | realised | whole-period LP, exclusivity relaxed |
| `oracle` | realised | the rolling engine: an oracle benchmark, not a proven optimum |
| `noop` | — | never trades |
| `rule_profile`, `rule_aemo` | profile, AEMO | charge in the 2 cheapest and discharge in the 2 dearest forecast hours of the next 24, if that clears losses and degradation |
| `L2_persistence`, `L2_profile`, `L2_aemo` | yesterday, 7-day median, AEMO | hourly MILP on the point forecast, 24 h look-ahead |
| `L3_profile`, `L3_aemo` | same | hourly two-stage stochastic MILP over 10 bootstrapped error scenarios |

The AEMO forecaster uses P5MIN, then pre-dispatch up to 4 hours ahead, then
the 7-day profile. Each run is used only once it is published.

**Headline execution: `fixed_bands`** (rules (a) and (b) in `src/bidding.py`).

- **Timetable.** The trading day runs 04:00–04:00 AEST. Each day's ten band
  prices per direction are fixed from information at 12:30 the day before.
  Every hour the policy may only move quantity between those fixed prices.
- **Historical rule.** These are the NEM rules for the whole study period.
  Daily bids close at 12:30 the day before, and rebids change quantities, not
  prices.
- **Comparison.** `bands`, the earlier rule, re-prices the ten bands every
  hour. It is run beside `fixed_bands` as a labelled comparison, to measure
  what that extra flexibility is worth. It is not a NEM-feasible bid.

**Failure handling.**

- **Forecasts.** A missing AEMO run falls back to the profile. This is causal
  and recorded per decision; the error pool skips such decisions rather than
  filling them.
- **Solver.** A solve that fails after one cold-start retry fails its task.
  There is no fallback, the failure is listed in the run manifest, and the run
  exits non-zero.
- **Unfavourable prices.** A planned quantity the realised price does not
  clear is not dispatched.
- **SOC envelope.** Inventory at the envelope cuts the cleared quantity back,
  and those intervals are counted.

## 5. Statistics and decision rule

- **Primary comparison.** `L3_aemo` against `L2_aemo` under `fixed_bands` on
  the test period. `L3_aemo`'s daily revenue is the mean over five predeclared
  scenario seeds: 101, 202, 303, 404 and 505.
- **Unit.** Paired differences in revenue per trading day (04:00–04:00), from
  the continuous traces.
- **Uncertainty.** A circular moving-block bootstrap with 7-day blocks and
  10,000 draws, seed 20240601. It gives a two-sided 95% percentile interval
  for the mean daily difference.
- **Verdict.** **Win** if the interval is above zero, **loss** if it is below
  zero, **inconclusive** otherwise.
- **Spikes.** The same comparison is repeated without the period's 24 and 120
  highest-price intervals, in both policies, so a result carried by a handful
  of spikes is visible.
- **Seeds.** Each seed's own difference is reported. Seed spread is the
  policy's sampling variation, not a confidence interval for future market
  revenue.
- **Secondary comparisons.** These use the same method and are reported as
  descriptive, with no multiplicity claim:
  - `L3_profile` − `L2_profile`;
  - `L2_aemo` − `L2_profile`, the value of AEMO's forecasts;
  - `L2_aemo` − `rule_aemo`, what optimisation adds over a rule;
  - each policy's `bands` − `fixed_bands`, what hourly re-pricing adds.
- **Test sensitivity.** The test also runs `L2_aemo` and `L3_aemo` at
  15-minute decision latency. It is reported and selects nothing.

## 6. Validation sensitivity study and selection rule (written before validation)

The development defaults are a 24-hour horizon, hourly commitment, 4 hours of
pre-dispatch, errors capped at 5%/95%, a 21-day pool with 10 scenarios,
decisions shared for the committed hour only, A$25/MWh degradation and zero
latency. Validation runs these alternatives under `fixed_bands`, each changing
one setting:

| Setting | Alternatives | Kind |
|---|---|---|
| Degradation | A$10, A$50/MWh | scope: reported, never selected |
| Pre-dispatch reach | 1 h, whole horizon | shared by L2 and L3 |
| Horizon | 12 h, 36 h | shared by L2 and L3 |
| Error cap | uncapped | L3 only |
| Error pool | 42 days with 20 scenarios | L3 only |
| Shared decisions (`k`) | 4 h, 24 h | L3 only |
| Latency | 5, 15 min | reported, never selected |

The selection rule:

- **Settings shared by L2 and L3.** An alternative is adopted only if it
  raises both `L2_aemo` and `L3_aemo` validation revenue by at least 1% of the
  validation ceiling.
- **L3-only settings.** An alternative is adopted only if it raises `L3_aemo`
  by at least 1% of the ceiling, averaged over three seeds (101, 202, 303).
- **Conflicts.** At most one alternative per setting is adopted: the one with
  the larger gain. Adopted changes are not re-tuned jointly.
- **Scope.** The degradation and latency rows are reported only. The scenario
  count is limited by the pool length, so a larger count comes with a larger
  declared pool.

## 7. Frozen configuration (completed after validation, before test)

To be completed from the validation results before `config/studies/test.toml`
is written and this file's hash is pinned.
