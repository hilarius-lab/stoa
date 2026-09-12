from datetime import datetime,timedelta
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb

from ..config import AUDIO_RETENTION_CACHE_DIR,TIMEZONE
from ..database import get_db_connection
from .audio import schedule_final_stt_windows,stabilize_transcripts


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
    visible="NOT EXISTS(SELECT 1 FROM client_text_captures captures WHERE captures.client_session_id=client_sessions.client_session_id)"
    if include_closed:
        with get_db_connection() as c:rows=c.execute(SELECT+f" WHERE {visible} ORDER BY created_at DESC,client_session_id DESC LIMIT %s OFFSET %s",(limit,offset)).fetchall()
    else:
        with get_db_connection() as c:rows=c.execute(SELECT+f" WHERE state=ANY(%s) AND {visible} ORDER BY updated_at DESC",(list(ACTIVE_STATES),)).fetchall()
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
        # the session already moved past draining (processing, or stalled at
        # attention_required) must be a no-op, not a regression back to
        # draining. Observed on the real device: twelve draining/processing
        # round-trips for one session over roughly three hours, all from this
        # exact path, before mark_settled() could ever fire client-side. The
        # attention_required case regressed the same way (session 1119): a
        # retried finish landed after capture_intent_failed had already set
        # attention_required, pushed the session back to draining, and then
        # crashed below because the ingestion session had already advanced —
        # stranding it in draining permanently instead of leaving the retry a
        # no-op.
        if old in ("processing","attention_required"):
            c.commit()
            return get_client_session(client_session_id)
        c.execute("UPDATE client_sessions SET state='draining',expected_final_sequence=%s,final_source_end_ms=%s,finish_requested_at=COALESCE(finish_requested_at,%s),updated_at=%s WHERE client_session_id=%s",
                  (final_sequence,final_source_end_ms,now,now,client_session_id))
        _audit(c,client_session_id,"finish_requested",old,"draining",{"final_sequence":final_sequence});c.commit()
    rec=reconciliation(client_session_id)
    if rec["upload_complete"]:
        from .ingestion import finish_ingestion_session_record,get_ingestion_session_record
        # finish_ingestion_session_record() raises for any status other than
        # 'open'/'finished' (routers/ingestion.py relies on that to report a
        # 409 for its own legacy finish endpoint). By the time a retried
        # finish reaches here, the worker pipeline may have already advanced
        # the ingestion session past 'open' on its own; calling the legacy
        # finish again would raise uncaught here and strand the session in
        # 'draining' (session 1119). Only call it while it is still safe to.
        current=get_ingestion_session_record(ingestion_id)
        if current and current["status"]=="open":
            legacy=finish_ingestion_session_record(ingestion_id)
            if legacy:
                schedule_final_stt_windows(ingestion_id)
                # schedule_final_stt_windows only fills in a window that never
                # got a transcription job at all. A single-window session
                # (the common case for a short memo) can instead have already
                # finished transcribing *before* this line flips
                # ingestion_sessions.status to 'finished' -- run_stt_once()
                # read the still-'open' status a moment earlier and passed
                # force=False, so its lone window stayed 'provisional' with
                # nothing left to ever revisit it: stabilize_transcripts() is
                # otherwise only ever called from inside that same completion
                # hook. Real case: session 1388 on 2026-09-12, stuck for hours
                # with a fully transcribed but never-confirmed window.
                #
                # force=True only when nothing else is still transcribing --
                # the same condition audio.py's own call already uses. A later
                # overlapping window can still revise an earlier window's
                # provisional tail (see stabilize_transcripts's docstring
                # further down); confirming here while that is in flight would
                # freeze a not-yet-corrected transcript. If something is still
                # pending, that job's own completion will re-run this with the
                # correct flag once it is the last one -- ingestion_sessions
                # is already 'finished' by then, so the race this closes
                # cannot recur for it.
                with get_db_connection() as c:
                    still_transcribing=c.execute("""SELECT 1 FROM processing_jobs
                    WHERE ingestion_session_id=%s AND job_type='audio_transcription'
                      AND status IN('queued','running') LIMIT 1""",(ingestion_id,)).fetchone()
                if not still_transcribing:stabilize_transcripts(ingestion_id,force=True)
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


