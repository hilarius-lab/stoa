"""Canonical semantic content types and local classification validation.

Artifacts are mutable session-memory candidates. Questions deliberately use
their own store, while fact/decision artifacts are candidates for atomic
claims. Keeping those distinctions here prevents each ingestion path from
inventing a slightly different type universe.
"""
from datetime import datetime
import re
from typing import Literal


ArtifactType = Literal["note", "task", "list", "list_item", "fact", "decision"]
ClaimType = Literal["fact", "opinion", "prediction", "requirement", "decision"]
QuestionKind = Literal["explicit", "implicit"]


SEGMENT_TYPES = frozenset({
    "statement", "note_candidate", "task_candidate", "list_candidate",
    "list_item_candidate", "question", "other",
})
ARTIFACT_TYPES = frozenset({"note", "task", "list", "list_item", "fact", "decision"})
CLASSIFICATION_TYPES = ARTIFACT_TYPES | {"question"}
CLAIM_TYPES = frozenset({"fact", "opinion", "prediction", "requirement", "decision"})
QUESTION_KINDS = frozenset({"explicit", "implicit"})
CAPTURE_ACTIONS = frozenset({"none", "save_note", "save_task", "save_list", "save_list_item"})
CAPTURE_ACTION_TYPE = {
    "save_note": "note", "save_task": "task", "save_list": "list",
    "save_list_item": "list_item",
}

CONTENT_FAMILY = {
    "note": "note",
    "task": "task",
    "list": "list",
    "list_item": "list",
    "fact": "claim",
    "decision": "claim",
    "question": "question",
}

SEGMENT_TO_CLASSIFICATION = {
    "statement": "fact",
    "note_candidate": "note",
    "task_candidate": "task",
    "list_candidate": "list",
    "list_item_candidate": "list_item",
    "question": "question",
    "other": "fact",
}


DEICTIC_LIST_INSTRUCTION = re.compile(
    r"^\s*(?:und\s+)?(?:bitte\s+)?(?:schreib|schreibe|setz|setze|pack|packe)"
    r"\s+(?:mir\s+)?(?:das|es)\s+(?:bitte\s+)?auf\s+eine\s+liste\b",
    re.I,
)


def is_deictic_list_instruction(text):
    return isinstance(text, str) and bool(DEICTIC_LIST_INSTRUCTION.search(text))


