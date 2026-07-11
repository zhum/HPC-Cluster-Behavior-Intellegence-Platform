"""Redis-backed content-addressed stage cache: key = sha256(stage params),
value = npz-serialized numpy arrays + a json meta sidecar, TTL 24h.

This is the Phase 5 half of the caching design started in analysis-core's
InterClusterPipeline (in-process LRU): the API layer additionally persists
each stage's output here so a fresh process (server restart, another worker)
can skip recomputation instead of only benefiting within a single
long-lived pipeline instance.
"""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from redis import Redis

TTL_SECONDS = 24 * 3600


def make_key(stage: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"stage": stage, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class RedisStageCache:
    client: Redis

    def _arrays_key(self, key: str) -> str:
        return f"stage:{key}:arrays"

    def _meta_key(self, key: str) -> str:
        return f"stage:{key}:meta"

    def get(self, key: str) -> tuple[dict[str, np.ndarray], dict[str, Any]] | None:
        arrays_blob = self.client.get(self._arrays_key(key))
        meta_blob = self.client.get(self._meta_key(key))
        if arrays_blob is None or meta_blob is None:
            return None
        with np.load(io.BytesIO(arrays_blob), allow_pickle=False) as data:
            arrays = {k: data[k] for k in data.files}
        meta = json.loads(meta_blob)
        return arrays, meta

    def put(self, key: str, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> None:
        buf = io.BytesIO()
        np.savez_compressed(buf, **arrays)  # type: ignore[arg-type]
        self.client.set(self._arrays_key(key), buf.getvalue(), ex=TTL_SECONDS)
        self.client.set(self._meta_key(key), json.dumps(meta, default=str), ex=TTL_SECONDS)
