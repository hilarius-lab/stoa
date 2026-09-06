# Processing job routes
from fastapi import APIRouter, HTTPException

from ..schemas import (
    ProcessingJobClaim, ProcessingJobComplete, ProcessingJobCreate,
    ProcessingJobFail, ProcessingJobRetry
)
from ..services.jobs import (
    ProcessingJobConflictError, claim_processing_job_record,
    complete_processing_job_record, enqueue_processing_job_record,
    fail_processing_job_record, get_processing_job_record,
    list_processing_job_records, retry_processing_job_record,get_job_queue_metrics
)

router = APIRouter()

@router.get("/api/processing-jobs/metrics/summary")
async def get_processing_job_metrics():
    return get_job_queue_metrics()


@router.post("/api/processing-jobs")
async def create_processing_job(job: ProcessingJobCreate):
    try:
        return enqueue_processing_job_record(**job.model_dump())
    except ProcessingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/processing-jobs")
async def get_processing_jobs(status: str | None = None):
    try:
        return list_processing_job_records(status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/processing-jobs/claim")
async def claim_processing_job(request: ProcessingJobClaim):
    return claim_processing_job_record(
        worker_id=request.worker_id,
        job_type=request.job_type,
        ingestion_session_id=request.ingestion_session_id
    )


@router.get("/api/processing-jobs/{job_id}")
async def get_processing_job(job_id: int):
    job = get_processing_job_record(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.post("/api/processing-jobs/{job_id}/complete")
async def complete_processing_job(job_id: int, request: ProcessingJobComplete):
    try:
        job = complete_processing_job_record(
            job_id=job_id,
            worker_id=request.worker_id,
            result=request.result
        )
    except ProcessingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.post("/api/processing-jobs/{job_id}/fail")
async def fail_processing_job(job_id: int, request: ProcessingJobFail):
    try:
        job = fail_processing_job_record(
            job_id=job_id,
            worker_id=request.worker_id,
            error=request.error
        )
    except ProcessingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job


@router.post("/api/processing-jobs/{job_id}/retry")
async def retry_processing_job(job_id: int, request: ProcessingJobRetry):
    try:
        job = retry_processing_job_record(
            job_id=job_id,
            available_at=request.available_at
        )
    except ProcessingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job
