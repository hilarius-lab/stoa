"""A05 hybrid preflight, classification, persistence, and no-mutation gate."""
import atexit
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from smart_notebook.app import app as _app  # noqa: F401 - imports apply migrations
from smart_notebook.config import EMBEDDING_DIMENSIONS,TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.knowledge_preflight import (
    ensure_artifact_knowledge_preflight,ensure_session_knowledge_preflights,
    get_session_knowledge_preflights,public_knowledge_preflights,
)
from smart_notebook.services.notes import save_note
from smart_notebook.services.promotion import promote_session_artifacts


_SESSIONS=[]
_NOTES=[]


def _cleanup():
    with get_db_connection() as db:
        for session_id in _SESSIONS:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(session_id,))
        for note_id in _NOTES:db.execute("DELETE FROM notes WHERE id=%s",(note_id,))
        db.commit()


atexit.register(_cleanup)


def _session():
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        session_id=db.execute("""INSERT INTO ingestion_sessions(source_type,status,started_at,created_at,updated_at)
        VALUES('_a05_contract_test','processing',%s,%s,%s) RETURNING id""",(now,now,now)).fetchone()[0];db.commit()
    _SESSIONS.append(session_id)
    return session_id


def _artifact(session_id,content,kind="note"):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        artifact_id=db.execute("""INSERT INTO session_artifacts(session_id,artifact_type,content,status,confidence,origin_key,created_at,updated_at)
        VALUES(%s,%s,%s,'confirmed',1,%s,%s,%s) RETURNING id""",
        (session_id,kind,content,f"a05:{uuid4()}",now,now)).fetchone()[0];db.commit()
    return artifact_id


def _candidate(key,content,kind="note",title=None,parent=None):
    return {"key":key,"type":kind,"id":int(key.split(":")[1]),"title":title,"content":content,
            "retrieval":{"stage":"exact","scores":{"exact":1.0}},"parent":parent}


def main():
    session_id=_session()

    # Exact identity is durable and lets promotion reuse the existing object.
    content=f"A05 identische Notiz {uuid4()}"
    note_id=save_note(content,[0.0]*EMBEDDING_DIMENSIONS);_NOTES.append(note_id)
    exact_artifact=_artifact(session_id,content)
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",
               new=AsyncMock(return_value=[_candidate(f"note:{note_id}",content)])) as search:
        exact=asyncio.run(ensure_artifact_knowledge_preflight(exact_artifact,"deterministic"))
        again=asyncio.run(ensure_artifact_knowledge_preflight(exact_artifact,"deterministic"))
    assert search.await_count==1 and exact==again
    assert exact["classification"]=="identical" and exact["related_candidate_keys"]==[f"note:{note_id}"],exact
    promoted=asyncio.run(promote_session_artifacts(session_id,"deterministic",artifact_ids=[exact_artifact]))
    assert promoted["promoted"][0]["knowledge_id"]==note_id and promoted["promoted"][0]["reused_existing"] is True,promoted
    with get_db_connection() as db:
        assert db.execute("SELECT count(*) FROM notes WHERE content=%s",(content,)).fetchone()[0]==1

    # No candidates means new; a related lexical result is complementary in
    # the deterministic oracle. Production uses the structured LLM here.
    new_artifact=_artifact(session_id,f"A05 neuer Inhalt {uuid4()}")
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[])):
        new=asyncio.run(ensure_artifact_knowledge_preflight(new_artifact,"deterministic"))
    assert new["classification"]=="new" and new["candidate_refs"]==[],new

    complementary_artifact=_artifact(session_id,"Atlas nutzt künftig zusätzlich blaue Etiketten.")
    related=_candidate("note:910001","Atlas nutzt Etiketten.")
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[related])):
        complementary=asyncio.run(ensure_artifact_knowledge_preflight(complementary_artifact,"deterministic"))
    assert complementary["classification"]=="complementary",complementary

    contradictory_artifact=_artifact(session_id,"Atlas nutzt ausschließlich rote Etiketten.")
    contradiction={"classification":"contradictory","confidence":.96,"related_candidate_indexes":[1],
                   "reason_codes":["conflicts_with_existing","model_assessment"]}
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[related])),\
         patch("smart_notebook.services.knowledge_preflight._classify_with_llm",
               new=AsyncMock(return_value=(contradiction,"test:model"))):
        contradictory=asyncio.run(ensure_artifact_knowledge_preflight(contradictory_artifact,"llm"))
    assert contradictory["classification"]=="contradictory",contradictory

    # Mutation language is only marked targeted. Candidate IDs remain possible
    # targets; no task is selected, completed, archived, or changed in A05.
    action="Hake die Aufgabe Atlas-Bericht ab."
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        db.execute("""INSERT INTO session_intent_decisions(session_id,primary_intent,target_type,target_text,confidence,
        multiple_intents_detected,reason_codes,decision_source,created_at,updated_at)
        VALUES(%s,'complete','task',%s,0.93,FALSE,'[\"marks_done\"]'::jsonb,'deterministic_test',%s,%s)""",
        (session_id,"Atlas-Bericht",now,now))
        part_id=db.execute("""INSERT INTO session_intent_parts(session_id,ordinal,primary_intent,target_type,target_text,
        source_text,source_start,source_end,confidence,reason_codes,decision_source,created_at)
        VALUES(%s,1,'complete','task',%s,%s,0,%s,0.93,'[\"marks_done\"]'::jsonb,'deterministic_test',%s) RETURNING id""",
        (session_id,"Atlas-Bericht",action,len(action),now)).fetchone()[0]
        task_state=db.execute("SELECT count(*),count(*) FILTER(WHERE status<>'open' OR archived) FROM tasks").fetchone();db.commit()
    task_candidate=_candidate("task:920001","Atlas-Bericht","task")
    part={"id":part_id,"primary_intent":"complete","target_type":"task","target_text":"Atlas-Bericht",
          "source_text":action,"confidence":.93}
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[task_candidate])):
        targeted=asyncio.run(ensure_session_knowledge_preflights(session_id,[part],artifact_ids=[],mode="deterministic"))[0]
    assert targeted["classification"]=="targeted" and targeted["related_candidate_keys"]==["task:920001"],targeted
    with get_db_connection() as db:
        assert db.execute("SELECT count(*),count(*) FILTER(WHERE status<>'open' OR archived) FROM tasks").fetchone()==task_state

    assessments=get_session_knowledge_preflights(session_id)
    assert {item["classification"] for item in assessments}=={"new","identical","complementary","contradictory","targeted"}
    public=public_knowledge_preflights(assessments)
    assert all("candidate_refs" not in item and "related_candidate_keys" not in item for item in public),public
    _cleanup()
    print("M8 KNOWLEDGE PREFLIGHT TEST: PASS")


if __name__=="__main__":main()
