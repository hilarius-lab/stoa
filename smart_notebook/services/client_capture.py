from datetime import datetime
import hashlib
from uuid import UUID,uuid5
from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from .events import create_event_record,mark_event_capture_processed


class CaptureConflict(Exception):pass


CLIENT_TEXT_CAPTURE_SOURCE_TYPE="client_text_capture"


def _provisional_intent(mode,text):
    """Legacy processing-response hint; A02 replaces it at finalization."""
    if mode!="auto":return mode
    lowered=text.casefold().lstrip();words=("wer ","was ","wann ","wo ","warum ","wieso ","wie ","welche ","kann ","können ","ist ","sind ")
    return "query" if text.rstrip().endswith("?") or lowered.startswith(words) else "memo"


def _item(r):
    if not r:return None
    return {"id":str(r[0]),"mode":r[1],"resolved_intent":r[2],"content":r[3],"context_ref":r[4],"event_id":r[5],
            "conversation_id":str(r[6]) if r[6] else None,"turn_id":str(r[7]) if r[7] else None,"status":r[8],"result":r[9],"error":r[10],
            "created_at":r[11].isoformat(),"updated_at":r[12].isoformat(),
            "client_session_id":str(r[13]) if r[13] else None}


SELECT="SELECT id,mode,resolved_intent,content,context_ref,event_id,conversation_id,turn_id,status,result,error,created_at,updated_at,client_session_id FROM client_text_captures"


def _get_capture(capture_id):
    with get_db_connection() as c:r=c.execute(SELECT+" WHERE id=%s",(capture_id,)).fetchone()
    return _item(r)


def _capture_job_error(ingestion_session_id):
    with get_db_connection() as c:
        row=c.execute("""SELECT error FROM processing_jobs
        WHERE ingestion_session_id=%s AND status IN('failed','parked','attention_required')
        ORDER BY updated_at DESC,id DESC LIMIT 1""",(ingestion_session_id,)).fetchone()
    return row[0] if row and row[0] else None


def _sync_capture(item):
    if not item or not item["client_session_id"]:return item
    from .client_sessions import completion_status,get_client_session
    session=get_client_session(item["client_session_id"])
    if not session:return item
    state=completion_status(item["client_session_id"])
    status="processing";result=item["result"];error=None
    resolved=item["resolved_intent"];conversation_id=item["conversation_id"];turn_id=item["turn_id"]
    if state=="completed":
        status="completed";result=session["capture_result"] or result
        if result:
            resolved=result.get("resolved_intent") or resolved
            conversation_id=result.get("conversation_id") or conversation_id
            turn_id=result.get("turn_id") or turn_id
    elif state=="attention_required":
        status="attention_required"
        error=session.get("last_error") or _capture_job_error(session["ingestion_session_id"]) or "processing requires attention"
    elif state in ("failed","aborted"):
        status="failed";error=session.get("last_error") or f"session {state}"
    changed=(status!=item["status"] or result!=item["result"] or error!=item["error"] or
             resolved!=item["resolved_intent"] or str(conversation_id or "")!=str(item["conversation_id"] or "") or
             str(turn_id or "")!=str(item["turn_id"] or ""))
    if changed:
        now=datetime.now(TIMEZONE)
        with get_db_connection() as c:
            c.execute("""UPDATE client_text_captures SET resolved_intent=%s,conversation_id=%s,turn_id=%s,
            status=%s,result=%s,error=%s,updated_at=%s WHERE id=%s""",
            (resolved,conversation_id,turn_id,status,Jsonb(result) if result is not None else None,error,now,item["id"]));c.commit()
        item=_get_capture(item["id"])
        if status=="completed" and item["event_id"]:mark_event_capture_processed(item["event_id"],result or {})
    return item


def get_capture(capture_id):
    return _sync_capture(_get_capture(capture_id))


def sync_capture_for_client_session(client_session_id):
    with get_db_connection() as c:
        row=c.execute(SELECT+" WHERE client_session_id=%s",(client_session_id,)).fetchone()
    return _sync_capture(_item(row))


