from datetime import datetime,timedelta
import hashlib,hmac,secrets
from uuid import UUID,uuid4

from ..config import CLIENT_DEVICE_AUTH_SECRET,TIMEZONE
from ..database import get_db_connection


class DeviceAuthError(Exception):
    def __init__(self,code):self.code=code


def _ready():
    if len(CLIENT_DEVICE_AUTH_SECRET)<32:raise DeviceAuthError("DEVICE_AUTH_NOT_CONFIGURED")


def _hash(value):return hashlib.sha256(value.encode()).hexdigest()
def _derive(purpose,value):return hmac.new(CLIENT_DEVICE_AUTH_SECRET.encode(),f"{purpose}:{value}".encode(),hashlib.sha256).hexdigest()


def issue_enrollment_code(minutes=15):
    code=secrets.token_urlsafe(18);now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("INSERT INTO client_enrollment_codes(code_hash,expires_at,created_at) VALUES(%s,%s,%s)",
                  (_hash(code),now+timedelta(minutes=minutes),now));c.commit()
    return code


def enroll(code,installation_id,device_model,firmware_version):
    _ready();installation_id=UUID(str(installation_id));now=datetime.now(TIMEZONE);code_hash=_hash(code)
    token=_derive("enroll",f"{code_hash}:{installation_id}");token_hash=_hash(token)
    with get_db_connection() as c:
        row=c.execute("SELECT expires_at,used_at,installation_id FROM client_enrollment_codes WHERE code_hash=%s FOR UPDATE",(code_hash,)).fetchone()
        if not row or row[0]<=now:raise DeviceAuthError("ENROLLMENT_CODE_INVALID")
        if row[1] is not None and row[2]!=installation_id:raise DeviceAuthError("ENROLLMENT_CODE_USED")
        existing=c.execute("SELECT id FROM client_installations WHERE id=%s",(installation_id,)).fetchone()
        if existing:
            c.execute("UPDATE client_installations SET device_model=%s,firmware_version=%s,updated_at=%s WHERE id=%s",
                      (device_model,firmware_version,now,installation_id))
        else:
            c.execute("INSERT INTO client_installations(id,device_model,firmware_version,status,created_at,updated_at) VALUES(%s,%s,%s,'active',%s,%s)",
                      (installation_id,device_model,firmware_version,now,now))
        credential_id=uuid4();expires=now+timedelta(days=90);rotate=now+timedelta(days=60)
        c.execute("""INSERT INTO client_device_credentials(id,installation_id,token_hash,status,issued_at,expires_at,rotate_after)
        VALUES(%s,%s,%s,'active',%s,%s,%s) ON CONFLICT(token_hash) DO NOTHING""",
                  (credential_id,installation_id,token_hash,now,expires,rotate))
        c.execute("UPDATE client_enrollment_codes SET used_at=COALESCE(used_at,%s),installation_id=%s WHERE code_hash=%s",
                  (now,installation_id,code_hash));c.commit()
        dates=c.execute("SELECT expires_at,rotate_after FROM client_device_credentials WHERE token_hash=%s",(token_hash,)).fetchone()
    return {"client_installation_id":installation_id,"credential":token,"expires_at":dates[0],"rotate_after":dates[1]}


def authenticate(token):
    _ready();now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("""SELECT d.installation_id,d.status,i.status,d.expires_at,d.id FROM client_device_credentials d
        JOIN client_installations i ON i.id=d.installation_id WHERE d.token_hash=%s""",(_hash(token),)).fetchone()
        if not row:raise DeviceAuthError("DEVICE_CREDENTIAL_INVALID")
        if row[1]!="active" or row[2]!="active":raise DeviceAuthError("DEVICE_CREDENTIAL_REVOKED")
        if row[3]<=now:raise DeviceAuthError("DEVICE_CREDENTIAL_EXPIRED")
        c.execute("UPDATE client_installations SET last_seen_at=%s WHERE id=%s",(now,row[0]))
        rotated=c.execute("SELECT 1 FROM client_credential_rotations WHERE credential_id=%s",(row[4],)).fetchone()
        if rotated:c.execute("UPDATE client_device_credentials SET status='revoked',revoked_at=%s WHERE installation_id=%s AND id<>%s AND status='active'",(now,row[0],row[4]))
        c.commit()
    return row[0]


def rotate(installation_id,request_id,current_token):
    installation_id=UUID(str(installation_id));request_id=UUID(str(request_id))
    if authenticate(current_token)!=installation_id:raise DeviceAuthError("DEVICE_CREDENTIAL_INVALID")
    token=_derive("rotate",f"{installation_id}:{request_id}");token_hash=_hash(token);now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        old=c.execute("SELECT credential_id FROM client_credential_rotations WHERE request_id=%s",(request_id,)).fetchone()
        if old:
            row=c.execute("SELECT expires_at,rotate_after FROM client_device_credentials WHERE id=%s",(old[0],)).fetchone()
            return {"client_installation_id":installation_id,"credential":token,"expires_at":row[0],"rotate_after":row[1]}
        credential_id=uuid4();expires=now+timedelta(days=90);rotate_after=now+timedelta(days=60)
        c.execute("INSERT INTO client_device_credentials(id,installation_id,token_hash,status,issued_at,expires_at,rotate_after) VALUES(%s,%s,%s,'active',%s,%s,%s)",
                  (credential_id,installation_id,token_hash,now,expires,rotate_after))
        c.execute("INSERT INTO client_credential_rotations(request_id,installation_id,credential_id,created_at) VALUES(%s,%s,%s,%s)",
                  (request_id,installation_id,credential_id,now))
        c.commit()
    return {"client_installation_id":installation_id,"credential":token,"expires_at":expires,"rotate_after":rotate_after}
