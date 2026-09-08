"""Deterministic marked two-way CalDAV projection without a real Nextcloud account."""
import asyncio
from datetime import datetime,timedelta
from uuid import uuid4

from smart_notebook.app import app  # noqa: F401 - migrations
from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.caldav_sync import (list_conflicts,parse_vtodo,resolve_conflict,
    serialize_vtodo,synchronize_caldav)


class FakeCalDAV:
    def __init__(self):self.objects={};self.revision=0;self.unmarked=True;self.put_count=0;self.incremental=False
    async def discover(self):return {"calendar_url":"https://nextcloud.test/dav/calendars/test/notizbuch/","display_name":"notizbuch","sync_token":str(self.revision)}
    async def fetch(self,calendar_url,sync_token=None):
        if self.incremental and sync_token is not None:
            return {"objects":[],"deleted_hrefs":[],"sync_token":str(self.revision),"complete":False}
        objects=list(self.objects.values())
        if self.unmarked:
            objects.append(parse_vtodo("BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:manual-nextcloud-task\r\nSUMMARY:Manuell und unmarkiert\r\nEND:VTODO\r\nEND:VCALENDAR\r\n","/dav/manual.ics",'"manual"'))
        return {"objects":objects,"deleted_hrefs":[],"sync_token":str(self.revision),"complete":True}
    async def put(self,calendar_url,entity,href=None,etag=None):
        self.put_count+=1;self.revision+=1;target=href or f"/dav/calendars/test/notizbuch/{entity['uid']}.ics";new_etag=f'"{self.revision}"'
        remote=parse_vtodo(serialize_vtodo(entity),target,new_etag);self.objects[entity["public_id"]]=remote
        return {"href":target,"etag":new_etag}
    async def delete(self,calendar_url,href,etag=None):
        target=next((public_id for public_id,item in self.objects.items() if item["href"]==href),None)
        if target is not None:self.revision+=1;self.objects.pop(target)
    def mutate(self,public_id,**changes):
        self.revision+=1;item=dict(self.objects[public_id]);item.update(changes);item["etag"]=f'"{self.revision}"';self.objects[public_id]=item
    def remove(self,public_id):self.revision+=1;self.objects.pop(public_id)


def row_for(kind,internal_id):
    with get_db_connection() as db:return db.execute("SELECT public_id FROM caldav_sync_entities WHERE entity_type=%s AND internal_id=%s",(kind,internal_id)).fetchone()[0]


