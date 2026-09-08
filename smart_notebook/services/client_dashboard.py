import hashlib,json
from datetime import datetime,timedelta
from uuid import uuid4

from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from .client_sessions import completion_status,get_client_session,list_client_sessions,reconciliation
from .knowledge_sync import refresh_sync_index

TITLE_MAX=100
PREVIEW_MAX=240
DETAIL_MAX=8000

# --- e-paper projection ------------------------------------------------------
#
# The ESP receives the same envelope as every other client, but a much smaller
# one. Measured on 6 September the unprojected surface was 28086 bytes against a
# device receive buffer of 8192, so the panel stayed blank: the server answered
# 200 and the client aborted mid-transfer. The surface that lands on the
# smallest device was in fact the largest the server produced, because
# `_idle_content` used to *add* the task and list sections for it without
# reducing anything.
#
# Three levers are applied here, in order of how safe they are.
ESP_SURFACE="esp32_epaper"
# 1. Fields the e-paper renderer never reads. Checked against the actual walker
#    in esp32-client/main/dashboard.c, which consumes exactly `component`,
#    `title`, `preview`, `status`, `icon`, `severity`, `color_role`,
#    `border_role`, `action.type` and `entity_ref`. `BACKEND_REQUIREMENTS.md`
#    additionally declares `layout`, `preferred_span` and `spacing_role`
#    ignored on this surface. Every key below is optional in
#    DashboardComponent, so dropping it is not a contract change.
#    `id` and `action` are deliberately kept: `id` is the stable focus identity
#    the contract guarantees, and `action` carries the distinction between
#    open_entity and open_clarification/open_session that the firmware will
#    need once it acts on more than entities.
ESP_DROP_KEYS=("entity_type","spacing_role","preferred_span","priority","layout",
               "rank","reason_code","reason_text")
# 2. Sections the device has no useful compact interaction or browser for.
#    Chat, knowledge history and topic browsing stay off this surface. Active
#    sessions already live in the paginated recording history; their home cards
#    only repeated technical state tokens and opened a mostly empty view.
#    This is the one product judgement in this file and the easiest thing to
#    revert: put an id back and it reappears.
ESP_DROP_SECTIONS=("recent-knowledge","topic-trends","open-chats","active-sessions")
# dashboard.c currently lays out entity cards only. Sending alerts, status
# banners, text blocks or input prompts produces an empty section heading, not
# a degraded rendering. Filter those components server-side and remove their
# now-empty section so the panel never claims there is content it cannot show.
ESP_RENDERED_COMPONENTS=("entity_card",)
# 3. Counts and lengths. General sections stay at a handful of cards with a
#    two-line preview. The dedicated Tasks view scrolls and must not silently
#    drop an actionable task merely because three others sort ahead of it, so
#    that one section may use the full ten rows already selected by the query.
#    Sending less than `limits` announces is allowed — they are maxima.
ESP_ITEMS_PER_SECTION=3
ESP_TASK_ITEMS_PER_SECTION=10
ESP_TITLE_MAX=80
ESP_PREVIEW_MAX=120
ESP_SESSIONS_MAX=6
ESP_TASK_MODERATE_URGENCY=.5

def _clip(value,limit):return value[:limit] if isinstance(value,str) else value


def _task_time_text(value,now,include_midnight=True):
    local=value.astimezone(TIMEZONE);today=now.astimezone(TIMEZONE).date()
    clock=local.strftime("%H:%M")
    suffix="" if not include_midnight and clock=="00:00" else f", {clock}"
    if local.date()==today:return clock if include_midnight else "heute"+suffix
    if local.date()==today+timedelta(days=1):return "morgen"+suffix
    return local.strftime("%d.%m.")+suffix


def _task_window_preview(work_start_at,due_at,urgency,now):
    if work_start_at:
        start=f"Ab {_task_time_text(work_start_at,now,include_midnight=False)}"
    else:
        start="Moderate Dringlichkeit" if urgency is not None and urgency>=ESP_TASK_MODERATE_URGENCY else "Noch nicht begonnen"
    end=f"bis {_task_time_text(due_at,now)}" if due_at else "ohne Frist"
    return f"{start} · {end}"


