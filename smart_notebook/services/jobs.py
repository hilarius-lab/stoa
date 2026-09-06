# Processing job queue service
import hashlib
import json
from datetime import datetime,timedelta

from ..config import TIMEZONE
from ..database import get_db_connection
from ..utils import normalize_event_time
from psycopg.types.json import Jsonb


class ProcessingJobConflictError(Exception):
    pass

def _job_priority(job_type):
    if job_type=='audio_transcription':return 100
    if job_type=='text_processing':return 80
    if job_type=='session_artifacts':return 70
    if job_type.startswith(('maintenance','night_')):return 10
    return 50


def _normalize_required_text(value: str, field_name: str):
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


def _job_from_row(row):
    if row is None:
        return None

    return {
        "id": row[0],
        "job_type": row[1],
        "ingestion_session_id": row[2],
        "chunk_id": row[3],
        "sequence": row[4],
        "status": row[5],
        "payload": row[6],
        "result": row[7],
        "attempts": row[8],
        "available_at": row[9].isoformat(),
        "locked_at": row[10].isoformat() if row[10] is not None else None,
        "locked_by": row[11],
        "started_at": row[12].isoformat() if row[12] is not None else None,
        "completed_at": row[13].isoformat() if row[13] is not None else None,
        "error": row[14],
        "idempotency_key": row[15],
        "created_at": row[16].isoformat(),
        "updated_at": row[17].isoformat(),
        "parked_at": row[18].isoformat() if len(row)>18 and row[18] else None,
        "error_class": row[19] if len(row)>19 else None,
        "night_repair_attempts": row[20] if len(row)>20 else 0,
    }


JOB_SELECT = """
    SELECT
        id, job_type, ingestion_session_id, chunk_id, sequence, status,
        payload, result, attempts, available_at, locked_at, locked_by,
        started_at, completed_at, error, idempotency_key, created_at, updated_at,
        parked_at,error_class,night_repair_attempts
    FROM processing_jobs
"""


