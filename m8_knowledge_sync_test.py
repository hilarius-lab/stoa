"""M8 offline library snapshot/delta/redirect-safe usage contract test."""
from datetime import datetime,timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection


def main():
    client=TestClient(app);now=datetime.now(TIMEZONE);batch_id=uuid4();installation=uuid4()
    with get_db_connection() as db:
        note_id=db.execute("INSERT INTO notes(content,created_at,updated_at,archived) VALUES(%s,%s,%s,FALSE) RETURNING id",("M8 Offline-Sync Ausgangsnotiz",now,now)).fetchone()[0];db.commit()
    libraries=client.get("/api/client/v1/knowledge/libraries");assert libraries.status_code==200,libraries.text
    by_key={x["key"]:x for x in libraries.json()["libraries"]}
    assert by_key["personal"]["sync_mode"]=="full_text" and by_key["personal"]["local_action"]=="retain"
    assert by_key["external"]["local_action"]=="delete_library"

    cursor=None;complete=None;found=None;replayed=False
    for _ in range(1000):
        params={"limit":7};
        if cursor:params["cursor"]=cursor
        response=client.get("/api/client/v1/knowledge/snapshot",params=params);assert response.status_code==200,response.text
        page=response.json()
        if cursor and not replayed:
            again=client.get("/api/client/v1/knowledge/snapshot",params=params).json()
            assert again["items"]==page["items"] and again["snapshot_sequence"]==page["snapshot_sequence"]
            replayed=True
        for change in page["items"]:
            entity=change["entity"]
            if entity.get("content")=="M8 Offline-Sync Ausgangsnotiz":found=entity
        if not page["has_more"]:complete=page["complete_cursor"];break
        cursor=page["next_cursor"]
    assert found and complete and found["type"]=="note"
    assert found["search"]["keywords"] and found["evidence"]["level"] in ("low","medium","high")

    usage={"batch_id":str(batch_id),"client_installation_id":str(installation),"items":[{"entity_id":found["id"],"view_count_delta":3,"last_viewed_at":now.isoformat()}]}
    accepted=client.post("/api/client/v1/knowledge/usage",json=usage);assert accepted.status_code==200 and accepted.json()["accepted_count"]==1
    repeat=client.post("/api/client/v1/knowledge/usage",json=usage);assert repeat.json()["idempotent"] is True
    changed_usage={**usage,"items":[{**usage["items"][0],"view_count_delta":4}]}
    conflict=client.post("/api/client/v1/knowledge/usage",json=changed_usage);assert conflict.status_code==409 and conflict.json()["code"]=="USAGE_BATCH_CONFLICT"

    with get_db_connection() as db:
        db.execute("UPDATE notes SET content=%s,updated_at=%s WHERE id=%s",("M8 Offline-Sync aktualisierte Notiz",now+timedelta(seconds=1),note_id));db.commit()
    delta=client.get("/api/client/v1/knowledge/delta",params={"cursor":complete,"limit":100});assert delta.status_code==200,delta.text
    updates=[x for x in delta.json()["changes"] if x["entity"].get("id")==found["id"]]
    assert updates and updates[-1]["operation"]=="upsert" and updates[-1]["entity"]["revision"]>found["revision"]
    next_cursor=delta.json()["next_cursor"]
    with get_db_connection() as db:db.execute("UPDATE notes SET archived=TRUE,updated_at=%s WHERE id=%s",(now+timedelta(seconds=2),note_id));db.commit()
    deleted=client.get("/api/client/v1/knowledge/delta",params={"cursor":next_cursor}).json()["changes"]
    assert any(x["operation"]=="delete" and x["entity"]["id"]==found["id"] for x in deleted)
    detail=client.get(f"/api/client/v1/knowledge/entities/{found['id']}");assert detail.json()["operation"]=="delete"

    expired_token=delta.json()["next_cursor"]
    with get_db_connection() as db:
        db.execute("UPDATE client_knowledge_cursors SET expires_at=%s WHERE token=%s",(now-timedelta(seconds=1),expired_token));db.commit()
    expired=client.get("/api/client/v1/knowledge/delta",params={"cursor":expired_token})
    assert expired.status_code==410 and expired.json()["code"]=="SYNC_CURSOR_EXPIRED"
    with get_db_connection() as db:
        db.execute("DELETE FROM knowledge_activity WHERE knowledge_type='note' AND knowledge_id=%s",(note_id,))
        db.execute("DELETE FROM knowledge_signals WHERE knowledge_type='note' AND knowledge_id=%s",(note_id,))
        db.execute("DELETE FROM client_knowledge_usage_batches WHERE batch_id=%s",(batch_id,))
        db.execute("DELETE FROM client_knowledge_changes WHERE public_id=%s",(found["id"],))
        db.execute("DELETE FROM client_knowledge_entities WHERE public_id=%s",(found["id"],))
        db.execute("DELETE FROM notes WHERE id=%s",(note_id,));db.commit()
    print("M8 KNOWLEDGE SYNC TEST: PASS")


if __name__=="__main__":main()
