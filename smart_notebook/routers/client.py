"""Discovery and immutable version-negotiation endpoints for dedicated clients."""
import asyncio,json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter,File,Form,Header,Request,UploadFile
from fastapi.responses import JSONResponse,StreamingResponse
from pydantic import BaseModel,Field
from uuid import UUID

from ..client_contract import ClientAPIError
from ..client_models import (AudioAckResponse,AudioDiagnosticResponse,CapabilitiesResponse,CaptureResponse,
    ChatSSEEvent,ClientSessionResponse,ConversationCreatedResponse,ConversationDetailResponse,
    ConversationListResponse,DashboardEntityResponse,DashboardResponse,DashboardSSEEvent,ErrorResponse,
    FinishResponse,HealthResponse,KnowledgeDeltaResponse,KnowledgeEntityResponse,KnowledgeSnapshotResponse,
    LibrariesResponse,PushRegistration,PushRegistrationCreateResponse,PushRegistrationListResponse,
    ReconciliationResponse,SessionListResponse,TurnResponse,UsageResponse)
from ..config import (
    APP_VERSION, AUDIO_RETENTION_DAYS, SYSTEM_LOG_RETENTION_HOURS,
    CLIENT_AUDIO_MAX_CHUNK_BYTES, CLIENT_AUDIO_SEGMENT_TARGET_MS,
    CLIENT_CONTRACT_VERSION, CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS, CLIENT_REQUEST_TIMEOUT_SECONDS,
    CLIENT_SERVER_STATUS, CLIENT_SERVER_STATUS_MESSAGE,
    CLIENT_SUPPORTED_CONTRACT_VERSIONS, TIMEZONE,
)
from ..database import get_db_connection
from ..services.audio import AudioChunkConflictError,create_audio_chunk
from ..services.audio_diagnostics import diagnose_audio_bytes
from ..services.client_dashboard import ESP_SURFACE,dashboard_snapshot,get_dashboard_entity
from ..services.client_chat import (ConversationConflict,abort_turn,add_turn,create_conversation,get_conversation,
    get_turn,list_conversations,list_messages,retry_turn,run_chat_turn_once,turn_events)
from ..services.client_capture import CaptureConflict,create_capture,get_capture,run_capture_once
from ..services.knowledge_sync import (SyncCursorExpired,SyncCursorInvalid,UsageBatchConflict,delta_page,
    get_synced_entity,initial_page,list_libraries,record_usage_batch)
from ..services.unified_push import PushRegistrationConflict,confirm as confirm_push,list_registrations,register as register_push,unregister as unregister_push
from ..services.client_sessions import (ClientSessionConflict,abort_client_session,create_client_session,
    completion_status,finalize_client_session,finish_client_session,get_client_session,list_client_sessions,
    reconciliation,record_upload_conflict,transition_client_session)
from ..services.device_auth import DeviceAuthError,enroll,rotate

ERROR_RESPONSES={400:{"model":ErrorResponse},401:{"model":ErrorResponse},404:{"model":ErrorResponse},409:{"model":ErrorResponse},
                 410:{"model":ErrorResponse},413:{"model":ErrorResponse},422:{"model":ErrorResponse},
                 500:{"model":ErrorResponse},503:{"model":ErrorResponse}}
router = APIRouter(tags=["client-contract"],responses=ERROR_RESPONSES)


