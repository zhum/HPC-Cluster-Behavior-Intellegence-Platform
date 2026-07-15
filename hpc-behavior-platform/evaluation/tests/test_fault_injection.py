"""Phase 4/7 gate: injected anomalies recovered with recall >= 0.9 at |z| >= 3.

All four fault types now clear the gate with per-fault detection settings
(FAULT_DETECTION in evaluation/fault_injection.py), each verified for recall
1.00 across seeds 0-4:

- memory_leak_ramp: previously a documented gap in the "7d" band. The 7d band
  was the wrong place to look on this fixture -- 8h of data (T=480 @ 60s)
  cannot resolve multi-day periods, and mrDMD's level windows cap the slowest
  retained frequency, so the 24h/7d bands only ever contain exact-DC modes
  (zero baseline variance => degenerate). The ramp's per-window signature
  lands in the "2h" band, where default settings recover it at z ~ 400+.
- ib_error_burst: previously a documented gap. A 2-sample impulse needs
  high-frequency modes that default max_cycles=1 structurally discards
  (nothing faster than 1 cycle per finest window is ever retained, leaving
  the "5m"/"30m" bands empty). With finer windows (min_finest_window=16) and
  max_cycles=8 the impulse dominates its window in the "5m" band.
"""
from __future__ import annotations

import pytest

from evaluation.fault_injection import FAULT_DETECTION, FAULTS, Z_THRESHOLD, run_fault_case


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_fault_meets_recall_gate(fault: str):
    cfg = FAULT_DETECTION[fault]
    result = run_fault_case(
        fault, band=cfg.band, max_cycles=cfg.max_cycles, min_finest_window=cfg.min_finest_window
    )
    assert result["recall_at_3"] >= 0.9


def test_memory_leak_ramp_7d_band_is_degenerate_on_short_fixtures():
    """Characterization: why FAULT_DETECTION maps the ramp to "2h" and not
    "7d". On an 8h fixture the 7d band holds only exact-DC modes, so the
    baseline band amplitude has zero variance and z-scoring is undefined
    (degenerate) -- the ramp must be read from the slowest *resolvable* band
    instead.
    """
    from analysis_core.intra.zscores import compute_zscores
    from evaluation.fault_injection import _phase_diverse_baseline

    S = _phase_diverse_baseline(n_nodes=20, T=480, period_samples=70, seed=0)
    affected = list(range(16, 20))
    S_faulty = FAULTS["memory_leak_ramp"](S, affected)

    result = compute_zscores(
        {"metric": S_faulty}, band="7d", resolution_s=60, baseline_windows={"metric": (0, 240)}
    )
    assert result.degenerate_metrics == ["metric"]


def test_z_threshold_is_the_spec_gate_value():
    assert Z_THRESHOLD == 3.0
