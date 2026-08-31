from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app.api import app
from app.config import get_settings


def test_public_api_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEOS_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("RUNTIME_STEP_DELAY_MS", "0")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("ENABLE_CLOUD_CONNECTORS", "false")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/api/v1/healthz").json()["status"] == "ok"
        response = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": "api-contract"},
            json={"external_ref": "INC-2026-1042", "title": "Suspected enterprise account compromise", "source": "test", "priority": "high", "demo_case": True},
        )
        assert response.status_code == 202
        assert response.json()["case_id"] == "CASE-042"
        duplicate = client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": "api-contract"},
            json={"external_ref": "ignored", "title": "ignored", "demo_case": True},
        )
        assert duplicate.status_code == 202
        assert duplicate.json() == response.json()
        assert client.get("/api/v1/fleet").status_code == 200
        fleet = client.get("/api/v1/fleet").json()
        assert len(fleet) == 13
        assert {item["agent_id"] for item in fleet} >= {
            "cross-model-verification-agent", "training-pack-agent"
        }
        assert client.get("/api/v1/integrations").status_code == 200
        assert client.get("/api/v1/system/model-integrations").json()["evidence_plane_isolated"] is True


def test_cloud_audit_push_ids_are_deterministic_and_deduplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEOS_DB_PATH", str(tmp_path / "push.db"))
    monkeypatch.setenv("TRACEOS_STORE", "sqlite")
    monkeypatch.setenv("RUNTIME_STEP_DELAY_MS", "0")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("ENABLE_CLOUD_CONNECTORS", "false")
    monkeypatch.setattr("app.api.verify_pubsub_identity", lambda token, settings: {})
    get_settings.cache_clear()

    event = {
        "insertId": "audit-source-event-001",
        "timestamp": "2026-08-26T12:00:00Z",
        "resource": {"labels": {"project_id": "traceos-test"}},
        "protoPayload": {"resourceName": "projects/traceos-test/services/example"},
    }
    encoded = base64.b64encode(json.dumps(event).encode()).decode()
    envelope = {"message": {"messageId": "pubsub-message-001", "data": encoded}}

    with TestClient(app) as client:
        client.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": "push-contract"},
            json={"external_ref": "PUSH-TEST", "title": "Push test", "demo_case": True},
        )
        first = client.post(
            "/api/v1/ingest/cloud-audit",
            headers={"Authorization": "Bearer test-token"},
            json=envelope,
        )
        duplicate = client.post(
            "/api/v1/ingest/cloud-audit",
            headers={"Authorization": "Bearer test-token"},
            json=envelope,
        )

        assert first.status_code == 202
        assert first.json()["evidence_id"].startswith("EVID-GCP-PUSH-")
        assert duplicate.json()["status"] == "DUPLICATE_IGNORED"
        state = client.get("/api/v1/cases/CASE-042").json()
        matching = [
            item for item in state["evidence"]
            if item.get("metadata", {}).get("pubsub_message_id") == "pubsub-message-001"
        ]
        assert len(matching) == 1
        assert matching[0]["external_event_id"] == "audit-source-event-001"
