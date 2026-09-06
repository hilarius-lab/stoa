"""Unified text/audio memo-query capture contract regression."""
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.database import get_db_connection


def main():
    client=TestClient(app);memo_id=uuid4()
    memo=client.post("/api/client/v1/captures",json={"client_capture_id":str(memo_id),"mode":"memo","content":"Dies ist eine lokale M8-Testnotiz."})
    assert memo.status_code==202 and memo.json()["resolved_intent"]=="memo" and memo.json()["status"]=="queued"
    assert client.post("/api/client/v1/captures",json={"client_capture_id":str(memo_id),"mode":"memo","content":"Dies ist eine lokale M8-Testnotiz."}).json()["id"]==str(memo_id)
    changed=client.post("/api/client/v1/captures",json={"client_capture_id":str(memo_id),"mode":"memo","content":"Anders"})
    assert changed.status_code==409
    for _ in range(20):
        run=client.post("/api/workers/client-capture/run-once",json={"mode":"deterministic"}).json()
        if run.get("capture",{}).get("id")==str(memo_id):break
    assert run["outcome"]=="completed" and run["capture"]["status"]=="completed"
    note_id=run["capture"]["result"]["knowledge_ref"]["internal_id"]

    query_id=uuid4();query=client.post("/api/client/v1/captures",json={"client_capture_id":str(query_id),"mode":"auto","content":"Wie ist der Status von Atlas?"})
    assert query.status_code==202 and query.json()["resolved_intent"]=="query" and query.json()["conversation_id"]

    session_id=uuid4();created=client.post("/api/client/v1/sessions",json={"client_session_id":str(session_id),"source_type":"audio_prompt","capture_mode":"query"})
    assert created.status_code==201;client.post(f"/api/client/v1/sessions/{session_id}/start").raise_for_status()
    with get_db_connection() as db:internal=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",(session_id,)).fetchone()[0]
    chunk=client.post(f"/api/ingestion-sessions/{internal}/chunks",json={"sequence":1,"client_chunk_id":"m8-audio-query-text","text":"Welche Frist gilt für Projekt Atlas?","source_start_ms":0,"source_end_ms":3000})
    assert chunk.status_code==200,chunk.text
    finished=client.post(f"/api/client/v1/sessions/{session_id}/finish",json={"final_sequence":0,"final_source_end_ms":3000});assert finished.status_code==200
    finalized=client.post(f"/api/client/v1/sessions/{session_id}/finalize");assert finalized.status_code==200,finalized.text
    assert finalized.json()["capture_result"]["resolved_intent"]=="query" and finalized.json()["capture_result"]["conversation_id"]

    with get_db_connection() as db:
        db.execute("DELETE FROM client_text_captures WHERE id IN(%s,%s)",(memo_id,query_id))
        db.execute("DELETE FROM knowledge_sources WHERE knowledge_type='note' AND knowledge_id=%s",(note_id,))
        db.execute("DELETE FROM notes WHERE id=%s",(note_id,))
        db.execute("DELETE FROM client_conversations WHERE id IN(%s,%s)",(query.json()["conversation_id"],finalized.json()["capture_result"]["conversation_id"]))
        db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(session_id,));db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(internal,));db.commit()
    print("M8 CAPTURE CONTRACT TEST: PASS")


if __name__=="__main__":main()
