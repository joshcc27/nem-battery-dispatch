"""Tables, paired comparisons and figures from a study run directory.

Everything here reads ``artifacts/artifacts/runs/<run_id>/`` as written by
:func:`battery_dispatch.study.runner.run_study` and nothing else, so a report is
regenerated from a run by one command (``battery-dispatch report``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from battery_dispatch.study.runner import trading_day_of
from battery_dispatch.study.spec import TOP_N_EXCLUDED
from battery_dispatch.study.stats import paired_comparison

PRIMARY = ("L3_aemo", "L2_aemo")
SECONDARY = (
    ("L3_profile", "L2_profile"),
    ("L2_aemo", "L2_profile"),
    ("L2_aemo", "rule_aemo"),
)
POLICY_ORDER = (
    "ceiling",
    "oracle",
    "L3_aemo",
    "L2_aemo",
    "rule_aemo",
    "L3_profile",
    "L2_profile",
    "rule_profile",
    "L2_persistence",
    "noop",
)


@dataclass
class Run:
    directory: Path
    summary: pd.DataFrame
    monthly: pd.DataFrame
    daily: pd.DataFrame
    manifest: dict

    @classmethod
    def load(cls, directory: str | Path) -> Run:
        directory = Path(directory)
        return cls(
            directory=directory,
            summary=pd.read_csv(directory / "summary.csv"),
            monthly=pd.read_csv(directory / "monthly.csv"),
            daily=pd.read_csv(directory / "daily.csv"),
            manifest=json.loads((directory / "manifest.json").read_text(encoding="utf-8")),
        )

    def trace(self, task: str) -> pd.DataFrame:
        return pd.read_parquet(self.directory / "traces" / f"{task}.parquet")

    def tasks(self, policy: str, execution: str) -> list[str]:
        rows = self.summary
        chosen = rows.loc[
            (rows["policy"] == policy) & (rows["execution"].isin([execution, "none"]))
        ]
        return chosen["task"].tolist()


def policy_table(run: Run) -> pd.DataFrame:
    """One row per policy and execution; stochastic policies averaged over seeds."""
    summary = run.summary.copy()
    numeric = summary.select_dtypes("number").columns.difference(["seed"])
    grouped = summary.groupby(["policy", "execution"])
    table = grouped[list(numeric)].mean()
    table["seeds"] = grouped["task"].count()
    table["revenue_seed_min"] = grouped["total_revenue"].min()
    table["revenue_seed_max"] = grouped["total_revenue"].max()
    table = table.reset_index()
    order = {name: i for i, name in enumerate(POLICY_ORDER)}
    table["_order"] = table["policy"].map(order).fillna(len(order))
    return table.sort_values(["_order", "execution"]).drop(columns="_order")


def daily_revenue(run: Run, policy: str, execution: str, exclude: set | None = None) -> pd.Series:
    """Revenue per trading day, the mean over seeds, optionally without some intervals."""
    series = []
    for task in run.tasks(policy, execution):
        trace = run.trace(task)
        if exclude:
            trace = trace.loc[~trace["settlementdate"].isin(exclude)]
        day = trading_day_of(trace["settlementdate"])
        series.append(trace.groupby(day)["total_revenue"].sum())
    if not series:
        raise KeyError(f"No tasks for {policy} under {execution}")
    return pd.concat(series, axis=1).mean(axis=1)


def top_intervals(run: Run, n: int) -> set:
    """The period's ``n`` highest-price intervals."""
    trace = run.trace(
        run.tasks("noop", "none")[0] if run.tasks("noop", "none") else run.summary["task"].iloc[0]
    )
    return set(trace.nlargest(n, "rrp")["settlementdate"])


