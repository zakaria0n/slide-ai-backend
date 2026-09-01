"""Outline-first generation: propose a slide plan before generating the deck.

``generate_outline`` asks the model for a concise, ordered plan — one entry
per slide with a short title and 2-4 key points. The caller (dashboard flow)
lets the user review/reorder/edit the plan, then generates the full deck
with ``GenerationRequest.outline`` set.
"""
from __future__ import annotations

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.core.model_catalog import resolve_model
from app.generation.llm import complete_json
from app.generation.schemas import OutlineItem

_SYSTEM = """\
You are a presentation architect. Given a topic, produce a slide-by-slide
outline for a presentation. Return ONLY valid JSON:
{"outline": [{"title": "<slide heading, 2-8 words>", "points": ["<key point>", "..."]}]}
Rules:
- One entry per slide, in presentation order.
- The FIRST entry is the opening slide (hook); the LAST is the closing/call-to-action.
- 2-4 short key points per slide (they guide the content, not full sentences).
- Titles are REAL headings specific to the topic — never "Overview" or "Introduction".
- Build a narrative arc: context → core ideas → evidence/data → conclusion.
"""


async def generate_outline(
    settings: Settings,
    *,
    prompt: str,
    slide_count: int,
    language: str = "English",
    tone: str = "Professional",
    model: str | None = None,
) -> list[OutlineItem]:
    """Generate an approved-outline plan for a deck (no slides yet)."""
    resolved = await resolve_model(settings, model)
    data = await complete_json(
        settings,
        model=resolved,
        system=_SYSTEM,
        user=(
            f"Topic: {prompt}\n"
            f"Number of slides: {slide_count}\n"
            f"Language: {language}\n"
            f"Tone: {tone}\n"
            "Produce exactly that many outline entries."
        ),
        max_tokens=3000,
    )
    entries = data.get("outline") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise ProviderError("The outline response was empty")
    items: list[OutlineItem] = []
    for raw in entries[:30]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        points = [str(p).strip() for p in (raw.get("points") or []) if str(p).strip()]
        items.append(OutlineItem(title=title[:300], points=points[:12]))
    if not items:
        raise ProviderError("The outline response was unusable")
    return items
