from typing import Literal
from uuid import UUID
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from ..services.reference_resolver import attach_candidate_to_claim,resolve_internal

router=APIRouter(tags=["references"])
class ResolveRequest(BaseModel):
    query:str=Field(min_length=1,max_length=2000)
    limit:int=Field(default=10,ge=1,le=20)
class AttachRequest(BaseModel):
    source_id:UUID
    quote:str=Field(min_length=1,max_length=5000)
    relation:Literal["supports","contradicts","mentions"]="supports"

@router.post("/api/references/resolve")
async def resolve_references(request:ResolveRequest):
    try:return await resolve_internal(request.query,request.limit)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.post("/api/claims/{claim_id}/reference-evidence")
async def attach_reference_evidence(claim_id:int,request:AttachRequest):
    try:item=attach_candidate_to_claim(claim_id,request.source_id,request.quote,request.relation)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    if item is None:raise HTTPException(404,"Claim not found")
    return item
