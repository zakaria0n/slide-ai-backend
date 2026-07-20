"""Template selector — picks the best TemplateFamily by keyword scoring."""
from __future__ import annotations

from app.templates.library import TEMPLATES, TemplateFamily


def select_template(prompt: str, tone: str = "") -> TemplateFamily:
    """Return the best-matching template family for the given prompt.

    Uses keyword scoring against each family's classify_keywords. Falls back
    to "generic" if no keywords match.
    """
    lower = prompt.lower()
    tone_lower = tone.lower()
    combined = f"{lower} {tone_lower}"

    best: TemplateFamily | None = None
    best_score = 0

    for family in TEMPLATES:
        if not family.classify_keywords:
            continue  # generic is fallback, skip scoring
        score = sum(1 for kw in family.classify_keywords if kw in combined)
        if score > best_score:
            best_score = score
            best = family

    return best or TEMPLATES[-1]  # generic is last
