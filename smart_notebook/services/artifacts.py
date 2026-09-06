# Live session artifact service
from datetime import datetime
import json,re
import httpx
from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from ..prompts import SESSION_ARTIFACT_SYSTEM_PROMPT
from .jobs import (
    claim_processing_job_record, complete_processing_job_record,
    enqueue_processing_job_record, fail_processing_job_record
)
from .recovery import refresh_session_watermarks, synchronize_processing_step_for_job
from .topics import create_session_topic_record, link_artifact_topic_record
from .ai_tasks import get_ai_task_profile
from .semantic_router import route_artifact, validate_route
from .semantic_examples import evaluate_semantic_examples
from .observability import emit_event

ARTIFACT_STEP = "session_artifacts"
ARTIFACT_JOB = "session_artifacts"


class SessionArtifactConflictError(Exception):
    pass


def _artifact_from_row(row):
    if row is None:
        return None
    artifact = {
        "id": row[0], "session_id": row[1], "artifact_type": row[2],
        "content": row[3], "status": row[4], "confidence": row[5],
        "origin_key": row[6], "superseded_by_artifact_id": row[7],
        "created_at": row[8].isoformat(), "updated_at": row[9].isoformat(),
        "source_segment_ids": row[10] or []
    }
    with get_db_connection() as connection:
        classification=connection.execute("""SELECT candidate_type,alternative_type,normalized_data,evidence_spans,reason_codes,
        missing_fields,confidence,decision_source,abstained,validated FROM artifact_classifications WHERE artifact_id=%s""",(row[0],)).fetchone()
    artifact["classification"] = ({"candidate_type":classification[0],"alternative_type":classification[1],"normalized_data":classification[2],
        "evidence_spans":classification[3],"reason_codes":classification[4],"missing_fields":classification[5],"confidence":classification[6],
        "decision_source":classification[7],"abstained":classification[8],"validated":classification[9]} if classification else None)
    return artifact


ARTIFACT_SELECT = """
    SELECT
        artifacts.id, artifacts.session_id, artifacts.artifact_type,
        artifacts.content, artifacts.status, artifacts.confidence,
        artifacts.origin_key, artifacts.superseded_by_artifact_id,
        artifacts.created_at, artifacts.updated_at,
        COALESCE(array_agg(sources.segment_id ORDER BY sources.segment_id)
            FILTER (WHERE sources.segment_id IS NOT NULL), '{}')
    FROM session_artifacts AS artifacts
    LEFT JOIN session_artifact_sources AS sources
      ON sources.artifact_id = artifacts.id
"""


def get_session_artifact_record(artifact_id):
    with get_db_connection() as connection:
        row = connection.execute(
            ARTIFACT_SELECT + " WHERE artifacts.id = %s GROUP BY artifacts.id",
            (artifact_id,)
        ).fetchone()
    return _artifact_from_row(row)


def list_session_artifact_records(session_id, include_inactive=False):
    with get_db_connection() as connection:
        exists = connection.execute(
            "SELECT id FROM ingestion_sessions WHERE id = %s", (session_id,)
        ).fetchone()
        if exists is None:
            return None
        condition = ""
        if not include_inactive:
            condition = " AND artifacts.status IN ('active', 'confirmed')"
        rows = connection.execute(
            ARTIFACT_SELECT
            + " WHERE artifacts.session_id = %s" + condition
            + " GROUP BY artifacts.id ORDER BY artifacts.created_at, artifacts.id",
            (session_id,)
        ).fetchall()
    return [_artifact_from_row(row) for row in rows]


def enqueue_artifact_processing_for_chunk(session_id, chunk_id, sequence):
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        step = connection.execute(
            """
            INSERT INTO chunk_processing_steps (
                session_id, chunk_id, sequence, step_type, status,
                attempts, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, 'pending', 0, %s, %s)
            ON CONFLICT (chunk_id, step_type) DO UPDATE
            SET updated_at = chunk_processing_steps.updated_at
            RETURNING id, processing_job_id
            """,
            (session_id, chunk_id, sequence, ARTIFACT_STEP, now, now)
        ).fetchone()
        connection.commit()
    job = enqueue_processing_job_record(
        job_type=ARTIFACT_JOB,
        ingestion_session_id=session_id,
        chunk_id=chunk_id,
        sequence=sequence,
        payload={"step_type": ARTIFACT_STEP},
        idempotency_key=f"{ARTIFACT_STEP}:chunk:{chunk_id}"
    )
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE chunk_processing_steps
            SET processing_job_id = %s, status = %s, attempts = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (job["id"], job["status"], job["attempts"], now, step[0])
        )
        connection.commit()
    return job


