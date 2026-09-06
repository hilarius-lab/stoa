# Smart Notebook application setup
from fastapi import FastAPI,Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse
from time import perf_counter
from hmac import compare_digest
import uuid

from .database import init_db
from .routers import system, ingestion, jobs, recovery, segmentation, artifacts, topics, intelligence, activity, audio, events, notes, tasks, lists, knowledge, maintenance, claims,live,client,caldav,references
from .client_contract import ClientAPIError,error_response
from .config import CLIENT_CONTRACT_VERSION,CLIENT_CORS_ORIGINS,CLIENT_DEVICE_AUTH_REQUIRED,CLIENT_OPERATOR_TOKEN

# Initialize and migrate the schema when the application module is imported.
init_db()

app = FastAPI()

# Reachable without any credential. Deliberately short: discovery a client needs
# before it can have one, plus enrollment itself, which is guarded by the
# single-use code rather than by a token. Rotation authenticates against the
# credential being replaced and is handled in its own route.
AUTH_PUBLIC={"/api/client/health","/api/client/capabilities","/api/client/v1/contract",
             "/api/client/v1/installations/enroll"}


def _bearer(request):
    value=request.headers.get("authorization","")
    return value[7:] if value.startswith("Bearer ") else ""


@app.middleware("http")
async def client_device_auth(request:Request,call_next):
    """Guard every /api/ route, not only the client contract.

    Two credentials, deliberately not interchangeable. A device credential opens
    /api/client/ and nothing else: the ESP has no business reaching the note,
    claim, task, list, artifact, CalDAV or worker routes, and a stolen device
    must not become an operator. The operator token opens everything under /api/,
    because those legacy routes have no per-caller identity to check and the
    honest alternative — leaving them open on a public hostname — is what this
    change exists to end.

    The socket peer is not consulted anywhere here. Behind a reverse proxy on the
    same host every request arrives from 127.0.0.1, so trusting localhost would
    hand the whole internet the operator surface.
    """
    path=request.url.path
    if not CLIENT_DEVICE_AUTH_REQUIRED or not path.startswith("/api/"):
        return await call_next(request)
    if path in AUTH_PUBLIC or path.endswith("/credentials/rotate"):
        return await call_next(request)
    token=_bearer(request)
    if not token:
        return error_response(request,401,"DEVICE_CREDENTIAL_INVALID","Authentication is required.","user_action")
    if CLIENT_OPERATOR_TOKEN and compare_digest(token,CLIENT_OPERATOR_TOKEN):
        request.state.operator=True
        return await call_next(request)
    if not path.startswith("/api/client/"):
        # An operator route reached with something that is not the operator
        # token. Whether it is a valid device credential is not worth saying:
        # the answer would tell an attacker which of the two they hold.
        return error_response(request,401,"OPERATOR_CREDENTIAL_INVALID","Operator authentication failed.","user_action")
    from .services.device_auth import DeviceAuthError,authenticate
    try:request.state.client_installation_id=authenticate(token)
    except DeviceAuthError as exc:
        retry="backoff" if exc.code=="DEVICE_AUTH_NOT_CONFIGURED" else "user_action"
        status=503 if exc.code=="DEVICE_AUTH_NOT_CONFIGURED" else 401
        return error_response(request,status,exc.code,"Device authentication failed.",retry)
    return await call_next(request)

if CLIENT_CORS_ORIGINS:
    app.add_middleware(CORSMiddleware,allow_origins=list(CLIENT_CORS_ORIGINS),allow_credentials=False,
        allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
        allow_headers=["Authorization","Content-Type","Last-Event-ID","X-Request-ID","X-Smart-Notebook-Contract","X-Client-Installation-ID","Idempotency-Key"],
        expose_headers=["X-Request-ID","X-Smart-Notebook-Contract"])

@app.exception_handler(ClientAPIError)
async def client_api_error_handler(request:Request,exc:ClientAPIError):
    return error_response(request,exc.status_code,exc.code,exc.message,exc.retry_class,exc.details)

@app.exception_handler(RequestValidationError)
async def client_validation_error_handler(request:Request,exc:RequestValidationError):
    if request.url.path.startswith("/api/client/"):
        # Pydantic's default error objects contain the rejected `input`, which may
        # be a memo, chat message or other sensitive body. The wire error only needs
        # the structural location and reason and is therefore deliberately redacted.
        errors=[{"type":item.get("type"),"loc":list(item.get("loc",())),"message":item.get("msg")}
                for item in exc.errors()]
        return error_response(request,422,"CONTRACT_VALIDATION_FAILED","The request does not match the client contract.","never",{"errors":errors})
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request,exc)

@app.exception_handler(StarletteHTTPException)
async def client_http_error_handler(request:Request,exc:StarletteHTTPException):
    if request.url.path.startswith("/api/client/"):
        codes={404:"RESOURCE_NOT_FOUND",405:"OPERATION_FORBIDDEN"}
        return error_response(request,exc.status_code,codes.get(exc.status_code,"SERVER_ERROR"),str(exc.detail),"never")
    from fastapi.exception_handlers import http_exception_handler
    return await http_exception_handler(request,exc)

@app.exception_handler(Exception)
async def client_unhandled_error_handler(request:Request,exc:Exception):
    if request.url.path.startswith("/api/client/"):
        return error_response(request,500,"SERVER_ERROR","The server could not complete the client request.","backoff",
                              {"error_type":type(exc).__name__})
    return PlainTextResponse("Internal Server Error",status_code=500)

@app.middleware("http")
async def structured_request_log(request:Request,call_next):
    from .services.observability import emit_event
    request_id=request.headers.get("x-request-id") or uuid.uuid4().hex;request.state.request_id=request_id;started=perf_counter()
    try:
        response=await call_next(request);level="warning" if response.status_code>=400 else "info"
        emit_event("api","request_completed",level,request_id,metadata={"method":request.method,"path":request.url.path,
            "status":response.status_code,"duration_ms":round((perf_counter()-started)*1000)})
        response.headers["x-request-id"]=request_id
        if request.url.path.startswith("/api/client/"):response.headers["x-smart-notebook-contract"]=CLIENT_CONTRACT_VERSION
        return response
    except Exception as exc:
        emit_event("api","request_failed","error",request_id,metadata={"method":request.method,"path":request.url.path,
            "error_type":type(exc).__name__,"duration_ms":round((perf_counter()-started)*1000)});raise

app.include_router(system.router)
app.include_router(ingestion.router)
app.include_router(jobs.router)
app.include_router(recovery.router)
app.include_router(segmentation.router)
app.include_router(artifacts.router)
app.include_router(topics.router)
app.include_router(intelligence.router)
app.include_router(activity.router)
app.include_router(audio.router)
app.include_router(events.router)
app.include_router(notes.router)
app.include_router(tasks.router)
app.include_router(lists.router)
app.include_router(knowledge.router)
app.include_router(maintenance.router)
app.include_router(claims.router)
app.include_router(live.router)
app.include_router(client.router)
app.include_router(caldav.router)
app.include_router(references.router)
