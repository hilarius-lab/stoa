"""A07 planning and idempotent execution for resolved capture mutations."""
from datetime import datetime
import json
import re

import httpx
from psycopg.types.json import Jsonb

from ..config import EMBEDDING_MODEL,MUTATION_ACTION_MIN_CONFIDENCE,TIMEZONE
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .embeddings import embedding_to_pgvector,get_embedding
from .intelligence import create_question
from .mutation_targets import get_session_mutation_target_resolutions


OPERATIONS={"note_update","note_archive","task_update","task_complete","task_reopen","task_archive",
            "list_rename","list_add_item","list_archive","list_item_update","list_item_complete",
            "list_item_reopen","list_item_archive"}
CHANGE_OPERATIONS={
    "note":{"note_update"},"task":{"task_update","task_reopen"},
    "list":{"list_rename","list_add_item"},"list_item":{"list_item_update","list_item_reopen"},
}
VALUE_OPERATIONS={"note_update","task_update","list_rename","list_add_item","list_item_update"}
REASON_CODES={"intent_complete","intent_archive","content_update","add_item","reopen","model_selection",
              "low_confidence","unclear_operation","invalid_value","stale_target"}


ACTION_SELECT="""SELECT a.id,a.session_id,a.intent_part_id,a.target_resolution_id,a.operation,a.payload,
a.status,a.confidence,a.reason_codes,a.decision_source,a.before_state,a.after_state,a.clarification_question_id,
a.executed_at,a.error_code,a.created_at,a.updated_at,p.ordinal,p.primary_intent,r.target_type,r.target_id
FROM mutation_action_executions a JOIN session_intent_parts p ON p.id=a.intent_part_id
JOIN mutation_target_resolutions r ON r.id=a.target_resolution_id"""


def _item(row):
    if not row:return None
    return {"id":row[0],"session_id":row[1],"intent_part_id":row[2],"target_resolution_id":row[3],
            "operation":row[4],"payload":row[5] or {},"status":row[6],"confidence":row[7],
            "reason_codes":row[8] or [],"decision_source":row[9],"before_state":row[10],
            "after_state":row[11],"clarification_question_id":row[12],
            "executed_at":row[13].isoformat() if row[13] else None,"error_code":row[14],
            "created_at":row[15].isoformat(),"updated_at":row[16].isoformat(),"ordinal":row[17],
            "intent":row[18],"target_type":row[19],"target_id":row[20]}


def get_session_mutation_actions(session_id):
    with get_db_connection() as c:
        rows=c.execute(ACTION_SELECT+" WHERE a.session_id=%s ORDER BY p.ordinal,a.id",(session_id,)).fetchall()
    return [_item(row) for row in rows]


def _source_segment_ids(part):
    if part.get("source_segment_ids") is not None:return part["source_segment_ids"]
    with get_db_connection() as c:
        rows=c.execute("SELECT segment_id FROM session_intent_part_segments WHERE part_id=%s ORDER BY segment_id",
                       (part["id"],)).fetchall()
    return [row[0] for row in rows]


def _state(connection,target_type,target_id,lock=False):
    suffix=" FOR UPDATE" if lock else ""
    if target_type=="note":
        row=connection.execute("SELECT id,content,archived,archived_at,archive_reason FROM notes WHERE id=%s"+suffix,
                               (target_id,)).fetchone()
        keys=("id","content","archived","archived_at","archive_reason")
    elif target_type=="task":
        row=connection.execute("""SELECT id,content,status,archived,percent_complete,due_at,work_start_at,
        archived_at,archive_reason FROM tasks WHERE id=%s"""+suffix,(target_id,)).fetchone()
        keys=("id","content","status","archived","percent_complete","due_at","work_start_at","archived_at","archive_reason")
    elif target_type=="list":
        row=connection.execute("SELECT id,title,description,archived,archived_at,archive_reason FROM lists WHERE id=%s"+suffix,
                               (target_id,)).fetchone()
        keys=("id","title","description","archived","archived_at","archive_reason")
    else:
        row=connection.execute("""SELECT id,list_id,content,status,archived,archived_at,archive_reason
        FROM list_items WHERE id=%s"""+suffix,(target_id,)).fetchone()
        keys=("id","list_id","content","status","archived","archived_at","archive_reason")
    if not row:return None
    result=dict(zip(keys,row))
    for key,value in list(result.items()):
        if isinstance(value,datetime):result[key]=value.isoformat()
    return result


