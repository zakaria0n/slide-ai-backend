"""MCP endpoint — Model Context Protocol over Streamable HTTP (stateless).

Implements the JSON-RPC surface AI coding agents speak:
``initialize`` → ``notifications/initialized`` → ``tools/list`` → ``tools/call``.

* Transport: POST /mcp with a single JSON-RPC message (batches supported).
  Responses are plain application/json (allowed by the Streamable HTTP spec
  when the answer fits one message); notifications get 202 Accepted.
* Sessions: none — every request is independent, so clients that don't
  persist a session id work too.
* Auth: the caller's Slide AI access token as ``Authorization: Bearer ...``
  (configured once in the client's MCP server entry, alongside the URL).
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from supabase import AsyncClient

from app.api.deps import owner_id, supabase
from app.core.config import Settings
from app.mcp.tools import MCP_TOOL_DEFINITIONS, ToolContext, call_tool

logger = logging.getLogger("slideai.mcp")

router = APIRouter(tags=["mcp"])

# Newest protocol version this server speaks; clients negotiate via
# initialize and are expected to settle on a shared version.
_LATEST_PROTOCOL_VERSION = "2025-06-18"
_SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}

SERVER_INSTRUCTIONS = (
    "Slide AI lets you create, generate, inspect and edit presentations. "
    "Start with list_presentations to find ids, get_presentation or "
    "get_slide_elements to read the structured spec and its elements, then "
    "control anything: update_element patches a single element (text, level, "
    "position x/y, width, animation, items...), add_element/move_element/"
    "remove_element manage content, define_custom_animation + "
    "set_element_animation give you unrestricted CSS keyframe animations "
    "(any property — only url()/javascript: are sandboxed), and "
    "update_custom_slide writes full HTML/CSS/JS slides. "
    "ai_edit_presentation handles whole-deck natural-language edits."
)

# JSON-RPC error codes
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602


def _result(msg_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _text_result(msg_id: Any, text: str, *, is_error: bool = False) -> dict:
    payload: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        payload["isError"] = True
    return _result(msg_id, payload)


async def _handle_message(ctx: ToolContext, msg: Any) -> dict | None:
    """Process one JSON-RPC message. Returns a response dict, or None for
    notifications / malformed entries inside a batch."""
    if not isinstance(msg, dict):
        return _error(None, _INVALID_REQUEST, "Request must be a JSON-RPC object")

    method = msg.get("method")
    msg_id = msg.get("id")
    is_notification = "id" not in msg or msg.get("id") is None

    # --- notifications (no response) ---
    if is_notification:
        return None

    # --- requests ---
    if method == "initialize":
        requested = (msg.get("params") or {}).get("protocolVersion")
        version = (
            requested
            if requested in _SUPPORTED_PROTOCOL_VERSIONS
            else _LATEST_PROTOCOL_VERSION
        )
        return _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "Slide AI", "version": "1.1.0"},
            "instructions": SERVER_INSTRUCTIONS,
        })

    if method == "ping":
        return _result(msg_id, {})

    if method == "tools/list":
        return _result(msg_id, {"tools": MCP_TOOL_DEFINITIONS})

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(
                msg_id, _INVALID_PARAMS,
                "tools/call requires 'name' (string) and 'arguments' (object)",
            )
        try:
            text = await call_tool(ctx, name, arguments)
        except Exception as exc:  # noqa: BLE001 — never fail the HTTP layer
            logger.exception("mcp tool %r crashed", name)
            text = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return _text_result(msg_id, text, is_error=False)

    if method == "resources/list":
        return _result(msg_id, {"resources": []})

    if method == "prompts/list":
        return _result(msg_id, {"prompts": []})

    return _error(msg_id, _METHOD_NOT_FOUND, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    oid: UUID = Depends(owner_id),
    supabase_client: AsyncClient = Depends(supabase),
):
    """Single entry point for the MCP JSON-RPC protocol."""
    settings: Settings = request.app.state.settings
    ctx = ToolContext(
        client=supabase_client, user_id=oid, settings=settings,
        storage=getattr(request.app.state, "storage", None),
    )

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            _error(None, _PARSE_ERROR, "Invalid JSON body"), status_code=400
        )

    batch = payload if isinstance(payload, list) else [payload]
    responses: list[dict] = []
    for msg in batch:
        try:
            response = await _handle_message(ctx, msg)
        except Exception as exc:  # noqa: BLE001
            logger.exception("mcp dispatch failed")
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            response = _error(msg_id, -32603, f"Internal error: {exc}")
        if response is not None:
            responses.append(response)

    if not responses:
        # Only notifications (e.g. notifications/initialized) — nothing to say.
        return Response(status_code=202)
    if isinstance(payload, list):
        return JSONResponse(responses)
    return JSONResponse(responses[0])


@router.get("/mcp")
async def mcp_get() -> Response:
    """Streamable HTTP servers may stream server-initiated messages on GET;
    this stateless server has nothing to stream."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
async def mcp_delete() -> Response:
    """No sessions, nothing to tear down."""
    return Response(status_code=405, headers={"Allow": "POST"})
