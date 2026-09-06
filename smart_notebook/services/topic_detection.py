"""Incremental, evidence-backed topic recognition for confirmed meeting sentences."""
from datetime import datetime
import re

from ..config import EMBEDDING_MODEL,TOPIC_LINK_MIN_CONFIDENCE,TOPIC_NEW_MIN_CONFIDENCE,TIMEZONE
from ..database import get_db_connection
from .embeddings import embedding_to_pgvector,get_embedding
from .topics import create_session_topic_record

EXPLICIT_PATTERNS=(
    r"\b(?:geht\s+es\s+um|sprechen\s+wir\s+über|thema\s+ist)\s+(?:das\s+|den\s+|die\s+)?((?:projekt|objekt|thema)\s+[\wÄÖÜäöüß-]+)",
    r"\b(?:zum|für\s+das)\s+((?:projekt|objekt)\s+[\wÄÖÜäöüß-]+)",
)

def explicit_topic_title(text):
    for pattern in EXPLICIT_PATTERNS:
        if match:=re.search(pattern,text,re.I):return " ".join(match.group(1).split()).title()
    return None

async def _ensure_embedding(table,topic_id,title):
    try:vector=embedding_to_pgvector(await get_embedding(title))
    except Exception:return None
    with get_db_connection() as c:
        c.execute(f"UPDATE {table} SET embedding=%s::vector,embedding_model=%s WHERE id=%s AND embedding IS NULL",
            (vector,EMBEDDING_MODEL,topic_id));c.commit()
    return vector

async def detect_topics_for_segments(session_id,segments):
    results=[]
    for segment in segments:
        if segment.get('status')!='confirmed':continue
        segment_id=segment['id'];text=segment['text'];title=explicit_topic_title(text)
        if title:
            confidence=max(TOPIC_NEW_MIN_CONFIDENCE,0.98)
            topic=create_session_topic_record(session_id,title,"Explizit genannter Meeting-Kontext.",confidence)
            await _ensure_embedding('session_topics',topic['id'],title);mode='explicit'
        else:
            with get_db_connection() as c:
                has_topics=c.execute("""SELECT 1 FROM session_topics WHERE session_id=%s AND status='active' AND embedding IS NOT NULL
                UNION ALL SELECT 1 FROM knowledge_topics WHERE embedding IS NOT NULL LIMIT 1""",(session_id,)).fetchone()
            vector=None
            if has_topics:
                try:vector=embedding_to_pgvector(await get_embedding(text))
                except Exception:vector=None
            if vector is None:
                row=durable=None
            else:
                with get_db_connection() as c:
                    row=c.execute("""SELECT id,title,1-(embedding<=>%s::vector) score FROM session_topics
                    WHERE session_id=%s AND status='active' AND embedding IS NOT NULL ORDER BY embedding<=>%s::vector LIMIT 1""",
                    (vector,session_id,vector)).fetchone()
                    durable=c.execute("""SELECT id,title,1-(embedding<=>%s::vector) score FROM knowledge_topics
                    WHERE embedding IS NOT NULL ORDER BY embedding<=>%s::vector LIMIT 1""",(vector,vector)).fetchone()
            candidates=[(source,r) for source,r in (("session",row),("durable",durable)) if r]
            source,best=max(candidates,key=lambda item:float(item[1][2])) if candidates else (None,None)
            if best and float(best[2])>=TOPIC_LINK_MIN_CONFIDENCE and source=="durable":
                created=create_session_topic_record(session_id,best[1],"Aus Durable Knowledge erkannter Kontext.",float(best[2]))
                await _ensure_embedding('session_topics',created['id'],best[1]);topic=created
                confidence=float(best[2]);mode='embedding'
            elif best and float(best[2])>=TOPIC_LINK_MIN_CONFIDENCE:
                topic={"id":best[0],"title":best[1]};confidence=float(best[2]);mode='embedding'
            else:
                with get_db_connection() as c:inherited=c.execute("""SELECT id,title,confidence FROM session_topics
                    WHERE session_id=%s AND status='active' ORDER BY created_at DESC,id DESC LIMIT 1""",(session_id,)).fetchone()
                if not inherited:continue
                topic={"id":inherited[0],"title":inherited[1]};confidence=float(inherited[2])*0.9;mode='context_inherited'
                if confidence<TOPIC_LINK_MIN_CONFIDENCE:continue
        now=datetime.now(TIMEZONE)
        with get_db_connection() as c:
            c.execute("""INSERT INTO session_topic_evidence(session_id,topic_id,segment_id,match_mode,confidence,created_at)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(topic_id,segment_id) DO UPDATE SET match_mode=EXCLUDED.match_mode,
            confidence=EXCLUDED.confidence""",(session_id,topic['id'],segment_id,mode,confidence,now))
            c.execute("UPDATE session_topics SET confidence=GREATEST(confidence,%s),updated_at=%s WHERE id=%s",(confidence,now,topic['id']));c.commit()
        results.append({"segment_id":segment_id,"topic_id":topic['id'],"title":topic['title'],"match_mode":mode,"confidence":confidence})
    return results
