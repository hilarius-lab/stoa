from datetime import datetime
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb

from ..config import AUDIO_RETENTION_CACHE_DIR,TIMEZONE
from ..database import get_db_connection
from .audio import schedule_final_stt_windows


ACTIVE_STATES=("created","recording","paused","draining","processing","failed","attention_required")
PROBLEM_JOB_STATES=("failed","parked","attention_required")
TRANSITIONS={
    "start":({"created"},"recording"),
    "pause":({"recording"},"paused"),
    "resume":({"paused"},"recording"),
}


class ClientSessionConflict(Exception):pass


def _serialize(row):
    if not row:return None
    keys=("client_session_id","ingestion_session_id","state","device_metadata","capture_mode","sequence_base","context_ref","capture_result","expected_final_sequence",
          "final_source_end_ms","paused_at","finish_requested_at","finalized_at","aborted_at","last_error","created_at","updated_at",
          "local_audio_release_allowed","local_audio_release_at")
    item=dict(zip(keys,row));item["client_session_id"]=str(item["client_session_id"])
    for key in ("paused_at","finish_requested_at","finalized_at","aborted_at","created_at","updated_at","local_audio_release_at"):
        item[key]=item[key].isoformat() if item[key] else None
    return item


SELECT="""SELECT client_session_id,ingestion_session_id,state,device_metadata,capture_mode,sequence_base,context_ref,capture_result,expected_final_sequence,
final_source_end_ms,paused_at,finish_requested_at,finalized_at,aborted_at,last_error,created_at,updated_at,
local_audio_release_allowed,local_audio_release_at FROM client_sessions"""


def get_client_session(client_session_id):
    with get_db_connection() as c:row=c.execute(SELECT+" WHERE client_session_id=%s",(client_session_id,)).fetchone()
    return _serialize(row)


def list_client_sessions(limit=None,offset=0,include_closed=False):
    if include_closed:
        with get_db_connection() as c:rows=c.execute(SELECT+" ORDER BY created_at DESC,client_session_id DESC LIMIT %s OFFSET %s",(limit,offset)).fetchall()
    else:
        with get_db_connection() as c:rows=c.execute(SELECT+" WHERE state=ANY(%s) ORDER BY updated_at DESC",(list(ACTIVE_STATES),)).fetchall()
    return [_serialize(row) for row in rows]


def _audit(c,session_id,event,old,new,metadata=None):
    c.execute("INSERT INTO client_session_audit(client_session_id,event_type,from_state,to_state,metadata,occurred_at) VALUES(%s,%s,%s,%s,%s,%s)",
              (session_id,event,old,new,Jsonb(metadata or {}),datetime.now(TIMEZONE)))


def _reuse_client_session(existing,client_session_id,capture_mode,context_ref,device_metadata,sequence_base):
    if existing["capture_mode"]!=capture_mode or existing["context_ref"]!=(context_ref or None):
        raise ClientSessionConflict("client_session_id already exists with different capture_mode or context_ref")
    if sequence_base is not None and existing["sequence_base"]!=sequence_base:
        raise ClientSessionConflict("client_session_id already exists with different sequence_base")
    metadata={key:value for key,value in (device_metadata or {}).items() if key!="sequence_base"}
    if existing["device_metadata"]!=metadata:
        # Device description is not session identity. Updating it must not
        # change updated_at, otherwise an idempotent retry changes the session.
        with get_db_connection() as c:
            c.execute("UPDATE client_sessions SET device_metadata=%s WHERE client_session_id=%s",(Jsonb(metadata),client_session_id));c.commit()
        existing=get_client_session(client_session_id)
    return existing


