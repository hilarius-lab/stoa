"""W07: per-step error isolation in run_daily_maintenance() and a real
catch-up boundary for daily consolidation instead of a fixed day start.

Two independent bugs, found while preparing Priority 10 (the pre-alpha
audit) against the current code, are covered here:

1. services/maintenance.py::run_daily_maintenance() called every nightly
   step sequentially with no isolation. An exception in an early step (e.g.
   consolidate_today()) skipped every step after it in that run -- including
   the A11/W06 night-repair mechanisms (retry_attention_required_client_
   sessions_for_night_repair, queue_failed_chat_turns_for_night_repair,
   retry_promotion_errors_for_night_repair,
   retry_stalled_processing_client_sessions_for_night_repair) built earlier
   in this chat's work. Fixed by wrapping every step individually.

2. services/consolidation.py::get_today_unarchived_events() (renamed
   get_pending_consolidation_events()) hard-coded its lower bound to
   00:00 of the call day, so an event left unarchived by a failed or
   skipped night could never be picked up by a later run -- it would
   never again fall inside "today". Fixed by dropping the day-scoped lower
   bound entirely: archived=FALSE is already the authoritative "still
   needs consolidating" marker (the same one the manual
   /api/events/{id}/unarchive endpoint relies on), so the only bound that
   still makes sense is an upper one (`as_of`, defaulting to now()).

Run directly: `.venv/Scripts/python.exe m8_maintenance_error_isolation_test.py`
"""
import atexit
from datetime import datetime, timedelta
from unittest import mock

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services import maintenance
from smart_notebook.services.consolidation import get_pending_consolidation_events

_CLEANUP_EVENT_IDS = []


def _cleanup():
    if not _CLEANUP_EVENT_IDS:
        return
    with get_db_connection() as db:
        db.execute("DELETE FROM events WHERE id = ANY(%s)", (_CLEANUP_EVENT_IDS,))
        db.commit()


atexit.register(_cleanup)


def _insert_event(created_at, archived=False):
    with get_db_connection() as db:
        event_id = db.execute(
            "INSERT INTO events(text, created_at, archived, source) VALUES(%s,%s,%s,'chat') RETURNING id",
            ("m8 W07 catch-up boundary test event", created_at, archived),
        ).fetchone()[0]
        db.commit()
    _CLEANUP_EVENT_IDS.append(event_id)
    return event_id


def _catch_up_boundary():
    now = datetime.now(TIMEZONE)
    old_created_at = now - timedelta(days=10)
    old_event_id = _insert_event(old_created_at)

    # The old lower bound (00:00 of the call day) would have excluded this
    # event outright, forever -- it can never again fall inside "today".
    pending = get_pending_consolidation_events(as_of=now)
    pending_ids = {event["id"] for event in pending}
    assert old_event_id in pending_ids, (old_event_id, pending_ids)

    # The upper bound (`as_of`) still excludes events from after it.
    pending_before_creation = get_pending_consolidation_events(as_of=old_created_at)
    assert old_event_id not in {event["id"] for event in pending_before_creation}

    # Archiving (what a successful consolidation run does) removes it, same
    # as it always did -- archived=FALSE remains the sole "pending" marker.
    with get_db_connection() as db:
        db.execute("UPDATE events SET archived=TRUE WHERE id=%s", (old_event_id,))
        db.commit()
    pending_after_archive = get_pending_consolidation_events(as_of=now)
    assert old_event_id not in {event["id"] for event in pending_after_archive}

    print("W07 CATCH-UP BOUNDARY: PASS")


def _step_isolation():
    # Patch the module-level name maintenance.py actually calls, exactly the
    # way run_daily_maintenance() invokes it (as a bare coroutine call).
    # mock.patch.object auto-detects consolidate_today as a coroutine
    # function and substitutes an AsyncMock; its side_effect must be the
    # exception itself (raised when the resulting coroutine is awaited), not
    # a callable returning one -- a callable's return value would just
    # become the (unawaited, leaked) result instead of being raised.
    with mock.patch.object(maintenance, "consolidate_today",
                            side_effect=RuntimeError("synthetic maintenance step failure")):
        import asyncio
        result = asyncio.run(maintenance.run_daily_maintenance())

    assert "consolidation" in result["failed_steps"], result["failed_steps"]
    # The failed step still contributes a neutral, shape-correct default...
    assert result["consolidation"] == {
        "events_processed": 0, "candidates": [], "results": [], "events_archived": 0,
    }, result["consolidation"]
    # ...and every step declared after the poisoned one in run_daily_maintenance()'s
    # own source order still actually ran, instead of being skipped -- this is
    # exactly the abort-on-first-failure behavior being fixed. audio_retention
    # only has this real shape (deleted_chunk_ids/errors keys) if
    # purge_expired_audio() genuinely executed rather than short-circuiting.
    assert set(result["audio_retention"].keys()) >= {"deleted_count", "deleted_chunk_ids", "errors"}, result["audio_retention"]
    assert "task_lifecycle" in result and "expired_count" in result["task_lifecycle"], result

    print("W07 STEP ISOLATION: PASS")


def main():
    _catch_up_boundary()
    _step_isolation()


if __name__ == "__main__":
    main()
