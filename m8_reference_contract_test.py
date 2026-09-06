"""M8 normative matrix, reference fixtures, redirects and privacy invariants."""
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID,uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.knowledge_sync import get_synced_entity,refresh_sync_index
from smart_notebook.services.client_chat import _sanitize_markdown
from smart_notebook.services.observability import _safe

ROOT=Path(__file__).resolve().parent


def main():
    fixture=json.loads((ROOT/"contracts"/"client-reference-fixtures-v1.json").read_text(encoding="utf-8"))
    assert fixture["contract_version"]=="1"
    assert set(fixture["session_states"])=={"created","recording","paused","draining","processing","completed","attention_required","aborted"}
    assert set(fixture["completion_states"])=={"uploads_pending","processing","completed","failed","attention_required","aborted"}
    assert fixture["audio_ack"]["durable_ack"] is True
    assert [x["operation"] for x in fixture["knowledge_changes"]]==["upsert","delete","redirect"]
    for change in fixture["knowledge_changes"]:UUID(change["entity"]["id"])

    client=TestClient(app);caps=client.get("/api/client/capabilities").json()
    assert caps["session_states"]==fixture["session_states"]
    assert caps["completion_states"]==fixture["completion_states"]
    assert caps["dashboard"]["component_types"]==fixture["dashboard_component_types"]
    assert caps["dashboard"]["actions"]==fixture["dashboard_actions"]
    assert caps["transports"]["sse_proxy_buffering"] is False
    assert caps["limits"]["request_timeout_seconds"]==60
    assert caps["audio_profiles"][0]["max_chunk_bytes"]==2*1024*1024

    # Contract validation must never echo a sensitive rejected body.
    secret="M8-PRIVATE-MEMO-MUST-NOT-BE-ECHOED"
    invalid=client.post("/api/client/v1/captures",json={"client_capture_id":str(uuid4()),"mode":"invalid","content":secret})
    assert invalid.status_code==422 and invalid.json()["code"]=="CONTRACT_VALIDATION_FAILED"
    assert secret not in invalid.text and "input" not in invalid.json()["details"]["errors"][0]
    assert _safe({"content":secret,"prompt":secret,"token":secret,"chunk_id":"safe-id","status":"queued"})=={"chunk_id":"safe-id","status":"queued"}
    sanitized=_sanitize_markdown("<script>x</script> [bad](javascript:alert(1)) [ok](https://example.test) ![secret](data:x)")
    assert "<script>" not in sanitized and "javascript:" not in sanitized and "data:" not in sanitized and "https://example.test" in sanitized

    # Every operation the first Android client may call is present in the frozen API.
    paths=set(app.openapi()["paths"])
    required={
        "/api/client/health","/api/client/capabilities","/api/client/v1/contract",
        "/api/client/v1/diagnostics/audio-upload-test",
        "/api/client/v1/sessions","/api/client/v1/sessions/{client_session_id}",
        "/api/client/v1/sessions/{client_session_id}/start","/api/client/v1/sessions/{client_session_id}/pause",
        "/api/client/v1/sessions/{client_session_id}/resume","/api/client/v1/sessions/{client_session_id}/finish",
        "/api/client/v1/sessions/{client_session_id}/finalize","/api/client/v1/sessions/{client_session_id}/abort",
        "/api/client/v1/sessions/{client_session_id}/audio-chunks","/api/client/v1/sessions/{client_session_id}/reconciliation",
        "/api/client/v1/dashboard","/api/client/v1/dashboard/events",
        "/api/client/v1/sessions/{client_session_id}/dashboard","/api/client/v1/sessions/{client_session_id}/dashboard/events",
        "/api/client/v1/entities/{entity_type}/{entity_id}","/api/client/v1/knowledge/libraries",
        "/api/client/v1/knowledge/snapshot","/api/client/v1/knowledge/delta","/api/client/v1/knowledge/entities/{entity_id}",
        "/api/client/v1/knowledge/usage","/api/client/v1/captures","/api/client/v1/captures/{capture_id}",
        "/api/client/v1/conversations","/api/client/v1/conversations/{conversation_id}",
        "/api/client/v1/conversations/{conversation_id}/turns","/api/client/v1/conversation-turns/{turn_id}",
        "/api/client/v1/conversation-turns/{turn_id}/events","/api/client/v1/conversation-turns/{turn_id}/abort",
        "/api/client/v1/conversation-turns/{turn_id}/retry","/api/client/v1/push/registrations",
        "/api/client/v1/push/registrations/{registration_id}/confirm","/api/client/v1/push/registrations/{registration_id}",
    }
    assert not (required-paths),sorted(required-paths)

    # Topic merges are a redirect, not a silent duplicate or recycled identity.
    now=datetime.now(TIMEZONE);suffix=uuid4().hex
    with get_db_connection() as db:
        source=db.execute("INSERT INTO knowledge_topics(title,normalized_key,description,created_at,updated_at) VALUES(%s,%s,'',%s,%s) RETURNING id",(f"M8 source {suffix}",f"m8-source-{suffix}",now,now)).fetchone()[0]
        target=db.execute("INSERT INTO knowledge_topics(title,normalized_key,description,created_at,updated_at) VALUES(%s,%s,'',%s,%s) RETURNING id",(f"M8 target {suffix}",f"m8-target-{suffix}",now,now)).fetchone()[0];db.commit()
    refresh_sync_index()
    with get_db_connection() as db:
        old_id=db.execute("SELECT public_id FROM client_knowledge_entities WHERE entity_type='topic' AND internal_id=%s",(source,)).fetchone()[0]
        new_id=db.execute("SELECT public_id FROM client_knowledge_entities WHERE entity_type='topic' AND internal_id=%s",(target,)).fetchone()[0]
        db.execute("INSERT INTO knowledge_topic_redirects(source_topic_id,target_topic_id,reason,created_at) VALUES(%s,%s,'m8_fixture_merge',%s)",(source,target,now));db.commit()
    refresh_sync_index();redirect=get_synced_entity(old_id)
    assert redirect["operation"]=="redirect" and redirect["entity"]["target_id"]==str(new_id) and redirect["entity"]["reason"]=="topic_merged"
    with get_db_connection() as db:
        db.execute("DELETE FROM knowledge_topic_redirects WHERE source_topic_id=%s",(source,))
        db.execute("DELETE FROM client_knowledge_changes WHERE public_id=ANY(%s)",([old_id,new_id],))
        db.execute("DELETE FROM client_knowledge_entities WHERE public_id=ANY(%s)",([old_id,new_id],))
        db.execute("DELETE FROM knowledge_topics WHERE id=ANY(%s)",([source,target],));db.commit()
    print("M8 REFERENCE CONTRACT TEST: PASS")


if __name__=="__main__":main()
