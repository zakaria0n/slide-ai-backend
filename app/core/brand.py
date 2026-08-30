"""Brand kit helpers shared by generation, chat and AI edit."""
from __future__ import annotations

from typing import Any


def format_brand_context(row: dict[str, Any] | None) -> str | None:
    """Human-readable brand identity line for LLM prompts (None if empty)."""
    if not row:
        return None
    parts: list[str] = []
    if row.get("color_primary"):
        parts.append(f"primary color {row['color_primary']}")
    if row.get("color_secondary"):
        parts.append(f"secondary color {row['color_secondary']}")
    if row.get("font_heading"):
        parts.append(f"heading font {row['font_heading']}")
    if row.get("font_body"):
        parts.append(f"body font {row['font_body']}")
    if not parts:
        return None
    return (
        "BRAND IDENTITY — the user's brand MUST be respected: use "
        + "; ".join(parts)
        + ". In custom slide code use these exact colors/fonts (theme CSS vars may be overridden inline)."
    )


async def get_brand_context(client, user_id) -> str | None:
    """Fetch the user's brand kit and format it for prompts (None if unset)."""
    try:
        import app.db as db

        return format_brand_context(await db.get_brand_kit(client, user_id))
    except Exception:
        return None
