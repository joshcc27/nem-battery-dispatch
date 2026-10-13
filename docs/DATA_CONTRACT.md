# Input data contract

The model settles against AEMO five-minute `DISPATCHPRICE` data only; AEMO's
published price forecasts are an input to the forecast layers, not to
settlement (see [AEMO forecast contract](#aemo-forecast-contract)). A study
period is expressed as physical boundaries `[start, end)`, while AEMO
timestamps are interval-ending, so the required observations are
`(start, end]` in fixed UTC+10 (`AEST`). The timestamp at 1 July 00:00 belongs to the financial year
that has just ended.

## Required price fields

| Field | Contract |
|---|---|
| `SETTLEMENTDATE` | Parseable timestamp; converted to fixed UTC+10 |
| `REGIONID` | Requested NEM region; part of the unique key |
| `RRP` | Numeric AUD/MWh, inside the dated market floor/cap |
| `INTERVENTION` | Numeric; only `0` is retained |

After intervention filtering, `(settlementdate, regionid)` must be unique.
There must be exactly one observation every five minutes for every requested
region, with no nulls, gaps, or timestamps outside the requested range. Unknown
financial years fail because no unverified market cap is carried forward.

## Cache and provenance

The cache stores one parquet file per table, region and physical calendar
month under `data/cache/partitions`. A monthly partition contains interval
ends in `(month_start, next_month_start]`; this convention prevents midnight
month-boundary gaps. Missing partitions are downloaded through NEMOSIS and
recorded in `data/cache/manifest.jsonl`. Existing partitions are immutable
cache hits and require no network access.

One committed manifest per input month, in
[`data/manifests/`](../data/manifests/), covers the two reference months and
their two warm-up months. Each records source, exact boundaries, partition row
counts, quality checks, the rationale for the period, and canonical checksums
of its prices and of its AEMO forecasts, without committing the market-data
files themselves. `battery-dispatch verify-reference` re-derives every one of those
values from a fresh fetch and fails if any differs, so the manifest is an
enforced contract rather than a description.

## AEMO forecast contract

The AEMO forecast layers read two MMSDM archive tables, fetched directly from
NEMWeb by `src/battery_dispatch/market/aemo_forecasts.py`:

| Table | Archive folder | Runs | Each run forecasts |
|---|---|---|---|
| `PREDISPATCHPRICE` | `PREDISP_ALL_DATA` | every 30 minutes | 30-minute periods to the end of the next trading day |
| `P5MIN_REGIONSOLUTION` | `DATA` | every 5 minutes | the next twelve 5-minute intervals |

Only the requested region's `INTERVENTION = 0` rows are kept, as `run_id`,
`published`, `target` and `rrp`. A run's `published` time is the latest
`LASTCHANGED` of any of its rows, and a forecaster may use a run only once it
is published: at a decision time, the latest run published at or before it.
After filtering, `(run_id, target)` must be unique, every run must have one
publication time, and every forecast price must lie inside the dated market
floor and cap.

The cache stores one parquet file per table, region and archive month under
`data/cache/partitions/{predispatch,p5min}_forecast`. Pre-dispatch archive
months are trading-day months, which start at 04:00. NEMSEER is the usual
client for these files but pins `xarray` below what linopy requires, so it is
not used.

**October 2022 is missing from the all-runs pre-dispatch archive.** Only the
`_D_` file, which keeps the final forecast for each period, exists for that
month, and it cannot be used without leaking later information. The gap is
stored as an empty partition and pinned in
[`data/manifests/sa1_2022-10.json`](../data/manifests/sa1_2022-10.json) with a
zero row count, so a later back-fill of the archive is detected rather than
silently changing results. Its consequences are set out in
[LIMITATIONS.md](LIMITATIONS.md#forecast-driven-policies).

## Loss-factor contract

`config/loss_factors.csv` is a version-controlled schedule keyed by region,
connection point and financial year. Every row must include separate generation
and load DUIDs, separate positive MLFs, an HTTPS source URL, title and page.
Duplicate financial years, inconsistent DUIDs or missing provenance fail at
load time. A run hash includes the selected asset configuration and the summary
records the loss-factor file SHA-256.

## Study coverage and inputs

Before any policy is run on a candidate period, `battery-dispatch coverage`
writes one row per month to `data/coverage/`. Each row records:

- whether every price interval is present;
- whether every interval has a configured loss factor and price cap;
- at what share of five-minute decision times an AEMO pre-dispatch run
  (60 minutes old at most) and a P5MIN run (15 minutes) were current;
- the longest gap without one.

The declared exclusion rule is written beside it. Exclusions are decided from
this file alone, before any revenue is seen.

`config/loss_factors.csv` carries FY2022-23 and FY2023-24 rows for the
Hornsdale 275 kV connection point (HPRG1/HPRL1). Both come from page 34 of
AEMO's MLF report for the year. The FY2023-24 column was read from the July
2024 version of that report. Its previous-year column reproduces the
committed FY2022-23 values, which confirms the table alignment.

Every study run records, for each month it reads, including warm-up:

- the canonical price checksum;
- both AEMO forecast tables' row counts and checksums;
- the loss-factor file's SHA-256.

## Output contract

The study runner writes `artifacts/runs/<name>-<hash>/`, where the hash is of the
resolved study configuration:

- `manifest.json` holds the configuration, the source commit and tree
  state, the environment, the input identity, every task's audit and every
  failure;
- `summary.csv` has one row per policy, execution and seed;
- `monthly.csv` and `daily.csv` slice the same continuous traces by calendar
  month and by trading day;
- `traces/` holds one settled parquet trace per task, and each fixed-band
  task's band prices by trading day.

`battery-dispatch report` turns a run into tables, figures and a
`report_manifest.json` that hashes every file it wrote.

The single-run CLI below writes two files. `dispatch_<config_hash>.csv` is the interval-level
trace: one row per five-minute interval with dispatch, SOC, prices, loss
factors, settlement components and the solver evidence for the window it came
from. `results.csv` holds one row per run, keyed by `config_hash` and upserted,
so re-running an identical configuration replaces its row rather than appending
a duplicate.

That summary row is deliberately wide — currently 67 columns. It is an **audit
record, not a report.** Alongside the headline revenue and cycling figures it
carries every value the acceptance gates were evaluated against: energy-balance
residuals, the exclusivity fraction, solver status, gaps and bounds per run,
completed-cycle evidence, the SOC decile distribution, and the price-audit
counts and checksum. Keeping them on one row means a stored result can be
re-checked without re-running it, and without joining two files. Read
`docs/RESEARCH_NOTE.md` for the figures that are meant to be quoted.
