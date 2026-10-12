# Battery dispatch

A three-layer revenue model for an energy-only, five-minute NEM battery. It
measures how much of a battery's theoretical arbitrage revenue survives when
dispatch has to be decided from a forecast, and whether planning for
uncertainty recovers any of it:

| Layer | What it knows | How it dispatches |
|---|---|---|
| **1. Perfect-foresight bound** | every realised price in the period | the whole period as one LP; no feasible dispatch can beat it |
| **2. Point forecast** | a price forecast published before each decision | re-solves hourly on a 24-hour forecast and bids the next hour |
| **3. Stochastic** | the same, plus the forecaster's own past errors | re-solves hourly over 10 forecast-error scenarios and bids a shared next hour |

Layers 2 and 3 run on three forecasters: persistence, a 7-day same-time
median, and **AEMO's own published forecasts** — P5MIN for the next hour and
pre-dispatch up to four hours ahead, each used only once AEMO had published
it. They bid the way a NEM battery does: each five-minute interval of the
next hour is offered in ten price bands around the value the plan puts on
stored energy, spread by the forecaster's recent errors, and the bands clear
against the realised price. Every decision is made from forecasts alone.

Beside layer 1 sits the **perfect-forecast policy**: the layer-2 engine fed the
realised prices. It is the best achievable dispatch at the same hourly cadence,
so the gap from it to layer 2 is the cost of the forecast alone.

The reference asset is a **hypothetical** 100 MW / 200 MWh battery at the
Hornsdale 275 kV connection point in SA1; it is not a model of the actual
Hornsdale Power Reserve. Both reference months, every layer and every audit
gate run in about 80 seconds on a laptop and are re-run by CI on every push.

For a meter-side dispatch trace, cash revenue is

```text
sum(dt * RRP * (generation_MLF * discharge - load_MLF * charge))
- degradation_cost_per_discharged_MWh * discharged_MWh
```

The asset has 87% round-trip efficiency, split symmetrically between charge and
discharge, a 5%–95% SOC envelope and a A$25/MWh degradation cost. Every layer
starts at minimum SOC so unpriced opening inventory is not counted as arbitrage
revenue, and every layer is settled at realised prices by the same settlement
function.

## Reference result

Share of the perfect-foresight bound, SA1, degradation A$25/MWh:

| Layer | Nov 2022 (extreme) | Apr 2023 (typical) |
|---|---:|---:|
| 1. Perfect-foresight bound | A$3,609,086 = 100% | A$1,715,918 = 100% |
| Perfect-forecast policy, hourly | 99.99% | 100.0% |
| 2. Persistence | 30.0% | 40.3% |
| 2. 7-day median profile | 35.5% | 49.3% |
| 2. **AEMO forecasts** | **60.9%** | 51.4% |
| 3. Stochastic, around the profile | 33.3% | 44.6% |
| 3. **Stochastic, around AEMO** | 55.5% | **54.3%** |

What it shows:

- **The forecast is almost the whole gap.** Hourly re-solving on a 24-hour
  look-ahead costs A$230 in November and nothing in April when prices are
  known. Everything below that is the price of not knowing them.
- **AEMO's forecasts are worth most where prices are wildest.** In November
  they keep 61% of the maximum against 36% for the naive profile, almost all
  of the difference earned by selling into the month's 11 intervals above
  A$5,000. In April, whose prices a 7-day median already tracks, the gain is
  two points.
- **Pre-dispatch is only good for a few hours.** Its error a day ahead is
  larger than the naive profile's, so it is used four hours out and the
  profile beyond — a cutoff read from these same two months.
- **Layer 3 adds value once its error history is good.** Around AEMO in
  April it is the best forecast layer, A$51k above layer 2. In November it
  is A$193k below, largely because AEMO's archive is missing October 2022,
  leaving its error history thin until 22 November. Around the naive profile
  it is A$81k below layer 2 in both months.
