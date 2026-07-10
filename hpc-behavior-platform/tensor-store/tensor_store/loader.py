"""ClickHouse -> long dataframe.

Kept separate from grid/tensor so the rest of the pipeline can be unit-tested
against synthetic long dataframes without a live ClickHouse instance.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import clickhouse_connect
from clickhouse_connect.driver.client import Client


def get_client(
    host: str = "localhost",
    port: int = 8123,
    username: str = "default",
    password: str = "",
) -> Client:
    return clickhouse_connect.get_client(
        host=host, port=port, username=username, password=password
    )


def list_nodes(
    client: Client,
    start: datetime,
    end: datetime,
    nodes: list[str] | None = None,
) -> list[str]:
    """Distinct node_ids present in [start, end), without pulling raw rows.

    Used by api.get_tensor to fix a stable node axis before per-metric-batch
    fetching, so every batch pivots onto the same (N,) ordering.
    """
    clauses = ["ts >= {start:DateTime64(3)}", "ts < {end:DateTime64(3)}"]
    params: dict[str, object] = {
        "start": start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }
    if nodes:
        clauses.append("node_id IN {nodes:Array(String)}")
        params["nodes"] = nodes
    query = f"SELECT DISTINCT node_id FROM metrics_raw WHERE {' AND '.join(clauses)}"
    result = client.query(query, parameters=params)
    return sorted(r[0] for r in result.result_rows)


def list_metrics(
    client: Client,
    start: datetime,
    end: datetime,
    metrics: list[str] | None = None,
) -> list[str]:
    """Distinct metric names present in [start, end); see list_nodes."""
    clauses = ["ts >= {start:DateTime64(3)}", "ts < {end:DateTime64(3)}"]
    params: dict[str, object] = {
        "start": start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }
    if metrics:
        clauses.append("metric IN {metrics:Array(String)}")
        params["metrics"] = metrics
    query = f"SELECT DISTINCT metric FROM metrics_raw WHERE {' AND '.join(clauses)}"
    result = client.query(query, parameters=params)
    return sorted(r[0] for r in result.result_rows)


def load_long(
    client: Client,
    start: datetime,
    end: datetime,
    nodes: list[str] | None,
    metrics: list[str] | None,
) -> pd.DataFrame:
    """Query metrics_raw for [start, end) and an optional node/metric subset.

    Returns a long dataframe with columns: ts, node_id, metric, value.
    """
    clauses = ["ts >= {start:DateTime64(3)}", "ts < {end:DateTime64(3)}"]
    # clickhouse-connect mis-formats bare `datetime` objects for DateTime64
    # server-side parameters (silently matches zero rows); pass explicit
    # millisecond-precision strings instead.
    params: dict[str, object] = {
        "start": start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }

    if nodes:
        clauses.append("node_id IN {nodes:Array(String)}")
        params["nodes"] = nodes
    if metrics:
        clauses.append("metric IN {metrics:Array(String)}")
        params["metrics"] = metrics

    query = (
        "SELECT ts, node_id, metric, value FROM metrics_raw "
        f"WHERE {' AND '.join(clauses)} ORDER BY node_id, metric, ts"
    )
    result = client.query(query, parameters=params)
    return pd.DataFrame(result.result_rows, columns=["ts", "node_id", "metric", "value"])


def load_gridded(
    client: Client,
    start: datetime,
    end: datetime,
    nodes: list[str] | None,
    metrics: list[str] | None,
    resolution_s: int,
) -> pd.DataFrame:
    """Like load_long, but buckets+dedups onto the resolution_s grid inside
    ClickHouse (toStartOfInterval + argMax-by-latest-ts) instead of pandas.

    Profiling at milestone scale (500 nodes x 100 metrics x 1 day @15s) showed
    resample_to_grid's own floor-bucket + groupby(...).last() dedup costing
    real time even when the raw data has exactly one reading per bucket --
    doing the bucket/dedup in ClickHouse (columnar, vectorized in C++) instead
    of pandas removes that redundant pass. Pair with grid.reindex_and_ffill,
    which only needs to reindex onto the full grid and forward-fill gaps.
    """
    resolution_s = int(resolution_s)
    clauses = ["ts >= {start:DateTime64(3)}", "ts < {end:DateTime64(3)}"]
    params: dict[str, object] = {
        "start": start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }
    if nodes:
        clauses.append("node_id IN {nodes:Array(String)}")
        params["nodes"] = nodes
    if metrics:
        clauses.append("metric IN {metrics:Array(String)}")
        params["metrics"] = metrics

    query = (
        f"SELECT toStartOfInterval(ts, INTERVAL {resolution_s} SECOND) AS ts, "
        "node_id, metric, argMax(value, ts) AS value "
        f"FROM metrics_raw WHERE {' AND '.join(clauses)} "
        "GROUP BY ts, node_id, metric ORDER BY node_id, metric, ts"
    )
    result = client.query(query, parameters=params)
    return pd.DataFrame(result.result_rows, columns=["ts", "node_id", "metric", "value"])
