from datetime import datetime
import hashlib
from uuid import UUID,uuid5

from psycopg.types.json import Jsonb

from ..config import EMBEDDING_DIMENSIONS,TIMEZONE
from ..database import get_db_connection
from .client_chat import create_conversation
from .events import create_event_record,mark_event_capture_processed


class CaptureConflict(Exception):pass


def _intent(mode,text):
    if mode!="auto":return mode
    lowered=text.casefold().lstrip();words=("wer ","was ","wann ","wo ","warum ","wieso ","wie ","welche ","kann ","können ","ist ","sind ")
    return "query" if text.rstrip().endswith("?") or lowered.startswith(words) else "memo"


def _item(r):
    if not r:return None
    return {"id":str(r[0]),"mode":r[1],"resolved_intent":r[2],"content":r[3],"context_ref":r[4],"event_id":r[5],
            "conversation_id":str(r[6]) if r[6] else None,"turn_id":str(r[7]) if r[7] else None,"status":r[8],"result":r[9],"error":r[10],
            "created_at":r[11].isoformat(),"updated_at":r[12].isoformat()}


SELECT="SELECT id,mode,resolved_intent,content,context_ref,event_id,conversation_id,turn_id,status,result,error,created_at,updated_at FROM client_text_captures"


def get_capture(capture_id):
    with get_db_connection() as c:r=c.execute(SELECT+" WHERE id=%s",(capture_id,)).fetchone()
    return _item(r)


def create_capture(capture_id,mode,content,context_ref=None):
    content=content.strip();digest=hashlib.sha256((mode+"\0"+content+"\0"+str(context_ref or {})).encode()).hexdigest();now=datetime.now(TIMEZONE)
    old=get_capture(capture_id)
    if old:
        with get_db_connection() as c:stored=c.execute("SELECT content_hash FROM client_text_captures WHERE id=%s",(capture_id,)).fetchone()[0]
        if stored!=digest:raise CaptureConflict("client_capture_id already exists with different capture data")
        return old
    resolved=_intent(mode,content)
    if resolved=="query":
        namespace=UUID(str(capture_id));chat=create_conversation(uuid5(namespace,"conversation"),uuid5(namespace,"message:1"),uuid5(namespace,"turn:1"),content)
        event_id=None;conversation_id=chat["conversation"]["id"];turn_id=chat["turn"]["id"]
        status="completed";result={"conversation_id":conversation_id,"turn_id":turn_id}
    else:
        event=create_event_record(content,source="client_memo",client_event_id=str(capture_id));event_id=event["id"]
        conversation_id=turn_id=None;status="queued";result=None
    with get_db_connection() as c:
        c.execute("""INSERT INTO client_text_captures(id,mode,resolved_intent,content,content_hash,context_ref,event_id,conversation_id,turn_id,status,result,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(capture_id,mode,resolved,content,digest,Jsonb(context_ref) if context_ref else None,event_id,conversation_id,turn_id,status,Jsonb(result) if result else None,now,now));c.commit()
    return get_capture(capture_id)


async def run_capture_once(mode="production"):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute(SELECT+" WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row:return {"outcome":"idle","capture":None}
        item=_item(row);c.execute("UPDATE client_text_captures SET status='processing',updated_at=%s WHERE id=%s",(now,item["id"]));c.commit()
    try:
        if mode=="deterministic":
            from .notes import save_note
            note_id=save_note(item["content"],[0.0]*EMBEDDING_DIMENSIONS,source_event_id=item["event_id"]);result={"resolved_intent":"memo","knowledge_ref":{"type":"note","internal_id":note_id}}
        else:
            from .capture import process_capture_action
            result=await process_capture_action(item["content"],item["event_id"],datetime.fromisoformat(item["created_at"]))
        mark_event_capture_processed(item["event_id"],result);completed=datetime.now(TIMEZONE)
        with get_db_connection() as c:c.execute("UPDATE client_text_captures SET status='completed',result=%s,error=NULL,updated_at=%s WHERE id=%s",(Jsonb(result),completed,item["id"]));c.commit()
        return {"outcome":"completed","capture":get_capture(item["id"])}
    except Exception as exc:
        failed=datetime.now(TIMEZONE)
        with get_db_connection() as c:c.execute("UPDATE client_text_captures SET status='failed',error=%s,updated_at=%s WHERE id=%s",(str(exc),failed,item["id"]));c.commit()
        return {"outcome":"failed","capture":get_capture(item["id"])}
