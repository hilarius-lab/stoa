# Logical AI task registry and model routing foundation
from copy import deepcopy
from ..config import LLM_MODEL, LLM_URL

_DEFAULT_LOCAL = {
    "provider": "self_hosted_openai_compatible",
    "endpoint": LLM_URL,
    "model": LLM_MODEL,
    "timeout_seconds": 180,
    "temperature": 0.0,
    "privacy_class": "local_only",
    "fallback_task_id": None,
    "enabled": True
}

AI_TASK_PROFILES = {
    "capture.classify": {"group":"capture","complexity":"standard"},
    "capture.intent": {"group":"capture","complexity":"standard"},
    "capture.intent_split": {"group":"capture","complexity":"standard"},
    "capture.knowledge_preflight": {"group":"capture","complexity":"standard"},
    "capture.target_resolution": {"group":"capture","complexity":"standard"},
    "capture.action_plan": {"group":"capture","complexity":"standard"},
    "segmentation.semantic": {"group":"semantic_segmentation","complexity":"complex"},
    "audio.plausibility": {"group":"stt_uncertainty","complexity":"standard"},
    "artifacts.session_memory": {"group":"session_artifact_analysis","complexity":"complex"},
    "artifacts.task_promotion": {"group":"session_artifact_analysis","complexity":"standard"},
    "questions.detect": {"group":"question_detection","complexity":"complex"},
    "questions.resolve": {"group":"question_resolution","complexity":"critical"},
    "deduplication.note": {"group":"deduplication","complexity":"standard"},
    "deduplication.task": {"group":"deduplication","complexity":"standard"},
    "deduplication.list_item": {"group":"deduplication","complexity":"standard"},
    "consolidation.daily": {"group":"consolidation","complexity":"complex"},
    "maintenance.note_cleanup": {"group":"maintenance","complexity":"complex"},
    "claims.extract": {"group":"claim_extraction","complexity":"complex"},
    "retrieval.answer": {"group":"retrieval_answer","complexity":"complex"},
    "conversation.reply": {"group":"conversation","complexity":"complex"},
    "coding.offload": {"group":"coding_offload","complexity":"critical","enabled":False,"privacy_class":"pseudonymizable"}
}

for _task_id, _profile in AI_TASK_PROFILES.items():
    merged = {**_DEFAULT_LOCAL, **_profile, "task_id": _task_id}
    AI_TASK_PROFILES[_task_id] = merged

def get_ai_task_profile(task_id):
    profile = AI_TASK_PROFILES.get(task_id)
    if profile is None:
        raise KeyError(f"Unknown AI task profile: {task_id}")
    if not profile["enabled"]:
        raise RuntimeError(f"AI task profile is disabled: {task_id}")
    return deepcopy(profile)

def list_ai_task_profiles():
    return [deepcopy(AI_TASK_PROFILES[key]) for key in sorted(AI_TASK_PROFILES)]
