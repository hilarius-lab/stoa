"""Marked two-way VTODO projection for a dedicated Nextcloud task calendar."""
import hashlib,json,re
from datetime import datetime,timezone
from urllib.parse import quote,urljoin,urlsplit,urlunsplit
from uuid import UUID,uuid4
from xml.etree import ElementTree as ET

import httpx
from psycopg.types.json import Jsonb

from ..config import (CALDAV_TIMEOUT_SECONDS,CALDAV_VERIFY_TLS,NEXTCLOUD_APP_PASSWORD,
    NEXTCLOUD_TASK_CALENDAR,NEXTCLOUD_URL,NEXTCLOUD_USERNAME,TIMEZONE)
from ..database import get_db_connection

PROFILE="nextcloud_notizbuch"
DAV="DAV:"
CALDAV="urn:ietf:params:xml:ns:caldav"
NS={"d":DAV,"c":CALDAV}


class CalDAVConfigurationError(Exception):pass
class CalDAVProtocolError(Exception):pass
class CalDAVPreconditionFailed(Exception):pass


def _configured():return bool(NEXTCLOUD_URL and NEXTCLOUD_USERNAME and NEXTCLOUD_APP_PASSWORD and NEXTCLOUD_TASK_CALENDAR)
def _ical_escape(value):return str(value or "").replace("\\","\\\\").replace("\n","\\n").replace(";","\\;").replace(",","\\,")
def _ical_unescape(value):return str(value or "").replace("\\n","\n").replace("\\N","\n").replace("\\,",",").replace("\\;",";").replace("\\\\","\\")
def _utc(value):
    if value is None:return None
    if value.tzinfo is None:value=value.replace(tzinfo=TIMEZONE)
    return value.astimezone(timezone.utc)
def _ical_time(value):return _utc(value).strftime("%Y%m%dT%H%M%SZ") if value else None
def _parse_time(value):
    if not value:return None
    raw=value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ","%Y%m%dT%H%M%S","%Y%m%d"):
        try:
            parsed=datetime.strptime(raw,fmt)
            return parsed.replace(tzinfo=timezone.utc if raw.endswith("Z") else TIMEZONE)
        except ValueError:pass
    return None
def _unfold(text):return re.sub(r"\r?\n[ \t]","",text.replace("\r\n","\n"))


def parse_vtodo(text,href=None,etag=None):
    properties={};params={};inside=False
    for raw in _unfold(text).splitlines():
        if raw.strip()=="BEGIN:VTODO":inside=True;continue
        if raw.strip()=="END:VTODO":break
        if not inside or ":" not in raw:continue
        left,value=raw.split(":",1);parts=left.split(";");name=parts[0].upper()
        properties[name]=_ical_unescape(value)
        params[name]={p.split("=",1)[0].upper():p.split("=",1)[1] for p in parts[1:] if "=" in p}
    if not properties.get("UID"):raise CalDAVProtocolError("VTODO has no UID")
    public_id=None
    try:public_id=UUID(properties.get("X-SMART-NOTEBOOK-ID",""))
    except ValueError:pass
    return {"href":href,"etag":etag,"uid":properties["UID"],"public_id":public_id,
        "entity_type":properties.get("X-SMART-NOTEBOOK-TYPE"),"summary":properties.get("SUMMARY","").strip(),
        "description":properties.get("DESCRIPTION","").strip(),"status":properties.get("STATUS","NEEDS-ACTION").upper(),
        "percent_complete":max(0,min(100,int(properties.get("PERCENT-COMPLETE","0") or 0))),
        "priority":max(0,min(9,int(properties.get("PRIORITY","0") or 0))),
        "urgency":float(properties["X-SMART-NOTEBOOK-URGENCY"]) if properties.get("X-SMART-NOTEBOOK-URGENCY") else None,
        "work_start_at":_parse_time(properties.get("DTSTART")),
        "due_at":_parse_time(properties.get("DUE")),"parent_uid":properties.get("RELATED-TO"),"raw":text}


