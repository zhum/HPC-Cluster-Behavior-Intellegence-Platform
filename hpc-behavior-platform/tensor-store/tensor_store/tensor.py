"""Pivot a uniform-grid long dataframe into the analysis tensor X (N, M, T)."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from tensor_store.grid import FFILL_LIMIT, build_grid


def pivot_tensor(
    df_grid: pd.DataFrame,
    nodes: list[str] | None = None,
    metrics: list[str] | None = None,
) -> tuple[np.ndarray, list[str], list[str], np.ndarray]:
    """df_grid: columns [ts, node_id, metric, value], already on a uniform grid
    (see grid.resample_to_grid). Returns (X, node_ids, metric_ids, times) where
    X has shape (N, M, T), NaN allowed for missing readings.

    If `nodes`/`metrics` are given, the output axes are ordered accordingly
    (missing combinations become all-NaN slices) so callers get a stable shape
    even when some requested node/metric never appears in df_grid.
    """
    if df_grid.empty:
        node_ids = list(nodes or [])
        metric_ids = list(metrics or [])
        return (
            np.full((len(node_ids), len(metric_ids), 0), np.nan),
            node_ids,
            metric_ids,
            np.array([], dtype="datetime64[ns]"),
        )

    times = pd.DatetimeIndex(sorted(df_grid["ts"].unique()))
    node_ids = list(nodes) if nodes is not None else sorted(df_grid["node_id"].unique())
    metric_ids = list(metrics) if metrics is not None else sorted(df_grid["metric"].unique())

    node_idx = {n: i for i, n in enumerate(node_ids)}
    metric_idx = {m: i for i, m in enumerate(metric_ids)}
    time_idx = {t: i for i, t in enumerate(times)}

    X = np.full((len(node_ids), len(metric_ids), len(times)), np.nan, dtype=np.float64)

    keep = df_grid["node_id"].isin(node_idx) & df_grid["metric"].isin(metric_idx)
    df_keep = df_grid.loc[keep]

    n_pos = df_keep["node_id"].map(node_idx).to_numpy()
    m_pos = df_keep["metric"].map(metric_idx).to_numpy()
    t_pos = df_keep["ts"].map(time_idx).to_numpy()
    X[n_pos, m_pos, t_pos] = df_keep["value"].to_numpy()

    return X, node_ids, metric_ids, times.to_numpy()


def bucketed_to_tensor(
    df_bucketed: pd.DataFrame,
    nodes: list[str],
    metrics: list[str],
    start: datetime,
    end: datetime,
    resolution_s: int,
    ffill_limit: int = FFILL_LIMIT,
) -> tuple[np.ndarray, list[str], list[str], np.ndarray]:
    """Fast path from SQL-pre-bucketed rows straight to the (N, M, T) tensor.

    Profiling at milestone scale (500 nodes x 100 metrics x 1 day @15s) found
    pandas' own `.pivot()` -- building a (T, N*M) wide frame from a
    categorical-dtype long frame -- costing 23.4s per 20-metric batch on its
    own (~117s projected for all 100 metrics), the actual bottleneck even
    after SQL-side dedup and batching. This version skips pivot()/reindex()/
    ffill() entirely: node/metric/time positions are resolved to integer
    array indices directly, values are scatter-written into a preallocated
    (N, M, T) array, and the forward-fill is a small number (ffill_limit) of
    vectorized numpy shift-and-fill passes along the T axis -- no pandas
    indexing machinery in the hot path at all.

    df_bucketed: columns [ts, node_id, metric, value], one row per
    (already-deduped) grid bucket -- see loader.load_gridded.
    """
    grid = build_grid(start, end, resolution_s)
    n, m, t = len(nodes), len(metrics), len(grid)
    X = np.full((n, m, t), np.nan, dtype=np.float64)

    if df_bucketed.empty or t == 0:
        return X, nodes, metrics, grid.to_numpy()

    node_idx = {node: i for i, node in enumerate(nodes)}
    metric_idx = {metric: i for i, metric in enumerate(metrics)}
    start_ts = pd.Timestamp(start)
    step = pd.Timedelta(seconds=resolution_s)

    keep = df_bucketed["node_id"].isin(node_idx) & df_bucketed["metric"].isin(metric_idx)
    df_keep = df_bucketed.loc[keep]

    t_pos_all = ((pd.to_datetime(df_keep["ts"]) - start_ts) // step).to_numpy()
    in_range = (t_pos_all >= 0) & (t_pos_all < t)
    df_keep = df_keep.loc[in_range]
    t_pos = t_pos_all[in_range].astype(np.intp)
    n_pos = df_keep["node_id"].map(node_idx).to_numpy().astype(np.intp)
    m_pos = df_keep["metric"].map(metric_idx).to_numpy().astype(np.intp)

    X[n_pos, m_pos, t_pos] = df_keep["value"].to_numpy()

    if ffill_limit > 0:
        X_orig = X.copy()
        for lag in range(1, ffill_limit + 1):
            shifted = np.full_like(X_orig, np.nan)
            shifted[:, :, lag:] = X_orig[:, :, :-lag]
            fill_mask = np.isnan(X) & ~np.isnan(shifted)
            X[fill_mask] = shifted[fill_mask]

    return X, nodes, metrics, grid.to_numpy()
