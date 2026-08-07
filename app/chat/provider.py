"""LLM provider for the conversational AI chat.

Uses OpenAI-compatible function calling with streaming.
The provider streams token deltas and accumulates tool call fragments.
"""
from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import httpx

from app.chat.tools import TOOL_DEFINITIONS
from app.core.config import Settings

logger = logging.getLogger("slideai.chat.provider")
DISPLAYED_PROVIDER = "Slide AI"


@dataclass
class ToolCallInfo:
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunk:
    type: str  # "token" | "tool_calls" | "done" | "error"
    delta: str = ""
    tool_calls: list[ToolCallInfo] = field(default_factory=list)
    reasoning_content: str = ""


class ChatProvider(ABC):
    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[StreamChunk, None]:
        ...


class OnlineChatProvider(ChatProvider):
    """Real LLM-based chat with tool calling and streaming."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_provider_base_url.rstrip("/")
        self._api_key = settings.ai_provider_api_key
        self._model = settings.ai_provider_default_model
        self._timeout = settings.ai_request_timeout_seconds

    async def stream_chat(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[StreamChunk, None]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "tools": TOOL_DEFINITIONS,
                "tool_choice": "auto",
                "stream": True,
                "temperature": 0.6,
            }

            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield StreamChunk(
                        type="error",
                        delta=f"AI provider error: {resp.status_code} {body.decode()[:200]}",
                    )
                    return

                content_buf = ""
                tool_calls_buf: dict[int, dict] = {}  # index -> {id, name, arguments}
                reasoning_buf: list[str] = []

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning("provider: non-JSON SSE line: %.200s", data)
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    finish = choices[0].get("finish_reason")
                    if finish:
                        logger.info("provider: finish_reason=%r tool_calls_buf=%s", finish, list(tool_calls_buf))
                    else:
                        logger.debug("provider: delta keys=%s", list(delta.keys()))

                    # Content delta
                    if delta.get("content"):
                        content_buf += delta["content"]
                        yield StreamChunk(type="token", delta=delta["content"])
                    # Deepseek-style reasoning streamed separately from content.
                    # Must be preserved so we can echo it back on the assistant
                    # tool-call message (the API rejects tool_results without it).
                    rc = delta.get("reasoning_content")
                    if rc:
                        reasoning_buf.append(rc)

                    # Tool call deltas (OpenAI streams these in fragments)
                    try:
                        if delta.get("tool_calls"):
                            for tc_delta in delta["tool_calls"]:
                                idx = tc_delta.get("index", 0)
                                if idx not in tool_calls_buf:
                                    tool_calls_buf[idx] = {"id": "", "name": "", "arguments": ""}

                                entry = tool_calls_buf[idx]
                                # BEWARE: OpenAI-compatible providers emit fragments where
                                # id/name/arguments can be null in any given chunk (e.g. the
                                # name arrives in chunk 1, arguments in chunk 2..n, and extra
                                # chunks send {"name": null}). Concatenating None would throw,
                                # so only append when the value is a non-empty string.
                                if tc_delta.get("id"):
                                    entry["id"] += tc_delta["id"]
                                func = tc_delta.get("function") or {}
                                name_val = func.get("name")
                                args_val = func.get("arguments")
                                if name_val:
                                    entry["name"] += name_val
                                if args_val:
                                    entry["arguments"] += args_val
                    except Exception as tc_err:
                        # Never let a malformed tool-call fragment kill the stream.
                        logger.warning("provider: tool-call fragment error: %r", tc_err)

                # Emit collected tool calls
                if tool_calls_buf:
                    calls = []
                    for idx in sorted(tool_calls_buf):
                        entry = tool_calls_buf[idx]
                        try:
                            args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                        except json.JSONDecodeError:
                            logger.warning("provider: bad tool args JSON for %s: %.300s", entry["name"], entry["arguments"])
                            args = {}
                        # Some providers omit the tool_call id. Synthesize a
                        # stable one so multi-turn loops can match tool calls
                        # to their results.
                        call_id = entry["id"] or f"call_{idx}"
                        calls.append(ToolCallInfo(id=call_id, name=entry["name"], arguments=args))
                    logger.info("provider: emitting %d tool call(s): %s", len(calls), [c.name for c in calls])
                    reasoning = "".join(reasoning_buf)
                    yield StreamChunk(type="tool_calls", tool_calls=calls, reasoning_content=reasoning)

                yield StreamChunk(type="done")


class OfflineChatProvider(ChatProvider):
    """Deterministic fallback for dev/tests without API key."""

    async def _emit_text(self, text: str) -> AsyncGenerator[StreamChunk, None]:
        """Yield the canned response in ~30-char slices.

        Preserves original whitespace (including newlines) instead of
        splitting on spaces, and sleeps briefly to simulate streaming.
        """
        for i in range(0, len(text), 30):
            yield StreamChunk(type="token", delta=text[i : i + 30])
            await asyncio.sleep(0.01)

    async def stream_chat(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[StreamChunk, None]:
        # Get the last user message
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "").lower()
                break

        if not user_msg:
            yield StreamChunk(type="done", delta="How can I help?")
            return

        # Greetings
        if any(g in user_msg for g in ("hi", "hello", "hey", "bonjour", "salut")):
            async for chunk in self._emit_text("Hello! How can I improve your presentation today?"):
                yield chunk
            yield StreamChunk(type="done")
            return

        # Theme change — require an explicit action verb + theme name so a
        # question like "explain the dark theme" doesn't trigger a rewrite.
        from app.chat.tools import THEMES
        action_verbs = ("make it", "change to", "change the", "switch to", "apply", "use the")
        if any(v in user_msg for v in action_verbs):
            for theme in THEMES:
                if theme in user_msg:
                    yield StreamChunk(type="token", delta=f"Changing theme to ")
                    yield StreamChunk(type="token", delta=theme)
                    yield StreamChunk(type="token", delta="...")
                    yield StreamChunk(
                        type="tool_calls",
                        tool_calls=[ToolCallInfo(name="change_theme", arguments={"theme_name": theme})],
                    )
                    yield StreamChunk(type="done")
                    return

        # Add slide
        if "add" in user_msg and "slide" in user_msg:
            yield StreamChunk(type="token", delta="Adding a new slide...")
            yield StreamChunk(
                type="tool_calls",
                tool_calls=[ToolCallInfo(name="add_slide", arguments={"layout": "title", "title": "New Slide"})],
            )
            yield StreamChunk(type="done")
            return

        # Default conversational response
        text = "I can help you edit your presentation. Try saying 'make it modern', 'add a slide', or 'improve slide 3'."
        async for chunk in self._emit_text(text):
            yield chunk
        yield StreamChunk(type="done")


def build_chat_provider(settings: Settings) -> ChatProvider:
    if not settings.ai_provider_api_key:
        return OfflineChatProvider()
    return OnlineChatProvider(settings)
