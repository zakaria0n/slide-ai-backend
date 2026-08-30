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
    "custom", "modern", "corporate", "startup", "education", "medical",
    "finance", "luxury", "minimal", "glass", "dark",
    "neon", "apple", "google", "microsoft", "openai",
]

LAYOUTS = [
    "hero", "title", "blank", "agenda", "section", "timeline",
    "comparison", "cards", "statistics", "pricing", "gallery",
    "process", "flow", "roadmap", "team", "quote", "swot",
    "table", "chart", "image-left", "image-right", "cta",
    "conclusion", "thank-you",
]

# Renderer built-in element animations (frontend components/renderer/animations.ts).
BUILTIN_ANIMATIONS = [
    "fade", "slide", "scale", "zoom", "rotate", "blur",
    "reveal", "typing", "counter", "gradient", "parallax", "sequential",
]

# Security blacklist mirrored from the frontend keyframes sanitizer.
_FORBIDDEN_CSS = ("url(", "expression(", "javascript:", "@import", "behavior:")

_ANIM_NAME_MAX = 40

# Fields update_element may patch on an existing element (validated afterwards
# through the element union, so an invalid shape is still rejected).
_ELEMENT_PATCHABLE_FIELDS = {
    "text", "level", "animation", "x", "y", "w",
    "alt", "caption", "author", "src", "items", "code", "language", "label",
    "style", "animation_delay",
}


def _find_element_indexes(slide: Any, element_text: str) -> list[int]:
    """Indexes of elements whose content contains element_text (case-insensitive)."""
    target = str(element_text or "").strip().lower()
    if not target:
        return []
    matches: list[int] = []
    for i, el in enumerate(slide.elements):
        data = el.model_dump() if hasattr(el, "model_dump") else el
        texts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("type", "id", "animation"):
                        continue
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str):
                texts.append(node)

        walk(data)
        if any(target in t.lower() for t in texts):
            matches.append(i)
    return matches


def _resolve_target_indexes(
    slide: Any, element_index: Any, element_text: Any,
) -> tuple[list[int], str | None]:
    """Shared element targeting: exact index wins, else text match.
    Returns (indexes, error_message)."""
    if element_index is not None:
        try:
            idx = int(element_index)
        except (TypeError, ValueError):
            return [], "Invalid element_index"
        if idx < 0 or idx >= len(slide.elements):
            return [], f"Invalid element_index {idx}"
        return [idx], None
    target = str(element_text or "").strip()
    if not target:
        return [], "Provide element_text (substring) or element_index to target elements"
    matches = _find_element_indexes(slide, target)
    if not matches:
        return [], f"No element matching \"{target}\" found"
    return matches, None

