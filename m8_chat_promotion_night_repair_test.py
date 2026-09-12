"""A11/W06: one nightly retry each for failed chat turns and promotion errors.

The client_sessions.attention_required slice of A11 (m8_client_session_night_repair_test.py)
deliberately left two cases open, both noted in BACKEND_LOGIK.md's A11/W06 rows:

1. A chat turn that lands in client_conversation_turns.status='failed' only ever
   recovers if the client calls the retry endpoint itself -- nothing on the
   backend ever retried it on its own, unlike processing_jobs.parked or
   client_sessions.attention_required.
2. promote_session_artifacts() (services/promotion.py) catches a per-artifact
   exception internally and records it on session_artifacts.promotion_error,
   but never re-raises it -- the owning client_session can still reach
   'completed' with that one artifact permanently stuck, invisible to
   client_sessions.py's own night repair (which only looks at client_sessions
   state, not at individual artifacts).

This exercises both new repair paths: services/client_chat.py::queue_failed_chat_turns_for_night_repair
and services/promotion.py::claim_promotion_error_artifacts_for_night_repair /
retry_promotion_errors_for_night_repair.
"""
import asyncio
import atexit
import time
from datetime import datetime
from uuid import uuid4

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.client_chat import (
    create_conversation,
    get_turn,
    queue_failed_chat_turns_for_night_repair,
    run_chat_turn_once,
)
from smart_notebook.services.promotion import (
    claim_promotion_error_artifacts_for_night_repair,
    promote_session_artifacts,
    retry_promotion_errors_for_night_repair,
)

_CLEANUP_CONVERSATION_IDS = []
_CLEANUP_INGESTION_IDS = []
_CLEANUP_NOTE_IDS = []


def _cleanup():
    with get_db_connection() as db:
        for conversation_id in _CLEANUP_CONVERSATION_IDS:
            db.execute("DELETE FROM client_conversations WHERE id=%s", (conversation_id,))
        for note_id in _CLEANUP_NOTE_IDS:
            db.execute("DELETE FROM knowledge_topic_links WHERE knowledge_type='note' AND knowledge_id=%s", (note_id,))
            db.execute("DELETE FROM claims WHERE source_knowledge_type='note' AND source_knowledge_id=%s", (note_id,))
            db.execute("DELETE FROM notes WHERE id=%s", (note_id,))
        for ingestion_id in _CLEANUP_INGESTION_IDS:
            db.execute("DELETE FROM ingestion_sessions WHERE id=%s", (ingestion_id,))
        db.commit()


atexit.register(_cleanup)


# ---------------------------------------------------------------------------
# Chat turn night repair
# ---------------------------------------------------------------------------

def _new_conversation_with_turn(content):
    result = create_conversation(uuid4(), uuid4(), uuid4(), content)
    conversation_id = result["conversation"]["id"]
    _CLEANUP_CONVERSATION_IDS.append(conversation_id)
    return conversation_id, result["turn"]["id"]


def _force_turn_failed(turn_id, night_repair_attempts=0):
    with get_db_connection() as db:
        db.execute("""UPDATE client_conversation_turns SET status='failed',error='synthetic test failure',
        night_repair_attempts=%s WHERE id=%s""", (night_repair_attempts, turn_id))
        db.commit()


