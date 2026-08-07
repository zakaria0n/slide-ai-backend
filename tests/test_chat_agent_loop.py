"""Tests for the multi-turn agent loop in ChatService.

The real upstream provider streams a single assistant turn, but the agent
loop feeds tool results back to the LLM and continues until the LLM stops
emitting tool calls or the iteration cap is reached. These tests drive the
loop with a scripted fake provider.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.chat.provider import StreamChunk, ToolCallInfo
from app.chat.service import ChatService, _MAX_AGENT_ITERATIONS
from app.generation.spec import PresentationSpec
from tests.conftest import FakeAsyncClient


def _make_spec() -> PresentationSpec:
    return PresentationSpec.model_validate({
        "meta": {"title": "Test Deck", "theme": "modern"},
        "slides": [
            {"layout": "title", "elements": [{"type": "title", "text": "Intro", "level": 1}]},
        ],
    })


async def _insert_presentation(
    client: FakeAsyncClient, pid, oid, spec: PresentationSpec,
) -> None:
    await client.table("presentations").insert({
        "id": str(pid),
        "owner_id": str(oid),
        "spec": spec.model_dump(),
        "slide_count": len(spec.slides),
    }).execute()


class ScriptedProvider:
    """Fake provider returning one scripted chunk list per stream_chat call."""

    def __init__(self, turns: list[list[StreamChunk]]) -> None:
        self._turns = list(turns)
        self.call_count = 0

    async def stream_chat(self, messages: list[dict]):
        self.call_count += 1
        if self.call_count <= len(self._turns):
            for chunk in self._turns[self.call_count - 1]:
                yield chunk
        else:
            yield StreamChunk(type="done")


async def _collect(
    service: ChatService, pid, oid, user_text: str,
) -> list[str]:
    events: list[str] = []
    async for raw in service.send_message_streaming(pid, oid, user_text):
        events.append(raw)
    return events


def _done_payload(events: list[str]) -> dict:
    done_event = next(e for e in events if e.startswith("event: done"))
    return json.loads(done_event.split("data: ", 1)[1].strip())


async def test_agent_loop_executes_multiple_turns(fake_supabase) -> None:
    pid = uuid4()
    oid = uuid4()
    await _insert_presentation(fake_supabase, pid, oid, _make_spec())

    provider = ScriptedProvider([
        [
            StreamChunk(type="token", delta="Let me add a slide. "),
            StreamChunk(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id="call_1",
                        name="add_slide",
                        arguments={"layout": "title", "title": "New Slide"},
                    ),
                ],
            ),
            StreamChunk(type="done"),
        ],
        [
            StreamChunk(type="token", delta="Done!"),
            StreamChunk(type="done"),
        ],
    ])
    service = ChatService(fake_supabase, provider)

    events = await _collect(service, pid, oid, "Add a slide")

    # Two LLM calls: turn 1 emits tool calls, turn 2 emits text only.
    assert provider.call_count == 2

    tool_call_events = [e for e in events if e.startswith("event: tool_call")]
    tool_result_events = [e for e in events if e.startswith("event: tool_result")]
    assert len(tool_call_events) == 1
    assert len(tool_result_events) == 1
    assert '"add_slide"' in tool_call_events[0]

    done = _done_payload(events)
    assert "Let me add a slide." in done["content"]
    assert "Done!" in done["content"]

    rows = (await fake_supabase.table("presentations").select("*").execute()).data
    assert rows[0]["slide_count"] == 2

    # The assistant message persists the executed tool calls.
    messages = (await fake_supabase.table("chat_messages").select("*").execute()).data
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["tool_calls"] == [
        {"name": "add_slide", "arguments": {"layout": "title", "title": "New Slide"}},
    ]


async def test_agent_loop_stops_on_iteration_cap(fake_supabase) -> None:
    pid = uuid4()
    oid = uuid4()
    await _insert_presentation(fake_supabase, pid, oid, _make_spec())

    class LoopProvider:
        """Always emits a fresh tool call (varying args) so the duplicate
        guard never triggers and the loop runs until the cap."""

        def __init__(self) -> None:
            self.call_count = 0

        async def stream_chat(self, messages: list[dict]):
            self.call_count += 1
            yield StreamChunk(type="token", delta=f"Adding slide {self.call_count}. ")
            yield StreamChunk(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id=f"call_{self.call_count}",
                        name="add_slide",
                        arguments={
                            "layout": "title",
                            "title": f"New Slide {self.call_count}",
                        },
                    ),
                ],
            )
            yield StreamChunk(type="done")

    provider = LoopProvider()
    service = ChatService(fake_supabase, provider)

    events = await _collect(service, pid, oid, "Keep adding slides")

    # Ran exactly up to the cap, then exited cleanly with a done event.
    assert provider.call_count == _MAX_AGENT_ITERATIONS
    done = _done_payload(events)
    assert done["message_id"]

    rows = (await fake_supabase.table("presentations").select("*").execute()).data
    assert rows[0]["slide_count"] == 1 + _MAX_AGENT_ITERATIONS


async def test_cap_surfaces_visible_continue_message(fake_supabase) -> None:
    """Fix 1: when the iteration cap is hit mid-tool, the stream must emit a
    visible 'continue' note instead of going silent — never a hang."""
    pid = uuid4()
    oid = uuid4()
    await _insert_presentation(fake_supabase, pid, oid, _make_spec())

    class InfiniteProvider:
        def __init__(self) -> None:
            self.call_count = 0

        async def stream_chat(self, messages: list[dict]):
            self.call_count += 1
            yield StreamChunk(
                type="tool_calls",
                tool_calls=[
                    ToolCallInfo(
                        id=f"call_{self.call_count}",
                        name="add_slide",
                        arguments={"layout": "title", "title": f"S {self.call_count}"},
                    ),
                ],
            )
            yield StreamChunk(type="done")

    service = ChatService(fake_supabase, InfiniteProvider())
    events = await _collect(service, pid, oid, "Add many slides")

    joined = "\n".join(events)
    assert "tool-call limit" in joined
    assert "continue" in joined
    assert any(e.startswith("event: tool_call") for e in events)
    assert any(e.startswith("event: done") for e in events)


async def test_tool_error_fed_back_to_model(fake_supabase) -> None:
    """Fix 1: a failing tool must be returned to the model as a tool_result
    (success=False) so it can adapt — not crash the loop or go silent."""
    pid = uuid4()
    oid = uuid4()
    await _insert_presentation(fake_supabase, pid, oid, _make_spec())

    class FailingProvider:
        """Turn 1 requests an out-of-range update_slide (fails); turn 2 sees
        the failure and apologizes/ends."""
        def __init__(self) -> None:
            self.call_count = 0
            self.seen_tool_result = False

        async def stream_chat(self, messages: list[dict]):
            self.call_count += 1
            if self.call_count == 1:
                # The failure is produced by the real dispatch_tool (out of range).
                yield StreamChunk(
                    type="tool_calls",
                    tool_calls=[
                        ToolCallInfo(id="call_x", name="update_slide", arguments={"slide_index": 99}),
                    ],
                )
                yield StreamChunk(type="done")
            else:
                tool_msgs = [m for m in messages if m.get("role") == "tool"]
                assert tool_msgs, "tool result must be fed back to the model"
                payload = json.loads(tool_msgs[0]["content"])
                assert payload["success"] is False
                self.seen_tool_result = True
                yield StreamChunk(type="token", delta="Sorry, slide 99 doesn't exist.")
                yield StreamChunk(type="done")

    provider = FailingProvider()
    service = ChatService(fake_supabase, provider)
    events = await _collect(service, pid, oid, "update slide 99")

    assert provider.call_count == 2
    assert provider.seen_tool_result is True
    done = _done_payload(events)
    assert "doesn't exist" in done["content"]