def serialize_vtodo(entity):
    now=_ical_time(datetime.now(timezone.utc));lines=["BEGIN:VCALENDAR","VERSION:2.0","CALSCALE:GREGORIAN",
        "PRODID:-//Smart Notebook//CalDAV Sync v1//EN","BEGIN:VTODO",f"UID:{_ical_escape(entity['uid'])}",
        f"DTSTAMP:{now}",f"LAST-MODIFIED:{now}",f"SUMMARY:{_ical_escape(entity['summary'])}",
        f"STATUS:{entity['status']}",f"PERCENT-COMPLETE:{entity['percent_complete']}",f"PRIORITY:{entity['priority']}",
        f"X-SMART-NOTEBOOK-ID:{entity['public_id']}",f"X-SMART-NOTEBOOK-TYPE:{entity['entity_type']}"]
    if entity.get("description"):lines.append(f"DESCRIPTION:{_ical_escape(entity['description'])}")
    if entity.get("work_start_at"):lines.append(f"DTSTART:{_ical_time(entity['work_start_at'])}")
    if entity.get("due_at"):lines.append(f"DUE:{_ical_time(entity['due_at'])}")
    if entity.get("urgency") is not None:lines.append(f"X-SMART-NOTEBOOK-URGENCY:{entity['urgency']:.4f}")
    if entity.get("parent_uid"):lines.append(f"RELATED-TO;RELTYPE=PARENT:{_ical_escape(entity['parent_uid'])}")
    lines.extend(["END:VTODO","END:VCALENDAR",""])
    return "\r\n".join(lines)


def _jsonable_remote(item):
    return {k:(v.isoformat() if isinstance(v,datetime) else str(v) if isinstance(v,UUID) else v)
            for k,v in item.items() if k!="raw"}
def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _local_fingerprint(entity):
    if entity is None:return None
    keys=("entity_type","summary","description","work_start_at","due_at","status","priority","urgency","percent_complete","parent_uid")
    return _hash({k:entity.get(k) for k in keys})
def _remote_fingerprint(entity):return _hash(_jsonable_remote(entity))


