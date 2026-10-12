from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from battery_dispatch.aemo_forecasts import ForecastRuns
from battery_dispatch.config import AEST, BatteryConfig
from battery_dispatch.layers import LAYER_ORDER, LayerSettings, layer_gaps, run_layers

SETTINGS = LayerSettings(
    deg_cost=2.0,
    horizon_hours=12,
    commit_minutes=60,
    profile_days=2,
    scenario_count=2,
    scenario_pool_days=3,
    bands=4,
)


def battery() -> BatteryConfig:
    return BatteryConfig(
        generation_loss_factor=1.0,
        load_loss_factor=1.0,
        power_mw=1.0,
        energy_mwh=2.0,
        round_trip_efficiency=0.81,
        soc_min_fraction=0.0,
        soc_max_fraction=1.0,
        interval_minutes=60,
    )


def frame(days: int) -> pd.DataFrame:
    rng = np.random.default_rng(9)
    shape = np.array([20.0, 10.0, 0.0, -10.0, 40.0, 120.0] * 4)
    values = np.tile(shape, days) + rng.normal(0.0, 20.0, days * 24)
    timestamps = pd.date_range("2023-01-01 01:00", periods=len(values), freq="h", tz=AEST)
    return pd.DataFrame({"settlementdate": timestamps, "rrp": values})


def published_forecasts(data: pd.DataFrame) -> dict[str, ForecastRuns]:
    """Hourly runs, published on the hour, forecasting the next 12 hours with noise."""
    rng = np.random.default_rng(3)
    rows = []
    for position in range(1, len(data)):
        published = data["settlementdate"].iloc[position - 1]
        ahead = data.iloc[position : position + 12]
        rows.append(
            pd.DataFrame(
                {
                    "run_id": str(position),
                    "published": published,
                    "target": ahead["settlementdate"].to_numpy(),
                    "rrp": ahead["rrp"].to_numpy() + rng.normal(0.0, 10.0, len(ahead)),
                }
            )
        )
    empty = pd.DataFrame(
        {
            "run_id": pd.Series([], dtype=str),
            "published": pd.Series([], dtype=pd.DatetimeTZDtype(tz=AEST)),
            "target": pd.Series([], dtype=pd.DatetimeTZDtype(tz=AEST)),
            "rrp": pd.Series([], dtype=float),
        }
    )
    return {
        "predispatch": ForecastRuns.from_frame(pd.concat(rows, ignore_index=True)),
        "p5min": ForecastRuns.from_frame(empty),
    }


def test_every_layer_runs_is_audited_and_sits_under_the_bound() -> None:
    asset = battery()
    history_len = SETTINGS.min_history_intervals(asset)
    data = frame(history_len // 24 + 4)
    result = run_layers(
        data.iloc[history_len:],
        data.iloc[:history_len],
        asset,
        SETTINGS,
        aemo_forecasts=published_forecasts(data),
    )
    summary = result.summary.set_index("layer")
    assert tuple(summary.index) == LAYER_ORDER
    bound = summary.loc["L1_bound", "total_revenue"]
    assert (summary["total_revenue"] <= bound + 1e-6).all()
    assert (summary["gap_to_bound_aud"] >= -1e-6).all()
    assert summary.loc["L1_perfect_forecast", "loss_making_cycle_count"] == 0
    assert summary.loc["L1_perfect_forecast", "committed_forecast_mae"] == 0
    # A perfect forecast has no errors, so its bands collapse to one limit.
    assert summary.loc["L1_perfect_forecast", "median_band_spread_aud"] == 0
    assert summary.loc["L2_aemo", "median_band_spread_aud"] > 0
    assert summary.loc["L3_aemo", "scenario_count"] == SETTINGS.scenario_count
    # The published forecasts are far closer than the profile.
    assert (
        summary.loc["L2_aemo", "committed_forecast_mae"]
        < summary.loc["L2_profile", "committed_forecast_mae"]
    )
    assert set(result.traces) == set(LAYER_ORDER[1:])
    assert len(result.bound_dispatch) == 4 * 24

    gaps = layer_gaps(result.summary)
    assert gaps["value_of_perfect_information_aemo"] == pytest.approx(
        bound - summary.loc["L3_aemo", "total_revenue"]
    )
    assert gaps["cadence_cost_under_perfect_forecast"] >= -1e-6


def test_layers_without_aemo_forecasts_leave_those_layers_out() -> None:
    asset = battery()
    history_len = SETTINGS.min_history_intervals(asset)
    data = frame(history_len // 24 + 2)
    result = run_layers(data.iloc[history_len:], data.iloc[:history_len], asset, SETTINGS)
    assert "L2_aemo" not in set(result.summary["layer"])
    assert "value_of_stochastic_solution_aemo" not in layer_gaps(result.summary)
    assert "value_of_stochastic_solution_profile" in layer_gaps(result.summary)


def test_layers_refuse_too_little_history() -> None:
    asset = battery()
    history_len = SETTINGS.min_history_intervals(asset) - 1
    data = frame(history_len // 24 + 3)
    with pytest.raises(ValueError, match="history"):
        run_layers(data.iloc[history_len:], data.iloc[:history_len], asset, SETTINGS)
