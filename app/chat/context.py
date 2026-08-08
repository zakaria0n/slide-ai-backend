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


_SYSTEM_TEMPLATE = """\
You are Slide AI, a friendly and professional presentation assistant. \
You help users create, refine, and discuss their presentations.

You have access to tools that can modify the presentation. Use them ONLY when \
the user clearly wants to change something. For casual conversation, greetings, \
questions, or brainstorming, respond naturally WITHOUT calling any tool.

When you do modify the presentation, briefly explain what you changed.

CURRENT PRESENTATION:
{spec_digest}

The user is currently viewing slide {current_index} of {total_slides}.
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
    msg = _SYSTEM_TEMPLATE.format(
        spec_digest=digest,
        current_index=current_slide_index,
        total_slides=len(spec.slides),
    )
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
