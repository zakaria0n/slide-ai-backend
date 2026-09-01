"""Supabase query layer.

Thin async helpers for every database table.  Each function accepts a
``supabase.AsyncClient`` and returns plain ``dict`` / ``list[dict]`` /
``None`` — no ORM models, no repositories, no session management.

All UUIDs are passed as strings because the Supabase REST layer uses
JSON transport.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from supabase import AsyncClient


# ---------------------------------------------------------------------------
# presentations
# ---------------------------------------------------------------------------


async def get_presentation(client: AsyncClient, presentation_id: UUID) -> dict | None:
    row = await client.table("presentations").select("*").eq("id", str(presentation_id)).maybe_single().execute()
    return row.data  # type: ignore[return-value]


_ROLE_RANK = {"owner": 4, "admin": 3, "editor": 2, "viewer": 1}


async def get_presentation_access_role(
    client: AsyncClient, presentation_id: UUID, user_id: UUID
) -> str | None:
    """Return the caller's effective role over a presentation, or ``None``.

    A user can access a presentation if they own it, or if they are a
    member of a workspace that contains the presentation. The strongest
    role wins.
    """
    row = await get_presentation(client, presentation_id)
    if row is None:
        return None
    if str(row["owner_id"]) == str(user_id):
        return "owner"

    wp = (
        await client.table("workspace_presentations")
        .select("workspace_id")
        .eq("presentation_id", str(presentation_id))
        .execute()
    )
    ws_ids = [str(r["workspace_id"]) for r in (wp.data or [])]
    if not ws_ids:
        return None
    members = (
        await client.table("workspace_members")
        .select("role")
        .in_("workspace_id", ws_ids)
        .eq("user_id", str(user_id))
        .execute()
    )
    roles = [str(r["role"]) for r in (members.data or [])]
    if not roles:
        return None
    return max(roles, key=lambda r: _ROLE_RANK.get(r, 0))


async def list_presentations_by_ids(client: AsyncClient, ids: list[str]) -> list[dict]:
    """Fetch full presentation rows for a list of ids (preserving input order)."""
    if not ids:
        return []
    resp = (
        await client.table("presentations")
        .select("*")
        .in_("id", ids)
        .execute()
    )
    by_id = {str(r["id"]): r for r in (resp.data or [])}
    return [by_id[i] for i in ids if i in by_id]


async def count_presentations(client: AsyncClient, owner_id: UUID) -> int:
    resp = (
        await client.table("presentations")
        .select("id", count="exact")
        .eq("owner_id", str(owner_id))
        .execute()
    )
    return resp.count  # type: ignore[return-value]


async def list_presentations(
    client: AsyncClient,
    owner_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    resp = (
        await client.table("presentations")
        .select("*")
        .eq("owner_id", str(owner_id))
        .order("updated_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def create_presentation(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("presentations").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def update_presentation(client: AsyncClient, presentation_id: UUID, **fields: Any) -> dict | None:
    resp = (
        await client.table("presentations")
        .update(fields)
        .eq("id", str(presentation_id))
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else None


async def delete_presentation(client: AsyncClient, presentation_id: UUID) -> None:
    await client.table("presentations").delete().eq("id", str(presentation_id)).execute()


# ---------------------------------------------------------------------------
# file_assets
# ---------------------------------------------------------------------------


async def get_file_asset(client: AsyncClient, file_id: UUID) -> dict | None:
    row = await client.table("file_assets").select("*").eq("id", str(file_id)).maybe_single().execute()
    return row.data  # type: ignore[return-value]


async def list_file_assets(
    client: AsyncClient,
    owner_id: UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    resp = (
        await client.table("file_assets")
        .select("*")
        .eq("owner_id", str(owner_id))
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def create_file_asset(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("file_assets").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def delete_file_asset(client: AsyncClient, file_id: UUID) -> None:
    await client.table("file_assets").delete().eq("id", str(file_id)).execute()


# ---------------------------------------------------------------------------
# presentation_shares
# ---------------------------------------------------------------------------


async def get_share_by_token(client: AsyncClient, token: str) -> dict | None:
    row = await client.table("presentation_shares").select("*").eq("token", token).maybe_single().execute()
    return row.data  # type: ignore[return-value]


async def list_shares(
    client: AsyncClient,
    presentation_id: UUID,
    *,
    limit: int = 50,
) -> list[dict]:
    resp = (
        await client.table("presentation_shares")
        .select("*")
        .eq("presentation_id", str(presentation_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def create_share(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("presentation_shares").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def delete_share(client: AsyncClient, token: str) -> None:
    await client.table("presentation_shares").delete().eq("token", token).execute()


# ---------------------------------------------------------------------------
# presentation_versions
# ---------------------------------------------------------------------------


async def list_versions(
    client: AsyncClient,
    presentation_id: UUID,
    *,
    limit: int = 50,
) -> list[dict]:
    resp = (
        await client.table("presentation_versions")
        .select("*")
        .eq("presentation_id", str(presentation_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def get_version(
    client: AsyncClient,
    version_id: UUID,
    *,
    owner_id: UUID | None = None,
) -> dict | None:
    q = client.table("presentation_versions").select("*").eq("id", str(version_id))
    if owner_id is not None:
        q = q.eq("owner_id", str(owner_id))
    row = await q.maybe_single().execute()
    return row.data  # type: ignore[return-value]


async def get_latest_spec_hash(client: AsyncClient, presentation_id: UUID) -> str | None:
    import json

    resp = (
        await client.table("presentation_versions")
        .select("spec")
        .eq("presentation_id", str(presentation_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows: list[dict] = resp.data
    if not rows:
        return None
    return json.dumps(rows[0].get("spec"), sort_keys=True)


async def create_version(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("presentation_versions").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# workspaces
# ---------------------------------------------------------------------------


async def get_workspace(client: AsyncClient, workspace_id: UUID, *, owner_id: UUID | None = None) -> dict | None:
    q = client.table("workspaces").select("*").eq("id", str(workspace_id))
    if owner_id is not None:
        q = q.eq("owner_id", str(owner_id))
    row = await q.maybe_single().execute()
    return row.data  # type: ignore[return-value]


async def list_workspaces(client: AsyncClient, user_id: UUID) -> list[dict]:
    """Return the workspaces the user belongs to (owner or member).

    Each row includes the caller's ``role`` in that workspace.
    """
    resp = (
        await client.table("workspace_members")
        .select("workspace_id", "role")
        .eq("user_id", str(user_id))
        .execute()
    )
    ws_ids = [str(r["workspace_id"]) for r in (resp.data or [])]
    if not ws_ids:
        return []
    role_by_id = {str(r["workspace_id"]): r.get("role") for r in (resp.data or [])}
    resp = (
        await client.table("workspaces")
        .select("*")
        .in_("id", ws_ids)
        .order("created_at", desc=True)
        .execute()
    )
    workspaces = list(resp.data or [])
    for w in workspaces:
        w["role"] = role_by_id.get(str(w["id"]), "member")
    return workspaces


async def create_workspace(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("workspaces").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def delete_workspace(client: AsyncClient, workspace_id: UUID) -> None:
    wid = str(workspace_id)
    for table in ("workspace_audit", "workspace_presentations", "workspace_members"):
        await client.table(table).delete().eq("workspace_id", wid).execute()
    await client.table("workspaces").delete().eq("id", wid).execute()


# ---------------------------------------------------------------------------
# workspace_members
# ---------------------------------------------------------------------------


async def list_members(client: AsyncClient, workspace_id: UUID) -> list[dict]:
    resp = (
        await client.table("workspace_members")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def _fetch_auth_users(client: AsyncClient, *, limit: int = 200) -> list[dict]:
    """Fetch auth users, preferring the GoTrue Admin API.

    The ``auth`` schema is usually NOT exposed to PostgREST, so
    ``schema("auth").from_("users")`` fails silently. The GoTrue Admin API
    (``/auth/v1/admin/users``) works with the service-role key and never
    requires schema exposure. Falls back to the ``auth`` schema query when
    the admin route is unavailable (e.g. local fakes).
    """
    # Real Supabase clients expose auth_url + the service-role key.
    auth_url = getattr(client, "auth_url", None)
    key = getattr(client, "supabase_key", None)
    if auth_url is not None and key is not None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    f"{auth_url}/admin/users",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                    params={"per_page": min(limit, 1000)},
                )
                resp.raise_for_status()
            rows = (resp.json() or {}).get("users") or []
            return [
                {
                    "id": u.get("id"),
                    "email": u.get("email") or "",
                    "raw_user_meta_data": u.get("raw_user_meta_data") or u.get("user_metadata") or {},
                }
                for u in rows
            ]
        except Exception:
            pass  # fall back to schema query below

    try:
        resp = (
            await client.schema("auth")
            .from_("users")
            .select("id, email, raw_user_meta_data")
            .limit(limit)
            .execute()
        )
        return [dict(r) for r in (resp.data or [])]
    except Exception:
        return []


async def list_user_profiles(client: AsyncClient, user_ids: list[str]) -> dict[str, dict[str, str]]:
    """Map user_id -> {display_name, email} from auth.users (best effort)."""
    profiles: dict[str, dict[str, str]] = {}
    if not user_ids:
        return profiles
    wanted = {str(uid) for uid in user_ids}
    for row in await _fetch_auth_users(client, limit=200):
        uid = str(row.get("id"))
        if uid not in wanted:
            continue
        meta = row.get("raw_user_meta_data") or {}
        if not isinstance(meta, dict):
            meta = {}
        name = meta.get("full_name") or meta.get("name") or row.get("email") or uid
        profiles[uid] = {
            "display_name": str(name),
            "email": str(row.get("email") or ""),
        }
    return profiles


async def search_users(client: AsyncClient, query: str, *, limit: int = 10) -> list[dict]:
    """Search auth.users by display name or email (best effort)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    matches: list[dict] = []
    for row in await _fetch_auth_users(client, limit=200):
        uid = str(row.get("id"))
        email = str(row.get("email") or "")
        meta = row.get("raw_user_meta_data") or {}
        if not isinstance(meta, dict):
            meta = {}
        name = str(meta.get("full_name") or meta.get("name") or "")
        if q in name.lower() or q in email.lower():
            matches.append({"user_id": uid, "display_name": name or email, "email": email})
        if len(matches) >= limit:
            break
    return matches