def _chat_turn_night_repair():
    conversation_id, turn_id = _new_conversation_with_turn("Nachtreparatur-Chattest eins")
    _force_turn_failed(turn_id, night_repair_attempts=0)

    repaired = queue_failed_chat_turns_for_night_repair(limit=100)
    repaired_ids = {item["id"] for item in repaired}
    assert turn_id in repaired_ids, (turn_id, repaired_ids)
    turn = get_turn(turn_id)
    assert turn["status"] == "queued", turn
    with get_db_connection() as db:
        attempts = db.execute("SELECT night_repair_attempts FROM client_conversation_turns WHERE id=%s",
                              (turn_id,)).fetchone()[0]
    assert attempts == 1, attempts
    with get_db_connection() as db:
        conversation_status = db.execute("SELECT status FROM client_conversations WHERE id=%s",
                                         (conversation_id,)).fetchone()[0]
    assert conversation_status == "processing", conversation_status

    # The repaired turn is now just an ordinary queued turn -- the existing
    # chat worker (worker.py's "chat" kind) picks it up exactly as it would
    # any other, with no special-casing for how it got there. This suite runs
    # against the same database a real, concurrent `worker.py all` may be
    # running against (no separate test DB) -- see
    # m8_client_session_night_repair_test.py for the same race observed
    # directly there. Our own call is therefore best-effort ("idle" just
    # means a real worker already claimed it); what actually gates success is
    # polling the turn's own state, not this call's return value.
    asyncio.run(run_chat_turn_once(mode="deterministic"))
    turn = None
    for _ in range(50):
        turn = get_turn(turn_id)
        if turn["status"] in ("completed", "failed"):
            break
        asyncio.run(run_chat_turn_once(mode="deterministic"))
        time.sleep(0.2)
    assert turn and turn["status"] == "completed", turn
    with get_db_connection() as db:
        conversation_status = db.execute("SELECT status FROM client_conversations WHERE id=%s",
                                         (conversation_id,)).fetchone()[0]
    assert conversation_status == "open", conversation_status

    # An already-escalated turn (its one attempt already spent) must never be
    # requeued again -- that is what stops a permanently broken turn from
    # being retried forever.
    _, escalated_turn_id = _new_conversation_with_turn("Nachtreparatur-Chattest zwei")
    _force_turn_failed(escalated_turn_id, night_repair_attempts=1)
    repaired_after_escalation = queue_failed_chat_turns_for_night_repair(limit=100)
    assert escalated_turn_id not in {item["id"] for item in repaired_after_escalation}
    still_failed = get_turn(escalated_turn_id)
    assert still_failed["status"] == "failed", still_failed

    print("A11/W06 CHAT TURN NIGHT REPAIR: PASS")


# ---------------------------------------------------------------------------
# Promotion-error night repair
# ---------------------------------------------------------------------------

def _build_confirmed_note_artifact(content):
    """A real, already-promoted 'note' session_artifacts row.

    Deliberately built directly (bare ingestion_sessions row + a confirmed
    session_artifacts row) rather than through the full memo-capture ->
    segmentation -> artifact-worker pipeline: a plain-prose memo does not
    reliably classify into any semantic_segments segment_type in deterministic
    mode, and the repair mechanism under test only cares about
    session_artifacts.promotion_error / promoted_at, not about how the row
    was originally produced -- the same reasoning
    m8_client_session_night_repair_test.py applies to forcing attention_required
    directly instead of reproducing a specific original failure mode.
    """
    now = datetime.now(TIMEZONE)
    with get_db_connection() as db:
        ingestion_id = db.execute("""INSERT INTO ingestion_sessions(source_type,status,started_at,created_at,updated_at)
        VALUES('text','completed',%s,%s,%s) RETURNING id""", (now, now, now)).fetchone()[0]
        _CLEANUP_INGESTION_IDS.append(ingestion_id)
        artifact_id = db.execute("""INSERT INTO session_artifacts(session_id,artifact_type,content,status,confidence,
        origin_key,created_at,updated_at) VALUES(%s,'note',%s,'confirmed',0.9,%s,%s,%s) RETURNING id""",
        (ingestion_id, content, f"night-repair-promo-test:{uuid4()}", now, now)).fetchone()[0]
        db.commit()
    outcome = asyncio.run(promote_session_artifacts(ingestion_id, "deterministic", artifact_ids=[artifact_id]))
    assert len(outcome["promoted"]) == 1 and outcome["deferred"] == [], outcome
    return ingestion_id, artifact_id, outcome["promoted"][0]["knowledge_id"]