def _model_state(target_type,current):
    """Expose only fields that help the model choose the requested operation."""
    allowed={
        "note":("content","archived"),
        "task":("content","status","archived","percent_complete","due_at","work_start_at"),
        "list":("title","description","archived"),
        "list_item":("content","status","archived"),
    }[target_type]
    return {key:current.get(key) for key in allowed}


def _validate_change_plan(raw,part,resolution):
    if not isinstance(raw,dict):raise ValueError("Mutation action plan must be an object")
    status=raw.get("status");operation=raw.get("operation");new_text=raw.get("new_text")
    confidence=raw.get("confidence");reasons=raw.get("reason_codes")
    if status not in {"executable","clarification_required"}:raise ValueError("Unknown action plan status")
    if operation not in OPERATIONS|{"none"}:raise ValueError("Unknown action operation")
    if not isinstance(new_text,str):raise ValueError("Action new_text must be a string")
    new_text=new_text.strip()
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not 0<=confidence<=1:
        raise ValueError("Action plan confidence must be between 0 and 1")
    if not isinstance(reasons,list) or len(reasons)>8 or any(reason not in REASON_CODES for reason in reasons):
        raise ValueError("Unknown or excessive action reason codes")
    allowed=CHANGE_OPERATIONS[resolution["target_type"]]
    valid=status=="executable" and operation in allowed
    if valid and (operation in VALUE_OPERATIONS)!=(bool(new_text)):valid=False
    if valid and new_text and new_text not in part["source_text"]:valid=False
    if confidence<MUTATION_ACTION_MIN_CONFIDENCE:valid=False
    if not valid:
        reasons=list(dict.fromkeys(reasons+(["low_confidence"] if confidence<MUTATION_ACTION_MIN_CONFIDENCE else
            ["invalid_value"] if operation in VALUE_OPERATIONS else ["unclear_operation"])))
        return {"status":"clarification_required","operation":None,"payload":{},"confidence":float(confidence),
                "reason_codes":reasons}
    semantic_reason=("add_item" if operation=="list_add_item" else "reopen" if operation.endswith("_reopen")
                     else "content_update")
    reasons=list(dict.fromkeys(reasons+[semantic_reason,"model_selection"]))
    return {"status":"planned","operation":operation,"payload":{"new_text":new_text} if new_text else {},
            "confidence":float(confidence),"reason_codes":reasons}


