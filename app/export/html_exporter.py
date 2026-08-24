"""Server-side HTML renderer for exports.

Turns a ``PresentationSpec`` into a single, self-contained HTML document.
It mirrors the frontend layouts closely enough to look like the real deck
while staying dependency-free. Animations are recreated with CSS keyframes
(HTML export keeps them; PDF export strips them via a print stylesheet).
"""
from __future__ import annotations

import html
import os
from typing import Any

from app.export.html_theme import ThemeTokens, tokens_for
from app.export.strategy import ExportFormat, ExportStrategy, ExportedFile
from app.generation.spec import PresentationSpec


# ── Google Fonts mapping ────────────────────────────────────────────────────────

_FONT_URLS: dict[str, str] = {
    "'Syne', sans-serif": "Syne:wght@400;600;700;800",
    "'Space Grotesk', sans-serif": "Space+Grotesk:wght@400;500;600;700",
    "'DM Sans', sans-serif": "DM+Sans:wght@400;500;600;700",
    "'Lora', serif": "Lora:wght@400;500;600;700",
    "'SF Pro Display', sans-serif": "Inter:wght@400;500;600;700",
    "'Product Sans', sans-serif": "Inter:wght@400;500;600;700",
    "'Segoe UI', sans-serif": "Inter:wght@400;500;600;700",
}


def _font_link(font_family: str) -> str:
    key = font_family.strip()
    family_name = _FONT_URLS.get(key)
    if not family_name:
        return ""
    return f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={family_name}&display=swap"/>'


# ── Animation definitions ─────────────────────────────────────────────────────

_ANIMATIONS: dict[str, str] = {
    "fade": "anim-fade",
    "slide-up": "anim-slide-up",
    "slide-left": "anim-slide-left",
    "slide-right": "anim-slide-right",
    "scale": "anim-scale",
}


def _anim_cls(el: dict) -> str:
    """Return CSS class name for the element's animation, or empty string."""
    anim = el.get("animation")
    cls = _ANIMATIONS.get(anim) if anim else None
    return cls or ""


def _anim_delay(index: float) -> str:
    """Return an animation-delay CSS snippet."""
    return f"animation-delay:{index * 0.1}s;"


def _custom_slide_srcdoc(code: dict, t: ThemeTokens) -> str:
    """Build the srcdoc for an AI free-coded slide (layout='custom').

    Mirrors the frontend CustomCodeFrame contract: theme tokens as CSS
    variables, `is-active` on body, and a slide:activate event. Chart.js /
    anime.js are NOT bundled here (the exported file stays dependency-free);
    authored JS that references them degrades to its static markup.
    """
    vars_css = (
        f"--bg:{t.bg};--surface:{t.surface};--surface2:{t.surface2};--border:{t.border};"
        f"--text:{t.text};--text-muted:{t.text_muted};--accent:{t.accent};--accent2:{t.accent2};"
        f"--font-heading:{t.font_heading};--font-body:{t.font_body};"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f":root {{{vars_css}}}"
        "html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;"
        "background:var(--bg);color:var(--text);font-family:var(--font-body),system-ui,sans-serif}"
        "</style>"
        f"<style>{code.get('css', '')}</style></head>"
        f"<body>{code.get('html', '')}"
        "<script>window.addEventListener('load',function(){"
        "document.body.classList.add('is-active');"
        "window.dispatchEvent(new CustomEvent('slide:activate'));});</script>"
        f"<script>try{{{code.get('js', '')}}}catch(e){{console.error(e)}}</script>"
        "</body></html>"
    )


