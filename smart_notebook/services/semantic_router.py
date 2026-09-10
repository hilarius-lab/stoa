"""High-precision local routing before generative artifact classification."""
from datetime import datetime, timedelta
import re

from ..config import TIMEZONE
from .content_types import CLASSIFICATION_TYPES, validate_classification


ARTIFACT_TYPES = CLASSIFICATION_TYPES
WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}
DAYPART_WINDOWS = {
    "früh": (6, 9), "vormittag": (8, 12), "mittag": (12, 14),
    "nachmittag": (12, 18), "abend": (18, 22),
}
URGENCY_DEFAULT = 0.4


def _span(text, pattern):
    match = re.search(pattern, text, re.I)
    return match.group(0) if match else None


def _relative_due(text, started_at, boundary="due"):
    started_at = started_at or datetime.now(TIMEZONE)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=TIMEZONE)
    else:
        started_at = started_at.astimezone(TIMEZONE)
    daypart_match = re.search(r"\b(früh|vormittag|mittag|nachmittag|abend)\b", text, re.I)
    hour = DAYPART_WINDOWS[daypart_match.group(1).casefold()][0 if boundary == "start" else 1] if daypart_match else 9
    minute = 0
    time_match = re.search(r"\b(?:um\s+)?(\d{1,2})(?::(\d{2}))?\s*uhr\b", text, re.I)
    if time_match:
        hour = int(time_match.group(1)); minute = int(time_match.group(2) or 0)
    relative_match = re.search(r"\b(heute|morgen|übermorgen)\b", text, re.I)
    if relative_match:
        delta = {"heute": 0, "morgen": 1, "übermorgen": 2}[relative_match.group(1).casefold()]
        due = (started_at + timedelta(days=delta)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        evidence = relative_match.group(0)
        if daypart_match:evidence += f" {daypart_match.group(0)}"
        if time_match:evidence += f" {time_match.group(0)}"
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
    evidence = weekday_match.group(0)
    if daypart_match:evidence += f" {daypart_match.group(0)}"
    if time_match:evidence += f" {time_match.group(0)}"
    return due, evidence


def _task_window(text, started_at):
    """Separate an explicit work start from a deadline before normal routing."""
    start_match = re.search(r"\bab\s+(.+?)(?=\s+\b(?:bis|spätestens)\b|[,.!?;]|$)", text, re.I)
    due_match = re.search(r"\b(?:bis|spätestens(?:\s+bis)?)\s+([^,.!?;]+)", text, re.I)
    work_start, start_evidence = _relative_due(start_match.group(1), started_at, "start") if start_match else (None, None)
    if due_match:
        due, due_evidence = _relative_due(due_match.group(1), started_at)
    elif start_match:
        # Do not reinterpret the start as a deadline when only "ab ..." was said.
        due, due_evidence = None, None
    else:
        if re.search(r"\b(früh|vormittag|mittag|nachmittag|abend)\b", text, re.I):
            work_start, start_evidence = _relative_due(text, started_at, "start")
            due, due_evidence = _relative_due(text, started_at, "due")
        else:
            due, due_evidence = _relative_due(text, started_at)
    return work_start, start_evidence, due, due_evidence


def _display_phrase(value):
    value = value.strip(" ,.;:!?\"'")
    return value[:1].upper() + value[1:] if value else value


def _contextual_list_parts(text):
    implicit = re.search(
        r"(?P<context>\bnach\s+(?:dem|der|den|einem|einer)\s+[^,.!?]+?)\s+"
        r"(?:will|möchte)\s+ich\s+(?P<item>[^,.!?]+?)"
        r"(?:\s*,\s*|\s*[.!?;]\s*)"
        r"(?:schreib|schreibe|setz|setze|pack|packe)\s+(?:das|es)\s+auf\s+eine\s+liste\b",
        text, re.I,
    )
    if implicit:
        return _display_phrase(implicit.group("context")), [_display_phrase(implicit.group("item"))], "implicit_list_context"
    create = re.search(
        r"\b(?:erstelle|erstell|lege|leg)\s+(?:mir\s+)?(?:eine\s+)?liste\s+"
        r"(?:über|für|zum\s+thema)\s*,?\s*(?P<topic>.+)$", text, re.I,
    )
    if not create:
        return None, [], None
    topic = create.group("topic").strip(" ,.;:!?")
    contextual = re.search(r"\b(nach\s+(?:dem|der|den|einem|einer)\s+.+?)(?=\s+(?:alles|machen|erledigen|will|möchte)\b|$)", topic, re.I)
    title = contextual.group(1) if contextual else topic
    title = re.sub(r"^(?:was|dinge|sachen)\s+(?:ich|wir)\s+", "", title, flags=re.I)
    return _display_phrase(title), [], "explicit_list_creation"


def _list_parts(text):
    target, items, reason = _contextual_list_parts(text)
    if target:
        return target, items, reason
    target_match = re.search(r"\b(?:auf|in|zu|zur)\s+(?:die\s+|der\s+)?([\wÄÖÜäöüß-]*liste)\b", text, re.I)
    if not target_match:
        return None, [], None
    target = target_match.group(1)
    if target.casefold() == "liste":
        return None, [], None
    prefix = text[:target_match.start()]
    prefix = re.sub(r"^.*?\b(?:bitte\s+)?(?:setze|füge|schreibe|packe|nimm)\s+(?:außerdem\s+|noch\s+)?", "", prefix, flags=re.I)
    prefix = prefix.strip(" ,.;:")
    items = [part.strip(" ,.;:") for part in re.split(r"\s*,\s*|\s+und\s+", prefix, flags=re.I) if part.strip(" ,.;:")]
    return target, items, "explicit_list_target"


def _concise_task_content(text):
    if re.search(r"listen\s+nicht\s+erstellt\s+werden\s+können", text, re.I):
        return "Listenerstellung im Smart Notebook reparieren" if re.search(r"smart\s+notebook", text, re.I) else "Listenerstellung reparieren"
    content = text.strip(" ,.;:!?")
    content = re.sub(r"^(?:heute|morgen|übermorgen)(?:\s+(?:früh|vormittag|mittag|nachmittag|abend))?\s+", "", content, flags=re.I)
    content = re.sub(r"^(?:ich|wir)\s+(?:muss|müssen|soll|sollen|möchte|wollen)\s+(?:noch\s+)?", "", content, flags=re.I)
    content = re.sub(r"^(?:muss|müssen|soll|sollen|möchte|wollen)\s+(?:ich|wir)\s+(?:noch\s+)?", "", content, flags=re.I)
    content = re.sub(r"\b(?:heute|morgen|übermorgen)(?:\s+(?:früh|vormittag|mittag|nachmittag|abend))?\b", "", content, flags=re.I)
    content = re.sub(r"\b(?:am\s+)?(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)(?:\s+um\s+\d{1,2}(?::\d{2})?\s*uhr)?\b", "", content, flags=re.I)
    content = re.sub(r"\bum\s+\d{1,2}(?::\d{2})?\s*uhr\b", "", content, flags=re.I)
    content = " ".join(content.split()).strip(" ,.;:!?")
    content = re.sub(r"^(?:(?:ab|bis|spätestens)\s+)+", "", content, flags=re.I)
    return _display_phrase(content)


def route_artifact(text, session_started_at=None, active_topics=None):
    text = text.strip(); active_topics = active_topics or []
    scores = {kind: 0.0 for kind in ARTIFACT_TYPES}
    reasons = []; evidence = []; normalized = {}; missing = []

    target, items, list_reason = _list_parts(text)
    if target:
        if items:
            scores["list_item"] = 0.99
            reasons += [list_reason, "enumerated_items" if len(items) > 1 else "explicit_list_item"]
            evidence += [span for span in [target] + items if span.casefold() in text.casefold()]
            normalized = {"target_list": target, "items": items}
        elif list_reason == "explicit_list_creation":
            scores["list"] = 0.99
            reasons.append(list_reason);evidence.append(text)
            normalized = {"list_title": target}

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
        normalized["content"] = _concise_task_content(text)
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
    errors = [error for error in validate_classification(text, route) if error != "classifier_abstained"]
    if route.get("abstain") and "router_abstained" not in errors:
        errors.append("router_abstained")
    return not errors, errors