class NextcloudCalDAVGateway:
    def __init__(self,url=None,username=None,password=None,calendar=None,transport=None):
        self.base_url=(url or NEXTCLOUD_URL).rstrip("/");self.username=username or NEXTCLOUD_USERNAME
        self.password=password or NEXTCLOUD_APP_PASSWORD;self.calendar=calendar or NEXTCLOUD_TASK_CALENDAR
        if not all((self.base_url,self.username,self.password,self.calendar)):raise CalDAVConfigurationError("Nextcloud URL, username, app password and task calendar are required")
        self.client=httpx.AsyncClient(auth=(self.username,self.password),timeout=CALDAV_TIMEOUT_SECONDS,
            verify=CALDAV_VERIFY_TLS,follow_redirects=True,transport=transport)

    async def close(self):await self.client.aclose()
    async def _request(self,method,url,body=None,depth=None,headers=None):
        combined={"Accept":"application/xml,text/calendar;q=0.9"};combined.update(headers or {})
        if depth is not None:combined["Depth"]=str(depth)
        if body is not None and "Content-Type" not in combined:combined["Content-Type"]="application/xml; charset=utf-8"
        response=await self.client.request(method,url,content=body.encode() if isinstance(body,str) else body,headers=combined)
        if response.status_code in (409,412):raise CalDAVPreconditionFailed(f"CalDAV precondition failed ({response.status_code})")
        if response.status_code>=400:raise CalDAVProtocolError(f"CalDAV {method} failed with HTTP {response.status_code}")
        return response

    async def discover(self):
        parsed=urlsplit(self.base_url);origin=urlunsplit((parsed.scheme,parsed.netloc,"","",""))
        well_known=origin+"/.well-known/caldav"
        principal_body='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
        response=await self._request("PROPFIND",well_known,principal_body,0)
        principal=ET.fromstring(response.content).findtext(".//d:current-user-principal/d:href",namespaces=NS)
        if not principal:principal=f"/remote.php/dav/principals/users/{quote(self.username)}/"
        principal_url=urljoin(str(response.url),principal)
        home_body='<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-home-set/></d:prop></d:propfind>'
        home_response=await self._request("PROPFIND",principal_url,home_body,0)
        home=ET.fromstring(home_response.content).findtext(".//c:calendar-home-set/d:href",namespaces=NS)
        if not home:home=f"/remote.php/dav/calendars/{quote(self.username)}/"
        home_url=urljoin(principal_url,home)
        list_body='<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/><d:sync-token/></d:prop></d:propfind>'
        listing=await self._request("PROPFIND",home_url,list_body,1);root=ET.fromstring(listing.content)
        wanted=self.calendar.casefold()
        for node in root.findall("d:response",NS):
            href=node.findtext("d:href",namespaces=NS) or "";display=node.findtext(".//d:displayname",namespaces=NS) or ""
            is_calendar=node.find(".//c:calendar",NS) is not None
            components=[x.attrib.get("name","").upper() for x in node.findall(".//c:comp",NS)]
            slug=href.rstrip("/").rsplit("/",1)[-1].casefold()
            if is_calendar and (not components or "VTODO" in components) and (display.casefold()==wanted or slug==wanted):
                return {"calendar_url":urljoin(home_url,href),"display_name":display or self.calendar,
                        "sync_token":node.findtext(".//d:sync-token",namespaces=NS)}
        raise CalDAVConfigurationError(f"VTODO calendar '{self.calendar}' was not found")

    def _multistatus(self,response):
        root=ET.fromstring(response.content);objects=[];deleted=[]
        for node in root.findall("d:response",NS):
            href=node.findtext("d:href",namespaces=NS) or "";status=" ".join(x.text or "" for x in node.findall(".//d:status",NS))
            data=node.findtext(".//c:calendar-data",namespaces=NS);etag=node.findtext(".//d:getetag",namespaces=NS)
            if " 404 " in f" {status} " or (not data and "404" in status):deleted.append(href)
            elif data:
                try:objects.append(parse_vtodo(data,href,etag))
                except CalDAVProtocolError:pass
        token=root.findtext(".//d:sync-token",namespaces=NS)
        return objects,deleted,token

    async def fetch(self,calendar_url,sync_token=None):
        if sync_token:
            body=f'''<?xml version="1.0"?><d:sync-collection xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:sync-token>{sync_token}</d:sync-token><d:sync-level>1</d:sync-level><d:prop><d:getetag/><c:calendar-data/></d:prop></d:sync-collection>'''
            try:
                response=await self._request("REPORT",calendar_url,body,1)
                objects,deleted,token=self._multistatus(response)
                return {"objects":objects,"deleted_hrefs":deleted,"sync_token":token or sync_token,"complete":False}
            except (CalDAVProtocolError,CalDAVPreconditionFailed):pass
        body='''<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VTODO"/></c:comp-filter></c:filter></c:calendar-query>'''
        response=await self._request("REPORT",calendar_url,body,1);objects,_,token=self._multistatus(response)
        if not token:
            token_body='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:sync-token/></d:prop></d:propfind>'
            token_response=await self._request("PROPFIND",calendar_url,token_body,0)
            token=ET.fromstring(token_response.content).findtext(".//d:sync-token",namespaces=NS)
        return {"objects":objects,"deleted_hrefs":[],"sync_token":token,"complete":True}

    async def put(self,calendar_url,entity,href=None,etag=None):
        target=urljoin(calendar_url,href) if href else urljoin(calendar_url.rstrip("/")+"/",quote(entity["uid"],safe="")+".ics")
        headers={"Content-Type":"text/calendar; charset=utf-8"}
        headers["If-Match" if etag else "If-None-Match"]=etag or "*"
        response=await self._request("PUT",target,serialize_vtodo(entity),headers=headers)
        stored_etag=response.headers.get("etag")
        stored_href=urlsplit(str(response.url)).path
        if not stored_etag:
            body='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>'
            check=await self._request("PROPFIND",str(response.url),body,0)
            stored_etag=ET.fromstring(check.content).findtext(".//d:getetag",namespaces=NS)
        return {"href":stored_href,"etag":stored_etag}

    async def delete(self,calendar_url,href,etag=None):
        headers={"If-Match":etag} if etag else {};await self._request("DELETE",urljoin(calendar_url,href),headers=headers)


def _ensure_mappings(only_entities=None):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        specs=[("task","tasks","archived=FALSE"),("list","lists","archived=FALSE"),("list_item","list_items","archived=FALSE")]
        for kind,table,where in specs:
            rows=c.execute(f"SELECT id FROM {table} x WHERE {where} OR EXISTS(SELECT 1 FROM caldav_sync_entities e WHERE e.entity_type=%s AND e.internal_id=x.id)",(kind,)).fetchall()
            for row in rows:
                if only_entities is not None and (kind,row[0]) not in only_entities:continue
                public=uuid4();uid=f"smart-notebook-{public}@local"
                c.execute("""INSERT INTO caldav_sync_entities(public_id,entity_type,internal_id,uid,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(entity_type,internal_id) DO NOTHING""",(public,kind,row[0],uid,now,now))
        c.execute("""UPDATE caldav_sync_entities child SET parent_public_id=parent.public_id FROM list_items i
        JOIN caldav_sync_entities parent ON parent.entity_type='list' AND parent.internal_id=i.list_id
        WHERE child.entity_type='list_item' AND child.internal_id=i.id AND child.parent_public_id IS DISTINCT FROM parent.public_id""")
        c.commit()