def _request_hash(
    job_type,
    ingestion_session_id,
    chunk_id,
    sequence,
    payload,
    available_at
):
    canonical = json.dumps(
        {
            "job_type": job_type,
            "ingestion_session_id": ingestion_session_id,
            "chunk_id": chunk_id,
            "sequence": sequence,
            "payload": payload,
            "available_at": available_at.isoformat() if available_at is not None else None
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def enqueue_processing_job_record(
    job_type: str,
    ingestion_session_id: int | None = None,
    chunk_id: int | None = None,
    sequence: int | None = None,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    available_at: datetime | None = None
):
    job_type = _normalize_required_text(job_type, "job_type")
    payload = payload or {}
    idempotency_key = (
        _normalize_required_text(idempotency_key, "idempotency_key")
        if idempotency_key is not None
        else None
    )
    requested_available_at = (
        normalize_event_time(available_at)
        if available_at is not None
        else None
    )
    effective_available_at = requested_available_at or datetime.now(TIMEZONE)
    request_hash = _request_hash(
        job_type,
        ingestion_session_id,
        chunk_id,
        sequence,
        payload,
        requested_available_at
    )
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        if idempotency_key is not None:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (idempotency_key,)
            )
            existing = connection.execute(
                JOB_SELECT + " WHERE idempotency_key = %s FOR UPDATE",
                (idempotency_key,)
            ).fetchone()
            if existing is not None:
                stored_hash = connection.execute(
                    "SELECT request_hash FROM processing_jobs WHERE id = %s",
                    (existing[0],)
                ).fetchone()[0]
                if stored_hash == request_hash:
                    return _job_from_row(existing)
                raise ProcessingJobConflictError(
                    "idempotency_key already exists with different job data"
                )

        chunk = None
        if chunk_id is not None:
            chunk = connection.execute(
                "SELECT session_id, sequence FROM ingestion_chunks WHERE id = %s",
                (chunk_id,)
            ).fetchone()
            if chunk is None:
                raise ValueError("Ingestion chunk not found")
            if ingestion_session_id is None:
                ingestion_session_id = chunk[0]
            elif ingestion_session_id != chunk[0]:
                raise ValueError("chunk_id does not belong to ingestion_session_id")
            if sequence is None:
                sequence = chunk[1]
            elif sequence != chunk[1]:
                raise ValueError("sequence does not match ingestion chunk")

        reserved_contract_session=False
        if ingestion_session_id is not None:
            session = connection.execute(
                "SELECT id,source_type FROM ingestion_sessions WHERE id = %s",
                (ingestion_session_id,)
            ).fetchone()
            if session is None:
                raise ValueError("Ingestion session not found")
            reserved_contract_session=(session[1] or "").startswith("_contract_test_")

        # Reserved contract-test work is invisible to already-running daemon workers,
        # including processes that have not reloaded the latest Python code. Explicit
        # scoped claims below may still process it immediately and deterministically.
        if reserved_contract_session and requested_available_at is None:
            effective_available_at=now+timedelta(days=36500)

        row = connection.execute(
            """
            INSERT INTO processing_jobs (
                job_type, ingestion_session_id, chunk_id, sequence, status,
                payload, attempts, available_at, idempotency_key, request_hash,
                created_at, updated_at,priority
            )
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, 0, %s, %s, %s, %s, %s,%s)
            RETURNING
                id, job_type, ingestion_session_id, chunk_id, sequence, status,
                payload, result, attempts, available_at, locked_at, locked_by,
                started_at, completed_at, error, idempotency_key, created_at, updated_at
            """,
            (
                job_type,
                ingestion_session_id,
                chunk_id,
                sequence,
                json.dumps(payload),
                effective_available_at,
                idempotency_key,
                request_hash,
                now,
                now,
                _job_priority(job_type)
            )
        ).fetchone()
        connection.commit()

    return _job_from_row(row)


def get_processing_job_record(job_id: int):
    with get_db_connection() as connection:
        row = connection.execute(
            JOB_SELECT + " WHERE id = %s",
            (job_id,)
        ).fetchone()
    return _job_from_row(row)


def list_processing_job_records(status: str | None = None):
    parameters = ()
    where = ""
    if status is not None:
        if status not in {"queued", "running", "done", "failed", "parked", "attention_required"}:
            raise ValueError("Unknown processing job status")
        where = " WHERE status = %s"
        parameters = (status,)

    with get_db_connection() as connection:
        rows = connection.execute(
            JOB_SELECT + where + " ORDER BY created_at ASC, id ASC",
            parameters
        ).fetchall()
    return [_job_from_row(row) for row in rows]


def claim_processing_job_record(worker_id: str, job_type: str | None = None, ingestion_session_id: int | None = None):
    worker_id = _normalize_required_text(worker_id, "worker_id")
    if job_type is not None:
        job_type = _normalize_required_text(job_type, "job_type")
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        row = connection.execute(
            """
            WITH candidate AS (
                SELECT j.id
                FROM processing_jobs j LEFT JOIN ingestion_sessions s ON s.id=j.ingestion_session_id
                WHERE j.status = 'queued'
                  AND (j.available_at <= %s OR %s::bigint IS NOT NULL)
                  AND (%s::text IS NULL OR job_type = %s)
                  AND (%s::bigint IS NULL OR ingestion_session_id = %s)
                  -- Contract tests use a reserved source namespace and always claim
                  -- with an explicit session id. Long-running production workers must
                  -- not race those deterministic jobs or accidentally invoke an LLM.
                  AND (%s::bigint IS NOT NULL OR left(COALESCE(s.source_type,''),15) <> '_contract_test_')
                ORDER BY (j.priority+CASE WHEN s.status='open' THEN 20 ELSE 0 END+
                  LEAST(30,FLOOR(EXTRACT(EPOCH FROM (%s-j.available_at))/300))) DESC,j.available_at ASC,j.id ASC
                FOR UPDATE OF j SKIP LOCKED
                LIMIT 1
            )
            UPDATE processing_jobs AS jobs
            SET status = 'running',
                attempts = jobs.attempts + 1,
                locked_at = %s,
                locked_by = %s,
                started_at = %s,
                completed_at = NULL,
                error = NULL,
                updated_at = %s
            FROM candidate
            WHERE jobs.id = candidate.id
            RETURNING
                jobs.id, jobs.job_type, jobs.ingestion_session_id, jobs.chunk_id,
                jobs.sequence, jobs.status, jobs.payload, jobs.result, jobs.attempts,
                jobs.available_at, jobs.locked_at, jobs.locked_by, jobs.started_at,
                jobs.completed_at, jobs.error, jobs.idempotency_key,
                jobs.created_at, jobs.updated_at
            """,
            (now,ingestion_session_id,job_type,job_type,ingestion_session_id,ingestion_session_id,ingestion_session_id,now,now,worker_id,now,now)
        ).fetchone()
        if row:
            connection.execute("""INSERT INTO processing_job_attempts(job_id,attempt_number,worker_id,phase,started_at)
            VALUES(%s,%s,%s,'running',%s) ON CONFLICT(job_id,attempt_number) DO UPDATE SET worker_id=EXCLUDED.worker_id,phase='running',started_at=EXCLUDED.started_at""",
            (row[0],row[8],worker_id,now))
        connection.commit()

    return _job_from_row(row)


def complete_processing_job_record(job_id: int, worker_id: str, result: dict | None = None):
    worker_id = _normalize_required_text(worker_id, "worker_id")
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        current = connection.execute(
            "SELECT status, locked_by FROM processing_jobs WHERE id = %s FOR UPDATE",
            (job_id,)
        ).fetchone()
        if current is None:
            return None
        if current != ("running", worker_id):
            raise ProcessingJobConflictError(
                "Only the worker that claimed a running job can complete it"
            )
        row = connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'done', result = %s::jsonb, completed_at = %s,
                locked_at = NULL, locked_by = NULL, updated_at = %s
            WHERE id = %s
            RETURNING
                id, job_type, ingestion_session_id, chunk_id, sequence, status,
                payload, result, attempts, available_at, locked_at, locked_by,
                started_at, completed_at, error, idempotency_key, created_at, updated_at
            """,
            (json.dumps(result or {}), now, now, job_id)
        ).fetchone()
        connection.execute("""UPDATE processing_job_attempts SET phase='done',completed_at=%s,
        duration_ms=GREATEST(0,EXTRACT(EPOCH FROM (%s-started_at))*1000)::bigint WHERE job_id=%s AND attempt_number=%s""",
        (now,now,job_id,row[8]))
        connection.commit()
    return _job_from_row(row)


def fail_processing_job_record(job_id: int, worker_id: str, error: str):
    worker_id = _normalize_required_text(worker_id, "worker_id")
    error = _normalize_required_text(error, "error")
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        current = connection.execute(
            "SELECT status, locked_by,attempts,night_repair_attempts FROM processing_jobs WHERE id = %s FOR UPDATE",
            (job_id,)
        ).fetchone()
        if current is None:
            return None
        if current[0:2] != ("running", worker_id):
            raise ProcessingJobConflictError(
                "Only the worker that claimed a running job can fail it"
            )
        error_lower=error.casefold()
        error_class="transient_network" if any(x in error_lower for x in ("timeout","connection","network")) else "processing_error"
        next_status="attention_required" if current[3]>=1 else ("parked" if current[2]>=3 else "failed")
        row = connection.execute(
            """
            UPDATE processing_jobs
            SET status = %s, error = %s, completed_at = %s,parked_at=CASE WHEN %s='parked' THEN %s ELSE parked_at END,
                error_class=%s,locked_at = NULL, locked_by = NULL, updated_at = %s
            WHERE id = %s
            RETURNING
                id, job_type, ingestion_session_id, chunk_id, sequence, status,
                payload, result, attempts, available_at, locked_at, locked_by,
                started_at, completed_at, error, idempotency_key, created_at, updated_at
            """,
            (next_status,error,now,next_status,now,error_class,now,job_id)
        ).fetchone()
        connection.execute("""UPDATE processing_job_attempts SET phase=%s,error_class=%s,error=%s,completed_at=%s,
        duration_ms=GREATEST(0,EXTRACT(EPOCH FROM (%s-started_at))*1000)::bigint WHERE job_id=%s AND attempt_number=%s""",
        (next_status,error_class,error,now,now,job_id,row[8]))
        connection.commit()
    return _job_from_row(row)


def retry_processing_job_record(job_id: int, available_at: datetime | None = None):
    retry_at = normalize_event_time(available_at) if available_at is not None else datetime.now(TIMEZONE)
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        current = connection.execute(
            "SELECT status FROM processing_jobs WHERE id = %s FOR UPDATE",
            (job_id,)
        ).fetchone()
        if current is None:
            return None
        if current[0] != "failed":
            raise ProcessingJobConflictError("Only a failed job can be retried")
        row = connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'queued', available_at = %s, result = NULL,
                error = NULL, started_at = NULL, completed_at = NULL,
                locked_at = NULL, locked_by = NULL, updated_at = %s
            WHERE id = %s
            RETURNING
                id, job_type, ingestion_session_id, chunk_id, sequence, status,
                payload, result, attempts, available_at, locked_at, locked_by,
                started_at, completed_at, error, idempotency_key, created_at, updated_at
            """,
            (retry_at, now, job_id)
        ).fetchone()
        connection.commit()
    return _job_from_row(row)


