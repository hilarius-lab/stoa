# List service
import httpx
import json
from datetime import datetime

from ..config import (
    TIMEZONE, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS,
    LIST_RETRIEVAL_LIMIT, LIST_RETRIEVAL_MIN_SIMILARITY, LIST_TARGET_CANDIDATE_LIMIT,
    LIST_ITEM_DEDUPE_LIMIT
)
from ..database import get_db_connection
from .embeddings import get_embedding, get_query_embedding, embedding_to_pgvector
from .provenance import add_knowledge_source, add_knowledge_sources
from .ai_tasks import get_ai_task_profile

def get_list_search_text(list_id: int):
    with get_db_connection() as connection:
        list_row = connection.execute(
            """
            SELECT title, description
            FROM lists
            WHERE id = %s
            """,
            (list_id,)
        ).fetchone()

        if list_row is None:
            return None

        item_rows = connection.execute(
            """
            SELECT content
            FROM list_items
            WHERE list_id = %s
              AND archived = FALSE
              AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            (list_id,)
        ).fetchall()

    parts = [list_row[0]]

    if list_row[1].strip():
        parts.append(list_row[1].strip())

    parts.extend(row[0] for row in item_rows)

    return "\n".join(parts)

async def refresh_list_embedding(list_id: int):
    search_text = get_list_search_text(list_id)

    if search_text is None:
        return False

    embedding = await get_embedding(search_text)
    vector_value = embedding_to_pgvector(embedding)
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE lists
            SET embedding = %s::vector,
                embedding_model = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                vector_value,
                EMBEDDING_MODEL,
                now,
                list_id
            )
        )
        connection.commit()

    return True

async def create_list_record(
    title: str,
    description: str = "",
    embedding_vector: list[float] | None = None,
):
    title = title.strip()
    description = description.strip()

    if not title:
        raise ValueError("List title must not be empty")

    now = datetime.now(TIMEZONE)
    embedding = embedding_vector if embedding_vector is not None else await get_embedding(
        title + ("\n" + description if description else "")
    )
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        list_id = connection.execute(
            """
            INSERT INTO lists (
                title,
                description,
                created_at,
                updated_at,
                embedding,
                embedding_model
            )
            VALUES (%s, %s, %s, %s, %s::vector, %s)
            RETURNING id
            """,
            (
                title,
                description,
                now,
                now,
                vector_value,
                EMBEDDING_MODEL
            )
        ).fetchone()[0]
        connection.commit()

    return list_id


async def get_or_create_active_list_record(
    title: str,
    description: str = "",
    embedding_vector: list[float] | None = None,
):
    """Return one active exact-title list, creating it only when absent.

    The advisory transaction lock makes the check-and-create path safe when
    two independently captured list-creation artifacts are promoted together.
    Archived lists deliberately do not block a new active list.
    """
    title = title.strip()
    description = description.strip()
    if not title:
        raise ValueError("List title must not be empty")

    lock_key = f"active-list-title:{title.casefold()}"

    # Reusing an exact active container must not depend on the embedding
    # service being available.  The unlocked read is only a fast path; a
    # second check under the advisory lock remains authoritative for creation.
    with get_db_connection() as connection:
        existing = connection.execute(
            """SELECT id FROM lists
            WHERE lower(title)=lower(%s) AND archived=FALSE
            ORDER BY id LIMIT 1""",
            (title,),
        ).fetchone()
    if existing is not None:
        return existing[0], False

    embedding = embedding_vector if embedding_vector is not None else await get_embedding(
        title + ("\n" + description if description else "")
    )
    vector_value = embedding_to_pgvector(embedding)
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
        existing = connection.execute(
            """SELECT id FROM lists
            WHERE lower(title)=lower(%s) AND archived=FALSE
            ORDER BY id LIMIT 1""",
            (title,),
        ).fetchone()
        if existing is not None:
            connection.commit()
            return existing[0], False
        list_id = connection.execute(
            """INSERT INTO lists (
                title, description, created_at, updated_at, embedding, embedding_model
            ) VALUES (%s, %s, %s, %s, %s::vector, %s)
            RETURNING id""",
            (title, description, now, now, vector_value, EMBEDDING_MODEL),
        ).fetchone()[0]
        connection.commit()
    return list_id, True

async def add_list_item_record(
    list_id: int,
    content: str,
    source_event_id: int | None = None,
    embedding_vector: list[float] | None = None,
    refresh_embedding: bool = True,
):
    content = content.strip()

    if not content:
        raise ValueError("List item content must not be empty")

    embedding = embedding_vector if embedding_vector is not None else await get_embedding(content)
    vector_value = embedding_to_pgvector(embedding)
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM lists WHERE id = %s AND archived = FALSE",
            (list_id,)
        ).fetchone()

        if exists is None:
            return None

        item_id = connection.execute(
            """
            INSERT INTO list_items (
                list_id,
                content,
                created_at,
                updated_at,
                source_event_id,
                embedding,
                embedding_model
            )
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
            RETURNING id
            """,
            (
                list_id,
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
        "list_item",
        item_id,
        source_event_id,
        "source"
    )

    add_knowledge_source(
        "list",
        list_id,
        source_event_id,
        "item_source"
    )

    if refresh_embedding:
        await refresh_list_embedding(list_id)

    return item_id

async def update_list_item_record(
    item_id: int,
    content: str
):
    content = content.strip()

    if not content:
        raise ValueError("List item content must not be empty")

    embedding = await get_embedding(content)
    vector_value = embedding_to_pgvector(embedding)
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            UPDATE list_items
            SET content = %s,
                updated_at = %s,
                embedding = %s::vector,
                embedding_model = %s
            WHERE id = %s
            RETURNING list_id
            """,
            (
                content,
                now,
                vector_value,
                EMBEDDING_MODEL,
                item_id
            )
        ).fetchone()
        connection.commit()

    if row is None:
        return None

    await refresh_list_embedding(row[0])
    return row[0]

