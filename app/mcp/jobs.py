"""Durable MCP generation jobs, stored in the `mcp_jobs` table.

Jobs survive server restarts; entries older than an hour are pruned on
creation so the table stays small.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from supabase import AsyncClient

import app.db as db

_MAX_AGE_SECONDS = 3600


async def create_job(client: AsyncClient, user_id: Any) -> str:
    await _prune(client)
    job_id = uuid4().hex
    await db.create_mcp_job(client, id=job_id, user_id=str(user_id), status="running")
    return job_id


async def finish_job(client: AsyncClient, job_id: str, *, presentation_id: str, title: str | None) -> None:
    await db.update_mcp_job(
        client, job_id, status="ready", presentation_id=presentation_id, title=title, error=None,
    )


async def fail_job(client: AsyncClient, job_id: str, error: str) -> None:
    await db.update_mcp_job(client, job_id, status="failed", error=str(error)[:500])


async def get_job(client: AsyncClient, job_id: str, user_id: Any) -> dict[str, Any] | None:
    row = await db.get_mcp_job(client, job_id)
    if row is None or row.get("user_id") != str(user_id):
        return None
    return {
        "status": row.get("status"),
        "presentation_id": row.get("presentation_id"),
        "title": row.get("title"),
        "error": row.get("error"),
    }


async def _prune(client: AsyncClient) -> None:
    cutoff = (datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        await client.table("mcp_jobs").delete().lt("created_at", cutoff).execute()
    except Exception:
        pass
