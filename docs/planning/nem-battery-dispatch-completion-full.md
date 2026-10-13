# NEM battery dispatch — completion plan

Prepared 13 October 2026 for a quantitative research/trading showcase. Reviewed GitHub commit: `d0f7fc7f49724b517d755c09f4e4a735ef8ef951` in [joshcc27/nem-battery-dispatch](https://github.com/joshcc27/nem-battery-dispatch).

The intended finished project answers: **How much energy-arbitrage value survives imperfect forecasts, and when does modeling forecast uncertainty improve the realized dispatch outcome?**

Completion means a defensible answer, supported by reproducible experiments and an explicit execution model. Stochastic planning does not have to win. A well-supported account of when it fails is a useful result.

This document is a proposed checklist. Its suggested additions have not been implemented or run. Revised the same day after a review of the local checkout and the code.

**Status, 13 October 2026 (branch `study-completion`):** every item below is implemented and run except the two marked open in their notes. The answer is in `docs/RESEARCH_NOTE.md`.

## Existing foundation

The current GitHub code already has deterministic and stochastic rolling policies, persistence/profile/AEMO forecasters, publication-time filtering, forecast-error bootstrap, three execution variants, physical and settlement audits, a relaxed perfect-foresight ceiling, mutation checks, and CI that regenerates two reference months. Preserve this foundation.

The local `battery_dispatch` clone is already at `d0f7fc7`, matching `main` on the renamed repository, with a clean working tree apart from this plan. Two things are stale: its remote still points at the old `joshcc27/battery_dispatch` URL, and its `.venv` editable install maps the package to `C:\Users\JoshuaCox\battery_dispatch\src`, an earlier location, so it does not import this checkout's code.

## 1. Establish a reproducible working baseline

- [x] Update the remote to `joshcc27/nem-battery-dispatch` and, if wanted, rename the local folder to match. Done: remote now points at `joshcc27/nem-battery-dispatch`. The local folder was not renamed; that is left to you, since it would move the working directory under open tools.
- [x] Recreate `.venv` from `uv.lock` and verify the installed package resolves into this checkout. Done: the old `.venv` was moved aside and recreated with `uv sync --frozen`; `battery_dispatch` resolves to this checkout's `src/`.
- [x] Run the existing lint, test, deterministic-fixture, and mutation gates. Done 13 October 2026 at `d0f7fc7` in a fresh environment built from `uv.lock` (outside `.venv`): ruff clean, 89 tests passed, fixture passed, all 8 mutation checks detected.
- [x] Verify the reference inputs and reproduce November 2022 and April 2023 with the existing configuration. Not yet run locally; it needs NEMWeb access and the ~250 MB input cache. Done: the stale cache was moved aside, all four manifests verified from a fresh download, and every reference figure reproduced to the dollar.
- [x] Record the baseline commit, environment, inputs, and regenerated summaries before changing the model. Done: `docs/BASELINE.md` and `results/baseline/`.

Existing documented checks, from the synchronized checkout after the environment is recreated:

```powershell
uv sync --frozen --extra dev
uv run ruff check src tests scripts
uv run pytest --basetemp .test-tmp
uv run python scripts/run_fixture.py
uv run python scripts/run_mutation_checks.py
uv run python scripts/verify_reference.py
uv run python scripts/run_layers.py
```

**Acceptance:** the current reference experiment can be reproduced on a fresh checkout; failures have been resolved or explained by source/input changes. The offline gates have passed locally; the reference reproduction has not yet been run.

## 2. Build the study runner and freeze the evaluation protocol

`scripts/run_layers.py` currently accepts only the two hardcoded reference months. The existing `battery-dispatch` CLI runs the older perfect-foresight rolling policy; it is not a general runner for the three-layer forecast comparison.

- [x] Add a configurable study entry point for the three-layer comparison: evaluation boundaries, warm-up boundaries, region, asset/loss-factor schedule, forecast choices, scenario settings, execution model, random seeds, and output directory. Done: `src/study.py`, `scripts/run_study.py`, `config/studies/*.toml`.
- [x] Save the resolved configuration, source commit, input checksums, dependency/environment information, and audit status with every result. Put results under a run-specific identifier so different settings do not overwrite each other. Done: every run writes `runs/<name>-<config hash>/manifest.json` with the configuration, commit and tree state, environment, input checksums, audits and failures.
- [x] Define development, validation, and untouched test periods before evaluating the final policy. Treat the existing two months as development/reference cases, since the four-hour pre-dispatch cutoff and execution choices were inspected on them. Done: `docs/PROTOCOL.md` section 2.
- [x] Name the periods up front. A working proposal: development = FY2022-23 (already inspected); validation = a few months of FY2023-24; test = twelve consecutive later months, fixed once the coverage check below is done. Done, with one deviation: validation is Dec 2022 – Feb 2023 (FY2022-23 months no earlier choice looked at) because twelve consecutive test months wholly before the June 2024 rule change, in the archive format the ingest reads, had to be June 2023 – May 2024.
- [x] Target twelve consecutive untouched months for final evaluation, after checking forecast archive and asset/loss-factor coverage. Record coverage-based exclusions before seeing policy revenue. Do not silently skip difficult months or replace missing forecasts with hindsight data. Done: coverage for Nov 2022 – May 2024 recorded in `data/coverage/` before any policy ran; no month excluded.
- [x] Choose the test period and the bidding rules together. AEMO's integrating-energy-storage rule change (bidirectional units, commencing around June 2024; verify the date and Hornsdale's registration) may mean a battery submits one offer spanning charge and discharge, leaving fewer than ten bands per direction. Prefer a test period that sits wholly on one side of that change. Done: test June 2023 – May 2024, wholly before IESS (3 June 2024; existing batteries moved to bidirectional units from mid-July 2024). AEMO's May 2024 fact sheet also keeps 10 bands per side for a bidirectional unit, adding a no-overlap check.
- [x] Add dated, sourced loss factors for the chosen study years. The current CSV covers only FY2022-23; price-cap entries for later years do not supply the missing asset loss factors. Done: FY2023-24 HPRG1 0.9653 / HPRL1 0.9682 from AEMO's MLF report p.34.
- [x] Freeze the forecast cutoff, error-pool construction, clipping/winsorization, horizon, decision cadence, bid construction, and chosen seed set before the final evaluation. Online updating may use already available observations according to this frozen rule. Done: `docs/PROTOCOL.md` section 7; `config/studies/test.toml` pins its hash.
- [x] Carry SOC continuously through the evaluation period. Report calendar-month outcomes from that trace rather than resetting inventory at each reporting boundary. Done.
- [x] Use the same initial inventory, closing-inventory convention, degradation, loss factors, and evaluation boundaries for all policies and their hindsight benchmark. Compute a whole-period ceiling for the continuous study; monthly slices of its trace are not independent monthly upper bounds. Done: one whole-period ceiling; monthly slices labelled as not monthly bounds.

