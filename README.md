# NEM battery dispatch: how much arbitrage survives imperfect forecasts?

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
[RESULTS.md#limitations](docs/RESULTS.md#limitations).

## Reproduce

Install and run the offline gates. These are lint, 115 tests, a deterministic
fixture, and fifteen mutation checks, each of which must turn a test red:

```powershell
uv sync --frozen --extra dev --extra report
uv run ruff check src tests scripts
uv run pytest --basetemp .test-tmp
uv run python scripts/run_fixture.py
uv run python scripts/run_mutation_checks.py
```

Re-run the holdout study and regenerate its tables and figures. It takes
about 25 minutes on 7 worker processes and downloads about 1 GB from NEMWeb
the first time:

```powershell
uv run python scripts/check_coverage.py --first 2023-05 --last 2024-05
uv run python scripts/run_study.py config/studies/test.toml --jobs 7
uv run python scripts/make_report.py runs/<run-id> --out results/test
uv run python scripts/verify_inputs.py results/test/report_manifest.json
```

The runner refuses a test-stage study unless the source tree is clean and
the protocol matches the hash the study pins. Each run writes
`runs/<name>-<config hash>/`, which holds:

- the resolved configuration;
- the source commit;
- the environment;
- every input month's checksum;
- every task's audit;
- the traces.

The development, validation and scenario-tree suites are
`scripts/run_experiments.py <suite>` followed by
`scripts/summarise_suite.py <suite>`. The two development reference months,
which CI re-runs on every push, are `scripts/verify_reference.py` followed by
`scripts/run_layers.py`. The GitHub workflow `study.yml` runs the full study
on demand.

## Repository map

```text
config/loss_factors.csv  dated, sourced MLFs for the connection point
config/studies/          declared studies: development, validation, test
data/manifests/          committed identity of the reference input months
data/coverage/           input coverage, checked before any policy was run
docs/RESEARCH_NOTE.md    the study: question, method, results, limitations
docs/PROTOCOL.md         periods, decision rule and frozen configuration
docs/RESULTS.md          development reference months and full limitations
docs/VALIDATION.md       gates, tests and mutation checks
docs/DATA_CONTRACT.md    input, coverage and output contracts
docs/BASELINE.md         the reproduced starting point
results/                 committed tables, figures and manifests per suite
src/study.py             declared study runner, provenance and slicing
src/bidding.py           NEM timetable, fixed daily bands, offer execution, rule baseline
src/mpc.py               forecast-driven rolling dispatch on a direct HiGHS model
src/scenario_tree.py     scenario-tree bundling and non-anticipative labels
src/forecast.py          forecasters, latency and error-pool wrappers, error bootstrap
src/aemo_forecasts.py    AEMO pre-dispatch and P5MIN archive ingest
src/ceiling.py           whole-period LP ceiling
src/stats.py             paired block-bootstrap comparison and decision rule
src/report.py            tables and figures from a run
src/coverage.py          per-month input coverage
src/settlement.py        the one settlement function
src/validation.py        physical, settlement and ceiling audits
src/data.py, src/mlf.py  price and loss-factor ingest
src/layers.py            the per-month comparison behind the reference months
scripts/                 coverage, studies, suites, reports, verification, mutations
tests/                   hand-worked, invariant, causality and contract tests
```