def _project_component(item):
    """One component, reduced to what the e-paper client actually renders."""
    result={key:value for key,value in item.items() if key not in ESP_DROP_KEYS}
    result["title"]=_clip(result.get("title"),ESP_TITLE_MAX)
    result["preview"]=_clip(result.get("preview"),ESP_PREVIEW_MAX)
    result["text"]=_clip(result.get("text"),ESP_PREVIEW_MAX)
    # A key that was absent stays absent: `None` would claim the server has no
    # title for a card, which is a different statement from not carrying one.
    for key in ("title","preview","text"):
        if result[key] is None and key not in item:del result[key]
    if isinstance(result.get("items"),list):
        item_limit=ESP_TASK_ITEMS_PER_SECTION if item.get("id")=="today" else ESP_ITEMS_PER_SECTION
        visible=[child for child in result["items"] if child.get("component") in ESP_RENDERED_COMPONENTS]
        result["items"]=[_project_component(child) for child in visible[:item_limit]]
    return result


def _project_for_epaper(content):
    """Shrink a finished snapshot body to what the 480x800 panel can show.

    Applied after the content is built and before it is hashed, so the cached
    revision belongs to the projected surface rather than to a payload the
    device never receives.
    """
    sections=[]
    for section in content["sections"]:
        if section.get("id") in ESP_DROP_SECTIONS:continue
        projected=_project_component(section)
        if projected.get("items"):sections.append(projected)
    return {**content,"sections":sections,"sessions":content["sessions"][:ESP_SESSIONS_MAX]}

def _card(kind,entity_id,title,preview,status="active",priority=.5,icon=None,action=None,ref_type=None):
    reference_type=ref_type or kind
    return {"component":"entity_card","required":False,"id":f"{reference_type}:{entity_id}","entity_ref":{"type":reference_type,"id":str(entity_id)},
            "entity_type":kind,"status":status,"title":_clip(title,TITLE_MAX),"preview":_clip(preview,PREVIEW_MAX),"icon":icon or kind,
            "color_role":"neutral","border_role":"subtle","spacing_role":"normal","preferred_span":"auto",
            "priority":priority,"action":action or {"type":"open_entity","params":{"entity_type":reference_type,"entity_id":str(entity_id)}}}


def _section(section_id,title,reason,cards,rank):
    return {"component":"section","required":False,"id":section_id,"title":title,"reason_code":reason,
            "reason_text":title,"rank":rank,"layout":{"preferred_span":"full"},"items":cards[:10]}


def _ensure_identities(c,entity_type,table,where="TRUE",params=()):
    rows=c.execute(f"SELECT id FROM {table} WHERE {where}",params).fetchall()
    for row in rows:c.execute("INSERT INTO client_entity_identities(public_id,entity_type,internal_id,created_at) VALUES(%s,%s,%s,%s) ON CONFLICT(entity_type,internal_id) DO NOTHING",(uuid4(),entity_type,row[0],datetime.now(TIMEZONE)))


