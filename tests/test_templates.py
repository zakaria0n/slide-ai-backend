"""Tests for the smart template engine."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.templates.selector import select_template


class TestSelector:
    def test_startup_pitch(self) -> None:
        result = select_template("startup pitch for eco app")
        assert result.name == "startup_pitch"

    def test_medical(self) -> None:
        result = select_template("diagnosis and treatment plan")
        assert result.name == "medical"

    def test_finance(self) -> None:
        result = select_template("quarterly earnings report")
        assert result.name == "finance"

    def test_education(self) -> None:
        result = select_template("university lecture on machine learning")
        assert result.name == "education"

    def test_marketing(self) -> None:
        result = select_template("marketing campaign for social media")
        assert result.name == "marketing"

    def test_product(self) -> None:
        result = select_template("product launch demo")
        assert result.name == "product"

    def test_research(self) -> None:
        result = select_template("research paper on climate change")
        assert result.name == "research"

    def test_generic_fallback(self) -> None:
        result = select_template("random topic about cooking")
        assert result.name == "generic"


def test_list_templates(client: TestClient) -> None:
    res = client.get("/api/v1/templates")
    assert res.status_code == 200
    body = res.json()
    assert len(body["templates"]) >= 8
    names = [t["name"] for t in body["templates"]]
    assert "startup_pitch" in names
    assert "generic" in names


def test_suggest_template(client: TestClient) -> None:
    res = client.get("/api/v1/templates/suggest?q=startup+pitch")
    assert res.status_code == 200
    body = res.json()
    assert body["template"]["name"] == "startup_pitch"


def test_suggest_fallback(client: TestClient) -> None:
    res = client.get("/api/v1/templates/suggest?q=random+stuff")
    assert res.status_code == 200
    assert res.json()["template"]["name"] == "generic"