def _anim_css() -> str:
    """Generate all animation keyframes and base rules."""
    return """
    @keyframes animFade { from { opacity: 0; } to { opacity: 1; } }
    @keyframes animSlideUp { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: none; } }
    @keyframes animSlideLeft { from { opacity: 0; transform: translateX(-30px); } to { opacity: 1; transform: none; } }
    @keyframes animSlideRight { from { opacity: 0; transform: translateX(30px); } to { opacity: 1; transform: none; } }
    @keyframes animScale { from { opacity: 0; transform: scale(0.92); } to { opacity: 1; transform: none; } }
    .anim-fade        { animation: animFade 0.6s cubic-bezier(.22,1,.36,1) both; }
    .anim-slide-up    { animation: animSlideUp 0.6s cubic-bezier(.22,1,.36,1) both; }
    .anim-slide-left  { animation: animSlideLeft 0.6s cubic-bezier(.22,1,.36,1) both; }
    .anim-slide-right { animation: animSlideRight 0.6s cubic-bezier(.22,1,.36,1) both; }
    .anim-scale       { animation: animScale 0.6s cubic-bezier(.22,1,.36,1) both; }
    """


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def _group(slide: dict) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    for el in slide.get("elements", []):
        by_type.setdefault(el.get("type", ""), []).append(el)
    return by_type


def _card_style(t: ThemeTokens) -> str:
    return (
        f"background:{t.surface};border:1px solid {t.border};"
        f"border-radius:{t.radius_lg};padding:26px;"
    )


def _render_elements(els: list[dict], t: ThemeTokens, i0: int = 0) -> str:
    out: list[str] = []
    for i, el in enumerate(els):
        etype = el.get("type")
        cls = _anim_cls(el)
        cls_attr = f'class="{cls}"' if cls else ""
        delay = _anim_delay(i0 + i) if cls else ""
        if etype == "title":
            lvl = el.get("level", 1)
            size = {1: "clamp(32px,5vw,64px)", 2: "clamp(26px,3.6vw,44px)", 3: "clamp(20px,2.6vw,32px)"}.get(lvl, "clamp(26px,3.6vw,44px)")
            out.append(f'<h1 {cls_attr} style="{delay}font-family:{t.font_heading};font-size:{size};font-weight:800;margin:0;line-height:1.1;letter-spacing:-0.02em;color:{t.text}">{_esc(el.get("text",""))}</h1>')
        elif etype == "subtitle":
            out.append(f'<p {cls_attr} style="{delay}font-family:{t.font_body};font-size:clamp(16px,2vw,24px);color:{t.text_muted};margin:8px 0 0">{_esc(el.get("text",""))}</p>')
        elif etype == "paragraph":
            out.append(f'<p {cls_attr} style="{delay}font-family:{t.font_body};font-size:clamp(15px,1.6vw,20px);line-height:1.6;color:{t.text_muted};max-width:60ch">{_esc(el.get("text",""))}</p>')
        elif etype == "bullets":
            items = "".join(
                f'<li style="display:flex;gap:12px;margin-bottom:12px;font-family:{t.font_body};font-size:clamp(15px,1.6vw,20px);color:{t.text}"><span style="width:8px;height:8px;border-radius:50%;background:{t.accent};margin-top:10px;flex-shrink:0"></span><span>{_esc(b)}</span></li>'
                for b in (el.get("items") or [])
            )
            out.append(f'<ul {cls_attr} style="{delay}list-style:none;padding:0;margin:0">{items}</ul>')
        elif etype == "quote":
            author = el.get("author")
            footer = f'<footer style="margin-top:14px;font-size:15px;color:{t.text_muted};font-style:normal">&mdash; {_esc(author)}</footer>' if author else ""
            out.append(f'<blockquote {cls_attr} style="{delay}font-family:{t.font_body};border-left:4px solid {t.accent2};padding-left:24px;font-style:italic;font-size:clamp(20px,2.6vw,32px);color:{t.text};margin:0">&ldquo;{_esc(el.get("text",""))}&rdquo;{footer}</blockquote>')
        elif etype == "code":
            out.append(f'<pre {cls_attr} style="{delay}background:#0a0a14;border:1px solid {t.border};border-radius:{t.radius};padding:20px;overflow:auto;font-family:ui-monospace,monospace;color:#c8c8ff;font-size:14px"><code>{_esc(el.get("code",""))}</code></pre>')
        elif etype == "image":
            if el.get("src"):
                out.append(f'<div {cls_attr} style="{delay}border-radius:{t.radius_lg};overflow:hidden;border:1px solid {t.border}"><img src="{_esc(el.get("src"))}" alt="{_esc(el.get("alt",""))}" style="width:100%;display:block"/></div>')
            else:
                out.append(f'<div {cls_attr} style="{delay}border-radius:{t.radius_lg};border:1px solid {t.border};background:{t.surface2};min-height:160px;display:flex;align-items:center;justify-content:center;color:{t.text_muted};font-style:italic">{_esc(el.get("alt","Image"))}</div>')
        elif etype == "table":
            headers = el.get("headers") or []
            rows = el.get("rows") or []
            thead = "".join(f'<th style="text-align:left;padding:12px 14px;border-bottom:2px solid {t.border};color:{t.accent}">{_esc(h)}</th>' for h in headers) if headers else ""
            body = "".join(
                "<tr>" + "".join(f'<td style="padding:12px 14px;border-bottom:1px solid {t.border};color:{t.text}">{_esc(c)}</td>' for c in r) + "</tr>"
                for r in rows
            )
            out.append(f'<div {cls_attr} style="{delay}overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-family:{t.font_body};font-size:15px">{("<thead><tr>"+thead+"</tr></thead>") if thead else ""}<tbody>{body}</tbody></table></div>')
        elif etype == "icon":
            out.append(f'<span {cls_attr} style="{delay}font-size:28px" title="{_esc(el.get("label",""))}">✨</span>')
        elif etype == "diagram":
            kind = el.get("kind", "diagram")
            label = el.get("label", "")
            out.append(f'<div {cls_attr} style="{delay}border:2px dashed {t.border};border-radius:{t.radius_lg};padding:40px;text-align:center;color:{t.text_muted};font-style:italic">[Diagram: {_esc(kind)}]{" — " + _esc(label) if label else ""}</div>')
    return "".join(out)