def _force_promotion_error(artifact_id, original_note_id, night_repair_attempts=0):
    """Simulate an artifact whose promotion attempt threw before ever recording
    a link -- the exact except-block path in promote_session_artifacts()."""
    with get_db_connection() as db:
        db.execute("DELETE FROM artifact_knowledge_links WHERE artifact_id=%s", (artifact_id,))
        db.execute("""UPDATE session_artifacts SET promoted_knowledge_type=NULL,promoted_knowledge_id=NULL,
        promoted_at=NULL,promotion_error='synthetic test failure',night_repair_attempts=%s WHERE id=%s""",
                   (night_repair_attempts, artifact_id))
        db.commit()
    _CLEANUP_NOTE_IDS.append(original_note_id)


def _promotion_night_repair():
    ingestion_id, artifact_id, original_note_id = _build_confirmed_note_artifact(
        "Dies ist eine Nachtreparatur-Promotionstestnotiz eins.")
    _force_promotion_error(artifact_id, original_note_id, night_repair_attempts=0)

    claimed = claim_promotion_error_artifacts_for_night_repair(limit=100)
    claimed_ids = {row[0] for row in claimed}
    assert artifact_id in claimed_ids, (artifact_id, claimed_ids)
    with get_db_connection() as db:
        attempts = db.execute("SELECT night_repair_attempts FROM session_artifacts WHERE id=%s",
                              (artifact_id,)).fetchone()[0]
    assert attempts == 1, attempts

    # Claiming is idempotent: a second pass before any retry runs must not
    # reclaim the same row.
    second_claim = claim_promotion_error_artifacts_for_night_repair(limit=100)
    assert artifact_id not in {row[0] for row in second_claim}

    # Reset to re-test through the combined claim+retry entry point that
    # maintenance.py actually calls; the isolated claim() above already spent
    # this row's one-shot guard by itself.
    with get_db_connection() as db:
        db.execute("UPDATE session_artifacts SET night_repair_attempts=0 WHERE id=%s", (artifact_id,))
        db.commit()
    results = asyncio.run(retry_promotion_errors_for_night_repair(limit=100, mode="deterministic"))
    matching = [r for r in results if r["session_id"] == ingestion_id]
    assert len(matching) == 1, results
    assert matching[0]["deferred"] == [], matching
    assert len(matching[0]["promoted"]) == 1, matching
    new_note_id = matching[0]["promoted"][0]["knowledge_id"]
    assert new_note_id != original_note_id
    _CLEANUP_NOTE_IDS.append(new_note_id)

    with get_db_connection() as db:
        row = db.execute("""SELECT promotion_error,promoted_at,promoted_knowledge_id FROM session_artifacts
        WHERE id=%s""", (artifact_id,)).fetchone()
    assert row[0] is None, row
    assert row[1] is not None, row
    assert row[2] == new_note_id, row

    # An already-escalated artifact (its one attempt already spent) must
    # never be claimed again.
    ingestion_id_2, artifact_id_2, original_note_id_2 = _build_confirmed_note_artifact(
        "Dies ist eine Nachtreparatur-Promotionstestnotiz zwei.")
    _force_promotion_error(artifact_id_2, original_note_id_2, night_repair_attempts=1)
    claimed_after_escalation = claim_promotion_error_artifacts_for_night_repair(limit=100)
    assert artifact_id_2 not in {row[0] for row in claimed_after_escalation}
    with get_db_connection() as db:
        still_broken = db.execute("SELECT promotion_error,promoted_at FROM session_artifacts WHERE id=%s",
                                  (artifact_id_2,)).fetchone()
    assert still_broken[0] is not None and still_broken[1] is None, still_broken

    print("A11/W06 PROMOTION NIGHT REPAIR: PASS")


def main():
    _chat_turn_night_repair()
    _promotion_night_repair()


if __name__ == "__main__":
    main()