def _artifact_type_for_segment(segment_type):
    return {
        "note_candidate": "note",
        "task_candidate": "task",
        "list_item_candidate": "list_item",
        "statement": "fact",
        "other": "fact"
    }.get(segment_type)


def _create_artifact_for_segment(connection, session_id, segment, now):
    artifact_type = _artifact_type_for_segment(segment[2])
    if artifact_type is None:
        return None
    origin_key = f"segment:{segment[0]}"
    row = connection.execute(
        """
        INSERT INTO session_artifacts (
            session_id, artifact_type, content, status, confidence,
            origin_key, created_at, updated_at
        ) VALUES (%s, %s, %s, 'active', %s, %s, %s, %s)
        ON CONFLICT (origin_key) DO UPDATE
        SET updated_at = session_artifacts.updated_at
        RETURNING id
        """,
        (
            session_id, artifact_type, segment[1], segment[3],
            origin_key, now, now
        )
    ).fetchone()
    connection.execute(
        """
        INSERT INTO session_artifact_sources (
            artifact_id, segment_id, relation, created_at
        ) VALUES (%s, %s, 'source', %s)
        ON CONFLICT (artifact_id, segment_id) DO NOTHING
        """,
        (row[0], segment[0], now)
    )
    return row[0]


def _attach_artifact_sources(artifact_id, segment_ids):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        for segment_id in segment_ids:
            connection.execute("""INSERT INTO session_artifact_sources(artifact_id,segment_id,relation,created_at)
            VALUES(%s,%s,'source',%s) ON CONFLICT(artifact_id,segment_id) DO NOTHING""",(artifact_id,segment_id,now))
        connection.commit()

def _link_evidenced_topics(artifact_id,segment_ids):
    from ..config import TOPIC_LINK_MIN_CONFIDENCE
    with get_db_connection() as connection:
        rows=connection.execute("""SELECT DISTINCT e.topic_id,e.match_mode,e.confidence FROM session_topic_evidence e
        WHERE e.segment_id=ANY(%s) AND e.confidence>=%s""",(segment_ids,TOPIC_LINK_MIN_CONFIDENCE)).fetchall()
    for topic_id,mode,confidence in rows:
        relation='inherited_topic' if mode=='context_inherited' else 'primary_topic'
        link_artifact_topic_record(artifact_id,topic_id,relation,confidence)

def _save_classification(artifact_id,classification):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        connection.execute("""INSERT INTO artifact_classifications(artifact_id,candidate_type,alternative_type,normalized_data,evidence_spans,
        reason_codes,missing_fields,confidence,decision_source,abstained,validated,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(artifact_id) DO UPDATE SET candidate_type=EXCLUDED.candidate_type,alternative_type=EXCLUDED.alternative_type,
        normalized_data=EXCLUDED.normalized_data,evidence_spans=EXCLUDED.evidence_spans,reason_codes=EXCLUDED.reason_codes,
        missing_fields=EXCLUDED.missing_fields,confidence=EXCLUDED.confidence,decision_source=EXCLUDED.decision_source,
        abstained=EXCLUDED.abstained,validated=EXCLUDED.validated,updated_at=EXCLUDED.updated_at""",
        (artifact_id,classification['candidate_type'],classification.get('alternative_type'),Jsonb(classification.get('normalized_data',{})),
         Jsonb(classification.get('evidence_spans',[])),Jsonb(classification.get('reason_codes',[])),Jsonb(classification.get('missing_fields',[])),
         classification['confidence'],classification.get('decision_source','hybrid'),classification.get('abstain',False),
         classification.get('validated',False),now,now));connection.commit()