def create_client_session(client_session_id,source_type,title=None,source=None,started_at=None,device_metadata=None,capture_mode="meeting",context_ref=None,sequence_base=None):
    existing=get_client_session(client_session_id)
    if existing:
        return _reuse_client_session(existing,client_session_id,capture_mode,context_ref,device_metadata,sequence_base)
    metadata=dict(device_metadata or {})
    effective_sequence_base=sequence_base
    if effective_sequence_base is None:
        effective_sequence_base=0 if metadata.get("sequence_base")==0 else 1
    metadata.pop("sequence_base",None)
    from .ingestion import create_ingestion_session_record
    ingestion=create_ingestion_session_record(source_type,title,source,started_at);now=datetime.now(TIMEZONE)
    try:
        with get_db_connection() as c:
            c.execute("""INSERT INTO client_sessions(client_session_id,ingestion_session_id,state,device_metadata,capture_mode,sequence_base,context_ref,created_at,updated_at)
            VALUES(%s,%s,'created',%s,%s,%s,%s,%s,%s)""",(client_session_id,ingestion["id"],Jsonb(metadata),capture_mode,effective_sequence_base,Jsonb(context_ref) if context_ref else None,now,now))
            _audit(c,client_session_id,"created",None,"created",{"ingestion_session_id":ingestion["id"]});c.commit()
    except Exception:
        with get_db_connection() as c:c.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion["id"],));c.commit()
        existing=get_client_session(client_session_id)
        if existing:return _reuse_client_session(existing,client_session_id,capture_mode,context_ref,device_metadata,sequence_base)
        raise
    return get_client_session(client_session_id)


def transition_client_session(client_session_id,action):
    allowed,target=TRANSITIONS[action];now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("SELECT state FROM client_sessions WHERE client_session_id=%s FOR UPDATE",(client_session_id,)).fetchone()
        if not row:return None
        old=row[0]
        if old==target:
            c.commit()
            return _serialize(c.execute(SELECT+" WHERE client_session_id=%s",(client_session_id,)).fetchone())
        if old not in allowed:raise ClientSessionConflict(f"cannot {action} a session in state {old}")
        paused=now if target=="paused" else None
        c.execute("UPDATE client_sessions SET state=%s,paused_at=%s,updated_at=%s WHERE client_session_id=%s",(target,paused,now,client_session_id))
        event={"start":"started","pause":"paused","resume":"resumed"}[action]
        _audit(c,client_session_id,event,old,target);c.commit()
    return get_client_session(client_session_id)


def reconciliation(client_session_id):
    item=get_client_session(client_session_id)
    if not item:return None
    chunks=[]
    if item["ingestion_session_id"]:
        with get_db_connection() as c:
            rows=c.execute("SELECT sequence,client_chunk_id,content_hash,byte_length,status,source_start_ms,source_end_ms FROM audio_chunks WHERE session_id=%s ORDER BY sequence",(item["ingestion_session_id"],)).fetchall()
        chunks=[{"sequence":r[0],"client_chunk_id":r[1],"content_hash":r[2],"byte_length":r[3],"status":r[4],"source_start_ms":r[5],"source_end_ms":r[6],"durable_ack":True} for r in rows]
    expected=item["expected_final_sequence"]
    received={x["sequence"] for x in chunks}
    missing=[n for n in range(1,(expected or 0)+1) if n not in received]
    with get_db_connection() as c:
        conflict_rows=c.execute("SELECT sequence,client_chunk_id,conflict_code,expected,received,occurred_at FROM client_upload_conflicts WHERE client_session_id=%s ORDER BY occurred_at DESC LIMIT 100",(client_session_id,)).fetchall()
    conflicts=[{"sequence":r[0],"client_chunk_id":r[1],"code":r[2],"expected":r[3],"received":r[4],"occurred_at":r[5].isoformat()} for r in conflict_rows]
    return {"client_session_id":item["client_session_id"],"state":item["state"],"expected_final_sequence":expected,
            "received_sequences":sorted(received),"missing_sequences":missing,"chunks":chunks,
            "conflicts":conflicts,"upload_complete":expected is not None and not missing and len(received)==expected}


