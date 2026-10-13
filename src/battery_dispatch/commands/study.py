"""Run a declared study: every policy on one continuous period.

    uv run battery-dispatch study config/studies/validation.toml --jobs 6
    uv run battery-dispatch study config/studies/validation.toml \\
        --name val-deg10 --set deg_cost=10 --set policies='["L2_aemo","L3_aemo"]'

``--set key=value`` overrides a top-level study key or a ``[settings]`` key;
the value is read as TOML, so strings need quotes. Every distinct resolved
configuration gets its own ``artifacts/runs/<name>-<hash>/`` directory. The command exits
non-zero if any task failed its solve or its audit.
"""

from __future__ import annotations

import argparse
import json
import logging
import tomllib
from pathlib import Path

from battery_dispatch.study.runner import run_study
from battery_dispatch.study.spec import load_study


def parse_override(text: str) -> tuple[str, object]:
    key, _, value = text.partition("=")
    if not key or not _:
        raise argparse.ArgumentTypeError(f"--set expects key=value, got {text!r}")
    return key.strip(), tomllib.loads(f"v = {value}")["v"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="battery-dispatch study",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("study", type=Path)
    parser.add_argument("--set", dest="overrides", action="append", type=parse_override,
                        default=[])
    parser.add_argument("--name", help="Override the study name (the run-id prefix)")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/runs"))
    args = parser.parse_args(argv)
    logging.getLogger("linopy").setLevel(logging.WARNING)
    overrides = dict(args.overrides)
    if args.name:
        overrides["name"] = args.name
    for key in ("policies", "executions", "seeds"):
        if key in overrides:
            overrides[key] = tuple(overrides[key])
    config = load_study(args.study, **overrides)
    directory = run_study(config, cache=args.cache, output=args.output, jobs=args.jobs)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["failures"]:
        raise SystemExit(f"{len(manifest['failures'])} task(s) failed; see {directory}")


if __name__ == "__main__":
    main()
