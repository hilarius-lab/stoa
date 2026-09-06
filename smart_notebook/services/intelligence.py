from datetime import datetime
import re

from ..config import TIMEZONE
from ..database import get_db_connection
from .recovery import refresh_session_watermarks


def _key(text):
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def generate_evidence_quotes(session_id):
    now = datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        if connection.execute("SELECT 1 FROM ingestion_sessions WHERE id=%s", (session_id,)).fetchone() is None:
            return None
        sources = connection.execute("""
            SELECT a.id, s.id, c.id, c.text, s.text, c.source_start_ms, c.source_end_ms
            FROM session_artifacts a
            JOIN session_artifact_sources x ON x.artifact_id=a.id
            JOIN semantic_segments s ON s.id=x.segment_id
            JOIN ingestion_chunks c ON c.id=s.chunk_id
            WHERE a.session_id=%s ORDER BY a.id, s.id
        """, (session_id,)).fetchall()
        created = 0
        for artifact_id, segment_id, chunk_id, chunk_text, quote, start_ms, end_ms in sources:
            char_start = chunk_text.find(quote)
            if char_start < 0:
                continue
            char_end = char_start + len(quote)
            cursor_start = cursor_end = None
            if start_ms is not None and end_ms is not None and len(chunk_text):
                duration = end_ms - start_ms
                cursor_start = start_ms + round(duration * char_start / len(chunk_text))
                cursor_end = start_ms + round(duration * char_end / len(chunk_text))
            result = connection.execute("""
                INSERT INTO evidence_quotes(session_id,chunk_id,segment_id,artifact_id,quote_text,
                    char_start,char_end,source_start_ms,source_end_ms,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(artifact_id,chunk_id,char_start,char_end) DO NOTHING RETURNING id
            """, (session_id,chunk_id,segment_id,artifact_id,quote,char_start,char_end,cursor_start,cursor_end,now)).fetchone()
            created += result is not None
        connection.commit()
    return {"session_id": session_id, "created": created, "evidence": list_evidence_quotes(session_id)}


def list_evidence_quotes(session_id):
    with get_db_connection() as connection:
        rows = connection.execute("""SELECT id,session_id,chunk_id,segment_id,artifact_id,quote_text,
            char_start,char_end,source_start_ms,source_end_ms,created_at
            FROM evidence_quotes WHERE session_id=%s ORDER BY chunk_id,char_start,id""", (session_id,)).fetchall()
    return [{"id":r[0],"session_id":r[1],"chunk_id":r[2],"segment_id":r[3],"artifact_id":r[4],
        "quote_text":r[5],"char_start":r[6],"char_end":r[7],"source_start_ms":r[8],
        "source_end_ms":r[9],"created_at":r[10].isoformat()} for r in rows]


