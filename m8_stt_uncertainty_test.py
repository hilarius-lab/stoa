"""Regression for the later STT-uncertainty block (BACKEND_LOGIK.md §18.3,
task.md Priority 4): combine local Whisper word probabilities with an
independent LLM plausibility check, arbitrate a material divergence with one
targeted second STT pass, and only surface a clarification for a
handlungsrelevant (action-relevant) ambiguity that stays unresolved.

Deterministic STT mode (`run_stt_once(...,'deterministic',...)`) never
produces real per-word probabilities -- there is no audio to derive them
from -- so the local "weak word" signal is injected directly onto the
persisted `transcript_segments` row after transcription, before the
downstream auto-capture pipeline (which includes the new
`ensure_session_stt_uncertainty` step) runs. That keeps every other row
(ingestion_chunks, semantic_segments, session_intent_parts) real and
FK-consistent, produced by the actual pipeline exactly as in production.

Covered here:
1. `_weak_word_signal` (audio.py): a high sentence average must not hide one
   individually very weak word.
2. `_evaluate_segment` (stt_uncertainty.py), all three reachable outcomes,
   exercised directly since only mode="llm" can drive a real second STT pass
   for the disagreement branch -- deterministic mode gets an explicit
   override seam for exactly this reason (see its docstring).
3. End-to-end through the real `/api/client/v1/sessions` auto-capture
   pipeline: a plain memo sentence with a locally weak word never gets an
   assessment at all (not handlungsrelevant -- no question, nothing
   withheld); a mutation-intent sentence ("Hake die Aufgabe ... ab") with a
   locally weak word that the deterministic plausibility oracle also flags
   implausible is withheld from A05/A06/A07 in this pass and gets exactly
   one clarification question.
4. `resume_stt_uncertainty_clarification` on a rejecting ("Nein") answer:
   the assessment is confirmed-closed but the result is "cancelled", and no
   mutation pipeline step is invoked for a target that was never real.

Not covered here (explicitly, not silently): the memo-creates-new-task/list
gate (`memo_creation_part_ids`) join is the same pattern already covered by
`capture_intent.py::promotable_artifact_ids_for_parts` on the artifact side;
reaching it end-to-end needs either a real LLM run (deterministic semantic
segmentation always emits `segment_type='statement'`, never
`task_candidate`/`list_candidate`) or hand-built fixture rows across five
tables, neither of which this file adds.
"""
import asyncio
import atexit
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from smart_notebook.app import app
from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR, CLIENT_OPERATOR_TOKEN
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.audio import _weak_word_signal, run_stt_once
from smart_notebook.services.client_sessions import finish_client_session, get_client_session
from smart_notebook.services.segmentation import run_text_processing_once
from smart_notebook.services.stt_uncertainty import (
    IMPLAUSIBLE_TEST_MARKER, _evaluate_segment, get_segment_uncertainty_assessment,
    resume_stt_uncertainty_clarification, stt_uncertainty_clarification_options)

_CLEANUP_SESSION_IDS = []
_CLEANUP_AUDIO_KEYS = []


def _cleanup():
    with get_db_connection() as db:
        for session_id in _CLEANUP_SESSION_IDS:
            row = db.execute("SELECT ingestion_session_id FROM client_sessions WHERE client_session_id=%s",
                              (session_id,)).fetchone()
            ingestion_id = row[0] if row else None
            db.execute("DELETE FROM client_dashboard_snapshots WHERE scope_key=%s", (f"session:{session_id}",))
            db.execute("DELETE FROM client_session_audit WHERE client_session_id=%s", (session_id,))
            db.execute("DELETE FROM client_sessions WHERE client_session_id=%s", (session_id,))
            if ingestion_id:
                db.execute("DELETE FROM ingestion_sessions WHERE id=%s", (ingestion_id,))
        db.commit()
    for key in _CLEANUP_AUDIO_KEYS:
        (Path(AUDIO_RETENTION_CACHE_DIR) / key).unlink(missing_ok=True)


atexit.register(_cleanup)

_HEADERS = {"Authorization": f"Bearer {CLIENT_OPERATOR_TOKEN}"} if CLIENT_OPERATOR_TOKEN else {}


def _fixture(path, duration, frequency):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                     "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                     "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "64k", "-ar", "48000", "-ac", "1", str(path)],
                    check=True)


