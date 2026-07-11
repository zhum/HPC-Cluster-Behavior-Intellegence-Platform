from __future__ import annotations

from fastapi import APIRouter, Depends

from analysis_api.deps import get_clickhouse_client, get_session_store, get_stage_cache
from analysis_api.schemas import JobInterval, JobsOverlayRequest, JobsOverlayResponse
from analysis_api.session import SessionStore
from analysis_api.staging import require_ready_session, run_staged

router = APIRouter()


@router.post("/jobs/overlay", response_model=JobsOverlayResponse)
def get_jobs_overlay(
    payload: JobsOverlayRequest,
    session_store: SessionStore = Depends(get_session_store),
    cache=Depends(get_stage_cache),
    client=Depends(get_clickhouse_client),
) -> JobsOverlayResponse:
    require_ready_session(session_store, payload.session_id)
    params = {"session_id": payload.session_id, "node_ids": sorted(payload.node_ids)}

    def compute():
        query = "SELECT job_id, user, partition, node_list, state, start_time, end_time FROM jobs " \
            "WHERE hasAny(node_list, {node_ids:Array(String)})"
        result = client.query(query, parameters={"node_ids": payload.node_ids})

        node_set = set(payload.node_ids)
        intervals = []
        mapped_nodes: set[str] = set()
        for job_id, user, partition, node_list, state, start_time, end_time in result.result_rows:
            for node in node_list:
                if node in node_set:
                    mapped_nodes.add(node)
                    intervals.append(
                        {
                            "job_id": job_id,
                            "user": user,
                            "partition": partition,
                            "node_id": node,
                            "state": state,
                            "start": str(start_time),
                            "end": str(end_time) if end_time is not None else None,
                        }
                    )
        unmapped = [n for n in payload.node_ids if n not in mapped_nodes]
        return {}, {"intervals": intervals, "unmapped": unmapped}

    _, meta, key, elapsed = run_staged(cache, "jobs_overlay", params, compute)
    return JobsOverlayResponse(
        intervals=[JobInterval(**iv) for iv in meta["intervals"]],
        unmapped_nodes=meta["unmapped"],
        cache_key=key,
        timings_ms={"jobs_overlay": elapsed},
    )
