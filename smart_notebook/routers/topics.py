# Session topic routes
from fastapi import APIRouter,HTTPException
from ..schemas import SessionTopicCreate,SessionTopicUpdate,SessionArtifactTopicLink,KnowledgeTopicRelationCreate
from ..services.topics import *
router=APIRouter()

@router.post("/api/ingestion-sessions/{session_id}/topics")
async def create_session_topic(session_id:int,topic:SessionTopicCreate):
    result=create_session_topic_record(session_id,topic.title,topic.description,topic.confidence)
    if result is None:raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/ingestion-sessions/{session_id}/topics")
async def get_session_topics(session_id:int,include_inactive:bool=False):
    result=list_session_topic_records(session_id,include_inactive)
    if result is None:raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/session-topics/{topic_id}")
async def get_session_topic(topic_id:int):
    result=get_session_topic_record(topic_id)
    if result is None:raise HTTPException(404,"Session topic not found")
    return result

@router.patch("/api/session-topics/{topic_id}")
async def update_session_topic(topic_id:int,update:SessionTopicUpdate):
    try: result=update_session_topic_record(topic_id,update.title,update.description,update.confidence)
    except SessionTopicConflictError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if result is None:raise HTTPException(404,"Session topic not found")
    return result

@router.post("/api/session-artifacts/{artifact_id}/topics")
async def link_artifact_topic(artifact_id:int,link:SessionArtifactTopicLink):
    try: result=link_artifact_topic_record(artifact_id,link.topic_id,link.relation,link.confidence)
    except SessionTopicConflictError as exc:raise HTTPException(409,str(exc)) from exc
    if result is None:raise HTTPException(404,"Artifact or topic not found")
    return result

@router.post("/api/knowledge-topics/{parent_topic_id}/relations")
async def create_knowledge_topic_relation(parent_topic_id:int,request:KnowledgeTopicRelationCreate):
    try:result=add_knowledge_topic_relation(parent_topic_id,request.child_topic_id,request.relation,request.confidence)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if result is None:raise HTTPException(404,"Knowledge topic not found")
    return result

@router.get("/api/knowledge/{knowledge_type}/{knowledge_id}/topics")
async def get_durable_knowledge_topics(knowledge_type:str,knowledge_id:int):
    return get_knowledge_topic_links(knowledge_type,knowledge_id)
