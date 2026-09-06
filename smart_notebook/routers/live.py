import asyncio,hashlib,json
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import StreamingResponse
from ..database import get_db_connection
from ..config import TOPIC_LIVE_MIN_CONFIDENCE
from ..services.retrieval import get_knowledge_record
from ..services.topics import get_knowledge_topic_links

router=APIRouter()

def _snapshot(session_id):
    with get_db_connection() as c:
        if c.execute("SELECT 1 FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None:return None
        transcripts=[{"id":r[0],"text":r[1],"status":r[2],"source_start_ms":r[3]} for r in c.execute("""SELECT id,text,status,source_start_ms FROM transcript_segments
        WHERE session_id=%s AND status IN('confirmed','provisional') ORDER BY source_start_ms,id""",(session_id,)).fetchall()]
        artifacts=[{"id":r[0],"type":r[1],"content":r[2],"status":r[3],"confidence":r[4]} for r in c.execute("""SELECT id,artifact_type,content,status,confidence
        FROM session_artifacts WHERE session_id=%s AND status IN('active','confirmed') ORDER BY id""",(session_id,)).fetchall()]
        topics=[{"id":r[0],"title":r[1],"confidence":r[2]} for r in c.execute("SELECT id,title,confidence FROM session_topics WHERE session_id=%s AND status='active' ORDER BY id",(session_id,)).fetchall()]
        questions=[{"id":r[0],"text":r[1],"status":r[2]} for r in c.execute("SELECT id,question_text,status FROM session_questions WHERE session_id=%s AND status='open' ORDER BY id",(session_id,)).fetchall()]
        relevant_rows=c.execute("""SELECT DISTINCT l.knowledge_type,l.knowledge_id,t.title,l.confidence
        FROM session_topics st JOIN knowledge_topics t ON t.normalized_key=st.normalized_key
        JOIN knowledge_topic_links l ON l.topic_id=t.id WHERE st.session_id=%s AND st.status='active'
        AND st.confidence>=%s AND l.confidence>=%s ORDER BY l.confidence DESC LIMIT 20""",
        (session_id,TOPIC_LIVE_MIN_CONFIDENCE,TOPIC_LIVE_MIN_CONFIDENCE)).fetchall()
    knowledge=[]
    for kind,object_id,topic_title,confidence in relevant_rows:
        record=get_knowledge_record(f"{kind}:{object_id}")
        if record:knowledge.append({"record":record,"topic":topic_title,"confidence":confidence,
            "topics":get_knowledge_topic_links(kind,object_id)})
    return {"session_id":session_id,"transcripts":transcripts,"artifacts":artifacts,"topics":topics,"questions":questions,"relevant_knowledge":knowledge}

@router.get("/api/ingestion-sessions/{session_id}/live-feed")
async def live_feed(session_id:int,request:Request):
    if _snapshot(session_id) is None:raise HTTPException(404,"Ingestion session not found")
    async def events():
        previous=None
        while not await request.is_disconnected():
            snapshot=_snapshot(session_id);payload=json.dumps(snapshot,ensure_ascii=False,separators=(',',':'));digest=hashlib.sha256(payload.encode()).hexdigest()
            if digest!=previous:
                previous=digest;yield f"event: state\ndata: {payload}\n\n"
            else:yield ": keepalive\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