def _capabilities():
    return {
        "contract": {
            "current": CLIENT_CONTRACT_VERSION,
            "supported": list(CLIENT_SUPPORTED_CONTRACT_VERSIONS),
            "api_base": f"/api/client/v{CLIENT_CONTRACT_VERSION}",
        },
        "server": {"version": APP_VERSION, "time": datetime.now(TIMEZONE).isoformat()},
        "status": CLIENT_SERVER_STATUS,
        "status_message": CLIENT_SERVER_STATUS_MESSAGE,
        "features": {
            "audio_upload": True,
            "audio_upload_diagnostics": True,
            "session_recovery": True,
            "dashboard_snapshot": True,
            "dashboard_sse": True,
            "offline_knowledge_sync": True,
            "chat": True,
            "unified_push": True,
        },
        "audio_profiles": [{
            "id": "android_aac_lc_v1", "mime_type": "audio/mp4",
            "container": "mp4", "codec": "aac-lc", "sample_rate_hz": 48000,
            "channels": 1, "bitrate_bps": 64000,
            "target_segment_ms": CLIENT_AUDIO_SEGMENT_TARGET_MS,
            "max_chunk_bytes": CLIENT_AUDIO_MAX_CHUNK_BYTES,
        }, {
            "id": "browser_webm_opus_v1", "mime_type": "audio/webm",
            "container": "webm", "codec": "opus", "sample_rate_hz": None,
            "channels": None, "bitrate_bps": None,
            "target_segment_ms": CLIENT_AUDIO_SEGMENT_TARGET_MS,
            "max_chunk_bytes": CLIENT_AUDIO_MAX_CHUNK_BYTES,
        }],
        "limits": {
            "request_timeout_seconds": CLIENT_REQUEST_TIMEOUT_SECONDS,
            "dashboard_cards_per_section": 10,
            "live_transcript_max_segments": 50,
            "live_transcript_window_seconds": 600,
            "dashboard_history_hours": 10,
            "dashboard_cache_max_age_seconds": CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS,
            "dashboard_title_max_chars": 100,
            "dashboard_preview_max_chars": 240,
            "dashboard_detail_max_chars": 8000,
            "server_raw_audio_retention_days": AUDIO_RETENTION_DAYS,
            "server_ephemeral_chat_retention_hours": 48,
            "server_technical_log_retention_hours": SYSTEM_LOG_RETENTION_HOURS,
        },
        "session_states": ["created","recording","paused","draining","processing","completed","attention_required","aborted"],
        "completion_states": ["uploads_pending","processing","completed","failed","attention_required","aborted"],
        "dashboard": {
            "schema_version": "1",
            "component_types": ["section","status_banner","text_block","entity_card","card_list","timeline","metric","alert","input_prompt","chat_preview","action_group","empty_state"],
            "actions": ["open_entity","open_conversation","open_session","open_clarification","submit_capture","retry_operation","dismiss_local","open_settings","open_external_https"],
            "color_roles": ["primary","secondary","neutral","muted","info","success","warning","danger","recording","offline"],
            "icon_tokens": ["generic","microphone","recording","session","question","warning","task","list","note","fact","decision","topic","chat","info"],
            "border_roles": ["none","subtle","emphasis","critical"],
            "spacing_roles": ["compact","normal","relaxed"],
            "preferred_spans": ["auto","full","half","third"],
            "unknown_optional_component": "skip",
            "unknown_required_component": "incompatible_region",
        },
        "transports": {"rest": True, "sse": True, "unified_push": True,
                       "foreground_refresh":"sse","background_refresh":"unified_push","fallback_refresh":"work_manager",
                       "sse_proxy_buffering":False},
    }


@router.get("/api/client/health",response_model=HealthResponse)
async def client_health():
    return {
        "status": "ok", "server_version": APP_VERSION,
        "contract_version": CLIENT_CONTRACT_VERSION,
        "time": datetime.now(TIMEZONE).isoformat(),
    }


@router.get("/api/client/capabilities",response_model=CapabilitiesResponse)
async def client_capabilities():
    return _capabilities()


@router.get("/api/client/v1/contract",response_model=CapabilitiesResponse)
async def client_contract(x_smart_notebook_contract: str | None = Header(default=None)):
    if x_smart_notebook_contract not in (None, CLIENT_CONTRACT_VERSION):
        raise ClientAPIError(
            409, "API_INCOMPATIBLE", "The requested client contract is not supported.",
            "user_action", {"supported_versions": list(CLIENT_SUPPORTED_CONTRACT_VERSIONS)},
        )
    return _capabilities()


class ClientSessionCreate(BaseModel):
    client_session_id:UUID
    source_type:str=Field(default="android_audio",min_length=1,max_length=100)
    title:str|None=Field(default=None,max_length=500)
    source:str|None=Field(default=None,max_length=500)
    started_at:datetime|None=None
    device_metadata:dict=Field(default_factory=dict)
    capture_mode:str=Field(default="meeting",pattern="^(meeting|memo|query|auto)$")
    sequence_base:Literal[0,1]|None=Field(default=None,description="Immutable wire sequence origin. Omit only for legacy clients; defaults to 1 unless legacy device_metadata declares 0 on first create.")
    context_ref:dict|None=None


class FinishRequest(BaseModel):
    final_sequence:int=Field(ge=0)
    final_source_end_ms:int|None=Field(default=None,ge=0)


