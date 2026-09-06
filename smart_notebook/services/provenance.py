# Provenance service
from datetime import datetime

from ..config import TIMEZONE
from ..database import get_db_connection

KNOWLEDGE_TYPES = {"note", "task", "list", "list_item"}

def add_knowledge_source(
    knowledge_type: str,
    knowledge_id: int,
    event_id: int | None,
    relation: str = "source"
):
    if event_id is None:
        return False

    if knowledge_type not in KNOWLEDGE_TYPES:
        raise ValueError(
            f"Unsupported knowledge type: {knowledge_type}"
        )

    relation = relation.strip() or "source"
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO knowledge_sources (
                knowledge_type,
                knowledge_id,
                event_id,
                relation,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (
                knowledge_type,
                knowledge_id,
                event_id
            )
            DO NOTHING
            RETURNING id
            """,
            (
                knowledge_type,
                knowledge_id,
                event_id,
                relation,
                now
            )
        ).fetchone()

        connection.commit()

    return row is not None

def add_knowledge_sources(
    knowledge_type: str,
    knowledge_id: int,
    event_ids: list[int] | None,
    relation: str = "source"
):
    if not event_ids:
        return 0

    added = 0

    for event_id in dict.fromkeys(event_ids):
        if add_knowledge_source(
            knowledge_type,
            knowledge_id,
            event_id,
            relation
        ):
            added += 1

    return added

def get_knowledge_sources(
    knowledge_type: str,
    knowledge_id: int
):
    if knowledge_type not in KNOWLEDGE_TYPES:
        raise ValueError(
            f"Unsupported knowledge type: {knowledge_type}"
        )

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                ks.event_id,
                ks.relation,
                ks.created_at,
                e.text,
                e.created_at,
                e.source,
                e.archived,
                e.client_event_id
            FROM knowledge_sources ks
            JOIN events e
              ON e.id = ks.event_id
            WHERE ks.knowledge_type = %s
              AND ks.knowledge_id = %s
            ORDER BY e.created_at ASC, ks.event_id ASC
            """,
            (
                knowledge_type,
                knowledge_id
            )
        ).fetchall()

    return [
        {
            "event_id": row[0],
            "relation": row[1],
            "linked_at": row[2].isoformat(),
            "event": {
                "id": row[0],
                "text": row[3],
                "created_at": row[4].isoformat(),
                "source": row[5],
                "archived": row[6],
                "client_event_id": row[7]
            }
        }
        for row in rows
    ]

def get_event_knowledge(event_id: int):
    with get_db_connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM events WHERE id = %s",
            (event_id,)
        ).fetchone()

        if exists is None:
            return None

        rows = connection.execute(
            """
            SELECT
                knowledge_type,
                knowledge_id,
                relation,
                created_at
            FROM knowledge_sources
            WHERE event_id = %s
            ORDER BY knowledge_type, knowledge_id
            """,
            (event_id,)
        ).fetchall()

    return [
        {
            "key": f"{row[0]}:{row[1]}",
            "type": row[0],
            "id": row[1],
            "relation": row[2],
            "linked_at": row[3].isoformat()
        }
        for row in rows
    ]

def transfer_knowledge_sources(
    knowledge_type: str,
    canonical_id: int,
    source_ids: list[int]
):
    source_ids = [
        item_id
        for item_id in dict.fromkeys(source_ids)
        if item_id != canonical_id
    ]

    if not source_ids:
        return 0

    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            INSERT INTO knowledge_sources (
                knowledge_type,
                knowledge_id,
                event_id,
                relation,
                created_at
            )
            SELECT DISTINCT
                %s,
                %s,
                event_id,
                'merged_source',
                %s
            FROM knowledge_sources
            WHERE knowledge_type = %s
              AND knowledge_id = ANY(%s)
            ON CONFLICT (
                knowledge_type,
                knowledge_id,
                event_id
            )
            DO NOTHING
            RETURNING id
            """,
            (
                knowledge_type,
                canonical_id,
                now,
                knowledge_type,
                source_ids
            )
        ).fetchall()

        connection.commit()

    return len(rows)

def normalize_candidate_source_ids(
    candidate: dict,
    valid_event_ids: set[int],
    fallback_event_id: int
):
    raw_ids = candidate.get("source_event_ids")

    if raw_ids is None:
        legacy_id = candidate.get("source_event_id")
        raw_ids = (
            [legacy_id]
            if legacy_id is not None
            else []
        )

    source_event_ids = [
        event_id
        for event_id in dict.fromkeys(raw_ids)
        if event_id in valid_event_ids
    ]

    if not source_event_ids:
        source_event_ids = [fallback_event_id]

    return source_event_ids
