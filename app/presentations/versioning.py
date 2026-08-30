"""Versioning helpers for presentations."""
from __future__ import annotations

import json

from supabase import AsyncClient

import app.db as db
from app.generation.spec import PresentationSpec


def _spec_hash(spec: PresentationSpec) -> str:
    return json.dumps(spec.model_dump(), sort_keys=True)


# Manual autosaves fire every few seconds — snapshotting each one floods the
# version history. Keep AI-edit snapshots (rare, restorable states worth
# keeping) and throttle only the routine manual ones.
_MANUAL_SNAPSHOT_MIN_INTERVAL_SECONDS = 300


async def snapshot_if_changed(
    client: AsyncClient,
    presentation_id: object,
    owner_id: object,
    spec: PresentationSpec,
    note: str = "auto-save",
    chat_messages: list[dict] | None = None,
) -> None:
    """Create a version snapshot only if the spec differs from the latest.

    Routine manual-edit snapshots are additionally throttled to one per
    _MANUAL_SNAPSHOT_MIN_INTERVAL_SECONDS so a long working session doesn't
    flood the history.
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    latest_hash = await db.get_latest_spec_hash(client, presentation_id)  # type: ignore[arg-type]
    new_hash = _spec_hash(spec)

    if latest_hash == new_hash:
        return

    if note.startswith("manual edit"):
        try:
            latest_rows = await db.list_versions(client, presentation_id, limit=1)  # type: ignore[arg-type]
            if latest_rows:
                latest = latest_rows[0]
                created = _dt.fromisoformat(str(latest["created_at"]).replace("Z", "+00:00"))
                if latest.get("version_note", "").startswith("manual edit"):
                    age = (_dt.now(_tz.utc) - created).total_seconds()
                    if age < _MANUAL_SNAPSHOT_MIN_INTERVAL_SECONDS:
                        return
        except (ValueError, TypeError, KeyError):
            pass

    fields = dict(
        presentation_id=str(presentation_id),
        owner_id=str(owner_id),
        spec=spec.model_dump(),
        version_note=note,
        slide_count=len(spec.slides),
    )
    # Include chat snapshot if available
    if chat_messages is not None:
        fields["chat_snapshot"] = chat_messages

    await db.create_version(client, **fields)


async def restore_conversation(
    client: AsyncClient,
    presentation_id: object,
    version_id: object,
    owner_id: object,
) -> None:
    """Restore chat messages from a version snapshot."""
    version = await db.get_version(client, version_id)
    if version is None:
        return

    snapshot = version.get("chat_snapshot")
    if not snapshot:
        return

    # Delete current messages
    await db.delete_chat_messages(
        client, presentation_id, owner_id=str(owner_id),
    )

    # Re-insert snapshot messages
    for msg in snapshot:
        await db.create_chat_message(
            client,
            presentation_id=str(presentation_id),
            owner_id=str(owner_id),
            role=msg.get("role", "user"),
            content=msg.get("content", ""),
            tool_calls=msg.get("tool_calls"),
        )
