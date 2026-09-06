# Session watermarks and repair service
from datetime import datetime, timedelta

from ..config import TIMEZONE
from ..database import get_db_connection
from .jobs import enqueue_processing_job_record, retry_processing_job_record

TEXT_PROCESSING_STEP = "text_processing"
TEXT_PROCESSING_JOB = "text_processing"


def _contiguous_through(sequences):
    expected = 1
    for sequence in sorted(set(sequences)):
        if sequence < expected:
            continue
        if sequence != expected:
            break
        expected += 1
    return expected - 1


def _iso(value):
    return value.isoformat() if value is not None else None


def _session_exists(connection, session_id):
    return connection.execute(
        "SELECT id FROM ingestion_sessions WHERE id = %s",
        (session_id,)
    ).fetchone() is not None


def _load_session_state(connection, session_id):
    chunks = connection.execute(
        """
        SELECT id, sequence, client_chunk_id
        FROM ingestion_chunks
        WHERE session_id = %s
        ORDER BY sequence ASC, id ASC
        """,
        (session_id,)
    ).fetchall()
    steps = connection.execute(
        """
        SELECT
            steps.id, steps.chunk_id, steps.sequence, steps.step_type,
            steps.status, steps.processing_job_id, steps.attempts,
            steps.last_error, steps.started_at, steps.completed_at,
            jobs.status, jobs.locked_at, jobs.locked_by, jobs.attempts,
            jobs.error
        FROM chunk_processing_steps AS steps
        LEFT JOIN processing_jobs AS jobs ON jobs.id = steps.processing_job_id
        WHERE steps.session_id = %s
        ORDER BY steps.sequence ASC, steps.id ASC
        """,
        (session_id,)
    ).fetchall()
    return chunks, steps


def _calculate_watermarks(chunks, steps):
    received = _contiguous_through([row[1] for row in chunks])
    queued = _contiguous_through([
        row[2] for row in steps
        if row[3] == TEXT_PROCESSING_STEP and row[5] is not None
    ])
    processed = _contiguous_through([
        row[2] for row in steps
        if row[3] == TEXT_PROCESSING_STEP and row[4] == "done"
    ])
    artifacts = _contiguous_through([
        row[2] for row in steps
        if row[3] == "session_artifacts" and row[4] == "done"
    ])
    return received, queued, processed, artifacts


def _store_watermarks(connection, session_id, received, queued, processed, artifacts):
    now = datetime.now(TIMEZONE)
    connection.execute(
        """
        INSERT INTO ingestion_session_watermarks (
            session_id, received_through_sequence, queued_through_sequence,
            processed_through_sequence, artifact_through_sequence, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET received_through_sequence = EXCLUDED.received_through_sequence,
            queued_through_sequence = EXCLUDED.queued_through_sequence,
            processed_through_sequence = EXCLUDED.processed_through_sequence,
            artifact_through_sequence = EXCLUDED.artifact_through_sequence,
            updated_at = EXCLUDED.updated_at
        """,
        (session_id, received, queued, processed, artifacts, now)
    )
    return now


def refresh_session_watermarks(session_id: int):
    with get_db_connection() as connection:
        if not _session_exists(connection, session_id):
            return None
        chunks, steps = _load_session_state(connection, session_id)
        received, queued, processed, artifacts = _calculate_watermarks(chunks, steps)
        updated_at = _store_watermarks(
            connection, session_id, received, queued, processed, artifacts
        )
        connection.commit()
    return {
        "session_id": session_id,
        "received_through_sequence": received,
        "queued_through_sequence": queued,
        "processed_through_sequence": processed,
        "artifact_through_sequence": artifacts,
        "updated_at": updated_at.isoformat()
    }


def get_session_processing_state(session_id: int):
    watermarks = refresh_session_watermarks(session_id)
    if watermarks is None:
        return None

    with get_db_connection() as connection:
        chunks, steps = _load_session_state(connection, session_id)

    chunk_sequences = [row[1] for row in chunks]
    maximum = max(chunk_sequences, default=0)
    present = set(chunk_sequences)
    missing = [sequence for sequence in range(1, maximum + 1) if sequence not in present]

    return {
        "session_id": session_id,
        "watermarks": watermarks,
        "missing_sequences": missing,
        "chunks": [
            {
                "id": row[0],
                "sequence": row[1],
                "client_chunk_id": row[2]
            }
            for row in chunks
        ],
        "processing_steps": [
            {
                "id": row[0],
                "chunk_id": row[1],
                "sequence": row[2],
                "step_type": row[3],
                "status": row[4],
                "processing_job_id": row[5],
                "attempts": row[6],
                "last_error": row[7],
                "started_at": _iso(row[8]),
                "completed_at": _iso(row[9]),
                "job_status": row[10],
                "job_locked_at": _iso(row[11]),
                "job_locked_by": row[12]
            }
            for row in steps
        ]
    }


