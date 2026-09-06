# Session topic service
from datetime import datetime
import re
from ..config import TIMEZONE
from ..database import get_db_connection

class SessionTopicConflictError(Exception):
    pass

def normalize_topic_key(title):
    title = " ".join(title.strip().casefold().split())
    return re.sub(r"[^\wäöüß]+", "-", title, flags=re.UNICODE).strip("-")

def _topic(row):
    if row is None: return None
    return {"id":row[0],"session_id":row[1],"title":row[2],"normalized_key":row[3],"description":row[4],"status":row[5],"confidence":row[6],"created_at":row[7].isoformat(),"updated_at":row[8].isoformat()}

TOPIC_SELECT="SELECT id,session_id,title,normalized_key,description,status,confidence,created_at,updated_at FROM session_topics"

def create_session_topic_record(session_id,title,description="",confidence=1.0):
    title=title.strip(); description=description.strip()
    if not title: raise ValueError("title must not be empty")
    key=normalize_topic_key(title); now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        if c.execute("SELECT id FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None: return None
        row=c.execute("""INSERT INTO session_topics(session_id,title,normalized_key,description,status,confidence,created_at,updated_at)
        VALUES(%s,%s,%s,%s,'active',%s,%s,%s) ON CONFLICT(session_id,normalized_key) DO UPDATE SET updated_at=session_topics.updated_at
        RETURNING id,session_id,title,normalized_key,description,status,confidence,created_at,updated_at""",(session_id,title,key,description,confidence,now,now)).fetchone(); c.commit()
    return _topic(row)

def list_session_topic_records(session_id,include_inactive=False):
    with get_db_connection() as c:
        if c.execute("SELECT id FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None:return None
        where="" if include_inactive else " AND status='active'"
        rows=c.execute(TOPIC_SELECT+" WHERE session_id=%s"+where+" ORDER BY created_at,id",(session_id,)).fetchall()
    return [_topic(r) for r in rows]

def get_session_topic_record(topic_id):
    with get_db_connection() as c: row=c.execute(TOPIC_SELECT+" WHERE id=%s",(topic_id,)).fetchone()
    return _topic(row)

def update_session_topic_record(topic_id,title=None,description=None,confidence=None):
    now=datetime.now(TIMEZONE); title=title.strip() if title is not None else None
    if title=="": raise ValueError("title must not be empty")
    with get_db_connection() as c:
        current=c.execute("SELECT status FROM session_topics WHERE id=%s FOR UPDATE",(topic_id,)).fetchone()
        if current is None:return None
        if current[0]!='active':raise SessionTopicConflictError("Inactive topic cannot be updated")
        c.execute("""UPDATE session_topics SET title=COALESCE(%s,title), normalized_key=COALESCE(%s,normalized_key),
        description=COALESCE(%s,description),confidence=COALESCE(%s,confidence),updated_at=%s WHERE id=%s""",
        (title,normalize_topic_key(title) if title else None,description,confidence,now,topic_id));c.commit()
    return get_session_topic_record(topic_id)

def link_artifact_topic_record(artifact_id,topic_id,relation,confidence):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        pair=c.execute("""SELECT artifacts.session_id,topics.session_id FROM session_artifacts artifacts
        JOIN session_topics topics ON topics.id=%s WHERE artifacts.id=%s""",(topic_id,artifact_id)).fetchone()
        if pair is None:return None
        if pair[0]!=pair[1]:raise SessionTopicConflictError("Artifact and topic belong to different sessions")
        c.execute("""INSERT INTO session_artifact_topics(artifact_id,topic_id,relation,confidence,created_at)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(artifact_id,topic_id,relation) DO UPDATE SET confidence=EXCLUDED.confidence""",
        (artifact_id,topic_id,relation,confidence,now));c.commit()
    return {"artifact_id":artifact_id,"topic_id":topic_id,"relation":relation,"confidence":confidence}

def add_knowledge_topic_relation(parent_id,child_id,relation,confidence):
    if parent_id==child_id:raise ValueError("Topic cannot be its own parent")
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        if len(c.execute("SELECT id FROM knowledge_topics WHERE id IN(%s,%s)",(parent_id,child_id)).fetchall())!=2:return None
        cycle=c.execute("""WITH RECURSIVE descendants(id) AS(SELECT child_topic_id FROM knowledge_topic_relations WHERE parent_topic_id=%s
        UNION SELECT r.child_topic_id FROM knowledge_topic_relations r JOIN descendants d ON r.parent_topic_id=d.id)
        SELECT 1 FROM descendants WHERE id=%s""",(child_id,parent_id)).fetchone()
        if cycle:raise ValueError("Topic relation would create a cycle")
        c.execute("""INSERT INTO knowledge_topic_relations(parent_topic_id,child_topic_id,relation,confidence,created_at)
        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(parent_topic_id,child_topic_id,relation) DO UPDATE SET confidence=EXCLUDED.confidence""",
        (parent_id,child_id,relation,confidence,now));c.commit()
    return {"parent_topic_id":parent_id,"child_topic_id":child_id,"relation":relation,"confidence":confidence}

def get_knowledge_topic_links(knowledge_type,knowledge_id):
    with get_db_connection() as c:
        direct=c.execute("""SELECT t.id,t.title,l.relation,l.confidence FROM knowledge_topic_links l JOIN knowledge_topics t ON t.id=l.topic_id
        WHERE l.knowledge_type=%s AND l.knowledge_id=%s AND l.link_origin='direct' ORDER BY t.title""",(knowledge_type,knowledge_id)).fetchall()
        stored_inherited=c.execute("""SELECT t.id,t.title,l.relation,l.confidence FROM knowledge_topic_links l JOIN knowledge_topics t ON t.id=l.topic_id
        WHERE l.knowledge_type=%s AND l.knowledge_id=%s AND l.link_origin='inherited' ORDER BY t.title""",(knowledge_type,knowledge_id)).fetchall()
        inherited=c.execute("""WITH RECURSIVE ancestors(id,depth) AS(
        SELECT r.parent_topic_id,1 FROM knowledge_topic_links l JOIN knowledge_topic_relations r ON r.child_topic_id=l.topic_id
        WHERE l.knowledge_type=%s AND l.knowledge_id=%s UNION SELECT r.parent_topic_id,a.depth+1 FROM knowledge_topic_relations r JOIN ancestors a ON r.child_topic_id=a.id)
        SELECT DISTINCT t.id,t.title,min(a.depth) FROM ancestors a JOIN knowledge_topics t ON t.id=a.id GROUP BY t.id,t.title ORDER BY min(a.depth),t.title""",
        (knowledge_type,knowledge_id)).fetchall()
    return {"direct":[{"topic_id":r[0],"title":r[1],"relation":r[2],"confidence":r[3],"origin":"direct"} for r in direct],
        "inherited":[{"topic_id":r[0],"title":r[1],"relation":r[2],"confidence":r[3],"origin":"inherited_context"} for r in stored_inherited]
        +[{"topic_id":r[0],"title":r[1],"depth":r[2],"origin":"inherited_hierarchy"} for r in inherited]}
