"""A study declared in TOML: its period, policies, executions, seeds and settings.

The resolved declaration is hashed into the run identifier, so two settings
never share a run directory. A test-stage study must pin its protocol.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import pandas as pd

from battery_dispatch.dispatch.forecast import (
    SameTimeProfile,
)
from battery_dispatch.market.config import BatteryConfig
from battery_dispatch.market.mlf import load_loss_factor_schedule
from battery_dispatch.study.layers import LayerSettings

STAGES = ("development", "validation", "test")


@dataclass(frozen=True)
class PolicySpec:
    """How one named policy forecasts and plans."""

    forecaster: str | None  # "perfect", "persistence", "profile", "aemo"; None for noop
    planner: str = "optimise"  # "optimise", "rule", "noop" or "ceiling"
    stochastic: bool = False
    description: str = ""


POLICIES: dict[str, PolicySpec] = {
    "ceiling": PolicySpec(
        "perfect", "ceiling", description="whole-period LP, exclusivity relaxed: a ceiling"
    ),
    "oracle": PolicySpec(
        "perfect", description="rolling engine given realised prices: an oracle benchmark"
    ),
    "noop": PolicySpec(None, "noop", description="never trades"),
    "rule_profile": PolicySpec("profile", "rule", description="k cheapest/dearest hours"),
    "rule_aemo": PolicySpec("aemo", "rule", description="k cheapest/dearest hours"),
    "L2_persistence": PolicySpec("persistence", description="point forecast"),
    "L2_profile": PolicySpec("profile", description="point forecast"),
    "L2_aemo": PolicySpec("aemo", description="point forecast"),
    "L3_profile": PolicySpec("profile", stochastic=True, description="error scenarios"),
    "L3_aemo": PolicySpec("aemo", stochastic=True, description="error scenarios"),
}

# Spike and negative-price thresholds for the revenue attribution, A$/MWh.
SPIKE_PRICE = 300.0
# The headline comparison is also reported without the period's N highest-price
# intervals, so a result carried by a handful of spikes is visible.
TOP_N_EXCLUDED = (24, 120)


@dataclass(frozen=True)
class StudyConfig:
    name: str
    stage: str
    start: str
    end: str
    region: str = "SA1"
    connection_point: str = "Hornsdale 275 kV"
    loss_factor_file: str = "config/loss_factors.csv"
    policies: tuple[str, ...] = tuple(POLICIES)
    executions: tuple[str, ...] = ("fixed_bands",)
    seeds: tuple[int, ...] = (20221101,)
    settings: LayerSettings = field(default_factory=LayerSettings)
    # Wrap every forecaster's error pool so it has no history before the
    # evaluation starts (the archive-gap control experiment).
    thin_error_history: bool = False
    # A test-stage study must name the frozen protocol and pin its hash.
    protocol: str | None = None
    protocol_sha256: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        if unknown := set(self.policies).difference(POLICIES):
            raise ValueError(f"Unknown policies: {sorted(unknown)}")
        if pd.Timestamp(self.end) <= pd.Timestamp(self.start):
            raise ValueError("end must be after start")
        if self.stage == "test" and not (self.protocol and self.protocol_sha256):
            raise ValueError("A test-stage study must pin its protocol and its sha256")
        if not self.seeds:
            raise ValueError("At least one seed is required")

    def resolved(self) -> dict[str, object]:
        payload = asdict(self)
        payload["policies"] = list(self.policies)
        payload["executions"] = list(self.executions)
        payload["seeds"] = list(self.seeds)
        return payload

    @property
    def config_sha256(self) -> str:
        encoded = json.dumps(self.resolved(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def run_id(self) -> str:
        return f"{self.name}-{self.config_sha256[:10]}"


def load_study(path: str | Path, **overrides: object) -> StudyConfig:
    """Read a study TOML; ``overrides`` replace top-level or ``settings`` keys."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    settings_raw = dict(raw.pop("settings", {}))
    for key in list(overrides):
        if key in {f.name for f in fields(LayerSettings)}:
            settings_raw[key] = overrides.pop(key)
    raw.update(overrides)
    known = {f.name for f in fields(LayerSettings)}
    if unknown := set(settings_raw).difference(known):
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    settings = LayerSettings(**settings_raw)
    for key in ("policies", "executions", "seeds"):
        if key in raw:
            raw[key] = tuple(raw[key])
    if unknown := set(raw).difference({f.name for f in fields(StudyConfig)}):
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    return StudyConfig(settings=settings, **raw)


def asset_for(config: StudyConfig) -> BatteryConfig:
    schedule = load_loss_factor_schedule(
        config.loss_factor_file, region=config.region, connection_point=config.connection_point
    )
    first = next(iter(schedule.table.by_financial_year.values()))
    return BatteryConfig(
        generation_loss_factor=first.generation,
        load_loss_factor=first.load,
        loss_factor_source=schedule.provenance,
        loss_factor_table=schedule.table,
        connection_point=schedule.connection_point,
        region=config.region,
    )


def warm_up_days(config: StudyConfig, asset: BatteryConfig) -> int:
    """Whole days of history the first decision and the first band design need.

    A fixed-band design plans from 12:30 two days before the period's first
    full trading day to the end of that day, about 40 hours, so its error pool
    reaches further back than an hourly decision's.
    """
    settings = config.settings
    per_day = settings.periods_per_day(asset)
    hourly = int(round(settings.horizon_hours * 60 / asset.interval_minutes))
    design = int(round(40 * 60 / asset.interval_minutes))
    steps = max(hourly, design) if "fixed_bands" in config.executions else hourly
    profile = SameTimeProfile(settings.profile_days, per_day)
    lag = settings.latency_minutes // asset.interval_minutes
    needed = settings.error_model(asset).min_history(profile, steps) + lag
    return math.ceil(needed / per_day) + 3


@dataclass(frozen=True)
class Task:
    policy: str
    execution: str
    seed: int | None

    @property
    def key(self) -> str:
        parts = [self.policy, self.execution]
        if self.seed is not None:
            parts.append(f"seed{self.seed}")
        return "__".join(parts)


def tasks_for(config: StudyConfig) -> list[Task]:
    tasks: list[Task] = []
    for policy in config.policies:
        spec = POLICIES[policy]
        if spec.planner in ("ceiling", "noop"):
            tasks.append(Task(policy, "none", None))
            continue
        for execution in config.executions:
            seeds = config.seeds if spec.stochastic else (None,)
            tasks.extend(Task(policy, execution, seed) for seed in seeds)
    return tasks


