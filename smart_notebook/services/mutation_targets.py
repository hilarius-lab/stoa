"""A06 resolution of mutation references without executing the mutation.

Only candidates already captured by A05 or an explicit public entity context
may become a target. Ambiguity is durable and creates a source-bound question;
the actual change remains A07's responsibility.
"""
from datetime import datetime
import json
from uuid import UUID

import httpx
from psycopg.types.json import Jsonb

from ..config import MUTATION_PART_MIN_CONFIDENCE,MUTATION_TARGET_MIN_CONFIDENCE,TIMEZONE
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .capture_intent import MUTATION_INTENTS
from .intelligence import create_question
from .knowledge_preflight import get_session_knowledge_preflights


STATUSES={"resolved","ambiguous","unresolved"}
TARGET_TYPES={"note","task","list","list_item"}
REASON_CODES={"context_reference","single_candidate","model_selection","no_candidates",
              "ambiguous_candidates","low_confidence","incompatible_context","stale_context",
              "weak_reference","low_intent_confidence"}
INTENT_TARGETS={"change":TARGET_TYPES,"complete":{"task","list_item"},
                "archive":TARGET_TYPES}


RESOLUTION_SELECT="""SELECT r.id,r.session_id,r.intent_part_id,r.preflight_assessment_id,r.status,r.target_type,
r.target_id,r.target_key,r.confidence,r.candidate_keys,r.reason_codes,r.decision_source,r.clarification_question_id,
r.created_at,r.updated_at,p.ordinal,p.primary_intent FROM mutation_target_resolutions r
JOIN session_intent_parts p ON p.id=r.intent_part_id"""


def _item(row):
    if not row:return None
    return {"id":row[0],"session_id":row[1],"intent_part_id":row[2],
            "preflight_assessment_id":row[3],"status":row[4],"target_type":row[5],
            "target_id":row[6],"target_key":row[7],"confidence":row[8],
            "candidate_keys":row[9] or [],"reason_codes":row[10] or [],
            "decision_source":row[11],"clarification_question_id":row[12],
            "created_at":row[13].isoformat(),"updated_at":row[14].isoformat(),
            "ordinal":row[15],"intent":row[16]}


def get_session_mutation_target_resolutions(session_id):
    with get_db_connection() as c:
        rows=c.execute(RESOLUTION_SELECT+" WHERE r.session_id=%s ORDER BY p.ordinal,r.id",(session_id,)).fetchall()
    return [_item(row) for row in rows]


def _compatible(part,candidate_type):
    if candidate_type not in INTENT_TARGETS.get(part["primary_intent"],set()):return False
    expected=part["target_type"]
    if expected=="unknown" or expected==candidate_type:return True
    # "dort noch Brot ergänzen" names an item semantically but points at the
    # list container that A07 will later extend.
    return part["primary_intent"]=="change" and expected=="list_item" and candidate_type=="list"


def _candidate_label(candidate):
    if candidate["type"]=="list":value=candidate.get("title") or candidate.get("content")
    elif candidate["type"]=="list_item":
        parent=(candidate.get("parent") or {}).get("title")
        value=f"{candidate.get('content') or ''} ({parent})" if parent else candidate.get("content")
    else:value=candidate.get("content") or candidate.get("title")
    return " ".join(str(value or candidate["type"]).split())[:100]


def _context_ref(session_id):
    with get_db_connection() as c:
        row=c.execute("SELECT context_ref FROM client_sessions WHERE ingestion_session_id=%s",(session_id,)).fetchone()
    return row[0] if row and isinstance(row[0],dict) else None


def _context_candidate(context):
    kind=context.get("type") if isinstance(context,dict) else None
    if kind not in TARGET_TYPES:return None,"incompatible_context" if context else None
    try:public_id=UUID(str(context.get("id")))
    except (TypeError,ValueError,AttributeError):return None,"stale_context"
    with get_db_connection() as c:
        if kind=="note":
            row=c.execute("""SELECT n.id,n.content FROM client_knowledge_entities e JOIN notes n
            ON n.id=e.internal_id WHERE e.public_id=%s AND e.entity_type='note' AND e.state='active'
            AND n.archived=FALSE""",(public_id,)).fetchone()
            if row:return {"key":f"note:{row[0]}","type":"note","id":row[0],"title":None,
                           "content":row[1],"parent":None},None
        else:
            identity=c.execute("SELECT internal_id FROM client_entity_identities WHERE public_id=%s AND entity_type=%s",
                               (public_id,kind)).fetchone()
            if identity:
                if kind=="task":row=c.execute("SELECT id,content FROM tasks WHERE id=%s AND archived=FALSE",identity).fetchone()
                elif kind=="list":row=c.execute("SELECT id,title,description FROM lists WHERE id=%s AND archived=FALSE",identity).fetchone()
                else:row=c.execute("""SELECT li.id,li.content,l.id,l.title FROM list_items li JOIN lists l ON l.id=li.list_id
                    WHERE li.id=%s AND li.archived=FALSE AND l.archived=FALSE""",identity).fetchone()
                if row and kind=="task":return {"key":f"task:{row[0]}","type":"task","id":row[0],"title":None,"content":row[1],"parent":None},None
                if row and kind=="list":return {"key":f"list:{row[0]}","type":"list","id":row[0],"title":row[1],"content":row[2],"parent":None},None
                if row:return {"key":f"list_item:{row[0]}","type":"list_item","id":row[0],"title":None,
                               "content":row[1],"parent":{"type":"list","id":row[2],"title":row[3]}},None
    return None,"stale_context"


