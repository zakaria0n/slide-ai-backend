"""Builds the LLM message context from DB rows + spec digest."""
from __future__ import annotations

from app.generation.spec import PresentationSpec


def build_spec_digest(spec: PresentationSpec) -> str:
    """Compact text summary of the spec (~50 tokens for 10 slides)."""
    lines = [
        f'Presentation: "{spec.meta.title}"',
        f"Theme: {spec.meta.theme or 'none'}",
        f"Language: {spec.meta.language}",
        f"Tone: {spec.meta.tone}",
        f"Slides: {len(spec.slides)}",
    ]
    for i, slide in enumerate(spec.slides):
        title_el = next(
            (e for e in slide.elements if getattr(e, "type", None) == "title"),
            None,
        )
        title_text = getattr(title_el, "text", "") if title_el else "(untitled)"
        lines.append(f"  [{i}] {slide.layout} | \"{title_text}\"")
    return "\n".join(lines)


def _truncate(value, limit: int = 90) -> str:
    text = str(value).replace(chr(10), " ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_current_slide_detail(spec: PresentationSpec, current_slide_index: int) -> str:
    """Spatial text-visualization of the slide the user is viewing.

    Models on the current provider cannot read images (verified by probe),
    so the chat "sees" the current slide through this description instead:
    every element with its index, position, size and content.
    """
    if current_slide_index < 0 or current_slide_index >= len(spec.slides):
        return ""
    slide = spec.slides[current_slide_index]
    lines = [f"CURRENT SLIDE (index {current_slide_index}) - layout: {slide.layout}"]
    if slide.background:
        lines.append(f"  background: {_truncate(slide.background, 120)}")
    if not slide.elements:
        lines.append("  (no elements yet - an empty canvas)")
    for i, el in enumerate(slide.elements):
        parts = [f"[{i}] {getattr(el, 'type', '?')}"]
        text = getattr(el, "text", None)
        if text:
            parts.append('"' + _truncate(text) + '"')
        level = getattr(el, "level", None)
        if level:
            parts.append(f"level={level}")
        x, y, w = getattr(el, "x", None), getattr(el, "y", None), getattr(el, "w", None)
        if x is not None and y is not None:
            pos = f"position x={x}%, y={y}%"
            if w is not None:
                pos += f", width={w}%"
            parts.append(pos + " (free-floating element)")
        anim = getattr(el, "animation", None)
        if anim:
            parts.append(f"animation={anim}")
        items = getattr(el, "items", None)
        if items:
            first = _truncate(str(getattr(items[0], "value", None) or getattr(items[0], "title", None) or items[0]), 60)
            parts.append(f"{len(items)} items, first: {first}")
        author = getattr(el, "author", None)
        if author:
            parts.append(f"by {_truncate(author, 40)}")
        lines.append("  " + " | ".join(parts))
    if slide.layout == "custom" and slide.code is not None:
        sizes = {k: len(getattr(slide.code, k) or "") for k in ("html", "css", "js")}
        lines.append(f"  custom-coded slide (html={sizes['html']}ch, css={sizes['css']}ch, js={sizes['js']}ch)")
    notes = getattr(slide, "notes", None)
    if notes:
        lines.append(f"  speaker notes: {_truncate(notes, 200)}")
    custom = spec.meta.customAnimations or []
    if custom:
        names = [d.get("name") if isinstance(d, dict) else getattr(d, "name", "") for d in custom]
        lines.append(f"  deck custom animations available: {', '.join(n for n in names if n)}")
    lines.append(
        "  (Use get_slide_detail for the full raw JSON of any slide; indexes above match element_index in update_element.)"
    )
    return chr(10).join(lines)


_CUSTOM_MODE_SECTION = """

CREATIVE FREEDOM MODE (theme = 'custom'):
This deck uses the 'custom' theme, which means FULL creative freedom for you:
- Prefer update_custom_slide to author your own self-contained HTML/CSS/JS
  slides - invent any layout, composition, typography or artwork (canvas,
  SVG, particles). The standard layout catalog is optional, not a limit.
- Author your OWN keyframe animations with define_custom_animation for every
  motion the design needs; you may ignore the built-in names entirely.
- You may restructure anything freely. The only hard rules: keep the number
  of slides and stay true to the user's subject.
"""

_SYSTEM_TEMPLATE = """\
You are Slide AI, a friendly and professional presentation assistant. \
You help users create, refine, and discuss their presentations.

You have access to tools that can modify the presentation. Use them ONLY when \
the user clearly wants to change something. For casual conversation, greetings, \
questions, or brainstorming, respond naturally WITHOUT calling any tool.

When you do modify the presentation, briefly explain what you changed.

CURRENT PRESENTATION:
{spec_digest}

{current_slide_detail}

The user is currently viewing slide {current_index} of {total_slides}.
Always write your replies and any new slide content in the deck's language ({language}) unless the user writes in another language.

ANIMATIONS (you have FULL creative freedom — no style filter, only a security sandbox):
- Built-in element animations: fade, slide, scale, zoom, rotate, blur, reveal, typing, counter, gradient, parallax, sequential.
- For anything richer, CREATE custom keyframes: call define_custom_animation(name, keyframes, duration, easing), then apply it with set_element_animation(slide_index, animation=name, element_text="..."). Re-defining an existing name replaces it. You can also patch an element's animation directly with update_element.
- ANY CSS property is allowed inside keyframes — transform, opacity, filter, color, box-shadow, letter-spacing, background-position, clip-path... choreograph multi-step timelines with percentages (0% / 40% / 70% / 100%). Only url(...)/expression(...)/javascript:/@import are stripped by the sandbox — never let security block creativity.
- When the user describes an animation in words ("make the title fly in with a glow", "shimmer effect on the stats", "cinematic 3D flip"), translate their description into keyframes yourself — pick evocative names, keep entrances 400-900ms (up to 1500ms for drama, loops longer), start hidden, end settled and fully readable. Chain: get_slide_detail → define_custom_animation → set_element_animation.

ELEMENT CONTROL (read, then edit precisely):
- get_slide_detail(slide_index) returns the FULL elements array with their indexes. Read before editing.
- update_element(slide_index, element_index, ...) patches ONE element in place: text, heading level, entrance animation, position x/y, width w (percent — x+y makes it float freely over the slide), image alt/caption/src, quote author, items (bullets/cards/timeline/statistics)... Only provided fields change; everything else is preserved.
- move_element(slide_index, to_index, element_index|element_text) reorders elements — use the last index to bring an element to front.
- add_element(slide_index, element) inserts one element; remove_element deletes matching ones.
- update_element also accepts a "style" object (color, font_size, font_weight, align, opacity, rotation) to override the theme look per element, and "animation_delay" (ms) to choreograph entrances precisely.
- update_slide accepts "notes" to write speaker notes; update_deck_meta changes the deck title/language/tone/theme.
- search_assets(query) finds image URLs in the user's library — put a returned url into an image element's src.
- If LIVE RENDER DIAGNOSTICS appear in this prompt, they are REAL measurements from the user's screen: an overflowing or overlapping element must be fixed (adjust x/y/w, shorten text, or reposition).

CUSTOM-CODED SLIDES:
- update_custom_slide(slide_index, html, css, js) writes a self-contained slide rendered in a sandboxed 16:9 iframe. Preloaded: Chart.js (`Chart`), anime.js v4 (`anime`), theme CSS variables (--bg, --surface, --text, --accent, --accent2, --gradient, --font-heading) and window.__THEME__. When the slide becomes visible the body gets class 'is-active' and a 'slide:activate' event fires — start hidden in CSS, run entrances on that event, always end fully visible. No network/localStorage/parent access.
- You can DRAW too: canvas, SVG, particles, animated charts — real code is fine here. Use for showpiece slides or when the user asks for something the structured layouts can't express.

EDIT STRATEGY:
- Prefer precise tools (get_slide_detail → update_element / set_element_animation / add_element / move_element) over rebuilding whole slides. Call get_slide_detail first when editing one specific slide.
"""

# Appended when the caller only has read access. Combined with tool filtering
# (the backend strips edit tools from the request entirely) this gives a
# defense-in-depth guarantee that a viewer can chat without ever mutating.
_VIEWER_SUFFIX = """

IMPORTANT — READ-ONLY ACCESS:
The current user has VIEWER (read-only) access to this presentation. You may
answer questions, explain content, summarise slides, give suggestions, and
discuss ideas in conversation. You MUST NOT call any tool that modifies the
presentation. If the user asks for an edit (add a slide, change the theme,
rewrite text, etc.), politely explain that they only have view access and
would need editor permissions to make changes themselves.
"""


def build_system_message(
    spec: PresentationSpec,
    current_slide_index: int = 0,
    *,
    role: str | None = None,
) -> str:
    digest = build_spec_digest(spec)
    detail = build_current_slide_detail(spec, current_slide_index)
    msg = _SYSTEM_TEMPLATE.format(
        spec_digest=digest,
        current_slide_detail=detail,
        current_index=current_slide_index,
        total_slides=len(spec.slides),
        language=spec.meta.language or "English",
    )
    if spec.meta.theme == "custom":
        msg += _CUSTOM_MODE_SECTION
    if role is None or role in ("owner", "admin", "editor"):
        return msg
    # viewer / unknown → read-only mode
    return msg + _VIEWER_SUFFIX


def build_llm_messages(
    db_messages: list[dict],
    spec: PresentationSpec,
    current_slide_index: int = 0,
    max_history: int = 20,
    *,
    role: str | None = None,
) -> list[dict]:
    """Build the full message list for the LLM."""
    messages: list[dict] = [
        {"role": "system", "content": build_system_message(spec, current_slide_index, role=role)},
    ]

    # Take last N messages from history (skip the latest user msg — it's appended after this)
    recent = db_messages[-max_history:]
    for msg in recent:
        role_label = msg.get("role", "user")
        if role_label in ("user", "assistant"):
            messages.append({"role": role_label, "content": msg.get("content", "")})

    return messages
