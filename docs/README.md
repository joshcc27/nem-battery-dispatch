# Documents

Read them in this order.

| Document | What it is |
|---|---|
| [RESEARCH_NOTE.md](RESEARCH_NOTE.md) | **The study.** Question, data, timing, models, protocol, test results, mechanisms, the scenario-tree extension and the limitations that bound the conclusion. |
| [PROTOCOL.md](PROTOCOL.md) | The evaluation protocol: periods, decision rule, validation selection rule and frozen configuration, committed before validation and frozen before the test. |
| [LIMITATIONS.md](LIMITATIONS.md) | The complete list of modelling limitations. |
| [VALIDATION.md](VALIDATION.md) | Every runtime gate, the tests behind each model and the fifteen mutation checks. |
| [DATA_CONTRACT.md](DATA_CONTRACT.md) | Input, coverage, loss-factor and output contracts. |
| [DEVELOPMENT_RESULTS.md](DEVELOPMENT_RESULTS.md) | The two development months (November 2022, April 2023) under the original per-month comparison, including the execution and perfect-foresight sensitivities. |
| [BASELINE.md](BASELINE.md) | The reproduced starting point at commit `d0f7fc7`, before any model change. |
| [planning/](planning/) | The completion plans this study was built from, with each item's status. |

`PROTOCOL.md` is pinned by hash in `config/studies/test.toml`, so it is never
edited. It names files by their paths at the commit that froze it (`e723026`):
`src/bidding.py` is now `src/battery_dispatch/dispatch/bidding.py`,
`src/study.py` is `src/battery_dispatch/study/`, and the `scripts/` it names
are `battery-dispatch` subcommands. `BASELINE.md` is a historical record in
the same way.
