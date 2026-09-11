"""W05 source-bound clarification answers and dependent action resumption."""
from datetime import datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from .capture_intent import get_session_intent_parts
from .intelligence import answer_question,get_question
from .mutation_actions import (ensure_session_mutation_actions,
    get_session_mutation_actions_for_question,resume_mutation_action)
from .mutation_targets import (get_session_mutation_target_resolutions_for_question,
    resume_mutation_target_resolution)


ATTEMPT_SELECT="""SELECT id,question_id,answer_session_id,answer_text,answer_source,status,result,
created_at,updated_at FROM clarification_answer_attempts"""


def _attempt(row):
    if not row:return None
    return {"id":row[0],"question_id":row[1],"answer_session_id":row[2],"answer_text":row[3],
            "answer_source":row[4],"status":row[5],"result":row[6] or {},
            "created_at":row[7].isoformat(),"updated_at":row[8].isoformat()}


def get_clarification_attempt(answer_session_id):
    with get_db_connection() as c:
        row=c.execute(ATTEMPT_SELECT+" WHERE answer_session_id=%s",(answer_session_id,)).fetchone()
    return _attempt(row)


def clarification_question_from_context(context):
    if not isinstance(context,dict) or context.get("type")!="clarification":return None
    try:public_id=UUID(str(context.get("id")))
    except (TypeError,ValueError,AttributeError):return None
    with get_db_connection() as c:
        row=c.execute("""SELECT q.id,q.status FROM client_entity_identities i
        JOIN session_questions q ON q.id=i.internal_id
        WHERE i.entity_type='question' AND i.public_id=%s""",(public_id,)).fetchone()
    return {"id":row[0],"status":row[1],"public_id":str(public_id)} if row else None


def clarification_detail_action(question_id,public_id,status):
    """Use the existing closed submit_capture action; params carry its fixed context."""
    if status!="open":return None
    params={"mode":"auto","context_ref":{"type":"clarification","id":str(public_id)}}
    resolutions=get_session_mutation_target_resolutions_for_question(question_id)
    if len(resolutions)==1 and "low_intent_confidence" in resolutions[0]["reason_codes"] and \
       len(resolutions[0]["candidate_keys"])==1:
        params.update({"label":"Ja","content":"Ja","answer_source":"suggested"})
        params["context_ref"]["answer_source"]="suggested"
    return {"type":"submit_capture","params":params}


def _answer_source(answer_session_id,context):
    if context.get("answer_source")=="suggested":return "suggested_answer"
    with get_db_connection() as c:
        row=c.execute("SELECT source_type FROM ingestion_sessions WHERE id=%s",(answer_session_id,)).fetchone()
    return "text_capture" if row and row[0]=="client_text_capture" else "audio_capture"


def _store_attempt(question_id,answer_session_id,answer,source):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("""INSERT INTO clarification_answer_attempts(question_id,answer_session_id,answer_text,
        answer_source,status,result,created_at,updated_at) VALUES(%s,%s,%s,%s,'processing','{}'::jsonb,%s,%s)
        ON CONFLICT(answer_session_id) DO NOTHING""",(question_id,answer_session_id,answer,source,now,now));c.commit()
        row=c.execute(ATTEMPT_SELECT+" WHERE answer_session_id=%s",(answer_session_id,)).fetchone()
    return _attempt(row)


def _finish_attempt(attempt,status,result):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("UPDATE clarification_answer_attempts SET status=%s,result=%s,updated_at=%s WHERE id=%s",
                  (status,Jsonb(result),now,attempt["id"]));c.commit()
        row=c.execute(ATTEMPT_SELECT+" WHERE id=%s",(attempt["id"],)).fetchone()
    return _attempt(row)


async def resolve_clarification_answer(answer_session_id,context,answer,mode="llm"):
    """Bind an answer to exactly one public question and resume only its dependency."""
    answer=" ".join((answer or "").split())
    if not answer:raise ValueError("Clarification answer must not be empty")
    existing=get_clarification_attempt(answer_session_id)
    if existing and existing["status"]!="processing":return existing["result"]
    reference=clarification_question_from_context(context)
    if not reference:raise ValueError("Clarification context is invalid or stale")
    source=_answer_source(answer_session_id,context)
    attempt=existing or _store_attempt(reference["id"],answer_session_id,answer,source)
    if attempt["answer_text"]!=answer or attempt["question_id"]!=reference["id"]:
        raise ValueError("Clarification answer session conflicts with its persisted context")
    question=get_question(reference["id"])
    if not question:raise ValueError("Clarification question no longer exists")
    target_resolutions=get_session_mutation_target_resolutions_for_question(reference["id"])
    action_resolutions=get_session_mutation_actions_for_question(reference["id"])
    if not target_resolutions and not action_resolutions:
        result={"question_id":reference["public_id"],"status":"needs_clarification",
                "action_status":"pending_clarification","reason_codes":["missing_dependency"]}
        _finish_attempt(attempt,"needs_clarification",result)
        return result
    parent_session=(target_resolutions[0]["session_id"] if target_resolutions
                    else action_resolutions[0]["session_id"])
    try:
        if target_resolutions:
            resolution=await resume_mutation_target_resolution(reference["id"],answer,mode)
            if resolution and resolution["status"]=="resolved":
                parts=get_session_intent_parts(parent_session)
                resumed=await ensure_session_mutation_actions(parent_session,parts,mode)
                dependent=next((item for item in resumed
                                if item["intent_part_id"]==resolution["intent_part_id"]),None)
                dependency_status=dependent["status"] if dependent else "planned"
            else:dependency_status=resolution["status"] if resolution else "unresolved"
        else:
            action=await resume_mutation_action(reference["id"],answer,mode)
            dependency_status=action["status"] if action else "clarification_required"
        if dependency_status in {"resolved","completed"}:
            final_status="completed";action_status="completed";reasons=["clarification_resolved"]
        elif dependency_status=="cancelled":
            final_status="cancelled";action_status="cancelled";reasons=["user_cancelled"]
        else:
            final_status="needs_clarification";action_status="pending_clarification"
            reasons=["insufficient_clarification"]
        if final_status in {"completed","cancelled"} and question["status"]=="open":
            answer_question(reference["id"],answer,source)
        result={"question_id":reference["public_id"],"status":final_status,
                "action_status":action_status,"reason_codes":reasons}
        _finish_attempt(attempt,final_status,result)
        from .client_sessions import refresh_capture_result_for_ingestion
        refresh_capture_result_for_ingestion(parent_session)
        return result
    except Exception:
        _finish_attempt(attempt,"failed",{"question_id":reference["public_id"],"status":"failed",
                                          "action_status":"failed","reason_codes":["processing_failed"]})
        raise
