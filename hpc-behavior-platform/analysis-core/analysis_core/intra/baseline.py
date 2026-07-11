"""Baseline extraction (paper Sec III-B-2, verbatim algorithm): simulate
'normal' behavior by tiling the longest quiet window across the full series.
"""
from __future__ import annotations

import numpy as np


def _tile_window(S: np.ndarray, window: slice, T: int) -> np.ndarray:
    segment = S[:, window]
    w = segment.shape[1]
    if w == 0:
        return np.zeros_like(S)
    reps = int(np.ceil(T / w))
    return np.tile(segment, (1, reps))[:, :T]


def default_baseline(S: np.ndarray) -> tuple[slice, np.ndarray]:
    """1) IQR (Q1, Q3) of ALL measurements across all nodes.
       2) Longest contiguous time window where every node's value lies
          within [Q1, Q3] at every timestep in the window.
       3) Tile that window across the full series length -> B (n_nodes, T).

    Returns (window, B); window is also handed back for UI display/brush
    adjustment (paper Fig. 3).
    """
    n, T = S.shape
    q1, q3 = np.nanpercentile(S, [25, 75])
    in_range = np.all((S >= q1) & (S <= q3), axis=0)  # (T,)

    best_start, best_len, cur_start = 0, 0, None
    for t in range(T):
        if in_range[t]:
            if cur_start is None:
                cur_start = t
            if t - cur_start + 1 > best_len:
                best_len = t - cur_start + 1
                best_start = cur_start
        else:
            cur_start = None

    window = slice(best_start, best_start + best_len) if best_len > 0 else slice(0, T)
    B = _tile_window(S, window, T)
    return window, B


def user_baseline(S: np.ndarray, t0: int, t1: int) -> np.ndarray:
    """Tile a user-brushed window [t0, t1) instead of the statistically
    derived default -- backs the baseline-adjust interaction (paper Fig. 3).
    """
    n, T = S.shape
    return _tile_window(S, slice(t0, t1), T)
