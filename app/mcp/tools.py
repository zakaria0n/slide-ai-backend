"""MCP tool registry — exposes Slide AI to external AI coding agents.

Tools let MCP clients (Claude Code, Cursor, OpenCode, Codex, ZCode, ...)
create, generate, inspect and edit presentations. Granular slide tools reuse
the exact executors the in-app AI chat uses (app.chat.tools), so the same
validation and normalization applies to edits coming from any agent.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from supabase import AsyncClient

import app.db as db
from app.chat.tools import TOOL_DEFINITIONS as _CHAT_TOOL_DEFINITIONS
from app.chat.tools import dispatch_tool
from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.generation.spec import PresentationSpec
from app.presentations.versioning import snapshot_if_changed

_UUID_RE_NOTE = "UUID string returned when the presentation was created (list_presentations)."


@dataclass
class McpToolOutput:
    """Rich tool result: text plus optional images (base64 PNG)."""

    text: str = ""
    images: list[dict[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.images is None:
            self.images = []


@dataclass
class ToolContext:
    """Per-call context: the caller's data client, identity and settings."""

    client: AsyncClient
    user_id: UUID
    settings: Any = None
    storage: Any = None


Handler = Callable[[ToolContext, dict], Awaitable[str]]


async def _require_row(ctx: ToolContext, presentation_id: str, *, write: bool = True) -> tuple[UUID, dict]:
    """Load a presentation the caller may access; enforce write when needed."""
    try:
        pid = UUID(str(presentation_id))
    except ValueError as exc:
        raise NotFoundError(f"Invalid presentation id '{presentation_id}'") from exc
    row = await db.get_presentation(ctx.client, pid)
    if row is None:
        raise NotFoundError("Presentation not found")
    role = await db.get_presentation_access_role(ctx.client, pid, ctx.user_id)
    if role is None:
        raise NotFoundError("Presentation not found")
    if write and role not in ("owner", "admin", "editor"):
        raise ForbiddenError(
            f"Your role on this presentation is '{role}' — write access is required"
        )
    return pid, row


