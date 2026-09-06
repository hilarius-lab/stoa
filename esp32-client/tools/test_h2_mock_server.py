"""Contract-focused tests for the local H2 mock server."""
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
import sys
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_mock_server import Store, make_server


def request(base, method, path, body=None, content_type="application/json"):
    data = None if body is None else (json.dumps(body).encode() if isinstance(body, dict) else body)
    item = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(item, timeout=2) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as response:
        return response.code, json.load(response)


def multipart(fields, audio):
    boundary = "h2mocktest"
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"x.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n".encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class MockTest(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(".work") / f"h2-test-{uuid.uuid4()}"
        self.store = Store(self.temporary)
        self.server = make_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.session = str(uuid.uuid4())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        shutil.rmtree(self.temporary)

    def create(self):
        return request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "memo",
            "source_type": "esp32_epaper_audio", "device_metadata": {"firmware_version": "test"},
        })

    def upload(self, sequence=0, chunk_id=None, audio=b"audio"):
        fields = {"sequence": sequence, "client_chunk_id": chunk_id or str(uuid.uuid4()),
                  "duration_ms": 1000, "source_start_ms": sequence * 1000,
                  "source_end_ms": (sequence + 1) * 1000,
                  "content_hash": hashlib.sha256(audio).hexdigest(), "codec": "aac",
                  "sample_rate_hz": 48000, "channels": 1}
        body, content_type = multipart(fields, audio)
        return request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/audio-chunks", body, content_type), fields

    def test_capabilities_are_contract_shaped(self):
        status, body = request(self.base, "GET", "/api/client/capabilities")
        self.assertEqual(200, status)
        self.assertEqual("1", body["contract"]["current"])
        self.assertEqual("ready", body["status"])
        self.assertTrue(body["features"]["audio_upload"])
        self.assertEqual("audio/mp4", body["audio_profiles"][0]["mime_type"])
        self.assertEqual("aac-lc", body["audio_profiles"][0]["codec"])

    def test_idempotent_create_upload_finish_and_reconcile(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first, second)
        chunk_id = str(uuid.uuid4())
        upload, _ = self.upload(chunk_id=chunk_id)
        repeat, _ = self.upload(chunk_id=chunk_id)
        self.assertEqual(201, upload[0])
        self.assertEqual(upload[1]["chunk"]["content_hash"], repeat[1]["chunk"]["content_hash"])
        status, finish = request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/finish",
                                 {"final_sequence": 0, "final_source_end_ms": 1000})
        self.assertEqual(200, status)
        self.assertEqual("completed", finish["completion_status"])
        status, reconciliation = request(self.base, "GET", f"/api/client/v1/sessions/{self.session}/reconciliation")
        self.assertEqual([0], reconciliation["received_sequences"])
        self.assertTrue(reconciliation["upload_complete"])

    def test_finish_names_the_segments_the_server_lacks(self):
        """The deadlock the device has to be able to escape.

        A server that lost a segment it had already acknowledged — a restored
        backup, a wiped store — answers finish with upload_complete false. The
        device holds a durable ACK for that segment and would never re-send it
        on its own, so the finish must say precisely which sequences are gone;
        the device demotes exactly those back to ready and uploads them again.
        """
        self.create()
        self.upload(sequence=0)
        status, finish = request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/finish",
                                 {"final_sequence": 1, "final_source_end_ms": 2000})
        self.assertEqual(200, status)
        self.assertFalse(finish["reconciliation"]["upload_complete"])
        self.assertEqual([1], finish["reconciliation"]["missing_sequences"])
        self.assertEqual([0], finish["reconciliation"]["received_sequences"])

        # Once the named segment arrives, the same finish completes.
        self.upload(sequence=1)
        status, finish = request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/finish",
                                 {"final_sequence": 1, "final_source_end_ms": 2000})
        self.assertEqual(200, status)
        self.assertEqual("completed", finish["completion_status"])
        self.assertEqual([], finish["reconciliation"]["missing_sequences"])

    def test_same_sequence_different_bytes_conflicts(self):
        self.create()
        self.upload(audio=b"one")
        status, body = self.upload(audio=b"two")[0]
        self.assertEqual(409, status)
        self.assertEqual("CHUNK_IDENTITY_CONFLICT", body["code"])
        status, reconciliation = request(self.base, "GET", f"/api/client/v1/sessions/{self.session}/reconciliation")
        self.assertEqual(1, len(reconciliation["conflicts"]))

    def test_firmware_change_does_not_conflict(self):
        """A session must survive a firmware update.

        The device sends its current firmware version and client model with
        every create. Those describe the device, not the session, so a repeated
        create after an update has to be accepted: a refused create aborts the
        pass before the segments are uploaded, and the recording would sit on
        the card undeliverable for good.
        """
        self.assertEqual(201, self.create()[0])
        status, body = request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "memo",
            "source_type": "esp32_epaper_audio",
            "device_metadata": {"firmware_version": "newer", "sequence_base": 0},
        })
        self.assertEqual(201, status)
        self.assertEqual("newer", body["device_metadata"]["firmware_version"])

        # The fields that do identify a session still conflict.
        status, body = request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "meeting",
            "source_type": "esp32_epaper_audio", "device_metadata": {"firmware_version": "test"},
        })
        self.assertEqual(409, status)
        self.assertEqual("SESSION_ID_CONFLICT", body["code"])

    def test_finish_reports_missing_sequence(self):
        self.create()
        self.upload(sequence=1)
        status, body = request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/finish", {"final_sequence": 1})
        self.assertEqual(200, status)
        self.assertEqual("uploads_pending", body["completion_status"])
        self.assertEqual([0], body["reconciliation"]["missing_sequences"])

    def test_drop_after_store_is_visible_to_reconciliation(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.store = Store(self.temporary, "drop-after-store-once")
        self.server = make_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.create()
        with self.assertRaises(Exception):
            self.upload()
        status, reconciliation = request(self.base, "GET", f"/api/client/v1/sessions/{self.session}/reconciliation")
        self.assertEqual(200, status)
        self.assertEqual([0], reconciliation["received_sequences"])

    def test_failure_scenarios_are_deterministic(self):
        temporary = self.temporary / "scenarios"
        session_id = str(uuid.uuid4())
        create = {"client_session_id": session_id, "capture_mode": "memo"}
        audio = b"scenario"
        fields = {"sequence": "0", "client_chunk_id": str(uuid.uuid4()),
                  "duration_ms": "1000", "source_start_ms": "0", "source_end_ms": "1000",
                  "content_hash": hashlib.sha256(audio).hexdigest()}

        failing = Store(temporary / "fail", "fail-first-upload")
        self.assertEqual(201, failing.create(create).status)
        self.assertEqual(503, failing.upload(session_id, fields, audio, "audio/mp4").status)
        self.assertEqual(201, failing.upload(session_id, fields, audio, "audio/mp4").status)

        invalid = Store(temporary / "invalid", "invalid-ack-once")
        self.assertEqual(201, invalid.create(create).status)
        self.assertFalse(invalid.upload(session_id, fields, audio, "audio/mp4").body["durable_ack"])
        self.assertTrue(invalid.upload(session_id, fields, audio, "audio/mp4").body["durable_ack"])

    def test_entity_detail(self):
        """The detail view opens an entity referenced by a dashboard card."""
        status, body = request(self.base, "GET",
                               "/api/client/v1/entities/question/00000000-0000-0000-0000-000000000002")
        self.assertEqual(200, status)
        for field in ("id", "type", "status", "created_at", "updated_at"):
            self.assertIn(field, body)
        self.assertEqual("question", body["type"])
        self.assertIn("question", body)

        # A type that does not match the id must not resolve.
        status, _ = request(self.base, "GET",
                            "/api/client/v1/entities/note/00000000-0000-0000-0000-000000000002")
        self.assertEqual(404, status)
        status, _ = request(self.base, "GET",
                            "/api/client/v1/entities/note/00000000-0000-0000-0000-00000000dead")
        self.assertEqual(404, status)

    def test_release_is_not_the_chunk_ack(self):
        """The retention release is a separate, later statement.

        A durable chunk ACK says the bytes arrived. Only
        `local_audio_release_allowed` says the server has durably kept them and
        the device may delete its copy. Confusing the two is how a recording
        gets lost, so the mock must keep them apart: released stays false while
        the upload is acknowledged but the session is not finished.
        """
        self.create()
        self.upload(sequence=0)
        status, session = request(self.base, "GET", f"/api/client/v1/sessions/{self.session}")
        self.assertEqual(200, status)
        self.assertFalse(session["local_audio_release_allowed"])
        self.assertIsNone(session["local_audio_release_at"])

        status, finish = request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/finish",
                                 {"final_sequence": 0, "final_source_end_ms": 1000})
        self.assertEqual("completed", finish["completion_status"])
        self.assertTrue(finish["session"]["local_audio_release_allowed"])

        # Monotone: a repeated finish does not move the timestamp.
        released_at = finish["session"]["local_audio_release_at"]
        self.assertIsNotNone(released_at)
        status, again = request(self.base, "POST", f"/api/client/v1/sessions/{self.session}/finish",
                                {"final_sequence": 0, "final_source_end_ms": 1000})
        self.assertEqual(released_at, again["session"]["local_audio_release_at"])

        status, body = request(self.base, "GET",
                               f"/api/client/v1/sessions/{uuid.uuid4()}")
        self.assertEqual(404, status)
        self.assertEqual("SESSION_NOT_FOUND", body["code"])

    def test_sequence_base_cannot_be_changed_afterwards(self):
        """The counting base is identity, and it is settled once.

        `sequence_base` decides what every sequence number in every upload
        means. It used to travel inside `device_metadata`, which the contract
        also allows a retry to replace — so a later request could have
        redefined the numbering of a session already half uploaded. It is a
        top-level field now, read from the old place only on the very first
        create so that older firmware is not stranded.
        """
        status, body = request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "memo",
            "source_type": "esp32_epaper_audio", "sequence_base": 0,
            "device_metadata": {"firmware_version": "test"},
        })
        self.assertEqual(201, status)
        self.assertEqual(0, body["sequence_base"])

        # A retry that says something else is a conflict, not a silent switch.
        status, body = request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "memo",
            "source_type": "esp32_epaper_audio", "sequence_base": 1,
            "device_metadata": {"firmware_version": "test"},
        })
        self.assertEqual(409, status)
        self.assertEqual("SESSION_ID_CONFLICT", body["code"])

        # The legacy position is ignored once the session exists, so an old
        # retry cannot move the base either.
        status, body = request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "memo",
            "source_type": "esp32_epaper_audio",
            "device_metadata": {"firmware_version": "old", "sequence_base": 1},
        })
        self.assertEqual(201, status)
        self.assertEqual(0, body["sequence_base"])
        # And it never lands in the stored metadata.
        self.assertNotIn("sequence_base", body["device_metadata"])

        # On a first create it still counts, so older firmware is not stranded.
        self.session = str(uuid.uuid4())
        status, body = request(self.base, "POST", "/api/client/v1/sessions", {
            "client_session_id": self.session, "capture_mode": "memo",
            "source_type": "esp32_epaper_audio",
            "device_metadata": {"firmware_version": "old", "sequence_base": 0},
        })
        self.assertEqual(201, status)
        self.assertEqual(0, body["sequence_base"])

    def test_drop_scenario_can_outlast_a_client_retry(self):
        """A fault that fires once is absorbed by the device's own retry.

        The device repeats a request whose reused connection failed, so a
        single dropped acknowledgement never reaches the reconciliation path it
        was written to exercise. `drop-after-store-twice` outlasts that retry;
        the segment is stored both times, and the client has to learn about it
        from the reconciliation instead of from the upload.
        """
        store = Store(self.temporary / "twice", scenario="drop-after-store-twice")
        server = make_server("127.0.0.1", 0, store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            self.base = base
            self.create()
            for _ in range(2):
                try:
                    self.upload(sequence=0, audio=b"audio")
                except Exception:
                    pass  # a dropped reply looks like a broken connection
            status, reconciliation = request(
                base, "GET", f"/api/client/v1/sessions/{self.session}/reconciliation")
            self.assertEqual(200, status)
            # Stored despite the silence, exactly once, and discoverable.
            self.assertEqual([0], reconciliation["received_sequences"])
            self.assertTrue(reconciliation["chunks"][0]["durable_ack"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_session_list_pages(self):
        """A constrained client asks for a window of the history.

        Entries run to roughly 520 bytes. Without paging the response outgrows
        an embedded receive buffer after about a dozen recordings and keeps
        growing for the life of the device, so the history view stops working
        the longer the product is used.
        """
        ids = []
        for _ in range(5):
            self.session = str(uuid.uuid4())
            ids.append(self.session)
            self.create()
        status, all_rows = request(self.base, "GET", "/api/client/v1/sessions")
        self.assertEqual(200, status)
        self.assertEqual(5, len(all_rows))

        status, page = request(self.base, "GET", "/api/client/v1/sessions?limit=2")
        self.assertEqual(200, status)
        self.assertEqual(2, len(page))
        self.assertEqual([row["client_session_id"] for row in all_rows[:2]],
                         [row["client_session_id"] for row in page])

        status, second = request(self.base, "GET", "/api/client/v1/sessions?limit=2&offset=2")
        self.assertEqual([row["client_session_id"] for row in all_rows[2:4]],
                         [row["client_session_id"] for row in second])

        # A nonsensical window is ignored rather than turned into an error: the
        # history is a read-only view and must not fail over a bad parameter.
        status, body = request(self.base, "GET", "/api/client/v1/sessions?limit=abc")
        self.assertEqual(200, status)
        self.assertEqual(5, len(body))

    def test_session_list_is_newest_first(self):
        """The history view needs sessions ordered by creation, newest first."""
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        for session in (first, second):
            request(self.base, "POST", "/api/client/v1/sessions",
                    {"client_session_id": session, "capture_mode": "memo",
                     "source_type": "esp32_epaper_audio", "device_metadata": {}})
        status, body = request(self.base, "GET", "/api/client/v1/sessions")
        self.assertEqual(200, status)
        self.assertIsInstance(body, list)
        identifiers = [item["client_session_id"] for item in body]
        self.assertIn(first, identifiers)
        self.assertIn(second, identifiers)
        timestamps = [item["created_at"] for item in body]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        for field in ("client_session_id", "state", "capture_mode", "created_at", "updated_at"):
            self.assertIn(field, body[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
