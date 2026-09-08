# Task service
from datetime import datetime

from ..config import TIMEZONE, EMBEDDING_MODEL
from ..database import get_db_connection
from .embeddings import get_embedding, get_query_embedding, embedding_to_pgvector
from .provenance import add_knowledge_source

def _task_time(value: datetime | None):
    if value is None:
        return None
    return value.replace(tzinfo=TIMEZONE) if value.tzinfo is None else value.astimezone(TIMEZONE)


def _task_window(due_at: datetime | None, work_start_at: datetime | None, reference: datetime):
    due_at = _task_time(due_at)
    work_start_at = _task_time(work_start_at)
    if due_at is not None and work_start_at is None:
        reference_day = _task_time(reference).replace(hour=0, minute=0, second=0, microsecond=0)
        # Imported or delayed tasks may already be overdue. Their implicit
        # window starts no later than the deadline instead of becoming invalid.
        work_start_at = min(reference_day, due_at)
    if due_at is not None and work_start_at is not None and work_start_at > due_at:
        raise ValueError("work_start_at must not be after due_at")
    return due_at, work_start_at


def save_task(
    content: str,
    due_at: datetime | None,
    embedding: list[float],
    source_event_id: int | None = None,
    priority: int = 0,
    urgency: float | None = None,
    urgency_source: str | None = None,
    percent_complete: int = 0,
    work_start_at: datetime | None = None,
    work_start_reference: datetime | None = None,
):
    now = datetime.now(TIMEZONE)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        reference = work_start_reference
        if reference is None and source_event_id is not None:
            event = connection.execute("SELECT created_at FROM events WHERE id=%s", (source_event_id,)).fetchone()
            if event:
                reference = event[0]
        due_at, work_start_at = _task_window(due_at, work_start_at, reference or now)
        task_id = connection.execute(
            """
            INSERT INTO tasks (
                content,
                created_at,
                updated_at,
                due_at,
                work_start_at,
                status,
                source_event_id,
                embedding,
                embedding_model,
                priority,
                urgency,
                percent_complete,
                urgency_source
            )
            VALUES (%s, %s, %s, %s, %s, 'open', %s, %s::vector, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                content,
                now,
                now,
                due_at,
                work_start_at,
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

async def update_task(task_id: int, content: str, due_at: datetime | None, priority: int | None = None, urgency: float | None = None, percent_complete: int | None = None, work_start_at: datetime | None = None):
    now = datetime.now(TIMEZONE)
    due_at, work_start_at = _task_window(due_at, work_start_at, now)

    embedding = await get_embedding(content)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET content = %s,
                due_at = %s,
                work_start_at = %s,
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
                work_start_at,
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
                work_start_at,
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
        "work_start_at": row[5].isoformat() if row[5] else None,
        "status": row[6],
        "source_event_id": row[7],
        "archived": row[8],
        "embedding_model": row[9],
        "embedding_dimensions": row[10],
        "priority": row[11], "urgency": row[12], "percent_complete": row[13], "urgency_source": row[14]
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
                work_start_at,
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
        "work_start_at": row[3].isoformat() if row[3] else None,
        "status": row[4],
        "archived": row[5],
        "updated_at": row[6].isoformat(), "priority":row[7],"urgency":row[8],"percent_complete":row[9]
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
                work_start_at,
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
            "work_start_at": row[5].isoformat() if row[5] else None,
            "status": row[6],
            "source_event_id": row[7],
            "embedding_model": row[8],
            "similarity": float(row[9]), "priority":row[10],"urgency":row[11],"percent_complete":row[12]
        }
        for row in rows
    ]
