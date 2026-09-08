"""M8 conversation recovery and encrypted UnifiedPush contract test."""
import asyncio,base64,json
from uuid import UUID,uuid4

import httpx
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.database import get_db_connection
from smart_notebook.services import unified_push
from smart_notebook.services.unified_push import broadcast_invalidation


def unb64(value):return base64.urlsafe_b64decode(value+"="*((4-len(value)%4)%4))
def decrypt(private,envelope):
    ephemeral=X25519PublicKey.from_public_bytes(unb64(envelope["ephemeral_public_key"]));shared=private.exchange(ephemeral)
    key=HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=b"smart-notebook-unifiedpush-v1").derive(shared)
    return json.loads(AESGCM(key).decrypt(unb64(envelope["nonce"]),unb64(envelope["ciphertext"]),b"smart-notebook:v1"))


def main():
    client=TestClient(app);conversation_key=uuid4();message_key=uuid4();turn_key=uuid4()
    request={"client_conversation_id":str(conversation_key),"client_message_id":str(message_key),"client_turn_id":str(turn_key),"content":"Was ist der Status von Projekt Atlas?"}
    created=client.post("/api/client/v1/conversations",json=request);assert created.status_code==201,created.text
    conversation=created.json()["conversation"];turn=created.json()["turn"]
    duplicate=client.post("/api/client/v1/conversations",json=request);assert duplicate.status_code==201 and duplicate.json()["turn"]["id"]==turn["id"]
    conflict=client.post("/api/client/v1/conversations",json={**request,"content":"Andere Eingabe"})
    assert conflict.status_code==409 and conflict.json()["code"]=="CHAT_IDEMPOTENCY_CONFLICT"
    dashboard=client.get("/api/client/v1/dashboard").json()
    assert any(any((card.get("entity_ref") or {}).get("id")==conversation["id"] for card in section["items"]) for section in dashboard["sections"])
    for _ in range(20):
        run=client.post("/api/workers/client-chat/run-once",json={"mode":"deterministic","deterministic_text":"Projekt Atlas befindet sich im Testbetrieb."}).json()
        if (run.get("turn") or {}).get("id")==turn["id"]:break
    assert run["outcome"]=="completed"
    polled=client.get(f"/api/client/v1/conversation-turns/{turn['id']}").json();assert polled["status"]=="completed"
    detail=client.get(f"/api/client/v1/conversations/{conversation['id']}").json()
    assert [m["role"] for m in detail["messages"]]==["user","assistant"] and detail["messages"][-1]["content"].startswith("Projekt Atlas")
    with client.stream("GET",f"/api/client/v1/conversation-turns/{turn['id']}/events") as stream:
        wire="".join(stream.iter_text())
    assert "event: started" in wire and "event: delta" in wire and "event: completed" in wire

    second=client.post(f"/api/client/v1/conversations/{conversation['id']}/turns",json={"client_message_id":str(uuid4()),"client_turn_id":str(uuid4()),"content":"Noch eine Frage"}).json()
    assert client.post(f"/api/client/v1/conversation-turns/{second['id']}/abort").json()["status"]=="aborted"
    assert client.post(f"/api/client/v1/conversation-turns/{second['id']}/retry").json()["status"]=="queued"

    private=X25519PrivateKey.generate();public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    public_text=base64.urlsafe_b64encode(public).decode().rstrip("=");delivered=[]
    async def fake_post(endpoint,envelope):
        delivered.append((endpoint,envelope));return httpx.Response(200,request=httpx.Request("POST",endpoint))
    original_post=unified_push._post;unified_push._post=fake_post
    registration=uuid4();installation=uuid4()
    try:
        registered=client.post("/api/client/v1/push/registrations",json={"registration_id":str(registration),"client_installation_id":str(installation),
            "distributor":"ntfy","endpoint":"https://push.example.test/opaque-topic","client_public_key":public_text})
        assert registered.status_code==202 and registered.json()["challenge_delivery"]=="delivered"
        challenge=decrypt(private,delivered[-1][1]);assert challenge["event_type"]=="challenge" and "challenge" in challenge
        wrong=client.post(f"/api/client/v1/push/registrations/{registration}/confirm",json={"challenge":"x"*24})
        assert wrong.status_code==409
        confirmed=client.post(f"/api/client/v1/push/registrations/{registration}/confirm",json={"challenge":challenge["challenge"]})
        assert confirmed.status_code==200 and confirmed.json()["status"]=="active"
        outcome=asyncio.run(broadcast_invalidation("dashboard_changed",17));assert outcome=={"attempted":1,"delivered":1}
        wake=decrypt(private,delivered[-1][1]);assert wake=={"event_type":"dashboard_changed","revision":17}
        removed=client.delete(f"/api/client/v1/push/registrations/{registration}");assert removed.status_code==204
    finally:unified_push._post=original_post
    with get_db_connection() as db:
        db.execute("DELETE FROM unified_push_registrations WHERE id=%s",(registration,))
        db.execute("DELETE FROM client_conversations WHERE id=%s",(conversation["id"],));db.commit()
    print("M8 CHAT + PUSH CONTRACT TEST: PASS")


if __name__=="__main__":main()
