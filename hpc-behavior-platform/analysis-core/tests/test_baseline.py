from __future__ import annotations

import numpy as np

from analysis_core.intra.baseline import default_baseline, user_baseline


def test_default_baseline_finds_known_quiet_interval():
    rng = np.random.default_rng(0)
    n_nodes, T = 10, 100
    S = rng.normal(0, 5.0, size=(n_nodes, T))  # noisy everywhere
    quiet = slice(30, 70)
    S[:, quiet] = rng.normal(0, 0.1, size=(n_nodes, 40))  # tight quiet window

    window, B = default_baseline(S)
    assert window.start >= 25 and window.stop <= 75  # overlaps the planted quiet window
    assert B.shape == S.shape


def test_default_baseline_tiles_across_full_length():
    S = np.zeros((3, 40))
    S[:, 10:20] = 1.0  # only this window sits inside its own IQR trivially
    window, B = default_baseline(S)
    assert B.shape == S.shape
    assert not np.isnan(B).any()


def test_user_baseline_tiles_given_window():
    S = np.arange(40).reshape(1, 40).astype(float)
    B = user_baseline(S, t0=0, t1=10)
    assert B.shape == (1, 40)
    np.testing.assert_allclose(B[0, :10], S[0, :10])
    np.testing.assert_allclose(B[0, 10:20], S[0, :10])  # tiled repeat
