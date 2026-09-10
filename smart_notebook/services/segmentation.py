# Semantic segmentation service and deterministic test worker
import hashlib
import json
import re
from datetime import datetime

import httpx

from ..config import TIMEZONE
from ..database import get_db_connection
from ..prompts import SEMANTIC_SEGMENTATION_SYSTEM_PROMPT
from .jobs import (
    claim_processing_job_record, complete_processing_job_record,
    fail_processing_job_record
)
from .recovery import (
    refresh_session_watermarks, synchronize_processing_step_for_job
)
from .ai_tasks import get_ai_task_profile
from .content_types import SEGMENT_TYPES

DETERMINISTIC_PROCESSOR = "deterministic_test"
CONTEXT_OVERLAP_CHARACTERS = 750
MAX_SEGMENTS_PER_CHUNK = 50
MAX_SEGMENT_TEXT_CHARACTERS = 4000
ALLOWED_SEGMENT_TYPES = SEGMENT_TYPES


class SemanticSegmentConflictError(Exception):
    pass


def _segment_from_row(row):
    if row is None:
        return None
    return {
        "id": row[0],
        "session_id": row[1],
        "chunk_id": row[2],
        "sequence": row[3],
        "segment_index": row[4],
        "segment_type": row[5],
        "text": row[6],
        "confidence": row[7],
        "source_start_ms": row[8],
        "source_end_ms": row[9],
        "context_before": row[10],
        "content_hash": row[11],
        "processor_type": row[12],
        "created_at": row[13].isoformat(),
        "updated_at": row[14].isoformat(),
        "status": row[15],
        "superseded_by_segment_id": row[16]
    }


SEGMENT_SELECT = """
    SELECT
        id, session_id, chunk_id, sequence, segment_index, segment_type,
        text, confidence, source_start_ms, source_end_ms, context_before,
        content_hash, processor_type, created_at, updated_at, status,
        superseded_by_segment_id
    FROM semantic_segments
"""


def get_semantic_segment_record(segment_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
            SEGMENT_SELECT + " WHERE id = %s",
            (segment_id,)
        ).fetchone()
    return _segment_from_row(row)


def list_semantic_segment_records(session_id: int):
    with get_db_connection() as connection:
        session = connection.execute(
            "SELECT id FROM ingestion_sessions WHERE id = %s",
            (session_id,)
        ).fetchone()
        if session is None:
            return None
        rows = connection.execute(
            SEGMENT_SELECT
            + " WHERE session_id = %s ORDER BY sequence ASC, segment_index ASC, id ASC",
            (session_id,)
        ).fetchall()
    return [_segment_from_row(row) for row in rows]


def _load_chunk_with_context(chunk_id: int):
    with get_db_connection() as connection:
        chunk = connection.execute(
            """
            SELECT session_id, sequence, text, source_start_ms, source_end_ms
            FROM ingestion_chunks
            WHERE id = %s
            """,
            (chunk_id,)
        ).fetchone()
        if chunk is None:
            return None
        previous = connection.execute(
            """
            SELECT text
            FROM ingestion_chunks
            WHERE session_id = %s AND sequence < %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (chunk[0], chunk[1])
        ).fetchone()
    context_before = previous[0][-CONTEXT_OVERLAP_CHARACTERS:] if previous else ""
    return {
        "session_id": chunk[0],
        "sequence": chunk[1],
        "text": chunk[2],
        "source_start_ms": chunk[3],
        "source_end_ms": chunk[4],
        "context_before": context_before
    }


def deterministic_segment_text(text: str):
    parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text.strip())
        if part.strip()
    ]
    if not parts and text.strip():
        parts = [text.strip()]
    if len(parts) > MAX_SEGMENTS_PER_CHUNK:
        raise ValueError(
            f"Chunk produces more than {MAX_SEGMENTS_PER_CHUNK} test segments"
        )
    return [
        {
            "segment_index": index,
            "segment_type": "statement",
            "text": part,
            "confidence": 1.0
        }
        for index, part in enumerate(parts, start=1)
    ]


def _text_ends_complete(text: str):
    return re.search(r"[.!?…][\"')\]]*$", text.strip()) is not None


def _normalize_boundary_text(text: str):
    return " ".join(text.casefold().split())


def _supersede_completed_boundary(connection, chunk, inserted_rows, now):
    if not inserted_rows or chunk["sequence"] <= 1:
        return
    previous = connection.execute(
        """
        SELECT segments.id, segments.text
        FROM semantic_segments AS segments
        JOIN ingestion_chunks AS chunks ON chunks.id = segments.chunk_id
        WHERE segments.session_id = %s
          AND chunks.sequence < %s
          AND segments.status = 'provisional'
        ORDER BY chunks.sequence DESC, segments.segment_index DESC
        LIMIT 1
        FOR UPDATE OF segments
        """,
        (chunk["session_id"], chunk["sequence"])
    ).fetchone()
    if previous is None:
        return
    previous_text = _normalize_boundary_text(previous[1])
    completed_text = _normalize_boundary_text(inserted_rows[0][6])
    if (
        previous_text
        and completed_text != previous_text
        and completed_text.startswith(previous_text)
    ):
        connection.execute(
            """
            UPDATE semantic_segments
            SET status = 'superseded', superseded_by_segment_id = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (inserted_rows[0][0], now, previous[0])
        )


