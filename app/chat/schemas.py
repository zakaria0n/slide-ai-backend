"""Pydantic schemas for the chat API."""
from __future__ import annotations

import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    tool_calls: list | None = None
    created_at: datetime


class ChatListResponse(BaseModel):
    messages: list[ChatMessageResponse]
    total: int
    # Caller's effective role on this presentation (owner/admin/editor/viewer)
    # or None when the caller has no access at all. Drives whether the AI
    # panel shows edit affordances.
    access_role: str | None = None


class SendChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    current_slide_index: int = Field(default=0, ge=0)
    # Model the caller picked in the AI panel. None → backend default.
    model: str | None = Field(default=None, max_length=80)
    # Optional PNG/JPEG capture of the slide the user is looking at. Only
    # attached to the LLM request when the model actually reads images
    # (probed per model — see app.core.vision); it is never persisted.
    screenshot: str | None = Field(default=None, max_length=5_000_000)
    # Optional render diagnostics measured by the frontend (bounding boxes of
    # the slide the user views): overflow, overlaps, truncation. Fed verbatim
    # to the model so it can "see" geometry problems without vision.
    diagnostics: list[dict] | None = Field(default=None, max_length=50)

    @field_validator("diagnostics")
    @classmethod
    def _validate_diagnostics(cls, value):
        if value is None:
            return None
        cleaned = []
        for item in value[:50]:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("element_index", -1))
            except (TypeError, ValueError):
                continue
            problem = str(item.get("problem", "")).strip()[:60]
            if idx < -1 or not problem:  # -1 = slide-level issue (no single element)
                continue
            cleaned.append({
                "element_index": idx,
                "problem": problem,
                "detail": str(item.get("detail", "")).strip()[:300],
            })
        return cleaned or None

    @field_validator("screenshot")
    @classmethod
    def _validate_screenshot(cls, value):
        if value is None:
            return None
        value = "".join(value.split())  # tolerate newlines from chunked reads
        if not _SCREENSHOT_RE.match(value):
            raise ValueError(
                "screenshot must be a base64 data URL (data:image/png;base64,...)"
            )
        return value


# data:image/png;base64,... (also jpeg/jpg/webp) — ~5MB cap ≈ a 1280px slide
# capture encoded, with headroom.
_SCREENSHOT_RE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=]+$"
)
