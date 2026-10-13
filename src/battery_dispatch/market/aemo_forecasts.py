"""AEMO pre-dispatch and 5-minute pre-dispatch price forecasts, as published.

Both come from the MMSDM monthly archive on NEMWeb, the archive NEMOSIS reads
dispatch prices from:

- ``PREDISPATCHPRICE`` from ``PREDISP_ALL_DATA``: every half-hourly
  pre-dispatch run, each forecasting 30-minute periods to the end of the next
  trading day.
- ``P5MIN_REGIONSOLUTION`` from ``DATA``: every 5-minute pre-dispatch run, each
  forecasting the next twelve 5-minute intervals.

Each run is stamped with when it was *published*: the latest ``LASTCHANGED``
of any of its rows. A forecaster may use a run only once it has been
published, so a decision never sees a forecast AEMO had not yet released.

NEMSEER is the usual client for these files, but it pins ``xarray`` below what
linopy requires, so the two files are fetched directly. Only the region's
non-intervention RRP forecasts are kept, as one parquet partition per table,
region and archive month, recorded in the same JSONL manifest as prices.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from battery_dispatch.market.config import AEST, MARKET_FLOOR_PRICE, market_price_cap

ARCHIVE_URL = "https://nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM/"
USER_AGENT = "Mozilla/5.0 (battery-dispatch research backtest)"

# Partition name: (archive folder, file stem, run column, target column).
TABLES = {
    "predispatch": (
        "PREDISP_ALL_DATA",
        "PUBLIC_DVD_PREDISPATCHPRICE",
        "PREDISPATCHSEQNO",
        "DATETIME",
    ),
    "p5min": ("DATA", "PUBLIC_DVD_P5MIN_REGIONSOLUTION", "RUN_DATETIME", "INTERVAL_DATETIME"),
}
FORECAST_COLUMNS = ["run_id", "published", "target", "rrp"]


def archive_url(table: str, month: pd.Timestamp) -> str:
    folder, stem, _, _ = TABLES[table]
    return (
        f"{ARCHIVE_URL}{month.year}/MMSDM_{month.year}_{month.month:02d}/"
        f"MMSDM_Historical_Data_SQLLoader/{folder}/{stem}_{month.year}{month.month:02d}010000.zip"
    )


def download(url: str) -> bytes:
    """GET with a browser-like user agent: NEMWeb returns empty bodies without one."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=900) as response:
        body = response.read()
    if not body:
        raise RuntimeError(f"NEMWeb returned an empty file for {url}")
    return body


def _aest(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, format="%Y/%m/%d %H:%M:%S").dt.tz_localize(AEST)


def parse_forecasts(table: str, archive: bytes, region: str) -> pd.DataFrame:
    """Return one region's non-intervention forecasts from an MMSDM zip.

    The CSV is AEMO's C/I/D format: one ``C`` header line, one ``I`` line naming
    the columns, ``D`` data rows and a closing ``C`` line.
    """
    _, _, run_column, target_column = TABLES[table]
    columns = [run_column, "INTERVENTION", "REGIONID", target_column, "RRP", "LASTCHANGED"]
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [name for name in bundle.namelist() if name.upper().endswith(".CSV")]
        if len(names) != 1:
            raise ValueError(f"Expected one CSV in the {table} archive, found {names}")
        with bundle.open(names[0]) as handle:
            raw = pd.read_csv(
                handle, skiprows=1, usecols=["I", *columns], dtype=str, low_memory=False
            )
    raw = raw.loc[(raw["I"] == "D") & (raw["REGIONID"] == region)]
    if raw.empty:
        raise ValueError(f"The {table} archive has no rows for {region}")
    raw = raw.loc[pd.to_numeric(raw["INTERVENTION"], errors="raise") == 0]
    frame = pd.DataFrame(
        {
            "run_id": raw[run_column].to_numpy(),
            "target": _aest(raw[target_column]).to_numpy(),
            "rrp": pd.to_numeric(raw["RRP"], errors="raise").to_numpy(),
            "lastchanged": _aest(raw["LASTCHANGED"]).to_numpy(),
        }
    )
    # A run is usable once its last row is published.
    frame["published"] = frame.groupby("run_id")["lastchanged"].transform("max")
    return validate_forecasts(frame[FORECAST_COLUMNS], table=table)


def validate_forecasts(frame: pd.DataFrame, *, table: str) -> pd.DataFrame:
    """Fail closed on missing values, duplicate forecasts or impossible prices."""
    if missing := set(FORECAST_COLUMNS).difference(frame.columns):
        raise ValueError(f"{table} forecasts are missing columns: {sorted(missing)}")
    frame = frame[FORECAST_COLUMNS].sort_values(["published", "run_id", "target"])
    frame = frame.reset_index(drop=True)
    if frame.isna().any().any():
        raise ValueError(f"{table} forecasts contain missing values")
    if frame.duplicated(["run_id", "target"]).any():
        raise ValueError(f"{table} forecasts have duplicate (run, target) rows")
    if frame.groupby("run_id")["published"].nunique().gt(1).any():
        raise ValueError(f"{table} runs have more than one publication time")
    if (frame["target"] <= frame["published"] - pd.Timedelta(minutes=30)).any():
        raise ValueError(f"{table} has forecasts for periods long before publication")
    targets = frame["target"]
    caps = targets.map({target: market_price_cap(target) for target in targets.unique()})
    if ((frame["rrp"] < MARKET_FLOOR_PRICE) | (frame["rrp"] > caps + 1e-6)).any():
        raise ValueError(f"{table} forecasts lie outside the dated market bounds")
    return frame