def main():
    now=datetime.now(TIMEZONE);suffix=uuid4().hex;profile=f"_contract_test_caldav_{suffix}";gateway=FakeCalDAV()
    with get_db_connection() as db:
        task=db.execute("""INSERT INTO tasks(content,created_at,updated_at,work_start_at,due_at,status,archived,priority,urgency,percent_complete,urgency_source)
        VALUES(%s,%s,%s,%s,%s,'open',FALSE,5,.4,0,'manual') RETURNING id""",(f"M8 CalDAV Aufgabe {suffix}",now,now,now,now+timedelta(days=1))).fetchone()[0]
        list_id=db.execute("INSERT INTO lists(title,description,created_at,updated_at,archived) VALUES(%s,'Testliste',%s,%s,FALSE) RETURNING id",(f"M8 CalDAV Liste {suffix}",now,now)).fetchone()[0]
        first=db.execute("INSERT INTO list_items(list_id,content,created_at,updated_at,status,archived) VALUES(%s,'Milch',%s,%s,'active',FALSE) RETURNING id",(list_id,now,now)).fetchone()[0]
        second=db.execute("INSERT INTO list_items(list_id,content,created_at,updated_at,status,archived) VALUES(%s,'Kaffee',%s,%s,'active',FALSE) RETURNING id",(list_id,now,now)).fetchone()[0];db.commit()
    scope={("task",task),("list",list_id),("list_item",first),("list_item",second)}
    try:
        initial=asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        assert initial["ignored_unmarked"]==1 and len([x for x in initial["actions"] if x["action"]=="create_remote"])==4
        task_uuid=row_for("task",task);list_uuid=row_for("list",list_id);first_uuid=row_for("list_item",first);second_uuid=row_for("list_item",second)
        assert gateway.objects[task_uuid]["work_start_at"] is not None
        assert gateway.objects[list_uuid]["entity_type"]=="list"
        assert gateway.objects[first_uuid]["parent_uid"]==gateway.objects[list_uuid]["uid"]

        # An incremental sync-collection response omits unchanged resources.
        # Such omissions must neither archive nor recreate remote objects.
        puts_before=gateway.put_count;gateway.incremental=True
        incremental=asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        assert incremental["action_count"]==0 and gateway.put_count==puts_before
        gateway.incremental=False

        gateway.mutate(task_uuid,status="COMPLETED",percent_complete=100,summary="Remote erledigte Aufgabe")
        completed_run=asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        assert any(x["action"]=="delete_remote_completed" and x["id"]==str(task_uuid) for x in completed_run["actions"])
        assert task_uuid not in gateway.objects
        with get_db_connection() as db:r=db.execute("SELECT content,status,archived,archive_reason FROM tasks WHERE id=%s",(task,)).fetchone()
        assert r==("Remote erledigte Aufgabe","archived",True,"remote_completed")

        # Reopening locally recreates the cleaned-up remote VTODO.
        with get_db_connection() as db:db.execute("UPDATE tasks SET status='open',archived=FALSE,archived_at=NULL,archive_reason=NULL,percent_complete=0,updated_at=%s WHERE id=%s",(datetime.now(TIMEZONE),task));db.commit()
        asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        assert task_uuid in gateway.objects and gateway.objects[task_uuid]["status"]=="NEEDS-ACTION"
        with get_db_connection() as db:r=db.execute("SELECT content,status,archived,archive_reason FROM tasks WHERE id=%s",(task,)).fetchone()
        assert r==("Remote erledigte Aufgabe","open",False,None)

        gateway.mutate(first_uuid,status="COMPLETED",percent_complete=100)
        asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        assert first_uuid not in gateway.objects
        with get_db_connection() as db:r=db.execute("SELECT status,archived,archive_reason FROM list_items WHERE id=%s",(first,)).fetchone()
        assert r==("archived",True,"remote_completed")

        gateway.remove(second_uuid);asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        with get_db_connection() as db:r=db.execute("SELECT status,archived,archive_reason FROM list_items WHERE id=%s",(second,)).fetchone()
        assert r==("archived",True,"remote_deleted")

        # Concurrent title edits preserve both sides and apply only remote completion immediately.
        with get_db_connection() as db:db.execute("UPDATE lists SET title='Lokaler Konflikttitel',updated_at=%s WHERE id=%s",(datetime.now(TIMEZONE),list_id));db.commit()
        gateway.mutate(list_uuid,summary="Remote Konflikttitel",status="COMPLETED",percent_complete=100)
        conflict_run=asyncio.run(synchronize_caldav(gateway=gateway,only_entities=scope,profile_key=profile))
        assert any(x["action"]=="conflict" and x["id"]==str(list_uuid) for x in conflict_run["actions"])
        conflict=next(x for x in list_conflicts() if x["public_id"]==str(list_uuid) and x["status"]=="open")
        with get_db_connection() as db:r=db.execute("SELECT title,archived,archive_reason FROM lists WHERE id=%s",(list_id,)).fetchone()
        assert r==("Lokaler Konflikttitel",True,"remote_completed")
        resolved=resolve_conflict(conflict["id"],"keep_remote");assert resolved["status"]=="resolved"
        with get_db_connection() as db:r=db.execute("SELECT title,archived FROM lists WHERE id=%s",(list_id,)).fetchone()
        assert r==("Remote Konflikttitel",True)
    finally:
        with get_db_connection() as db:
            ids=[r[0] for r in db.execute("SELECT public_id FROM caldav_sync_entities WHERE (entity_type='task' AND internal_id=%s) OR (entity_type='list' AND internal_id=%s) OR (entity_type='list_item' AND internal_id=ANY(%s))",(task,list_id,[first,second])).fetchall()]
            if ids:
                db.execute("DELETE FROM caldav_sync_audit WHERE public_id=ANY(%s)",(ids,));db.execute("DELETE FROM caldav_sync_conflicts WHERE public_id=ANY(%s)",(ids,));db.execute("DELETE FROM caldav_sync_entities WHERE public_id=ANY(%s)",(ids,))
            db.execute("DELETE FROM caldav_sync_state WHERE profile_key=%s",(profile,));db.execute("DELETE FROM list_items WHERE id=ANY(%s)",([first,second],));db.execute("DELETE FROM lists WHERE id=%s",(list_id,));db.execute("DELETE FROM tasks WHERE id=%s",(task,));db.commit()
    print("CALDAV TWO-WAY SYNC TEST: PASS")


if __name__=="__main__":main()