def _mapping_rows():
    with get_db_connection() as c:rows=c.execute("""SELECT public_id,entity_type,internal_id,uid,href,etag,remote_hash,local_fingerprint,parent_public_id,sync_state
    FROM caldav_sync_entities ORDER BY CASE entity_type WHEN 'task' THEN 1 WHEN 'list' THEN 2 ELSE 3 END,internal_id""").fetchall()
    return [{"public_id":r[0],"entity_type":r[1],"internal_id":r[2],"uid":r[3],"href":r[4],"etag":r[5],"remote_hash":r[6],"local_fingerprint":r[7],"parent_public_id":r[8],"sync_state":r[9]} for r in rows]


def _local_entity(mapping):
    with get_db_connection() as c:
        if mapping["entity_type"]=="task":
            r=c.execute("SELECT content,work_start_at,due_at,status,archived,priority,urgency,percent_complete FROM tasks WHERE id=%s",(mapping["internal_id"],)).fetchone()
            if not r:return None
            complete=r[4] or r[3] in ("done","archived") or r[7]>=100
            return {**mapping,"summary":r[0],"description":"","work_start_at":r[1],"due_at":r[2],"status":"COMPLETED" if complete else "NEEDS-ACTION",
                "priority":r[5],"urgency":r[6],"percent_complete":100 if complete else r[7],"parent_uid":None}
        if mapping["entity_type"]=="list":
            r=c.execute("SELECT title,description,archived FROM lists WHERE id=%s",(mapping["internal_id"],)).fetchone()
            if not r:return None
            return {**mapping,"summary":r[0],"description":r[1],"due_at":None,"status":"COMPLETED" if r[2] else "NEEDS-ACTION",
                "priority":0,"urgency":None,"percent_complete":100 if r[2] else 0,"parent_uid":None}
        r=c.execute("SELECT content,status,archived FROM list_items WHERE id=%s",(mapping["internal_id"],)).fetchone()
        if not r:return None
        parent=c.execute("SELECT uid FROM caldav_sync_entities WHERE public_id=%s",(mapping["parent_public_id"],)).fetchone()
        complete=r[2] or r[1] in ("done","archived")
        return {**mapping,"summary":r[0],"description":"","due_at":None,"status":"COMPLETED" if complete else "NEEDS-ACTION",
            "priority":0,"urgency":None,"percent_complete":100 if complete else 0,"parent_uid":parent[0] if parent else None}


def _archive(mapping,reason,completed=True):
    now=datetime.now(TIMEZONE);kind=mapping["entity_type"];internal=mapping["internal_id"]
    with get_db_connection() as c:
        if kind=="task":c.execute("UPDATE tasks SET status='archived',archived=TRUE,percent_complete=CASE WHEN %s THEN 100 ELSE percent_complete END,archived_at=%s,archive_reason=%s,updated_at=%s WHERE id=%s",(completed,now,reason,now,internal))
        elif kind=="list":
            c.execute("UPDATE lists SET archived=TRUE,archived_at=%s,archive_reason=%s,updated_at=%s WHERE id=%s",(now,reason,now,internal))
            c.execute("UPDATE list_items SET status='archived',archived=TRUE,archived_at=%s,archive_reason=%s,updated_at=%s WHERE list_id=%s AND archived=FALSE",(now,"remote_parent_"+("completed" if completed else "deleted"),now,internal))
        else:c.execute("UPDATE list_items SET status='archived',archived=TRUE,archived_at=%s,archive_reason=%s,updated_at=%s WHERE id=%s",(now,reason,now,internal))
        c.commit()