@dataclass(frozen=True)
class ForecastRuns:
    """One forecast table as run publication times and each run's targets."""

    published: np.ndarray  # datetime64[ns, UTC-naive], sorted, one per run
    starts: np.ndarray  # row offset of each run in targets/rrp
    targets: np.ndarray  # datetime64 of forecast period or interval ends
    rrp: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> ForecastRuns:
        frame = frame.sort_values(["published", "run_id", "target"]).reset_index(drop=True)
        run_change = frame["run_id"].ne(frame["run_id"].shift())
        starts = np.flatnonzero(run_change.to_numpy())
        return cls(
            published=_naive_utc(frame["published"].iloc[starts]),
            starts=np.append(starts, len(frame)),
            targets=_naive_utc(frame["target"]),
            rrp=frame["rrp"].to_numpy(dtype=float),
        )

    def latest(self, decision_time: np.datetime64) -> tuple[np.ndarray, np.ndarray, np.datetime64]:
        """Targets and prices of the latest run published at or before the decision."""
        index = int(np.searchsorted(self.published, decision_time, side="right")) - 1
        if index < 0:
            return np.array([], dtype="datetime64[ns]"), np.array([]), np.datetime64("NaT", "ns")
        rows = slice(self.starts[index], self.starts[index + 1])
        return self.targets[rows], self.rrp[rows], self.published[index]


def _naive_utc(values: pd.Series) -> np.ndarray:
    return pd.DatetimeIndex(values).tz_convert("UTC").tz_localize(None).to_numpy()


class ForecastCache:
    """Monthly parquet partitions of one region's AEMO price forecasts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.jsonl"

    def partition_path(self, table: str, region: str, month: pd.Timestamp) -> Path:
        return (
            self.root
            / "partitions"
            / f"{table}_forecast"
            / f"region={region}"
            / f"year={month.year:04d}"
            / f"month={month.month:02d}.parquet"
        )

    def month(
        self,
        table: str,
        region: str,
        month: pd.Timestamp,
        *,
        fetch: Callable[[str], bytes] = download,
    ) -> pd.DataFrame:
        path = self.partition_path(table, region, month)
        if path.exists():
            return validate_forecasts(pd.read_parquet(path), table=table)
        url = archive_url(table, month)
        try:
            frame = parse_forecasts(table, fetch(url), region)
            missing = False
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            # The archive has gaps (all-run pre-dispatch for October 2022 is
            # absent). An empty partition records the gap, so the month is not
            # re-requested and every run sees the same inputs.
            when = pd.Series([], dtype=pd.DatetimeTZDtype(tz=AEST))
            frame = pd.DataFrame(
                {
                    "run_id": pd.Series([], dtype=str),
                    "published": when,
                    "target": when,
                    "rrp": pd.Series([], dtype=float),
                }
            )
            missing = True
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        record = {
            "table": f"{table}_forecast",
            "region": region,
            "month": month.strftime("%Y-%m"),
            "path": path.relative_to(self.root).as_posix(),
            "source_url": url,
            "fetched_at_utc": datetime.now(UTC).isoformat(),
            "row_count": len(frame),
            "missing_from_archive": missing,
        }
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return frame

    def fetch(
        self,
        start: object,
        end: object,
        region: str,
        *,
        fetch: Callable[[str], bytes] = download,
    ) -> dict[str, ForecastRuns]:
        """Forecast runs from the archive months covering ``[start, end)``.

        The pre-dispatch archive is organised by trading day, which starts at
        04:00, so the first hours of ``start``'s month are in the previous
        month's file. Those hours are never a decision time here: the first
        decision reads forecasts at least three weeks into the warm-up month.
        """
        first = pd.Timestamp(start).tz_localize(None).to_period("M").start_time
        last = (pd.Timestamp(end).tz_localize(None) - pd.Timedelta(minutes=5)).to_period(
            "M"
        ).start_time
        months = list(pd.date_range(first, last, freq="MS"))
        return {
            table: ForecastRuns.from_frame(
                # A run at a month boundary can appear in both months' files.
                pd.concat(
                    [self.month(table, region, month, fetch=fetch) for month in months],
                    ignore_index=True,
                ).drop_duplicates(["run_id", "target"])
            )
            for table in TABLES
        }


def forecast_identity(frame: pd.DataFrame) -> dict[str, object]:
    """Row count, run count and canonical checksum of one forecast partition.

    An empty partition (a month missing from AEMO's archive) has no checksum,
    so a later back-fill of the archive changes the identity and is caught.
    """
    from battery_dispatch.audit.validation import dataframe_sha256

    return {
        "row_count": len(frame),
        "run_count": int(frame["run_id"].nunique()),
        "canonical_sha256": (
            dataframe_sha256(frame, ["run_id", "target", "published", "rrp"])
            if len(frame)
            else None
        ),
    }
