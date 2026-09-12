"""Later STT-uncertainty block (BACKEND_LOGIK.md §18.3).

Combines two independent signals for an already-transcribed sentence: the
local Whisper word probabilities already present in the raw response
(`transcript_segments.weak_words`, computed in `audio.py`), and an
independent LLM plausibility check of the sentence content. A high average
confidence must never hide one individually very weak word -- that is why
the local signal is evaluated per word, not on the sentence average. Only
when the two signals materially diverge (local weak, LLM plausible) does one
targeted second STT pass with a different decoding parameter arbitrate.
Nothing is silently corrected: an unresolved, handlungsrelevant ambiguity
becomes a concrete yes/no clarification instead, and a "no" answer leaves
the affected intent part unexecuted for this session rather than guessing.
"""
from datetime import datetime
import json,re

import httpx
from psycopg.types.json import Jsonb

from ..config import TIMEZONE
from ..database import get_db_connection
from ..prompts import STT_PLAUSIBILITY_SYSTEM_PROMPT
from .ai_tasks import get_ai_task_profile
from .audio import _normalized_transcript_text,transcribe_slice_second_pass
from .capture_intent import MUTATION_INTENTS,get_session_intent_parts
from .intelligence import create_question,get_question


ACTIONABLE_ARTIFACT_TYPES={"task","list","list_item"}

SELECT="""SELECT id,segment_id,session_id,local_signal,min_word_probability,weak_words,
llm_verdict,reason_codes,second_run_requested,second_run_text,second_run_agrees,status,
clarification_question_id,created_at,updated_at FROM transcript_segment_uncertainty_assessments"""


def _item(row):
    if not row:return None
    return {"id":row[0],"segment_id":row[1],"session_id":row[2],"local_signal":row[3],
            "min_word_probability":row[4],"weak_words":row[5] or [],"llm_verdict":row[6],
            "reason_codes":row[7] or [],"second_run_requested":row[8],"second_run_text":row[9],
            "second_run_agrees":row[10],"status":row[11],"clarification_question_id":row[12],
            "created_at":row[13].isoformat(),"updated_at":row[14].isoformat()}


def get_segment_uncertainty_assessment(segment_id):
    with get_db_connection() as c:
        row=c.execute(SELECT+" WHERE segment_id=%s",(segment_id,)).fetchone()
    return _item(row)


def get_session_stt_uncertainty_for_question(question_id):
    with get_db_connection() as c:
        rows=c.execute(SELECT+" WHERE clarification_question_id=%s ORDER BY id",(question_id,)).fetchall()
    return [_item(row) for row in rows]


def stt_uncertainty_clarification_options(question_id):
    """Deliberately binary: this clarification only ever confirms or rejects
    the original transcript, never accepts a free rewrite (see module
    docstring -- a wrong guess here must not silently become new "truth")."""
    if not get_session_stt_uncertainty_for_question(question_id):return []
    return [{"label":"Ja","content":"Ja"},{"label":"Nein","content":"Nein"}]


def memo_creation_part_ids(session_id,part_ids):
    """`session_intent_parts.target_type` only names an EXISTING object for a
    mutation (see prompts.py: "Nutze none nur, wenn kein bestehendes Ziel
    gemeint ist") -- a `memo` part that creates a new task/list/list_item has
    no target_type of its own. What it actually creates lives on
    `session_artifacts.artifact_type`, reached the same way
    `capture_intent.py::promotable_artifact_ids_for_parts` already reaches it
    from the artifact side."""
    if not part_ids:return set()
    with get_db_connection() as c:
        rows=c.execute("""SELECT DISTINCT x.part_id FROM session_intent_part_segments x
        JOIN session_artifact_sources s ON s.segment_id=x.segment_id
        JOIN session_artifacts a ON a.id=s.artifact_id
        WHERE x.part_id=ANY(%s) AND a.session_id=%s AND a.artifact_type=ANY(%s)""",
        (list(part_ids),session_id,list(ACTIONABLE_ARTIFACT_TYPES))).fetchall()
    return {row[0] for row in rows}


def _is_affirmative(answer):
    normalized=" ".join(re.sub(r"[^\wäöüß]+"," ",(answer or "").casefold()).split())
    return normalized in {"ja","ja bitte","bestätigen","bestaetigen","stimmt","richtig"}


def _transcript_segments_for_part(part):
    if not part["source_segment_ids"]:return []
    with get_db_connection() as c:
        rows=c.execute("""SELECT ts.id,ts.window_id,ts.text,ts.source_start_ms,ts.source_end_ms,
        ts.min_word_probability,ts.weak_words FROM semantic_segments ss
        JOIN transcript_segments ts ON ts.materialized_chunk_id=ss.chunk_id
        WHERE ss.id=ANY(%s)""",(part["source_segment_ids"],)).fetchall()
    return [{"id":r[0],"window_id":r[1],"text":r[2],"source_start_ms":r[3],"source_end_ms":r[4],
             "min_word_probability":r[5],"weak_words":r[6] or []} for r in rows]


