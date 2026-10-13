from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from battery_dispatch.bidding import band_prices
from battery_dispatch.config import AEST, BatteryConfig
from battery_dispatch.layers import LayerSettings
from battery_dispatch.stats import block_bootstrap_means, paired_comparison, verdict
from battery_dispatch.study import (
    StudyConfig,
    Task,
    _Inputs,
    load_study,
    run_task,
    slices,
    tasks_for,
    warm_up_days,
)


def test_block_bootstrap_keeps_whole_blocks_and_is_repeatable() -> None:
    values = np.arange(10, dtype=float)
    means = block_bootstrap_means(values, block=10, draws=50, seed=1)
    # A single block covering the series resamples a rotation of it.
    np.testing.assert_allclose(means, values.mean())
    again = block_bootstrap_means(np.arange(30.0), block=7, draws=200, seed=3)
    np.testing.assert_array_equal(
        again, block_bootstrap_means(np.arange(30.0), block=7, draws=200, seed=3)
    )


def test_paired_verdicts() -> None:
    rng = np.random.default_rng(0)
    base = rng.normal(1_000.0, 300.0, 200)
    assert paired_comparison(base + 100.0, base).verdict == "win"
    assert paired_comparison(base - 100.0, base).verdict == "loss"
    noisy = base + rng.normal(0.0, 500.0, 200)
    result = paired_comparison(noisy, base)
    assert result.verdict == "inconclusive"
    assert result.ci_low < result.mean_daily_difference < result.ci_high
    assert verdict(0.0, 1.0) == "inconclusive"
    with pytest.raises(ValueError):
        paired_comparison(np.ones(3), np.ones(4))


def test_laddered_bands_reach_the_market_bounds() -> None:
    wanted = np.linspace(50.0, 150.0, 100)
    discharge = band_prices(wanted, 10, cap=16_600.0, direction="discharge")
    charge = band_prices(wanted, 10, cap=16_600.0, direction="charge")
    assert np.all(np.diff(discharge) > 0) and np.all(np.diff(charge) > 0)
    assert discharge[-1] == pytest.approx(16_600.0, abs=0.1)
    assert charge[0] == pytest.approx(-1_000.0, abs=0.1)
    # The seven core bands stay inside the wanted range.
    assert 50.0 <= discharge[0] and discharge[6] <= 150.1
    assert 50.0 <= charge[3] and charge[9] <= 150.1


def write_study(tmp_path: Path, **lines: str) -> Path:
    body = {
        "name": '"t"',
        "stage": '"validation"',
        "start": '"2023-01-10 00:00"',
        "end": '"2023-01-12 00:00"',
        **lines,
    }
    text = "\n".join(f"{key} = {value}" for key, value in body.items())
    path = tmp_path / "study.toml"
    path.write_text(text + "\n[settings]\ndeg_cost = 5.0\n", encoding="utf-8")
    return path


def test_study_identity_is_its_resolved_configuration(tmp_path: Path) -> None:
    path = write_study(tmp_path)
    config = load_study(path)
    assert config.settings.deg_cost == 5.0
    assert config.run_id == load_study(path).run_id
    changed = load_study(path, deg_cost=10.0)
    assert changed.settings.deg_cost == 10.0 and changed.run_id != config.run_id
    with pytest.raises(ValueError, match="Unknown settings"):
        load_study(path, not_a_setting=1)
    with pytest.raises(ValueError, match="protocol"):
        load_study(path, stage="test")
    with pytest.raises(ValueError, match="Unknown policies"):
        load_study(path, policies=("L9",))


def test_tasks_cover_each_execution_and_seed_once() -> None:
    config = StudyConfig(
        name="t",
        stage="validation",
        start="2023-01-01",
        end="2023-02-01",
        policies=("ceiling", "noop", "L2_aemo", "L3_aemo"),
        executions=("fixed_bands", "bands"),
        seeds=(1, 2, 3),
    )
    keys = [task.key for task in tasks_for(config)]
    assert keys.count("ceiling__none") == 1 and keys.count("noop__none") == 1
    assert sum(k.startswith("L2_aemo") for k in keys) == 2
    assert sum(k.startswith("L3_aemo") for k in keys) == 6
    asset = BatteryConfig(generation_loss_factor=1.0, load_loss_factor=1.0)
    # 21 pool days from a two-day first lag, plus the 7-day profile and slack.
    assert warm_up_days(config, asset) == 22 + 7 + 3
    hourly = replace(config, executions=("bands",))
    assert warm_up_days(hourly, asset) == 21 + 7 + 3


def synthetic_inputs(days: int, history_days: int) -> _Inputs:
    asset = BatteryConfig(
        generation_loss_factor=1.0, load_loss_factor=1.0, power_mw=1.0, energy_mwh=2.0
    )
    rng = np.random.default_rng(5)
    count = (days + history_days) * 288
    shape = np.tile(
        np.r_[np.full(96, 20.0), np.full(96, -5.0), np.full(96, 90.0)], days + history_days
    )
    values = shape + rng.normal(0.0, 15.0, count)
    timestamps = pd.date_range("2023-01-01 00:05", periods=count, freq="5min", tz=AEST)
    frame = pd.DataFrame({"settlementdate": timestamps, "rrp": values})
    split = history_days * 288
    return _Inputs(
        asset,
        frame.iloc[split:].reset_index(drop=True),
        frame.iloc[:split].reset_index(drop=True),
        {},
    )


def test_tasks_run_settle_audit_and_slice_on_one_continuous_trace() -> None:
    inputs = synthetic_inputs(days=3, history_days=12)
    settings = LayerSettings(
        deg_cost=2.0,
        horizon_hours=6,
        profile_days=2,
        scenario_count=2,
        scenario_pool_days=3,
        bands=10,
    )
    config = StudyConfig(
        name="t",
        stage="validation",
        start="2023-01-13",
        end="2023-01-16",
        policies=("ceiling", "noop", "oracle", "rule_profile", "L2_profile", "L3_profile"),
        executions=("fixed_bands", "bands"),
        seeds=(7,),
        settings=settings,
    )
    totals = {}
    for task in tasks_for(config):
        result = run_task(config, task, Path("unused"), inputs=inputs)
        row = result["row"]
        totals[task.key] = row["total_revenue"]
        assert row["gap_to_ceiling_aud"] >= -1.0
        monthly, daily = slices(result["trace"], task, inputs.asset)
        assert daily["total_revenue"].sum() == pytest.approx(row["total_revenue"], abs=1e-6)
        assert monthly["total_revenue"].sum() == pytest.approx(row["total_revenue"], abs=1e-6)
        if task.execution == "fixed_bands" and task.policy != "noop":
            assert len(result["bands"]) >= 3
    assert totals["noop__none"] == 0.0
    assert totals["oracle__bands"] == pytest.approx(totals["ceiling__none"], rel=1e-3)
    assert Task("L3_profile", "bands", 7).key in totals