def _render_complex(slide: dict, g: dict[str, list[dict]], t: ThemeTokens) -> str:
    out: list[str] = []
    title_html = _render_elements(g.get("title", []), t)
    if "cards" in g:
        items = (g["cards"][0].get("items") or []) if g.get("cards") else []
        cells = "".join(
            f'<div style="{_card_style(t)}"><div style="font-family:{t.font_heading};font-weight:700;font-size:18px;margin-bottom:8px;color:{t.text}">{_esc(it.get("title",""))}</div><div style="color:{t.text_muted};font-size:15px;line-height:1.5">{_esc(it.get("body",""))}</div></div>'
            for it in items
        )
        out.append(f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:8px">{cells}</div>')
    if "statistics" in g:
        items = (g["statistics"][0].get("items") or []) if g.get("statistics") else []
        cells = "".join(
            f'<div style="{_card_style(t)};text-align:center"><div style="font-family:{t.font_heading};font-weight:800;font-size:clamp(30px,4vw,48px);background:{t.gradient};-webkit-background-clip:text;background-clip:text;color:transparent">{_esc(it.get("value",""))}</div><div style="color:{t.text_muted};margin-top:6px;font-size:15px">{_esc(it.get("label",""))}</div></div>'
            for it in items
        )
        out.append(f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-top:8px">{cells}</div>')
    if "timeline" in g:
        items = (g["timeline"][0].get("items") or []) if g.get("timeline") else []
        rows = "".join(
            f'<div style="display:flex;gap:18px;align-items:flex-start;margin-bottom:18px"><div style="width:16px;height:16px;border-radius:50%;background:{t.accent};margin-top:4px;flex-shrink:0"></div><div><div style="font-family:{t.font_heading};font-weight:700;color:{t.accent3};font-size:16px">{_esc(it.get("year",it.get("time","")))}</div><div style="color:{t.text}">{_esc(it.get("text",""))}</div></div></div>'
            for it in items
        )
        out.append(f'<div style="margin-top:10px">{rows}</div>')
    if "comparison" in g:
        cmp = g["comparison"][0] if g.get("comparison") else {}
        cell_style = "margin:0;padding-left:18px;color:" + t.text
        cols = ""
        for col, tc in ((cmp.get("left", {}), t.accent), (cmp.get("right", {}), t.accent2)):
            points = "".join(
                '<li style="margin-bottom:8px">' + _esc(p) + "</li>"
                for p in (col.get("points") or [])
            )
            cols += (
                '<div style="' + _card_style(t) + ";border-color:" + tc + '">'
                '<div style="font-family:' + t.font_heading + ";font-weight:700;margin-bottom:12px;color:" + tc + '">'
                + _esc(col.get("title", "")) + "</div>"
                '<ul style="' + cell_style + '">' + points + "</ul></div>"
            )
        out.append('<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:8px">' + cols + "</div>")
    return title_html + "".join(out)


def render_spec_html(spec: PresentationSpec, theme: ThemeTokens, animate: bool = True) -> str:
    meta = spec.meta or {}
    theme_name = getattr(meta, "theme", None) or "modern"
    global_t = tokens_for(theme_name) if theme is None else theme
    slides_html: list[str] = []
    for slide in spec.slides:
        s = slide.model_dump() if hasattr(slide, "model_dump") else slide
        # Per-slide theme override
        slide_theme_name = s.get("theme")
        t = tokens_for(slide_theme_name) if slide_theme_name else global_t
        bg = s.get("background") or t.bg

        # AI free-coded slide (layout="custom"): embed the authored code
        # verbatim inside an isolated iframe so its scripts/styles can't leak.
        code = s.get("code") or {}
        if s.get("layout") == "custom" and isinstance(code, dict) and (code.get("html") or code.get("css") or code.get("js")):
            srcdoc = _custom_slide_srcdoc(code, t)
            slides_html.append(
                f'<section class="slide print-break" data-slide '
                f'style="background:{bg};border-radius:{t.radius_lg};position:relative;overflow:hidden">'
                f'<iframe sandbox="allow-scripts" style="border:0;position:absolute;inset:0;width:100%;height:100%" '
                f'srcdoc="{html.escape(srcdoc, quote=True)}"></iframe>'
                f'</section>'
            )
            continue

        g = _group(s)
        # Title is rendered inside _render_complex (which prepends it). Only
        # subtitle + paragraph go here so the title isn't emitted twice.
        body = _render_elements(g.get("subtitle", []) + g.get("paragraph", []), t)
        body += _render_complex(s, g, t)
        body += _render_elements([e for et in ("bullets", "quote", "code", "table", "image", "icon", "diagram") for e in g.get(et, [])], t, i0=10)
        slides_html.append(
            f'<section class="slide print-break" data-slide '
            f'style="background:{bg};border-radius:{t.radius_lg};border:1px solid {t.border};'
            f'padding:clamp(24px,4vw,64px);color:{t.text};box-sizing:border-box;overflow:hidden;'
            f'display:flex;flex-direction:column;justify-content:flex-start">'
            f'{body}'
            f'</section>'
        )

    # Collect unique font links
    font_links: set[str] = set()
    for s in spec.slides:
        sd = s.model_dump() if hasattr(s, "model_dump") else s
        stn = sd.get("theme")
        st = tokens_for(stn) if stn else global_t
        for f in (st.font_heading, st.font_body):
            link = _font_link(f)
            if link:
                font_links.add(link)
    # Also add global theme fonts
    for f in (global_t.font_heading, global_t.font_body):
        link = _font_link(f)
        if link:
            font_links.add(link)

    anim_css = _anim_css() if animate else ""
    font_links_html = "\n".join(sorted(font_links))
    title_escaped = _esc(getattr(meta, "title", "Slide AI Presentation"))

    # CSS for the navigation/presentation shell. Slides are sized to fit the
    # viewport while keeping 16:9 (contain, not cover — exports don't crop).
    # All slides are present in the DOM; only .active is visible. Print mode
    # overrides everything to stack the slides for PDF.
    presentation_css = """
  html, body { height: 100%; margin: 0; background: #000; overflow: hidden; }
  .stage {
    position: fixed; inset: 0;
    display: flex; align-items: center; justify-content: center;
    background: #000;
  }
  .slide {
    position: absolute;
    width: min(100vw, 177.78vh);
    height: min(100vh, 56.25vw);
    box-shadow: 0 30px 90px rgba(0,0,0,0.5);
    visibility: hidden;
    opacity: 0;
    transition: opacity 0.35s ease;
  }
  .slide.active { visibility: visible; opacity: 1; }
  .controls {
    position: fixed; left: 0; right: 0; bottom: 0;
    display: flex; align-items: center; gap: 12px;
    padding: 12px 20px;
    background: linear-gradient(to top, rgba(0,0,0,0.65), transparent);
    color: #c0c0d8;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    z-index: 10;
  }
  .ctrl-btn {
    padding: 8px 14px; border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.12);
    background: rgba(20,20,32,0.55); color: #fff;
    font-size: 14px; cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }
  .ctrl-btn:hover { background: rgba(40,40,56,0.7); }
  .ctrl-btn:active { transform: scale(0.97); }
  .ctrl-btn:disabled { color: #555; cursor: default; opacity: 0.5; }
  .counter {
    font-size: 13px; font-variant-numeric: tabular-nums;
    color: rgba(255,255,255,0.85); white-space: nowrap;
  }
  .progress {
    flex: 1; height: 4px; border-radius: 2px; overflow: hidden;
    background: rgba(255,255,255,0.2); min-width: 80px;
  }
  .progress > span {
    display: block; height: 100%;
    background: linear-gradient(90deg, #7c6aff, #ff6ac1);
    transition: width 0.3s ease-out;
  }
  @media print {
    html, body { height: auto; overflow: visible; background: #fff; }
    .stage { position: static; display: block; background: #fff; }
    .slide {
      position: static; width: 100%; height: auto; aspect-ratio: 16/9;
      visibility: visible; opacity: 1; box-shadow: none; page-break-after: always;
    }
    .controls { display: none !important; }
    [class^="anim-"] { animation: none !important; }
  }
  @media (prefers-reduced-motion: reduce) {
    [class^="anim-"] { animation: none !important; transition: none !important; }
    .slide { transition: none !important; }
  }
"""

    # Vanilla JS — must work in file:// (no modules, no fetch). Animations
    # are replayed on every slide change by cloning the slide's innerHTML,
    # which forces the browser to restart any CSS animation on the new nodes.
    presentation_js = """
(function () {
  var slides = Array.prototype.slice.call(document.querySelectorAll('[data-slide]'));
  var total = slides.length;
  if (total === 0) return;
  var current = 0;
  var counterEl = document.getElementById('counter');
  var prevBtn = document.getElementById('prev');
  var nextBtn = document.getElementById('next');
  var fsBtn = document.getElementById('fullscreen');
  var progressBar = document.getElementById('progress-bar');
  var stage = document.querySelector('.stage');

  // Stash each slide's original HTML so we can reset+replay animations by
  // re-injecting it (cloning nodes restarts CSS animations).
  slides.forEach(function (s) { s.setAttribute('data-original', s.innerHTML); });

  function show(idx) {
    if (idx < 0 || idx >= total) return;
    // Hide all, show active.
    slides.forEach(function (s, i) {
      if (i === idx) {
        s.classList.add('active');
        // Replay animations: re-inject original HTML → fresh DOM nodes →
        // animations start from initial state again.
        s.innerHTML = s.getAttribute('data-original');
      } else {
        s.classList.remove('active');
      }
    });
    current = idx;
    if (counterEl) counterEl.textContent = (idx + 1) + ' / ' + total;
    if (prevBtn) prevBtn.disabled = idx === 0;
    if (nextBtn) nextBtn.disabled = idx === total - 1;
    if (progressBar) progressBar.style.width = (((idx + 1) / total) * 100) + '%';
  }
  function next() { if (current < total - 1) show(current + 1); }
  function prev() { if (current > 0) show(current - 1); }

  if (prevBtn) prevBtn.addEventListener('click', function (e) { e.stopPropagation(); prev(); });
  if (nextBtn) nextBtn.addEventListener('click', function (e) { e.stopPropagation(); next(); });
  if (fsBtn) fsBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    if (!document.fullscreenElement) {
      (document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || function(){}).call(document.documentElement);
    } else {
      (document.exitFullscreen || document.webkitExitFullscreen || function(){}).call(document);
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    switch (e.key) {
      case 'ArrowRight': case 'PageDown': case ' ':
        e.preventDefault(); next(); break;
      case 'ArrowLeft': case 'PageUp':
        e.preventDefault(); prev(); break;
      case 'Home':
        e.preventDefault(); show(0); break;
      case 'End':
        e.preventDefault(); show(total - 1); break;
      case 'f': case 'F':
        e.preventDefault(); if (fsBtn) fsBtn.click(); break;
    }
  });

  // Click zones: left third = prev, right two-thirds = next.
  // Ignore clicks that originate from the controls bar.
  if (stage) {
    stage.addEventListener('click', function (e) {
      if (e.target.closest('.controls') || e.target.closest('.ctrl-btn')) return;
      var rect = stage.getBoundingClientRect();
      var x = (e.clientX - rect.left) / rect.width;
      if (x < 0.33) prev(); else next();
    });
    // Touch swipe
    var touchX = null;
    stage.addEventListener('touchstart', function (e) {
      touchX = e.changedTouches[0] ? e.changedTouches[0].clientX : null;
    }, { passive: true });
    stage.addEventListener('touchend', function (e) {
      if (touchX === null) return;
      var dx = (e.changedTouches[0] ? e.changedTouches[0].clientX : 0) - touchX;
      if (Math.abs(dx) > 50) { if (dx < 0) next(); else prev(); }
      touchX = null;
    }, { passive: true });
  }

  show(0);
})();
"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title_escaped}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
{font_links_html}
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family:{global_t.font_body}; }}
{anim_css}
{presentation_css}
</style></head>
<body>
  <div class="stage">
    {"".join(slides_html)}
  </div>
  <div class="controls">
    <button class="ctrl-btn" id="prev" title="Previous (←)">&lsaquo;</button>
    <span class="counter" id="counter">1 / {len(slides_html)}</span>
    <div class="progress"><span id="progress-bar" style="width:0%"></span></div>
    <button class="ctrl-btn" id="fullscreen" title="Fullscreen (F)">&#x26F6;</button>
    <button class="ctrl-btn" id="next" title="Next (→)">&rsaquo;</button>
  </div>
  <script>
{presentation_js}
  </script>
</body></html>"""


class HtmlExportStrategy(ExportStrategy):
    format = ExportFormat.HTML

    def export(self, spec: PresentationSpec, theme_hint: str | None = None) -> ExportedFile:
        t = tokens_for(theme_hint or (getattr(spec.meta, "theme", None) if spec.meta else None))
        doc = render_spec_html(spec, t, animate=True)
        title = getattr(spec.meta, "title", "presentation") if spec.meta else "presentation"
        safe = "".join(c if c.isalnum() else "-" for c in str(title)).strip("-") or "presentation"
        return ExportedFile(doc.encode("utf-8"), "text/html", f"{safe}.html")


class PdfExportStrategy(ExportStrategy):
    """Renders the HTML export to a real vector PDF via Playwright (Chromium headless)."""

    format = ExportFormat.PDF

    async def export(self, spec: PresentationSpec, theme_hint: str | None = None) -> ExportedFile:
        import asyncio
        import tempfile

        from playwright.async_api import async_playwright

        t = tokens_for(theme_hint or (getattr(spec.meta, "theme", None) if spec.meta else None))
        doc = render_spec_html(spec, t, animate=False)
        title = getattr(spec.meta, "title", "presentation") if spec.meta else "presentation"
        safe = "".join(c if c.isalnum() else "-" for c in str(title)).strip("-") or "presentation"

        # Write HTML to a temp file so Chromium can load it via file://
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(doc)
            html_path = f.name

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(f"file:///{html_path.replace(os.sep, '/')}", wait_until="networkidle")
                pdf_bytes = await page.pdf(
                    width="1280px",
                    height="720px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
                await browser.close()
        except Exception as exc:
            # The most common cause is a missing Chromium binary —
            # `playwright install chromium` must be run manually after pip install.
            from app.core.exceptions import ProviderError

            msg = str(exc)
            if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
                raise ProviderError(
                    "PDF export requires the Chromium binary. "
                    "Run `python -m playwright install chromium` on the server."
                ) from exc
            raise ProviderError(f"PDF export failed: {exc}") from exc
        finally:
            try:
                os.unlink(html_path)
            except OSError:
                pass

        return ExportedFile(pdf_bytes, "application/pdf", f"{safe}.pdf")
