"""Shared helper for the check-Redis / else-compute-and-store pattern used by
every endpoint that reports cache_key + timings_ms.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import numpy as np
from fastapi import HTTPException

from analysis_api.cache import RedisStageCache, make_key
from analysis_api.session import Session, SessionStore


def require_ready_session(session_store: SessionStore, session_id: str) -> Session:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.status == "pending":
        raise HTTPException(status_code=409, detail="session not ready yet; poll /session/{id}/status")
    if session.status == "error":
        raise HTTPException(status_code=409, detail=f"session failed: {session.error}")
    return session


def run_staged(
    cache: RedisStageCache,
    stage: str,
    params: dict[str, Any],
    compute: Callable[[], tuple[dict[str, np.ndarray], dict[str, Any]]],
) -> tuple[dict[str, np.ndarray], dict[str, Any], str, float]:
    """compute() -> (arrays, meta). Returns (arrays, meta, cache_key, elapsed_ms)."""
    key = make_key(stage, params)
    t0 = time.perf_counter()

    cached = cache.get(key)
    if cached is not None:
        arrays, meta = cached
        return arrays, meta, key, (time.perf_counter() - t0) * 1000

    arrays, meta = compute()
    cache.put(key, arrays, meta)
    return arrays, meta, key, (time.perf_counter() - t0) * 1000
