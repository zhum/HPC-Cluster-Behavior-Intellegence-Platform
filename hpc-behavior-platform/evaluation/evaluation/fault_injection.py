"""Fault-injection tests (Phase 7 item 2): scripted perturbations on
synthetic nodes -> assert the injected nodes surface in the top-decile |z|
for the right metrics/bands. Also restates the Phase 4 shipping gate
(recall >= 0.9 at |z| >= 3) as a directly checkable function here.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from analysis_core.intra.zscores import compute_zscores

# a node must exceed this magnitude to count as "flagged" -- the Phase 4 gate.
Z_THRESHOLD = 3.0


def _phase_diverse_baseline(n_nodes: int, T: int, period_samples: float, seed: int = 0) -> np.ndarray:
    """Shared-frequency, per-node-phase-diverse oscillation -- required for
    plain DMD to represent rotational dynamics at all (see analysis-core's
    mrdmd tests: identical waveforms across nodes are spatially rank-1).
    """
    rng = np.random.default_rng(seed)
    t = np.arange(T)
    phases = rng.uniform(0, 2 * np.pi, n_nodes)
    S = np.zeros((n_nodes, T))
    for i in range(n_nodes):
        S[i] = np.sin(2 * np.pi * t / period_samples + phases[i]) + rng.normal(0, 0.05, T)
    return S


def inject_cpu_steal(S: np.ndarray, affected: list[int], start: int, end: int, amplitude: float = 8.0) -> np.ndarray:
    """CPU-steal: bursty high-frequency interference during a window (a
    noisy-neighbor / hypervisor contention signature)."""
    out = S.copy()
    length = end - start
    burst = amplitude * np.sin(2 * np.pi * np.arange(length) / 4)
    for i in affected:
        out[i, start:end] += burst
    return out


def inject_memory_leak_ramp(S: np.ndarray, affected: list[int], start: int, slope: float = 0.4) -> np.ndarray:
    """Memory leak: monotonic ramp from `start` onward -- low-frequency
    (near-DC) energy, should surface in the slower bands."""
    out = S.copy()
    T = S.shape[1]
    ramp = np.zeros(T)
    ramp[start:] = slope * np.arange(T - start)
    for i in affected:
        out[i] += ramp
    return out


def inject_ib_error_burst(S: np.ndarray, affected: list[int], burst_at: int, amplitude: float = 15.0, width: int = 2) -> np.ndarray:
    """InfiniBand error burst: a short, sharp spike -- broadband energy."""
    out = S.copy()
    for i in affected:
        out[i, burst_at : burst_at + width] += amplitude
    return out


def inject_dead_node(S: np.ndarray, affected: list[int], start: int) -> np.ndarray:
    """Dead node: readings flatline (freeze at last value) from `start`."""
    out = S.copy()
    for i in affected:
        out[i, start:] = out[i, start]
    return out


FAULT_START_FRACTION = 1 / 2  # all faults kick in halfway through the series

FAULTS: dict[str, Callable[[np.ndarray, list[int]], np.ndarray]] = {
    "cpu_steal": lambda S, affected: inject_cpu_steal(
        S, affected, start=S.shape[1] // 2, end=S.shape[1] // 2 + 60, amplitude=40.0
    ),
    "memory_leak_ramp": lambda S, affected: inject_memory_leak_ramp(S, affected, start=S.shape[1] // 2, slope=2.0),
    "ib_error_burst": lambda S, affected: inject_ib_error_burst(S, affected, burst_at=S.shape[1] // 2, amplitude=15.0),
    "dead_node": lambda S, affected: inject_dead_node(S, affected, start=S.shape[1] // 2),
}


def run_fault_case(
    fault_name: str,
    band: str,
    n_nodes: int = 20,
    n_affected: int = 4,
    T: int = 480,
    period_samples: float = 70,
    resolution_s: float = 60,
    seed: int = 0,
) -> dict[str, object]:
    S = _phase_diverse_baseline(n_nodes, T, period_samples, seed=seed)
    affected = list(range(n_nodes - n_affected, n_nodes))
    S_faulty = FAULTS[fault_name](S, affected)
    fault_start = int(T * FAULT_START_FRACTION)

    # default_baseline's global-IQR quiet-window search is fooled here: with
    # only n_affected/n_nodes minority of nodes perturbed, the flattened
    # population IQR bounds stretch enough that the post-fault window still
    # looks "in range" and gets included in the baseline, diluting the
    # z-score toward a population-statistics artifact (verified empirically:
    # a fixed z~2.0 regardless of fault magnitude, from 4-of-20 nodes at a
    # constant multiple of the other 16's baseline amplitude -- pure
    # arithmetic, not signal). An explicit pre-fault window is what an
    # operator investigating a known incident would brush anyway.
    result = compute_zscores(
        {"metric": S_faulty},
        band=band,
        resolution_s=resolution_s,
        baseline_windows={"metric": (0, fault_start)},
    )
    z = result.z[:, 0]
    flagged = {i for i in range(n_nodes) if abs(z[i]) >= Z_THRESHOLD}
    recall = len(flagged & set(affected)) / len(affected)

    return {"fault": fault_name, "band": band, "z": z, "affected": affected, "flagged": flagged, "recall_at_3": recall}