def get_list_record(list_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                title,
                description,
                created_at,
                updated_at,
                archived,
                embedding_model,
                CASE
                    WHEN embedding IS NULL THEN NULL
                    ELSE vector_dims(embedding)
                END
            FROM lists
            WHERE id = %s
            """,
            (list_id,)
        ).fetchone()

        if row is None:
            return None

        item_rows = connection.execute(
            """
            SELECT
                id,
                content,
                created_at,
                updated_at,
                source_event_id,
                status,
                archived,
                embedding_model
            FROM list_items
            WHERE list_id = %s
              AND archived = FALSE
            ORDER BY created_at ASC, id ASC
            """,
            (list_id,)
        ).fetchall()

    return {
        "id": row[0],
        "title": row[1],
        "description": row[2],
        "created_at": row[3].isoformat(),
        "updated_at": row[4].isoformat(),
        "archived": row[5],
        "embedding_model": row[6],
        "embedding_dimensions": row[7],
        "items": [
            {
                "id": item[0],
                "content": item[1],
                "created_at": item[2].isoformat(),
                "updated_at": item[3].isoformat(),
                "source_event_id": item[4],
                "status": item[5],
                "archived": item[6],
                "embedding_model": item[7]
            }
            for item in item_rows
        ]
    }

def get_list_item_record(item_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                list_id,
                content,
                created_at,
                updated_at,
                source_event_id,
                status,
                archived,
                embedding_model,
                CASE
                    WHEN embedding IS NULL THEN NULL
                    ELSE vector_dims(embedding)
                END
            FROM list_items
            WHERE id = %s
            """,
            (item_id,)
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row[0],
        "list_id": row[1],
        "content": row[2],
        "created_at": row[3].isoformat(),
        "updated_at": row[4].isoformat(),
        "source_event_id": row[5],
        "status": row[6],
        "archived": row[7],
        "embedding_model": row[8],
        "embedding_dimensions": row[9]
    }

