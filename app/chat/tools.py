"""Tool definitions and executors for the AI chat system.

Each tool is a Python async function that receives the current PresentationSpec
and keyword arguments, and returns a ToolResult with the (possibly) modified
spec and a human-readable summary.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from app.generation.spec import Element, PresentationSpec, SlideSpec

_element_adapter = TypeAdapter(Element)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    spec: PresentationSpec
    summary: str
    changed_indexes: list[int] = field(default_factory=list)
    success: bool = True


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling schema)
# ---------------------------------------------------------------------------

THEMES = [
    "modern", "corporate", "startup", "education", "medical",
    "finance", "luxury", "minimal", "glass", "dark",
    "neon", "apple", "google", "microsoft", "openai",
]

LAYOUTS = [
    "hero", "title", "agenda", "section", "timeline",
    "comparison", "cards", "statistics", "pricing", "gallery",
    "process", "flow", "roadmap", "team", "quote", "swot",
    "table", "chart", "image-left", "image-right", "cta",
    "conclusion", "thank-you",
]

# Compact, copy-pasteable shape guide the model is told to follow when it
# supplies "new_elements". Mirrors app.generation.spec.ElementType exactly.
ELEMENT_SHAPES = """Each element MUST have a valid "type" (one of: title, subtitle, paragraph, bullets, image, cards, timeline, comparison, quote, statistics, code, table, diagram, icon).
Field shapes by type:
- title: {"type":"title","text":"...","level":1}
- subtitle: {"type":"subtitle","text":"..."}
- paragraph: {"type":"paragraph","text":"..."}
- bullets: {"type":"bullets","items":["...","..."]}
- image: {"type":"image","src":null,"alt":"...","caption":null}
- cards: {"type":"cards","items":[{"title":"...","body":"..."}]}
- timeline: {"type":"timeline","items":[{"year":"...","text":"..."}]}
- comparison: {"type":"comparison","left":{"title":"...","points":[...]},"right":{"title":"...","points":[...]}}
- quote: {"type":"quote","text":"...","author":"..."}
- statistics: {"type":"statistics","items":[{"value":"...","label":"..."}]}
- code: {"type":"code","code":"...","language":"..."}
- table: {"type":"table","headers":[...],"rows":[[...]]}
- diagram: {"type":"diagram","kind":"...","nodes":[...]}
- icon: {"type":"icon","icon":"...","label":"..."}
IMPORTANT: the type for cards is "cards" (with an s), never "card"."""

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_slide",
            "description": "Update a slide's title, layout, background, theme, or content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "title": {"type": "string", "description": "New slide title"},
                    "layout": {"type": "string", "description": f"New layout: {', '.join(LAYOUTS)}"},
                    "background": {"type": "string", "description": "New background color or gradient"},
                    "theme": {"type": "string", "description": f"New theme: {', '.join(THEMES)}"},
                    "new_elements": {
                        "type": "array",
                        "description": f"Replace the slide's elements with these new ones. {ELEMENT_SHAPES}",
                        "items": {"type": "object"},
                    },
                },
                "required": ["slide_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_slide",
            "description": "Add a new slide at a specific position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layout": {"type": "string", "description": f"Layout for the new slide: {', '.join(LAYOUTS)}"},
                    "title": {"type": "string", "description": "Slide title"},
                    "position": {"type": "integer", "description": "0-based insertion index (insert BEFORE this slide). -1 or omit = append at end."},
                    "subtitle": {"type": "string", "description": "Optional subtitle text"},
                    "bullets": {
                        "type": "array",
                        "description": "Optional bullet points",
                        "items": {"type": "string"},
                    },
                },
                "required": ["layout", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_slide",
            "description": "Delete a slide by index. Cannot delete the last slide.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index to delete"},
                },
                "required": ["slide_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_slide",
            "description": "Move a slide from one position to another.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_index": {"type": "integer", "description": "Current 0-based index"},
                    "to_index": {"type": "integer", "description": "Target 0-based index"},
                },
                "required": ["from_index", "to_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_theme",
            "description": "Change the theme of the entire presentation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "theme_name": {"type": "string", "description": f"One of: {', '.join(THEMES)}"},
                },
                "required": ["theme_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rewrite_titles",
            "description": "Rewrite all slide titles with a specific style.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titles": {
                        "type": "array",
                        "description": "Array of new title strings, one per slide in order",
                        "items": {"type": "string"},
                    },
                },
                "required": ["titles"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reduce_text",
            "description": "Reduce text length on specific slides or all slides.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_indexes": {
                        "type": "array",
                        "description": "0-based indexes to reduce. Empty = all slides.",
                        "items": {"type": "integer"},
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_element",
            "description": "Remove a specific element/section from a slide by matching its text or title. Use this for targeted deletions instead of rebuilding the whole slide. Provide either element_text (text contained in the element) or element_type, or both.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "element_text": {"type": "string", "description": "Substring that identifies the element to remove (e.g. a card title, list item, paragraph text). Elements whose text/title/items contain this string are removed."},
                    "element_type": {"type": "string", "description": "Optional type filter: title, subtitle, paragraph, bullets, image, cards, timeline, comparison, quote, statistics, code, table, diagram, icon. Only elements of this type matching are removed."},
                },
                "required": ["slide_index", "element_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_slide_detail",
            "description": "Get the full content (all elements) of a specific slide. Use this when you need to see the full slide before deciding how to edit it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                },
                "required": ["slide_index"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

async def execute_update_slide(
    spec: PresentationSpec, slide_index: int, **kwargs: Any,
) -> ToolResult:
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    # Validate the layout up-front so we never persist an invalid value.
    if "layout" in kwargs and kwargs["layout"] is not None:
        from app.generation.spec import LayoutName
        try:
            LayoutName.__args__  # type: ignore[attr-defined]
            allowed = set(LayoutName.__args__)  # type: ignore[attr-defined]
        except AttributeError:
            allowed = set()
        if allowed and kwargs["layout"] not in allowed:
            return ToolResult(
                spec,
                f"Invalid layout '{kwargs['layout']}'. Allowed: {', '.join(sorted(allowed))}",
                success=False,
            )

    # Validate incoming new_elements through the discriminated union so
    # arbitrary dicts cannot be persisted as elements. Normalize common model
    # mistakes first (e.g. "card" -> "cards") so a near-miss still succeeds.
    new_elements_validated: list[Element] | None = None
    if "new_elements" in kwargs and kwargs["new_elements"] is not None:
        elements = _validate_elements(kwargs["new_elements"])
        if elements is None:
            return ToolResult(
                spec,
                "Invalid elements. Follow the element shape guide exactly: "
                "use type \"cards\" (never \"card\") and include the required "
                "fields shown in the tool description.",
                success=False,
            )
        new_elements_validated = elements

    modified = copy.deepcopy(spec)
    slide = modified.slides[slide_index]

    if "title" in kwargs and kwargs["title"] is not None:
        _set_title(slide, str(kwargs["title"]))
    if "layout" in kwargs and kwargs["layout"] is not None:
        slide.layout = str(kwargs["layout"])
    if "background" in kwargs and kwargs["background"] is not None:
        slide.background = str(kwargs["background"])
    if "theme" in kwargs and kwargs["theme"] is not None:
        slide.theme = str(kwargs["theme"])
    if new_elements_validated is not None:
        slide.elements = new_elements_validated

    return ToolResult(modified, f"Updated slide {slide_index + 1}", changed_indexes=[slide_index])


async def execute_add_slide(
    spec: PresentationSpec, layout: str, title: str, **kwargs: Any,
) -> ToolResult:
    modified = copy.deepcopy(spec)

    elements: list[Element] = [
        _element_adapter.validate_python({"type": "title", "text": title, "level": 1}),
    ]
    if "subtitle" in kwargs:
        elements.append(_element_adapter.validate_python({"type": "subtitle", "text": str(kwargs["subtitle"])}))
    if "bullets" in kwargs:
        elements.append(_element_adapter.validate_python({"type": "bullets", "items": [str(b) for b in kwargs["bullets"]]}))

    new_slide = SlideSpec(layout=layout, elements=elements)

    position = kwargs.get("position", -1)
    if position == -1 or position >= len(modified.slides):
        modified.slides.append(new_slide)
        idx = len(modified.slides) - 1
    else:
        modified.slides.insert(position, new_slide)
        idx = position

    return ToolResult(modified, f"Added new slide \"{title}\" at position {idx + 1}", changed_indexes=[idx])


async def execute_delete_slide(
    spec: PresentationSpec, slide_index: int, **kwargs: Any,
) -> ToolResult:
    if len(spec.slides) <= 1:
        return ToolResult(spec, "Cannot delete the only slide", success=False)
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    modified = copy.deepcopy(spec)
    removed = modified.slides.pop(slide_index)
    title = _get_title_text(removed)
    return ToolResult(modified, f"Deleted slide {slide_index + 1} \"{title}\"", changed_indexes=list(range(slide_index, len(modified.slides))))


async def execute_move_slide(
    spec: PresentationSpec, from_index: int, to_index: int, **kwargs: Any,
) -> ToolResult:
    if not (0 <= from_index < len(spec.slides) and 0 <= to_index < len(spec.slides)):
        return ToolResult(spec, "Invalid slide indices", success=False)
    if from_index == to_index:
        return ToolResult(spec, "Source and destination are the same", success=False)

    modified = copy.deepcopy(spec)
    slide = modified.slides.pop(from_index)
    modified.slides.insert(to_index, slide)
    return ToolResult(modified, f"Moved slide {from_index + 1} to position {to_index + 1}", changed_indexes=list(range(min(from_index, to_index), max(from_index, to_index) + 1)))


async def execute_change_theme(
    spec: PresentationSpec, theme_name: str, **kwargs: Any,
) -> ToolResult:
    modified = copy.deepcopy(spec)
    modified.meta.theme = theme_name
    for slide in modified.slides:
        slide.theme = theme_name
    return ToolResult(modified, f"Changed theme to \"{theme_name}\"", changed_indexes=list(range(len(modified.slides))))


async def execute_rewrite_titles(
    spec: PresentationSpec, titles: list[str], **kwargs: Any,
) -> ToolResult:
    if not titles:
        return ToolResult(spec, "No titles provided", success=False)

    modified = copy.deepcopy(spec)
    count = 0
    for i, slide in enumerate(modified.slides):
        if i < len(titles):
            _set_title(slide, titles[i])
            count += 1

    return ToolResult(modified, f"Rewrote {count} slide titles", changed_indexes=list(range(count)))


async def execute_reduce_text(
    spec: PresentationSpec, **kwargs: Any,
) -> ToolResult:
    targets = kwargs.get("slide_indexes", [])
    modified = copy.deepcopy(spec)
    changed: list[int] = []

    for i, slide in enumerate(modified.slides):
        if targets and i not in targets:
            continue
        for el in slide.elements:
            el_type = el.type if hasattr(el, "type") else el.get("type")
            if el_type == "paragraph":
                text = el.text if hasattr(el, "text") else el.get("text", "")
                words = str(text).split()
                if len(words) > 6:
                    short = " ".join(words[: max(3, len(words) // 2)])
                    if hasattr(el, "text"):
                        el.text = short
                    else:
                        el["text"] = short
                    changed.append(i)
            elif el_type == "bullets":
                items = el.items if hasattr(el, "items") else el.get("items", [])
                if items:
                    short = [str(x) for x in items[: max(1, len(items) - 1)]]
                    if hasattr(el, "items"):
                        el.items = short
                    else:
                        el["items"] = short
                    changed.append(i)

    if not changed:
        return ToolResult(modified, "Text is already concise", changed_indexes=[])

    return ToolResult(modified, f"Reduced text on {len(set(changed))} slide(s)", changed_indexes=list(set(changed)))


async def execute_remove_element(
    spec: PresentationSpec, slide_index: int, element_text: str, **kwargs: Any,
) -> ToolResult:
    """Removes only matching element(s), never the whole slide.

    Removes the elements within the slide whose text/title/items contain
    ``element_text``. Optionally filtered by ``element_type``.
    """
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    from app.generation.spec import ElementType
    allowed = set(ElementType.__args__)
    etype = kwargs.get("element_type")
    if etype and etype not in allowed:
        return ToolResult(spec, f"Invalid element_type '{etype}'", success=False)

    target = str(element_text).strip().lower()
    if not target:
        return ToolResult(spec, "No element_text provided", success=False)

    modified = copy.deepcopy(spec)
    slide = modified.slides[slide_index]

    def _match(el: Any) -> bool:
        if etype and (getattr(el, "type", None) or el.get("type")) != etype:
            return False

        # Flatten every string reachable from the element into one bag of text.
        data = el.model_dump() if hasattr(el, "model_dump") else el
        texts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "type" or k == "id" or k == "animation":
                        continue
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str):
                texts.append(node)

        walk(data)
        return any(target in t.lower() for t in texts)

    idxs = [i for i, el in enumerate(slide.elements) if _match(el)]
    removed = []
    for i in sorted(idxs, reverse=True):
        removed.append(slide.elements.pop(i))

    if not removed:
        return ToolResult(spec, f"No element matching \"{element_text}\" found on slide {slide_index + 1}", success=False)

    return ToolResult(
        modified,
        f"Removed {len(removed)} element(s) matching \"{element_text}\" from slide {slide_index + 1}",
        changed_indexes=[slide_index],
    )


async def execute_get_slide_detail(
    spec: PresentationSpec, slide_index: int, **kwargs: Any,
) -> ToolResult:
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    slide = spec.slides[slide_index]
    detail = slide.model_dump(mode="json") if hasattr(slide, "model_dump") else slide
    detail_str = json.dumps(detail, ensure_ascii=False)
    if len(detail_str) > 1500:
        detail_str = detail_str[:1500] + "..."
    return ToolResult(spec, f"Slide {slide_index + 1}: {detail_str}", changed_indexes=[])


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Tools that mutate the presentation spec. Anything not in this set is
# read-only (currently just `get_slide_detail`).
_WRITE_TOOLS = {
    "update_slide",
    "add_slide",
    "delete_slide",
    "move_slide",
    "change_theme",
    "rewrite_titles",
    "reduce_text",
    "remove_element",
}

TOOL_EXECUTORS: dict[str, Any] = {
    "update_slide": execute_update_slide,
    "add_slide": execute_add_slide,
    "delete_slide": execute_delete_slide,
    "move_slide": execute_move_slide,
    "change_theme": execute_change_theme,
    "rewrite_titles": execute_rewrite_titles,
    "reduce_text": execute_reduce_text,
    "remove_element": execute_remove_element,
    "get_slide_detail": execute_get_slide_detail,
}


def tool_definitions_for_role(role: str | None) -> list[dict[str, Any]]:
    """Return the OpenAI tool definitions the caller is allowed to use.

    Editors/admins/owners get the full set. Viewers (and any unknown role)
    get only read-only tools — the model literally cannot emit an edit tool
    call because the tool is not in its menu.
    """
    if role in ("owner", "admin", "editor"):
        return list(TOOL_DEFINITIONS)
    return [t for t in TOOL_DEFINITIONS if t["function"]["name"] not in _WRITE_TOOLS]


async def dispatch_tool(
    name: str, arguments: dict[str, Any], spec: PresentationSpec,
) -> ToolResult:
    executor = TOOL_EXECUTORS.get(name)
    if executor is None:
        return ToolResult(spec, f"Unknown tool: {name}", success=False)
    try:
        return await executor(spec, **arguments)
    except Exception as exc:
        return ToolResult(spec, f"Tool error: {exc}", success=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_title(slide: Any, title: str) -> None:
    for el in slide.elements:
        el_type = el.type if hasattr(el, "type") else el.get("type")
        if el_type == "title":
            if hasattr(el, "text"):
                el.text = title
            else:
                el["text"] = title
            return
    # No title element — prepend one
    slide.elements.insert(0, _element_adapter.validate_python({"type": "title", "text": title, "level": 1}))


def _normalize_element(el: dict) -> dict:
    """Tolerate the small mistakes LLMs make when fabricating elements, so a
    slightly-off tool call doesn't fail the whole update.

    Maps common bad type strings to the real ElementType and fills in the
    minimal required fields a model tends to omit.
    """
    if not isinstance(el, dict):
        return {"type": "paragraph", "text": str(el)}

    t = (el.get("type") or "").strip().lower()
    canonical = {
        "card": "cards", "bullet": "bullets", "image": "image",
        "stat": "statistics", "stats": "statistics",
        "timeline": "timeline", "table": "table",
    }
    if t in canonical:
        el = dict(el)
        el["type"] = canonical[t]

    if el["type"] == "cards" and isinstance(el.get("items"), list):
        items = []
        for it in el["items"]:
            if isinstance(it, dict):
                if isinstance(it.get("title"), dict):
                    items.append({"title": str(it["title"].get("text", "")), "body": str(it.get("body") or "")})
                else:
                    items.append({"title": str(it.get("title") or ""), "body": str(it.get("body") or it.get("text") or "")})
            else:
                items.append({"title": "", "body": str(it)})
        el["items"] = items

    return el


def _validate_elements(elements: list[dict]) -> list[Element] | None:
    """Validate incoming elements, tolerating common model quirks.

    Returns the validated list, or None if validation still fails even after
    normalization (caller then reports the error to the model).
    """
    try:
        return [_element_adapter.validate_python(_normalize_element(el)) for el in elements]
    except Exception:
        return None


def _get_title_text(slide: Any) -> str:
    for el in slide.elements:
        el_type = el.type if hasattr(el, "type") else el.get("type")
        if el_type == "title":
            return el.text if hasattr(el, "text") else el.get("text", "(untitled)")
    return "(untitled)"