def _iso_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_classification(source_text, classification, artifact_content=None):
    """Return stable reason codes for an invalid candidate classification."""
    if not isinstance(classification, dict):
        return ["classification_not_object"]
    errors = []
    candidate = classification.get("candidate_type")
    alternative = classification.get("alternative_type")
    if candidate not in CLASSIFICATION_TYPES:
        errors.append("unknown_candidate_type")
    if alternative is not None and alternative not in CLASSIFICATION_TYPES:
        errors.append("unknown_alternative_type")

    confidence = classification.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("invalid_confidence")
    data = classification.get("normalized_data", {})
    if not isinstance(data, dict):
        errors.append("normalized_data_not_object")
        data = {}
    evidence = classification.get("evidence_spans", [])
    if not isinstance(evidence, list) or any(not isinstance(span, str) or not span.strip() for span in evidence):
        errors.append("invalid_evidence_spans")
        evidence = []
    else:
        folded = (source_text or "").casefold()
        if any(span.casefold() not in folded for span in evidence):
            errors.append("evidence_not_in_source")
    missing = classification.get("missing_fields", [])
    if not isinstance(missing, list) or any(not isinstance(field, str) for field in missing):
        errors.append("invalid_missing_fields")
        missing = []
    if missing:
        errors.append("required_fields_missing")
    if classification.get("abstain"):
        errors.append("classifier_abstained")

    content = artifact_content if artifact_content is not None else source_text
    if candidate in ARTIFACT_TYPES and (not isinstance(content, str) or not content.strip()):
        errors.append("artifact_content_empty")
    if candidate == "question" and artifact_content is not None:
        errors.append("question_uses_separate_store")
    if candidate == "task":
        due_raw = data.get("due_at")
        start_raw = data.get("work_start_at")
        urgency = data.get("urgency")
        if not due_raw and urgency is None:
            errors.append("task_requires_due_or_urgency")
        if urgency is not None and (isinstance(urgency, bool) or not isinstance(urgency, (int, float)) or not 0 <= urgency <= 1):
            errors.append("invalid_task_urgency")
        try:
            due = _iso_datetime(due_raw)
            start = _iso_datetime(start_raw)
            if due and start and start > due:
                errors.append("task_start_after_due")
        except (TypeError, ValueError):
            errors.append("invalid_task_time")
        normalized_content = data.get("content")
        if normalized_content is not None and (not isinstance(normalized_content, str) or not normalized_content.strip()):
            errors.append("invalid_task_content")
        if isinstance(normalized_content, str) and re.search(
            r"\b(?:heute|morgen|übermorgen|vormittag|mittag|nachmittag|abend)\b", normalized_content, re.I
        ):
            errors.append("task_content_contains_relative_time")
    elif candidate == "list":
        title = data.get("list_title") or content
        if not isinstance(title, str) or not title.strip():
            errors.append("list_requires_title")
        if is_deictic_list_instruction(source_text):
            errors.append("list_requires_explicit_content")
    elif candidate == "list_item":
        items = data.get("items")
        if items is None:
            # The rule router (semantic_router.py) always proposes every item
            # enumerated in one sentence together in a single call, filling
            # `normalized_data.target_list`/`items` itself -- that shape is
            # validated below when `items` is present. An LLM-proposed single
            # list_item (one call per segmentation-identified
            # list_item_candidate segment, see artifacts.py's
            # _router_overrides) naturally has no batch to describe; it
            # carries its one item as `content`/artifact_content, and its
            # target list as the operation's own `topic_titles`, which this
            # generic classification validator never sees (only artifacts.py
            # does). Demanding a normalized_data target here regardless is
            # demanding a field this call shape has no reason to produce, and
            # the model's actual choice of key for it proved unstable across
            # calls (`parent_list`, then nothing at all) -- silently dropping
            # every such item either way. The real gate against an unlinked
            # item is promote_session_artifacts()'s own `not topic_title`
            # check at promotion time; this only needs the item's text itself,
            # already required generically above (`artifact_content_empty`).
            # Real case: session 1388 on 2026-09-12, three items open in the
            # transcript, zero ever created.
            pass
        elif not isinstance(items, list) or not items or any(not isinstance(item, str) or not item.strip() for item in items):
            errors.append("list_item_requires_items")
        if items is not None and (not isinstance(data.get("target_list"), str) or not data["target_list"].strip()):
            errors.append("list_item_requires_target")
    elif candidate == "decision" and data.get("decision_status") not in {"open", "decided"}:
        errors.append("decision_requires_status")

    if not evidence:
        errors.append("evidence_required")
    return list(dict.fromkeys(errors))


def classification_is_valid(source_text, classification, artifact_content=None):
    return not validate_classification(source_text, classification, artifact_content)


def capture_result_classification(source_text, result):
    """Translate the legacy direct-capture shape into the canonical contract."""
    if not isinstance(result, dict) or result.get("action") not in CAPTURE_ACTIONS:
        raise ValueError("Unknown capture action")
    action = result["action"]
    if action == "none":
        return None
    candidate = CAPTURE_ACTION_TYPE[action]
    data = {}
    if candidate == "task":
        data = {
            "content": result.get("content", ""),
            "work_start_at": result.get("work_start_at", ""),
            "due_at": result.get("due_at", ""),
        }
        if not data["due_at"]:
            data["urgency"] = 0.4
            data["urgency_source"] = "policy_default"
    elif candidate == "list":
        data = {"list_title": result.get("list_title") or result.get("content", "")}
    elif candidate == "list_item":
        data = {"target_list": result.get("list_title", ""), "items": [result.get("content", "")]}
    classification = {
        "candidate_type": candidate, "alternative_type": None,
        "normalized_data": data, "evidence_spans": [source_text],
        "reason_codes": ["direct_capture"], "missing_fields": [],
        "confidence": 1.0, "decision_source": "llm", "abstain": False,
    }
    artifact_content = data.get("list_title") if candidate == "list" else result.get("content")
    errors = validate_classification(source_text, classification, artifact_content)
    if errors:
        raise ValueError("Invalid capture classification: " + ",".join(errors))
    return classification


def normalize_capture_result(result):
    """Clear fields that do not belong to the selected direct-capture type."""
    if not isinstance(result, dict) or result.get("action") not in CAPTURE_ACTIONS:
        raise ValueError("Unknown capture action")
    normalized = dict(result); action = normalized["action"]
    for key in ("content", "work_start_at", "due_at", "list_title"):
        if not isinstance(normalized.get(key), str):
            raise ValueError(f"Capture field {key} must be a string")
    if action != "save_task":
        normalized["work_start_at"] = ""; normalized["due_at"] = ""
    if action not in {"save_list", "save_list_item"}:
        normalized["list_title"] = ""
    if action == "none":
        normalized["content"] = ""
    return normalized
