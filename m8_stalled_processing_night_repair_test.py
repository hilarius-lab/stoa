"""One nightly retry for client_sessions stuck in 'processing' with a fully
done job graph (2026-09-12).

Observed live on session 1390: audio_transcription, text_processing and
session_artifacts for its ingestion_session_id all reached 'done', yet
client_sessions.state stayed 'processing' with last_error=None. Root cause:
settle_client_session_for_ingestion() silently swallows ClientSessionConflict
raised by finalize_client_session_with_knowledge() -- by design, per its own
docstring ("a failed promotion therefore leaves the client session
recoverably in processing"), on the assumption that something else would
retry it later. Nothing does: finish_client_session() explicitly no-ops a
retried `finish` once state is already 'processing', and A11's existing night
repair only ever claims state='attention_required'. Calling
finalize_client_session_with_knowledge() by hand on the real session
completed it immediately with no error, confirming whatever blocked the
original attempt was transient -- but nothing would ever have tried again on
its own.

Fixed with claim_stalled_processing_client_sessions_for_night_repair() /
retry_stalled_processing_client_sessions_for_night_repair() in
services/client_sessions.py, wired into run_daily_maintenance() next to the
existing attention_required repair. A claim still stuck in 'processing' after
its one attempt is promoted to attention_required with night_repair_attempts
reset to 0 -- a hand-off to the existing attention_required repair for one
further, independent try, rather than a second silent dead end.

This drives a real capture to `completed`, then forces two distinct stalled
scenarios: one that resolves on retry (the transient case actually observed),
and one made permanently stuck (upload_complete forced false forever) to
prove the escalation path this file's second half exists for.
"""
import asyncio
import atexit
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import CLIENT_OPERATOR_TOKEN
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.client_sessions import (
    claim_stalled_processing_client_sessions_for_night_repair,
    get_client_session,
    retry_stalled_processing_client_sessions_for_night_repair,
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

# CLIENT_DEVICE_AUTH_REQUIRED is a deployment toggle (this repo's .env has it
# on right now, for testing against the real ESP32), not a test concern --
# the operator token bypasses it the same way any other non-device caller
# would, per app.py's client_device_auth middleware.
_HEADERS = {"Authorization": f"Bearer {CLIENT_OPERATOR_TOKEN}"} if CLIENT_OPERATOR_TOKEN else {}


def _build_completed_session(content):
    """A real capture, driven to `completed` -- same two-step deterministic
    drive as m8_client_session_night_repair_test.py, best effort against a
    possibly-concurrent real worker.py (see that file's docstring)."""
    client = TestClient(app)
    capture_id = uuid4()
    _CLEANUP_CAPTURE_IDS.append(capture_id)
    response = client.post("/api/client/v1/captures",
                            json={"client_capture_id": str(capture_id), "mode": "memo", "content": content},
                            headers=_HEADERS)
    assert response.status_code == 202, response.text
    _CLEANUP_EVENT_IDS.append(response.json()["event_id"])
    with get_db_connection() as db:
        row = db.execute("SELECT client_session_id FROM client_text_captures WHERE id=%s", (capture_id,)).fetchone()
    client_session_id = row[0]
    _CLEANUP_SESSION_IDS.append(client_session_id)
    ingestion_id = get_client_session(client_session_id)["ingestion_session_id"]

    asyncio.run(run_text_processing_once(f"stalled-repair-text-{capture_id}", "deterministic", ingestion_id))
    asyncio.run(run_session_artifact_worker_once(
        f"stalled-repair-artifacts-{capture_id}", "deterministic", ingestion_id))

    item = None
    for _ in range(150):
        item = get_client_session(client_session_id)
        if item["state"] == "completed":
            break
        time.sleep(0.4)
    assert item and item["state"] == "completed", item
    return client_session_id


def _force_stalled_processing(client_session_id, night_repair_attempts=0, minutes_old=30):
    with get_db_connection() as db:
        db.execute("""UPDATE client_sessions SET state='processing',finalized_at=NULL,
        night_repair_attempts=%s,updated_at=now() - make_interval(mins=>%s)
        WHERE client_session_id=%s""", (night_repair_attempts, minutes_old, client_session_id))
        db.commit()


def main():
    # Scenario 1: the transient case actually observed on session 1390 --
    # every job is 'done', nothing is actually wrong, the retry just needs to
    # run once. Reusing an already-`completed` session for this is exact:
    # its whole job graph really is 'done', matching the real bug precisely.
    recoverable = _build_completed_session("Dies ist eine Stall-Reparatur-Testnotiz eins.")
    _force_stalled_processing(recoverable)

    claimed = claim_stalled_processing_client_sessions_for_night_repair(limit=100)
    claimed_ids = {item["client_session_id"] for item in claimed}
    assert recoverable in claimed_ids, (recoverable, claimed_ids)
    with get_db_connection() as db:
        attempts = db.execute("SELECT night_repair_attempts FROM client_sessions WHERE client_session_id=%s",
                              (recoverable,)).fetchone()[0]
    assert attempts == 1, attempts

    # One-shot guard: an immediate second claim must not reclaim it.
    second_claim = claim_stalled_processing_client_sessions_for_night_repair(limit=100)
    assert recoverable not in {item["client_session_id"] for item in second_claim}

    # A session updated moments ago must not be claimed even with a fully done
    # job graph -- its own completion hook may still be about to call settle().
    _force_stalled_processing(recoverable, minutes_old=1)
    fresh_claim = claim_stalled_processing_client_sessions_for_night_repair(limit=100)
    assert recoverable not in {item["client_session_id"] for item in fresh_claim}

    # Reset to re-test through the combined claim+retry entry point maintenance.py
    # actually calls; the isolated claim() above already spent this row's guard.
    _force_stalled_processing(recoverable)
    results = asyncio.run(retry_stalled_processing_client_sessions_for_night_repair(limit=100, mode="deterministic"))
    matching = [r for r in results if r["client_session_id"] == recoverable]
    assert len(matching) == 1, results
    assert matching[0]["state"] == "completed", matching

    # Scenario 2: genuinely, persistently stuck -- force upload_complete to
    # stay false forever, so finalize_client_session_with_knowledge() keeps
    # raising ClientSessionConflict no matter how many times it is retried.
    # Must be promoted to attention_required, not silently reclaimed forever.
    stuck = _build_completed_session("Dies ist eine Stall-Reparatur-Testnotiz zwei.")
    with get_db_connection() as db:
        db.execute("UPDATE client_sessions SET expected_final_sequence=expected_final_sequence+1 WHERE client_session_id=%s",
                   (stuck,))
        db.commit()
    _force_stalled_processing(stuck)
    escalation_results = asyncio.run(
        retry_stalled_processing_client_sessions_for_night_repair(limit=100, mode="deterministic"))
    matching = [r for r in escalation_results if r["client_session_id"] == stuck]
    assert len(matching) == 1, escalation_results
    assert matching[0]["state"] == "attention_required", matching

    after = get_client_session(stuck)
    assert after["state"] == "attention_required", after
    assert after["last_error"], after

    with get_db_connection() as db:
        attempts, error = db.execute(
            "SELECT night_repair_attempts,last_error FROM client_sessions WHERE client_session_id=%s",
            (stuck,)).fetchone()
    # Reset to 0: a genuine hand-off to the existing attention_required night
    # repair, which owns its own independent one-shot guard from here.
    assert attempts == 0, attempts
    assert error, error

    print("STALLED PROCESSING NIGHT REPAIR: PASS")


if __name__ == "__main__":
    main()
