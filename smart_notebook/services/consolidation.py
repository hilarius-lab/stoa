# Consolidation service
import httpx
import json
from datetime import datetime

from ..config import TIMEZONE
from .ai_tasks import get_ai_task_profile

def _optional_due_at(value):
    if not value or not value.strip(): return None
    due_at=datetime.fromisoformat(value.replace('Z','+00:00'))
    return due_at.replace(tzinfo=TIMEZONE) if due_at.tzinfo is None else due_at
from ..database import get_db_connection
from ..prompts import CONSOLIDATION_SYSTEM_PROMPT
from .embeddings import get_embedding
from .provenance import add_knowledge_sources, normalize_candidate_source_ids
from .lists import create_list_record, process_list_item_candidate
from .notes import save_note, update_note
from .tasks import save_task, update_task
from .dedupe import decide_note_deduplication, decide_task_deduplication
from .content_types import validate_classification
from .semantic_router import route_artifact, validate_route

def get_pending_consolidation_events(as_of=None):
    # W07: `archived=FALSE` is already the authoritative "still needs
    # consolidating" marker (see also the manual /api/events/{id}/unarchive
    # endpoint, which relies on exactly this to make an old event eligible
    # again) -- an additional "created today" lower bound only ever excluded
    # events a failed or skipped night left behind, with no way to catch them
    # up later. `as_of` is an upper bound only, so a run has a well-defined,
    # reproducible boundary instead of implicitly depending on wall-clock time
    # during the query.
    as_of = as_of or datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, text, created_at
            FROM events
            WHERE archived = FALSE
              AND created_at < %s
            ORDER BY created_at ASC, id ASC
            """,
            (as_of,)
        ).fetchall()

    return [
        {
            'id': row[0],
            'text': row[1],
            'created_at': row[2].astimezone(TIMEZONE).isoformat()
        }
        for row in rows
    ]


def _canonicalize_daily_candidates(events, candidates):
    event_by_id = {event['id']: event for event in events}
    validated = []
    for candidate in candidates:
        candidate = dict(candidate); source_ids = candidate['source_event_ids']
        if not source_ids or any(source_id not in event_by_id for source_id in source_ids):
            continue
        source_text = "\n".join(event_by_id[source_id]['text'] for source_id in source_ids)
        kind = candidate['kind']; data = {}
        if len(source_ids) == 1:
            event_time = datetime.fromisoformat(event_by_id[source_ids[0]]['created_at'].replace('Z', '+00:00'))
            route = route_artifact(source_text, event_time); route_valid, _ = validate_route(source_text, route)
            if route_valid and route['candidate_type'] == kind:
                route_data = route['normalized_data']
                if kind == 'task':
                    candidate['content'] = route_data.get('content') or candidate['content']
                    candidate['work_start_at'] = route_data.get('work_start_at', '')
                    candidate['due_at'] = route_data.get('due_at', '')
                elif kind == 'list':
                    candidate['content'] = route_data['list_title']
                elif kind == 'list_item' and len(route_data['items']) == 1:
                    candidate['list_title'] = route_data['target_list']
                    candidate['content'] = route_data['items'][0]
        if kind == 'task':
            data = {"content": candidate['content'], "work_start_at": candidate['work_start_at'],
                    "due_at": candidate['due_at']}
            if not candidate['due_at']:
                data.update({"urgency": 0.4, "urgency_source": "policy_default"})
        elif kind == 'list':
            data = {"list_title": candidate['content']}
        elif kind == 'list_item':
            data = {"target_list": candidate['list_title'], "items": [candidate['content']]}
        classification = {"candidate_type": kind, "alternative_type": None, "normalized_data": data,
            "evidence_spans": [source_text], "reason_codes": ["daily_consolidation"], "missing_fields": [],
            "confidence": 1.0, "decision_source": "llm", "abstain": False}
        if not validate_classification(source_text, classification, candidate['content']):
            validated.append(candidate)
    return validated

async def extract_daily_candidates(events: list[dict]):
    profile = get_ai_task_profile("consolidation.daily")
    if not events:
        return []

    schema = {
        'type': 'object',
        'properties': {
            'notes': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'content': {'type': 'string'},
                        'source_event_ids': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                            'minItems': 1,
                            'uniqueItems': True
                        }
                    },
                    'required': ['content', 'source_event_ids'],
                    'additionalProperties': False
                }
            },
            'tasks': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'content': {'type': 'string'},
                        'work_start_at': {'type': 'string'},
                        'due_at': {'type': 'string'},
                        'source_event_ids': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                            'minItems': 1,
                            'uniqueItems': True
                        }
                    },
                    'required': ['content', 'work_start_at', 'due_at', 'source_event_ids'],
                    'additionalProperties': False
                }
            },
            'lists': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string'},
                        'source_event_ids': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                            'minItems': 1,
                            'uniqueItems': True
                        }
                    },
                    'required': ['title', 'source_event_ids'],
                    'additionalProperties': False
                }
            },
            'list_items': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'list_title': {'type': 'string'},
                        'content': {'type': 'string'},
                        'source_event_ids': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                            'minItems': 1,
                            'uniqueItems': True
                        }
                    },
                    'required': ['list_title', 'content', 'source_event_ids'],
                    'additionalProperties': False
                }
            }
        },
        'required': ['notes', 'tasks', 'lists', 'list_items'],
        'additionalProperties': False
    }

    event_text = '\n'.join(
        f"[Event {event['id']}] Zeit: {event['created_at']} | Text: {event['text']}"
        for event in events
    )

    payload = {
        'model': profile['model'],
        'messages': [
            {'role': 'system', 'content': CONSOLIDATION_SYSTEM_PROMPT},
            {
                'role': 'user',
                'content': (
                    'Konsolidiere die folgenden Events des Tages. '
                    'Gib dauerhafte Informationen ausschließlich unter notes aus, '
                    'Aufgaben unter tasks und fortlaufende '
                    'Sammlungen unter lists sowie Listenpunkte unter list_items. '
                    'Bei Tasks bedeutet work_start_at "bearbeiten ab" und due_at "erledigen bis"; '
                    'ein ausdrücklich genannter Beginn darf nicht als Frist ausgegeben werden. '
                    'Ist nur eine Frist belegt, bleibt work_start_at leer und wird später auf den Erfassungstag gesetzt. '
                    'Notes und Listeneinträge haben weder work_start_at noch due_at.\n\n'
                    + event_text
                )
            }
        ],
        'temperature': profile['temperature'],
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'smart_notebook_daily_consolidation',
                'strict': True,
                'schema': schema
            }
        }
    }

    async with httpx.AsyncClient(timeout=profile['timeout_seconds'], trust_env=False) as client:
        response = await client.post(profile['endpoint'], json=payload)
        response.raise_for_status()

    data = response.json()
    result = json.loads(data['choices'][0]['message']['content'])

    candidates = []

    for note in result['notes']:
        candidates.append({
            'kind': 'note',
            'content': note['content'],
            'source_event_ids': note['source_event_ids']
        })

    for task in result['tasks']:
        candidates.append({
            'kind': 'task',
            'content': task['content'],
            'work_start_at': task['work_start_at'],
            'due_at': task['due_at'],
            'source_event_ids': task['source_event_ids']
        })

    for item in result['lists']:
        candidates.append({
            'kind': 'list',
            'content': item['title'],
            'source_event_ids': item['source_event_ids']
        })

    for item in result['list_items']:
        candidates.append({
            'kind': 'list_item',
            'list_title': item['list_title'],
            'content': item['content'],
            'source_event_ids': item['source_event_ids']
        })

    return _canonicalize_daily_candidates(events, candidates)

def archive_events(event_ids: list[int]):
    if not event_ids:
        return

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE events
            SET archived = TRUE,
                archived_at = %s
            WHERE id = ANY(%s)
            """,
            (datetime.now(TIMEZONE), event_ids)
        )
        connection.commit()