async def get_member(client: AsyncClient, workspace_id: UUID, user_id: UUID) -> dict | None:
    row = (
        await client.table("workspace_members")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .eq("user_id", str(user_id))
        .maybe_single()
        .execute()
    )
    return row.data  # type: ignore[return-value]


async def add_member(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("workspace_members").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def delete_member(client: AsyncClient, workspace_id: UUID, user_id: UUID) -> None:
    await (
        client.table("workspace_members")
        .delete()
        .eq("workspace_id", str(workspace_id))
        .eq("user_id", str(user_id))
        .execute()
    )


async def update_member_role(client: AsyncClient, workspace_id: UUID, user_id: UUID, role: str) -> dict | None:
    resp = (
        await client.table("workspace_members")
        .update({"role": role})
        .eq("workspace_id", str(workspace_id))
        .eq("user_id", str(user_id))
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# workspace_presentations
# ---------------------------------------------------------------------------


async def add_workspace_presentation(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("workspace_presentations").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def list_workspace_presentations(client: AsyncClient, workspace_id: UUID) -> list[dict]:
    resp = (
        await client.table("workspace_presentations")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def delete_workspace_presentation(client: AsyncClient, workspace_id: UUID, presentation_id: UUID) -> None:
    await (
        client.table("workspace_presentations")
        .delete()
        .eq("workspace_id", str(workspace_id))
        .eq("presentation_id", str(presentation_id))
        .execute()
    )


# ---------------------------------------------------------------------------
# workspace_audit
# ---------------------------------------------------------------------------


async def create_audit_entry(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("workspace_audit").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def list_audit(client: AsyncClient, workspace_id: UUID, *, limit: int = 50) -> list[dict]:
    resp = (
        await client.table("workspace_audit")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# workspace_invitations
# ---------------------------------------------------------------------------


async def create_invitation(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("workspace_invitations").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def list_workspace_invitations(client: AsyncClient, workspace_id: UUID) -> list[dict]:
    resp = (
        await client.table("workspace_invitations")
        .select("*")
        .eq("workspace_id", str(workspace_id))
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


async def get_invitation(client: AsyncClient, invitation_id: UUID) -> dict | None:
    row = (
        await client.table("workspace_invitations")
        .select("*")
        .eq("id", str(invitation_id))
        .maybe_single()
        .execute()
    )
    return row.data  # type: ignore[return-value]


async def update_invitation_status(client: AsyncClient, invitation_id: UUID, status: str) -> dict | None:
    resp = (
        await client.table("workspace_invitations")
        .update({"status": status})
        .eq("id", str(invitation_id))
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else None


async def list_pending_invitations_for_email(client: AsyncClient, email: str) -> list[dict]:
    """Return pending invitations targeting a given email address."""
    resp = (
        await client.table("workspace_invitations")
        .select("*")
        .eq("email", email)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# chat_messages
# ---------------------------------------------------------------------------


async def list_chat_messages(
    client: AsyncClient,
    presentation_id: UUID,
    *,
    owner_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    q = (
        client.table("chat_messages")
        .select("*")
        .eq("presentation_id", str(presentation_id))
        .order("created_at", desc=False)
        .limit(limit)
    )
    if owner_id is not None:
        q = q.eq("owner_id", owner_id)
    resp = await q.execute()
    return resp.data  # type: ignore[return-value]


async def create_chat_message(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("chat_messages").insert(fields).execute()
    return resp.data[0]  # type: ignore[return-value]


async def delete_chat_messages(
    client: AsyncClient,
    presentation_id: UUID,
    owner_id: str | None = None,
) -> None:
    q = client.table("chat_messages").delete().eq("presentation_id", str(presentation_id))
    if owner_id is not None:
        q = q.eq("owner_id", owner_id)
    await q.execute()


async def get_brand_kit(client: AsyncClient, user_id: UUID) -> dict | None:
    resp = (
        await client.table("user_brand_kits")
        .select("*")
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else None


async def upsert_brand_kit(client: AsyncClient, user_id: UUID, **fields: Any) -> dict:
    payload = {"user_id": str(user_id), **fields, "updated_at": "now()"}
    payload = {k: v for k, v in payload.items() if v is not None or k == "user_id"}
    resp = (
        await client.table("user_brand_kits")
        .upsert(payload)
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else {}


async def list_user_themes(client: AsyncClient, user_id: UUID) -> list[dict]:
    resp = (
        await client.table("user_themes")
        .select("*")
        .eq("user_id", str(user_id))
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data or []


async def get_user_theme(client: AsyncClient, theme_id: UUID, user_id: UUID) -> dict | None:
    resp = (
        await client.table("user_themes")
        .select("*")
        .eq("id", str(theme_id))
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else None


async def create_user_theme(client: AsyncClient, **fields: Any) -> dict:
    resp = await client.table("user_themes").insert(fields).execute()
    rows: list[dict] = resp.data
    return rows[0] if rows else {}


async def delete_user_theme(client: AsyncClient, theme_id: UUID, user_id: UUID) -> None:
    await (
        client.table("user_themes")
        .delete()
        .eq("id", str(theme_id))
        .eq("user_id", str(user_id))
        .execute()
    )


async def create_mcp_job(client: AsyncClient, *, id: str, user_id: str, status: str) -> dict:
    resp = (
        await client.table("mcp_jobs")
        .insert({"id": id, "user_id": user_id, "status": status})
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else {}


async def update_mcp_job(client: AsyncClient, job_id: str, **fields: Any) -> None:
    await client.table("mcp_jobs").update(fields).eq("id", job_id).execute()


async def get_mcp_job(client: AsyncClient, job_id: str) -> dict | None:
    resp = (
        await client.table("mcp_jobs")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else None


async def increment_share_views(client: AsyncClient, token: str) -> None:
    row = await get_share_by_token(client, token)
    if row is None:
        return
    await (
        client.table("presentation_shares")
        .update({"view_count": int(row.get("view_count") or 0) + 1})
        .eq("token", token)
        .execute()
    )


async def create_share_comment(client: AsyncClient, *, share_token: str, author_name: str | None, content: str) -> dict:
    resp = (
        await client.table("share_comments")
        .insert({"share_token": share_token, "author_name": author_name, "content": content})
        .execute()
    )
    rows: list[dict] = resp.data
    return rows[0] if rows else {}


async def list_share_comments(client: AsyncClient, share_token: str, *, limit: int = 100) -> list[dict]:
    resp = (
        await client.table("share_comments")
        .select("*")
        .eq("share_token", share_token)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return resp.data
