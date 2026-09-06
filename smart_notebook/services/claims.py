"""Deterministic claim storage and conservative conflict detection."""
from datetime import datetime
import hashlib
import json
import re
import httpx

from psycopg.types.json import Jsonb

from ..config import TIMEZONE,EMBEDDING_MODEL
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .embeddings import get_embedding


def normalize_claim_subject(value: str) -> str:
    return re.sub(r"[^\wäöüß]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _task_subject(content):
    match=re.search(r"^(?:der|die|das)?\s*(.+?)\s+(?:muss|müssen|soll|sollen)\b",content,re.I)
    if match:return match.group(1).strip(" ,.;:")
    match=re.search(r"^(.+?)\s+übernimmt\b",content,re.I)
    return (match.group(1) if match else content).strip(" ,.;:")


def _decision_subject(content):
    match=re.search(r"\büber\s+(.+?)\s+(?:entscheiden|wird entschieden)\b",content,re.I)
    return (match.group(1) if match else content).strip(" ,.;:")


def _claim(row):
    if row is None:
        return None
    return {
        "id": row[0], "claim_type": row[1], "statement": row[2], "subject": row[3],
        "normalized_subject": row[4], "predicate": row[5], "object_value": row[6],
        "polarity": row[7], "modality": row[8],
        "valid_from": row[9].isoformat() if row[9] else None,
        "valid_until": row[10].isoformat() if row[10] else None,
        "status": row[11], "confidence": row[12], "source_knowledge_type": row[13],
        "source_knowledge_id": row[14], "derived": row[15], "metadata": row[16],
        "created_at": row[17].isoformat(), "updated_at": row[18].isoformat(),
    }


CLAIM_SELECT = """SELECT id,claim_type,statement,subject,normalized_subject,predicate,object_value,
polarity,modality,valid_from,valid_until,status,confidence,source_knowledge_type,
source_knowledge_id,derived,metadata,created_at,updated_at FROM claims"""


def create_claim_record(data):
    statement = data.statement.strip(); subject = data.subject.strip(); predicate = data.predicate.strip()
    if data.valid_from and data.valid_until and data.valid_until < data.valid_from:
        raise ValueError("valid_until must not be before valid_from")
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row = connection.execute(
            """INSERT INTO claims(claim_type,statement,subject,normalized_subject,predicate,object_value,
            polarity,modality,valid_from,valid_until,status,confidence,source_knowledge_type,
            source_knowledge_id,derived,metadata,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s)
            RETURNING id,claim_type,statement,subject,normalized_subject,predicate,object_value,
            polarity,modality,valid_from,valid_until,status,confidence,source_knowledge_type,
            source_knowledge_id,derived,metadata,created_at,updated_at""",
            (data.claim_type,statement,subject,normalize_claim_subject(subject),predicate.casefold(),
             data.object_value.strip() if data.object_value else None,data.polarity,data.modality,
             data.valid_from,data.valid_until,data.confidence,data.source_knowledge_type,
             data.source_knowledge_id,data.derived,Jsonb(data.metadata),now,now),
        ).fetchone()
        connection.commit()
    return _claim(row)


def get_claim_record(claim_id):
    with get_db_connection() as connection:
        row = connection.execute(CLAIM_SELECT + " WHERE id=%s", (claim_id,)).fetchone()
        if row is None: return None
        evidence = connection.execute("""SELECT id,evidence_quote_id,source_type,source_id,relation,excerpt,
        source_quality,expertise,independence,directness,extraction_confidence,metadata,created_at,
        source_identity_id,recency,evidence_strength
        FROM claim_evidence WHERE claim_id=%s ORDER BY id""",(claim_id,)).fetchall()
        relations = connection.execute("""SELECT source_claim_id,target_claim_id,relation,confidence,reason_codes,created_at
        FROM claim_relations WHERE source_claim_id=%s OR target_claim_id=%s ORDER BY created_at""",(claim_id,claim_id)).fetchall()
    result=_claim(row)
    result["evidence"]=[{"id":r[0],"evidence_quote_id":r[1],"source_type":r[2],"source_id":r[3],
        "relation":r[4],"excerpt":r[5],"source_quality":r[6],"expertise":r[7],"independence":r[8],
        "directness":r[9],"extraction_confidence":r[10],"metadata":r[11],"created_at":r[12].isoformat(),
        "source_identity_id":r[13],"recency":r[14],"evidence_strength":r[15]} for r in evidence]
    result["relations"]=[{"source_claim_id":r[0],"target_claim_id":r[1],"relation":r[2],
        "confidence":r[3],"reason_codes":r[4],"created_at":r[5].isoformat()} for r in relations]
    return result


def list_claim_records(status=None, subject=None, limit=100):
    clauses=[]; params=[]
    if status: clauses.append("status=%s"); params.append(status)
    if subject: clauses.append("normalized_subject=%s"); params.append(normalize_claim_subject(subject))
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with get_db_connection() as connection:
        rows=connection.execute(CLAIM_SELECT+where+" ORDER BY created_at DESC,id DESC LIMIT %s",params).fetchall()
    return [_claim(row) for row in rows]


def materialize_validated_artifact_claims(artifact_id,knowledge_type,knowledge_id):
    """Create only claims whose structured value is already locally validated."""
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row=connection.execute("""SELECT a.artifact_type,a.content,a.confidence,c.normalized_data,c.validated,c.abstained
        FROM session_artifacts a JOIN artifact_classifications c ON c.artifact_id=a.id WHERE a.id=%s""",(artifact_id,)).fetchone()
        if row is None or not row[4] or row[5]:return {"artifact_id":artifact_id,"created":[],"skipped":"not_validated"}
        kind,content,confidence,data=row[0],row[1],row[2],row[3] or {};specs=[]
        if kind=='task' and data.get('due_at'):
            specs.append({"key":"task:due_at","claim_type":"requirement","subject":_task_subject(content),
                "predicate":"has_due_at","object":data['due_at'],"modality":"required"})
        elif kind=='decision' and data.get('decision_status'):
            specs.append({"key":"decision:status","claim_type":"decision","subject":_decision_subject(content),
                "predicate":"decision_status","object":data['decision_status'],
                "modality":"asserted" if data['decision_status']=='decided' else "possible"})
        if not specs:return {"artifact_id":artifact_id,"created":[],"skipped":"no_deterministic_claim_shape"}
        created=[]
        quotes=connection.execute("SELECT id,quote_text FROM evidence_quotes WHERE artifact_id=%s ORDER BY id",(artifact_id,)).fetchall()
        for spec in specs:
            existing=connection.execute("SELECT claim_id FROM artifact_claim_links WHERE artifact_id=%s AND claim_key=%s",(artifact_id,spec['key'])).fetchone()
            if existing:created.append({"claim_id":existing[0],"claim_key":spec['key'],"idempotent":True});continue
            claim_id=connection.execute("""INSERT INTO claims(claim_type,statement,subject,normalized_subject,predicate,
            object_value,polarity,modality,status,confidence,source_knowledge_type,source_knowledge_id,derived,metadata,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,'positive',%s,'active',%s,%s,%s,FALSE,%s,%s,%s) RETURNING id""",
            (spec['claim_type'],content,spec['subject'],normalize_claim_subject(spec['subject']),spec['predicate'],spec['object'],
             spec['modality'],confidence,knowledge_type,knowledge_id,Jsonb({"artifact_id":artifact_id,"materializer":"deterministic_v1"}),now,now)).fetchone()[0]
            connection.execute("INSERT INTO artifact_claim_links(artifact_id,claim_id,claim_key,created_at) VALUES(%s,%s,%s,%s)",(artifact_id,claim_id,spec['key'],now))
            if quotes:
                for quote_id,excerpt in quotes:
                    connection.execute("""INSERT INTO claim_evidence(claim_id,evidence_quote_id,source_type,source_id,relation,excerpt,
                    directness,extraction_confidence,metadata,created_at) VALUES(%s,%s,'meeting_transcript',%s,'supports',%s,1.0,1.0,%s,%s)
                    ON CONFLICT DO NOTHING""",(claim_id,quote_id,str(artifact_id),excerpt,Jsonb({"artifact_id":artifact_id}),now))
            else:
                connection.execute("""INSERT INTO claim_evidence(claim_id,source_type,source_id,relation,excerpt,directness,
                extraction_confidence,metadata,created_at) VALUES(%s,'session_artifact',%s,'supports',%s,1.0,%s,%s,%s)""",
                (claim_id,str(artifact_id),content,confidence,Jsonb({"artifact_id":artifact_id}),now))
            created.append({"claim_id":claim_id,"claim_key":spec['key'],"idempotent":False})
        connection.commit()
    return {"artifact_id":artifact_id,"created":created,"skipped":None}


def add_claim_evidence_record(claim_id, data):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        if connection.execute("SELECT 1 FROM claims WHERE id=%s",(claim_id,)).fetchone() is None:return None
        if data.evidence_quote_id and connection.execute("SELECT 1 FROM evidence_quotes WHERE id=%s",(data.evidence_quote_id,)).fetchone() is None:
            raise ValueError("evidence_quote_id not found")
        if data.source_identity_id and connection.execute("SELECT 1 FROM evidence_sources WHERE id=%s",(data.source_identity_id,)).fetchone() is None:
            raise ValueError("source_identity_id not found")
        row=connection.execute("""INSERT INTO claim_evidence(claim_id,evidence_quote_id,source_type,source_id,
        relation,excerpt,source_quality,expertise,independence,directness,extraction_confidence,metadata,created_at,
        source_identity_id,recency,evidence_strength)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (claim_id,data.evidence_quote_id,data.source_type,data.source_id,data.relation,data.excerpt.strip(),
         data.source_quality,data.expertise,data.independence,data.directness,data.extraction_confidence,
         Jsonb(data.metadata),now,data.source_identity_id,data.recency,data.evidence_strength)).fetchone();connection.commit()
    return {"id":row[0],"claim_id":claim_id}


def create_evidence_source_record(data):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row=connection.execute("""INSERT INTO evidence_sources(source_type,provider,external_id,display_name,privacy_class,metadata,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_type,provider,external_id) DO UPDATE SET
        display_name=COALESCE(EXCLUDED.display_name,evidence_sources.display_name),updated_at=EXCLUDED.updated_at
        RETURNING id,source_type,provider,external_id,display_name,privacy_class,metadata,created_at,updated_at""",
        (data.source_type.strip(),data.provider,data.external_id,data.display_name,data.privacy_class,Jsonb(data.metadata),now,now)).fetchone();connection.commit()
    return {"id":row[0],"source_type":row[1],"provider":row[2],"external_id":row[3],"display_name":row[4],
        "privacy_class":row[5],"metadata":row[6],"created_at":row[7].isoformat(),"updated_at":row[8].isoformat()}


def list_evidence_source_records():
    with get_db_connection() as connection:rows=connection.execute("""SELECT id,source_type,provider,external_id,display_name,
    privacy_class,metadata,created_at,updated_at FROM evidence_sources ORDER BY id""").fetchall()
    return [{"id":r[0],"source_type":r[1],"provider":r[2],"external_id":r[3],"display_name":r[4],
        "privacy_class":r[5],"metadata":r[6],"created_at":r[7].isoformat(),"updated_at":r[8].isoformat()} for r in rows]


def add_claim_relation_record(source_claim_id, data):
    if source_claim_id == data.target_claim_id: raise ValueError("A claim cannot relate to itself")
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        existing=connection.execute("SELECT id FROM claims WHERE id IN(%s,%s)",(source_claim_id,data.target_claim_id)).fetchall()
        if len(existing)!=2:return None
        connection.execute("""INSERT INTO claim_relations(source_claim_id,target_claim_id,relation,confidence,reason_codes,created_at)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(source_claim_id,target_claim_id,relation)
        DO UPDATE SET confidence=EXCLUDED.confidence,reason_codes=EXCLUDED.reason_codes""",
        (source_claim_id,data.target_claim_id,data.relation,data.confidence,Jsonb(data.reason_codes),now));connection.commit()
    return {"source_claim_id":source_claim_id,"target_claim_id":data.target_claim_id,"relation":data.relation,"confidence":data.confidence}


def _overlapping_validity(a,b):
    return not ((a[10] and b[9] and a[10] < b[9]) or (b[10] and a[9] and b[10] < a[9]))


def _conflict_type(a,b):
    same_object=(a[6] or "").casefold() == (b[6] or "").casefold()
    if a[7] != b[7]: return ("negation", "polarity") if same_object else None
    if same_object: return None
    predicate=a[5]
    if any(token in predicate for token in ("due","date","time","deadline")):return "temporal","object_value"
    if any(token in predicate for token in ("status","state","completed","approved")):return "status","object_value"
    return "value","object_value"


def detect_conflicts(claim_ids=None,dry_run=True):
    params=[];where=" WHERE status IN('active','disputed')"
    if claim_ids: where+=" AND id=ANY(%s)";params.append(claim_ids)
    with get_db_connection() as connection: rows=connection.execute(CLAIM_SELECT+where,params).fetchall()
    actions=[]
    for index,a in enumerate(rows):
        for b in rows[index+1:]:
            if a[4]!=b[4] or a[5]!=b[5] or not _overlapping_validity(a,b):continue
            detected=_conflict_type(a,b)
            if not detected:continue
            conflict_type,dimension=detected; low,high=sorted((a[0],b[0]))
            key=hashlib.sha256(f"{low}:{high}:{conflict_type}:{dimension}".encode()).hexdigest()
            actions.append({"conflict_key":key,"conflict_type":conflict_type,"affected_dimension":dimension,
                "claim_ids":[low,high],"summary":f"Conflicting {dimension} for {a[3]} / {a[5]}"})
    applied=_apply_conflict_actions(actions) if not dry_run else 0
    return {"dry_run":dry_run,"candidate_count":len(actions),"applied_count":applied,"actions":actions}


def _apply_conflict_actions(actions):
    applied=0
    if actions:
        now=datetime.now(TIMEZONE)
        with get_db_connection() as connection:
            for action in actions:
                row=connection.execute("""INSERT INTO conflict_cases(conflict_key,conflict_type,affected_dimension,status,summary,created_at,updated_at)
                VALUES(%s,%s,%s,'detected',%s,%s,%s) ON CONFLICT(conflict_key) DO NOTHING RETURNING id""",
                (action["conflict_key"],action["conflict_type"],action["affected_dimension"],action["summary"],now,now)).fetchone()
                if row is None:
                    case_id=connection.execute("SELECT id FROM conflict_cases WHERE conflict_key=%s",(action["conflict_key"],)).fetchone()[0]
                    continue
                case_id=row[0]
                for claim_id in action["claim_ids"]:
                    connection.execute("INSERT INTO conflict_case_claims(conflict_case_id,claim_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(case_id,claim_id))
                low,high=action["claim_ids"]
                connection.execute("""INSERT INTO claim_relations(source_claim_id,target_claim_id,relation,confidence,reason_codes,created_at)
                VALUES(%s,%s,'contradicts',1.0,%s,%s) ON CONFLICT DO NOTHING""",(low,high,Jsonb(action.get("reason_codes",["deterministic_same_subject_predicate"])),now))
                connection.execute("UPDATE claims SET status='disputed',updated_at=%s WHERE id=ANY(%s) AND status='active'",(now,action["claim_ids"]))
                applied+=1
            connection.commit()
    return applied


def list_conflict_cases(status=None,limit=100):
    where=" WHERE status=%s" if status else "";params=[status] if status else [] ;params.append(limit)
    with get_db_connection() as connection:
        rows=connection.execute("""SELECT id,conflict_key,conflict_type,affected_dimension,status,summary,assessment,
        resolution_claim_id,created_at,updated_at FROM conflict_cases"""+where+" ORDER BY updated_at DESC,id DESC LIMIT %s",params).fetchall()
        result=[]
        for r in rows:
            ids=[x[0] for x in connection.execute("SELECT claim_id FROM conflict_case_claims WHERE conflict_case_id=%s ORDER BY claim_id",(r[0],)).fetchall()]
            result.append({"id":r[0],"conflict_key":r[1],"conflict_type":r[2],"affected_dimension":r[3],
                "status":r[4],"summary":r[5],"assessment":r[6],"resolution_claim_id":r[7],
                "claim_ids":ids,"created_at":r[8].isoformat(),"updated_at":r[9].isoformat()})
    return result


async def extract_note_claim_candidates(note_id,mode="llm"):
    now=datetime.now(TIMEZONE);prompt_version="claim_extraction_v1"
    with get_db_connection() as connection:
        note=connection.execute("SELECT content FROM notes WHERE id=%s AND archived=FALSE",(note_id,)).fetchone()
        if note is None:return None
        run_id=connection.execute("""INSERT INTO claim_extraction_runs(note_id,mode,status,prompt_version,created_at)
        VALUES(%s,%s,'running',%s,%s) RETURNING id""",(note_id,mode,prompt_version,now)).fetchone()[0];connection.commit()
    try:
        if mode=="deterministic_test":raw=[]
        else:
            profile=get_ai_task_profile("claims.extract")
            item={"type":"object","properties":{"claim_type":{"type":"string","enum":["fact","opinion","prediction","requirement","decision"]},
                "statement":{"type":"string"},"subject":{"type":"string"},"predicate":{"type":"string"},"object_value":{"type":"string"},
                "polarity":{"type":"string","enum":["positive","negative"]},"modality":{"type":"string","enum":["asserted","required","probable","possible","uncertain"]},
                "evidence_excerpt":{"type":"string"},"confidence":{"type":"number"},"reason_codes":{"type":"array","items":{"type":"string"}}},
                "required":["claim_type","statement","subject","predicate","object_value","polarity","modality","evidence_excerpt","confidence","reason_codes"],"additionalProperties":False}
            schema={"type":"object","properties":{"candidates":{"type":"array","items":item}},"required":["candidates"],"additionalProperties":False}
            prompt="""Zerlege die Note in null, einen oder mehrere atomare Claims. Jeder Claim muss genau eine überprüfbare Aussage enthalten. evidence_excerpt muss eine exakte zusammenhängende Passage der Note sein. Vermische keine unabhängigen Aussagen und erfinde weder Subjekte noch Werte. Wenn nichts belastbar extrahierbar ist, gib eine leere Liste zurück."""
            payload={"model":profile["model"],"messages":[{"role":"system","content":prompt},{"role":"user","content":note[0]}],
                "temperature":profile["temperature"],"response_format":{"type":"json_schema","json_schema":{"name":"claim_candidates","strict":True,"schema":schema}}}
            async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
                response=await client.post(profile["endpoint"],json=payload);response.raise_for_status()
            raw=json.loads(response.json()["choices"][0]["message"]["content"])["candidates"]
        saved=[];rejected=0
        with get_db_connection() as connection:
            for index,candidate in enumerate(raw,1):
                errors=[];excerpt=candidate["evidence_excerpt"].strip()
                if not excerpt or excerpt.casefold() not in note[0].casefold():errors.append("evidence_not_in_note")
                if not all(candidate[key].strip() for key in ("statement","subject","predicate")):errors.append("empty_atomic_field")
                if not 0<=candidate["confidence"]<=1:errors.append("invalid_confidence")
                status="rejected" if errors else "proposed";rejected+=int(bool(errors))
                row=connection.execute("""INSERT INTO claim_extraction_candidates(run_id,note_id,candidate_index,claim_type,
                statement,subject,predicate,object_value,polarity,modality,evidence_excerpt,confidence,reason_codes,status,
                validation_errors,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (run_id,note_id,index,candidate["claim_type"],candidate["statement"].strip(),candidate["subject"].strip(),
                 candidate["predicate"].strip().casefold(),candidate["object_value"].strip() or None,candidate["polarity"],candidate["modality"],
                 excerpt,candidate["confidence"],Jsonb(candidate["reason_codes"]),status,Jsonb(errors),now)).fetchone()
                saved.append({"id":row[0],"status":status,"validation_errors":errors,**candidate})
            summary={"candidate_count":len(saved),"proposed_count":len(saved)-rejected,"rejected_count":rejected,"mutated_claims":0}
            connection.execute("UPDATE claim_extraction_runs SET status='completed',summary=%s,completed_at=%s WHERE id=%s",(Jsonb(summary),datetime.now(TIMEZONE),run_id));connection.commit()
        return {"run_id":run_id,"note_id":note_id,"mode":mode,"summary":summary,"candidates":saved}
    except Exception as exc:
        with get_db_connection() as connection:connection.execute("UPDATE claim_extraction_runs SET status='failed',summary=%s,completed_at=%s WHERE id=%s",(Jsonb({"error":str(exc),"mutated_claims":0}),datetime.now(TIMEZONE),run_id));connection.commit()
        raise


def list_note_claim_candidates(note_id):
    with get_db_connection() as connection:
        if connection.execute("SELECT 1 FROM notes WHERE id=%s",(note_id,)).fetchone() is None:return None
        rows=connection.execute("""SELECT id,run_id,candidate_index,claim_type,statement,subject,predicate,object_value,
        polarity,modality,evidence_excerpt,confidence,reason_codes,status,validation_errors,created_at
        FROM claim_extraction_candidates WHERE note_id=%s ORDER BY created_at DESC,candidate_index""",(note_id,)).fetchall()
    return [{"id":r[0],"run_id":r[1],"candidate_index":r[2],"claim_type":r[3],"statement":r[4],"subject":r[5],
        "predicate":r[6],"object_value":r[7],"polarity":r[8],"modality":r[9],"evidence_excerpt":r[10],
        "confidence":r[11],"reason_codes":r[12],"status":r[13],"validation_errors":r[14],"created_at":r[15].isoformat()} for r in rows]


async def run_changed_conflict_scan(dry_run=True,semantic_threshold=.88):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        changed=connection.execute("""SELECT id,normalized_subject,predicate,statement,embedding FROM claims
        WHERE status IN('active','disputed') AND (conflict_checked_at IS NULL OR conflict_checked_at<updated_at)
        ORDER BY id""").fetchall()
        changed_ids=[r[0] for r in changed]
        candidate_ids=set(changed_ids)
        for _,subject,predicate,_,_ in changed:
            candidate_ids.update(r[0] for r in connection.execute("""SELECT id FROM claims WHERE normalized_subject=%s
            AND predicate=%s AND status IN('active','disputed')""",(subject,predicate)).fetchall())
        run_id=connection.execute("""INSERT INTO conflict_scan_runs(dry_run,status,changed_claim_count,candidate_claim_count,created_at)
        VALUES(%s,'running',%s,%s,%s) RETURNING id""",(dry_run,len(changed_ids),len(candidate_ids),now)).fetchone()[0];connection.commit()
    try:
        for claim_id,_,_,statement,embedding in changed:
            if embedding is None:
                vector=await get_embedding(statement)
                with get_db_connection() as connection:connection.execute("UPDATE claims SET embedding=%s,embedding_model=%s WHERE id=%s",(vector,EMBEDDING_MODEL,claim_id));connection.commit()
        exact=detect_conflicts(sorted(candidate_ids),dry_run);semantic_actions=[];seen=set()
        with get_db_connection() as connection:
            changed_rows=connection.execute(CLAIM_SELECT+" WHERE id=ANY(%s)",(changed_ids,)).fetchall() if changed_ids else []
            for source in changed_rows:
                if connection.execute("SELECT embedding FROM claims WHERE id=%s",(source[0],)).fetchone()[0] is None:continue
                neighbors=connection.execute(CLAIM_SELECT+""" WHERE id<>%s AND predicate=%s AND status IN('active','disputed')
                AND embedding IS NOT NULL AND 1-(embedding<=>(SELECT embedding FROM claims WHERE id=%s))>=%s
                ORDER BY embedding<=>(SELECT embedding FROM claims WHERE id=%s) LIMIT 20""",(source[0],source[5],source[0],semantic_threshold,source[0])).fetchall()
                for target in neighbors:
                    if source[4]==target[4] or not _overlapping_validity(source,target):continue
                    detected=_conflict_type(source,target)
                    if not detected:continue
                    low,high=sorted((source[0],target[0]));kind,dimension=detected;identity=(low,high,kind,dimension)
                    if identity in seen:continue
                    seen.add(identity);similarity=connection.execute("SELECT 1-(a.embedding<=>b.embedding) FROM claims a,claims b WHERE a.id=%s AND b.id=%s",(low,high)).fetchone()[0]
                    key=hashlib.sha256(f"{low}:{high}:{kind}:{dimension}:semantic_v1".encode()).hexdigest()
                    semantic_actions.append({"conflict_key":key,"conflict_type":kind,"affected_dimension":dimension,"claim_ids":[low,high],
                        "summary":f"Semantic-neighbor conflict for {source[3]} / {source[5]}","subject_similarity":float(similarity),"reason_codes":["semantic_subject_neighbor"]})
        # Semantic subject matching remains shadow-only until alpha evaluations
        # establish its precision. Exact deterministic conflicts may still apply.
        semantic_applied=0
        result={"dry_run":dry_run,"candidate_count":exact["candidate_count"]+len(semantic_actions),"applied_count":exact["applied_count"]+semantic_applied,
            "actions":exact["actions"]+semantic_actions,"scan_run_id":run_id,"changed_claim_ids":changed_ids,"candidate_claim_ids":sorted(candidate_ids),
            "comparison_mode":"exact_plus_semantic_subject_v1","semantic_threshold":semantic_threshold,"semantic_shadow":True}
        with get_db_connection() as connection:
            if not dry_run and changed_ids:
                connection.execute("UPDATE claims SET conflict_checked_at=%s WHERE id=ANY(%s)",(datetime.now(TIMEZONE),changed_ids))
            connection.execute("UPDATE conflict_scan_runs SET status='completed',result=%s,completed_at=%s WHERE id=%s",(Jsonb(result),datetime.now(TIMEZONE),run_id));connection.commit()
        return result
    except Exception as exc:
        with get_db_connection() as connection:connection.execute("UPDATE conflict_scan_runs SET status='failed',result=%s,completed_at=%s WHERE id=%s",(Jsonb({"error":str(exc)}),datetime.now(TIMEZONE),run_id));connection.commit()
        raise
