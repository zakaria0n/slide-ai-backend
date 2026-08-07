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
        g = _group(s)
        body = _render_elements(g.get("title", []) + g.get("subtitle", []) + g.get("paragraph", []), t)
        body += _render_complex(s, g, t)
        body += _render_elements([e for et in ("bullets", "quote", "code", "table", "image", "icon", "diagram") for e in g.get(et, [])], t, i0=10)
        bg = s.get("background") or t.bg
        slides_html.append(
            f'<section class="slide print-break" style="width:100%;aspect-ratio:16/9;max-height:100%;background:{bg};border-radius:{t.radius_lg};border:1px solid {t.border};padding:clamp(24px,4vw,64px);padding-top:clamp(24px,4vw,64px);color:{t.text};box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-start">'
            f'<div style="margin-top:24px">{body}</div>'
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
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(getattr(meta, 'title', 'Slide AI Presentation'))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
{font_links_html}
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:{global_t.bg}; font-family:{global_t.font_body}; }}
  .deck {{ display:flex; flex-direction:column; gap:40px; padding:40px; align-items:center; }}
  {anim_css}
  @media print {{
    body {{ background:#fff; }}
    .deck {{ gap:0; padding:0; }}
    .print-break {{ page-break-after: always; break-after: page; }}
    [class^="anim-"] {{ animation: none !important; }}
  }}
</style></head>
<body><div class="deck">{"".join(slides_html)}</div></body></html>"""


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
