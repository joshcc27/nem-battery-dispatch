"""Summarise a suite of runs into tables, applying the validation selection rule.

    uv run python scripts/summarise_suite.py validation --out results/validation

Reads ``runs/<suite>_index.csv``. For ``validation`` it applies the selection
rule of docs/PROTOCOL.md section 6 mechanically and writes the outcome to
``selection.csv`` and ``summary.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_dispatch.report import Run, comparisons, markdown_table, policy_table

MONEY = "{:,.0f}"
SHARE = "{:.1%}"
PCT = "{:+.2%}"

# docs/PROTOCOL.md section 6.
SELECTION_THRESHOLD = 0.01
SETTINGS = {
    "reach": ("shared", ["val-reach1h", "val-reachall"]),
    "horizon": ("shared", ["val-horizon12", "val-horizon36"]),
    "error cap": ("l3", ["val-uncapped"]),
    "error pool": ("l3", ["val-pool42"]),
    "shared decisions": ("l3", ["val-k4h", "val-k24h"]),
    "degradation": ("report", ["val-deg10", "val-deg50"]),
    "latency": ("report", ["val-latency5", "val-latency15"]),
}


def load_index(suite: str, runs: Path) -> dict[str, Run]:
    index = pd.read_csv(runs / f"{suite}_index.csv")
    return {row.variant: Run.load(row.run) for row in index.itertuples()}


def revenue(run: Run, policy: str, execution: str = "fixed_bands") -> float:
    table = policy_table(run)
    row = table.loc[(table["policy"] == policy) & (table["execution"].isin([execution, "none"]))]
    return float(row["total_revenue"].iloc[0]) if len(row) else float("nan")


def ceiling(run: Run) -> float:
    return revenue(run, "ceiling", "none")


def overview(runs: dict[str, Run]) -> pd.DataFrame:
    rows = []
    for variant, run in runs.items():
        table = policy_table(run)
        for row in table.itertuples():
            rows.append(
                {
                    "variant": variant,
                    "policy": row.policy,
                    "execution": row.execution,
                    "seeds": row.seeds,
                    "total_revenue": row.total_revenue,
                    "share_of_ceiling": row.share_of_ceiling,
                    "revenue_seed_min": row.revenue_seed_min,
                    "revenue_seed_max": row.revenue_seed_max,
                    "equivalent_full_cycles": row.equivalent_full_cycles,
                    "runtime_seconds": row.runtime_seconds,
                }
            )
    return pd.DataFrame(rows)


def selection(runs: dict[str, Run]) -> pd.DataFrame:
    base = runs["val-main"]
    bound = ceiling(base)
    base_l2, base_l3 = revenue(base, "L2_aemo"), revenue(base, "L3_aemo")
    rows = []
    for setting, (kind, variants) in SETTINGS.items():
        for variant in variants:
            if variant not in runs:
                continue
            run = runs[variant]
            l2 = revenue(run, "L2_aemo")
            l3 = revenue(run, "L3_aemo")
            gain_l2 = (l2 - base_l2) / bound
            gain_l3 = (l3 - base_l3) / bound
            if kind == "shared":
                passes = gain_l2 >= SELECTION_THRESHOLD and gain_l3 >= SELECTION_THRESHOLD
            elif kind == "l3":
                passes = gain_l3 >= SELECTION_THRESHOLD
            else:
                passes = False
            rows.append(
                {
                    "setting": setting,
                    "kind": kind,
                    "variant": variant,
                    "ceiling": ceiling(run),
                    "L2_aemo": l2,
                    "L3_aemo": l3,
                    "L2_aemo_share": l2 / ceiling(run),
                    "L3_aemo_share": l3 / ceiling(run),
                    "L2_gain_of_base_ceiling": gain_l2,
                    "L3_gain_of_base_ceiling": gain_l3,
                    "meets_rule": passes,
                }
            )
    table = pd.DataFrame(rows)
    table["adopted"] = False
    for _setting, group in table.groupby("setting"):
        eligible = group.loc[group["meets_rule"]]
        if len(eligible):
            best = eligible["L3_gain_of_base_ceiling"].idxmax()
            table.loc[best, "adopted"] = True
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["development", "validation", "extension"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    args = parser.parse_args()
    runs = load_index(args.suite, args.runs)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    table = overview(runs)
    table.to_csv(out / "overview.csv", index=False)
    lines = [f"# {args.suite.capitalize()} suite", ""]
    lines += ["Run directories and their identities:", ""]
    lines += [
        f"- `{name}`: `{run.manifest['run_id']}`, commit "
        f"`{run.manifest['source']['commit'][:10]}`, clean tree "
        f"{run.manifest['source']['source_tree_clean']}, audits passed "
        f"{run.manifest['all_audits_passed']}"
        for name, run in runs.items()
    ]
    lines += ["", "## Policies by variant (stochastic policies are seed means)", ""]
    lines.append(
        markdown_table(
            table[
                [
                    "variant",
                    "policy",
                    "execution",
                    "seeds",
                    "total_revenue",
                    "share_of_ceiling",
                    "revenue_seed_min",
                    "revenue_seed_max",
                ]
            ],
            {
                "total_revenue": MONEY,
                "share_of_ceiling": SHARE,
                "revenue_seed_min": MONEY,
                "revenue_seed_max": MONEY,
            },
        )
    )
    primary_variants = [
        v for v in runs if v in ("val-main", "dev-2022-11", "dev-2023-04", "dev-2023-04-thin")
    ]
    for variant in primary_variants:
        for execution in ("fixed_bands", "bands"):
            if execution not in set(runs[variant].summary["execution"]):
                continue
            compared = comparisons(runs[variant], execution)
            compared.to_csv(out / f"comparisons_{variant}_{execution}.csv", index=False)
            lines += ["", f"## Paired comparisons, `{variant}`, `{execution}`", ""]
            lines.append(
                markdown_table(
                    compared[
                        [
                            "comparison",
                            "excluded_top_intervals",
                            "mean_daily_difference",
                            "ci_low",
                            "ci_high",
                            "total_difference",
                            "verdict",
                        ]
                    ],
                    {
                        "mean_daily_difference": MONEY,
                        "ci_low": MONEY,
                        "ci_high": MONEY,
                        "total_difference": MONEY,
                    },
                )
            )
    if args.suite == "validation":
        chosen = selection(runs)
        chosen.to_csv(out / "selection.csv", index=False)
        lines += ["", "## Selection rule (docs/PROTOCOL.md section 6)", ""]
        lines.append(
            markdown_table(
                chosen[
                    [
                        "setting",
                        "kind",
                        "variant",
                        "L2_aemo_share",
                        "L3_aemo_share",
                        "L2_gain_of_base_ceiling",
                        "L3_gain_of_base_ceiling",
                        "meets_rule",
                        "adopted",
                    ]
                ],
                {
                    "L2_aemo_share": SHARE,
                    "L3_aemo_share": SHARE,
                    "L2_gain_of_base_ceiling": PCT,
                    "L3_gain_of_base_ceiling": PCT,
                },
            )
        )
        adopted = chosen.loc[chosen["adopted"], "variant"].tolist()
        lines += ["", f"Adopted: {', '.join(adopted) if adopted else 'none'}."]
    summary = out / "summary.md"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "manifest.json")
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "suite": args.suite,
                "runs": {name: run.manifest["run_id"] for name, run in runs.items()},
                "commits": sorted({run.manifest["source"]["commit"] for run in runs.values()}),
                "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {summary}")


if __name__ == "__main__":
    main()
