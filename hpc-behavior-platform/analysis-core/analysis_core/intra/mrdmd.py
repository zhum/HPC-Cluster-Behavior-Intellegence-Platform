"""Multi-resolution DMD with frequency-band isolation (paper Sec III-B-2).

Runs per-metric on the RAW (n_nodes, T) sub-tensor for one cluster -- unlike
Phase 3's MulTiDR, this stage does not touch the DR embedding at all.

pydmd's MrDMD wrapper has a real quirk worth documenting: its inherited
`.fitted`/`.amplitudes` properties check `self.operator`, which MrDMD (a
composite of many per-level, per-window single-level DMD fits) never sets --
so `mrdmd.amplitudes` silently returns None even after a successful fit. The
per-(level, leaf) sub-DMD objects in `mrdmd.dmd_tree` are the real single-level
DMD instances and have working `.amplitudes`/`.frequency`/`.modes`, so this
module reads mode data from there directly instead of the top-level wrapper.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydmd import DMD, MrDMD

MIN_FINEST_WINDOW = 32

# (name -> period in seconds). Kept ascending by period (descending by
# frequency) since band-edge computation below relies on that ordering.
NAMED_BAND_PERIODS_S: dict[str, float] = {
    "5m": 5 * 60,
    "30m": 30 * 60,
    "2h": 2 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400,
}


@dataclass
class Mode:
    level: int
    window: tuple[float, float]  # (t0, tend) in timestep units
    omega: complex  # log(eigenvalue), rad/timestep (dt = 1 timestep) -- continuous-time analog
    amplitude: np.ndarray  # (n_nodes,) per-node contribution magnitude
    power: float  # sum of amplitude**2 across nodes, a mode-energy scalar


def compute_max_level(T: int, min_window: int = MIN_FINEST_WINDOW) -> int:
    """Largest max_level such that the finest level's window (T / 2**level)
    is still >= min_window timesteps.
    """
    if T < min_window:
        return 0
    return max(0, int(np.floor(np.log2(T / min_window))))


def prepare_series(S: np.ndarray, max_gap: int = 3) -> tuple[np.ndarray, slice]:
    """Interpolate NaN runs of length <= max_gap per node (linear, using that
    node's own surrounding valid points). If any longer gap remains at a
    timestep for ANY node, mrDMD can't run on the full series (DMD needs a
    complete, gap-free snapshot matrix) -- return the longest contiguous
    stretch of timesteps where every node is valid instead, alongside the
    slice into the original T axis (the caller/UI must show which segment
    was actually used).
    """
    n, T = S.shape
    filled = S.copy()

    for i in range(n):
        row = filled[i]
        nan_mask = np.isnan(row)
        if not nan_mask.any():
            continue
        valid_idx = np.where(~nan_mask)[0]
        if len(valid_idx) < 2:
            continue
        nan_idx = np.where(nan_mask)[0]
        # group nan_idx into contiguous runs
        breaks = np.where(np.diff(nan_idx) != 1)[0] + 1
        runs = np.split(nan_idx, breaks) if len(nan_idx) else []
        for run in runs:
            if 0 < len(run) <= max_gap:
                row[run] = np.interp(run, valid_idx, row[valid_idx])
        filled[i] = row

    still_nan_any_node = np.isnan(filled).any(axis=0)
    if not still_nan_any_node.any():
        return filled, slice(0, T)

    valid = ~still_nan_any_node
    best_start, best_len, cur_start = 0, 0, None
    for t in range(T):
        if valid[t]:
            if cur_start is None:
                cur_start = t
            if t - cur_start + 1 > best_len:
                best_len = t - cur_start + 1
                best_start = cur_start
        else:
            cur_start = None

    segment = slice(best_start, best_start + best_len)
    return filled[:, segment], segment


def mrdmd_spectrum(
    S: np.ndarray, max_cycles: int = 1, min_finest_window: int = MIN_FINEST_WINDOW
) -> tuple[list[Mode], slice]:
    """S: (n_nodes, T) raw time series for one metric, one cluster.

    Returns (modes, segment_used) -- segment_used is the slice of the
    original T axis that mrDMD actually ran on (see prepare_series).
    """
    S_used, segment = prepare_series(S)
    n_nodes, T = S_used.shape

    if T < min_finest_window or n_nodes == 0:
        return [], segment

    max_level = compute_max_level(T, min_finest_window)
    dmd = DMD(svd_rank=-1)
    mrdmd = MrDMD(dmd, max_level=max_level, max_cycles=max_cycles)
    mrdmd.fit(S_used)

    modes: list[Mode] = []
    for level in mrdmd.dmd_tree.levels:
        n_leaves = 2**level
        for leaf in range(n_leaves):
            sub = mrdmd.dmd_tree[level, leaf]
            n_modes = sub.modes.shape[1]
            if n_modes == 0:
                continue
            window = mrdmd.partial_time_interval(level, leaf)
            for mode_i in range(n_modes):
                eig = sub.eigs[mode_i]
                b = sub.amplitudes[mode_i]
                mode_shape = sub.modes[:, mode_i]
                amplitude = np.abs(mode_shape) * np.abs(b)
                omega = np.log(eig) if eig != 0 else complex(0, 0)
                modes.append(
                    Mode(
                        level=level,
                        window=(window["t0"], window["tend"]),
                        omega=omega,
                        amplitude=amplitude,
                        power=float(np.sum(amplitude**2)),
                    )
                )

    return modes, segment


def isolate_band(modes: list[Mode], f_low: float, f_high: float) -> list[Mode]:
    """Keep modes whose cyclic frequency |Im(omega)| / (2*pi) (cycles per
    timestep) falls in [f_low, f_high).
    """
    kept = []
    for mode in modes:
        freq = abs(mode.omega.imag) / (2 * np.pi)
        if f_low <= freq < f_high:
            kept.append(mode)
    return kept


def named_bands(resolution_s: float) -> dict[str, tuple[float, float]]:
    """Named frequency bands (cycles/timestep) for the given grid resolution.

    Band edges are the geometric mean (in Hz) between each named period and
    its neighbor -- i.e. bands partition frequency space at the midpoint (on
    a log scale) between adjacent named periods, like octave bands. The
    fastest band ("5m") is unbounded above; the slowest ("7d") is unbounded
    below (down to DC). Frequencies are converted from Hz to cycles/timestep
    by multiplying by resolution_s (Hz * seconds/sample = cycles/sample).
    """
    names_by_period = sorted(NAMED_BAND_PERIODS_S, key=lambda k: NAMED_BAND_PERIODS_S[k])
    freqs_hz = [1.0 / NAMED_BAND_PERIODS_S[name] for name in names_by_period]  # descending

    edges_hz = [np.sqrt(freqs_hz[i] * freqs_hz[i + 1]) for i in range(len(freqs_hz) - 1)]

    bands: dict[str, tuple[float, float]] = {}
    for i, name in enumerate(names_by_period):
        f_high_hz = edges_hz[i - 1] if i > 0 else float("inf")
        f_low_hz = edges_hz[i] if i < len(edges_hz) else 0.0
        f_high = f_high_hz * resolution_s if f_high_hz != float("inf") else float("inf")
        f_low = f_low_hz * resolution_s
        bands[name] = (f_low, f_high)
    return bands
