# Task service
from datetime import datetime

from ..config import TIMEZONE, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS, TASK_RETRIEVAL_LIMIT, TASK_RETRIEVAL_MIN_SIMILARITY
from ..database import get_db_connection
from .embeddings import get_embedding, get_query_embedding, embedding_to_pgvector
from .provenance import add_knowledge_source

def save_task(
    content: str,
    due_at: datetime | None,
    embedding: list[float],
    source_event_id: int | None = None,
    priority: int = 0,
    urgency: float | None = None,
    urgency_source: str | None = None,
    percent_complete: int = 0
):
    now = datetime.now(TIMEZONE)
    vector_value = embedding_to_pgvector(embedding)

    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=TIMEZONE)

    with get_db_connection() as connection:
        task_id = connection.execute(
            """
            INSERT INTO tasks (
                content,
                created_at,
                updated_at,
                due_at,
                status,
                source_event_id,
                embedding,
                embedding_model,
                priority,
                urgency,
                percent_complete,
                urgency_source
            )
            VALUES (%s, %s, %s, %s, 'open', %s, %s::vector, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                content,
                now,
                now,
                due_at,
                source_event_id,
                vector_value,
                EMBEDDING_MODEL
                ,priority, urgency, percent_complete, urgency_source
            )
        ).fetchone()[0]

        connection.commit()

    add_knowledge_source(
        "task",
        task_id,
        source_event_id,
        "source"
    )

    return task_id

async def update_task(task_id: int, content: str, due_at: datetime | None, priority: int | None = None, urgency: float | None = None, percent_complete: int | None = None):
    now = datetime.now(TIMEZONE)

    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=TIMEZONE)

    embedding = await get_embedding(content)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET content = %s,
                due_at = %s,
                updated_at = %s,
                embedding = %s::vector,
                embedding_model = %s
                ,priority = COALESCE(%s, priority)
                ,urgency = COALESCE(%s, urgency)
                ,percent_complete = COALESCE(%s, percent_complete)
            WHERE id = %s
            """,
            (
                content,
                due_at,
                now,
                vector_value,
                EMBEDDING_MODEL,
                priority,
                urgency,
                percent_complete,
                task_id
            )
        )
        connection.commit()

def get_task_record(task_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                content,
                created_at,
                updated_at,
                due_at,
                status,
                source_event_id,
                archived,
                embedding_model,
                CASE
                    WHEN embedding IS NULL THEN NULL
                    ELSE vector_dims(embedding)
                END
                ,priority,urgency,percent_complete,urgency_source
            FROM tasks
            WHERE id = %s
            """,
            (task_id,)
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "content": row[1],
        "created_at": row[2].isoformat(),
        "updated_at": row[3].isoformat(),
        "due_at": row[4].isoformat() if row[4] else None,
        "status": row[5],
        "source_event_id": row[6],
        "archived": row[7],
        "embedding_model": row[8],
        "embedding_dimensions": row[9],
        "priority": row[10], "urgency": row[11], "percent_complete": row[12], "urgency_source": row[13]
    }

def set_task_status(task_id: int, status: str):
    if status not in {"open", "done", "expired", "archived"}:
        raise ValueError(f"Unsupported task status: {status}")

    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            UPDATE tasks
            SET status = %s,
                percent_complete = CASE
                    WHEN %s = 'done' THEN 100
                    WHEN %s = 'open' AND percent_complete = 100 THEN 0
                    ELSE percent_complete
                END,
                archived = CASE
                    WHEN %s = 'archived' THEN TRUE
                    WHEN %s = 'open' THEN FALSE
                    ELSE archived
                END,
                updated_at = %s
            WHERE id = %s
            RETURNING
                id,
                content,
                due_at,
                status,
                archived,
                updated_at
                ,priority,urgency,percent_complete
            """,
            (
                status,
                status,
                status,
                status,
                status,
                now,
                task_id
            )
        ).fetchone()

        connection.commit()

    if row is None:
        return None

    return {
        "id": row[0],
        "content": row[1],
        "due_at": row[2].isoformat() if row[2] else None,
        "status": row[3],
        "archived": row[4],
        "updated_at": row[5].isoformat(), "priority":row[6],"urgency":row[7],"percent_complete":row[8]
    }

def expire_overdue_tasks():
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            UPDATE tasks
            SET status = 'expired',
                updated_at = %s
            WHERE status = 'open'
              AND archived = FALSE
              AND due_at < %s
            RETURNING
                id,
                content,
                due_at,
                status,
                archived,
                updated_at
            """,
            (
                now,
                now
            )
        ).fetchall()

        connection.commit()

    return [
        {
            "id": row[0],
            "content": row[1],
            "due_at": row[2].isoformat() if row[2] else None,
            "status": row[3],
            "archived": row[4],
            "updated_at": row[5].isoformat()
        }
        for row in rows
    ]

def archive_closed_tasks():
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            UPDATE tasks
            SET status = 'archived',
                archived = TRUE,
                updated_at = %s
            WHERE archived = FALSE
              AND status IN ('done', 'expired')
            RETURNING
                id,
                content,
                due_at,
                status,
                archived,
                updated_at
            """,
            (now,)
        ).fetchall()

        connection.commit()

    return [
        {
            "id": row[0],
            "content": row[1],
            "due_at": row[2].isoformat() if row[2] else None,
            "status": row[3],
            "archived": row[4],
            "updated_at": row[5].isoformat()
        }
        for row in rows
    ]

async def search_tasks(query: str, limit: int = 5):
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
                due_at,
                status,
                source_event_id,
                embedding_model,
                1 - (embedding <=> %s::vector) AS similarity
                ,priority,urgency,percent_complete
            FROM tasks
            WHERE archived = FALSE
              AND status = 'open'
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
            "due_at": row[4].isoformat() if row[4] else None,
            "status": row[5],
            "source_event_id": row[6],
            "embedding_model": row[7],
            "similarity": float(row[8]), "priority":row[9],"urgency":row[10],"percent_complete":row[11]
        }
        for row in rows
    ]
