from fastapi import APIRouter, HTTPException, Query

from ..schemas import ClaimCreate, ClaimEvidenceCreate, ClaimRelationCreate, ConflictDetectionRequest,ClaimCandidateExtractionRequest,EvidenceSourceCreate
from ..services.claims import (
    add_claim_evidence_record, add_claim_relation_record, create_claim_record, detect_conflicts,
    get_claim_record, list_claim_records, list_conflict_cases,extract_note_claim_candidates,list_note_claim_candidates,
    create_evidence_source_record,list_evidence_source_records,run_changed_conflict_scan,
)

router=APIRouter()

@router.post("/api/claims")
async def create_claim(claim:ClaimCreate):
    try:return await create_claim_record(claim)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc

@router.get("/api/claims")
async def get_claims(status:str|None=None,subject:str|None=None,limit:int=Query(default=100,ge=1,le=1000)):
    return list_claim_records(status,subject,limit)

@router.get("/api/claims/{claim_id}")
async def get_claim(claim_id:int):
    result=get_claim_record(claim_id)
    if result is None:raise HTTPException(404,"Claim not found")
    return result

@router.post("/api/claims/{claim_id}/evidence")
async def add_claim_evidence(claim_id:int,evidence:ClaimEvidenceCreate):
    try:result=add_claim_evidence_record(claim_id,evidence)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if result is None:raise HTTPException(404,"Claim not found")
    return result

@router.post("/api/claims/{claim_id}/relations")
async def add_claim_relation(claim_id:int,relation:ClaimRelationCreate):
    try:result=add_claim_relation_record(claim_id,relation)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if result is None:raise HTTPException(404,"Claim not found")
    return result

@router.post("/api/conflicts/detect")
async def detect_claim_conflicts(request:ConflictDetectionRequest):
    return detect_conflicts(request.claim_ids,request.dry_run)

@router.get("/api/conflicts")
async def get_conflicts(status:str|None=None,limit:int=Query(default=100,ge=1,le=1000)):
    return list_conflict_cases(status,limit)

@router.post("/api/notes/{note_id}/claim-candidates")
async def extract_claim_candidates(note_id:int,request:ClaimCandidateExtractionRequest):
    result=await extract_note_claim_candidates(note_id,request.mode)
    if result is None:raise HTTPException(404,"Note not found")
    return result

@router.get("/api/notes/{note_id}/claim-candidates")
async def get_claim_candidates(note_id:int):
    result=list_note_claim_candidates(note_id)
    if result is None:raise HTTPException(404,"Note not found")
    return result

@router.post("/api/evidence-sources")
async def create_evidence_source(source:EvidenceSourceCreate):
    return create_evidence_source_record(source)

@router.get("/api/evidence-sources")
async def get_evidence_sources():
    return list_evidence_source_records()

@router.post("/api/maintenance/conflicts/scan")
async def scan_changed_conflicts(request:ConflictDetectionRequest):
    return await run_changed_conflict_scan(request.dry_run)
