"""Regenerate every table and figure of a study from its run directory.

    uv run --extra report python scripts/make_report.py runs/<run_id> --out results/test

Writes CSV tables, a ``tables.md`` with the same tables in markdown, three
figures, and ``report_manifest.json`` with the run identity and the SHA-256 of
every file written, so a published figure can be traced to the run it came
from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from battery_dispatch.report import (
    Run,
    comparisons,
    execution_comparisons,
    figure_case,
    figure_ceiling_share,
    figure_monthly,
    markdown_table,
    monthly_table,
    monthly_uplift,
    policy_table,
    seed_differences,
)

MONEY = "{:,.0f}"
SHARE = "{:.1%}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--execution", default="fixed_bands", help="Headline execution")
    args = parser.parse_args()
    run = Run.load(args.run)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(frame: pd.DataFrame, name: str) -> None:
        path = out / f"{name}.csv"
        frame.to_csv(path, index=False)
        written.append(path)

    policies = policy_table(run)
    save(policies, "policies")
    compared = comparisons(run, args.execution)
    save(compared, "comparisons")
    # The same predeclared comparisons under every other execution, descriptive.
    for execution in sorted(set(run.summary["execution"]) - {args.execution, "none"}):
        save(comparisons(run, execution), f"comparisons_{execution}")
    by_execution = execution_comparisons(run)
    save(by_execution, "execution_comparisons")
    seeds = seed_differences(run, args.execution)
    save(seeds, "seed_differences")
    names = (
        "ceiling",
        "oracle",
        "L3_aemo",
        "L2_aemo",
        "rule_aemo",
        "L3_profile",
        "L2_profile",
        "L2_persistence",
    )
    monthly = monthly_table(run, args.execution, names).reset_index()
    save(monthly, "monthly_revenue")
    uplift = monthly_uplift(run, args.execution, "L3_aemo", "L2_aemo").reset_index()
    save(uplift, "monthly_uplift")

    headline = policies.loc[policies["execution"].isin([args.execution, "none"])]
    sections = [
        f"# Tables for {run.manifest['run_id']}",
        "",
        f"Source commit `{run.manifest['source']['commit']}`, clean source tree: "
        f"{run.manifest['source']['source_tree_clean']}. Config SHA-256 "
        f"`{run.manifest['config_sha256']}`. All audits passed: "
        f"{run.manifest['all_audits_passed']}.",
        "",
        f"## Policies under `{args.execution}`",
        "",
        markdown_table(
            headline[
                [
                    "policy",
                    "total_revenue",
                    "share_of_ceiling",
                    "energy_revenue",
                    "degradation_cost",
                    "equivalent_full_cycles",
                    "terminal_soc_mwh",
                    "revenue_seed_min",
                    "revenue_seed_max",
                ]
            ],
            {
                "total_revenue": MONEY,
                "share_of_ceiling": SHARE,
                "energy_revenue": MONEY,
                "degradation_cost": MONEY,
                "equivalent_full_cycles": "{:.1f}",
                "terminal_soc_mwh": "{:.0f}",
                "revenue_seed_min": MONEY,
                "revenue_seed_max": MONEY,
            },
        ),
        "",
        "## Revenue attribution",
        "",
        markdown_table(
            headline[
                [
                    "policy",
                    "discharge_revenue_aud",
                    "charge_cost_aud",
                    "spike_discharge_revenue_aud",
                    "spike_charge_cost_aud",
                    "negative_price_charge_income_aud",
                    "soc_limited_intervals",
                    "loss_making_cycle_count",
                    "committed_forecast_mae",
                    "mean_error_pool_days",
                ]
            ].fillna(float("nan")),
            {
                "discharge_revenue_aud": MONEY,
                "charge_cost_aud": MONEY,
                "spike_discharge_revenue_aud": MONEY,
                "spike_charge_cost_aud": MONEY,
                "negative_price_charge_income_aud": MONEY,
                "soc_limited_intervals": "{:,.0f}",
                "loss_making_cycle_count": "{:,.0f}",
                "committed_forecast_mae": "{:.1f}",
                "mean_error_pool_days": "{:.1f}",
            },
        ),
        "",
        "## Paired comparisons by trading day",
        "",
        markdown_table(
            compared[
                [
                    "role",
                    "comparison",
                    "excluded_top_intervals",
                    "days",
                    "mean_daily_difference",
                    "ci_low",
                    "ci_high",
                    "total_difference",
                    "days_a_ahead",
                    "verdict",
                ]
            ],
            {
                "mean_daily_difference": MONEY,
                "ci_low": MONEY,
                "ci_high": MONEY,
                "total_difference": MONEY,
            },
        ),
        "",
        "## Seed-by-seed period differences",
        "",
        markdown_table(seeds, {"difference_aud": MONEY}) if len(seeds) else "(none)",
        "",
        "## What hourly re-pricing adds over fixed daily bands",
        "",
        markdown_table(
            by_execution[
                [
                    "comparison",
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
        if len(by_execution)
        else "(only one execution was run)",
        "",
        "## Monthly net revenue",
        "",
        markdown_table(monthly, {c: MONEY for c in monthly.columns if c != "month"}),
        "",
        "Monthly ceiling figures are slices of the whole-period ceiling's trace, not "
        "monthly upper bounds.",
        "",
    ]
    tables = out / "tables.md"
    tables.write_text("\n".join(sections), encoding="utf-8")
    written.append(tables)

    for name, draw in (
        ("fig1_monthly_revenue.png", lambda p: figure_monthly(run, args.execution, p)),
        ("fig2_share_of_ceiling.png", lambda p: figure_ceiling_share(run, p)),
        ("fig3_dispatch_case.png", lambda p: figure_case(run, args.execution, p)),
    ):
        draw(out / name)
        written.append(out / name)

    manifest = {
        "run_id": run.manifest["run_id"],
        "run_directory": run.directory.as_posix(),
        "config_sha256": run.manifest["config_sha256"],
        "source": run.manifest["source"],
        "inputs": run.manifest["inputs"],
        "all_audits_passed": run.manifest["all_audits_passed"],
        "headline_execution": args.execution,
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in written},
    }
    (out / "report_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(written)} files to {out}")


if __name__ == "__main__":
    main()