async def _persist_spec(
    ctx: ToolContext, pid: UUID, old_spec: PresentationSpec, new_spec: PresentationSpec, note: str
) -> None:
    await snapshot_if_changed(ctx.client, pid, ctx.user_id, old_spec, note=note)
    await db.update_presentation(
        ctx.client, pid,
        spec=new_spec.model_dump(),
        slide_count=len(new_spec.slides),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Deck-level tools
# ---------------------------------------------------------------------------


async def _h_list_presentations(ctx: ToolContext, args: dict) -> str:
    rows = await db.list_presentations(ctx.client, ctx.user_id, limit=50, offset=0)
    items = [
        {
            "id": r["id"],
            "title": r.get("title"),
            "slide_count": r.get("slide_count", 0),
            "status": r.get("status"),
            "theme": r.get("theme"),
            "updated_at": r.get("updated_at"),
        }
        for r in rows
    ]
    return _json({"total": len(items), "presentations": items})


async def _h_get_presentation(ctx: ToolContext, args: dict) -> str:
    pid, row = await _require_row(ctx, args["presentation_id"], write=False)
    return _json({
        "id": str(pid),
        "title": row.get("title"),
        "description": row.get("description"),
        "slide_count": row.get("slide_count", 0),
        "status": row.get("status"),
        "theme": row.get("theme"),
        "spec": row.get("spec"),
    })


async def _h_create_presentation(ctx: ToolContext, args: dict) -> str:
    title = str(args["title"]).strip() or "Untitled presentation"
    row = await db.create_presentation(
        ctx.client,
        owner_id=str(ctx.user_id),
        title=title[:200],
        description=None,
        theme=None,
        status="ready",
        slide_count=1,
    )
    pid = UUID(row["id"])
    spec = PresentationSpec.model_validate({
        "meta": {"title": title[:200], "theme": None, "background": None,
                 "language": "English", "tone": "Professional"},
        "slides": [{
            "layout": "title",
            "elements": [
                {"type": "title", "text": title[:200], "level": 1},
                {"type": "subtitle", "text": "Created via MCP"},
            ],
        }],
    })
    await db.update_presentation(ctx.client, pid, spec=spec.model_dump(), slide_count=len(spec.slides))
    return _json({
        "id": str(pid),
        "title": title,
        "slide_count": 1,
        "next": "Use update_slide / add_slide / add_element / ai_edit_presentation on this id.",
    })


async def _do_generate(ctx: ToolContext, request) -> dict:
    from app.generation.service import GenerationService
    from app.generation.spec_provider import build_spec_provider

    provider = build_spec_provider(ctx.settings)
    service = GenerationService(ctx.client, provider=provider)
    return await service.generate(ctx.user_id, request=request)


async def _h_generate_presentation(ctx: ToolContext, args: dict) -> str:
    import asyncio as _asyncio

    from app.core.model_catalog import resolve_model
    from app.core.ratelimit import generation_limiter
    from app.core.brand import get_brand_context
    from app.generation.schemas import GenerationRequest

    from app.mcp import jobs

    generation_limiter.check(str(ctx.user_id))
    brand_context = await get_brand_context(ctx.client, ctx.user_id)

    model = await resolve_model(ctx.settings, args.get("model"))
    request = GenerationRequest(
        prompt=str(args["prompt"]),
        slide_count=int(args.get("slide_count") or 10),
        tone=str(args.get("tone") or "Professional")[:40],
        language=str(args.get("language") or "English")[:40],
        # MCP agents get the 'custom' theme by default: full creative freedom
        # mode (the model authors its own layouts and animations).
        theme=args.get("theme") or "custom",
        model=model,
        brand_context=brand_context,
    )

    if args.get("async_mode"):
        job_id = await jobs.create_job(ctx.client, ctx.user_id)

        async def _run() -> None:
            try:
                saved = await _do_generate(ctx, request)
                await jobs.finish_job(ctx.client, job_id, presentation_id=saved["id"], title=saved.get("title"))
            except Exception as exc:  # noqa: BLE001 — reported through the job
                await jobs.fail_job(ctx.client, job_id, str(exc))

        _asyncio.get_running_loop().create_task(_run())
        return _json({
            "job_id": job_id,
            "status": "running",
            "next": "Poll get_generation_job(job_id) until status is 'ready', then use the presentation_id.",
        })

    saved = await _do_generate(ctx, request)
    return _json({
        "id": saved["id"],
        "title": saved.get("title"),
        "slide_count": saved.get("slide_count"),
        "model": model,
    })


async def _h_get_slide_screenshot(ctx: ToolContext, args: dict) -> McpToolOutput:
    """Render one slide with headless Chromium and return a PNG image.

    Lets vision-capable client models actually SEE the rendered slide
    instead of reasoning blind over the JSON spec.
    """
    import os
    import tempfile

    pid, row = await _require_row(ctx, args["presentation_id"], write=False)
    spec = PresentationSpec.model_validate(row["spec"])
    slide_index = int(args.get("slide_index") or 0)
    if slide_index < 0 or slide_index >= len(spec.slides):
        return _json({"error": f"Invalid slide_index {slide_index}; the deck has {len(spec.slides)} slides"})

    from app.export.html_exporter import render_spec_html
    from app.export.html_theme import tokens_for

    theme = tokens_for(spec.meta.theme)
    doc = render_spec_html(spec, theme, animate=False)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(doc)
        html_path = f.name

    import base64

    b64 = ""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.goto(f"file:///{html_path.replace(os.sep, '/')}", wait_until="networkidle")
            await page.wait_for_timeout(400)
            element = page.locator(".slide").nth(slide_index)
            png = await element.screenshot()
            await browser.close()
        b64 = base64.b64encode(png).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — surfaced as tool error text
        return _json({
            "error": f"Screenshot failed: {exc}",
            "hint": "The server needs the Chromium binary: python -m playwright install chromium",
        })
    finally:
        try:
            os.unlink(html_path)
        except OSError:
            pass

    slide = spec.slides[slide_index]
    title_el = next((e for e in slide.elements if getattr(e, "type", "") == "title"), None)
    title = getattr(title_el, "text", "") if title_el else ""
    return McpToolOutput(
        text=(
            f"Screenshot of slide {slide_index + 1}/{len(spec.slides)} "
            f"('{title or slide.layout}') — attached as an image. This is the "
            "RENDERED slide: use it to judge layout, spacing and readability. "
            "The JSON structure is available via get_slide_elements."
        ),
        images=[{"data": b64, "mimeType": "image/png"}],
    )


async def _h_get_generation_job(ctx: ToolContext, args: dict) -> str:
    from app.mcp import jobs

    job = await jobs.get_job(ctx.client, str(args.get("job_id") or ""), ctx.user_id)
    if job is None:
        return _json({"error": "Unknown or expired job_id"})
    return _json(job)


async def _h_rename_presentation(ctx: ToolContext, args: dict) -> str:
    import app.db as _db

    pid, _row = await _require_row(ctx, args["presentation_id"])
    title = str(args["title"]).strip()
    if not title:
        return _json({"error": "Title must not be empty"})
    await _db.update_presentation(ctx.client, pid, title=title[:200])
    return _json({"id": str(pid), "title": title[:200]})


async def _h_duplicate_presentation(ctx: ToolContext, args: dict) -> str:
    from app.presentations.service import PresentationService

    pid, _row = await _require_row(ctx, args["presentation_id"])
    service = PresentationService(ctx.client)
    entity = await service.duplicate(pid, ctx.user_id)
    return _json({"id": str(entity.id), "title": entity.title, "slide_count": entity.slide_count})


async def _h_search_assets(ctx: ToolContext, args: dict) -> str:
    from app.chat.service import run_search_assets

    return await run_search_assets(ctx.settings, args)


async def _h_upload_image(ctx: ToolContext, args: dict) -> str:
    """Upload a base64 image so agents can attach local files to a deck."""
    import base64
    import binascii
    import re

    from app.files.service import FileService

    filename = str(args.get("filename") or "image.png")
    raw = str(args.get("file_base64") or "")
    data_url_match = re.match(r"^data:image/[a-zA-Z+]+;base64,(.+)$", raw, re.DOTALL)
    if data_url_match:
        raw = data_url_match.group(1)
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return _json({"error": "file_base64 is not valid base64"})
    if not data:
        return _json({"error": "File is empty"})
    if len(data) > 6 * 1024 * 1024:
        return _json({"error": "Image exceeds the 6 MB MCP limit"})
    if ctx.storage is None:
        return _json({"error": "Storage is not configured on this server"})

    service = FileService(ctx.client, ctx.storage)
    asset = await service.upload(ctx.user_id, filename=filename, data=data, content_type=None)
    url_info = await service.signed_url(asset["id"], ctx.user_id, expires_in=24 * 3600)
    return _json({
        "file_id": asset["id"],
        "filename": asset.get("filename"),
        "url": url_info["url"],
        "next": "Use this url as the src of an image element (add_element / update_element).",
    })


async def _h_ai_edit_presentation(ctx: ToolContext, args: dict) -> str:
    from app.core.model_catalog import resolve_model
    from app.core.ratelimit import generation_limiter
    from app.generation.spec_editor import build_spec_edit_provider

    generation_limiter.check(str(ctx.user_id))
    pid, row = await _require_row(ctx, args["presentation_id"])
    old_spec = PresentationSpec.model_validate(row["spec"])

    settings = ctx.settings
    model = await resolve_model(settings, args.get("model")) if settings else None
    from app.core.brand import get_brand_context

    brand_context = await get_brand_context(ctx.client, ctx.user_id)
    provider = build_spec_edit_provider(settings)
    result = await provider.edit_spec(
        old_spec, str(args["instruction"]), args.get("target_indexes"), model=model,
        brand_context=brand_context,
    )

    await _persist_spec(ctx, pid, old_spec, result.modified_spec, note=f"mcp ai edit: {args['instruction'][:80]}")
    return _json({"summary": result.summary, "changed_indexes": result.changed_indexes})


async def _h_get_slide_elements(ctx: ToolContext, args: dict) -> str:
    """Full, untruncated read of one slide's elements with their array
    indexes — the read half of read-then-patch element control."""
    pid, row = await _require_row(ctx, args["presentation_id"], write=False)
    spec = PresentationSpec.model_validate(row["spec"])
    slide_index = int(args["slide_index"])
    if slide_index < 0 or slide_index >= len(spec.slides):
        return _json({"error": f"Invalid slide_index {slide_index}; the deck has {len(spec.slides)} slides"})
    slide = spec.slides[slide_index]
    elements = []
    for i, el in enumerate(slide.elements):
        data = el.model_dump(mode="json") if hasattr(el, "model_dump") else el
        # Annotate each element with its index so update_element / move_element
        # can target it without guessing.
        elements.append({"element_index": i, **data})
    return _json({
        "presentation_id": str(pid),
        "slide_index": slide_index,
        "layout": slide.layout,
        "theme": slide.theme,
        "background": slide.background,
        "notes": slide.notes,
        "element_count": len(elements),
        "elements": elements,
        "custom_animations": [d["name"] for d in (spec.meta.customAnimations or [])],
    })


async def _h_delete_presentation(ctx: ToolContext, args: dict) -> str:
    pid, _row = await _require_row(ctx, args["presentation_id"])
    await db.delete_presentation(ctx.client, pid)
    return _json({"deleted": str(pid)})


# ---------------------------------------------------------------------------
# Granular slide tools (reuse the in-app chat executors verbatim)
# ---------------------------------------------------------------------------

_SPEC_TOOL_NAMES = [
    "update_slide",
    "add_slide",
    "delete_slide",
    "move_slide",
    "change_theme",
    "rewrite_titles",
    "reduce_text",
    "remove_element",
    "add_element",
    "update_element",
    "move_element",
    "define_custom_animation",
    "set_element_animation",
    "update_custom_slide",
    "get_slide_detail",
]


def _make_spec_tool_handler(tool_name: str) -> Handler:
    async def handler(ctx: ToolContext, args: dict) -> str:
        pid, row = await _require_row(ctx, args["presentation_id"])
        old_spec = PresentationSpec.model_validate(row["spec"])

        tool_args = {k: v for k, v in args.items() if k != "presentation_id"}
        result = await dispatch_tool(tool_name, tool_args, old_spec)

        note = f"mcp: {tool_name}"
        if result.success and result.spec is not old_spec:
            await _persist_spec(ctx, pid, old_spec, result.spec, note=note)
        elif not result.success:
            return _json({"success": False, "summary": result.summary})
        return _json({"success": result.success, "summary": result.summary})

    return handler


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Chat-tool schemas, extended with the presentation_id argument.
_MCP_SPEC_TOOLS: list[dict] = []
for chat_def in _CHAT_TOOL_DEFINITIONS:
    name = chat_def["function"]["name"]
    if name not in _SPEC_TOOL_NAMES:
        continue
    schema = copy.deepcopy(chat_def["function"].get("parameters") or {"type": "object", "properties": {}})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema["properties"] = {
        "presentation_id": {
            "type": "string",
            "description": _UUID_RE_NOTE,
        },
        **schema["properties"],
    }
    schema["required"] = ["presentation_id"] + [r for r in schema.get("required", []) if r != "presentation_id"]
    _MCP_SPEC_TOOLS.append({
        "name": name,
        "description": chat_def["function"]["description"],
        "inputSchema": schema,
    })

_DECK_TOOLS: list[dict] = [
    {
        "name": "list_presentations",
        "description": "List the caller's presentations with id, title, slide count and status. Always call this first when you don't have a presentation id.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_presentation",
        "description": "Get the full presentation: metadata plus the complete structured spec (slides, elements, themes, customAnimations, custom slide code). Use this to inspect a deck before editing it.",
        "inputSchema": {
            "type": "object",
            "properties": {"presentation_id": {"type": "string", "description": _UUID_RE_NOTE}},
            "required": ["presentation_id"],
        },
    },
    {
        "name": "get_slide_elements",
        "description": "Read ALL elements of one slide, full and untruncated, each annotated with its element_index — the exact indexes update_element / move_element / set_element_animation expect. Read this before patching an element.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "presentation_id": {"type": "string", "description": _UUID_RE_NOTE},
                "slide_index": {"type": "integer", "description": "0-based slide index"},
            },
            "required": ["presentation_id", "slide_index"],
        },
    },
    {
        "name": "create_presentation",
        "description": "Create a NEW empty presentation with a single title slide and return its id. Use generate_presentation instead when the user wants AI-written content.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Presentation title"}},
            "required": ["title"],
        },
    },
    {
        "name": "generate_presentation",
        "description": "OPT-IN TOOL — DO NOT CALL BY DEFAULT. You are the LLM: build the deck yourself with create_presentation + add_slide/update_slide/add_element/update_custom_slide (better, and it follows your analysis). Call this ONLY when the user EXPLICITLY asks to send the job to Slide AI\’s generation model (e.g. \’send this prompt to the Slide AI generator\’). Generates a full deck from the topic; defaults to theme=custom (full creative freedom). Returns the new presentation id, or a job_id with async_mode=true for large decks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Topic / description of the deck to generate"},
                "slide_count": {"type": "integer", "description": "Number of slides (1-30). Default 10."},
                "tone": {"type": "string", "description": "Content tone. Default 'Professional'."},
                "language": {"type": "string", "description": "Content language. Default 'English'."},
                "theme": {"type": "string", "description": "Optional theme: modern, corporate, startup, education, medical, finance, luxury, minimal, glass, dark, neon, apple, google, microsoft, openai."},
                "model": {"type": "string", "description": "Optional AI model id. Omit for the default."},
                "async_mode": {"type": "boolean", "description": "true = return a job_id immediately and poll get_generation_job. Default false (synchronous)."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "ai_edit_presentation",
        "description": "Delegate this slide/deck edit to Slide AI\’s model. PREFER the granular tools (update_element, add_element, set_element_animation...) which you drive yourself — only use this for broad natural-language rewrites, or when the user explicitly asks for Slide AI\’s model. Returns a summary and the changed slide indexes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "presentation_id": {"type": "string", "description": _UUID_RE_NOTE},
                "instruction": {"type": "string", "description": "What to change, e.g. 'add a pricing slide', 'make slide 2 punchier', 'add a glow animation on the hero title'."},
                "target_indexes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional 0-based slide indexes to restrict the edit to.",
                },
                "model": {"type": "string", "description": "Optional AI model id. Omit for the default."},
            },
            "required": ["presentation_id", "instruction"],
        },
    },
    {
        "name": "get_slide_screenshot",
        "description": "Render one slide with headless Chromium and return a PNG screenshot of the ACTUAL rendered slide, so you can SEE the layout (slow: takes a few seconds). Use after building or editing slides to visually verify spacing/overflow, whenever you want to see the design, or when the user asks what a slide looks like.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "presentation_id": {"type": "string", "description": _UUID_RE_NOTE},
                "slide_index": {"type": "integer", "description": "0-based slide index"},
            },
            "required": ["presentation_id", "slide_index"],
        },
    },
    {
        "name": "get_generation_job",
        "description": "Poll the status of an asynchronous generation started with generate_presentation(async_mode=true). Returns {status: running|ready|failed, presentation_id?, title?, error?}.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "The job_id returned by generate_presentation"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "rename_presentation",
        "description": "Rename a presentation (the title shown in the app and exports).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "presentation_id": {"type": "string", "description": _UUID_RE_NOTE},
                "title": {"type": "string", "description": "New title"},
            },
            "required": ["presentation_id", "title"],
        },
    },
    {
        "name": "duplicate_presentation",
        "description": "Duplicate a presentation (full spec copy) into a new deck owned by you.",
        "inputSchema": {
            "type": "object",
            "properties": {"presentation_id": {"type": "string", "description": _UUID_RE_NOTE}},
            "required": ["presentation_id"],
        },
    },
    {
        "name": "search_assets",
        "description": "Search the user's image/icon library and return direct URLs. Put a returned url into an image element's src (add_element or update_element).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "kind": {"type": "string", "description": "image (default), icon or svg"},
                "limit": {"type": "integer", "description": "Max results (1-20, default 8)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "upload_image",
        "description": "Upload an image (base64, max 6 MB) to the user's library and get a URL usable as an image element src. Use this to attach a local file (logo, screenshot, photo) to a deck.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename with extension, e.g. logo.png"},
                "file_base64": {"type": "string", "description": "Base64 file content (a data: URL prefix is accepted and stripped)"},
            },
            "required": ["filename", "file_base64"],
        },
    },
    {
        "name": "delete_presentation",
        "description": "Permanently delete a presentation and its versions. Destructive — confirm with the user before calling.",
        "inputSchema": {
            "type": "object",
            "properties": {"presentation_id": {"type": "string", "description": _UUID_RE_NOTE}},
            "required": ["presentation_id"],
        },
    },
]


