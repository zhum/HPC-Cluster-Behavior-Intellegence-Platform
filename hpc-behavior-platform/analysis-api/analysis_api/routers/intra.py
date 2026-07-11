from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends

from analysis_api.deps import get_session_store, get_stage_cache
from analysis_api.schemas import BaselineRequest, BaselineResponse, ZScoresRequest, ZScoresResponse
from analysis_api.session import SessionStore
from analysis_api.staging import require_ready_session, run_staged
from analysis_core.intra.baseline import default_baseline
from analysis_core.intra.zscores import compute_zscores

router = APIRouter()


def _resolution_s(times: np.ndarray) -> float:
    if len(times) < 2:
        return 1.0
    return float((times[1] - times[0]) / np.timedelta64(1, "s"))


@router.post("/intra/zscores", response_model=ZScoresResponse)
def get_zscores(
    payload: ZScoresRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> ZScoresResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "node_ids": sorted(payload.node_ids),
        "metrics": sorted(payload.metrics),
        "band": payload.band,
        "baseline": payload.baseline,
    }

    def compute():
        node_idx = [session.bundle.nodes.index(n) for n in payload.node_ids]
        metric_idx = {m: i for i, m in enumerate(session.bundle.metrics)}
        tensor_by_metric = {
            m: session.bundle.X[np.ix_(node_idx, [metric_idx[m]])][:, 0, :] for m in payload.metrics
        }
        resolution_s = _resolution_s(session.bundle.times)
        result = compute_zscores(
            tensor_by_metric, band=payload.band, resolution_s=resolution_s, baseline_windows=payload.baseline
        )
        meta = {
            "metrics": result.metrics,
            "baseline_windows": {m: [s.start, s.stop] for m, s in result.baseline_windows.items()},
            "segment_used": {m: [s.start, s.stop] for m, s in result.segment_used.items()},
            "degenerate_metrics": result.degenerate_metrics,
        }
        return {"z": result.z}, meta

    arrays, meta, key, elapsed = run_staged(cache, "zscores", params, compute)
    return ZScoresResponse(
        z=arrays["z"].tolist(),
        metrics=meta["metrics"],
        node_ids=payload.node_ids,
        baseline_windows={m: (v[0], v[1]) for m, v in meta["baseline_windows"].items()},
        band=payload.band,
        segment_used={m: (v[0], v[1]) for m, v in meta["segment_used"].items()},
        degenerate_metrics=meta["degenerate_metrics"],
        cache_key=key,
        timings_ms={"zscores": elapsed},
    )


@router.post("/intra/baseline", response_model=BaselineResponse)
def get_baseline(
    payload: BaselineRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> BaselineResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {"session_id": payload.session_id, "metric": payload.metric, "node_ids": sorted(payload.node_ids)}

    def compute():
        node_idx = [session.bundle.nodes.index(n) for n in payload.node_ids]
        metric_i = session.bundle.metrics.index(payload.metric)
        S = session.bundle.X[np.ix_(node_idx, [metric_i])][:, 0, :]
        window, _ = default_baseline(S)
        q1, q3 = np.nanpercentile(S, [25, 75])
        return {"window": np.array([window.start, window.stop])}, {"iqr": [float(q1), float(q3)]}

    arrays, meta, key, elapsed = run_staged(cache, "baseline", params, compute)
    w = arrays["window"]
    return BaselineResponse(
        window=(int(w[0]), int(w[1])),
        iqr=(meta["iqr"][0], meta["iqr"][1]),
        cache_key=key,
        timings_ms={"baseline": elapsed},
    )
