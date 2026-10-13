"""The predeclared paired comparison between two policies.

Revenue is compared by trading day. Continuous SOC makes consecutive days
dependent, since what one day leaves in store is what the next day sells, so
the uncertainty of the mean daily difference comes from a circular moving-block
bootstrap with week-long blocks rather than from treating days as independent.

The decision rule, fixed before the test period was run (docs/PROTOCOL.md):

- **win** if the 95% interval of the mean daily difference lies above zero;
- **loss** if it lies below zero;
- **inconclusive** otherwise.

The interval describes day-to-day variation in this period's realised
differences. It is not a confidence interval for future market revenue, and
the spread across scenario seeds, reported separately, is sampling variation
of the policy itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

BLOCK_DAYS = 7
DRAWS = 10_000
BOOTSTRAP_SEED = 20240601
LEVEL = 0.95


@dataclass(frozen=True)
class PairedResult:
    days: int
    mean_daily_difference: float
    total_difference: float
    ci_low: float
    ci_high: float
    share_of_draws_at_or_below_zero: float
    days_a_ahead: int
    verdict: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def block_bootstrap_means(
    values: np.ndarray, *, block: int = BLOCK_DAYS, draws: int = DRAWS, seed: int = BOOTSTRAP_SEED
) -> np.ndarray:
    """Means of ``draws`` circular moving-block resamples of ``values``."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        raise ValueError("No values to resample")
    block = max(1, min(block, n))
    blocks = -(-n // block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(draws, blocks))
    index = (starts[:, :, np.newaxis] + np.arange(block)) % n
    index = index.reshape(draws, -1)[:, :n]
    return values[index].mean(axis=1)


def verdict(low: float, high: float) -> str:
    if low > 0:
        return "win"
    if high < 0:
        return "loss"
    return "inconclusive"


def paired_comparison(
    a: np.ndarray,
    b: np.ndarray,
    *,
    block: int = BLOCK_DAYS,
    draws: int = DRAWS,
    seed: int = BOOTSTRAP_SEED,
    level: float = LEVEL,
) -> PairedResult:
    """Policy ``a`` against policy ``b`` on the same trading days."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("Daily series must cover the same days")
    difference = a - b
    means = block_bootstrap_means(difference, block=block, draws=draws, seed=seed)
    tail = (1.0 - level) / 2.0
    low, high = np.quantile(means, [tail, 1.0 - tail])
    return PairedResult(
        days=len(difference),
        mean_daily_difference=float(difference.mean()),
        total_difference=float(difference.sum()),
        ci_low=float(low),
        ci_high=float(high),
        share_of_draws_at_or_below_zero=float(np.mean(means <= 0)),
        days_a_ahead=int(np.sum(difference > 0)),
        verdict=verdict(float(low), float(high)),
    )
