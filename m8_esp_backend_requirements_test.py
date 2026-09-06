"""Regression gate for backend guarantees consumed by the ESP32 client."""
import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS
from smart_notebook.database import get_db_connection,init_db
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.jobs import enqueue_processing_job_record


def main():
    init_db()
    client=TestClient(app)
    created_ids=[];ingestion_ids=[]
    try:
        sid=str(uuid4());created_ids.append(sid)
        identity={"client_session_id":sid,"source_type":"_esp_backend_requirements",
                  "capture_mode":"meeting","context_ref":{"project":"stable"},
                  "sequence_base":1,
                  "device_metadata":{"firmware_version":"1"}}
        first=client.post("/api/client/v1/sessions",json=identity)
        assert first.status_code==201,first.text
        assert first.json()["sequence_base"]==1
        assert first.json()["local_audio_release_allowed"] is False
        assert first.json()["local_audio_release_at"] is None
        assert client.post("/api/client/v1/sessions",json=identity).json()==first.json()

        metadata_retry={**identity,"device_metadata":{"firmware_version":"2","sequence_base":0}}
        refreshed=client.post("/api/client/v1/sessions",json=metadata_retry)
        assert refreshed.status_code==201,refreshed.text
        assert refreshed.json()["device_metadata"]["firmware_version"]=="2"
        assert "sequence_base" not in refreshed.json()["device_metadata"]
        assert refreshed.json()["sequence_base"]==1
        assert refreshed.json()["updated_at"]==first.json()["updated_at"]
        conflict=client.post("/api/client/v1/sessions",json={**identity,"capture_mode":"memo"})
        assert conflict.status_code==409 and conflict.json()["code"]=="SESSION_ID_CONFLICT",conflict.text
        base_conflict=client.post("/api/client/v1/sessions",json={**identity,"sequence_base":0})
        assert base_conflict.status_code==409 and base_conflict.json()["code"]=="SESSION_ID_CONFLICT",base_conflict.text

        with get_db_connection() as db:
            ingestion_id=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",(sid,)).fetchone()[0]
        ingestion_ids.append(ingestion_id)
        finished=client.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":-1})
        assert finished.status_code==422
        finished=client.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":0})
        assert finished.status_code==200 and finished.json()["session"]["state"]=="processing",finished.text
        assert finished.json()["session"]["local_audio_release_allowed"] is False

        enqueue_processing_job_record("session_artifacts",ingestion_session_id=ingestion_id,
                                      payload={"contract_test":True},
                                      idempotency_key=f"esp-release:{sid}")
        outcome=asyncio.run(run_session_artifact_worker_once("esp-contract-worker","deterministic",ingestion_id))
        assert outcome["outcome"]=="completed",outcome
        completed=client.get(f"/api/client/v1/sessions/{sid}")
        assert completed.status_code==200,completed.text
        body=completed.json()
        assert body["state"]=="completed" and body["capture_result"]=={"resolved_intent":"meeting"}
        assert body["local_audio_release_allowed"] is True and body["local_audio_release_at"]
        released_at=body["local_audio_release_at"]
        repeat=client.post(f"/api/client/v1/sessions/{sid}/finalize")
        assert repeat.status_code==200 and repeat.json()["local_audio_release_at"]==released_at

        # The no-query route retains the Android active-session behavior. A
        # bounded query selects deterministic ESP history, including closed rows.
        assert sid not in {row["client_session_id"] for row in client.get("/api/client/v1/sessions").json()}
        history=client.get("/api/client/v1/sessions?limit=1&offset=0")
        assert history.status_code==200 and len(history.json())==1,history.text
        assert "local_audio_release_allowed" in history.json()[0]
        invalid=client.get("/api/client/v1/sessions?limit=nonsense")
        assert invalid.status_code==200

        capabilities=client.get("/api/client/capabilities")
        assert capabilities.status_code==200
        assert capabilities.json()["features"]["dashboard_sse"] is True
        assert capabilities.json()["transports"]["sse_proxy_buffering"] is False
        assert capabilities.json()["limits"]["dashboard_cache_max_age_seconds"]==CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS
        print("M8 ESP BACKEND REQUIREMENTS TEST: PASS")
    finally:
        with get_db_connection() as db:
            for sid in created_ids:
                db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s",(sid,))
                db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(sid,))
            for ingestion_id in ingestion_ids:
                db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
            db.commit()


if __name__=="__main__":main()
