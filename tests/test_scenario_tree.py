from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_dispatch.dispatch.forecast import ErrorBootstrap, SameTimeProfile
from battery_dispatch.dispatch.rolling import run_forecast_policy
from battery_dispatch.dispatch.scenario_model import ScenarioDispatchModel
from battery_dispatch.dispatch.scenario_tree import (
    bundle_to_tree,
    history_labels,
    is_nonanticipative,
    parse_splits,
    two_stage_labels,
)
from battery_dispatch.market.config import AEST, BatteryConfig


def hourly_asset(**changes: float) -> BatteryConfig:
    values = {
        "generation_loss_factor": 1.0,
        "load_loss_factor": 1.0,
        "power_mw": 1.0,
        "energy_mwh": 1.0,
        "round_trip_efficiency": 1.0,
        "soc_min_fraction": 0.0,
        "soc_max_fraction": 1.0,
        "interval_minutes": 60,
    }
    values.update(changes)
    return BatteryConfig(**values)


def solve(paths: np.ndarray, *, committed: int = 1, **model):
    asset = hourly_asset()
    count, steps = paths.shape
    return ScenarioDispatchModel(
        asset, steps=steps, committed=committed, scenarios=count, **model
    ).solve(-paths, paths, 0.0, throughput_tie_breaker=0.0)


def test_paths_that_diverge_late_keep_their_early_decisions_shared() -> None:
    """Hand-worked. Prices are 50, 50, then 100 or 0 with equal chance.

    Two-stage shares only hour 0, so after it each scenario plans as if it knew
    its own hour 2: the 100 scenario buys at 50 in hour 1 and sells at 100,
    the 0 scenario stays idle, and the plan expects (50 + 0) / 2 = 25.
    In the tree, hour 2's price is unseen until hour 2 has passed, so hours 0
    to 2 are one decision for both scenarios: buying at 50 to sell at 100 or 0
    is worth (50 - 50) / 2 = 0, so it does nothing and expects 0.
    """
    paths = np.array([[50.0, 50.0, 100.0], [50.0, 50.0, 0.0]])
    two_stage = solve(paths)
    assert two_stage.objective_value == pytest.approx(25.0)
    labels = history_labels(paths, 1)
    assert is_nonanticipative(paths, labels, 1)
    assert (labels == 0).all()  # nothing distinguishes them before hour 3
    tree = solve(paths, groups=labels)
    assert tree.objective_value == pytest.approx(0.0)
    # Removing clairvoyance can only lower the planned value.
    assert tree.objective_value <= two_stage.objective_value


def test_two_stage_labels_reproduce_the_default_model() -> None:
    rng = np.random.default_rng(4)
    paths = rng.normal(40.0, 30.0, (4, 10))
    default = solve(paths, committed=2)
    labelled = solve(paths, committed=2, groups=two_stage_labels(4, 10, 2))
    assert labelled.objective_value == pytest.approx(default.objective_value, abs=1e-9)
    np.testing.assert_allclose(labelled.charge_mw, default.charge_mw, atol=1e-9)
    np.testing.assert_allclose(labelled.stored_energy_value, default.stored_energy_value, atol=1e-9)
    with pytest.raises(ValueError, match="committed block"):
        solve(paths, committed=2, groups=two_stage_labels(4, 10, 1))


def test_a_tree_that_branches_at_once_is_the_two_stage_model() -> None:
    """Paths that already differ in the committed hour are told apart after it."""
    rng = np.random.default_rng(6)
    paths = rng.normal(40.0, 30.0, (4, 8))
    labels = history_labels(paths, 2)
    np.testing.assert_array_equal(labels, history_labels(paths, 2))
    assert is_nonanticipative(paths, labels, 2)
    tree = solve(paths, committed=2, groups=labels)
    two_stage = solve(paths, committed=2)
    assert tree.objective_value == pytest.approx(two_stage.objective_value, abs=1e-9)


def test_bundling_builds_a_nonanticipative_tree_in_canonical_order() -> None:
    rng = np.random.default_rng(0)
    paths = rng.normal(50.0, 30.0, (8, 48))
    bundled, labels = bundle_to_tree(paths, ((12, 2), (24, 2), (36, 2)), 12)
    assert is_nonanticipative(bundled, labels, 12)
    # One bundle up to the first split, then 2, 4 and 8 distinct futures.
    for first, last, distinct in ((0, 12, 1), (12, 24, 2), (24, 36, 4), (36, 48, 8)):
        assert len(np.unique(bundled[:, first:last], axis=0)) == distinct
    # Each split becomes a separate decision one block after it happens.
    assert [len(np.unique(labels[:, t])) for t in (0, 12, 24, 36, 47)] == [1, 1, 2, 4, 4]
    # Means are preserved: bundling only averages within bundles.
    np.testing.assert_allclose(bundled.mean(axis=0), paths.mean(axis=0))
    # The labels depend only on the shape and splits.
    other, other_labels = bundle_to_tree(
        rng.normal(0.0, 5.0, (8, 48)), ((12, 2), (24, 2), (36, 2)), 12
    )
    np.testing.assert_array_equal(labels, other_labels)
    with pytest.raises(ValueError, match="block"):
        bundle_to_tree(paths, ((6, 2),), 12)
    assert parse_splits("60:2,240:2", 5) == ((12, 2), (48, 2))
    with pytest.raises(ValueError):
        parse_splits("240:2,60:2", 5)


def test_rolling_policy_runs_on_a_tree() -> None:
    asset = hourly_asset(energy_mwh=2.0, round_trip_efficiency=0.81)
    rng = np.random.default_rng(5)
    values = np.tile([10.0, 5.0, 0.0, 20.0, 90.0, 60.0] * 4, 10) + rng.normal(0, 15, 10 * 24)
    frame = pd.DataFrame(
        {
            "settlementdate": pd.date_range(
                "2023-01-01 01:00", periods=len(values), freq="h", tz=AEST
            ),
            "rrp": values,
        }
    )
    prices, history = frame.iloc[168:], frame.iloc[:168]
    common = {
        "scenarios": ErrorBootstrap(count=4, pool_days=4, periods_per_day=24),
        "horizon_hours": 12,
        "commit_minutes": 60,
        "execution": "bid",
        "tree_splits": ((1, 2), (3, 2)),
    }
    traces = {
        mode: run_forecast_policy(
            prices, history, asset, SameTimeProfile(2, 24), nonanticipativity=mode, **common
        )
        for mode in ("two_stage", "tree")
    }
    first = {m: t["planned_objective"].iloc[0] for m, t in traces.items()}
    # From the same SOC on the same bundled paths, removing the two-stage
    # model's clairvoyance can only lower the planned value.
    assert first["tree"] <= first["two_stage"] + 1e-6
    for trace in traces.values():
        assert trace["planned_objective"].notna().all()
    with pytest.raises(ValueError, match="tree"):
        run_forecast_policy(
            prices,
            history,
            asset,
            SameTimeProfile(2, 24),
            nonanticipativity="tree",
            horizon_hours=12,
            execution="bid",
        )
