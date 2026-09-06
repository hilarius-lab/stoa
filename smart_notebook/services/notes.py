# Note service
from datetime import datetime

from ..config import TIMEZONE, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, NOTE_RETRIEVAL_LIMIT, NOTE_RETRIEVAL_MIN_SIMILARITY
from ..database import get_db_connection
from .embeddings import get_embedding, get_query_embedding, embedding_to_pgvector
from .provenance import add_knowledge_source

def save_note(
    content: str,
    embedding: list[float],
    source_event_id: int | None = None
):
    now = datetime.now(TIMEZONE)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        note_id = connection.execute(
            """
            INSERT INTO notes (
                content,
                created_at,
                updated_at,
                source_event_id,
                embedding,
                embedding_model
            )
            VALUES (%s, %s, %s, %s, %s::vector, %s)
            RETURNING id
            """,
            (
                content,
                now,
                now,
                source_event_id,
                vector_value,
                EMBEDDING_MODEL
            )
        ).fetchone()[0]

        connection.commit()

    add_knowledge_source(
        "note",
        note_id,
        source_event_id,
        "source"
    )

    return note_id

async def update_note(note_id: int, content: str):
    now = datetime.now(TIMEZONE)
    embedding = await get_embedding(content)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE notes
            SET content = %s,
                updated_at = %s,
                embedding = %s::vector,
                embedding_model = %s
            WHERE id = %s
            """,
            (
                content,
                now,
                vector_value,
                EMBEDDING_MODEL,
                note_id
            )
        )
        connection.commit()

def get_note_record(note_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                content,
                created_at,
                updated_at,
                source_event_id,
                archived,
                embedding_model,
                CASE
                    WHEN embedding IS NULL THEN NULL
                    ELSE vector_dims(embedding)
                END
            FROM notes
            WHERE id = %s
            """,
            (note_id,)
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "content": row[1],
        "created_at": row[2].isoformat(),
        "updated_at": row[3].isoformat(),
        "source_event_id": row[4],
        "archived": row[5],
        "embedding_model": row[6],
        "embedding_dimensions": row[7]
    }

def set_note_archived(note_id: int, archived: bool):
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            UPDATE notes
            SET archived = %s,
                updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                archived,
                now,
                note_id
            )
        ).fetchone()

        connection.commit()

    if row is None:
        return None

    return get_note_record(note_id)

async def search_notes(query: str, limit: int = 5):
    limit = max(1, min(limit, 20))

    embedding = await get_query_embedding(query)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                content,
                created_at,
                updated_at,
                source_event_id,
                embedding_model,
                1 - (embedding <=> %s::vector) AS similarity
            FROM notes
            WHERE archived = FALSE
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_value,
                vector_value,
                limit
            )
        ).fetchall()

    return [
        {
            "id": row[0],
            "content": row[1],
            "created_at": row[2].isoformat(),
            "updated_at": row[3].isoformat(),
            "source_event_id": row[4],
            "embedding_model": row[5],
            "similarity": float(row[6])
        }
        for row in rows
    ]
