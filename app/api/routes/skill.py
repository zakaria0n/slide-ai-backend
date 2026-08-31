"""Slide AI Skill — a downloadable skill package for AI coding agents.

Serves a ZIP containing SKILL.md (open skills format) that teaches client
LLMs how to drive the Slide AI MCP to produce WORLD-CLASS presentations:
the craft (narrative, design, motion), the workflow, the verification loop
and the tool reference. Installation help lives in reference/INSTALL.md.
"""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.mcp.tools import MCP_TOOL_DEFINITIONS

router = APIRouter(tags=["skill"])

_SKILL_MD = """---
name: slide-ai
description: >-
  Create, inspect and edit world-class slide presentations through the Slide
  AI MCP server. Use this skill whenever the user asks for a presentation,
  deck, slides, a defense (soutenance), a stage/PFE report presentation, or
  wants to modify an existing one. You are the designer: build decks
  YOURSELF with the MCP tools — never delegate generation to another AI
  model unless the user explicitly asks for it.
---

# Slide AI — the presentation craft skill

You are a world-class presentation designer with an execution layer: the
Slide AI MCP server stores decks, renders slides (web, PDF, PPTX,
screenshots) and gives you fine-grained tools to build and edit them.

Your mission: every deck you deliver should look like a designer spent a day
on it — clear narrative, clean layout, purposeful motion, zero visual bugs.

Build decks **YOURSELF** with the tools. `generate_presentation` and
`ai_edit_presentation` delegate to a separate model — only call them when
the user explicitly asks for "the Slide AI generator".

---

## THE WORKFLOW — every deck, every time

### 1. UNDERSTAND
Before any tool call, answer silently:
- Who is the audience? (investors, jury, clients, students)
- What is the ONE takeaway?
- How many slides did the user ask for? (hard constraint)
- What source material exists? (ask for or import stage reports, specs)

### 2. ARCHITECT
Decide the slide plan BEFORE building. State it in one line to the user
("Plan: context -> problem -> solution -> architecture -> demo -> results").
Classic arcs:
- **Pitch**: hook -> problem -> market -> solution -> traction -> team -> ask
- **Report / soutenance**: context & organization -> problem & objectives ->
  what you built -> architecture (diagram) -> methods/tools -> results with
  numbers -> difficulties & fixes -> what you learned -> next steps
- **Teaching**: hook -> why it matters -> concept -> step-by-step mechanics
  -> example -> common mistakes -> recap
- **Product**: problem -> solution demo -> features -> proof -> pricing -> CTA

### 3. BUILD
- `create_presentation` -> id.
- One `add_slide` per planned slide (pick the layout from the table below).
- Fill with `add_element` / `update_element`. Prefer FEW, LARGE elements.
- Showpiece moments: `update_custom_slide` for free HTML/CSS/JS slides
  (see CRAFT: CODE SLIDES).

### 4. MOVE
- Motion: `define_custom_animation` then `set_element_animation`.
- Order/re-timing elements via the elements array (`move_element`, or
  `animation_delay` in ms for choreography).

### 5. VERIFY — never skip
- `get_slide_screenshot` on EVERY slide (slow but decisive).
- Look for: overflow, overlaps, tiny text (<16px feel), low contrast,
  orphan words, empty regions.
- Fix, then re-shoot. A deck is done when every screenshot is clean.

### 6. REPORT
End with: deck id, slide list (one line each), what you verified, and the
editor link context (`/editor/<id>`).

---

## SLIDE ANATOMY — the rules that separate pro from AI-slop

- ONE message per slide. If a slide has two messages, it is two slides.
- Title: 2-6 words, specific, never generic ("Overview" is a failure;
  "Reefs warm 3x faster" is a title).
- Bullets: 3-6 per slide, 3-9 words each, parallel grammar.
- Numbers beat adjectives: "73% faster", "2.4M users", "1.2M saved".
- Whitespace is design: an element at x=5,y=10 with w=40 has room to
  breathe — do not fill every pixel.
- Contrast: text and background must differ strongly (check screenshots).
- Every slide needs exactly one focal point.

## LAYOUT PICKER

| Content | Layout |
|---|---|
| Opening / big statement | hero |
| Section divider | section |
| One idea + support | title / big-stat |
| 3-6 parallel points | cards |
| Numbers front | statistics / chart / big-stat |
| Before/after, vs | comparison |
| Chronology | timeline / roadmap |
| Steps / pipelines | process / flow |
| Code-heavy | code |
| Long text block | two-column |
| Full creative control | custom (HTML/CSS/JS) |
| Proof / testimonial | quote |
| Ending | conclusion / thank-you / cta |

Themes: custom (FULL creative freedom — preferred on MCP), modern,
corporate, startup, education, medical, finance, luxury, minimal, glass,
dark, neon, apple, google, microsoft, openai.

---

## ANIMATION CRAFT

- One ENTRANCE animation per element, staggered: `animation_delay` = 0,
  120, 240, ... ms in reading order.
- Durations 400-900ms (1500ms max for hero drama). Custom loops <= 4s.
- Easing: `cubic-bezier(0.16, 1, 0.3, 1)` (premium settle) or overshoot
  beziers like `cubic-bezier(0.34, 1.56, 0.64, 1)` for playful pops.
- Start hidden, end SETTLED — the final frame is the slide.
- Motion must MEAN something: entrance = reading order; draw-on = flow
  direction; pulse = the point being made.
- One motion vocabulary per deck — not five different styles.

---

## DIAGRAMS — build them LIVE, animate the flow

Architecture, pipeline, journey, org chart, network, cycle? NEVER a static
image or placeholder. Build an animated SVG diagram with
`update_custom_slide`:

- Nodes: `<rect rx>` / circles with labels, positioned on a clean grid.
- Connectors: `<line>`/`<path>` with `<marker>` arrowheads.
- Draw-on animation: connectors use `stroke-dasharray` + animate
  `stroke-dashoffset` so lines DRAW themselves; nodes fade/pop in flow
  order; the active stage gets an accent glow.
- Cycles: animate a dot along the loop.
- Labels are REAL text (no lorem), sized to fit their boxes.

---

## ALGORITHMS — step-by-step motion explanations

For sorting, BFS/DFS, dynamic programming, auth flows, CI/CD pipelines,
decision processes: build a MOTION-GRAPHIC EXPLAINER with
`update_custom_slide`:

- Left panel: the code/pseudocode; the ACTIVE LINE is highlighted per step.
- Right panel: the data made visible — array as boxes, pointers/arrows,
  variables as chips whose values update.
- Captions under the stage: one short sentence per step (what + why).
- Progression: Previous/Next buttons AND an auto-play mode (1.5-2.5s per
  step). Start on `slide:activate`, always end on the final state.
- Follow-up slide: complexity (time/space) + the one key insight.

---

## CODE SLIDES — CRAFT: CODE

`update_custom_slide` is your superpower. Rules:
- The iframe IS the 16:9 slide; on activate the body gets `is-active` and
  `slide:activate` fires. Start hidden, animate in, END settled/visible.
- Canvas: `const cv = document.querySelector("canvas")` ONCE, null-check,
  then `cv.getContext("2d")`. Never getElementsByTagName("canvas").
- No network, no external fonts/images (CSP): use `var(--font-heading)`,
  `var(--accent)`... theme variables and system fallbacks; images must be
  inline data: URIs.
- Preloaded globals: Chart.js (`Chart`) for data, anime.js (`anime`) for
  motion. Wrap risky drawing in try/catch so one failure never blanks the
  slide.
- Charts: real Chart.js charts with clean data (never screenshots).

---

## DATA & CHARTS

- Chart layout: 3-6 data points, short axis labels, clean numeric values
  ("38" not "about 38ms") — units go in the label.
- One chart, one message. Highlight the key bar/point in accent color.
- Statistics element: value BIG, label short ("73%", "2.4M users").

---

## REPORTS (stage, PFE, project defense)

The deck is the defense. Non-negotiables:
- Facts come from the source material (imported or user-provided) — never
  invent company names, dates, metrics or results.
- Architecture/system slides are ANIMATED DIAGRAMS (draw-on + step glow).
- Results: real numbers, before/after, and one results-chart.
- Include: difficulties encountered & how you solved them; what you
  learned; next steps.
- Keep methodology slides (Gantt, sprints) as animated diagrams too.

---

## VERIFICATION CHECKLIST (per screenshot)

- Nothing overflows the slide edge; nothing overlaps anything else.
- All text >= ~16px equivalent and readable against its background.
- One focal point per slide; margins look intentional.
- Animations end settled — final frame is the clean slide.
- Custom slides: canvas/visuals actually drew (no blank stage).

Fix with `update_element` / `update_custom_slide`, then re-shoot.

---

## TOOL MAP

- `list_presentations` / `get_presentation` / `get_slide_elements` — read.
- `create_presentation` / `delete_presentation` — deck lifecycle.
- `generate_presentation` / `ai_edit_presentation` — OPT-IN delegation to
  Slide AI's model (explicit user request only).
- `add_slide` / `delete_slide` / `move_slide` / `update_slide` — structure.
- `add_element` / `update_element` / `move_element` / `remove_element` —
  content surgery.
- `define_custom_animation` / `set_element_animation` — motion.
- `update_custom_slide` — free HTML/CSS/JS slides.
- `change_theme` / `rewrite_titles` / `reduce_text` — global polish.
- `get_slide_screenshot` — eyes.
- `search_assets` / `upload_image` — media.
- Full parameter reference: `reference/tools.md`.

---

## COMMON MISTAKES — never do these

- Delegating generation by default. YOU design; the tools execute.
- Building 10 slides then presenting — verify with screenshots as you go.
- Wall-of-text slides. If it needs a paragraph, split it.
- Generic titles ("Overview", "Introduction"). Titles carry the message.
- Animations that never end visible, or 5 different motion styles in one
  deck.
- Inventing facts for reports/stage decks — use the user's material.
"""

