from datetime import datetime, timedelta
import math

from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection

ALLOWED_TYPES={"note":"notes","fact":"claims","task":"tasks","list":"lists","list_item":"list_items","session_artifact":"session_artifacts","topic":"session_topics"}
ACCESS_TYPES={"displayed","opened","cited"}
ACTIVATION_TYPES={"retrieved","activated"}


def subject_exists(connection, knowledge_type, knowledge_id):
    table=ALLOWED_TYPES.get(knowledge_type)
    if table is None: raise ValueError("unsupported knowledge_type")
    return connection.execute(f"SELECT 1 FROM {table} WHERE id=%s",(knowledge_id,)).fetchone() is not None


def record_activity(knowledge_type,knowledge_id,activity_type,session_id=None,metadata=None,created_at=None):
    now=created_at or datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        if not subject_exists(connection,knowledge_type,knowledge_id): return None
        row=connection.execute("""INSERT INTO knowledge_activity(knowledge_type,knowledge_id,activity_type,session_id,metadata,created_at)
            VALUES(%s,%s,%s,%s,%s,%s) RETURNING id,knowledge_type,knowledge_id,activity_type,session_id,metadata,created_at""",
            (knowledge_type,knowledge_id,activity_type,session_id,Jsonb(metadata or {}),now)).fetchone();connection.commit()
    return _activity(row)


def _activity(row):
    return {"id":row[0],"knowledge_type":row[1],"knowledge_id":row[2],"activity_type":row[3],"session_id":row[4],"metadata":row[5],"created_at":row[6].isoformat()}


def list_activity(knowledge_type=None,knowledge_id=None,activity_type=None,limit=100):
    clauses=[];params=[]
    if knowledge_type: clauses.append("knowledge_type=%s");params.append(knowledge_type)
    if knowledge_id: clauses.append("knowledge_id=%s");params.append(knowledge_id)
    if activity_type: clauses.append("activity_type=%s");params.append(activity_type)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    params.append(max(1,min(limit,1000)))
    with get_db_connection() as connection: rows=connection.execute("SELECT id,knowledge_type,knowledge_id,activity_type,session_id,metadata,created_at FROM knowledge_activity"+where+" ORDER BY created_at DESC,id DESC LIMIT %s",params).fetchall()
    return [_activity(r) for r in rows]


def _evidence_counts(connection,kind,object_id):
    if kind=="session_artifact":
        return connection.execute("""SELECT count(*),count(DISTINCT session_id)
            FROM evidence_quotes WHERE artifact_id=%s""",(object_id,)).fetchone()
    if kind in {"note","task","list","list_item"}:
        return connection.execute("SELECT count(*),0 FROM knowledge_sources WHERE knowledge_type=%s AND knowledge_id=%s",(kind,object_id)).fetchone()
    return (0,0)


def calculate_signals(kind,object_id):
    now=datetime.now(TIMEZONE);recent=now-timedelta(days=7);previous=now-timedelta(days=14)
    with get_db_connection() as connection:
        if not subject_exists(connection,kind,object_id):return None
        rows=connection.execute("""SELECT activity_type,count(*),max(created_at),
            count(*) FILTER(WHERE created_at>=%s),count(*) FILTER(WHERE created_at>=%s AND created_at<%s)
            FROM knowledge_activity WHERE knowledge_type=%s AND knowledge_id=%s GROUP BY activity_type""",
            (recent,previous,recent,kind,object_id)).fetchall()
        counts={r[0]:r for r in rows};activation=sum(counts.get(t,(None,0))[1] for t in ACTIVATION_TYPES);access=sum(counts.get(t,(None,0))[1] for t in ACCESS_TYPES)
        last_activation=max((counts[t][2] for t in ACTIVATION_TYPES if t in counts),default=None);last_access=max((counts[t][2] for t in ACCESS_TYPES if t in counts),default=None)
        recent_count=sum(r[3] for r in rows);previous_count=sum(r[4] for r in rows);trend=(recent_count-previous_count)/max(1,recent_count+previous_count);trend=max(-1,min(1,trend))
        evidence,sessions=_evidence_counts(connection,kind,object_id)
        recency=max((x for x in (last_activation,last_access) if x),default=None)
        recency_score=0 if recency is None else math.exp(-max(0,(now-recency).total_seconds())/(30*86400))
        importance=min(1,0.25*math.log1p(evidence)/math.log(6)+0.20*math.log1p(sessions)/math.log(4)+0.20*math.log1p(activation)/math.log(11)+0.20*math.log1p(access)/math.log(11)+0.15*recency_score)
        row=connection.execute("""INSERT INTO knowledge_signals(knowledge_type,knowledge_id,evidence_count,independent_session_count,activation_count,access_count,last_activated_at,last_accessed_at,importance_score,trend_score,calculated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(knowledge_type,knowledge_id) DO UPDATE SET evidence_count=EXCLUDED.evidence_count,independent_session_count=EXCLUDED.independent_session_count,activation_count=EXCLUDED.activation_count,access_count=EXCLUDED.access_count,last_activated_at=EXCLUDED.last_activated_at,last_accessed_at=EXCLUDED.last_accessed_at,importance_score=EXCLUDED.importance_score,trend_score=EXCLUDED.trend_score,calculated_at=EXCLUDED.calculated_at RETURNING knowledge_type,knowledge_id,evidence_count,independent_session_count,activation_count,access_count,last_activated_at,last_accessed_at,importance_score,trend_score,calculated_at""",
            (kind,object_id,evidence,sessions,activation,access,last_activation,last_access,importance,trend,now)).fetchone();connection.commit()
    return _signal(row)


def _signal(r):
    return {"knowledge_type":r[0],"knowledge_id":r[1],"evidence_count":r[2],"independent_session_count":r[3],"activation_count":r[4],"access_count":r[5],"last_activated_at":r[6].isoformat() if r[6] else None,"last_accessed_at":r[7].isoformat() if r[7] else None,"importance_score":r[8],"trend_score":r[9],"calculated_at":r[10].isoformat()}


def list_signals(kind=None,limit=100):
    where=" WHERE knowledge_type=%s" if kind else "";params=[kind] if kind else [];params.append(max(1,min(limit,1000)))
    with get_db_connection() as connection: rows=connection.execute("SELECT knowledge_type,knowledge_id,evidence_count,independent_session_count,activation_count,access_count,last_activated_at,last_accessed_at,importance_score,trend_score,calculated_at FROM knowledge_signals"+where+" ORDER BY trend_score DESC,importance_score DESC LIMIT %s",params).fetchall()
    return [_signal(r) for r in rows]
