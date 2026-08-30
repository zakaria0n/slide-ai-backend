"""MCP endpoint tests — JSON-RPC handshake, listing and tool calls."""
from __future__ import annotations

from uuid import uuid4


def _rpc(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}


def _headers() -> dict:
    from tests.test_generation_routes import _auth, _token

    return _auth(_token("12345678-1234-1234-1234-123456789012"))


def _post(client, payload: dict) -> dict:
    res = client.post("/api/v1/mcp", json=payload, headers=_headers())
    assert res.status_code == 200, res.text
    return res.json()


def test_mcp_requires_auth(client) -> None:
    res = client.post("/api/v1/mcp", json=_rpc("tools/list"))
    assert res.status_code == 401


def test_mcp_initialize_handshake(client) -> None:
    body = _post(client, _rpc("initialize", {"protocolVersion": "2025-06-18"}))
    result = body["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "Slide AI"


def test_mcp_initialize_downgrades_old_client(client) -> None:
    body = _post(client, _rpc("initialize", {"protocolVersion": "1999-01-01"}))
    assert body["result"]["protocolVersion"] in {"2024-11-05", "2025-03-26", "2025-06-18"}


def test_mcp_tools_list(client) -> None:
    body = _post(client, _rpc("tools/list"))
    names = {t["name"] for t in body["result"]["tools"]}
    assert {"list_presentations", "create_presentation", "generate_presentation",
            "update_slide", "set_element_animation", "add_element"} <= names
    for tool in body["result"]["tools"]:
        assert "inputSchema" in tool and tool["inputSchema"]["type"] == "object"


def test_mcp_notification_returns_202(client) -> None:
    res = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=_headers(),
    )
    assert res.status_code == 202


def test_mcp_unknown_method(client) -> None:
    body = _post(client, _rpc("does/not/exist"))
    assert body["error"]["code"] == -32601


def test_mcp_create_and_get_presentation(client) -> None:
    created = _post(client, _rpc("tools/call", {
        "name": "create_presentation",
        "arguments": {"title": "From Claude Code"},
    }, 7))["result"]
    text = created["content"][0]["text"]
    pid = __import__("json").loads(text)["id"]

    got = _post(client, _rpc("tools/call", {
        "name": "get_presentation",
        "arguments": {"presentation_id": pid},
    }, 8))["result"]["content"][0]["text"]
    assert "From Claude Code" in got


def test_mcp_list_presentations(client) -> None:
    body = _post(client, _rpc("tools/call", {"name": "list_presentations", "arguments": {}}))
    text = body["result"]["content"][0]["text"]
    assert "presentations" in text


def test_mcp_update_slide_persists(client) -> None:
    created = _post(client, _rpc("tools/call", {
        "name": "create_presentation",
        "arguments": {"title": "Editable deck"},
    }))["result"]["content"][0]["text"]
    import json as _json
    pid = _json.loads(created)["id"]

    res = _post(client, _rpc("tools/call", {
        "name": "update_slide",
        "arguments": {"presentation_id": pid, "slide_index": 0, "title": "New MCP title"},
    }))["result"]["content"][0]["text"]
    assert '"success": true' in res.replace("True", "true").lower() or "success" in res

    got = _post(client, _rpc("tools/call", {
        "name": "get_presentation",
        "arguments": {"presentation_id": pid},
    }))["result"]["content"][0]["text"]
    assert "New MCP title" in got


def test_mcp_unknown_tool_reports_in_band(client) -> None:
    body = _post(client, _rpc("tools/call", {"name": "nope", "arguments": {}}))
    result = body["result"]
    assert "Unknown tool" in result["content"][0]["text"]


def test_mcp_tool_error_surfaced_in_band(client) -> None:
    body = _post(client, _rpc("tools/call", {
        "name": "get_presentation",
        "arguments": {"presentation_id": str(uuid4())},
    }))
    assert "not found" in body["result"]["content"][0]["text"].lower()


def test_mcp_read_then_patch_element_flow(client) -> None:
    """The full agent loop: create → read elements with indexes → patch one."""
    import json as _json

    created = _post(client, _rpc("tools/call", {
        "name": "create_presentation",
        "arguments": {"title": "Element Control"},
    }))["result"]["content"][0]["text"]
    pid = _json.loads(created)["id"]

    # 1. Read elements (untruncated, with indexes).
    read = _json.loads(_post(client, _rpc("tools/call", {
        "name": "get_slide_elements",
        "arguments": {"presentation_id": pid, "slide_index": 0},
    }))["result"]["content"][0]["text"])
    assert read["element_count"] == 2
    assert read["elements"][0]["element_index"] == 0
    title_idx = next(e["element_index"] for e in read["elements"] if e["type"] == "title")

    # 2. Patch that exact element (text + free position + animation).
    patched = _post(client, _rpc("tools/call", {
        "name": "update_element",
        "arguments": {
            "presentation_id": pid,
            "slide_index": 0,
            "element_index": title_idx,
            "text": "Agent-controlled title",
            "x": 20, "y": 30, "w": 60,
            "animation": "fade",
        },
    }))["result"]["content"][0]["text"]
    assert '"success": true' in patched or "Updated element" in patched

    # 3. Verify persistence.
    got = _json.loads(_post(client, _rpc("tools/call", {
        "name": "get_slide_elements",
        "arguments": {"presentation_id": pid, "slide_index": 0},
    }))["result"]["content"][0]["text"])
    el = got["elements"][title_idx]
    assert el["text"] == "Agent-controlled title"
    assert (el["x"], el["y"], el["w"]) == (20, 30, 60)
    assert el["animation"] == "fade"


def test_mcp_move_element(client) -> None:
    import json as _json

    created = _post(client, _rpc("tools/call", {
        "name": "create_presentation",
        "arguments": {"title": "Reorder deck"},
    }))["result"]["content"][0]["text"]
    pid = _json.loads(created)["id"]

    res = _post(client, _rpc("tools/call", {
        "name": "move_element",
        "arguments": {"presentation_id": pid, "slide_index": 0, "element_index": 0, "to_index": 1},
    }))["result"]["content"][0]["text"]
    assert "Moved element" in res
