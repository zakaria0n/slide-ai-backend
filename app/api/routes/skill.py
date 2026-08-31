"""Slide AI Skill — a downloadable skill package for AI coding agents.

Serves a ZIP containing SKILL.md (open skills format) that teaches client
LLMs how to drive the Slide AI MCP: build decks themselves with the tools,
structure content, author animations, verify visually with screenshots, and
avoid delegating generation to another AI.
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
  Create, inspect and edit beautiful slide presentations through the Slide AI
  MCP server. Use this skill whenever the user asks for a presentation, deck
  or slides, or wants to modify an existing one. IMPORTANT: build decks
  YOURSELF using the Slide AI MCP tools — do not delegate generation to
  another AI model unless the user explicitly asks for it.
---

# Slide AI — presentation toolbox for LLM agents

You are the intelligence. Slide AI is your execution layer: it stores decks,
renders slides (web + PDF + PPTX + screenshots) and exposes tools to create
and edit structured presentations.

## Golden rules

1. **Build decks YOURSELF.** Use the MCP tools directly. Only call
   `generate_presentation` / `ai_edit_presentation` when the user explicitly
   asks to "send this to the Slide AI generator" — those delegate to a
   separate AI model.
2. **Think before building**: analyze the subject, define a narrative arc
   (context -> problem -> solution -> proof -> next step), then create.
3. **Verify visually**: after building or editing, call
   `get_slide_screenshot` to SEE the rendered slide and fix overflow,
   overlaps or ugly spacing.
4. **Respect the user's slide count and subject.** Everything else
   (structure, design, animations) is your creative space.

## Core workflow (new deck)

1. `create_presentation` (title) -> returns the presentation id.
2. For each slide: `add_slide` (layout + title), then `add_element` or
   `update_element` to fill content.
3. Add motion: `define_custom_animation` (CSS keyframes — any property) then
   `set_element_animation` to apply it.
4. For showpiece slides: `update_custom_slide` writes full HTML/CSS/JS
   rendered in a sandboxed 16:9 iframe (Chart.js and anime.js preloaded).
5. `get_slide_screenshot` to check the result; iterate if needed.

## Element shapes (add_element / update_element / new_elements)

- title: {"type":"title","text":"...","level":1}
- subtitle: {"type":"subtitle","text":"..."}
- paragraph: {"type":"paragraph","text":"..."}
- bullets: {"type":"bullets","items":["..."]}
- image: {"type":"image","src":"<url>","alt":"..."}
- cards: {"type":"cards","items":[{"title":"...","body":"..."}]}
- timeline: {"type":"timeline","items":[{"year":"...","text":"..."}]}
- comparison: {"type":"comparison","left":{"title":"...","points":[...]},"right":{...}}
- quote: {"type":"quote","text":"...","author":"..."}
- statistics: {"type":"statistics","items":[{"value":"42","label":"..."}]}
- code: {"type":"code","code":"...","language":"..."}
- table: {"type":"table","headers":[...],"rows":[[...]]}
- icon: {"type":"icon","name":"rocket","label":"..."}

Every element accepts free Canvas placement: "x" and "y" (percent of the
slide), "w" (width percent), "h" (height percent) — plus "style" overrides
(color, font_size, font_weight, align, opacity, rotation) and
"animation_delay" (ms).

## Layouts

blank, title, hero, section, agenda, bullets, cards, statistics, comparison,
timeline, process, flow, roadmap, table, chart, pricing, team, quote, swot,
image-left, image-right, gallery, two-column, big-stat, cta, conclusion,
thank-you, custom (full code). Layout "blank" is an empty canvas: use it with
free-positioned elements for complete control.

## Themes

custom (FULL creative freedom — preferred by MCP users), modern, corporate,
startup, education, medical, finance, luxury, minimal, glass, dark, neon,
apple, google, microsoft, openai.

## DIAGRAMS, ARCHITECTURE & FLOWS (reports, stage projects, systems)

When the subject or source material describes a process, architecture,
pipeline, journey, org chart or system: **NEVER insert a static image or a
"[diagram]" placeholder. BUILD the diagram as live animated SVG/HTML** with
`update_custom_slide`:
- Nodes as rounded rects (SVG `<rect rx>` or styled divs), connectors as
  `<line>`/`<path>` with arrowheads (`<marker>`), labels on every node.
- Animate the FLOW: connectors draw themselves
  (`stroke-dasharray` + animate `stroke-dashoffset`), nodes pop in sequence
  following the logical order, the current stage glows (accent color).
- For cycles/loops, animate a moving dot along the path
  (`<animateMotion>` or JS-driven).
- Keep text in the diagram REAL (labels, not lorem), sized to fit boxes.

## ALGORITHMS — STEP-BY-STEP MOTION EXPLANATIONS

When the subject is an algorithm, a calculation, or a procedure: do NOT
paste static code and text. Build a MOTION-GRAPHIC EXPLANATION with
`update_custom_slide`:
- Left: the code/pseudocode with the active line highlighted per step.
- Right: a live visualization of the data — array as boxes, pointers/arrows,
  variables as chips that update values.
- Step captions below: what happens at this step and why (1 short sentence).
- Progression: auto-advance every 1.5-2.5s, or Previous/Next buttons in the
  slide. Start on `slide:activate`, end on the final state (sorted array,
  found path, result value).
- Close with a summary slide: complexity (time/space), the one key insight.
Example subjects: sorting, BFS/DFS, fibonacci/DP, auth flow, CI/CD pipeline,
loan approval process, project methodology.

## REPORTS (rapport de stage, project reports, PFE)

For internship/project reports the deck IS the defense:
- Structure: context & company -> problem/objectives -> solution/what you
  built -> architecture diagram (animated, see above) -> demos/results with
  real numbers -> difficulties & solutions -> what you learned -> next steps.
- Use the source material facts (import or user text); never invent company
  names, dates or metrics.
- Methodology/tooling slides (Gantt, sprint flow) belong as animated
  diagrams too.

## Common mistakes to avoid

- Calling generate_presentation by default. DON'T. Build it yourself.
- Forgetting `get_slide_elements` before editing — read, then patch.
- Slides with 10+ elements — split them.
- Titles longer than ~70 chars, or bullet lists longer than 7 items.
- Text that overflows the slide — keep x/y within 0-96 and check with a
  screenshot.
- Animations that never end visible: start hidden, end fully readable.
"""


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
        zf.writestr("slide-ai/SKILL.md", _SKILL_MD)
        zf.writestr("slide-ai/reference/tools.md", _tools_md())
        zf.writestr("slide-ai/reference/INSTALL.md", install_md)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="slide-ai-skill.zip"'},
    )
