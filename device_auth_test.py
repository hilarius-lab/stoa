"""Deterministic enrollment, bearer protection and two-phase rotation test."""
from uuid import uuid4
from fastapi.testclient import TestClient
import smart_notebook.app as app_module
import smart_notebook.services.device_auth as auth
from smart_notebook.app import app
from smart_notebook.database import get_db_connection


def main():
    auth.CLIENT_DEVICE_AUTH_SECRET="device-auth-test-secret-32-bytes-minimum"
    app_module.CLIENT_DEVICE_AUTH_REQUIRED=True
    client=TestClient(app);installation=uuid4();code=auth.issue_enrollment_code()
    request={"enrollment_code":code,"client_installation_id":str(installation),
             "device_model":"esp32-test","firmware_version":"test"}
    first=client.post("/api/client/v1/installations/enroll",json=request)
    assert first.status_code==200,first.text;token=first.json()["credential"]
    duplicate=client.post("/api/client/v1/installations/enroll",json=request)
    assert duplicate.status_code==200 and duplicate.json()["credential"]==token
    assert client.get("/api/client/v1/dashboard").status_code==401
    headers={"Authorization":f"Bearer {token}"}
    assert client.get("/api/client/v1/dashboard",headers=headers).status_code==200
    rotation_id=uuid4();url=f"/api/client/v1/installations/{installation}/credentials/rotate"
    rotated=client.post(url,json={"request_id":str(rotation_id)},headers=headers)
    assert rotated.status_code==200,rotated.text;new_token=rotated.json()["credential"]
    repeated=client.post(url,json={"request_id":str(rotation_id)},headers=headers)
    assert repeated.status_code==200 and repeated.json()["credential"]==new_token
    new_headers={"Authorization":f"Bearer {new_token}"}
    assert client.get("/api/client/v1/dashboard",headers=new_headers).status_code==200
    assert client.get("/api/client/v1/dashboard",headers=headers).status_code==401

    # --- the operator surface ------------------------------------------------
    #
    # 138 of 179 routes live outside /api/client/ and used to be reachable by
    # anyone, even with device auth switched on. They now need a credential of
    # their own, and a device credential is explicitly not it: the ESP has no
    # business writing notes or triggering workers, and a stolen device must not
    # become an operator.
    operator="operator-token-test-value-32-bytes-min"
    app_module.CLIENT_OPERATOR_TOKEN=""
    assert client.get("/api/system/status").status_code==401,"an unauthenticated legacy route answered"
    assert client.get("/api/system/status",headers=new_headers).status_code==401,(
        "a device credential opened an operator route")
    app_module.CLIENT_OPERATOR_TOKEN=operator
    operator_headers={"Authorization":f"Bearer {operator}"}
    assert client.get("/api/system/status",headers=operator_headers).status_code==200,(
        "the operator token did not open its own surface")
    assert client.get("/api/system/status",headers=new_headers).status_code==401
    # The device credential keeps working on the contract it belongs to, and the
    # public discovery routes stay reachable with no credential at all — a client
    # has to be able to find out where to enroll before it can hold anything.
    assert client.get("/api/client/v1/dashboard",headers=new_headers).status_code==200
    assert client.get("/api/client/capabilities").status_code==200
    assert client.get("/api/client/health").status_code==200
    app_module.CLIENT_OPERATOR_TOKEN=""

    with get_db_connection() as c:
        c.execute("DELETE FROM client_enrollment_codes WHERE code_hash=%s",(auth._hash(code),));c.execute("DELETE FROM client_installations WHERE id=%s",(installation,));c.commit()
    print("DEVICE AUTH TEST: PASS")


if __name__=="__main__":main()
