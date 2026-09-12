from datetime import datetime,timedelta
import re
from uuid import uuid4

from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection


class ConversationConflict(Exception):pass


def _sanitize_markdown(value):
    """Constrain server-authored Markdown to the v1 passive rendering subset."""
    text=str(value or "").replace("\x00","")
    # Images/embedded media are never part of the client contract; preserve only alt text.
    text=re.sub(r"!\[([^\]]*)\]\([^)]*\)",r"\1",text)
    # Keep only explicit HTTPS links. All other schemes become inert label text.
    text=re.sub(r"\[([^\]]+)\]\((?!https://)[^)]*\)",r"\1",text,flags=re.IGNORECASE)
    # Raw HTML is displayed as text instead of being interpreted by a renderer.
    return text.replace("<","&lt;").replace(">","&gt;")


def _conversation(r):
    if not r:return None
    return {"id":str(r[0]),"title":r[1],"status":r[2],"revision":r[3],"agent":{"key":r[4],"display_name":"Smart Notebook"},
            "created_at":r[5].isoformat(),"last_activity_at":r[6].isoformat(),"dashboard_until":r[7].isoformat()}


def get_conversation(conversation_id):
    with get_db_connection() as c:r=c.execute("SELECT id,title,status,revision,agent_key,created_at,last_activity_at,dashboard_until FROM client_conversations WHERE id=%s",(conversation_id,)).fetchone()
    return _conversation(r)


def list_conversations(include_stale=False):
    now=datetime.now(TIMEZONE);where="" if include_stale else " WHERE dashboard_until>%s";params=() if include_stale else (now,)
    with get_db_connection() as c:rows=c.execute("SELECT id,title,status,revision,agent_key,created_at,last_activity_at,dashboard_until FROM client_conversations"+where+" ORDER BY last_activity_at DESC",params).fetchall()
    return [_conversation(r) for r in rows]


def list_messages(conversation_id):
    with get_db_connection() as c:
        if c.execute("SELECT 1 FROM client_conversations WHERE id=%s",(conversation_id,)).fetchone() is None:return None
        rows=c.execute("SELECT id,sequence,role,content,content_format,created_at FROM client_conversation_messages WHERE conversation_id=%s ORDER BY sequence",(conversation_id,)).fetchall()
    return [{"id":str(r[0]),"sequence":r[1],"role":r[2],"content":r[3],"content_format":r[4],"created_at":r[5].isoformat()} for r in rows]


def _turn(r):
    if not r:return None
    return {"id":str(r[0]),"conversation_id":str(r[1]),"client_turn_id":str(r[2]),"user_message_id":str(r[3]),
            "assistant_message_id":str(r[4]) if r[4] else None,"status":r[5],"attempts":r[6],"error":r[7],
            "created_at":r[8].isoformat(),"started_at":r[9].isoformat() if r[9] else None,
            "completed_at":r[10].isoformat() if r[10] else None,"updated_at":r[11].isoformat()}


TURN_SELECT="SELECT id,conversation_id,client_turn_id,user_message_id,assistant_message_id,status,attempts,error,created_at,started_at,completed_at,updated_at FROM client_conversation_turns"


def get_turn(turn_id):
    with get_db_connection() as c:r=c.execute(TURN_SELECT+" WHERE id=%s",(turn_id,)).fetchone()
    return _turn(r)


def _add_turn(c,conversation_id,client_message_id,client_turn_id,content,now):
    old=c.execute(TURN_SELECT+" WHERE conversation_id=%s AND client_turn_id=%s",(conversation_id,client_turn_id)).fetchone()
    if old:
        message=c.execute("SELECT content,client_message_id FROM client_conversation_messages WHERE id=%s",(old[3],)).fetchone()
        if message[0]!=content or message[1]!=client_message_id:raise ConversationConflict("client_turn_id already exists with different input")
        return _turn(old)
    sequence=c.execute("SELECT COALESCE(max(sequence),0)+1 FROM client_conversation_messages WHERE conversation_id=%s",(conversation_id,)).fetchone()[0]
    message_id=uuid4();turn_id=uuid4()
    c.execute("INSERT INTO client_conversation_messages(id,conversation_id,client_message_id,sequence,role,content,created_at) VALUES(%s,%s,%s,%s,'user',%s,%s)",(message_id,conversation_id,client_message_id,sequence,content,now))
    c.execute("INSERT INTO client_conversation_turns(id,conversation_id,client_turn_id,user_message_id,status,created_at,updated_at) VALUES(%s,%s,%s,%s,'queued',%s,%s)",(turn_id,conversation_id,client_turn_id,message_id,now,now))
    c.execute("UPDATE client_conversations SET status='processing',revision=revision+1,last_activity_at=%s,dashboard_until=%s,delete_after=%s WHERE id=%s",
              (now,now+timedelta(hours=24),now+timedelta(hours=48),conversation_id))
    return _turn(c.execute(TURN_SELECT+" WHERE id=%s",(turn_id,)).fetchone())


