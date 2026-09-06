import hashlib,json,re
from datetime import datetime,timedelta
from uuid import UUID,uuid4

from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from .activity import calculate_signals,record_activity

PERSONAL_LIBRARY=UUID("00000000-0000-4000-8000-000000000001")
CURSOR_TTL_DAYS=30


class SyncCursorExpired(Exception):pass
class SyncCursorInvalid(Exception):pass
class UsageBatchConflict(Exception):pass


def _keywords(text):return list(dict.fromkeys(re.findall(r"[\wäöüß]{3,}",text.casefold())))[:100]
def _title(text):
    compact=" ".join(text.split());return (re.split(r"(?<=[.!?])\s+",compact)[0] or compact)[:120]
def _level(score):return "high" if score>=.8 else "medium" if score>=.5 else "low"


def list_libraries():
    with get_db_connection() as c:rows=c.execute("SELECT id,library_key,library_type,title,description,version,privacy_class,offline_enabled,sync_mode,scope,updated_at FROM knowledge_libraries ORDER BY library_key").fetchall()
    result=[]
    with get_db_connection() as c:
        for r in rows:
            stats=c.execute("""SELECT count(*) FILTER(WHERE state='active'),COALESCE((SELECT max(sequence) FROM client_knowledge_changes WHERE library_id=%s),0),
            COALESCE((SELECT sum(pg_column_size(payload)) FROM client_knowledge_changes WHERE library_id=%s),0) FROM client_knowledge_entities WHERE library_id=%s""",(r[0],r[0],r[0])).fetchone()
            result.append({"id":str(r[0]),"key":r[1],"type":r[2],"title":r[3],"description":r[4],"version":r[5],"privacy_class":r[6],
                "offline_enabled":r[7],"sync_mode":r[8],"scope":r[9],"local_action":"retain" if r[7] and r[8]!="off" else "delete_library",
                "stats":{"entity_count":stats[0],"latest_change_sequence":stats[1],"change_log_bytes":stats[2]},"updated_at":r[10].isoformat()})
    return result


def _topics(c,kind,object_id):
    rows=c.execute("""SELECT e.public_id,t.title,l.relation,l.link_origin,l.confidence FROM knowledge_topic_links l
    JOIN knowledge_topics t ON t.id=l.topic_id LEFT JOIN client_knowledge_entities e ON e.entity_type='topic' AND e.internal_id=t.id
    WHERE l.knowledge_type=%s AND l.knowledge_id=%s ORDER BY l.confidence DESC,t.title""",(kind,object_id)).fetchall()
    return [{"id":str(r[0]) if r[0] else None,"title":r[1],"relation":r[2],"origin":r[3],"confidence":r[4]} for r in rows]


def _note_payload(c,row,public_id,revision):
    note_id,content,created,updated,archived=row
    sources=c.execute("SELECT e.id,e.text,e.source FROM knowledge_sources s JOIN events e ON e.id=s.event_id WHERE s.knowledge_type='note' AND s.knowledge_id=%s ORDER BY e.created_at DESC LIMIT 5",(note_id,)).fetchall()
    score=min(1,.35+.15*len(sources));sup=c.execute("SELECT canonical_id FROM knowledge_supersessions WHERE knowledge_type='note' AND original_id=%s",(note_id,)).fetchone()
    return {"id":str(public_id),"revision":revision,"type":"note","library_id":str(PERSONAL_LIBRARY),"title":_title(content),"content":content,
            "status":"superseded" if sup else ("archived" if archived else "active"),"created_at":created.isoformat(),"updated_at":updated.isoformat(),
            "search":{"normalized_text":" ".join(content.casefold().split()),"keywords":_keywords(content)},"topics":_topics(c,"note",note_id),
            "evidence":{"score":score,"level":_level(score),"conflict_status":"none","independent_sources":len(sources),
                        "quotes":[{"text":r[1][:240],"source_type":r[2],"source_id":str(r[0])} for r in sources]}}


def _fact_payload(c,row,public_id,revision):
    fact_id,statement,status,confidence,created,updated=row
    evidence=c.execute("""SELECT e.source_type,e.source_id,e.relation,e.excerpt,e.extraction_confidence,q.session_id,q.source_start_ms,q.source_end_ms
    FROM claim_evidence e LEFT JOIN evidence_quotes q ON q.id=e.evidence_quote_id WHERE e.claim_id=%s ORDER BY e.extraction_confidence DESC LIMIT 5""",(fact_id,)).fetchall()
    independent=len({(r[0],r[1]) for r in evidence if r[1]})
    conflicts=c.execute("SELECT count(*) FROM conflict_case_claims cc JOIN conflict_cases x ON x.id=cc.conflict_case_id WHERE cc.claim_id=%s AND x.status IN('detected','investigating','unresolved')",(fact_id,)).fetchone()[0]
    return {"id":str(public_id),"revision":revision,"type":"fact","library_id":str(PERSONAL_LIBRARY),"title":_title(statement),"content":statement,
            "status":status,"created_at":created.isoformat(),"updated_at":updated.isoformat(),
            "search":{"normalized_text":" ".join(statement.casefold().split()),"keywords":_keywords(statement)},"topics":_topics(c,"fact",fact_id),
            "evidence":{"score":confidence,"level":_level(confidence),"conflict_status":"disputed" if status=="disputed" or conflicts else "none",
                        "independent_sources":independent,"quotes":[{"text":r[3][:240],"source_type":r[0],"source_id":r[1],"relation":r[2],"confidence":r[4],
                        "session_id":r[5],"source_start_ms":r[6],"source_end_ms":r[7]} for r in evidence]}}


