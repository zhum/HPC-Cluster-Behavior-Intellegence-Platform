"""Phase 8 item 3 (multi-user sessions, optional/beyond the paper): saved
analyses persisted per user. Ownership is enforced entirely by the WHERE
clause on every read/write -- get/delete for an analysis_id that exists but
belongs to a different user_id behaves identically to it not existing.

Deletion is a soft-delete flag, not ClickHouse's ALTER TABLE ... DELETE:
that's an async mutation with no guaranteed immediate visibility to a
subsequent SELECT (confirmed live -- a delete followed immediately by a
list refresh still showed the "deleted" row). Riding the same
ReplacingMergeTree(updated_at) + FINAL read pattern already used for
updates keeps deletes synchronously visible too.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

_COLUMNS = ["id", "user_id", "name", "state_json", "deleted", "created_at", "updated_at"]


class SavedAnalysesStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    def save(self, user_id: str, name: str, state: dict[str, Any], analysis_id: str | None = None) -> str:
        aid = analysis_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.client.insert(
            "saved_analyses",
            [(aid, user_id, name, json.dumps(state), 0, now, now)],
            column_names=_COLUMNS,
        )
        return aid

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        query = (
            "SELECT id, user_id, name, updated_at FROM saved_analyses FINAL "
            "WHERE user_id = {user_id:String} AND deleted = 0 ORDER BY updated_at DESC"
        )
        result = self.client.query(query, parameters={"user_id": user_id})
        return [
            {"id": r[0], "user_id": r[1], "name": r[2], "updated_at": str(r[3])} for r in result.result_rows
        ]

    def get(self, analysis_id: str, user_id: str) -> dict[str, Any] | None:
        query = (
            "SELECT id, user_id, name, state_json, updated_at FROM saved_analyses FINAL "
            "WHERE id = {id:String} AND user_id = {user_id:String} AND deleted = 0"
        )
        result = self.client.query(query, parameters={"id": analysis_id, "user_id": user_id})
        if not result.result_rows:
            return None
        r = result.result_rows[0]
        return {"id": r[0], "user_id": r[1], "name": r[2], "state": json.loads(r[3]), "updated_at": str(r[4])}

    def delete(self, analysis_id: str, user_id: str) -> bool:
        existing = self.get(analysis_id, user_id)
        if existing is None:
            return False
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.client.insert(
            "saved_analyses",
            [(analysis_id, user_id, existing["name"], json.dumps(existing["state"]), 1, now, now)],
            column_names=_COLUMNS,
        )
        return True
