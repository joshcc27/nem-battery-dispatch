"""The ``battery-dispatch`` command line.

Each subcommand is one module in :mod:`battery_dispatch.commands` with a
``main(argv)`` function; this only routes to it, so ``battery-dispatch study
--help`` shows that command's own options.
"""

from __future__ import annotations

import importlib
import sys

# Subcommand: (module, one-line summary), in the order a study is run.
COMMANDS: dict[str, tuple[str, str]] = {
    "coverage": ("coverage", "check a candidate period's input coverage before any run"),
    "study": ("study", "run a declared study (config/studies/*.toml)"),
    "experiments": ("experiments", "run a named suite: development, validation or extension"),
    "tree-decisions": ("tree_decisions", "two-stage against tree from identical states"),
    "report": ("report", "regenerate a study's tables and figures from its run"),
    "summarise": ("summarise", "summarise a suite and apply the validation selection rule"),
    "verify-inputs": ("verify_inputs", "re-derive a published result's input checksums"),
    "verify-reference": ("verify_reference", "check the reference months against manifests"),
    "reference": ("reference", "the per-month layer comparison on the reference months"),
    "backtest": ("backtest", "one perfect-foresight rolling backtest over any period"),
}


def usage() -> str:
    width = max(len(name) for name in COMMANDS)
    lines = [
        "usage: battery-dispatch <command> [options]",
        "",
        "How much NEM battery arbitrage survives imperfect forecasts.",
        "",
        "commands:",
        *(f"  {name:<{width}}  {summary}" for name, (_, summary) in COMMANDS.items()),
        "",
        "Run 'battery-dispatch <command> --help' for a command's options.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(usage())
        return
    name, rest = argv[0], argv[1:]
    if name not in COMMANDS:
        print(usage(), file=sys.stderr)
        raise SystemExit(f"\nUnknown command: {name}")
    module = importlib.import_module(f"battery_dispatch.commands.{COMMANDS[name][0]}")
    module.main(rest)


if __name__ == "__main__":
    main()
