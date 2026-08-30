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

import asyncio
import json
import random
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
# If the requested/default model repeatedly fails, retry the whole generation
# once with the first of these that exists in the provider catalog.
_FALLBACK_MODELS = ["hy3-free", "nemotron-3.5-lightning-free", "deepseek-v4-flash-free"]

_GENERIC_TITLE_RE = None  # compiled lazily


def _spec_quality_feedback(spec) -> list[str]:
    """Deterministic quality checks — fed back to the model on retries.

    These are structural issues we can measure without taste: under-filled
    layouts and placeholder-ish titles. Never blocks a deck; only shapes
    the retry prompt.
    """
    issues: list[str] = []
    generic_titles = {"untitled", "overview", "introduction", "conclusion", "content", "agenda"}
    for i, slide in enumerate(spec.slides):
        layout = slide.layout
        counts: dict[str, int] = {}
        for el in slide.elements:
            counts[el.type] = counts.get(el.type, 0) + 1
        if layout == "statistics" and counts.get("statistics", 0) and _items_len(slide, "statistics") < 3:
            issues.append(f"slide {i + 1} (statistics): fewer than 3 stat items — add at least 3")
        if layout == "cards" and counts.get("cards", 0) and _items_len(slide, "cards") < 3:
            issues.append(f"slide {i + 1} (cards): fewer than 3 cards — add at least 3")
        if counts.get("bullets", 0) and _bullets_count(slide) < 3:
            issues.append(f"slide {i + 1}: fewer than 3 bullet points — expand the list")
        if layout == "timeline" and counts.get("timeline", 0) and _items_len(slide, "timeline") < 4:
            issues.append(f"slide {i + 1} (timeline): fewer than 4 entries")
        if layout == "comparison" and counts.get("comparison", 0) and _comparison_min(slide) < 3:
            issues.append(f"slide {i + 1} (comparison): fewer than 3 points on a side")
        if layout == "table" and counts.get("table", 0) and _table_rows(slide) < 3:
            issues.append(f"slide {i + 1} (table): fewer than 3 data rows")
        for el in slide.elements:
            text = getattr(el, "text", None)
            if getattr(el, "type", "") == "title" and text and str(text).strip().lower() in generic_titles:
                issues.append(f'slide {i + 1}: title "{text}" is generic — write a real expressive heading')
    return issues[:12]


def _items_len(slide, el_type: str) -> int:
    for el in slide.elements:
        if getattr(el, "type", "") == el_type:
            return len(getattr(el, "items", []) or [])
    return 0


def _bullets_count(slide) -> int:
    total = 0
    for el in slide.elements:
        if getattr(el, "type", "") == "bullets":
            total += len(getattr(el, "items", []) or [])
    return total


def _comparison_min(slide) -> int:
    for el in slide.elements:
        if getattr(el, "type", "") == "comparison":
            left = len(getattr(el, "left").points or []) if getattr(el, "left", None) else 0
            right = len(getattr(el, "right").points or []) if getattr(el, "right", None) else 0
            return min(left, right)
    return 0


def _table_rows(slide) -> int:
    for el in slide.elements:
        if getattr(el, "type", "") == "table":
            return len(getattr(el, "rows", []) or [])
    return 0