def _apply_remote(mapping,remote,status_only=False):
    completed=remote["status"]=="COMPLETED" or remote["percent_complete"]>=100
    now=datetime.now(TIMEZONE);kind=mapping["entity_type"];internal=mapping["internal_id"]
    if completed:_archive(mapping,"remote_completed",True)
    with get_db_connection() as c:
        if kind=="task":
            if not completed:
                c.execute("UPDATE tasks SET status='open',archived=FALSE,archived_at=NULL,archive_reason=NULL,percent_complete=%s,updated_at=%s WHERE id=%s",(remote["percent_complete"],now,internal))
            if not status_only:c.execute("""UPDATE tasks SET content=%s,work_start_at=COALESCE(%s,
                CASE WHEN %s IS NOT NULL THEN date_trunc('day',created_at AT TIME ZONE 'Europe/Berlin') AT TIME ZONE 'Europe/Berlin' END),
                due_at=%s,priority=%s,urgency=COALESCE(%s,urgency),embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s""",
                (remote["summary"],remote["work_start_at"],remote["due_at"],remote["due_at"],remote["priority"],remote["urgency"],now,internal))
        elif kind=="list":
            if not completed:
                c.execute("UPDATE lists SET archived=FALSE,archived_at=NULL,archive_reason=NULL,updated_at=%s WHERE id=%s",(now,internal))
                c.execute("UPDATE list_items SET status='active',archived=FALSE,archived_at=NULL,archive_reason=NULL,updated_at=%s WHERE list_id=%s AND archive_reason='remote_parent_completed'",(now,internal))
            if not status_only:c.execute("UPDATE lists SET title=%s,description=%s,embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(remote["summary"],remote["description"],now,internal))
        else:
            if not completed:c.execute("UPDATE list_items SET status='active',archived=FALSE,archived_at=NULL,archive_reason=NULL,updated_at=%s WHERE id=%s",(now,internal))
            if not status_only:
                parent=c.execute("SELECT internal_id FROM caldav_sync_entities WHERE uid=%s AND entity_type='list'",(remote.get("parent_uid"),)).fetchone()
                c.execute("UPDATE list_items SET content=%s,list_id=COALESCE(%s,list_id),embedding=NULL,embedding_model=NULL,updated_at=%s WHERE id=%s",(remote["summary"],parent[0] if parent else None,now,internal))
        c.commit()


def _record_conflict(mapping,local,remote):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        exists=c.execute("SELECT id FROM caldav_sync_conflicts WHERE public_id=%s AND status='open'",(mapping["public_id"],)).fetchone()
        if exists:return exists[0]
        row=c.execute("INSERT INTO caldav_sync_conflicts(public_id,conflict_type,local_snapshot,remote_snapshot,detected_at) VALUES(%s,'concurrent_change',%s,%s,%s) RETURNING id",
            (mapping["public_id"],Jsonb(_public_local(local)),Jsonb(_jsonable_remote(remote)),now)).fetchone();c.commit();return row[0]
def _public_local(local):return {k:(str(v) if isinstance(v,UUID) else v.isoformat() if isinstance(v,datetime) else v) for k,v in local.items() if k not in ("internal_id","remote_hash","local_fingerprint")}
def _audit(public,event,direction,outcome,href=None,etag=None,metadata=None):
    with get_db_connection() as c:c.execute("INSERT INTO caldav_sync_audit(public_id,event_type,direction,outcome,href,etag,metadata,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (public,event,direction,outcome,href,etag,Jsonb(metadata or {}),datetime.now(TIMEZONE)));c.commit()


async def synchronize_caldav(dry_run=False,gateway=None,only_entities=None,profile_key=PROFILE):
    if gateway is None and not _configured():raise CalDAVConfigurationError("Nextcloud CalDAV is not configured")
    lock_connection=get_db_connection()
    acquired=lock_connection.execute("SELECT pg_try_advisory_lock(hashtext('smart_notebook_caldav_sync'))").fetchone()[0]
    if not acquired:
        lock_connection.close();return {"profile":profile_key,"dry_run":dry_run,"outcome":"already_running","actions":[],"action_count":0}
    owned=gateway is None;gateway=gateway or NextcloudCalDAVGateway();started=datetime.now(TIMEZONE)
    try:
        discovered=await gateway.discover();calendar_url=discovered["calendar_url"]
        with get_db_connection() as c:
            state=c.execute("SELECT sync_token FROM caldav_sync_state WHERE profile_key=%s",(profile_key,)).fetchone();token=state[0] if state else None
            c.execute("""INSERT INTO caldav_sync_state(profile_key,calendar_url,sync_token,last_sync_started_at,updated_at)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(profile_key) DO UPDATE SET calendar_url=EXCLUDED.calendar_url,last_sync_started_at=EXCLUDED.last_sync_started_at,updated_at=EXCLUDED.updated_at""",
            (profile_key,calendar_url,token,started,started));c.commit()
        _ensure_mappings(only_entities);batch=await gateway.fetch(calendar_url,token);mappings=_mapping_rows()
        if only_entities is not None:mappings=[x for x in mappings if (x["entity_type"],x["internal_id"]) in only_entities]
        marked={x["public_id"]:x for x in batch["objects"] if x.get("public_id") and x.get("entity_type") in ("task","list","list_item")}
        deleted=set(batch.get("deleted_hrefs") or []);actions=[]
        for mapping in mappings:
            local=_local_entity(mapping);remote=marked.get(mapping["public_id"])
            if remote and (remote["uid"]!=mapping["uid"] or remote["entity_type"]!=mapping["entity_type"]):
                actions.append({"action":"ignore_marker_mismatch","id":str(mapping["public_id"])});continue
            local_fp=_local_fingerprint(local) if local else None
            if remote:
                if local is None:
                    actions.append({"action":"delete_remote_orphan","id":str(mapping["public_id"])})
                    if not dry_run:
                        await gateway.delete(calendar_url,remote["href"],remote["etag"])
                        with get_db_connection() as c:c.execute("UPDATE caldav_sync_entities SET href=NULL,etag=NULL,remote_hash=NULL,sync_state='archived',updated_at=%s WHERE public_id=%s",(datetime.now(TIMEZONE),mapping["public_id"]));c.commit()
                        _audit(mapping["public_id"],"remote_delete_orphan","local_to_remote","applied",remote["href"],remote["etag"])
                    continue
                remote_fp=_remote_fingerprint(remote);remote_changed=mapping["etag"] is not None and remote["etag"]!=mapping["etag"]
                local_changed=mapping["local_fingerprint"] is not None and local_fp!=mapping["local_fingerprint"]
                remote_completed=remote["status"]=="COMPLETED" or remote["percent_complete"]>=100
                # Compatibility cleanup for completions imported before automatic
                # removal was enabled: the local archive is already durable.
                if remote_completed and local["status"]=="COMPLETED" and not remote_changed:
                    actions.append({"action":"delete_remote_completed","id":str(mapping["public_id"])})
                    if not dry_run:
                        await gateway.delete(calendar_url,remote["href"],remote["etag"])
                        with get_db_connection() as c:c.execute("UPDATE caldav_sync_entities SET href=NULL,etag=NULL,remote_hash=NULL,sync_state='archived',last_synced_at=%s,updated_at=%s WHERE public_id=%s",(datetime.now(TIMEZONE),datetime.now(TIMEZONE),mapping["public_id"]));c.commit()
                        _audit(mapping["public_id"],"remote_completed_cleanup","local_to_remote","applied",remote["href"],remote["etag"])
                    continue
                if remote_changed and local_changed:
                    actions.append({"action":"conflict","id":str(mapping["public_id"])})
                    if not dry_run:
                        _apply_remote(mapping,remote,True);local=_local_entity(mapping);local_fp=_local_fingerprint(local);_record_conflict(mapping,local,remote)
                        with get_db_connection() as c:c.execute("UPDATE caldav_sync_entities SET href=%s,etag=%s,remote_hash=%s,local_fingerprint=%s,updated_at=%s WHERE public_id=%s",(remote["href"],remote["etag"],remote_fp,local_fp,datetime.now(TIMEZONE),mapping["public_id"]));c.commit()
                        _audit(mapping["public_id"],"concurrent_change","system","conflict",remote["href"],remote["etag"])
                elif remote_changed or mapping["etag"] is None:
                    actions.append({"action":"apply_remote","id":str(mapping["public_id"])})
                    if not dry_run:
                        _apply_remote(mapping,remote);local=_local_entity(mapping);local_fp=_local_fingerprint(local)
                        remote_completed=remote["status"]=="COMPLETED" or remote["percent_complete"]>=100
                        if remote_completed:
                            await gateway.delete(calendar_url,remote["href"],remote["etag"])
                            actions.append({"action":"delete_remote_completed","id":str(mapping["public_id"])})
                        with get_db_connection() as c:c.execute("UPDATE caldav_sync_entities SET href=%s,etag=%s,remote_hash=%s,local_fingerprint=%s,sync_state=%s,last_synced_at=%s,updated_at=%s WHERE public_id=%s",(None if remote_completed else remote["href"],None if remote_completed else remote["etag"],None if remote_completed else remote_fp,local_fp,"archived" if remote_completed else "active",datetime.now(TIMEZONE),datetime.now(TIMEZONE),mapping["public_id"]));c.commit()
                        _audit(mapping["public_id"],"remote_update","remote_to_local","applied",remote["href"],remote["etag"])
                        if remote_completed:_audit(mapping["public_id"],"remote_completed_cleanup","local_to_remote","applied",remote["href"],remote["etag"])
                elif local_changed:
                    actions.append({"action":"push_local","id":str(mapping["public_id"])})
                    if not dry_run:
                        result=await gateway.put(calendar_url,local,mapping["href"],mapping["etag"]);_save_push(mapping,local,result)
            elif mapping["href"] and not batch.get("complete") and mapping["href"] not in deleted:
                # An incremental REPORT omits unchanged remote objects. It is not a
                # deletion signal. A locally durable completion is the exception:
                # its known href can be removed without receiving the object again.
                if local and local["status"]=="COMPLETED" and mapping["sync_state"]=="archived":
                    actions.append({"action":"delete_remote_completed","id":str(mapping["public_id"])})
                    if not dry_run:
                        await gateway.delete(calendar_url,mapping["href"],mapping["etag"])
                        with get_db_connection() as c:c.execute("UPDATE caldav_sync_entities SET href=NULL,etag=NULL,remote_hash=NULL,last_synced_at=%s,updated_at=%s WHERE public_id=%s",(datetime.now(TIMEZONE),datetime.now(TIMEZONE),mapping["public_id"]));c.commit()
                        _audit(mapping["public_id"],"remote_completed_cleanup","local_to_remote","applied",mapping["href"],mapping["etag"])
                elif local and local_fp!=mapping["local_fingerprint"]:
                    actions.append({"action":"push_local","id":str(mapping["public_id"])})
                    if not dry_run:
                        result=await gateway.put(calendar_url,local,mapping["href"],mapping["etag"]);_save_push(mapping,local,result)
            elif mapping["href"] and (batch.get("complete") or mapping["href"] in deleted):
                if mapping["sync_state"]!="remote_deleted":
                    actions.append({"action":"archive_remote_deleted","id":str(mapping["public_id"])})
                    if not dry_run:
                        _archive(mapping,"remote_deleted",False);local=_local_entity(mapping)
                        with get_db_connection() as c:c.execute("UPDATE caldav_sync_entities SET etag=NULL,remote_hash=NULL,local_fingerprint=%s,sync_state='remote_deleted',last_synced_at=%s,updated_at=%s WHERE public_id=%s",(_local_fingerprint(local),datetime.now(TIMEZONE),datetime.now(TIMEZONE),mapping["public_id"]));c.commit()
                        _audit(mapping["public_id"],"remote_delete","remote_to_local","applied",mapping["href"])
                elif local and local["status"]!="COMPLETED":
                    actions.append({"action":"recreate_remote","id":str(mapping["public_id"])})
                    if not dry_run:
                        result=await gateway.put(calendar_url,local,None,None);_save_push(mapping,local,result)
            elif local and local["status"]!="COMPLETED":
                actions.append({"action":"create_remote","id":str(mapping["public_id"])})
                if not dry_run:
                    result=await gateway.put(calendar_url,local,None,None);_save_push(mapping,local,result)
        completed=datetime.now(TIMEZONE)
        if not dry_run:
            with get_db_connection() as c:c.execute("""UPDATE caldav_sync_state SET calendar_url=%s,sync_token=%s,last_sync_completed_at=%s,last_outcome='success',last_error_type=NULL,updated_at=%s WHERE profile_key=%s""",
                (calendar_url,batch.get("sync_token"),completed,completed,profile_key));c.commit()
        return {"profile":profile_key,"dry_run":dry_run,"calendar_url":calendar_url,"ignored_unmarked":len([x for x in batch["objects"] if not x.get("public_id")]),
            "actions":actions,"action_count":len(actions),"sync_token":batch.get("sync_token")}
    except Exception as exc:
        with get_db_connection() as c:c.execute("""INSERT INTO caldav_sync_state(profile_key,last_sync_started_at,last_outcome,last_error_type,updated_at)
        VALUES(%s,%s,'failed',%s,%s) ON CONFLICT(profile_key) DO UPDATE SET last_outcome='failed',last_error_type=EXCLUDED.last_error_type,updated_at=EXCLUDED.updated_at""",
        (profile_key,started,type(exc).__name__,datetime.now(TIMEZONE)));c.commit()
        raise
    finally:
        if owned:await gateway.close()
        lock_connection.execute("SELECT pg_advisory_unlock(hashtext('smart_notebook_caldav_sync'))")
        lock_connection.close()


def _save_push(mapping,local,result):
    now=datetime.now(TIMEZONE);fingerprint=_local_fingerprint(local)
    with get_db_connection() as c:c.execute("""UPDATE caldav_sync_entities SET href=%s,etag=%s,remote_hash=%s,local_fingerprint=%s,
    sync_state=%s,last_synced_at=%s,updated_at=%s WHERE public_id=%s""",(result["href"],result.get("etag"),_hash(serialize_vtodo(local)),fingerprint,
        "archived" if local["status"]=="COMPLETED" else "active",now,now,mapping["public_id"]));c.commit()
    _audit(mapping["public_id"],"remote_put","local_to_remote","applied",result["href"],result.get("etag"))


def caldav_status():
    with get_db_connection() as c:
        state=c.execute("SELECT calendar_url,sync_token,last_sync_started_at,last_sync_completed_at,last_outcome,last_error_type FROM caldav_sync_state WHERE profile_key=%s",(PROFILE,)).fetchone()
        counts=c.execute("SELECT count(*),count(*) FILTER(WHERE sync_state='active'),count(*) FILTER(WHERE sync_state='remote_deleted') FROM caldav_sync_entities").fetchone()
        conflicts=c.execute("SELECT count(*) FROM caldav_sync_conflicts WHERE status='open'").fetchone()[0]
    return {"configured":_configured(),"profile":PROFILE,"server_url":NEXTCLOUD_URL or None,"username":NEXTCLOUD_USERNAME or None,
        "calendar":NEXTCLOUD_TASK_CALENDAR,"credentials_present":bool(NEXTCLOUD_APP_PASSWORD),"calendar_url":state[0] if state else None,
        "sync_token_present":bool(state and state[1]),"last_sync_started_at":state[2].isoformat() if state and state[2] else None,
        "last_sync_completed_at":state[3].isoformat() if state and state[3] else None,"last_outcome":state[4] if state else None,
        "last_error_type":state[5] if state else None,"entities":{"total":counts[0],"active":counts[1],"remote_deleted":counts[2]},"open_conflicts":conflicts}


def list_conflicts():
    with get_db_connection() as c:rows=c.execute("SELECT id,public_id,conflict_type,local_snapshot,remote_snapshot,status,resolution,detected_at,resolved_at FROM caldav_sync_conflicts ORDER BY detected_at DESC").fetchall()
    return [{"id":r[0],"public_id":str(r[1]),"conflict_type":r[2],"local":r[3],"remote":r[4],"status":r[5],"resolution":r[6],"detected_at":r[7].isoformat(),"resolved_at":r[8].isoformat() if r[8] else None} for r in rows]


def resolve_conflict(conflict_id,resolution):
    if resolution not in ("keep_local","keep_remote"):raise ValueError("resolution must be keep_local or keep_remote")
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("SELECT public_id,remote_snapshot,status FROM caldav_sync_conflicts WHERE id=%s FOR UPDATE",(conflict_id,)).fetchone()
        if not row:return None
        if row[2]=="resolved":return next(x for x in list_conflicts() if x["id"]==conflict_id)
        mapping=next(x for x in _mapping_rows() if x["public_id"]==row[0])
        if resolution=="keep_remote":
            remote=dict(row[1]);remote["public_id"]=UUID(remote["public_id"])
            if remote.get("due_at"):
                try:remote["due_at"]=datetime.fromisoformat(remote["due_at"])
                except ValueError:remote["due_at"]=_parse_time(remote["due_at"])
            _apply_remote(mapping,remote)
            local_fp=_local_fingerprint(_local_entity(mapping));c.execute("UPDATE caldav_sync_entities SET local_fingerprint=%s WHERE public_id=%s",(local_fp,row[0]))
        else:c.execute("UPDATE caldav_sync_entities SET local_fingerprint='' WHERE public_id=%s",(row[0],))
        c.execute("UPDATE caldav_sync_conflicts SET status='resolved',resolution=%s,resolved_at=%s WHERE id=%s",(resolution,now,conflict_id));c.commit()
    return next(x for x in list_conflicts() if x["id"]==conflict_id)
