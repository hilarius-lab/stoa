"""Persisted content-based intent decisions for completed auto captures."""
from datetime import datetime
import json,re

import httpx
from psycopg.types.json import Jsonb

from ..config import MUTATION_PART_MIN_CONFIDENCE,TIMEZONE
from ..database import get_db_connection
from ..prompts import CAPTURE_INTENT_SPLIT_SYSTEM_PROMPT,CAPTURE_INTENT_SYSTEM_PROMPT
from .ai_tasks import get_ai_task_profile


INTENTS={"memo","query","change","complete","archive"}
TARGET_TYPES={"none","unknown","note","task","list","list_item"}
REASON_CODES={"asks_for_answer","adds_information","creates_object","modifies_existing",
              "marks_done","removes_or_forgets","multiple_intents","uncertain_target",
              "tentative_action"}
MUTATION_INTENTS={"change","complete","archive"}
MAX_INTENT_PARTS=12


def _tentative_action(text):
    return bool(re.search(r"\b(vielleicht|eventuell|möglicherweise)\b|\bkönnte(?:st|n)?\b",text.casefold()))


def _contains_span(text,span):
    """Whitespace-insensitive substring check.

    STT output and semantic-segment text normalize whitespace around
    punctuation differently (observed: "W05 -Testschrank" vs "W05-Testschrank"),
    so a byte-exact containment check on incidental whitespace rejects a
    faithfully-quoted span. Stripping all whitespace keeps the anti-
    hallucination guarantee (same characters, same order) without being
    sensitive to spacing artifacts that carry no meaning.
    """
    strip_ws=lambda value:re.sub(r"\s+","",value)
    return strip_ws(span) in strip_ws(text)


def _item(row):
    if not row:return None
    return {"session_id":row[0],"primary_intent":row[1],"target_type":row[2],"target_text":row[3],
            "confidence":row[4],"multiple_intents_detected":row[5],"reason_codes":row[6],
            "decision_source":row[7],"created_at":row[8].isoformat(),"updated_at":row[9].isoformat()}


SELECT="""SELECT session_id,primary_intent,target_type,target_text,confidence,
multiple_intents_detected,reason_codes,decision_source,created_at,updated_at FROM session_intent_decisions"""


def get_session_intent_decision(session_id):
    with get_db_connection() as c:row=c.execute(SELECT+" WHERE session_id=%s",(session_id,)).fetchone()
    return _item(row)


def _session_text_and_context(session_id):
    with get_db_connection() as c:
        chunks=c.execute("SELECT text FROM ingestion_chunks WHERE session_id=%s ORDER BY sequence",(session_id,)).fetchall()
        segments=c.execute("""SELECT id,segment_type,text,confidence FROM semantic_segments
        WHERE session_id=%s AND status<>'superseded' ORDER BY sequence,segment_index""",(session_id,)).fetchall()
        artifacts=c.execute("""SELECT artifact_type,content,status FROM session_artifacts
        WHERE session_id=%s AND status<>'superseded' ORDER BY id""",(session_id,)).fetchall()
    text=" ".join(row[0].strip() for row in chunks if row[0].strip()).strip()
    return text,[{"id":r[0],"type":r[1],"text":r[2],"confidence":r[3]} for r in segments],\
        [{"type":r[0],"content":r[1],"status":r[2]} for r in artifacts]


def _validate_decision(raw,text):
    if not isinstance(raw,dict):raise ValueError("Intent response must be an object")
    intent=raw.get("primary_intent");target_type=raw.get("target_type");target_text=raw.get("target_text")
    confidence=raw.get("confidence");multiple=raw.get("multiple_intents_detected");reasons=raw.get("reason_codes")
    if intent not in INTENTS:raise ValueError("Unknown primary intent")
    if target_type not in TARGET_TYPES:raise ValueError("Unknown intent target type")
    if not isinstance(target_text,str):raise ValueError("target_text must be a string")
    target_text=target_text.strip()
    if target_text and not _contains_span(text,target_text):raise ValueError("target_text must be an exact source span")
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not 0<=confidence<=1:
        raise ValueError("Intent confidence must be between 0 and 1")
    if not isinstance(multiple,bool):raise ValueError("multiple_intents_detected must be boolean")
    if not isinstance(reasons,list) or len(reasons)>8 or any(reason not in REASON_CODES for reason in reasons):
        raise ValueError("Unknown or excessive intent reason codes")
    if intent in MUTATION_INTENTS and target_type=="none":raise ValueError("Mutation intent requires a target type")
    if intent in MUTATION_INTENTS and not target_text:raise ValueError("Mutation intent requires an exact target span")
    reasons=list(dict.fromkeys(reasons))
    if intent in MUTATION_INTENTS and _tentative_action(text):
        confidence=min(float(confidence),max(0.0,MUTATION_PART_MIN_CONFIDENCE-.01))
        if "tentative_action" not in reasons:reasons.append("tentative_action")
    else:reasons=[reason for reason in reasons if reason!="tentative_action"]
    return {"primary_intent":intent,"target_type":target_type,"target_text":target_text,
            "confidence":float(confidence),"multiple_intents_detected":multiple,"reason_codes":reasons}


