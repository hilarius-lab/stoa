"""Dashboard/SSE failure must not couple to durable recording uploads."""
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.routers import client as client_router


def main():
    http=TestClient(app,raise_server_exceptions=False);sid=uuid4()
    http.post("/api/client/v1/sessions",json={"client_session_id":str(sid),"source_type":"_contract_test_dashboard_isolation"}).raise_for_status()
    http.post(f"/api/client/v1/sessions/{sid}/start").raise_for_status()
    original=client_router.dashboard_snapshot
    try:
        def unavailable(*args,**kwargs):raise RuntimeError("simulated dashboard outage")
        client_router.dashboard_snapshot=unavailable
        failed=http.get("/api/client/v1/dashboard")
        assert failed.status_code==500 and failed.json()["code"]=="SERVER_ERROR" and failed.json()["retry_class"]=="backoff"
        uploaded=http.post(f"/api/client/v1/sessions/{sid}/audio-chunks",files={"audio":("isolation.m4a",b"durable-isolation-bytes","audio/mp4")},
            data={"sequence":1,"client_chunk_id":"isolation-1","duration_ms":1000,"source_start_ms":0,"source_end_ms":1000})
        assert uploaded.status_code==201 and uploaded.json()["durable_ack"] is True
        finished=http.post(f"/api/client/v1/sessions/{sid}/finish",json={"final_sequence":1,"final_source_end_ms":1000})
        assert finished.status_code==200 and finished.json()["completion_status"]=="processing"
    finally:
        client_router.dashboard_snapshot=original
        http.post(f"/api/client/v1/sessions/{sid}/abort",json={"reason":"isolation test cleanup"})
    print("M8 DASHBOARD ISOLATION TEST: PASS")


if __name__=="__main__":main()
