# Ingestion routes
from fastapi import APIRouter, HTTPException

from ..schemas import IngestionChunkCreate, IngestionSessionCreate
from ..services.ingestion import (
    create_ingestion_session_record, get_ingestion_session_record,
    list_ingestion_session_records, finish_ingestion_session_record,
    create_ingestion_chunk_record, list_ingestion_chunk_records,
    get_ingestion_chunk_record, IngestionChunkConflictError
)

router = APIRouter()

@router.post("/api/ingestion-sessions")
async def create_ingestion_session(
    session: IngestionSessionCreate
):
    try:
        return create_ingestion_session_record(
            source_type=session.source_type,
            title=session.title,
            source=session.source,
            started_at=session.started_at
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

@router.get("/api/ingestion-sessions")
async def get_ingestion_sessions():
    return list_ingestion_session_records()

@router.get("/api/ingestion-sessions/{session_id}")
async def get_ingestion_session(
    session_id: int
):
    session = get_ingestion_session_record(
        session_id
    )

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Ingestion session not found"
        )

    return session

@router.post("/api/ingestion-sessions/{session_id}/chunks")
async def create_ingestion_chunk(
    session_id: int,
    chunk: IngestionChunkCreate
):
    try:
        result = create_ingestion_chunk_record(
            session_id=session_id,
            sequence=chunk.sequence,
            client_chunk_id=chunk.client_chunk_id,
            text=chunk.text,
            source_start_ms=chunk.source_start_ms,
            source_end_ms=chunk.source_end_ms
        )
    except IngestionChunkConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Ingestion session not found"
        )

    return result

@router.get("/api/ingestion-sessions/{session_id}/chunks")
async def get_ingestion_chunks(session_id: int):
    chunks = list_ingestion_chunk_records(session_id)

    if chunks is None:
        raise HTTPException(
            status_code=404,
            detail="Ingestion session not found"
        )

    return chunks

@router.get("/api/ingestion-chunks/{chunk_id}")
async def get_ingestion_chunk(chunk_id: int):
    chunk = get_ingestion_chunk_record(chunk_id)

    if chunk is None:
        raise HTTPException(
            status_code=404,
            detail="Ingestion chunk not found"
        )

    return chunk

@router.post("/api/ingestion-sessions/{session_id}/finish")
async def finish_ingestion_session(
    session_id: int
):
    try:
        session = finish_ingestion_session_record(
            session_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc)
        ) from exc

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Ingestion session not found"
        )

    # Finishing closes the upload horizon, so a short final STT window can be
    # queued safely. Import locally to keep ingestion/audio services decoupled.
    from ..services.audio import schedule_final_stt_windows
    schedule_final_stt_windows(session_id)

    return session
