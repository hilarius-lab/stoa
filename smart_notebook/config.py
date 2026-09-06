# Smart Notebook configuration
from zoneinfo import ZoneInfo
from pathlib import Path
import os


def _load_local_env():
    """Load a workspace-local .env without overriding process environment variables."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()

APP_VERSION = "local"
CLIENT_CONTRACT_VERSION = "1"
CLIENT_SUPPORTED_CONTRACT_VERSIONS = ("1",)
CLIENT_AUDIO_MAX_CHUNK_BYTES = min(16 * 1024 * 1024, max(64 * 1024, int(os.getenv("CLIENT_AUDIO_MAX_CHUNK_BYTES", str(2 * 1024 * 1024)))))
CLIENT_AUDIO_SEGMENT_TARGET_MS = min(60000, max(1000, int(os.getenv("CLIENT_AUDIO_SEGMENT_TARGET_MS", "10000"))))
CLIENT_REQUEST_TIMEOUT_SECONDS = min(300, max(5, int(os.getenv("CLIENT_REQUEST_TIMEOUT_SECONDS", "60"))))
CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS = min(604800, max(300, int(os.getenv("CLIENT_DASHBOARD_CACHE_MAX_AGE_SECONDS", "7200"))))
CLIENT_CORS_ORIGINS = tuple(item.strip() for item in os.getenv("CLIENT_CORS_ORIGINS", "").split(",") if item.strip())
CLIENT_SERVER_STATUS = os.getenv("CLIENT_SERVER_STATUS", "ready").strip().casefold()
if CLIENT_SERVER_STATUS not in {"ready", "degraded", "maintenance"}:
    CLIENT_SERVER_STATUS = "degraded"
CLIENT_SERVER_STATUS_MESSAGE = os.getenv("CLIENT_SERVER_STATUS_MESSAGE", "").strip()[:500] or None
CLIENT_DEVICE_AUTH_REQUIRED = os.getenv("CLIENT_DEVICE_AUTH_REQUIRED", "false").strip().casefold() in {"1","true","yes","on"}
CLIENT_DEVICE_AUTH_SECRET = os.getenv("CLIENT_DEVICE_AUTH_SECRET", "")
# Operator credential for everything under /api/ that is not the client contract:
# the legacy note/claim/task/list/artifact routes, the CalDAV endpoints and the
# worker triggers. A device credential must not open those, and they must not be
# open at all — 138 of 179 routes sit outside /api/client/ and were never touched
# by the device-auth middleware, so switching that flag on was closing the front
# door of a building with no back wall. Empty disables the operator path
# entirely, which locks those routes rather than opening them.
CLIENT_OPERATOR_TOKEN = os.getenv("CLIENT_OPERATOR_TOKEN", "")
NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL", "").strip().rstrip("/")
NEXTCLOUD_USERNAME = os.getenv("NEXTCLOUD_USERNAME", "").strip()
NEXTCLOUD_APP_PASSWORD = os.getenv("NEXTCLOUD_APP_PASSWORD", "")
NEXTCLOUD_TASK_CALENDAR = os.getenv("NEXTCLOUD_TASK_CALENDAR", "notizbuch").strip() or "notizbuch"
CALDAV_TIMEOUT_SECONDS = min(120,max(5,int(os.getenv("CALDAV_TIMEOUT_SECONDS","30"))))
CALDAV_VERIFY_TLS = os.getenv("CALDAV_VERIFY_TLS","true").strip().casefold() not in {"0","false","no","off"}
CALDAV_SYNC_INTERVAL_SECONDS = min(86400,max(30,int(os.getenv("CALDAV_SYNC_INTERVAL_SECONDS","300"))))
CALDAV_ALERT_AFTER_FAILURES = min(100,max(1,int(os.getenv("CALDAV_ALERT_AFTER_FAILURES","3"))))
NTFY_SERVER_URL = os.getenv("NTFY_SERVER_URL", "").strip().rstrip("/")
NTFY_ERROR_TOPIC = os.getenv("NTFY_ERROR_TOPIC", "").strip().strip("/")
NTFY_ACCESS_TOKEN = os.getenv("NTFY_ACCESS_TOKEN", "")
NTFY_TIMEOUT_SECONDS = min(60,max(5,int(os.getenv("NTFY_TIMEOUT_SECONDS","15"))))
LLM_URL = "http://capybara.nb.internal:8080/v1/chat/completions"
LLM_MODEL = os.getenv("LLM_MODEL", "CapybaraLM")
EMBEDDING_URL = "http://192.168.124.5:8181/v1/embeddings"
EMBEDDING_MODEL = "Qwen3-Embedding-0.6B"
EMBEDDING_DIMENSIONS = 1024
STT_URL = "http://192.168.124.5:9000/v1/audio/transcriptions"
STT_MODEL = "large-v3"
STT_API_MODEL_PARAMETER = "whisper-1"
STT_DEFAULT_LANGUAGE = "de"
AUDIO_RETENTION_CACHE_DIR = Path(os.getenv("AUDIO_RETENTION_CACHE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "audio"))).resolve()
AUDIO_RETENTION_DAYS = int(os.getenv("AUDIO_RETENTION_DAYS", "7"))
SYSTEM_LOG_RETENTION_HOURS = min(48,max(1,int(os.getenv("SYSTEM_LOG_RETENTION_HOURS", "48"))))
TOPIC_NEW_MIN_CONFIDENCE = min(1.0,max(0.0,float(os.getenv("TOPIC_NEW_MIN_CONFIDENCE", "0.90"))))
TOPIC_LINK_MIN_CONFIDENCE = min(1.0,max(0.0,float(os.getenv("TOPIC_LINK_MIN_CONFIDENCE", "0.82"))))
TOPIC_LIVE_MIN_CONFIDENCE = min(1.0,max(0.0,float(os.getenv("TOPIC_LIVE_MIN_CONFIDENCE", "0.85"))))
SEMANTIC_EXAMPLE_MIN_SIMILARITY = min(1.0,max(-1.0,float(os.getenv("SEMANTIC_EXAMPLE_MIN_SIMILARITY", "0.86"))))
SEMANTIC_EXAMPLE_MIN_MARGIN = min(2.0,max(0.0,float(os.getenv("SEMANTIC_EXAMPLE_MIN_MARGIN", "0.08"))))
NIGHTLY_KNOWLEDGE_SEMANTIC_MIN_SIMILARITY = min(1.0,max(-1.0,float(os.getenv("NIGHTLY_KNOWLEDGE_SEMANTIC_MIN_SIMILARITY","0.82"))))
NIGHTLY_TOPIC_SEMANTIC_MIN_SIMILARITY = min(1.0,max(-1.0,float(os.getenv("NIGHTLY_TOPIC_SEMANTIC_MIN_SIMILARITY","0.80"))))
RETRIEVAL_CACHE_TTL_HOURS = min(24,max(1,int(os.getenv("RETRIEVAL_CACHE_TTL_HOURS","24"))))
REFERENCE_RESULT_TTL_HOURS = min(24,max(1,int(os.getenv("REFERENCE_RESULT_TTL_HOURS","24"))))
REFERENCE_STRONG_CONFIDENCE = min(1.0,max(0.0,float(os.getenv("REFERENCE_STRONG_CONFIDENCE","0.82"))))
REFERENCE_SUPPORTING_CONFIDENCE = min(1.0,max(0.0,float(os.getenv("REFERENCE_SUPPORTING_CONFIDENCE","0.72"))))
REFERENCE_AMBIGUITY_MARGIN = min(1.0,max(0.0,float(os.getenv("REFERENCE_AMBIGUITY_MARGIN","0.08"))))
NOTE_TO_FACT_MIN_EVIDENCE_SCORE = min(1.0,max(0.0,float(os.getenv("NOTE_TO_FACT_MIN_EVIDENCE_SCORE","0.80"))))
POSTGRES_HOST = "192.168.124.5"
POSTGRES_PORT = 5432
POSTGRES_DB = "smart_notebook"
POSTGRES_USER = "smart_notebook"
POSTGRES_PASSWORD = "CHANGE_ME_TO_A_LONG_RANDOM_PASSWORD"
CONTEXT_EVENT_LIMIT = 10
CONTEXT_MAX_AGE_MINUTES = 60
NOTE_RETRIEVAL_LIMIT = 5
NOTE_RETRIEVAL_MIN_SIMILARITY = 0.35
TASK_RETRIEVAL_LIMIT = 5
TASK_RETRIEVAL_MIN_SIMILARITY = 0.35
CONSOLIDATION_DEDUPE_LIMIT = 3
KNOWLEDGE_RETRIEVAL_LIMIT = 7
KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY = 0.30
HYBRID_CANDIDATE_LIMIT = 20
HYBRID_RRF_K = 60
HYBRID_TRIGRAM_MIN_SCORE = 0.35
KNOWLEDGE_LIST_CONTEXT_ITEM_LIMIT = 12
CHAT_NOTE_REDUNDANCY_SIMILARITY = 0.88
NOTE_CLEANUP_CANDIDATE_SIMILARITY = 0.78
NOTE_CLEANUP_MAX_GROUPS = 10
LIST_RETRIEVAL_LIMIT = 3
LIST_RETRIEVAL_MIN_SIMILARITY = 0.30
LIST_TARGET_CANDIDATE_LIMIT = 3
LIST_ITEM_DEDUPE_LIMIT = 3
TIMEZONE = ZoneInfo("Europe/Berlin")