# Backoff between provider retries (seconds) — free-tier 503s usually clear fast.
_RETRY_BACKOFF_S = [3.0, 8.0]
# Upstream statuses worth retrying (capacity / rate limiting).
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _creative_direction() -> str:
    """Random creative directive appended to each generation request."""
    return random.choice(OnlineSpecProvider._DIRECTIONS)


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
  "meta": {"title": "<concise deck title>", "theme": "<theme_name>|null", "background": null, "language": "<lang>", "tone": "<tone>", "customAnimations": [{"name": "<anim_name>", "keyframes": "@keyframes <anim_name> { ... }", "duration": <ms>, "easing": "<easing>"}]},
  "slides": [
    {
      "layout": "<one of: hero, title, agenda, section, timeline, comparison, cards, statistics, pricing, gallery, process, flow, roadmap, team, quote, swot, table, chart, image-left, image-right, cta, conclusion, thank-you, custom>",
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

2. SPECIFICITY MANDATE (critical for quality):
   - Every statistic, example, name, or claim MUST be specific to the EXACT topic the user gave.
   - NEVER use generic filler: "increased efficiency", "better results", "improved performance", "key benefits", "industry-leading", "best practices", "cutting-edge".
   - If the topic is "gamification in education", mention actual mechanics (XP, badges, leaderboards, spaced repetition), actual platforms (Duolingo, Kahoot, ClassDojo), actual studies with numbers (% retention, % engagement).
   - If the topic is "startup pitch for a coffee brand", mention actual market data (specialty coffee market size, $X billion), actual competitors (Blue Bottle, Stumptown, La Colombe), actual unit economics (CAC, LTV, gross margin per bag).
   - If the topic is "quarterly finance report", mention actual line items (revenue $X, gross margin Y%, OpEx Z%, EBITDA), actual quarters (Q1 2024 vs Q1 2023), actual variance drivers.
   - When you don't have a real number, INVENT a plausible, specific one — "73% of K-12 teachers using gamification report higher homework completion" is far better than "many teachers report improvement".
   - Rule of thumb: if a bullet/stat/comparison could appear unchanged in a deck about ANY other topic, it's too generic — rewrite it.

3. STORYTELLING & STRUCTURE:
   - Slide 1: hero layout with a powerful, short title + compelling subtitle. Hook the audience immediately.
   - Early slides: set context — what problem exists, why it matters.
   - Middle slides: the solution, evidence, data, comparisons.
   - Late slides: roadmap, team, social proof, call to action.
   - Final slide: thank-you or cta layout.
   - Build a NARRATIVE arc. Each slide should logically lead to the next.
   - ADAPT THE STRUCTURE TO THE TOPIC. If the topic is fundamentally a comparison, lead with comparison slides. If it's a process, lead with timeline/process. If it's data-heavy, lead with statistics/chart/table. Do NOT force a generic "problem → solution → market → team" flow on topics where it doesn't fit.

4. VISUAL HIERARCHY & TEXT AMOUNT:
   - Titles: 2-6 words max. Punchy.
   - Subtitles: one line, supplementary context.
   - Bullet points: 3-5 items per slide, each 3-10 words. Concise, not sentences.
   - Paragraphs: 1-2 sentences max per slide. If you need more, use bullets instead.
   - NEVER wall-of-text. A slide should be scannable in 3 seconds.

5. MINIMUM ELEMENTS PER LAYOUT (enforce strictly):
   - layout=statistics → at least 3 stat items, ideally 4
   - layout=cards → at least 3 cards, ideally 4
   - layout=bullets or layouts using a bullets element → at least 4 bullet items
   - layout=comparison → at least 3 points on EACH side (left AND right)
   - layout=timeline → at least 4 timeline entries
   - layout=table → at least 3 data rows (excluding header)
   - layout=pricing → at least 3 pricing tiers
   - layout=process/flow → at least 4 steps
   - layout=swot → at least 1 bullet per quadrant (4 bullets total)
   - layout=chart → at least 4 data points in the statistics element
   - layout=team → at least 3 team entries (use cards if individual bios are needed)
   A slide with only a title and one thin element is a failure — fill the layout meaningfully.

6. LAYOUT VARIETY — use diverse layouts to maintain visual interest:
   - hero: opening or major section starts
   - title + section: section dividers between topics
   - statistics: when showcasing numbers, metrics, KPIs
   - comparison: pros vs cons, before vs after, us vs competitors
   - cards: features, pillars, benefits
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

7. CONTENT QUALITY:
   - Use specific, believable data in statistics (e.g., "47% faster" not "faster").
   - Cards should have distinct, meaningful titles — not "Point 1", "Point 2".
   - Timeline entries need real-looking years/labels and descriptive text.
   - Comparisons should have balanced, substantive points on each side.
   - layout=chart renders as a REAL interactive chart (Chart.js): give 3–6
     items with SHORT axis labels and clean numeric values where possible
     ("38" or "38.4" rather than "about 38ms") — units belong in the label.

8. THEME AWARENESS:
   - If a theme is specified, tailor the content style to match.
   - For corporate themes: use formal language, data-driven content.
   - For startup themes: bold claims, growth metrics, vision language.
   - For education themes: clear explanations, structured learning.
   - For minimal themes: less text, more white space, fewer elements per slide.

9. CUSTOM ANIMATIONS (EXPECTED in every deck):
   - EVERY deck you produce defines 1–2 custom keyframe animations in
     meta.customAnimations and applies them via "animation": "<anim_name>" on
     the hero title, key statistics titles, and the CTA/conclusion title.
     A deck with zero custom animations is an incomplete deck.
   - You may animate ANY CSS property. transform/opacity/filter are the
     smoothest (GPU-accelerated), but box-shadow glows, color shimmers,
     letter-spacing reveals and background-position sweeps are all welcome.
   - The ONLY forbidden things are security hazards: NEVER include url(...),
     expression(...), javascript:, @import or external references inside
     keyframes — those are stripped.
   - "duration": milliseconds 100–4000 (typical 400–900; up to 1500 for hero
     drama; longer for slow ambient loops). Out-of-range values are clamped,
     never dropped.
   - "easing": any timing function — cubic-bezier(...) for personality
     (overshoot y-values like 1.56 give playful bounce), linear for rotations/
     loops/shimmer sweeps, steps(...) for retro reveals. If you omit it you get
     a premium expo-out.
   - Start hidden at 0% (opacity 0 and/or off-transform/scale) and settle fully
     visible and at-rest at 100% so text stays crisp after the entrance.
   - Invent names that fit THIS deck's identity ("riseGlow", "steamRise",
     "pulseGold") — don't reuse the same two names in every deck.

10. CUSTOM-CODED SLIDES (layout="custom" — full creative freedom):
   - For 1–2 SHOWPIECE slides per deck (hero, product reveal, data showcase)
     you may write REAL CODE instead of using elements:
       {"layout": "custom", "elements": [], "notes": "...",
        "code": {"html": "...", "css": "...", "js": "..."}}
   - The slide runs in its own sandboxed frame: the iframe IS the 16:9 slide
     (width/height 100%). You control everything — layout, gradients, canvas,
     SVG, WebGL, particles, animated charts.
   - Preloaded for you: Chart.js (global `Chart`), anime.js v4 (global `anime`)
     and the deck theme as CSS variables (--bg, --surface, --text, --accent,
     --accent2, --gradient, --font-heading...) plus window.__THEME__.
   - Entrance choreography: when the slide becomes visible the body gets class
     `is-active` and a `slide:activate` event fires on window. Start elements
     hidden (opacity 0 / transformed) in CSS, then run your entrance on that
     event. ALWAYS end settled: fully visible, readable, nothing mid-flight.
     Example: document.addEventListener('slide:activate', () =>
     anime({targets:'.reveal', opacity:[0,1], translateY:[40,0], delay:anime.stagger(90)}));
   - HARD RULES (sandbox enforces them anyway): no external network requests
     (no CDN/fetch/img URLs), no localStorage/cookies, no access to parent.
     Everything self-contained in your html/css/js strings.
   - Use custom slides SPARINGLY and purposefully; keep regular structured
     layouts for content-heavy slides so decks stay consistent and editable.

FEW-SHOT EXAMPLES — the level of specificity and density expected:

Example A — topic "gamification in education" (3 slides):
{
  "meta": {"title": "Gamification in Education", "theme": "education", "background": null, "language": "English", "tone": "Professional",
    "customAnimations": [
      {"name": "chalkRise", "keyframes": "@keyframes chalkRise { 0% { opacity: 0; transform: translateY(28px) } 100% { opacity: 1; transform: translateY(0) } }", "duration": 600, "easing": "cubic-bezier(0.16, 1, 0.3, 1)"},
      {"name": "xpPop", "keyframes": "@keyframes xpPop { 0% { opacity: 0; transform: scale(0.7) } 70% { opacity: 1; transform: scale(1.05) } 100% { opacity: 1; transform: scale(1) } }", "duration": 450, "easing": "ease-out"}
    ]},
  "slides": [
    {"layout": "hero", "elements": [
      {"type": "title", "text": "Classrooms, Reimagined as Games", "level": 1, "animation": "chalkRise"},
      {"type": "subtitle", "text": "How XP, badges, and leaderboards are reshaping K-12 and higher-ed engagement"}
    ]},
    {"layout": "statistics", "elements": [
      {"type": "title", "text": "The Engagement Dividend", "level": 2, "animation": "xpPop"},
      {"type": "statistics", "items": [
        {"value": "73%", "label": "Teachers using Kahoot report higher homework completion"},
        {"value": "2.3×", "label": "Daily active sessions on Duolingo vs traditional apps"},
        {"value": "$1.5B", "label": "EdTech gamification market, 2024 → 2030 (CAGR 27%)"},
        {"value": "61%", "label": "Students say streaks are the #1 reason they return daily"}
      ]}
    ]},
    {"layout": "comparison", "elements": [
      {"type": "title", "text": "Traditional vs Gameful Classrooms", "level": 2, "animation": "chalkRise"},
      {"type": "comparison", "left": {
        "title": "Traditional",
        "points": ["Single grade per quarter", "Failure = permanent", "Same pace for everyone", "Extrinsic (fear of F)"]
      }, "right": {
        "title": "Gameful",
        "points": ["XP & badges every session", "Mistakes = respawns, not F", "Adaptive difficulty (ClassDojo)", "Intrinsic streaks & mastery"]}
      }
    ]}
  ]
}

Example B — topic "quarterly finance report" (3 slides):
{
  "meta": {"title": "Q3 2024 Financial Review", "theme": "finance", "background": null, "language": "English", "tone": "Professional",
    "customAnimations": [
      {"name": "ledgerIn", "keyframes": "@keyframes ledgerIn { 0% { opacity: 0; transform: translateY(20px) } 100% { opacity: 1; transform: translateY(0) } }", "duration": 550, "easing": "cubic-bezier(0.16, 1, 0.3, 1)"}
    ]},
  "slides": [
    {"layout": "hero", "elements": [
      {"type": "title", "text": "Q3 2024: Margin-Driven Growth", "level": 1, "animation": "ledgerIn"},
      {"type": "subtitle", "text": "Revenue +18% YoY, gross margin 64.2%, EBITDA $12.4M"}
    ]},
    {"layout": "table", "elements": [
      {"type": "title", "text": "P&L Snapshot ($M)", "level": 2},
      {"type": "table", "headers": ["Line item", "Q3 2023", "Q3 2024", "Δ"],
      "rows": [
        ["Revenue", "28.1", "33.2", "+18%"],
        ["Gross profit", "16.3", "21.3", "+31%"],
        ["OpEx", "8.9", "9.7", "+9%"],
        ["EBITDA", "7.4", "11.6", "+57%"]
      ]}
    ]},
    {"layout": "cards", "elements": [
      {"type": "title", "text": "Variance Drivers", "level": 2},
      {"type": "cards", "items": [
        {"title": "Enterprise tier +24%", "body": "Multi-year deals closed with 3 Fortune-500 logos"},
        {"title": "Gross margin +6.1pts", "body": "AWS contract renegotiated, -19% on compute"},
        {"title": "OpEx +9%", "body": "Headcount +12 (sales), fully absorbed by revenue scale"},
        {"title": "Cash position $48M", "body": "Runway extended to Q4 2026 at current burn"}
      ]}
    ]}
  ]
}

Example C — topic "startup pitch for a coffee brand" (3 slides):
{
  "meta": {"title": "Verde Coffee Roasters", "theme": "startup", "background": null, "language": "English", "tone": "Bold",
    "customAnimations": [
      {"name": "steamRise", "keyframes": "@keyframes steamRise { 0% { opacity: 0; transform: translateY(18px) scale(0.96); filter: blur(4px) } 100% { opacity: 1; transform: translateY(0) scale(1); filter: blur(0) } }", "duration": 650, "easing": "cubic-bezier(0.16, 1, 0.3, 1)"},
      {"name": "roastGlow", "keyframes": "@keyframes roastGlow { 0% { box-shadow: 0 0 0 rgba(230,126,34,0) } 100% { box-shadow: 0 0 32px rgba(230,126,34,.45) } }", "duration": 900, "easing": "ease-in-out"}
    ]},
  "slides": [
    {"layout": "hero", "elements": [
      {"type": "title", "text": "Specialty Coffee, Direct to Office", "level": 1, "animation": "steamRise"},
      {"type": "subtitle", "text": "Single-origin beans, IoT-roasted, delivered to 5,000+ workplaces in 12 cities"}
    ]},
    {"layout": "statistics", "elements": [
      {"type": "title", "text": "The Market Window", "level": 2},
      {"type": "statistics", "items": [
        {"value": "$48B", "label": "US specialty coffee market (2024)"},
        {"value": "67%", "label": "Offices without a quality coffee setup"},
        {"value": "$2.40", "label": "Our cost per cup vs $5.20 at the café next door"},
        {"value": "8.4/10", "label": "Average NPS across 1,200 pilot employees"}
      ]}
    ]},
    {"layout": "timeline", "elements": [
      {"type": "title", "text": "Roadmap to Profitability", "level": 2},
      {"type": "timeline", "items": [
        {"year": "Q1 2025", "text": "Launch 3 new metros (Austin, Denver, Atlanta) — 1,200 sites"},
        {"year": "Q3 2025", "text": "Open Nashville roastery, cutting COGS by 22%"},
        {"year": "Q1 2026", "text": "Launch B2C subscription tier targeting 50K households"},
        {"year": "Q4 2026", "text": "Break-even at $24M ARR; raise Series B"}
      ]}
    ]}
  ]
}

Example D — topic "product launch keynote" showing CUSTOM ANIMATIONS (3 slides):
{
  "meta": {"title": "Aurora Engine Launch", "theme": "startup", "background": null, "language": "English", "tone": "Bold",
    "customAnimations": [
      {"name": "riseGlow", "keyframes": "@keyframes riseGlow { 0% { opacity: 0; transform: translateY(36px) scale(0.96); filter: blur(6px) } 60% { opacity: 1; filter: blur(0px) } 100% { opacity: 1; transform: none; filter: none } }", "duration": 700, "easing": "cubic-bezier(0.16, 1, 0.3, 1)"},
      {"name": "glowPulse", "keyframes": "@keyframes glowPulse { 0% { opacity: 0; box-shadow: 0 0 0 rgba(64,220,255,0) } 60% { opacity: 1; box-shadow: 0 0 44px rgba(64,220,255,.55) } 100% { opacity: 1; box-shadow: 0 0 16px rgba(64,220,255,.3) } }", "duration": 900, "easing": "cubic-bezier(0.16, 1, 0.3, 1)"},
      {"name": "popIn", "keyframes": "@keyframes popIn { 0%, 20% { opacity: 0; transform: scale(0.6) } 80%, 100% { opacity: 1; transform: scale(1) } }", "duration": 450, "easing": "ease-out"}
    ]},
  "slides": [
    {"layout": "hero", "elements": [
      {"type": "title", "text": "Aurora: Real-Time Rendering, Reimagined", "level": 1, "animation": "riseGlow"},
      {"type": "subtitle", "text": "4.2× faster scenes, zero GPU upgrades"}
    ]},
    {"layout": "statistics", "elements": [
      {"type": "title", "text": "Why Teams Are Switching", "level": 2},
      {"type": "statistics", "items": [
        {"value": "4.2×", "label": "Faster render on the same hardware"},
        {"value": "38ms", "label": "Avg frame time in heavy scenes"},
        {"value": "12k", "label": "Studios on the early-access list"},
        {"value": "99.98%", "label": "Uptime across the public beta"}
      ]}
    ]},
    {"layout": "conclusion", "elements": [
      {"type": "title", "text": "Early Access Now Open", "level": 2, "animation": "glowPulse"},
      {"type": "paragraph", "text": "Join 12,000 studios shaping the future of real-time graphics."}
    ]}
  ]
}

Example E — CUSTOM-CODED showpiece slide (inside the slides array):
{
  "layout": "custom",
  "elements": [],
  "notes": "Hero reveal with animated counter and orbiting particles.",
  "code": {
    "html": "<div class='stage'><canvas id='orbit'></canvas><div class='center'><h1 class='reveal'>Aurora Engine</h1><p class='reveal'>Real-time rendering at <span id='fps'>0</span> fps</p></div></div>",
    "css": ".stage{position:relative;width:100%;height:100%;background:radial-gradient(ellipse at 50% 120%, #1a0b2e, var(--bg));overflow:hidden}.center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}.reveal{opacity:0}h1{font-family:var(--font-heading);font-size:clamp(40px,6vw,84px);margin:0;background:var(--gradient);-webkit-background-clip:text;background-clip:text;color:transparent}p{color:var(--text-muted)}canvas{position:absolute;inset:0}",
    "js": "document.addEventListener('slide:activate', function(){ anime({targets:'.reveal',opacity:[0,1],translateY:[36,0],delay:anime.stagger(140,{start:150}),duration:800,easing:'outExpo'}); var o={v:0},el=document.getElementById('fps'); anime({targets:o,v:144,duration:1400,easing:'outExpo',update:function(){el.textContent=Math.round(o.v)}}); });"
  }
}
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

    # Motion/structure personalities rotated per generation so repeated topics
    # produce visually distinct decks instead of converging on one template.
    _DIRECTIONS = [
        "Open with a dramatic custom-coded hero (layout='custom'): oversized kinetic typography, staggered reveals, a live counter or animated gradient backdrop.",
        "Lead with momentum: timeline/process structure, custom 'riseGlow'-style entrance on the hero title, stats that count up.",
        "Go editorial: comparison and quote layouts front and center, slow blur-focus entrances, generous whitespace.",
        "Data-first: statistics/chart layouts dominate, animate numbers popping in with overshoot (bounce bezier), connect figures into one narrative.",
        "Cinematic minimal: few elements per slide, long smooth drift+fade entrances, one bold statement per slide.",
        "High-energy pitch: cards with playful bounce-in (y-overshoot bezier), a custom-coded showpiece slide mid-deck, punchy 3-4 word titles.",
    ]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.ai_provider_base_url.rstrip("/")
        self._api_key = settings.ai_provider_api_key
        self._model = settings.ai_provider_default_model
        self._timeout = settings.ai_request_timeout_seconds

    async def generate_spec(self, request: GenerationRequest) -> PresentationSpec:
        # Caller-selected model (settings page / dashboard), validated against
        # the provider catalog; falls back to the configured default.
        from app.core.model_catalog import list_model_ids, resolve_model

        model = await resolve_model(self._settings, request.model)

        # Fallback chain: if the primary model cannot produce a valid spec,
        # try one alternate from the catalog before giving up.
        candidates = [model]
        try:
            ids = set(await list_model_ids(self._settings))
        except Exception:  # pragma: no cover - defensive
            ids = set()
        for candidate in _FALLBACK_MODELS:
            if candidate != model and (not ids or candidate in ids):
                candidates.append(candidate)
                break

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                return await self._generate_with_model(candidate, request)
            except ProviderError as exc:
                last_error = exc
        raise last_error or ProviderError(
            f"{DISPLAYED_PROVIDER} is busy right now and could not generate your deck. "
            "Please try again in a minute — or pick a different model in Settings."
        )

    async def _generate_with_model(self, model: str, request: GenerationRequest) -> PresentationSpec:
        # Per-generation creative direction — rotates so two runs on the SAME
        # topic diverge in structure and motion instead of converging.
        direction = _creative_direction()
        user_prompt = (
            f"Create a {request.slide_count}-slide presentation.\n"
            f"Topic: {request.prompt}\n"
            f"Tone: {request.tone}\n"
            f"Language: {request.language}"
            + (f"\nTheme: {request.theme} — adapt content style to this theme." if request.theme else "")
            + f"\n\nCREATIVE DIRECTION for THIS deck (follow it): {direction}"
            + "\n\n"
            f"CRITICAL: You MUST generate exactly {request.slide_count} slides. No more, no fewer.\n"
            "CRITICAL: Every statistic, name, and example MUST be specific to the topic above. "
            "No generic filler. If the topic is about a domain, mention real players, real numbers, "
            "real mechanics from that domain.\n"
            "CRITICAL: Adapt the structure to what makes sense for THIS topic — don't force a generic flow. "
            "If the topic is fundamentally a comparison, lead with comparison; if it's a process, "
            "use timeline/process with real steps; if it's data-heavy, use statistics/chart/table.\n"
            "CRITICAL: The meta.title must be a SHORT, PROFESSIONAL name (3-6 words), never the raw prompt. "
            "Example: prompt 'Create a presentation about AI in healthcare' → title 'AI in Healthcare'.\n"
            "CRITICAL: Respect the minimum elements per layout (statistics ≥ 3 items, cards ≥ 3, "
            "bullets ≥ 4, comparison ≥ 3 per side, timeline ≥ 4, table ≥ 3 rows).\n"
            "Give every slide a real, expressive title. Vary layouts. Keep text scannable.\n"
            f"CRITICAL: Write ALL slide content in {request.language}."
        )
        if request.source_content:
            material = request.source_content[:6000]
            user_prompt += (
                "\n\nSOURCE MATERIAL — base the deck's facts, structure and wording on "
                "the material below (stay faithful to it, do not invent contradicting data):\n"
                f"<source>\n{material}\n</source>"
            )
        last_error: Exception | None = None
        quality_issues: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(_MAX_RETRIES + 1):
                system = _SYSTEM_PROMPT
                if request.theme == "custom":
                    system = _CUSTOM_MODE_PROMPT + "\n\n" + system
                template = get_template(request.template_name)
                if template is not None:
                    layouts_hint = ", ".join(s.layout for s in template.slides)
                    purposes_hint = "; ".join(s.purpose for s in template.slides)
                    system = (
                        f"A content curator pre-suggested the '{request.template_name}' "
                        f"template for this topic. Recommended layouts (you may pick any "
                        f"subset and reorder freely): {layouts_hint}.\n"
                        f"Suggested sections: {purposes_hint}.\n"
                        f"You DON'T have to use all of them — pick the ones that fit the "
                        f"actual content, and add others if the topic calls for it.\n\n"
                    ) + system
                if attempt > 0:
                    system = system + (
                        "\nYour previous output was invalid or too generic. "
                        "Fix the JSON AND make every element topic-specific with real numbers."
                    )
                if quality_issues:
                    system = system + (
                        "\nQUALITY ISSUES measured in your previous output — fix ALL of them:\n- "
                        + "\n- ".join(quality_issues)
                    )
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.75,
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
                    # Network/timeout failure — retry with backoff; free-tier
                    # endpoints hiccup often.
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)])
                        continue
                    raise ProviderError(
                        f"{DISPLAYED_PROVIDER} is temporarily unavailable"
                    ) from exc
                if resp.status_code in _TRANSIENT_STATUS and attempt < _MAX_RETRIES:
                    # Upstream capacity errors (503/502/429) — wait and retry.
                    await asyncio.sleep(_RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)])
                    continue
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
                    parsed = _parse_spec(content)
                except ProviderError as exc:
                    last_error = exc
                    # Auto-retry on schema failure.
                    continue
                try:
                    issues = _spec_quality_feedback(parsed)
                except Exception:  # pragma: no cover - checks must never fail a deck
                    issues = []
                if issues and attempt < _MAX_RETRIES:
                    quality_issues = issues
                    last_error = ProviderError("quality: " + "; ".join(issues[:3]))
                    continue
                return parsed
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