async def _plan_change_with_llm(part,resolution,current):
    profile=get_ai_task_profile("capture.action_plan");allowed=sorted(CHANGE_OPERATIONS[resolution["target_type"]])
    schema={"type":"object","properties":{
        "status":{"type":"string","enum":["executable","clarification_required"]},
        "operation":{"type":"string","enum":["none",*allowed]},"new_text":{"type":"string"},
        "confidence":{"type":"number"},
        "reason_codes":{"type":"array","items":{"type":"string","enum":sorted(REASON_CODES)},"maxItems":8}},
        "required":["status","operation","new_text","confidence","reason_codes"],"additionalProperties":False}
    system=("Plane genau eine bereits auf ein Objekt aufgelöste Änderung. Nutze nur eine erlaubte Operation. "
        "Für update, rename oder add_item muss new_text eine exakte zusammenhängende Spanne der Nutzereingabe sein "
        "und nur den neuen Wert enthalten. Für reopen muss new_text leer sein. Ist Operation oder neuer Wert nicht "
        "eindeutig, antworte clarification_required/none. Führe nichts aus und erfinde nichts.")
    context={"intent":{"source_text":part["source_text"],"target_text":part["target_text"],
        "expected_target_type":part["target_type"]},"resolved_target":{"type":resolution["target_type"],
        "current":_model_state(resolution["target_type"],current)},"allowed_operations":allowed}
    payload={"model":profile["model"],"messages":[{"role":"system","content":system},
        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{"name":"smart_notebook_mutation_action","strict":True,
        "schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    raw=json.loads(response.json()["choices"][0]["message"]["content"])
    return _validate_change_plan(raw,part,resolution),f"{profile['provider']}:{profile['model']}"


def _deterministic_change_plan(part,resolution):
    text=part["source_text"];lower=text.casefold();target_type=resolution["target_type"]
    if re.search(r"\b(wieder\s+öffnen|wiedereröffnen|reaktivieren|erneut\s+öffnen)\b",lower):
        operation={"task":"task_reopen","list_item":"list_item_reopen"}.get(target_type)
        if operation:return {"status":"planned","operation":operation,"payload":{},"confidence":1.0,
                             "reason_codes":["reopen"]},"deterministic_test"
    if target_type=="list" and part["target_type"]=="list_item":
        match=re.search(r"\b(?:ergänze|füge)(?:\s+(?:noch|außerdem))?\s+(.+?)\s+(?:auf|in|zu|zur)\s+(?:die\s+|der\s+)?[\wÄÖÜäöüß-]*liste\b",text,re.I)
        if match:
            return {"status":"planned","operation":"list_add_item","payload":{"new_text":match.group(1).strip()},
                    "confidence":1.0,"reason_codes":["add_item"]},"deterministic_test"
    return {"status":"clarification_required","operation":None,"payload":{},"confidence":0.0,
            "reason_codes":["unclear_operation"]},"deterministic_test"


def _clarification_text(part):
    target=" ".join((part["target_text"] or part["source_text"]).split())[:180]
    return f"Wie genau soll „{target}“ geändert werden?"


def _persist_plan(part,resolution,plan,source):
    question=None
    if plan["status"]=="clarification_required":
        question=create_question(part["session_id"],_clarification_text(part),"implicit",
            max(.5,1-plan["confidence"]),.95,segment_ids=_source_segment_ids(part))
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("""INSERT INTO mutation_action_executions(session_id,intent_part_id,target_resolution_id,operation,
        payload,status,confidence,reason_codes,decision_source,clarification_question_id,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(intent_part_id) DO NOTHING""",
        (part["session_id"],part["id"],resolution["id"],plan["operation"],Jsonb(plan["payload"]),plan["status"],
         plan["confidence"],Jsonb(plan["reason_codes"]),source,question["id"] if question else None,now,now));c.commit()
        row=c.execute(ACTION_SELECT+" WHERE a.intent_part_id=%s",(part["id"],)).fetchone()
    return _item(row)


async def _mark_stale(action,part):
    question=create_question(part["session_id"],"Das ausgewählte Ziel ist nicht mehr aktiv. Welches Objekt meinst du?",
        "implicit",1.0,.95,segment_ids=_source_segment_ids(part));now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("""UPDATE mutation_action_executions SET status='clarification_required',operation=NULL,
        reason_codes=%s,clarification_question_id=%s,error_code='stale_target',updated_at=%s WHERE id=%s""",
        (Jsonb(list(dict.fromkeys(action["reason_codes"]+["stale_target"]))),question["id"],now,action["id"]));c.commit()
        row=c.execute(ACTION_SELECT+" WHERE a.id=%s",(action["id"],)).fetchone()
    return _item(row)


async def _execute(action,part):
    if action["status"]!="planned":return action
    operation=action["operation"];new_text=action["payload"].get("new_text")
    vector=None
    if operation in VALUE_OPERATIONS:
        vector=embedding_to_pgvector(await get_embedding(new_text))
    now=datetime.now(TIMEZONE)
    committed=False
    try:
        with get_db_connection() as c:
            locked=c.execute(ACTION_SELECT+" WHERE a.id=%s FOR UPDATE OF a",(action["id"],)).fetchone()
            current_action=_item(locked)
            if current_action["status"]!="planned":c.commit();return current_action
            before=_state(c,current_action["target_type"],current_action["target_id"],lock=True)
            if not before:raise LookupError("stale_target")
            if operation not in {"note_archive","task_archive","list_archive","list_item_archive"} and before.get("archived"):
                raise LookupError("stale_target")
            target_id=current_action["target_id"]
            if operation=="note_update":
                c.execute("UPDATE notes SET content=%s,embedding=%s::vector,embedding_model=%s,updated_at=%s WHERE id=%s",
                          (new_text,vector,EMBEDDING_MODEL,now,target_id))
            elif operation=="note_archive":
                c.execute("UPDATE notes SET archived=TRUE,archived_at=%s,archive_reason='user_requested',updated_at=%s WHERE id=%s",
                          (now,now,target_id))
            elif operation=="task_update":
                c.execute("UPDATE tasks SET content=%s,embedding=%s::vector,embedding_model=%s,updated_at=%s WHERE id=%s",
                          (new_text,vector,EMBEDDING_MODEL,now,target_id))
            elif operation=="task_complete":
                c.execute("UPDATE tasks SET status='done',percent_complete=100,updated_at=%s WHERE id=%s",(now,target_id))
            elif operation=="task_reopen":
                c.execute("UPDATE tasks SET status='open',percent_complete=CASE WHEN percent_complete=100 THEN 0 ELSE percent_complete END,updated_at=%s WHERE id=%s",
                          (now,target_id))
            elif operation=="task_archive":
                c.execute("UPDATE tasks SET status='archived',archived=TRUE,archived_at=%s,archive_reason='user_requested',updated_at=%s WHERE id=%s",
                          (now,now,target_id))
            elif operation=="list_rename":
                c.execute("UPDATE lists SET title=%s,embedding=%s::vector,embedding_model=%s,updated_at=%s WHERE id=%s",
                          (new_text,vector,EMBEDDING_MODEL,now,target_id))
            elif operation=="list_add_item":
                existing_item=c.execute("""SELECT id FROM list_items WHERE list_id=%s AND archived=FALSE
                AND lower(content)=lower(%s) ORDER BY id LIMIT 1""",(target_id,new_text)).fetchone()
                item_id=existing_item[0] if existing_item else c.execute("""INSERT INTO list_items(list_id,content,
                created_at,updated_at,status,archived,embedding,embedding_model)
                VALUES(%s,%s,%s,%s,'active',FALSE,%s::vector,%s) RETURNING id""",
                (target_id,new_text,now,now,vector,EMBEDDING_MODEL)).fetchone()[0]
                c.execute("UPDATE lists SET embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(now,target_id))
            elif operation=="list_archive":
                c.execute("UPDATE lists SET archived=TRUE,archived_at=%s,archive_reason='user_requested',updated_at=%s WHERE id=%s",
                          (now,now,target_id))
                c.execute("""UPDATE list_items SET status='archived',archived=TRUE,archived_at=%s,
                archive_reason='user_requested_parent',updated_at=%s WHERE list_id=%s AND archived=FALSE""",(now,now,target_id))
            elif operation=="list_item_update":
                c.execute("UPDATE list_items SET content=%s,embedding=%s::vector,embedding_model=%s,updated_at=%s WHERE id=%s",
                          (new_text,vector,EMBEDDING_MODEL,now,target_id))
                c.execute("UPDATE lists SET embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(now,before["list_id"]))
            elif operation=="list_item_complete":
                c.execute("UPDATE list_items SET status='done',updated_at=%s WHERE id=%s",(now,target_id))
                c.execute("UPDATE lists SET embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(now,before["list_id"]))
            elif operation=="list_item_reopen":
                c.execute("UPDATE list_items SET status='active',updated_at=%s WHERE id=%s",(now,target_id))
                c.execute("UPDATE lists SET embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(now,before["list_id"]))
            elif operation=="list_item_archive":
                c.execute("""UPDATE list_items SET status='archived',archived=TRUE,archived_at=%s,
                archive_reason='user_requested',updated_at=%s WHERE id=%s""",(now,now,target_id))
                c.execute("UPDATE lists SET embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(now,before["list_id"]))
            else:raise ValueError("Unsupported persisted mutation operation")
            after=_state(c,current_action["target_type"],target_id)
            if operation=="list_add_item":after={**after,"added_item":{"id":item_id,"content":new_text}}
            c.execute("""UPDATE mutation_action_executions SET status='completed',before_state=%s,after_state=%s,
            executed_at=%s,updated_at=%s WHERE id=%s""",(Jsonb(before),Jsonb(after),now,now,action["id"]));c.commit()
            committed=True
            row=c.execute(ACTION_SELECT+" WHERE a.id=%s",(action["id"],)).fetchone()
        return _item(row)
    except LookupError:
        return await _mark_stale(action,part)
    except Exception as exc:
        if committed:raise
        with get_db_connection() as c:
            c.execute("UPDATE mutation_action_executions SET status='failed',error_code=%s,updated_at=%s WHERE id=%s",
                      (type(exc).__name__,datetime.now(TIMEZONE),action["id"]));c.commit()
        raise


async def ensure_session_mutation_actions(session_id,intent_parts,mode="llm"):
    existing={item["intent_part_id"]:item for item in get_session_mutation_actions(session_id)}
    resolutions={item["intent_part_id"]:item for item in get_session_mutation_target_resolutions(session_id)}
    results=[]
    for part in intent_parts:
        resolution=resolutions.get(part["id"])
        if not resolution or resolution["status"]!="resolved":continue
        action=existing.get(part["id"])
        if action and action["status"]=="failed":
            with get_db_connection() as c:
                c.execute("""UPDATE mutation_action_executions SET status='planned',error_code=NULL,updated_at=%s
                WHERE id=%s""",(datetime.now(TIMEZONE),action["id"]));c.commit()
                row=c.execute(ACTION_SELECT+" WHERE a.id=%s",(action["id"],)).fetchone()
            action=_item(row)
        if not action:
            intent=part["primary_intent"];target_type=resolution["target_type"]
            if intent=="complete":
                operation={"task":"task_complete","list_item":"list_item_complete"}.get(target_type)
                plan={"status":"planned","operation":operation,"payload":{},"confidence":resolution["confidence"],
                      "reason_codes":["intent_complete"]};source="rules"
            elif intent=="archive":
                operation=f"{target_type}_archive"
                plan={"status":"planned","operation":operation,"payload":{},"confidence":resolution["confidence"],
                      "reason_codes":["intent_archive"]};source="rules"
            else:
                with get_db_connection() as c:current=_state(c,target_type,resolution["target_id"])
                if not current:
                    plan={"status":"clarification_required","operation":None,"payload":{},"confidence":0.0,
                          "reason_codes":["stale_target"]};source="rules"
                elif mode=="deterministic":plan,source=_deterministic_change_plan(part,resolution)
                elif mode=="llm":plan,source=await _plan_change_with_llm(part,resolution,current)
                else:raise ValueError("Mutation action mode must be llm or deterministic")
            if not plan.get("operation") and plan["status"]=="planned":
                plan={"status":"clarification_required","operation":None,"payload":{},"confidence":0.0,
                      "reason_codes":["unclear_operation"]}
            action=_persist_plan(part,resolution,plan,source)
        results.append(await _execute(action,part))
    return results


def public_mutation_actions(actions):
    return [{"ordinal":item["ordinal"],"intent":item["intent"],"operation":item["operation"],
             "target_type":item["target_type"],"status":item["status"],"confidence":item["confidence"],
             "clarification_required":item["status"]=="clarification_required","reason_codes":item["reason_codes"]}
            for item in actions]