IMPLAUSIBLE_TEST_MARKER="unverständliches Kauderwelsch"


def deterministic_plausibility(text):
    """Deterministic test oracle for the LLM plausibility check, driven by the
    input text itself (same convention as capture_intent.py's
    deterministic_content_intent) so a test can choose which branch to hit."""
    implausible=IMPLAUSIBLE_TEST_MARKER in text
    return {"plausible":not implausible,"reason_codes":["deterministic_test_marker"] if implausible else []}


async def _plausibility_verdict(text,mode):
    if mode=="deterministic":return deterministic_plausibility(text)
    if mode!="llm":raise ValueError("Plausibility mode must be llm or deterministic")
    profile=get_ai_task_profile("audio.plausibility")
    schema={"type":"object","properties":{
        "plausible":{"type":"boolean"},
        "reason_codes":{"type":"array","items":{"type":"string"}}},
        "required":["plausible","reason_codes"],"additionalProperties":False}
    payload={"model":profile["model"],
        "messages":[{"role":"system","content":STT_PLAUSIBILITY_SYSTEM_PROMPT},
                    {"role":"user","content":f"SATZ: {text}"}],
        "temperature":profile["temperature"],
        "response_format":{"type":"json_schema","json_schema":{
            "name":"smart_notebook_stt_plausibility","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile["timeout_seconds"],trust_env=False) as client:
        response=await client.post(profile["endpoint"],json=payload)
        if response.is_error:
            raise RuntimeError(f"LLM request failed with HTTP {response.status_code}: {response.text[:1000]}")
    data=response.json();content=json.loads(data["choices"][0]["message"]["content"])
    if not isinstance(content.get("plausible"),bool):
        raise ValueError("Plausibility response must include a boolean 'plausible'")
    return {"plausible":content["plausible"],"reason_codes":content.get("reason_codes") or []}


async def _evaluate_segment(segment,mode,_second_pass_text_override=None):
    """Local signal already flagged this segment weak (caller's job). Returns
    (status, verdict, second_run) without persisting anything yet, so the
    caller can create one shared clarification question before the first
    unresolved row is written (transcript_segment_uncertainty_assessments
    requires a question on every unresolved row).

    `_second_pass_text_override` exists only for deterministic tests: the
    real second STT pass genuinely re-transcribes audio, but the
    deterministic test mode has no audio to diverge on its own, so a test
    that needs to exercise a disagreeing second pass supplies one directly."""
    verdict=await _plausibility_verdict(segment["text"],mode)
    if not verdict["plausible"]:
        # Both signals agree something is off -- no tie-break needed, and a
        # second pass could not add information a third opinion doesn't
        # already have consensus on.
        return "unresolved",verdict,None
    # Material divergence: local weak, LLM plausible. Arbitrate with one
    # targeted second pass using a different decoding parameter.
    second_pass_text=_second_pass_text_override if _second_pass_text_override is not None else segment["text"]
    response=await transcribe_slice_second_pass(segment["window_id"],segment["source_start_ms"],
        segment["source_end_ms"],mode,deterministic_text=second_pass_text)
    second_text=((response or {}).get("text") or "").strip()
    agrees=(not second_text) or _normalized_transcript_text(second_text)==_normalized_transcript_text(segment["text"])
    return ("confirmed" if agrees else "unresolved"),verdict,{"text":second_text,"agrees":agrees}


def _persist_assessment(segment,session_id,verdict,second_run,status,question_id):
    now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        c.execute("""INSERT INTO transcript_segment_uncertainty_assessments(segment_id,session_id,local_signal,
        min_word_probability,weak_words,llm_verdict,reason_codes,second_run_requested,second_run_text,
        second_run_agrees,status,clarification_question_id,created_at,updated_at)
        VALUES(%s,%s,'weak',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(segment_id) DO NOTHING""",
        (segment["id"],session_id,segment["min_word_probability"],Jsonb(segment["weak_words"]),
         "plausible" if verdict["plausible"] else "implausible",Jsonb(verdict["reason_codes"]),
         second_run is not None,second_run.get("text") if second_run else None,
         second_run.get("agrees") if second_run else None,status,question_id,now,now));c.commit()


def _clarification_text(part):
    target=" ".join((part["target_text"] or part["source_text"]).split())[:180]
    return f"Ich habe akustisch nicht alles sicher verstanden. Habe ich das richtig verstanden: „{target}\"?"


async def ensure_session_stt_uncertainty(session_id,intent_parts,mode="llm"):
    """Runs between A02/A03 intent-part persistence and A05 knowledge
    preflight (see client_sessions.py). Returns the set of intent_part ids
    that must be withheld from A05/A06/A07 and from memo-artifact promotion
    this pass because an action-relevant transcript span is still uncertain."""
    withheld=set()
    memo_part_ids=[p["id"] for p in intent_parts if p["primary_intent"]=="memo"]
    creation_part_ids=memo_creation_part_ids(session_id,memo_part_ids)
    for part in intent_parts:
        actionable=part["primary_intent"] in MUTATION_INTENTS or part["id"] in creation_part_ids
        if not actionable:continue
        weak_segments=[s for s in _transcript_segments_for_part(part) if s["weak_words"]]
        if not weak_segments:continue
        existing={s["id"]:get_segment_uncertainty_assessment(s["id"]) for s in weak_segments}
        to_evaluate=[s for s in weak_segments if existing[s["id"]] is None]
        evaluated=[]
        for segment in to_evaluate:
            status,verdict,second_run=await _evaluate_segment(segment,mode)
            evaluated.append((segment,status,verdict,second_run))
        already_unresolved=[a for a in existing.values() if a and a["status"]=="unresolved"]
        newly_unresolved=[e for e in evaluated if e[1]=="unresolved"]
        if already_unresolved or newly_unresolved:
            withheld.add(part["id"])
        question_id=already_unresolved[0]["clarification_question_id"] if already_unresolved else None
        if newly_unresolved and question_id is None:
            question=create_question(session_id,_clarification_text(part),"implicit",0.5,0.9,
                                      segment_ids=part["source_segment_ids"])
            question_id=question["id"] if question else None
        for segment,status,verdict,second_run in evaluated:
            _persist_assessment(segment,session_id,verdict,second_run,status,
                                 question_id if status=="unresolved" else None)
    return withheld


def blocked_artifact_ids_for_parts(session_id,withheld_part_ids):
    """Same join `capture_intent.py::promotable_artifact_ids_for_parts` already
    uses to trace an artifact back to its source intent parts -- reused here
    to keep a memo-created task/list/list_item out of promotion while its
    source span is still an unresolved STT ambiguity."""
    if not withheld_part_ids:return set()
    with get_db_connection() as c:
        rows=c.execute("""SELECT DISTINCT a.id FROM session_artifacts a
        JOIN session_artifact_sources s ON s.artifact_id=a.id
        JOIN session_intent_part_segments x ON x.segment_id=s.segment_id
        WHERE a.session_id=%s AND x.part_id=ANY(%s)""",(session_id,list(withheld_part_ids))).fetchall()
    return {row[0] for row in rows}


async def resume_stt_uncertainty_clarification(question_id,answer,mode="llm"):
    assessments=get_session_stt_uncertainty_for_question(question_id)
    unresolved=[a for a in assessments if a["status"]=="unresolved"]
    if not unresolved:return {"status":"resolved"} if assessments else None
    session_id=unresolved[0]["session_id"];now=datetime.now(TIMEZONE)
    confirmed=_is_affirmative(answer)
    with get_db_connection() as c:
        c.execute("UPDATE transcript_segment_uncertainty_assessments SET status='confirmed',updated_at=%s WHERE id=ANY(%s)",
                  (now,[a["id"] for a in unresolved]));c.commit()
    if not confirmed:
        # A rejected reading is not guessed at further -- the part stays
        # unexecuted for this session; the user can simply capture it again.
        return {"status":"cancelled","session_id":session_id}
    with get_db_connection() as c:
        part_ids={row[0] for row in c.execute("""SELECT DISTINCT x.part_id FROM session_intent_part_segments x
        JOIN semantic_segments ss ON ss.id=x.segment_id
        JOIN transcript_segments ts ON ts.materialized_chunk_id=ss.chunk_id
        WHERE ts.id=ANY(%s)""",([a["segment_id"] for a in unresolved],)).fetchall()}
    parts=[p for p in get_session_intent_parts(session_id) if p["id"] in part_ids]
    if not parts:return {"status":"resolved","session_id":session_id}
    mutation_parts=[p for p in parts if p["primary_intent"] in MUTATION_INTENTS]
    if mutation_parts:
        from .knowledge_preflight import ensure_session_knowledge_preflights
        from .mutation_targets import ensure_session_mutation_target_resolutions
        from .mutation_actions import ensure_session_mutation_actions
        await ensure_session_knowledge_preflights(session_id,mutation_parts,None,mode)
        await ensure_session_mutation_target_resolutions(session_id,mutation_parts,mode)
        await ensure_session_mutation_actions(session_id,mutation_parts,mode)
    resumed_creation_ids=memo_creation_part_ids(session_id,[p["id"] for p in parts if p["primary_intent"]=="memo"])
    if resumed_creation_ids:
        artifact_ids=blocked_artifact_ids_for_parts(session_id,resumed_creation_ids)
        if artifact_ids:
            from .promotion import promote_session_artifacts
            await promote_session_artifacts(session_id,mode,artifact_ids=list(artifact_ids))
    return {"status":"resolved","session_id":session_id}
