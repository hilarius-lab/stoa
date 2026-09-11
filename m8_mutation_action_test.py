"""A07 action planning, execution, audit, idempotency, and safety gate."""
import atexit
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from smart_notebook.app import app as _app  # noqa: F401 - imports apply migrations
from smart_notebook.config import EMBEDDING_DIMENSIONS,TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.client_sessions import create_client_session,_materialize_capture_result
from smart_notebook.services.knowledge_preflight import ensure_session_knowledge_preflights
from smart_notebook.services.mutation_actions import (
    ensure_session_mutation_actions,public_mutation_actions,_model_state,_validate_change_plan,
)
from smart_notebook.services.mutation_targets import ensure_session_mutation_target_resolutions


_CLIENT_SESSIONS=[]
_TASKS=[]
_NOTES=[]
_LISTS=[]
_IDENTITIES=[]


def _cleanup():
    with get_db_connection() as db:
        for public_id in _IDENTITIES:db.execute("DELETE FROM client_entity_identities WHERE public_id=%s",(public_id,))
        for client_session_id in _CLIENT_SESSIONS:
            row=db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",
                           (client_session_id,)).fetchone()
            ingestion_id=row[0] if row else None
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s",(client_session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s",(client_session_id,))
            if ingestion_id:db.execute("DELETE FROM ingestion_sessions WHERE id=%s",(ingestion_id,))
        for task_id in _TASKS:db.execute("DELETE FROM tasks WHERE id=%s",(task_id,))
        for note_id in _NOTES:db.execute("DELETE FROM notes WHERE id=%s",(note_id,))
        for list_id in _LISTS:db.execute("DELETE FROM lists WHERE id=%s",(list_id,))
        db.commit()


atexit.register(_cleanup)


def _task(content,status="open"):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        task_id=db.execute("""INSERT INTO tasks(content,created_at,updated_at,status,archived,urgency,
        urgency_source,percent_complete) VALUES(%s,%s,%s,%s,FALSE,.5,'policy_default',%s) RETURNING id""",
        (content,now,now,status,100 if status=="done" else 0)).fetchone()[0];db.commit()
    _TASKS.append(task_id);return task_id


def _note(content):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        note_id=db.execute("INSERT INTO notes(content,created_at,updated_at,archived) VALUES(%s,%s,%s,FALSE) RETURNING id",
                           (content,now,now)).fetchone()[0];db.commit()
    _NOTES.append(note_id);return note_id


def _list(title,items=()):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as db:
        list_id=db.execute("INSERT INTO lists(title,description,created_at,updated_at,archived) VALUES(%s,'',%s,%s,FALSE) RETURNING id",
                           (title,now,now)).fetchone()[0]
        item_ids=[db.execute("""INSERT INTO list_items(list_id,content,created_at,updated_at,status,archived)
                  VALUES(%s,%s,%s,%s,'active',FALSE) RETURNING id""",(list_id,item,now,now)).fetchone()[0]
                  for item in items]
        db.commit()
    _LISTS.append(list_id);return list_id,item_ids


def _candidate(kind,internal_id,text,parent=None):
    return {"key":f"{kind}:{internal_id}","type":kind,"id":internal_id,
            "title":text if kind=="list" else None,"content":"" if kind=="list" else text,
            "retrieval":{"stage":"exact","scores":{"exact":1.0}},"parent":parent}


def _session_part(source_text,target_text,intent,target_type,context_ref=None):
    client_session_id=uuid4();session=create_client_session(client_session_id,"_a07_contract_test",
        capture_mode="auto",context_ref=context_ref);_CLIENT_SESSIONS.append(client_session_id)
    session_id=session["ingestion_session_id"];now=datetime.now(TIMEZONE);content_hash=uuid4().hex
    with get_db_connection() as db:
        chunk_id=db.execute("""INSERT INTO ingestion_chunks(session_id,sequence,client_chunk_id,text,
        source_start_ms,source_end_ms,content_hash,created_at) VALUES(%s,1,%s,%s,0,2500,%s,%s) RETURNING id""",
        (session_id,f"a07-{uuid4()}",source_text,content_hash,now)).fetchone()[0]
        segment_id=db.execute("""INSERT INTO semantic_segments(session_id,chunk_id,sequence,segment_index,
        segment_type,text,confidence,source_start_ms,source_end_ms,context_before,content_hash,processor_type,status,
        created_at,updated_at) VALUES(%s,%s,1,1,'statement',%s,.97,0,2500,'',%s,'deterministic','confirmed',%s,%s)
        RETURNING id""",(session_id,chunk_id,source_text,content_hash,now,now)).fetchone()[0]
        db.execute("""INSERT INTO session_intent_decisions(session_id,primary_intent,target_type,target_text,
        confidence,multiple_intents_detected,reason_codes,decision_source,created_at,updated_at)
        VALUES(%s,%s,%s,%s,.97,FALSE,'[]'::jsonb,'deterministic_test',%s,%s)""",
        (session_id,intent,target_type,target_text,now,now))
        part_id=db.execute("""INSERT INTO session_intent_parts(session_id,ordinal,primary_intent,target_type,
        target_text,source_text,source_start,source_end,confidence,reason_codes,decision_source,created_at)
        VALUES(%s,1,%s,%s,%s,%s,0,%s,.97,'[]'::jsonb,'deterministic_test',%s) RETURNING id""",
        (session_id,intent,target_type,target_text,source_text,len(source_text),now)).fetchone()[0]
        db.execute("INSERT INTO session_intent_part_segments(part_id,segment_id) VALUES(%s,%s)",(part_id,segment_id));db.commit()
    return client_session_id,session_id,{"id":part_id,"session_id":session_id,"ordinal":1,
        "primary_intent":intent,"target_type":target_type,"target_text":target_text,"source_text":source_text,
        "source_start":0,"source_end":len(source_text),"confidence":.97,"source_segment_ids":[segment_id]}


