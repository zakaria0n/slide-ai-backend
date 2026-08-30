"""Tests for vision probing, 72h MCP tokens, chat screenshots and custom mode."""
from __future__ import annotations

import json
import time

import jwt as pyjwt
import pytest

from app.core.vision import interpret_probe_response
from app.chat.schemas import SendChatRequest


# --- vision probe verdict ------------------------------------------------------


def test_probe_positive_when_color_named() -> None:
    assert interpret_probe_response(200, "red", "") is True


def test_probe_negative_when_model_cannot_see() -> None:
    assert interpret_probe_response(200, "", "The user wants the color. However, I cannot see an image.") is False


def test_probe_negative_on_http_error() -> None:
    assert interpret_probe_response(400, "red", "") is False
    assert interpret_probe_response(503, "", "") is False


# --- chat screenshot validation -------------------------------------------------


def test_screenshot_accepts_valid_data_url() -> None:
    req = SendChatRequest(message="hi", screenshot="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==")
    assert req.screenshot.startswith("data:image/png;base64,")


def test_screenshot_accepts_line_wrapped_base64() -> None:
    wrapped = "data:image/png;base64,iVBO\nRw0K\nGgo="
    req = SendChatRequest(message="hi", screenshot=wrapped)
    assert "\n" not in req.screenshot


def test_screenshot_rejects_non_data_url() -> None:
    with pytest.raises(Exception):
        SendChatRequest(message="hi", screenshot="https://evil.example/img.png")
    with pytest.raises(Exception):
        SendChatRequest(message="hi", screenshot="data:text/html;base64,PGI+")


# --- 72h MCP token --------------------------------------------------------------


def test_mcp_token_mints_72h_verifiable_token(client) -> None:
    from tests.test_generation_routes import _auth, _token

    uid = "12345678-1234-1234-1234-123456789012"
    res = client.post("/api/v1/auth/mcp-token", headers=_auth(_token(uid)))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expires_in"] == 72 * 3600
    assert body["purpose"] == "mcp"

    # The minted token must authenticate against a protected endpoint.
    me = client.get("/api/v1/auth/me", headers=_auth(body["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["id"] == uid


def test_mcp_token_requires_auth(client) -> None:
    res = client.post("/api/v1/auth/mcp-token")
    assert res.status_code == 401


# --- custom theme (MCP default + generation) ------------------------------------


def test_mcp_generate_defaults_to_custom_theme(client) -> None:
    """generate_presentation via MCP must default to theme=custom."""
    from tests.test_generation_routes import _auth, _token

    headers = _auth(_token("22345678-1234-1234-1234-123456789012"))

    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "generate_presentation",
            "arguments": {"prompt": "Deep dive on coral reefs", "slide_count": 3},
        },
    }
    res = client.post("/api/v1/mcp", json=rpc, headers=headers)
    assert res.status_code == 200, res.text
    payload = json.loads(res.json()["result"]["content"][0]["text"])
    pid = payload["id"]

    spec_res = client.get(f"/api/v1/presentations/{pid}/spec", headers=headers)
    assert spec_res.status_code == 200
    assert spec_res.json()["meta"]["theme"] == "custom"
