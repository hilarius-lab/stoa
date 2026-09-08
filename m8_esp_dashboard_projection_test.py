"""Verify the ESP dashboard surface without exposing task/list write APIs."""
from datetime import datetime,timedelta
from unittest.mock import AsyncMock,patch
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS,EMBEDDING_DIMENSIONS,TIMEZONE
from smart_notebook.database import get_db_connection,init_db
from smart_notebook.services.client_dashboard import (ESP_DROP_KEYS,ESP_ITEMS_PER_SECTION,
    ESP_PREVIEW_MAX,ESP_RENDERED_COMPONENTS,ESP_SURFACE,ESP_TASK_ITEMS_PER_SECTION,ESP_TITLE_MAX,
    _idle_content,_project_for_epaper,get_dashboard_entity)
from smart_notebook.routers.client import _capabilities

# The receive buffer the device shipped with when the surface first overflowed.
# The firmware has since been given twice that, and this bound stays at the old
# value on purpose: it is the budget the projection is supposed to respect, and
# the headroom on the device is insurance, not an allowance to spend.
ESP_RESPONSE_BUDGET_BYTES=8192
# Every key esp32-client/main/dashboard.c reads off an entity_card. If one of
# these stops being sent the panel keeps drawing, just wrong — an icon becomes
# generic, an urgent card loses its strip. That is the failure this list exists
# to make loud.
ESP_RENDERED_KEYS=("component","title","preview","status","icon","color_role","border_role","entity_ref")


def check_epaper_projection():
    """The e-paper response must fit the device and keep what it renders.

    Measured on the wire, not on the snapshot dict. Those two are not the same
    number and the difference is not small: Pydantic writes every optional field
    of DashboardComponent out as null, which once turned a 5353 byte snapshot
    into 9277 bytes of JSON. A guard that weighs the dict weighs the wrong thing
    and passes while the device chokes.
    """
    client=TestClient(app)
    response=client.get("/api/client/v1/dashboard",params={"surface":ESP_SURFACE})
    assert response.status_code==200,response.text
    encoded=response.content
    assert len(encoded)<ESP_RESPONSE_BUDGET_BYTES,(
        f"the esp32_epaper response is {len(encoded)} bytes against a "
        f"{ESP_RESPONSE_BUDGET_BYTES} byte budget; the device shows nothing at all "
        f"when the response outgrows its buffer, and answers 200 while doing it")
    snapshot=response.json()
    assert snapshot["schema_version"]=="1" and snapshot["scope"]==f"home:{ESP_SURFACE}"
    # The envelope keeps its nullable fields even where they are null: absent and
    # null are different statements in the contract, and only the components are
    # allowed to leave theirs out.
    assert "primary_live_session" in snapshot and "sessions" in snapshot
    for section in snapshot["sections"]:
        assert section.get("id") not in ("recent-knowledge","topic-trends","open-chats","active-sessions")
        items=section.get("items") or []
        assert items,"the e-paper projection must not leave empty section headings"
        item_limit=ESP_TASK_ITEMS_PER_SECTION if section.get("id")=="today" else ESP_ITEMS_PER_SECTION
        assert len(items)<=item_limit,f"{section.get('id')} carries {len(items)} items"
        for item in items:
            assert item["component"] in ESP_RENDERED_COMPONENTS,item
            assert not set(item)&set(ESP_DROP_KEYS),f"unrendered keys survived: {set(item)&set(ESP_DROP_KEYS)}"
            assert len(item.get("title") or "")<=ESP_TITLE_MAX
            assert len(item.get("preview") or "")<=ESP_PREVIEW_MAX
            if item["component"]=="entity_card":
                missing=[key for key in ESP_RENDERED_KEYS if key not in item]
                assert not missing,f"the renderer reads {missing} and they were dropped"
                # Focus identity and the action verb are contract, not decoration:
                # the firmware holds focus by id and will need open_clarification
                # told apart from open_entity.
                assert item.get("id") and item.get("action",{}).get("type")
    # The projection is for one surface only. The default surface, which the
    # Android client consumes, must still carry its nulls and its full component
    # vocabulary — this is the check that keeps the e-paper work from leaking.
    default=client.get("/api/client/v1/dashboard").json()
    assert default["scope"]=="home:default"
    for section in default["sections"]:
        assert "reason_code" in section and "rank" in section,(
            "the default surface lost fields to the e-paper projection")
    return len(encoded)


