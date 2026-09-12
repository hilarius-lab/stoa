"""Regression for the real session-1119 finish() crash.

Observed live on 2026-09-11: a client_session that hit `attention_required`
(capture_intent_failed) received a retried ESP `finish` call after the
underlying ingestion pipeline had already advanced the ingestion_sessions row
past 'open' (all the way to 'completed', independently of the stuck client
session). finish_client_session() regressed attention_required back to
'draining' just like it already correctly avoids doing for 'processing'
(see the surrounding comment), then unconditionally called
finish_ingestion_session_record(), which raises ValueError for anything but
'open'/'finished' -- exactly the guard routers/ingestion.py relies on to
report 409 for its own legacy endpoint. That ValueError was never caught
here, so the request 500'd and the session was stranded in 'draining'
forever: the DB write to 'draining' had already committed in its own
transaction before the crash, and nothing ever revisited it.

Fixed with two changes in finish_client_session(): (1) a retried finish on an
already-attention_required session is now a no-op, matching the existing
'processing' guard; (2) the legacy ingestion finish is only called while the
ingestion session is still 'open', so a retry landing after independent
pipeline completion self-heals into 'processing' instead of crashing.
This test drives a real capture through the actual pipeline to `completed`
(so ingestion_sessions.status is genuinely non-'open'), then forces each of
the two now-guarded scenarios and asserts neither one crashes or leaves the
session stuck in 'draining'.
"""
import asyncio
import atexit
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.client_sessions import finish_client_session, get_client_session
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
    """A real capture, driven all the way to `completed` so
    ingestion_sessions.status is genuinely past 'open' -- same two-step
    deterministic drive m8_client_session_night_repair_test.py uses, best
    effort against a possibly-concurrent real worker.py."""
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

    asyncio.run(run_text_processing_once(f"finish-regress-text-{capture_id}", "deterministic", ingestion_id))
    asyncio.run(run_session_artifact_worker_once(
        f"finish-regress-artifacts-{capture_id}", "deterministic", ingestion_id))

    item = None
    for _ in range(150):
        item = get_client_session(client_session_id)
        if item["state"] == "completed":
            break
        time.sleep(0.4)
    assert item and item["state"] == "completed", item
    with get_db_connection() as db:
        status = db.execute("SELECT status FROM ingestion_sessions WHERE id=%s", (ingestion_id,)).fetchone()[0]
    assert status == "completed", status
    return client_session_id


def main():
    session_id = _build_completed_session("Dies ist eine Regressionsnotiz fuer den finish-Absturz.")
    item = get_client_session(session_id)
    final_sequence = item["expected_final_sequence"]
    final_source_end_ms = item["final_source_end_ms"]

    # Scenario 1: exactly session 1119 -- attention_required, ingestion
    # already completed, ESP retries finish. Must be a no-op, not a crash,
    # and must not regress into draining.
    with get_db_connection() as db:
        db.execute("""UPDATE client_sessions SET state='attention_required',
        last_error='synthetic capture_intent_failed' WHERE client_session_id=%s""", (session_id,))
        db.commit()
    result = finish_client_session(session_id, final_sequence, final_source_end_ms)
    assert result["state"] == "attention_required", result

    # Same retry through the actual HTTP endpoint the ESP calls, so a
    # regression here would also show up as the 500 the device actually saw.
    client = TestClient(app)
    response = client.post(f"/api/client/v1/sessions/{session_id}/finish",
                            json={"final_sequence": final_sequence, "final_source_end_ms": final_source_end_ms})
    assert response.status_code == 200, response.text
    assert response.json()["session"]["state"] == "attention_required", response.json()

    # Scenario 2: defense in depth for any other path that reaches 'draining'
    # after the ingestion session already advanced past 'open' -- must
    # self-heal into 'processing' instead of raising the uncaught ValueError
    # finish_ingestion_session_record() raises for a non-open, non-finished
    # ingestion session.
    with get_db_connection() as db:
        db.execute("UPDATE client_sessions SET state='draining' WHERE client_session_id=%s", (session_id,))
        db.commit()
    result = finish_client_session(session_id, final_sequence, final_source_end_ms)
    assert result["state"] == "processing", result

    print("CLIENT SESSION FINISH REGRESSION (session 1119): PASS")


if __name__ == "__main__":
    main()
