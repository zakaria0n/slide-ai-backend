"""Chat service — orchestrates conversation persistence and AI streaming.

Multi-turn agent loop: tool results are fed back to the LLM and the
conversation continues until the LLM stops emitting tool calls or the
iteration cap is reached.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from supabase import AsyncClient

import app.db as db
from app.chat.context import build_llm_messages, build_system_message
from app.chat.provider import ChatProvider, StreamChunk, ToolCallInfo
from app.chat.tools import ToolResult, dispatch_tool
from app.generation.spec import PresentationSpec
from app.presentations.versioning import snapshot_if_changed

logger = logging.getLogger("slideai.chat.service")

# Maximum agent loop iterations to prevent runaway execution.
_MAX_AGENT_ITERATIONS = 10


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatService:
    def __init__(self, client: AsyncClient, provider: ChatProvider) -> None:
        self._client = client
        self._provider = provider

    async def list_messages(
        self, presentation_id: Any, owner_id: Any,
    ) -> list[dict]:
        return await db.list_chat_messages(
            self._client, presentation_id, owner_id=owner_id,
        )

    async def clear_messages(
        self, presentation_id: Any, owner_id: Any,
    ) -> None:
        await db.delete_chat_messages(self._client, presentation_id, owner_id)

    async def send_message_streaming(
        self,
        presentation_id: Any,
        owner_id: Any,
        user_text: str,
        current_slide_index: int = 0,
        max_history: int = 20,
    ) -> AsyncGenerator[str, None]:
        """Yields SSE event strings for the streaming response.

        Agent loop:
        1. Send message to LLM
        2. If LLM returns tool calls → execute → feed results back → go to 1
        3. If LLM returns text only → done
        """
        pid = str(presentation_id)
        oid = str(owner_id)

        # 1. Load presentation
        row = await db.get_presentation(self._client, presentation_id)
        if row is None:
            yield _sse("error", {"message": "Presentation not found"})
            return
        role = await db.get_presentation_access_role(self._client, presentation_id, owner_id)
        if role is None:
            yield _sse("error", {"message": "Presentation not found"})
            return
        if role not in ("owner", "admin", "editor"):
            yield _sse("error", {"message": "You have read-only access to this presentation"})
            return

        spec_raw = row.get("spec")
        if not spec_raw:
            yield _sse("error", {"message": "Presentation has no spec"})
            return
        spec = PresentationSpec.model_validate(spec_raw)

        # 2. Persist user message
        await db.create_chat_message(
            self._client,
            presentation_id=pid,
            owner_id=oid,
            role="user",
            content=user_text,
        )

        # 3. Load conversation history
        db_messages = await db.list_chat_messages(
            self._client, pid, owner_id=oid, limit=max_history,
        )

        # 4. Build initial LLM context
        llm_messages = build_llm_messages(db_messages, spec, current_slide_index, max_history)

        # 5. Agent loop
        spec_changed = False
        all_tool_calls: list[ToolCallInfo] = []
        all_tool_results: list[dict] = []  # [{name, success, summary}]
        full_text = ""
        iteration = 0
        stopped_by_cap = False

        # Snapshot the pre-edit spec once so we can persist a version row
        # if any tool mutates it during this turn.
        pre_edit_spec = spec
        initial_spec_hash = json.dumps(spec.model_dump(), sort_keys=True)
        prev_turn_sig: list[tuple[str, str]] | None = None

        try:
            while True:
                if iteration >= _MAX_AGENT_ITERATIONS:
                    stopped_by_cap = True
                    break
                iteration += 1

                # 5a. Stream LLM response
                turn_text = ""
                turn_reasoning = ""
                turn_tool_calls: list[ToolCallInfo] = []

                try:
                    async for chunk in self._provider.stream_chat(llm_messages):
                        if chunk.type == "token":
                            turn_text += chunk.delta
                            full_text += chunk.delta
                            yield _sse("token", {"delta": chunk.delta})
                        elif chunk.type == "tool_calls":
                            turn_tool_calls = chunk.tool_calls
                            turn_reasoning = chunk.reasoning_content
                        elif chunk.type == "error":
                            yield _sse("error", {"message": chunk.delta})
                            if not turn_tool_calls:
                                break
                        elif chunk.type == "done":
                            if chunk.delta and not turn_text:
                                turn_text = chunk.delta
                                full_text += chunk.delta
                except Exception as provider_err:
                    yield _sse("token", {"delta": f"\n\n(A provider error occurred: {provider_err}. Continuing with what we have so far.)"})
                    break

                if not turn_tool_calls:
                    break
                logger.info("turn %d: %d tool call(s) -> %s", iteration, len(turn_tool_calls), [t.name for t in turn_tool_calls])

                # 5c. Execute all tools in this turn
                turn_results: list[dict] = []
                for tc in turn_tool_calls:
                    yield _sse("tool_call", {"name": tc.name, "arguments": tc.arguments})

                    result: ToolResult = await dispatch_tool(tc.name, tc.arguments, spec)
                    spec = result.spec
                    all_tool_calls.append(tc)
                    logger.info("tool %r success=%s summary=%.200s", tc.name, result.success, result.summary)

                    tool_result = {
                        "name": tc.name,
                        "success": result.success,
                        "summary": result.summary,
                    }
                    turn_results.append(tool_result)
                    all_tool_results.append(tool_result)

                    yield _sse("tool_result", tool_result)

                # 5d. Persist spec if changed
                new_spec_hash = json.dumps(spec.model_dump(), sort_keys=True)
                if new_spec_hash != initial_spec_hash:
                    spec_changed = True
                    # Snapshot the pre-edit spec so the change shows up in
                    # version history (the same way manual edits do).
                    from app.presentations.versioning import snapshot_if_changed

                    await snapshot_if_changed(
                        self._client,
                        pid,
                        oid,
                        pre_edit_spec,
                        note=f"before chat edit: {user_text[:80]}",
                    )
                    await db.update_presentation(
                        self._client, pid,
                        spec=spec.model_dump(),
                        slide_count=len(spec.slides),
                    )

                # 5e. Feed tool results back to the LLM and continue the loop.
                # Append the assistant message (with its tool_calls) followed
                # by one tool-role result per call, in the same order.
                # DeepSeek thinking-mode requires the assistant tool-call turn's
                # original reasoning_content to be echoed verbatim on the follow-up
                # request; a null/omitted value is the classic cause of a 400 here.
                # Include the key ONLY when a non-empty reasoning string was
                # captured for this turn — never emit it as null.
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": turn_text or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in turn_tool_calls
                    ],
                }
                if turn_reasoning:
                    assistant_msg["reasoning_content"] = turn_reasoning
                llm_messages.append(assistant_msg)
                for tc, result in zip(turn_tool_calls, turn_results):
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(
                            {"success": result["success"], "summary": result["summary"]},
                            ensure_ascii=False,
                        ),
                    })

                # Duplicate-turn guard: if the exact same tool calls (name +
                # arguments) were requested two turns in a row, the provider
                # is looping — stop instead of repeating the edits forever.
                cur_sig = [
                    (tc.name, json.dumps(tc.arguments, sort_keys=True))
                    for tc in turn_tool_calls
                ]
                if prev_turn_sig is not None and cur_sig == prev_turn_sig:
                    note = (
                        "\n\n(The same change was requested again — "
                        "stopping to avoid repeating the edit.)"
                    )
                    full_text += note
                    yield _sse("token", {"delta": note})
                    break
                prev_turn_sig = cur_sig

        except Exception as exc:
            yield _sse("error", {"message": f"AI provider error: {exc}"})
            return

        # If the agent hit the iteration cap without ending cleanly, surface a
        # visible note so the frontend is never left hanging silently. If the
        # last thing the model did was request a tool that never finished, tell
        # the user how to resume instead of looping forever.
        if stopped_by_cap:
            if all_tool_calls:
                note = (
                    "\n\n(I've reached the tool-call limit for this turn. "
                    "Everything requested has been applied. "
                    "Ask me to 'continue' and I'll carry on from here.)"
                )
            else:
                note = (
                    "\n\n(I've reached the step limit for this turn. "
                    "The requested work may be incomplete — ask me to "
                    "'continue' to finish it.)"
                )
            full_text += note
            yield _sse("token", {"delta": note})

        # 6. Persist assistant message
        tc_data = (
            [{"name": tc.name, "arguments": tc.arguments} for tc in all_tool_calls]
            or None
        )
        assistant_msg = await db.create_chat_message(
            self._client,
            presentation_id=pid,
            owner_id=oid,
            role="assistant",
            content=full_text,
            tool_calls=tc_data,
        )

        # 7. Emit final events
        if spec_changed:
            yield _sse("spec_update", {"spec": spec.model_dump(mode="json")})

        yield _sse("done", {
            "message_id": assistant_msg["id"],
            "content": full_text,
        })
