"""High-precision local routing before generative artifact classification."""
from datetime import datetime, timedelta
import re

from ..config import TIMEZONE


ARTIFACT_TYPES = {"note", "fact", "decision", "task", "list", "list_item", "question"}
WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}
URGENCY_DEFAULT = 0.4


def _span(text, pattern):
    match = re.search(pattern, text, re.I)
    return match.group(0) if match else None


def _relative_due(text, started_at):
    started_at = started_at or datetime.now(TIMEZONE)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=TIMEZONE)
    else:
        started_at = started_at.astimezone(TIMEZONE)
    hour = 9; minute = 0
    time_match = re.search(r"\b(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*uhr\b", text, re.I)
    if time_match:
        hour = int(time_match.group(1)); minute = int(time_match.group(2) or 0)
    relative_match = re.search(r"\b(heute|morgen|übermorgen)\b", text, re.I)
    if relative_match:
        delta = {"heute": 0, "morgen": 1, "übermorgen": 2}[relative_match.group(1).casefold()]
        due = (started_at + timedelta(days=delta)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        evidence = relative_match.group(0) + (f" {time_match.group(0)}" if time_match else "")
        return due, evidence
    weekday_match = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", text, re.I)
    if not weekday_match:
        return None, None
    target = WEEKDAYS[weekday_match.group(1).casefold()]
    delta = (target - started_at.weekday()) % 7
    # A named weekday means the next occurrence when today has already started.
    if delta == 0:
        delta = 7
    due = (started_at + timedelta(days=delta)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    evidence = weekday_match.group(0) + (f" {time_match.group(0)}" if time_match else "")
    return due, evidence


def _task_window(text, started_at):
    """Separate an explicit work start from a deadline before normal routing."""
    start_match = re.search(r"\bab\s+(.+?)(?=\s+\b(?:bis|spätestens)\b|[,.!?;]|$)", text, re.I)
    due_match = re.search(r"\b(?:bis|spätestens(?:\s+bis)?)\s+([^,.!?;]+)", text, re.I)
    work_start, start_evidence = _relative_due(start_match.group(1), started_at) if start_match else (None, None)
    if due_match:
        due, due_evidence = _relative_due(due_match.group(1), started_at)
    elif start_match:
        # Do not reinterpret the start as a deadline when only "ab ..." was said.
        due, due_evidence = None, None
    else:
        due, due_evidence = _relative_due(text, started_at)
    return work_start, start_evidence, due, due_evidence


def _list_parts(text):
    target_match = re.search(r"\b(?:auf|in|zu|zur)\s+(?:die\s+|der\s+)?([\wÄÖÜäöüß-]*liste)\b", text, re.I)
    if not target_match:
        return None, []
    target = target_match.group(1)
    prefix = text[:target_match.start()]
    prefix = re.sub(r"^.*?\b(?:bitte\s+)?(?:setze|füge|schreibe|packe|nimm)\s+(?:außerdem\s+|noch\s+)?", "", prefix, flags=re.I)
    prefix = prefix.strip(" ,.;:")
    items = [part.strip(" ,.;:") for part in re.split(r"\s*,\s*|\s+und\s+", prefix, flags=re.I) if part.strip(" ,.;:")]
    return target, items


def route_artifact(text, session_started_at=None, active_topics=None):
    text = text.strip(); active_topics = active_topics or []
    scores = {kind: 0.0 for kind in ARTIFACT_TYPES}
    reasons = []; evidence = []; normalized = {}; missing = []

    target, items = _list_parts(text)
    if target and items:
        scores["list_item"] = 0.99
        reasons += ["explicit_list_target", "enumerated_items" if len(items) > 1 else "explicit_list_item"]
        evidence += [target] + items
        normalized = {"target_list": target, "items": items}

    open_decision = _span(text, r"\b(?:entscheiden\s+wir|wird\s+entschieden|entscheidung\s+.*?\s+erfolgt|ob\s+.+?\s+ist\s+noch\s+offen)\b")
    closed_decision = _span(text, r"\b(?:wir\s+haben\s+entschieden|beschlossen\s+ist|wir\s+beschließen)\b")
    if open_decision:
        scores["decision"] = max(scores["decision"], 0.96)
        reasons.append("future_or_open_decision"); evidence.append(open_decision)
        normalized = {**normalized, "decision_status": "open"}
    elif closed_decision:
        scores["decision"] = max(scores["decision"], 0.98)
        reasons.append("explicit_committed_decision"); evidence.append(closed_decision)
        normalized = {**normalized, "decision_status": "decided"}

    question_signal = text.endswith("?") or _span(text, r"^(wer|wann|warum|wie|was|wo|welche?r?|kann|soll)\b")
    if question_signal:
        scores["question"] = 0.98; reasons.append("explicit_question")
        evidence.append(question_signal if isinstance(question_signal, str) else text)

    task_signal = _span(text, r"\b(muss|müssen|soll|sollen|übernimmt|bitte|zu erledigen|kümmert sich)\b")
    work_start, work_start_evidence, due, due_evidence = _task_window(text, session_started_at)
    explicit_urgency = _span(text, r"\b(sehr wichtig|dringend|sofort|unverzüglich|höchste priorität)\b")
    if task_signal and scores["list_item"] < 0.9 and scores["decision"] < 0.9:
        scores["task"] = 0.94 if due or work_start else 0.86
        reasons.append("action_or_responsibility"); evidence.append(task_signal)
        if work_start:
            normalized["work_start_at"] = work_start.isoformat(); normalized["work_start_source"] = "explicit_relative"
            evidence.append(work_start_evidence)
        if due:
            normalized["due_at"] = due.isoformat(); normalized["due_source"] = "explicit_relative"
            evidence.append(due_evidence)
        if explicit_urgency:
            normalized["urgency"] = 0.9; normalized["urgency_source"] = "explicit"
            reasons.append("explicit_urgency"); evidence.append(explicit_urgency)
        elif not due:
            normalized["urgency"] = URGENCY_DEFAULT; normalized["urgency_source"] = "policy_default"
            reasons.append("policy_default_urgency")

    if max(scores.values()) == 0:
        scores["fact"] = 0.62; scores["note"] = 0.58
        reasons.append("declarative_statement")

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    candidate, confidence = ordered[0]; alternative, alternative_score = ordered[1]
    abstain = confidence < 0.75 or confidence - alternative_score < 0.15
    if candidate == "list_item" and not items:
        missing.append("items"); abstain = True
    if candidate == "decision" and "decision_status" not in normalized:
        missing.append("decision_status"); abstain = True
    if candidate == "task" and not normalized.get("due_at") and normalized.get("urgency") is None:
        missing.append("due_or_urgency"); abstain = True
    return {
        "candidate_type": candidate, "alternative_type": alternative,
        "candidate_scores": scores, "confidence": confidence,
        "evidence_spans": list(dict.fromkeys(x for x in evidence if x)),
        "reason_codes": list(dict.fromkeys(reasons)), "missing_fields": missing,
        "normalized_data": normalized, "abstain": abstain,
        "decision_source": "rules", "active_topics": active_topics,
    }


def validate_route(text, route):
    if route.get("candidate_type") not in ARTIFACT_TYPES:
        return False, ["unknown_candidate_type"]
    errors = []
    for span in route.get("evidence_spans", []):
        if span.casefold() not in text.casefold():
            errors.append("evidence_not_in_source")
    data = route.get("normalized_data", {})
    if route["candidate_type"] == "task" and not data.get("due_at") and data.get("urgency") is None:
        errors.append("task_requires_due_or_urgency")
    if route["candidate_type"] == "list_item" and (not data.get("target_list") or not data.get("items")):
        errors.append("list_item_requires_target_and_items")
    if route["candidate_type"] == "decision" and data.get("decision_status") not in {"open", "decided"}:
        errors.append("decision_requires_status")
    if route.get("abstain"):
        errors.append("router_abstained")
    return not errors, errors