def queue_parked_jobs_for_night_repair(limit=100):
    now=datetime.now(TIMEZONE);limit=max(1,min(limit,1000))
    with get_db_connection() as connection:
        rows=connection.execute("""WITH candidates AS(SELECT id FROM processing_jobs WHERE status='parked'
        AND night_repair_attempts=0 ORDER BY parked_at,id FOR UPDATE SKIP LOCKED LIMIT %s)
        UPDATE processing_jobs j SET status='queued',available_at=%s,night_repair_attempts=1,error=NULL,
        started_at=NULL,completed_at=NULL,locked_at=NULL,locked_by=NULL,updated_at=%s FROM candidates c WHERE j.id=c.id
        RETURNING j.id""",(limit,now,now)).fetchall();connection.commit()
    return [get_processing_job_record(r[0]) for r in rows]


def get_job_queue_metrics():
    with get_db_connection() as connection:
        statuses={r[0]:r[1] for r in connection.execute("SELECT status,count(*) FROM processing_jobs GROUP BY status").fetchall()}
        types=[{"job_type":r[0],"status":r[1],"count":r[2]} for r in connection.execute("SELECT job_type,status,count(*) FROM processing_jobs GROUP BY job_type,status ORDER BY job_type,status").fetchall()]
        oldest=connection.execute("SELECT min(available_at) FROM processing_jobs WHERE status='queued'").fetchone()[0]
        workers=[{"worker_id":r[0],"worker_kind":r[1],"status":r[2],"current_job_id":r[3],"last_seen_at":r[4].isoformat()}
        for r in connection.execute("SELECT worker_id,worker_kind,status,current_job_id,last_seen_at FROM worker_heartbeats ORDER BY worker_id").fetchall()]
        latency=[{"job_type":r[0],"attempts":r[1],"average_duration_ms":float(r[2] or 0),"max_duration_ms":r[3] or 0}
        for r in connection.execute("SELECT j.job_type,count(*),avg(a.duration_ms),max(a.duration_ms) FROM processing_job_attempts a JOIN processing_jobs j ON j.id=a.job_id WHERE a.completed_at IS NOT NULL GROUP BY j.job_type").fetchall()]
    return {"statuses":statuses,"by_job_type":types,"oldest_queued_at":oldest.isoformat() if oldest else None,"live_attempt_limit":3,"night_repair_limit":1,"workers":workers,"latency":latency}

def record_worker_heartbeat(worker_id,worker_kind,status,current_job_id=None,metadata=None):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        connection.execute("""INSERT INTO worker_heartbeats(worker_id,worker_kind,status,current_job_id,metadata,started_at,last_seen_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(worker_id) DO UPDATE SET worker_kind=EXCLUDED.worker_kind,status=EXCLUDED.status,
        current_job_id=EXCLUDED.current_job_id,metadata=EXCLUDED.metadata,last_seen_at=EXCLUDED.last_seen_at""",
        (worker_id,worker_kind,status,current_job_id,Jsonb(metadata or {}),now,now));connection.commit()
