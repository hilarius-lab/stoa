# Chat service
import httpx
from datetime import datetime, timedelta

from ..config import (
    TIMEZONE, CONTEXT_EVENT_LIMIT, CONTEXT_MAX_AGE_MINUTES,
    KNOWLEDGE_RETRIEVAL_LIMIT, KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY,
    KNOWLEDGE_LIST_CONTEXT_ITEM_LIMIT, CHAT_NOTE_REDUNDANCY_SIMILARITY,
    LLM_APPLY_TEMPLATE_URL
)
from ..database import get_db_connection
from ..prompts import SYSTEM_PROMPT
from .retrieval import search_knowledge
from .ai_tasks import get_ai_task_profile

def get_recent_conversation(before_event_id: int):
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                text,
                response,
                created_at
            FROM events
            WHERE id < %s
              AND response IS NOT NULL
              AND created_at >= NOW() - (%s * INTERVAL '1 minute')
            ORDER BY id DESC
            LIMIT %s
            """,
            (
                before_event_id,
                CONTEXT_MAX_AGE_MINUTES,
                CONTEXT_EVENT_LIMIT
            )
        ).fetchall()

    rows.reverse()

    messages = []

    for text, response, created_at in rows:
        messages.append({
            "role": "user",
            "content": text
        })

        messages.append({
            "role": "assistant",
            "content": response
        })

    return messages

def get_conversation_turn_context(conversation_id, before_sequence: int, limit: int = CONTEXT_EVENT_LIMIT):
    # W03: client_chat.py's conversations each have their own turn history in
    # client_conversation_messages (introduced for A11) -- unlike the single
    # implicit legacy thread get_recent_conversation() was built for, several
    # client_chat conversations exist concurrently, so context must be scoped
    # to this one conversation instead of a global, source-agnostic time
    # window. `before_sequence` excludes the user message that started the
    # current turn (already appended separately by build_messages()).
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT role, content
            FROM client_conversation_messages
            WHERE conversation_id = %s
              AND sequence < %s
            ORDER BY sequence DESC
            LIMIT %s
            """,
            (conversation_id, before_sequence, limit * 2)
        ).fetchall()

    rows.reverse()

    return [
        {"role": role, "content": content}
        for role, content in rows
    ]

