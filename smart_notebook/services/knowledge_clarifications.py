"""W05 resolution of source-bound contradictions in durable notebook knowledge."""
from datetime import datetime
import json

import httpx
from psycopg.types.json import Jsonb

from ..config import EMBEDDING_DIMENSIONS,EMBEDDING_MODEL,TIMEZONE
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .embeddings import embedding_to_pgvector,get_embedding
from .intelligence import create_question


RESOLUTION_SELECT="""SELECT id,session_id,artifact_id,preflight_assessment_id,
clarification_question_id,status,resolution,selected_candidate_key,candidate_keys,
answer_session_id,before_state,after_state,reason_codes,created_at,updated_at,resolved_at
FROM knowledge_clarification_resolutions"""


def _item(row):
    if not row:return None
    return {"id":row[0],"session_id":row[1],"artifact_id":row[2],
            "preflight_assessment_id":row[3],"clarification_question_id":row[4],
            "status":row[5],"resolution":row[6],"selected_candidate_key":row[7],
            "candidate_keys":row[8] or [],"answer_session_id":row[9],
            "before_state":row[10],"after_state":row[11],"reason_codes":row[12] or [],
            "created_at":row[13].isoformat(),"updated_at":row[14].isoformat(),
            "resolved_at":row[15].isoformat() if row[15] else None}


def get_artifact_knowledge_clarification(artifact_id):
    with get_db_connection() as c:
        row=c.execute(RESOLUTION_SELECT+" WHERE artifact_id=%s",(artifact_id,)).fetchone()
    return _item(row)


def get_question_knowledge_clarifications(question_id):
    with get_db_connection() as c:
        rows=c.execute(RESOLUTION_SELECT+" WHERE clarification_question_id=%s ORDER BY id",(question_id,)).fetchall()
    return [_item(row) for row in rows]


def get_session_knowledge_clarifications(session_id):
    with get_db_connection() as c:
        rows=c.execute(RESOLUTION_SELECT+" WHERE session_id=%s ORDER BY id",(session_id,)).fetchall()
    return [_item(row) for row in rows]


def _short(text,limit=96):
    text=" ".join((text or "").split())
    return text if len(text)<=limit else text[:limit-1].rstrip()+"…"


def _related_note_candidates(assessment):
    keys=set(assessment.get("related_candidate_keys") or [])
    return [candidate for candidate in assessment.get("candidate_refs") or []
            if candidate.get("key") in keys and candidate.get("type")=="note"
            and candidate.get("content")]


def ensure_artifact_knowledge_clarification(assessment):
    """Create one blocking question only for a material, actionable note conflict."""
    if not assessment or assessment.get("classification")!="contradictory":return None
    if assessment.get("input_type") not in {"note","fact","decision"}:return None
    if float(assessment.get("confidence") or 0)<.85:return None
    existing=get_artifact_knowledge_clarification(assessment["artifact_id"])
    if existing:return existing
    candidates=_related_note_candidates(assessment)
    if not candidates:return None
    pending=_short(assessment["input_text"],140)
    if len(candidates)==1:
        question_text=f'Soll die neue Angabe „{pending}“ die bisherige Angabe „{_short(candidates[0]["content"],140)}“ ersetzen?'
    else:
        question_text=f'Welche Angabe soll gelten? Neu: „{pending}“; bisher bestehen {len(candidates)} widersprechende Angaben.'
    with get_db_connection() as c:
        segments=[row[0] for row in c.execute(
            "SELECT segment_id FROM session_artifact_sources WHERE artifact_id=%s ORDER BY segment_id",
            (assessment["artifact_id"],)).fetchall()]
    question=create_question(assessment["session_id"],question_text,"implicit",
                             assessment["confidence"],.95,segment_ids=segments)
    now=datetime.now(TIMEZONE);candidate_keys=[item["key"] for item in candidates]
    with get_db_connection() as c:
        c.execute("""INSERT INTO knowledge_clarification_resolutions(session_id,artifact_id,
        preflight_assessment_id,clarification_question_id,status,candidate_keys,reason_codes,created_at,updated_at)
        VALUES(%s,%s,%s,%s,'pending',%s,%s,%s,%s) ON CONFLICT(artifact_id) DO NOTHING""",
        (assessment["session_id"],assessment["artifact_id"],assessment["id"],question["id"],
         Jsonb(candidate_keys),Jsonb(["knowledge_contradiction"]),now,now));c.commit()
    return get_artifact_knowledge_clarification(assessment["artifact_id"])