def _live_content(item):
    ingestion_id=item["ingestion_session_id"]
    rec=reconciliation(item["client_session_id"])
    refresh_sync_index()
    with get_db_connection() as c:
        _ensure_identities(c,"session_artifact","session_artifacts","session_id=%s",(ingestion_id,))
        _ensure_identities(c,"session_topic","session_topics","session_id=%s",(ingestion_id,))
        _ensure_identities(c,"question","session_questions","session_id=%s",(ingestion_id,));c.commit()
        maximum=c.execute("SELECT max(source_end_ms) FROM transcript_segments WHERE session_id=%s AND status IN('confirmed','provisional')",(ingestion_id,)).fetchone()[0] or 0
        transcripts=c.execute("""SELECT id,text,status,source_start_ms,source_end_ms FROM transcript_segments
        WHERE session_id=%s AND status IN('confirmed','provisional') AND source_end_ms>=%s
        ORDER BY source_start_ms DESC,id DESC LIMIT 50""",(ingestion_id,max(0,maximum-600000))).fetchall()[::-1]
        artifacts=c.execute("""SELECT i.public_id,a.artifact_type,a.content,a.status,a.confidence FROM session_artifacts a JOIN client_entity_identities i ON i.entity_type='session_artifact' AND i.internal_id=a.id
        WHERE a.session_id=%s AND a.status IN('active','confirmed') AND a.artifact_type IN('note','fact','decision') ORDER BY a.confidence DESC,a.updated_at DESC LIMIT 10""",(ingestion_id,)).fetchall()
        questions=c.execute("""SELECT i.public_id,q.question_text,q.status,q.priority FROM session_questions q JOIN client_entity_identities i ON i.entity_type='question' AND i.internal_id=q.id
        WHERE q.session_id=%s AND q.status IN('open','answered') ORDER BY q.priority DESC,q.updated_at DESC LIMIT 10""",(ingestion_id,)).fetchall()
        topics=c.execute("""SELECT i.public_id,t.title,t.confidence FROM session_topics t JOIN client_entity_identities i ON i.entity_type='session_topic' AND i.internal_id=t.id
        WHERE t.session_id=%s AND t.status='active' ORDER BY t.confidence DESC,t.updated_at DESC LIMIT 10""",(ingestion_id,)).fetchall()
        relevant=c.execute("""SELECT DISTINCT e.public_id,e.entity_type,CASE WHEN e.entity_type='note' THEN n.content ELSE cl.statement END content,
        l.confidence FROM session_topics st JOIN knowledge_topics kt ON kt.normalized_key=st.normalized_key
        JOIN knowledge_topic_links l ON l.topic_id=kt.id JOIN client_knowledge_entities e ON e.entity_type=l.knowledge_type AND e.internal_id=l.knowledge_id
        LEFT JOIN notes n ON e.entity_type='note' AND n.id=e.internal_id LEFT JOIN claims cl ON e.entity_type='fact' AND cl.id=e.internal_id
        WHERE st.session_id=%s AND st.status='active' AND e.state='active' AND e.entity_type IN('note','fact')
        ORDER BY l.confidence DESC LIMIT 10""",(ingestion_id,)).fetchall()
        watermark_row=c.execute("SELECT received_through_sequence,queued_through_sequence,processed_through_sequence,artifact_through_sequence FROM ingestion_session_watermarks WHERE session_id=%s",(ingestion_id,)).fetchone()
    status=completion_status(item["client_session_id"])
    status_item={"component":"status_banner","required":True,"id":"session-status","status":status,
                 "title":f"Session {item['state']}","text":f"Empfangen: {len(rec['received_sequences'])}; fehlend: {len(rec['missing_sequences'])}",
                 "icon":"recording" if item["state"]=="recording" else "session","color_role":"recording" if item["state"]=="recording" else "info"}
    transcript_items=[{"component":"text_block","required":False,"id":f"transcript:{r[0]}","text":r[1],"format":"plain_text",
                       "status":r[2],"source_start_ms":r[3],"source_end_ms":r[4]} for r in transcripts]
    sections=[_section("session-state","Aufnahmestatus","active_session",[status_item],0)]
    if transcript_items:sections.append(_section("live-transcript","Live-Transkript","active_session",transcript_items,10))
    if artifacts:sections.append(_section("session-entities","Erkannte Inhalte","relevant_knowledge",[_card(r[1],r[0],r[2][:100],r[2],r[3],r[4],ref_type="session_artifact") for r in artifacts],20))
    if questions:sections.append(_section("session-questions","Fragen","clarification_due",[_card("question_open" if r[2]=="open" else "question_answered",r[0],r[1],r[1],r[2],r[3],"question",ref_type="question") for r in questions],30))
    if topics:sections.append(_section("session-topics","Themen","topic_trend",[_card("topic",r[0],r[1],r[1],priority=r[2],ref_type="session_topic") for r in topics],40))
    if relevant:sections.append(_section("relevant-knowledge","Passendes Wissen","relevant_knowledge",[_card(r[1],r[0],r[2][:100],r[2],priority=r[3]) for r in relevant if r[2]],50))
    watermarks={"received_through_sequence":watermark_row[0],"queued_through_sequence":watermark_row[1],
                "processed_through_sequence":watermark_row[2],"artifact_through_sequence":watermark_row[3]} if watermark_row else None
    return {"mode":"live","primary_live_session":{"client_session_id":item["client_session_id"],"state":item["state"]},
            "processing":{"completion_status":status,"watermarks":watermarks,"missing_sequences":rec["missing_sequences"],
                          "upload_conflict_count":len(rec["conflicts"])},
            "sessions":[{"client_session_id":s["client_session_id"],"state":s["state"]} for s in list_client_sessions()],"sections":sections}


