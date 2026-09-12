"""Regression for the real session-1388 stuck-in-processing race (2026-09-12).

Observed live: a short voice memo ("Auf die Liste von Ausgaben ...") uploaded
as three transport chunks, all arriving fast enough that chunk 3 (which
completes the one-and-only STT window) triggered `schedule_stt_window()`
*before* the ESP's `finish` request landed. The STT job itself then finished
transcribing about half a second *before* `finish_ingestion_session_record()`
flipped `ingestion_sessions.status` to 'finished' -- so
`stabilize_transcripts()`'s own read of that status, taken from inside the
just-completed job's own completion hook (`run_stt_once()` in
services/audio.py), still saw 'open' and passed `force=False`. With exactly
one window that leaves `cutoff = contiguous - 1 = 0`, so nothing gets
confirmed. Nothing else in the pipeline ever revisits a 'provisional' window:
`stabilize_transcripts()` is otherwise only called from that one completion
hook, and `finish_client_session()`'s own `schedule_final_stt_windows()` is a
no-op replay of an idempotency key whose job already exists and is done. The
session's transcript stayed 'provisional' forever, `ingestion_chunks` never
got its row, `text_processing`/`session_artifacts` never ran, and
`client_sessions.state` sat at 'processing' indefinitely with the LLM
completely idle -- there was nothing left to retry.

Fixed in `finish_client_session()` (services/client_sessions.py): right after
`schedule_final_stt_windows()`, if no `audio_transcription` job for this
session is still queued/running, force-confirm via
`stabilize_transcripts(ingestion_id, force=True)`. That is the exact
catch-up a session in this state needed and nothing else ever provided.

This test drives the real pipeline through the same ordering that produced
the bug: upload three chunks (auto-scheduling the one STT job on the third),
consume that job with the ingestion session still 'open', assert the segment
is stuck 'provisional' exactly as observed, then call finish and assert the
whole chain unblocks all the way to `client_sessions.state == 'completed'`.
"""
import asyncio
import atexit
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from smart_notebook.app import app
from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR, CLIENT_OPERATOR_TOKEN
from smart_notebook.database import get_db_connection
from smart_notebook.services.artifacts import run_session_artifact_worker_once
from smart_notebook.services.audio import run_stt_once
from smart_notebook.services.client_sessions import finish_client_session, get_client_session
from smart_notebook.services.segmentation import run_text_processing_once

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

# CLIENT_DEVICE_AUTH_REQUIRED is a deployment toggle (this repo's .env has it
# on right now, for testing against the real ESP32), not a test concern --
# the operator token bypasses it the same way any other non-device caller
# would, per app.py's client_device_auth middleware.
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


def main():
    sid = uuid4()
    client = TestClient(app)
    root = Path(__file__).resolve().parent / "data" / "m8-test-fixtures"
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        durations = ((2.0, 330), (2.0, 440), (1.5, 550))
        offset = 0
        bounds = []
        for index, (duration, frequency) in enumerate(durations, 1):
            path = root / f"{sid}-race-{index}.m4a"
            _fixture(path, duration, frequency)
            paths.append(path)
            end = offset + int(duration * 1000)
            bounds.append((offset, end))
            offset = end

        create = client.post("/api/client/v1/sessions",
                              json={"client_session_id": str(sid), "source_type": "_contract_test_stt_race",
                                    "capture_mode": "memo"}, headers=_HEADERS)
        assert create.status_code == 201, create.text
        _CLEANUP_SESSION_IDS.append(sid)
        ingestion_id = get_client_session(sid)["ingestion_session_id"]

        # Chunk 3 is the one that auto-schedules the (only) STT window, exactly
        # as it did for the real session -- create_audio_chunk() only queues a
        # job once a full 3-chunk window exists.
        for index, ((start, end), path) in enumerate(zip(bounds, paths), 1):
            response = _upload(client, sid, index, start, end, path, f"race-{index}")
            assert response.status_code == 201, response.text

        with get_db_connection() as db:
            status = db.execute("SELECT status FROM ingestion_sessions WHERE id=%s", (ingestion_id,)).fetchone()[0]
            _CLEANUP_AUDIO_KEYS.extend(
                r[0] for r in db.execute("SELECT storage_key FROM audio_chunks WHERE session_id=%s",
                                          (ingestion_id,)).fetchall())
        assert status == "open", status

        # Consume the STT job now, deliberately before finish -- reproduces the
        # real race, where transcription finished while the session was still
        # 'open'. This test file has no database of its own (see
        # m8_client_session_night_repair_test.py's note on the same subject):
        # a real, concurrently running worker.py may claim the job before this
        # call does, so poll the job's actual status instead of trusting this
        # call's own return value.
        text = "Erstelle die Liste Regressionstest mit dem Eintrag Racebedingung."
        asyncio.run(run_stt_once("m8-race-stt", "deterministic", ingestion_id, text))
        job_status = None
        for _ in range(50):
            with get_db_connection() as db:
                job_status = db.execute(
                    "SELECT status FROM processing_jobs WHERE ingestion_session_id=%s AND job_type='audio_transcription'",
                    (ingestion_id,)).fetchone()
            if job_status and job_status[0] == "done":
                break
            asyncio.run(run_stt_once("m8-race-stt", "deterministic", ingestion_id, text))
            time.sleep(0.2)
        assert job_status and job_status[0] == "done", job_status

        with get_db_connection() as db:
            segment_status = db.execute(
                "SELECT status FROM transcript_segments WHERE session_id=%s", (ingestion_id,)).fetchall()
            chunk_count = db.execute(
                "SELECT count(*) FROM ingestion_chunks WHERE session_id=%s", (ingestion_id,)).fetchone()[0]
        # This is the bug, reproduced: transcribed, but stuck 'provisional'
        # with nothing materialized, because the session was still 'open' when
        # the job's own stabilize_transcripts() call ran.
        assert segment_status and all(s[0] == "provisional" for s in segment_status), segment_status
        assert chunk_count == 0, chunk_count

        finish_client_session(sid, 3, bounds[-1][1])

        with get_db_connection() as db:
            segment_status = db.execute(
                "SELECT status FROM transcript_segments WHERE session_id=%s", (ingestion_id,)).fetchall()
            chunk_count = db.execute(
                "SELECT count(*) FROM ingestion_chunks WHERE session_id=%s", (ingestion_id,)).fetchone()[0]
        assert segment_status and all(s[0] == "confirmed" for s in segment_status), segment_status
        assert chunk_count >= 1, chunk_count

        for _ in range(20):
            outcome = asyncio.run(run_text_processing_once("m8-race-text", "deterministic", ingestion_id))
            if outcome["outcome"] == "idle":
                break
        for _ in range(20):
            outcome = asyncio.run(run_session_artifact_worker_once("m8-race-artifacts", "deterministic", ingestion_id))
            if outcome["outcome"] == "idle":
                break

        final = None
        for _ in range(150):
            final = get_client_session(sid)
            if final["state"] == "completed":
                break
            time.sleep(0.4)
        assert final and final["state"] == "completed", final

        print("M8 STT/FINISH RACE REGRESSION (session 1388): PASS")
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
