# Event service
import json
from datetime import datetime

from ..config import TIMEZONE
from ..database import get_db_connection
from ..utils import normalize_event_time

def create_event_record(
    text: str,
    created_at: datetime | None = None,
    source: str = "api",
    client_event_id: str | None = None
):
    event_time = normalize_event_time(created_at)
    source = (source or "api").strip() or "api"

    if client_event_id is not None:
        client_event_id = client_event_id.strip() or None

    with get_db_connection() as connection:
        if client_event_id is None:
            row = connection.execute(
                """
                INSERT INTO events (
                    text,
                    created_at,
                    source
                )
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    text,
                    event_time,
                    source
                )
            ).fetchone()
            created = True
        else:
            row = connection.execute(
                """
                INSERT INTO events (
                    text,
                    created_at,
                    source,
                    client_event_id
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (client_event_id)
                DO NOTHING
                RETURNING id
                """,
                (
                    text,
                    event_time,
                    source,
                    client_event_id
                )
            ).fetchone()

            created = row is not None

            if row is None:
                row = connection.execute(
                    """
                    SELECT id
                    FROM events
                    WHERE client_event_id = %s
                    """,
                    (client_event_id,)
                ).fetchone()

        connection.commit()

    event = get_event_record(row[0])
    event["created"] = created
    return event

def get_event_record(event_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
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
                capture_processed_at,
                capture_result
            FROM events
            WHERE id = %s
            """,
            (event_id,)
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "text": row[1],
        "created_at": row[2].isoformat(),
        "response": row[3],
        "archived": row[4],
        "archived_at": (
            row[5].isoformat()
            if row[5] is not None
            else None
        ),
        "source": row[6],
        "client_event_id": row[7],
        "capture_processed_at": (
            row[8].isoformat()
            if row[8] is not None
            else None
        ),
        "capture_result": row[9]
    }

def get_event_record_by_client_id(client_event_id: str):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT id
            FROM events
            WHERE client_event_id = %s
            """,
            (client_event_id,)
        ).fetchone()

    if row is None:
        return None

    return get_event_record(row[0])

def mark_event_capture_processed(
    event_id: int,
    capture_result: dict
):
    processed_at = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE events
            SET capture_processed_at = %s,
                capture_result = %s::jsonb
            WHERE id = %s
            """,
            (
                processed_at,
                json.dumps(capture_result),
                event_id
            )
        )
        connection.commit()

async def process_stored_event_capture(event_id: int):
    from .capture import process_capture_action
    event = get_event_record(event_id)

    if event is None:
        return None

    if event["capture_processed_at"] is not None:
        return {
            "event_id": event_id,
            "already_processed": True,
            "capture_processed_at": event["capture_processed_at"],
            "capture": event["capture_result"]
        }

    event_time = datetime.fromisoformat(
        event["created_at"]
    )

    capture = await process_capture_action(
        event["text"],
        event_id,
        event_time
    )

    mark_event_capture_processed(
        event_id,
        capture
    )

    updated = get_event_record(event_id)

    return {
        "event_id": event_id,
        "already_processed": False,
        "capture_processed_at": updated["capture_processed_at"],
        "capture": capture
    }

def set_event_archived(event_id: int, archived: bool):
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            UPDATE events
            SET archived = %s,
                archived_at = CASE
                    WHEN %s = TRUE THEN %s
                    ELSE NULL
                END
            WHERE id = %s
            RETURNING id
            """,
            (
                archived,
                archived,
                now,
                event_id
            )
        ).fetchone()

        connection.commit()

    if row is None:
        return None

    return get_event_record(event_id)