def _idle_content(surface="default"):
    refresh_sync_index();sessions=list_client_sessions();sections=[]
    with get_db_connection() as c:
        _ensure_identities(c,"question","session_questions")
        if surface=="esp32_epaper":
            _ensure_identities(c,"task","tasks","archived=FALSE AND status='open'")
            _ensure_identities(c,"list","lists","archived=FALSE")
            _ensure_identities(c,"list_item","list_items","archived=FALSE AND status='active'")
        c.commit()
        now=datetime.now(TIMEZONE)
        failures=c.execute("SELECT count(*) FROM processing_jobs WHERE status='failed'").fetchone()[0]
        questions=c.execute("""SELECT i.public_id,q.question_text,q.priority FROM session_questions q JOIN client_entity_identities i ON i.entity_type='question' AND i.internal_id=q.id
        WHERE q.status='open' ORDER BY q.priority DESC,q.updated_at DESC LIMIT 10""").fetchall()
        notes=c.execute("""SELECT e.public_id,n.content,n.updated_at FROM notes n JOIN client_knowledge_entities e ON e.entity_type='note' AND e.internal_id=n.id
        WHERE n.archived=FALSE AND e.state='active' ORDER BY n.updated_at DESC LIMIT 10""").fetchall()
        facts=c.execute("""SELECT e.public_id,c.statement,c.status,c.confidence FROM claims c JOIN client_knowledge_entities e ON e.entity_type='fact' AND e.internal_id=c.id
        WHERE c.claim_type='fact' AND c.status IN('active','disputed') AND e.state='active' ORDER BY c.updated_at DESC LIMIT 10""").fetchall()
        topics=c.execute("""SELECT e.public_id,t.title FROM knowledge_topics t JOIN client_knowledge_entities e ON e.entity_type='topic' AND e.internal_id=t.id
        WHERE e.state='active' ORDER BY t.updated_at DESC LIMIT 10""").fetchall()
        chats=c.execute("SELECT id,title,status,last_activity_at FROM client_conversations WHERE dashboard_until>%s ORDER BY last_activity_at DESC LIMIT 10",(now,)).fetchall()
        tasks=c.execute("""SELECT i.public_id,t.content,t.work_start_at,t.due_at,t.urgency,t.percent_complete FROM tasks t
        JOIN client_entity_identities i ON i.entity_type='task' AND i.internal_id=t.id
        WHERE t.archived=FALSE AND t.status='open'
          AND ((t.work_start_at IS NOT NULL AND t.work_start_at<=%s) OR t.urgency>=%s)
        ORDER BY CASE WHEN t.work_start_at IS NOT NULL AND t.work_start_at<=%s THEN 0 ELSE 1 END,
                 t.due_at NULLS LAST,t.urgency DESC,t.updated_at DESC LIMIT 10""",
        (now,ESP_TASK_MODERATE_URGENCY,now)).fetchall() if surface=="esp32_epaper" else []
        lists=c.execute("""SELECT i.public_id,l.title,l.description,
        count(li.id) FILTER(WHERE li.archived=FALSE AND li.status='active') active_count,
        string_agg(li.content,' · ' ORDER BY li.created_at) FILTER(WHERE li.archived=FALSE AND li.status='active') preview
        FROM lists l JOIN client_entity_identities i ON i.entity_type='list' AND i.internal_id=l.id
        LEFT JOIN list_items li ON li.list_id=l.id WHERE l.archived=FALSE
        GROUP BY i.public_id,l.id,l.title,l.description,l.updated_at
        HAVING count(li.id) FILTER(WHERE li.archived=FALSE AND li.status='active')>0
        ORDER BY l.updated_at DESC LIMIT 10""").fetchall() if surface=="esp32_epaper" else []
    if failures:
        sections.append(_section("system-attention","Systemhinweise","system_attention",[{"component":"alert","required":False,"id":"failed-jobs","severity":"warning","title":"Verarbeitung benötigt Aufmerksamkeit","text":f"{failures} Job(s) sind fehlgeschlagen.","icon":"warning"}],0))
    if questions:sections.append(_section("open-clarifications","Offene Fragen","clarification_due",[_card("question_open",r[0],r[1],r[1],priority=r[2],icon="question",action={"type":"open_clarification","params":{"question_id":str(r[0])}},ref_type="question") for r in questions],10))
    if sessions:sections.append(_section("active-sessions","Offene Sessions","active_session",[_card("session",s["client_session_id"],s.get("state","Session"),s.get("state",""),s["state"],.7,"session",{"type":"open_session","params":{"client_session_id":s["client_session_id"]}}) for s in sessions],20))
    if tasks:sections.append(_section("today","Aufgaben","due_today",[_card("task",r[0],r[1][:100],_task_window_preview(r[2],r[3],r[4],now),"open",r[4],"task",ref_type="task") for r in tasks],25))
    if lists:sections.append(_section("lists","Listen","active_lists",[_card("list",r[0],r[1],(r[4] or r[2] or "")[:240],f"{r[3]} offen",min(1,.4+r[3]/20),"list",ref_type="list") for r in lists],27))
    knowledge=[_card("note",r[0],r[1][:100],r[1],priority=.5) for r in notes]+[_card("fact",r[0],r[1][:100],r[1],r[2],r[3],"fact") for r in facts]
    if knowledge:sections.append(_section("recent-knowledge","Zuletzt relevantes Wissen","recent_knowledge",knowledge,30))
    if topics:sections.append(_section("topic-trends","Themen","topic_trend",[_card("topic",r[0],r[1],r[1]) for r in topics],40))
    if chats:sections.append(_section("open-chats","Offene Chats","open_chat",[_card("chat",r[0],r[1],r[1],r[2],.6,"chat",{"type":"open_conversation","params":{"conversation_id":str(r[0])}}) for r in chats],50))
    sections.append(_section("capture","Neue Eingabe","capture_suggestion",[{"component":"input_prompt","required":False,"id":"main-capture","title":"Memo oder Frage erfassen","modes":["auto","memo","query"],"default_mode":"auto","icon":"microphone"}],90))
    if not sections:sections=[_section("empty","Noch keine Inhalte","capture_suggestion",[{"component":"empty_state","required":False,"code":"no_content","title":"Noch keine Inhalte","text":"Erfasse ein Memo oder starte eine Aufnahme.","icon":"info"}],100)]
    return {"mode":"idle","primary_live_session":None,"sessions":[{"client_session_id":s["client_session_id"],"state":s["state"]} for s in sessions],"sections":sections}


