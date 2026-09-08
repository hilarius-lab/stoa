"""Normative response models for every public client API operation."""
from datetime import datetime
from typing import Any,Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,RootModel

JsonObject=dict[str,Any]
SessionState=Literal["created","recording","paused","draining","processing","completed","failed","attention_required","aborted"]
CompletionState=Literal["uploads_pending","processing","completed","failed","attention_required","aborted"]

class ExtensibleModel(BaseModel):model_config=ConfigDict(extra="allow")
class ErrorResponse(BaseModel):
    code:str;message:str;retry_class:Literal["never","immediate","backoff","network","user_action"]
    request_id:str;details:JsonObject=Field(default_factory=dict);timestamp:datetime
class HealthResponse(BaseModel):status:Literal["ok"];server_version:str;contract_version:str;time:datetime
class ContractInfo(BaseModel):current:str;supported:list[str];api_base:str
class ServerInfo(BaseModel):version:str;time:datetime
class FeatureInfo(BaseModel):
    audio_upload:bool;audio_upload_diagnostics:bool;session_recovery:bool;dashboard_snapshot:bool
    dashboard_sse:bool;offline_knowledge_sync:bool;chat:bool;unified_push:bool
class AudioProfile(BaseModel):
    id:str;mime_type:str;container:str;codec:str;sample_rate_hz:int|None;channels:int|None
    bitrate_bps:int|None;target_segment_ms:int;max_chunk_bytes:int
class LimitInfo(BaseModel):
    request_timeout_seconds:int;dashboard_cards_per_section:int;live_transcript_max_segments:int
    live_transcript_window_seconds:int;dashboard_history_hours:int
    dashboard_cache_max_age_seconds:int=Field(ge=0,le=604800,examples=[7200],description="Authoritative client snapshot freshness window; 0 means no server recommendation and the server default is 7200 seconds.")
    dashboard_title_max_chars:int;dashboard_preview_max_chars:int;dashboard_detail_max_chars:int;server_raw_audio_retention_days:int
    server_ephemeral_chat_retention_hours:int;server_technical_log_retention_hours:int
class DashboardCapabilities(BaseModel):
    schema_version:str;component_types:list[str];actions:list[str];color_roles:list[str]
    icon_tokens:list[str];border_roles:list[str];spacing_roles:list[str];preferred_spans:list[str]
    unknown_optional_component:str;unknown_required_component:str
class TransportCapabilities(BaseModel):
    rest:bool;sse:bool;unified_push:bool;foreground_refresh:str;background_refresh:str
    fallback_refresh:str;sse_proxy_buffering:bool
class CapabilitiesResponse(BaseModel):
    contract:ContractInfo;server:ServerInfo;status:str;status_message:str|None;features:FeatureInfo
    audio_profiles:list[AudioProfile];limits:LimitInfo;session_states:list[str]
    completion_states:list[str];dashboard:DashboardCapabilities;transports:TransportCapabilities

class ClientSessionResponse(BaseModel):
    client_session_id:UUID;state:SessionState;device_metadata:JsonObject;capture_mode:str
    sequence_base:Literal[0,1]=Field(description="Immutable wire sequence origin for this session; part of session identity.")
    context_ref:JsonObject|None;capture_result:JsonObject|None;expected_final_sequence:int|None
    final_source_end_ms:int|None;paused_at:datetime|None;finish_requested_at:datetime|None
    finalized_at:datetime|None;aborted_at:datetime|None;last_error:str|None
    local_audio_release_allowed:bool=Field(description="Monotone per-session server release; false never authorizes client audio deletion.")
    local_audio_release_at:datetime|None=Field(description="First and only time the session-wide local-audio release became true.")
    created_at:datetime;updated_at:datetime
class SessionListResponse(RootModel[list[ClientSessionResponse]]):pass
class ReconciliationChunk(BaseModel):
    sequence:int;client_chunk_id:str;content_hash:str;byte_length:int;status:str
    source_start_ms:int;source_end_ms:int;durable_ack:bool
class UploadConflict(BaseModel):
    sequence:int|None;client_chunk_id:str|None;code:str;expected:JsonObject;received:JsonObject;occurred_at:datetime
class ReconciliationResponse(BaseModel):
    client_session_id:UUID;state:SessionState;expected_final_sequence:int|None
    received_sequences:list[int];missing_sequences:list[int];chunks:list[ReconciliationChunk]
    conflicts:list[UploadConflict];upload_complete:bool
class FinishResponse(BaseModel):session:ClientSessionResponse;completion_status:CompletionState;reconciliation:ReconciliationResponse
class AudioChunkResponse(BaseModel):
    sequence:int;client_chunk_id:str;content_hash:str;byte_length:int;mime_type:str;codec:str|None
    sample_rate_hz:int|None;channels:int|None;duration_ms:int;source_start_ms:int;source_end_ms:int
    captured_at:datetime|None;status:str;retain_until:datetime|None;retain_permanently:bool
    created_at:datetime;updated_at:datetime
class AudioAckResponse(BaseModel):client_session_id:UUID;chunk:AudioChunkResponse;durable_ack:Literal[True]
class AudioDiagnosticResponse(BaseModel):
    compatible:bool;profile_id:str|None;declared_mime_type:str;detected_container:str|None
    detected_codec:str|None;sample_rate_hz:int|None;channels:int|None;bitrate_bps:int|None
    duration_ms:int|None;byte_length:int;reason_codes:list[str];durable_state_created:Literal[False]

