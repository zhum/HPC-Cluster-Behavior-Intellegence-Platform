"""get_tensor(request) -> TensorBundle: the tensor-store's public contract.

Orchestrates loader -> grid -> tensor -> nulls -> coverage-based filtering,
with a content-addressed cache in front of the whole pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from clickhouse_connect.driver.client import Client

from tensor_store.cache import DiskCache, make_key
from tensor_store.loader import list_metrics, list_nodes, load_gridded
from tensor_store.tensor import bucketed_to_tensor

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "hpc-behavior-platform" / "tensor-store"

METRIC_COVERAGE_MIN = 0.5   # metrics below this coverage are dropped
NODE_COVERAGE_MIN = 0.2     # nodes below this coverage are flagged inactive (kept)

# Fetching+gridding all metrics in one pandas pass holds several full-size
# (N, M, T) intermediates (long df, wide pivot, reindex, ffill, restack) live
# at once -- at 500 nodes x 100 metrics x 1 day @15s that peaks at 20GB+ and
# OOMs. Batching by metric bounds each batch's intermediates to (N, batch, T).
METRIC_BATCH_SIZE = 20


@dataclass(frozen=True)
class TensorRequest:
    start: datetime
    end: datetime
    resolution_s: int  # 15 | 60 | 300
    nodes: list[str] | None = None
    metrics: list[str] | None = None

    def cache_params(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "resolution_s": self.resolution_s,
            "nodes": sorted(self.nodes) if self.nodes else None,
            "metrics": sorted(self.metrics) if self.metrics else None,
        }


@dataclass
class TensorBundle:
    X: np.ndarray                  # (N, M, T), NaN allowed
    nodes: list[str]
    metrics: list[str]
    times: np.ndarray
    null_segments: pd.DataFrame    # node_id, seg_start, seg_end (all-metric nulls)
    coverage: np.ndarray           # (N, M) fraction of non-NaN
    inactive_nodes: list[str] = field(default_factory=list)


def _coverage(X: np.ndarray) -> np.ndarray:
    """(N, M, T) -> (N, M) fraction of non-NaN entries along T."""
    if X.shape[2] == 0:
        return np.zeros((X.shape[0], X.shape[1]))
    return 1.0 - np.isnan(X).mean(axis=2)


def _filter_low_coverage_metrics(
    X: np.ndarray, metrics: list[str], coverage: np.ndarray
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Drop metrics whose mean coverage across nodes is below threshold."""
    if X.shape[1] == 0:
        return X, metrics, coverage
    metric_coverage = coverage.mean(axis=0)
    keep = metric_coverage >= METRIC_COVERAGE_MIN
    dropped = [m for m, k in zip(metrics, keep) if not k]
    if dropped:
        print(f"[tensor-store] dropping low-coverage metrics (<{METRIC_COVERAGE_MIN}): {dropped}")
    return X[:, keep, :], [m for m, k in zip(metrics, keep) if k], coverage[:, keep]


def _flag_inactive_nodes(nodes: list[str], coverage: np.ndarray) -> list[str]:
    """Nodes whose mean coverage across (kept) metrics is below threshold are
    flagged inactive but NOT dropped -- persistent-nulls nodes are a real
    cluster in the paper's findings.
    """
    if coverage.shape[1] == 0:
        return []
    node_coverage = coverage.mean(axis=1)
    return [n for n, c in zip(nodes, node_coverage) if c < NODE_COVERAGE_MIN]


def _drop_constant_metrics(
    X: np.ndarray, metrics: list[str]
) -> tuple[np.ndarray, list[str]]:
    from tensor_store.normalize import constant_metric_mask

    mask = constant_metric_mask(X)
    if mask.any():
        dropped = [m for m, is_const in zip(metrics, mask) if is_const]
        print(f"[tensor-store] dropping constant metrics: {dropped}")
    keep = ~mask
    return X[:, keep, :], [m for m, k in zip(metrics, keep) if k]


def get_tensor(
    request: TensorRequest,
    client: Client | None = None,
    cache: DiskCache | None = None,
    use_cache: bool = True,
) -> TensorBundle:
    from tensor_store.nulls import null_segments as compute_null_segments

    cache = cache or DiskCache(DEFAULT_CACHE_DIR)
    key = make_key(request.cache_params())

    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            arrays, meta = cached
            return TensorBundle(
                X=arrays["X"],
                nodes=meta["nodes"],
                metrics=meta["metrics"],
                times=arrays["times"],
                null_segments=pd.DataFrame(meta["null_segments"]),
                coverage=arrays["coverage"],
                inactive_nodes=meta["inactive_nodes"],
            )

    if client is None:
        raise ValueError("client required on cache miss")

    # fix stable node/metric axes up front so every metric-batch pivots onto
    # the same (N,) ordering and can be concatenated at the end.
    nodes = request.nodes if request.nodes is not None else list_nodes(client, request.start, request.end)
    metrics = (
        request.metrics if request.metrics is not None else list_metrics(client, request.start, request.end)
    )

    X_batches = []
    times = np.array([], dtype="datetime64[ns]")
    for i in range(0, len(metrics), METRIC_BATCH_SIZE):
        batch_metrics = metrics[i : i + METRIC_BATCH_SIZE]
        df_bucketed = load_gridded(
            client, request.start, request.end, nodes, batch_metrics, request.resolution_s
        )
        X_batch, _, _, times = bucketed_to_tensor(
            df_bucketed, nodes, batch_metrics, request.start, request.end, request.resolution_s
        )
        X_batches.append(X_batch)
        del df_bucketed

    X = (
        np.concatenate(X_batches, axis=1)
        if X_batches
        else np.full((len(nodes), 0, 0), np.nan)
    )

    coverage = _coverage(X)
    X, metrics, coverage = _filter_low_coverage_metrics(X, metrics, coverage)
    X, metrics = _drop_constant_metrics(X, metrics)
    coverage = _coverage(X)  # recompute post-drop for the returned bundle
    inactive_nodes = _flag_inactive_nodes(nodes, coverage)

    segments = compute_null_segments(X, nodes, times)

    bundle = TensorBundle(
        X=X,
        nodes=nodes,
        metrics=metrics,
        times=times,
        null_segments=segments,
        coverage=coverage,
        inactive_nodes=inactive_nodes,
    )

    if use_cache:
        cache.put(
            key,
            arrays={"X": bundle.X, "times": bundle.times, "coverage": bundle.coverage},
            meta={
                "nodes": bundle.nodes,
                "metrics": bundle.metrics,
                "null_segments": bundle.null_segments.to_dict(orient="records"),
                "inactive_nodes": bundle.inactive_nodes,
            },
        )

    return bundle
