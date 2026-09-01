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
whose keys are OPAQUE IDS (like "k0", "k17") and whose values are source
strings. Return ONLY valid JSON with the SAME ids mapping to the strings
translated into the target language.
Rules:
- Copy every id EXACTLY as given — never rename, merge, drop or reorder ids.
- Translate meaning, not word-for-word; keep the presentation tone.
- Keep numbers, %, currency symbols and proper nouns intact.
- Keep it SHORT — these strings go on slides. Never make a translation
  much longer than the source.
- Every id must appear exactly once in your answer.
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
            elif t == "chart":
                # Chart categories and series names are words too; the numeric
                # data itself is never touched.
                for k, lbl in enumerate(el.labels or []):
                    put(f"{i}.{j}.labels[{k}]", lbl)
                for k, ds in enumerate(el.datasets or []):
                    put(f"{i}.{j}.datasets[{k}].label", ds.label)
        put(f"{i}.notes", slide.notes)

    # Deck title last so it is part of the same single call.
    if spec.meta and spec.meta.title:
        put("meta.title", spec.meta.title)
    return texts


# --- custom-coded slides (layout="custom") ------------------------------------
#
# The AI-authored HTML is real markup: translating it naively would corrupt
# tags and JS. Strategy: mask <script>/<style> blocks, then replace every
# TEXT RUN (between tags) and translatable ATTRIBUTE (alt/title/placeholder/
# aria-label) with a \x00-keyed sentinel. Only the sentinels' source strings
# enter the translation map; afterwards each sentinel is swapped back to its
# translation (or the original when the model skipped it). JS string literals
# are deliberately left alone — rewriting code strings risks breaking logic.

import re as _re

_TEXT_RUN_RE = _re.compile(r">([^<>]+)<")
_ATTR_RE = _re.compile(r'\b(alt|title|placeholder|aria-label|content)\s*=\s*"([^"]*)"')
_MASK_RE = _re.compile(r"(<script\b.*?</script\s*>|<style\b.*?</style\s*>|<!--.*?-->)", _re.IGNORECASE | _re.DOTALL)
_RUN_RE = _re.compile(r"\x00R(\d+)\x00")
_MASK_KEY = "\x00M{}\x00"


def _has_words(s: str) -> bool:
    return any(ch.isalpha() for ch in s)


def extract_html_texts(html: str, prefix: str) -> tuple[str, dict[str, str], dict[str, str], dict[str, str]]:
    """Return (sentinel_html, texts, originals, masks).

    ``texts`` maps stable ids ("0.html.run[3]") to the source strings that must
    be translated; ``originals`` maps the same ids back to their source so a
    missing translation can be restored verbatim.
    """
    masks: dict[str, str] = {}

    def mask(m: "_re.Match") -> str:
        key = _MASK_KEY.format(len(masks))
        masks[key] = m.group(1)
        return key

    html = _MASK_RE.sub(mask, html)

    texts: dict[str, str] = {}
    originals: dict[str, str] = {}

    def sentinel(key: str) -> str:
        return f"\x00{key}\x00"

    def sub_run(m: "_re.Match") -> str:
        inner = m.group(1)
        s = inner.strip()
        if not s or not _has_words(s):
            return m.group(0)
        key = f"{prefix}.run[{len(texts)}]"
        texts[key] = s
        originals[key] = inner
        return ">" + sentinel(key) + "<"

    def sub_attr(m: "_re.Match") -> str:
        val = m.group(2)
        s = val.strip()
        if not s or not _has_words(s):
            return m.group(0)
        key = f"{prefix}.attr[{len(texts)}]"
        texts[key] = s
        originals[key] = val
        return f'{m.group(1)}="{sentinel(key)}"'

    html = _TEXT_RUN_RE.sub(sub_run, html)
    html = _ATTR_RE.sub(sub_attr, html)
    return html, texts, originals, masks


