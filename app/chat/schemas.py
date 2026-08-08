"""Pydantic schemas for the chat API."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


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
