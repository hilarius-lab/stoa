"""W04 (Haelfte A): claim creation now eagerly triggers the conflict scan.

claims.py::run_changed_conflict_scan() -- the only thing that ever sets a
claim's status to 'disputed' -- previously ran exclusively on a schedule
(maintenance.py's nightly run_daily_maintenance()) or via a manual admin call
(POST /api/maintenance/conflicts/scan). A claim created (or contradicted)
after tonight's scan simply wasn't flagged as disputed until the *next*
night, even though existing guards elsewhere (e.g. note_fact.py's promotion
check, which requires "no open conflict case") already assume that status is
current. This is the narrower "guard before mutations" half of W04; the
"guard before answers" half is blocked on W02 (search_knowledge not knowing
about claims at all yet) and is deliberately deferred.

Fixed by claims.py::_trigger_eager_conflict_scan(), called after
create_claim_record() and after materialize_validated_artifact_claims()
actually creates a new (non-idempotent) claim.

This test creates two claims via the real create_claim_record() path (same
subject/predicate/object_value, opposite polarity -- a deterministic
"negation" conflict per claims.py::_conflict_type) and checks BOTH are
already 'disputed' immediately afterward, without ever calling
run_changed_conflict_scan() or run_daily_maintenance() itself.

Run directly: `.venv/Scripts/python.exe m8_claim_conflict_guard_test.py`
"""
import asyncio
import atexit
from types import SimpleNamespace
from uuid import uuid4

from smart_notebook.database import get_db_connection
from smart_notebook.services.claims import create_claim_record

_CLEANUP_CLAIM_IDS = []


def _cleanup():
    if not _CLEANUP_CLAIM_IDS:
        return
    with get_db_connection() as db:
        case_ids = [r[0] for r in db.execute(
            "SELECT DISTINCT conflict_case_id FROM conflict_case_claims WHERE claim_id=ANY(%s)",
            (_CLEANUP_CLAIM_IDS,),
        ).fetchall()]
        if case_ids:
            db.execute("DELETE FROM conflict_cases WHERE id=ANY(%s)", (case_ids,))
        db.execute("DELETE FROM claims WHERE id=ANY(%s)", (_CLEANUP_CLAIM_IDS,))
        db.commit()


atexit.register(_cleanup)


def _claim_data(subject, predicate, object_value, polarity):
    return SimpleNamespace(
        claim_type="fact", statement=f"{subject} {predicate} {object_value}", subject=subject,
        predicate=predicate, object_value=object_value, polarity=polarity, modality="asserted",
        valid_from=None, valid_until=None, confidence=0.9, source_knowledge_type=None,
        source_knowledge_id=None, derived=False, metadata={},
    )


def main():
    subject = f"m8-w04-workshop-{uuid4().hex[:10]}"

    claim_a = asyncio.run(create_claim_record(_claim_data(subject, "ist_am", "Montag", "positive")))
    _CLEANUP_CLAIM_IDS.append(claim_a["id"])
    assert claim_a["status"] == "active", claim_a

    claim_b = asyncio.run(create_claim_record(_claim_data(subject, "ist_am", "Montag", "negative")))
    _CLEANUP_CLAIM_IDS.append(claim_b["id"])

    with get_db_connection() as db:
        statuses = dict(db.execute(
            "SELECT id,status FROM claims WHERE id=ANY(%s)", (_CLEANUP_CLAIM_IDS,)
        ).fetchall())

    assert statuses[claim_a["id"]] == "disputed", statuses
    assert statuses[claim_b["id"]] == "disputed", statuses

    with get_db_connection() as db:
        case_count = db.execute(
            "SELECT count(*) FROM conflict_case_claims WHERE claim_id=%s", (claim_a["id"],)
        ).fetchone()[0]
    assert case_count == 1, case_count

    print("W04 CLAIM CONFLICT GUARD: PASS")


if __name__ == "__main__":
    main()