def _spec_tool_description(name: str, description: str) -> str:
    return description + " (Edits are persisted immediately and versioned.)"


MCP_TOOL_DEFINITIONS: list[dict] = [
    *_DECK_TOOLS,
    *[
        {**t, "description": _spec_tool_description(t["name"], t["description"])}
        for t in _MCP_SPEC_TOOLS
    ],
]

MCP_TOOL_HANDLERS: dict[str, Handler] = {
    "list_presentations": _h_list_presentations,
    "get_presentation": _h_get_presentation,
    "get_slide_elements": _h_get_slide_elements,
    "create_presentation": _h_create_presentation,
    "generate_presentation": _h_generate_presentation,
    "get_generation_job": _h_get_generation_job,
    "get_slide_screenshot": _h_get_slide_screenshot,
    "rename_presentation": _h_rename_presentation,
    "duplicate_presentation": _h_duplicate_presentation,
    "search_assets": _h_search_assets,
    "upload_image": _h_upload_image,
    "ai_edit_presentation": _h_ai_edit_presentation,
    "delete_presentation": _h_delete_presentation,
    **{name: _make_spec_tool_handler(name) for name in _SPEC_TOOL_NAMES},
}


async def call_tool(ctx: ToolContext, name: str, arguments: dict) -> str:
    """Execute an MCP tool, converting errors into readable tool output."""
    handler = MCP_TOOL_HANDLERS.get(name)
    if handler is None:
        known = ", ".join(sorted(MCP_TOOL_HANDLERS))
        return _json({"error": f"Unknown tool '{name}'. Available tools: {known}."})
    try:
        result = await handler(ctx, arguments or {})
        return result
    except AppError as exc:
        return _json({"error": exc.message, "code": exc.code})
    except Exception as exc:  # noqa: BLE001 — surfaced to the agent in-band
        return _json({"error": f"{type(exc).__name__}: {exc}"})
