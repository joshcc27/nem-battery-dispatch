# Results

Every file here is regenerated from a run directory by a committed command.
Each folder's `manifest.json` or `report_manifest.json` records the run
identifiers, the source commits and the SHA-256 of every file written. The
run directories themselves (`runs/`, with interval traces) are not committed;
re-running the command that made them reproduces them.

| Folder | What | Made by |
|---|---|---|
| [`test/`](test/tables.md) | **The holdout test**, June 2023 – May 2024: every policy, both executions, five seeds. Tables, paired comparisons and the three central figures. | `scripts/run_study.py config/studies/test.toml`, then `scripts/make_report.py` |
| [`test-latency15/`](test-latency15/tables.md) | The test's declared sensitivity: AEMO policies with a 15-minute decision delay | the same, with `--set latency_minutes=15` |
| [`validation/`](validation/summary.md) | Thirteen validation runs and the mechanical selection rule; nothing was adopted | `scripts/run_experiments.py validation`, then `scripts/summarise_suite.py validation` |
| [`development/`](development/summary.md) | Both reference months under every policy, the `k`-sharing bracket and the thinned-error-history control | `... development` |
| [`extension/`](extension/summary.md) | Two-stage against scenario tree on identical bundled paths, and controlled single decisions | `... extension` and `scripts/run_tree_decisions.py` |
| [`baseline/`](baseline/) | The reference layers as reproduced at the starting commit `d0f7fc7` | `scripts/run_layers.py` |

The figures are 160-dpi PNGs; the tables are CSV, with a markdown copy in
each `tables.md` or `summary.md`.