- **Bidding is what makes the extreme month work.** Dispatching planned
  quantities at whatever price clears instead, the naive forecasts lose money
  in November by charging through price spikes; bids decline them. Ten price
  bands and a single price limit are level overall, and committed quantities
  do best in the calm month. See
  [RESULTS.md](docs/RESULTS.md#execution-bands-one-limit-or-committed-quantities).

Every decision solved to optimality, every layer sits below its bound, and all
physical, exclusivity and settlement gates passed. Prices and AEMO forecasts
for every input month are checked against committed checksums in
[`data/manifests/`](data/manifests/) before any result is computed. Full
detail is in [`docs/RESULTS.md`](docs/RESULTS.md).

## Scope

The model includes wholesale-energy arbitrage only. FCAS, caps, contracts,
network support, compensation, availability outages, strategic bidding and
market impact are excluded: the battery's offers are price-taking limits at
the plan's value of stored energy, and never move the price. FCAS is therefore exactly 0% of **modelled**
revenue, not an estimate of its share for a real battery.

Two months are not a distribution. November 2022 was chosen as an extreme and
April 2023 as a typical month of the same financial year; neither result should
be annualised.

AEMO's forecasts are fetched directly from the MMSDM archive on NEMWeb.
NEMSEER, the usual client, pins `xarray` below what linopy requires. The
archive has no every-run pre-dispatch file for October 2022; how that is
handled is set out in [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md#aemo-forecast-contract).

The complete list of modelling limitations is
[`docs/RESULTS.md#limitations`](docs/RESULTS.md#limitations). It is maintained
in one place; this section is a summary, not the full set.

No ramp constraint is imposed because a grid battery can reverse within a
five-minute interval. A binary mode prevents simultaneous charging and
discharging in every implemented interval, including at negative prices. A
non-settled A$0.0001/MWh throughput tie-breaker selects the least-cycling
schedule among economically equivalent optima.

## Reproduce

Install and run the offline gates:

```powershell
uv sync --extra dev
uv run pytest --basetemp .test-tmp
uv run python scripts/run_fixture.py
uv run python scripts/run_mutation_checks.py
```

Verify the reference inputs, then run the three-layer comparison:

```powershell
uv run python scripts/verify_reference.py
uv run python scripts/run_layers.py
```

This writes `analysis/layers.csv`, `analysis/layer_gaps.csv` and one interval
trace per layer and month under `analysis/layer_traces/`, including each
interval's planned quantities, offer limits, band spread and error-pool size.
`--execution bid` offers one price limit per direction, `--execution
committed` dispatches the planned quantities at any price, `--no-error-cap`
leaves past errors uncapped and `--aemo-predispatch-hours` moves the
pre-dispatch cutoff (0 for its whole horizon). The optional perfect-foresight endpoint and degradation grid on November 2022 is
`scripts/run_reference_sensitivities.py`; CI does not run it.

Run a single perfect-foresight rolling dispatch over any other period through
the CLI:

```powershell
uv run battery-dispatch `
  --start "2022-11-01 00:00" `
  --end "2022-12-01 00:00" `
  --region SA1 `
  --connection-point "Hornsdale 275 kV" `
  --loss-factor-file config/loss_factors.csv `
  --degradation-cost 25
```

The price downloader calls NEMOSIS, and the forecast downloader NEMWeb, only
for missing monthly partitions. Inputs fail closed on gaps, duplicates, intervention rows, unknown
dated price caps or incomplete MLF provenance.

## Repository map

```text
config/               reference asset MLF schedule
data/manifests/       committed input identity and quality evidence
docs/                 data contract, validation and results
src/data.py           NEMOSIS download, partition cache, ingest checks
src/mlf.py            provenance-preserving annual MLF ingestion
src/battery.py        SOC physics and feasibility checks
src/settlement.py     authoritative loss-adjusted settlement calculation
src/ceiling.py        layer 1: whole-period perfect-foresight bound
src/aemo_forecasts.py AEMO pre-dispatch and P5MIN archive ingest and cache
src/forecast.py       forecasters, and the error pool behind scenarios and bands
src/mpc.py            forecast-driven rolling dispatch on a direct HiGHS model
src/layers.py         runs, settles and audits every layer for one period
src/optimiser.py      linopy/HiGHS per-window MILP and exclusivity reduction
src/horizon.py        perfect-foresight rolling-horizon policy (CLI, sensitivities)
src/metrics.py        run summary and durable output
src/validation.py     independent run and cycle audits
src/sensitivity.py    optional endpoint/degradation scenarios
scripts/              input verification, layer comparison, fixture, mutations
tests/                hand-worked, invariant and contract tests
```

Detailed contracts and evidence are in
[`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) and
[`docs/VALIDATION.md`](docs/VALIDATION.md).
