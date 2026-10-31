"""Phase 4/7 gate: injected anomalies recovered with recall >= 0.9 at |z| >= 3,
with at most MAX_FALSE_POSITIVE_RATE of healthy nodes flagged, on every seed in
GATE_SEEDS.

ib_error_burst does not meet it (see reports/fault_injection.md): a 2-sample
impulse only reaches the "5m" band through noise-level DMD modes, which spill
the burst across nodes, so recall drops on some seeds and healthy nodes are
flagged on others. It is a strict xfail, so a fix shows up as an unexpected
pass.

On seed 0 the per-fault settings recover every fault, which the recall
test below keeps as a detection regression check:

- memory_leak_ramp: previously a documented gap in the "7d" band. The 7d band
  was the wrong place to look on this fixture -- 8h of data (T=480 @ 60s)
  cannot resolve multi-day periods, and mrDMD's level windows cap the slowest
  retained frequency, so the 24h/7d bands only ever contain exact-DC modes
  (zero baseline variance => degenerate). The ramp's per-window signature
  lands in the "2h" band, where default settings recover it at z ~ 400+.
- cpu_steal and ib_error_burst need high-frequency modes that default
  max_cycles=1 structurally discards (nothing faster than 1 cycle per finest
  window is ever retained, leaving the "5m"/"30m" bands empty); both read
  from "5m" with a higher max_cycles.
"""
from __future__ import annotations

import pytest

from evaluation.fault_injection import FAULT_DETECTION, FAULTS, Z_THRESHOLD, gate_over_seeds, run_fault_case

GATE_FAILURES = {"ib_error_burst"}


@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(f, marks=pytest.mark.xfail(strict=True, reason="known gate failure, see module docstring"))
        if f in GATE_FAILURES
        else f
        for f in sorted(FAULTS)
    ],
)
def test_fault_meets_gate_across_seeds(fault: str):
    assert gate_over_seeds(fault)["passed"]


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_fault_recall_on_seed_0(fault: str):
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
