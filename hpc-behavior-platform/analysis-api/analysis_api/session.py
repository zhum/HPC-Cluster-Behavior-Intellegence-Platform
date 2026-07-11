"""In-process session state: each session holds the materialized tensor
bundle plus an InterClusterPipeline instance (analysis-core's in-process
staged cache for V/E/labels/ccpca). Session state itself is NOT persisted to
Redis -- only stage artifacts are (see cache.py) -- so sessions require a
single long-lived process/worker in this implementation; documented as a
known limitation rather than solved here (out of Phase 5's stated scope).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from analysis_core.inter.pipeline import InterClusterPipeline
from tensor_store.api import TensorBundle

SessionStatus = Literal["pending", "ready", "error"]


@dataclass
class Session:
    session_id: str
    status: SessionStatus = "pending"
    bundle: TensorBundle | None = None
    pipeline: InterClusterPipeline | None = None
    error: str | None = None


@dataclass
class SessionStore:
    sessions: dict[str, Session] = field(default_factory=dict)

    def create_pending(self) -> Session:
        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id)
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def mark_ready(self, session_id: str, bundle: TensorBundle) -> None:
        session = self.sessions[session_id]
        session.bundle = bundle
        session.pipeline = InterClusterPipeline(bundle.X)
        session.status = "ready"

    def mark_error(self, session_id: str, error: str) -> None:
        session = self.sessions[session_id]
        session.status = "error"
        session.error = error
