"""M8 API discovery, compatibility, error-envelope and OpenAPI regression."""
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from smart_notebook.client_openapi import canonical_client_openapi

ROOT = Path(__file__).resolve().parent


def main():
    with TestClient(app) as client:
        health = client.get("/api/client/health")
        assert health.status_code == 200
        assert health.json()["contract_version"] == "1"
        assert health.headers["x-smart-notebook-contract"] == "1"

        capabilities = client.get("/api/client/capabilities").json()
        assert capabilities["contract"]["api_base"] == "/api/client/v1"
        assert capabilities["audio_profiles"][0] == {
            "id": "android_aac_lc_v1", "mime_type": "audio/mp4",
            "container": "mp4", "codec": "aac-lc", "sample_rate_hz": 48000,
            "channels": 1, "bitrate_bps": 64000, "target_segment_ms": 10000,
            "max_chunk_bytes": 2097152,
        }
        assert capabilities["features"]["session_recovery"] is True

        incompatible = client.get(
            "/api/client/v1/contract",
            headers={"X-Smart-Notebook-Contract": "999", "X-Request-ID": "m8-test"},
        )
        assert incompatible.status_code == 409
        assert incompatible.json() == {
            "code": "API_INCOMPATIBLE",
            "message": "The requested client contract is not supported.",
            "retry_class": "user_action",
            "request_id": "m8-test",
            "details": {"supported_versions": ["1"]},
            "timestamp": incompatible.json()["timestamp"],
        }

        missing = client.get("/api/client/v1/not-present")
        assert missing.status_code == 404
        assert missing.json()["code"] == "RESOURCE_NOT_FOUND"

    expected = (ROOT / "contracts" / "client-openapi-v1.json").read_text(encoding="utf-8")
    assert canonical_client_openapi(app) == expected, "Client OpenAPI snapshot changed"
    print("M8 CONTRACT FOUNDATION TEST: PASS")


if __name__ == "__main__":
    main()