def _create_llm_artifact(session_id,chunk_id,op_index,operation):
    now=datetime.now(TIMEZONE)
    status='confirmed' if operation.get('validated') else 'active'
    with get_db_connection() as connection:
        row=connection.execute("""INSERT INTO session_artifacts(session_id,artifact_type,content,status,confidence,origin_key,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(origin_key) DO UPDATE SET updated_at=session_artifacts.updated_at RETURNING id""",
        (session_id,operation['artifact_type'],operation['content'],status,operation['confidence'],f"llm:chunk:{chunk_id}:op:{op_index}",now,now)).fetchone();connection.commit()
    _attach_artifact_sources(row[0],operation['source_segment_ids'])
    if operation.get('classification'):_save_classification(row[0],operation['classification'])
    return row[0]

def _task_modifier(text):
    """Return a conservative urgency modifier with an explicit task referent."""
    reference=re.search(r"\b(?:diese|die|jene)\s+aufgabe\b",text,re.I)
    if not reference:return None
    signals=(
        (r"\b(?:äußerst|sehr)\s+(?:wichtig|dringend)\b",0.9,"explicit_high_urgency"),
        (r"\b(?:höchste\s+priorität|sofort|unverzüglich)\b",1.0,"explicit_critical_urgency"),
        (r"\b(?:wichtig|dringend)\b",0.8,"explicit_urgency"),
        (r"\b(?:nicht\s+dringend|geringe\s+priorität|nicht\s+wichtig)\b",0.2,"explicit_low_urgency"),
    )
    # Low/negated phrases must win over their nested positive token.
    signals=(signals[3],)+signals[:3]
    for pattern,urgency,reason in signals:
        match=re.search(pattern,text,re.I)
        if match:return {"urgency":urgency,"urgency_source":"explicit","reason_code":reason,
                         "evidence_spans":[reference.group(0),match.group(0)]}
    return None

def _adjacent_task_modifier_operation(session_id,segment_id,text,segment_confidence):
    modifier=_task_modifier(text)
    if not modifier:return None
    with get_db_connection() as connection:
        current=connection.execute("SELECT sequence FROM semantic_segments WHERE id=%s AND session_id=%s",(segment_id,session_id)).fetchone()
        if not current:return None
        target=connection.execute("""SELECT a.id,a.content,a.confidence,c.normalized_data
        FROM session_artifacts a JOIN session_artifact_sources src ON src.artifact_id=a.id
        JOIN semantic_segments s ON s.id=src.segment_id
        LEFT JOIN artifact_classifications c ON c.artifact_id=a.id
        WHERE a.session_id=%s AND a.artifact_type='task' AND a.status IN('active','confirmed')
          AND s.sequence=%s ORDER BY s.segment_index DESC,a.updated_at DESC LIMIT 1""",
          (session_id,current[0]-1)).fetchone()
    if not target:return None
    normalized={**(target[3] or {}),"urgency":modifier['urgency'],"urgency_source":modifier['urgency_source']}
    classification={"candidate_type":"task","alternative_type":None,"normalized_data":normalized,
        "evidence_spans":modifier['evidence_spans'],"reason_codes":[modifier['reason_code']],"missing_fields":[],
        "confidence":max(float(target[2]),float(segment_confidence),modifier['urgency']),"decision_source":"rules",
        "abstain":False,"validated":True}
    return {"action":"update","target_artifact_id":target[0],"artifact_type":"task","content":target[1],
        "confidence":classification['confidence'],"source_segment_ids":[segment_id],"topic_titles":[],
        "validated":True,"classification":classification}

def _router_overrides(session_id,segments,topics,started_at):
    topic_titles=[row[1] for row in topics];operations=[];handled=set();new_topics=[]
    for segment_id,text,segment_type,segment_confidence in segments:
        modifier_operation=_adjacent_task_modifier_operation(session_id,segment_id,text,segment_confidence)
        if modifier_operation:
            handled.add(segment_id);operations.append(modifier_operation);continue
        route=route_artifact(text,started_at,topic_titles);valid,errors=validate_route(text,route)
        if not valid or route['confidence']<0.85 or route['candidate_type']=='question':continue
        handled.add(segment_id);route['validated']=True;route['decision_source']='rules'
        if route['candidate_type']=='list_item':
            target=route['normalized_data']['target_list'];new_topics.append({"title":target,"description":"Explizit genannte Zielliste.","confidence":route['confidence']})
            for item in route['normalized_data']['items']:
                item_route={**route,"normalized_data":{**route['normalized_data'],"items":[item]}}
                operations.append({"action":"create","target_artifact_id":0,"artifact_type":"list_item","content":item,
                    "confidence":route['confidence'],"source_segment_ids":[segment_id],"topic_titles":[target],"validated":True,"classification":item_route})
        else:
            operations.append({"action":"create","target_artifact_id":0,"artifact_type":route['candidate_type'],"content":text,
                # Never attach the first active topic merely because it exists.
                # Direct topic links require explicit evidence; inherited links
                # are derived later by the topic hierarchy/retrieval layer.
                "confidence":route['confidence'],"source_segment_ids":[segment_id],"topic_titles":[],"validated":True,"classification":route})
    return operations,handled,new_topics

