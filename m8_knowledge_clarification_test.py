"""W05 knowledge contradiction, answer binding, audit, and stale-snapshot gate."""
import asyncio
import atexit
from datetime import datetime
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from smart_notebook.app import app as _app  # noqa: F401 - applies migrations
from smart_notebook.config import EMBEDDING_DIMENSIONS,TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.clarifications import resolve_clarification_answer
from smart_notebook.services.client_dashboard import _ensure_identities,get_dashboard_entity
from smart_notebook.services.knowledge_preflight import ensure_artifact_knowledge_preflight
from smart_notebook.services.notes import save_note
from smart_notebook.services.promotion import promote_session_artifacts


_SESSIONS=[]
_NOTES=[]


def _cleanup():
    with get_db_connection() as db:
        replacement_ids=[]
        for session_id in _SESSIONS:
            replacement_ids.extend(int(row[0].split(":",1)[1]) for row in db.execute("""SELECT selected_candidate_key
            FROM knowledge_clarification_resolutions WHERE session_id=%s AND selected_candidate_key LIKE 'note:%%'""",
            (session_id,)).fetchall() if row[0])
        for session_id in _SESSIONS:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(session_id,))
        for note_id in set(_NOTES+replacement_ids):db.execute("DELETE FROM notes WHERE id=%s",(note_id,))
        db.commit()


atexit.register(_cleanup)


def _session(source="_w05_knowledge_test"):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        session_id=db.execute("""INSERT INTO ingestion_sessions(source_type,status,started_at,created_at,updated_at)
        VALUES(%s,'processing',%s,%s,%s) RETURNING id""",(source,now,now,now)).fetchone()[0];db.commit()
    _SESSIONS.append(session_id);return session_id


def _artifact(session_id,content):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        artifact_id=db.execute("""INSERT INTO session_artifacts(session_id,artifact_type,content,status,
        confidence,origin_key,created_at,updated_at) VALUES(%s,'fact',%s,'confirmed',.98,%s,%s,%s) RETURNING id""",
        (session_id,content,f"w05-knowledge:{uuid4()}",now,now)).fetchone()[0];db.commit()
    return artifact_id


def _candidate(note_id,content):
    return {"key":f"note:{note_id}","type":"note","id":note_id,"title":None,"content":content,
            "retrieval":{"stage":"exact","scores":{"exact":1.0}},"parent":None}


async def _prepare(old_text,new_text):
    note_id=save_note(old_text,[0.0]*EMBEDDING_DIMENSIONS);_NOTES.append(note_id)
    session_id=_session();artifact_id=_artifact(session_id,new_text)
    contradiction={"classification":"contradictory","confidence":.98,"related_candidate_indexes":[1],
                   "reason_codes":["conflicts_with_existing","model_assessment"]}
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",
               new=AsyncMock(return_value=[_candidate(note_id,old_text)])),\
         patch("smart_notebook.services.knowledge_preflight._classify_with_llm",
               new=AsyncMock(return_value=(contradiction,"test:model"))):
        await ensure_artifact_knowledge_preflight(artifact_id,"llm")
    promoted=await promote_session_artifacts(session_id,"deterministic",artifact_ids=[artifact_id])
    assert promoted["promoted"]==[] and promoted["deferred"]==[
        {"artifact_id":artifact_id,"reason":"knowledge_clarification_required"}],promoted
    with get_db_connection() as db:
        question_id=db.execute("""SELECT clarification_question_id FROM knowledge_clarification_resolutions
        WHERE artifact_id=%s""",(artifact_id,)).fetchone()[0]
        _ensure_identities(db,"question","session_questions","id=%s",(question_id,));db.commit()
        public_id=db.execute("""SELECT public_id FROM client_entity_identities
        WHERE entity_type='question' AND internal_id=%s""",(question_id,)).fetchone()[0]
    return session_id,artifact_id,note_id,question_id,public_id


def _answer_session():return _session("_w05_knowledge_answer")