def dashboard_snapshot(client_session_id=None,surface="default"):
    if client_session_id:
        item=get_client_session(client_session_id)
        if not item:return None
        content=_live_content(item) if item["ingestion_session_id"] else {"mode":"idle","primary_live_session":None,"sessions":[],"sections":[]}
        scope=f"session:{client_session_id}"
    else:
        sessions=list_client_sessions();primary=next((s for s in sessions if s["state"] in ("recording","paused")),None)
        content=_live_content(primary) if primary else _idle_content(surface);scope=f"home:{surface}"
        # Both branches, not only idle: a live snapshot carries up to fifty
        # transcript blocks, which the e-paper walker skips entirely because
        # they are not cards. Unprojected they would be pure overflow during a
        # recording — the one moment the panel must stay responsive.
        if surface==ESP_SURFACE:content=_project_for_epaper(content)
    material={"schema_version":"1","scope":scope,**content}
    encoded=json.dumps(material,ensure_ascii=False,sort_keys=True,separators=(",",":"));digest=hashlib.sha256(encoded.encode()).hexdigest();now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("SELECT revision,content_hash,snapshot FROM client_dashboard_snapshots WHERE scope_key=%s FOR UPDATE",(scope,)).fetchone()
        if row and row[1]==digest:snapshot=row[2]
        else:
            revision=(row[0]+1) if row else 1
            snapshot={**material,"revision":revision,"generated_at":now.isoformat()}
            c.execute("""INSERT INTO client_dashboard_snapshots(scope_key,revision,content_hash,snapshot,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_key) DO UPDATE SET revision=EXCLUDED.revision,content_hash=EXCLUDED.content_hash,
            snapshot=EXCLUDED.snapshot,updated_at=EXCLUDED.updated_at""",(scope,revision,digest,Jsonb(snapshot),now,now));c.commit()
    return {**snapshot,"server_time":now.isoformat()}