async def _propose_artifact_operations(session_id,chunk_id):
    profile=get_ai_task_profile("artifacts.session_memory")
    with get_db_connection() as connection:
        segments=connection.execute("""SELECT id,text,segment_type,confidence FROM semantic_segments
        WHERE chunk_id=%s AND status='confirmed' ORDER BY segment_index""",(chunk_id,)).fetchall()
        artifacts=connection.execute("""SELECT id,artifact_type,content,status,confidence FROM session_artifacts
        WHERE session_id=%s AND status IN('active','confirmed') ORDER BY updated_at DESC LIMIT 100""",(session_id,)).fetchall()
        topics=connection.execute("SELECT id,title,description FROM session_topics WHERE session_id=%s AND status='active' ORDER BY id",(session_id,)).fetchall()
        started_at=connection.execute("SELECT started_at FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone()[0]
    # Embedding examples remain mutation-free during alpha. Persist their
    # nearest-class/OOD signal for calibration, but do not alter routing.
    for segment in segments:
        try:await evaluate_semantic_examples(segment[0],segment[1])
        except Exception as exc:emit_event("semantic_examples","shadow_evaluation_failed","warning",
            session_id=session_id,metadata={"segment_id":segment[0],"error_type":type(exc).__name__})
    overrides,handled,router_topics=_router_overrides(session_id,segments,topics,started_at)
    unresolved=[r for r in segments if r[0] not in handled]
    if not unresolved:return {"topics":router_topics,"operations":overrides}
    schema={"type":"object","properties":{"topics":{"type":"array","items":{"type":"object","properties":{"title":{"type":"string"},"description":{"type":"string"},"confidence":{"type":"number"}},"required":["title","description","confidence"],"additionalProperties":False}},"operations":{"type":"array","items":{"type":"object","properties":{"action":{"type":"string","enum":["create","update","confirm","supersede","dismiss","none"]},"target_artifact_id":{"type":"integer"},"artifact_type":{"type":"string","enum":["note","task","list","list_item","fact","decision"]},"content":{"type":"string"},"confidence":{"type":"number"},"source_segment_ids":{"type":"array","items":{"type":"integer"}},"topic_titles":{"type":"array","items":{"type":"string"}},"evidence_spans":{"type":"array","items":{"type":"string"}},"reason_codes":{"type":"array","items":{"type":"string"}},"missing_fields":{"type":"array","items":{"type":"string"}},"abstain":{"type":"boolean"}},"required":["action","target_artifact_id","artifact_type","content","confidence","source_segment_ids","topic_titles","evidence_spans","reason_codes","missing_fields","abstain"],"additionalProperties":False}}},"required":["topics","operations"],"additionalProperties":False}
    routing=[route_artifact(r[1],started_at,[t[1] for t in topics]) for r in unresolved]
    context=json.dumps({"new_segments":[{"id":r[0],"text":r[1],"type":r[2],"confidence":r[3],"router":routing[i]} for i,r in enumerate(unresolved)],"active_artifacts":[{"id":r[0],"type":r[1],"content":r[2],"status":r[3],"confidence":r[4]} for r in artifacts],"active_topics":[{"id":r[0],"title":r[1],"description":r[2]} for r in topics]},ensure_ascii=False)
    system=SESSION_ARTIFACT_SYSTEM_PROMPT+"\nNutze nur die verbleibenden Kandidaten und exakte Evidence-Spans. Bei Unsicherheit setze abstain=true und action=none. Erfinde keine Felder."
    payload={"model":profile['model'],"messages":[{"role":"system","content":system},{"role":"user","content":context}],"temperature":profile['temperature'],"response_format":{"type":"json_schema","json_schema":{"name":"smart_notebook_session_artifacts","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile['timeout_seconds'], trust_env=False) as client: response=await client.post(profile['endpoint'],json=payload)
    if response.is_error: raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    proposal=json.loads(response.json()['choices'][0]['message']['content'])
    valid_segments={r[0] for r in segments};valid_artifacts={r[0] for r in artifacts}
    for op in proposal.get('operations',[]):
        if not set(op['source_segment_ids']).issubset(valid_segments):raise ValueError('LLM proposed unknown source segment')
        if op['action'] in {'update','confirm','supersede','dismiss'} and op['target_artifact_id'] not in valid_artifacts:raise ValueError('LLM proposed unknown target artifact')
        if op['action'] in {'create','none'} and op['target_artifact_id']!=0:raise ValueError('create/none target_artifact_id must be 0')
        if not 0<=op['confidence']<=1:raise ValueError('Artifact confidence must be between 0 and 1')
        source_text=" ".join(r[1] for r in unresolved if r[0] in op['source_segment_ids'])
        spans_valid=all(span.casefold() in source_text.casefold() for span in op['evidence_spans'])
        op['validated']=bool(not op['abstain'] and not op['missing_fields'] and spans_valid and op['evidence_spans'])
        op['classification']={"candidate_type":op['artifact_type'],"alternative_type":None,"normalized_data":{},
            "evidence_spans":op['evidence_spans'],"reason_codes":op['reason_codes'],"missing_fields":op['missing_fields'],
            "confidence":op['confidence'],"decision_source":"llm","abstain":op['abstain'],"validated":op['validated']}
        if op['abstain']:op['action']='none';op['target_artifact_id']=0
    proposal['topics']=proposal.get('topics',[])+router_topics;proposal['operations']=proposal.get('operations',[])+overrides
    return proposal

def _apply_llm_proposal(session_id,chunk_id,proposal):
    topic_by_title={}
    for topic in proposal.get('topics',[]):
        created=create_session_topic_record(session_id,topic['title'],topic['description'],topic['confidence']);topic_by_title[topic['title']]=created
    artifact_ids=[]
    for index,op in enumerate(proposal.get('operations',[]),start=1):
        action=op['action'];artifact_id=None
        if action=='create':artifact_id=_create_llm_artifact(session_id,chunk_id,index,op)
        elif action=='update':artifact_id=op['target_artifact_id'];update_session_artifact_record(artifact_id,op['content'],op['confidence']);_attach_artifact_sources(artifact_id,op['source_segment_ids'])
        elif action=='confirm':artifact_id=op['target_artifact_id'];set_session_artifact_status(artifact_id,'confirmed');_attach_artifact_sources(artifact_id,op['source_segment_ids'])
        elif action=='dismiss':artifact_id=op['target_artifact_id'];set_session_artifact_status(artifact_id,'dismissed');_attach_artifact_sources(artifact_id,op['source_segment_ids'])
        elif action=='supersede':
            result=supersede_session_artifact_record(op['target_artifact_id'],op['artifact_type'],op['content'],op['confidence']);artifact_id=result['replacement']['id'];_attach_artifact_sources(artifact_id,op['source_segment_ids'])
        if artifact_id:
            artifact_ids.append(artifact_id)
            if op.get('classification'):_save_classification(artifact_id,op['classification'])
            _link_evidenced_topics(artifact_id,op['source_segment_ids'])
            for title in op['topic_titles']:
                topic=topic_by_title.get(title) or create_session_topic_record(session_id,title,'',op['confidence']);topic_by_title[title]=topic
                link_artifact_topic_record(artifact_id,topic['id'],'primary_topic',op['confidence'])
    return artifact_ids

async def run_session_artifact_worker_once(worker_id,mode="llm",ingestion_session_id=None):
    worker_id = worker_id.strip()
    if not worker_id:
        raise ValueError("worker_id must not be empty")
    job = claim_processing_job_record(worker_id, job_type=ARTIFACT_JOB, ingestion_session_id=ingestion_session_id)
    if job is None:
        return {"outcome": "idle", "job": None, "artifacts": []}
    try:
        now = datetime.now(TIMEZONE)
        with get_db_connection() as connection:
            segments = connection.execute(
                """
                SELECT id, text, segment_type, confidence
                FROM semantic_segments
                WHERE chunk_id = %s AND status = 'confirmed'
                ORDER BY segment_index
                """,
                (job["chunk_id"],)
            ).fetchall()
            artifact_ids = []
            if mode == "deterministic":
                for segment in segments:
                    artifact_id = _create_artifact_for_segment(connection, job["ingestion_session_id"], segment, now)
                    if artifact_id is not None: artifact_ids.append(artifact_id)
            connection.commit()
        if mode == "llm":
            proposal=await _propose_artifact_operations(job['ingestion_session_id'],job['chunk_id'])
            artifact_ids=_apply_llm_proposal(job['ingestion_session_id'],job['chunk_id'],proposal)
        completed = complete_processing_job_record(
            job["id"], worker_id,
            {"artifact_count": len(artifact_ids), "artifact_ids": artifact_ids,"mode":mode}
        )
        synchronize_processing_step_for_job(job["id"])
        refresh_session_watermarks(job["ingestion_session_id"])
        from .client_sessions import settle_client_session_for_ingestion
        settle_client_session_for_ingestion(job["ingestion_session_id"])
        return {
            "outcome": "completed", "job": completed,
            "artifacts": [get_session_artifact_record(i) for i in artifact_ids]
        }
    except Exception as exc:
        failed = fail_processing_job_record(job["id"], worker_id, str(exc))
        synchronize_processing_step_for_job(job["id"])
        refresh_session_watermarks(job["ingestion_session_id"])
        return {"outcome": "failed", "job": failed, "artifacts": [], "error": str(exc)}


def update_session_artifact_record(artifact_id, content=None, confidence=None):
    if content is not None:
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        current = connection.execute(
            "SELECT status FROM session_artifacts WHERE id = %s FOR UPDATE",
            (artifact_id,)
        ).fetchone()
        if current is None:
            return None
        if current[0] not in {"active", "confirmed"}:
            raise SessionArtifactConflictError("Inactive artifact cannot be updated")
        connection.execute(
            """
            UPDATE session_artifacts
            SET content = COALESCE(%s, content),
                confidence = COALESCE(%s, confidence), updated_at = %s
            WHERE id = %s
            """,
            (content, confidence, now, artifact_id)
        )
        connection.commit()
    return get_session_artifact_record(artifact_id)


def set_session_artifact_status(artifact_id, status):
    if status not in {"confirmed", "dismissed"}:
        raise ValueError("Unknown artifact status")
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        current = connection.execute(
            "SELECT status FROM session_artifacts WHERE id = %s FOR UPDATE",
            (artifact_id,)
        ).fetchone()
        if current is None:
            return None
        if current[0] in {"superseded", "dismissed"}:
            raise SessionArtifactConflictError("Inactive artifact cannot change status")
        connection.execute(
            "UPDATE session_artifacts SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, artifact_id)
        )
        connection.commit()
    return get_session_artifact_record(artifact_id)


def supersede_session_artifact_record(
    artifact_id, artifact_type, content, confidence
):
    content = content.strip()
    if not content:
        raise ValueError("content must not be empty")
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        current = connection.execute(
            """
            SELECT session_id, status FROM session_artifacts
            WHERE id = %s FOR UPDATE
            """,
            (artifact_id,)
        ).fetchone()
        if current is None:
            return None
        if current[1] not in {"active", "confirmed"}:
            raise SessionArtifactConflictError("Inactive artifact cannot be superseded")
        replacement = connection.execute(
            """
            INSERT INTO session_artifacts (
                session_id, artifact_type, content, status, confidence,
                origin_key, created_at, updated_at
            ) VALUES (%s, %s, %s, 'active', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                current[0], artifact_type, content, confidence,
                f"supersede:{artifact_id}:{now.isoformat()}", now, now
            )
        ).fetchone()
        connection.execute(
            """
            INSERT INTO session_artifact_sources (
                artifact_id, segment_id, relation, created_at
            )
            SELECT %s, segment_id, 'supersedes_source', %s
            FROM session_artifact_sources WHERE artifact_id = %s
            """,
            (replacement[0], now, artifact_id)
        )
        connection.execute(
            """
            UPDATE session_artifacts
            SET status = 'superseded', superseded_by_artifact_id = %s,
                updated_at = %s WHERE id = %s
            """,
            (replacement[0], now, artifact_id)
        )
        connection.commit()
    return {
        "superseded": get_session_artifact_record(artifact_id),
        "replacement": get_session_artifact_record(replacement[0])
    }