def _validate_model_result(raw,candidate_count):
    if not isinstance(raw,dict):raise ValueError("Target resolution response must be an object")
    status=raw.get("status");index=raw.get("selected_candidate_index");confidence=raw.get("confidence")
    reasons=raw.get("reason_codes")
    if status not in STATUSES:raise ValueError("Unknown target resolution status")
    if isinstance(index,bool) or not isinstance(index,int) or index<0 or index>candidate_count:
        raise ValueError("Target resolution contains an unknown candidate index")
    if (status=="resolved")!=(index>0):raise ValueError("Only a resolved target may select a candidate")
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not 0<=confidence<=1:
        raise ValueError("Target resolution confidence must be between 0 and 1")
    if not isinstance(reasons,list) or len(reasons)>8 or any(reason not in REASON_CODES for reason in reasons):
        raise ValueError("Unknown or excessive target resolution reason codes")
    reasons=list(dict.fromkeys(reasons))
    if status=="resolved":
        reasons=[reason for reason in reasons if reason not in {"no_candidates","ambiguous_candidates","weak_reference"}]
        if not any(reason in {"model_selection","single_candidate"} for reason in reasons):reasons.append("model_selection")
    elif status=="ambiguous":
        reasons=[reason for reason in reasons if reason not in {"no_candidates","single_candidate","model_selection"}]
        if "ambiguous_candidates" not in reasons:reasons.append("ambiguous_candidates")
    else:
        reasons=[reason for reason in reasons if reason not in {"no_candidates","single_candidate","model_selection","ambiguous_candidates"}]
        if "weak_reference" not in reasons:reasons.append("weak_reference")
    return {"status":status,"selected_candidate_index":index,"confidence":float(confidence),
            "reason_codes":reasons}


