"""Internal-first reference resolution with validated source attribution."""
from datetime import datetime,timedelta
import hashlib
from uuid import uuid4
from psycopg.types.json import Jsonb
from ..config import (REFERENCE_AMBIGUITY_MARGIN,REFERENCE_RESULT_TTL_HOURS,
    REFERENCE_STRONG_CONFIDENCE,REFERENCE_SUPPORTING_CONFIDENCE,TIMEZONE)
from ..database import get_db_connection
from .retrieval import search_knowledge

def _confidence(item):
    scores=item.get("retrieval",{}).get("scores",{})
    if "exact" in scores:return 1.0
    if "vector" in scores:return max(0.0,min(1.0,float(scores["vector"])))
    if "trigram" in scores:return max(0.0,min(1.0,float(scores["trigram"])))
    return .72 if float(scores.get("fts",0))>0 else 0.0

def _fact_candidates(query,limit):
    with get_db_connection() as c:rows=c.execute("""SELECT id,statement,confidence,
    GREATEST(similarity(lower(statement),lower(%s)),word_similarity(lower(%s),lower(statement)),
    CASE WHEN position(lower(%s) in lower(statement))>0 THEN 1 ELSE 0 END),claim_type,status,updated_at
    FROM claims WHERE status IN('active','disputed') ORDER BY 4 DESC LIMIT %s""",(query,query,query,limit)).fetchall()
    return [{"type":"fact","id":r[0],"title":r[4],"content":r[1],"confidence":float(r[3]),"stage":"trigram",
        "metadata":{"claim_confidence":r[2],"claim_status":r[5],"updated_at":r[6].isoformat()}} for r in rows if r[3]>=.3]

def _assessment(items):
    scores=sorted((x["confidence"] for x in items),reverse=True);top=scores[0] if scores else 0.0
    supporting=sum(x>=REFERENCE_SUPPORTING_CONFIDENCE for x in scores)
    disputed=any(x.get("metadata",{}).get("claim_status")=="disputed" for x in items)
    if len(scores)>1 and top-scores[1]<REFERENCE_AMBIGUITY_MARGIN and disputed:
        return "conflicting",{"top_confidence":top,"supporting_count":supporting,"reason":"ambiguous_disputed_candidates"}
    adequate=top>=REFERENCE_STRONG_CONFIDENCE or supporting>=2
    return ("sufficient" if adequate else "insufficient"),{"top_confidence":top,"supporting_count":supporting,
        "strong_threshold":REFERENCE_STRONG_CONFIDENCE,"supporting_threshold":REFERENCE_SUPPORTING_CONFIDENCE}

async def resolve_internal(query,limit=10):
    query=" ".join(query.split())
    if not query:raise ValueError("query must not be empty")
    limit=max(1,min(20,limit));notes=await search_knowledge(query,limit=limit,types=["note"],min_similarity=.3)
    items=[{"type":"note","id":x["id"],"title":x.get("title"),"content":x["content"],"confidence":_confidence(x),
        "stage":x["retrieval"].get("stage") or "hybrid","metadata":{"key":x["key"]}} for x in notes]
    items.extend(_fact_candidates(query,limit));items.sort(key=lambda x:x["confidence"],reverse=True);items=items[:limit]
    adequacy,assessment=_assessment(items);now=datetime.now(TIMEZONE);expires=now+timedelta(hours=REFERENCE_RESULT_TTL_HOURS);run_id=uuid4();result=[]
    with get_db_connection() as c:
        c.execute("INSERT INTO reference_resolver_runs VALUES(%s,%s,'completed',%s,%s,%s,%s,%s)",(run_id,hashlib.sha256(query.casefold().encode()).hexdigest(),adequacy,None if adequacy=='sufficient' else 'external',Jsonb(assessment),now,expires))
        for item in items:
            source_id=uuid4();c.execute("""INSERT INTO reference_candidates(source_id,run_id,source_type,source_record_id,title,content,confidence,retrieval_stage,metadata,created_at,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(source_id,run_id,item["type"],item["id"],item["title"],item["content"],item["confidence"],item["stage"],Jsonb(item["metadata"]),now,expires))
            result.append({"source_id":str(source_id),"source_type":item["type"],"source_record_id":item["id"],"title":item["title"],"content":item["content"],"confidence":item["confidence"],"retrieval_stage":item["stage"]})
        c.commit()
    return {"run_id":str(run_id),"scope":"internal","adequacy":adequacy,"escalation_target":None if adequacy=='sufficient' else 'external',"assessment":assessment,"expires_at":expires.isoformat(),"candidates":result}

def attach_candidate_to_claim(claim_id,source_id,quote,relation="supports"):
    quote=" ".join(quote.split());now=datetime.now(TIMEZONE)
    if not quote:raise ValueError("quote must not be empty")
    with get_db_connection() as c:
        if not c.execute("SELECT 1 FROM claims WHERE id=%s",(claim_id,)).fetchone():return None
        row=c.execute("SELECT source_type,source_record_id,content,confidence,expires_at FROM reference_candidates WHERE source_id=%s FOR UPDATE",(source_id,)).fetchone()
        if not row:raise ValueError("source_id is unknown")
        if row[4]<=now:raise ValueError("source_id has expired")
        if quote.casefold() not in " ".join(row[2].split()).casefold():raise ValueError("quote is not contained in the referenced candidate")
        evidence=c.execute("""INSERT INTO claim_evidence(claim_id,source_type,source_id,relation,excerpt,extraction_confidence,metadata,created_at,evidence_strength)
        VALUES(%s,'internal_reference',%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(claim_id,source_type,source_id,excerpt,relation)
        DO UPDATE SET extraction_confidence=GREATEST(claim_evidence.extraction_confidence,EXCLUDED.extraction_confidence) RETURNING id""",
        (claim_id,str(source_id),relation,quote,row[3],Jsonb({"source_type":row[0],"source_record_id":row[1]}),now,row[3])).fetchone()[0]
        c.execute("UPDATE reference_candidates SET used_at=COALESCE(used_at,%s) WHERE source_id=%s",(now,source_id));c.commit()
    return {"evidence_id":evidence,"claim_id":claim_id,"source_id":str(source_id),"quote":quote,"relation":relation}

def purge_expired_reference_candidates():
    with get_db_connection() as c:count=c.execute("DELETE FROM reference_resolver_runs WHERE expires_at<=%s",(datetime.now(TIMEZONE),)).rowcount;c.commit()
    return count
