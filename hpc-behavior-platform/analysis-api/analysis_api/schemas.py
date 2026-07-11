from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TensorRequestModel(BaseModel):
    start: datetime
    end: datetime
    resolution_s: int
    nodes: list[str] | None = None
    metrics: list[str] | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    status: Literal["pending", "ready", "error"]


class SessionStatusResponse(BaseModel):
    session_id: str
    status: Literal["pending", "ready", "error"]
    error: str | None = None
    n_nodes: int | None = None
    n_metrics: int | None = None
    n_timesteps: int | None = None


class UmapParams(BaseModel):
    n_neighbors: int = 15
    min_dist: float = 0.1
    random_state: int = 42


class EmbeddingRequest(UmapParams):
    session_id: str


class EmbeddingResponse(BaseModel):
    E: list[list[float]]
    inactive_flags: list[bool]
    cache_key: str
    timings_ms: dict[str, float]


class ClustersRequest(UmapParams):
    session_id: str
    k: int = 4
    n_init: int = 10


class ClustersResponse(BaseModel):
    labels: list[int]
    centroids: list[list[float]]
    quality_metrics: dict[str, float]
    cache_key: str
    timings_ms: dict[str, float]


class ExplainRequest(UmapParams):
    session_id: str
    k: int = 4
    n_init: int = 10


class ExplainResult(BaseModel):
    cluster: int
    weights: list[float]
    ranked_metrics: list[str]
    alpha: float


class ExplainResponse(BaseModel):
    results: list[ExplainResult]
    cache_key: str
    timings_ms: dict[str, float]


class TimeDomainRequest(UmapParams):
    session_id: str
    k: int = 4
    n_init: int = 10


class NullSegment(BaseModel):
    node_id: str
    seg_start: str
    seg_end: str


class TimeDomainResponse(BaseModel):
    clusters: dict[str, list[NullSegment]]
    cache_key: str
    timings_ms: dict[str, float]


class ClusterMeansRequest(UmapParams):
    session_id: str
    k: int = 4
    n_init: int = 10
    metrics: list[str]
    smoothing_w: int = 1


class ClusterMeansResponse(BaseModel):
    times: list[str]
    polylines: dict[str, dict[str, list[float]]]  # cluster_id(str) -> metric -> values
    cache_key: str
    timings_ms: dict[str, float]


class ZScoresRequest(BaseModel):
    session_id: str
    node_ids: list[str]
    metrics: list[str]
    band: Literal["5m", "30m", "2h", "24h", "7d"]
    baseline: dict[str, tuple[int, int]] | None = None


class ZScoresResponse(BaseModel):
    z: list[list[float]]
    metrics: list[str]
    node_ids: list[str]
    baseline_windows: dict[str, tuple[int, int]]
    band: str
    segment_used: dict[str, tuple[int, int]]
    degenerate_metrics: list[str]
    cache_key: str
    timings_ms: dict[str, float]


class BaselineRequest(BaseModel):
    session_id: str
    metric: str
    node_ids: list[str]


class BaselineResponse(BaseModel):
    window: tuple[int, int]
    iqr: tuple[float, float]
    cache_key: str
    timings_ms: dict[str, float]


class RawSeriesRequest(BaseModel):
    session_id: str
    node_ids: list[str]
    metrics: list[str]
    t0: int
    t1: int
    max_points: int = 2000


class RawSeriesResponse(BaseModel):
    times: list[str]
    series: dict[str, dict[str, list[float]]]  # node_id -> metric -> values
    cache_key: str
    timings_ms: dict[str, float]


class JobsOverlayRequest(BaseModel):
    session_id: str
    node_ids: list[str]


class JobInterval(BaseModel):
    job_id: str
    user: str
    partition: str
    node_id: str
    state: str
    start: str
    end: str | None


class JobsOverlayResponse(BaseModel):
    intervals: list[JobInterval]
    unmapped_nodes: list[str]
    cache_key: str
    timings_ms: dict[str, float]
