# Session recovery routes
from fastapi import APIRouter, HTTPException

from ..schemas import IngestionSessionRepairRequest
from ..services.recovery import (
    get_session_processing_state, refresh_session_watermarks,
    repair_ingestion_session_record
)

router = APIRouter()


@router.get("/api/ingestion-sessions/{session_id}/watermarks")
async def get_ingestion_session_watermarks(session_id: int):
    watermarks = refresh_session_watermarks(session_id)
    if watermarks is None:
        raise HTTPException(status_code=404, detail="Ingestion session not found")
    return watermarks


@router.get("/api/ingestion-sessions/{session_id}/processing-state")
async def get_ingestion_session_processing_state(session_id: int):
    state = get_session_processing_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Ingestion session not found")
    return state


@router.post("/api/ingestion-sessions/{session_id}/repair")
async def repair_ingestion_session(
    session_id: int,
    request: IngestionSessionRepairRequest
):
    try:
        result = repair_ingestion_session_record(
            session_id=session_id,
            dry_run=request.dry_run,
            stale_after_minutes=request.stale_after_minutes
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Ingestion session not found")
    return result
