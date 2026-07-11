from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends

from analysis_api.deps import get_session_store, get_stage_cache
from analysis_api.schemas import RawSeriesRequest, RawSeriesResponse
from analysis_api.session import SessionStore
from analysis_api.staging import require_ready_session, run_staged

router = APIRouter()


@router.post("/raw/series", response_model=RawSeriesResponse)
def get_raw_series(
    payload: RawSeriesRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
) -> RawSeriesResponse:
    session = require_ready_session(session_store, payload.session_id)
    params = {
        "session_id": payload.session_id,
        "node_ids": sorted(payload.node_ids),
        "metrics": sorted(payload.metrics),
        "t0": payload.t0,
        "t1": payload.t1,
        "max_points": payload.max_points,
    }

    def compute():
        node_idx = [session.bundle.nodes.index(n) for n in payload.node_ids]
        metric_idx = [session.bundle.metrics.index(m) for m in payload.metrics]
        t_idx = list(range(payload.t0, payload.t1))
        X = session.bundle.X[np.ix_(node_idx, metric_idx, t_idx)]
        times_slice = session.bundle.times[payload.t0 : payload.t1]

        n_t = X.shape[2]
        if n_t > payload.max_points:
            step = int(np.ceil(n_t / payload.max_points))
            keep = np.arange(0, n_t, step)
            X = X[:, :, keep]
            times_slice = times_slice[keep]

        return {"X": X}, {"times": [str(t) for t in times_slice]}

    arrays, meta, key, elapsed = run_staged(cache, "raw_series", params, compute)
    X = arrays["X"]
    series: dict[str, dict[str, list[float]]] = {}
    for n_i, node in enumerate(payload.node_ids):
        series[node] = {m: X[n_i, m_i, :].tolist() for m_i, m in enumerate(payload.metrics)}

    return RawSeriesResponse(times=meta["times"], series=series, cache_key=key, timings_ms={"raw_series": elapsed})
