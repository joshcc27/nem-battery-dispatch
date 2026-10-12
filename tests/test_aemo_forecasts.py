from __future__ import annotations

import io
import json
import urllib.error
import zipfile

import numpy as np
import pandas as pd
import pytest

from battery_dispatch.aemo_forecasts import (
    ForecastCache,
    ForecastRuns,
    parse_forecasts,
    validate_forecasts,
)
from battery_dispatch.config import AEST
from battery_dispatch.forecast import AemoForecast, SameTimeProfile, grid_times


def archive(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("PUBLIC_DVD_PREDISPATCHPRICE_202211010000.CSV", "\n".join(lines) + "\n")
    return buffer.getvalue()


def row(region: str, intervention: int, rrp: float, lastchanged: str, period_end: str) -> str:
    return (
        f"D,PREDISPATCH,REGION_PRICES,1,2022110101,1,{region},01,{intervention},{rrp},"
        f'"2022/11/01 {lastchanged}","2022/11/01 {period_end}"'
    )


PREDISPATCH_CSV = [
    "C,SETP.WORLD,DVD_PREDISPATCHPRICE,AEMO,PUBLIC,2022/12/07,04:55:12,1,,1",
    "I,PREDISPATCH,REGION_PRICES,1,PREDISPATCHSEQNO,RUNNO,REGIONID,PERIODID,"
    "INTERVENTION,RRP,LASTCHANGED,DATETIME",
    row("SA1", 0, 50, "04:01:10", "04:30:00"),
    row("SA1", 0, 60, "04:01:22", "05:00:00"),
    row("SA1", 1, 999, "04:01:22", "05:00:00"),
    row("VIC1", 0, 70, "04:01:22", "04:30:00"),
    "C,END OF REPORT,6",
]


def test_parse_keeps_one_regions_non_intervention_forecasts() -> None:
    frame = parse_forecasts("predispatch", archive(PREDISPATCH_CSV), "SA1")
    assert frame["rrp"].tolist() == [50.0, 60.0]
    # A run is usable only once its last row is out.
    assert (frame["published"] == pd.Timestamp("2022-11-01 04:01:22", tz=AEST)).all()
    assert frame["target"].tolist() == [
        pd.Timestamp("2022-11-01 04:30", tz=AEST),
        pd.Timestamp("2022-11-01 05:00", tz=AEST),
    ]


def test_validation_rejects_duplicate_forecasts() -> None:
    frame = parse_forecasts("predispatch", archive(PREDISPATCH_CSV), "SA1")
    with pytest.raises(ValueError, match="duplicate"):
        validate_forecasts(pd.concat([frame, frame.iloc[:1]]), table="predispatch")


def test_an_archive_gap_is_recorded_once_and_not_refetched(tmp_path) -> None:
    calls: list[str] = []

    def missing(url: str) -> bytes:
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "missing", {}, None)

    cache = ForecastCache(tmp_path)
    month = pd.Timestamp("2022-10-01")
    assert cache.month("predispatch", "SA1", month, fetch=missing).empty
    assert cache.month("predispatch", "SA1", month, fetch=missing).empty
    assert len(calls) == 1
    record = json.loads(cache.manifest_path.read_text(encoding="utf-8").strip())
    assert record["missing_from_archive"] is True


def runs(published: str, targets: list[str], prices: list[float], run_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "run_id": run_id,
            "published": pd.Timestamp(published, tz=AEST),
            "target": pd.to_datetime(targets).tz_localize(AEST),
            "rrp": prices,
        }
    )


@pytest.fixture
def grid() -> pd.Series:
    return pd.Series(pd.date_range("2022-11-01 00:05", periods=48, freq="5min", tz=AEST))


def forecaster(grid: pd.Series, predispatch: pd.DataFrame, p5min: pd.DataFrame) -> AemoForecast:
    return AemoForecast(
        timestamps=grid_times(grid),
        predispatch=ForecastRuns.from_frame(predispatch),
        p5min=ForecastRuns.from_frame(p5min),
        fallback=SameTimeProfile(1, periods_per_day=6),
    )


def test_p5min_then_predispatch_then_profile(grid) -> None:
    predispatch = pd.concat(
        [
            runs("2022-11-01 00:29", ["2022-11-01 01:00", "2022-11-01 01:30"], [10, 20], "a"),
            # Published after the decision at 00:30: must not be used.
            runs("2022-11-01 00:31", ["2022-11-01 01:00", "2022-11-01 01:30"], [99, 99], "b"),
        ]
    )
    p5min = runs("2022-11-01 00:30", ["2022-11-01 00:35", "2022-11-01 00:40"], [1, 2], "c")
    aemo = forecaster(grid, predispatch, p5min)
    history = np.arange(6.0)  # six intervals settled: the decision is at 00:30
    forecast = aemo.forecast(history, 18)
    # 00:35 and 00:40 from P5MIN; 00:45 to 01:00 in the period ending 01:00;
    # 01:05 to 01:30 in the next; beyond pre-dispatch, the profile.
    assert forecast[:2].tolist() == [1.0, 2.0]
    assert forecast[2:6].tolist() == [10.0] * 4
    assert forecast[6:12].tolist() == [20.0] * 6
    assert forecast[12:].tolist() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_stale_runs_are_ignored_and_reported_as_not_covering(grid) -> None:
    old = runs("2022-11-01 00:00", ["2022-11-01 03:00"], [10.0], "a")
    empty = old.iloc[0:0]
    aemo = forecaster(grid, old, empty)
    assert aemo.covers(6)  # decision at 00:30, run 30 minutes old
    assert not aemo.covers(18)  # decision at 01:30, run 90 minutes old
    history = np.arange(18.0)
    np.testing.assert_array_equal(aemo.forecast(history, 6), history[-6:])


def test_predispatch_is_used_only_within_its_reach(grid) -> None:
    predispatch = runs(
        "2022-11-01 00:29",
        ["2022-11-01 01:00", "2022-11-01 01:30", "2022-11-01 02:00"],
        [10, 20, 30],
        "a",
    )
    aemo = AemoForecast(
        timestamps=grid_times(grid),
        predispatch=ForecastRuns.from_frame(predispatch),
        p5min=ForecastRuns.from_frame(predispatch.iloc[0:0]),
        fallback=SameTimeProfile(1, periods_per_day=6),
        predispatch_hours=1.0,
    )
    assert aemo.name == "aemo_1h"
    forecast = aemo.forecast(np.arange(6.0), 18)  # decision at 00:30
    # Up to 01:30 from pre-dispatch; beyond an hour ahead, the profile.
    assert forecast[:12].tolist() == [10.0] * 6 + [20.0] * 6
    assert forecast[12:].tolist() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