def _upload(client, sid, sequence, start, end, path, chunk_id):
    with path.open("rb") as handle:
        return client.post(f"/api/client/v1/sessions/{sid}/audio-chunks",
                            files={"audio": (path.name, handle, "audio/mp4")},
                            data={"sequence": sequence, "client_chunk_id": chunk_id, "duration_ms": end - start,
                                  "source_start_ms": start, "source_end_ms": end, "codec": "aac-lc",
                                  "sample_rate_hz": 48000, "channels": 1},
                            headers=_HEADERS)


def _run_auto_capture(client, text, root):
    """Drives one auto-capture session through upload, deterministic STT,
    finish, text-processing and artifact-worker polling -- exactly the same
    real pipeline m8_stt_finish_race_test.py uses, just with capture_mode
    'auto' so intent classification (and the new STT-uncertainty step) runs."""
    sid = uuid4()
    paths = []
    durations = ((2.0, 330), (2.0, 440), (1.5, 550))
    offset = 0
    bounds = []
    for index, (duration, frequency) in enumerate(durations, 1):
        path = root / f"{sid}-{index}.m4a"
        _fixture(path, duration, frequency)
        paths.append(path)
        end = offset + int(duration * 1000)
        bounds.append((offset, end))
        offset = end

    create = client.post("/api/client/v1/sessions",
                          json={"client_session_id": str(sid), "source_type": "_contract_test_stt_uncertainty",
                                "capture_mode": "auto"}, headers=_HEADERS)
    assert create.status_code == 201, create.text
    _CLEANUP_SESSION_IDS.append(sid)
    ingestion_id = get_client_session(sid)["ingestion_session_id"]

    for index, ((start, end), path) in enumerate(zip(bounds, paths), 1):
        response = _upload(client, sid, index, start, end, path, f"chunk-{index}")
        assert response.status_code == 201, response.text

    with get_db_connection() as db:
        _CLEANUP_AUDIO_KEYS.extend(
            r[0] for r in db.execute("SELECT storage_key FROM audio_chunks WHERE session_id=%s",
                                      (ingestion_id,)).fetchall())

    asyncio.run(run_stt_once("m8-stt-uncertainty", "deterministic", ingestion_id, text))
    for path in paths:
        path.unlink(missing_ok=True)
    return sid, ingestion_id


def _mark_weak(ingestion_id, word="Testkuchen", probability=0.2):
    with get_db_connection() as db:
        segment_id = db.execute("SELECT id FROM transcript_segments WHERE session_id=%s",
                                 (ingestion_id,)).fetchone()[0]
        db.execute("UPDATE transcript_segments SET min_word_probability=%s,weak_words=%s WHERE id=%s",
                   (probability, Jsonb([{"word": word, "probability": probability}]), segment_id))
        db.commit()
    return segment_id


def _settle(sid, ingestion_id, bounds_end):
    finish_client_session(sid, 3, bounds_end)
    for _ in range(30):
        outcome = asyncio.run(run_text_processing_once("m8-stt-uncertainty-text", "deterministic", ingestion_id))
        if outcome["outcome"] == "idle":
            break
    for _ in range(30):
        outcome = asyncio.run(run_session_artifact_worker_once("m8-stt-uncertainty-artifacts", "deterministic", ingestion_id))
        if outcome["outcome"] == "idle":
            break
    final = None
    for _ in range(60):
        final = get_client_session(sid)
        if final["state"] in ("completed", "attention_required"):
            break
        time.sleep(0.2)
    return final


def test_weak_word_signal_not_masked_by_average():
    words = [{"word": "Ich", "probability": 0.99}, {"word": "mag", "probability": 0.98},
              {"word": "Kartoffelsalat", "probability": 0.15}, {"word": ".", "probability": 0.97}]
    signal = _weak_word_signal(words)
    assert signal["min_word_probability"] == 0.15, signal
    assert signal["weak_words"] == [{"word": "Kartoffelsalat", "probability": 0.15}], signal
    assert signal["avg_logprob"] > 0.7, signal  # the average alone looks fine
    print("weak-word masking check: PASS")


