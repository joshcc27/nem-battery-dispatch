# NEM battery dispatch: how much arbitrage survives imperfect forecasts?

[![CI](https://github.com/joshcc27/nem-battery-dispatch/actions/workflows/ci.yml/badge.svg)](https://github.com/joshcc27/nem-battery-dispatch/actions/workflows/ci.yml)

A reproducible holdout study of energy arbitrage by a five-minute NEM battery.
It measures how much of the perfect-foresight arbitrage value a battery keeps
when it must dispatch from forecasts and bid under the NEM's rules. It also
asks whether planning for forecast uncertainty improves the realised outcome.

The asset is a **hypothetical** 100 MW / 200 MWh battery at the Hornsdale
275 kV connection point in SA1. It is not a model of the Hornsdale Power
Reserve. Only the connection point and its published loss factors are real.

## Result

Twelve untouched months, June 2023 to May 2024, ran under a protocol frozen
in advance ([PROTOCOL.md](docs/PROTOCOL.md)). Band prices were fixed for each
trading day at 12:30 the day before, as the NEM requires.

| Policy | Net revenue | Share of ceiling |
|---|---:|---:|
| Ceiling: the whole year as one LP | A$26.56M | 100% |
| Oracle: the rolling engine on realised prices | A$22.04M | 83.0% |
| **Stochastic, around AEMO's forecasts** (5-seed mean) | **A$13.47M** | **50.7%** |
| **Point forecast, AEMO** | **A$13.45M** | **50.6%** |
| Point forecast, 7-day profile | A$8.54M | 32.2% |
| Rule: 2 cheapest / 2 dearest forecast hours, AEMO | A$5.86M | 22.1% |

- **Forecast quality is most of the story.** AEMO's published forecasts are
  worth A$4.9M a year over a naive profile.
- **Optimisation is worth A$7.6M a year** over a cheapest/dearest-hours rule
  on the same forecast.
- **Modelling uncertainty did not measurably help.** The stochastic and point
  AEMO policies are level. The predeclared paired test by trading day is
  inconclusive: +A$59 a day, with a 95% interval of −A$2,466 to +A$2,091.
- **Where it gains and loses.** The stochastic policy earns A$309k more in
  ordinary intervals and gives A$287k back in the year's 120 highest-priced
  ones. Without those it wins, by A$876 a day. Around the naive profile it
  loses.
- **The NEM's day-ahead band prices cost every policy.** Re-pricing bands
  hourly, which the NEM does not allow, is worth A$1.6M to the AEMO
  point-forecast policy and A$4.5M even to the oracle.
- **Scenario-tree extension.** Removing the two-stage model's clairvoyance
  about scenario futures lowers its planned value by 2–4%. It changes
  realised revenue by under 2%.

The question, data, timing, models, results, mechanisms and limitations are
in the **[research note](docs/RESEARCH_NOTE.md)**. Every table and figure is
regenerated from its run by one command and is listed, with hashes, in
[`results/`](results/).

![Share of the ceiling by policy and execution](results/test/fig2_share_of_ceiling.png)

## Scope

- **Revenue.** Wholesale energy only: no FCAS, contracts or caps. FCAS is
  therefore 0% of *modelled* revenue, not an estimate of its share for a real
  battery.
- **Price taking.** The battery clears its offers against historical
  regional prices and never moves them. There is no dispatch engine, network
  constraint or market impact.
- **One region and year.** SA1 for one test year. The verdict and its
  interval describe those twelve months, not future revenue.

The complete list of limitations is
[LIMITATIONS.md](docs/LIMITATIONS.md).

## Reproduce

Install and run the offline gates: lint, 116 tests, a deterministic fixture,
and fifteen mutation checks, each of which must turn a test red.

```powershell
uv sync --frozen --extra dev --extra report
uv run ruff check src tests scripts
uv run pytest --basetemp .test-tmp
uv run python scripts/run_fixture.py
uv run python scripts/run_mutation_checks.py
```

Re-run the holdout study and regenerate its tables and figures. It takes
about 25 minutes on 7 worker processes, and the first run downloads about
1 GB from NEMWeb.

```powershell
uv run battery-dispatch coverage --first 2023-05 --last 2024-05
uv run battery-dispatch study config/studies/test.toml --jobs 7
uv run battery-dispatch report artifacts/runs/<run-id> --out results/test
uv run battery-dispatch verify-inputs results/test/report_manifest.json
```

The runner refuses a test-stage study unless the source tree is clean and
the protocol matches the hash the study pins. Each run writes
`artifacts/runs/<name>-<config hash>/`. That folder holds the resolved
configuration, the source commit, the environment, every input month's
checksum, every task's audit and the traces. Everything under `artifacts/` is
regenerable and is not committed.

Every step of the workflow is one subcommand; `uv run battery-dispatch --help`
lists them.

| Command | Does |
|---|---|
| `coverage` | checks a candidate period's inputs before any run |
| `study` | runs a declared study from `config/studies/` |
| `experiments` | runs a suite: `development`, `validation` or `extension` |
| `summarise` | tabulates a suite and applies the validation selection rule |
| `tree-decisions` | compares the two-stage model and the tree from identical states |
| `report` | regenerates a study's tables and figures from its run |
| `verify-inputs` | re-derives a published result's input checksums |
| `verify-reference`, `reference` | the two development months that CI re-runs on every push |
| `backtest` | runs one perfect-foresight rolling backtest over any period |

The GitHub workflow `study.yml` runs the full study on demand.

## Repository map

```text
src/battery_dispatch/
  market/      prices, AEMO forecasts, loss factors, settlement
  dispatch/    forecasters, optimiser, scenario model, rolling policy,
               NEM bidding, scenario tree, ceiling
  audit/       battery physics and the run audits
  study/       study spec, tasks and runner, statistics, reports, coverage
  backtest/    the original perfect-foresight rolling backtest
  commands/    one module per battery-dispatch subcommand
  cli.py       the battery-dispatch entry point
tests/         hand-worked, invariant, causality and contract tests
scripts/       developer checks (fixture, mutations) and legacy analyses
config/        dated MLFs and the declared studies
data/          committed input manifests and coverage reports
docs/          research note, protocol, limitations, validation, contracts
results/       committed tables, figures and manifests per suite
artifacts/     regenerable run outputs (ignored)
```

Start with [docs/README.md](docs/README.md) for a guide to the documents.
