from __future__ import annotations

import numpy as np

from analysis_core.intra.zscores import compute_zscores


def _anomaly_fixture(rng):
    """20 nodes with a shared (phase-diverse) 70-sample oscillation ("2h" band
    at resolution_s=60) plus 2 nodes whose amplitude jumps 8x partway through
    the series -- the spec's required test scenario.
    """
    n_normal, n_anom = 20, 2
    N = n_normal + n_anom
    T = 480
    period_samples = 70
    t = np.arange(T)
    phases = rng.uniform(0, 2 * np.pi, N)

    S = np.zeros((N, T))
    for i in range(N):
        wave = np.sin(2 * np.pi * t / period_samples + phases[i])
        S[i, :240] = wave[:240]
        S[i, 240:] = wave[240:] * (8.0 if i >= n_normal else 1.0)
        S[i] += rng.normal(0, 0.05, T)
    return S, n_normal, n_anom


def test_zscores_flags_anomalous_nodes_in_right_band():
    rng = np.random.default_rng(0)
    S, n_normal, n_anom = _anomaly_fixture(rng)

    result = compute_zscores({"metric_x": S}, band="2h", resolution_s=60)
    z = result.z[:, 0]

    assert np.abs(z[:n_normal]).max() < 1.0
    assert np.all(np.abs(z[n_normal:]) > 3.0)
    assert result.degenerate_metrics == []


def test_zscores_silent_in_unrelated_bands():
    rng = np.random.default_rng(0)
    S, n_normal, n_anom = _anomaly_fixture(rng)

    for band in ["30m", "24h", "7d"]:
        result = compute_zscores({"metric_x": S}, band=band, resolution_s=60)
        # no injected signal in these bands -> a_B has zero spread -> flagged degenerate, z=0
        assert result.degenerate_metrics == ["metric_x"]
        assert np.all(result.z == 0)


def test_zscores_respects_user_supplied_baseline_window():
    rng = np.random.default_rng(0)
    S, n_normal, n_anom = _anomaly_fixture(rng)

    result = compute_zscores(
        {"metric_x": S}, band="2h", resolution_s=60, baseline_windows={"metric_x": (0, 200)}
    )
    assert result.baseline_windows["metric_x"] == slice(0, 200)
    z = result.z[:, 0]
    assert np.all(np.abs(z[n_normal:]) > 3.0)


def test_zresult_metrics_and_shape_multi_metric():
    rng = np.random.default_rng(1)
    S1, n_normal, n_anom = _anomaly_fixture(rng)
    S2 = rng.normal(size=S1.shape)  # unrelated second metric, no signal anywhere

    result = compute_zscores({"metric_a": S1, "metric_b": S2}, band="2h", resolution_s=60)
    assert result.metrics == ["metric_a", "metric_b"]
    assert result.z.shape == (S1.shape[0], 2)
