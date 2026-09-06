"""M8 atomic dashboard and resumable SSE contract regression."""
import asyncio,json
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.routers.client import _dashboard_stream


class FakeRequest:
    def __init__(self,last_event_id=None):
        self.headers={"last-event-id":str(last_event_id)} if last_event_id is not None else {}
    async def is_disconnected(self):return False


async def sse_first(session_id,last_event_id=None):
    response=_dashboard_stream(FakeRequest(last_event_id),session_id)
    iterator=response.body_iterator
    item=await anext(iterator)
    await iterator.aclose()
    return item.decode() if isinstance(item,bytes) else item


def main():
    client=TestClient(app);sid=str(uuid4())
    client.post("/api/client/v1/sessions",json={"client_session_id":sid,"source_type":"m8_dashboard_test"}).raise_for_status()
    client.post(f"/api/client/v1/sessions/{sid}/start").raise_for_status()
    first=client.get(f"/api/client/v1/sessions/{sid}/dashboard");assert first.status_code==200,first.text
    body=first.json();assert body["schema_version"]=="1" and body["mode"]=="live" and body["revision"]>=1
    unchanged=client.get(f"/api/client/v1/sessions/{sid}/dashboard").json()
    assert unchanged["revision"]==body["revision"] and unchanged["generated_at"]==body["generated_at"]
    event=asyncio.run(sse_first(sid,0));assert f"id: {body['revision']}\n" in event and "event: dashboard\n" in event
    data=json.loads(next(line[6:] for line in event.splitlines() if line.startswith("data: ")))
    assert data["revision"]==body["revision"]
    keepalive=asyncio.run(sse_first(sid,body["revision"]));assert keepalive==": keepalive\n\n"
    client.post(f"/api/client/v1/sessions/{sid}/pause").raise_for_status()
    changed=client.get(f"/api/client/v1/sessions/{sid}/dashboard").json()
    assert changed["revision"]==body["revision"]+1 and changed["primary_live_session"]["state"]=="paused"
    client.post(f"/api/client/v1/sessions/{sid}/abort",json={"reason":"dashboard test cleanup"}).raise_for_status()
    print("M8 DASHBOARD CONTRACT TEST: PASS")


if __name__=="__main__":main()
