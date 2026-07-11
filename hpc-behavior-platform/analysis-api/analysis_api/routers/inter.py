from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends

from analysis_api.deps import get_session_store, get_stage_cache
from analysis_api.schemas import (
    ClusterMeansRequest,
    ClusterMeansResponse,
    ClustersRequest,
    ClustersResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    ExplainRequest,
    ExplainResponse,
    ExplainResult,
    NullSegment,
    TimeDomainRequest,
    TimeDomainResponse,
)
from analysis_api.session import SessionStore
from analysis_api.staging import require_ready_session, run_staged
from analysis_core.inter.quality import cluster_quality

router = APIRouter()


@router.post("/inter/embedding", response_model=EmbeddingResponse)
def get_embedding(
    payload: EmbeddingRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> EmbeddingResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "n_neighbors": payload.n_neighbors,
        "min_dist": payload.min_dist,
        "random_state": payload.random_state,
    }

    def compute():
        E = session.pipeline.get_E(
            n_neighbors=payload.n_neighbors, min_dist=payload.min_dist, random_state=payload.random_state
        )
        return {"E": E}, {}

    arrays, _, key, elapsed = run_staged(cache, "embedding", params, compute)
    inactive_flags = [n in session.bundle.inactive_nodes for n in session.bundle.nodes]
    return EmbeddingResponse(
        E=arrays["E"].tolist(), inactive_flags=inactive_flags, cache_key=key, timings_ms={"embedding": elapsed}
    )


@router.post("/inter/clusters", response_model=ClustersResponse)
def get_clusters(
    payload: ClustersRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> ClustersResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "k": payload.k,
        "n_neighbors": payload.n_neighbors,
        "min_dist": payload.min_dist,
        "random_state": payload.random_state,
        "n_init": payload.n_init,
    }

    def compute():
        labels, centroids = session.pipeline.get_labels(
            k=payload.k,
            n_neighbors=payload.n_neighbors,
            min_dist=payload.min_dist,
            random_state=payload.random_state,
            n_init=payload.n_init,
        )
        E = session.pipeline.get_E(
            n_neighbors=payload.n_neighbors, min_dist=payload.min_dist, random_state=payload.random_state
        )
        quality = cluster_quality(E, labels)
        return {"labels": labels.astype(np.float64), "centroids": centroids}, {"quality": quality}

    arrays, meta, key, elapsed = run_staged(cache, "clusters", params, compute)
    return ClustersResponse(
        labels=[int(x) for x in arrays["labels"]],
        centroids=arrays["centroids"].tolist(),
        quality_metrics=meta["quality"],
        cache_key=key,
        timings_ms={"clusters": elapsed},
    )


@router.post("/inter/explain", response_model=ExplainResponse)
def get_explain(
    payload: ExplainRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> ExplainResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "k": payload.k,
        "n_neighbors": payload.n_neighbors,
        "min_dist": payload.min_dist,
        "random_state": payload.random_state,
        "n_init": payload.n_init,
    }

    def compute():
        ccpca_results = session.pipeline.get_ccpca(
            k=payload.k,
            n_neighbors=payload.n_neighbors,
            min_dist=payload.min_dist,
            random_state=payload.random_state,
            n_init=payload.n_init,
        )
        weights = np.stack([r.weights for r in ccpca_results])
        alphas = np.array([r.alpha for r in ccpca_results])
        meta = {
            "clusters": [r.cluster for r in ccpca_results],
            "ranked": [r.ranked_metric_idx.tolist() for r in ccpca_results],
        }
        return {"weights": weights, "alphas": alphas}, meta

    arrays, meta, key, elapsed = run_staged(cache, "explain", params, compute)
    results = []
    for i, cluster in enumerate(meta["clusters"]):
        ranked_names = [session.bundle.metrics[j] for j in meta["ranked"][i]]
        results.append(
            ExplainResult(
                cluster=cluster,
                weights=arrays["weights"][i].tolist(),
                ranked_metrics=ranked_names,
                alpha=float(arrays["alphas"][i]),
            )
        )
    return ExplainResponse(results=results, cache_key=key, timings_ms={"explain": elapsed})


@router.post("/inter/timedomain", response_model=TimeDomainResponse)
def get_timedomain(
    payload: TimeDomainRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> TimeDomainResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "k": payload.k,
        "n_neighbors": payload.n_neighbors,
        "min_dist": payload.min_dist,
        "random_state": payload.random_state,
        "n_init": payload.n_init,
    }

    def compute():
        labels, _ = session.pipeline.get_labels(
            k=payload.k,
            n_neighbors=payload.n_neighbors,
            min_dist=payload.min_dist,
            random_state=payload.random_state,
            n_init=payload.n_init,
        )
        return {"labels": labels.astype(np.float64)}, {}

    arrays, _, key, elapsed = run_staged(cache, "timedomain", params, compute)
    labels = arrays["labels"].astype(int)
    node_to_cluster = dict(zip(session.bundle.nodes, labels))

    clusters: dict[str, list[NullSegment]] = {}
    for _, row in session.bundle.null_segments.iterrows():
        cluster = node_to_cluster.get(row["node_id"])
        if cluster is None:
            continue
        clusters.setdefault(str(cluster), []).append(
            NullSegment(node_id=row["node_id"], seg_start=str(row["seg_start"]), seg_end=str(row["seg_end"]))
        )

    return TimeDomainResponse(clusters=clusters, cache_key=key, timings_ms={"timedomain": elapsed})


@router.post("/inter/cluster_means", response_model=ClusterMeansResponse)
def get_cluster_means(
    payload: ClusterMeansRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> ClusterMeansResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "k": payload.k,
        "n_neighbors": payload.n_neighbors,
        "min_dist": payload.min_dist,
        "random_state": payload.random_state,
        "n_init": payload.n_init,
    }

    def compute():
        labels, _ = session.pipeline.get_labels(
            k=payload.k,
            n_neighbors=payload.n_neighbors,
            min_dist=payload.min_dist,
            random_state=payload.random_state,
            n_init=payload.n_init,
        )
        return {"labels": labels.astype(np.float64)}, {}

    arrays, _, key, elapsed = run_staged(cache, "cluster_means", params, compute)
    labels = arrays["labels"].astype(int)

    X = session.bundle.X
    metric_idx = {m: i for i, m in enumerate(session.bundle.metrics)}
    polylines: dict[str, dict[str, list[float]]] = {}
    for cluster in sorted(set(labels)):
        mask = labels == cluster
        cluster_dict: dict[str, list[float]] = {}
        for metric in payload.metrics:
            if metric not in metric_idx:
                continue
            series = np.nanmean(X[mask, metric_idx[metric], :], axis=0)
            if payload.smoothing_w > 1:
                kernel = np.ones(payload.smoothing_w) / payload.smoothing_w
                series = np.convolve(np.nan_to_num(series), kernel, mode="same")
            cluster_dict[metric] = series.tolist()
        polylines[str(cluster)] = cluster_dict

    return ClusterMeansResponse(
        times=[str(t) for t in session.bundle.times],
        polylines=polylines,
        cache_key=key,
        timings_ms={"cluster_means": elapsed},
    )