# Compact, copy-pasteable shape guide the model is told to follow when it
# supplies "new_elements" or "element". Mirrors app.generation.spec.ElementType
# exactly.
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
IMPORTANT: the type for cards is "cards" (with an s), never "card".
Every element may also carry free Canvas-style placement: "x" and "y" (percent
of the slide, 0-100) and "w" (width percent, 1-100). Elements WITH x/y float
freely over the slide; elements WITHOUT x/y flow inside the layout."""

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
                    "notes": {"type": "string", "description": "Speaker notes for this slide."},
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
    {
        "type": "function",
        "function": {
            "name": "define_custom_animation",
            "description": "Define (or redefine) a named CSS @keyframes animation for the deck. After defining, apply it to elements with set_element_animation. Any CSS property is allowed inside keyframes (url(...), expression(...), javascript: and @import are stripped). Prefer transform/opacity/filter for smoothness; start frames hidden and end fully visible.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": f"Animation name (letters/digits/_/-, max {_ANIM_NAME_MAX} chars), e.g. 'riseGlow'. Re-defining an existing name replaces it."},
                    "keyframes": {"type": "string", "description": "Full '@keyframes <name> { ... }' rule (or just the braces body), e.g. \"@keyframes riseGlow { 0% { opacity: 0; transform: translateY(36px) } 100% { opacity: 1; transform: none } }\""},
                    "duration": {"type": "integer", "description": "Duration in milliseconds (100-4000). Out-of-range values are clamped."},
                    "easing": {"type": "string", "description": "Timing function: ease, linear, cubic-bezier(...), steps(...). Default: premium expo-out."},
                },
                "required": ["name", "keyframes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_element_animation",
            "description": f"Apply (or remove) an entrance animation on elements of a slide. The animation must be a built-in ({', '.join(BUILTIN_ANIMATIONS)}) or a name defined via define_custom_animation. Target elements by text (substring match, like remove_element) or by exact element index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "animation": {"type": "string", "description": f"Animation name ({', '.join(BUILTIN_ANIMATIONS)} or a custom name). Pass \"none\" to remove the animation."},
                    "element_text": {"type": "string", "description": "Substring identifying the target element(s) (matches any text inside the element)."},
                    "element_index": {"type": "integer", "description": "Exact 0-based index of the element within slide.elements (overrides element_text)."},
                },
                "required": ["slide_index", "animation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_element",
            "description": "Insert ONE new element into a slide (append at the end of its elements). Use update_slide with new_elements instead when rebuilding a whole slide.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "element": {
                        "type": "object",
                        "description": f"The element to append. {ELEMENT_SHAPES}",
                    },
                },
                "required": ["slide_index", "element"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_element",
            "description": "Patch ONE element of a slide in place: rewrite its text, heading level, position (x/y free placement, w width — all in percent of the slide), entrance animation, media fields or items — WITHOUT rebuilding the whole slide. Target the element with element_index (exact, from get_slide_detail) or element_text (substring). Only provided fields change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "element_index": {"type": "integer", "description": "Exact 0-based index of the element within slide.elements (overrides element_text)."},
                    "element_text": {"type": "string", "description": "Substring identifying the target element (must match exactly one element)."},
                    "text": {"type": "string", "description": "New text (title/subtitle/paragraph/quote...)."},
                    "level": {"type": "integer", "description": "Heading level 1-6 for title elements."},
                    "animation": {"type": "string", "description": f"Entrance animation: built-in ({', '.join(BUILTIN_ANIMATIONS)}) or a custom name; \"none\" removes it."},
                    "x": {"type": "number", "description": "Horizontal position in percent of the slide (0-100). Setting x+y turns the element into a free-floating (Canvas-style) element."},
                    "y": {"type": "number", "description": "Vertical position in percent of the slide (0-100)."},
                    "w": {"type": "number", "description": "Width in percent of the slide (1-100)."},
                    "alt": {"type": "string", "description": "Alt text for image elements."},
                    "caption": {"type": "string", "description": "Caption for image elements."},
                    "author": {"type": "string", "description": "Author for quote elements."},
                    "items": {"type": "array", "description": "Replace the items array (bullets: strings; cards: [{title,body}]; timeline: [{year,text}]; statistics: [{value,label}])."},
                    "code": {"type": "string", "description": "New code for code elements."},
                    "language": {"type": "string", "description": "Language for code elements."},
                    "style": {
                        "type": "object",
                        "description": "Per-element style overrides (any subset): {color, font_size (e.g. \"48px\"), font_weight (\"700\"), align (left/center/right/justify), opacity (0-1), rotation (degrees)}. Unset fields keep the theme look.",
                    },
                    "animation_delay": {"type": "integer", "description": "Extra delay in ms before this element's entrance animation starts (0-10000)."},
                },
                "required": ["slide_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_element",
            "description": "Reorder an element within a slide (changes stacking order for free-positioned elements and reading order for layout elements). Target with element_index or element_text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "to_index": {"type": "integer", "description": "New 0-based position within slide.elements. Use the last index to bring the element to front."},
                    "element_index": {"type": "integer", "description": "Exact 0-based index of the element to move."},
                    "element_text": {"type": "string", "description": "Substring identifying the element to move (must match exactly one)."},
                },
                "required": ["slide_index", "to_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_deck_meta",
            "description": "Update deck-level metadata: title, content language, tone or theme. Changing theme re-skins every slide.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "New deck title"},
                    "language": {"type": "string", "description": "Content language (e.g. English, French)"},
                    "tone": {"type": "string", "description": "Content tone (e.g. Professional, Bold)"},
                    "theme": {"type": "string", "description": f"Theme for the whole deck: {', '.join(THEMES)}"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_assets",
            "description": "Search the user's image/icon library and return direct URLs. Use a returned url as the src of an image element (add_element or update_element).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query, e.g. 'office team', 'chart'"},
                    "kind": {"type": "string", "description": "image (default), icon or svg"},
                    "limit": {"type": "integer", "description": "Max results (1-20, default 8)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_custom_slide",
            "description": "Write or patch the HTML/CSS/JS of a custom-coded slide (the slide becomes layout='custom' and renders your code in a sandboxed 16:9 iframe). The iframe IS the slide: preloaded globals are Chart.js (`Chart`), anime.js v4 (`anime`), theme CSS variables (--bg, --surface, --text, --accent, --accent2, --gradient, --font-heading) and window.__THEME__. When the slide becomes visible the body gets class 'is-active' and a 'slide:activate' event fires on window — start elements hidden in CSS and run entrance choreography on that event, always ending settled and fully visible. No external network requests, no localStorage, no parent access. Omitted fields keep their current code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_index": {"type": "integer", "description": "0-based slide index"},
                    "html": {"type": "string", "description": "HTML body markup for the slide"},
                    "css": {"type": "string", "description": "CSS for the slide (scoped to the iframe)"},
                    "js": {"type": "string", "description": "JavaScript for the slide"},
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
    if "notes" in kwargs:
        slide.notes = str(kwargs["notes"]) if kwargs["notes"] is not None else None

    return ToolResult(modified, f"Updated slide {slide_index + 1}" + (" (+ speaker notes)" if "notes" in kwargs else ""), changed_indexes=[slide_index])


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
    if len(detail_str) > 6000:
        detail_str = detail_str[:6000] + "..."
    return ToolResult(spec, f"Slide {slide_index + 1}: {detail_str}", changed_indexes=[])


async def execute_define_custom_animation(
    spec: PresentationSpec, name: str, keyframes: str, **kwargs: Any,
) -> ToolResult:
    """Define or replace a named deck-level custom animation."""
    import re

    clean_name = str(name).strip()
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,39}", clean_name):
        return ToolResult(
            spec,
            f"Invalid animation name '{name}'. Use letters/digits/_/-, starting with a letter (max {_ANIM_NAME_MAX} chars).",
            success=False,
        )

    kf = str(keyframes or "").strip()
    if not kf:
        return ToolResult(spec, "No keyframes provided", success=False)
    lowered = kf.lower()
    if any(bad in lowered for bad in _FORBIDDEN_CSS):
        return ToolResult(
            spec,
            "Keyframes contain forbidden constructs (url(...), expression(...), javascript:, @import). Remove them and retry.",
            success=False,
        )

    try:
        duration = int(kwargs.get("duration") or 600)
    except (TypeError, ValueError):
        duration = 600
    duration = max(100, min(duration, 4000))
    easing = kwargs.get("easing")
    easing = str(easing).strip() if easing else None

    modified = copy.deepcopy(spec)
    defs = list(modified.meta.customAnimations or [])
    new_def = {
        "name": clean_name,
        "keyframes": kf,
        "duration": duration,
        "easing": easing,
    }
    replaced = False
    for i, existing in enumerate(defs):
        existing_name = existing.get("name") if isinstance(existing, dict) else getattr(existing, "name", "")
        if existing_name == clean_name:
            defs[i] = new_def
            replaced = True
            break
    if not replaced:
        defs.append(new_def)
    # Keep the deck-level list bounded.
    modified.meta.customAnimations = defs[-24:]

    action = "redefined" if replaced else "defined"
    return ToolResult(
        modified,
        f"{action} custom animation '{clean_name}' ({duration}ms). Apply it with set_element_animation.",
        changed_indexes=[],
    )


async def execute_set_element_animation(
    spec: PresentationSpec, slide_index: int, animation: str, **kwargs: Any,
) -> ToolResult:
    """Attach (or clear) an entrance animation on matching slide elements."""
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    anim = str(animation).strip()
    removing = anim.lower() in ("", "none", "null")
    if not removing:
        custom_names = {
            (d.get("name") if isinstance(d, dict) else getattr(d, "name", ""))
            for d in (spec.meta.customAnimations or [])
        }
        if anim not in BUILTIN_ANIMATIONS and anim not in custom_names:
            return ToolResult(
                spec,
                f"Unknown animation '{anim}'. Use a built-in ({', '.join(BUILTIN_ANIMATIONS)}) "
                f"or define it first with define_custom_animation.",
                success=False,
            )

    modified = copy.deepcopy(spec)
    slide = modified.slides[slide_index]

    targets, err = _resolve_target_indexes(
        slide, kwargs.get("element_index"), kwargs.get("element_text"),
    )
    if err:
        return ToolResult(spec, err, success=False)

    applied = 0
    for i in targets:
        el = slide.elements[i]
        value = None if removing else anim
        if hasattr(el, "animation"):
            el.animation = value
        else:
            el["animation"] = value
        applied += 1

    verb = "Removed animation from" if removing else f"Applied animation '{anim}' to"
    return ToolResult(
        modified,
        f"{verb} {applied} element(s) on slide {slide_index + 1}",
        changed_indexes=[slide_index],
    )


async def execute_add_element(
    spec: PresentationSpec, slide_index: int, element: dict, **kwargs: Any,
) -> ToolResult:
    """Append one validated element to a slide."""
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    validated = _validate_elements([element])
    if validated is None:
        return ToolResult(
            spec,
            "Invalid element. Follow the element shape guide exactly: "
            "use type \"cards\" (never \"card\") and include the required fields.",
            success=False,
        )

    modified = copy.deepcopy(spec)
    modified.slides[slide_index].elements.append(validated[0])
    el_type = getattr(validated[0], "type", "?")
    return ToolResult(
        modified,
        f"Added {el_type} element to slide {slide_index + 1}",
        changed_indexes=[slide_index],
    )


async def execute_update_element(
    spec: PresentationSpec, slide_index: int, **kwargs: Any,
) -> ToolResult:
    """Patch ONE element in place — text, level, position (x/y/w), animation,
    media fields or content items — without rebuilding the whole slide.

    The patched element is revalidated through the discriminated union, so an
    invalid shape for its type is rejected instead of being persisted.
    """
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    patch = {
        field: kwargs[field]
        for field in _ELEMENT_PATCHABLE_FIELDS
        if kwargs.get(field) is not None
    }
    if not patch:
        return ToolResult(
            spec,
            "Nothing to update — provide at least one of: "
            + ", ".join(sorted(_ELEMENT_PATCHABLE_FIELDS)),
            success=False,
        )

    if "animation" in patch:
        anim = str(patch["animation"]).strip()
        if anim.lower() in ("", "none", "null"):
            patch["animation"] = None
        else:
            custom_names = {
                (d.get("name") if isinstance(d, dict) else getattr(d, "name", ""))
                for d in (spec.meta.customAnimations or [])
            }
            if anim not in BUILTIN_ANIMATIONS and anim not in custom_names:
                return ToolResult(
                    spec,
                    f"Unknown animation '{anim}'. Use a built-in ({', '.join(BUILTIN_ANIMATIONS)}) "
                    f"or define it first with define_custom_animation.",
                    success=False,
                )
            patch["animation"] = anim

    if "style" in patch:
        style_value = patch["style"]
        if not isinstance(style_value, dict):
            return ToolResult(
                spec,
                'style must be an object like {"color": "#ff0000", "font_size": "48px"} '
                "(allowed keys: color, font_size, font_weight, align, opacity, rotation)",
                success=False,
            )
        merged_style = {k: v for k, v in style_value.items() if v is not None}
        from app.generation.spec import ElementStyle

        try:
            ElementStyle.model_validate(merged_style)
        except Exception:
            return ToolResult(
                spec,
                "Invalid style object. Allowed keys: color, font_size, font_weight, "
                "align (left/center/right/justify), opacity (0-1), rotation (degrees).",
                success=False,
            )
        patch["style"] = merged_style

    if "animation_delay" in patch:
        try:
            patch["animation_delay"] = max(0, min(int(patch["animation_delay"]), 10000))
        except (TypeError, ValueError):
            return ToolResult(spec, "animation_delay must be an integer (ms)", success=False)

    modified = copy.deepcopy(spec)
    slide = modified.slides[slide_index]

    targets, err = _resolve_target_indexes(
        slide, kwargs.get("element_index"), kwargs.get("element_text"),
    )
    if err:
        return ToolResult(spec, err, success=False)
    if len(targets) > 1:
        return ToolResult(
            spec,
            f"element_text matched {len(targets)} elements — be more specific or use element_index",
            success=False,
        )

    idx = targets[0]
    el = slide.elements[idx]
    data = el.model_dump() if hasattr(el, "model_dump") else dict(el)

    # Nested merge: updating one style key keeps the others.
    if isinstance(patch.get("style"), dict):
        existing_style = data.get("style") or {}
        if hasattr(existing_style, "model_dump"):
            existing_style = existing_style.model_dump()
        patch["style"] = {**existing_style, **patch["style"]}

    # Reject fields that don't belong to this element's type (pydantic would
    # silently drop them, which would fake a successful edit).
    model_fields = set(getattr(type(el), "model_fields", {}).keys())
    unknown = [k for k in patch if k not in model_fields]
    if unknown:
        return ToolResult(
            spec,
            f"Field(s) {', '.join(sorted(unknown))} not valid for a '{data.get('type')}' element. "
            f"Valid fields: {', '.join(sorted(model_fields))}",
            success=False,
        )

    data.update(patch)
    try:
        slide.elements[idx] = _element_adapter.validate_python(data)
    except Exception:
        return ToolResult(
            spec,
            f"Invalid patch for a '{data.get('type')}' element. Check field shapes in the element shape guide.",
            success=False,
        )

    updated = ", ".join(sorted(patch))
    return ToolResult(
        modified,
        f"Updated element {idx} ({data.get('type')}) on slide {slide_index + 1}: {updated}",
        changed_indexes=[slide_index],
    )


async def execute_update_deck_meta(spec: PresentationSpec, **kwargs: Any) -> ToolResult:
    """Patch deck-level metadata (title, language, tone, theme)."""
    patch = {
        key: kwargs[key]
        for key in ("title", "language", "tone", "theme")
        if kwargs.get(key) is not None
    }
    if not patch:
        return ToolResult(spec, "Nothing to update — provide title, language, tone and/or theme", success=False)

    modified = copy.deepcopy(spec)
    limits = {"title": 200, "language": 40, "tone": 40, "theme": 40}
    for key, value in patch.items():
        setattr(modified.meta, key, str(value)[: limits[key]])
    if "theme" in patch:
        for slide in modified.slides:
            slide.theme = patch["theme"]

    return ToolResult(
        modified,
        f"Updated deck meta: {', '.join(sorted(patch))}",
        changed_indexes=list(range(len(modified.slides))),
    )


async def execute_move_element(
    spec: PresentationSpec, slide_index: int, to_index: int, **kwargs: Any,
) -> ToolResult:
    """Reorder an element within a slide (changes stacking/reading order)."""
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    modified = copy.deepcopy(spec)
    slide = modified.slides[slide_index]

    targets, err = _resolve_target_indexes(
        slide, kwargs.get("element_index"), kwargs.get("element_text"),
    )
    if err:
        return ToolResult(spec, err, success=False)

    from_idx = targets[0]
    try:
        to_idx = int(to_index)
    except (TypeError, ValueError):
        return ToolResult(spec, "Invalid to_index", success=False)
    if to_idx < 0 or to_idx >= len(slide.elements):
        return ToolResult(spec, f"Invalid to_index {to_index}", success=False)
    if from_idx == to_idx:
        return ToolResult(spec, "Source and destination are the same", success=False)

    el = slide.elements.pop(from_idx)
    slide.elements.insert(to_idx, el)
    return ToolResult(
        modified,
        f"Moved element {from_idx} to position {to_idx} on slide {slide_index + 1}",
        changed_indexes=[slide_index],
    )


async def execute_update_custom_slide(
    spec: PresentationSpec, slide_index: int, **kwargs: Any,
) -> ToolResult:
    """Create or patch the html/css/js of a custom-coded slide."""
    if slide_index < 0 or slide_index >= len(spec.slides):
        return ToolResult(spec, f"Invalid slide index {slide_index}", success=False)

    patches = {
        field: kwargs[field]
        for field in ("html", "css", "js")
        if kwargs.get(field) is not None
    }
    if not patches:
        return ToolResult(spec, "Nothing to update — provide html, css and/or js", success=False)

    from app.generation.spec import CustomSlideCode

    lowered = {k: str(v).lower() for k, v in patches.items()}
    if any(bad in v for v in lowered.values() for bad in ("javascript:", "document.cookie", "localstorage", "window.parent", "top.location")):
        return ToolResult(
            spec,
            "Custom slide code contains forbidden constructs (javascript:, localStorage, document.cookie, parent access). The sandbox blocks them — remove and retry.",
            success=False,
        )

    modified = copy.deepcopy(spec)
    slide = modified.slides[slide_index]
    current = slide.code or CustomSlideCode()
    data = current.model_dump()
    data.update(patches)
    slide.code = CustomSlideCode(**data)
    slide.layout = "custom"

    fields = ", ".join(sorted(patches))
    return ToolResult(
        modified,
        f"Updated custom slide {slide_index + 1} code ({fields})",
        changed_indexes=[slide_index],
    )


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
    "define_custom_animation",
    "set_element_animation",
    "add_element",
    "update_element",
    "move_element",
    "update_deck_meta",
    "update_custom_slide",
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
    "define_custom_animation": execute_define_custom_animation,
    "set_element_animation": execute_set_element_animation,
    "add_element": execute_add_element,
    "update_element": execute_update_element,
    "move_element": execute_move_element,
    "update_deck_meta": execute_update_deck_meta,
    "update_custom_slide": execute_update_custom_slide,
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
