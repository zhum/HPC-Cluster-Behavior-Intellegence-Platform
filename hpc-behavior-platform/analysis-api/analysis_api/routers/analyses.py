from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from analysis_api.deps import get_saved_analyses_store
from analysis_api.saved_analyses import SavedAnalysesStore
from analysis_api.schemas import (
    ListAnalysesResponse,
    SaveAnalysisRequest,
    SavedAnalysisDetail,
    SavedAnalysisSummary,
)

router = APIRouter()


@router.post("/analyses", response_model=SavedAnalysisSummary)
def save_analysis(
    payload: SaveAnalysisRequest, store: SavedAnalysesStore = Depends(get_saved_analyses_store)
) -> SavedAnalysisSummary:
    if payload.analysis_id is not None and store.get(payload.analysis_id, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="analysis not found for this user")

    aid = store.save(payload.user_id, payload.name, payload.state, payload.analysis_id)
    saved = store.get(aid, payload.user_id)
    assert saved is not None
    return SavedAnalysisSummary(id=saved["id"], user_id=saved["user_id"], name=saved["name"], updated_at=saved["updated_at"])


@router.get("/analyses", response_model=ListAnalysesResponse)
def list_analyses(
    user_id: str, store: SavedAnalysesStore = Depends(get_saved_analyses_store)
) -> ListAnalysesResponse:
    analyses = [SavedAnalysisSummary(**a) for a in store.list_for_user(user_id)]
    return ListAnalysesResponse(analyses=analyses)


@router.get("/analyses/{analysis_id}", response_model=SavedAnalysisDetail)
def get_analysis(
    analysis_id: str, user_id: str, store: SavedAnalysesStore = Depends(get_saved_analyses_store)
) -> SavedAnalysisDetail:
    result = store.get(analysis_id, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found for this user")
    return SavedAnalysisDetail(**result)


@router.delete("/analyses/{analysis_id}")
def delete_analysis(
    analysis_id: str, user_id: str, store: SavedAnalysesStore = Depends(get_saved_analyses_store)
) -> dict[str, bool]:
    deleted = store.delete(analysis_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="analysis not found for this user")
    return {"deleted": True}
