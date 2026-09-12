# Maintenance service
import httpx
import json
from datetime import datetime

from ..config import (
    TIMEZONE, NOTE_CLEANUP_CANDIDATE_SIMILARITY, NOTE_CLEANUP_MAX_GROUPS,SYSTEM_LOG_RETENTION_HOURS
)
from ..database import get_db_connection
from ..prompts import NOTE_CLEANUP_SYSTEM_PROMPT
from .notes import update_note
from .ai_tasks import get_ai_task_profile
from .tasks import expire_overdue_tasks, archive_closed_tasks
from .provenance import transfer_knowledge_sources
from .consolidation import consolidate_today
from .claims import run_changed_conflict_scan
from .jobs import queue_parked_jobs_for_night_repair
from .client_sessions import retry_attention_required_client_sessions_for_night_repair
from .client_chat import queue_failed_chat_turns_for_night_repair
from .promotion import retry_promotion_errors_for_night_repair
from .shadow import purge_expired_shadow_details
from .audio import purge_expired_audio
from .observability import purge_expired_logs
from .retrieval import purge_expired_retrieval_cache
from .reference_resolver import purge_expired_reference_candidates
from .nightly_consolidation import run_nightly_knowledge_consolidation

def find_note_cleanup_candidate_groups(
    candidate_similarity: float,
    max_groups: int
):
    candidate_similarity = max(
        -1.0,
        min(candidate_similarity, 1.0)
    )
    max_groups = max(1, min(max_groups, 50))

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                a.id,
                a.content,
                b.id,
                b.content,
                1 - (a.embedding <=> b.embedding) AS similarity
            FROM notes a
            JOIN notes b
              ON a.id < b.id
            WHERE a.archived = FALSE
              AND b.archived = FALSE
              AND a.embedding IS NOT NULL
              AND b.embedding IS NOT NULL
              AND 1 - (a.embedding <=> b.embedding) >= %s
            ORDER BY similarity DESC
            """,
            (candidate_similarity,)
        ).fetchall()

    if not rows:
        return []

    note_contents = {}
    adjacency = {}
    pair_similarity = {}

    for row in rows:
        left_id = row[0]
        right_id = row[2]
        similarity = float(row[4])

        note_contents[left_id] = row[1]
        note_contents[right_id] = row[3]

        adjacency.setdefault(left_id, set()).add(right_id)
        adjacency.setdefault(right_id, set()).add(left_id)

        pair_similarity[(left_id, right_id)] = similarity

    groups = []
    visited = set()

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
            stack.extend(adjacency.get(current, set()) - visited)

        if len(component) < 2:
            continue

        component = sorted(component)

        similarities = []

        for index, left_id in enumerate(component):
            for right_id in component[index + 1:]:
                key = (
                    min(left_id, right_id),
                    max(left_id, right_id)
                )

                if key in pair_similarity:
                    similarities.append({
                        "left_id": key[0],
                        "right_id": key[1],
                        "similarity": pair_similarity[key]
                    })

        groups.append({
            "note_ids": component,
            "notes": [
                {
                    "id": current_id,
                    "content": note_contents[current_id]
                }
                for current_id in component
            ],
            "candidate_pairs": similarities
        })

    groups.sort(
        key=lambda group: max(
            (
                pair["similarity"]
                for pair in group["candidate_pairs"]
            ),
            default=-1.0
        ),
        reverse=True
    )

    return groups[:max_groups]

async def propose_note_cleanup_group(group: dict):
    profile = get_ai_task_profile("maintenance.note_cleanup")
    schema = {
        "type": "object",
        "properties": {
            "merge_groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "note_ids": {
                            "type": "array",
                            "items": {
                                "type": "integer"
                            }
                        },
                        "canonical_id": {
                            "type": "integer"
                        },
                        "merged_content": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "note_ids",
                        "canonical_id",
                        "merged_content"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": [
            "merge_groups"
        ],
        "additionalProperties": False
    }

    notes_text = "\n".join(
        (
            f"[Note {note['id']}] "
            f"{note['content']}"
        )
        for note in group["notes"]
    )

    pair_text = "\n".join(
        (
            f"- Note {pair['left_id']} <-> Note {pair['right_id']}: "
            f"{pair['similarity']:.3f}"
        )
        for pair in group["candidate_pairs"]
    )

    payload = {
        "model": profile["model"],
        "messages": [
            {
                "role": "system",
                "content": NOTE_CLEANUP_SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": (
                    "Prüfe diese Kandidatengruppe:\n\n"
                    f"{notes_text}\n\n"
                    "Vektorähnliche Kandidatenpaare:\n"
                    f"{pair_text}"
                )
            }
        ],
        "temperature": profile["temperature"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_notebook_note_cleanup",
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
    proposal = json.loads(
        data["choices"][0]["message"]["content"]
    )

    valid_ids = set(group["note_ids"])
    used_ids = set()
    validated_groups = []

    for merge_group in proposal["merge_groups"]:
        note_ids = list(dict.fromkeys(
            merge_group["note_ids"]
        ))
        canonical_id = merge_group["canonical_id"]
        merged_content = merge_group[
            "merged_content"
        ].strip()

        if len(note_ids) < 2:
            continue

        if not set(note_ids).issubset(valid_ids):
            continue

        if canonical_id not in note_ids:
            continue

        if not merged_content:
            continue

        if used_ids.intersection(note_ids):
            continue

        used_ids.update(note_ids)

        validated_groups.append({
            "note_ids": note_ids,
            "canonical_id": canonical_id,
            "merged_content": merged_content
        })

    return {
        "merge_groups": validated_groups
    }

def archive_note_ids(note_ids: list[int]):
    if not note_ids:
        return 0

    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            UPDATE notes
            SET archived = TRUE,
                updated_at = %s
            WHERE id = ANY(%s)
              AND archived = FALSE
            RETURNING id
            """,
            (
                now,
                note_ids
            )
        ).fetchall()

        connection.commit()

    return len(rows)

