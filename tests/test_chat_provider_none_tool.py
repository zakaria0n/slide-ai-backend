"""Regression test: provider must tolerate OpenAI-compatible tool-call fragments
where name/id/arguments arrive as null in some chunks (the real LLM does this),
and must always deliver a complete, parseable arguments dict.

Previously the accumulation loop did `entry += val` on None and threw
`TypeError: can only concatenate str (not "NoneType") to str`, producing an
empty-argument tool call that then failed with "missing required argument" and
created an infinite tool loop (the exact bug seen in production).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


def _settings():
    from app.core.config import Settings
    return Settings(
        _env_file=None,
        ai_provider_base_url="http://local.test",
        ai_provider_api_key="test-key",
        ai_provider_default_model="test-model",
        ai_request_timeout_seconds=30,
    )


class FakeClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._status = 200

    def stream(self, *_args, **_kwargs):
        return self

    @property
    def status_code(self) -> int:
        return self._status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b"oops"


def test_tool_call_with_null_fragments_is_complete():
    from app.chat.provider import OnlineChatProvider

    lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_0","type":"function","function":{"name":"get_slide_detail","arguments":""}}]},"finish_reason":null}]}',
        # Regression: this chunk sends name=null while supplying the arguments
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":null,"arguments":"{\\"slide_index\\": 2}"}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    client = FakeClient(lines)

    provider = OnlineChatProvider(_settings())

    async def _replaced(client_obj, *a, **k):
        return client_obj

    with patch("httpx.AsyncClient", lambda **kwargs: client):
        async def read():
            out = []
            async for chunk in provider.stream_chat([{"role": "user", "content": "x"}]):
                out.append(chunk)
            return out

        chunks = asyncio.run(read())

    tool_calls = [c for c in chunks if c.type == "tool_calls"]
    assert len(tool_calls) == 1
    calls = tool_calls[0].tool_calls
    assert len(calls) == 1
    assert calls[0].name == "get_slide_detail"
    assert calls[0].arguments == {"slide_index": 2}