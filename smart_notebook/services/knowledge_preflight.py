"""A05 preflight against durable knowledge before creation or later mutation.

This stage finds possible objects and classifies the relationship.  It never
resolves a mutation target and never changes knowledge; those remain A06/A07.
"""
from datetime import datetime
import json

import httpx
from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .capture_intent import MUTATION_INTENTS
from .retrieval import search_knowledge


CLASSIFICATIONS={"new","identical","complementary","contradictory","targeted"}
REASON_CODES={"no_candidates","exact_identity","related_subject","adds_detail",
              "conflicts_with_existing","mutation_intent","ambiguous_candidates","model_assessment"}
TYPE_FILTERS={
    "note":["note"],"fact":["note"],"decision":["note"],"task":["task"],
    "list":["list"],"list_item":["list_item","list"],"unknown":["note","task","list","list_item"],
}


def _normalized(value):
    return " ".join((value or "").casefold().split())


def _candidate_ref(item):
    retrieval=item.get("retrieval") or {}
    return {"key":item["key"],"type":item["type"],"id":item["id"],
            "title":item.get("title"),"content":item.get("content") or "",
            "stage":retrieval.get("stage"),"scores":retrieval.get("scores") or {},
            "due_at":item.get("due_at"),"work_start_at":item.get("work_start_at"),
            "urgency":item.get("urgency"),"parent":item.get("parent")}


def _assessment_item(row):
    if not row:return None
    return {"id":row[0],"session_id":row[1],"artifact_id":row[2],"intent_part_id":row[3],
            "input_kind":row[4],"input_type":row[5],"input_text":row[6],
            "classification":row[7],"confidence":row[8],"candidate_refs":row[9] or [],
            "related_candidate_keys":row[10] or [],"reason_codes":row[11] or [],
            "decision_source":row[12],"created_at":row[13].isoformat(),"updated_at":row[14].isoformat()}


ASSESSMENT_SELECT="""SELECT id,session_id,artifact_id,intent_part_id,input_kind,input_type,input_text,
classification,confidence,candidate_refs,related_candidate_keys,reason_codes,decision_source,created_at,updated_at
FROM knowledge_preflight_assessments"""


def get_artifact_knowledge_preflight(artifact_id):
    with get_db_connection() as c:
        row=c.execute(ASSESSMENT_SELECT+" WHERE artifact_id=%s",(artifact_id,)).fetchone()
    return _assessment_item(row)


def get_session_knowledge_preflights(session_id):
    with get_db_connection() as c:
        rows=c.execute(ASSESSMENT_SELECT+" WHERE session_id=%s ORDER BY id",(session_id,)).fetchall()
    return [_assessment_item(row) for row in rows]


def _exact_identity(subject,candidate):
    kind=subject["input_type"]
    if kind=="list":
        same=_normalized(subject["input_text"])==_normalized(candidate.get("title"))
    else:
        same=_normalized(subject["input_text"])==_normalized(candidate.get("content"))
    if not same:return False
    if kind=="list_item" and subject.get("target_title"):
        if _normalized(subject["target_title"])!=_normalized((candidate.get("parent") or {}).get("title")):
            return False
    if kind=="task":
        data=subject.get("normalized_data") or {}
        for key in ("due_at","work_start_at"):
            if data.get(key) and data[key]!=candidate.get(key):return False
        if data.get("urgency") is not None and candidate.get("urgency") is not None:
            if abs(float(data["urgency"])-float(candidate["urgency"]))>.01:return False
    return True


