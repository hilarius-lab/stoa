"""A08 per-intent confidence gate and partial execution contract."""
import atexit
import asyncio
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from smart_notebook.app import app as _app  # noqa: F401 - imports apply migrations
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.capture_intent import deterministic_content_intent
from smart_notebook.services.client_sessions import create_client_session,_materialize_capture_result
from smart_notebook.services.knowledge_preflight import ensure_session_knowledge_preflights
from smart_notebook.services.mutation_actions import ensure_session_mutation_actions
from smart_notebook.services.mutation_targets import ensure_session_mutation_target_resolutions


_CLIENT_SESSIONS=[]
_LISTS=[]


def _cleanup():
    with get_db_connection() as db:
        for client_session_id in _CLIENT_SESSIONS:
            row=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",
                           (client_session_id,)).fetchone()
            ingestion_id=row[0] if row else None
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s",(client_session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(client_session_id,))
            if ingestion_id:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
        for list_id in _LISTS:db.execute("DELETE FROM lists WHERE id=%s",(list_id,))
        db.commit()


atexit.register(_cleanup)


def _list(title,item=None):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        list_id=db.execute("""INSERT INTO lists(title,description,created_at,updated_at,archived)
        VALUES(%s,'',%s,%s,FALSE) RETURNING id""",(title,now,now)).fetchone()[0]
        item_id=None
        if item:
            item_id=db.execute("""INSERT INTO list_items(list_id,content,created_at,updated_at,status,archived)
            VALUES(%s,%s,%s,%s,'active',FALSE) RETURNING id""",(list_id,item,now,now)).fetchone()[0]
        db.commit()
    _LISTS.append(list_id)
    return list_id,item_id


def _candidate(kind,internal_id,text,parent=None):
    return {"key":f"{kind}:{internal_id}","type":kind,"id":internal_id,
            "title":text if kind=="list" else None,"content":"" if kind=="list" else text,
            "retrieval":{"stage":"exact","scores":{"exact":1.0}},"parent":parent}


def _mixed_session(parts):
    client_session_id=uuid4();session=create_client_session(client_session_id,"_a08_contract_test",capture_mode="auto")
    _CLIENT_SESSIONS.append(client_session_id);session_id=session["ingestion_session_id"]
    text=" ".join(item["source_text"] for item in parts);now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        chunk_id=db.execute("""INSERT INTO ingestion_chunks(session_id,sequence,client_chunk_id,text,
        source_start_ms,source_end_ms,content_hash,created_at) VALUES(%s,1,%s,%s,0,5000,%s,%s) RETURNING id""",
        (session_id,f"a08-{uuid4()}",text,uuid4().hex,now)).fetchone()[0]
        segment_ids=[];cursor=0
        for index,part in enumerate(parts,start=1):
            start=text.index(part["source_text"],cursor);cursor=start+len(part["source_text"])
            segment_id=db.execute("""INSERT INTO semantic_segments(session_id,chunk_id,sequence,segment_index,
            segment_type,text,confidence,source_start_ms,source_end_ms,context_before,content_hash,processor_type,status,
            created_at,updated_at) VALUES(%s,%s,1,%s,'statement',%s,%s,%s,%s,'',%s,'deterministic','confirmed',%s,%s)
            RETURNING id""",(session_id,chunk_id,index,part["source_text"],part["confidence"],start*100,
            cursor*100,uuid4().hex,now,now)).fetchone()[0]
            segment_ids.append(segment_id)
        first=parts[0]
        db.execute("""INSERT INTO session_intent_decisions(session_id,primary_intent,target_type,target_text,
        confidence,multiple_intents_detected,reason_codes,decision_source,created_at,updated_at)
        VALUES(%s,%s,%s,%s,%s,TRUE,'["multiple_intents"]'::jsonb,'deterministic_test',%s,%s)""",
        (session_id,first["intent"],first["target_type"],first["target_text"],first["confidence"],now,now))
        stored=[];cursor=0
        for ordinal,(part,segment_id) in enumerate(zip(parts,segment_ids),start=1):
            start=text.index(part["source_text"],cursor);cursor=start+len(part["source_text"])
            part_id=db.execute("""INSERT INTO session_intent_parts(session_id,ordinal,primary_intent,target_type,
            target_text,source_text,source_start,source_end,confidence,reason_codes,decision_source,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'[]'::jsonb,'deterministic_test',%s) RETURNING id""",
            (session_id,ordinal,part["intent"],part["target_type"],part["target_text"],part["source_text"],
             start,cursor,part["confidence"],now)).fetchone()[0]
            db.execute("INSERT INTO session_intent_part_segments(part_id,segment_id) VALUES(%s,%s)",(part_id,segment_id))
            stored.append({"id":part_id,"session_id":session_id,"ordinal":ordinal,
                "primary_intent":part["intent"],"target_type":part["target_type"],
                "target_text":part["target_text"],"source_text":part["source_text"],
                "source_start":start,"source_end":cursor,"confidence":part["confidence"],
                "reason_codes":[],"source_segment_ids":[segment_id]})
        db.commit()
    return client_session_id,session_id,stored


