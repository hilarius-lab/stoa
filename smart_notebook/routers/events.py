# Event routes
from datetime import datetime
from fastapi import APIRouter, HTTPException

from ..database import get_db_connection
from ..schemas import EventCreate, EventBatch, Message
from ..services.events import (
    create_event_record, get_event_record, get_event_record_by_client_id,
    mark_event_capture_processed, process_stored_event_capture, set_event_archived
)
from ..services.capture import process_capture_action
from ..services.chat import ask_llm
from ..services.provenance import get_event_knowledge

router = APIRouter()

@router.post("/api/events")
async def create_event(event: EventCreate):
    """
    Store a raw Event without running capture classification or an assistant reply.
    Useful for later device, speech-to-text and offline-sync ingestion.
    """
    return create_event_record(
        event.text,
        created_at=event.created_at,
        source=event.source,
        client_event_id=event.client_event_id
    )

@router.post("/api/capture")
async def capture_without_chat(event: EventCreate):
    """
    Store an Event and run Note/Task capture, but do not ask the chat LLM for a reply.
    """
    stored_event = create_event_record(
        event.text,
        created_at=event.created_at,
        source=event.source,
        client_event_id=event.client_event_id
    )

    processing = await process_stored_event_capture(
        stored_event["id"]
    )

    return {
        "event": get_event_record(stored_event["id"]),
        "already_existed": not stored_event["created"],
        "capture": processing["capture"],
        "capture_already_processed": processing["already_processed"]
    }

@router.post("/api/events/batch")
async def create_events_batch(batch: EventBatch):
    if len(batch.events) > 100:
        raise HTTPException(
            status_code=400,
            detail="A batch may contain at most 100 events"
        )

    results = [
        create_event_record(
            item.text,
            created_at=item.created_at,
            source=item.source,
            client_event_id=item.client_event_id
        )
        for item in batch.events
    ]

    created_count = sum(
        1 for item in results if item["created"]
    )

    return {
        "count": len(results),
        "created_count": created_count,
        "existing_count": len(results) - created_count,
        "events": results
    }

@router.post("/api/capture/batch")
async def capture_events_batch(batch: EventBatch):
    if len(batch.events) > 100:
        raise HTTPException(
            status_code=400,
            detail="A batch may contain at most 100 events"
        )

    results = []
    created_count = 0
    processed_count = 0
    already_processed_count = 0

    for item in batch.events:
        stored = create_event_record(
            item.text,
            created_at=item.created_at,
            source=item.source,
            client_event_id=item.client_event_id
        )

        if stored["created"]:
            created_count += 1

        processing = await process_stored_event_capture(
            stored["id"]
        )

        if processing["already_processed"]:
            already_processed_count += 1
        else:
            processed_count += 1

        results.append({
            "event": get_event_record(stored["id"]),
            "already_existed": not stored["created"],
            "capture": processing["capture"],
            "capture_already_processed": processing[
                "already_processed"
            ]
        })

    return {
        "count": len(results),
        "created_count": created_count,
        "existing_count": len(results) - created_count,
        "processed_count": processed_count,
        "already_processed_count": already_processed_count,
        "results": results
    }

@router.post("/api/message")
async def receive_message(message: Message):
    event = create_event_record(
        message.text,
        source="chat"
    )

    event_id = event["id"]
    created_at = datetime.fromisoformat(
        event["created_at"]
    )

    capture = await process_capture_action(
        message.text,
        event_id,
        created_at
    )

    mark_event_capture_processed(
        event_id,
        capture
    )

    llm_response, debug = await ask_llm(
        message.text,
        event_id
    )

    debug["capture"] = capture

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE events
            SET response = %s
            WHERE id = %s
            """,
            (
                llm_response,
                event_id
            )
        )

        connection.commit()

    return {
        "event_id": event_id,
        "received": message.text,
        "created_at": created_at.isoformat(),
        "response": llm_response,
        "capture": capture,
        "debug": debug
    }

@router.get("/api/events/by-client-id/{client_event_id}")
async def get_event_by_client_id(client_event_id: str):
    event = get_event_record_by_client_id(
        client_event_id
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return event

@router.post("/api/events/{event_id}/capture")
async def capture_existing_event(event_id: int):
    processing = await process_stored_event_capture(
        event_id
    )

    if processing is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return {
        "event": get_event_record(event_id),
        "capture": processing["capture"],
        "capture_already_processed": processing[
            "already_processed"
        ]
    }

@router.get("/api/events/{event_id}/knowledge")
async def api_get_event_knowledge(event_id: int):
    items = get_event_knowledge(event_id)

    if items is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return {
        "event_id": event_id,
        "count": len(items),
        "knowledge": items
    }

@router.get("/api/events/{event_id}")
async def get_event(event_id: int):
    event = get_event_record(event_id)

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return event

@router.post("/api/events/{event_id}/archive")
async def archive_event(event_id: int):
    event = set_event_archived(
        event_id,
        True
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return event

@router.post("/api/events/{event_id}/unarchive")
async def unarchive_event(event_id: int):
    event = set_event_archived(
        event_id,
        False
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return event

@router.get("/api/events")
async def get_events():
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                text,
                created_at,
                response,
                archived,
                archived_at,
                source,
                client_event_id,
                capture_processed_at
            FROM events
            ORDER BY id DESC
            """
        ).fetchall()

    events = []

    for row in rows:
        events.append({
            "id": row[0],
            "text": row[1],
            "created_at": row[2].isoformat(),
            "response": row[3],
            "archived": row[4],
            "archived_at": row[5].isoformat() if row[5] is not None else None,
            "source": row[6],
            "client_event_id": row[7],
            "capture_processed_at": (
                row[8].isoformat()
                if row[8] is not None
                else None
            )
        })

    return events