def _repair_actions(chunks, steps, stale_before):
    step_by_chunk = {
        row[1]: row
        for row in steps
        if row[3] == TEXT_PROCESSING_STEP
    }
    actions = []
    for chunk_id, sequence, _client_chunk_id in chunks:
        step = step_by_chunk.get(chunk_id)
        if step is None:
            actions.append({
                "action": "create_step_and_job",
                "chunk_id": chunk_id,
                "sequence": sequence,
                "step_type": TEXT_PROCESSING_STEP
            })
            continue
        job_id = step[5]
        job_status = step[10]
        if job_id is None or job_status is None:
            actions.append({
                "action": "attach_missing_job",
                "step_id": step[0],
                "chunk_id": chunk_id,
                "sequence": sequence,
                "step_type": TEXT_PROCESSING_STEP
            })
        elif job_status == "failed":
            actions.append({
                "action": "retry_failed_job",
                "step_id": step[0],
                "job_id": job_id,
                "chunk_id": chunk_id,
                "sequence": sequence
            })
        elif (
            job_status == "running"
            and step[11] is not None
            and step[11] < stale_before
        ):
            actions.append({
                "action": "requeue_stale_job",
                "step_id": step[0],
                "job_id": job_id,
                "chunk_id": chunk_id,
                "sequence": sequence,
                "locked_at": step[11].isoformat(),
                "locked_by": step[12]
            })
        elif step[4] != job_status:
            actions.append({
                "action": "synchronize_step_status",
                "step_id": step[0],
                "job_id": job_id,
                "chunk_id": chunk_id,
                "sequence": sequence,
                "from_status": step[4],
                "to_status": job_status
            })
    return actions


def _ensure_step(session_id, chunk_id, sequence):
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row = connection.execute(
            """
            INSERT INTO chunk_processing_steps (
                session_id, chunk_id, sequence, step_type, status,
                attempts, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, 'pending', 0, %s, %s)
            ON CONFLICT (chunk_id, step_type) DO UPDATE
            SET updated_at = chunk_processing_steps.updated_at
            RETURNING id
            """,
            (session_id, chunk_id, sequence, TEXT_PROCESSING_STEP, now, now)
        ).fetchone()
        connection.commit()
    return row[0]


def _attach_job(session_id, step_id, chunk_id, sequence):
    job = enqueue_processing_job_record(
        job_type=TEXT_PROCESSING_JOB,
        ingestion_session_id=session_id,
        chunk_id=chunk_id,
        sequence=sequence,
        payload={"step_type": TEXT_PROCESSING_STEP},
        idempotency_key=f"{TEXT_PROCESSING_STEP}:chunk:{chunk_id}"
    )
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE chunk_processing_steps
            SET processing_job_id = %s, status = %s, attempts = %s,
                last_error = %s, started_at = %s, completed_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                job["id"], job["status"], job["attempts"], job["error"],
                job["started_at"], job["completed_at"], now, step_id
            )
        )
        connection.commit()


def _apply_action(session_id, action):
    if action["action"] == "create_step_and_job":
        step_id = _ensure_step(
            session_id, action["chunk_id"], action["sequence"]
        )
        _attach_job(
            session_id, step_id, action["chunk_id"], action["sequence"]
        )
    elif action["action"] == "attach_missing_job":
        _attach_job(
            session_id, action["step_id"], action["chunk_id"], action["sequence"]
        )
    elif action["action"] == "retry_failed_job":
        retry_processing_job_record(action["job_id"])
        _synchronize_step(action["step_id"], action["job_id"])
    elif action["action"] == "requeue_stale_job":
        now = datetime.now(TIMEZONE)
        with get_db_connection() as connection:
            connection.execute(
                """
                UPDATE processing_jobs
                SET status = 'queued', available_at = %s, locked_at = NULL,
                    locked_by = NULL, started_at = NULL, completed_at = NULL,
                    error = NULL, updated_at = %s
                WHERE id = %s AND status = 'running'
                """,
                (now, now, action["job_id"])
            )
            connection.commit()
        _synchronize_step(action["step_id"], action["job_id"])
    elif action["action"] == "synchronize_step_status":
        _synchronize_step(action["step_id"], action["job_id"])


def _synchronize_step(step_id, job_id):
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE chunk_processing_steps AS steps
            SET status = jobs.status,
                attempts = jobs.attempts,
                last_error = jobs.error,
                started_at = jobs.started_at,
                completed_at = jobs.completed_at,
                updated_at = %s
            FROM processing_jobs AS jobs
            WHERE steps.id = %s AND jobs.id = %s
            """,
            (now, step_id, job_id)
        )
        connection.commit()


def synchronize_processing_step_for_job(job_id: int):
    with get_db_connection() as connection:
        step = connection.execute(
            "SELECT id FROM chunk_processing_steps WHERE processing_job_id = %s",
            (job_id,)
        ).fetchone()
    if step is None:
        return False
    _synchronize_step(step[0], job_id)
    return True


def repair_ingestion_session_record(
    session_id: int,
    dry_run: bool = True,
    stale_after_minutes: int = 15
):
    if stale_after_minutes < 1:
        raise ValueError("stale_after_minutes must be at least 1")
    with get_db_connection() as connection:
        if not _session_exists(connection, session_id):
            return None
        chunks, steps = _load_session_state(connection, session_id)

    sequences = [row[1] for row in chunks]
    maximum = max(sequences, default=0)
    present = set(sequences)
    missing_sequences = [
        sequence for sequence in range(1, maximum + 1)
        if sequence not in present
    ]
    stale_before = datetime.now(TIMEZONE) - timedelta(minutes=stale_after_minutes)
    actions = _repair_actions(chunks, steps, stale_before)

    if not dry_run:
        for action in actions:
            _apply_action(session_id, action)

    watermarks = refresh_session_watermarks(session_id)
    return {
        "session_id": session_id,
        "dry_run": dry_run,
        "missing_sequences": missing_sequences,
        "actions": actions,
        "applied_action_count": 0 if dry_run else len(actions),
        "watermarks": watermarks
    }
