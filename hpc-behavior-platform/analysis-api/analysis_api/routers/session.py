from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from analysis_api.deps import get_clickhouse_client, get_session_store
from analysis_api.envelope import enforce_envelope
from analysis_api.schemas import SessionCreateResponse, SessionStatusResponse, TensorRequestModel
from analysis_api.session import SessionStore
from tensor_store.api import TensorRequest, get_tensor

router = APIRouter()


def _materialize(session_store: SessionStore, session_id: str, payload: TensorRequestModel, client) -> None:
    """Runs via BackgroundTasks -- Starlette executes sync background
    callables in a threadpool, so this doesn't block the HTTP response;
    the client polls /session/{id}/status until it flips to ready/error.
    """
    try:
        request = TensorRequest(
            start=payload.start,
            end=payload.end,
            resolution_s=payload.resolution_s,
            nodes=payload.nodes,
            metrics=payload.metrics,
        )
        bundle = get_tensor(request, client=client)
        enforce_envelope(len(bundle.nodes), len(bundle.metrics), bundle.X.shape[2])
        session_store.mark_ready(session_id, bundle)
        # "warms dr1": eagerly compute V so the first /inter/embedding call is warm too.
        session = session_store.get(session_id)
        if session is not None and session.pipeline is not None:
            session.pipeline.get_V()
    except HTTPException as e:
        session_store.mark_error(session_id, e.detail if isinstance(e.detail, str) else str(e.detail))
    except Exception as e:  # noqa: BLE001 -- surface any failure via session status, not a raised exception
        session_store.mark_error(session_id, str(e))


@router.post("/session/create", response_model=SessionCreateResponse)
def create_session(
    payload: TensorRequestModel,
    background_tasks: BackgroundTasks,
    session_store: SessionStore = Depends(get_session_store),
    client=Depends(get_clickhouse_client),
) -> SessionCreateResponse:
    session = session_store.create_pending()
    background_tasks.add_task(_materialize, session_store, session.session_id, payload, client)
    return SessionCreateResponse(session_id=session.session_id, status="pending")


@router.get("/session/{session_id}/status", response_model=SessionStatusResponse)
def session_status(
    session_id: str, session_store: SessionStore = Depends(get_session_store)
) -> SessionStatusResponse:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    resp = SessionStatusResponse(session_id=session_id, status=session.status, error=session.error)
    if session.bundle is not None:
        resp.n_nodes = len(session.bundle.nodes)
        resp.n_metrics = len(session.bundle.metrics)
        resp.n_timesteps = session.bundle.X.shape[2]
    return resp