async def consolidate_today():
    events = get_pending_consolidation_events()

    if not events:
        return {
            'events_processed': 0,
            'candidates': [],
            'results': [],
            'events_archived': 0
        }

    candidates = await extract_daily_candidates(events)
    valid_event_ids = {event['id'] for event in events}
    results = []

    for candidate in candidates:
        kind = candidate['kind']
        content = candidate['content'].strip()
        source_event_ids = normalize_candidate_source_ids(
            candidate,
            valid_event_ids,
            events[0]['id']
        )
        source_event_id = source_event_ids[0]

        if not content:
            continue

        if kind == 'note':
            decision = await decide_note_deduplication(content)
            result = {
                'kind': 'note',
                'candidate': content,
                'source_event_id': source_event_id,
                'source_event_ids': source_event_ids,
                'deduplication': decision['action'],
                'saved_id': None,
                'updated_id': None
            }

            if decision['action'] == 'save_new':
                final_content = decision['content'].strip() or content
                embedding = await get_embedding(final_content)
                result['saved_id'] = save_note(
                    final_content,
                    embedding,
                    source_event_id=source_event_id
                )
                add_knowledge_sources(
                    "note",
                    result['saved_id'],
                    source_event_ids,
                    "source"
                )
            elif decision['action'] == 'update_existing':
                final_content = decision['content'].strip() or content
                await update_note(decision['target_id'], final_content)
                add_knowledge_sources(
                    "note",
                    decision['target_id'],
                    source_event_ids,
                    "supporting"
                )
                result['updated_id'] = decision['target_id']
            else:
                target_id = decision.get('target_id')
                if target_id:
                    add_knowledge_sources(
                        "note",
                        target_id,
                        source_event_ids,
                        "supporting"
                    )

            results.append(result)

        elif kind == 'task':
            work_start_at_raw = candidate['work_start_at'].strip()
            due_at_raw = candidate['due_at'].strip()
            try:
                work_start_at = _optional_due_at(work_start_at_raw)
                due_at = _optional_due_at(due_at_raw)
            except ValueError:
                results.append({
                    'kind': 'task',
                    'candidate': content,
                    'source_event_id': source_event_id,
                    'source_event_ids': source_event_ids,
                    'deduplication': 'invalid_due_at',
                    'saved_id': None,
                    'updated_id': None
                })
                continue

            decision = await decide_task_deduplication(content, due_at, work_start_at)
            result = {
                'kind': 'task',
                'candidate': content,
                'source_event_id': source_event_id,
                'source_event_ids': source_event_ids,
                'work_start_at': work_start_at.isoformat() if work_start_at else None,
                'due_at': due_at.isoformat() if due_at else None,
                'deduplication': decision['action'],
                'saved_id': None,
                'updated_id': None
            }

            if decision['action'] == 'save_new':
                final_content = decision['content'].strip() or content
                final_work_start_at = _optional_due_at(decision['work_start_at'])
                final_due_at = _optional_due_at(decision['due_at'])
                embedding = await get_embedding(final_content)
                result['saved_id'] = save_task(
                    final_content,
                    final_due_at,
                    embedding,
                    source_event_id=source_event_id,
                    urgency=0.4 if final_due_at is None else None,
                    urgency_source="policy_default" if final_due_at is None else None,
                    work_start_at=final_work_start_at,
                )
                add_knowledge_sources(
                    "task",
                    result['saved_id'],
                    source_event_ids,
                    "source"
                )
            elif decision['action'] == 'update_existing':
                final_content = decision['content'].strip() or content
                final_work_start_at = _optional_due_at(decision['work_start_at'])
                final_due_at = _optional_due_at(decision['due_at'])
                await update_task(
                    decision['target_id'],
                    final_content,
                    final_due_at,
                    work_start_at=final_work_start_at,
                )
                add_knowledge_sources(
                    "task",
                    decision['target_id'],
                    source_event_ids,
                    "supporting"
                )
                result['updated_id'] = decision['target_id']
            else:
                target_id = decision.get('target_id')
                if target_id:
                    add_knowledge_sources(
                        "task",
                        target_id,
                        source_event_ids,
                        "supporting"
                    )

            results.append(result)

        elif kind == 'list':
            list_id = await create_list_record(content)
            add_knowledge_sources("list", list_id, source_event_ids, "source")
            results.append({
                'kind': 'list',
                'candidate': content,
                'source_event_id': source_event_id,
                'source_event_ids': source_event_ids,
                'saved_id': list_id
            })

        elif kind == 'list_item':
            list_result = await process_list_item_candidate(
                candidate['list_title'],
                content,
                source_event_id=source_event_id,
                source_event_ids=source_event_ids,
                explicit_target=True,
            )

            results.append({
                'kind': 'list_item',
                'candidate': content,
                'list_title': candidate['list_title'],
                'source_event_id': source_event_id,
                'source_event_ids': source_event_ids,
                'list_id': list_result['list_id'],
                'list_created': list_result['list_created'],
                'deduplication': list_result['deduplication'],
                'saved_id': list_result['item_id'],
                'updated_id': list_result['updated_item_id']
            })

    event_ids = [event['id'] for event in events]
    archive_events(event_ids)

    return {
        'events_processed': len(events),
        'candidates': candidates,
        'results': results,
        'events_archived': len(event_ids)
    }
