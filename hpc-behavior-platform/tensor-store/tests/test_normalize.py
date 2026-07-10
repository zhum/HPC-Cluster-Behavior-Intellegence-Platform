from __future__ import annotations

import numpy as np

from tensor_store.normalize import constant_metric_mask, normalize


def test_zscore_per_metric_independent():
    X = np.zeros((4, 2, 10))
    X[:, 0, :] = np.arange(10) * 10.0  # broad range
    X[:, 1, :] = 5.0 + np.arange(10) * 0.01  # tight range
    Z = normalize(X, method="zscore")
    assert abs(np.nanmean(Z[:, 0, :])) < 1e-9
    assert abs(np.nanstd(Z[:, 0, :]) - 1.0) < 1e-9
    assert abs(np.nanmean(Z[:, 1, :])) < 1e-9


def test_constant_metric_detected():
    X = np.zeros((3, 2, 5))
    X[:, 0, :] = 7.0  # constant
    X[:, 1, :] = np.random.RandomState(0).randn(3, 5)
    mask = constant_metric_mask(X)
    assert mask[0] == True  # noqa: E712
    assert mask[1] == False  # noqa: E712


def test_constant_with_nan_flagged_constant():
    X = np.full((3, 1, 5), np.nan)
    mask = constant_metric_mask(X)
    assert mask[0] == True  # noqa: E712
