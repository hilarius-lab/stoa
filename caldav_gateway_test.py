"""Nextcloud WebDAV wire contract using an in-memory HTTP transport."""
import asyncio
from datetime import datetime,timezone
from uuid import uuid4

import httpx

from smart_notebook.services.caldav_sync import NextcloudCalDAVGateway,parse_vtodo


def multistatus(body):return httpx.Response(207,headers={"content-type":"application/xml"},content=body)


async def scenario():
    calls=[];public=uuid4();uid=f"smart-notebook-{public}@local"
    def handler(request):
        content=request.content.decode();calls.append((request.method,request.url.path,dict(request.headers),content))
        if request.method=="PROPFIND" and request.url.path=="/.well-known/caldav":
            return multistatus(b'''<d:multistatus xmlns:d="DAV:"><d:response><d:href>/remote.php/dav/principals/users/test/</d:href><d:propstat><d:prop><d:current-user-principal><d:href>/remote.php/dav/principals/users/test/</d:href></d:current-user-principal></d:prop></d:propstat></d:response></d:multistatus>''')
        if request.method=="PROPFIND" and request.url.path=="/remote.php/dav/principals/users/test/":
            return multistatus(b'''<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/remote.php/dav/principals/users/test/</d:href><d:propstat><d:prop><c:calendar-home-set><d:href>/remote.php/dav/calendars/test/</d:href></c:calendar-home-set></d:prop></d:propstat></d:response></d:multistatus>''')
        if request.method=="PROPFIND" and request.url.path=="/remote.php/dav/calendars/test/":
            return multistatus(b'''<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/remote.php/dav/calendars/test/notizbuch/</d:href><d:propstat><d:prop><d:displayname>notizbuch</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype><c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set><d:sync-token>token-1</d:sync-token></d:prop></d:propstat></d:response></d:multistatus>''')
        if request.method=="REPORT" and "calendar-query" in content:
            ics="BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:manual\r\nSUMMARY:Unmarkiert\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
            xml=f'''<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/remote.php/dav/calendars/test/notizbuch/manual.ics</d:href><d:propstat><d:prop><d:getetag>"m1"</d:getetag><c:calendar-data>{ics}</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>'''
            return multistatus(xml.encode())
        if request.method=="PROPFIND" and request.url.path=="/remote.php/dav/calendars/test/notizbuch/":
            return multistatus(b'''<d:multistatus xmlns:d="DAV:"><d:response><d:href>/remote.php/dav/calendars/test/notizbuch/</d:href><d:propstat><d:prop><d:sync-token>token-1</d:sync-token></d:prop></d:propstat></d:response></d:multistatus>''')
        if request.method=="REPORT" and "sync-collection" in content:
            assert "token-1" in content
            return multistatus(b'''<d:multistatus xmlns:d="DAV:"><d:sync-token>token-2</d:sync-token><d:response><d:href>/remote.php/dav/calendars/test/notizbuch/gone.ics</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response></d:multistatus>''')
        if request.method=="PUT":
            assert request.headers["content-type"].startswith("text/calendar") and request.headers["if-none-match"]=="*"
            parsed=parse_vtodo(content);assert parsed["public_id"]==public and parsed["entity_type"]=="task"
            assert parsed["work_start_at"] is not None
            return httpx.Response(201,headers={"etag":'"created-1"'})
        raise AssertionError((request.method,str(request.url),content))

    gateway=NextcloudCalDAVGateway("https://nextcloud.test/apps/tasks/calendars/notizbuch","test","app-password","notizbuch",httpx.MockTransport(handler))
    try:
        discovered=await gateway.discover();assert discovered["calendar_url"]=="https://nextcloud.test/remote.php/dav/calendars/test/notizbuch/"
        full=await gateway.fetch(discovered["calendar_url"]);assert full["complete"] and len(full["objects"])==1 and full["sync_token"]=="token-1"
        entity={"public_id":public,"uid":uid,"entity_type":"task","summary":"Wire-Test","description":"","status":"NEEDS-ACTION",
            "percent_complete":0,"priority":5,"urgency":.4,"work_start_at":datetime(2026,9,8,8,tzinfo=timezone.utc),"due_at":None,"parent_uid":None}
        stored=await gateway.put(discovered["calendar_url"],entity);assert stored["etag"]=='"created-1"' and stored["href"].endswith(".ics")
        delta=await gateway.fetch(discovered["calendar_url"],"token-1")
        assert not delta["complete"] and delta["sync_token"]=="token-2" and delta["deleted_hrefs"]==["/remote.php/dav/calendars/test/notizbuch/gone.ics"]
    finally:await gateway.close()
    assert any(x[0]=="PROPFIND" for x in calls) and any(x[0]=="REPORT" for x in calls) and any(x[0]=="PUT" for x in calls)


def main():asyncio.run(scenario());print("CALDAV NEXTCLOUD GATEWAY TEST: PASS")
if __name__=="__main__":main()