def _validate_model_result(raw,candidate_count):
    if not isinstance(raw,dict):raise ValueError("Knowledge preflight response must be an object")
    classification=raw.get("classification");confidence=raw.get("confidence");indexes=raw.get("related_candidate_indexes")
    reasons=raw.get("reason_codes")
    if classification not in CLASSIFICATIONS-{"targeted"}:raise ValueError("Unknown knowledge preflight classification")
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not 0<=confidence<=1:
        raise ValueError("Knowledge preflight confidence must be between 0 and 1")
    if not isinstance(indexes,list) or any(isinstance(value,bool) or not isinstance(value,int) or value<1 or value>candidate_count for value in indexes):
        raise ValueError("Knowledge preflight contains an unknown candidate index")
    indexes=list(dict.fromkeys(indexes))
    if classification in {"identical","complementary","contradictory"} and not indexes:
        raise ValueError("Related knowledge classification requires a candidate")
    if classification=="new" and indexes:raise ValueError("New knowledge cannot select a related candidate")
    if not isinstance(reasons,list) or len(reasons)>8 or any(reason not in REASON_CODES for reason in reasons):
        raise ValueError("Unknown or excessive knowledge preflight reason codes")
    return {"classification":classification,"confidence":float(confidence),
            "related_candidate_indexes":indexes,"reason_codes":list(dict.fromkeys(reasons))}