def create_question(session_id, text, kind, confidence, priority, topic_id=None, segment_ids=None):
    text = text.strip(); normalized = _key(text); now = datetime.now(TIMEZONE)
    if not normalized: raise ValueError("question_text must not be empty")
    with get_db_connection() as connection:
        if connection.execute("SELECT 1 FROM ingestion_sessions WHERE id=%s",(session_id,)).fetchone() is None:return None
        budget = connection.execute("SELECT max_open_questions,max_questions_per_topic FROM session_question_budgets WHERE session_id=%s",(session_id,)).fetchone() or (12,4)
        existing = connection.execute("SELECT id,status FROM session_questions WHERE session_id=%s AND normalized_key=%s FOR UPDATE",(session_id,normalized)).fetchone()
        if existing:
            connection.execute("UPDATE session_questions SET status='open',question_text=%s,confidence=GREATEST(confidence,%s),priority=GREATEST(priority,%s),updated_at=%s WHERE id=%s",(text,confidence,priority,now,existing[0])); qid=existing[0]
        else:
            open_count=connection.execute("SELECT count(*) FROM session_questions WHERE session_id=%s AND status='open'",(session_id,)).fetchone()[0]
            topic_count=connection.execute("SELECT count(*) FROM session_questions WHERE session_id=%s AND topic_id IS NOT DISTINCT FROM %s AND status='open'",(session_id,topic_id)).fetchone()[0]
            if open_count>=budget[0] or topic_count>=budget[1]: raise ValueError("question budget exhausted")
            qid=connection.execute("""INSERT INTO session_questions(session_id,topic_id,question_text,normalized_key,question_kind,status,confidence,priority,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,'open',%s,%s,%s,%s) RETURNING id""",(session_id,topic_id,text,normalized,kind,confidence,priority,now,now)).fetchone()[0]
        for segment_id in segment_ids or []:
            connection.execute("INSERT INTO session_question_sources(question_id,segment_id,created_at) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(qid,segment_id,now))
        connection.commit()
    return get_question(qid)


def get_question(question_id):
    with get_db_connection() as connection:
        r=connection.execute("""SELECT q.id,q.session_id,q.topic_id,q.question_text,q.question_kind,q.status,q.confidence,q.priority,q.answer_text,q.answer_source,q.created_at,q.updated_at,
            COALESCE(array_agg(s.segment_id ORDER BY s.segment_id) FILTER(WHERE s.segment_id IS NOT NULL),'{}') FROM session_questions q LEFT JOIN session_question_sources s ON s.question_id=q.id WHERE q.id=%s GROUP BY q.id""",(question_id,)).fetchone()
    if not r:return None
    return {"id":r[0],"session_id":r[1],"topic_id":r[2],"question_text":r[3],"question_kind":r[4],"status":r[5],"confidence":r[6],"priority":r[7],"answer_text":r[8],"answer_source":r[9],"created_at":r[10].isoformat(),"updated_at":r[11].isoformat(),"source_segment_ids":r[12]}


def list_questions(session_id):
    with get_db_connection() as connection: ids=connection.execute("SELECT id FROM session_questions WHERE session_id=%s ORDER BY priority DESC,id",(session_id,)).fetchall()
    return [get_question(r[0]) for r in ids]


def detect_questions(session_id):
    with get_db_connection() as connection:
        rows=connection.execute("""SELECT id,text,confidence FROM semantic_segments
            WHERE session_id=%s AND status='confirmed'
              AND (segment_type='question' OR rtrim(text) LIKE '%%?')
            ORDER BY sequence,segment_index""",(session_id,)).fetchall()
    questions=[]
    for segment_id,text,confidence in rows:
        question=create_question(session_id,text,"explicit",confidence,min(1.0,0.5+confidence/2),segment_ids=[segment_id])
        questions.append(question)
    return {"session_id":session_id,"detected":len(rows),"questions":questions}


def answer_question(question_id, answer, source):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row=connection.execute("UPDATE session_questions SET status='answered',answer_text=%s,answer_source=%s,updated_at=%s WHERE id=%s RETURNING id",(answer.strip(),source,now,question_id)).fetchone();connection.commit()
    return get_question(row[0]) if row else None


def reopen_question_record(question_id):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row=connection.execute("UPDATE session_questions SET status='open',answer_text=NULL,answer_source=NULL,updated_at=%s WHERE id=%s RETURNING id",(now,question_id)).fetchone();connection.commit()
    return get_question(row[0]) if row else None


def set_budget(session_id, maximum, per_topic):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        row=connection.execute("""INSERT INTO session_question_budgets(session_id,max_open_questions,max_questions_per_topic,updated_at) VALUES(%s,%s,%s,%s)
            ON CONFLICT(session_id) DO UPDATE SET max_open_questions=EXCLUDED.max_open_questions,max_questions_per_topic=EXCLUDED.max_questions_per_topic,updated_at=EXCLUDED.updated_at RETURNING session_id,max_open_questions,max_questions_per_topic,updated_at""",(session_id,maximum,per_topic,now)).fetchone();connection.commit()
    return {"session_id":row[0],"max_open_questions":row[1],"max_questions_per_topic":row[2],"updated_at":row[3].isoformat()}


def personal_knowledge_fast_path(query):
    terms=[x for x in _key(query).split() if len(x)>=3][:8]
    if not terms:return []
    pattern="%"+"%".join(terms)+"%"
    with get_db_connection() as connection:
        rows=connection.execute("""SELECT kind,id,content FROM (
            SELECT 'note' kind,id,content FROM notes WHERE NOT archived UNION ALL
            SELECT 'task',id,content FROM tasks WHERE NOT archived UNION ALL
            SELECT 'list_item',id,content FROM list_items WHERE NOT archived) k
            WHERE lower(content) LIKE %s LIMIT 10""",(pattern,)).fetchall()
    return [{"knowledge_type":r[0],"knowledge_id":r[1],"content":r[2]} for r in rows]


def finalize_session(session_id, force=False):
    refresh_session_watermarks(session_id)
    with get_db_connection() as connection:
        session=connection.execute("SELECT status FROM ingestion_sessions WHERE id=%s FOR UPDATE",(session_id,)).fetchone()
        if not session:return None
        wm=connection.execute("SELECT received_through_sequence,processed_through_sequence,artifact_through_sequence FROM ingestion_session_watermarks WHERE session_id=%s",(session_id,)).fetchone()
        running=connection.execute("SELECT count(*) FROM processing_jobs WHERE ingestion_session_id=%s AND status IN('queued','running')",(session_id,)).fetchone()[0]
        ready=wm and wm[0]==wm[1]==wm[2] and running==0
        if not ready and not force: raise ValueError("session processing is not complete")
        now=datetime.now(TIMEZONE)
        connection.execute("""UPDATE session_artifacts a SET status='confirmed',updated_at=%s
        FROM artifact_classifications c WHERE a.id=c.artifact_id AND a.session_id=%s AND a.status='active'
        AND c.validated=TRUE AND c.abstained=FALSE""",(now,session_id))
        connection.execute("UPDATE ingestion_sessions SET status='completed',ended_at=COALESCE(ended_at,%s),updated_at=%s WHERE id=%s",(now,now,session_id));connection.commit()
    generate_evidence_quotes(session_id)
    return {"session_id":session_id,"status":"completed","forced":force,"ready_before_finalize":bool(ready),"evidence_count":len(list_evidence_quotes(session_id)),"questions":list_questions(session_id)}