def deterministic_content_intent(text):
    """Deterministic test oracle; production decisions use the structured LLM."""
    lowered=text.casefold()
    multiple=bool(re.search(r"[.!?]\s+",text.strip()[:-1]))
    target_type="list_item" if "liste" in lowered else ("task" if "aufgabe" in lowered else ("note" if "notiz" in lowered else "unknown"))
    if re.search(r"\b(abhaken|abgehakt|hake|haken|erledigt|streiche|streichen|gestrichen)\b",lowered):
        intent="complete";reasons=["marks_done"]
    elif re.search(r"\b(archivieren|archiviere|archiviert|vergessen|vergiss|löschen|lösche)\b",lowered):
        intent="archive";reasons=["removes_or_forgets"]
    elif re.search(r"\b(ändern|ändere|korrigieren|korrigiere|umbenennen|ergänzen)\b",lowered):
        intent="change";reasons=["modifies_existing"]
    elif text.rstrip().endswith("?") or re.match(r"\s*(wer|was|wann|wo|warum|wieso|wie|welche|kann|können|ist|sind)\b",lowered):
        intent="query";target_type="none";reasons=["asks_for_answer"]
    else:
        intent="memo";target_type="none";reasons=["adds_information"]
    tentative=_tentative_action(text)
    confidence=.6 if intent in MUTATION_INTENTS and tentative else 1.0
    if tentative and intent in MUTATION_INTENTS:reasons.append("tentative_action")
    if multiple:reasons.append("multiple_intents")
    target_text=text.strip() if intent in MUTATION_INTENTS else ""
    return _validate_decision({"primary_intent":intent,"target_type":target_type,"target_text":target_text,
        "confidence":confidence,"multiple_intents_detected":multiple,"reason_codes":reasons},text)