def get_dashboard_entity(entity_type,public_id):
    if entity_type not in ("session_artifact","session_topic","question","task","list"):return None
    with get_db_connection() as c:
        identity=c.execute("SELECT internal_id FROM client_entity_identities WHERE entity_type=%s AND public_id=%s",(entity_type,public_id)).fetchone()
        if not identity:return None
        internal_id=identity[0]
        if entity_type=="session_artifact":
            r=c.execute("SELECT artifact_type,content,status,confidence,created_at,updated_at FROM session_artifacts WHERE id=%s",(internal_id,)).fetchone()
            return {"id":str(public_id),"type":r[0],"content":_clip(r[1],DETAIL_MAX),"status":r[2],"confidence":r[3],"created_at":r[4].isoformat(),"updated_at":r[5].isoformat()} if r else None
        if entity_type=="session_topic":
            r=c.execute("SELECT title,description,status,confidence,created_at,updated_at FROM session_topics WHERE id=%s",(internal_id,)).fetchone()
            return {"id":str(public_id),"type":"topic","title":_clip(r[0],TITLE_MAX),"description":_clip(r[1],DETAIL_MAX),"status":r[2],"confidence":r[3],"created_at":r[4].isoformat(),"updated_at":r[5].isoformat()} if r else None
        if entity_type=="task":
            r=c.execute("SELECT content,work_start_at,due_at,status,priority,urgency,percent_complete,created_at,updated_at FROM tasks WHERE id=%s",(internal_id,)).fetchone()
            if not r:return None
            result={"id":str(public_id),"type":"task","content":_clip(r[0],DETAIL_MAX),"work_start_at":r[1].isoformat() if r[1] else None,"due_at":r[2].isoformat() if r[2] else None,"status":r[3],"priority":r[4],"urgency":r[5],"percent_complete":r[6],"created_at":r[7].isoformat(),"updated_at":r[8].isoformat()}
            # Only an open task has anything left to do; a task already done,
            # expired or archived offers no action, same as an entity_card
            # whose action the client does not implement — present but inert.
            if r[3]=="open":result["action"]={"type":"complete_task","params":{"task_id":str(public_id)}}
            return result
        if entity_type=="list":
            r=c.execute("SELECT title,description,created_at,updated_at FROM lists WHERE id=%s",(internal_id,)).fetchone()
            if not r:return None
            # A list detail is an actionable snapshot. Every active item gets
            # an opaque, stable client identity; completed items are absent,
            # not merely labelled done, so a successful completion cannot
            # reappear on the next fetch. The text projection remains for
            # clients that have not implemented structured list interaction.
            _ensure_identities(c,"list_item","list_items","list_id=%s AND archived=FALSE AND status='active'",(internal_id,))
            c.commit()
            items=c.execute("""SELECT i.public_id,li.content FROM list_items li
            JOIN client_entity_identities i ON i.entity_type='list_item' AND i.internal_id=li.id
            WHERE li.list_id=%s AND li.archived=FALSE AND li.status='active'
            ORDER BY li.created_at,li.id LIMIT 20""",(internal_id,)).fetchall()
            body=_clip(" · ".join(f"• {x[1]}" for x in items),DETAIL_MAX)
            return {"id":str(public_id),"type":"list","title":_clip(r[0],TITLE_MAX),"content":body,
                    "description":_clip(r[1],DETAIL_MAX),"status":f"{len(items)} offen",
                    "items":[{"id":str(x[0]),"content":_clip(x[1],DETAIL_MAX),"status":"active"} for x in items],
                    "created_at":r[2].isoformat(),"updated_at":r[3].isoformat()}
        r=c.execute("SELECT question_text,question_kind,status,confidence,priority,answer_text,answer_source,created_at,updated_at FROM session_questions WHERE id=%s",(internal_id,)).fetchone()
        return {"id":str(public_id),"type":"question","question":_clip(r[0],DETAIL_MAX),"question_kind":r[1],"status":r[2],"confidence":r[3],"priority":r[4],"answer":_clip(r[5],DETAIL_MAX),"answer_source":r[6],"created_at":r[7].isoformat(),"updated_at":r[8].isoformat()} if r else None
