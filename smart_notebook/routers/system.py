# System routes
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..config import *
from ..database import get_db_connection
from ..services.ingestion import INGESTION_SESSION_STATUSES
from ..services.ai_tasks import list_ai_task_profiles
from ..services.observability import system_status

router = APIRouter()

@router.get("/api/system/status")
async def get_system_status():
    return system_status()

@router.get("/api/ai-task-profiles")
async def get_ai_task_profiles():
    return list_ai_task_profiles()

@router.get("/", response_class=HTMLResponse)
async def home():
    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Smart Notebook</title>
        </head>

        <body>
            <h1>Smart Notebook Test</h1>
            <p>Version: {APP_VERSION}</p>

            <input
                id="message"
                type="text"
                placeholder="Nachricht eingeben"
            >

            <button onclick="sendMessage()">
                Senden
            </button>

            <pre id="output"></pre>

            <h2>Gespeicherte Events</h2>

            <button onclick="loadEvents()">
                Events laden
            </button>

            <pre id="events"></pre>

            <hr><h2>Audio-Aufnahme (PoC)</h2>
            <button id="audioStart" onclick="startAudio()">Aufnahme starten</button>
            <button id="audioPause" onclick="pauseAudio()" disabled>Pause</button>
            <button id="audioStop" onclick="stopAudio()" disabled>Beenden</button>
            <button id="audioRetry" onclick="manualRetryAudio()" hidden>Upload erneut versuchen</button>
            <p id="audioStatus">Nicht aktiv</p>
            <pre id="audioQueue"></pre>

            <script>
                async function sendMessage() {{
                    const text =
                        document.getElementById("message").value;

                    const response =
                        await fetch("/api/message", {{
                            method: "POST",
                            headers: {{
                                "Content-Type": "application/json"
                            }},
                            body: JSON.stringify({{
                                text: text
                            }})
                        }});

                    const data =
                        await response.json();

                    document.getElementById("output").textContent =
                        JSON.stringify(data, null, 2);
                }}

                async function loadEvents() {{
                    const response =
                        await fetch("/api/events");

                    const data =
                        await response.json();

                    document.getElementById("events").textContent =
                        JSON.stringify(data, null, 2);
                }}

                let recorder, mediaStream, audioSessionId, audioSequence=0, segmentTimer,recordingHeartbeatTimer;
                let audioActive=false, audioPaused=false;
                let recordingStartedAt=0, lastChunkAt=0;
                const uploadInFlight=new Set(),ATTENTION_AFTER_MS=24*60*60*1000;
                const audioDb=new Promise((resolve,reject)=>{{
                    const request=indexedDB.open("smart-notebook-audio",2);
                    request.onupgradeneeded=()=>{{if(!request.result.objectStoreNames.contains("queue"))request.result.createObjectStore("queue",{{keyPath:"client_chunk_id"}});if(!request.result.objectStoreNames.contains("sessions"))request.result.createObjectStore("sessions",{{keyPath:"session_id"}})}};
                    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
                }});
                async function queuePut(item){{const db=await audioDb;const tx=db.transaction("queue","readwrite");tx.objectStore("queue").put(item);return new Promise(r=>tx.oncomplete=r)}}
                async function queueDelete(id){{const db=await audioDb;const tx=db.transaction("queue","readwrite");tx.objectStore("queue").delete(id);return new Promise(r=>tx.oncomplete=r)}}
                async function queueAll(){{const db=await audioDb;return new Promise((resolve,reject)=>{{const q=db.transaction("queue").objectStore("queue").getAll();q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)}})}}
                async function sessionPut(item){{const db=await audioDb;const tx=db.transaction("sessions","readwrite");tx.objectStore("sessions").put(item);return new Promise(r=>tx.oncomplete=r)}}
                async function sessionDelete(id){{const db=await audioDb;const tx=db.transaction("sessions","readwrite");tx.objectStore("sessions").delete(id);return new Promise(r=>tx.oncomplete=r)}}
                async function sessionAll(){{const db=await audioDb;return new Promise((resolve,reject)=>{{const q=db.transaction("sessions").objectStore("sessions").getAll();q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)}})}}
                async function recoverInterruptedSessions(){{const now=Date.now();for(const session of await sessionAll()){{if(!session.finish_requested&&now-(session.heartbeat_at||session.created_at)>20000){{session.finish_requested=true;session.recovery_reason="stale_browser_heartbeat";await sessionPut(session);document.getElementById("audioStatus").textContent=`Unterbrochene Session ${{session.session_id}} wird wiederhergestellt`}}}}}}
                async function finalizeReadySessions(){{const queued=await queueAll();for(const session of await sessionAll()){{if(!session.finish_requested||queued.some(i=>i.session_id===session.session_id))continue;try{{const finished=await fetch(`/api/ingestion-sessions/${{session.session_id}}/finish`,{{method:"POST"}});const stabilized=finished.ok?await fetch(`/api/ingestion-sessions/${{session.session_id}}/transcripts/stabilize`,{{method:"POST"}}):null;if(finished.ok&&stabilized&&stabilized.ok){{await sessionDelete(session.session_id);document.getElementById("audioStatus").textContent=`Session ${{session.session_id}} beendet · Transkript stabilisiert`}}}}catch(error){{document.getElementById("audioStatus").textContent=`Session-Abschluss wartet: ${{error}}`}}}}}}
                async function refreshQueue(manual=false){{const items=await queueAll();const now=Date.now();
                    for(const item of items){{if(now-(item.queued_at||now)>=ATTENTION_AFTER_MS)item.attention_required=true;if(manual)item.attention_required=false;await queuePut(item)}}
                    const attention=items.filter(i=>i.attention_required).length;document.getElementById("audioRetry").hidden=attention===0;
                    document.getElementById("audioQueue").textContent=`Lokale Queue: ${{items.length}} Chunk(s)${{attention?` · ${{attention}} benötigen Aufmerksamkeit`:""}}`;
                    await Promise.all(items.filter(i=>manual||!i.attention_required).map(uploadQueued));const remaining=await queueAll();const leftAttention=remaining.filter(i=>i.attention_required).length;
                    document.getElementById("audioRetry").hidden=leftAttention===0;document.getElementById("audioQueue").textContent=`Lokale Queue: ${{remaining.length}} Chunk(s)${{leftAttention?` · ${{leftAttention}} benötigen manuellen Retry`:""}}`;await finalizeReadySessions();return remaining.length}}
                async function manualRetryAudio(){{await refreshQueue(true)}}
                function chooseAudioType(){{for(const t of ["audio/webm;codecs=opus","audio/ogg;codecs=opus","audio/mp4"])if(MediaRecorder.isTypeSupported(t))return t;return ""}}
                function startRecorderSegment(){{
                    if(!audioActive||audioPaused)return;
                    const type=chooseAudioType();recorder=new MediaRecorder(mediaStream,type?{{mimeType:type,audioBitsPerSecond:64000}}:undefined);
                    const segmentRecorder=recorder;
                    const start=lastChunkAt;
                    recorder.ondataavailable=async event=>{{if(!event.data.size)return;const end=Math.round(performance.now()-recordingStartedAt);lastChunkAt=end;audioSequence++;
                        const item={{client_chunk_id:crypto.randomUUID(),session_id:audioSessionId,sequence:audioSequence,blob:event.data,mime_type:segmentRecorder.mimeType||event.data.type,duration_ms:Math.max(1,end-start),source_start_ms:start,source_end_ms:end,captured_at:new Date().toISOString(),queued_at:Date.now(),attempts:0,last_error:null,attention_required:false}};
                        await queuePut(item);await refreshQueue();}};
                    recorder.onstop=()=>{{if(audioActive&&!audioPaused)startRecorderSegment();}};
                    recorder.start();segmentTimer=setTimeout(()=>{{if(recorder.state==="recording")recorder.stop()}},10000);
                }}
                async function startAudio(){{
                    const session=await (await fetch("/api/ingestion-sessions",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{source_type:"audio-web-poc",title:"Browser Audio PoC",source:"web"}})}})).json();
                    audioSessionId=session.id;audioSequence=0;const owner=crypto.randomUUID();await sessionPut({{session_id:audioSessionId,finish_requested:false,created_at:Date.now(),heartbeat_at:Date.now(),owner_id:owner}});recordingHeartbeatTimer=setInterval(async()=>{{if(audioActive)await sessionPut({{session_id:audioSessionId,finish_requested:false,created_at:Date.now(),heartbeat_at:Date.now(),owner_id:owner}})}},5000);mediaStream=await navigator.mediaDevices.getUserMedia({{audio:true}});
                    recordingStartedAt=performance.now();lastChunkAt=0;audioActive=true;audioPaused=false;startRecorderSegment();
                    document.getElementById("audioStatus").textContent=`Session ${{audioSessionId}} · eigenständige 10-Sekunden-Clips`;
                    document.getElementById("audioStart").disabled=true;document.getElementById("audioPause").disabled=false;document.getElementById("audioStop").disabled=false;
                }}
                function pauseAudio(){{clearTimeout(segmentTimer);if(!audioPaused){{audioPaused=true;if(recorder.state==="recording")recorder.stop();document.getElementById("audioPause").textContent="Fortsetzen"}}else{{audioPaused=false;lastChunkAt=Math.round(performance.now()-recordingStartedAt);startRecorderSegment();document.getElementById("audioPause").textContent="Pause"}}}}
                async function stopAudio(){{audioActive=false;clearTimeout(segmentTimer);clearInterval(recordingHeartbeatTimer);if(recorder&&recorder.state==="recording")recorder.stop();mediaStream.getTracks().forEach(t=>t.stop());document.getElementById("audioStart").disabled=false;document.getElementById("audioPause").disabled=true;document.getElementById("audioStop").disabled=true;
                    await new Promise(r=>setTimeout(r,400));for(let i=0;i<30;i++){{if(await refreshQueue()===0)break;await new Promise(r=>setTimeout(r,500));}}
                    await sessionPut({{session_id:audioSessionId,finish_requested:true,created_at:Date.now()}});await finalizeReadySessions();}}
                async function uploadQueued(item){{if(uploadInFlight.has(item.client_chunk_id))return;uploadInFlight.add(item.client_chunk_id);try{{item.attempts=(item.attempts||0)+1;item.last_attempt_at=Date.now();await queuePut(item);const form=new FormData();form.append("audio",item.blob,`chunk-${{item.sequence}}`);for(const k of ["sequence","client_chunk_id","duration_ms","source_start_ms","source_end_ms","captured_at"])form.append(k,item[k]);const response=await fetch(`/api/ingestion-sessions/${{item.session_id}}/audio-chunks`,{{method:"POST",body:form}});const ack=response.ok?await response.json():null;
                    if(response.ok&&ack&&ack.session_id===item.session_id&&ack.sequence===item.sequence&&ack.client_chunk_id===item.client_chunk_id&&ack.id)await queueDelete(item.client_chunk_id);
                    else{{item.last_error=`ACK ungültig oder Upload fehlgeschlagen (${{response.status}})`;await queuePut(item)}}}}catch(error){{item.last_error=String(error);await queuePut(item);document.getElementById("audioStatus").textContent=`Upload wartet: ${{error}}`;}}finally{{uploadInFlight.delete(item.client_chunk_id)}}}}
                window.addEventListener("online",refreshQueue);recoverInterruptedSessions().then(refreshQueue);setInterval(async()=>{{await recoverInterruptedSessions();await refreshQueue()}},15000);
            </script>
        </body>
    </html>
    """

@router.get("/api/debug")
async def debug_status():
    now = datetime.now(TIMEZONE)

    with get_db_connection() as connection:
        postgres_version = connection.execute(
            "SELECT version()"
        ).fetchone()[0]

        vector_version_row = connection.execute(
            """
            SELECT extversion
            FROM pg_extension
            WHERE extname = 'vector'
            """
        ).fetchone()

        trgm_version_row = connection.execute(
            """
            SELECT extversion
            FROM pg_extension
            WHERE extname = 'pg_trgm'
            """
        ).fetchone()

    return {
        "app_version": APP_VERSION,
        "current_time": now.isoformat(),
        "llm_url": LLM_URL,
        "llm_model": LLM_MODEL,
        "context_event_limit": CONTEXT_EVENT_LIMIT,
        "context_max_age_minutes": CONTEXT_MAX_AGE_MINUTES,
        "postgres_host": POSTGRES_HOST,
        "postgres_database": POSTGRES_DB,
        "postgres_version": postgres_version,
        "pgvector_version": vector_version_row[0] if vector_version_row else None,
        "pg_trgm_version": trgm_version_row[0] if trgm_version_row else None,
        "embedding_url": EMBEDDING_URL,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "stt_url": STT_URL,
        "stt_model": STT_MODEL,
        "stt_default_language": STT_DEFAULT_LANGUAGE,
        "note_retrieval": "cosine_similarity_pgvector",
        "note_retrieval_limit": NOTE_RETRIEVAL_LIMIT,
        "note_retrieval_min_similarity": NOTE_RETRIEVAL_MIN_SIMILARITY,
        "task_retrieval_limit": TASK_RETRIEVAL_LIMIT,
        "task_retrieval_min_similarity": TASK_RETRIEVAL_MIN_SIMILARITY,
        "consolidation_dedupe_limit": CONSOLIDATION_DEDUPE_LIMIT,
        "runtime_capture_deduplication": True,
        "task_lifecycle": "open -> done/expired -> archived",
        "daily_maintenance_endpoint": "/api/maintenance/daily",
        "core_api_surface": "events + capture + notes + tasks + lists",
        "list_retrieval_limit": LIST_RETRIEVAL_LIMIT,
        "list_retrieval_min_similarity": LIST_RETRIEVAL_MIN_SIMILARITY,
        "chat_note_redundancy_similarity": CHAT_NOTE_REDUNDANCY_SIMILARITY,
        "note_cleanup_candidate_similarity": NOTE_CLEANUP_CANDIDATE_SIMILARITY,
        "note_cleanup_endpoint": "/api/maintenance/deduplicate-notes",
        "knowledge_retrieval_mode": "hybrid_rrf",
        "hybrid_candidate_limit": HYBRID_CANDIDATE_LIMIT,
        "hybrid_rrf_k": HYBRID_RRF_K,
        "hybrid_trigram_min_score": HYBRID_TRIGRAM_MIN_SCORE,
        "hybrid_fts_config": "simple",
        "provenance_model": "knowledge_sources",
        "multi_source_provenance": True,
        "offline_device_ingestion": True,
        "event_batch_limit": 100,
        "event_idempotency_key": "client_event_id",
        "ingestion_sessions": True,
        "ingestion_session_statuses": sorted(
            INGESTION_SESSION_STATUSES
        )
    }
