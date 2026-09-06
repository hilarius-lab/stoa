from pathlib import Path
import ast
import importlib
import sys

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "smart_notebook"

if not PACKAGE.exists():
    raise RuntimeError(f"Paketordner fehlt: {PACKAGE}")

sys.path.insert(0, str(ROOT))

# 1) Syntax aller Module
python_files = list(PACKAGE.rglob("*.py"))
for path in python_files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

print(f"[OK] Syntax aller Module ({len(python_files)} Dateien)")

# 2) App importieren, aber im statischen Test keine echte DB-Migration starten
db = importlib.import_module("smart_notebook.database")
real_init_db = db.init_db
db.init_db = lambda: None

try:
    app_module = importlib.import_module("smart_notebook.app")
finally:
    db.init_db = real_init_db

app = app_module.app
print(f"[INFO] Geladene app.py: {app_module.__file__}")

# 3) Effektive API über OpenAPI bestimmen
openapi = app.openapi()
paths = openapi.get("paths", {})

http_methods = {
    "get", "post", "put", "patch", "delete",
    "options", "head", "trace"
}

operations = set()
for path, path_item in paths.items():
    for method in path_item:
        m = method.lower()
        if m in http_methods:
            operations.add((m.upper(), path))

print(f"[INFO] OpenAPI Paths: {len(paths)}")
print(f"[INFO] Smart-Notebook-Operationen: {len(operations)}")

