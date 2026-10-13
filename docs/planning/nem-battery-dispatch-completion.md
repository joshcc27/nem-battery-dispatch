# NEM battery dispatch — completion plan

Prepared 13 October 2026 for a small, rigorous quantitative research showcase that is easy to run. Based on commit `d0f7fc7f49724b517d755c09f4e4a735ef8ef951` in [joshcc27/nem-battery-dispatch](https://github.com/joshcc27/nem-battery-dispatch). The earlier, broader version of this plan is kept in `nem-battery-dispatch-completion-full.md`.

## Research question

> **How much of the perfect-foresight arbitrage value survives at each level of price knowledge, and does modelling forecast uncertainty recover any of it?**

The project stays tight: one question, one controlled experiment, one engine, and a full study that runs from one command on a laptop. An unfavourable stochastic result is a valid finding.

## Fixed scope decisions

Stated once in the README and not revisited:

- SA1 only; the hypothetical 100 MW / 200 MWh battery at the Hornsdale 275 kV connection point; wholesale energy only.
- Execution is the current hourly re-priced bands, cleared against realised prices with the battery as a price-taker. It is labelled as idealised execution and is identical for every layer, so gaps between layers are differences in information alone.
- Each month runs independently, with the same opening and closing inventory convention for every policy and for its bound. Months can run in parallel and be cached, and each month's bound is a true upper bound for that month.
- Degradation is A$25/MWh.
- Out of scope: fixed daily band prices, AEMO's 2024 bidirectional-unit rule change, scenario trees, SOC carried across months, FCAS, market impact.

## Knowledge levels compared

| Level | Policy |
| --- | --- |
| Ceiling | Whole-month LP bound (exclusivity relaxed) |
| Perfect knowledge | Rolling oracle: the same engine given realised prices |
| Controlled degradation | Realised price + α × a real past AEMO error path, α ∈ {0.25, 0.5, 0.75, 1} |
| Real forecasts | AEMO (P5MIN + pre-dispatch), 7-day profile, persistence |
| Uncertainty-aware | Stochastic layer around AEMO and around the profile, 5 fixed seeds |
| Floors | Simple rule (charge in the k cheapest forecast hours, discharge in the k dearest), no operation |

The α ladder is a controlled experiment, not a forecaster that could be run live, and is labelled that way. It turns separate results into a curve of revenue captured against forecast quality, which is the headline figure.

## Current state

- The two reference months, every layer and every audit run in about 80 seconds; CI re-runs them on every push; inputs are pinned by checksum.
- Offline gates passed on 13 October 2026 at `d0f7fc7` in a fresh environment built from `uv.lock`: ruff clean, 89 tests, fixture, all 8 mutation checks.
- The local checkout matches GitHub `main`. Its remote still uses the old `joshcc27/battery_dispatch` URL, and `.venv` maps the package to an earlier folder (`C:\Users\JoshuaCox\battery_dispatch\src`).
- Gaps: two months only, an AEMO pre-dispatch cutoff tuned on those same months, no predeclared statistical test, and gap columns named after stochastic-programming quantities they do not compute.

## Phases

### 0. Baseline — small

- [ ] Point the remote at `joshcc27/nem-battery-dispatch`; optionally rename the local folder.
- [ ] Recreate `.venv` with `uv sync --frozen --extra dev` and confirm the package imports from this checkout.
- [ ] Run `verify_reference.py` and `run_layers.py`; confirm November 2022 and April 2023 match `docs/RESULTS.md`.

### 1. Study runner — medium

- [ ] Add `scripts/run_study.py --config study.toml`. The config lists months, layers, settings and seeds.
- [ ] Write each month's output under `results/<config-hash>/<month>/`; skip months already complete; add `--jobs N` for parallel months.
- [ ] Save a manifest with every run: commit, resolved config, input checksums, audit status, runtime.
- [ ] Extend `verify_reference.py` and `data/manifests/` to any listed month, and add a coverage report that runs before any revenue is computed.
- [ ] Make this the single entry point: fold in or retire the older perfect-foresight CLI, `.github/workflows/backtest.yml` and `scripts/run_reference_sensitivities.py`, keeping whatever `src/mpc.py` still uses from `src/optimiser.py`.

### 2. Periods and protocol — small

- [ ] **Development:** November 2022 and April 2023 (already inspected).
- [ ] **Validation:** three or four other FY2022-23 months, avoiding the October 2022 pre-dispatch archive gap and its warm-up effect.
- [ ] **Test:** the twelve months of FY2023-24, untouched. Add sourced FY2023-24 loss factors to `config/loss_factors.csv` and check archive coverage first. Record any exclusions before seeing revenue.
- [ ] Write `docs/PROTOCOL.md` before the test run:
  - frozen settings: pre-dispatch cutoff, error cap, horizon, scenario count, seeds, k;
  - test statistic: daily paired differences with a weekly block bootstrap;
  - decision rule: what counts as a stochastic win, a loss, or inconclusive.

### 3. Model additions — medium

- [ ] Rule-based baseline.
- [ ] α ladder.
- [ ] k-sharing diagnostic for the stochastic layer: share decisions across scenarios over the first k = 1, 4, 24 hours while executing one hour. k = 1 hour is the current, optimistic model; k = 24 hours is a single non-adaptive plan. This tests whether treating each scenario's future as known explains layer 3's losses.
- [ ] Rename `value_of_stochastic_solution_*` and `value_of_perfect_information_*` in `src/layers.py` to `realized_stochastic_uplift_*` and `gap_bound_to_l3_*`, and update the docs.
- [ ] Re-select the AEMO pre-dispatch cutoff on validation months, not development months.
- [ ] Run a small sensitivity set on validation data only (cutoff, error capping, k), then freeze.

### 4. Test run — small

- [ ] Run the frozen configuration once and commit its manifest. No changes afterwards; if the policy changes, the first result stays reported and the new policy needs a new untouched period.

### 5. Write-up — medium

- [ ] Three figures:
  1. Share of the bound against forecast error: the α ladder, with the real forecasters placed on it.
  2. Monthly paired stochastic-minus-point difference with bootstrap intervals, with and without the top-N price intervals.
  3. One dispatch/SOC case explaining a key win or loss.
- [ ] One results table.
- [ ] Rewrite `docs/RESULTS.md` as a short research note: question, data, method, protocol, results, limitations. Move detail to an appendix. Remove the "lower bound on real battery revenue" sentence; call the relaxed LP a ceiling under the stated model and the rolling perfect-forecast policy an oracle benchmark.
- [ ] Add `scripts/make_report.py`, which regenerates every figure and table from `results/`.
- [ ] README: headline figure, a three-line answer, and a one-command reproduce section.

### 6. Release — small

- [ ] CI keeps the offline gates plus the two reference months on every push; a manual workflow runs the full study and uploads `results/`.
- [ ] Tag `v1.0` with the results manifest, figures and tables. Update the GitHub description and topics.

## Size

About 18 months of input (12 test, 4–6 validation and development, plus warm-up): roughly 1 GB downloaded once, then about 10–15 minutes per full study run, less with `--jobs`.

## Done means

Someone can read the README in two minutes, see the curve and the answer, run one command, and get the same tables. Every claim maps to a check that was fixed before the test run.

## Cut or deferred

- Fixed daily band prices: optional later, as one sensitivity row, on a period before June 2024.
- Scenario-tree model: only if the k diagnostic shows a large effect.
- Latency sensitivity, other regions, FCAS, neural forecasting, dashboards.
