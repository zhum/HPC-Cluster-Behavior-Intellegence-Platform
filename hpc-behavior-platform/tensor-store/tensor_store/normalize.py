"""Per-metric normalization across (N, T), config-driven."""
from __future__ import annotations

from typing import Literal

import numpy as np

Method = Literal["zscore", "minmax"]


def normalize(X: np.ndarray, method: Method = "zscore") -> np.ndarray:
    """X: (N, M, T) -> normalized copy, same shape. Normalizes each metric
    slice X[:, m, :] independently over both N and T (ignoring NaN).
    """
    out = X.copy()
    n_metrics = X.shape[1]
    for m in range(n_metrics):
        slice_ = out[:, m, :]
        if method == "zscore":
            mean = np.nanmean(slice_)
            std = np.nanstd(slice_)
            out[:, m, :] = (slice_ - mean) / std if std > 0 else slice_ - mean
        elif method == "minmax":
            lo = np.nanmin(slice_)
            hi = np.nanmax(slice_)
            out[:, m, :] = (slice_ - lo) / (hi - lo) if hi > lo else slice_ - lo
        else:
            raise ValueError(f"unknown normalize method: {method}")
    return out


def constant_metric_mask(X: np.ndarray) -> np.ndarray:
    """X: (N, M, T) -> (M,) bool, True where std == 0 across (N, T) (ignoring
    NaN). Constant metrics must be dropped before PCA/ccPCA (degenerate).
    """
    n_metrics = X.shape[1]
    mask = np.zeros(n_metrics, dtype=bool)
    for m in range(n_metrics):
        std = np.nanstd(X[:, m, :])
        mask[m] = bool(np.isnan(std) or std == 0)
    return mask
