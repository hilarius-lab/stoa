# Live session artifact routes
from fastapi import APIRouter, HTTPException

from ..schemas import (
    SessionArtifactSupersede, SessionArtifactUpdate,
    SessionArtifactWorkerRunOnceRequest
    ,ArtifactPromotionRequest,SemanticShadowRunRequest
)
from ..services.artifacts import (
    SessionArtifactConflictError, get_session_artifact_record,
    list_session_artifact_records, run_session_artifact_worker_once,
    set_session_artifact_status, supersede_session_artifact_record,
    update_session_artifact_record
)
from ..services.promotion import promote_session_artifacts
from ..services.shadow import get_shadow_run,run_semantic_shadow
from ..services.semantic_examples import record_gold_example,seed_curated_examples,list_gold_examples
from ..services.observability import emit_event

router = APIRouter()

async def _learn_correction_safely(artifact,label):
    try:
        await record_gold_example(artifact["content"],artifact["artifact_type"],label,"user_correction",artifact["id"])
    except Exception as exc:
        emit_event("semantic_examples","correction_embedding_failed","warning",metadata={"artifact_id":artifact["id"],"error_type":type(exc).__name__})


@router.get("/api/ingestion-sessions/{session_id}/artifacts")
async def get_session_artifacts(session_id: int, include_inactive: bool = False):
    artifacts = list_session_artifact_records(session_id, include_inactive)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Ingestion session not found")
    return artifacts


@router.get("/api/session-artifacts/{artifact_id}")
async def get_session_artifact(artifact_id: int):
    artifact = get_session_artifact_record(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    return artifact


@router.patch("/api/session-artifacts/{artifact_id}")
async def update_session_artifact(artifact_id: int, update: SessionArtifactUpdate):
    try:
        artifact = update_session_artifact_record(
            artifact_id, update.content, update.confidence
        )
    except SessionArtifactConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    # PATCH is an explicit user correction; automatic confirmations never
    # become gold examples by themselves.
    await _learn_correction_safely(artifact,"positive")
    return artifact


def _status_result(artifact_id, status):
    try:
        artifact = set_session_artifact_status(artifact_id, status)
    except SessionArtifactConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    return artifact


@router.post("/api/session-artifacts/{artifact_id}/confirm")
async def confirm_session_artifact(artifact_id: int):
    return _status_result(artifact_id, "confirmed")


@router.post("/api/session-artifacts/{artifact_id}/dismiss")
async def dismiss_session_artifact(artifact_id: int):
    return _status_result(artifact_id, "dismissed")


@router.post("/api/session-artifacts/{artifact_id}/supersede")
async def supersede_session_artifact(
    artifact_id: int, replacement: SessionArtifactSupersede
):
    try:
        result = supersede_session_artifact_record(
            artifact_id, replacement.artifact_type,
            replacement.content, replacement.confidence
        )
    except SessionArtifactConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Session artifact not found")
    await _learn_correction_safely(result["replacement"],"positive")
    await _learn_correction_safely(result["superseded"],"negative")
    return result

@router.post("/api/semantic-gold-examples/seed")
async def seed_semantic_examples():
    return await seed_curated_examples()

@router.get("/api/semantic-gold-examples")
async def get_semantic_examples():
    return {"examples":list_gold_examples()}


@router.post("/api/workers/session-artifacts/run-once")
async def run_artifact_worker_once(request: SessionArtifactWorkerRunOnceRequest):
    return await run_session_artifact_worker_once(request.worker_id,request.mode,request.ingestion_session_id)

@router.post("/api/ingestion-sessions/{session_id}/artifacts/promote")
async def promote_artifacts(session_id:int,request:ArtifactPromotionRequest):
    return await promote_session_artifacts(session_id,request.mode)

@router.post("/api/ingestion-sessions/{session_id}/semantic-shadow")
async def run_shadow(session_id:int,request:SemanticShadowRunRequest):
    result=await run_semantic_shadow(session_id,request.mode)
    if result is None:raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/semantic-shadow-runs/{run_id}")
async def get_shadow(run_id:int):
    result=get_shadow_run(run_id)
    if result is None:raise HTTPException(404,"Shadow run not found")
    return result