def main():
    tentative=deterministic_content_intent("Lösche vielleicht die A08 Urlaubsliste.")
    assert tentative["confidence"]<.85 and "tentative_action" in tentative["reason_codes"],tentative

    safe_list,safe_item=_list(f"A08 Einkauf {uuid4().hex[:8]}","A08 Milch")
    uncertain_list,_=_list(f"A08 Urlaub {uuid4().hex[:8]}")
    parts=[
        {"source_text":"Hake A08 Milch ab.","target_text":"A08 Milch","intent":"complete",
         "target_type":"list_item","confidence":.97},
        {"source_text":"Lösche vielleicht die A08 Urlaubsliste.","target_text":"A08 Urlaubsliste",
         "intent":"archive","target_type":"list","confidence":.62},
    ]
    client_id,session_id,stored=_mixed_session(parts)

    async def search(query,**_kwargs):
        if "Milch" in query:
            return [_candidate("list_item",safe_item,"A08 Milch",
                {"type":"list","id":safe_list,"title":"A08 Einkauf"})]
        return [_candidate("list",uncertain_list,"A08 Urlaubsliste")]

    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=search):
        asyncio.run(ensure_session_knowledge_preflights(session_id,stored,artifact_ids=[],mode="deterministic"))
    resolutions=asyncio.run(ensure_session_mutation_target_resolutions(session_id,stored,"deterministic"))
    assert [item["status"] for item in resolutions]==["resolved","unresolved"],resolutions
    assert resolutions[1]["reason_codes"]==["low_intent_confidence"],resolutions

    actions=asyncio.run(ensure_session_mutation_actions(session_id,stored,"deterministic"))
    assert len(actions)==1 and actions[0]["status"]=="completed",actions
    result=_materialize_capture_result(client_id)
    assert result["action_status"]=="partially_completed",result
    assert [item["status"] for item in result["action_outcomes"]]==[
        "completed","pending_clarification"],result
    assert result["action_outcomes"][1]["confidence"]==.62,result
    assert all("target_id" not in item and "intent_part_id" not in item and "payload" not in item
               for item in result["action_outcomes"]),result
    with get_db_connection() as db:
        assert db.execute("SELECT status FROM list_items WHERE id=%s",(safe_item,)).fetchone()[0]=="done"
        assert db.execute("SELECT archived FROM lists WHERE id=%s",(uncertain_list,)).fetchone()[0] is False
        question=db.execute("""SELECT q.question_text,array_agg(s.segment_id) FROM session_questions q
        LEFT JOIN session_question_sources s ON s.question_id=q.id WHERE q.session_id=%s
        GROUP BY q.id""",(session_id,)).fetchone()
    assert question and "wirklich archiviert" in question[0] and len(question[1])==1,question

    repeated=asyncio.run(ensure_session_mutation_actions(session_id,stored,"deterministic"))
    assert repeated==actions,"A08 retry repeated an already completed sibling"
    _cleanup()
    print("M8 PARTIAL ACTION TEST: PASS")


if __name__=="__main__":main()
