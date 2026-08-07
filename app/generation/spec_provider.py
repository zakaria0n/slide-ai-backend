"""Presentation Specification generation.

Builds a :class:`PresentationSpec` from a :class:`GenerationRequest`.

* The real provider (surfaced only as "Slide AI") is prompted
  to return the strict specification JSON.
* The offline stub produces a valid spec deterministically so the full
  pipeline works without a network key.
* :func:`generate_spec` validates the provider output and **auto-retries**
  (re-asking the model to fix the JSON) when the schema is invalid, per the
  Phase 7 requirement.

This module reuses the existing :class:`GenerationProvider` abstraction; the
spec generator is a thin strategy over it.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.generation.schemas import GenerationRequest
from app.generation.spec import PresentationSpec
from app.templates.library import get_template

DISPLAYED_PROVIDER = "Slide AI"
_MAX_RETRIES = 2


class SpecProvider(ABC):
    """Contract for producing a validated PresentationSpec."""

    @abstractmethod
    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        ...


# The strict schema description embedded in prompts so the model returns the
# exact structure the renderer expects.
_SCHEMA_HINT = """\
Return ONLY valid JSON (no markdown fences, no commentary) with this exact shape:
{
  "meta": {"title": "<concise deck title>", "theme": "<theme_name>|null", "background": null, "language": "<lang>", "tone": "<tone>"},
  "slides": [
    {
      "layout": "<one of: hero, title, agenda, section, timeline, comparison, cards, statistics, pricing, gallery, process, flow, roadmap, team, quote, swot, table, chart, image-left, image-right, cta, conclusion, thank-you>",
      "background": null,
      "theme": null,
      "notes": "<speaker notes or null>",
      "elements": [
        {"type": "title", "text": "...", "level": 1},
        {"type": "subtitle", "text": "..."},
        {"type": "paragraph", "text": "..."},
        {"type": "bullets", "items": ["..."]},
        {"type": "image", "src": null, "alt": "..."},
        {"type": "quote", "text": "...", "author": "..."},
        {"type": "statistics", "items": [{"value": "...", "label": "..."}]},
        {"type": "cards", "items": [{"title": "...", "body": "..."}]},
        {"type": "timeline", "items": [{"year": "...", "text": "..."}]},
        {"type": "comparison", "left": {"title": "...", "points": ["..."]}, "right": {"title": "...", "points": ["..."]}},
        {"type": "table", "headers": ["..."], "rows": [["..."]]},
        {"type": "code", "language": "...", "code": "..."}
      ]
    }
  ]
}

DESIGN RULES — follow these strictly:

1. TITLE RULES (most important):
   - NEVER use the user's raw prompt as a slide title.
   - The meta.title must be a SHORT, PROFESSIONAL name (3-6 words). If the user says "Create a 5-slide investor pitch for a climate tech startup", the title is "ClimateTech" or "GreenVolt", NOT "Create a 5-slide investor pitch...".
   - Each slide's title (level 1 or 2) must be a REAL HEADING that captures the slide's content — not a numbered generic like "1. Overview". Use expressive titles like "The $12B Green Energy Gap" or "How We Cut Costs 60%".
   - Vary title styles: some bold statements, some questions, some data-driven.

2. STORYTELLING & STRUCTURE:
   - Slide 1: hero layout with a powerful, short title + compelling subtitle. Hook the audience immediately.
   - Early slides: set context — what problem exists, why it matters.
   - Middle slides: the solution, evidence, data, comparisons.
   - Late slides: roadmap, team, social proof, call to action.
   - Final slide: thank-you or cta layout.
   - Build a NARRATIVE arc. Each slide should logically lead to the next.

3. VISUAL HIERARCHY & TEXT AMOUNT:
   - Titles: 2-6 words max. Punchy.
   - Subtitles: one line, supplementary context.
   - Bullet points: 3-5 items per slide, each 3-10 words. Concise, not sentences.
   - Paragraphs: 1-2 sentences max per slide. If you need more, use bullets instead.
   - NEVER wall-of-text. A slide should be scannable in 3 seconds.