def _topic_payload(c,row,public_id,revision):
    topic_id,title,description,created,updated=row
    parents=c.execute("""SELECT e.public_id,t.title,r.relation FROM knowledge_topic_relations r JOIN knowledge_topics t ON t.id=r.parent_topic_id
    LEFT JOIN client_knowledge_entities e ON e.entity_type='topic' AND e.internal_id=t.id WHERE r.child_topic_id=%s""",(topic_id,)).fetchall()
    children=c.execute("""SELECT e.public_id,t.title,r.relation FROM knowledge_topic_relations r JOIN knowledge_topics t ON t.id=r.child_topic_id
    LEFT JOIN client_knowledge_entities e ON e.entity_type='topic' AND e.internal_id=t.id WHERE r.parent_topic_id=%s""",(topic_id,)).fetchall()
    return {"id":str(public_id),"revision":revision,"type":"topic","library_id":str(PERSONAL_LIBRARY),"title":title,"content":description,
            "status":"active","created_at":created.isoformat(),"updated_at":updated.isoformat(),"search":{"normalized_text":title.casefold(),"keywords":_keywords(title+" "+description)},
            "relations":{"parents":[{"id":str(r[0]) if r[0] else None,"title":r[1],"relation":r[2]} for r in parents],
                         "children":[{"id":str(r[0]) if r[0] else None,"title":r[1],"relation":r[2]} for r in children]}}