def create_conversation(client_conversation_id,client_message_id,client_turn_id,content):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        old=c.execute("SELECT id FROM client_conversations WHERE client_conversation_id=%s",(client_conversation_id,)).fetchone()
        if old:conversation_id=old[0]
        else:
            conversation_id=uuid4();title=" ".join(content.split())[:120]
            c.execute("""INSERT INTO client_conversations(id,client_conversation_id,title,status,created_at,last_activity_at,dashboard_until,delete_after)
            VALUES(%s,%s,%s,'open',%s,%s,%s,%s)""",(conversation_id,client_conversation_id,title,now,now,now+timedelta(hours=24),now+timedelta(hours=48)))
        turn=_add_turn(c,conversation_id,client_message_id,client_turn_id,content,now);c.commit()
    return {"conversation":get_conversation(conversation_id),"turn":turn}


def add_turn(conversation_id,client_message_id,client_turn_id,content):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        if c.execute("SELECT 1 FROM client_conversations WHERE id=%s",(conversation_id,)).fetchone() is None:return None
        turn=_add_turn(c,conversation_id,client_message_id,client_turn_id,content,now);c.commit()
    return turn


def abort_turn(turn_id):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute(TURN_SELECT+" WHERE id=%s FOR UPDATE",(turn_id,)).fetchone()
        if not row:return None
        if row[5]=="aborted":return _turn(row)
        if row[5] not in ("queued","running"):raise ConversationConflict(f"cannot abort turn in state {row[5]}")
        c.execute("UPDATE client_conversation_turns SET status='aborted',completed_at=%s,updated_at=%s WHERE id=%s",(now,now,turn_id))
        c.execute("INSERT INTO client_conversation_turn_events(turn_id,event_type,payload,created_at) VALUES(%s,'aborted','{}',%s)",(turn_id,now));c.commit()
        c.execute("UPDATE client_conversations SET status='open',revision=revision+1,last_activity_at=%s WHERE id=%s",(now,row[1]));c.commit()
    return get_turn(turn_id)


def retry_turn(turn_id):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute(TURN_SELECT+" WHERE id=%s FOR UPDATE",(turn_id,)).fetchone()
        if not row:return None
        if row[5]=="queued":return _turn(row)
        if row[5] not in ("failed","aborted"):raise ConversationConflict(f"cannot retry turn in state {row[5]}")
        c.execute("UPDATE client_conversation_turns SET status='queued',error=NULL,started_at=NULL,completed_at=NULL,updated_at=%s WHERE id=%s",(now,turn_id));c.commit()
        c.execute("UPDATE client_conversations SET status='processing',revision=revision+1,last_activity_at=%s WHERE id=%s",(now,row[1]));c.commit()
    return get_turn(turn_id)


def queue_failed_chat_turns_for_night_repair(limit=100):
    """Requeue up to `limit` chat turns stuck in 'failed' for one retry each.

    A11/W06: unlike processing_jobs.parked (jobs.py::queue_parked_jobs_for_night_repair)
    and client_sessions.attention_required (client_sessions.py::retry_attention_required_
    client_sessions_for_night_repair), a chat turn that lands in 'failed' only ever
    recovers if the client calls retry_turn() itself -- nothing on the backend
    ever retried it on its own. Mirrors retry_turn()'s own state reset, gated by
    night_repair_attempts (0..1) so a turn that fails again after its one nightly
    repair escalates and stays failed for good instead of being retried forever.
    The actual retry runs later, picked up by worker.py's existing chat queue
    (run_chat_turn_once), the same as any other queued turn.
    """
    now=datetime.now(TIMEZONE);limit=max(1,min(limit,1000))
    with get_db_connection() as c:
        rows=c.execute("""WITH candidates AS(SELECT id FROM client_conversation_turns WHERE status='failed'
        AND night_repair_attempts=0 ORDER BY completed_at,id FOR UPDATE SKIP LOCKED LIMIT %s)
        UPDATE client_conversation_turns t SET status='queued',night_repair_attempts=1,error=NULL,
        started_at=NULL,completed_at=NULL,updated_at=%s FROM candidates ca WHERE t.id=ca.id
        RETURNING t.id,t.conversation_id""",(limit,now)).fetchall()
        conversation_ids=list({r[1] for r in rows})
        if conversation_ids:
            c.execute("""UPDATE client_conversations SET status='processing',revision=revision+1,last_activity_at=%s
            WHERE id=ANY(%s)""",(now,conversation_ids))
        c.commit()
    return [get_turn(r[0]) for r in rows]