async def classify_content_intent_with_llm(text,segments,artifacts):
    profile=get_ai_task_profile("capture.intent")
    schema={"type":"object","properties":{
        "primary_intent":{"type":"string","enum":sorted(INTENTS)},
        "target_type":{"type":"string","enum":sorted(TARGET_TYPES)},
        "target_text":{"type":"string"},"confidence":{"type":"number"},
        "multiple_intents_detected":{"type":"boolean"},
        "reason_codes":{"type":"array","items":{"type":"string","enum":sorted(REASON_CODES)},"maxItems":8}},
        "required":["primary_intent","target_type","target_text","confidence","multiple_intents_detected","reason_codes"],
        "additionalProperties":False}
    payload={"model":profile["model"],"messages":[{"role":"system","content":CAPTURE_INTENT_SYSTEM_PROMPT},
        {"role":"user","content":"EINGABE:\n"+text+"\n\nSEMANTISCHE SEGMENTE:\n"+json.dumps(segments,ensure_ascii=False)+
         "\n\nSESSION-ARTEFAKTE:\n"+json.dumps(artifacts,ensure_ascii=False)}],"temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{"name":"smart_notebook_capture_intent","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    return _validate_decision(json.loads(response.json()["choices"][0]["message"]["content"]),text)


async def ensure_session_intent_decision(session_id,mode="llm"):
    existing=get_session_intent_decision(session_id)
    if existing:return existing
    text,segments,artifacts=_session_text_and_context(session_id)
    if not text:raise ValueError("Cannot classify an empty capture")
    if mode=="deterministic":decision=deterministic_content_intent(text);source="deterministic_test"
    elif mode=="llm":
        decision=await classify_content_intent_with_llm(text,segments,artifacts)
        profile=get_ai_task_profile("capture.intent");source=f"{profile['provider']}:{profile['model']}"
    else:raise ValueError("Intent mode must be llm or deterministic")
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("""INSERT INTO session_intent_decisions(session_id,primary_intent,target_type,target_text,
        confidence,multiple_intents_detected,reason_codes,decision_source,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(session_id) DO UPDATE
        SET updated_at=session_intent_decisions.updated_at RETURNING session_id,primary_intent,target_type,target_text,
        confidence,multiple_intents_detected,reason_codes,decision_source,created_at,updated_at""",
        (session_id,decision["primary_intent"],decision["target_type"],decision["target_text"],decision["confidence"],
         decision["multiple_intents_detected"],Jsonb(decision["reason_codes"]),source,now,now)).fetchone();c.commit()
    return _item(row)


def public_intent_decision(decision):
    if not decision:return None
    return {key:decision[key] for key in ("primary_intent","target_type","target_text","confidence",
                                           "multiple_intents_detected","reason_codes")}


PART_SELECT="""SELECT p.id,p.session_id,p.ordinal,p.primary_intent,p.target_type,p.target_text,
p.source_text,p.source_start,p.source_end,p.confidence,p.reason_codes,p.decision_source,p.created_at,
COALESCE(array_agg(x.segment_id ORDER BY x.segment_id) FILTER(WHERE x.segment_id IS NOT NULL),'{}')
FROM session_intent_parts p LEFT JOIN session_intent_part_segments x ON x.part_id=p.id"""


def _part_item(row):
    return {"id":row[0],"session_id":row[1],"ordinal":row[2],"primary_intent":row[3],
            "target_type":row[4],"target_text":row[5],"source_text":row[6],
            "source_start":row[7],"source_end":row[8],"confidence":row[9],
            "reason_codes":row[10],"decision_source":row[11],
            "created_at":row[12].isoformat(),"source_segment_ids":row[13] or []}


def get_session_intent_parts(session_id):
    with get_db_connection() as c:
        rows=c.execute(PART_SELECT+" WHERE p.session_id=%s GROUP BY p.id ORDER BY p.ordinal",(session_id,)).fetchall()
    return [_part_item(row) for row in rows]


def _validate_parts(raw,text,segments,require_multiple=False):
    if not isinstance(raw,dict) or not isinstance(raw.get("parts"),list):
        raise ValueError("Intent split response must contain a parts list")
    parts=raw["parts"]
    if not parts or len(parts)>MAX_INTENT_PARTS:
        raise ValueError("Intent split must contain between 1 and 12 parts")
    if require_multiple and len(parts)<2:raise ValueError("Multiple intent decision requires at least two parts")
    segment_text={item["id"]:item["text"].strip() for item in segments}
    cursor=0;validated=[]
    for ordinal,part in enumerate(parts,start=1):
        if not isinstance(part,dict) or part.get("ordinal")!=ordinal:
            raise ValueError("Intent part ordinals must be contiguous and start at 1")
        source_text=part.get("source_text")
        if not isinstance(source_text,str) or not source_text.strip():raise ValueError("Intent part source_text must not be empty")
        start=text.find(source_text,cursor)
        if start<0 or text[cursor:start].strip():raise ValueError("Intent parts must be exact, ordered, and non-overlapping")
        end=start+len(source_text);cursor=end
        ids=part.get("source_segment_ids")
        if (not isinstance(ids,list) or not ids or len(ids)>50 or
            any(isinstance(value,bool) or not isinstance(value,int) or value not in segment_text for value in ids)):
            raise ValueError("Intent parts require valid source segment IDs")
        ids=list(dict.fromkeys(ids))
        normalized_source=source_text.strip()
        if any(normalized_source not in segment_text[value] and segment_text[value] not in normalized_source for value in ids):
            raise ValueError("Intent part segment does not support its source span")
        decision=_validate_decision({"primary_intent":part.get("primary_intent"),
            "target_type":part.get("target_type"),"target_text":part.get("target_text"),
            "confidence":part.get("confidence"),"multiple_intents_detected":False,
            "reason_codes":part.get("reason_codes")},source_text)
        validated.append({"ordinal":ordinal,"source_text":source_text,"source_start":start,"source_end":end,
            "source_segment_ids":ids,**{key:decision[key] for key in ("primary_intent","target_type","target_text","confidence","reason_codes")}})
    if text[cursor:].strip():raise ValueError("Intent parts must cover the complete input")
    return validated


def deterministic_intent_parts(text,segments):
    """Deterministic sentence splitter for tests; production uses the LLM."""
    pieces=[part.strip() for part in re.split(r"(?<=[.!?…])\s+|[\r\n]+",text.strip()) if part.strip()]
    raw=[]
    for ordinal,piece in enumerate(pieces or [text.strip()],start=1):
        decision=deterministic_content_intent(piece)
        supporting=[segment["id"] for segment in segments
                    if piece in segment["text"].strip() or segment["text"].strip() in piece]
        raw.append({"ordinal":ordinal,"source_text":piece,"source_segment_ids":supporting,
            **{key:decision[key] for key in ("primary_intent","target_type","target_text","confidence","reason_codes")}})
    return _validate_parts({"parts":raw},text,segments,require_multiple=len(raw)>1)


async def classify_intent_parts_with_llm(text,segments,artifacts):
    profile=get_ai_task_profile("capture.intent_split")
    part_schema={"type":"object","properties":{
        "ordinal":{"type":"integer"},"source_text":{"type":"string"},
        "source_segment_ids":{"type":"array","items":{"type":"integer"},"maxItems":50},
        "primary_intent":{"type":"string","enum":sorted(INTENTS)},
        "target_type":{"type":"string","enum":sorted(TARGET_TYPES)},"target_text":{"type":"string"},
        "confidence":{"type":"number"},
        "reason_codes":{"type":"array","items":{"type":"string","enum":sorted(REASON_CODES)},"maxItems":8}},
        "required":["ordinal","source_text","source_segment_ids","primary_intent","target_type","target_text","confidence","reason_codes"],
        "additionalProperties":False}
    schema={"type":"object","properties":{"parts":{"type":"array","items":part_schema,"maxItems":MAX_INTENT_PARTS}},
            "required":["parts"],"additionalProperties":False}
    context={"input":text,"semantic_segments":segments,"session_artifacts":artifacts}
    payload={"model":profile["model"],"messages":[{"role":"system","content":CAPTURE_INTENT_SPLIT_SYSTEM_PROMPT},
        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{"name":"smart_notebook_intent_parts","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    return _validate_parts(json.loads(response.json()["choices"][0]["message"]["content"]),text,segments,require_multiple=True)


def _persist_intent_parts(session_id,parts,source):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        for part in parts:
            row=c.execute("""INSERT INTO session_intent_parts(session_id,ordinal,primary_intent,target_type,target_text,
            source_text,source_start,source_end,confidence,reason_codes,decision_source,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(session_id,ordinal) DO NOTHING RETURNING id""",
            (session_id,part["ordinal"],part["primary_intent"],part["target_type"],part["target_text"],part["source_text"],
             part["source_start"],part["source_end"],part["confidence"],Jsonb(part["reason_codes"]),source,now)).fetchone()
            if row:
                for segment_id in part["source_segment_ids"]:
                    c.execute("INSERT INTO session_intent_part_segments(part_id,segment_id) VALUES(%s,%s)",(row[0],segment_id))
        c.commit()
    return get_session_intent_parts(session_id)


async def ensure_session_intent_parts(session_id,decision,mode="llm"):
    existing=get_session_intent_parts(session_id)
    if existing:return existing
    text,segments,artifacts=_session_text_and_context(session_id)
    if not text or not segments:raise ValueError("Cannot split intent without source text and segments")
    if not decision["multiple_intents_detected"]:
        parts=[{"ordinal":1,"source_text":text,"source_start":0,"source_end":len(text),
            "source_segment_ids":[item["id"] for item in segments],
            **{key:decision[key] for key in ("primary_intent","target_type","target_text","confidence","reason_codes")}}]
        source=decision["decision_source"]
    elif mode=="deterministic":
        parts=deterministic_intent_parts(text,segments);source="deterministic_test"
    elif mode=="llm":
        parts=await classify_intent_parts_with_llm(text,segments,artifacts)
        profile=get_ai_task_profile("capture.intent_split");source=f"{profile['provider']}:{profile['model']}"
    else:raise ValueError("Intent split mode must be llm or deterministic")
    if decision["primary_intent"] not in {part["primary_intent"] for part in parts}:
        raise ValueError("Intent parts do not contain the persisted primary intent")
    return _persist_intent_parts(session_id,parts,source)


def promotable_artifact_ids_for_parts(session_id,parts):
    if len(parts)<=1:return None
    with get_db_connection() as c:
        rows=c.execute("""SELECT a.id,array_agg(DISTINCT p.primary_intent)
        FROM session_artifacts a JOIN session_artifact_sources s ON s.artifact_id=a.id
        JOIN session_intent_part_segments x ON x.segment_id=s.segment_id
        JOIN session_intent_parts p ON p.id=x.part_id
        WHERE a.session_id=%s GROUP BY a.id ORDER BY a.id""",(session_id,)).fetchall()
    return [row[0] for row in rows if set(row[1])=={"memo"}]


def public_intent_parts(parts):
    return [{key:part[key] for key in ("ordinal","primary_intent","target_type","target_text","source_text",
            "source_start","source_end","confidence","reason_codes")} for part in parts]