async def settle_client_session_for_ingestion(ingestion_session_id,mode="llm"):
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
    try:
        result=await finalize_client_session_with_knowledge(row[0],promotion_mode=mode)
        from .client_capture import sync_capture_for_client_session
        sync_capture_for_client_session(row[0])
        return result
    except ClientSessionConflict:
        return None
    except Exception as exc:
        # The processing job is already durable ``done`` when settlement is
        # attempted.  Never try to fail that completed job retroactively.
        # A real promotion failure is persisted on the client session and can
        # be retried through the idempotent client finalize endpoint.
        from .observability import emit_event
        emit_event("client_session","knowledge_finalization_failed","error",metadata={"error_type":type(exc).__name__})
        from .client_capture import sync_capture_for_client_session
        sync_capture_for_client_session(row[0])
        return None


def claim_attention_required_client_sessions_for_night_repair(limit=100):
    """Claim up to `limit` attention_required sessions for one retry each.

    A11: unlike processing_jobs.parked (jobs.py::queue_parked_jobs_for_night_repair),
    client_sessions.attention_required from capture_intent_failed,
    knowledge_finalization_failed or clarification_answer_failed had no
    retry at all -- nothing ever called finalize_client_session_with_knowledge
    again on its own. Mirrors that job-repair shape: one attempt per session,
    ever, gated by night_repair_attempts, so a session that fails again after
    its repair escalates and stays attention_required for good rather than
    being retried forever.
    """
    now=datetime.now(TIMEZONE);limit=max(1,min(limit,1000))
    with get_db_connection() as c:
        rows=c.execute("""WITH candidates AS(SELECT client_session_id FROM client_sessions
        WHERE state='attention_required' AND night_repair_attempts=0 AND ingestion_session_id IS NOT NULL
        ORDER BY updated_at,client_session_id FOR UPDATE SKIP LOCKED LIMIT %s)
        UPDATE client_sessions cs SET night_repair_attempts=1,updated_at=%s FROM candidates ca
        WHERE cs.client_session_id=ca.client_session_id
        RETURNING cs.client_session_id,cs.ingestion_session_id""",(limit,now)).fetchall();c.commit()
    return [{"client_session_id":r[0],"ingestion_session_id":r[1]} for r in rows]


async def retry_attention_required_client_sessions_for_night_repair(limit=100,mode="llm"):
    """Run the one claimed repair attempt for each session, synchronously.

    There is no separate worker pool for client_sessions the way processing_jobs
    has one; settle_client_session_for_ingestion already owns the retry's error
    handling (ClientSessionConflict / generic exceptions both leave the session
    in attention_required, now with night_repair_attempts=1) and its own
    transactions, so each claimed session is retried directly here.
    """
    claimed=claim_attention_required_client_sessions_for_night_repair(limit)
    results=[]
    for item in claimed:
        await settle_client_session_for_ingestion(item["ingestion_session_id"],mode)
        after=get_client_session(item["client_session_id"])
        results.append({"client_session_id":item["client_session_id"],
                         "ingestion_session_id":item["ingestion_session_id"],
                         "state":after["state"] if after else None})
    return results


def claim_stalled_processing_client_sessions_for_night_repair(limit=100,older_than_minutes=10):
    """Claim `processing` sessions whose whole job graph is done but which never
    finalized, for one repair attempt each.

    Real case, session 1390 on 2026-09-12: every processing_jobs row for its
    ingestion_session_id reached 'done' (audio_transcription, text_processing,
    session_artifacts), yet client_sessions.state stayed 'processing' with
    last_error=None -- settle_client_session_for_ingestion() silently swallows
    ClientSessionConflict (see its docstring: "a failed promotion therefore
    leaves the client session recoverably in processing"), and unlike
    attention_required, nothing else ever revisits a 'processing' session --
    finish_client_session() explicitly no-ops a retried finish once state is
    already 'processing' or attention_required. Calling
    finalize_client_session_with_knowledge() by hand on the real session
    completed it immediately with no error at all, so whatever blocked the
    original automatic attempt was transient. `older_than_minutes` exists so
    this does not race a session whose last job finished moments ago and whose
    own completion hook has not run settle() yet.
    """
    now=datetime.now(TIMEZONE);limit=max(1,min(limit,1000));cutoff=now-timedelta(minutes=older_than_minutes)
    with get_db_connection() as c:
        rows=c.execute("""WITH candidates AS(SELECT cs.client_session_id FROM client_sessions cs
        WHERE cs.state='processing' AND cs.night_repair_attempts=0 AND cs.ingestion_session_id IS NOT NULL
          AND cs.updated_at<%s
          AND NOT EXISTS(SELECT 1 FROM processing_jobs pj WHERE pj.ingestion_session_id=cs.ingestion_session_id AND pj.status<>'done')
        ORDER BY cs.updated_at,cs.client_session_id FOR UPDATE SKIP LOCKED LIMIT %s)
        UPDATE client_sessions cs SET night_repair_attempts=1,updated_at=%s FROM candidates ca
        WHERE cs.client_session_id=ca.client_session_id
        RETURNING cs.client_session_id,cs.ingestion_session_id""",(cutoff,limit,now)).fetchall();c.commit()
    return [{"client_session_id":r[0],"ingestion_session_id":r[1]} for r in rows]