def knowledge_clarification_options(question_id):
    resolutions=get_question_knowledge_clarifications(question_id)
    if len(resolutions)!=1 or resolutions[0]["status"] not in {"pending","needs_clarification"}:return []
    resolution=resolutions[0]
    with get_db_connection() as c:
        row=c.execute("""SELECT a.content,p.candidate_refs FROM session_artifacts a
        JOIN knowledge_preflight_assessments p ON p.id=%s WHERE a.id=%s""",
        (resolution["preflight_assessment_id"],resolution["artifact_id"])).fetchone()
    if not row:return []
    candidates=[item for item in row[1] or [] if item.get("key") in resolution["candidate_keys"]]
    if len(candidates)!=1:return []
    return [{"label":"Neue Angabe","content":f'Neue Angabe: {_short(row[0])}'},
            {"label":"Bisherige Angabe","content":f'Bisherige Angabe: {_short(candidates[0].get("content"))}'}]


def _normalize(value):return " ".join((value or "").casefold().split()).strip(" .!?\"„“")


def _rule_decision(answer,pending,candidates):
    normalized=_normalize(answer)
    if len(candidates)==1 and (normalized in {"ja","ja bitte","genau","die neue angabe","neue angabe"}
                               or normalized.startswith("neue angabe:")):
        return {"decision":"pending_statement","candidate_index":0,"replacement_text":"","confidence":1.0}
    if len(candidates)==1 and (normalized in {"nein","nein bitte","die bisherige angabe","bisherige angabe"}
                              or normalized.startswith("bisherige angabe:")):
        return {"decision":"existing_statement","candidate_index":1,"replacement_text":"","confidence":1.0}
    if normalized in {"abbrechen","keine","keine davon"}:
        return {"decision":"cancelled","candidate_index":0,"replacement_text":"","confidence":1.0}
    if normalized==_normalize(pending):
        return {"decision":"pending_statement","candidate_index":0,"replacement_text":"","confidence":1.0}
    for index,candidate in enumerate(candidates,start=1):
        if normalized==_normalize(candidate["content"]):
            return {"decision":"existing_statement","candidate_index":index,"replacement_text":"","confidence":1.0}
    return None