def refresh_sync_index():
    now=datetime.now(TIMEZONE);changed=0
    with get_db_connection() as c:
        specs=[("note",c.execute("SELECT id,content,created_at,updated_at,archived FROM notes ORDER BY id").fetchall(),_note_payload),
               ("fact",c.execute("SELECT id,statement,status,confidence,created_at,updated_at FROM claims WHERE claim_type='fact' ORDER BY id").fetchall(),_fact_payload),
               ("topic",c.execute("SELECT id,title,description,created_at,updated_at FROM knowledge_topics ORDER BY id").fetchall(),_topic_payload)]
        # Allocate all identities before rendering topic relations.
        for kind,rows,_ in specs:
            for row in rows:c.execute("""INSERT INTO client_knowledge_entities(public_id,entity_type,internal_id,library_id,revision,state,fingerprint,created_at,updated_at)
                VALUES(%s,%s,%s,%s,1,'active','',%s,%s) ON CONFLICT(entity_type,internal_id) DO NOTHING""",(uuid4(),kind,row[0],PERSONAL_LIBRARY,now,now))
        for kind,rows,builder in specs:
            for row in rows:
                entity=c.execute("SELECT public_id,revision,fingerprint,state FROM client_knowledge_entities WHERE entity_type=%s AND internal_id=%s",(kind,row[0])).fetchone()
                superseded=((kind=="note" and c.execute("SELECT 1 FROM knowledge_supersessions WHERE knowledge_type='note' AND original_id=%s UNION ALL SELECT 1 FROM note_fact_promotions WHERE note_id=%s LIMIT 1",(row[0],row[0])).fetchone() is not None)
                            or (kind=="topic" and c.execute("SELECT 1 FROM knowledge_topic_redirects WHERE source_topic_id=%s",(row[0],)).fetchone() is not None))
                state=("superseded" if superseded else "archived" if kind=="note" and row[4] else "deleted" if kind=="fact" and row[2] in ("superseded","retracted") else "active")
                provisional=builder(c,row,entity[0],entity[1]);fingerprint=hashlib.sha256(json.dumps({k:v for k,v in provisional.items() if k!="revision"},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if fingerprint==entity[2] and state==entity[3]:continue
                if state=="superseded":
                    c.execute("UPDATE client_knowledge_entities SET state='superseded',fingerprint=%s,updated_at=%s WHERE public_id=%s",(fingerprint,now,entity[0]))
                    continue
                revision=entity[1] if not entity[2] else entity[1]+1;payload=builder(c,row,entity[0],revision)
                operation="delete" if state in ("archived","deleted") else "upsert"
                if operation=="delete":payload={"id":str(entity[0]),"revision":revision,"type":kind,"reason":state}
                c.execute("UPDATE client_knowledge_entities SET revision=%s,state=%s,fingerprint=%s,updated_at=%s WHERE public_id=%s",(revision,state,fingerprint,now,entity[0]))
                c.execute("INSERT INTO client_knowledge_changes(library_id,public_id,operation,entity_type,revision,payload,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                          (PERSONAL_LIBRARY,entity[0],operation,kind,revision,Jsonb(payload),now));changed+=1
        # Exact consolidation redirects preserve old UUID deep links.
        redirects=c.execute("""SELECT old.public_id,new.public_id,old.revision FROM knowledge_supersessions s
        JOIN client_knowledge_entities old ON old.entity_type=s.knowledge_type AND old.internal_id=s.original_id
        JOIN client_knowledge_entities new ON new.entity_type=s.knowledge_type AND new.internal_id=s.canonical_id
        WHERE s.knowledge_type='note'""").fetchall()
        for old_id,new_id,revision in redirects:
            exists=c.execute("SELECT 1 FROM client_knowledge_changes WHERE public_id=%s AND operation='redirect' AND payload->>'target_id'=%s",(old_id,str(new_id))).fetchone()
            if not exists:
                revision+=1;payload={"id":str(old_id),"revision":revision,"type":"note","target_id":str(new_id),"reason":"superseded"}
                c.execute("UPDATE client_knowledge_entities SET revision=%s,state='superseded',updated_at=%s WHERE public_id=%s",(revision,now,old_id))
                c.execute("INSERT INTO client_knowledge_changes(library_id,public_id,operation,entity_type,revision,payload,created_at) VALUES(%s,%s,'redirect','note',%s,%s,%s)",(PERSONAL_LIBRARY,old_id,revision,Jsonb(payload),now));changed+=1
        promotions=c.execute("""SELECT old.public_id,new.public_id,old.revision FROM note_fact_promotions p
        JOIN client_knowledge_entities old ON old.entity_type='note' AND old.internal_id=p.note_id
        JOIN client_knowledge_entities new ON new.entity_type='fact' AND new.internal_id=p.claim_id""").fetchall()
        for old_id,new_id,revision in promotions:
            exists=c.execute("SELECT 1 FROM client_knowledge_changes WHERE public_id=%s AND operation='redirect' AND payload->>'target_id'=%s",(old_id,str(new_id))).fetchone()
            if not exists:
                revision+=1;payload={"id":str(old_id),"revision":revision,"type":"note","target_id":str(new_id),"target_type":"fact","reason":"evidence_promoted"}
                c.execute("UPDATE client_knowledge_entities SET revision=%s,state='superseded',updated_at=%s WHERE public_id=%s",(revision,now,old_id))
                c.execute("INSERT INTO client_knowledge_changes(library_id,public_id,operation,entity_type,revision,payload,created_at) VALUES(%s,%s,'redirect','note',%s,%s,%s)",(PERSONAL_LIBRARY,old_id,revision,Jsonb(payload),now));changed+=1
        topic_redirects=c.execute("""SELECT old.public_id,new.public_id,old.revision FROM knowledge_topic_redirects r
        JOIN client_knowledge_entities old ON old.entity_type='topic' AND old.internal_id=r.source_topic_id
        JOIN client_knowledge_entities new ON new.entity_type='topic' AND new.internal_id=r.target_topic_id""").fetchall()
        for old_id,new_id,revision in topic_redirects:
            exists=c.execute("SELECT 1 FROM client_knowledge_changes WHERE public_id=%s AND operation='redirect' AND payload->>'target_id'=%s",(old_id,str(new_id))).fetchone()
            if not exists:
                revision+=1;payload={"id":str(old_id),"revision":revision,"type":"topic","target_id":str(new_id),"target_type":"topic","reason":"topic_merged"}
                c.execute("UPDATE client_knowledge_entities SET revision=%s,state='superseded',updated_at=%s WHERE public_id=%s",(revision,now,old_id))
                c.execute("INSERT INTO client_knowledge_changes(library_id,public_id,operation,entity_type,revision,payload,created_at) VALUES(%s,%s,'redirect','topic',%s,%s,%s)",(PERSONAL_LIBRARY,old_id,revision,Jsonb(payload),now));changed+=1
        c.commit()
    return changed


def _cursor(c,kind,libraries,after,snapshot=None,position=None):
    token=uuid4();now=datetime.now(TIMEZONE)
    c.execute("INSERT INTO client_knowledge_cursors(token,cursor_kind,library_ids,after_sequence,snapshot_sequence,position_public_id,expires_at,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
              (token,kind,libraries,after,snapshot,position,now+timedelta(days=CURSOR_TTL_DAYS),now));return str(token)


def _load_cursor(c,token,expected):
    try:value=UUID(str(token))
    except (ValueError,TypeError):raise SyncCursorInvalid("invalid opaque cursor")
    row=c.execute("SELECT cursor_kind,library_ids,after_sequence,snapshot_sequence,position_public_id,expires_at FROM client_knowledge_cursors WHERE token=%s",(value,)).fetchone()
    if not row or row[0]!=expected:raise SyncCursorInvalid("cursor is unknown or has the wrong kind")
    if row[5]<datetime.now(TIMEZONE):raise SyncCursorExpired("cursor expired; a full resync is required")
    return row


def initial_page(cursor=None,limit=200):
    refresh_sync_index();limit=max(1,min(limit,500))
    with get_db_connection() as c:
        if cursor:row=_load_cursor(c,cursor,"snapshot");libraries,snapshot,position=row[1],row[3],row[4]
        else:
            libraries=[r[0] for r in c.execute("SELECT id FROM knowledge_libraries WHERE offline_enabled=TRUE AND sync_mode<>'off'").fetchall()]
            snapshot=c.execute("SELECT COALESCE(max(sequence),0) FROM client_knowledge_changes").fetchone()[0];position=None
        rows=c.execute("""WITH latest AS (SELECT DISTINCT ON(public_id) public_id,operation,payload FROM client_knowledge_changes
        WHERE library_id=ANY(%s) AND sequence<=%s ORDER BY public_id,sequence DESC)
        SELECT public_id,operation,payload FROM latest WHERE public_id>%s ORDER BY public_id LIMIT %s""",(libraries,snapshot,position or UUID(int=0),limit+1)).fetchall()
        page=rows[:limit];has_more=len(rows)>limit;next_cursor=_cursor(c,"snapshot",libraries,0,snapshot,page[-1][0]) if has_more and page else None
        complete_cursor=None if has_more else _cursor(c,"delta",libraries,snapshot);c.commit()
    return {"mode":"snapshot","items":[{"operation":r[1],"entity":r[2]} for r in page],"next_cursor":next_cursor,
            "complete_cursor":complete_cursor,"has_more":has_more,"snapshot_sequence":snapshot}


def delta_page(cursor,limit=200):
    refresh_sync_index();limit=max(1,min(limit,500))
    with get_db_connection() as c:
        row=_load_cursor(c,cursor,"delta");libraries,after=row[1],row[2]
        rows=c.execute("SELECT sequence,operation,payload FROM client_knowledge_changes WHERE library_id=ANY(%s) AND sequence>%s ORDER BY sequence LIMIT %s",(libraries,after,limit+1)).fetchall()
        page=rows[:limit];last=page[-1][0] if page else after;next_cursor=_cursor(c,"delta",libraries,last);c.commit()
    return {"mode":"delta","changes":[{"sequence":r[0],"operation":r[1],"entity":r[2]} for r in page],"next_cursor":next_cursor,"has_more":len(rows)>limit}


def get_synced_entity(public_id):
    refresh_sync_index()
    with get_db_connection() as c:
        row=c.execute("SELECT operation,payload FROM client_knowledge_changes WHERE public_id=%s ORDER BY sequence DESC LIMIT 1",(public_id,)).fetchone()
    return {"operation":row[0],"entity":row[1]} if row else None


def record_usage_batch(batch_id,client_installation_id,items):
    canonical=json.dumps(items,sort_keys=True,separators=(",",":"),default=str);digest=hashlib.sha256(canonical.encode()).hexdigest();now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        old=c.execute("SELECT payload_hash,accepted_count FROM client_knowledge_usage_batches WHERE batch_id=%s",(batch_id,)).fetchone()
        if old:
            if old[0]!=digest:raise UsageBatchConflict("batch_id already exists with different usage data")
            return {"batch_id":str(batch_id),"accepted_count":old[1],"idempotent":True}
        resolved=[]
        for item in items:
            entity=c.execute("SELECT entity_type,internal_id FROM client_knowledge_entities WHERE public_id=%s AND state='active'",(item["entity_id"],)).fetchone()
            if entity and entity[0] in ("note","fact"):resolved.append((entity[0],entity[1],item))
        c.execute("INSERT INTO client_knowledge_usage_batches(batch_id,client_installation_id,payload_hash,accepted_count,created_at) VALUES(%s,%s,%s,%s,%s)",(batch_id,client_installation_id,digest,len(resolved),now));c.commit()
    for kind,internal_id,item in resolved:
        # One aggregated activity row preserves the client count without inflating Evidence.
        record_activity(kind,internal_id,"opened",metadata={"source":"offline_client","view_count_delta":item["view_count_delta"],"last_viewed_at":str(item["last_viewed_at"])})
        calculate_signals(kind,internal_id)
    return {"batch_id":str(batch_id),"accepted_count":len(resolved),"idempotent":False}