async def retry_stalled_processing_client_sessions_for_night_repair(limit=100,mode="llm"):
    """Run the one claimed repair attempt for each stalled session.

    A repair that still ends in 'processing' (the silent-swallow case this
    exists for) is promoted to attention_required with its own
    night_repair_attempts reset to 0 -- a genuine hand-off to the existing
    attention_required repair for one further, independent try, rather than a
    second silent dead end. A repair that already produced a more specific
    attention_required (capture_intent_failed and friends set their own
    last_error before raising) is left exactly as that call left it: this
    counts as its one attempt, same as everywhere else in this file.
    """
    claimed=claim_stalled_processing_client_sessions_for_night_repair(limit)
    results=[]
    for item in claimed:
        await settle_client_session_for_ingestion(item["ingestion_session_id"],mode)
        after=get_client_session(item["client_session_id"])
        if after and after["state"]=="processing":
            now=datetime.now(TIMEZONE)
            with get_db_connection() as c:
                c.execute("""UPDATE client_sessions SET state='attention_required',night_repair_attempts=0,
                last_error='stalled in processing after a completed job graph; automatic repair could not progress it',
                updated_at=%s WHERE client_session_id=%s AND state='processing'""",
                          (now,item["client_session_id"]))
                _audit(c,item["client_session_id"],"state_reconciled","processing","attention_required",
                       {"reason":"stalled_processing_repair_failed"});c.commit()
            after=get_client_session(item["client_session_id"])
        results.append({"client_session_id":item["client_session_id"],
                         "ingestion_session_id":item["ingestion_session_id"],
                         "state":after["state"] if after else None})
    return results


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
    from .capture_intent import (MUTATION_INTENTS,ensure_session_intent_decision,
        ensure_session_intent_parts,promotable_artifact_ids_for_parts)
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
    context=item["context_ref"] if isinstance(item["context_ref"],dict) else None
    if context and context.get("type")=="clarification":
        text=_stabilized_text(item["ingestion_session_id"])
        from .clarifications import resolve_clarification_answer
        try:await resolve_clarification_answer(item["ingestion_session_id"],context,text,promotion_mode)
        except Exception as exc:
            _mark_client_finalization_attention(client_session_id,"clarification_answer_failed",exc)
            raise
        return finalize_client_session(client_session_id)
    intent_decision=None;intent_parts=[]
    if item["capture_mode"]=="auto":
        try:
            intent_decision=await ensure_session_intent_decision(item["ingestion_session_id"],promotion_mode)
            intent_parts=await ensure_session_intent_parts(item["ingestion_session_id"],intent_decision,promotion_mode)
        except Exception as exc:
            _mark_client_finalization_attention(client_session_id,"capture_intent_failed",exc)
            raise
    withheld_part_ids=set()
    if item["capture_mode"]=="auto" and intent_parts:
        try:
            from .stt_uncertainty import ensure_session_stt_uncertainty
            withheld_part_ids=await ensure_session_stt_uncertainty(item["ingestion_session_id"],intent_parts,promotion_mode)
        except Exception as exc:
            _mark_client_finalization_attention(client_session_id,"stt_uncertainty_failed",exc)
            raise
    active_intent_parts=[part for part in intent_parts if part["id"] not in withheld_part_ids]
    # A03 permits only artifacts supported exclusively by memo parts through
    # the ordinary creation path. Query and mutation segments cannot leak into
    # a new note/task/list; A06/A07 will resolve and execute those mutations.
    promotion_ids=promotable_artifact_ids_for_parts(item["ingestion_session_id"],intent_parts) if len(intent_parts)>1 else None
    if withheld_part_ids:
        from .stt_uncertainty import blocked_artifact_ids_for_parts
        blocked=blocked_artifact_ids_for_parts(item["ingestion_session_id"],withheld_part_ids)
        if blocked:
            if promotion_ids is None:
                with get_db_connection() as c:
                    promotion_ids=[r[0] for r in c.execute("SELECT id FROM session_artifacts WHERE session_id=%s",
                                                            (item["ingestion_session_id"],)).fetchall() if r[0] not in blocked]
            else:promotion_ids=[i for i in promotion_ids if i not in blocked]
        if len(intent_parts)==1 and intent_parts[0]["id"] in withheld_part_ids:promotion_ids=[]
    promotion_deferred=bool(intent_decision and len(intent_parts)==1 and
                            intent_decision["primary_intent"] in MUTATION_INTENTS)
    try:
        if item["capture_mode"]=="auto":
            from .knowledge_preflight import ensure_session_knowledge_preflights
            preflight_artifact_ids=[] if promotion_deferred else promotion_ids
            await ensure_session_knowledge_preflights(item["ingestion_session_id"],active_intent_parts,
                                                       preflight_artifact_ids,promotion_mode)
            from .mutation_targets import ensure_session_mutation_target_resolutions
            await ensure_session_mutation_target_resolutions(item["ingestion_session_id"],active_intent_parts,promotion_mode)
            from .mutation_actions import ensure_session_mutation_actions
            await ensure_session_mutation_actions(item["ingestion_session_id"],active_intent_parts,promotion_mode)
        if not promotion_deferred and promotion_ids!=[]:
            if promotion_ids is None:
                await promote_session_artifacts(item["ingestion_session_id"],promotion_mode)
            else:
                await promote_session_artifacts(item["ingestion_session_id"],promotion_mode,artifact_ids=promotion_ids)
    except Exception as exc:
        _mark_client_finalization_attention(client_session_id,"knowledge_finalization_failed",exc)
        raise
    return finalize_client_session(client_session_id)


