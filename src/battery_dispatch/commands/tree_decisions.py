"""Controlled comparison of single decisions: two-stage model against scenario tree.

Rolling runs diverge after the first decision, so first-hour choices are only
comparable from an identical state. This takes preselected decision points,
every six hours through the validation period, at the SOC a reference run
actually had there, and at each solves on identical inputs:

- ``fan``: the two-stage model on the bootstrapped fan, as in layer 3;
- ``bundled``: the two-stage model on the tree's bundled paths;
- ``tree``: the scenario tree on the same bundled paths;
- ``shared``: one plan for every bundled path.

It records each committed-hour dispatch, the planned objective (what the model
expects to earn), the stored-energy value at the end of the committed hour and
the solve time.

    uv run battery-dispatch tree-decisions --out results/extension \
        --reference artifacts/runs/<ext-val-bundled>/traces/L3_aemo__bands__seed101.parquet
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from battery_dispatch.dispatch.scenario_model import ScenarioDispatchModel
from battery_dispatch.dispatch.scenario_tree import bundle_to_tree, parse_splits
from battery_dispatch.market.config import MARKET_FLOOR_PRICE, market_price_cap
from battery_dispatch.market.settlement import settlement_coefficients
from battery_dispatch.study.spec import load_study
from battery_dispatch.study.tasks import build_forecaster, load_inputs

TREE = "60:2,240:2,720:2"
EVERY_HOURS = 6


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="battery-dispatch tree-decisions",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--reference",
        type=Path,
        required=True,
        help="A validation trace whose SOC sets each decision's state",
    )
    parser.add_argument("--forecaster", default="aemo", choices=["aemo", "profile"])
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    config = load_study("config/studies/validation.toml", scenario_count=8, seeds=(args.seed,))
    settings = replace(config.settings, seed=args.seed)
    inputs = load_inputs(config, Path("data/cache"))
    asset = inputs.asset
    forecaster = build_forecaster(args.forecaster, inputs, settings, thin=False)
    errors_model = settings.error_model(asset)
    combined = pd.concat([inputs.history, inputs.evaluation], ignore_index=True)
    actual = combined["rrp"].to_numpy(dtype=float)
    timestamps = combined["settlementdate"]
    unit = settlement_coefficients(np.ones(len(combined)), asset, settlementdate=timestamps)
    generation, load = unit.generation_loss_factor, unit.load_loss_factor
    caps = np.array([market_price_cap(t) for t in timestamps])
    reference = pd.read_parquet(args.reference)
    soc_after = reference["soc_mwh"].to_numpy()
    start = len(inputs.history)
    steps = int(settings.horizon_hours * 12)
    commit = settings.commit_minutes // asset.interval_minutes
    splits = parse_splits(TREE, asset.interval_minutes)
    dt = asset.interval_hours
    models: dict[str, ScenarioDispatchModel] = {}
    rows = []
    stride = EVERY_HOURS * 12
    for k, position in enumerate(range(start, len(combined) - steps, stride)):
        offset = position - start
        soc = asset.initial_soc_mwh if offset == 0 else float(soc_after[offset - 1])
        seen = actual[:position]
        base = forecaster.forecast(seen, steps)
        errors = errors_model.errors(forecaster, seen, steps)
        fan = errors_model.scenarios(errors, base, k)
        window = slice(position, position + steps)
        fan = np.clip(fan, MARKET_FLOOR_PRICE, caps[window])
        bundled, labels = bundle_to_tree(fan, splits, commit)
        variants = {
            "fan": (fan, {}),
            "bundled": (bundled, {}),
            "tree": (bundled, {"groups": labels}),
            "shared": (bundled, {"shared": steps}),
        }
        for name, (paths, extra) in variants.items():
            key = f"{name}-{hash(labels.tobytes()) if name == 'tree' else ''}"
            if key not in models:
                models[key] = ScenarioDispatchModel(
                    asset, steps=steps, committed=commit, scenarios=len(paths), **extra
                )
            started = perf_counter()
            result = models[key].solve(
                -dt * load[window] * paths,
                dt * (generation[window] * paths - settings.deg_cost),
                soc,
            )
            rows.append(
                {
                    "decision": k,
                    "time": timestamps.iloc[position - 1],
                    "soc_mwh": soc,
                    "variant": name,
                    "committed_charge_mwh": float(result.charge_mw.sum() * dt),
                    "committed_discharge_mwh": float(result.discharge_mw.sum() * dt),
                    "planned_objective": result.objective_value,
                    "stored_energy_value_end_of_hour": float(result.stored_energy_value[-1]),
                    "solve_seconds": perf_counter() - started,
                }
            )
    frame = pd.DataFrame(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        args.out / f"tree_decisions_{args.forecaster}.csv", index=False, lineterminator="\n"
    )
    wide = frame.pivot(index="decision", columns="variant")
    net = wide["committed_discharge_mwh"] - wide["committed_charge_mwh"]
    summary = []
    for name in ("fan", "tree", "shared"):
        other = "bundled"
        summary.append(
            {
                "forecaster": args.forecaster,
                "compared_with_bundled_two_stage": name,
                "decisions": len(wide),
                "same_committed_hour_share": float((np.abs(net[name] - net[other]) < 1e-3).mean()),
                "mean_abs_net_mwh_difference": float(np.abs(net[name] - net[other]).mean()),
                "mean_planned_objective": float(wide["planned_objective"][name].mean()),
                "mean_planned_objective_bundled": float(wide["planned_objective"][other].mean()),
                "mean_end_of_hour_value": float(
                    wide["stored_energy_value_end_of_hour"][name].mean()
                ),
                "mean_end_of_hour_value_bundled": float(
                    wide["stored_energy_value_end_of_hour"][other].mean()
                ),
                "mean_solve_seconds": float(wide["solve_seconds"][name].mean()),
                "mean_solve_seconds_bundled": float(wide["solve_seconds"][other].mean()),
            }
        )
    pd.DataFrame(summary).to_csv(
        args.out / f"tree_decisions_{args.forecaster}_summary.csv", index=False, lineterminator="\n"
    )
    print(pd.DataFrame(summary).T.to_string())


if __name__ == "__main__":
    main()