async def main_async():
    old=f"Der Projektraum ist blau {uuid4().hex[:6]}."
    new=f"Der Projektraum ist grün {uuid4().hex[:6]}."
    parent,artifact,note,question,public_id=await _prepare(old,new)
    detail=get_dashboard_entity("question",public_id)
    assert detail["action"]["params"]["options"][0]["label"]=="Neue Angabe",detail
    assert detail["action"]["params"]["options"][1]["label"]=="Bisherige Angabe",detail
    answer_session=_answer_session();selected=detail["action"]["params"]["options"][0]["content"]
    result=await resolve_clarification_answer(answer_session,
        {"type":"clarification","id":str(public_id),"answer_source":"suggested"},selected,"deterministic")
    assert result["status"]=="completed",result
    assert await resolve_clarification_answer(answer_session,
        {"type":"clarification","id":str(public_id),"answer_source":"suggested"},selected,"deterministic")==result
    with get_db_connection() as db:
        assert db.execute("SELECT content,archived,archive_reason FROM notes WHERE id=%s",(note,)).fetchone()==(
            old,True,"clarification_superseded")
        replacement_note=db.execute("SELECT promoted_knowledge_id FROM session_artifacts WHERE id=%s",
                                    (artifact,)).fetchone()[0]
        assert db.execute("SELECT content,archived FROM notes WHERE id=%s",(replacement_note,)).fetchone()==(new,False)
        assert db.execute("SELECT promoted_knowledge_type,promoted_knowledge_id FROM session_artifacts WHERE id=%s",
                          (artifact,)).fetchone()==("note",replacement_note)
        resolution=db.execute("""SELECT status,resolution,answer_session_id,before_state,after_state
        FROM knowledge_clarification_resolutions WHERE artifact_id=%s""",(artifact,)).fetchone()
        assert resolution[0:3]==("completed","replace_existing",answer_session),resolution
        assert resolution[3][0]["content"]==old and resolution[4][0]["archived"] is True,resolution
        assert resolution[4][1]["content"]==new and resolution[4][1]["archived"] is False,resolution
        assert db.execute("SELECT status FROM session_questions WHERE id=%s",(question,)).fetchone()[0]=="answered"

    # A free, source-bound answer may provide the exact corrected statement.
    old2=f"Die Werkstatt öffnet montags {uuid4().hex[:6]}."
    new2=f"Die Werkstatt öffnet dienstags {uuid4().hex[:6]}."
    _parent2,artifact2,note2,question2,public2=await _prepare(old2,new2)
    revised=f"Die Werkstatt öffnet mittwochs {uuid4().hex[:6]}."
    answer2=_answer_session()
    corrected=await resolve_clarification_answer(answer2,{"type":"clarification","id":str(public2)},
                                                 revised,"deterministic")
    assert corrected["status"]=="completed",corrected
    with get_db_connection() as db:
        assert db.execute("SELECT content,archived FROM notes WHERE id=%s",(note2,)).fetchone()==(old2,True)
        replacement2=int(db.execute("""SELECT split_part(selected_candidate_key,':',2)::bigint
        FROM knowledge_clarification_resolutions WHERE artifact_id=%s""",(artifact2,)).fetchone()[0])
        assert db.execute("SELECT content,archived FROM notes WHERE id=%s",(replacement2,)).fetchone()==(revised,False)
        assert db.execute("SELECT status FROM session_artifacts WHERE id=%s",(artifact2,)).fetchone()[0]=="dismissed"
        assert db.execute("SELECT resolution FROM knowledge_clarification_resolutions WHERE artifact_id=%s",
                          (artifact2,)).fetchone()[0]=="revised_statement"
        assert db.execute("SELECT status FROM session_questions WHERE id=%s",(question2,)).fetchone()[0]=="answered"

    # The immutable A05 snapshot wins over a stale answer attempt.
    old3=f"Der Schrank steht links {uuid4().hex[:6]}."
    new3=f"Der Schrank steht rechts {uuid4().hex[:6]}."
    _parent3,artifact3,note3,question3,public3=await _prepare(old3,new3)
    externally_changed=f"Der Schrank wurde bereits versetzt {uuid4().hex[:6]}."
    with get_db_connection() as db:
        db.execute("UPDATE notes SET content=%s,updated_at=%s WHERE id=%s",
                   (externally_changed,datetime.now(TIMEZONE),note3));db.commit()
    stale=await resolve_clarification_answer(_answer_session(),{"type":"clarification","id":str(public3)},
                                             "Ja","deterministic")
    assert stale["status"]=="needs_clarification",stale
    with get_db_connection() as db:
        assert db.execute("SELECT content FROM notes WHERE id=%s",(note3,)).fetchone()[0]==externally_changed
        assert db.execute("SELECT status FROM session_questions WHERE id=%s",(question3,)).fetchone()[0]=="open"
        assert db.execute("SELECT promoted_knowledge_id FROM session_artifacts WHERE id=%s",(artifact3,)).fetchone()[0] is None


def main():
    try:asyncio.run(main_async())
    finally:_cleanup()
    print("M8 KNOWLEDGE CLARIFICATION TEST: PASS")


if __name__=="__main__":main()
