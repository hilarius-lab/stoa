"""Mutation-free comparison of the active semantic path with an LLM-only shadow."""
from datetime import datetime,timedelta
import hashlib,json,time
import httpx
from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .content_types import CLASSIFICATION_TYPES

TYPES=CLASSIFICATION_TYPES

async def _llm_only(segments):
    profile=get_ai_task_profile("artifacts.session_memory")
    schema={"type":"object","properties":{"classifications":{"type":"array","items":{"type":"object","properties":{
        "segment_id":{"type":"integer"},"artifact_type":{"type":"string","enum":sorted(TYPES)},
        "confidence":{"type":"number"},"abstain":{"type":"boolean"},"reason_codes":{"type":"array","items":{"type":"string"}}},
        "required":["segment_id","artifact_type","confidence","abstain","reason_codes"],"additionalProperties":False}}},
        "required":["classifications"],"additionalProperties":False}
    prompt="""Klassifiziere jeden Meetingabschnitt ohne Regeln oder vorgeschlagene Kandidaten als note, fact, decision, task, list, list_item oder question. Enthalte dich bei Mehrdeutigkeit. Dies ist ein mutationsfreier Shadow-Test; erfinde keine Inhalte."""
    payload={"model":profile["model"],"messages":[{"role":"system","content":prompt},{"role":"user","content":json.dumps(segments,ensure_ascii=False)}],
        "temperature":profile["temperature"],"response_format":{"type":"json_schema","json_schema":{"name":"semantic_shadow","strict":True,"schema":schema}}}
    started=time.perf_counter()
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload);response.raise_for_status()
    latency=round((time.perf_counter()-started)*1000)
    return json.loads(response.json()["choices"][0]["message"]["content"])["classifications"],latency

async def run_semantic_shadow(session_id,mode="llm_only"):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        if connection.execute("SELECT 1 FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None:return None
        rows=connection.execute("""SELECT s.id,s.text,s.segment_type,
        (SELECT a.artifact_type FROM session_artifact_sources x JOIN session_artifacts a ON a.id=x.artifact_id
         WHERE x.segment_id=s.id AND a.status IN('active','confirmed') ORDER BY a.confidence DESC,a.id LIMIT 1),
        (SELECT a.confidence FROM session_artifact_sources x JOIN session_artifacts a ON a.id=x.artifact_id
         WHERE x.segment_id=s.id AND a.status IN('active','confirmed') ORDER BY a.confidence DESC,a.id LIMIT 1)
        FROM semantic_segments s WHERE s.session_id=%s AND s.status='confirmed' ORDER BY s.sequence,s.segment_index,s.id""",(session_id,)).fetchall()
        run_id=connection.execute("""INSERT INTO semantic_shadow_runs(session_id,shadow_mode,status,detail_retain_until,created_at)
        VALUES(%s,%s,'running',%s,%s) RETURNING id""",(session_id,mode,now+timedelta(days=30),now)).fetchone()[0];connection.commit()
    try:
        segments=[{"segment_id":r[0],"text":r[1]} for r in rows]
        if mode=="llm_only":proposals,total_latency=await _llm_only(segments) if segments else ([],0)
        else:
            proposals=[{"segment_id":r[0],"artifact_type":r[2] if r[2] in TYPES else "note","confidence":r[4] or .5,"abstain":False,"reason_codes":["deterministic_test"]} for r in rows];total_latency=0
        valid_ids={r[0] for r in rows};by_id={}
        for proposal in proposals:
            if proposal["segment_id"] in valid_ids and 0<=proposal["confidence"]<=1:by_id[proposal["segment_id"]]=proposal
        confusion={};agreements=0;abstentions=0
        with get_db_connection() as connection:
            for row in rows:
                proposal=by_id.get(row[0],{"artifact_type":"note","confidence":0.0,"abstain":True,"reason_codes":["missing_shadow_result"]})
                active=row[3];shadow=proposal["artifact_type"];abstain=proposal["abstain"];agrees=bool(active and not abstain and active==shadow)
                agreements+=int(agrees);abstentions+=int(abstain);key=f"{active or 'none'}->{shadow if not abstain else 'abstain'}";confusion[key]=confusion.get(key,0)+1
                connection.execute("""INSERT INTO semantic_shadow_results(run_id,segment_id,text_hash,active_type,active_confidence,
                shadow_type,shadow_confidence,shadow_abstained,agrees,reason_codes,latency_ms,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(run_id,row[0],hashlib.sha256(row[1].encode()).hexdigest(),active,row[4],shadow,
                proposal["confidence"],abstain,agrees,Jsonb(proposal["reason_codes"]),round(total_latency/max(1,len(rows))),now))
            summary={"segments":len(rows),"agreements":agreements,"disagreements":len(rows)-agreements-abstentions,
                "abstentions":abstentions,"agreement_rate":agreements/len(rows) if rows else 1.0,"confusion":confusion,"total_latency_ms":total_latency}
            connection.execute("UPDATE semantic_shadow_runs SET status='completed',summary=%s,completed_at=%s WHERE id=%s",(Jsonb(summary),datetime.now(TIMEZONE),run_id));connection.commit()
        return get_shadow_run(run_id)
    except Exception as exc:
        with get_db_connection() as connection:connection.execute("UPDATE semantic_shadow_runs SET status='failed',summary=%s,completed_at=%s WHERE id=%s",(Jsonb({"error":str(exc)}),datetime.now(TIMEZONE),run_id));connection.commit()
        raise

def get_shadow_run(run_id):
    with get_db_connection() as connection:
        row=connection.execute("SELECT id,session_id,shadow_mode,status,summary,detail_retain_until,created_at,completed_at FROM semantic_shadow_runs WHERE id=%s",(run_id,)).fetchone()
        if row is None:return None
        results=connection.execute("""SELECT segment_id,active_type,active_confidence,shadow_type,shadow_confidence,shadow_abstained,
        agrees,reason_codes,latency_ms FROM semantic_shadow_results WHERE run_id=%s ORDER BY segment_id""",(run_id,)).fetchall()
    return {"id":row[0],"session_id":row[1],"shadow_mode":row[2],"status":row[3],"summary":row[4],
        "detail_retain_until":row[5].isoformat(),"created_at":row[6].isoformat(),"completed_at":row[7].isoformat() if row[7] else None,
        "results":[{"segment_id":r[0],"active_type":r[1],"active_confidence":r[2],"shadow_type":r[3],"shadow_confidence":r[4],
        "shadow_abstained":r[5],"agrees":r[6],"reason_codes":r[7],"latency_ms":r[8]} for r in results]}

def purge_expired_shadow_details():
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        rows=connection.execute("""DELETE FROM semantic_shadow_results r USING semantic_shadow_runs run
        WHERE r.run_id=run.id AND run.detail_retain_until<=%s RETURNING r.id""",(now,)).fetchall();connection.commit()
    return len(rows)
