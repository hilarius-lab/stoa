# Semantic segmentation routes
from fastapi import APIRouter, HTTPException

from ..schemas import TextProcessingRunOnceRequest
from ..services.segmentation import (
    get_semantic_segment_record, list_semantic_segment_records,
    run_text_processing_once
)

router = APIRouter()


@router.get("/api/ingestion-sessions/{session_id}/segments")
async def get_ingestion_session_segments(session_id: int):
    segments = list_semantic_segment_records(session_id)
    if segments is None:
        raise HTTPException(status_code=404, detail="Ingestion session not found")
    return segments


@router.get("/api/semantic-segments/{segment_id}")
async def get_semantic_segment(segment_id: int):
    segment = get_semantic_segment_record(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Semantic segment not found")
    return segment


@router.post("/api/workers/text-processing/run-once")
async def run_text_processing_worker_once(request: TextProcessingRunOnceRequest):
    try:
        return await run_text_processing_once(
            worker_id=request.worker_id,
            mode=request.mode,
            ingestion_session_id=request.ingestion_session_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
