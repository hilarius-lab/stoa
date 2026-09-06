from fastapi import APIRouter,HTTPException

from ..schemas import KnowledgeActivityCreate
from ..services.activity import calculate_signals,list_activity,list_signals,record_activity

router=APIRouter()

@router.post("/api/knowledge-activity")
async def create_activity(request:KnowledgeActivityCreate):
    result=record_activity(request.knowledge_type,request.knowledge_id,request.activity_type,request.session_id,request.metadata)
    if result is None:raise HTTPException(404,"Knowledge object not found")
    return result

@router.get("/api/knowledge-activity")
async def get_activity(knowledge_type:str|None=None,knowledge_id:int|None=None,activity_type:str|None=None,limit:int=100):
    return list_activity(knowledge_type,knowledge_id,activity_type,limit)

@router.post("/api/knowledge/{knowledge_type}/{knowledge_id}/signals/refresh")
async def refresh_signals(knowledge_type:str,knowledge_id:int):
    try:result=calculate_signals(knowledge_type,knowledge_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if result is None:raise HTTPException(404,"Knowledge object not found")
    return result

@router.get("/api/knowledge-signals")
async def get_signals(knowledge_type:str|None=None,limit:int=100):return list_signals(knowledge_type,limit)
