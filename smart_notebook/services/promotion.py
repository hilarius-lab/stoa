from datetime import datetime
import json,re
import httpx

from ..config import EMBEDDING_DIMENSIONS,TIMEZONE
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .embeddings import get_embedding
from .lists import (add_list_item_record,create_list_record,
                    get_or_create_active_list_record,process_list_item_candidate)
from .notes import save_note
from .tasks import save_task
from .claims import materialize_validated_artifact_claims
from .topics import normalize_topic_key
from .knowledge_preflight import ensure_artifact_knowledge_preflight,identical_knowledge_target
from .knowledge_clarifications import ensure_artifact_knowledge_clarification

async def _task_fields(content,mode,started_at=None):
    if mode=='deterministic':
        urgency=0.9 if re.search(r'\b(dringend|sofort|unverzüglich|urgent)\b',content,re.I) else None
        return {"can_promote":urgency is not None,"content":content,"work_start_at":"","due_at":"","urgency":urgency or 0}
    profile=get_ai_task_profile('artifacts.task_promotion')
    schema={"type":"object","properties":{"can_promote":{"type":"boolean"},"content":{"type":"string"},"work_start_at":{"type":"string"},"due_at":{"type":"string"},"urgency":{"type":"number"}},"required":["can_promote","content","work_start_at","due_at","urgency"],"additionalProperties":False}
    # Without today's date a relative reference like "heute"/"morgen" cannot
    # become an ISO due_at at all -- the model silently fell back to urgency
    # instead, and the task never carried a due date the dashboard could use.
    # Anchored to session start, matching how the rule router in
    # semantic_router.py already resolves weekday references (BACKEND_LOGIK.md
    # 7.3), not wall-clock "now" at promotion time.
    reference=(started_at or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    prompt=f"""Heutiges Datum/Sessionstart: {reference.isoformat()}. Prüfe ein bestätigtes Task-Artifact. Extrahiere einen ausdrücklich genannten Bearbeitungsbeginn (zum Beispiel 'ab morgen') als work_start_at und eine ausdrücklich genannte Frist (zum Beispiel 'bis Freitag') als due_at, jeweils ISO-8601 oder leer und relativ zu diesem Datum. Verwechsle work_start_at nicht mit due_at. Wenn keine Frist existiert, bewerte urgency von 0 bis 1 nur wenn Dringlichkeit aus Wortlaut/Kontext begründbar ist. can_promote ist nur wahr, wenn due_at gesetzt oder urgency begründet ist. Erfinde nichts."""
    payload={"model":profile['model'],"messages":[{"role":"system","content":prompt},{"role":"user","content":content}],"temperature":profile['temperature'],"response_format":{"type":"json_schema","json_schema":{"name":"task_promotion","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile['timeout_seconds'], trust_env=False) as client:r=await client.post(profile['endpoint'],json=payload)
    r.raise_for_status();return json.loads(r.json()['choices'][0]['message']['content'])

def _linked(artifact_id):
    with get_db_connection() as c:
        return c.execute("""SELECT COALESCE(l.knowledge_type,a.promoted_knowledge_type),
            COALESCE(l.knowledge_id,a.promoted_knowledge_id)
            FROM session_artifacts a
            LEFT JOIN artifact_knowledge_links l ON l.artifact_id=a.id
            WHERE a.id=%s AND (l.artifact_id IS NOT NULL OR
                (a.promoted_knowledge_type IS NOT NULL AND a.promoted_knowledge_id IS NOT NULL))""",
            (artifact_id,)).fetchone()

def _record(artifact_id,kind,knowledge_id):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        # The original schema intentionally permits only one canonical
        # artifact_knowledge_link per knowledge object.  A later exact
        # duplicate still records its durable reuse on session_artifacts; the
        # conflict-free insert preserves the canonical link instead of turning
        # successful deduplication into a promotion error.
        c.execute("INSERT INTO artifact_knowledge_links(artifact_id,knowledge_type,knowledge_id,created_at) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",(artifact_id,kind,knowledge_id,now));c.execute("UPDATE session_artifacts SET promoted_knowledge_type=%s,promoted_knowledge_id=%s,promoted_at=%s,promotion_error=NULL WHERE id=%s",(kind,knowledge_id,now,artifact_id));c.commit()

def _transfer_all_topics(artifact_id,knowledge_type,knowledge_id):
    now=datetime.now(TIMEZONE);linked=[]
    with get_db_connection() as c:
        rows=c.execute("""SELECT t.title,t.description,x.relation,x.confidence,t.embedding,t.embedding_model FROM session_artifact_topics x
        JOIN session_topics t ON t.id=x.topic_id WHERE x.artifact_id=%s""",(artifact_id,)).fetchall()
        for title,description,relation,confidence,embedding,embedding_model in rows:
            topic_id=c.execute("""INSERT INTO knowledge_topics(title,normalized_key,description,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(normalized_key) DO UPDATE SET updated_at=knowledge_topics.updated_at RETURNING id""",
            (title,normalize_topic_key(title),description,now,now)).fetchone()[0]
            if embedding is not None:c.execute("UPDATE knowledge_topics SET embedding=%s,embedding_model=%s WHERE id=%s AND embedding IS NULL",
                (embedding,embedding_model,topic_id))
            c.execute("""INSERT INTO knowledge_topic_links(knowledge_type,knowledge_id,topic_id,relation,link_origin,confidence,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(knowledge_type,knowledge_id,topic_id,relation)
            DO UPDATE SET confidence=EXCLUDED.confidence,link_origin=EXCLUDED.link_origin""",
            (knowledge_type,knowledge_id,topic_id,relation,'inherited' if relation=='inherited_topic' else 'direct',confidence,now));linked.append(topic_id)
        c.commit()
    return linked

def claim_promotion_error_artifacts_for_night_repair(limit=100):
    now=datetime.now(TIMEZONE);limit=max(1,min(limit,1000))
    with get_db_connection() as c:
        rows=c.execute("""WITH candidates AS(SELECT id FROM session_artifacts WHERE status='confirmed'
        AND promotion_error IS NOT NULL AND promoted_at IS NULL AND night_repair_attempts=0
        ORDER BY updated_at,id FOR UPDATE SKIP LOCKED LIMIT %s)
        UPDATE session_artifacts a SET night_repair_attempts=1,updated_at=%s FROM candidates ca
        WHERE a.id=ca.id RETURNING a.id,a.session_id""",(limit,now)).fetchall();c.commit()
    return rows


async def retry_promotion_errors_for_night_repair(limit=100,mode='llm'):
    """Retry up to `limit` session_artifacts stuck with a promotion_error, once each.

    A11/W06: promote_session_artifacts() catches per-artifact exceptions internally
    (see the except-block below) so one failing artifact never fails the session's
    overall knowledge finalization -- the client_session this artifact belongs to
    already reached 'completed' and client_sessions.py's own night repair never
    sees it. Nothing else ever calls promote_session_artifacts() again for that
    artifact on its own. Mirrors the existing night-repair shape: one attempt per
    artifact, ever, gated by night_repair_attempts, grouped back into a single
    promote_session_artifacts() call per session_id (it already accepts a
    restricted artifact_ids list for exactly this kind of partial retry).
    """
    claimed=claim_promotion_error_artifacts_for_night_repair(limit)
    by_session={}
    for artifact_id,session_id in claimed:by_session.setdefault(session_id,[]).append(artifact_id)
    results=[]
    for session_id,artifact_ids in by_session.items():
        outcome=await promote_session_artifacts(session_id,mode,artifact_ids=artifact_ids)
        results.append({"session_id":session_id,"artifact_ids":artifact_ids,
                         "promoted":outcome["promoted"],"deferred":outcome["deferred"]})
    return results


async def promote_session_artifacts(session_id,mode='llm',artifact_ids=None):
    with get_db_connection() as c:
        session_row=c.execute("SELECT started_at FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone()
        if session_row is None:return {"session_id":session_id,"outcome":"not_found","promoted":[],"deferred":[]}
        started_at=session_row[0]
        if artifact_ids==[]:return {"session_id":session_id,"outcome":"completed","promoted":[],"deferred":[]}
        id_filter=" AND a.id=ANY(%s)" if artifact_ids is not None else ""
        params=(session_id,artifact_ids) if artifact_ids is not None else (session_id,)
        rows=c.execute("""SELECT a.id,a.artifact_type,a.content,a.confidence,
        (SELECT t.title FROM session_artifact_topics x JOIN session_topics t ON t.id=x.topic_id WHERE x.artifact_id=a.id ORDER BY x.relation='primary_topic' DESC LIMIT 1),
        c.normalized_data,c.validated,c.reason_codes
        FROM session_artifacts a LEFT JOIN artifact_classifications c ON c.artifact_id=a.id
        WHERE a.session_id=%s AND a.status='confirmed'"""+id_filter+" ORDER BY a.id",params).fetchall()
    promoted=[];deferred=[]
    list_cache={}
    for artifact_id,kind,content,confidence,topic_title,normalized_data,classification_validated,reason_codes in rows:
        old=_linked(artifact_id)
        if old:
            claim_result=materialize_validated_artifact_claims(artifact_id,old[0],old[1])
            topic_ids=_transfer_all_topics(artifact_id,old[0],old[1])
            promoted.append({"artifact_id":artifact_id,"knowledge_type":old[0],"knowledge_id":old[1],"idempotent":True,"claims":claim_result,"topic_ids":topic_ids})
            continue
        try:
            assessment=await ensure_artifact_knowledge_preflight(artifact_id,mode)
            clarification=ensure_artifact_knowledge_clarification(assessment)
            if clarification and clarification["status"] in {"pending","needs_clarification"}:
                deferred.append({"artifact_id":artifact_id,"reason":"knowledge_clarification_required"})
                continue
            target='note' if kind in {'note','fact','decision'} else kind
            identical_id=identical_knowledge_target(assessment,target)
            if identical_id is not None:
                _record(artifact_id,target,identical_id)
                claim_result=materialize_validated_artifact_claims(artifact_id,target,identical_id)
                topic_ids=_transfer_all_topics(artifact_id,target,identical_id)
                promoted.append({"artifact_id":artifact_id,"knowledge_type":target,"knowledge_id":identical_id,
                    "idempotent":False,"reused_existing":True,"knowledge_classification":"identical",
                    "claims":claim_result,"topic_ids":topic_ids})
                continue
            if kind in {'note','fact','decision'}:
                embedding=[0.0]*EMBEDDING_DIMENSIONS if mode=='deterministic' else await get_embedding(content)
                knowledge_id=save_note(content,embedding);target='note'
            elif kind=='task':
                data=normalized_data or {}
                fields=({"can_promote":True,"content":data.get('content') or content,"work_start_at":data.get('work_start_at',''),"due_at":data.get('due_at',''),"urgency":data.get('urgency') or 0}
                        if classification_validated and (data.get('due_at') or data.get('urgency') is not None) else await _task_fields(content,mode,started_at))
                if not fields['can_promote'] or (not fields['due_at'] and fields['urgency']<=0):deferred.append({"artifact_id":artifact_id,"reason":"task_requires_due_or_urgency"});continue
                due=None
                if fields['due_at']:
                    due=datetime.fromisoformat(fields['due_at'].replace('Z','+00:00'));due=due.replace(tzinfo=TIMEZONE) if due.tzinfo is None else due
                work_start=None
                if fields.get('work_start_at'):
                    work_start=datetime.fromisoformat(fields['work_start_at'].replace('Z','+00:00'));work_start=work_start.replace(tzinfo=TIMEZONE) if work_start.tzinfo is None else work_start
                embedding=[0.0]*EMBEDDING_DIMENSIONS if mode=='deterministic' else await get_embedding(fields['content'] or content)
                # Due date and urgency are independent CalDAV-facing task
                # dimensions; an explicit urgency must survive even with a due.
                urgency_value=fields['urgency'] if fields['urgency']>0 else None
                knowledge_id=save_task(fields['content'] or content,due,embedding,urgency=urgency_value,
                    urgency_source=(data.get('urgency_source') if urgency_value is not None else None),
                    work_start_at=work_start,work_start_reference=started_at);target='task'
            elif kind=='list':
                if confidence<0.85:deferred.append({"artifact_id":artifact_id,"reason":"list_confidence_below_0.85"});continue
                embedding=[0.0]*EMBEDDING_DIMENSIONS if mode=='deterministic' else None
                knowledge_id,_=await get_or_create_active_list_record(content,embedding_vector=embedding);target='list'
            elif kind=='list_item':
                if confidence<0.85 or not topic_title:deferred.append({"artifact_id":artifact_id,"reason":"list_target_not_confident"});continue
                if mode=='deterministic':
                    embedding=[0.0]*EMBEDDING_DIMENSIONS
                    key=topic_title.casefold()
                    if key not in list_cache:
                        with get_db_connection() as c:
                            existing=c.execute("SELECT id FROM lists WHERE lower(title)=lower(%s) AND archived=FALSE ORDER BY id LIMIT 1",(topic_title,)).fetchone()
                        list_cache[key]=existing[0] if existing else await create_list_record(topic_title,embedding_vector=embedding)
                    knowledge_id=await add_list_item_record(list_cache[key],content,embedding_vector=embedding,refresh_embedding=False)
                else:
                    # 'list_item_candidate' is the LLM proposal path's own reason
                    # code (artifacts.py::_router_overrides now defers every
                    # list_candidate/list_item_candidate segment segmentation
                    # already identified to the LLM instead of guessing rules
                    # against isolated text -- see that function's comment).
                    # Without it here, every LLM-classified list item fell back
                    # to explicit_target=False and resolve_list_target()'s
                    # semantic-similarity search over ALL lists, using the
                    # item's own content rather than its already-linked
                    # topic_title. Real case, session 1388 on 2026-09-12:
                    # "Kette für nach dem M2" was correctly linked to the topic
                    # "Geplante Ausgaben", but its own wording matched an
                    # unrelated, older "nach dem M2" list closely enough to be
                    # filed there instead. topic_title here already reflects
                    # segmentation's and the LLM's agreement on the target list;
                    # trust it the same way an explicit rule match would be.
                    explicit_target=bool(classification_validated and set(reason_codes or []) & {
                        'explicit_list_target','implicit_list_context','list_item_candidate'
                    })
                    result=await process_list_item_candidate(topic_title,content,explicit_target=explicit_target)
                    knowledge_id=result.get('item_id') or result.get('updated_item_id') or result.get('existing_item_id')
                    if not knowledge_id:deferred.append({"artifact_id":artifact_id,"reason":result.get('reason','list_item_rejected')});continue
                target='list_item'
            else:deferred.append({"artifact_id":artifact_id,"reason":"unsupported_artifact_type"});continue
            _record(artifact_id,target,knowledge_id)
            claim_result=materialize_validated_artifact_claims(artifact_id,target,knowledge_id)
            topic_ids=_transfer_all_topics(artifact_id,target,knowledge_id)
            promoted.append({"artifact_id":artifact_id,"knowledge_type":target,"knowledge_id":knowledge_id,"idempotent":False,"claims":claim_result,"topic_ids":topic_ids})
        except Exception as exc:
            with get_db_connection() as c:c.execute("UPDATE session_artifacts SET promotion_error=%s WHERE id=%s",(str(exc),artifact_id));c.commit()
            deferred.append({"artifact_id":artifact_id,"reason":str(exc)})
    return {"session_id":session_id,"outcome":"completed","promoted":promoted,"deferred":deferred}
