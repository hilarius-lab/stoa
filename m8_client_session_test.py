"""Deterministic M8 client-session contract and recovery test."""
import atexit
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR
from smart_notebook.database import get_db_connection
from smart_notebook.services.client_dashboard import dashboard_snapshot


_CLEANUP_SESSION_IDS=[]


def _cleanup_test_sessions():
    """Keep a failed run from leaking technical cards into the shared DB."""
    if not _CLEANUP_SESSION_IDS:return
    root=Path(AUDIO_RETENTION_CACHE_DIR).resolve()
    with get_db_connection() as db:
        for session_id in _CLEANUP_SESSION_IDS:
            row=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",(session_id,)).fetchone()
            if not row:continue
            ingestion_id=row[0]
            if ingestion_id:
                keys=[item[0] for item in db.execute("SELECT storage_key FROM audio_chunks WHERE session_id=%s",(ingestion_id,)).fetchall()]
                for key in keys:
                    path=(root/key).resolve()
                    if root in path.parents:path.unlink(missing_ok=True)
            db.execute("DELETE FROM client_dashboard_snapshots WHERE scope_key=%s",(f"session:{session_id}",))
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s",(session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(session_id,))
            if ingestion_id:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
        db.commit()


atexit.register(_cleanup_test_sessions)


def check_error(response,code,status):
    assert response.status_code==status,response.text
    body=response.json();assert body["code"]==code and body["retry_class"] and body["request_id"]