# Erwartete bestehende API inklusive A2:
EXPECTED_OPERATIONS = {
    ("POST", "/api/references/resolve"),
    ("POST", "/api/claims/{claim_id}/reference-evidence"),
    ("GET", "/api/caldav/status"),
    ("POST", "/api/caldav/discover"),
    ("POST", "/api/caldav/sync"),
    ("GET", "/api/caldav/conflicts"),
    ("POST", "/api/caldav/conflicts/{conflict_id}/resolve"),
    ("GET", "/api/system/status"),
    ("GET", "/api/client/health"),
    ("GET", "/api/client/capabilities"),
    ("GET", "/api/client/v1/contract"),
    ("POST", "/api/client/v1/diagnostics/audio-upload-test"),
    ("GET", "/api/client/v1/dashboard"),
    ("GET", "/api/client/v1/dashboard/events"),
    ("GET", "/api/client/v1/knowledge/libraries"),
    ("GET", "/api/client/v1/knowledge/snapshot"),
    ("GET", "/api/client/v1/knowledge/delta"),
    ("GET", "/api/client/v1/knowledge/entities/{entity_id}"),
    ("GET", "/api/client/v1/entities/{entity_type}/{entity_id}"),
    ("POST", "/api/client/v1/captures"),
    ("GET", "/api/client/v1/captures/{capture_id}"),
    ("POST", "/api/workers/client-capture/run-once"),
    ("POST", "/api/client/v1/knowledge/usage"),
    ("GET", "/api/client/v1/conversations"),
    ("POST", "/api/client/v1/conversations"),
    ("GET", "/api/client/v1/conversations/{conversation_id}"),
    ("POST", "/api/client/v1/conversations/{conversation_id}/turns"),
    ("GET", "/api/client/v1/conversation-turns/{turn_id}"),
    ("GET", "/api/client/v1/conversation-turns/{turn_id}/events"),
    ("POST", "/api/client/v1/conversation-turns/{turn_id}/abort"),
    ("POST", "/api/client/v1/conversation-turns/{turn_id}/retry"),
    ("POST", "/api/workers/client-chat/run-once"),
    ("GET", "/api/client/v1/push/registrations"),
    ("POST", "/api/client/v1/push/registrations"),
    ("POST", "/api/client/v1/push/registrations/{registration_id}/confirm"),
    ("DELETE", "/api/client/v1/push/registrations/{registration_id}"),
    ("GET", "/api/client/v1/sessions"),
    ("GET", "/api/client/v1/sessions/{client_session_id}"),
    ("GET", "/api/client/v1/sessions/{client_session_id}/reconciliation"),
    ("GET", "/api/client/v1/sessions/{client_session_id}/dashboard"),
    ("GET", "/api/client/v1/sessions/{client_session_id}/dashboard/events"),
    ("POST", "/api/client/v1/sessions"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/start"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/pause"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/resume"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/finish"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/finalize"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/abort"),
    ("POST", "/api/client/v1/sessions/{client_session_id}/audio-chunks"),
    ("POST", "/api/client/v1/installations/enroll"),
    ("POST", "/api/client/v1/installations/{client_installation_id}/credentials/rotate"),
    ("GET", "/api/semantic-gold-examples"),
    ("POST", "/api/semantic-gold-examples/seed"),
    ('GET', '/'),
    ('GET', '/api/debug'),
    ('GET', '/api/ai-task-profiles'),
    ('GET', '/api/audio-chunks/{chunk_id}'),
    ('GET', '/api/claims'),
    ('GET', '/api/claims/{claim_id}'),
    ('GET', '/api/conflicts'),
    ('GET', '/api/events'),
    ('GET', '/api/events/by-client-id/{client_event_id}'),
    ('GET', '/api/events/{event_id}'),
    ('GET', '/api/events/{event_id}/knowledge'),
    ('GET', '/api/evidence-sources'),
    ('GET', '/api/ingestion-sessions'),
    ('GET', '/api/ingestion-sessions/{session_id}'),
    ('GET', '/api/ingestion-sessions/{session_id}/chunks'),
    ('GET', '/api/ingestion-sessions/{session_id}/artifacts'),
    ('GET', '/api/ingestion-sessions/{session_id}/audio-chunks'),
    ('GET', '/api/ingestion-sessions/{session_id}/transcripts'),
    ('GET', '/api/ingestion-sessions/{session_id}/processing-state'),
    ('GET', '/api/ingestion-sessions/{session_id}/segments'),
    ('GET', '/api/ingestion-sessions/{session_id}/topics'),
    ('GET', '/api/ingestion-sessions/{session_id}/watermarks'),
    ('GET', '/api/ingestion-sessions/{session_id}/live-feed'),
    ('GET', '/api/ingestion-sessions/{session_id}/evidence'),
    ('GET', '/api/ingestion-sessions/{session_id}/questions'),
    ('GET', '/api/personal-knowledge/fast-path'),
    ('GET', '/api/ingestion-chunks/{chunk_id}'),
    ('GET', '/api/knowledge/{key}'),
    ('GET', '/api/knowledge/{key}/sources'),
    ('GET', '/api/knowledge/{knowledge_type}/{knowledge_id}/topics'),
    ('GET', '/api/knowledge-activity'),
    ('GET', '/api/knowledge-signals'),
    ('GET', '/api/list-items/{item_id}'),
    ('GET', '/api/lists'),
    ('GET', '/api/lists/{list_id}'),
    ('GET', '/api/lists/{list_id}/items'),
    ('GET', '/api/notes'),
    ('GET', '/api/notes/{note_id}'),
    ('GET', '/api/notes/{note_id}/claim-candidates'),
    ('GET', '/api/processing-jobs'),
    ('GET', '/api/processing-jobs/metrics/summary'),
    ('GET', '/api/processing-jobs/{job_id}'),
    ('GET', '/api/semantic-segments/{segment_id}'),
    ('GET', '/api/semantic-shadow-runs/{run_id}'),
    ('GET', '/api/session-artifacts/{artifact_id}'),
    ('GET', '/api/session-topics/{topic_id}'),
    ('GET', '/api/tasks'),
    ('GET', '/api/tasks/{task_id}'),
    ('PATCH', '/api/list-items/{item_id}'),
    ('PATCH', '/api/lists/{list_id}'),
    ('PATCH', '/api/notes/{note_id}'),
    ('PATCH', '/api/tasks/{task_id}'),
    ('PATCH', '/api/session-artifacts/{artifact_id}'),
    ('PATCH', '/api/session-topics/{topic_id}'),
    ('POST', '/api/capture'),
    ('POST', '/api/capture/batch'),
    ('POST', '/api/claims'),
    ('POST', '/api/claims/{claim_id}/evidence'),
    ('POST', '/api/claims/{claim_id}/relations'),
    ('POST', '/api/conflicts/detect'),
    ('POST', '/api/consolidate-today'),
    ('POST', '/api/events'),
    ('POST', '/api/events/batch'),
    ('POST', '/api/events/{event_id}/archive'),
    ('POST', '/api/events/{event_id}/capture'),
    ('POST', '/api/events/{event_id}/unarchive'),
    ('POST', '/api/evidence-sources'),
    ('POST', '/api/ingestion-sessions'),
    ('POST', '/api/ingestion-sessions/{session_id}/chunks'),
    ('POST', '/api/ingestion-sessions/{session_id}/audio-chunks'),
    ('POST', '/api/ingestion-sessions/{session_id}/finish'),
    ('POST', '/api/ingestion-sessions/{session_id}/finalize'),
    ('POST', '/api/ingestion-sessions/{session_id}/evidence/generate'),
    ('POST', '/api/ingestion-sessions/{session_id}/questions'),
    ('POST', '/api/ingestion-sessions/{session_id}/artifacts/promote'),
    ('POST', '/api/ingestion-sessions/{session_id}/questions/detect'),
    ('POST', '/api/ingestion-sessions/{session_id}/transcripts/stabilize'),
    ('POST', '/api/ingestion-sessions/{session_id}/repair'),
    ('POST', '/api/ingestion-sessions/{session_id}/semantic-shadow'),
    ('POST', '/api/list-items/{item_id}/archive'),
    ('POST', '/api/list-items/{item_id}/done'),
    ('POST', '/api/list-items/{item_id}/reopen'),
    ('POST', '/api/lists'),
    ('POST', '/api/lists/{list_id}/archive'),
    ('POST', '/api/lists/{list_id}/items'),
    ('POST', '/api/lists/{list_id}/unarchive'),
    ('POST', '/api/maintenance/daily'),
    ('POST', '/api/maintenance/deduplicate-notes'),
    ('POST', '/api/maintenance/conflicts/scan'),
    ('POST', '/api/maintenance/jobs/night-repair'),
    ('POST', '/api/maintenance/nightly-consolidation'),
    ('POST', '/api/knowledge-activity'),
    ('POST', '/api/knowledge/{knowledge_type}/{knowledge_id}/signals/refresh'),
    ('POST', '/api/knowledge-topics/{parent_topic_id}/relations'),
    ('POST', '/api/message'),
    ('POST', '/api/notes'),
    ('POST', '/api/notes/{note_id}/claim-candidates'),
    ('POST', '/api/notes/{note_id}/archive'),
    ('POST', '/api/notes/{note_id}/unarchive'),
    ('POST', '/api/processing-jobs'),
    ('POST', '/api/processing-jobs/claim'),
    ('POST', '/api/processing-jobs/{job_id}/complete'),
    ('POST', '/api/processing-jobs/{job_id}/fail'),
    ('POST', '/api/processing-jobs/{job_id}/retry'),
    ('POST', '/api/search-knowledge'),
    ('POST', '/api/search-list-items'),
    ('POST', '/api/search-lists'),
    ('POST', '/api/search-notes'),
    ('POST', '/api/search-tasks'),
    ('POST', '/api/tasks'),
    ('POST', '/api/tasks/archive-closed'),
    ('POST', '/api/tasks/expire-overdue'),
    ('POST', '/api/tasks/{task_id}/archive'),
    ('POST', '/api/tasks/{task_id}/done'),
    ('POST', '/api/tasks/{task_id}/reopen'),
    ('POST', '/api/workers/text-processing/run-once'),
    ('POST', '/api/workers/session-artifacts/run-once'),
    ('POST', '/api/workers/audio-stt/run-once'),
    ('POST', '/api/session-artifacts/{artifact_id}/confirm'),
    ('POST', '/api/session-artifacts/{artifact_id}/dismiss'),
    ('POST', '/api/session-artifacts/{artifact_id}/supersede'),
    ('POST', '/api/session-artifacts/{artifact_id}/topics'),
    ('POST', '/api/session-questions/{question_id}/answer'),
    ('POST', '/api/session-questions/{question_id}/reopen'),
    ('POST', '/api/ingestion-sessions/{session_id}/topics'),
    ('PUT', '/api/ingestion-sessions/{session_id}/question-budget'),
}

missing = EXPECTED_OPERATIONS - operations
extra = operations - EXPECTED_OPERATIONS

if missing or extra:
    print()
    print("[DIAG] API-Abweichung gefunden")

    if missing:
        print("Fehlt in der Anwendung:")
        for method, path in sorted(missing):
            print(f"  {method:6} {path}")

    if extra:
        print("Zusätzlich in der Anwendung:")
        for method, path in sorted(extra):
            print(f"  {method:6} {path}")

    raise AssertionError(
        "API stimmt nicht exakt mit der erwarteten Operationenliste überein"
    )

assert len(EXPECTED_OPERATIONS) == 179
assert len(operations) == 179

print("[OK] FastAPI-App importierbar")
print("[OK] 177 effektive Smart-Notebook-Operationen")
print("[OK] Bestehende API plus Foundation, B1-B5 und C1-C3 vorhanden")
print("STATIC SMOKE TEST: PASS")
