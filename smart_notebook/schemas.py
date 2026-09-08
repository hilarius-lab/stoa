# Smart Notebook API schemas
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator

from .config import (
    KNOWLEDGE_RETRIEVAL_LIMIT, KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY,
    NOTE_CLEANUP_CANDIDATE_SIMILARITY, NOTE_CLEANUP_MAX_GROUPS
)

class Message(BaseModel):
    text: str

class IngestionSessionCreate(BaseModel):
    source_type: str
    title: str | None = None
    source: str | None = None
    started_at: datetime | None = None

class IngestionChunkCreate(BaseModel):
    sequence: int = Field(ge=1)
    client_chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_start_ms: int | None = Field(default=None, ge=0)
    source_end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_source_range(self):
        if (
            self.source_start_ms is not None
            and self.source_end_ms is not None
            and self.source_end_ms < self.source_start_ms
        ):
            raise ValueError(
                "source_end_ms must be greater than or equal to source_start_ms"
            )

        return self

class ProcessingJobCreate(BaseModel):
    job_type: str = Field(min_length=1)
    ingestion_session_id: int | None = Field(default=None, ge=1)
    chunk_id: int | None = Field(default=None, ge=1)
    sequence: int | None = Field(default=None, ge=1)
    payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1)
    available_at: datetime | None = None

class ProcessingJobClaim(BaseModel):
    worker_id: str = Field(min_length=1)
    job_type: str | None = Field(default=None, min_length=1)
    ingestion_session_id: int | None = Field(default=None, ge=1)

class ProcessingJobComplete(BaseModel):
    worker_id: str = Field(min_length=1)
    result: dict = Field(default_factory=dict)

class ProcessingJobFail(BaseModel):
    worker_id: str = Field(min_length=1)
    error: str = Field(min_length=1)

class ProcessingJobRetry(BaseModel):
    available_at: datetime | None = None

class IngestionSessionRepairRequest(BaseModel):
    dry_run: bool = True
    stale_after_minutes: int = Field(default=15, ge=1, le=10080)

class TextProcessingRunOnceRequest(BaseModel):
    worker_id: str = Field(default="text-worker-manual", min_length=1)
    mode: Literal["llm", "deterministic"] = "llm"
    ingestion_session_id: int | None = Field(default=None, ge=1)

class SessionArtifactWorkerRunOnceRequest(BaseModel):
    worker_id: str = Field(default="artifact-worker-manual", min_length=1)
    mode: Literal["llm", "deterministic"] = "llm"
    ingestion_session_id: int | None = Field(default=None, ge=1)

class SessionArtifactUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)

class SessionArtifactSupersede(BaseModel):
    artifact_type: Literal["note", "task", "list", "list_item", "fact", "decision"]
    content: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

class SessionTopicCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)

class SessionTopicUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

class SessionArtifactTopicLink(BaseModel):
    topic_id: int = Field(ge=1)
    relation: Literal["primary_topic", "related_topic", "project", "person", "document"] = "primary_topic"
    confidence: float = Field(default=1.0, ge=0, le=1)

class SessionQuestionCreate(BaseModel):
    question_text: str = Field(min_length=1)
    question_kind: Literal["explicit", "implicit"] = "explicit"
    confidence: float = Field(default=1.0, ge=0, le=1)
    priority: float = Field(default=0.5, ge=0, le=1)
    topic_id: int | None = Field(default=None, ge=1)
    segment_ids: list[int] = Field(default_factory=list)

class SessionQuestionAnswer(BaseModel):
    answer_text: str = Field(min_length=1)
    answer_source: Literal["personal_knowledge", "meeting", "manual", "external"] = "manual"

class SessionQuestionBudgetUpdate(BaseModel):
    max_open_questions: int = Field(default=12, ge=0, le=1000)
    max_questions_per_topic: int = Field(default=4, ge=0, le=100)

class SessionFinalizeRequest(BaseModel):
    force: bool = False
    promotion_mode: Literal["llm","deterministic","none"] = "llm"

class KnowledgeActivityCreate(BaseModel):
    knowledge_type: Literal["note","task","list","list_item","session_artifact","topic"]
    knowledge_id: int = Field(ge=1)
    activity_type: Literal["retrieved","activated","displayed","opened","cited","updated"]
    session_id: int | None = Field(default=None, ge=1)
    metadata: dict = Field(default_factory=dict)

class AudioSTTRunOnceRequest(BaseModel):
    worker_id: str = Field(default="audio-stt-manual",min_length=1)
    mode: Literal["ocean","deterministic"] = "ocean"
    ingestion_session_id: int | None = Field(default=None,ge=1)
    deterministic_text: str = "Deterministisches Testtranskript."

class ArtifactPromotionRequest(BaseModel):
    mode: Literal["llm","deterministic"] = "llm"