async def set_list_item_status(item_id: int, status: str):
    if status not in {"active", "done", "archived"}:
        raise ValueError(f"Unsupported list item status: {status}")

    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            UPDATE list_items
            SET status = %s,
                archived = CASE
                    WHEN %s = 'archived' THEN TRUE
                    WHEN %s = 'active' THEN FALSE
                    ELSE archived
                END,
                updated_at = %s
            WHERE id = %s
            RETURNING list_id
            """,
            (
                status,
                status,
                status,
                now,
                item_id
            )
        ).fetchone()
        connection.commit()

    if row is None:
        return None

    await refresh_list_embedding(row[0])
    return get_list_item_record(item_id)

async def set_list_archived(list_id: int, archived: bool):
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            UPDATE lists
            SET archived = %s,
                updated_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                archived,
                now,
                list_id
            )
        ).fetchone()
        connection.commit()

    if row is None:
        return None

    return get_list_record(list_id)

async def search_lists(query: str, limit: int = 3):
    limit = max(1, min(limit, 20))
    embedding = await get_query_embedding(query)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                description,
                updated_at,
                embedding_model,
                1 - (embedding <=> %s::vector) AS similarity
            FROM lists
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

        results = []

        for row in rows:
            item_rows = connection.execute(
                """
                SELECT id, content, status
                FROM list_items
                WHERE list_id = %s
                  AND archived = FALSE
                  AND status = 'active'
                ORDER BY created_at ASC, id ASC
                LIMIT 50
                """,
                (row[0],)
            ).fetchall()

            results.append({
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "updated_at": row[3].isoformat(),
                "embedding_model": row[4],
                "similarity": float(row[5]),
                "items": [
                    {
                        "id": item[0],
                        "content": item[1],
                        "status": item[2]
                    }
                    for item in item_rows
                ]
            })

    return results

async def search_list_items(
    list_id: int,
    query: str,
    limit: int = 3
):
    limit = max(1, min(limit, 20))
    embedding = await get_query_embedding(query)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                content,
                source_event_id,
                status,
                embedding_model,
                1 - (embedding <=> %s::vector) AS similarity
            FROM list_items
            WHERE list_id = %s
              AND archived = FALSE
              AND status = 'active'
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_value,
                list_id,
                vector_value,
                limit
            )
        ).fetchall()

    return [
        {
            "id": row[0],
            "content": row[1],
            "source_event_id": row[2],
            "status": row[3],
            "embedding_model": row[4],
            "similarity": float(row[5])
        }
        for row in rows
    ]

async def search_list_items_global(
    query: str,
    limit: int = 5
):
    limit = max(1, min(limit, 50))
    embedding = await get_query_embedding(query)
    vector_value = embedding_to_pgvector(embedding)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                li.id,
                li.list_id,
                l.title,
                li.content,
                li.created_at,
                li.updated_at,
                li.source_event_id,
                li.status,
                li.embedding_model,
                1 - (li.embedding <=> %s::vector) AS similarity
            FROM list_items li
            JOIN lists l
              ON l.id = li.list_id
            WHERE li.archived = FALSE
              AND li.status = 'active'
              AND li.embedding IS NOT NULL
              AND l.archived = FALSE
            ORDER BY li.embedding <=> %s::vector
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
            "list_id": row[1],
            "list_title": row[2],
            "content": row[3],
            "created_at": row[4].isoformat(),
            "updated_at": row[5].isoformat(),
            "source_event_id": row[6],
            "status": row[7],
            "embedding_model": row[8],
            "similarity": float(row[9])
        }
        for row in rows
    ]

async def resolve_list_target(
    proposed_title: str,
    item_content: str
):
    profile = get_ai_task_profile("deduplication.list_item")
    query = f"{proposed_title}\n{item_content}".strip()
    matches = await search_lists(
        query,
        LIST_TARGET_CANDIDATE_LIMIT
    )

    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["use_existing", "create_new", "reject"]
            },
            "target_id": {"type": "integer"},
            "title": {"type": "string"},
            "confidence": {"type": "number"}
        },
        "required": ["action", "target_id", "title", "confidence"],
        "additionalProperties": False
    }

    match_text = "\n".join(
        (
            f"[List {match['id']}] {match['title']} | "
            f"{match['description']} | "
            f"similarity={match['similarity']:.3f}"
        )
        for match in matches
    ) or "Keine vorhandenen Listen gefunden."

    payload = {
        "model": profile["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "Du ordnest einen neuen Listenpunkt einer bestehenden Liste zu. "
                    "Nutze use_existing nur, wenn die vorhandene Liste semantisch "
                    "wirklich dieselbe Sammlung darstellt. Sonst create_new. "
                    "Bei create_new formuliere einen kurzen stabilen Listentitel. "
                    "Nutze create_new nur für einen eindeutig belegten fortlaufenden "
                    "Sammlungskontext. Nutze reject bei einer Einzelinformation, einem "
                    "unspezifischen Titel oder Unsicherheit. Erfinde weder Listenzweck "
                    "noch Einträge. confidence bewertet ausschließlich die Sicherheit "
                    "der Zuordnungs-/Erstellentscheidung."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Vorgeschlagener Listentitel: {proposed_title}\n"
                    f"Neuer Punkt: {item_content}\n\n"
                    f"Vorhandene Kandidaten:\n{match_text}"
                )
            }
        ],
        "temperature": profile["temperature"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_notebook_list_target",
                "strict": True,
                "schema": schema
            }
        }
    }

    async with httpx.AsyncClient(timeout=profile["timeout_seconds"]) as client:
        response = await client.post(profile["endpoint"], json=payload)
        response.raise_for_status()

    data = response.json()
    result = json.loads(data["choices"][0]["message"]["content"])

    valid_ids = {match["id"] for match in matches}

    if not 0 <= result["confidence"] <= 1:
        result = {"action":"reject","target_id":0,"title":proposed_title,"confidence":0}

    if (
        result["action"] == "use_existing"
        and result["target_id"] not in valid_ids
    ):
        result = {
            "action": "create_new",
            "target_id": 0,
            "title": proposed_title,
            "confidence": 0
        }

    if result["action"] == "create_new" and result["confidence"] < 0.85:
        result = {"action":"reject","target_id":0,"title":proposed_title,"confidence":result["confidence"]}

    if not result["title"].strip():
        result["title"] = proposed_title

    return result

async def decide_list_item_deduplication(
    list_id: int,
    content: str
):
    profile = get_ai_task_profile("deduplication.list_item")
    matches = await search_list_items(
        list_id,
        content,
        LIST_ITEM_DEDUPE_LIMIT
    )

    if not matches:
        return {
            "action": "save_new",
            "target_id": 0,
            "content": content
        }

    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["skip", "update_existing", "save_new"]
            },
            "target_id": {"type": "integer"},
            "content": {"type": "string"}
        },
        "required": ["action", "target_id", "content"],
        "additionalProperties": False
    }

    match_text = "\n".join(
        (
            f"[Item {match['id']}] {match['content']} "
            f"(similarity={match['similarity']:.3f})"
        )
        for match in matches
    )

    payload = {
        "model": profile["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "Prüfe einen neuen Listenpunkt gegen vorhandene Punkte derselben "
                    "Liste. skip = bereits vollständig enthalten. update_existing = "
                    "derselbe Punkt mit materieller Ergänzung. save_new = eigenständiger "
                    "neuer Punkt. Erfinde nichts."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Neuer Listenpunkt: {content}\n\n"
                    f"Ähnlichste vorhandene Punkte:\n{match_text}"
                )
            }
        ],
        "temperature": profile["temperature"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_notebook_list_item_deduplication",
                "strict": True,
                "schema": schema
            }
        }
    }

    async with httpx.AsyncClient(timeout=profile["timeout_seconds"]) as client:
        response = await client.post(profile["endpoint"], json=payload)
        response.raise_for_status()

    data = response.json()
    result = json.loads(data["choices"][0]["message"]["content"])
    valid_ids = {match["id"] for match in matches}

    if (
        result["action"] == "update_existing"
        and result["target_id"] not in valid_ids
    ):
        result = {
            "action": "save_new",
            "target_id": 0,
            "content": content
        }

    return result

async def process_list_item_candidate(
    list_title: str,
    content: str,
    source_event_id: int | None = None,
    source_event_ids: list[int] | None = None,
    explicit_target: bool = False,
):
    list_title = list_title.strip()
    content = content.strip()

    all_source_event_ids = list(
        dict.fromkeys(
            (
                source_event_ids
                if source_event_ids is not None
                else (
                    [source_event_id]
                    if source_event_id is not None
                    else []
                )
            )
        )
    )

    primary_source_event_id = (
        all_source_event_ids[0]
        if all_source_event_ids
        else source_event_id
    )

    if not list_title or not content:
        return {
            "action": "invalid",
            "list_id": None,
            "list_created": False,
            "item_id": None,
            "updated_item_id": None,
            "deduplication": None
        }

    if explicit_target:
        with get_db_connection() as connection:
            existing = connection.execute(
                """SELECT id, title FROM lists
                WHERE lower(title)=lower(%s) AND archived=FALSE
                ORDER BY id LIMIT 1""",
                (list_title,),
            ).fetchone()
        target = ({"action":"use_existing", "target_id":existing[0],
                   "title":existing[1], "confidence":1.0}
                  if existing else
                  {"action":"create_new", "target_id":0,
                   "title":list_title, "confidence":1.0})
    else:
        target = await resolve_list_target(
            list_title,
            content
        )

    if target["action"] == "reject":
        return {"action":"rejected","reason":"list_target_not_confident","confidence":target["confidence"],"list_id":None,"list_created":False,"item_id":None,"updated_item_id":None,"deduplication":None}

    list_created = False

    if target["action"] == "create_new":
        final_title = target["title"].strip() or list_title
        list_id = await create_list_record(final_title)
        list_created = True
    else:
        list_id = target["target_id"]

    add_knowledge_sources(
        "list",
        list_id,
        all_source_event_ids,
        "source" if list_created else "item_source"
    )

    decision = await decide_list_item_deduplication(
        list_id,
        content
    )

    result = {
        "action": "save_list_item",
        "list_id": list_id,
        "list_created": list_created,
        "item_id": None,
        "updated_item_id": None,
        "deduplication": decision["action"],
        "content": content
    }

    if decision["action"] == "save_new":
        final_content = decision["content"].strip() or content

        result["item_id"] = await add_list_item_record(
            list_id,
            final_content,
            source_event_id=primary_source_event_id
        )

        add_knowledge_sources(
            "list_item",
            result["item_id"],
            all_source_event_ids,
            "source"
        )

        result["content"] = final_content

    elif decision["action"] == "update_existing":
        final_content = decision["content"].strip() or content

        await update_list_item_record(
            decision["target_id"],
            final_content
        )

        add_knowledge_sources(
            "list_item",
            decision["target_id"],
            all_source_event_ids,
            "supporting"
        )

        result["updated_item_id"] = decision["target_id"]
        result["content"] = final_content

    else:
        target_id = decision.get("target_id")

        if target_id:
            # A deduplicated candidate is still a successful durable result.
            # Expose the reused row so callers can link provenance/artifacts
            # instead of treating the intentional no-op as a rejection.
            result["existing_item_id"] = target_id
            add_knowledge_sources(
                "list_item",
                target_id,
                all_source_event_ids,
                "supporting"
            )

    return result
