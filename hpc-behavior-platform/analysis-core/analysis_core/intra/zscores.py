"""Z-scores: compare each node's band-isolated mrDMD amplitude against the
metric's own baseline, across nodes (paper Sec III-B-2/3).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from analysis_core.intra.baseline import default_baseline, user_baseline
from analysis_core.intra.mrdmd import (
    MIN_FINEST_WINDOW,
    Mode,
    compute_max_level,
    isolate_band,
    mrdmd_spectrum,
    named_bands,
)


@dataclass
class ZResult:
    z: np.ndarray  # (n_nodes, n_metrics)
    metrics: list[str]
    baseline_windows: dict[str, slice]  # metric -> baseline window used
    band: str
    segment_used: dict[str, slice]  # metric -> segment mrDMD actually ran on
    degenerate_metrics: list[str] = field(default_factory=list)  # std(a_B) == 0


def _band_amplitude(n_nodes: int, modes: list[Mode], f_low: float, f_high: float) -> np.ndarray:
    """Band-aggregated amplitude per node: sum of |amplitude| over modes
    whose frequency falls in [f_low, f_high).
    """
    retained = isolate_band(modes, f_low, f_high)
    if not retained:
        return np.zeros(n_nodes)
    return np.sum([mode.amplitude for mode in retained], axis=0)


def _common_mode_var(modes: list[Mode], f_low: float, f_high: float, max_level: int) -> float:
    """Variance of the band amplitude shared by all nodes.

    A node's amplitude in one mrDMD window is |mode_i| * |b|, and |b| is
    common to every node, so window-to-window estimation noise in |b| shifts
    all nodes together. Cross-node std(a_B) never sees it: on near-identical
    nodes it is a fraction of that noise, and a no-fault series reads |z| ~ 3
    on every node. Per level, estimate the noise as the variance of the
    per-window node-mean amplitude across the baseline's windows (no band
    modes = 0); a node total sums 2**level windows of each level.
    """
    window_means: dict[int, dict[tuple[float, float], float]] = {}
    for mode in isolate_band(modes, f_low, f_high):
        level = window_means.setdefault(mode.level, {})
        level[mode.window] = level.get(mode.window, 0.0) + float(mode.amplitude.mean())

    total = 0.0
    for level in range(1, max_level + 1):  # level 0 is a single window: no spread to measure
        n_windows = 2**level
        means = list(window_means.get(level, {}).values())
        means += [0.0] * (n_windows - len(means))
        total += n_windows * float(np.var(means, ddof=1))
    return total


def compute_zscores(
    tensor_by_metric: dict[str, np.ndarray],
    band: str,
    resolution_s: float,
    baseline_windows: dict[str, tuple[int, int]] | None = None,
    max_cycles: int = 1,
    min_finest_window: int = MIN_FINEST_WINDOW,
) -> ZResult:
    """tensor_by_metric: metric name -> S (n_nodes, T) raw sub-tensor for one
    cluster. baseline_windows, if given, overrides default_baseline per
    metric with a user-brushed [t0, t1) window.

    max_cycles and min_finest_window tune mrDMD's frequency reach: modes
    faster than max_cycles cycles per finest window are never retained, so
    short impulses (a few samples wide) are only detectable with a smaller
    min_finest_window and/or larger max_cycles than the defaults.
    """
    metrics = list(tensor_by_metric.keys())
    if not metrics:
        return ZResult(z=np.zeros((0, 0)), metrics=[], baseline_windows={}, band=band, segment_used={})

    n_nodes = next(iter(tensor_by_metric.values())).shape[0]
    bands = named_bands(resolution_s)
    f_low, f_high = bands[band]

    z = np.zeros((n_nodes, len(metrics)))
    baseline_windows_used: dict[str, slice] = {}
    segment_used: dict[str, slice] = {}
    degenerate: list[str] = []

    for m_i, metric in enumerate(metrics):
        S = tensor_by_metric[metric]

        if baseline_windows and metric in baseline_windows:
            t0, t1 = baseline_windows[metric]
            window = slice(t0, t1)
            B = user_baseline(S, t0, t1)
        else:
            window, B = default_baseline(S)
        baseline_windows_used[metric] = window

        modes_S, seg_S = mrdmd_spectrum(S, max_cycles=max_cycles, min_finest_window=min_finest_window)
        modes_B, _ = mrdmd_spectrum(B, max_cycles=max_cycles, min_finest_window=min_finest_window)
        segment_used[metric] = seg_S
        a_S = _band_amplitude(n_nodes, modes_S, f_low, f_high)
        a_B = _band_amplitude(n_nodes, modes_B, f_low, f_high)

        std_B = a_B.std()
        if std_B == 0:
            z[:, m_i] = 0.0
            degenerate.append(metric)
        else:
            max_level = compute_max_level(B.shape[1], min_finest_window)
            # a_S and a_B each carry the common-mode noise: their difference twice
            common_var = _common_mode_var(modes_B, f_low, f_high, max_level)
            z[:, m_i] = (a_S - a_B.mean()) / np.sqrt(std_B**2 + 2 * common_var)

    return ZResult(
        z=z,
        metrics=metrics,
        baseline_windows=baseline_windows_used,
        band=band,
        segment_used=segment_used,
        degenerate_metrics=degenerate,
    )
