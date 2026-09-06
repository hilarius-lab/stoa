# Ingestion service
from datetime import datetime
import hashlib

from ..config import TIMEZONE
from ..database import get_db_connection
from ..utils import normalize_event_time

INGESTION_SESSION_STATUSES = {
    "open", "finished", "processing", "completed", "failed"
}

class IngestionChunkConflictError(Exception):
    pass

def _normalize_optional_text(value: str | None):
    if value is None:
        return None

    value = value.strip()
    return value or None

def create_ingestion_session_record(
    source_type: str,
    title: str | None = None,
    source: str | None = None,
    started_at: datetime | None = None
):
    source_type = source_type.strip()

    if not source_type:
        raise ValueError(
            "source_type must not be empty"
        )

    title = _normalize_optional_text(title)
    source = _normalize_optional_text(source)

    session_started_at = normalize_event_time(
        started_at
    )
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO ingestion_sessions (
                title,
                source_type,
                source,
                status,
                started_at,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                'open',
                %s,
                %s,
                %s
            )
            RETURNING id
            """,
            (
                title,
                source_type,
                source,
                session_started_at,
                now,
                now
            )
        ).fetchone()

        connection.commit()

    return get_ingestion_session_record(
        row[0]
    )

def get_ingestion_session_record(
    session_id: int
):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                title,
                source_type,
                source,
                status,
                started_at,
                ended_at,
                created_at,
                updated_at
            FROM ingestion_sessions
            WHERE id = %s
            """,
            (session_id,)
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "title": row[1],
        "source_type": row[2],
        "source": row[3],
        "status": row[4],
        "started_at": row[5].isoformat(),
        "ended_at": (
            row[6].isoformat()
            if row[6] is not None
            else None
        ),
        "created_at": row[7].isoformat(),
        "updated_at": row[8].isoformat()
    }

def list_ingestion_session_records():
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                source_type,
                source,
                status,
                started_at,
                ended_at,
                created_at,
                updated_at
            FROM ingestion_sessions
            ORDER BY started_at DESC, id DESC
            """
        ).fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "source_type": row[2],
            "source": row[3],
            "status": row[4],
            "started_at": row[5].isoformat(),
            "ended_at": (
                row[6].isoformat()
                if row[6] is not None
                else None
            ),
            "created_at": row[7].isoformat(),
            "updated_at": row[8].isoformat()
        }
        for row in rows
    ]

def finish_ingestion_session_record(
    session_id: int
):
    current = get_ingestion_session_record(
        session_id
    )

    if current is None:
        return None

    if current["status"] == "finished":
        return current

    if current["status"] != "open":
        raise ValueError(
            "Only an open ingestion session can be finished"
        )

    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE ingestion_sessions
            SET status = 'finished',
                ended_at = %s,
                updated_at = %s
            WHERE id = %s
              AND status = 'open'
            """,
            (
                now,
                now,
                session_id
            )
        )

        connection.commit()

    return get_ingestion_session_record(
        session_id
    )

def _ingestion_chunk_from_row(row):
    if row is None:
        return None

    return {
        "id": row[0],
        "session_id": row[1],
        "sequence": row[2],
        "client_chunk_id": row[3],
        "text": row[4],
        "source_start_ms": row[5],
        "source_end_ms": row[6],
        "content_hash": row[7],
        "created_at": row[8].isoformat()
    }

def _select_ingestion_chunk(connection, clause, parameters):
    return connection.execute(
        f"""
        SELECT
            id,
            session_id,
            sequence,
            client_chunk_id,
            text,
            source_start_ms,
            source_end_ms,
            content_hash,
            created_at
        FROM ingestion_chunks
        WHERE {clause}
        """,
        parameters
    ).fetchone()

def create_ingestion_chunk_record(
    session_id: int,
    sequence: int,
    client_chunk_id: str,
    text: str,
    source_start_ms: int | None = None,
    source_end_ms: int | None = None
):
    client_chunk_id = client_chunk_id.strip()

    if not client_chunk_id:
        raise ValueError("client_chunk_id must not be empty")

    if not text.strip():
        raise ValueError("text must not be empty")

    if sequence < 1:
        raise ValueError("sequence must be greater than or equal to 1")

    if source_start_ms is not None and source_start_ms < 0:
        raise ValueError("source_start_ms must not be negative")

    if source_end_ms is not None and source_end_ms < 0:
        raise ValueError("source_end_ms must not be negative")

    if (
        source_start_ms is not None
        and source_end_ms is not None
        and source_end_ms < source_start_ms
    ):
        raise ValueError(
            "source_end_ms must be greater than or equal to source_start_ms"
        )

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        session = connection.execute(
            """
            SELECT id
            FROM ingestion_sessions
            WHERE id = %s
            FOR UPDATE
            """,
            (session_id,)
        ).fetchone()

        if session is None:
            return None

        existing_client = _select_ingestion_chunk(
            connection,
            "session_id = %s AND client_chunk_id = %s",
            (session_id, client_chunk_id)
        )

        if existing_client is not None:
            existing = _ingestion_chunk_from_row(existing_client)
            if (
                existing["sequence"] == sequence
                and existing["text"] == text
                and existing["source_start_ms"] == source_start_ms
                and existing["source_end_ms"] == source_end_ms
                and existing["content_hash"] == content_hash
            ):
                return existing

            raise IngestionChunkConflictError(
                "client_chunk_id already exists with different chunk data"
            )

        existing_sequence = _select_ingestion_chunk(
            connection,
            "session_id = %s AND sequence = %s",
            (session_id, sequence)
        )

        if existing_sequence is not None:
            raise IngestionChunkConflictError(
                "sequence already exists for this ingestion session"
            )

        row = connection.execute(
            """
            INSERT INTO ingestion_chunks (
                session_id,
                sequence,
                client_chunk_id,
                text,
                source_start_ms,
                source_end_ms,
                content_hash,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id,
                session_id,
                sequence,
                client_chunk_id,
                text,
                source_start_ms,
                source_end_ms,
                content_hash,
                created_at
            """,
            (
                session_id,
                sequence,
                client_chunk_id,
                text,
                source_start_ms,
                source_end_ms,
                content_hash,
                now
            )
        ).fetchone()

        connection.commit()

    return _ingestion_chunk_from_row(row)

def list_ingestion_chunk_records(session_id: int):
    with get_db_connection() as connection:
        session = connection.execute(
            "SELECT id FROM ingestion_sessions WHERE id = %s",
            (session_id,)
        ).fetchone()

        if session is None:
            return None

        rows = connection.execute(
            """
            SELECT
                id,
                session_id,
                sequence,
                client_chunk_id,
                text,
                source_start_ms,
                source_end_ms,
                content_hash,
                created_at
            FROM ingestion_chunks
            WHERE session_id = %s
            ORDER BY sequence ASC, id ASC
            """,
            (session_id,)
        ).fetchall()

    return [_ingestion_chunk_from_row(row) for row in rows]

def get_ingestion_chunk_record(chunk_id: int):
    with get_db_connection() as connection:
        row = _select_ingestion_chunk(
            connection,
            "id = %s",
            (chunk_id,)
        )

    return _ingestion_chunk_from_row(row)
