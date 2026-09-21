import asyncio
import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.coordinator import EventCoordinator
from app.main import create_app


def settings():
    return Settings(
        _env_file=None,
        internal_api_key="internal-secret",
        forge_webhook_secret="forge-secret",
        ingestion_internal_api_key="ingestion-secret",
    )


def test_capabilities_are_read_only():
    with TestClient(create_app(settings())) as client:
        response = client.get("/v1/capabilities")
    assert response.status_code == 200
    assert response.json()["write"] == []
    assert response.json()["writeEnabled"] is False


def test_metrics_are_exposed_without_content_payloads():
    with TestClient(create_app(settings())) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "pi_atlassian_events_total" in response.text


def test_mutation_is_always_rejected():
    with TestClient(create_app(settings())) as client:
        response = client.post(
            "/v1/internal/mutations",
            headers={"X-Internal-Api-Key": "internal-secret"},
            json={"operation": "createIssue", "arguments": {}},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ATLASSIAN_WRITE_DISABLED"


def test_signed_event_is_accepted_once():
    payload = b'{"eventId":"event-1","eventType":"avi:jira:updated:issue","eventCreatedAt":"2026-09-11T12:00:00Z","cloudId":"cloud","resourceType":"ISSUE","resourceId":"1001","parentResourceId":null,"projectOrSpaceId":"T0","applicationProjectId":"T2.0","selfGenerated":false}'
    timestamp = str(int(time.time()))
    signature = (
        "sha256="
        + hmac.new(b"forge-secret", timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    )
    headers = {
        "content-type": "application/json",
        "X-Atlassian-Timestamp": timestamp,
        "X-Atlassian-Signature-256": signature,
    }
    with TestClient(create_app(settings())) as client:
        first = client.post("/v1/events/atlassian", headers=headers, content=payload)
        second = client.post("/v1/events/atlassian", headers=headers, content=payload)
    assert first.status_code == 202 and first.json()["accepted"] is True
    assert second.status_code == 202 and second.json()["duplicate"] is True


def test_user_read_never_falls_back_to_service_identity():
    configured = settings()
    configured.rovo_service_token = "s" * 32
    with TestClient(create_app(configured)) as client:
        response = client.post(
            "/v1/internal/search",
            headers={"X-Internal-Api-Key": "internal-secret"},
            json={
                "projectId": "P1",
                "userId": "U1",
                "identityClass": "USER",
                "tool": "search",
                "query": "T0-7",
            },
        )
    assert response.status_code == 401


def test_service_identity_cannot_impersonate_user():
    with TestClient(create_app(settings())) as client:
        response = client.post(
            "/v1/internal/search",
            headers={"X-Internal-Api-Key": "internal-secret"},
            json={
                "projectId": "P1",
                "userId": "U1",
                "identityClass": "SERVICE",
                "tool": "search",
                "query": "T0-7",
            },
        )
    assert response.status_code == 422


def test_basic_service_auth_requires_a_username():
    with pytest.raises(ValidationError, match="Rovo username"):
        Settings(
            _env_file=None,
            rovo_service_auth_mode="BASIC",
            rovo_service_token="token",
        )


def test_recovery_reports_project_discovery_failure_and_can_retry(monkeypatch):
    coordinator = EventCoordinator(settings())
    attempts = 0

    async def projects():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("backend unavailable")
        return ()

    monkeypatch.setattr(coordinator, "_projects", projects)
    asyncio.run(coordinator.catch_up())
    assert coordinator.last_failure == "project_discovery:RuntimeError"
    asyncio.run(coordinator.catch_up())
    assert coordinator.last_failure == "project_discovery:no_authorized_projects"


def test_freshness_reports_provider_scopes_independently():
    configured = settings()
    app = create_app(configured)
    app.state.coordinator.freshness_by_scope["P1:JIRA"] = {
        "state": "FRESH",
        "lastCompletedAt": 1.0,
        "lastFailure": None,
    }
    app.state.coordinator.freshness_by_scope["P1:CONFLUENCE"] = {"state": "IN_PROGRESS"}
    with TestClient(app) as client:
        response = client.get("/v1/freshness")

    assert response.status_code == 200
    assert response.json()["scopes"]["P1:JIRA"]["state"] == "FRESH"
    assert response.json()["scopes"]["P1:CONFLUENCE"]["state"] == "IN_PROGRESS"