class InstallationEnrollRequest(BaseModel):
    enrollment_code:str=Field(min_length=12,max_length=200)
    client_installation_id:UUID
    device_model:str=Field(min_length=1,max_length=200)
    firmware_version:str=Field(min_length=1,max_length=100)


class CredentialRotateRequest(BaseModel):
    request_id:UUID


class DeviceCredentialResponse(BaseModel):
    client_installation_id:UUID;credential:str;expires_at:datetime;rotate_after:datetime


class AbortRequest(BaseModel):
    reason:str|None=Field(default=None,max_length=500)


class KnowledgeUsageItem(BaseModel):
    entity_id:UUID
    view_count_delta:int=Field(ge=1,le=10000)
    last_viewed_at:datetime


class KnowledgeUsageBatch(BaseModel):
    batch_id:UUID
    client_installation_id:UUID
    items:list[KnowledgeUsageItem]=Field(min_length=1,max_length=500)


class ConversationCreate(BaseModel):
    client_conversation_id:UUID
    client_message_id:UUID
    client_turn_id:UUID
    content:str=Field(min_length=1,max_length=50000)


class ConversationTurnCreate(BaseModel):
    client_message_id:UUID
    client_turn_id:UUID
    content:str=Field(min_length=1,max_length=50000)


class ChatWorkerRequest(BaseModel):
    mode:str="llm"
    deterministic_text:str="Deterministische Testantwort."


class PushRegistrationCreate(BaseModel):
    registration_id:UUID
    client_installation_id:UUID
    distributor:str=Field(default="ntfy",min_length=1,max_length=100)
    endpoint:str=Field(min_length=1,max_length=4000)
    client_public_key:str=Field(min_length=40,max_length=100)


class PushChallengeConfirm(BaseModel):
    challenge:str=Field(min_length=20,max_length=200)


class TextCaptureCreate(BaseModel):
    client_capture_id:UUID
    mode:str=Field(default="auto",pattern="^(memo|query|auto)$")
    content:str=Field(min_length=1,max_length=50000)
    context_ref:dict|None=None


class CaptureWorkerRequest(BaseModel):
    mode:str="production"


def _public_session(item):
    if item is None:return None
    result={key:value for key,value in item.items() if key!="ingestion_session_id"}
    if _zero_based(item) and result.get("expected_final_sequence") is not None:
        result["expected_final_sequence"]-=1
    return result


def _zero_based(item):
    return item.get("sequence_base")==0


def _public_reconciliation(result,item):
    if result is None or not _zero_based(item):return result
    public=dict(result)
    if public.get("expected_final_sequence") is not None:public["expected_final_sequence"]-=1
    public["received_sequences"]=[value-1 for value in public["received_sequences"]]
    public["missing_sequences"]=[value-1 for value in public["missing_sequences"]]
    public["chunks"]=[{**chunk,"sequence":chunk["sequence"]-1} for chunk in public["chunks"]]
    public["conflicts"]=[{**conflict,"sequence":conflict["sequence"]-1} for conflict in public["conflicts"]]
    return public


def _session_or_404(session_id):
    item=get_client_session(session_id)
    if not item:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return item


def _conflict(exc):
    raise ClientAPIError(409,"SESSION_STATE_CONFLICT",str(exc),"user_action") from exc


def _auth_error(exc):
    statuses={"DEVICE_AUTH_NOT_CONFIGURED":503,"ENROLLMENT_CODE_INVALID":401,
              "ENROLLMENT_CODE_USED":409,"DEVICE_CREDENTIAL_INVALID":401,
              "DEVICE_CREDENTIAL_REVOKED":401,"DEVICE_CREDENTIAL_EXPIRED":401}
    retry="backoff" if exc.code=="DEVICE_AUTH_NOT_CONFIGURED" else "user_action"
    raise ClientAPIError(statuses.get(exc.code,401),exc.code,"Device authentication failed.",retry) from exc


@router.post("/api/client/v1/installations/enroll",response_model=DeviceCredentialResponse)
async def enroll_v1_installation(request:InstallationEnrollRequest):
    try:return enroll(request.enrollment_code,request.client_installation_id,request.device_model,request.firmware_version)
    except DeviceAuthError as exc:_auth_error(exc)


