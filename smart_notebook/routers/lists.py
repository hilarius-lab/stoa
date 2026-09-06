# List routes
from datetime import datetime
from fastapi import APIRouter, HTTPException

from ..config import TIMEZONE
from ..database import get_db_connection
from ..schemas import ListCreate, ListUpdate, ListItemCreate, ListItemUpdate, NoteSearch
from ..services.lists import (
    create_list_record, get_list_record, refresh_list_embedding, set_list_archived,
    add_list_item_record, decide_list_item_deduplication, get_list_item_record,
    update_list_item_record, set_list_item_status, search_list_items_global, search_lists
)

router = APIRouter()

@router.post("/api/lists")
async def create_list(payload: ListCreate):
    title = payload.title.strip()

    if not title:
        raise HTTPException(status_code=400, detail="List title must not be empty")

    list_id = await create_list_record(
        title,
        payload.description
    )

    return get_list_record(list_id)

@router.get("/api/lists")
async def get_lists(include_archived: bool = False):
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM lists
            WHERE (%s = TRUE OR archived = FALSE)
            ORDER BY updated_at DESC
            """,
            (include_archived,)
        ).fetchall()

    return [get_list_record(row[0]) for row in rows]

@router.get("/api/lists/{list_id}")
async def get_list(list_id: int):
    result = get_list_record(list_id)

    if result is None:
        raise HTTPException(status_code=404, detail="List not found")

    return result

@router.patch("/api/lists/{list_id}")
async def patch_list(
    list_id: int,
    payload: ListUpdate
):
    existing = get_list_record(list_id)

    if existing is None:
        raise HTTPException(status_code=404, detail="List not found")

    title = (
        payload.title.strip()
        if payload.title is not None
        else existing["title"]
    )
    description = (
        payload.description.strip()
        if payload.description is not None
        else existing["description"]
    )

    if not title:
        raise HTTPException(status_code=400, detail="List title must not be empty")

    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE lists
            SET title = %s,
                description = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                title,
                description,
                now,
                list_id
            )
        )
        connection.commit()

    await refresh_list_embedding(list_id)
    return get_list_record(list_id)

@router.post("/api/lists/{list_id}/archive")
async def archive_list(list_id: int):
    result = await set_list_archived(list_id, True)

    if result is None:
        raise HTTPException(status_code=404, detail="List not found")

    return result

@router.post("/api/lists/{list_id}/unarchive")
async def unarchive_list(list_id: int):
    result = await set_list_archived(list_id, False)

    if result is None:
        raise HTTPException(status_code=404, detail="List not found")

    return result

@router.post("/api/lists/{list_id}/items")
async def create_list_item(
    list_id: int,
    payload: ListItemCreate
):
    existing = get_list_record(list_id)

    if existing is None or existing["archived"]:
        raise HTTPException(status_code=404, detail="Active list not found")

    decision = await decide_list_item_deduplication(
        list_id,
        payload.content
    )

    if decision["action"] == "skip":
        return {
            "deduplication": "skip",
            "list_id": list_id,
            "item_id": None,
            "target_id": decision["target_id"]
        }

    if decision["action"] == "update_existing":
        final_content = decision["content"].strip() or payload.content
        await update_list_item_record(
            decision["target_id"],
            final_content
        )
        return {
            "deduplication": "update_existing",
            "list_id": list_id,
            "item": get_list_item_record(decision["target_id"])
        }

    final_content = decision["content"].strip() or payload.content
    item_id = await add_list_item_record(
        list_id,
        final_content,
        source_event_id=payload.source_event_id
    )

    return {
        "deduplication": "save_new",
        "list_id": list_id,
        "item": get_list_item_record(item_id)
    }

@router.get("/api/lists/{list_id}/items")
async def get_list_items(
    list_id: int,
    include_archived: bool = False
):
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM list_items
            WHERE list_id = %s
              AND (%s = TRUE OR archived = FALSE)
            ORDER BY created_at ASC, id ASC
            """,
            (
                list_id,
                include_archived
            )
        ).fetchall()

    return [get_list_item_record(row[0]) for row in rows]

@router.get("/api/list-items/{item_id}")
async def get_list_item(item_id: int):
    result = get_list_item_record(item_id)

    if result is None:
        raise HTTPException(status_code=404, detail="List item not found")

    return result

@router.patch("/api/list-items/{item_id}")
async def patch_list_item(
    item_id: int,
    payload: ListItemUpdate
):
    list_id = await update_list_item_record(
        item_id,
        payload.content
    )

    if list_id is None:
        raise HTTPException(status_code=404, detail="List item not found")

    return get_list_item_record(item_id)

@router.post("/api/list-items/{item_id}/done")
async def mark_list_item_done(item_id: int):
    result = await set_list_item_status(item_id, "done")

    if result is None:
        raise HTTPException(status_code=404, detail="List item not found")

    return result

@router.post("/api/list-items/{item_id}/reopen")
async def reopen_list_item(item_id: int):
    result = await set_list_item_status(item_id, "active")

    if result is None:
        raise HTTPException(status_code=404, detail="List item not found")

    return result

@router.post("/api/list-items/{item_id}/archive")
async def archive_list_item(item_id: int):
    result = await set_list_item_status(item_id, "archived")

    if result is None:
        raise HTTPException(status_code=404, detail="List item not found")

    return result

@router.post("/api/search-list-items")
async def api_search_list_items(search: NoteSearch):
    results = await search_list_items_global(
        search.query,
        search.limit
    )

    return {
        "query": search.query,
        "count": len(results),
        "results": results
    }

@router.post("/api/search-lists")
async def api_search_lists(search: NoteSearch):
    results = await search_lists(
        search.query,
        search.limit
    )

    return {
        "query": search.query,
        "count": len(results),
        "results": results
    }