class EntityRef(BaseModel):type:str;id:UUID
class DashboardAction(ExtensibleModel):type:str;params:JsonObject=Field(default_factory=dict)
class DashboardComponent(ExtensibleModel):
    component:str;required:bool;id:str|None=Field(default=None,description="Stable for the same focusable logical entity within a surface across revisions, text changes and reordering; rank and array position are not identity.");title:str|None=None;text:str|None=None
    preview:str|None=None;status:str|None=None;entity_ref:EntityRef|None=None;entity_type:str|None=None
    icon:str|None=None;color_role:str|None=None;border_role:str|None=None;spacing_role:str|None=None
    preferred_span:str|None=None;priority:float|None=None;action:DashboardAction|None=None
    items:list["DashboardComponent"]|None=None;layout:JsonObject|None=None;reason_code:str|None=None
    reason_text:str|None=None;rank:int|None=None;format:str|None=None;source_start_ms:int|None=None
    source_end_ms:int|None=None;severity:str|None=None;modes:list[str]|None=None;default_mode:str|None=None
class SessionSummary(BaseModel):client_session_id:UUID;state:SessionState
class ProcessingSummary(BaseModel):
    completion_status:CompletionState;watermarks:JsonObject|None;missing_sequences:list[int];upload_conflict_count:int
class DashboardResponse(BaseModel):
    schema_version:str;scope:str;mode:Literal["live","idle"];primary_live_session:SessionSummary|None
    sessions:list[SessionSummary];sections:list[DashboardComponent];processing:ProcessingSummary|None=None
    revision:int;generated_at:datetime;server_time:datetime
class DashboardSSEEvent(BaseModel):id:int;event:Literal["dashboard"];data:DashboardResponse

class LibraryStats(BaseModel):entity_count:int;latest_change_sequence:int;change_log_bytes:int
class KnowledgeLibrary(BaseModel):
    id:UUID;key:str;type:str;title:str;description:str;version:int;privacy_class:str
    offline_enabled:bool;sync_mode:str;scope:JsonObject;local_action:str;stats:LibraryStats;updated_at:datetime
class LibrariesResponse(BaseModel):libraries:list[KnowledgeLibrary]
class KnowledgeChange(BaseModel):operation:Literal["upsert","delete","redirect"];entity:JsonObject
class KnowledgeSnapshotResponse(BaseModel):
    mode:Literal["snapshot"];items:list[KnowledgeChange];next_cursor:str|None;complete_cursor:str|None
    has_more:bool;snapshot_sequence:int
class DeltaChange(KnowledgeChange):sequence:int
class KnowledgeDeltaResponse(BaseModel):mode:Literal["delta"];changes:list[DeltaChange];next_cursor:str;has_more:bool
class KnowledgeEntityResponse(KnowledgeChange):pass
class DashboardEntityResponse(ExtensibleModel):
    id:UUID;type:str;status:str;created_at:datetime;updated_at:datetime
    title:str|None=None;content:str|None=None;description:str|None=None;question:str|None=None
    question_kind:str|None=None;confidence:float|None=None;priority:float|None=None
    answer:str|None=None;answer_source:str|None=None
    work_start_at:datetime|None=None;due_at:datetime|None=None
    urgency:float|None=None;percent_complete:int|None=None
    items:list["DashboardListItem"]|None=None
    # Set only while the detail view offers a mutation beyond navigation —
    # a task that is still open, so far. Absent once there is nothing left
    # to do, same convention as an unimplemented action on a dashboard card:
    # the client acts on what is present, not on a fixed type per entity_type.
    action:DashboardAction|None=None
class DashboardListItem(BaseModel):
    id:UUID;content:str;status:Literal["active"]
class ListItemStatusUpdate(BaseModel):status:Literal["active","done"]
class ListItemStatusResponse(BaseModel):
    id:UUID;status:Literal["active","done"];updated_at:datetime
class UsageResponse(BaseModel):batch_id:UUID;accepted_count:int;idempotent:bool

class AgentInfo(BaseModel):key:str;display_name:str
class ConversationResponse(BaseModel):
    id:UUID;title:str;status:str;revision:int;agent:AgentInfo;created_at:datetime
    last_activity_at:datetime;dashboard_until:datetime
class TurnResponse(BaseModel):
    id:UUID;conversation_id:UUID;client_turn_id:UUID;user_message_id:UUID;assistant_message_id:UUID|None
    status:str;attempts:int;error:str|None;created_at:datetime;started_at:datetime|None
    completed_at:datetime|None;updated_at:datetime
class ConversationCreatedResponse(BaseModel):conversation:ConversationResponse;turn:TurnResponse
class ConversationListResponse(BaseModel):conversations:list[ConversationResponse]
class ChatMessage(BaseModel):id:UUID;sequence:int;role:str;content:str;content_format:str;created_at:datetime
class ConversationDetailResponse(BaseModel):conversation:ConversationResponse;messages:list[ChatMessage]
class ChatSSEEvent(BaseModel):sequence:int;type:Literal["started","delta","citation","action","completed","failed","aborted"];payload:JsonObject;created_at:datetime

class PushRegistration(BaseModel):
    id:UUID;client_installation_id:UUID;distributor:str;status:str;created_at:datetime
    updated_at:datetime;last_success_at:datetime|None;failure_count:int
class PushRegistrationCreateResponse(BaseModel):registration:PushRegistration;challenge_delivery:Literal["delivered","failed"]
class PushRegistrationListResponse(BaseModel):registrations:list[PushRegistration]
class CaptureResponse(BaseModel):
    id:UUID;mode:str;resolved_intent:str;content:str;context_ref:JsonObject|None;event_id:int|None
    conversation_id:UUID|None;turn_id:UUID|None;status:str;result:JsonObject|None;error:str|None
    created_at:datetime;updated_at:datetime
