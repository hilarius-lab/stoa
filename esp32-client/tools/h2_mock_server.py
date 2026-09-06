"""Persistent local implementation of the ESP32-facing H2 wire contract.

This is deliberately a protocol test double, not a miniature backend. It stores
opaque audio bytes and just enough metadata to exercise create, upload, finish,
retry and reconciliation from the device.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

CONTRACT = "1"
SESSION_RE = re.compile(
    r"^/api/client/v1/sessions/([0-9a-fA-F-]{36})/(audio-chunks|finish|reconciliation|dashboard)$"
)
ENTITY_RE = re.compile(r"^/api/client/v1/entities/([a-z_]{1,32})/([0-9a-fA-F-]{36})$")
# The three cards the demo dashboard shows, so the detail view has something
# real to open. Keyed by the ids used in the snapshot above.
DEMO_ENTITIES = {
    "00000000-0000-0000-0000-000000000001": {
        "type": "task", "status": "open", "title": "Rückmeldung zum Konzept geben",
        "description": "Vor dem nächsten Termin",
        "content": "Das Konzept für die Gerätebedienung liegt seit Montag vor. "
                   "Offen sind die Rückfragen zur Tastenbelegung und zur Frage, "
                   "ob der Verlauf eine eigene Ansicht bekommt.",
        "priority": 2.0,
    },
    "00000000-0000-0000-0000-000000000002": {
        "type": "question", "status": "open", "title": "Wie soll die Session heißen?",
        "description": "Offene Rückfrage aus der letzten Memo",
        "question": "Soll die Aufnahme vom Dienstag unter dem Projektnamen oder "
                    "unter dem Datum abgelegt werden?",
        "question_kind": "clarification",
        "answer": None, "answer_source": None, "confidence": 0.62,
    },
    "00000000-0000-0000-0000-000000000003": {
        "type": "note", "status": "active", "title": "ESP-Dashboard",
        "description": "Hochformat und servergesteuerte Karten",
        "content": "Der Client rendert ausschließlich den geschlossenen Katalog. "
                   "Farbrollen werden monochrom als Rasterstufen abgebildet, "
                   "Artsymbole sitzen auf einer freigestellten Plakette.",
    },
}

SCENARIOS = {
    "normal",
    "drop-after-store-once",
    # Twice, so the device's own retry cannot paper over it and the ACK has to
    # be recovered through reconciliation — which is the path under test.
    "drop-after-store-twice",
    "fail-first-upload",
    "invalid-ack-once",
    "maintenance",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with temporary.open("r+b") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


def error(code: str, message: str, retry_class: str, **details: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "retry_class": retry_class,
        "request_id": str(uuid.uuid4()),
        "timestamp": now(),
        "details": details,
    }


def capabilities(status: str = "ready") -> dict[str, Any]:
    return {
        "contract": {"current": CONTRACT, "supported": [CONTRACT], "api_base": "/api/client/v1"},
        "server": {"version": "h2-mock-1", "time": now()},
        "status": status,
        "status_message": None if status in {"ready", "degraded"} else "Local mock maintenance scenario",
        "features": {
            "audio_upload": True, "audio_upload_diagnostics": False,
            "session_recovery": True, "dashboard_snapshot": True,
            "dashboard_sse": False, "offline_knowledge_sync": False,
            "chat": False, "unified_push": False,
        },
        "audio_profiles": [{
            "id": "esp32-aac-m4a-v1", "mime_type": "audio/mp4", "container": "mp4",
            "codec": "aac-lc", "sample_rate_hz": 48000, "channels": 1,
            "bitrate_bps": 64000, "target_segment_ms": 10000,
            "max_chunk_bytes": 2 * 1024 * 1024,
        }],
        "limits": {
            "request_timeout_seconds": 20, "dashboard_cards_per_section": 20,
            "live_transcript_max_segments": 0, "live_transcript_window_seconds": 0,
            "dashboard_history_hours": 0, "dashboard_cache_max_age_seconds": 0,
            "dashboard_title_max_chars": 200, "dashboard_preview_max_chars": 500,
            "dashboard_detail_max_chars": 4000, "server_raw_audio_retention_days": 1,
            "server_ephemeral_chat_retention_hours": 1,
            "server_technical_log_retention_hours": 1,
        },
        "session_states": ["created", "recording", "paused", "draining", "processing", "completed", "failed", "attention_required", "aborted"],
        "completion_states": ["uploads_pending", "processing", "completed", "failed", "attention_required", "aborted"],
        "dashboard": {
            "schema_version": "1", "component_types": ["section","entity_card"], "actions": ["open_entity"],
            "color_roles": ["neutral","info","warning"], "icon_tokens": ["task","question","note"], "border_roles": ["subtle","emphasis"],
            "spacing_roles": [], "preferred_spans": [],
            "unknown_optional_component": "ignore", "unknown_required_component": "reject",
        },
        "transports": {
            "rest": True, "sse": False, "unified_push": False,
            "foreground_refresh": "poll", "background_refresh": "poll",
            "fallback_refresh": "poll", "sse_proxy_buffering": False,
        },
    }


"""Fields that identify a session. A repeated create that agrees on these is the
same session; anything else in the create payload describes the device, not the
session, and must not be able to cause a conflict.

