"""Deck translation: rewrite every text in a spec into a target language.

Strategy: extract all translatable strings into a numbered map, translate
the map in ONE model call (cheap, consistent terminology across slides),
then write the translations back positionally. Non-text fields (colors,
data series numbers, code, image srcs) are never touched.
"""
from __future__ import annotations

from app.core.config import Settings
from app.core.exceptions import ProviderError
from app.core.model_catalog import resolve_model
from app.generation.llm import complete_json
from app.generation.spec import PresentationSpec

# Max characters sent for translation in one call (safety valve).
_MAX_TEXT_CHARS = 24000

_SYSTEM = """\
You are a professional presentation translator. You receive a JSON object
mapping numeric ids to source strings. Return ONLY valid JSON with the SAME
numeric ids mapping to the strings translated into the target language.
Rules:
- Translate meaning, not word-for-word; keep the presentation tone.
- Keep numbers, %, currency symbols and proper nouns intact.
- Keep it SHORT — these strings go on slides. Never make a translation
  much longer than the source.
- Never merge, drop or reorder entries. Every id must appear exactly once.
- Do not translate code snippets, URLs or file paths — return them unchanged.
"""


def _collect_texts(spec: PresentationSpec) -> dict[str, str]:
    """Walk the spec and collect every human-readable string by stable id."""
    texts: dict[str, str] = {}

    def put(key: str, value) -> None:
        s = str(value or "").strip()
        if s:
            texts[key] = s

    for i, slide in enumerate(spec.slides):
        for j, el in enumerate(slide.elements):
            t = getattr(el, "type", "")
            if t in ("title", "subtitle", "paragraph"):
                put(f"{i}.{j}.text", getattr(el, "text", ""))
            elif t == "bullets":
                for k, item in enumerate(el.items or []):
                    put(f"{i}.{j}.items[{k}]", item)
            elif t == "quote":
                put(f"{i}.{j}.text", getattr(el, "text", ""))
                put(f"{i}.{j}.author", getattr(el, "author", None))
            elif t == "statistics":
                for k, item in enumerate(el.items or []):
                    put(f"{i}.{j}.items[{k}].label", item.label)
            elif t == "cards":
                for k, item in enumerate(el.items or []):
                    put(f"{i}.{j}.items[{k}].title", item.title)
                    put(f"{i}.{j}.items[{k}].body", item.body)
            elif t == "timeline":
                for k, item in enumerate(el.items or []):
                    put(f"{i}.{j}.items[{k}].text", item.text)
            elif t == "comparison":
                put(f"{i}.{j}.left.title", el.left.title)
                put(f"{i}.{j}.right.title", el.right.title)
                for k, p in enumerate(el.left.points or []):
                    put(f"{i}.{j}.left.points[{k}]", p)
                for k, p in enumerate(el.right.points or []):
                    put(f"{i}.{j}.right.points[{k}]", p)
            elif t == "table":
                for k, h in enumerate(el.headers or []):
                    put(f"{i}.{j}.headers[{k}]", h)
                for r, row in enumerate(el.rows or []):
                    for c, cell in enumerate(row or []):
                        if isinstance(cell, str):
                            put(f"{i}.{j}.rows[{r}][{c}]", cell)
        put(f"{i}.notes", slide.notes)

    # Deck title last so it is part of the same single call.
    if spec.meta and spec.meta.title:
        put("meta.title", spec.meta.title)
    return texts


def _apply_translations(spec: PresentationSpec, translations: dict[str, str]) -> None:
    for i, slide in enumerate(spec.slides):
        for j, el in enumerate(slide.elements):
            t = getattr(el, "type", "")
            if t in ("title", "subtitle", "paragraph"):
                new = translations.get(f"{i}.{j}.text")
                if new:
                    el.text = new
            elif t == "bullets":
                for k in range(len(el.items or [])):
                    new = translations.get(f"{i}.{j}.items[{k}]")
                    if new:
                        el.items[k] = new
            elif t == "quote":
                new = translations.get(f"{i}.{j}.text")
                if new:
                    el.text = new
                new = translations.get(f"{i}.{j}.author")
                if new:
                    el.author = new
            elif t == "statistics":
                for k, item in enumerate(el.items or []):
                    new = translations.get(f"{i}.{j}.items[{k}].label")
                    if new:
                        item.label = new
            elif t == "cards":
                for k, item in enumerate(el.items or []):
                    new = translations.get(f"{i}.{j}.items[{k}].title")
                    if new:
                        item.title = new
                    new = translations.get(f"{i}.{j}.items[{k}].body")
                    if new:
                        item.body = new
            elif t == "timeline":
                for k, item in enumerate(el.items or []):
                    new = translations.get(f"{i}.{j}.items[{k}].text")
                    if new:
                        item.text = new
            elif t == "comparison":
                new = translations.get(f"{i}.{j}.left.title")
                if new:
                    el.left.title = new
                new = translations.get(f"{i}.{j}.right.title")
                if new:
                    el.right.title = new
                for k in range(len(el.left.points or [])):
                    new = translations.get(f"{i}.{j}.left.points[{k}]")
                    if new:
                        el.left.points[k] = new
                for k in range(len(el.right.points or [])):
                    new = translations.get(f"{i}.{j}.right.points[{k}]")
                    if new:
                        el.right.points[k] = new
            elif t == "table":
                for k in range(len(el.headers or [])):
                    new = translations.get(f"{i}.{j}.headers[{k}]")
                    if new:
                        el.headers[k] = new
                for r, row in enumerate(el.rows or []):
                    for c, cell in enumerate(row or []):
                        if isinstance(cell, str):
                            new = translations.get(f"{i}.{j}.rows[{r}][{c}]")
                            if new:
                                row[c] = new
        new = translations.get(f"{i}.notes")
        if new:
            slide.notes = new

    if spec.meta:
        new = translations.get("meta.title")
        if new:
            spec.meta.title = new


async def translate_spec(
    spec: PresentationSpec,
    settings: Settings,
    *,
    target_language: str,
    model: str | None = None,
) -> PresentationSpec:
    """Return the spec with every text translated into ``target_language``."""
    texts = _collect_texts(spec)
    if not texts:
        return spec

    # Budget guard: drop extra strings beyond the char budget (rare).
    payload: dict[str, str] = {}
    used = 0
    for key, value in texts.items():
        if used + len(value) > _MAX_TEXT_CHARS:
            break
        payload[key] = value
        used += len(value)

    resolved = await resolve_model(settings, model)
    import json as _json

    data = await complete_json(
        settings,
        model=resolved,
        system=_SYSTEM,
        user=(
            f"Target language: {target_language}.\n"
            f"Translate every value of this JSON object into {target_language}:\n"
            + _json.dumps(payload, ensure_ascii=False)
        ),
        max_tokens=16000,
    )
    translations = data if isinstance(data, dict) else {}
    if not translations:
        raise ProviderError("The translation response was empty")
    _apply_translations(spec, {str(k): str(v) for k, v in translations.items()})
    if spec.meta:
        spec.meta.language = target_language
    return spec
