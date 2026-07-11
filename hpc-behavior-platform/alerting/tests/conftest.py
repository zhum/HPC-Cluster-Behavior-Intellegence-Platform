from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pytest


@dataclass
class _QueryResult:
    result_rows: list[tuple]
    column_names: list[str] | None = None


class FakeClient:
    """Combined fake for tensor-store's SQL-pushdown contract (list_nodes/
    list_metrics/load_gridded) AND the alerting tables (anomalies,
    suppression_rules, baseline_state) -- the scheduler uses the same client
    object for both in production (one ClickHouse instance), so tests do too.
    """

    def __init__(self, node_ids: list[str], metric_ids: list[str], times: list[datetime], values: np.ndarray) -> None:
        self.node_ids = node_ids
        self.metric_ids = metric_ids
        self.times = times
        self.values = values  # (N, M, T)

        self.anomalies: list[dict] = []
        self.suppression_rules: list[dict] = []
        self.baseline_state: dict[tuple[int, str], tuple[int, int]] = {}

    # --- tensor-store contract -------------------------------------------------
    def query(self, query: str, parameters: dict):
        if "DISTINCT node_id" in query:
            return _QueryResult([(n,) for n in self.node_ids])
        if "DISTINCT metric" in query:
            return _QueryResult([(m,) for m in self.metric_ids])

        if "FROM suppression_rules" in query:
            node_id, metric, band = parameters["node_id"], parameters["metric"], parameters["band"]
            count = sum(
                1
                for r in self.suppression_rules
                if r["node_id"] == node_id and r["metric"] == metric and r["band"] == band
            )
            return _QueryResult([(count,)])

        if "FROM baseline_state" in query:
            key = (parameters["cluster_id"], parameters["metric"])
            window = self.baseline_state.get(key)
            return _QueryResult([window] if window else [])

        if "FROM anomalies" in query:
            rows = [a for a in self.anomalies if a["status"] == "open"]
            cols = [
                "id",
                "detected_at",
                "cluster_id",
                "node_id",
                "metric",
                "band",
                "z_score",
                "baseline_window_start",
                "baseline_window_end",
                "status",
                "dismissed_at",
                "dismissed_by",
                "dismiss_reason",
            ]
            return _QueryResult([tuple(r[c] for c in cols) for r in rows], column_names=cols)

        # load_gridded: emulate toStartOfInterval + argMax bucketing on
        # already-on-grid synthetic fixture data.
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

    # --- alerting tables ---------------------------------------------------
    def insert(self, table: str, rows: list[tuple], column_names: list[str]) -> None:
        if table == "anomalies":
            for row in rows:
                self.anomalies.append(dict(zip(column_names, row)))
        elif table == "suppression_rules":
            for row in rows:
                self.suppression_rules.append(dict(zip(column_names, row)))
        elif table == "baseline_state":
            for row in rows:
                d = dict(zip(column_names, row))
                self.baseline_state[(d["cluster_id"], d["metric"])] = (d["window_start"], d["window_end"])

    def command(self, query: str, parameters: dict) -> None:
        assert "ALTER TABLE anomalies UPDATE" in query
        anomaly_id = parameters["id"]
        for a in self.anomalies:
            if a["id"] == anomaly_id:
                a["status"] = "dismissed"
                a["dismissed_at"] = parameters["now"]
                a["dismissed_by"] = parameters["by"]
                a["dismiss_reason"] = parameters["reason"]


@pytest.fixture
def synthetic_client():
    """N=20/T=480/period=70/resolution_s=60 reuses the exact parameters
    validated in analysis-core's own mrDMD tests: period must exceed
    mrDMD's finest-level window (here 60 samples, from T=480 and the
    default min-finest-window of 32) to be captured as a "slow enough"
    mode at all, and 70*60s=70min lands cleanly in the "2h" named band.
    """
    rng = np.random.default_rng(0)
    n_nodes, n_metrics, n_t = 20, 3, 480
    resolution_s = 60
    period_samples = 70
    start = datetime(2026, 1, 1)
    times = [start + timedelta(seconds=resolution_s * i) for i in range(n_t)]
    node_ids = [f"node-{i:03d}" for i in range(n_nodes)]
    metric_ids = [f"metric-{i:02d}" for i in range(n_metrics)]

    t_idx = np.arange(n_t)
    values = np.zeros((n_nodes, n_metrics, n_t))
    phases = rng.uniform(0, 2 * np.pi, n_nodes)
    for i in range(n_nodes):
        for m in range(n_metrics):
            values[i, m] = np.sin(2 * np.pi * t_idx / period_samples + phases[i]) + rng.normal(0, 0.05, n_t)

    client = FakeClient(node_ids, metric_ids, times, values)
    end = times[-1] + timedelta(seconds=resolution_s)
    return client, start, end, resolution_s