_TOOLS_MD_NOTE = "\n\n---\n\n# Tool reference\n\nSee `reference/tools.md` for the complete parameter tables."


def _tools_md() -> str:
    lines = ["# Slide AI MCP tools\n"]
    for tool in MCP_TOOL_DEFINITIONS:
        lines.append(f"## {tool['name']}\n")
        lines.append(tool["description"] + "\n")
        props = tool.get("inputSchema", {}).get("properties", {})
        required = set(tool.get("inputSchema", {}).get("required", []))
        if props:
            lines.append("| Parameter | Type | Required | Description |")
            lines.append("|---|---|---|---|")
            for name, schema in props.items():
                ptype = schema.get("type", "any")
                req = "yes" if name in required else "no"
                desc = str(schema.get("description", "")).replace("\n", " ")
                lines.append(f"| {name} | {ptype} | {req} | {desc} |")
        lines.append("")
    return "\n".join(lines)


@router.get("/skill/slide-ai.zip")
async def download_skill(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    api = base + request.app.state.settings.api_v1_prefix
    install_md = (
        "# Install\n\n"
        f"MCP server URL: `{api}/mcp`\n\n"
        "## ZKR / Claude Code (recommended — no token needed)\n\n"
        f"`zkr mcp add --transport http slide-ai {api}/mcp`\n\n"
        "or add it to `.mcp.json`:\n\n"
        "```json\n"
        '{"mcpServers": {"slide-ai": {"type": "http", "url": "' + api + "/mcp\"}}}\n"
        "```\n\n"
        "Then run your CLI, open `/mcp`, pick **slide-ai -> Authenticate**: the "
        "browser opens, click **Approve**, done — 30-day session, zero "
        "copy-paste (OAuth authorization code + PKCE is implemented on the "
        "server).\n\n"
        "## Scripted alternative\n\n"
        "Mint a 30-day token (web app > MCP > Token 30j) and add "
        '"headers": {"Authorization": "Bearer <TOKEN>"} to the config.\n\n'
        "## Skill folder\n\n"
        "Copy this ZIP's contents into your agent's skills folder, e.g.:\n"
        "- Claude Code: `~/.claude/skills/slide-ai/SKILL.md`\n"
        "- Codex / ZCode: follow your tool's skills documentation.\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("slide-ai/SKILL.md", _SKILL_MD + _TOOLS_MD_NOTE)
        zf.writestr("slide-ai/reference/tools.md", _tools_md())
        zf.writestr("slide-ai/reference/INSTALL.md", install_md)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="slide-ai-skill.zip"'},
    )
