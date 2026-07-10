"""Content-addressed on-disk cache: key = sha256(request params).

Stores a .npz (numpy arrays) + a .json sidecar (everything else: node/metric
lists, null_segments as records, coverage as a list). This is the mechanism
that lets a cold `get_tensor()` cost seconds while a repeat call for the same
{time_range, nodes, metrics, resolution} costs a disk read.

Deliberately uncompressed (np.savez, not np.savez_compressed): profiling at
milestone scale (500 nodes x 100 metrics x 1 day @15s, ~2.3GB tensor) found
zlib decompression costing 9.1s per cache read vs 2.46s uncompressed -- a
3.7x hit on every "warm" load, in exchange for only ~7% smaller files on
data that doesn't compress well. Cache reads happen far more often than
writes, so read latency dominates the tradeoff.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


def make_key(params: dict[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class DiskCache:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.root / f"{key}.npz", self.root / f"{key}.json"

    def has(self, key: str) -> bool:
        npz_path, json_path = self._paths(key)
        return npz_path.exists() and json_path.exists()

    def put(self, key: str, arrays: dict[str, np.ndarray], meta: dict[str, Any]) -> None:
        npz_path, json_path = self._paths(key)
        np.savez(npz_path, **arrays)  # type: ignore[arg-type]  # numpy stub misparses **kwargs here
        json_path.write_text(json.dumps(meta, default=str))

    def get(self, key: str) -> tuple[dict[str, np.ndarray], dict[str, Any]] | None:
        if not self.has(key):
            return None
        npz_path, json_path = self._paths(key)
        with np.load(npz_path, allow_pickle=False) as data:
            arrays = {k: data[k] for k in data.files}
        meta = json.loads(json_path.read_text())
        return arrays, meta