def _ensure_capture_pipeline(capture_id):
    item=_get_capture(capture_id)
    if not item:return None
    from .client_sessions import create_client_session,finish_client_session,get_client_session,transition_client_session
    from .ingestion import create_ingestion_chunk_record
    from .recovery import repair_ingestion_session_record
    session_id=item["client_session_id"] or uuid5(UUID(str(capture_id)),"text-pipeline-session")
    session=get_client_session(session_id)
    if session:
        with get_db_connection() as c:
            source_type=c.execute("SELECT source_type FROM ingestion_sessions WHERE id=%s",(session["ingestion_session_id"],)).fetchone()
        if not source_type or source_type[0]!=CLIENT_TEXT_CAPTURE_SOURCE_TYPE:
            raise CaptureConflict("client_capture_id conflicts with an unrelated client session")
    else:
        session=create_client_session(session_id,CLIENT_TEXT_CAPTURE_SOURCE_TYPE,source="client_api",
            started_at=datetime.fromisoformat(item["created_at"]),device_metadata={"input":"text"},
            capture_mode=item["mode"],context_ref=item["context_ref"],sequence_base=1)
    if session["state"]=="created":session=transition_client_session(session_id,"start")
    chunk=create_ingestion_chunk_record(session["ingestion_session_id"],1,f"capture:{capture_id}",item["content"])
    if chunk is None:raise RuntimeError("text capture ingestion session disappeared")
    repair_ingestion_session_record(session["ingestion_session_id"],dry_run=False)
    session=finish_client_session(session_id,0)
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("""UPDATE client_text_captures SET client_session_id=%s,status='processing',error=NULL,updated_at=%s
        WHERE id=%s""",(session_id,now,capture_id));c.commit()
    return session


def create_capture(capture_id,mode,content,context_ref=None):
    content=content.strip();digest=hashlib.sha256((mode+"\0"+content+"\0"+str(context_ref or {})).encode()).hexdigest();now=datetime.now(TIMEZONE)
    old=get_capture(capture_id)
    if old:
        with get_db_connection() as c:stored=c.execute("SELECT content_hash FROM client_text_captures WHERE id=%s",(capture_id,)).fetchone()[0]
        if stored!=digest:raise CaptureConflict("client_capture_id already exists with different capture data")
        if old["status"]=="queued":_ensure_capture_pipeline(capture_id)
        return get_capture(capture_id)
    resolved=_provisional_intent(mode,content)
    event=create_event_record(content,source="client_text_capture",client_event_id=str(capture_id));event_id=event["id"]
    conversation_id=turn_id=None;status="queued";result=None
    with get_db_connection() as c:
        c.execute("""INSERT INTO client_text_captures(id,mode,resolved_intent,content,content_hash,context_ref,event_id,conversation_id,turn_id,status,result,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(capture_id,mode,resolved,content,digest,Jsonb(context_ref) if context_ref else None,event_id,conversation_id,turn_id,status,Jsonb(result) if result else None,now,now));c.commit()
    _ensure_capture_pipeline(capture_id)
    return get_capture(capture_id)


async def run_capture_once(mode="production"):
    # Compatibility/recovery worker: new API captures build their durable text
    # pipeline immediately. A queued legacy or interrupted capture is attached
    # to that same pipeline here; no separate classification path remains.
    with get_db_connection() as c:
        row=c.execute(SELECT+" WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row:return {"outcome":"idle","capture":None}
        item=_item(row);c.commit()
    try:
        _ensure_capture_pipeline(item["id"])
        return {"outcome":"processing","capture":get_capture(item["id"])}
    except Exception as exc:
        failed=datetime.now(TIMEZONE)
        with get_db_connection() as c:c.execute("UPDATE client_text_captures SET status='failed',error=%s,updated_at=%s WHERE id=%s",(str(exc),failed,item["id"]));c.commit()
        return {"outcome":"failed","capture":get_capture(item["id"])}
