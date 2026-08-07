"""Chat API routes — persistent conversational AI editor."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

import app.db as db
from app.api.deps import extract_token, owner_id, supabase
from app.chat.schemas import ChatListResponse, ChatMessageResponse, SendChatRequest
from app.chat.service import ChatService
from app.core.config import Settings
from app.core.exceptions import ForbiddenError, NotFoundError

router = APIRouter(prefix="/presentations", tags=["chat"])


async def _require_presentation(
    supabase_client, presentation_id: UUID, user_id: UUID, *, write: bool = False
) -> dict:
    row = await db.get_presentation(supabase_client, presentation_id)
    if row is None:
        raise NotFoundError("Presentation not found")
    role = await db.get_presentation_access_role(supabase_client, presentation_id, user_id)
    if role is None:
        raise NotFoundError("Presentation not found")
    if write and role not in ("owner", "admin", "editor"):
        raise ForbiddenError("You have read-only access to this presentation")
    return row


async def _chat_service(
    request: Request,
    supabase_client=Depends(supabase),
) -> ChatService:
    from app.chat.provider import build_chat_provider

    settings: Settings = request.app.state.settings
    provider = build_chat_provider(settings)
    return ChatService(supabase_client, provider)


@router.get("/{presentation_id}/chat", response_model=ChatListResponse)
async def list_chat(
    presentation_id: UUID,
    oid: UUID = Depends(owner_id),
    supabase_client=Depends(supabase),
) -> ChatListResponse:
    await _require_presentation(supabase_client, presentation_id, oid)

    messages = await db.list_chat_messages(
        supabase_client, presentation_id, owner_id=str(oid),
    )

    return ChatListResponse(
        messages=[
            ChatMessageResponse(
                id=str(m["id"]),
                role=m["role"],
                content=m.get("content", ""),
                tool_calls=m.get("tool_calls"),
                created_at=m["created_at"],
            )
            for m in messages
        ],
        total=len(messages),
    )


@router.post("/{presentation_id}/chat/stream")
async def chat_stream(
    presentation_id: UUID,
    req: SendChatRequest,
    oid: UUID = Depends(owner_id),
    service: ChatService = Depends(_chat_service),
) -> StreamingResponse:
    """SSE streaming endpoint for the AI chat."""
    from app.core.ratelimit import generation_limiter
    generation_limiter.check(str(oid))

    row = await _require_presentation(supabase_client, presentation_id, oid, write=True)

    return StreamingResponse(
        service.send_message_streaming(
            presentation_id, oid,
            user_text=req.message,
            current_slide_index=req.current_slide_index,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{presentation_id}/chat")
async def clear_chat(
    presentation_id: UUID,
    oid: UUID = Depends(owner_id),
    supabase_client=Depends(supabase),
) -> dict:
    await _require_presentation(supabase_client, presentation_id, oid, write=True)

    await db.delete_chat_messages(supabase_client, presentation_id, str(oid))
    return {"message": "Conversation cleared"}