def record_upload_conflict(client_session_id,sequence,client_chunk_id,code,expected=None,received=None):
    with get_db_connection() as c:
        c.execute("INSERT INTO client_upload_conflicts(client_session_id,sequence,client_chunk_id,conflict_code,expected,received,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                  (client_session_id,sequence,client_chunk_id,code,Jsonb(expected or {}),Jsonb(received or {}),datetime.now(TIMEZONE)));c.commit()


def completion_status(client_session_id):
    item=get_client_session(client_session_id)
    if not item:return None
    if item["state"] in ("completed","failed","attention_required"):return item["state"]
    rec=reconciliation(client_session_id)
    if item["state"]=="draining" and not rec["upload_complete"]:return "uploads_pending"
    if item["ingestion_session_id"]:
        with get_db_connection() as c:
            blocked=c.execute("SELECT count(*) FROM processing_jobs WHERE ingestion_session_id=%s AND status=ANY(%s)",(item["ingestion_session_id"],list(PROBLEM_JOB_STATES))).fetchone()[0]
        if blocked:return "attention_required"
    return "processing"


def finish_client_session(client_session_id,final_sequence,final_source_end_ms=None):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("SELECT state,ingestion_session_id,expected_final_sequence FROM client_sessions WHERE client_session_id=%s FOR UPDATE",(client_session_id,)).fetchone()
        if not row:return None
        old,ingestion_id,previous=row
        if old in ("aborted","completed"):raise ClientSessionConflict(f"cannot finish a session in state {old}")
        if previous is not None and previous!=final_sequence:raise ClientSessionConflict("final_sequence conflicts with the previously closed upload horizon")
        # The client is expected to keep retrying finish until it locally
        # confirms completion (contract, not a bug) — a retry that lands after
        # the session already reached processing must be a no-op, not a
        # regression back to draining. Observed on the real device: twelve
        # draining/processing round-trips for one session over roughly three
        # hours, all from this exact path, before mark_settled() could ever
        # fire client-side.
        if old=="processing":
            c.commit()
            return get_client_session(client_session_id)
        c.execute("UPDATE client_sessions SET state='draining',expected_final_sequence=%s,final_source_end_ms=%s,finish_requested_at=COALESCE(finish_requested_at,%s),updated_at=%s WHERE client_session_id=%s",
                  (final_sequence,final_source_end_ms,now,now,client_session_id))
        _audit(c,client_session_id,"finish_requested",old,"draining",{"final_sequence":final_sequence});c.commit()
    rec=reconciliation(client_session_id)
    if rec["upload_complete"]:
        from .ingestion import finish_ingestion_session_record
        legacy=finish_ingestion_session_record(ingestion_id)
        if legacy:schedule_final_stt_windows(ingestion_id)
        with get_db_connection() as c:c.execute("UPDATE client_sessions SET state='processing',updated_at=%s WHERE client_session_id=%s",(datetime.now(TIMEZONE),client_session_id));c.commit()
    return get_client_session(client_session_id)


def finalize_client_session(client_session_id):
    rec=reconciliation(client_session_id)
    if not rec:return None
    item=get_client_session(client_session_id)
    if item["state"]=="completed":
        if item["capture_result"] is None:_materialize_capture_result(client_session_id)
        _release_local_audio(client_session_id)
        return get_client_session(client_session_id)
    if item["state"] not in ("processing","attention_required") or not rec["upload_complete"]:raise ClientSessionConflict("session is not ready to finalize")
    with get_db_connection() as c:
        statuses=dict(c.execute("SELECT status,count(*) FROM processing_jobs WHERE ingestion_session_id=%s AND status<>'done' GROUP BY status",(item["ingestion_session_id"],)).fetchall())
        blocked=sum(statuses.get(status,0) for status in PROBLEM_JOB_STATES)
        if blocked:
            now=datetime.now(TIMEZONE);message=f"{blocked} processing job(s) require attention"
            if item["state"]!="attention_required":
                c.execute("UPDATE client_sessions SET state='attention_required',last_error=%s,updated_at=%s WHERE client_session_id=%s",(message,now,client_session_id))
                _audit(c,client_session_id,"state_reconciled",item["state"],"attention_required",{"reason":"processing_jobs_require_attention","job_statuses":statuses})
            c.commit()
            raise ClientSessionConflict("session has processing jobs that require attention")
        pending=sum(statuses.values())
        if pending:raise ClientSessionConflict("session still has pending processing jobs")
        if item["state"]=="attention_required":
            now=datetime.now(TIMEZONE)
            c.execute("UPDATE client_sessions SET state='processing',last_error=NULL,updated_at=%s WHERE client_session_id=%s",(now,client_session_id))
            _audit(c,client_session_id,"state_reconciled","attention_required","processing",{"reason":"processing_jobs_recovered"})
            c.commit()
    # Materialization is part of the release barrier. Do it while the session
    # is still recoverably in `processing`; a failure must never leave a
    # completed session whose source audio was released without a result.
    _materialize_capture_result(client_session_id)
    with get_db_connection() as c:
        now=datetime.now(TIMEZONE);c.execute("UPDATE client_sessions SET state='completed',finalized_at=%s,updated_at=%s WHERE client_session_id=%s",(now,now,client_session_id))
        c.execute("UPDATE ingestion_sessions SET status='completed',updated_at=%s WHERE id=%s",(now,item["ingestion_session_id"]))
        _audit(c,client_session_id,"finalized","processing","completed");c.commit()
    _release_local_audio(client_session_id)
    return get_client_session(client_session_id)


def _release_local_audio(client_session_id):
    """Monotone release after the server has completed and materialized a session."""
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("""SELECT state,capture_result,local_audio_release_allowed FROM client_sessions
        WHERE client_session_id=%s FOR UPDATE""",(client_session_id,)).fetchone()
        if not row or row[2] or row[0]!="completed" or row[1] is None:return False
        c.execute("""UPDATE client_sessions SET local_audio_release_allowed=TRUE,local_audio_release_at=%s
        WHERE client_session_id=%s""",(now,client_session_id))
        _audit(c,client_session_id,"local_audio_released","completed","completed",{"scope":"session"});c.commit()
    return True


async def settle_client_session_for_ingestion(ingestion_session_id):
    """Finalize and promote a ready client session after its last job.

    BACKEND_LOGIK.md A09/D02: new validated artifacts were auto-confirmed,
    but nothing in the automatic worker chain ever promoted them, so a
    recorded memo never became a visible task without a manual API call.
    Knowledge finalization and promotion deliberately precede the technical
    client completion and local-audio release barrier.  A failed promotion
    therefore leaves the client session recoverably in ``processing``.
    """
    if ingestion_session_id is None:return None
    with get_db_connection() as c:
        row=c.execute("SELECT client_session_id FROM client_sessions WHERE ingestion_session_id=%s AND state IN('processing','attention_required')",(ingestion_session_id,)).fetchone()
    if not row:return None
    try:return await finalize_client_session_with_knowledge(row[0])
    except ClientSessionConflict:
        return None
    except Exception as exc:
        # The processing job is already durable ``done`` when settlement is
        # attempted.  Never try to fail that completed job retroactively.
        # A real promotion failure is persisted on the client session and can
        # be retried through the idempotent client finalize endpoint.
        from .observability import emit_event
        emit_event("client_session","knowledge_finalization_failed","error",metadata={"error_type":type(exc).__name__})
        return None


async def finalize_client_session_with_knowledge(client_session_id,promotion_mode="llm",allow_text_only_compatibility=False):
    """Run the knowledge barrier before marking a client session complete."""
    item=get_client_session(client_session_id)
    if not item:return None
    if item["state"]=="completed":return finalize_client_session(client_session_id)
    rec=reconciliation(client_session_id)
    if item["state"] not in ("processing","attention_required") or not rec["upload_complete"]:
        raise ClientSessionConflict("session is not ready to finalize")
    from .intelligence import finalize_session
    from .promotion import promote_session_artifacts
    try:finalize_session(item["ingestion_session_id"])
    except ValueError as exc:
        if allow_text_only_compatibility:
            with get_db_connection() as c:
                audio_count=c.execute("SELECT count(*) FROM audio_chunks WHERE session_id=%s",(item["ingestion_session_id"],)).fetchone()[0]
                job_count=c.execute("SELECT count(*) FROM processing_jobs WHERE ingestion_session_id=%s",(item["ingestion_session_id"],)).fetchone()[0]
            # Frozen client-contract compatibility: a directly injected text
            # chunk historically materializes a capture result without the
            # session interpretation pipeline.  It has no source audio to
            # release and remains the explicit D03 exception.
            if audio_count==0 and job_count==0:return finalize_client_session(client_session_id)
        raise ClientSessionConflict(str(exc)) from exc
    try:await promote_session_artifacts(item["ingestion_session_id"],promotion_mode)
    except Exception as exc:
        now=datetime.now(TIMEZONE);error=f"{type(exc).__name__}: knowledge promotion failed"
        with get_db_connection() as c:
            current=c.execute("SELECT state FROM client_sessions WHERE client_session_id=%s FOR UPDATE",(client_session_id,)).fetchone()
            if current and current[0] in ("processing","attention_required"):
                c.execute("UPDATE client_sessions SET state='attention_required',last_error=%s,updated_at=%s WHERE client_session_id=%s",(error,now,client_session_id))
                if current[0]!="attention_required":_audit(c,client_session_id,"state_reconciled",current[0],"attention_required",{"reason":"knowledge_finalization_failed","error_type":type(exc).__name__})
                c.commit()
        raise
    return finalize_client_session(client_session_id)


def _materialize_capture_result(client_session_id):
    item=get_client_session(client_session_id)
    if not item or item["capture_result"] is not None:return item["capture_result"] if item else None
    if item["capture_mode"]=="meeting":result={"resolved_intent":"meeting"}
    else:
        with get_db_connection() as c:rows=c.execute("SELECT text FROM ingestion_chunks WHERE session_id=%s ORDER BY sequence",(item["ingestion_session_id"],)).fetchall()
        text=" ".join(r[0].strip() for r in rows if r[0].strip()).strip()
        if not text:raise ClientSessionConflict("stabilized transcript is empty; capture cannot be materialized")
        mode=item["capture_mode"]
        if mode=="auto":
            lowered=text.casefold().lstrip();question_words=("wer ","was ","wann ","wo ","warum ","wieso ","wie ","welche ","kann ","können ","ist ","sind ")
            mode="query" if text.rstrip().endswith("?") or lowered.startswith(question_words) else "memo"
        if mode=="query":
            from uuid import UUID,uuid5
            from .client_chat import create_conversation
            namespace=UUID(str(client_session_id));chat=create_conversation(uuid5(namespace,"conversation"),uuid5(namespace,"message:1"),uuid5(namespace,"turn:1"),text)
            result={"resolved_intent":"query","transcript_text":text,"conversation_id":chat["conversation"]["id"],"turn_id":chat["turn"]["id"]}
        else:result={"resolved_intent":"memo","transcript_text":text}
    with get_db_connection() as c:c.execute("UPDATE client_sessions SET capture_result=%s,updated_at=%s WHERE client_session_id=%s",(Jsonb(result),datetime.now(TIMEZONE),client_session_id));c.commit()
    return result


def abort_client_session(client_session_id,reason=None):
    item=get_client_session(client_session_id)
    if not item:return None
    if item["state"]=="aborted":return item
    if item["state"]=="completed":raise ClientSessionConflict("a completed session cannot be aborted")
    ingestion_id=item["ingestion_session_id"]
    if ingestion_id:
        with get_db_connection() as c:keys=[r[0] for r in c.execute("SELECT storage_key FROM audio_chunks WHERE session_id=%s",(ingestion_id,)).fetchall()]
        root=Path(AUDIO_RETENTION_CACHE_DIR).resolve()
        for key in keys:
            path=(root/key).resolve()
            if root in path.parents:path.unlink(missing_ok=True)
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        if ingestion_id:c.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
        c.execute("UPDATE client_sessions SET ingestion_session_id=NULL,state='aborted',aborted_at=%s,last_error=%s,updated_at=%s WHERE client_session_id=%s",(now,reason,now,client_session_id))
        _audit(c,client_session_id,"aborted",item["state"],"aborted",{"reason":reason,"purged_ingestion_session_id":ingestion_id});c.commit()
    return get_client_session(client_session_id)
