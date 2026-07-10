"""Resample a long telemetry dataframe onto a uniform time grid.

Vectorized: every raw reading is floor-bucketed to its grid timestamp in one
pass (no per-(node,metric) Python loop -- with 500 nodes x 100 metrics that's
50,000 groups, and a per-group merge_asof call there cost ~75s for a single
day's tensor; the milestone target is <30s cold). Gaps up to `ffill_limit`
grid steps are then forward-filled per column, in one vectorized pandas call;
beyond that, values are left NaN (Phase 2 nulls.py and the DR input step at
Phase 3 are what turn NaN-runs into signal or zero-fill).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

FFILL_LIMIT = 2


def build_grid(start: datetime, end: datetime, resolution_s: int) -> pd.DatetimeIndex:
    return pd.date_range(start=start, end=end, freq=f"{resolution_s}s", inclusive="left")


def resample_to_grid(
    df_long: pd.DataFrame,
    start: datetime,
    end: datetime,
    resolution_s: int,
    ffill_limit: int = FFILL_LIMIT,
) -> pd.DataFrame:
    """df_long: columns [ts, node_id, metric, value] (any order/dtype of ts is
    coerced to datetime64[ns]). Returns a long dataframe reindexed onto the
    uniform grid, same columns, with per-(node,metric) forward-fill applied.
    """
    grid = build_grid(start, end, resolution_s)
    if df_long.empty or len(grid) == 0:
        return pd.DataFrame(columns=["ts", "node_id", "metric", "value"])

    df = df_long.copy()
    df["ts"] = pd.to_datetime(df["ts"])

    start_ts = pd.Timestamp(start)
    step = pd.Timedelta(seconds=resolution_s)

    # floor each raw reading to its grid bucket (vectorized, no per-group loop)
    offset = (df["ts"] - start_ts) // step
    n_grid = len(grid)
    in_range = (offset >= 0) & (offset < n_grid)
    df = df.loc[in_range].copy()
    if df.empty:
        return pd.DataFrame(columns=["ts", "node_id", "metric", "value"])
    df["grid_ts"] = start_ts + offset.loc[in_range] * step

    # multiple raw readings can land in the same bucket; keep the latest.
    # groupby with sort=False + last() is a vectorized pandas op, not a
    # Python-level loop over groups.
    df = df.sort_values("ts")
    collapsed = (
        df.groupby(["node_id", "metric", "grid_ts"], sort=False, observed=True)["value"]
        .last()
        .reset_index()
    )

    return _pivot_reindex_ffill(collapsed, "grid_ts", grid, ffill_limit)


def reindex_and_ffill(
    df_bucketed: pd.DataFrame,
    start: datetime,
    end: datetime,
    resolution_s: int,
    ffill_limit: int = FFILL_LIMIT,
) -> pd.DataFrame:
    """Like resample_to_grid, but for input that a caller (typically a SQL
    query with toStartOfInterval + argMax dedup -- see loader.load_long) has
    already floor-bucketed and deduped onto grid timestamps. Skips the
    per-row floor-bucket arithmetic and groupby(...).last() dedup, which are
    redundant work when the source already guarantees one row per
    (node, metric, grid bucket).
    """
    grid = build_grid(start, end, resolution_s)
    if df_bucketed.empty or len(grid) == 0:
        return pd.DataFrame(columns=["ts", "node_id", "metric", "value"])
    return _pivot_reindex_ffill(df_bucketed, "ts", grid, ffill_limit)


def _pivot_reindex_ffill(
    df: pd.DataFrame, ts_col: str, grid: pd.DatetimeIndex, ffill_limit: int
) -> pd.DataFrame:
    wide = df.pivot(index=ts_col, columns=["node_id", "metric"], values="value")
    wide = wide.reindex(grid)
    wide = wide.ffill(limit=ffill_limit)

    long_df = wide.stack(["node_id", "metric"], future_stack=True).reset_index()
    long_df.columns = ["ts", "node_id", "metric", "value"]
    return long_df
