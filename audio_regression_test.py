"""Repeatable N1-N7 audio API regression test without calling Ocean Whisper."""
from pathlib import Path
import io
import subprocess
import sys
import time
import wave
from uuid import uuid4

import httpx

from smart_notebook.config import AUDIO_RETENTION_CACHE_DIR
from smart_notebook.database import get_db_connection
from smart_notebook.services.audio import _render_window, _window_for_job, get_audio_chunk, schedule_final_stt_windows


ROOT = Path(__file__).resolve().parent
PORT = 8014
BASE = f"http://127.0.0.1:{PORT}"


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 4000)
    return output.getvalue()


def main():
    token = uuid4().hex
    session_id = None
    storage_paths = []
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=BASE, timeout=15) as client:
            deadline = time.time() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"test server exited with code {process.returncode}")
                try:
                    if client.get("/api/debug").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() >= deadline:
                    raise TimeoutError("test server did not become ready")
                time.sleep(0.2)

            response = client.post("/api/ingestion-sessions", json={
                "source_type": "audio-regression", "title": f"N1-N7 {token}", "source": "audio_regression_test.py"
            })
            response.raise_for_status(); session_id = response.json()["id"]

            created = []
            for sequence, (start_ms, end_ms) in enumerate(((0, 10000), (10000, 20000), (20000, 30000), (30000, 40000)), start=1):
                fields = {
                    "sequence": str(sequence), "client_chunk_id": f"{token}-{sequence}",
                    "duration_ms": "10000", "source_start_ms": str(start_ms), "source_end_ms": str(end_ms),
                }
                files = {"audio": (f"chunk-{sequence}.wav", wav_bytes(), "audio/wav")}
                response = client.post(f"/api/ingestion-sessions/{session_id}/audio-chunks", data=fields, files=files)
                response.raise_for_status(); created.append(response.json())

            # Same identity and bytes must return the original row.
            fields = {"sequence": "1", "client_chunk_id": f"{token}-1", "duration_ms": "10000", "source_start_ms": "0", "source_end_ms": "10000"}
            duplicate = client.post(f"/api/ingestion-sessions/{session_id}/audio-chunks", data=fields,
                                    files={"audio": ("chunk-1.wav", wav_bytes(), "audio/wav")})
            duplicate.raise_for_status()
            assert duplicate.json()["id"] == created[0]["id"]

            conflict = client.post(f"/api/ingestion-sessions/{session_id}/audio-chunks", data=fields,
                                   files={"audio": ("chunk-1.webm", b"different", "audio/webm")})
            assert conflict.status_code == 409

            window = _window_for_job(get_audio_chunk(created[0]["id"]))
            rendered = _render_window(window)
            try:
                assert rendered.stat().st_size > 44
            finally:
                rendered.unlink(missing_ok=True)

            # Chunk 3 queues the complete 1-3 live window. Finishing queues the
            # short 3-4 tail; no per-transport-chunk jobs may race the upload.
            client.post(f"/api/ingestion-sessions/{session_id}/finish").raise_for_status()
            schedule_final_stt_windows(session_id)
            for sequence in (1, 2):
                response = client.post("/api/workers/audio-stt/run-once", json={
                    "worker_id": f"{token}-worker-{sequence}", "mode": "deterministic",
                    "ingestion_session_id": session_id,
                    "deterministic_text": "Überlappende revidierte Hypothese." if sequence >= 2 else "Erstes Transkript."
                })
                response.raise_for_status(); assert response.json()["outcome"] == "completed", response.json()

            before = client.get(f"/api/ingestion-sessions/{session_id}/transcripts")
            before.raise_for_status(); statuses = [item["status"] for item in before.json()]
            # The final outstanding STT window stabilizes the finished session;
            # the earlier window must remain provisional until that moment.
            assert statuses == ["confirmed", "confirmed"], statuses

            stabilized = client.post(f"/api/ingestion-sessions/{session_id}/transcripts/stabilize", json={"force": True})
            stabilized.raise_for_status(); assert stabilized.json()["confirmed"] == 0
            after = client.get(f"/api/ingestion-sessions/{session_id}/transcripts")
            after.raise_for_status(); assert [item["status"] for item in after.json()] == ["confirmed", "confirmed"]

            chunks = client.get(f"/api/ingestion-sessions/{session_id}/chunks")
            chunks.raise_for_status(); assert len(chunks.json()) == 2
            audio = client.get(f"/api/ingestion-sessions/{session_id}/audio-chunks")
            audio.raise_for_status(); storage_paths = [Path(AUDIO_RETENTION_CACHE_DIR) / item["storage_key"] for item in audio.json()]

        print("N1-N7 AUDIO REGRESSION TEST: PASS")
        print("[OK] multipart upload, MIME acceptance and configurable blob storage")
        print("[OK] idempotency and conflicting-upload rejection")
        print("[OK] queued deterministic STT processing")
        print("[OK] 30-second server windows with overlapping tail window")
        print("[OK] confirmed transcript materialization into the text pipeline")
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        if session_id is not None:
            with get_db_connection() as connection:
                if not storage_paths:
                    storage_paths = [Path(AUDIO_RETENTION_CACHE_DIR) / row[0] for row in connection.execute(
                        "SELECT storage_key FROM audio_chunks WHERE session_id=%s", (session_id,)
                    ).fetchall()]
                connection.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='audio-regression'", (session_id,))
                connection.commit()
        root = Path(AUDIO_RETENTION_CACHE_DIR).resolve()
        for path in storage_paths:
            resolved = path.resolve()
            if root in resolved.parents:
                resolved.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
