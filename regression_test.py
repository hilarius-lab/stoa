"""Automated A1-C3 API, idempotency and restart regression test.

Starts an isolated local API process on port 8012. It uses the configured PostgreSQL
database, but creates uniquely marked test records and removes only those records.
No LLM call is made; workers run in deterministic mode.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from smart_notebook.config import TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.tasks import save_task


ROOT = Path(__file__).resolve().parent
PORT = 8012
BASE = f"http://127.0.0.1:{PORT}"


def request(method, path, body=None, expected=200):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=15) as response:
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        status = exc.code
        payload = json.loads(exc.read().decode("utf-8"))
    if status != expected:
        raise AssertionError(f"{method} {path}: expected HTTP {expected}, got {status}: {payload}")
    return payload


def start_server():
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Test server exited with code {process.returncode}")
        try:
            request("GET", "/api/debug")
            return process
        except Exception:
            time.sleep(0.2)
    stop_server(process)
    raise TimeoutError("Test server did not become ready")


def stop_server(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=5)


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def main():
    token = uuid4().hex
    session_id = None
    note_id = None
    signal_subject_id = None
    task_id = None
    promoted_knowledge = []
    server = None
    checks = []
    try:
        server = start_server()
        session = request("POST", "/api/ingestion-sessions", {
            "source_type": "automated-regression", "title": f"A1-C1 regression {token}", "source": "regression_test.py"
        })
        session_id = session["id"]
        checks.append("session creation")

        chunks = [
            {"sequence": 1, "client_chunk_id": f"{token}-1", "text": "Das Projekt Atlas wird am Freitag um 15 Uhr abgegeben.", "source_start_ms": 0, "source_end_ms": 5000},
            {"sequence": 2, "client_chunk_id": f"{token}-2", "text": "Wer übernimmt die Qualitätskontrolle?", "source_start_ms": 5000, "source_end_ms": 9000},
        ]
        first = request("POST", f"/api/ingestion-sessions/{session_id}/chunks", chunks[0])
        duplicate = request("POST", f"/api/ingestion-sessions/{session_id}/chunks", chunks[0])
        assert_true(first["id"] == duplicate["id"], "identical chunk was not idempotent")
        conflict = dict(chunks[0], text="Conflicting payload")
        request("POST", f"/api/ingestion-sessions/{session_id}/chunks", conflict, expected=409)
        request("POST", f"/api/ingestion-sessions/{session_id}/chunks", chunks[1])
        checks.append("chunk idempotency and conflict")

        request("POST", f"/api/ingestion-sessions/{session_id}/finalize", {"force": False}, expected=409)
        request("POST", f"/api/ingestion-sessions/{session_id}/finish")
        repair = request("POST", f"/api/ingestion-sessions/{session_id}/repair", {"dry_run": False, "stale_after_minutes": 15})
        assert_true(repair["applied_action_count"] == 2, "repair did not queue both chunks")

        run1 = request("POST", "/api/workers/text-processing/run-once", {
            "worker_id": f"{token}-text-1", "mode": "deterministic", "ingestion_session_id": session_id
        })
        assert_true(run1["outcome"] == "completed" and run1["job"]["sequence"] == 1, "sequence 1 processing failed")

        crashed = request("POST", "/api/processing-jobs/claim", {
            "worker_id": f"{token}-crashed", "job_type": "text_processing", "ingestion_session_id": session_id
        })
        assert_true(crashed and crashed["sequence"] == 2 and crashed["status"] == "running", "restart job was not claimed")
        stop_server(server); server = None
        server = start_server()
        persisted = request("GET", f"/api/processing-jobs/{crashed['id']}")
        assert_true(persisted["status"] == "running", "running job did not survive restart")
        with get_db_connection() as connection:
            connection.execute("UPDATE processing_jobs SET locked_at=%s,updated_at=%s WHERE id=%s AND ingestion_session_id=%s",
                (datetime.now(TIMEZONE)-timedelta(minutes=2), datetime.now(TIMEZONE)-timedelta(minutes=2), crashed["id"], session_id))
            connection.commit()
        repaired = request("POST", f"/api/ingestion-sessions/{session_id}/repair", {"dry_run": False, "stale_after_minutes": 1})
        assert_true(any(a["action"] == "requeue_stale_job" for a in repaired["actions"]), "stale lock was not recovered")
        run2 = request("POST", "/api/workers/text-processing/run-once", {
            "worker_id": f"{token}-text-2", "mode": "deterministic", "ingestion_session_id": session_id
        })
        assert_true(run2["outcome"] == "completed" and run2["job"]["attempts"] == 2, "restarted job did not retry")
        checks.append("process restart and stale-lock recovery")

        for index in (1, 2):
            result = request("POST", "/api/workers/session-artifacts/run-once", {
                "worker_id": f"{token}-artifact-{index}", "mode": "deterministic", "ingestion_session_id": session_id
            })
            assert_true(result["outcome"] == "completed", f"artifact worker {index} failed")
        state = request("GET", f"/api/ingestion-sessions/{session_id}/processing-state")
        wm = state["watermarks"]
        assert_true(wm["received_through_sequence"] == wm["processed_through_sequence"] == wm["artifact_through_sequence"] == 2,
            f"watermarks are not contiguous: {wm}")
        checks.append("contiguous processing and artifact watermarks")

        evidence1 = request("POST", f"/api/ingestion-sessions/{session_id}/evidence/generate")["evidence"]
        evidence2 = request("POST", f"/api/ingestion-sessions/{session_id}/evidence/generate")["evidence"]
        assert_true(len(evidence1) == len(evidence2) > 0, "evidence generation is not idempotent")
        for evidence in evidence2:
            chunk = request("GET", f"/api/ingestion-chunks/{evidence['chunk_id']}")
            actual = chunk["text"][evidence["char_start"]:evidence["char_end"]]
            assert_true(actual == evidence["quote_text"], "evidence character offsets are incorrect")
        checks.append("idempotent evidence and exact offsets")

        artifacts = request("GET", f"/api/ingestion-sessions/{session_id}/artifacts")
        subject = next((item for item in artifacts if item["artifact_type"] in {"note", "fact", "decision"}), artifacts[0])
        signal_subject_id = subject["id"]
        request("POST", f"/api/session-artifacts/{subject['id']}/confirm")
        for activity_type in ("retrieved", "activated", "displayed", "opened", "cited"):
            request("POST", "/api/knowledge-activity", {
                "knowledge_type": "session_artifact", "knowledge_id": subject["id"],
                "activity_type": activity_type, "session_id": session_id,
                "metadata": {"test_run": token}
            })
        activity = request("GET", f"/api/knowledge-activity?knowledge_type=session_artifact&knowledge_id={subject['id']}")
        assert_true(len(activity) == 5, "knowledge activity log is incomplete")
        signals = request("POST", f"/api/knowledge/session_artifact/{subject['id']}/signals/refresh")
        assert_true(signals["evidence_count"] >= 1 and signals["activation_count"] == 2 and signals["access_count"] == 3,
            f"knowledge signal counts are incorrect: {signals}")
        assert_true(0 < signals["importance_score"] <= 1 and signals["trend_score"] > 0,
            f"importance/trend scores are outside expected bounds: {signals}")
        ranked = request("GET", "/api/knowledge-signals?knowledge_type=session_artifact")
        assert_true(any(item["knowledge_id"] == subject["id"] for item in ranked), "signal ranking did not include subject")
        checks.append("knowledge activity, importance and trend signals")

        detected = request("POST", f"/api/ingestion-sessions/{session_id}/questions/detect")
        assert_true(detected["detected"] == 1, "explicit question was not detected")
        question = detected["questions"][0]
        duplicate_question = request("POST", f"/api/ingestion-sessions/{session_id}/questions", {
            "question_text": question["question_text"], "question_kind": "explicit", "confidence": 1, "priority": 1,
            "segment_ids": question["source_segment_ids"]
        })
        assert_true(duplicate_question["id"] == question["id"], "question deduplication failed")
        answered = request("POST", f"/api/session-questions/{question['id']}/answer", {
            "answer_text": "Lisa übernimmt die Qualitätskontrolle.", "answer_source": "meeting"
        })
        reopened = request("POST", f"/api/session-questions/{question['id']}/reopen")
        assert_true(answered["status"] == "answered" and reopened["status"] == "open", "question lifecycle failed")
        checks.append("question detection, deduplication and lifecycle")

        with get_db_connection() as connection:
            now = datetime.now(TIMEZONE)
            note_id = connection.execute("INSERT INTO notes(content,created_at,updated_at,archived) VALUES(%s,%s,%s,FALSE) RETURNING id",
                (f"Regression knowledge {token}", now, now)).fetchone()[0]
            connection.commit()
        fast = request("GET", f"/api/personal-knowledge/fast-path?q=Regression%20knowledge%20{token}")
        assert_true(not fast["external_research_needed"] and any(r["knowledge_id"] == note_id for r in fast["results"]),
            "personal knowledge fast path failed")
        checks.append("personal-knowledge fast path")

        task_id=save_task(f"Undated task {token}",None,[0.0]*1024,priority=2,urgency=0.85)
        task=request("GET",f"/api/tasks/{task_id}")
        assert_true(task["due_at"] is None and task["priority"]==2 and task["urgency"]==0.85,"undated task fields failed")
        done=request("POST",f"/api/tasks/{task_id}/done");reopened=request("POST",f"/api/tasks/{task_id}/reopen")
        assert_true(done["percent_complete"]==100 and reopened["percent_complete"]==0,"CalDAV-compatible task lifecycle failed")
        checks.append("undated tasks, priority, urgency and progress")

        # A controlled confirmed fact isolates promotion semantics from the
        # conservative artifact extraction policy used above.
        with get_db_connection() as connection:
            now = datetime.now(TIMEZONE)
            connection.execute("""INSERT INTO session_artifacts(
                session_id,artifact_type,content,status,confidence,origin_key,created_at,updated_at
            ) VALUES(%s,'fact',%s,'confirmed',1.0,%s,%s,%s)""",
                (session_id, f"Promotion fact {token}", f"regression-promotion:{token}", now, now))
            connection.commit()
        direct_promotion = request("POST", f"/api/ingestion-sessions/{session_id}/artifacts/promote", {"mode": "deterministic"})
        assert_true(len(direct_promotion["promoted"]) > 0, f"confirmed artifacts were not promoted: {direct_promotion}")
        final1 = request("POST", f"/api/ingestion-sessions/{session_id}/finalize", {"force": False,"promotion_mode":"deterministic"})
        final2 = request("POST", f"/api/ingestion-sessions/{session_id}/finalize", {"force": False,"promotion_mode":"deterministic"})
        promoted_knowledge=final1.get("promotion",{}).get("promoted",[])
        assert_true(final1["status"] == final2["status"] == "completed", "finalization is not idempotent")
        assert_true(len(promoted_knowledge) > 0, "promoted artifacts were not returned idempotently")
        second_promotion = final2.get("promotion", {}).get("promoted", [])
        assert_true(all(item["idempotent"] for item in second_promotion), "artifact promotion is not idempotent")
        checks.append("guarded finalization and idempotent artifact promotion")

        print("A1-C3 REGRESSION TEST: PASS")
        for check in checks:
            print(f"[OK] {check}")
    finally:
        stop_server(server)
        with get_db_connection() as connection:
            connection.execute("DELETE FROM knowledge_activity WHERE metadata->>'test_run'=%s", (token,))
            if signal_subject_id is not None:
                connection.execute("DELETE FROM knowledge_signals WHERE knowledge_type='session_artifact' AND knowledge_id=%s", (signal_subject_id,))
            if session_id is not None:
                connection.execute("DELETE FROM ingestion_sessions WHERE id=%s AND source_type='automated-regression'", (session_id,))
            if note_id is not None:
                connection.execute("DELETE FROM notes WHERE id=%s AND content=%s", (note_id, f"Regression knowledge {token}"))
            if task_id is not None:
                connection.execute("DELETE FROM tasks WHERE id=%s AND content=%s",(task_id,f"Undated task {token}"))
            for promoted in promoted_knowledge:
                table={"note":"notes","task":"tasks","list":"lists","list_item":"list_items"}.get(promoted.get("knowledge_type"))
                if table:connection.execute(f"DELETE FROM {table} WHERE id=%s",(promoted["knowledge_id"],))
            connection.commit()


if __name__ == "__main__":
    main()