def comparisons(run: Run, execution: str) -> pd.DataFrame:
    """The predeclared primary and secondary comparisons, with spike exclusions."""
    pairs = [("primary", *PRIMARY)] + [("secondary", a, b) for a, b in SECONDARY]
    available = set(run.summary["policy"])
    rows = []
    for exclude_n in (0, *TOP_N_EXCLUDED):
        exclude = top_intervals(run, exclude_n) if exclude_n else None
        for role, a, b in pairs:
            if not {a, b} <= available:
                continue
            first = daily_revenue(run, a, execution, exclude)
            second = daily_revenue(run, b, execution, exclude)
            result = paired_comparison(first.to_numpy(), second.to_numpy())
            rows.append(
                {
                    "role": role,
                    "comparison": f"{a} - {b}",
                    "execution": execution,
                    "excluded_top_intervals": exclude_n,
                    **result.as_dict(),
                }
            )
    return pd.DataFrame(rows)


def execution_comparisons(run: Run) -> pd.DataFrame:
    """What hourly re-pricing adds over fixed daily bands, policy by policy."""
    rows = []
    executions = set(run.summary["execution"])
    if not {"bands", "fixed_bands"} <= executions:
        return pd.DataFrame()
    for policy in POLICY_ORDER:
        if not run.tasks(policy, "bands") or policy in ("ceiling", "noop"):
            continue
        hourly = daily_revenue(run, policy, "bands")
        fixed = daily_revenue(run, policy, "fixed_bands")
        result = paired_comparison(hourly.to_numpy(), fixed.to_numpy())
        rows.append({"comparison": f"{policy}: bands - fixed_bands", **result.as_dict()})
    return pd.DataFrame(rows)


def seed_differences(run: Run, execution: str) -> pd.DataFrame:
    """Each scenario seed's own period difference, stochastic minus point forecast."""
    rows = []
    summary = run.summary.set_index("task")
    for stochastic, point in (PRIMARY, SECONDARY[0]):
        point_tasks = run.tasks(point, execution)
        if not point_tasks:
            continue
        point_revenue = summary.loc[point_tasks[0], "total_revenue"]
        for task in run.tasks(stochastic, execution):
            rows.append(
                {
                    "comparison": f"{stochastic} - {point}",
                    "seed": int(summary.loc[task, "seed"]),
                    "difference_aud": summary.loc[task, "total_revenue"] - point_revenue,
                }
            )
    return pd.DataFrame(rows)


def monthly_table(run: Run, execution: str, policies: tuple[str, ...]) -> pd.DataFrame:
    monthly = run.monthly.loc[run.monthly["execution"].isin([execution, "none"])]
    monthly = monthly.loc[monthly["policy"].isin(policies)]
    table = monthly.groupby(["month", "policy"])["total_revenue"].mean().unstack("policy")
    return table[[p for p in policies if p in table.columns]]


def monthly_uplift(run: Run, execution: str, stochastic: str, point: str) -> pd.DataFrame:
    monthly = run.monthly.loc[run.monthly["execution"] == execution]
    point_rev = monthly.loc[monthly["policy"] == point].set_index("month")["total_revenue"]
    seeds = monthly.loc[monthly["policy"] == stochastic].pivot_table(
        index="month", columns="seed", values="total_revenue"
    )
    uplift = seeds.sub(point_rev, axis=0)
    return pd.DataFrame(
        {"mean": uplift.mean(axis=1), "min": uplift.min(axis=1), "max": uplift.max(axis=1)}
    )


def case_day(run: Run, execution: str) -> pd.Timestamp:
    """The trading day with the largest absolute primary difference: chosen mechanically."""
    a = daily_revenue(run, PRIMARY[0], execution)
    b = daily_revenue(run, PRIMARY[1], execution)
    return (a - b).abs().idxmax()


# ---------------------------------------------------------------------------
# Figures. Static images for a repository release: thin marks, one axis per
# panel, a legend for every multi-series panel, muted chrome, and categorical
# colours in a fixed order that follows the policy, never its rank.

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
POLICY_COLOURS = {
    "L2_aemo": "#2a78d6",  # slot 1, blue
    "L3_aemo": "#eb6834",  # slot 2, orange
    "L2_profile": "#1baf7a",  # slot 3, aqua
    "rule_aemo": "#eda100",  # slot 4, yellow
}
REFERENCE_COLOUR = MUTED  # the ceiling and oracle are references, not series
POSITIVE = "#2a78d6"  # diverging pair: blue for gains
NEGATIVE = "#e34948"  # and red for losses
LABELS = {
    "ceiling": "Ceiling (whole-period LP)",
    "oracle": "Oracle (rolling, realised prices)",
    "L3_aemo": "Stochastic, AEMO",
    "L2_aemo": "Point forecast, AEMO",
    "rule_aemo": "Rule, AEMO",
    "L3_profile": "Stochastic, profile",
    "L2_profile": "Point forecast, profile",
    "rule_profile": "Rule, profile",
    "L2_persistence": "Point forecast, persistence",
    "noop": "No operation",
}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)


