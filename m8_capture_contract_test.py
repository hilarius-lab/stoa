"""Unified text/audio memo-query interpretation-pipeline regression."""
import atexit
import asyncio
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.capture_intent import deterministic_content_intent
from smart_notebook.services.client_capture import get_capture
from smart_notebook.services.client_sessions import get_client_session
from smart_notebook.services.jobs import claim_processing_job_record,fail_processing_job_record
from smart_notebook.services.recovery import repair_ingestion_session_record
from smart_notebook.services.segmentation import run_text_processing_once
from worker import WORKER_KINDS,run_worker_once


_CLEANUP_CAPTURE_IDS=[]
_CLEANUP_CONVERSATION_IDS=[]
_CLEANUP_SESSION_IDS=[]
_CLEANUP_EVENT_IDS=[]


def _cleanup_test_records():
    """Make assertion failures harmless to the repository's shared database."""
    with get_db_connection() as db:
        for capture_id in _CLEANUP_CAPTURE_IDS:
            db.execute("DELETE FROM client_text_captures WHERE id=%s",(capture_id,))
        for conversation_id in _CLEANUP_CONVERSATION_IDS:
            db.execute("DELETE FROM client_conversations WHERE id=%s",(conversation_id,))
        for session_id in _CLEANUP_SESSION_IDS:
            row=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",(session_id,)).fetchone()
            ingestion_id=row[0] if row else None
            db.execute("DELETE FROM client_dashboard_snapshots WHERE scope_key=%s",(f"session:{session_id}",))
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s",(session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(session_id,))
            if ingestion_id:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
        for event_id in _CLEANUP_EVENT_IDS:
            db.execute("DELETE FROM events WHERE id=%s",(event_id,))
        db.commit()


atexit.register(_cleanup_test_records)


def _run_interpretation_pipeline(ingestion_id,label):
    text=asyncio.run(run_text_processing_once(f"{label}-text","deterministic",ingestion_id))
    assert text["outcome"]=="completed",text
    artifacts=asyncio.run(run_session_artifact_worker_once(f"{label}-artifacts","deterministic",ingestion_id))
    assert artifacts["outcome"]=="completed",artifacts


def _pipeline_shape(ingestion_id):
    with get_db_connection() as db:
        segments=db.execute("""SELECT segment_type,text,status FROM semantic_segments
        WHERE session_id=%s ORDER BY sequence,segment_index""",(ingestion_id,)).fetchall()
        artifacts=db.execute("""SELECT artifact_type,content,status FROM session_artifacts
        WHERE session_id=%s ORDER BY id""",(ingestion_id,)).fetchall()
    return [tuple(row) for row in segments],[tuple(row) for row in artifacts]


def _capture_session(capture_id):
    with get_db_connection() as db:
        row=db.execute("SELECT client_session_id FROM client_text_captures WHERE id=%s",(capture_id,)).fetchone()
    assert row and row[0]
    return get_client_session(row[0])