class EventCreate(BaseModel):
    text: str
    created_at: datetime | None = None
    source: str = "api"
    client_event_id: str | None = None

class EventBatch(BaseModel):
    events: list[EventCreate]

class NoteCreate(BaseModel):
    content: str
    source_event_id: int | None = None

class NoteUpdate(BaseModel):
    content: str

class TaskCreate(BaseModel):
    content: str
    work_start_at: datetime | None = None
    due_at: datetime | None = None
    priority: int = Field(default=0, ge=0, le=9)
    urgency: float | None = Field(default=None, ge=0, le=1)
    percent_complete: int = Field(default=0, ge=0, le=100)
    source_event_id: int | None = None

    @model_validator(mode="after")
    def require_due_or_urgency(self):
        if self.due_at is None and self.urgency is None:
            raise ValueError("Task requires due_at or explicitly assessed urgency")
        return self

class TaskUpdate(BaseModel):
    content: str | None = None
    work_start_at: datetime | None = None
    clear_work_start_at: bool = False
    due_at: datetime | None = None
    clear_due_at: bool = False
    priority: int | None = Field(default=None, ge=0, le=9)
    urgency: float | None = Field(default=None, ge=0, le=1)
    percent_complete: int | None = Field(default=None, ge=0, le=100)

class NoteSearch(BaseModel):
    query: str
    limit: int = 5

class KnowledgeSearch(BaseModel):
    query: str
    limit: int = KNOWLEDGE_RETRIEVAL_LIMIT
    types: list[str] | None = None
    min_similarity: float | None = KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY

class NoteCleanupRequest(BaseModel):
    dry_run: bool = True
    candidate_similarity: float = NOTE_CLEANUP_CANDIDATE_SIMILARITY
    max_groups: int = NOTE_CLEANUP_MAX_GROUPS

class ListCreate(BaseModel):
    title: str
    description: str = ""

class ListUpdate(BaseModel):
    title: str | None = None
    description: str | None = None

class ListItemCreate(BaseModel):
    content: str
    source_event_id: int | None = None

class ListItemUpdate(BaseModel):
    content: str

class ClaimCreate(BaseModel):
    claim_type: Literal["fact","opinion","prediction","requirement","decision"]
    statement: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_value: str | None = None
    polarity: Literal["positive","negative"] = "positive"
    modality: Literal["asserted","required","probable","possible","uncertain"] = "asserted"
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_knowledge_type: str | None = None
    source_knowledge_id: int | None = Field(default=None, ge=1)
    derived: bool = False
    metadata: dict = Field(default_factory=dict)

class ClaimEvidenceCreate(BaseModel):
    evidence_quote_id: int | None = Field(default=None, ge=1)
    source_identity_id: int | None = Field(default=None, ge=1)
    source_type: str = Field(min_length=1)
    source_id: str | None = None
    relation: Literal["supports","contradicts","mentions"] = "supports"
    excerpt: str = Field(min_length=1)
    source_quality: float | None = Field(default=None, ge=0, le=1)
    expertise: float | None = Field(default=None, ge=0, le=1)
    independence: float | None = Field(default=None, ge=0, le=1)
    directness: float | None = Field(default=None, ge=0, le=1)
    recency: float | None = Field(default=None, ge=0, le=1)
    evidence_strength: float | None = Field(default=None, ge=0, le=1)
    extraction_confidence: float = Field(default=1.0, ge=0, le=1)
    metadata: dict = Field(default_factory=dict)

class ClaimRelationCreate(BaseModel):
    target_claim_id: int = Field(ge=1)
    relation: Literal["supports","contradicts","qualifies","supersedes","equivalent_to","derived_from","applies_to","broader_than","narrower_than"]
    confidence: float = Field(default=1.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)

class ConflictDetectionRequest(BaseModel):
    claim_ids: list[int] = Field(default_factory=list)
    dry_run: bool = True

class SemanticShadowRunRequest(BaseModel):
    mode: Literal["llm_only","deterministic_test"] = "llm_only"

class ClaimCandidateExtractionRequest(BaseModel):
    mode: Literal["llm","deterministic_test"] = "llm"

class EvidenceSourceCreate(BaseModel):
    source_type: str = Field(min_length=1)
    provider: str | None = None
    external_id: str | None = None
    display_name: str | None = None
    privacy_class: Literal["local_only","pseudonymizable","anonymizable","public"] = "local_only"
    metadata: dict = Field(default_factory=dict)

class NightRepairRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)

class NightlyConsolidationRequest(BaseModel):
    dry_run: bool = True
    semantic_review: bool = True
    limit: int = Field(default=40, ge=1, le=200)

class KnowledgeTopicRelationCreate(BaseModel):
    child_topic_id: int = Field(ge=1)
    relation: Literal["parent","broader_than"] = "parent"
    confidence: float = Field(default=1.0, ge=0, le=1)
