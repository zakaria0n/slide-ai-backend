"""Tests for health endpoints using FakeAsyncClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


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
    assert "OpenCode" not in res.text
    assert "Zen" not in res.text


def test_docs_available(client: TestClient) -> None:
    res = client.get("/docs")
    assert res.status_code == 200