def main():
    assert deterministic_content_intent("Wie ist der Status von Atlas?")["primary_intent"]=="query"
    assert deterministic_content_intent("Hake Milch auf der Einkaufsliste ab.")["primary_intent"]=="complete"
    assert deterministic_content_intent("Streiche Milch von der Einkaufsliste.")["target_type"]=="list_item"
    assert deterministic_content_intent("Ändere die Aufgabe Steuererklärung.")["primary_intent"]=="change"
    assert deterministic_content_intent("Archiviere die Notiz Urlaubsideen.")["primary_intent"]=="archive"
    assert deterministic_content_intent("Atlas ist ein internes Projekt.")["primary_intent"]=="memo"
    assert deterministic_content_intent("Atlas ist ein internes Projekt. Was weißt du darüber?")["multiple_intents_detected"] is True
    assert {"capture","chat"}.issubset(WORKER_KINDS)
    with patch("worker.run_capture_once",new=AsyncMock(return_value={"outcome":"idle"})) as capture_run:
        asyncio.run(run_worker_once("capture","m8-dispatch"));capture_run.assert_awaited_once_with("production")
    with patch("worker.run_chat_turn_once",new=AsyncMock(return_value={"outcome":"idle"})) as chat_run:
        asyncio.run(run_worker_once("chat","m8-dispatch"));chat_run.assert_awaited_once_with("llm")
    client=TestClient(app);content="Dies ist eine lokale M8-Paritätsnotiz."
    memo_id=uuid4();_CLEANUP_CAPTURE_IDS.append(memo_id)
    with patch("smart_notebook.services.client_capture.CLIENT_TEXT_CAPTURE_SOURCE_TYPE","_contract_test_client_text_capture"):
        memo=client.post("/api/client/v1/captures",json={"client_capture_id":str(memo_id),"mode":"memo","content":content})
    assert memo.status_code==202 and memo.json()["resolved_intent"]=="memo" and memo.json()["status"]=="processing",memo.text
    _CLEANUP_EVENT_IDS.append(memo.json()["event_id"])
    assert client.post("/api/client/v1/captures",json={"client_capture_id":str(memo_id),"mode":"memo","content":content}).json()["id"]==str(memo_id)
    changed=client.post("/api/client/v1/captures",json={"client_capture_id":str(memo_id),"mode":"memo","content":"Anders"})
    assert changed.status_code==409
    memo_session=_capture_session(memo_id);_CLEANUP_SESSION_IDS.append(memo_session["client_session_id"]);memo_internal=memo_session["ingestion_session_id"]
    visible_sessions=client.get("/api/client/v1/sessions?limit=100&offset=0").json()
    assert memo_session["client_session_id"] not in {item["client_session_id"] for item in visible_sessions}
    with get_db_connection() as db:
        chunk_count=db.execute("SELECT count(*) FROM ingestion_chunks WHERE session_id=%s",(memo_internal,)).fetchone()[0]
        job_count=db.execute("SELECT count(*) FROM processing_jobs WHERE ingestion_session_id=%s AND job_type='text_processing'",(memo_internal,)).fetchone()[0]
    assert chunk_count==1 and job_count==1
    _run_interpretation_pipeline(memo_internal,"m8-direct")
    processed=get_capture(memo_id)
    assert processed["status"]=="completed" and processed["result"]=={"resolved_intent":"memo","transcript_text":content},processed

    # Feed the exact same stabilized text through an audio-shaped client
    # session. Both sources must produce the same segments and artifacts.
    audio_id=uuid4();_CLEANUP_SESSION_IDS.append(audio_id)
    created=client.post("/api/client/v1/sessions",json={"client_session_id":str(audio_id),"source_type":"_contract_test_audio_prompt","capture_mode":"memo"})
    assert created.status_code==201;client.post(f"/api/client/v1/sessions/{audio_id}/start").raise_for_status()
    audio_internal=get_client_session(audio_id)["ingestion_session_id"]
    chunk=client.post(f"/api/ingestion-sessions/{audio_internal}/chunks",json={"sequence":1,"client_chunk_id":"m8-audio-parity-text","text":content,"source_start_ms":0,"source_end_ms":3000})
    assert chunk.status_code==200,chunk.text
    repair_ingestion_session_record(audio_internal,dry_run=False)
    client.post(f"/api/client/v1/sessions/{audio_id}/finish",json={"final_sequence":0,"final_source_end_ms":3000}).raise_for_status()
    _run_interpretation_pipeline(audio_internal,"m8-audio")
    assert get_client_session(audio_id)["capture_result"]==processed["result"]
    assert _pipeline_shape(audio_internal)==_pipeline_shape(memo_internal)

    # A failed common-pipeline job is visible through the capture status, and
    # the ordinary session repair moves it back to processing.
    attention_id=uuid4();_CLEANUP_CAPTURE_IDS.append(attention_id)
    with patch("smart_notebook.services.client_capture.CLIENT_TEXT_CAPTURE_SOURCE_TYPE","_contract_test_client_text_capture"):
        attention=client.post("/api/client/v1/captures",json={"client_capture_id":str(attention_id),"mode":"memo","content":"Statuspfad prüfen."})
    assert attention.status_code==202,attention.text
    _CLEANUP_EVENT_IDS.append(attention.json()["event_id"])
    attention_session=_capture_session(attention_id);_CLEANUP_SESSION_IDS.append(attention_session["client_session_id"]);attention_internal=attention_session["ingestion_session_id"]
    failed_job=claim_processing_job_record("m8-status-failure","text_processing",attention_internal)
    assert failed_job is not None
    fail_processing_job_record(failed_job["id"],"m8-status-failure","simulated text failure")
    attention=client.get(f"/api/client/v1/captures/{attention_id}").json()
    assert attention["status"]=="attention_required" and attention["error"]=="simulated text failure",attention
    repair_ingestion_session_record(attention_internal,dry_run=False)
    assert client.get(f"/api/client/v1/captures/{attention_id}").json()["status"]=="processing"
    _run_interpretation_pipeline(attention_internal,"m8-status-recovered")
    assert get_capture(attention_id)["status"]=="completed"

    query_id=uuid4();_CLEANUP_CAPTURE_IDS.append(query_id)
    with patch("smart_notebook.services.client_capture.CLIENT_TEXT_CAPTURE_SOURCE_TYPE","_contract_test_client_text_capture"):
        query=client.post("/api/client/v1/captures",json={"client_capture_id":str(query_id),"mode":"auto","content":"Wie ist der Status von Atlas?"})
    assert query.status_code==202 and query.json()["resolved_intent"]=="query" and query.json()["status"]=="processing"
    _CLEANUP_EVENT_IDS.append(query.json()["event_id"])
    query_session=_capture_session(query_id);_CLEANUP_SESSION_IDS.append(query_session["client_session_id"]);query_internal=query_session["ingestion_session_id"]
    _run_interpretation_pipeline(query_internal,"m8-query")
    query=get_capture(query_id)
    assert query["status"]=="completed" and query["conversation_id"] and query["turn_id"],query
    assert query["result"]["intent"]["primary_intent"]=="query",query
    _CLEANUP_CONVERSATION_IDS.append(query["conversation_id"])

    # A03 splits independent intents in source order. Only artifacts supported
    # exclusively by memo parts are offered to ordinary knowledge promotion;
    # the mutation is resolved or turned into a clarification without being
    # executed, and the query turn contains only its own span.
    mixed_content="Atlas ist ein internes Projekt. Den Anruf bei Paul habe ich erledigt. Was weißt du über Atlas?"
    mixed_id=uuid4();_CLEANUP_CAPTURE_IDS.append(mixed_id)
    with patch("smart_notebook.services.client_capture.CLIENT_TEXT_CAPTURE_SOURCE_TYPE","_contract_test_client_text_capture"):
        mixed=client.post("/api/client/v1/captures",json={"client_capture_id":str(mixed_id),"mode":"auto","content":mixed_content})
    assert mixed.status_code==202 and mixed.json()["status"]=="processing",mixed.text
    _CLEANUP_EVENT_IDS.append(mixed.json()["event_id"])
    mixed_session=_capture_session(mixed_id);_CLEANUP_SESSION_IDS.append(mixed_session["client_session_id"]);mixed_internal=mixed_session["ingestion_session_id"]
    text=asyncio.run(run_text_processing_once("m8-mixed-text","deterministic",mixed_internal))
    assert text["outcome"]=="completed",text
    with patch("smart_notebook.services.promotion.promote_session_artifacts",new=AsyncMock()) as promote,\
         patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[])):
        artifacts=asyncio.run(run_session_artifact_worker_once("m8-mixed-artifacts","deterministic",mixed_internal))
        assert artifacts["outcome"]=="completed",artifacts
        assert promote.await_count==1
        promoted_ids=promote.await_args.kwargs["artifact_ids"]
    mixed=get_capture(mixed_id)
    assert mixed["status"]=="completed" and mixed["resolved_intent"]=="complete",mixed
    result=mixed["result"]
    assert [part["primary_intent"] for part in result["intents"]]==["memo","complete","query"],result
    assert [part["ordinal"] for part in result["intents"]]==[1,2,3],result
    assert "".join(part["source_text"] for part in result["intents"]).replace(" ","")==mixed_content.replace(" ",""),result
    assert all(mixed_content[part["source_start"]:part["source_end"]]==part["source_text"] for part in result["intents"]),result
    assert all("source_segment_ids" not in part for part in result["intents"]),result
    assert result["interpretation_status"]=="split_completed",result
    assert result["action_status"]=="pending_clarification" and result["actions"]==[],result
    assert len(result["reference_resolutions"])==1 and result["reference_resolutions"][0]["ordinal"]==2,result
    assert all("target_id" not in item and "target_key" not in item for item in result["reference_resolutions"]),result
    assert any(item["input_kind"]=="mutation_intent" and item["classification"]=="targeted"
               for item in result["knowledge_assessments"]),result
    assert all("candidate_refs" not in item for item in result["knowledge_assessments"]),result
    assert result["conversation_id"] and result["turn_id"],result
    _CLEANUP_CONVERSATION_IDS.append(result["conversation_id"])
    with get_db_connection() as db:
        rows=db.execute("""SELECT p.ordinal,p.primary_intent,p.source_start,p.source_end,count(x.segment_id)
        FROM session_intent_parts p JOIN session_intent_part_segments x ON x.part_id=p.id
        WHERE p.session_id=%s GROUP BY p.id ORDER BY p.ordinal""",(mixed_internal,)).fetchall()
        memo_artifact=db.execute("""SELECT a.id FROM session_artifacts a JOIN session_artifact_sources x ON x.artifact_id=a.id
        JOIN semantic_segments s ON s.id=x.segment_id WHERE a.session_id=%s AND s.text=%s""",
        (mixed_internal,"Atlas ist ein internes Projekt.")).fetchone()[0]
        question=db.execute("""SELECT m.content FROM client_conversation_turns t
        JOIN client_conversation_messages m ON m.id=t.user_message_id WHERE t.id=%s""",(result["turn_id"],)).fetchone()[0]
    assert [row[1] for row in rows]==["memo","complete","query"] and all(row[4]>=1 for row in rows),rows
    assert promoted_ids==[memo_artifact],promoted_ids
    assert question=="Was weißt du über Atlas?",question

    # A02 recognizes a natural-language object action after the common
    # interpretation pipeline, persists it, and does not accidentally promote
    # the command as newly asserted knowledge. A06 resolves or asks; A07 executes.
    action_id=uuid4();_CLEANUP_CAPTURE_IDS.append(action_id)
    with patch("smart_notebook.services.client_capture.CLIENT_TEXT_CAPTURE_SOURCE_TYPE","_contract_test_client_text_capture"):
        action=client.post("/api/client/v1/captures",json={"client_capture_id":str(action_id),"mode":"auto","content":"Hake Milch auf der Einkaufsliste ab."})
    assert action.status_code==202 and action.json()["status"]=="processing",action.text
    _CLEANUP_EVENT_IDS.append(action.json()["event_id"])
    action_session=_capture_session(action_id);_CLEANUP_SESSION_IDS.append(action_session["client_session_id"]);action_internal=action_session["ingestion_session_id"]
    text=asyncio.run(run_text_processing_once("m8-action-text","deterministic",action_internal))
    assert text["outcome"]=="completed",text
    with patch("smart_notebook.services.promotion.promote_session_artifacts",new=AsyncMock()) as promote,\
         patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[])):
        artifacts=asyncio.run(run_session_artifact_worker_once("m8-action-artifacts","deterministic",action_internal))
        assert artifacts["outcome"]=="completed",artifacts
        promote.assert_not_awaited()
    action=get_capture(action_id)
    assert action["status"]=="completed" and action["resolved_intent"]=="complete",action
    assert action["result"]["action_status"]=="pending_clarification" and action["result"]["actions"]==[],action
    assert len(action["result"]["reference_resolutions"])==1,action
    assert action["result"]["intent"]["target_type"]=="list_item",action
    assert action["result"]["knowledge_assessments"][0]["classification"]=="targeted",action
    with get_db_connection() as db:
        decision=db.execute("SELECT primary_intent,target_type,decision_source FROM session_intent_decisions WHERE session_id=%s",(action_internal,)).fetchone()
    assert tuple(decision)==("complete","list_item","deterministic_test"),decision

    # The same decision stage is reached from an audio-shaped auto session;
    # only STT is represented here by its already stabilized text chunk.
    audio_action_id=uuid4();_CLEANUP_SESSION_IDS.append(audio_action_id)
    created=client.post("/api/client/v1/sessions",json={"client_session_id":str(audio_action_id),"source_type":"_contract_test_audio_auto","capture_mode":"auto"})
    assert created.status_code==201;client.post(f"/api/client/v1/sessions/{audio_action_id}/start").raise_for_status()
    audio_action_internal=get_client_session(audio_action_id)["ingestion_session_id"]
    chunk=client.post(f"/api/ingestion-sessions/{audio_action_internal}/chunks",json={"sequence":1,"client_chunk_id":"m8-audio-auto-action","text":"Archiviere die Notiz Urlaubsideen.","source_start_ms":0,"source_end_ms":2500})
    assert chunk.status_code==200,chunk.text
    repair_ingestion_session_record(audio_action_internal,dry_run=False)
    client.post(f"/api/client/v1/sessions/{audio_action_id}/finish",json={"final_sequence":0,"final_source_end_ms":2500}).raise_for_status()
    text=asyncio.run(run_text_processing_once("m8-audio-action-text","deterministic",audio_action_internal))
    assert text["outcome"]=="completed",text
    with patch("smart_notebook.services.promotion.promote_session_artifacts",new=AsyncMock()) as promote,\
         patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[])):
        artifacts=asyncio.run(run_session_artifact_worker_once("m8-audio-action-artifacts","deterministic",audio_action_internal))
        assert artifacts["outcome"]=="completed",artifacts
        promote.assert_not_awaited()
    audio_action=get_client_session(audio_action_id)
    assert audio_action["state"]=="completed",audio_action
    assert audio_action["capture_result"]["resolved_intent"]=="archive",audio_action
    assert audio_action["capture_result"]["action_status"]=="pending_clarification",audio_action
    assert audio_action["capture_result"]["actions"]==[],audio_action
    assert len(audio_action["capture_result"]["reference_resolutions"])==1,audio_action

    _cleanup_test_records()
    print("M8 CAPTURE CONTRACT TEST: PASS")


if __name__=="__main__":main()
