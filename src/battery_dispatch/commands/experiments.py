"""Run a named suite of declared studies.

    uv run battery-dispatch experiments development --jobs 6
    uv run battery-dispatch experiments validation --jobs 6

Every variant is a study config with overrides, so each has its own run
directory and manifest. ``artifacts/runs/<suite>_index.csv`` maps variant names to run
directories for the reporting scripts.

- ``development``: both reference months under every policy, the ``k``-sharing
  bracket (decisions shared for 1, 4 or 24 hours), and the archive-gap control
  (a well-covered month with its error history deliberately thinned).
- ``validation``: the main validation run and the one-at-a-time sensitivity
  study of docs/PROTOCOL.md section 6.
- ``extension``: the scenario-information experiment of the completion plan's
  section 5, on the validation period and both development months.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from battery_dispatch.study.runner import run_study
from battery_dispatch.study.spec import load_study

AEMO_AND_PROFILE = ("ceiling", "L2_aemo", "L3_aemo", "L2_profile", "L3_profile")
VALIDATION_SEEDS = (101, 202, 303)
DEV_MONTHS = {
    "2022-11": ("2022-11-01 00:00", "2022-12-01 00:00"),
    "2023-04": ("2023-04-01 00:00", "2023-05-01 00:00"),
}


def development() -> list[tuple[str, dict[str, object]]]:
    variants: list[tuple[str, dict[str, object]]] = []
    for month, (start, end) in DEV_MONTHS.items():
        period = {"start": start, "end": end, "seeds": VALIDATION_SEEDS}
        variants.append((f"dev-{month}", {**period}))
        for hours in (4, 24):
            variants.append(
                (
                    f"dev-{month}-k{hours}h",
                    {
                        **period,
                        "policies": ("ceiling", "L3_aemo", "L3_profile"),
                        "shared_minutes": hours * 60,
                    },
                )
            )
    april = {"start": DEV_MONTHS["2023-04"][0], "end": DEV_MONTHS["2023-04"][1]}
    variants.append(
        (
            "dev-2023-04-thin",
            {
                **april,
                "seeds": VALIDATION_SEEDS,
                "policies": ("ceiling", "L2_aemo", "L3_aemo"),
                "thin_error_history": True,
            },
        )
    )
    return variants


def validation() -> list[tuple[str, dict[str, object]]]:
    focused = {
        "policies": AEMO_AND_PROFILE,
        "executions": ("fixed_bands",),
        "seeds": VALIDATION_SEEDS,
    }
    variants: list[tuple[str, dict[str, object]]] = [("val-main", {"seeds": VALIDATION_SEEDS})]
    variants += [
        ("val-deg10", {**focused, "deg_cost": 10.0}),
        ("val-deg50", {**focused, "deg_cost": 50.0}),
        ("val-reach1h", {**focused, "aemo_predispatch_hours": 1.0}),
        # 48 h reaches past every pre-dispatch run: its whole horizon.
        ("val-reachall", {**focused, "aemo_predispatch_hours": 48.0}),
        ("val-horizon12", {**focused, "horizon_hours": 12.0}),
        ("val-horizon36", {**focused, "horizon_hours": 36.0}),
        ("val-uncapped", {**focused, "error_winsorize": 0.0}),
        ("val-pool42", {**focused, "scenario_pool_days": 42, "scenario_count": 20}),
        ("val-k4h", {**focused, "shared_minutes": 240}),
        ("val-k24h", {**focused, "shared_minutes": 1440}),
        ("val-latency5", {**focused, "latency_minutes": 5}),
        ("val-latency15", {**focused, "latency_minutes": 15}),
    ]
    return variants


TREE = "60:2,240:2,720:2"
# Preselected before any tree result was seen: the validation period and both
# development months.
EXTENSION_WINDOWS = {
    "val": ("config/studies/validation.toml", {}),
    "dev-2022-11": (
        "config/studies/development.toml",
        {"start": DEV_MONTHS["2022-11"][0], "end": DEV_MONTHS["2022-11"][1]},
    ),
    "dev-2023-04": (
        "config/studies/development.toml",
        {"start": DEV_MONTHS["2023-04"][0], "end": DEV_MONTHS["2023-04"][1]},
    ),
}


def extension() -> list[tuple[str, dict[str, object]]]:
    """Section 5: how much does the two-stage model's future information matter?

    Every variant uses eight scenarios so a 2-2-2 tree has one path per leaf.
    ``fan`` is the ordinary two-stage model; ``bundled`` is the same model on
    the tree's bundled paths; ``tree`` shares decisions while bundles share
    their history; ``shared`` is one plan for every scenario.
    """
    common = {
        "policies": ("ceiling", "L3_aemo", "L3_profile"),
        "seeds": VALIDATION_SEEDS,
        "scenario_count": 8,
    }
    variants = []
    for window, (_, period) in EXTENSION_WINDOWS.items():
        base = {**common, **period}
        variants += [
            (f"ext-{window}-fan", base),
            (f"ext-{window}-bundled", {**base, "tree_splits": TREE}),
            (f"ext-{window}-tree", {**base, "tree_splits": TREE, "nonanticipativity": "tree"}),
            (f"ext-{window}-shared", {**base, "shared_minutes": 1440}),
        ]
    return variants


SUITES = {
    "development": ("config/studies/development.toml", development),
    "validation": ("config/studies/validation.toml", validation),
    "extension": (None, extension),
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="battery-dispatch experiments",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("suite", choices=sorted(SUITES))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--only", action="append", help="Run only the named variant(s)")
    parser.add_argument("--output", type=Path, default=Path("artifacts/runs"))
    args = parser.parse_args(argv)
    logging.getLogger("linopy").setLevel(logging.WARNING)
    base, variants = SUITES[args.suite]
    index_path = args.output / f"{args.suite}_index.csv"
    index = (
        pd.read_csv(index_path).set_index("variant")["run"].to_dict() if index_path.exists() else {}
    )
    failed = []
    for name, overrides in variants():
        if args.only and name not in args.only:
            continue
        study = base or EXTENSION_WINDOWS[name.split("-", 1)[1].rsplit("-", 1)[0]][0]
        config = load_study(study, name=name, **overrides)
        print(f"== {name}", flush=True)
        directory = run_study(config, output=args.output, jobs=args.jobs)
        index[name] = directory.as_posix()
        args.output.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"variant": list(index), "run": list(index.values())}).to_csv(
            index_path, index=False, lineterminator="\n"
        )
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["failures"]:
            failed.append(name)
    if failed:
        raise SystemExit(f"Variants with failed tasks: {failed}")


if __name__ == "__main__":
    main()