async def run_note_cleanup(
    dry_run: bool = True,
    candidate_similarity: float = NOTE_CLEANUP_CANDIDATE_SIMILARITY,
    max_groups: int = NOTE_CLEANUP_MAX_GROUPS
):
    groups = find_note_cleanup_candidate_groups(
        candidate_similarity=candidate_similarity,
        max_groups=max_groups
    )

    analyzed = []
    merged_count = 0
    archived_count = 0

    for group in groups:
        proposal = await propose_note_cleanup_group(
            group
        )

        applied_groups = []

        for merge_group in proposal["merge_groups"]:
            canonical_id = merge_group[
                "canonical_id"
            ]
            merged_content = merge_group[
                "merged_content"
            ]
            duplicate_ids = [
                note_id
                for note_id in merge_group["note_ids"]
                if note_id != canonical_id
            ]

            applied = False

            if not dry_run:
                await update_note(
                    canonical_id,
                    merged_content
                )

                transfer_knowledge_sources(
                    "note",
                    canonical_id,
                    duplicate_ids
                )

                archived_count += archive_note_ids(
                    duplicate_ids
                )
                merged_count += 1
                applied = True

            applied_groups.append({
                **merge_group,
                "duplicate_ids": duplicate_ids,
                "applied": applied
            })

        analyzed.append({
            "candidate_group": group,
            "merge_groups": applied_groups
        })

    return {
        "dry_run": dry_run,
        "candidate_similarity": candidate_similarity,
        "candidate_groups": len(groups),
        "merge_groups": sum(
            len(item["merge_groups"])
            for item in analyzed
        ),
        "merged_count": merged_count,
        "archived_count": archived_count,
        "analysis": analyzed
    }

async def run_daily_maintenance():
    consolidation = await consolidate_today()
    nightly_knowledge=await run_nightly_knowledge_consolidation(dry_run=False,semantic_review=True)
    conflicts = await run_changed_conflict_scan(dry_run=False)
    from .note_fact import promote_eligible_notes_to_facts
    note_fact_promotions=promote_eligible_notes_to_facts(dry_run=False)
    repaired_jobs=queue_parked_jobs_for_night_repair()
    repaired_sessions=await retry_attention_required_client_sessions_for_night_repair()
    repaired_chat_turns=queue_failed_chat_turns_for_night_repair()
    repaired_promotions=await retry_promotion_errors_for_night_repair()
    purged_shadow_details=purge_expired_shadow_details()
    audio_retention=purge_expired_audio()
    purged_logs=purge_expired_logs()
    purged_cache=purge_expired_retrieval_cache()
    purged_reference_runs=purge_expired_reference_candidates()
    from .client_chat import purge_expired_conversations
    purged_conversations=purge_expired_conversations()

    expired_tasks = expire_overdue_tasks()
    archived_tasks = archive_closed_tasks()

    return {
        "consolidation": consolidation,
        "nightly_knowledge":nightly_knowledge,
        "claim_conflicts": conflicts,
        "note_fact_promotions":note_fact_promotions,
        "night_repair":{"queued_count":len(repaired_jobs),"jobs":repaired_jobs},
        "client_session_night_repair":{"retried_count":len(repaired_sessions),"sessions":repaired_sessions},
        "chat_turn_night_repair":{"retried_count":len(repaired_chat_turns),"turns":repaired_chat_turns},
        "promotion_night_repair":{"retried_session_count":len(repaired_promotions),"sessions":repaired_promotions},
        "shadow_retention":{"purged_detail_rows":purged_shadow_details},
        "audio_retention":audio_retention,
        "log_retention":{"retention_hours":SYSTEM_LOG_RETENTION_HOURS,"purged_rows":purged_logs},
        "retrieval_cache":{"purged_rows":purged_cache},
        "reference_resolver_retention":{"purged_runs":purged_reference_runs},
        "conversation_retention":{"purged_conversations":purged_conversations},
        "task_lifecycle": {
            "expired_count": len(expired_tasks),
            "expired_tasks": expired_tasks,
            "archived_count": len(archived_tasks),
            "archived_tasks": archived_tasks
        }
    }