`sequence_base` belongs here because it changes what every sequence number in
every upload means. It used to arrive inside `device_metadata`, which the
contract simultaneously allows to be replaced on any retry — semantics in a
container for replaceable diagnostics. It is now a top-level field, stored once
and never changed; the legacy position is accepted on the first create only.

`device_metadata` is deliberately absent. It carries the firmware version and
the client model, both of which legitimately change between the moment a session
is created and the moment it is retried after a restart or an update. Comparing
it made every session that outlived a firmware change conflict forever, and
since a refused create aborts the pass before the segments are uploaded, that
session's audio could never be delivered. A device must be able to finish
delivering what it recorded before an update."""
IDENTITY_FIELDS = ("client_session_id", "capture_mode", "context_ref", "sequence_base")


def identity_matches(stored: dict[str, Any], incoming: dict[str, Any]) -> bool:
    return all(stored.get(field) == incoming.get(field) for field in IDENTITY_FIELDS)


@dataclass
class Reply:
    status: int
    body: dict[str, Any]
    drop: bool = False


class Store:
    def __init__(self, root: Path, scenario: str = "normal") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario}")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.audio = self.root / "audio"
        self.audio.mkdir(exist_ok=True)
        self.path = self.root / "state.json"
        self.lock = threading.RLock()
        self.scenario = scenario
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.state = {"sessions": {}, "scenario_hits": {}}
            self._save()

    def _save(self) -> None:
        atomic_json(self.path, self.state)

    def _hit(self, name: str, times: int = 1) -> bool:
        """True for the first `times` calls, then False for good.

        More than one is not a detail: the device retries a request once on a
        connection it had reused, so a fault that fires a single time is
        absorbed by that retry and never reaches the recovery path it was meant
        to exercise. Firing twice outlasts the retry.
        """
        hits = self.state["scenario_hits"]
        used = int(hits.get(name) or 0)
        if used >= times:
            return False
        hits[name] = used + 1
        self._save()
        return True

    def _hit_once(self, name: str) -> bool:
        return self._hit(name, 1)

    def list_sessions(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        """Past recordings, newest first. Feeds the history view.

        `limit` and `offset` are what make this endpoint usable at all from a
        constrained client: at roughly 520 bytes per entry an unbounded list
        outgrows an embedded receive buffer after a dozen or so recordings, and
        it grows for the life of the device. A list endpoint without paging is
        not a small omission — it is one that stops working the longer the
        product is used.
        """
        with self.lock:
            sessions = list(self.state["sessions"].items())
        # The identifier is the key, and the original create request holds the
        # fields the device sent.
        sessions.sort(key=lambda entry: entry[1].get("created_at", ""), reverse=True)
        if offset:
            sessions = sessions[offset:]
        if limit is not None:
            sessions = sessions[:limit]
        return [
            {
                "client_session_id": session_id,
                "state": item.get("state", "completed"),
                "capture_mode": item.get("create", {}).get("capture_mode", "memo"),
                "created_at": item.get("created_at", now()),
                "updated_at": item.get("updated_at", item.get("created_at", now())),
                "device_metadata": item.get("create", {}).get("device_metadata", {}),
                "expected_final_sequence": item.get("final_sequence"),
                "final_source_end_ms": item.get("final_source_end_ms"),
                "finalized_at": item.get("finalized_at"),
                "finish_requested_at": item.get("finish_requested_at"),
                "paused_at": None, "aborted_at": None,
                "capture_result": None, "context_ref": None,
                "last_error": item.get("last_error"),
            }
            for session_id, item in sessions
        ]

    def entity(self, entity_type: str, entity_id: str) -> Reply:
        entity = DEMO_ENTITIES.get(entity_id)
        if not entity or entity["type"] != entity_type:
            return Reply(404, error("NOT_FOUND", "entity not found", "never"))
        payload = {"id": entity_id, "created_at": now(), "updated_at": now()}
        payload.update(entity)
        return Reply(200, payload)

    def session_dashboard(self, session_id: str) -> Reply:
        """The dashboard of one past recording, in the same envelope as the home
        dashboard so the device renders it with the same code.

        A protocol double has no transcript and no derived entities, so it shows
        only what it actually knows about the session. Inventing plausible cards
        here would make the device look finished while testing nothing.
        """
        with self.lock:
            session = self.state["sessions"].get(session_id)
            if not session:
                return Reply(404, error("SESSION_NOT_FOUND", "session does not exist", "never"))
            chunks = len(session["chunks"])
            created = session.get("created_at", now())
            state = session.get("state", "completed")
            duration = session.get("final_source_end_ms")
        items = [{
            "component": "entity_card", "required": False, "id": f"session:{session_id}:state",
            "title": created.replace("T", " ")[:16],
            "preview": f"Zustand: {state}",
            "icon": "note", "color_role": "neutral", "border_role": "subtle",
        }, {
            "component": "entity_card", "required": False, "id": f"session:{session_id}:audio",
            "title": f"{chunks} Segmente",
            "preview": "Dauer unbekannt" if not duration else f"{duration // 1000} Sekunden",
            "icon": "note", "color_role": "neutral", "border_role": "subtle",
        }]
        return Reply(200, {
            "schema_version": "1", "revision": 1, "generated_at": now(), "server_time": now(),
            "scope": f"session:{session_id}", "mode": "session",
            "primary_live_session": None, "sessions": [], "processing": None,
            "sections": [{"component": "section", "required": False, "id": "session",
                          "title": "Aufnahme", "rank": 10, "items": items}],
        })

    def create(self, request: dict[str, Any]) -> Reply:
        required = request.get("client_session_id")
        try:
            session_id = str(uuid.UUID(str(required)))
        except (ValueError, TypeError, AttributeError):
            return Reply(422, error("INVALID_SESSION_ID", "client_session_id must be a UUID", "never"))
        capture_mode = request.get("capture_mode", "meeting")
        if capture_mode not in {"meeting", "memo", "query", "auto"}:
            return Reply(422, error("INVALID_CAPTURE_MODE", "unsupported capture_mode", "never"))
        metadata = dict(request.get("device_metadata") or {})
        # Stripped either way: whatever the legacy position holds, it must not
        # survive into the stored metadata, or a later retry could carry a
        # different counting base back in.
        legacy = metadata.pop("sequence_base", None)
        top = request.get("sequence_base")
        with self.lock:
            existing = self.state["sessions"].get(session_id)
            if top is not None:
                base = top
            elif existing:
                # An established session keeps the base it was created with.
                # Reading the legacy position again here is exactly how a retry
                # from older firmware would silently redefine every sequence.
                base = existing["create"].get("sequence_base", 1)
            else:
                # First create only: older firmware may still say it in the old
                # place, and refusing that would strand its recordings.
                base = legacy if legacy is not None else 1
            try:
                base = int(base)
            except (TypeError, ValueError):
                return Reply(422, error("INVALID_SEQUENCE_BASE", "sequence_base must be 0 or 1", "never"))
            if base not in (0, 1):
                return Reply(422, error("INVALID_SEQUENCE_BASE", "sequence_base must be 0 or 1", "never"))
            canonical = {
                "client_session_id": session_id,
                "capture_mode": capture_mode,
                "device_metadata": metadata,
                "context_ref": request.get("context_ref"),
                "sequence_base": base,
            }
            if existing:
                if not identity_matches(existing["create"], canonical):
                    return Reply(409, error("SESSION_ID_CONFLICT", "session id has different create data", "user_action"))
                # Descriptive metadata is refreshed rather than compared, so the
                # server always holds the newest description of the device.
                # `updated_at` stays untouched: a repeated create does not change
                # the session, and an identical create must return an identical
                # response for the retry path to be verifiable.
                if existing["create"]["device_metadata"] != canonical["device_metadata"]:
                    existing["create"]["device_metadata"] = canonical["device_metadata"]
                    self._save()
                return Reply(201, self._session(existing))
            timestamp = now()
            value = {"create": canonical, "state": "created", "chunks": {},
                     "conflicts": [], "final_sequence": None,
                     "final_source_end_ms": None, "created_at": timestamp,
                     "updated_at": timestamp, "finish_requested_at": None}
            self.state["sessions"][session_id] = value
            self._save()
            return Reply(201, self._session(value))

    def upload(self, session_id: str, fields: dict[str, str], audio: bytes, mime_type: str) -> Reply:
        with self.lock:
            session = self.state["sessions"].get(session_id)
            if not session:
                return Reply(404, error("SESSION_NOT_FOUND", "session does not exist", "never"))
            try:
                sequence = int(fields["sequence"])
                duration = int(fields["duration_ms"])
                source_start = int(fields["source_start_ms"])
                source_end = int(fields["source_end_ms"])
                chunk_id = str(uuid.UUID(fields["client_chunk_id"]))
            except (KeyError, ValueError):
                return Reply(422, error("INVALID_CHUNK_METADATA", "required chunk metadata is invalid", "never"))
            if sequence < 0 or duration < 0 or source_start < 0 or source_end < source_start:
                return Reply(422, error("INVALID_CHUNK_RANGE", "chunk ranges must be monotone", "never"))
            digest = hashlib.sha256(audio).hexdigest()
            supplied = fields.get("content_hash")
            if supplied and supplied.lower() != digest:
                return Reply(422, error("CONTENT_HASH_MISMATCH", "content_hash does not match audio", "never"))
            key = str(sequence)
            candidate = {"sequence": sequence, "client_chunk_id": chunk_id,
                         "content_hash": digest, "byte_length": len(audio),
                         "mime_type": mime_type or "application/octet-stream",
                         "codec": fields.get("codec"),
                         "sample_rate_hz": int(fields["sample_rate_hz"]) if fields.get("sample_rate_hz") else None,
                         "channels": int(fields["channels"]) if fields.get("channels") else None,
                         "duration_ms": duration, "source_start_ms": source_start,
                         "source_end_ms": source_end, "captured_at": fields.get("captured_at"),
                         "status": "stored", "retain_until": None,
                         "retain_permanently": False, "created_at": now(), "updated_at": now()}
            existing = session["chunks"].get(key)
            if existing:
                if existing["client_chunk_id"] == chunk_id and existing["content_hash"] == digest:
                    return Reply(201, self._ack(session_id, existing))
                conflict = {"sequence": sequence, "client_chunk_id": chunk_id,
                            "code": "CHUNK_IDENTITY_CONFLICT",
                            "expected": {"client_chunk_id": existing["client_chunk_id"], "content_hash": existing["content_hash"]},
                            "received": {"client_chunk_id": chunk_id, "content_hash": digest},
                            "occurred_at": now()}
                session["conflicts"].append(conflict)
                session["state"] = "attention_required"
                session["updated_at"] = now()
                self._save()
                return Reply(409, error("CHUNK_IDENTITY_CONFLICT", "sequence already has different identity or bytes", "user_action", sequence=sequence))
            if self.scenario == "fail-first-upload" and self._hit_once("fail-first-upload"):
                return Reply(503, error("MOCK_TEMPORARY_FAILURE", "deterministic first-upload failure", "backoff"))
            audio_path = self.audio / f"{session_id}-{sequence:08d}.bin"
            temporary = audio_path.with_suffix(".tmp")
            with temporary.open("wb") as handle:
                handle.write(audio)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(audio_path)
            session["chunks"][key] = candidate
            session["updated_at"] = now()
            self._save()
            reply = Reply(201, self._ack(session_id, candidate))
            if self.scenario == "drop-after-store-once" and self._hit_once("drop-after-store-once"):
                reply.drop = True
            elif self.scenario == "drop-after-store-twice" and self._hit("drop-after-store-twice", 2):
                reply.drop = True
            elif self.scenario == "invalid-ack-once" and self._hit_once("invalid-ack-once"):
                reply.body["durable_ack"] = False
            return reply

    def finish(self, session_id: str, request: dict[str, Any]) -> Reply:
        with self.lock:
            session = self.state["sessions"].get(session_id)
            if not session:
                return Reply(404, error("SESSION_NOT_FOUND", "session does not exist", "never"))
            try:
                final = int(request["final_sequence"])
                source_end = request.get("final_source_end_ms")
                source_end = int(source_end) if source_end is not None else None
            except (KeyError, ValueError, TypeError):
                return Reply(422, error("INVALID_FINISH", "finish metadata is invalid", "never"))
            if final < 0 or (source_end is not None and source_end < 0):
                return Reply(422, error("INVALID_FINISH", "finish values must be non-negative", "never"))
            if session["final_sequence"] not in (None, final) or session["final_source_end_ms"] not in (None, source_end):
                return Reply(409, error("FINISH_CONFLICT", "session was finished with different bounds", "user_action"))
            session["final_sequence"] = final
            session["final_source_end_ms"] = source_end
            session["finish_requested_at"] = session["finish_requested_at"] or now()
            reconciliation = self._reconciliation(session_id, session)
            session["state"] = "completed" if reconciliation["upload_complete"] else "draining"
            # Monotone: set once and never withdrawn.
            if session["state"] == "completed" and not session.get("local_audio_release_at"):
                session["local_audio_release_at"] = now()
            session["updated_at"] = now()
            self._save()
            reconciliation = self._reconciliation(session_id, session)
            return Reply(200, {"session": self._session(session),
                               "completion_status": "completed" if reconciliation["upload_complete"] else "uploads_pending",
                               "reconciliation": reconciliation})

    def reconcile(self, session_id: str) -> Reply:
        with self.lock:
            session = self.state["sessions"].get(session_id)
            if not session:
                return Reply(404, error("SESSION_NOT_FOUND", "session does not exist", "never"))
            return Reply(200, self._reconciliation(session_id, session))

    @staticmethod
    def _ack(session_id: str, chunk: dict[str, Any]) -> dict[str, Any]:
        return {"client_session_id": session_id, "chunk": dict(chunk), "durable_ack": True}

    @staticmethod
    def _session(session: dict[str, Any]) -> dict[str, Any]:
        create = session["create"]
        return {
            "client_session_id": create["client_session_id"], "state": session["state"],
            "device_metadata": create["device_metadata"], "capture_mode": create["capture_mode"],
            "context_ref": create["context_ref"], "capture_result": None,
            "expected_final_sequence": session["final_sequence"],
            "final_source_end_ms": session["final_source_end_ms"],
            "paused_at": None, "finish_requested_at": session["finish_requested_at"],
            "finalized_at": None, "aborted_at": None, "last_error": None,
            "created_at": session["created_at"], "updated_at": session["updated_at"],
            # Echoed so the device can check the stored counting base against
            # its own before it uploads anything.
            "sequence_base": create.get("sequence_base", 1),
            # The retention release: monotone, session-wide, and never inferred
            # by the client from a chunk ACK. A protocol double has no worker
            # chain, so it releases once the session is completed — the real
            # backend additionally requires its processing to have finished.
            "local_audio_release_allowed": bool(session.get("local_audio_release_at")),
            "local_audio_release_at": session.get("local_audio_release_at"),
        }

    @staticmethod
    def _reconciliation(session_id: str, session: dict[str, Any]) -> dict[str, Any]:
        received = sorted(int(item) for item in session["chunks"])
        final = session["final_sequence"]
        missing = [] if final is None else [item for item in range(final + 1) if item not in received]
        chunks = [{
            "sequence": value["sequence"], "client_chunk_id": value["client_chunk_id"],
            "content_hash": value["content_hash"], "byte_length": value["byte_length"],
            "status": value["status"], "source_start_ms": value["source_start_ms"],
            "source_end_ms": value["source_end_ms"], "durable_ack": True,
        } for _, value in sorted(session["chunks"].items(), key=lambda item: int(item[0]))]
        return {"client_session_id": session_id, "state": session["state"],
                "expected_final_sequence": final, "received_sequences": received,
                "missing_sequences": missing, "chunks": chunks,
                "conflicts": session["conflicts"],
                "upload_complete": final is not None and not missing and not session["conflicts"]}


def multipart(content_type: str, body: bytes) -> tuple[dict[str, str], bytes, str]:
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if not message.is_multipart():
        raise ValueError("multipart/form-data required")
    fields: dict[str, str] = {}
    audio = None
    audio_type = "application/octet-stream"
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        value = part.get_payload(decode=True) or b""
        if name == "audio":
            audio = value
            audio_type = part.get_content_type()
        elif name:
            fields[name] = value.decode("utf-8")
    if audio is None:
        raise ValueError("audio part missing")
    return fields, audio, audio_type


class Handler(BaseHTTPRequestHandler):
    server_version = "SmartNotebookH2Mock/1"

    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, template: str, *args: Any) -> None:
        print(f"{self.address_string()} {template % args}")

    def _body(self, limit: int = 3 * 1024 * 1024) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length > limit:
            raise OverflowError
        return self.rfile.read(length)

    def _send(self, reply: Reply) -> None:
        if reply.drop:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        payload = json.dumps(reply.body, separators=(",", ":")).encode()
        self.send_response(reply.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/api/client/capabilities", "/api/client/v1/contract"}:
            status = "maintenance" if self.store.scenario == "maintenance" else "ready"
            self._send(Reply(200, capabilities(status)))
            return
        if path == "/api/client/v1/dashboard":
            self._send(Reply(200, {
                "schema_version":"1","revision":1,"generated_at":now(),"server_time":now(),
                "scope":"home:esp32_epaper","mode":"idle","primary_live_session":None,
                "sessions":[],"processing":None,"sections":[
                    {"component":"section","required":False,"id":"today","title":"Heute","rank":10,"items":[
                        {"component":"entity_card","required":False,"id":"task:demo-1","title":"Rückmeldung zum Konzept geben","preview":"Vor dem nächsten Termin","icon":"task","color_role":"warning","border_role":"emphasis","entity_ref":{"type":"task","id":"00000000-0000-0000-0000-000000000001"},"action":{"type":"open_entity","params":{}}},
                        {"component":"entity_card","required":False,"id":"question:demo-2","title":"Wie soll die Session heißen?","preview":"Offene Rückfrage aus der letzten Memo","icon":"question","color_role":"info","border_role":"subtle","entity_ref":{"type":"question","id":"00000000-0000-0000-0000-000000000002"},"action":{"type":"open_entity","params":{}}},
                        {"component":"entity_card","required":False,"id":"note:demo-3","title":"ESP-Dashboard","preview":"Hochformat und servergesteuerte Karten","icon":"note","color_role":"neutral","border_role":"subtle","entity_ref":{"type":"note","id":"00000000-0000-0000-0000-000000000003"},"action":{"type":"open_entity","params":{}}}
                    ]}
                ]}))
            return
        if path == "/api/client/v1/sessions":
            # The history view lists past recordings, newest first. A client
            # that cannot hold the whole list asks for a window of it.
            query = parse_qs(urlparse(self.path).query)
            def number(name: str) -> int | None:
                try:
                    value = int(query[name][0])
                except (KeyError, ValueError, IndexError):
                    return None
                return value if value >= 0 else None
            limit = number("limit")
            self._send(Reply(200, self.store.list_sessions(limit, number("offset") or 0)))
            return
        single = re.match(r"^/api/client/v1/sessions/([0-9a-fA-F-]{36})$", path)
        if single:
            with self.store.lock:
                found = self.store.state["sessions"].get(str(uuid.UUID(single.group(1))))
            if not found:
                self._send(Reply(404, error("SESSION_NOT_FOUND", "session does not exist", "never")))
            else:
                self._send(Reply(200, self.store._session(found)))
            return
        entity = ENTITY_RE.match(path)
        if entity:
            self._send(self.store.entity(entity.group(1), entity.group(2)))
            return
        match = SESSION_RE.match(path)
        if match and match.group(2) == "reconciliation":
            self._send(self.store.reconcile(str(uuid.UUID(match.group(1)))))
            return
        if match and match.group(2) == "dashboard":
            self._send(self.store.session_dashboard(str(uuid.UUID(match.group(1)))))
            return
        self._send(Reply(404, error("NOT_FOUND", "route not found", "never")))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/client/v1/sessions":
                self._send(self.store.create(json.loads(body)))
                return
            match = SESSION_RE.match(path)
            if not match:
                self._send(Reply(404, error("NOT_FOUND", "route not found", "never")))
                return
            session_id, operation = str(uuid.UUID(match.group(1))), match.group(2)
            if operation == "audio-chunks":
                fields, audio, mime_type = multipart(self.headers.get("Content-Type", ""), body)
                self._send(self.store.upload(session_id, fields, audio, mime_type))
            elif operation == "finish":
                self._send(self.store.finish(session_id, json.loads(body)))
            else:
                self._send(Reply(405, error("METHOD_NOT_ALLOWED", "method not allowed", "never")))
        except OverflowError:
            self._send(Reply(413, error("REQUEST_TOO_LARGE", "request exceeds mock limit", "never")))
        except (ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send(Reply(422, error("INVALID_REQUEST", str(exc), "never")))


def make_server(host: str, port: int, store: Store) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.store = store  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent local H2 protocol mock")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", type=Path, default=Path(".work/h2-mock"))
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal")
    args = parser.parse_args()
    server = make_server(args.host, args.port, Store(args.data, args.scenario))
    print(f"H2 mock listening on http://{args.host}:{server.server_port} scenario={args.scenario} data={args.data}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