async def _resolved_action(source_text,target_text,intent,target_type,candidate,action_mode="deterministic",
                           plan=None,context_ref=None):
    client_session_id,session_id,part=_session_part(source_text,target_text,intent,target_type,context_ref)
    with patch("smart_notebook.services.knowledge_preflight.search_knowledge",new=AsyncMock(return_value=[candidate])):
        await ensure_session_knowledge_preflights(session_id,[part],artifact_ids=[],mode="deterministic")
    resolutions=await ensure_session_mutation_target_resolutions(session_id,[part],"deterministic")
    assert resolutions[0]["status"]=="resolved",resolutions
    embedding=AsyncMock(return_value=[0.0]*EMBEDDING_DIMENSIONS)
    planner=AsyncMock(return_value=(plan,"test:model")) if plan else None
    with patch("smart_notebook.services.mutation_actions.get_embedding",new=embedding):
        if planner:
            with patch("smart_notebook.services.mutation_actions._plan_change_with_llm",new=planner):
                actions=await ensure_session_mutation_actions(session_id,[part],action_mode)
        else:actions=await ensure_session_mutation_actions(session_id,[part],action_mode)
    return client_session_id,session_id,part,actions


def main():
    task_id=_task(f"A07 Atlas-Bericht {uuid4().hex[:8]}")
    client_id,session_id,part,actions=asyncio.run(_resolved_action(
        "Hake den A07 Atlas-Bericht ab.","A07 Atlas-Bericht","complete","task",
        _candidate("task",task_id,"A07 Atlas-Bericht")))
    assert actions[0]["status"]=="completed" and actions[0]["operation"]=="task_complete",actions
    with get_db_connection() as db:
        assert tuple(db.execute("SELECT status,percent_complete,archived FROM tasks WHERE id=%s",(task_id,)).fetchone())==("done",100,False)
        audit=db.execute("SELECT before_state,after_state FROM mutation_action_executions WHERE session_id=%s",(session_id,)).fetchone()
    assert audit[0]["status"]=="open" and audit[1]["status"]=="done",audit
    again=asyncio.run(ensure_session_mutation_actions(session_id,[part],"deterministic"))
    assert again==actions,"completed execution must be idempotent"
    result=_materialize_capture_result(client_id)
    assert result["action_status"]=="completed" and result["actions"][0]["status"]=="completed",result
    assert all("target_id" not in item and "before_state" not in item and "after_state" not in item
               for item in result["actions"]),result

    item_list,item_ids=_list(f"A07 Einkaufsliste {uuid4().hex[:8]}",["Milch"]);item_id=item_ids[0]
    _,_,_,actions=asyncio.run(_resolved_action("Hake Milch auf der Liste ab.","Milch","complete","list_item",
        _candidate("list_item",item_id,"Milch",{"type":"list","id":item_list,"title":"Liste"})))
    assert actions[0]["operation"]=="list_item_complete"
    with get_db_connection() as db:assert db.execute("SELECT status FROM list_items WHERE id=%s",(item_id,)).fetchone()[0]=="done"

    note_id=_note(f"A07 Urlaubsideen {uuid4().hex[:8]}")
    _,_,_,actions=asyncio.run(_resolved_action("Vergiss die Notiz A07 Urlaubsideen.","A07 Urlaubsideen","archive","note",
        _candidate("note",note_id,"A07 Urlaubsideen")))
    assert actions[0]["operation"]=="note_archive"
    with get_db_connection() as db:
        note=db.execute("SELECT archived,archived_at IS NOT NULL,archive_reason FROM notes WHERE id=%s",(note_id,)).fetchone()
    assert tuple(note)==(True,True,"user_requested"),note

    archive_list,archive_items=_list(f"A07 Herbsturlaub {uuid4().hex[:8]}",["Jacke","Schuhe"])
    _,_,_,actions=asyncio.run(_resolved_action("Lösche die Liste A07 Herbsturlaub.","A07 Herbsturlaub","archive","list",
        _candidate("list",archive_list,"A07 Herbsturlaub")))
    assert actions[0]["operation"]=="list_archive"
    with get_db_connection() as db:
        parent=db.execute("SELECT archived,archive_reason FROM lists WHERE id=%s",(archive_list,)).fetchone()
        children=db.execute("SELECT status,archived,archive_reason FROM list_items WHERE list_id=%s ORDER BY id",(archive_list,)).fetchall()
    assert tuple(parent)==(True,"user_requested") and all(tuple(row)==("archived",True,"user_requested_parent") for row in children)

    add_list,_=_list(f"A07 Packliste {uuid4().hex[:8]}")
    _,_,_,actions=asyncio.run(_resolved_action("Ergänze Brot auf der Packliste.","Packliste","change","list_item",
        _candidate("list",add_list,"Packliste")))
    assert actions[0]["operation"]=="list_add_item" and actions[0]["status"]=="completed",actions
    with get_db_connection() as db:
        assert db.execute("SELECT count(*) FROM list_items WHERE list_id=%s AND content='Brot'",(add_list,)).fetchone()[0]==1
    asyncio.run(_resolved_action("Ergänze Brot auf der Packliste.","Packliste","change","list_item",
        _candidate("list",add_list,"Packliste")))
    with get_db_connection() as db:
        assert db.execute("SELECT count(*) FROM list_items WHERE list_id=%s AND content='Brot'",(add_list,)).fetchone()[0]==1

    update_note=_note(f"A07 alter Inhalt {uuid4().hex[:8]}")
    update_plan={"status":"planned","operation":"note_update","payload":{"new_text":"A07 neuer Inhalt"},
                 "confidence":.96,"reason_codes":["content_update"]}
    _,_,_,actions=asyncio.run(_resolved_action("Ändere die Notiz in A07 neuer Inhalt.","Notiz","change","note",
        _candidate("note",update_note,"alter Inhalt"),action_mode="llm",plan=update_plan))
    assert actions[0]["operation"]=="note_update"
    with get_db_connection() as db:assert db.execute("SELECT content FROM notes WHERE id=%s",(update_note,)).fetchone()[0]=="A07 neuer Inhalt"

    done_task=_task(f"A07 Kontext erledigt {uuid4().hex[:8]}",status="done");public_id=uuid4();_IDENTITIES.append(public_id)
    with get_db_connection() as db:
        db.execute("INSERT INTO client_entity_identities(public_id,entity_type,internal_id,created_at) VALUES(%s,'task',%s,%s)",
                   (public_id,done_task,datetime.now(TIMEZONE)));db.commit()
    _,_,_,actions=asyncio.run(_resolved_action("Aufgabe A07 wieder öffnen.","Aufgabe A07","change","task",
        _candidate("task",done_task,"A07 Kontext erledigt"),context_ref={"type":"task","id":str(public_id)}))
    assert actions[0]["operation"]=="task_reopen"
    with get_db_connection() as db:
        assert tuple(db.execute("SELECT status,percent_complete FROM tasks WHERE id=%s",(done_task,)).fetchone())==("open",0)

    unclear_task=_task(f"A07 unklare Aufgabe {uuid4().hex[:8]}")
    _,session_id,_,actions=asyncio.run(_resolved_action("Ändere die Aufgabe A07 irgendwie.","A07 irgendwie","change","task",
        _candidate("task",unclear_task,"A07 unklare Aufgabe")))
    assert actions[0]["status"]=="clarification_required" and actions[0]["operation"] is None,actions
    with get_db_connection() as db:
        assert db.execute("SELECT count(*) FROM session_questions WHERE session_id=%s AND status='open'",(session_id,)).fetchone()[0]==1
        assert db.execute("SELECT content FROM tasks WHERE id=%s",(unclear_task,)).fetchone()[0].startswith("A07 unklare Aufgabe")

    invalid=_validate_change_plan({"status":"executable","operation":"task_update","new_text":"erfunden",
        "confidence":.99,"reason_codes":["model_selection"]},
        {"source_text":"Ändere die Aufgabe auf belegt.","target_type":"task"},{"target_type":"task"})
    assert invalid["status"]=="clarification_required" and "invalid_value" in invalid["reason_codes"],invalid

    model_state=_model_state("list_item",{"id":42,"list_id":7,"content":"Milch","status":"active",
        "archived":False,"archive_reason":"internal","archived_at":None})
    assert model_state=={"content":"Milch","status":"active","archived":False},model_state

    public=public_mutation_actions(actions)
    assert all("target_id" not in item and "payload" not in item for item in public),public
    _cleanup()
    print("M8 MUTATION ACTION TEST: PASS")


if __name__=="__main__":main()
