"""A06 target resolution, clarification, privacy, and no-mutation gate."""
import atexit
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from smart_notebook.app import app as _app  # noqa: F401 - imports apply migrations
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.client_sessions import create_client_session
from smart_notebook.services.knowledge_preflight import ensure_session_knowledge_preflights
from smart_notebook.services.mutation_targets import (
    ensure_session_mutation_target_resolutions,public_mutation_target_resolutions,
    _validate_model_result,
)


_CLIENT_SESSIONS=[]
_TASKS=[]
_IDENTITIES=[]


def _cleanup():
    with get_db_connection() as db:
        for public_id in _IDENTITIES:
            db.execute("DELETE FROM client_entity_identities WHERE public_id=%s",(public_id,))
        for client_session_id in _CLIENT_SESSIONS:
            row=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",
                           (client_session_id,)).fetchone()
            ingestion_id=row[0] if row else None
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s",(client_session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(client_session_id,))
            if ingestion_id:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
        for task_id in _TASKS:db.execute("DELETE FROM tasks WHERE id=%s",(task_id,))
        db.commit()


atexit.register(_cleanup)


def _task(content):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        task_id=db.execute("""INSERT INTO tasks(content,created_at,updated_at,status,archived,urgency,urgency_source)
        VALUES(%s,%s,%s,'open',FALSE,.5,'policy_default') RETURNING id""",(content,now,now)).fetchone()[0]
        db.commit()
    _TASKS.append(task_id)
    return task_id


def _candidate(task_id,content):
    return {"key":f"task:{task_id}","type":"task","id":task_id,"title":None,"content":content,
            "retrieval":{"stage":"exact","scores":{"exact":1.0}},"parent":None}


def _session_with_part(source_text,target_text,context_ref=None,intent="complete",target_type="task"):
    client_session_id=uuid4()
    session=create_client_session(client_session_id,"_a06_contract_test",capture_mode="auto",context_ref=context_ref)
    _CLIENT_SESSIONS.append(client_session_id)
    session_id=session["ingestion_session_id"];now=datetime.now(TIMEZONE);content_hash=uuid4().hex
    with get_db_connection() as db:
        chunk_id=db.execute("""INSERT INTO ingestion_chunks(session_id,sequence,client_chunk_id,text,
        source_start_ms,source_end_ms,content_hash,created_at) VALUES(%s,1,%s,%s,0,2500,%s,%s) RETURNING id""",
        (session_id,f"a06-{uuid4()}",source_text,content_hash,now)).fetchone()[0]
        segment_id=db.execute("""INSERT INTO semantic_segments(session_id,chunk_id,sequence,segment_index,
        segment_type,text,confidence,source_start_ms,source_end_ms,context_before,content_hash,processor_type,status,
        created_at,updated_at) VALUES(%s,%s,1,1,'statement',%s,.96,0,2500,'',%s,'deterministic','confirmed',%s,%s)
        RETURNING id""",(session_id,chunk_id,source_text,content_hash,now,now)).fetchone()[0]
        db.execute("""INSERT INTO session_intent_decisions(session_id,primary_intent,target_type,target_text,
        confidence,multiple_intents_detected,reason_codes,decision_source,created_at,updated_at)
        VALUES(%s,%s,%s,%s,.96,FALSE,'["marks_done"]'::jsonb,'deterministic_test',%s,%s)""",
        (session_id,intent,target_type,target_text,now,now))
        part_id=db.execute("""INSERT INTO session_intent_parts(session_id,ordinal,primary_intent,target_type,
        target_text,source_text,source_start,source_end,confidence,reason_codes,decision_source,created_at)
        VALUES(%s,1,%s,%s,%s,%s,0,%s,.96,'["marks_done"]'::jsonb,'deterministic_test',%s) RETURNING id""",
        (session_id,intent,target_type,target_text,source_text,len(source_text),now)).fetchone()[0]
        db.execute("INSERT INTO session_intent_part_segments(part_id,segment_id) VALUES(%s,%s)",(part_id,segment_id))
        db.commit()
    part={"id":part_id,"session_id":session_id,"ordinal":1,"primary_intent":intent,
          "target_type":target_type,"target_text":target_text,"source_text":source_text,
          "source_start":0,"source_end":len(source_text),"confidence":.96,
          "source_segment_ids":[segment_id]}
    return session_id,part,segment_id


async def _prepare(session_id,part,candidates,mode="deterministic"):
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",
               new=AsyncMock(return_value=candidates)):
        assessments=await ensure_session_knowledge_preflights(session_id,[part],artifact_ids=[],mode=mode)
    assert assessments[0]["classification"]=="targeted",assessments


def _task_state(task_ids):
    with get_db_connection() as db:
        return [tuple(row) for row in db.execute("""SELECT id,content,status,archived,percent_complete
        FROM tasks WHERE id=ANY(%s) ORDER BY id""",(task_ids,)).fetchall()]