def main():
    client=TestClient(app);sid=str(uuid4())
    _CLEANUP_SESSION_IDS.append(sid)
    create={"client_session_id":sid,"source_type":"_contract_test_client_session","title":"M8 lifecycle",
            "device_metadata":{"model":"untrusted-test-device","app_version":"test"}}
    first=client.post("/api/client/v1/sessions",json=create);assert first.status_code==201,first.text
    assert first.json()["state"]=="created" and "ingestion_session_id" not in first.json()
    duplicate=client.post("/api/client/v1/sessions",json=create);assert duplicate.status_code==201
    assert duplicate.json()["client_session_id"]==sid
    assert client.post(f"/api/client/v1/sessions/{sid}/start").json()["state"]=="recording"
    assert client.post(f"/api/client/v1/sessions/{sid}/pause").json()["state"]=="paused"
    assert client.post(f"/api/client/v1/sessions/{sid}/resume").json()["state"]=="recording"
    dash=client.get(f"/api/client/v1/sessions/{sid}/dashboard");assert dash.status_code==200,dash.text
    assert dash.json()["mode"]=="live" and dash.json()["schema_version"]=="1"
    assert all(len(section["items"])<=10 for section in dash.json()["sections"])
    same_dash=dashboard_snapshot(sid);assert same_dash["revision"]==dash.json()["revision"]

    def upload(sequence,start,end,chunk_id,data=b"deterministic-audio"):
        return client.post(f"/api/client/v1/sessions/{sid}/audio-chunks",
            files={"audio":("chunk.m4a",data,"audio/mp4")},data={"sequence":str(sequence),"client_chunk_id":chunk_id,
            "duration_ms":str(end-start),"source_start_ms":str(start),"source_end_ms":str(end),"codec":"aac-lc",
            "sample_rate_hz":"48000","channels":"1"})

    one=upload(1,0,10000,"m8-1");assert one.status_code==201,one.text
    assert one.json()["durable_ack"] is True and "storage_key" not in one.json()["chunk"]
    same=upload(1,0,10000,"m8-1");assert same.status_code==201
    conflict=upload(1,0,10000,"m8-1",b"different")
    check_error(conflict,"AUDIO_IDENTITY_CONFLICT",409)
    # A pause gap is valid, but overlap with sequence 1 is not.
    overlap=upload(2,9000,19000,"m8-overlap");check_error(overlap,"AUDIO_TIMELINE_OVERLAP",409)
    two=upload(2,15000,25000,"m8-2");assert two.status_code==201,two.text
    rec=client.get(f"/api/client/v1/sessions/{sid}/reconciliation").json()
    assert rec["received_sequences"]==[1,2] and all(chunk["durable_ack"] for chunk in rec["chunks"])
    assert {item["code"] for item in rec["conflicts"]}>={"AUDIO_IDENTITY_CONFLICT","AUDIO_TIMELINE_OVERLAP"}

    finish=client.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":3,"final_source_end_ms":35000})
    assert finish.status_code==200 and finish.json()["session"]["state"]=="draining"
    assert finish.json()["completion_status"]=="uploads_pending"
    assert finish.json()["reconciliation"]["missing_sequences"]==[3]
    beyond=upload(4,35000,45000,"m8-4");check_error(beyond,"UPLOAD_HORIZON_CLOSED",409)
    three=upload(3,25000,35000,"m8-3");assert three.status_code==201,three.text
    finish=client.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":3,"final_source_end_ms":35000})
    assert finish.status_code==200 and finish.json()["session"]["state"]=="processing"
    assert finish.json()["completion_status"]=="processing"
    assert any(item["code"]=="UPLOAD_HORIZON_CLOSED" for item in finish.json()["reconciliation"]["conflicts"])

    with get_db_connection() as db:
        keys=[r[0] for r in db.execute("SELECT storage_key FROM audio_chunks a JOIN client_sessions c ON c.ingestion_session_id=a.session_id WHERE c.client_session_id=%s",(sid,)).fetchall()]
    assert keys and all((Path(AUDIO_RETENTION_CACHE_DIR)/key).exists() for key in keys)
    aborted=client.post(f"/api/client/v1/sessions/{sid}/abort",json={"reason":"contract test cleanup"})
    assert aborted.status_code==200 and aborted.json()["state"]=="aborted"
    assert all(not (Path(AUDIO_RETENTION_CACHE_DIR)/key).exists() for key in keys)
    assert client.post(f"/api/client/v1/sessions/{sid}/abort",json={}).status_code==200
    assert all(item["client_session_id"]!=sid for item in client.get("/api/client/v1/sessions").json())

    # The ESP exposes zero-based wire sequences while the established Android
    # and processing model remains one-based internally. Quick memo and auto
    # captures upload directly from `created`, without the meeting-only start
    # transition. Testing both protects adopted legacy memos and h4-auto.
    for quick_mode in ("memo","auto"):
        esp_sid=str(uuid4())
        _CLEANUP_SESSION_IDS.append(esp_sid)
        esp_create={"client_session_id":esp_sid,"source_type":"esp32_epaper_audio","capture_mode":quick_mode,
                    "device_metadata":{"client":"waveshare-esp32-s3-epaper-3.97","firmware_version":"test",
                                       "sequence_base":0}}
        created=client.post("/api/client/v1/sessions",json=esp_create)
        assert created.status_code==201 and created.json()["state"]=="created",created.text
        assert created.json()["sequence_base"]==0
        esp_chunk_id=str(uuid4())
        esp_upload=client.post(f"/api/client/v1/sessions/{esp_sid}/audio-chunks",
            files={"audio":("segment.m4a",b"esp32-contract-audio","audio/mp4")},
            data={"sequence":"0","client_chunk_id":esp_chunk_id,"duration_ms":"10000",
                  "source_start_ms":"0","source_end_ms":"10000","codec":"aac-lc",
                  "sample_rate_hz":"48000","channels":"1"})
        assert esp_upload.status_code==201,esp_upload.text
        assert esp_upload.json()["chunk"]["sequence"]==0 and esp_upload.json()["durable_ack"] is True
        esp_rec=client.get(f"/api/client/v1/sessions/{esp_sid}/reconciliation")
        assert esp_rec.status_code==200 and esp_rec.json()["received_sequences"]==[0],esp_rec.text
        esp_finish=client.post(f"/api/client/v1/sessions/{esp_sid}/finish",
                               json={"final_sequence":0,"final_source_end_ms":10000})
        assert esp_finish.status_code==200,esp_finish.text
        assert esp_finish.json()["reconciliation"]["upload_complete"] is True
        assert esp_finish.json()["reconciliation"]["expected_final_sequence"]==0
        assert client.post(f"/api/client/v1/sessions/{esp_sid}/abort",
                           json={"reason":"ESP contract test cleanup"}).status_code==200
    home=client.get("/api/client/v1/dashboard");assert home.status_code==200 and home.json()["mode"] in ("live","idle")
    print("M8 CLIENT SESSION TEST: PASS")


if __name__=="__main__":main()