def _validate_segment_proposal(proposal):
    if not isinstance(proposal, dict) or not isinstance(proposal.get("segments"), list):
        raise ValueError("LLM response must contain a segments list")
    raw_segments = proposal["segments"]
    if not raw_segments:
        raise ValueError("LLM response contains no semantic segments")
    if len(raw_segments) > MAX_SEGMENTS_PER_CHUNK:
        raise ValueError(
            f"LLM response contains more than {MAX_SEGMENTS_PER_CHUNK} segments"
        )

    validated = []
    for expected_index, segment in enumerate(raw_segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError("Each semantic segment must be an object")
        if segment.get("segment_index") != expected_index:
            raise ValueError("segment_index values must be contiguous and start at 1")
        segment_type = segment.get("segment_type")
        if segment_type not in ALLOWED_SEGMENT_TYPES:
            raise ValueError(f"Unknown semantic segment type: {segment_type}")
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Segment text must not be empty")
        text = text.strip()
        if len(text) > MAX_SEGMENT_TEXT_CHARACTERS:
            raise ValueError(
                f"Segment text exceeds {MAX_SEGMENT_TEXT_CHARACTERS} characters"
            )
        confidence = segment.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Segment confidence must be between 0 and 1")
        validated.append({
            "segment_index": expected_index,
            "segment_type": segment_type,
            "text": text,
            "confidence": float(confidence)
        })
    return validated


async def segment_text_with_llm(text: str, context_before: str):
    profile = get_ai_task_profile("segmentation.semantic")
    schema = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "segment_index": {"type": "integer"},
                        "segment_type": {
                            "type": "string",
                            "enum": sorted(ALLOWED_SEGMENT_TYPES)
                        },
                        "text": {"type": "string"},
                        "confidence": {"type": "number"}
                    },
                    "required": [
                        "segment_index", "segment_type", "text", "confidence"
                    ],
                    "additionalProperties": False
                }
            }
        },
        "required": ["segments"],
        "additionalProperties": False
    }
    user_content = (
        "VORHERIGER KONTEXT (nur zum Verstehen, nicht erneut ausgeben):\n"
        f"{context_before or '[kein vorheriger Kontext]'}\n\n"
        "AKTUELLER CHUNK (diesen Inhalt segmentieren):\n"
        f"{text}"
    )
    payload = {
        "model": profile["model"],
        "messages": [
            {"role": "system", "content": SEMANTIC_SEGMENTATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": profile["temperature"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "smart_notebook_semantic_segments",
                "strict": True,
                "schema": schema
            }
        }
    }
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"], trust_env=False) as client:
        response = await client.post(profile["endpoint"], json=payload)
        if response.is_error:
            raise RuntimeError(
                f"LLM request failed with HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return _validate_segment_proposal(json.loads(content))


def store_semantic_segments_record(
    chunk_id: int,
    segments: list[dict],
    processor_type: str,
    context_before: str = ""
):
    chunk = _load_chunk_with_context(chunk_id)
    if chunk is None:
        raise ValueError("Ingestion chunk not found")
    normalized = []
    for segment in segments:
        text = segment["text"].strip()
        if not text:
            raise ValueError("Segment text must not be empty")
        normalized.append({
            "segment_index": segment["segment_index"],
            "segment_type": segment["segment_type"],
            "text": text,
            "confidence": float(segment["confidence"]),
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()
        })
    indexes = [item["segment_index"] for item in normalized]
    if indexes != list(range(1, len(normalized) + 1)):
        raise ValueError("segment_index values must be contiguous and start at 1")

    with get_db_connection() as connection:
        existing_rows = connection.execute(
            SEGMENT_SELECT
            + " WHERE chunk_id = %s ORDER BY segment_index ASC",
            (chunk_id,)
        ).fetchall()
        existing = [_segment_from_row(row) for row in existing_rows]
        if existing:
            comparable_existing = [
                {
                    "segment_index": item["segment_index"],
                    "segment_type": item["segment_type"],
                    "text": item["text"],
                    "confidence": item["confidence"],
                    "content_hash": item["content_hash"]
                }
                for item in existing
            ]
            if (
                comparable_existing == normalized
                and all(item["processor_type"] == processor_type for item in existing)
            ):
                return existing
            raise SemanticSegmentConflictError(
                "Chunk already has different semantic segments"
            )

        now = datetime.now(TIMEZONE)
        rows = []
        final_segment_is_provisional = not _text_ends_complete(chunk["text"])
        for item in normalized:
            status = (
                "provisional"
                if final_segment_is_provisional
                and item["segment_index"] == len(normalized)
                else "confirmed"
            )
            row = connection.execute(
                """
                INSERT INTO semantic_segments (
                    session_id, chunk_id, sequence, segment_index, segment_type,
                    text, confidence, source_start_ms, source_end_ms,
                    context_before, content_hash, processor_type, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s, %s, %s, %s, %s)
                RETURNING
                    id, session_id, chunk_id, sequence, segment_index, segment_type,
                    text, confidence, source_start_ms, source_end_ms, context_before,
                    content_hash, processor_type, created_at, updated_at, status,
                    superseded_by_segment_id
                """,
                (
                    chunk["session_id"], chunk_id, chunk["sequence"],
                    item["segment_index"], item["segment_type"], item["text"],
                    item["confidence"], context_before, item["content_hash"],
                    processor_type, now, now
                )
            ).fetchone()
            if status == "provisional":
                row = connection.execute(
                    """
                    UPDATE semantic_segments
                    SET status = 'provisional'
                    WHERE id = %s
                    RETURNING
                        id, session_id, chunk_id, sequence, segment_index,
                        segment_type, text, confidence, source_start_ms,
                        source_end_ms, context_before, content_hash,
                        processor_type, created_at, updated_at, status,
                        superseded_by_segment_id
                    """,
                    (row[0],)
                ).fetchone()
            rows.append(row)
        _supersede_completed_boundary(connection, chunk, rows, now)
        connection.commit()
    return [_segment_from_row(row) for row in rows]


async def run_text_processing_once(worker_id: str, mode: str = "llm", ingestion_session_id: int | None = None):
    worker_id = worker_id.strip()
    if not worker_id:
        raise ValueError("worker_id must not be empty")
    if mode not in {"llm", "deterministic"}:
        raise ValueError("mode must be llm or deterministic")
    job = claim_processing_job_record(worker_id, job_type="text_processing", ingestion_session_id=ingestion_session_id)
    if job is None:
        return {"outcome": "idle", "job": None, "segments": []}

    try:
        chunk = _load_chunk_with_context(job["chunk_id"])
        if chunk is None:
            raise ValueError("Ingestion chunk not found")
        if mode == "llm":
            profile = get_ai_task_profile("segmentation.semantic")
            segments = await segment_text_with_llm(
                chunk["text"], chunk["context_before"]
            )
            processor_type = f"{profile['provider']}:{profile['model']}"
        else:
            segments = deterministic_segment_text(chunk["text"])
            processor_type = DETERMINISTIC_PROCESSOR
        stored = store_semantic_segments_record(
            chunk_id=job["chunk_id"],
            segments=segments,
            processor_type=processor_type,
            context_before=chunk["context_before"]
        )
        from .topic_detection import detect_topics_for_segments
        topic_matches=await detect_topics_for_segments(chunk["session_id"],stored)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        failed = fail_processing_job_record(
            job_id=job["id"],
            worker_id=worker_id,
            error=message
        )
        synchronize_processing_step_for_job(job["id"])
        refresh_session_watermarks(job["ingestion_session_id"])
        return {"outcome": "failed", "job": failed, "segments": [], "error": message}

    completed = complete_processing_job_record(
        job_id=job["id"],
        worker_id=worker_id,
        result={
            "processor_type": processor_type,
            "segment_count": len(stored),
            "segment_ids": [segment["id"] for segment in stored],
            "topic_matches":topic_matches
        }
    )
    synchronize_processing_step_for_job(job["id"])
    from .artifacts import enqueue_artifact_processing_for_chunk
    enqueue_artifact_processing_for_chunk(
        session_id=job["ingestion_session_id"],
        chunk_id=job["chunk_id"],
        sequence=job["sequence"]
    )
    refresh_session_watermarks(job["ingestion_session_id"])
    from .client_sessions import settle_client_session_for_ingestion
    await settle_client_session_for_ingestion(job["ingestion_session_id"])
    return {"outcome": "completed", "job": completed, "segments": stored,"topic_matches":topic_matches}
