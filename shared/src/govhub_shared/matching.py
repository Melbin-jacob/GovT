"""Similarity and optimal one-to-one assignment (plain code, deterministic).

Moved from the rulebook's clause diff so the assessment engine's drafting harness matches
new controls with the very same code (Hungarian assignment on word-token similarity).
"""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

__all__ = ["containment", "hungarian_max", "similarity"]


def similarity(a: Sequence[str], b: Sequence[str]) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def containment(part: Sequence[str], whole: Sequence[str]) -> float:
    """Share of ``part``'s tokens that appear, in order, in ``whole``."""
    if not part:
        return 0.0
    blocks = SequenceMatcher(None, part, whole, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(part)


def hungarian_max(scores: list[list[float]]) -> list[tuple[int, int]]:
    """Maximum-weight one-to-one assignment for a rectangular matrix (rows x cols).

    Classic O(n^2 m) shortest-augmenting-path algorithm on costs ``1 - score``.
    Returns (row, col) pairs, one per row if rows <= cols (else one per col).
    """
    if not scores or not scores[0]:
        return []
    transposed = len(scores) > len(scores[0])
    matrix = [list(r) for r in zip(*scores, strict=True)] if transposed else scores
    n, m = len(matrix), len(matrix[0])
    cost = [[1.0 - matrix[i][j] for j in range(m)] for i in range(n)]
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    pairs = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j]]
    if transposed:
        pairs = [(c, r) for r, c in pairs]
    return sorted(pairs)
