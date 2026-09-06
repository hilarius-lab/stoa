# Capture service
import httpx
import json
from datetime import datetime

from ..config import TIMEZONE
from ..database import get_db_connection
from ..prompts import CAPTURE_SYSTEM_PROMPT
from .embeddings import get_embedding
from .provenance import add_knowledge_source
from .lists import process_list_item_candidate
from .notes import save_note, update_note
from .tasks import save_task, update_task
from .dedupe import decide_note_deduplication, decide_task_deduplication
from .ai_tasks import get_ai_task_profile

def _optional_due_at(value):
    if not value or not value.strip(): return None
    due_at=datetime.fromisoformat(value.replace("Z","+00:00"))
    return due_at.replace(tzinfo=TIMEZONE) if due_at.tzinfo is None else due_at

async def classify_capture(text: str, event_time: datetime):
    profile = get_ai_task_profile("capture.classify")
    with get_db_connection() as connection:
        active_lists = connection.execute(
            """
            SELECT title
            FROM lists
            WHERE archived = FALSE
            ORDER BY updated_at DESC
            LIMIT 20
            """
        ).fetchall()

    active_list_context = ", ".join(row[0] for row in active_lists) or "keine"

    runtime_context = (
        f"Event-Zeitpunkt: {event_time.isoformat()}\n"
        "Zeitzone: Europe/Berlin\n"
        f"Bereits vorhandene aktive Listen: {active_list_context}\n"
        "Interpretieren Sie relative Zeitangaben ausschließlich relativ zu diesem "
        "Event-Zeitpunkt."
    )

    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "none",
                    "save_note",
                    "save_task",
                    "save_list_item"
                ]
            },
            "content": {
                "type": "string"
            },
            "due_at": {
                "type": "string"
            },
            "list_title": {
                "type": "string"
            }
        },
        "required": [
            "action",
            "content",
            "due_at",
            "list_title"
        ],
        "additionalProperties": False
    }

    payload = {
        "model": profile["model"],
        "messages": [
            {
                "role": "system",
                "content": CAPTURE_SYSTEM_PROMPT + "\n\n" + runtime_context
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": profile["temperature"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_notebook_capture",
                "strict": True,
                "schema": schema
            }
        }
    }

    async with httpx.AsyncClient(timeout=profile["timeout_seconds"]) as client:
        response = await client.post(
            profile["endpoint"],
            json=payload
        )
        response.raise_for_status()

    data = response.json()
    raw_content = data["choices"][0]["message"]["content"]

    result = json.loads(raw_content)

    return result

async def process_capture_action(
    text: str,
    event_id: int,
    event_time: datetime
):
    result = await classify_capture(
        text,
        event_time
    )

    action = result["action"]
    content = result["content"].strip()
    due_at_raw = result["due_at"].strip()
    list_title = result["list_title"].strip()

    saved = {
        "action": action,
        "content": content,
        "due_at": due_at_raw or None,
        "list_title": list_title or None,
        "deduplication": None,
        "deduplication_target_id": None,
        "note_id": None,
        "task_id": None,
        "updated_note_id": None,
        "updated_task_id": None,
        "list_id": None,
        "list_created": False,
        "list_item_id": None,
        "updated_list_item_id": None
    }

    if action == "save_note":
        if not content:
            saved["action"] = "none"
            return saved

        decision = await decide_note_deduplication(content)

        saved["deduplication"] = decision["action"]
        saved["deduplication_target_id"] = (
            decision["target_id"] or None
        )

        if decision["action"] == "save_new":
            final_content = (
                decision["content"].strip()
                or content
            )

            embedding = await get_embedding(
                final_content
            )

            saved["note_id"] = save_note(
                final_content,
                embedding,
                source_event_id=event_id
            )

            saved["content"] = final_content

        elif decision["action"] == "update_existing":
            final_content = (
                decision["content"].strip()
                or content
            )

            await update_note(
                decision["target_id"],
                final_content
            )

            add_knowledge_source(
                "note",
                decision["target_id"],
                event_id,
                "supporting"
            )

            saved["updated_note_id"] = (
                decision["target_id"]
            )
            saved["content"] = final_content

        else:
            target_id = decision.get("target_id")

            if target_id:
                add_knowledge_source(
                    "note",
                    target_id,
                    event_id,
                    "supporting"
                )

    elif action == "save_task":
        if not content:
            saved["action"] = "none"
            return saved

        try:
            due_at = _optional_due_at(due_at_raw)
        except ValueError:
            saved["action"] = "none"
            saved["deduplication"] = (
                "invalid_due_at"
            )
            return saved

        decision = await decide_task_deduplication(
            content,
            due_at
        )

        saved["deduplication"] = decision["action"]
        saved["deduplication_target_id"] = (
            decision["target_id"] or None
        )

        if decision["action"] == "save_new":
            final_content = (
                decision["content"].strip()
                or content
            )

            final_due_at = _optional_due_at(decision["due_at"])

            embedding = await get_embedding(
                final_content
            )

            saved["task_id"] = save_task(
                final_content,
                final_due_at,
                embedding,
                source_event_id=event_id
            )

            saved["content"] = final_content
            saved["due_at"] = (
                final_due_at.isoformat() if final_due_at else None
            )

        elif decision["action"] == "update_existing":
            final_content = (
                decision["content"].strip()
                or content
            )

            final_due_at = _optional_due_at(decision["due_at"])

            await update_task(
                decision["target_id"],
                final_content,
                final_due_at
            )

            add_knowledge_source(
                "task",
                decision["target_id"],
                event_id,
                "supporting"
            )

            saved["updated_task_id"] = (
                decision["target_id"]
            )
            saved["content"] = final_content
            saved["due_at"] = (
                final_due_at.isoformat() if final_due_at else None
            )

        else:
            target_id = decision.get("target_id")

            if target_id:
                add_knowledge_source(
                    "task",
                    target_id,
                    event_id,
                    "supporting"
                )

    elif action == "save_list_item":
        list_result = await process_list_item_candidate(
            list_title,
            content,
            source_event_id=event_id
        )

        if list_result["action"] == "invalid":
            saved["action"] = "none"
            return saved

        saved["list_id"] = list_result["list_id"]
        saved["list_created"] = list_result["list_created"]
        saved["list_item_id"] = list_result["item_id"]
        saved["updated_list_item_id"] = list_result["updated_item_id"]
        saved["deduplication"] = list_result["deduplication"]
        saved["content"] = list_result["content"]

    return saved
