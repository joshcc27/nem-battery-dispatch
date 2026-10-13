"""A small scenario tree: decisions shared while scenarios share their history.

The two-stage model behind layer 3 shares only the committed hour across
scenarios; after it, each scenario's dispatch is planned as if that scenario's
whole future were known. This is distinct from leaking realised prices into a
decision, but it is optimistic about future information, and it can overvalue
holding energy for a spike that only some scenarios contain.

A scenario tree removes that optimism. Here it is built from the same
bootstrapped fan of price paths by bundling: up to the first split every path
is replaced by the fan's mean; at each split every bundle divides into
``branching`` sub-bundles of equal size, ranked by their mean price over the
rest of the look-ahead; within each bundle the paths are replaced by the
bundle's mean until the next split. After the last split each sub-bundle keeps
its own mean path. The decision for an interval is made at the start of its
committed block, and two scenarios share it exactly when their paths agree on
every interval before that block: the labels are computed from the bundled
paths themselves, so the tree cannot share a decision between scenarios the
decision time could tell apart, nor split one between scenarios it could not.
A bundle that diverges at a split is therefore still one decision for the
block that starts there, because that block's price has not yet been seen.

Comparing the two-stage model with the tree **on the same bundled paths**
isolates the effect of the information assumption: the price scenarios, the
error pool and everything else are identical.
"""

from __future__ import annotations

import numpy as np


def parse_splits(text: str, interval_minutes: int) -> tuple[tuple[int, int], ...]:
    """``"60:2,240:2,720:2"`` (minutes:branching) as (step, branching) pairs."""
    splits = []
    for part in text.split(","):
        minutes, _, branching = part.strip().partition(":")
        if int(minutes) % interval_minutes:
            raise ValueError("Split times must be whole intervals")
        splits.append((int(minutes) // interval_minutes, int(branching)))
    steps = [step for step, _ in splits]
    if steps != sorted(steps) or len(set(steps)) != len(steps) or min(steps) < 1:
        raise ValueError("Split times must be positive and increasing")
    if min(branching for _, branching in splits) < 2:
        raise ValueError("Each split must branch at least two ways")
    return tuple(splits)


def bundle_to_tree(
    paths: np.ndarray, splits: tuple[tuple[int, int], ...], block: int
) -> tuple[np.ndarray, np.ndarray]:
    """Tree-consistent paths and decision labels, in a canonical scenario order.

    Returns ``(bundled, labels)``, both ``(scenarios, steps)``. Scenarios are
    reordered so that every bundle is a contiguous block, which makes the
    labels depend only on the shape and the splits, so one model serves every
    decision. Splits at or beyond the look-ahead are ignored; ``block`` is the
    committed block, and every split must fall on one of its boundaries.
    """
    paths = np.asarray(paths, dtype=float)
    count, steps = paths.shape
    if any(split % block for split, _ in splits):
        raise ValueError("Splits must fall on committed-block boundaries")
    groups = [np.arange(count)]
    segments: list[tuple[int, int, list[np.ndarray]]] = []
    start = 0
    for split, branching in [*[s for s in splits if s[0] < steps], (steps, 1)]:
        segments.append((start, split, groups))
        if split == steps:
            break
        divided: list[np.ndarray] = []
        for members in groups:
            ranking = paths[members, split:].mean(axis=1)
            ordered = members[np.argsort(ranking, kind="stable")]
            divided.extend(part for part in np.array_split(ordered, branching) if len(part))
        groups = divided
        start = split
    order = np.concatenate(groups)
    position = np.empty(count, dtype=int)
    position[order] = np.arange(count)
    bundled = np.empty_like(paths)
    for first, last, members_list in segments:
        for members in members_list:
            bundled[position[members], first:last] = paths[members, first:last].mean(axis=0)
    return bundled, history_labels(bundled, block)


def history_labels(paths: np.ndarray, block: int) -> np.ndarray:
    """Label each scenario at each interval by its history before that block."""
    count, steps = paths.shape
    labels = np.zeros((count, steps), dtype=np.int64)
    for known in range(block, steps, block):
        _, inverse = np.unique(paths[:, :known], axis=0, return_inverse=True)
        # Number the histories in scenario order, so labels are canonical.
        _, first_seen = np.unique(inverse, return_index=True)
        rank = np.argsort(np.argsort(first_seen))
        labels[:, known : known + block] = rank[inverse.ravel()][:, np.newaxis]
    return labels


def two_stage_labels(count: int, steps: int, shared: int) -> np.ndarray:
    """Labels for the two-stage model: one decision for ``shared`` steps, then each alone."""
    labels = np.repeat(np.arange(count)[:, np.newaxis], steps, axis=1)
    labels[:, :shared] = 0
    return labels


def is_nonanticipative(paths: np.ndarray, labels: np.ndarray, block: int) -> bool:
    """Whether labels share exactly the decisions whose observed history is equal.

    The decision for interval ``t`` is made at the start of its block, when
    prices before that block are known. Two scenarios must share it if, and
    only if, their paths agree on every earlier interval.
    """
    count, steps = paths.shape
    for t in range(steps):
        known = (t // block) * block
        for a in range(count):
            for b in range(a + 1, count):
                same_history = np.array_equal(paths[a, :known], paths[b, :known])
                if same_history != (labels[a, t] == labels[b, t]):
                    return False
    return True