_CUSTOM_MODE_PROMPT = """
CUSTOM CREATIVE MODE (theme = 'custom') - FULL CREATIVE FREEDOM:
The user picked the 'custom' theme: you are NOT limited to the standard
layout catalog or the preset animation names.
- Author MOST slides as layout="custom" with your own self-contained
  HTML/CSS/JS (rule 10): invent any layout, composition, typography, or
  artwork (canvas, SVG, particles, WebGL). The structured element layouts
  are optional tools, not obligations.
- Author your OWN keyframe animations (meta.customAnimations) for every
  motion; you may ignore the built-in animation names entirely. Any CSS
  property is allowed.
- The ONLY hard requirements: EXACTLY the requested number of slides,
  content deeply specific to the topic, and every custom slide ends fully
  visible and settled on 'slide:activate'.
- Use structured layouts only where they genuinely serve clarity.
"""

_SYSTEM_PROMPT = (
    "You are Slide AI, a world-class presentation designer. "
    "You create stunning, professional presentations that tell compelling stories. "
    "Every slide you design is visually balanced, scannable in 3 seconds, yet "
    "packed with topic-specific evidence — real numbers, named players, concrete "
    "mechanics from the user's domain. Never generic. Always specific.\n\n"
    + _SCHEMA_HINT
)
