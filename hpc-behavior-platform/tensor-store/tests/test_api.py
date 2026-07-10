from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pytest

import tensor_store.api as api_mod
from tensor_store.api import TensorRequest, get_tensor
from tensor_store.cache import DiskCache


@dataclass
class _QueryResult:
    result_rows: list[tuple]


class FakeClient:
    """Stands in for clickhouse_connect.Client: serves list_nodes/list_metrics
    (SELECT DISTINCT ...) and load_long (SELECT ts, node_id, metric, value ...)
    against an in-memory long dataframe, so get_tensor's metric-batching logic
    can be exercised without a live ClickHouse instance.
    """

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows  # (ts, node_id, metric, value)
        self.queries: list[str] = []

    def query(self, query: str, parameters: dict) -> _QueryResult:
        self.queries.append(query)
        if "DISTINCT node_id" in query:
            metrics = parameters.get("metrics")
            vals = {r[1] for r in self.rows if metrics is None or r[2] in metrics}
            return _QueryResult([(v,) for v in vals])
        if "DISTINCT metric" in query:
            nodes = parameters.get("nodes")
            vals = {r[2] for r in self.rows if nodes is None or r[1] in nodes}
            return _QueryResult([(v,) for v in vals])

        nodes = parameters.get("nodes")
        metrics = parameters.get("metrics")
        filtered = [
            r
            for r in self.rows
            if (nodes is None or r[1] in nodes) and (metrics is None or r[2] in metrics)
        ]

        match = re.search(r"INTERVAL (\d+) SECOND", query)
        if match is None:
            return _QueryResult(filtered)

        # emulate load_gridded's server-side toStartOfInterval + argMax(value, ts):
        # floor-bucket each row, then keep only the latest reading per bucket.
        resolution_s = int(match.group(1))
        step = timedelta(seconds=resolution_s)
        latest: dict[tuple, tuple] = {}
        for ts, node_id, metric, value in filtered:
            epoch = ts.timestamp() if hasattr(ts, "timestamp") else 0
            bucket_ts = datetime.fromtimestamp(epoch - (epoch % resolution_s))
            key = (bucket_ts, node_id, metric)
            if key not in latest or ts > latest[key][0]:
                latest[key] = (ts, value)
        out = [(bucket_ts, node_id, metric, v[1]) for (bucket_ts, node_id, metric), v in latest.items()]
        return _QueryResult(out)


def _make_rows(n_nodes: int, n_metrics: int, n_t: int, start: datetime, resolution_s: int) -> list[tuple]:
    rows = []
    for n_i in range(n_nodes):
        for m_i in range(n_metrics):
            for t_i in range(n_t):
                ts = start + timedelta(seconds=resolution_s * t_i)
                rows.append((ts, f"node-{n_i}", f"metric-{m_i}", float(n_i * 1000 + m_i * 10 + t_i)))
    return rows


def test_batched_matches_unbatched(tmp_path, monkeypatch):
    start = datetime(2026, 1, 1)
    resolution_s = 15
    n_t = 10
    end = start + timedelta(seconds=resolution_s * n_t)
    rows = _make_rows(n_nodes=3, n_metrics=7, n_t=n_t, start=start, resolution_s=resolution_s)
    client = FakeClient(rows)
    request = TensorRequest(start=start, end=end, resolution_s=resolution_s)

    monkeypatch.setattr(api_mod, "METRIC_BATCH_SIZE", 3)
    batched = get_tensor(request, client=client, cache=DiskCache(tmp_path / "batched"), use_cache=False)

    monkeypatch.setattr(api_mod, "METRIC_BATCH_SIZE", 1000)
    unbatched = get_tensor(request, client=client, cache=DiskCache(tmp_path / "unbatched"), use_cache=False)

    assert batched.nodes == unbatched.nodes
    assert batched.metrics == unbatched.metrics
    np.testing.assert_array_equal(batched.times, unbatched.times)
    np.testing.assert_allclose(batched.X, unbatched.X)


def test_batching_bounds_peak_intermediate_size(tmp_path, monkeypatch):
    """Each per-batch df_grid should only ever carry METRIC_BATCH_SIZE metrics,
    never the full metric set -- this is the actual memory-bounding property.
    """
    start = datetime(2026, 1, 1)
    resolution_s = 15
    n_t = 5
    end = start + timedelta(seconds=resolution_s * n_t)
    rows = _make_rows(n_nodes=2, n_metrics=9, n_t=n_t, start=start, resolution_s=resolution_s)
    client = FakeClient(rows)
    request = TensorRequest(start=start, end=end, resolution_s=resolution_s)

    seen_batch_metric_counts = []
    real_bucketed_to_tensor = api_mod.bucketed_to_tensor

    def spy_bucketed_to_tensor(df_bucketed, *args, **kwargs):
        seen_batch_metric_counts.append(df_bucketed["metric"].nunique())
        return real_bucketed_to_tensor(df_bucketed, *args, **kwargs)

    monkeypatch.setattr(api_mod, "METRIC_BATCH_SIZE", 4)
    monkeypatch.setattr(api_mod, "bucketed_to_tensor", spy_bucketed_to_tensor)
    bundle = get_tensor(request, client=client, cache=DiskCache(tmp_path / "c"), use_cache=False)

    assert all(c <= 4 for c in seen_batch_metric_counts)
    assert len(seen_batch_metric_counts) == 3  # 9 metrics / batch=4 -> 3 batches
    assert bundle.X.shape[1] == 9