def get_note_pair_similarities(note_ids: list[int]):
    unique_ids = sorted(set(note_ids))

    if len(unique_ids) < 2:
        return {}

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                a.id,
                b.id,
                1 - (a.embedding <=> b.embedding) AS similarity
            FROM notes a
            JOIN notes b
              ON a.id < b.id
            WHERE a.id = ANY(%s)
              AND b.id = ANY(%s)
              AND a.embedding IS NOT NULL
              AND b.embedding IS NOT NULL
            """,
            (
                unique_ids,
                unique_ids
            )
        ).fetchall()

    similarities = {}

    for row in rows:
        key = (row[0], row[1])
        similarities[key] = float(row[2])

    return similarities

def suppress_redundant_note_context(
    results: list[dict]
):
    note_results = [
        result
        for result in results
        if result["type"] == "note"
    ]

    if len(note_results) < 2:
        return results, []

    pair_similarities = get_note_pair_similarities(
        [result["id"] for result in note_results]
    )

    # Build connected components only from very-near duplicate notes.
    adjacency = {
        result["id"]: set()
        for result in note_results
    }

    for (left_id, right_id), similarity in pair_similarities.items():
        if similarity >= CHAT_NOTE_REDUNDANCY_SIMILARITY:
            adjacency[left_id].add(right_id)
            adjacency[right_id].add(left_id)

    by_id = {
        result["id"]: result
        for result in note_results
    }

    visited = set()
    keep_note_ids = set()
    suppressed = []

    for note_id in adjacency:
        if note_id in visited:
            continue

        stack = [note_id]
        component = []

        while stack:
            current = stack.pop()

            if current in visited:
                continue

            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)

        if len(component) == 1:
            keep_note_ids.add(component[0])
            continue

        # Prefer the richer note; break ties with relevance to this query.
        representative_id = max(
            component,
            key=lambda current_id: (
                len(by_id[current_id]["content"].split()),
                by_id[current_id]["similarity"]
            )
        )

        keep_note_ids.add(representative_id)

        for current_id in component:
            if current_id == representative_id:
                continue

            suppressed.append({
                "key": by_id[current_id]["key"],
                "type": "note",
                "id": current_id,
                "content": by_id[current_id]["content"],
                "similarity": by_id[current_id]["similarity"],
                "suppressed_by": f"note:{representative_id}"
            })

    filtered = []

    for result in results:
        if result["type"] == "note":
            if result["id"] not in keep_note_ids:
                continue

        filtered.append(result)

    return filtered, suppressed

async def build_messages(text: str, before_event_id: int, conversation_id=None, before_sequence: int | None = None):
    now = datetime.now(TIMEZONE)

    runtime_context = (
        "\n\nLAUFZEITKONTEXT – DIESE INFORMATIONEN SIND AUTORITATIV:\n"
        f"- Aktuelles Datum: {now.strftime('%Y-%m-%d')}\n"
        f"- Aktuelle Uhrzeit: {now.strftime('%H:%M:%S')}\n"
        f"- Zeitzone: Europe/Berlin\n\n"
        "Wenn der Nutzer nach Datum, Uhrzeit oder relativen Zeitangaben fragt, "
        "verwende diese Werte direkt. Behaupte in diesem Fall nicht, dass du "
        "keinen Zugriff auf die aktuelle Uhrzeit oder Echtzeitdaten hast."
    )

    if conversation_id is not None:
        conversation_context = get_conversation_turn_context(conversation_id, before_sequence)
    else:
        conversation_context = get_recent_conversation(before_event_id)

    retrieved_knowledge = await search_knowledge(
        query=text,
        limit=KNOWLEDGE_RETRIEVAL_LIMIT,
        min_similarity=KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY
    )

    deduplicated_knowledge, suppressed_knowledge = (
        suppress_redundant_note_context(
            retrieved_knowledge
        )
    )

    # If a complete list is already present, avoid repeating its individual
    # list-item hits in the LLM context. The raw search results stay available
    # in debug output.
    retrieved_list_ids = {
        result["id"]
        for result in deduplicated_knowledge
        if result["type"] == "list"
    }

    context_results = []

    for result in deduplicated_knowledge:
        if result["type"] == "list_item":
            parent = result.get("parent") or {}

            if parent.get("id") in retrieved_list_ids:
                continue

        context_results.append(result)

    knowledge_context = "\n\nPERSÖNLICHES WISSEN – RETRIEVAL-TREFFER:\n"

    if not context_results:
        knowledge_context += (
            "Keine ausreichend relevanten gespeicherten Wissenseinträge gefunden.\n"
        )
    else:
        for result in context_results:
            result_type = result["type"]

            if result_type == "note":
                knowledge_context += (
                    f"- [Note {result['id']}] {result['content']}\n"
                )

            elif result_type == "task":
                knowledge_context += (
                    f"- [Task {result['id']}] {result['content']} "
                    f"(fällig: {result['due_at']})\n"
                )

            elif result_type == "list_item":
                parent = result.get("parent") or {}
                parent_title = parent.get("title") or "Unbekannte Liste"

                knowledge_context += (
                    f"- [List Item {result['id']}] {result['content']} "
                    f"(Liste: {parent_title})\n"
                )

            elif result_type == "fact":
                knowledge_context += (
                    f"- [Fact {result['id']}] {result['content']}\n"
                )

            elif result_type == "list":
                knowledge_context += (
                    f"- [List {result['id']}] {result['title']}\n"
                )

                if result.get("content"):
                    knowledge_context += (
                        f"  Beschreibung: {result['content']}\n"
                    )

                items = result.get("items", [])
                visible_items = items[
                    :KNOWLEDGE_LIST_CONTEXT_ITEM_LIMIT
                ]

                for item in visible_items:
                    knowledge_context += (
                        f"  - [Item {item['id']}] {item['content']}\n"
                    )

                hidden_count = len(items) - len(visible_items)

                if hidden_count > 0:
                    knowledge_context += (
                        f"  - ... {hidden_count} weitere aktive Items "
                        "nicht in diesen Kontext aufgenommen.\n"
                    )

    knowledge_context += (
        "\nDie Treffer wurden automatisch aus dem persönlichen Wissensspeicher "
        "ermittelt. Verwende nur tatsächlich relevante Treffer. "
        "Notes sind dauerhaftes Wissen. Tasks sind offene zeitgebundene "
        "Verpflichtungen. Lists sind veränderliche Sammlungen; List Items gehören "
        "zu ihrer angegebenen Liste. Facts sind einzelne geprüfte Aussagen, "
        "die aus einer Note hervorgegangen sind; die Note selbst ist danach "
        "archiviert und nicht mehr separat aufgeführt. Erfinde keine "
        "persönlichen Fakten, Aufgaben oder Listeneinträge."
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + runtime_context + knowledge_context
        }
    ]

    messages.extend(conversation_context)

    messages.append({
        "role": "user",
        "content": text
    })

    return (
        messages,
        runtime_context,
        conversation_context,
        retrieved_knowledge,
        context_results,
        suppressed_knowledge
    )

async def get_applied_prompt(messages: list[dict]):
    url = LLM_APPLY_TEMPLATE_URL

    payload = {
        "messages": messages
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

        data = response.json()

        if isinstance(data, dict):
            return data.get("prompt", data)

        return data

    except Exception as exc:
        return f"apply-template debug failed: {type(exc).__name__}: {exc}"

async def ask_llm(text: str, current_event_id: int, conversation_id=None, before_sequence: int | None = None):
    profile = get_ai_task_profile("conversation.reply")
    (
        messages,
        runtime_context,
        conversation_context,
        retrieved_knowledge,
        knowledge_context_results,
        suppressed_knowledge
    ) = await build_messages(
        text,
        current_event_id,
        conversation_id,
        before_sequence
    )

    payload = {
        "model": profile["model"],
        "messages": messages,
        "temperature": 0.3
    }

    applied_prompt = await get_applied_prompt(messages)

    async with httpx.AsyncClient(timeout=profile["timeout_seconds"]) as client:
        response = await client.post(
            profile["endpoint"],
            json=payload
        )
        response.raise_for_status()

    data = response.json()

    llm_response = data["choices"][0]["message"]["content"]

    debug = {
        "runtime_context": runtime_context,
        "conversation_context": conversation_context,
        "retrieved_knowledge": retrieved_knowledge,
        "knowledge_context_results": knowledge_context_results,
        "suppressed_knowledge": suppressed_knowledge,
        "messages_sent": messages,
        "applied_prompt": applied_prompt
    }

    return llm_response, debug
