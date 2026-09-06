# Maintenance routes
from fastapi import APIRouter

from ..schemas import NoteCleanupRequest,NightRepairRequest,NightlyConsolidationRequest
from ..services.maintenance import run_note_cleanup, run_daily_maintenance
from ..services.consolidation import consolidate_today
from ..services.jobs import queue_parked_jobs_for_night_repair
from ..services.nightly_consolidation import run_nightly_knowledge_consolidation

router = APIRouter()

@router.post("/api/maintenance/deduplicate-notes")
async def api_deduplicate_notes(
    request: NoteCleanupRequest
):
    return await run_note_cleanup(
        dry_run=request.dry_run,
        candidate_similarity=request.candidate_similarity,
        max_groups=request.max_groups
    )

@router.post("/api/maintenance/daily")
async def api_daily_maintenance():
    return await run_daily_maintenance()

@router.post("/api/maintenance/jobs/night-repair")
async def api_night_repair(request:NightRepairRequest):
    jobs=queue_parked_jobs_for_night_repair(request.limit)
    return {"queued_count":len(jobs),"jobs":jobs}

@router.post("/api/maintenance/nightly-consolidation")
async def api_nightly_consolidation(request:NightlyConsolidationRequest):
    return await run_nightly_knowledge_consolidation(request.dry_run,request.semantic_review,request.limit)

@router.post("/api/consolidate-today")
async def api_consolidate_today():
    return await consolidate_today()