def main():
    init_db()
    capabilities=_capabilities();icons=capabilities["dashboard"]["icon_tokens"]
    assert {"generic","task","list","warning","recording"}<=set(icons)
    limits=capabilities["limits"]
    assert limits["dashboard_title_max_chars"]==100
    assert limits["dashboard_preview_max_chars"]==240
    assert limits["dashboard_detail_max_chars"]==8000
    assert limits["dashboard_cache_max_age_seconds"]==CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS
    token=uuid4().hex
    now=datetime.now(TIMEZONE);task_id=list_id=item_id=other_task_id=future_low_id=future_moderate_id=None
    try:
        with get_db_connection() as db:
            task_id=db.execute("""INSERT INTO tasks(content,created_at,updated_at,work_start_at,due_at,status,archived,priority,urgency,percent_complete,urgency_source)
                VALUES(%s,%s,%s,%s,%s,'open',FALSE,3,.8,0,'manual') RETURNING id""",
                (f"ESP today {token}",now,now,now.replace(hour=0,minute=0,second=0,microsecond=0),now+timedelta(hours=1))).fetchone()[0]
            future_low_id=db.execute("""INSERT INTO tasks(content,created_at,updated_at,work_start_at,due_at,status,archived,priority,urgency,percent_complete,urgency_source)
                VALUES(%s,%s,%s,%s,%s,'open',FALSE,1,.4,0,'policy_default') RETURNING id""",
                (f"ESP future low {token}",now,now,now+timedelta(days=2),now+timedelta(days=3))).fetchone()[0]
            future_moderate_id=db.execute("""INSERT INTO tasks(content,created_at,updated_at,work_start_at,due_at,status,archived,priority,urgency,percent_complete,urgency_source)
                VALUES(%s,%s,%s,%s,%s,'open',FALSE,1,.5,0,'manual') RETURNING id""",
                (f"ESP future moderate {token}",now,now,now+timedelta(days=2),now+timedelta(days=3))).fetchone()[0]
            list_id=db.execute("INSERT INTO lists(title,description,created_at,updated_at,archived) VALUES(%s,%s,%s,%s,FALSE) RETURNING id",
                (f"ESP list {token}","Projection test",now,now)).fetchone()[0]
            item_id=db.execute("INSERT INTO list_items(list_id,content,created_at,updated_at,status,archived) VALUES(%s,%s,%s,%s,'active',FALSE) RETURNING id",
                (list_id,f"ESP item {token}",now,now)).fetchone()[0];db.commit()

        default=_idle_content();assert all(x["id"] not in ("today","lists") for x in default["sections"])
        esp=_idle_content("esp32_epaper");sections={x["id"]:x for x in esp["sections"]}
        assert any(token in x["title"] for x in sections["today"]["items"])
        assert not any(f"future low {token}" in x["title"] for x in sections["today"]["items"])
        assert any(f"future moderate {token}" in x["title"] for x in sections["today"]["items"])
        projected_tasks=next(x for x in _project_for_epaper(esp)["sections"] if x["id"]=="today")
        assert any(f"future moderate {token}" in x["title"] for x in projected_tasks["items"])
        assert any(token in x["title"] for x in sections["lists"]["items"])
        task=next(x for x in sections["today"]["items"] if token in x["title"])
        assert task["preview"].startswith("Ab heute · bis "),task
        listing=next(x for x in sections["lists"]["items"] if token in x["title"])
        assert listing["status"]=="1 offen",listing
        assert task["id"]==f"task:{task['entity_ref']['id']}"
        assert listing["id"]==f"list:{listing['entity_ref']['id']}"
        # Focus identity is an API guarantee: a changed snapshot or ordering
        # must preserve both the opaque card id and persistent entity_ref.
        original_identity=(task["id"],task["entity_ref"])
        with get_db_connection() as db:
            other_task_id=db.execute("""INSERT INTO tasks(content,created_at,updated_at,work_start_at,due_at,status,archived,priority,urgency,percent_complete,urgency_source)
                VALUES(%s,%s,%s,%s,%s,'open',FALSE,1,1,0,'manual') RETURNING id""",
                (f"ESP reorder {token}",now,now,now,now+timedelta(minutes=1))).fetchone()[0]
            db.commit()
        later=_idle_content("esp32_epaper");later_task=next(
            x for section in later["sections"] for x in section["items"]
            if x.get("title","")==f"ESP today {token}"
        )
        assert (later_task["id"],later_task["entity_ref"])==original_identity
        detail=get_dashboard_entity("task",task["entity_ref"]["id"])
        assert detail["type"]=="task" and detail["work_start_at"] is not None
        list_detail=get_dashboard_entity("list",listing["entity_ref"]["id"])
        assert list_detail["items"][0]["content"].endswith(token)
        item_public_id=list_detail["items"][0]["id"]
        assert list_detail["items"][0]["status"]=="active"
        assert list_detail["content"]==f"• ESP item {token}" and list_detail["status"]=="1 offen",list_detail
        # One idempotent desired-state operation backs the ESP's durable local
        # action queue. A completed item is omitted from the next list detail;
        # setting the same status again remains a success, so retries after a
        # lost response cannot turn a completed action into an error.
        with patch("smart_notebook.services.lists.get_embedding",AsyncMock(return_value=[0.0]*EMBEDDING_DIMENSIONS)):
            completed=TestClient(app).put(
                f"/api/client/v1/entities/list-item/{item_public_id}/status",
                json={"status":"done"})
            assert completed.status_code==200,completed.text
            assert completed.json()["id"]==item_public_id and completed.json()["status"]=="done"
            repeated=TestClient(app).put(
                f"/api/client/v1/entities/list-item/{item_public_id}/status",
                json={"status":"done"})
            assert repeated.status_code==200,repeated.text
            assert get_dashboard_entity("list",listing["entity_ref"]["id"])["items"]==[]
            reopened=TestClient(app).put(
                f"/api/client/v1/entities/list-item/{item_public_id}/status",
                json={"status":"active"})
            assert reopened.status_code==200,reopened.text
            assert reopened.json()["status"]=="active"
        # The e-paper walker ignores every non-card component. The projection
        # must remove both those items and their headings instead of producing
        # the visually empty "Systemhinweise"/"Neue Eingabe" sections seen on
        # the real panel. Session cards belong to the recording history.
        sparse=_project_for_epaper({"sessions":[],"sections":[
            {"id":"system-attention","title":"Systemhinweise","items":[{"component":"alert","title":"Warnung"}]},
            {"id":"active-sessions","title":"Offene Sessions","items":[{"component":"entity_card","title":"processing"}]},
            {"id":"capture","title":"Neue Eingabe","items":[{"component":"input_prompt","title":"Memo"}]},
        ]})
        assert sparse["sections"]==[],sparse
        size=check_epaper_projection()
        print(f"M8 ESP DASHBOARD PROJECTION TEST: PASS (esp32_epaper snapshot {size} bytes "
              f"of {ESP_RESPONSE_BUDGET_BYTES})")
    finally:
        with get_db_connection() as db:
            if task_id is not None:db.execute("DELETE FROM client_entity_identities WHERE entity_type='task' AND internal_id=%s",(task_id,))
            if list_id is not None:db.execute("DELETE FROM client_entity_identities WHERE entity_type='list' AND internal_id=%s",(list_id,))
            if item_id is not None:db.execute("DELETE FROM client_entity_identities WHERE entity_type='list_item' AND internal_id=%s",(item_id,))
            if item_id is not None:db.execute("DELETE FROM list_items WHERE id=%s",(item_id,))
            if list_id is not None:db.execute("DELETE FROM lists WHERE id=%s",(list_id,))
            if other_task_id is not None:
                db.execute("DELETE FROM client_entity_identities WHERE entity_type='task' AND internal_id=%s",(other_task_id,))
                db.execute("DELETE FROM tasks WHERE id=%s",(other_task_id,))
            for extra_task_id in (future_low_id,future_moderate_id):
                if extra_task_id is not None:
                    db.execute("DELETE FROM client_entity_identities WHERE entity_type='task' AND internal_id=%s",(extra_task_id,))
                    db.execute("DELETE FROM tasks WHERE id=%s",(extra_task_id,))
            if task_id is not None:db.execute("DELETE FROM tasks WHERE id=%s",(task_id,))
            db.commit()


if __name__=="__main__":main()
