# Results

Every file here is regenerated from a run directory by a committed command.
Each folder's `manifest.json` or `report_manifest.json` records the run
identifiers, the source commits and the SHA-256 of every file written. The
run directories themselves (`artifacts/runs/`, with interval traces) are not committed;
re-running the command that made them reproduces them.

| Folder | What | Made by |
|---|---|---|
| [`test/`](test/tables.md) | **The holdout test**, June 2023 – May 2024: every policy, both executions, five seeds. Tables, paired comparisons and the three central figures. | `battery-dispatch study config/studies/test.toml`, then `battery-dispatch report` |
| [`test/sensitivities/latency15/`](test/sensitivities/latency15/tables.md) | The test's declared sensitivity: AEMO policies with a 15-minute decision delay | the same, with `--set latency_minutes=15` |
| [`validation/`](validation/summary.md) | Thirteen validation runs and the mechanical selection rule; nothing was adopted | `battery-dispatch experiments validation`, then `battery-dispatch summarise validation` |
| [`development/`](development/summary.md) | Both reference months under every policy, the `k`-sharing bracket and the thinned-error-history control | `... development` |
| [`extension/`](extension/summary.md) | Two-stage against scenario tree on identical bundled paths, and controlled single decisions | `... extension` and `battery-dispatch tree-decisions` |
| [`history/baseline/`](history/baseline/) | The reference layers as reproduced at the starting commit `d0f7fc7`, with the layer and gap names of that time | `scripts/run_layers.py` at `d0f7fc7` |

The figures are 160-dpi PNGs; the tables are CSV, with a markdown copy in
each `tables.md` or `summary.md`.
