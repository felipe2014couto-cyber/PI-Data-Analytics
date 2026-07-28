"""Tests for the PI Web API health endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.pi.errors import (
    PiAuthError,
    PiInvalidResponseError,
    PiSSLError,
    PiTimeoutError,
    PiUnavailableError,
)


def _configure_pi() -> None:
    settings = get_settings()
    settings.pi_web_api_base_url = "https://pi.local/piwebapi"
    settings.pi_data_server_name = "PI_DATA"
    settings.pi_web_api_auth_mode = "none"


def test_pi_health_unconfigured(client: TestClient) -> None:
    settings = get_settings()
    settings.pi_web_api_base_url = None
    settings.pi_data_server_name = None

    response = client.get("/api/pi/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_configured"
    assert body["base_url"] is None
    assert body["data_server"] is None
    assert "message" in body


def test_pi_health_connected(client: TestClient) -> None:
    _configure_pi()

    response = client.get("/api/pi/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected"
    assert body["base_url"] == "https://pi.local/piwebapi"
    assert body["data_server"] == "PI_DATA"
    assert isinstance(body["response_time_ms"], int)
    assert client.fake_provider.ping_calls == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "exc,expected_code",
    [
        (PiAuthError(), "PI_AUTH_FAILED"),
        (PiTimeoutError(), "PI_TIMEOUT"),
        (PiSSLError(), "PI_SSL_ERROR"),
        (PiUnavailableError(), "PI_UNAVAILABLE"),
        (PiInvalidResponseError(), "PI_INVALID_RESPONSE"),
    ],
)
def test_pi_health_unavailable(client: TestClient, exc, expected_code) -> None:
    _configure_pi()
    client.fake_provider._raise_on_ping = exc  # type: ignore[attr-defined]

    response = client.get("/api/pi/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["error_code"] == expected_code
    # Ensure no password or authorization data leaks.
    text = response.text.lower()
    assert "authorization" not in text
    assert "password" not in text
    assert "bearer" not in text