def _text(text: str) -> str:
    """Escape dollar signs, which matplotlib otherwise reads as maths."""
    return text.replace("$", r"\$")


def _legend_above(ax) -> None:
    ax.legend(
        frameon=False,
        fontsize=8.5,
        labelcolor=INK_2,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncols=2,
        borderaxespad=0.2,
    )


def _money(value: float, _pos: object = None) -> str:
    magnitude = abs(value)
    sign = "-" if value < 0 else ""
    if magnitude >= 1e6:
        return f"{sign}A${magnitude / 1e6:.1f}M"
    if magnitude >= 1e3:
        return f"{sign}A${magnitude / 1e3:.0f}K"
    return f"{sign}A${magnitude:.0f}"


def figure_monthly(run: Run, execution: str, path: Path) -> None:
    """Monthly revenue by policy, and the stochastic policy's monthly uplift."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    policies = ("ceiling", "L3_aemo", "L2_aemo", "L2_profile", "rule_aemo")
    table = monthly_table(run, execution, policies)
    uplift = monthly_uplift(run, execution, *PRIMARY)
    months = [pd.Period(m).strftime("%b %y") for m in table.index]
    x = np.arange(len(months))
    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(9, 6.6),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 2]},
        facecolor=SURFACE,
    )
    for ax in (top, bottom):
        _style(ax)
    top.plot(
        x,
        table["ceiling"],
        color=REFERENCE_COLOUR,
        linewidth=2,
        linestyle=(0, (1, 2)),
        label=LABELS["ceiling"] + ", trace slice",
    )
    for policy in policies[1:]:
        if policy not in table:
            continue
        top.plot(
            x,
            table[policy],
            color=POLICY_COLOURS[policy],
            linewidth=2,
            solid_capstyle="round",
            label=LABELS[policy],
            marker="o",
            markersize=4,
            markeredgecolor=SURFACE,
            markeredgewidth=1.5,
        )
    top.yaxis.set_major_formatter(FuncFormatter(_money))
    top.set_ylabel("Net revenue per month", color=INK_2, fontsize=9)
    top.legend(
        frameon=False,
        fontsize=8.5,
        labelcolor=INK_2,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncols=3,
        borderaxespad=0.2,
    )
    top.set_title(
        "Monthly net revenue under fixed daily bands"
        if execution == "fixed_bands"
        else f"Monthly net revenue ({execution})",
        color=INK,
        fontsize=11,
        loc="left",
        pad=46,
    )
    colours = [POSITIVE if v >= 0 else NEGATIVE for v in uplift["mean"]]
    bottom.bar(x, uplift["mean"], width=0.5, color=colours)
    bottom.vlines(x, uplift["min"], uplift["max"], color=INK_2, linewidth=1)
    bottom.axhline(0, color=AXIS, linewidth=1)
    bottom.yaxis.set_major_formatter(FuncFormatter(_money))
    bottom.set_ylabel("Stochastic − point, AEMO", color=INK_2, fontsize=9)
    bottom.set_title(
        "Realised stochastic uplift by month: seed mean, with seed range",
        color=INK,
        fontsize=10,
        loc="left",
    )
    bottom.set_xticks(x, months)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def figure_ceiling_share(run: Run, path: Path) -> None:
    """Share of the period's ceiling kept by each policy, under each execution."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    table = policy_table(run)
    table = table.loc[~table["policy"].isin(["ceiling", "noop"])]
    executions = [e for e in ("fixed_bands", "bands") if e in set(table["execution"])]
    names = {"fixed_bands": "Fixed daily bands (NEM rule)", "bands": "Hourly re-priced bands"}
    colours = {"fixed_bands": "#2a78d6", "bands": "#eb6834"}
    policies = [p for p in POLICY_ORDER if p in set(table["policy"])]
    y = np.arange(len(policies))
    height = 0.36
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(policies) + 1.4), facecolor=SURFACE)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=1)
    for i, execution in enumerate(executions):
        rows = table.loc[table["execution"] == execution].set_index("policy")
        values = [rows["share_of_ceiling"].get(p, np.nan) for p in policies]
        offset = (i - (len(executions) - 1) / 2) * (height + 0.04)
        ax.barh(y + offset, values, height=height, color=colours[execution], label=names[execution])
        for yy, value in zip(y + offset, values, strict=True):
            if np.isfinite(value):
                ax.text(value + 0.005, yy, f"{value:.1%}", va="center", fontsize=8, color=INK_2)
    ax.set_yticks(y, [LABELS.get(p, p) for p in policies], color=INK_2)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlim(0, 1.08)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK_2, loc="lower right")
    ax.set_title(
        "Share of the whole-period ceiling kept, by policy and execution",
        color=INK,
        fontsize=11,
        loc="left",
    )
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def figure_case(run: Run, execution: str, path: Path) -> pd.Timestamp:
    """Price and SOC on the trading day with the largest primary difference."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    day = case_day(run, execution)
    point = run.trace(run.tasks(PRIMARY[1], execution)[0])
    seed_task = run.tasks(PRIMARY[0], execution)[0]
    stochastic = run.trace(seed_task)
    in_day = trading_day_of(point["settlementdate"]) == day
    p = point.loc[in_day]
    s = stochastic.loc[(trading_day_of(stochastic["settlementdate"]) == day)]
    times = pd.DatetimeIndex(p["settlementdate"]).tz_convert("Australia/Brisbane")
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6), sharex=True, facecolor=SURFACE)
    for ax in (top, bottom):
        _style(ax)
    top.plot(times, p["rrp"], color=INK_2, linewidth=1.5, label="Realised price")
    top.plot(
        times,
        p["forecast_rrp"],
        color="#2a78d6",
        linewidth=1.5,
        label="AEMO forecast at the hourly decision",
    )
    top.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"A${v:,.0f}"))
    _legend_above(top)
    top.set_title(f"Trading day {day:%d %b %Y}: price", color=INK, fontsize=11, loc="left", pad=26)
    bottom.plot(
        times, p["soc_mwh"], color=POLICY_COLOURS["L2_aemo"], linewidth=2, label=LABELS["L2_aemo"]
    )
    bottom.plot(
        times,
        s["soc_mwh"],
        color=POLICY_COLOURS["L3_aemo"],
        linewidth=2,
        label=f"{LABELS['L3_aemo']} (first seed)",
    )
    bottom.set_ylabel("Stored energy, MWh", color=INK_2, fontsize=9)
    revenue_p = p["total_revenue"].sum()
    revenue_s = s["total_revenue"].sum()
    bottom.set_title(
        _text(
            f"State of charge: point forecast earns {_money(revenue_p)}, stochastic "
            f"{_money(revenue_s)} that day"
        ),
        color=INK,
        fontsize=10,
        loc="left",
        pad=26,
    )
    _legend_above(bottom)
    import matplotlib.dates as mdates

    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=times.tz))
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return day


def markdown_table(frame: pd.DataFrame, formats: dict[str, str] | None = None) -> str:
    """A GitHub-flavoured markdown table, with per-column format strings."""
    formats = formats or {}
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    align = (
        "|"
        + "|".join(
            "---:" if pd.api.types.is_numeric_dtype(frame[c]) else "---" for c in frame.columns
        )
        + "|"
    )
    lines = [header, align]
    for _, row in frame.iterrows():
        cells = []
        for column in frame.columns:
            value = row[column]
            if isinstance(value, float) and not np.isfinite(value):
                cells.append("—")
            elif column in formats:
                cells.append(formats[column].format(value))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