def test_evaluate_segment_outcomes():
    base = {"id": -1, "window_id": -1, "text": "Hake die Aufgabe Testkuchen ab.",
            "source_start_ms": 0, "source_end_ms": 1000}

    implausible_text = f"Hake die Aufgabe Testkuchen ab {IMPLAUSIBLE_TEST_MARKER}."
    status, verdict, second_run = asyncio.run(
        _evaluate_segment({**base, "text": implausible_text}, "deterministic"))
    assert status == "unresolved" and verdict["plausible"] is False and second_run is None, (status, verdict, second_run)

    status, verdict, second_run = asyncio.run(_evaluate_segment(base, "deterministic"))
    assert status == "confirmed" and verdict["plausible"] is True and second_run["agrees"] is True, (status, second_run)

    status, verdict, second_run = asyncio.run(
        _evaluate_segment(base, "deterministic", _second_pass_text_override="etwas ganz anderes"))
    assert status == "unresolved" and second_run["agrees"] is False, (status, second_run)

    print("_evaluate_segment outcome matrix: PASS")


def test_pipeline_filters_and_clarifies():
    client = TestClient(app)
    root = Path(__file__).resolve().parent / "data" / "m8-test-fixtures"
    root.mkdir(parents=True, exist_ok=True)

    # A: plain memo, no mutation/task/list keyword -- weak word present, but
    # not handlungsrelevant. No assessment, no question, must not be withheld.
    sid_a, ingestion_a = _run_auto_capture(client, "Ich mag Kartoffelsalat sehr.", root)
    segment_a = _mark_weak(ingestion_a, "Kartoffelsalat")
    final_a = _settle(sid_a, ingestion_a, 5500)
    assert final_a and final_a["state"] == "completed", final_a
    assert get_segment_uncertainty_assessment(segment_a) is None, "non-actionable content must not be assessed"
    with get_db_connection() as db:
        open_questions_a = db.execute(
            "SELECT count(*) FROM session_questions WHERE session_id=%s AND status='open'", (ingestion_a,)).fetchone()[0]
    assert open_questions_a == 0, open_questions_a

    # B: mutation intent ("hake ... aufgabe ... ab") with a weak word the
    # deterministic plausibility oracle also flags implausible -- both
    # signals agree, no second pass, immediate clarification, withheld from
    # A05/A06/A07 this pass (asserted via: no mutation_target_resolutions row
    # exists yet, because active_intent_parts excluded this part).
    text_b = f"Hake die Aufgabe Testkuchen ab {IMPLAUSIBLE_TEST_MARKER}."
    sid_b, ingestion_b = _run_auto_capture(client, text_b, root)
    segment_b = _mark_weak(ingestion_b)
    final_b = _settle(sid_b, ingestion_b, 5500)
    assert final_b and final_b["state"] in ("attention_required", "completed"), final_b

    assessment_b = get_segment_uncertainty_assessment(segment_b)
    assert assessment_b and assessment_b["status"] == "unresolved", assessment_b
    assert assessment_b["second_run_requested"] is False, assessment_b
    question_id = assessment_b["clarification_question_id"]
    assert question_id, assessment_b
    with get_db_connection() as db:
        target_rows = db.execute(
            "SELECT count(*) FROM mutation_target_resolutions WHERE session_id=%s", (ingestion_b,)).fetchone()[0]
    assert target_rows == 0, "withheld part must not reach A06 in this pass"

    options = stt_uncertainty_clarification_options(question_id)
    assert {o["label"] for o in options} == {"Ja", "Nein"}, options

    # A rejected reading closes the assessment without guessing further and
    # without touching a mutation pipeline for a target that was never real.
    result = asyncio.run(resume_stt_uncertainty_clarification(question_id, "Nein", "deterministic"))
    assert result["status"] == "cancelled", result
    assessment_after = get_segment_uncertainty_assessment(segment_b)
    assert assessment_after["status"] == "confirmed", assessment_after
    with get_db_connection() as db:
        target_rows_after = db.execute(
            "SELECT count(*) FROM mutation_target_resolutions WHERE session_id=%s", (ingestion_b,)).fetchone()[0]
    assert target_rows_after == 0, "a rejected reading must not retroactively run the mutation pipeline"

    print("M8 STT UNCERTAINTY PIPELINE (handlungsrelevant filter + clarification + reject): PASS")


def main():
    test_weak_word_signal_not_masked_by_average()
    test_evaluate_segment_outcomes()
    test_pipeline_filters_and_clarifies()


if __name__ == "__main__":
    main()