@router.post("/api/client/v1/installations/{client_installation_id}/credentials/rotate",response_model=DeviceCredentialResponse)
async def rotate_v1_credential(client_installation_id:UUID,request:CredentialRotateRequest,
                               authorization:str|None=Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise ClientAPIError(401,"DEVICE_CREDENTIAL_INVALID","Device authentication failed.","user_action")
    try:return rotate(client_installation_id,request.request_id,authorization[7:])
    except DeviceAuthError as exc:_auth_error(exc)


@router.post("/api/client/v1/sessions",status_code=201,response_model=ClientSessionResponse)
async def create_v1_session(request:ClientSessionCreate):
    try:item=create_client_session(request.client_session_id,request.source_type,request.title,request.source,
                                   request.started_at,request.device_metadata,request.capture_mode,request.context_ref,
                                   request.sequence_base)
    except ClientSessionConflict as exc:
        raise ClientAPIError(409,"SESSION_ID_CONFLICT",str(exc),"user_action") from exc
    return _public_session(item)


SESSION_HISTORY_PARAMETERS=[
    {"name":"limit","in":"query","required":False,"schema":{"type":"integer","minimum":0,"maximum":100},
     "description":"When present, select history mode and return at most this many sessions."},
    {"name":"offset","in":"query","required":False,"schema":{"type":"integer","minimum":0},
     "description":"History offset; ignored unless a valid limit is present."},
]


def _history_number(request,name,maximum=None):
    try:value=int(request.query_params[name])
    except (KeyError,TypeError,ValueError):return None
    if value<0:return None
    return min(value,maximum) if maximum is not None else value


@router.get("/api/client/v1/sessions",response_model=SessionListResponse,openapi_extra={"parameters":SESSION_HISTORY_PARAMETERS})
async def list_v1_sessions(request:Request):
    limit=_history_number(request,"limit",100)
    if limit is None:return [_public_session(item) for item in list_client_sessions()]
    offset=_history_number(request,"offset") or 0
    return [_public_session(item) for item in list_client_sessions(limit,offset,include_closed=True)]


@router.get("/api/client/v1/sessions/{client_session_id}",response_model=ClientSessionResponse)
async def get_v1_session(client_session_id:UUID):return _public_session(_session_or_404(client_session_id))


async def _transition(session_id,action):
    try:item=transition_client_session(session_id,action)
    except ClientSessionConflict as exc:_conflict(exc)
    if not item:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return _public_session(item)


@router.post("/api/client/v1/sessions/{client_session_id}/start",response_model=ClientSessionResponse)
async def start_v1_session(client_session_id:UUID):return await _transition(client_session_id,"start")


@router.post("/api/client/v1/sessions/{client_session_id}/pause",response_model=ClientSessionResponse)
async def pause_v1_session(client_session_id:UUID):return await _transition(client_session_id,"pause")


@router.post("/api/client/v1/sessions/{client_session_id}/resume",response_model=ClientSessionResponse)
async def resume_v1_session(client_session_id:UUID):return await _transition(client_session_id,"resume")


@router.get("/api/client/v1/sessions/{client_session_id}/reconciliation",response_model=ReconciliationResponse)
async def reconcile_v1_session(client_session_id:UUID):
    item=_session_or_404(client_session_id)
    result=reconciliation(client_session_id)
    if result is None:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return _public_reconciliation(result,item)


@router.post("/api/client/v1/sessions/{client_session_id}/finish",response_model=FinishResponse)
async def finish_v1_session(client_session_id:UUID,request:FinishRequest):
    existing=_session_or_404(client_session_id)
    final_sequence=request.final_sequence+1 if _zero_based(existing) else request.final_sequence
    try:item=finish_client_session(client_session_id,final_sequence,request.final_source_end_ms)
    except ClientSessionConflict as exc:_conflict(exc)
    if not item:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return {"session":_public_session(item),"completion_status":completion_status(client_session_id),
            "reconciliation":_public_reconciliation(reconciliation(client_session_id),item)}


@router.post("/api/client/v1/sessions/{client_session_id}/finalize",response_model=ClientSessionResponse)
async def finalize_v1_session(client_session_id:UUID):
    try:item=finalize_client_session(client_session_id)
    except ClientSessionConflict as exc:_conflict(exc)
    if not item:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return _public_session(item)


@router.post("/api/client/v1/sessions/{client_session_id}/abort",response_model=ClientSessionResponse)
async def abort_v1_session(client_session_id:UUID,request:AbortRequest=AbortRequest()):
    try:item=abort_client_session(client_session_id,request.reason)
    except ClientSessionConflict as exc:_conflict(exc)
    if not item:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return _public_session(item)


@router.post("/api/client/v1/sessions/{client_session_id}/audio-chunks",status_code=201,response_model=AudioAckResponse)
async def upload_v1_audio(client_session_id:UUID,audio:UploadFile=File(...),sequence:int=Form(...),
        client_chunk_id:str=Form(...),duration_ms:int=Form(...),source_start_ms:int=Form(...),source_end_ms:int=Form(...),
        captured_at:datetime|None=Form(None),content_hash:str|None=Form(None),codec:str|None=Form(None),
        sample_rate_hz:int|None=Form(None),channels:int|None=Form(None)):
    item=_session_or_404(client_session_id)
    if item["state"] not in ("recording","paused","draining") and not (
            item["state"]=="created" and item["capture_mode"]=="memo"):
        raise ClientAPIError(409,"SESSION_STATE_CONFLICT",f"audio is not accepted in state {item['state']}","user_action")
    if sequence<(0 if _zero_based(item) else 1) or duration_ms<=0 or source_start_ms<0 or source_end_ms<=source_start_ms:
        raise ClientAPIError(422,"AUDIO_METADATA_INVALID","Audio sequence, duration or source range is invalid.","never")
    storage_sequence=sequence+1 if _zero_based(item) else sequence
    if item["expected_final_sequence"] is not None and storage_sequence>item["expected_final_sequence"]:
        record_upload_conflict(client_session_id,storage_sequence,client_chunk_id,"UPLOAD_HORIZON_CLOSED",
                               {"max_sequence":item["expected_final_sequence"]},{"sequence":storage_sequence})
        raise ClientAPIError(409,"UPLOAD_HORIZON_CLOSED","The chunk is beyond the declared final sequence.","user_action")
    data=await audio.read(CLIENT_AUDIO_MAX_CHUNK_BYTES+1)
    if not data:raise ClientAPIError(422,"AUDIO_EMPTY","Audio file must not be empty.","never")
    if len(data)>CLIENT_AUDIO_MAX_CHUNK_BYTES:
        raise ClientAPIError(413,"AUDIO_TOO_LARGE","Audio chunk exceeds the negotiated byte limit.","never",{"max_bytes":CLIENT_AUDIO_MAX_CHUNK_BYTES})
    with get_db_connection() as c:
        previous=c.execute("SELECT source_end_ms FROM audio_chunks WHERE session_id=%s AND sequence<%s ORDER BY sequence DESC LIMIT 1",(item["ingestion_session_id"],storage_sequence)).fetchone()
        following=c.execute("SELECT source_start_ms FROM audio_chunks WHERE session_id=%s AND sequence>%s ORDER BY sequence LIMIT 1",(item["ingestion_session_id"],storage_sequence)).fetchone()
    if (previous and source_start_ms<previous[0]) or (following and source_end_ms>following[0]):
        record_upload_conflict(client_session_id,storage_sequence,client_chunk_id,"AUDIO_TIMELINE_OVERLAP",
                               {"previous_end_ms":previous[0] if previous else None,"following_start_ms":following[0] if following else None},
                               {"source_start_ms":source_start_ms,"source_end_ms":source_end_ms})
        raise ClientAPIError(409,"AUDIO_TIMELINE_OVERLAP","Audio source ranges must be monotonic; pause gaps are allowed.","user_action")
    try:
        result=create_audio_chunk(item["ingestion_session_id"],storage_sequence,client_chunk_id,data,audio.content_type or "application/octet-stream",
                                  duration_ms,source_start_ms,source_end_ms,captured_at,codec,sample_rate_hz,channels,content_hash)
    except AudioChunkConflictError as exc:
        record_upload_conflict(client_session_id,storage_sequence,client_chunk_id,"AUDIO_IDENTITY_CONFLICT",received={"content_hash":content_hash})
        raise ClientAPIError(409,"AUDIO_IDENTITY_CONFLICT",str(exc),"user_action") from exc
    except ValueError as exc:
        raise ClientAPIError(422,"AUDIO_METADATA_INVALID",str(exc),"never") from exc
    chunk={key:value for key,value in result.items() if key not in ("id","session_id","storage_key")}
    if _zero_based(item):chunk["sequence"]-=1
    return {"client_session_id":str(client_session_id),"chunk":chunk,"durable_ack":True}


@router.post("/api/client/v1/diagnostics/audio-upload-test",response_model=AudioDiagnosticResponse)
async def diagnostic_audio_upload(audio:UploadFile=File(...)):
    data=await audio.read(CLIENT_AUDIO_MAX_CHUNK_BYTES+1)
    if not data:raise ClientAPIError(422,"AUDIO_EMPTY","Audio file must not be empty.","never")
    if len(data)>CLIENT_AUDIO_MAX_CHUNK_BYTES:
        raise ClientAPIError(413,"AUDIO_TOO_LARGE","Audio chunk exceeds the negotiated byte limit.","never",{"max_bytes":CLIENT_AUDIO_MAX_CHUNK_BYTES})
    return diagnose_audio_bytes(data,audio.content_type)


def _dashboard_payload(snapshot,surface):
    """Serialise a dashboard snapshot for one surface.

    On the e-paper surface the components leave out their absent fields instead
    of carrying them as null. Pydantic fills every optional field of
    DashboardComponent on the way out, which quietly put back most of what the
    projection had just removed — a 5353 byte snapshot left the server as 9277
    bytes of JSON, and the size guard, which measured the snapshot rather than
    the response, saw none of it. The device cannot tell the two apart anyway:
    cJSON returns NULL for a missing key and for a null one alike.

    Only the components. The envelope keeps its nulls on every surface, because
    the contract distinguishes `null` from absent and `primary_live_session:
    null` is a statement — no session is live — not a field nobody filled in.
    """
    if surface!=ESP_SURFACE:return snapshot
    validated=DashboardResponse.model_validate(snapshot)
    payload=validated.model_dump(mode="json")
    payload["sections"]=[section.model_dump(mode="json",exclude_none=True)
                         for section in validated.sections]
    return JSONResponse(payload)


@router.get("/api/client/v1/dashboard",response_model=DashboardResponse)
async def get_v1_dashboard(surface:Literal["default","esp32_epaper"]="default"):
    return _dashboard_payload(dashboard_snapshot(surface=surface),surface)


@router.get("/api/client/v1/sessions/{client_session_id}/dashboard",response_model=DashboardResponse)
async def get_v1_session_dashboard(client_session_id:UUID):
    result=dashboard_snapshot(client_session_id)
    if result is None:raise ClientAPIError(404,"SESSION_NOT_FOUND","Client session not found.","never")
    return result


def _dashboard_stream(request,client_session_id=None,surface="default"):
    async def events():
        raw=request.headers.get("last-event-id");last=int(raw) if raw and raw.isdigit() else 0
        while not await request.is_disconnected():
            snapshot=dashboard_snapshot(client_session_id,surface)
            if snapshot is None:
                yield "event: error\ndata: {\"code\":\"SESSION_NOT_FOUND\"}\n\n";return
            revision=snapshot["revision"]
            if revision>last:
                last=revision;payload=json.dumps(snapshot,ensure_ascii=False,separators=(",",":"))
                yield f"id: {revision}\nevent: dashboard\ndata: {payload}\n\n"
            else:yield ": keepalive\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@router.get("/api/client/v1/dashboard/events",response_class=StreamingResponse,responses={200:{"description":"Dashboard SSE stream","content":{"text/event-stream":{"schema":{"type":"string","contentMediaType":"text/event-stream","x-event-data-schema":{"$ref":"#/components/schemas/DashboardSSEEvent"}}}}}})
async def stream_v1_dashboard(request:Request,surface:Literal["default","esp32_epaper"]="default"):return _dashboard_stream(request,surface=surface)


@router.get("/api/client/v1/sessions/{client_session_id}/dashboard/events",response_class=StreamingResponse,responses={200:{"description":"Session dashboard SSE stream","content":{"text/event-stream":{"schema":{"type":"string","contentMediaType":"text/event-stream","x-event-data-schema":{"$ref":"#/components/schemas/DashboardSSEEvent"}}}}}})
async def stream_v1_session_dashboard(client_session_id:UUID,request:Request):
    _session_or_404(client_session_id)
    return _dashboard_stream(request,client_session_id)


@router.get("/api/client/v1/knowledge/libraries",response_model=LibrariesResponse)
async def get_v1_knowledge_libraries():return {"libraries":list_libraries()}


def _sync_error(exc):
    if isinstance(exc,SyncCursorExpired):raise ClientAPIError(410,"SYNC_CURSOR_EXPIRED",str(exc),"user_action",{"required_action":"full_resync"}) from exc
    raise ClientAPIError(400,"SYNC_CURSOR_INVALID",str(exc),"never") from exc


@router.get("/api/client/v1/knowledge/snapshot",response_model=KnowledgeSnapshotResponse)
async def get_v1_knowledge_snapshot(cursor:str|None=None,limit:int=200):
    try:return initial_page(cursor,limit)
    except (SyncCursorExpired,SyncCursorInvalid) as exc:_sync_error(exc)


@router.get("/api/client/v1/knowledge/delta",response_model=KnowledgeDeltaResponse)
async def get_v1_knowledge_delta(cursor:str,limit:int=200):
    try:return delta_page(cursor,limit)
    except (SyncCursorExpired,SyncCursorInvalid) as exc:_sync_error(exc)


@router.get("/api/client/v1/knowledge/entities/{entity_id}",response_model=KnowledgeEntityResponse)
async def get_v1_knowledge_entity(entity_id:UUID):
    result=get_synced_entity(entity_id)
    if result is None:raise ClientAPIError(404,"KNOWLEDGE_NOT_FOUND","Knowledge entity not found.","never")
    return result


@router.get("/api/client/v1/entities/{entity_type}/{entity_id}",response_model=DashboardEntityResponse)
async def get_v1_dashboard_entity(entity_type:str,entity_id:UUID):
    result=get_dashboard_entity(entity_type,entity_id)
    if result is None:raise ClientAPIError(404,"ENTITY_NOT_FOUND","Client entity not found.","never")
    return result


@router.post("/api/client/v1/knowledge/usage",response_model=UsageResponse)
async def post_v1_knowledge_usage(request:KnowledgeUsageBatch):
    try:return record_usage_batch(request.batch_id,request.client_installation_id,[item.model_dump() for item in request.items])
    except UsageBatchConflict as exc:raise ClientAPIError(409,"USAGE_BATCH_CONFLICT",str(exc),"user_action") from exc


@router.post("/api/client/v1/conversations",status_code=201,response_model=ConversationCreatedResponse)
async def create_v1_conversation(request:ConversationCreate):
    try:return create_conversation(request.client_conversation_id,request.client_message_id,request.client_turn_id,request.content)
    except ConversationConflict as exc:raise ClientAPIError(409,"CHAT_IDEMPOTENCY_CONFLICT",str(exc),"user_action") from exc


@router.get("/api/client/v1/conversations",response_model=ConversationListResponse)
async def list_v1_conversations():return {"conversations":list_conversations()}


@router.get("/api/client/v1/conversations/{conversation_id}",response_model=ConversationDetailResponse)
async def get_v1_conversation(conversation_id:UUID):
    item=get_conversation(conversation_id)
    if not item:raise ClientAPIError(404,"CONVERSATION_NOT_FOUND","Conversation not found.","never")
    return {"conversation":item,"messages":list_messages(conversation_id)}


@router.post("/api/client/v1/conversations/{conversation_id}/turns",status_code=201,response_model=TurnResponse)
async def create_v1_conversation_turn(conversation_id:UUID,request:ConversationTurnCreate):
    try:item=add_turn(conversation_id,request.client_message_id,request.client_turn_id,request.content)
    except ConversationConflict as exc:raise ClientAPIError(409,"CHAT_IDEMPOTENCY_CONFLICT",str(exc),"user_action") from exc
    if not item:raise ClientAPIError(404,"CONVERSATION_NOT_FOUND","Conversation not found.","never")
    return item


@router.get("/api/client/v1/conversation-turns/{turn_id}",response_model=TurnResponse)
async def get_v1_conversation_turn(turn_id:UUID):
    item=get_turn(turn_id)
    if not item:raise ClientAPIError(404,"TURN_NOT_FOUND","Conversation turn not found.","never")
    return item


@router.post("/api/client/v1/conversation-turns/{turn_id}/abort",response_model=TurnResponse)
async def abort_v1_conversation_turn(turn_id:UUID):
    try:item=abort_turn(turn_id)
    except ConversationConflict as exc:raise ClientAPIError(409,"TURN_STATE_CONFLICT",str(exc),"user_action") from exc
    if not item:raise ClientAPIError(404,"TURN_NOT_FOUND","Conversation turn not found.","never")
    return item


@router.post("/api/client/v1/conversation-turns/{turn_id}/retry",response_model=TurnResponse)
async def retry_v1_conversation_turn(turn_id:UUID):
    try:item=retry_turn(turn_id)
    except ConversationConflict as exc:raise ClientAPIError(409,"TURN_STATE_CONFLICT",str(exc),"user_action") from exc
    if not item:raise ClientAPIError(404,"TURN_NOT_FOUND","Conversation turn not found.","never")
    return item


@router.get("/api/client/v1/conversation-turns/{turn_id}/events",response_class=StreamingResponse,responses={200:{"description":"Conversation turn SSE stream","content":{"text/event-stream":{"schema":{"type":"string","contentMediaType":"text/event-stream","x-event-data-schema":{"$ref":"#/components/schemas/ChatSSEEvent"}}}}}})
async def stream_v1_conversation_turn(turn_id:UUID,request:Request):
    if get_turn(turn_id) is None:raise ClientAPIError(404,"TURN_NOT_FOUND","Conversation turn not found.","never")
    async def events():
        raw=request.headers.get("last-event-id");after=int(raw) if raw and raw.isdigit() else 0
        while not await request.is_disconnected():
            items=turn_events(turn_id,after) or []
            if items:
                for item in items:
                    after=item["sequence"];payload=json.dumps(item["payload"],ensure_ascii=False,separators=(",",":"))
                    yield f"id: {after}\nevent: {item['type']}\ndata: {payload}\n\n"
                if items[-1]["type"] in ("completed","failed","aborted"):return
            else:yield ": keepalive\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@router.post("/api/workers/client-chat/run-once")
async def run_client_chat_worker_once(request:ChatWorkerRequest):
    if request.mode not in ("llm","deterministic"):raise ClientAPIError(422,"CHAT_MODE_INVALID","Unsupported worker mode.","never")
    return await run_chat_turn_once(request.mode,request.deterministic_text)


@router.post("/api/client/v1/push/registrations",status_code=202,response_model=PushRegistrationCreateResponse)
async def create_v1_push_registration(request:PushRegistrationCreate):
    try:return await register_push(request.registration_id,request.client_installation_id,request.distributor,request.endpoint,request.client_public_key)
    except ValueError as exc:raise ClientAPIError(422,"PUSH_REGISTRATION_INVALID",str(exc),"never") from exc
    except PushRegistrationConflict as exc:raise ClientAPIError(409,"PUSH_REGISTRATION_CONFLICT",str(exc),"user_action") from exc


@router.get("/api/client/v1/push/registrations",response_model=PushRegistrationListResponse)
async def get_v1_push_registrations(client_installation_id:UUID|None=None):return {"registrations":list_registrations(client_installation_id)}


@router.post("/api/client/v1/push/registrations/{registration_id}/confirm",response_model=PushRegistration)
async def confirm_v1_push_registration(registration_id:UUID,request:PushChallengeConfirm):
    try:item=confirm_push(registration_id,request.challenge)
    except PushRegistrationConflict as exc:raise ClientAPIError(409,"PUSH_CHALLENGE_INVALID",str(exc),"user_action") from exc
    if item is None:raise ClientAPIError(404,"PUSH_REGISTRATION_NOT_FOUND","Push registration not found.","never")
    return item


@router.delete("/api/client/v1/push/registrations/{registration_id}",status_code=204)
async def delete_v1_push_registration(registration_id:UUID):
    if not unregister_push(registration_id):raise ClientAPIError(404,"PUSH_REGISTRATION_NOT_FOUND","Push registration not found.","never")


@router.post("/api/client/v1/captures",status_code=202,response_model=CaptureResponse)
async def create_v1_capture(request:TextCaptureCreate):
    try:return create_capture(request.client_capture_id,request.mode,request.content,request.context_ref)
    except CaptureConflict as exc:raise ClientAPIError(409,"CAPTURE_IDEMPOTENCY_CONFLICT",str(exc),"user_action") from exc


@router.get("/api/client/v1/captures/{capture_id}",response_model=CaptureResponse)
async def get_v1_capture(capture_id:UUID):
    item=get_capture(capture_id)
    if item is None:raise ClientAPIError(404,"CAPTURE_NOT_FOUND","Capture not found.","never")
    return item


@router.post("/api/workers/client-capture/run-once")
async def run_client_capture_worker_once(request:CaptureWorkerRequest):
    if request.mode not in ("production","deterministic"):raise ClientAPIError(422,"CAPTURE_MODE_INVALID","Unsupported capture worker mode.","never")
    return await run_capture_once(request.mode)
