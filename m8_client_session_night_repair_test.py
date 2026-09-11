"""A11: one nightly retry for client_sessions stuck in attention_required.

Unlike processing_jobs.parked (jobs.py::queue_parked_jobs_for_night_repair),
nothing ever retried a client_sessions row left in attention_required by
capture_intent_failed / knowledge_finalization_failed / clarification_answer_failed
-- observed live on session 1119, stuck since 2026-09-11 with the crash it hit
already fixed, because nothing ever called finalize_client_session_with_knowledge
again. This exercises the new repair path end to end, against a real
capture/segmentation/artifact pipeline rather than a synthetic fixture, with
the failure itself forced afterward -- the mechanism being tested is the
retry scheduling, not any specific original failure mode.
"""
import asyncio
import atexit
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.client_sessions import (
    claim_attention_required_client_sessions_for_night_repair,
    get_client_session,
    retry_attention_required_client_sessions_for_night_repair,
)
from smart_notebook.services.segmentation import run_text_processing_once

_CLEANUP_CAPTURE_IDS = []
_CLEANUP_SESSION_IDS = []
_CLEANUP_EVENT_IDS = []


def _cleanup():
    with get_db_connection() as db:
        for capture_id in _CLEANUP_CAPTURE_IDS:
            db.execute("DELETE FROM client_text_captures WHERE id=%s", (capture_id,))
        for session_id in _CLEANUP_SESSION_IDS:
            row = db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",
                              (session_id,)).fetchone()
            ingestion_id = row[0] if row else None
            db.execute("DELETE FROM client_dashboard_snapshots WHERE scope_key=%s", (f"session:{session_id}",))
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s", (session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s", (session_id,))
            if ingestion_id:
                db.execute("DELETE FROM ingestion_sessions WHERE id=%s", (ingestion_id,))
        for event_id in _CLEANUP_EVENT_IDS:
            db.execute("DELETE FROM events WHERE id=%s", (event_id,))
        db.commit()


atexit.register(_cleanup)


def _build_completed_session(content):
    """A real capture, driven to `completed`.

    capture_mode is not load-bearing for what this file tests: the repair
    mechanism only cares that a client_sessions row exists and reaches
    `completed`, then gets forced back into attention_required regardless of
    how it originally got there. `memo` is the mode m8_capture_contract_test.py
    already exercises reliably through this exact two-step pipeline.

    This repository's test suite runs against the same database a real
    `worker.py all` may be running against live (no separate test DB), so a
    background worker can win the race and claim this capture's jobs before
    the deterministic calls below do -- observed directly: a job already
    `running` under a different worker_id moments after posting. Both calls
    are therefore best-effort (their outcome may legitimately be "idle",
    meaning someone else is handling it); what actually gates success is
    polling the session state, not either call's own return value.
    """
    client = TestClient(app)
    capture_id = uuid4()
    _CLEANUP_CAPTURE_IDS.append(capture_id)
    response = client.post("/api/client/v1/captures",
                            json={"client_capture_id": str(capture_id), "mode": "memo", "content": content})
    assert response.status_code == 202, response.text
    _CLEANUP_EVENT_IDS.append(response.json()["event_id"])
    with get_db_connection() as db:
        row = db.execute("SELECT client_session_id FROM client_text_captures WHERE id=%s", (capture_id,)).fetchone()
    client_session_id = row[0]
    _CLEANUP_SESSION_IDS.append(client_session_id)
    ingestion_id = get_client_session(client_session_id)["ingestion_session_id"]

    asyncio.run(run_text_processing_once(f"night-repair-text-{capture_id}", "deterministic", ingestion_id))
    asyncio.run(run_session_artifact_worker_once(
        f"night-repair-artifacts-{capture_id}", "deterministic", ingestion_id))

    # Generous: a concurrent production worker's LLM-mode pipeline (real STT/
    # segmentation/artifact/promotion calls) can take far longer than this
    # process's own deterministic attempt above.
    item = None
    for _ in range(150):
        item = get_client_session(client_session_id)
        if item["state"] == "completed":
            break
        time.sleep(0.4)
    assert item and item["state"] == "completed", item
    return client_session_id


def _force_attention_required(client_session_id, night_repair_attempts=0):
    with get_db_connection() as db:
        db.execute("""UPDATE client_sessions SET state='attention_required',
        last_error='synthetic test failure',night_repair_attempts=%s WHERE client_session_id=%s""",
                   (night_repair_attempts, client_session_id))
        db.commit()


def main():
    # A resolvable case: forced into attention_required despite nothing
    # actually being broken, so the retry succeeds and the session recovers.
    recoverable = _build_completed_session("Dies ist eine Nachtreparatur-Testnotiz eins.")
    _force_attention_required(recoverable, night_repair_attempts=0)

    claimed = claim_attention_required_client_sessions_for_night_repair(limit=100)
    claimed_ids = {item["client_session_id"] for item in claimed}
    assert recoverable in claimed_ids, (recoverable, claimed_ids)
    with get_db_connection() as db:
        attempts = db.execute("SELECT night_repair_attempts FROM client_sessions WHERE client_session_id=%s",
                              (recoverable,)).fetchone()[0]
    assert attempts == 1, attempts

    # Claiming is idempotent: a second pass before any retry runs must not
    # reclaim the same row (it would otherwise reset its one-shot guard).
    second_claim = claim_attention_required_client_sessions_for_night_repair(limit=100)
    assert recoverable not in {item["client_session_id"] for item in second_claim}

    # Reset to re-test the same row through the combined claim+retry entry
    # point that maintenance.py actually calls; the isolated claim() above
    # already spent this row's one-shot guard by itself.
    _force_attention_required(recoverable, night_repair_attempts=0)
    results = asyncio.run(retry_attention_required_client_sessions_for_night_repair(limit=100, mode="deterministic"))
    matching = [r for r in results if r["client_session_id"] == recoverable]
    assert len(matching) == 1, results
    assert matching[0]["state"] == "completed", matching

    after = get_client_session(recoverable)
    assert after["state"] == "completed", after

    # An already-escalated case (its one attempt already spent) must never
    # be claimed again -- that is what stops a permanently broken session
    # from being retried forever.
    escalated = _build_completed_session("Dies ist eine Nachtreparatur-Testnotiz zwei.")
    _force_attention_required(escalated, night_repair_attempts=1)
    claimed_after_escalation = claim_attention_required_client_sessions_for_night_repair(limit=100)
    assert escalated not in {item["client_session_id"] for item in claimed_after_escalation}
    still_attention_required = get_client_session(escalated)
    assert still_attention_required["state"] == "attention_required", still_attention_required

    print("A11 CLIENT SESSION NIGHT REPAIR: PASS")


if __name__ == "__main__":
    main()
