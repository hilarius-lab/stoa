from fastapi import APIRouter, HTTPException

from ..schemas import SessionFinalizeRequest, SessionQuestionAnswer, SessionQuestionBudgetUpdate, SessionQuestionCreate
from ..services.intelligence import answer_question, create_question, detect_questions, finalize_session, generate_evidence_quotes, list_evidence_quotes, list_questions, personal_knowledge_fast_path, reopen_question_record, set_budget
from ..services.promotion import promote_session_artifacts

router = APIRouter()

@router.post("/api/ingestion-sessions/{session_id}/evidence/generate")
async def generate_evidence(session_id:int):
    result=generate_evidence_quotes(session_id)
    if result is None: raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/ingestion-sessions/{session_id}/evidence")
async def get_evidence(session_id:int): return list_evidence_quotes(session_id)

@router.post("/api/ingestion-sessions/{session_id}/questions")
async def post_question(session_id:int, request:SessionQuestionCreate):
    try: result=create_question(session_id,request.question_text,request.question_kind,request.confidence,request.priority,request.topic_id,request.segment_ids)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    if result is None: raise HTTPException(404,"Ingestion session not found")
    return result

@router.get("/api/ingestion-sessions/{session_id}/questions")
async def get_questions(session_id:int): return list_questions(session_id)

@router.post("/api/ingestion-sessions/{session_id}/questions/detect")
async def detect_session_questions(session_id:int): return detect_questions(session_id)

@router.post("/api/session-questions/{question_id}/answer")
async def post_answer(question_id:int, request:SessionQuestionAnswer):
    result=answer_question(question_id,request.answer_text,request.answer_source)
    if result is None: raise HTTPException(404,"Session question not found")
    return result

@router.post("/api/session-questions/{question_id}/reopen")
async def reopen_question(question_id:int):
    question=reopen_question_record(question_id)
    if question is None: raise HTTPException(404,"Session question not found")
    return question

@router.put("/api/ingestion-sessions/{session_id}/question-budget")
async def put_budget(session_id:int, request:SessionQuestionBudgetUpdate): return set_budget(session_id,request.max_open_questions,request.max_questions_per_topic)

@router.get("/api/personal-knowledge/fast-path")
async def fast_path(q:str): return {"query":q,"external_research_needed":not bool(results:=personal_knowledge_fast_path(q)),"results":results}

@router.post("/api/ingestion-sessions/{session_id}/finalize")
async def finalize(session_id:int, request:SessionFinalizeRequest):
    try: result=finalize_session(session_id,request.force)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    if result is None: raise HTTPException(404,"Ingestion session not found")
    if request.promotion_mode!="none":result["promotion"]=await promote_session_artifacts(session_id,request.promotion_mode)
    return result
