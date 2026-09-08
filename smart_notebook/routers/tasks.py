# Task routes
from datetime import datetime
from fastapi import APIRouter, HTTPException

from ..config import TIMEZONE

from ..database import get_db_connection
from ..schemas import TaskCreate, TaskUpdate, NoteSearch
from ..services.embeddings import get_embedding
from ..services.tasks import (
    get_task_record, update_task, set_task_status, search_tasks, save_task,
    expire_overdue_tasks, archive_closed_tasks
)

router = APIRouter()

@router.post("/api/tasks/{task_id}/done")
async def mark_task_done(task_id: int):
    result = set_task_status(task_id, "done")

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    return result

@router.post("/api/tasks/{task_id}/archive")
async def archive_task(task_id: int):
    result = set_task_status(task_id, "archived")

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    return result

@router.post("/api/tasks/expire-overdue")
async def api_expire_overdue_tasks():
    tasks = expire_overdue_tasks()

    return {
        "count": len(tasks),
        "tasks": tasks
    }

@router.post("/api/tasks/archive-closed")
async def api_archive_closed_tasks():
    tasks = archive_closed_tasks()

    return {
        "count": len(tasks),
        "tasks": tasks
    }

@router.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    task = get_task_record(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    return task

@router.patch("/api/tasks/{task_id}")
async def patch_task(
    task_id: int,
    task: TaskUpdate
):
    existing = get_task_record(task_id)

    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    if (task.content is None and task.work_start_at is None and not task.clear_work_start_at
            and task.due_at is None and not task.clear_due_at and task.priority is None
            and task.urgency is None and task.percent_complete is None):
        raise HTTPException(
            status_code=400,
            detail="Provide content and/or due_at"
        )

    content = (
        task.content
        if task.content is not None
        else existing["content"]
    )

    due_at = None if task.clear_due_at else (
        task.due_at if task.due_at is not None
        else (datetime.fromisoformat(existing["due_at"]) if existing["due_at"] else None)
    )

    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=TIMEZONE)

    work_start_at = None if task.clear_work_start_at else (
        task.work_start_at if task.work_start_at is not None
        else (datetime.fromisoformat(existing["work_start_at"]) if existing["work_start_at"] else None)
    )
    if work_start_at is not None and work_start_at.tzinfo is None:
        work_start_at = work_start_at.replace(tzinfo=TIMEZONE)

    try:
        await update_task(
            task_id,
            content,
            due_at,
            task.priority,
            task.urgency,
            task.percent_complete,
            work_start_at
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return get_task_record(task_id)

@router.post("/api/tasks/{task_id}/reopen")
async def reopen_task(task_id: int):
    result = set_task_status(task_id, "open")

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    return get_task_record(task_id)

@router.post("/api/search-tasks")
async def api_search_tasks(search: NoteSearch):
    results = await search_tasks(
        search.query,
        search.limit
    )

    return {
        "query": search.query,
        "count": len(results),
        "results": results
    }

@router.post("/api/tasks")
async def create_task(task: TaskCreate):
    now = datetime.now(TIMEZONE)

    due_at = task.due_at

    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=TIMEZONE)

    embedding = await get_embedding(task.content)

    try:
        task_id = save_task(
            task.content,
            due_at,
            embedding,
            source_event_id=task.source_event_id,
            priority=task.priority,
            urgency=task.urgency,
            percent_complete=task.percent_complete,
            work_start_at=task.work_start_at,
            work_start_reference=now,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return get_task_record(task_id)

@router.get("/api/tasks")
async def get_tasks(
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
                due_at,
                work_start_at,
                status,
                source_event_id,
                archived,
                embedding_model,
                CASE WHEN embedding IS NULL THEN NULL ELSE vector_dims(embedding) END
                ,priority,urgency,percent_complete
            FROM tasks
            WHERE (%s = TRUE OR archived = FALSE)
            ORDER BY due_at ASC
            """,
            (include_archived,)
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
            "archived": row[8],
            "embedding_model": row[9],
            "embedding_dimensions": row[10],
            "priority":row[11],"urgency":row[12],"percent_complete":row[13]
        }
        for row in rows
    ]