def turn_events(turn_id,after=0):
    with get_db_connection() as c:
        if c.execute("SELECT 1 FROM client_conversation_turns WHERE id=%s",(turn_id,)).fetchone() is None:return None
        rows=c.execute("SELECT sequence,event_type,payload,created_at FROM client_conversation_turn_events WHERE turn_id=%s AND sequence>%s ORDER BY sequence",(turn_id,after)).fetchall()
    return [{"sequence":r[0],"type":r[1],"payload":r[2],"created_at":r[3].isoformat()} for r in rows]


async def run_chat_turn_once(mode="llm",deterministic_text="Deterministische Testantwort."):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute(TURN_SELECT+" WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row:return {"outcome":"idle","turn":None}
        turn=_turn(row);c.execute("UPDATE client_conversation_turns SET status='running',attempts=attempts+1,started_at=%s,updated_at=%s WHERE id=%s",(now,now,row[0]))
        c.execute("INSERT INTO client_conversation_turn_events(turn_id,event_type,payload,created_at) VALUES(%s,'started','{}',%s)",(row[0],now));c.commit()
    try:
        with get_db_connection() as c:user,user_sequence=c.execute("SELECT content,sequence FROM client_conversation_messages WHERE id=%s",(turn["user_message_id"],)).fetchone()
        if mode=="deterministic":answer=deterministic_text;citations=[]
        else:
            from .events import create_event_record
            from .chat import ask_llm
            event=create_event_record(user,source="client_chat")
            answer,debug=await ask_llm(user,event["id"],conversation_id=turn["conversation_id"],before_sequence=user_sequence)
            citations=[{"type":x.get("type"),"id":x.get("id")} for x in debug.get("retrieved_knowledge",[]) if isinstance(x,dict)]
        answer=_sanitize_markdown(answer)
        completed=datetime.now(TIMEZONE);assistant_id=uuid4()
        with get_db_connection() as c:
            current=c.execute("SELECT status FROM client_conversation_turns WHERE id=%s FOR UPDATE",(turn["id"],)).fetchone()[0]
            if current=="aborted":
                c.commit()
                return {"outcome":"aborted","turn":_turn(c.execute(TURN_SELECT+" WHERE id=%s",(turn["id"],)).fetchone())}
            sequence=c.execute("SELECT COALESCE(max(sequence),0)+1 FROM client_conversation_messages WHERE conversation_id=%s",(turn["conversation_id"],)).fetchone()[0]
            c.execute("INSERT INTO client_conversation_messages(id,conversation_id,sequence,role,content,content_format,created_at) VALUES(%s,%s,%s,'assistant',%s,'markdown',%s)",(assistant_id,turn["conversation_id"],sequence,answer,completed))
            c.execute("INSERT INTO client_conversation_turn_events(turn_id,event_type,payload,created_at) VALUES(%s,'delta',%s,%s)",(turn["id"],Jsonb({"text":answer}),completed))
            for citation in citations:c.execute("INSERT INTO client_conversation_turn_events(turn_id,event_type,payload,created_at) VALUES(%s,'citation',%s,%s)",(turn["id"],Jsonb(citation),completed))
            c.execute("INSERT INTO client_conversation_turn_events(turn_id,event_type,payload,created_at) VALUES(%s,'completed',%s,%s)",(turn["id"],Jsonb({"assistant_message_id":str(assistant_id)}),completed))
            c.execute("UPDATE client_conversation_turns SET status='completed',assistant_message_id=%s,completed_at=%s,updated_at=%s WHERE id=%s",(assistant_id,completed,completed,turn["id"]))
            c.execute("UPDATE client_conversations SET status='open',revision=revision+1,last_activity_at=%s,dashboard_until=%s,delete_after=%s WHERE id=%s",(completed,completed+timedelta(hours=24),completed+timedelta(hours=48),turn["conversation_id"]));c.commit()
        return {"outcome":"completed","turn":get_turn(turn["id"])}
    except Exception as exc:
        failed=datetime.now(TIMEZONE)
        with get_db_connection() as c:
            c.execute("UPDATE client_conversation_turns SET status='failed',error=%s,completed_at=%s,updated_at=%s WHERE id=%s",(str(exc),failed,failed,turn["id"]))
            c.execute("INSERT INTO client_conversation_turn_events(turn_id,event_type,payload,created_at) VALUES(%s,'failed',%s,%s)",(turn["id"],Jsonb({"error_type":type(exc).__name__}),failed));c.commit()
            c.execute("UPDATE client_conversations SET status='failed',revision=revision+1,last_activity_at=%s WHERE id=%s",(failed,turn["conversation_id"]));c.commit()
        return {"outcome":"failed","turn":get_turn(turn["id"])}


def purge_expired_conversations():
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        rows=c.execute("""DELETE FROM client_conversations x WHERE delete_after<=%s AND NOT EXISTS(
        SELECT 1 FROM client_conversation_messages m WHERE m.conversation_id=x.id AND m.retained_as_knowledge=TRUE) RETURNING id""",(now,)).fetchall();c.commit()
    return len(rows)