async def _resolve_with_llm(part,candidates):
    profile=get_ai_task_profile("capture.target_resolution")
    schema={"type":"object","properties":{
        "status":{"type":"string","enum":sorted(STATUSES)},
        "selected_candidate_index":{"type":"integer","minimum":0},
        "confidence":{"type":"number"},
        "reason_codes":{"type":"array","items":{"type":"string","enum":sorted(REASON_CODES)},"maxItems":8}},
        "required":["status","selected_candidate_index","confidence","reason_codes"],"additionalProperties":False}
    system=("Löse ausschließlich die Referenz einer erkannten Änderungsabsicht auf. Wähle genau einen der nummerierten "
        "Kandidaten nur wenn die Eingabe ihn eindeutig meint. Bei mehreren plausiblen Zielen antworte ambiguous, bei keinem "
        "belegbaren Ziel unresolved. selected_candidate_index ist nur bei resolved 1-basiert, sonst 0. Führe keine Änderung aus.")
    context={"intent":{"kind":part["primary_intent"],"target_type":part["target_type"],
        "target_text":part["target_text"],"source_text":part["source_text"]},
        "candidates":[{"index":index,"type":item["type"],"title":item.get("title"),
                       "content":item.get("content"),"parent":item.get("parent")}
                      for index,item in enumerate(candidates,start=1)]}
    payload={"model":profile["model"],"messages":[{"role":"system","content":system},
        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{"name":"smart_notebook_target_resolution","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    return _validate_model_result(json.loads(response.json()["choices"][0]["message"]["content"]),len(candidates)),f"{profile['provider']}:{profile['model']}"


def _clarification_text(part,candidates,decision):
    target=" ".join((part["target_text"] or part["source_text"]).split())[:180]
    if "low_intent_confidence" in decision["reason_codes"]:
        action={"archive":"archiviert","complete":"als erledigt markiert","change":"geändert"}[part["primary_intent"]]
        return f"Soll „{target}“ wirklich {action} werden?"
    if decision["status"]=="ambiguous" and candidates:
        labels=[_candidate_label(item) for item in candidates[:3]]
        return f"Welches Ziel meinst du mit „{target}“: "+" oder ".join(f"„{label}“" for label in labels)+"?"
    return f"Welches Objekt meinst du mit „{target}“?"


def _persist(part,assessment,decision,candidates,source):
    target=candidates[decision["selected_candidate_index"]-1] if decision["status"]=="resolved" else None
    question=None
    if target is None:
        question=create_question(part["session_id"],_clarification_text(part,candidates,decision),
            "implicit",max(.5,1-decision["confidence"]),.95,segment_ids=part.get("source_segment_ids") or [])
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("""INSERT INTO mutation_target_resolutions(session_id,intent_part_id,preflight_assessment_id,status,
        target_type,target_id,target_key,confidence,candidate_keys,reason_codes,decision_source,clarification_question_id,
        created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(intent_part_id) DO NOTHING""",
        (part["session_id"],part["id"],assessment["id"],decision["status"],target["type"] if target else None,
         target["id"] if target else None,target["key"] if target else None,decision["confidence"],
         Jsonb([item["key"] for item in candidates]),Jsonb(decision["reason_codes"]),source,
         question["id"] if question else None,now,now));c.commit()
        row=c.execute(RESOLUTION_SELECT+" WHERE r.intent_part_id=%s",(part["id"],)).fetchone()
    return _item(row)


async def ensure_session_mutation_target_resolutions(session_id,intent_parts,mode="llm"):
    existing={item["intent_part_id"]:item for item in get_session_mutation_target_resolutions(session_id)}
    assessments={item["intent_part_id"]:item for item in get_session_knowledge_preflights(session_id)
                 if item["intent_part_id"] is not None}
    context=_context_ref(session_id);context_candidate,context_error=_context_candidate(context)
    results=[]
    for part in intent_parts:
        if part["primary_intent"] not in MUTATION_INTENTS:continue
        if part["id"] in existing:results.append(existing[part["id"]]);continue
        assessment=assessments.get(part["id"])
        if not assessment:raise ValueError("Mutation target resolution requires A05 preflight")
        candidates=[]
        for item in assessment["candidate_refs"]:
            if _compatible(part,item["type"]) and item["key"] not in {x["key"] for x in candidates}:
                candidates.append(item)
        if part["confidence"]<MUTATION_PART_MIN_CONFIDENCE:
            decision={"status":"unresolved","selected_candidate_index":0,"confidence":part["confidence"],
                      "reason_codes":["low_intent_confidence"]};source="policy"
        elif context_candidate and _compatible(part,context_candidate["type"]):
            candidates=[context_candidate]+[item for item in candidates if item["key"]!=context_candidate["key"]]
            decision={"status":"resolved","selected_candidate_index":1,"confidence":1.0,
                      "reason_codes":["context_reference"]};source="context"
        elif context_candidate:
            decision={"status":"unresolved","selected_candidate_index":0,"confidence":0.0,
                      "reason_codes":["incompatible_context"]};source="policy"
        elif context_error in {"stale_context"}:
            decision={"status":"unresolved","selected_candidate_index":0,"confidence":0.0,
                      "reason_codes":[context_error]};source="policy"
        elif not candidates:
            decision={"status":"unresolved","selected_candidate_index":0,"confidence":0.0,
                      "reason_codes":["no_candidates"]};source="rules"
        elif mode=="deterministic":
            resolved=len(candidates)==1
            decision={"status":"resolved" if resolved else "ambiguous",
                      "selected_candidate_index":1 if resolved else 0,"confidence":1.0 if resolved else .5,
                      "reason_codes":["single_candidate"] if resolved else ["ambiguous_candidates"]};source="deterministic_test"
        elif mode=="llm":decision,source=await _resolve_with_llm(part,candidates)
        else:raise ValueError("Target resolution mode must be llm or deterministic")
        if decision["status"]=="resolved" and decision["confidence"]<MUTATION_TARGET_MIN_CONFIDENCE:
            decision={"status":"ambiguous" if len(candidates)>1 else "unresolved","selected_candidate_index":0,
                      "confidence":decision["confidence"],
                      "reason_codes":list(dict.fromkeys(decision["reason_codes"]+["low_confidence"]))}
        results.append(_persist(part,assessment,decision,candidates,source))
    return results


def public_mutation_target_resolutions(resolutions):
    return [{"ordinal":item["ordinal"],"intent":item["intent"],"status":item["status"],
             "target_type":item["target_type"],"confidence":item["confidence"],
             "candidate_count":len(item["candidate_keys"]),
             "clarification_required":item["status"]!="resolved","reason_codes":item["reason_codes"]}
            for item in resolutions]
