from __future__ import annotations

import numpy as np

from analysis_core.intra.mrdmd import (
    Mode,
    compute_max_level,
    isolate_band,
    mrdmd_spectrum,
    named_bands,
    prepare_series,
)


def test_compute_max_level_respects_min_finest_window():
    assert compute_max_level(480, min_window=32) == 3  # 480/2**3 = 60 >= 32, 480/2**4=30 < 32
    assert compute_max_level(31, min_window=32) == 0
    assert compute_max_level(32, min_window=32) == 0


def test_named_bands_ordered_and_cover_dc_to_inf():
    bands = named_bands(resolution_s=60)
    assert set(bands) == {"5m", "30m", "2h", "24h", "7d"}
    assert bands["5m"][1] == float("inf")
    assert bands["7d"][0] == 0.0
    # bands should chain: each band's low == the next slower band's high
    ordered = ["5m", "30m", "2h", "24h", "7d"]
    for fast, slow in zip(ordered, ordered[1:]):
        assert bands[fast][0] == bands[slow][1]


def test_isolate_band_filters_by_frequency():
    modes = [
        Mode(level=0, window=(0, 10), omega=complex(0, 2 * np.pi * 0.1), amplitude=np.zeros(1), power=0.0),
        Mode(level=0, window=(0, 10), omega=complex(0, 2 * np.pi * 0.5), amplitude=np.zeros(1), power=0.0),
    ]
    kept = isolate_band(modes, f_low=0.05, f_high=0.2)
    assert len(kept) == 1
    assert abs(kept[0].omega.imag) == 2 * np.pi * 0.1


def test_prepare_series_interpolates_short_gaps():
    S = np.array([[1.0, np.nan, np.nan, 4.0, 5.0]])
    filled, segment = prepare_series(S, max_gap=3)
    assert segment == slice(0, 5)
    assert not np.isnan(filled).any()
    np.testing.assert_allclose(filled[0], [1.0, 2.0, 3.0, 4.0, 5.0])


def test_prepare_series_splits_at_long_gap():
    # gap of length 5 (> max_gap=3) in the middle -> longest contiguous
    # valid-for-all-nodes stretch is the tail segment.
    S = np.full((2, 20), 1.0)
    S[:, 5:10] = np.nan
    filled, segment = prepare_series(S, max_gap=3)
    assert segment == slice(10, 20)
    assert filled.shape == (2, 10)
    assert not np.isnan(filled).any()


def _phase_diverse_signal(n_nodes, T, period_samples, rng):
    t = np.arange(T)
    phases = rng.uniform(0, 2 * np.pi, n_nodes)
    S = np.zeros((n_nodes, T))
    for i in range(n_nodes):
        S[i] = np.sin(2 * np.pi * t / period_samples + phases[i]) + rng.normal(0, 0.05, T)
    return S


def test_mrdmd_spectrum_recovers_injected_frequency():
    """Per-node phase diversity is required for plain DMD to represent
    rotational dynamics at all (identical waveforms across nodes are
    spatially rank-1 and cannot encode a sin/cos pair) -- verified this is
    the deciding factor empirically before writing this test. Period is
    chosen to exceed the finest MrDMD level's window (60 samples here),
    which is required for the oscillation to pass MrDMD's per-level
    "slow enough to keep" mode-selection filter (rho = max_cycles / window).
    """
    rng = np.random.default_rng(0)
    T = 480
    period_samples = 70
    S = _phase_diverse_signal(20, T, period_samples, rng)

    modes, segment = mrdmd_spectrum(S)
    assert segment == slice(0, T)

    oscillatory = [m for m in modes if abs(m.omega.imag) > 1e-6]
    assert len(oscillatory) > 0
    periods = [2 * np.pi / abs(m.omega.imag) for m in oscillatory]
    assert any(abs(p - period_samples) < 5 for p in periods)


def test_mrdmd_spectrum_frequency_isolated_to_correct_band():
    rng = np.random.default_rng(0)
    resolution_s = 60
    T = 480
    period_samples = 70  # 70 * 60s = 4200s = 70min -> falls in the "2h" band
    S = _phase_diverse_signal(20, T, period_samples, rng)

    modes, _ = mrdmd_spectrum(S)
    bands = named_bands(resolution_s)

    in_2h = isolate_band(modes, *bands["2h"])
    in_24h = isolate_band(modes, *bands["24h"])
    in_30m = isolate_band(modes, *bands["30m"])

    assert len(in_2h) > 0
    assert len(in_24h) == 0
    assert len(in_30m) == 0