def rebuild_html(
    sentinel_html: str,
    originals: dict[str, str],
    masks: dict[str, str],
    translations: dict[str, str],
) -> str:
    """Swap sentinels back to translations (originals when untranslated)."""
    html = sentinel_html
    for key, original in originals.items():
        replacement = str(translations.get(key) or "").strip()
        html = html.replace(f"\x00{key}\x00", replacement or original)
    for mask_key, masked in masks.items():
        html = html.replace(mask_key, masked)
    return html


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
            elif t == "chart":
                for k in range(len(el.labels or [])):
                    new = translations.get(f"{i}.{j}.labels[{k}]")
                    if new:
                        el.labels[k] = new
                for k, ds in enumerate(el.datasets or []):
                    new = translations.get(f"{i}.{j}.datasets[{k}].label")
                    if new:
                        ds.label = new
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
    """Return the spec with every text translated into ``target_language``.

    Covers structured elements, speaker notes, chart labels/series names AND
    the visible text inside custom-coded slides (layout="custom") — their
    HTML markup is preserved via sentinel extraction, scripts/styles untouched.
    """
    texts = _collect_texts(spec)

    # Custom-coded slides: extract their visible text into the same payload.
    html_edits: list[tuple[object, str, dict[str, str], dict[str, str]]] = []
    for i, slide in enumerate(spec.slides):
        if slide.layout == "custom" and slide.code and slide.code.html:
            sentinel_html, html_texts, originals, masks = extract_html_texts(
                slide.code.html, f"{i}.html"
            )
            if html_texts:
                texts.update(html_texts)
                slide.code.html = sentinel_html
                html_edits.append((slide, originals, masks, sentinel_html))

    if not texts:
        # Un-mask any custom HTML before bailing out.
        for slide, originals, masks, sentinel_html in html_edits:
            slide.code.html = rebuild_html(sentinel_html, originals, masks, {})
        return spec

    # Budget guard: drop extra strings beyond the char budget (rare).
    payload: dict[str, str] = {}
    used = 0
    for key, value in texts.items():
        if used + len(value) > _MAX_TEXT_CHARS:
            break
        payload[key] = value
        used += len(value)

    # Translate in CHUNKS with OPAQUE FLAT IDS ("k0", "k1", …). Dotted /
    # bracketed keys ("meta.title", "3.html.run[2]") made reasoning models
    # emit broken JSON (they try to nest or quote the dots). The model only
    # ever sees k-ids; the real spec paths stay in a local key_map.
    import json as _json

    flat_payload: dict[str, str] = {}
    key_map: dict[str, str] = {}
    for real_key, value in payload.items():
        fid = f"k{len(key_map)}"
        flat_payload[fid] = value
        key_map[fid] = real_key

    chunks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    current_chars = 0
    for fid, value in flat_payload.items():
        if current and (len(current) >= 80 or current_chars + len(value) > 6000):
            chunks.append(current)
            current = {}
            current_chars = 0
        current[fid] = value
        current_chars += len(value)
    if current:
        chunks.append(current)

    resolved = await resolve_model(settings, model)
    merged: dict[str, str] = {}
    failed_chunks = 0
    for chunk in chunks:
        try:
            data = await complete_json(
                settings,
                model=resolved,
                system=_SYSTEM,
                user=(
                    f"Target language: {target_language}.\n"
                    f"Translate every value of this JSON object into {target_language}:\n"
                    + _json.dumps(chunk, ensure_ascii=False)
                ),
                max_tokens=16000,
            )
        except ProviderError:
            # One flaky chunk must not sink the whole deck: keep the original
            # strings for that batch and translate the rest.
            failed_chunks += 1
            continue
        if isinstance(data, dict) and data:
            merged.update({str(k): str(v) for k, v in data.items()})

    translations = {key_map[fid]: v for fid, v in merged.items() if fid in key_map}
    if not translations:
        # Un-mask custom HTML before failing — never persist sentinels.
        for slide, originals, masks, sentinel_html in html_edits:
            slide.code.html = rebuild_html(sentinel_html, originals, masks, {})
        raise ProviderError("The translation response was empty")
    if failed_chunks:
        import logging

        logging.getLogger("generation").warning(
            "translate: %d/%d chunk(s) failed — those strings kept their original language",
            failed_chunks, len(chunks),
        )

    clean = {str(k): str(v) for k, v in translations.items()}
    _apply_translations(spec, clean)
    for slide, originals, masks, sentinel_html in html_edits:
        slide.code.html = rebuild_html(sentinel_html, originals, masks, clean)
    if spec.meta:
        spec.meta.language = target_language
    return spec