4. LAYOUT VARIETY — use diverse layouts to maintain visual interest:
   - hero: opening or major section starts
   - title + section: section dividers between topics
   - statistics: when showcasing numbers, metrics, KPIs (use 3-4 stats)
   - comparison: pros vs cons, before vs after, us vs competitors
   - cards: features, pillars, benefits (3-4 cards)
   - timeline: chronological events, milestones, roadmap phases
   - process/flow: step-by-step flows, pipelines
   - team: people with roles
   - quote: testimonials or powerful statements
   - swot: strengths/weaknesses/opportunities/threats analysis
   - table: structured data comparison
   - pricing: pricing tiers
   - chart: bar-chart style data visualization (uses statistics element)
   - cta: call-to-action slides
   - agenda: overview of what will be covered
   - NEVER use the same layout more than twice in a row.

5. CONTENT QUALITY:
   - Use specific, believable data in statistics (e.g., "47% faster" not "faster").
   - Cards should have distinct, meaningful titles — not "Point 1", "Point 2".
   - Timeline entries need real-looking years/labels and descriptive text.
   - Comparisons should have balanced, substantive points on each side.

6. THEME AWARENESS:
   - If a theme is specified, tailor the content style to match.
   - For corporate themes: use formal language, data-driven content.
   - For startup themes: bold claims, growth metrics, vision language.
   - For education themes: clear explanations, structured learning.
   - For minimal themes: less text, more white space, fewer elements per slide.
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (optionally "json").
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.startswith("json"):
            text = text[4:]
        # Remove closing fence.
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _parse_spec(raw: str) -> PresentationSpec:
    cleaned = _strip_fences(raw)
    try:
        data: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ProviderError("The generation response was not valid JSON") from exc
    try:
        return PresentationSpec.validate_spec(data)
    except ValidationError as exc:
        # Re-raise so the caller can retry.
        raise ProviderError("The specification did not match the required schema") from exc