def main():
    normalized=_validate_model_result({"status":"resolved","selected_candidate_index":1,"confidence":.98,
        "reason_codes":["no_candidates"]},2)
    assert normalized["reason_codes"]==["model_selection"],normalized

    one_id=_task(f"A06 Atlas-Bericht {uuid4().hex[:8]}")
    two_a=_task(f"A06 Atlas-Entwurf {uuid4().hex[:8]}")
    two_b=_task(f"A06 Atlas-Abschluss {uuid4().hex[:8]}")
    context_id=_task(f"A06 Kontext-Aufgabe {uuid4().hex[:8]}")
    other_id=_task(f"A06 andere Aufgabe {uuid4().hex[:8]}")
    all_task_ids=[one_id,two_a,two_b,context_id,other_id]
    before=_task_state(all_task_ids)

    # A single compatible A05 candidate resolves durably and idempotently,
    # while the public result never exposes internal IDs or candidate keys.
    session_id,part,_=_session_with_part("Hake den Atlas-Bericht ab.","Atlas-Bericht")
    asyncio.run(_prepare(session_id,part,[_candidate(one_id,"Atlas-Bericht")]))
    first=asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"deterministic"))
    again=asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"deterministic"))
    assert first==again and first[0]["status"]=="resolved",first
    assert first[0]["target_type"]=="task" and first[0]["target_id"]==one_id,first
    public=public_mutation_target_resolutions(first)
    assert public==[{"ordinal":1,"intent":"complete","status":"resolved","target_type":"task",
        "confidence":1.0,"candidate_count":1,"clarification_required":False,
        "reason_codes":["single_candidate"]}],public
    assert all("target_id" not in item and "target_key" not in item and "candidate_keys" not in item for item in public)

    # Multiple plausible candidates remain ambiguous and create exactly one
    # implicit question that retains the source segment provenance.
    session_id,part,segment_id=_session_with_part("Hake die Atlas-Aufgabe ab.","Atlas-Aufgabe")
    candidates=[_candidate(two_a,"Atlas-Entwurf"),_candidate(two_b,"Atlas-Abschluss")]
    asyncio.run(_prepare(session_id,part,candidates))
    ambiguous=asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"deterministic"))[0]
    assert ambiguous["status"]=="ambiguous" and ambiguous["target_id"] is None,ambiguous
    with get_db_connection() as db:
        question=db.execute("""SELECT q.question_kind,q.status,x.segment_id FROM session_questions q
        JOIN session_question_sources x ON x.question_id=q.id WHERE q.id=%s""",
        (ambiguous["clarification_question_id"],)).fetchone()
    assert tuple(question)==("implicit","open",segment_id),question
    asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"deterministic"))
    with get_db_connection() as db:
        assert db.execute("SELECT count(*) FROM session_questions WHERE session_id=%s",(session_id,)).fetchone()[0]==1

    # No candidate is unresolved rather than guessed, with a durable question.
    session_id,part,_=_session_with_part("Hake das dort ab.","das dort")
    asyncio.run(_prepare(session_id,part,[]))
    unresolved=asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"deterministic"))[0]
    assert unresolved["status"]=="unresolved" and unresolved["reason_codes"]==["no_candidates"],unresolved
    assert unresolved["clarification_question_id"] is not None

    # A valid explicit public context wins over language-search candidates.
    public_id=uuid4();_IDENTITIES.append(public_id)
    with get_db_connection() as db:
        db.execute("INSERT INTO client_entity_identities(public_id,entity_type,internal_id,created_at) VALUES(%s,'task',%s,%s)",
                   (public_id,context_id,datetime.now(TIMEZONE)));db.commit()
    session_id,part,_=_session_with_part("Das ist erledigt.","das",{"type":"task","id":str(public_id)})
    asyncio.run(_prepare(session_id,part,[_candidate(other_id,"andere Aufgabe")]))
    contextual=asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"deterministic"))[0]
    assert contextual["status"]=="resolved" and contextual["target_id"]==context_id,contextual
    assert contextual["reason_codes"]==["context_reference"]

    # Even a model selection is rejected below the confidence threshold.
    session_id,part,_=_session_with_part("Hake vielleicht den Atlas-Bericht ab.","Atlas-Bericht")
    asyncio.run(_prepare(session_id,part,[_candidate(one_id,"Atlas-Bericht")],mode="llm"))
    weak=({"status":"resolved","selected_candidate_index":1,"confidence":.6,
           "reason_codes":["model_selection"]},"test:model")
    with patch("smart_notebook.services.mutation_targets._resolve_with_llm",new=AsyncMock(return_value=weak)):
        low=asyncio.run(ensure_session_mutation_target_resolutions(session_id,[part],"llm"))[0]
    assert low["status"]=="unresolved" and low["target_id"] is None,low
    assert low["reason_codes"]==["model_selection","low_confidence"],low

    assert _task_state(all_task_ids)==before,"A06 must not execute, complete, archive, or rewrite a target"
    _cleanup()
    print("M8 MUTATION TARGET RESOLUTION TEST: PASS")


if __name__=="__main__":main()