**Acceptance:** one declared configuration runs every policy on the same continuous period and produces complete, identifiable outputs. No policy tuning uses the final test outcomes.

## 3. Make the execution model appropriate for the project's claims

The current policy reprices its bid bands every hour. This is an idealized price-taking execution rule. The repository acknowledges that NEM band prices are fixed for a trading day while quantities can be rebid.

For the strongest finished NEM showcase:

- [x] Add an execution variant that fixes daily band prices using information available by the relevant bid deadline and updates quantities using information available at subsequent decisions. Done: `fixed_bands` in `src/bidding.py` and `src/mpc.py`.
- [x] Specify the fixed-band policy before coding it; this is a design decision, not only an execution change. Today band prices are re-derived each hour from the plan's stored-energy value (`lam`). With fixed prices the policy needs two written rules: (a) how ten band prices are chosen by the deadline, up to ~40 hours before the last interval they apply to, for example quantiles of a day-ahead distribution of `lam` or price; and (b) how each hourly re-plan is mapped to quantities in those fixed bands. Keep both rules simple and causal. Done: rules (a) and (b) in the `src/bidding.py` docstring. Rule (a) gained a ladder of three outer bands after the April 2023 development month showed spikes being withheld; recorded there, before any validation run.
- [x] If the test period falls under single-offer bidirectional units, apply the band budget that regime actually allows. Not applicable: the test period is before the change (see above).
- [x] Respect the trading-day boundary and use the rules applicable to the historical evaluation period. AEMO's current timetable defines a trading day as 04:00–04:00 AEST and closes band-price changes at 12:30 on the preceding day; verify the historical convention before applying it to archived periods. Done: 04:00–04:00 trading day, 12:30 deadline, verified for the period and tested at the boundaries.
- [x] Keep the existing hourly-repriced execution as a labeled comparison. Quantify how its extra flexibility affects revenue instead of describing it as a full NEM bidding simulation. Done: `bands` runs beside `fixed_bands`; its value is quantified per policy.
- [x] Continue to describe clearing against historical prices as a price-taking approximation. Fixed bands alone do not model the dispatch engine, network constraints, or market impact. Done.
- [x] Specify what happens when planned power is not cleared, inventory hits its limits, forecasts are missing, or the solve fails. A fail-fast study is acceptable if failed cases are reported; a fallback, if implemented, must be causal and explicit. Done: `docs/PROTOCOL.md` section 4; failures are recorded per task and fail the run. A third solver step (fresh HiGHS instance) was added after one warm-start 'Unknown'.
- [x] Extend the existing validation for the new submission schedule: future prices and later forecast publications cannot change an already submitted offer. Realized prices may legitimately affect clearing after submission. Done: `tests/test_bidding.py` (later prices and later AEMO runs cannot change a submitted band price) plus a mutation check.
- [x] Add a decision-latency sensitivity. A decision at time `t` currently uses the price of the interval ending at `t` and AEMO runs published by `t`, with zero delay. Re-run with data cut off at `t − 5` and `t − 15` minutes. Done: 5 and 15 minutes in validation, 15 minutes on the test.

