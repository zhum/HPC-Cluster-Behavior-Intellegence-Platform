"""ClickHouse-backed anomaly + suppression-rule store.

`dismiss()` is the operator false-positive feedback loop: it both marks the
specific anomaly dismissed and inserts a suppression rule for that (node_id,
metric, band), so the scheduler skips that combination on future runs
without needing to re-litigate it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class Anomaly:
    id: str
    detected_at: datetime
    cluster_id: int
    node_id: str
    metric: str
    band: str
    z_score: float
    baseline_window: tuple[int, int]


class AnomalyStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    def is_suppressed(self, node_id: str, metric: str, band: str) -> bool:
        query = (
            "SELECT count() FROM suppression_rules "
            "WHERE node_id = {node_id:String} AND metric = {metric:String} AND band = {band:String}"
        )
        result = self.client.query(query, parameters={"node_id": node_id, "metric": metric, "band": band})
        return result.result_rows[0][0] > 0

    def insert_anomalies(self, anomalies: list[Anomaly]) -> None:
        if not anomalies:
            return
        rows = [
            (
                a.id,
                a.detected_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                a.cluster_id,
                a.node_id,
                a.metric,
                a.band,
                a.z_score,
                a.baseline_window[0],
                a.baseline_window[1],
                "open",
                None,
                None,
                None,
            )
            for a in anomalies
        ]
        self.client.insert(
            "anomalies",
            rows,
            column_names=[
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
            ],
        )

    def list_open_anomalies(self, cluster_id: int | None = None) -> list[dict[str, Any]]:
        clauses = ["status = 'open'"]
        params: dict[str, Any] = {}
        if cluster_id is not None:
            clauses.append("cluster_id = {cluster_id:Int32}")
            params["cluster_id"] = cluster_id
        query = f"SELECT * FROM anomalies WHERE {' AND '.join(clauses)} ORDER BY detected_at DESC"
        result = self.client.query(query, parameters=params)
        return [dict(zip(result.column_names, row)) for row in result.result_rows]

    def dismiss(self, anomaly_id: str, node_id: str, metric: str, band: str, by: str, reason: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        self.client.command(
            "ALTER TABLE anomalies UPDATE status='dismissed', dismissed_at={now:DateTime64(3)}, "
            "dismissed_by={by:String}, dismiss_reason={reason:String} WHERE id={id:String}",
            parameters={
                "now": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "by": by,
                "reason": reason or "",
                "id": anomaly_id,
            },
        )
        self.client.insert(
            "suppression_rules",
            [(str(uuid.uuid4()), node_id, metric, band, now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], by, reason)],
            column_names=["id", "node_id", "metric", "band", "created_at", "created_by", "reason"],
        )
