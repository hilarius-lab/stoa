"""Regression for evidence-based cross-sentence task urgency modifiers."""
import asyncio
from datetime import datetime,timedelta
import hashlib

from psycopg.types.json import Jsonb

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import (
    _apply_llm_proposal, _router_overrides, _save_classification,
    get_session_artifact_record,
)
from smart_notebook.services.ingestion import create_ingestion_session_record
from smart_notebook.services.promotion import promote_session_artifacts


def main():
    now=datetime.now(TIMEZONE);session_id=None;task_id=None
    try:
        session_id=create_ingestion_session_record("task-modifier-regression",source="task_modifier_test.py")["id"]
        texts=("Der Bericht muss am Freitag um 15 Uhr verschickt werden.","Diese Aufgabe ist sehr wichtig.")
        with get_db_connection() as c:
            chunk_ids=[];segment_ids=[]
            for sequence,text in enumerate(texts,1):
                chunk_id=c.execute("""INSERT INTO ingestion_chunks(session_id,sequence,client_chunk_id,text,content_hash,created_at)
                VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",(session_id,sequence,f"modifier-{session_id}-{sequence}",text,
                hashlib.sha256(text.encode()).hexdigest(),now)).fetchone()[0];chunk_ids.append(chunk_id)
                segment_id=c.execute("""INSERT INTO semantic_segments(session_id,chunk_id,sequence,segment_index,segment_type,text,
                confidence,context_before,content_hash,processor_type,status,created_at,updated_at)
                VALUES(%s,%s,%s,1,'statement',%s,1.0,'',%s,'regression','confirmed',%s,%s) RETURNING id""",
                (session_id,chunk_id,sequence,text,hashlib.sha256(text.encode()).hexdigest(),now,now)).fetchone()[0];segment_ids.append(segment_id)
            artifact_id=c.execute("""INSERT INTO session_artifacts(session_id,artifact_type,content,status,confidence,origin_key,created_at,updated_at)
            VALUES(%s,'task',%s,'confirmed',0.94,%s,%s,%s) RETURNING id""",(session_id,texts[0],f"modifier-test:{session_id}",now,now)).fetchone()[0]
            c.execute("INSERT INTO session_artifact_sources(artifact_id,segment_id,relation,created_at) VALUES(%s,%s,'source',%s)",(artifact_id,segment_ids[0],now));c.commit()
        due_at=(now+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
        _save_classification(artifact_id,{"candidate_type":"task","alternative_type":"note",
            "normalized_data":{"due_at":due_at.isoformat(),"due_source":"explicit_relative"},
            "evidence_spans":["Freitag um 15 Uhr"],"reason_codes":["action_or_responsibility"],"missing_fields":[],
            "confidence":0.94,"decision_source":"rules","abstain":False,"validated":True})
        operations,handled,_=_router_overrides(session_id,[(segment_ids[1],texts[1],"statement",1.0)],[],now)
        assert handled=={segment_ids[1]} and len(operations)==1,operations
        _apply_llm_proposal(session_id,chunk_ids[1],{"topics":[],"operations":operations})
        artifact=get_session_artifact_record(artifact_id);data=artifact["classification"]["normalized_data"]
        assert data["due_at"]==due_at.isoformat() and data["urgency"]==0.9,data
        assert artifact["source_segment_ids"]==segment_ids,artifact
        result=asyncio.run(promote_session_artifacts(session_id,"deterministic"));assert not result["deferred"],result
        task_id=result["promoted"][0]["knowledge_id"]
        with get_db_connection() as c:
            row=c.execute("SELECT work_start_at,due_at,urgency,urgency_source FROM tasks WHERE id=%s",(task_id,)).fetchone()
        assert row[0]==now.replace(hour=0,minute=0,second=0,microsecond=0),row
        assert row[1] is not None and row[2]==0.9 and row[3]=="explicit",row
        print("TASK MODIFIER REGRESSION TEST: PASS")
    finally:
        with get_db_connection() as c:
            if task_id is not None:
                c.execute("DELETE FROM claims WHERE source_knowledge_type='task' AND source_knowledge_id=%s",(task_id,))
                c.execute("DELETE FROM tasks WHERE id=%s",(task_id,))
            if session_id is not None:c.execute("DELETE FROM ingestion_sessions WHERE id=%s",(session_id,))
            c.commit()


if __name__=="__main__":main()
