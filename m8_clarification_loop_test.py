"""W05 bound answer, suggestion, correction, continuation, and idempotency gate."""
import asyncio
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from smart_notebook.app import app as _app  # noqa: F401 - applies migrations
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.clarifications import resolve_clarification_answer
from smart_notebook.services.client_dashboard import _ensure_identities,get_dashboard_entity
from smart_notebook.services.client_sessions import create_client_session,_materialize_capture_result
from smart_notebook.services.knowledge_preflight import ensure_session_knowledge_preflights
from smart_notebook.services.mutation_targets import ensure_session_mutation_target_resolutions

from m8_partial_action_test import (_CLIENT_SESSIONS,_candidate,_cleanup,_list,
                                    _mixed_session)


def _question_public(session_id):
    with get_db_connection() as db:
        question_id=db.execute("SELECT id FROM session_questions WHERE session_id=%s ORDER BY id DESC LIMIT 1",
                               (session_id,)).fetchone()[0]
        _ensure_identities(db,"question","session_questions","id=%s",(question_id,));db.commit()
        public_id=db.execute("""SELECT public_id FROM client_entity_identities
        WHERE entity_type='question' AND internal_id=%s""",(question_id,)).fetchone()[0]
    return question_id,public_id


def _answer_session(public_id,text):
    client_id=uuid4()
    child=create_client_session(client_id,"_w05_contract_test",capture_mode="auto",
        context_ref={"type":"clarification","id":str(public_id)},sequence_base=1)
    _CLIENT_SESSIONS.append(client_id)
    with get_db_connection() as db:
        db.execute("""INSERT INTO ingestion_chunks(session_id,sequence,client_chunk_id,text,
        source_start_ms,source_end_ms,content_hash,created_at) VALUES(%s,1,%s,%s,0,1000,%s,%s)""",
        (child["ingestion_session_id"],f"w05-{uuid4()}",text,uuid4().hex,datetime.now(TIMEZONE)))
        db.commit()
    return child


async def _prepare(parts,candidates):
    client_id,session_id,stored=_mixed_session(parts)
    async def search(_query,**_kwargs):return candidates
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=search):
        await ensure_session_knowledge_preflights(session_id,stored,artifact_ids=[],mode="deterministic")
    await ensure_session_mutation_target_resolutions(session_id,stored,"deterministic")
    _materialize_capture_result(client_id)
    return client_id,session_id


async def main_async():
    confirm_list,_=_list(f"W05 Silberwald {uuid4().hex[:8]}")
    confirm_parts=[{"source_text":"Lösche vielleicht die Liste Silberwald.","target_text":"Silberwald",
        "intent":"archive","target_type":"list","confidence":.62}]
    confirm_client,confirm_session=await _prepare(confirm_parts,
        [_candidate("list",confirm_list,"Silberwald")])
    confirm_question,confirm_public=_question_public(confirm_session)
    detail=get_dashboard_entity("question",confirm_public)
    assert detail["action"]["type"]=="submit_capture" and detail["action"]["params"]["content"]=="Ja",detail
    assert detail["action"]["params"]["context_ref"]=={
        "type":"clarification","id":str(confirm_public),"answer_source":"suggested"},detail
    child=_answer_session(confirm_public,"Ja")
    result=await resolve_clarification_answer(child["ingestion_session_id"],
        {"type":"clarification","id":str(confirm_public),"answer_source":"suggested"},"Ja","deterministic")
    assert result["status"]=="completed" and result["action_status"]=="completed",result
    assert await resolve_clarification_answer(child["ingestion_session_id"],
        {"type":"clarification","id":str(confirm_public),"answer_source":"suggested"},"Ja","deterministic")==result
    child_result=_materialize_capture_result(child["client_session_id"])
    assert child_result["resolved_intent"]=="clarification" and child_result["clarification"]==result,child_result
    with get_db_connection() as db:
        assert db.execute("SELECT archived FROM lists WHERE id=%s",(confirm_list,)).fetchone()[0] is True
        assert db.execute("SELECT status,answer_text,answer_source FROM session_questions WHERE id=%s",
                          (confirm_question,)).fetchone()==("answered","Ja","suggested_answer")
        attempts=db.execute("SELECT count(*) FROM clarification_answer_attempts WHERE answer_session_id=%s",
                            (child["ingestion_session_id"],)).fetchone()[0]
    assert attempts==1
    refreshed=_materialize_capture_result(confirm_client)
    assert refreshed["action_status"]=="completed",refreshed

    first,_=_list(f"W05 Frühling {uuid4().hex[:8]}")
    second,_=_list(f"W05 Herbsturlaub {uuid4().hex[:8]}")
    correction_parts=[{"source_text":"Lösche die Urlaubsliste.","target_text":"Urlaubsliste",
        "intent":"archive","target_type":"list","confidence":.97}]
    _correction_client,correction_session=await _prepare(correction_parts,[
        _candidate("list",first,"Frühlingsurlaub"),_candidate("list",second,"Herbsturlaub")])
    _correction_question,correction_public=_question_public(correction_session)
    correction_detail=get_dashboard_entity("question",correction_public)
    assert correction_detail["action"]["type"]=="submit_capture"
    assert "content" not in correction_detail["action"]["params"],correction_detail
    correction_child=_answer_session(correction_public,"Ich meine den Herbsturlaub.")
    corrected=await resolve_clarification_answer(correction_child["ingestion_session_id"],
        {"type":"clarification","id":str(correction_public)},"Ich meine den Herbsturlaub.","deterministic")
    assert corrected["status"]=="completed",corrected
    with get_db_connection() as db:
        states=db.execute("SELECT id,archived FROM lists WHERE id IN(%s,%s) ORDER BY id",(first,second)).fetchall()
    assert dict(states)=={first:False,second:True},states


def main():
    try:asyncio.run(main_async())
    finally:_cleanup()
    print("M8 CLARIFICATION LOOP TEST: PASS")


if __name__=="__main__":main()