async def _classify_with_llm(subject,candidates):
    profile=get_ai_task_profile("capture.knowledge_preflight")
    schema={"type":"object","properties":{
        "classification":{"type":"string","enum":["new","identical","complementary","contradictory"]},
        "confidence":{"type":"number"},
        "related_candidate_indexes":{"type":"array","items":{"type":"integer"},"maxItems":7},
        "reason_codes":{"type":"array","items":{"type":"string","enum":sorted(REASON_CODES)},"maxItems":8}},
        "required":["classification","confidence","related_candidate_indexes","reason_codes"],"additionalProperties":False}
    system=("Ordne neuen, noch unveränderten Notebook-Inhalt gegenüber vorhandenen Suchtreffern ein. "
        "new: kein Treffer behandelt denselben Gegenstand. identical: gleiche Aussage oder dasselbe Objekt ohne neue materielle Information. "
        "complementary: kompatible neue Information zum selben Gegenstand. contradictory: materiell unvereinbare Information zum selben Gegenstand. "
        "Wähle nur wirklich bezogene Treffer über ihre 1-basierte Nummer. Führe keine Änderung aus und erfinde nichts.")
    context={"new_input":subject,"candidates":[{"index":index,**candidate} for index,candidate in enumerate(candidates,start=1)]}
    payload={"model":profile["model"],"messages":[{"role":"system","content":system},
        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{"name":"smart_notebook_knowledge_preflight","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    return _validate_model_result(json.loads(response.json()["choices"][0]["message"]["content"]),len(candidates)),f"{profile['provider']}:{profile['model']}"


async def _assess(subject,mode):
    candidates=[_candidate_ref(item) for item in await search_knowledge(subject["search_query"],limit=7,
        types=TYPE_FILTERS.get(subject["input_type"],TYPE_FILTERS["unknown"]),include_vector=mode!="deterministic")]
    if subject["input_kind"]=="mutation_intent":
        return {"classification":"targeted","confidence":subject["intent_confidence"],
                "related_candidate_indexes":list(range(1,len(candidates)+1)),
                "reason_codes":["mutation_intent"]+(["ambiguous_candidates"] if len(candidates)>1 else [])},candidates,"policy"
    exact=[index for index,candidate in enumerate(candidates,start=1) if _exact_identity(subject,candidate)]
    if exact:
        return {"classification":"identical","confidence":1.0,"related_candidate_indexes":exact,
                "reason_codes":["exact_identity"]+(["ambiguous_candidates"] if len(exact)>1 else [])},candidates,"rules"
    if not candidates:
        return {"classification":"new","confidence":1.0,"related_candidate_indexes":[],
                "reason_codes":["no_candidates"]},candidates,"rules"
    if mode=="deterministic":
        return {"classification":"complementary","confidence":.75,"related_candidate_indexes":[1],
                "reason_codes":["related_subject"]},candidates,"deterministic_test"
    decision,source=await _classify_with_llm(subject,candidates)
    return decision,candidates,source


def _persist(subject,decision,candidates,source):
    now=datetime.now(TIMEZONE);related=[candidates[index-1]["key"] for index in decision["related_candidate_indexes"]]
    with get_db_connection() as c:
        c.execute("""INSERT INTO knowledge_preflight_assessments(session_id,artifact_id,intent_part_id,input_kind,input_type,
        input_text,classification,confidence,candidate_refs,related_candidate_keys,reason_codes,decision_source,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        (subject["session_id"],subject.get("artifact_id"),subject.get("intent_part_id"),subject["input_kind"],
         subject["input_type"],subject["input_text"],decision["classification"],decision["confidence"],
         Jsonb(candidates),Jsonb(related),Jsonb(decision["reason_codes"]),source,now,now));c.commit()
    if subject.get("artifact_id") is not None:return get_artifact_knowledge_preflight(subject["artifact_id"])
    with get_db_connection() as c:
        row=c.execute(ASSESSMENT_SELECT+" WHERE intent_part_id=%s",(subject["intent_part_id"],)).fetchone()
    return _assessment_item(row)


async def ensure_artifact_knowledge_preflight(artifact_id,mode="llm"):
    existing=get_artifact_knowledge_preflight(artifact_id)
    if existing:return existing
    with get_db_connection() as c:
        row=c.execute("""SELECT a.session_id,a.artifact_type,a.content,COALESCE(cl.normalized_data,'{}'::jsonb),
        (SELECT t.title FROM session_artifact_topics x JOIN session_topics t ON t.id=x.topic_id
         WHERE x.artifact_id=a.id ORDER BY x.relation='primary_topic' DESC LIMIT 1)
        FROM session_artifacts a LEFT JOIN artifact_classifications cl ON cl.artifact_id=a.id WHERE a.id=%s""",(artifact_id,)).fetchone()
    if not row:raise ValueError("Unknown session artifact")
    kind=row[1]
    query=" ".join(part for part in (row[4] if kind=="list_item" else "",row[2]) if part)
    subject={"session_id":row[0],"artifact_id":artifact_id,"input_kind":"artifact","input_type":kind,
             "input_text":row[2],"search_query":query,"normalized_data":row[3] or {},"target_title":row[4]}
    decision,candidates,source=await _assess(subject,mode)
    return _persist(subject,decision,candidates,source)


async def ensure_session_knowledge_preflights(session_id,intent_parts,artifact_ids=None,mode="llm"):
    assessments=[]
    for part in intent_parts:
        if part["primary_intent"] not in MUTATION_INTENTS:continue
        with get_db_connection() as c:
            row=c.execute(ASSESSMENT_SELECT+" WHERE intent_part_id=%s",(part["id"],)).fetchone()
        if row:assessments.append(_assessment_item(row));continue
        query=part["target_text"].strip() or part["source_text"].strip()
        subject={"session_id":session_id,"intent_part_id":part["id"],"input_kind":"mutation_intent",
                 "input_type":part["target_type"],"input_text":part["source_text"],"search_query":query,
                 "intent_confidence":part["confidence"]}
        decision,candidates,source=await _assess(subject,mode);assessments.append(_persist(subject,decision,candidates,source))
    with get_db_connection() as c:
        sql="""SELECT id FROM session_artifacts WHERE session_id=%s AND status='confirmed'"""
        params=(session_id,)
        if artifact_ids is not None:
            sql+=" AND id=ANY(%s)";params=(session_id,artifact_ids)
        artifact_rows=c.execute(sql+" ORDER BY id",params).fetchall() if artifact_ids!=[] else []
    for row in artifact_rows:assessments.append(await ensure_artifact_knowledge_preflight(row[0],mode))
    return assessments


def identical_knowledge_target(assessment,knowledge_type):
    if not assessment or assessment["classification"]!="identical":return None
    matching=[item for item in assessment["candidate_refs"]
              if item["key"] in assessment["related_candidate_keys"] and item["type"]==knowledge_type]
    return matching[0]["id"] if len(matching)==1 else None


def public_knowledge_preflights(assessments):
    return [{"input_kind":item["input_kind"],"input_type":item["input_type"],
             "classification":item["classification"],"confidence":item["confidence"],
             "candidate_count":len(item["candidate_refs"]),"related_candidate_count":len(item["related_candidate_keys"]),
             "reason_codes":item["reason_codes"]} for item in assessments]
