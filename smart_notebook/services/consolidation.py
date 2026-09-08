# Consolidation service
import httpx
import json
from datetime import datetime, timedelta

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
from .lists import process_list_item_candidate
from .notes import save_note, update_note
from .tasks import save_task, update_task
from .dedupe import decide_note_deduplication, decide_task_deduplication

def get_today_unarchived_events():
    now = datetime.now(TIMEZONE)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, text, created_at
            FROM events
            WHERE archived = FALSE
              AND created_at >= %s
              AND created_at < %s
            ORDER BY created_at ASC, id ASC
            """,
            (day_start, day_end)
        ).fetchall()

    return [
        {
            'id': row[0],
            'text': row[1],
            'created_at': row[2].astimezone(TIMEZONE).isoformat()
        }
        for row in rows
    ]

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
        'required': ['notes', 'tasks', 'list_items'],
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
                    'Aufgaben mit belastbarer Frist unter tasks und fortlaufende '
                    'Sammlungs-/Listenpunkte unter list_items. '
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

    for item in result['list_items']:
        candidates.append({
            'kind': 'list_item',
            'list_title': item['list_title'],
            'content': item['content'],
            'source_event_ids': item['source_event_ids']
        })

    return candidates

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
    events = get_today_unarchived_events()

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

        elif kind == 'list_item':
            list_result = await process_list_item_candidate(
                candidate['list_title'],
                content,
                source_event_id=source_event_id,
                source_event_ids=source_event_ids
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
