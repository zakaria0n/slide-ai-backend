"""Server-side slide rendering to PNG via headless Chromium.

Shared by the MCP `get_slide_screenshot` tool and the PPTX export (custom /
free-coded slides are captured as full-slide images so PowerPoint files are
never empty).
"""
from __future__ import annotations

import os
import tempfile

from app.export.html_exporter import render_spec_html
from app.export.html_theme import tokens_for
from app.generation.spec import PresentationSpec


async def render_slide_pngs(
    spec: PresentationSpec,
    indices: list[int],
    theme_hint: str | None = None,
    *,
    width: int = 1600,
    height: int = 900,
) -> dict[int, bytes]:
    """Render the requested slides to PNG bytes (one Chromium launch).

    Each slide is rendered as a single-slide deck at its settled state
    (animations off) — ideal for screenshots and static exports.
    Raises RuntimeError when Chromium is missing; callers decide fallback.
    """
    from playwright.async_api import async_playwright

    t = tokens_for(theme_hint or (spec.meta.theme if spec.meta else None))
    outs: dict[int, bytes] = {}
    tmp_paths: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})
        try:
            for idx in indices:
                if idx < 0 or idx >= len(spec.slides):
                    continue
                single = spec.model_copy(deep=True)
                single.slides = [spec.slides[idx]]
                doc = render_spec_html(single, t, animate=False)
                with tempfile.NamedTemporaryFile(
                    suffix=".html", delete=False, mode="w", encoding="utf-8"
                ) as f:
                    f.write(doc)
                    html_path = f.name
                tmp_paths.append(html_path)

                await page.goto(
                    f"file:///{html_path.replace(os.sep, '/')}",
                    wait_until="networkidle",
                )
                # Let iframes / JS settle so custom slides reach their final look.
                await page.wait_for_timeout(600)
                outs[idx] = await page.locator(".slide").first.screenshot()
        finally:
            try:
                await browser.close()
            except Exception:
                pass
            for path in tmp_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return outs


async def render_slide_png(
    spec: PresentationSpec,
    slide_index: int,
    theme_hint: str | None = None,
    *,
    width: int = 1600,
    height: int = 900,
) -> bytes | None:
    outs = await render_slide_pngs(
        spec, [slide_index], theme_hint, width=width, height=height
    )
    return outs.get(slide_index)
