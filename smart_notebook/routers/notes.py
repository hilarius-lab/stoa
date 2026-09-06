# Note routes
from datetime import datetime
from fastapi import APIRouter, HTTPException

from ..config import TIMEZONE, EMBEDDING_MODEL

from ..database import get_db_connection
from ..schemas import NoteCreate, NoteUpdate, NoteSearch
from ..services.embeddings import get_embedding
from ..services.notes import (
    get_note_record, update_note, set_note_archived, search_notes, save_note
)

router = APIRouter()

@router.get("/api/notes/{note_id}")
async def get_note(note_id: int):
    note = get_note_record(note_id)

    if note is None:
        raise HTTPException(
            status_code=404,
            detail="Note not found"
        )

    return note

@router.patch("/api/notes/{note_id}")
async def patch_note(
    note_id: int,
    note: NoteUpdate
):
    existing = get_note_record(note_id)

    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Note not found"
        )

    content = note.content.strip()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Note content must not be empty"
        )

    await update_note(
        note_id,
        content
    )

    return get_note_record(note_id)

@router.post("/api/notes/{note_id}/archive")
async def archive_note(note_id: int):
    result = set_note_archived(
        note_id,
        True
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Note not found"
        )

    return result

@router.post("/api/notes/{note_id}/unarchive")
async def unarchive_note(note_id: int):
    result = set_note_archived(
        note_id,
        False
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Note not found"
        )

    return result

@router.post("/api/search-notes")
async def api_search_notes(search: NoteSearch):
    results = await search_notes(
        search.query,
        search.limit
    )

    return {
        "query": search.query,
        "count": len(results),
        "results": results
    }

@router.post("/api/notes")
async def create_note(note: NoteCreate):
    now = datetime.now(TIMEZONE)
    embedding = await get_embedding(note.content)

    note_id = save_note(
        note.content,
        embedding,
        source_event_id=note.source_event_id
    )

    return {
        "id": note_id,
        "content": note.content,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "source_event_id": note.source_event_id,
        "archived": False,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": len(embedding)
    }

@router.get("/api/notes")
async def get_notes(
    include_archived: bool = False
):
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                content,
                created_at,
                updated_at,
                source_event_id,
                archived,
                embedding_model,
                CASE WHEN embedding IS NULL THEN NULL ELSE vector_dims(embedding) END
            FROM notes
            WHERE (%s = TRUE OR archived = FALSE)
            ORDER BY updated_at DESC
            """,
            (include_archived,)
        ).fetchall()

    return [
        {
            "id": row[0],
            "content": row[1],
            "created_at": row[2].isoformat(),
            "updated_at": row[3].isoformat(),
            "source_event_id": row[4],
            "archived": row[5],
            "embedding_model": row[6],
            "embedding_dimensions": row[7]
        }
        for row in rows
    ]