async def _model_decision(answer,pending,candidates):
    profile=get_ai_task_profile("questions.resolve")
    schema={"type":"object","properties":{
        "decision":{"type":"string","enum":["pending_statement","existing_statement","revised_statement","unresolved","cancelled"]},
        "candidate_index":{"type":"integer"},"replacement_text":{"type":"string"},
        "confidence":{"type":"number"}},
        "required":["decision","candidate_index","replacement_text","confidence"],"additionalProperties":False}
    context={"pending_statement":pending,"existing_statements":[
        {"index":index,"text":item["content"]} for index,item in enumerate(candidates,start=1)],
        "answer":answer}
    system=("Löse ausschließlich die konkrete Wissensrückfrage. Entscheide, ob die Antwort die neue Aussage, "
        "genau eine bisherige Aussage oder eine frei formulierte korrigierte Aussage bestätigt. "
        "replacement_text muss bei revised_statement eine exakte zusammenhängende Spanne der Antwort sein; "
        "sonst leer. Bei Zweifel unresolved. Erfinde und ergänze nichts.")
    payload={"model":profile["model"],"messages":[{"role":"system","content":system},
        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{"name":"knowledge_clarification_resolution","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    result=json.loads(response.json()["choices"][0]["message"]["content"])
    if isinstance(result.get("confidence"),bool) or not isinstance(result.get("confidence"),(int,float)) or not 0<=result["confidence"]<=1:
        raise ValueError("Knowledge clarification confidence must be between 0 and 1")
    decision=result.get("decision");index=result.get("candidate_index")
    if decision=="existing_statement" and (isinstance(index,bool) or not isinstance(index,int) or not 1<=index<=len(candidates)):
        raise ValueError("Knowledge clarification selected an unknown candidate")
    replacement=result.get("replacement_text") or ""
    if decision=="revised_statement" and (not replacement.strip() or replacement not in answer):
        raise ValueError("Knowledge clarification replacement is not an exact answer span")
    if decision!="revised_statement" and replacement:raise ValueError("Unexpected knowledge clarification replacement")
    return result


def _snapshot(c,candidates,lock=False,validate=True):
    rows=[]
    suffix=" FOR UPDATE" if lock else ""
    for candidate in candidates:
        row=c.execute("SELECT id,content,archived FROM notes WHERE id=%s"+suffix,(candidate["id"],)).fetchone()
        if not row or (validate and (row[1]!=candidate["content"] or row[2])):return None
        rows.append({"key":candidate["key"],"content":row[1],"archived":row[2]})
    return rows


def _answer_artifact(c,answer_session_id,replacement):
    rows=c.execute("""SELECT id,content FROM session_artifacts WHERE session_id=%s
    AND status='confirmed' AND artifact_type IN('note','fact','decision') ORDER BY id""",
    (answer_session_id,)).fetchall()
    matching=[row[0] for row in rows if _normalize(row[1])==_normalize(replacement)]
    return matching[0] if len(matching)==1 else None


async def resume_knowledge_clarification(question_id,answer_session_id,answer,mode="llm"):
    resolutions=get_question_knowledge_clarifications(question_id)
    if len(resolutions)!=1:return None
    resolution=resolutions[0]
    if resolution["status"] in {"completed","cancelled"}:return resolution
    with get_db_connection() as c:
        row=c.execute("""SELECT a.content,p.candidate_refs FROM session_artifacts a
        JOIN knowledge_preflight_assessments p ON p.id=%s WHERE a.id=%s""",
        (resolution["preflight_assessment_id"],resolution["artifact_id"])).fetchone()
    if not row:return None
    pending=row[0];candidates=[item for item in row[1] or [] if item.get("key") in resolution["candidate_keys"]]
    decision=_rule_decision(answer,pending,candidates)
    if decision is None:
        if mode=="deterministic":
            decision={"decision":"revised_statement","candidate_index":0,
                      "replacement_text":answer,"confidence":1.0}
        else:decision=await _model_decision(answer,pending,candidates)
    if decision["decision"]=="unresolved" or float(decision["confidence"])<.85:
        now=datetime.now(TIMEZONE)
        with get_db_connection() as c:
            c.execute("""UPDATE knowledge_clarification_resolutions SET status='needs_clarification',
            answer_session_id=%s,reason_codes=%s,updated_at=%s WHERE id=%s""",
            (answer_session_id,Jsonb(["answer_ambiguous"]),now,resolution["id"]));c.commit()
        return get_artifact_knowledge_clarification(resolution["artifact_id"])
    now=datetime.now(TIMEZONE)
    if decision["decision"]=="cancelled":
        with get_db_connection() as c:
            c.execute("UPDATE session_artifacts SET status='dismissed',updated_at=%s WHERE id=%s",(now,resolution["artifact_id"]))
            c.execute("""UPDATE knowledge_clarification_resolutions SET status='cancelled',answer_session_id=%s,
            reason_codes=%s,updated_at=%s,resolved_at=%s WHERE id=%s""",
            (answer_session_id,Jsonb(["user_cancelled"]),now,now,resolution["id"]));c.commit()
        return get_artifact_knowledge_clarification(resolution["artifact_id"])
    replacement=(pending if decision["decision"]=="pending_statement" else
                 (candidates[decision["candidate_index"]-1]["content"] if decision["decision"]=="existing_statement"
                  else decision["replacement_text"].strip()))
    selected=(candidates[decision["candidate_index"]-1] if decision["decision"]=="existing_statement" else None)
    vector=None
    linked_artifact_id=None
    if decision["decision"]!="existing_statement":
        vector=[0.0]*EMBEDDING_DIMENSIONS if mode=="deterministic" else await get_embedding(replacement)
    with get_db_connection() as c:
        locked=c.execute(RESOLUTION_SELECT+" WHERE id=%s FOR UPDATE",(resolution["id"],)).fetchone()
        if locked[5] in {"completed","cancelled"}:c.commit();return _item(locked)
        before=_snapshot(c,candidates,lock=True)
        if before is None:
            c.execute("""UPDATE knowledge_clarification_resolutions SET status='needs_clarification',
            answer_session_id=%s,reason_codes=%s,updated_at=%s WHERE id=%s""",
            (answer_session_id,Jsonb(["knowledge_changed_since_question"]),now,resolution["id"]));c.commit()
            return get_artifact_knowledge_clarification(resolution["artifact_id"])
        selected_id=selected["id"] if selected else None
        if decision["decision"]!="existing_statement":
            selected_id=c.execute("""INSERT INTO notes(content,created_at,updated_at,source_event_id,
            embedding,embedding_model,archived) VALUES(%s,%s,%s,NULL,%s::vector,%s,FALSE) RETURNING id""",
            (replacement,now,now,embedding_to_pgvector(vector),EMBEDDING_MODEL)).fetchone()[0]
        for candidate in candidates:
            if candidate["id"]!=selected_id:
                c.execute("""UPDATE notes SET archived=TRUE,archived_at=%s,
                archive_reason='clarification_superseded',updated_at=%s WHERE id=%s""",(now,now,candidate["id"]))
        if decision["decision"]=="pending_statement":
            c.execute("""INSERT INTO artifact_knowledge_links(artifact_id,knowledge_type,knowledge_id,created_at)
            VALUES(%s,'note',%s,%s) ON CONFLICT DO NOTHING""",(resolution["artifact_id"],selected_id,now))
            c.execute("""UPDATE session_artifacts SET promoted_knowledge_type='note',promoted_knowledge_id=%s,
            promoted_at=%s,promotion_error=NULL WHERE id=%s""",(selected_id,now,resolution["artifact_id"]))
            result_resolution="replace_existing"
        else:
            c.execute("UPDATE session_artifacts SET status='dismissed',updated_at=%s WHERE id=%s",(now,resolution["artifact_id"]))
            result_resolution="keep_existing" if decision["decision"]=="existing_statement" else "revised_statement"
            if decision["decision"]=="revised_statement":
                answer_artifact_id=_answer_artifact(c,answer_session_id,replacement)
                if answer_artifact_id:
                    linked_artifact_id=answer_artifact_id
                    c.execute("""INSERT INTO artifact_knowledge_links(artifact_id,knowledge_type,knowledge_id,created_at)
                    VALUES(%s,'note',%s,%s) ON CONFLICT DO NOTHING""",(answer_artifact_id,selected_id,now))
                    c.execute("""UPDATE session_artifacts SET promoted_knowledge_type='note',promoted_knowledge_id=%s,
                    promoted_at=%s,promotion_error=NULL WHERE id=%s""",(selected_id,now,answer_artifact_id))
        after=_snapshot(c,candidates,validate=False)
        if decision["decision"]!="existing_statement":
            after.append({"key":f"note:{selected_id}","content":replacement,"archived":False})
        c.execute("""UPDATE knowledge_clarification_resolutions SET status='completed',resolution=%s,
        selected_candidate_key=%s,answer_session_id=%s,before_state=%s,after_state=%s,
        reason_codes=%s,updated_at=%s,resolved_at=%s WHERE id=%s""",
        (result_resolution,(selected["key"] if selected else f"note:{selected_id}"),answer_session_id,Jsonb(before),Jsonb(after),
         Jsonb(["user_clarified_knowledge"]),now,now,resolution["id"]));c.commit()
    if decision["decision"]=="pending_statement" or linked_artifact_id:
        from .claims import materialize_validated_artifact_claims
        from .promotion import _transfer_all_topics
        source_artifact=(resolution["artifact_id"] if decision["decision"]=="pending_statement"
                         else linked_artifact_id)
        await materialize_validated_artifact_claims(source_artifact,"note",selected_id)
        _transfer_all_topics(source_artifact,"note",selected_id)
    return get_artifact_knowledge_clarification(resolution["artifact_id"])


def public_knowledge_clarifications(items):
    return [{"status":item["status"],"resolution":item["resolution"],
             "requires_clarification":item["status"] in {"pending","needs_clarification"},
             "reason_codes":item["reason_codes"]} for item in items]
