"""Integration tests for the application factory and health endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_allowed_origins=["http://localhost:5173"],
    )
    # Force a local, non-resolving DB so the startup connectivity check
    # fails gracefully (logged warning) without a real Supabase instance.
    settings.database_url = "postgresql+asyncpg://u:p@127.0.0.1:1/none"
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_root_endpoint(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "Slide AI"
    assert body["docs"] == "/docs"


def test_health_endpoint_exposes_only_slide_ai(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "Slide AI"
    assert body["provider"] == "Slide AI"
    # The internal provider must never be revealed.
    assert "OpenCode" not in res.text
    assert "Zen" not in res.text


def test_docs_available(client: TestClient) -> None:
    res = client.get("/docs")
    assert res.status_code == 200
