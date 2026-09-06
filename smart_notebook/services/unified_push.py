import base64,hashlib,json,secrets
from datetime import datetime,timedelta
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import TIMEZONE
from ..database import get_db_connection


class PushRegistrationConflict(Exception):pass


def _b64(value):return base64.urlsafe_b64encode(value).decode().rstrip("=")
def _unb64(value):return base64.urlsafe_b64decode(value+"="*((4-len(value)%4)%4))
def _hash(value):return hashlib.sha256(value.encode()).hexdigest()


def encrypt_payload(client_public_key,payload):
    client=X25519PublicKey.from_public_bytes(_unb64(client_public_key));ephemeral=X25519PrivateKey.generate()
    shared=ephemeral.exchange(client);key=HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=b"smart-notebook-unifiedpush-v1").derive(shared)
    nonce=secrets.token_bytes(12);plain=json.dumps(payload,sort_keys=True,separators=(",",":")).encode();cipher=AESGCM(key).encrypt(nonce,plain,b"smart-notebook:v1")
    public=ephemeral.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    return {"version":1,"algorithm":"X25519-HKDF-SHA256-AESGCM","ephemeral_public_key":_b64(public),"nonce":_b64(nonce),"ciphertext":_b64(cipher)}


async def _post(endpoint,envelope):
    async with httpx.AsyncClient(timeout=15,trust_env=False) as client:return await client.post(endpoint,json=envelope)


def _item(r):
    if not r:return None
    return {"id":str(r[0]),"client_installation_id":str(r[1]),"distributor":r[2],"status":r[3],"created_at":r[4].isoformat(),
            "updated_at":r[5].isoformat(),"last_success_at":r[6].isoformat() if r[6] else None,"failure_count":r[7]}


SELECT="SELECT id,client_installation_id,distributor,status,created_at,updated_at,last_success_at,failure_count FROM unified_push_registrations"


async def register(registration_id,installation_id,distributor,endpoint,client_public_key):
    parsed=urlparse(endpoint)
    if parsed.scheme!="https" or not parsed.netloc:raise ValueError("UnifiedPush endpoint must use HTTPS")
    try:X25519PublicKey.from_public_bytes(_unb64(client_public_key))
    except Exception as exc:raise ValueError("client_public_key must be a base64url X25519 public key") from exc
    now=datetime.now(TIMEZONE);endpoint_hash=_hash(endpoint);challenge=secrets.token_urlsafe(32);challenge_hash=_hash(challenge)
    with get_db_connection() as c:
        old=c.execute("SELECT endpoint_hash,client_public_key FROM unified_push_registrations WHERE id=%s",(registration_id,)).fetchone()
        if old and old!=(endpoint_hash,client_public_key):raise PushRegistrationConflict("registration id already exists with different endpoint or key")
        c.execute("UPDATE unified_push_registrations SET status='disabled',updated_at=%s WHERE client_installation_id=%s AND id<>%s AND status<>'disabled'",(now,installation_id,registration_id))
        c.execute("""INSERT INTO unified_push_registrations(id,client_installation_id,distributor,endpoint,endpoint_hash,client_public_key,status,challenge_hash,challenge_expires_at,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET challenge_hash=EXCLUDED.challenge_hash,
        challenge_expires_at=EXCLUDED.challenge_expires_at,status='pending',updated_at=EXCLUDED.updated_at""",
        (registration_id,installation_id,distributor,endpoint,endpoint_hash,client_public_key,challenge_hash,now+timedelta(minutes=10),now,now));c.commit()
    delivered=await deliver(registration_id,"challenge",0,{"challenge":challenge})
    return {"registration":get_registration(registration_id),"challenge_delivery":"delivered" if delivered else "failed"}


def get_registration(registration_id):
    with get_db_connection() as c:r=c.execute(SELECT+" WHERE id=%s",(registration_id,)).fetchone()
    return _item(r)


def list_registrations(installation_id=None):
    where=" WHERE client_installation_id=%s" if installation_id else "";params=(installation_id,) if installation_id else ()
    with get_db_connection() as c:rows=c.execute(SELECT+where+" ORDER BY updated_at DESC",params).fetchall()
    return [_item(r) for r in rows]


async def deliver(registration_id,event_type,revision,extra=None):
    with get_db_connection() as c:r=c.execute("SELECT endpoint,client_public_key,status FROM unified_push_registrations WHERE id=%s",(registration_id,)).fetchone()
    if not r or (r[2]!="active" and event_type!="challenge"):return False
    envelope=encrypt_payload(r[1],{"event_type":event_type,"revision":revision,**(extra or {})});now=datetime.now(TIMEZONE)
    try:
        response=await _post(r[0],envelope);response.raise_for_status();status=response.status_code
        with get_db_connection() as c:
            c.execute("UPDATE unified_push_registrations SET last_success_at=%s,updated_at=%s,failure_count=0 WHERE id=%s",(now,now,registration_id))
            c.execute("INSERT INTO unified_push_delivery_audit(registration_id,event_type,revision,outcome,http_status,created_at) VALUES(%s,%s,%s,'delivered',%s,%s)",(registration_id,event_type,revision,status,now));c.commit()
        return True
    except Exception as exc:
        with get_db_connection() as c:
            c.execute("UPDATE unified_push_registrations SET last_failure_at=%s,updated_at=%s,failure_count=failure_count+1 WHERE id=%s",(now,now,registration_id))
            c.execute("INSERT INTO unified_push_delivery_audit(registration_id,event_type,revision,outcome,error_type,created_at) VALUES(%s,%s,%s,'failed',%s,%s)",(registration_id,event_type,revision,type(exc).__name__,now));c.commit()
        return False


def confirm(registration_id,challenge):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("SELECT challenge_hash,challenge_expires_at,status FROM unified_push_registrations WHERE id=%s FOR UPDATE",(registration_id,)).fetchone()
        if not row:return None
        if row[2]=="active":return _item(c.execute(SELECT+" WHERE id=%s",(registration_id,)).fetchone())
        if not row[0] or row[1]<now or not secrets.compare_digest(row[0],_hash(challenge)):raise PushRegistrationConflict("challenge is invalid or expired")
        c.execute("UPDATE unified_push_registrations SET status='active',challenge_hash=NULL,challenge_expires_at=NULL,updated_at=%s WHERE id=%s",(now,registration_id));c.commit()
    return get_registration(registration_id)


def unregister(registration_id):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("UPDATE unified_push_registrations SET status='disabled',updated_at=%s WHERE id=%s RETURNING id",(now,registration_id)).fetchone();c.commit()
    return bool(row)


async def broadcast_invalidation(event_type,revision):
    with get_db_connection() as c:ids=[r[0] for r in c.execute("SELECT id FROM unified_push_registrations WHERE status='active'").fetchall()]
    outcomes=[]
    for registration_id in ids:outcomes.append(await deliver(registration_id,event_type,revision))
    return {"attempted":len(ids),"delivered":sum(outcomes)}
