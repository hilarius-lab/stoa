# Deduplication service
import httpx
import json
from datetime import datetime

from ..config import CONSOLIDATION_DEDUPE_LIMIT
from .ai_tasks import get_ai_task_profile
from ..prompts import DEDUPLICATION_SYSTEM_PROMPT
from .notes import search_notes
from .tasks import search_tasks

async def decide_note_deduplication(content: str):
    profile = get_ai_task_profile("deduplication.note")
    matches = await search_notes(content, CONSOLIDATION_DEDUPE_LIMIT)

    if not matches:
        return {
            'action': 'save_new',
            'target_id': 0,
            'content': content,
            'matches': []
        }

    schema = {
        'type': 'object',
        'properties': {
            'action': {
                'type': 'string',
                'enum': ['skip', 'update_existing', 'save_new']
            },
            'target_id': {'type': 'integer'},
            'content': {'type': 'string'}
        },
        'required': ['action', 'target_id', 'content'],
        'additionalProperties': False
    }

    existing_text = '\n'.join(
        f"[Note {m['id']}] {m['content']} (similarity={m['similarity']:.3f})"
        for m in matches
    )

    payload = {
        'model': profile['model'],
        'messages': [
            {'role': 'system', 'content': DEDUPLICATION_SYSTEM_PROMPT},
            {
                'role': 'user',
                'content': (
                    f"Neuer Note-Kandidat:\n{content}\n\n"
                    f"Ähnlichste vorhandene Notes:\n{existing_text}"
                )
            }
        ],
        'temperature': profile['temperature'],
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'smart_notebook_note_deduplication',
                'strict': True,
                'schema': schema
            }
        }
    }

    async with httpx.AsyncClient(timeout=profile['timeout_seconds'], trust_env=False) as client:
        response = await client.post(profile['endpoint'], json=payload)
        response.raise_for_status()

    result = json.loads(response.json()['choices'][0]['message']['content'])
    valid_ids = {m['id'] for m in matches}

    if result['action'] == 'update_existing' and result['target_id'] not in valid_ids:
        result = {'action': 'save_new', 'target_id': 0, 'content': content}

    result['matches'] = matches
    return result

async def decide_task_deduplication(content: str, due_at: datetime | None):
    profile = get_ai_task_profile("deduplication.task")
    matches = await search_tasks(content, CONSOLIDATION_DEDUPE_LIMIT)

    if not matches:
        return {
            'action': 'save_new',
            'target_id': 0,
            'content': content,
            'due_at': due_at.isoformat() if due_at else '',
            'matches': []
        }

    schema = {
        'type': 'object',
        'properties': {
            'action': {
                'type': 'string',
                'enum': ['skip', 'update_existing', 'save_new']
            },
            'target_id': {'type': 'integer'},
            'content': {'type': 'string'},
            'due_at': {'type': 'string'}
        },
        'required': ['action', 'target_id', 'content', 'due_at'],
        'additionalProperties': False
    }

    existing_text = '\n'.join(
        (
            f"[Task {m['id']}] {m['content']} | due_at={m['due_at']} "
            f"(similarity={m['similarity']:.3f})"
        )
        for m in matches
    )

    payload = {
        'model': profile['model'],
        'messages': [
            {
                'role': 'system',
                'content': DEDUPLICATION_SYSTEM_PROMPT + (
                    '\nBei Tasks berücksichtige zusätzlich, ob sich Aufgabe oder '
                    'Fälligkeit materiell geändert haben.'
                )
            },
            {
                'role': 'user',
                'content': (
                    f"Neuer Task-Kandidat:\n{content}\n"
                    f"due_at={due_at.isoformat() if due_at else 'nicht festgelegt'}\n\n"
                    f"Ähnlichste vorhandene offene Tasks:\n{existing_text}"
                )
            }
        ],
        'temperature': profile['temperature'],
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'smart_notebook_task_deduplication',
                'strict': True,
                'schema': schema
            }
        }
    }

    async with httpx.AsyncClient(timeout=profile['timeout_seconds'], trust_env=False) as client:
        response = await client.post(profile['endpoint'], json=payload)
        response.raise_for_status()

    result = json.loads(response.json()['choices'][0]['message']['content'])
    valid_ids = {m['id'] for m in matches}

    if result['action'] == 'update_existing' and result['target_id'] not in valid_ids:
        result = {
            'action': 'save_new',
            'target_id': 0,
            'content': content,
            'due_at': due_at.isoformat() if due_at else ''
        }

    result['matches'] = matches
    return result
