"""Privacy-preserving structured events for Docker stdout and short-lived PostgreSQL diagnostics."""
from datetime import datetime,timedelta
import json,sys,uuid

from psycopg.types.json import Jsonb

from ..config import SYSTEM_LOG_RETENTION_HOURS,RETRIEVAL_CACHE_TTL_HOURS,TIMEZONE
from ..database import get_db_connection

_SENSITIVE_KEYS={"text","content","prompt","response","audio","password","token","secret","authorization","cookie"}

def _safe(value):
    if not isinstance(value,dict):return {}
    return {str(k):v for k,v in value.items() if str(k).casefold() not in _SENSITIVE_KEYS and isinstance(v,(str,int,float,bool,type(None)))}

def emit_event(component,event,level="info",request_id=None,session_id=None,job_id=None,metadata=None):
    now=datetime.now(TIMEZONE);record={"ts":now.isoformat(),"level":level,"component":component,"event":event,
        "request_id":request_id,"session_id":session_id,"job_id":job_id,"metadata":_safe(metadata)}
    print(json.dumps(record,ensure_ascii=False,separators=(",",":")),file=sys.stdout,flush=True)
    try:
        with get_db_connection() as c:
            c.execute("""INSERT INTO system_logs(occurred_at,level,component,event,request_id,session_id,job_id,metadata)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",(now,level,component,event,request_id,session_id,job_id,Jsonb(record['metadata'])));c.commit()
    except Exception:
        pass
    return record

def purge_expired_logs():
    cutoff=datetime.now(TIMEZONE)-timedelta(hours=SYSTEM_LOG_RETENTION_HOURS)
    with get_db_connection() as c:
        count=c.execute("DELETE FROM system_logs WHERE occurred_at<%s",(cutoff,)).rowcount;c.commit()
    return count

def system_status():
    with get_db_connection() as c:
        queues=[{"status":r[0],"count":r[1]} for r in c.execute("SELECT status,count(*) FROM processing_jobs GROUP BY status ORDER BY status").fetchall()]
        workers=[{"worker_id":r[0],"kind":r[1],"status":r[2],"job_id":r[3],"last_seen_at":r[4].isoformat()} for r in c.execute(
            "SELECT worker_id,worker_kind,status,current_job_id,last_seen_at FROM worker_heartbeats ORDER BY worker_id").fetchall()]
        watermarks={"sessions":r[0],"received_lag":r[1] or 0,"processing_lag":r[2] or 0,"artifact_lag":r[3] or 0} if (r:=c.execute(
            """SELECT count(*),sum(GREATEST(received_through_sequence-queued_through_sequence,0)),
            sum(GREATEST(queued_through_sequence-processed_through_sequence,0)),sum(GREATEST(processed_through_sequence-artifact_through_sequence,0)) FROM ingestion_session_watermarks""").fetchone()) else {}
        errors=[{"component":r[0],"event":r[1],"count":r[2]} for r in c.execute("""SELECT component,event,count(*) FROM system_logs
            WHERE occurred_at>=now()-(%s * interval '1 hour') AND level IN('error','critical') GROUP BY component,event ORDER BY count(*) DESC""",
            (SYSTEM_LOG_RETENTION_HOURS,)).fetchall()]
        semantics=c.execute("""SELECT count(*),count(*) FILTER(WHERE abstained),count(*) FILTER(WHERE validated)
            FROM artifact_classifications""").fetchone()
        promotions=c.execute("SELECT count(*) FILTER(WHERE promotion_error IS NOT NULL),count(*) FILTER(WHERE promoted_at IS NOT NULL) FROM session_artifacts").fetchone()
        model_jobs=[{"job_type":r[0],"attempts":r[1],"total_duration_ms":r[2] or 0,"average_duration_ms":float(r[3] or 0)} for r in c.execute(
            """SELECT j.job_type,count(*),sum(a.duration_ms),avg(a.duration_ms) FROM processing_job_attempts a JOIN processing_jobs j ON j.id=a.job_id
            WHERE a.completed_at IS NOT NULL GROUP BY j.job_type ORDER BY j.job_type""").fetchall()]
        embedding_eval=c.execute("""SELECT count(*),count(*) FILTER(WHERE out_of_distribution),
            count(*) FILTER(WHERE direct_decision_allowed) FROM semantic_example_evaluations""").fetchone()
        cache=c.execute("SELECT count(*),COALESCE(sum(hit_count),0),count(*) FILTER(WHERE expires_at<=now()) FROM retrieval_cache").fetchone()
    return {"generated_at":datetime.now(TIMEZONE).isoformat(),"log_retention_hours":SYSTEM_LOG_RETENTION_HOURS,
        "queues":queues,"workers":workers,"watermarks":watermarks,"recent_errors":errors,
        "semantics":{"classifications":semantics[0],"abstentions":semantics[1],"validated":semantics[2]},
        "promotions":{"errors":promotions[0],"completed":promotions[1]},
        "semantic_embedding_shadow":{"evaluations":embedding_eval[0],"out_of_distribution":embedding_eval[1],
            "direct_decisions":embedding_eval[2]},
        "model_job_time":model_jobs,
        "cache":{"implemented":True,"entries":cache[0],"hits":cache[1],"expired_entries":cache[2],"ttl_hours":RETRIEVAL_CACHE_TTL_HOURS},
        "gpu_time":{"available":False,"reason":"provider_does_not_report_gpu_time"}}
