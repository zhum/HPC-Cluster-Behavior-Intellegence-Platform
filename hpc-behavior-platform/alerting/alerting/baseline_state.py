"""Last-known-good baseline persistence per (cluster, metric).

Only updated after a clean run (no anomaly detected for that metric) --
otherwise an ongoing anomaly could pollute what the scheduler considers
"normal" on the next run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class BaselineStateStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get(self, cluster_id: int, metric: str) -> tuple[int, int] | None:
        query = (
            "SELECT window_start, window_end FROM baseline_state "
            "WHERE cluster_id = {cluster_id:Int32} AND metric = {metric:String}"
        )
        result = self.client.query(query, parameters={"cluster_id": cluster_id, "metric": metric})
        if not result.result_rows:
            return None
        row = result.result_rows[0]
        return int(row[0]), int(row[1])

    def set(self, cluster_id: int, metric: str, window: tuple[int, int]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.client.insert(
            "baseline_state",
            [(cluster_id, metric, window[0], window[1], now)],
            column_names=["cluster_id", "metric", "window_start", "window_end", "updated_at"],
        )