def _mark_client_finalization_attention(client_session_id,reason,exc):
    now=datetime.now(TIMEZONE);error=f"{type(exc).__name__}: {reason.replace('_',' ')}"
    with get_db_connection() as c:
        current=c.execute("SELECT state FROM client_sessions WHERE client_session_id=%s FOR UPDATE",(client_session_id,)).fetchone()
        if current and current[0] in ("processing","attention_required"):
            c.execute("UPDATE client_sessions SET state='attention_required',last_error=%s,updated_at=%s WHERE client_session_id=%s",(error,now,client_session_id))
            if current[0]!="attention_required":_audit(c,client_session_id,"state_reconciled",current[0],"attention_required",{"reason":reason,"error_type":type(exc).__name__})
            c.commit()


def _stabilized_text(ingestion_session_id):
    with get_db_connection() as c:
        rows=c.execute("SELECT text FROM ingestion_chunks WHERE session_id=%s ORDER BY sequence",
                       (ingestion_session_id,)).fetchall()
    return " ".join(r[0].strip() for r in rows if r[0].strip()).strip()


def _materialize_capture_result(client_session_id):
    item=get_client_session(client_session_id)
    if not item or item["capture_result"] is not None:return item["capture_result"] if item else None
    if item["capture_mode"]=="meeting":result={"resolved_intent":"meeting"}
    else:
        text=_stabilized_text(item["ingestion_session_id"])
        if not text:raise ClientSessionConflict("stabilized transcript is empty; capture cannot be materialized")
        context=item["context_ref"] if isinstance(item["context_ref"],dict) else None
        if context and context.get("type")=="clarification":
            from .clarifications import get_clarification_attempt
            attempt=get_clarification_attempt(item["ingestion_session_id"])
            if not attempt or attempt["status"] in {"processing","failed"}:
                raise ClientSessionConflict("clarification answer is not materialized")
            result={"resolved_intent":"clarification","transcript_text":text,
                    "clarification":attempt["result"]}
            intent_decision=None;intent_parts=[];mode="clarification"
        else:mode=item["capture_mode"];intent_decision=None;intent_parts=[]
        if mode=="auto":
            from .capture_intent import (get_session_intent_decision,get_session_intent_parts,
                public_intent_decision,public_intent_parts)
            intent_decision=get_session_intent_decision(item["ingestion_session_id"])
            if intent_decision:
                mode=intent_decision["primary_intent"]
                intent_parts=get_session_intent_parts(item["ingestion_session_id"])
            else:
                # Compatibility only for old text-only D03 sessions that have
                # no processing jobs and therefore no semantic intent stage.
                lowered=text.casefold().lstrip();question_words=("wer ","was ","wann ","wo ","warum ","wieso ","wie ","welche ","kann ","können ","ist ","sind ")
                mode="query" if text.rstrip().endswith("?") or lowered.startswith(question_words) else "memo"
        query_text=("\n".join(part["source_text"].strip() for part in intent_parts
                              if part["primary_intent"]=="query") if intent_parts else
                    (text if mode=="query" else ""))
        if mode=="clarification":pass
        elif query_text:
            from uuid import UUID,uuid5
            from .client_chat import create_conversation
            namespace=UUID(str(client_session_id));chat=create_conversation(uuid5(namespace,"conversation"),uuid5(namespace,"message:1"),uuid5(namespace,"turn:1"),query_text)
            result={"resolved_intent":mode,"transcript_text":text,"conversation_id":chat["conversation"]["id"],"turn_id":chat["turn"]["id"]}
        else:result={"resolved_intent":mode,"transcript_text":text}
        if intent_decision:
            result["intent"]=public_intent_decision(intent_decision)
            result["intents"]=public_intent_parts(intent_parts)
            if any(part["primary_intent"] in ("change","complete","archive") for part in intent_parts):
                from .mutation_targets import (get_session_mutation_target_resolutions,
                    public_mutation_target_resolutions)
                resolutions=get_session_mutation_target_resolutions(item["ingestion_session_id"])
                result["reference_resolutions"]=public_mutation_target_resolutions(resolutions)
                from .mutation_actions import (get_session_mutation_actions,mutation_action_status,
                    public_mutation_actions,public_mutation_part_outcomes)
                actions=get_session_mutation_actions(item["ingestion_session_id"])
                result["actions"]=public_mutation_actions(actions)
                outcomes=public_mutation_part_outcomes(intent_parts,resolutions,actions)
                result["action_outcomes"]=outcomes
                result["action_status"]=mutation_action_status(outcomes)
            if len(intent_parts)>1:result["interpretation_status"]="split_completed"
            from .knowledge_preflight import get_session_knowledge_preflights,public_knowledge_preflights
            assessments=get_session_knowledge_preflights(item["ingestion_session_id"])
            if assessments:result["knowledge_assessments"]=public_knowledge_preflights(assessments)
            from .knowledge_clarifications import (get_session_knowledge_clarifications,
                public_knowledge_clarifications)
            knowledge_clarifications=get_session_knowledge_clarifications(item["ingestion_session_id"])
            if knowledge_clarifications:
                result["knowledge_clarifications"]=public_knowledge_clarifications(knowledge_clarifications)
    with get_db_connection() as c:c.execute("UPDATE client_sessions SET capture_result=%s,updated_at=%s WHERE client_session_id=%s",(Jsonb(result),datetime.now(TIMEZONE),client_session_id));c.commit()
    return result


def refresh_capture_result_for_ingestion(ingestion_session_id):
    """Re-materialize a completed parent after a clarification resumed its action."""
    with get_db_connection() as c:
        row=c.execute("SELECT client_session_id FROM client_sessions WHERE ingestion_session_id=%s",
                      (ingestion_session_id,)).fetchone()
        if not row:return None
        c.execute("UPDATE client_sessions SET capture_result=NULL,updated_at=%s WHERE client_session_id=%s",
                  (datetime.now(TIMEZONE),row[0]));c.commit()
    return _materialize_capture_result(row[0])


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
