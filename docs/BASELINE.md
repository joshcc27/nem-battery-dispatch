# Baseline reproduction

Recorded 13 October 2026, before any model change, so later results can be
traced back to a reproduced starting point.

## Source and environment

| | |
|---|---|
| Commit | `d0f7fc7f49724b517d755c09f4e4a735ef8ef951` (`main`, matches `joshcc27/nem-battery-dispatch`) |
| Remote | updated from `joshcc27/battery_dispatch` to `joshcc27/nem-battery-dispatch` |
| Environment | `.venv` recreated with `uv sync --frozen --extra dev` from `uv.lock`; the old one, whose editable install pointed at a previous checkout location, was moved aside |
| Python | CPython 3.14.6, Windows 11 (x86-64 under emulation) |
| uv | 0.11.26 |
| Packages | highspy 1.15.1, linopy 0.9.1, numpy 2.5.3, pandas 3.0.6, pyarrow 25.0.1, nemosis 3.8.1 |

The editable install now resolves `battery_dispatch` to this checkout's
`src/`.

## Inputs

The local market-data cache predated the current ingest convention (its
November 2022 price partition had 8,639 rows; the manifest pins 8,640), so it
was moved aside and every input was downloaded afresh from NEMWeb.
`scripts/verify_reference.py` then matched all four committed manifests
(October 2022 to April 2023) on row counts, interval checks, price bounds, the
canonical price checksum and both AEMO forecast tables' checksums, including
the empty October 2022 pre-dispatch partition.

## Gates

| Gate | Result |
|---|---|
| `ruff check src tests scripts` | clean |
| `pytest` | 89 passed |
| `scripts/run_fixture.py` | passed |
| `scripts/run_mutation_checks.py` | all 12 mutations detected |

## Reference reproduction

`scripts/run_layers.py` (123 s on this machine) reproduced every figure in the
README and `docs/RESULTS.md` to the dollar, for example A$3,609,085.78 for the
November 2022 bound, 60.9% of it for `L2_aemo`, and A$932,363.53 for
`L3_aemo` in April 2023. The regenerated `layers.csv` and `layer_gaps.csv` are
kept in [`results/baseline/`](../results/baseline/), with the layer and gap
names as they were at this commit.

After the execution engine was refactored for fixed daily bands, the same
command reproduced every layer's revenue and every interval's dispatch exactly
(zero difference), so the refactor changed no reference result.
