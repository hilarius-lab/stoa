"""W02: fact-claims are now findable through search_knowledge().

retrieval.py::search_knowledge() previously only knew about note/task/list/
list_item -- claims (the "fact" knowledge_type) were entirely invisible to
it. This mattered concretely: note_fact.py::promote_eligible_notes_to_facts()
archives the original note once it promotes it to a fact-claim (see its own
docstring/BACKEND_LOGIK.md 11.3), so a promoted-and-archived note could
disappear from chat retrieval entirely -- the fact that superseded it was
never searchable either.

Fixed by adding "fact" as a fifth type across every hybrid-retrieval channel
(exact/vector/fts/trigram), the cache-invalidating _knowledge_version() hash,
and get_knowledge_record()/parse_knowledge_key(). Only claims with
claim_type='fact' AND status='active' are surfaced -- deliberately excluding
'disputed'/'superseded'/'retracted', since there is not yet any chat-side
handling for presenting a disputed fact (that is W04's still-deferred
"guard before answers" half, blocked on this very change landing first).

This test both exercises search_knowledge() directly and makes one real LLM
call through chat.py::ask_llm() to prove a fact-claim actually reaches and is
used by a real chat answer, not just that the query returns a row.

Run directly: `.venv/Scripts/python.exe m8_fact_search_test.py`
"""
import asyncio
import atexit
from types import SimpleNamespace
from uuid import uuid4

from smart_notebook.database import get_db_connection
from smart_notebook.services.chat import ask_llm
from smart_notebook.services.claims import create_claim_record
from smart_notebook.services.events import create_event_record
from smart_notebook.services.retrieval import search_knowledge

_CLEANUP_CLAIM_IDS = []
_CLEANUP_EVENT_IDS = []


def _cleanup():
    with get_db_connection() as db:
        if _CLEANUP_CLAIM_IDS:
            case_ids = [r[0] for r in db.execute(
                "SELECT DISTINCT conflict_case_id FROM conflict_case_claims WHERE claim_id=ANY(%s)",
                (_CLEANUP_CLAIM_IDS,),
            ).fetchall()]
            if case_ids:
                db.execute("DELETE FROM conflict_cases WHERE id=ANY(%s)", (case_ids,))
            db.execute("DELETE FROM claims WHERE id=ANY(%s)", (_CLEANUP_CLAIM_IDS,))
        for event_id in _CLEANUP_EVENT_IDS:
            db.execute("DELETE FROM events WHERE id=%s", (event_id,))
        db.commit()


atexit.register(_cleanup)


def _delete_claims_now(claim_ids):
    """Remove this sub-test's own claims immediately rather than waiting for
    atexit -- real embeddings rate short, similarly-templated synthetic test
    sentences ("X predicate Y") as moderately similar to each other regardless
    of content, so a still-live claim from an earlier sub-test can otherwise
    leak into a later sub-test's semantic search results (observed directly:
    cosine similarity 0.53 between two unrelated synthetic fact statements,
    comfortably clearing KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY=0.30)."""
    with get_db_connection() as db:
        case_ids = [r[0] for r in db.execute(
            "SELECT DISTINCT conflict_case_id FROM conflict_case_claims WHERE claim_id=ANY(%s)",
            (claim_ids,),
        ).fetchall()]
        if case_ids:
            db.execute("DELETE FROM conflict_cases WHERE id=ANY(%s)", (case_ids,))
        db.execute("DELETE FROM claims WHERE id=ANY(%s)", (claim_ids,))
        db.commit()
    for claim_id in claim_ids:
        if claim_id in _CLEANUP_CLAIM_IDS:
            _CLEANUP_CLAIM_IDS.remove(claim_id)


def _fact_data(subject, predicate, object_value, polarity="positive"):
    return SimpleNamespace(
        claim_type="fact", statement=f"{subject} {predicate} {object_value}", subject=subject,
        predicate=predicate, object_value=object_value, polarity=polarity, modality="asserted",
        valid_from=None, valid_until=None, confidence=0.95, source_knowledge_type=None,
        source_knowledge_id=None, derived=False, metadata={},
    )


def _search_finds_fact():
    subject = f"m8-w02-search-{uuid4().hex[:10]}"
    claim = asyncio.run(create_claim_record(_fact_data(subject, "hat_projekt", "Atlas")))
    _CLEANUP_CLAIM_IDS.append(claim["id"])
    assert claim["status"] == "active", claim

    scoped = asyncio.run(search_knowledge(query=subject, types=["fact"]))
    assert len(scoped) == 1 and scoped[0]["type"] == "fact" and scoped[0]["id"] == claim["id"], scoped
    assert "Atlas" in scoped[0]["content"], scoped

    default_types = asyncio.run(search_knowledge(query=subject))
    assert any(r["type"] == "fact" and r["id"] == claim["id"] for r in default_types), default_types

    _delete_claims_now([claim["id"]])
    print("W02 SEARCH FINDS ACTIVE FACT: PASS")


def _disputed_facts_excluded():
    subject = f"m8-w02-disputed-{uuid4().hex[:10]}"
    claim_a = asyncio.run(create_claim_record(_fact_data(subject, "ist_status", "X", "positive")))
    _CLEANUP_CLAIM_IDS.append(claim_a["id"])
    claim_b = asyncio.run(create_claim_record(_fact_data(subject, "ist_status", "X", "negative")))
    _CLEANUP_CLAIM_IDS.append(claim_b["id"])

    with get_db_connection() as db:
        statuses = dict(db.execute(
            "SELECT id,status FROM claims WHERE id=ANY(%s)", (_CLEANUP_CLAIM_IDS[-2:],)
        ).fetchall())
    assert statuses[claim_a["id"]] == "disputed" and statuses[claim_b["id"]] == "disputed", statuses

    results = asyncio.run(search_knowledge(query=subject, types=["fact"]))
    assert results == [], results

    _delete_claims_now([claim_a["id"], claim_b["id"]])
    print("W02 DISPUTED FACTS STAY HIDDEN: PASS")


def _real_chat_answer_uses_a_fact():
    subject = f"m8-w02-chat-{uuid4().hex[:10]}"
    claim = asyncio.run(create_claim_record(_fact_data(subject, "wohnt_in", "Bregenz")))
    _CLEANUP_CLAIM_IDS.append(claim["id"])

    question = f"In welcher Stadt wohnt {subject} laut den gespeicherten Fakten?"
    event = create_event_record(question, source="chat")
    _CLEANUP_EVENT_IDS.append(event["id"])

    answer, debug = asyncio.run(ask_llm(question, event["id"]))
    assert any(r.get("type") == "fact" and r.get("id") == claim["id"] for r in debug["retrieved_knowledge"]), debug["retrieved_knowledge"]
    assert "Bregenz" in answer, answer

    _delete_claims_now([claim["id"]])
    print("W02 REAL CHAT ANSWER USES A FACT: PASS")


def main():
    _search_finds_fact()
    _disputed_facts_excluded()
    _real_chat_answer_uses_a_fact()


if __name__ == "__main__":
    main()