**Acceptance:** the headline execution rule is explicit and uses only information available at submission. Tests cover its new day/deadline boundaries and physical behavior.

Source: [AEMO Spot Market Operations Timetable](https://aemo.com.au/-/media/files/stakeholder_consultation/consultations/nem-consultations/2023/reliability-forecasting-guidelines-and-methodology-consultation/final/spot-market-operations-timetable.pdf?la=en), pages 3 and 5. This is a current reference; historical evaluation must use the appropriate period's rules.

## 4. Run a controlled comparison and explain the outcome

- [x] Include no-operation, persistence, seven-day-profile, AEMO-point-forecast, stochastic-profile, and stochastic-AEMO policies, together with the relaxed ceiling and rolling oracle benchmark. Done.
- [x] Add a simple rule-based baseline, such as charging in the `k` cheapest forecast hours of each day and discharging in the `k` dearest, under the same execution. No-operation alone does not show what the optimization adds. Done: `rule_profile`, `rule_aemo`.
- [x] Predeclare the statistical test and the decision rule before the test run. Twelve monthly paired differences have little power, and November 2022's result came mostly from 11 intervals. Use paired differences by week or trading day with a block bootstrap; blocks must be long enough to respect the dependence that continuous SOC creates. State in advance what counts as a stochastic win, a loss, or an inconclusive result. Done: trading-day paired differences, 7-day circular block bootstrap, win/loss/inconclusive by the 95% interval (`src/stats.py`, protocol section 5).
- [x] Report the headline comparison with and without the top-N price intervals, so a result carried by a handful of spikes is visible. Done: N = 24 and 120.
- [x] Compare deterministic and stochastic policies under identical asset, execution, forecast inputs, and inventory conventions. Done.
- [x] Report period and monthly net energy-arbitrage revenue, energy revenue versus degradation, cycling, closing SOC, loss-making inventory segments, forecast coverage/error, solver gaps/failures, and runtime. The three central figures and the paired-difference table are the core; the rest can sit in an appendix. Report share of the ceiling where that ratio is meaningful; do not make a ratio the headline when its denominator is near zero. Done: `results/test/`.
- [x] Report paired deterministic/stochastic revenue differences across months and across a predeclared set of scenario-sampling seeds. Seed variability measures sampling variability; it is not a confidence interval for future market revenue. Done: five seeds, reported separately from the bootstrap interval.
- [x] Attribute outcomes to charging/discharging decisions, spike capture, negative-price periods, and inventory constraints. Forecast MAE alone does not establish economic value. Done: discharge revenue, charge cost, spike and negative-price revenue, SOC-limited intervals, top-N splits and a case day.
- [x] Test the archive-gap explanation with a controlled comparison. For example, deliberately thin a well-covered error history and compare the same dates/policy. The two reference months alone do not isolate error-pool quality from different market conditions. Done: thinning April 2023's error history did not lower revenue, so the explanation is not supported.
- [x] Use development/validation data for a small sensitivity study: degradation at A$10/25/50 per discharged MWh, forecast reach, horizon, capped versus uncapped errors, and scenario-pool/sampling choices. Freeze the selected policy before its final test. Done: thirteen validation runs; the mechanical selection rule adopted nothing.

Keep sensitivities focused. The current bootstrap limits scenario count to pool length; a larger scenario count requires a correspondingly larger declared pool. Do not create a huge parameter sweep solely to find a winning configuration.

**Acceptance:** the report answers whether uncertainty modeling helps, how stable that result is, and which observed mechanisms explain wins or losses. An unfavorable stochastic result remains valid evidence.

## 5. Complete one focused research extension

Recommended extension: **measure the effect of assuming that future scenario paths become known after the first committed hour.**

The current stochastic formulation shares first-hour decisions, then lets future actions differ freely across each scenario. This is a two-stage approximation with optimistic future information. It is distinct from leaking actual future market observations into the live first-hour decision.

- [x] First bracket the effect cheaply. `ScenarioDispatchModel` shares decisions across scenarios only for the executed hour. Add a parameter `k` that shares decisions over the first `k` intervals while still executing one hour, and run `k` = 1, 4 and 24 hours. `k` = 1 hour is the current, optimistic two-stage model; `k` = 24 hours is a single non-adaptive plan, which is pessimistic. If both give similar realized revenue, the scenario-tree work below matters less. Done: `shared_minutes`; k = 1, 4, 24 h on both development months.
- [x] Implement a small scenario-tree reference or another explicitly constrained future policy in which decisions remain shared while scenarios have the same observed history. Done: `src/scenario_tree.py` with history-based labels.
- [x] Verify it on hand-worked cases. Include a case where future paths diverge only later: decisions before that divergence must remain identical. Done: `tests/test_scenario_tree.py` plus a mutation check.
- [x] Compare its first-hour choices, predicted objective, realized revenue, and runtime with the current approximation on controlled cases and preselected market windows. Done: `results/extension/`.
- [x] Publish the tradeoff: does the approximation distort inventory value, does reducing that optimism improve realized decisions, and what does it cost computationally? Done: research note, extension section.

**Acceptance:** a bounded experiment establishes the effect of a modeling assumption. A full-year, large multistage solver is not necessary to answer this extension's question.

For a first portfolio release, the documented two-stage model and the preceding evaluation are sufficient. This extension is the additional work I would prioritize for the project's strongest finished research version.

## 6. Finish claims, presentation, and release artifacts

- [x] Remove the remaining “lower bound on real battery revenue” sentence from `docs/RESULTS.md`. Omitted income streams do not establish that bound when other assumptions can inflate modeled income. Done.
- [x] Call the relaxed LP a ceiling under the stated model; it may allow simultaneous charging/discharging and need not be attainable by a physical policy. Done.
- [x] Call the rolling perfect-forecast policy an oracle benchmark. A finite rolling horizon does not prove it is the globally best policy at that cadence, even when it nearly reaches the ceiling on the two reference cases. Done.
- [x] Describe `L3 − L2` as realized stochastic-policy uplift under the shared experiment. Avoid implying that one period's realized difference proves a general expected-value advantage. Done.
- [x] Rename the output columns too, not only the prose. `layer_gaps()` in `src/layers.py` writes `value_of_stochastic_solution_*` and `value_of_perfect_information_*`. In stochastic programming VSS and EVPI are expected values computed under the model's own distribution (RP − EEV and WS − RP); these columns are realized out-of-sample differences. Use names such as `realized_stochastic_uplift_*` and `gap_bound_to_l3_*`, and update `docs/RESULTS.md` to match. Done: `realized_stochastic_uplift_*`, `gap_ceiling_to_l3_*`, `oracle_gap_to_ceiling`.
- [x] Present causal explanations as hypotheses until controlled comparisons support them. Keep energy-only scope, price-taking assumptions, forecast gaps, and inventory conventions visible. Done.
- [x] Publish three central figures: monthly policy revenue/uplift; gap to the hindsight ceiling; and one dispatch/SOC case that explains an important success or failure. Done: `results/test/fig1–3`.
- [x] Produce a short research note covering question, data, timing, models, experiment protocol, results, and limitations. Make tables and figures regenerable by one documented reporting command. Done: `docs/RESEARCH_NOTE.md`; `scripts/make_report.py` regenerates every table and figure.
- [x] Keep quick offline checks and the existing reference regression in CI. Make the full holdout study reproducible through a manual/release workflow or documented command, retaining its output artifacts. Done: `ci.yml` unchanged in scope; `.github/workflows/study.yml` runs the holdout study on demand.
- [ ] Update the README title, GitHub description, topics, repository links, and install/run instructions. Publish a tagged version with a results manifest and download-ready figures/tables. README, install and run instructions, and version 1.0.0 done; a local tag `v1.0.0` is created. Not done: the GitHub description, topics and pushing the branch and tag, which publish outside this machine and are left for you.

**Acceptance:** someone can inspect the main result quickly, reproduce it from the declared version, and understand the limits of the conclusion.

## Recommended implementation order

1. Restore the current baseline locally: fix the remote and `.venv`, then reproduce the reference months (the offline gates already pass).
2. Add the configurable study runner, result identity, and data-coverage report; choose the test period with the bidding regime in view.
3. Write down the fixed-band policy rules, then implement and test daily fixed-band execution; use existing reference cases during development.
4. Run the cheap `k`-sharing bracket from section 5 on development data, since it may change the policy or the extension.
5. Complete the small validation/sensitivity study, including latency, add the rule-based baseline, predeclare the statistical test, and freeze the final protocol.
6. Run the untouched continuous evaluation and generate the report.
7. Complete the bounded scenario-information experiment if the bracket shows it matters, then prepare the final release.

If the extension changes the selected policy after seeing final-test results, retain the first evaluation as a completed experiment and obtain a new untouched period for the changed policy's performance claim.

## Finish line

The project is complete as a strong résumé showcase when it has a reproducible baseline, a configurable and auditable study runner, an explicit causal execution model, a frozen untouched evaluation, a supported research conclusion, and a readable tagged release. The bounded scenario-information experiment strengthens the final research contribution.

FCAS co-optimization, a neural forecast model, detailed battery aging, a live trading service, multiple regions, and a dashboard are possible future projects. They are not requirements for completing this energy-arbitrage study.

Repository evidence: [README](https://github.com/joshcc27/nem-battery-dispatch/blob/d0f7fc7f49724b517d755c09f4e4a735ef8ef951/README.md), [study script](https://github.com/joshcc27/nem-battery-dispatch/blob/d0f7fc7f49724b517d755c09f4e4a735ef8ef951/scripts/run_layers.py), [results and limitations](https://github.com/joshcc27/nem-battery-dispatch/blob/d0f7fc7f49724b517d755c09f4e4a735ef8ef951/docs/RESULTS.md), [validation](https://github.com/joshcc27/nem-battery-dispatch/blob/d0f7fc7f49724b517d755c09f4e4a735ef8ef951/docs/VALIDATION.md), [loss-factor schedule](https://github.com/joshcc27/nem-battery-dispatch/blob/d0f7fc7f49724b517d755c09f4e4a735ef8ef951/config/loss_factors.csv).
