from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import fakeredis
import numpy as np
import pytest
from fastapi.testclient import TestClient

from analysis_api.cache import RedisStageCache
from analysis_api.main import create_app
from analysis_api.saved_analyses import SavedAnalysesStore
from analysis_api.session import SessionStore


@dataclass
class _QueryResult:
    result_rows: list[tuple]


class FakeClickHouseClient:
    """Serves list_nodes/list_metrics/load_gridded (tensor-store's SQL-pushdown
    contract) and a minimal `jobs` table, all from in-memory synthetic data --
    the "synthetic ClickHouse fixture" the Phase 5 spec calls for, so the API
    layer can be integration-tested without a live ClickHouse/tensor-store
    round trip.
    """

    def __init__(self, node_ids, metric_ids, times, values):
        self.node_ids = node_ids
        self.metric_ids = metric_ids
        self.times = times
        self.values = values  # (N, M, T)
        self.jobs: list[tuple] = []
        self.saved_analyses: list[dict] = []

    def query(self, query: str, parameters: dict):
        if "DISTINCT node_id" in query:
            return _QueryResult([(n,) for n in self.node_ids])
        if "DISTINCT metric" in query:
            return _QueryResult([(m,) for m in self.metric_ids])
        if "FROM jobs" in query:
            wanted = set(parameters["node_ids"])
            rows = [r for r in self.jobs if wanted & set(r[3])]
            return _QueryResult(rows)
        if "FROM saved_analyses" in query:
            rows = self.saved_analyses
            if "id" in parameters:
                rows = [r for r in rows if r["id"] == parameters["id"]]
            if "user_id" in parameters:
                rows = [r for r in rows if r["user_id"] == parameters["user_id"]]
            if "deleted = 0" in query:
                rows = [r for r in rows if r["deleted"] == 0]
            if "SELECT id, user_id, name, updated_at " in query:
                return _QueryResult([(r["id"], r["user_id"], r["name"], r["updated_at"]) for r in rows])
            return _QueryResult(
                [(r["id"], r["user_id"], r["name"], r["state_json"], r["updated_at"]) for r in rows]
            )

        # load_gridded: toStartOfInterval + argMax bucketing emulation --
        # our fixture data is already exactly on-grid and deduped, so this
        # just filters to the requested node/metric subset.
        nodes = parameters.get("nodes") or self.node_ids
        metrics = parameters.get("metrics") or self.metric_ids
        rows = []
        for n_i, node in enumerate(self.node_ids):
            if node not in nodes:
                continue
            for m_i, metric in enumerate(self.metric_ids):
                if metric not in metrics:
                    continue
                for t_i, ts in enumerate(self.times):
                    rows.append((ts, node, metric, float(self.values[n_i, m_i, t_i])))
        return _QueryResult(rows)

    def insert(self, table: str, rows: list[tuple], column_names: list[str]) -> None:
        assert table == "saved_analyses"
        for row in rows:
            record = dict(zip(column_names, row))
            # mimic ReplacingMergeTree(updated_at) + FINAL: latest insert for
            # a given id wins, including soft-deletes (deleted=1 inserts).
            self.saved_analyses = [a for a in self.saved_analyses if a["id"] != record["id"]]
            self.saved_analyses.append(record)


@pytest.fixture
def synthetic_client():
    rng = np.random.default_rng(0)
    n_nodes, n_metrics, n_t = 12, 6, 40
    resolution_s = 60
    start = datetime(2026, 1, 1)
    times = [start + timedelta(seconds=resolution_s * i) for i in range(n_t)]
    node_ids = [f"node-{i:03d}" for i in range(n_nodes)]
    metric_ids = [f"metric-{i:02d}" for i in range(n_metrics)]

    values = rng.normal(50, 5, size=(n_nodes, n_metrics, n_t))
    # planted structure so k-means/ccPCA/UMAP have something non-degenerate
    # to find: first half of nodes share a distinctive temporal SHAPE on
    # metric-00. A constant offset would NOT work here -- dr1_pca_over_time
    # z-scores each node's own time series before PCA, which erases any
    # constant per-node offset/scale; only shape differences (like this
    # shared sinusoid) survive to be picked up (same lesson learned building
    # the Phase 3 ccPCA fixture).
    t_idx = np.arange(n_t)
    shared_wave = 20 * np.sin(2 * np.pi * t_idx / 10)
    values[: n_nodes // 2, 0, :] += shared_wave

    client = FakeClickHouseClient(node_ids, metric_ids, times, values)
    client.jobs = [
        ("job-1", "alice", "gpu", [node_ids[0], node_ids[1]], "RUNNING", start, None),
    ]
    return client, start, times[-1] + timedelta(seconds=resolution_s), resolution_s


@pytest.fixture
def app_client(synthetic_client):
    client, _, _, _ = synthetic_client
    app = create_app()
    app.state.session_store = SessionStore()
    app.state.stage_cache = RedisStageCache(fakeredis.FakeRedis())
    app.state.clickhouse_client = client
    app.state.saved_analyses_store = SavedAnalysesStore(client)
    return TestClient(app)