class OnlineSpecProvider(SpecProvider):
    """Real provider client that returns a structured specification."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_provider_base_url.rstrip("/")
        self._api_key = settings.ai_provider_api_key
        self._model = settings.ai_provider_default_model
        self._timeout = settings.ai_request_timeout_seconds

    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        user_prompt = (
            f"Create a {request.slide_count}-slide presentation.\n"
            f"Topic: {request.prompt}\n"
            f"Tone: {request.tone}\n"
            f"Language: {request.language}"
            + (f"\nTheme: {request.theme} — adapt content style to this theme." if request.theme else "")
            + "\n\n"
            f"IMPORTANT: You MUST generate exactly {request.slide_count} slides. No more, no fewer.\n"
            "IMPORTANT: The meta.title must be a SHORT, PROFESSIONAL name (3-6 words). "
            "Do NOT use the user's raw prompt as the title. "
            "Example: prompt 'Create a presentation about AI in healthcare' → title 'AI in Healthcare'.\n"
            "Give every slide a real, expressive title. Vary layouts. Keep text minimal and impactful."
        )
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(_MAX_RETRIES + 1):
                system = _SYSTEM_PROMPT
                template = get_template(request.template_name)
                if template is not None:
                    purposes = ", ".join(s.purpose for s in template.slides)
                    system = (
                        f"Structure the deck following the "
                        f"'{request.template_name}' template structure. "
                        f"Sections to include: {purposes}.\n\n"
                    ) + system
                if attempt > 0:
                    system = system + (
                        "\nFix the previous output to match the schema exactly."
                    )
                payload = {
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.7,
                }
                try:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                except httpx.HTTPError as exc:
                    raise ProviderError(
                        f"{DISPLAYED_PROVIDER} is temporarily unavailable"
                    ) from exc
                if resp.status_code != 200:
                    raise ProviderError(f"{DISPLAYED_PROVIDER} returned an error")
                try:
                    body = resp.json()
                    content = body["choices"][0]["message"]["content"]
                except (KeyError, IndexError, ValueError) as exc:
                    raise ProviderError(
                        "The generation response was malformed"
                    ) from exc
                try:
                    return _parse_spec(content)
                except ProviderError as exc:
                    last_error = exc
                    # Auto-retry on schema failure.
                    continue
        raise ProviderError(
            f"{DISPLAYED_PROVIDER} could not produce a valid specification"
        ) from last_error


class OfflineSpecProvider(SpecProvider):
    """Deterministic generator that builds a topic-aware presentation.

    Used only when no API key is configured at all. Produces a valid spec
    with content derived from the user's prompt — never template garbage.
    """

    # Prefixes to strip from prompts to extract a clean topic.
    _STRIP_PREFIXES = [
        "create a ", "create an ", "make a ", "make an ",
        "build a ", "build an ", "design a ", "design an ",
        "generate a ", "generate an ", "write a ", "write an ",
        "prepare a ", "prepare an ", "draft a ", "draft an ",
        "create ", "make ", "build ", "design ", "generate ", "prepare ", "draft ",
        "presentation about ", "presentation on ", "slides about ", "slides on ",
        "deck about ", "deck on ", "talk about ", "talk on ",
        "a presentation about ", "a presentation on ",
        "a deck about ", "a deck on ",
        "my ",
    ]

    @staticmethod
    def _derive_title(prompt: str) -> str:
        """Extract a short, professional title from the raw prompt."""
        topic = prompt.strip()
        changed = True
        while changed:
            changed = False
            lower = topic.lower()
            for prefix in OfflineSpecProvider._STRIP_PREFIXES:
                if lower.startswith(prefix):
                    topic = topic[len(prefix):].strip()
                    changed = True
                    break
        # Remove trailing punctuation and whitespace.
        topic = topic.rstrip(".!?,;:").strip()
        # Capitalise first letter.
        if topic:
            topic = topic[0].upper() + topic[1:]
        # Truncate to 8 words.
        words = topic.split()
        if len(words) > 8:
            topic = " ".join(words[:8])
        return topic or "Untitled Presentation"

    @staticmethod
    def _pick_layouts(topic: str, count: int) -> list[str]:
        """Choose layouts based on topic keywords and slide count."""
        lower = topic.lower()
        # Keyword → layout hints.
        hints: list[str] = []
        if any(w in lower for w in ("compare", "versus", "vs", "pros and cons", "before and after")):
            hints.append("comparison")
        if any(w in lower for w in ("timeline", "history", "evolution", "roadmap", "milestone")):
            hints.append("timeline")
        if any(w in lower for w in ("statistic", "metric", "data", "number", "kpi", "growth", "revenue")):
            hints.append("statistics")
        if any(w in lower for w in ("feature", "benefit", "pillar", "approach", "strategy")):
            hints.append("cards")
        if any(w in lower for w in ("step", "process", "workflow", "pipeline", "how to")):
            hints.append("process")
        if any(w in lower for w in ("team", "people", "founder", "member")):
            hints.append("team")
        if any(w in lower for w in ("quote", "testimonial", "review")):
            hints.append("quote")
        if any(w in lower for w in ("swot", "strength", "weakness")):
            hints.append("swot")
        if any(w in lower for w in ("table", "comparison table")):
            hints.append("table")
        if any(w in lower for w in ("price", "pricing", "plan", "tier")):
            hints.append("pricing")

        # Build a layout sequence. Always start with hero, end optionally with cta.
        pool = hints if hints else ["statistics", "cards", "timeline", "comparison", "quote", "process"]
        layouts: list[str] = ["hero"]

        # Body slides.
        body_count = max(0, count - 1 - (1 if count > 8 else 0))
        for i in range(body_count):
            if i < len(hints):
                layouts.append(hints[i])
            else:
                # Alternate between pool items.
                layouts.append(pool[i % len(pool)])

        # Closing slide for longer decks.
        if count > 8:
            layouts.append("cta")

        return layouts[:count]

    @staticmethod
    def _build_section_titles(topic: str, count: int) -> list[str]:
        """Generate section titles from the topic."""
        words = topic.split()
        short = words[0] if words else "This"
        titles = [
            f"Understanding {topic}",
            f"Why {short} Matters Now",
            f"Key Challenges in {short}",
            f"The Approach",
            f"Core Results",
            f"Implementation Roadmap",
            f"Measuring Success",
            f"What Comes Next",
            f"Getting Started",
            f"Summary & Next Steps",
        ]
        return titles[:count]

    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        count = max(1, min(request.slide_count, 30))
        topic = self._derive_title(request.prompt)
        short = topic.split()[0] if topic.split() else "This"
        layouts = self._pick_layouts(request.prompt, count)
        section_titles = self._build_section_titles(topic, count)
        tone = request.tone.lower()

        slides: list[dict[str, Any]] = []

        for i, layout in enumerate(layouts):
            title = section_titles[i] if i < len(section_titles) else f"Slide {i + 1}"
            elements: list[dict[str, Any]] = []

            if layout == "hero":
                elements = [
                    {"type": "title", "text": topic, "level": 1},
                    {"type": "subtitle", "text": f"A {tone} overview for {request.language}-speaking audiences"},
                ]
            elif layout == "statistics":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "statistics",
                        "items": [
                            {"value": "47%", "label": f"Impact on {short}"},
                            {"value": "3.2x", "label": "Performance Gain"},
                            {"value": "12k+", "label": "Active Users"},
                        ],
                    },
                ]
            elif layout == "cards":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "cards",
                        "items": [
                            {"title": "Foundation", "body": f"The core principle behind {topic.lower()}"},
                            {"title": "Execution", "body": f"How {short} is applied in practice"},
                            {"title": "Impact", "body": f"Measurable outcomes for stakeholders"},
                        ],
                    },
                ]
            elif layout == "timeline":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "timeline",
                        "items": [
                            {"year": "Phase 1", "text": f"Research and planning for {short}"},
                            {"year": "Phase 2", "text": f"Implementation of core {short} capabilities"},
                            {"year": "Phase 3", "text": "Scaling and optimisation"},
                            {"year": "Phase 4", "text": "Long-term sustainability"},
                        ],
                    },
                ]
            elif layout == "comparison":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "comparison",
                        "left": {
                            "title": "Without",
                            "points": [f"Manual {short} processes", "Inconsistent results", "Higher costs"],
                        },
                        "right": {
                            "title": "With",
                            "points": [f"Streamlined {short} workflow", "Reliable outcomes", "Cost reduction"],
                        },
                    },
                ]
            elif layout == "quote":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "quote",
                        "text": f"{topic} represents a fundamental shift in how organisations approach this domain.",
                        "author": "Industry Analyst",
                    },
                ]
            elif layout == "process":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "bullets",
                        "items": [
                            f"Define objectives and success criteria for {short}",
                            f"Design the approach based on best practices",
                            f"Execute with iterative feedback loops",
                            f"Measure and refine continuously",
                        ],
                    },
                ]
            elif layout == "team":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "bullets",
                        "items": [
                            "Cross-functional expertise",
                            f"Deep experience in {short}",
                            "Proven track record of delivery",
                        ],
                    },
                ]
            elif layout == "swot":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "bullets",
                        "items": [
                            "Strength: Clear value proposition",
                            "Weakness: Early-stage adoption curve",
                            "Opportunity: Growing market demand",
                            "Threat: Competitive landscape",
                        ],
                    },
                ]
            elif layout == "table":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "table",
                        "headers": ["Aspect", "Current", "Proposed"],
                        "rows": [
                            ["Efficiency", "Low", "High"],
                            ["Cost", "High", "Reduced"],
                            ["Scalability", "Limited", "Built-in"],
                        ],
                    },
                ]
            elif layout == "pricing":
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "cards",
                        "items": [
                            {"title": "Starter", "body": "Essential features to get started"},
                            {"title": "Professional", "body": "Advanced capabilities for growing teams"},
                            {"title": "Enterprise", "body": "Full suite with dedicated support"},
                        ],
                    },
                ]
            elif layout == "cta":
                elements = [
                    {"type": "title", "text": f"Get Started with {short}", "level": 1},
                    {"type": "subtitle", "text": "Begin your journey today"},
                ]
            else:
                # Default: title + bullets
                layout = "title"
                elements = [
                    {"type": "title", "text": title, "level": 2},
                    {
                        "type": "bullets",
                        "items": [
                            f"Key insight about {topic.lower()}",
                            f"Supporting evidence and data points",
                            f"Actionable next step for the audience",
                        ],
                    },
                ]

            slides.append({"layout": layout, "elements": elements})

        spec = {
            "meta": {
                "title": topic,
                "theme": request.theme,
                "background": None,
                "language": request.language,
                "tone": request.tone,
            },
            "slides": slides,
        }
        return PresentationSpec.validate_spec(spec)


def build_spec_provider(settings: Settings) -> SpecProvider:
    """Select a spec provider based on configuration."""
    if not settings.ai_provider_api_key:
        return OfflineSpecProvider()
    return OnlineSpecProvider(settings)


_SYSTEM_PROMPT = (
    "You are Slide AI, a world-class presentation designer. "
    "You create stunning, professional presentations that tell compelling stories. "
    "Every slide you design is visually balanced, content-sparse, and impactful.\n\n"
    + _SCHEMA_HINT
)
