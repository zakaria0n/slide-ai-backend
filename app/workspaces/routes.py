"""Workspace routes."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, field_validator
from supabase import AsyncClient

import app.db as db
from app.api.deps import owner_id, supabase, user_email
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.presentations.schemas import PresentationResponse

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_owner_id = owner_id
_supabase = supabase
_email = user_email


# --- schemas ---


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    created_at: str
    role: str = "member"


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]


class CreateWorkspaceRequest(BaseModel):
    name: str


class MemberResponse(BaseModel):
    id: str
    user_id: str
    role: str
    created_at: str
    display_name: str = ""
    email: str = ""


class MemberListResponse(BaseModel):
    members: list[MemberResponse]


class UserSearchResult(BaseModel):
    user_id: str
    display_name: str
    email: str


class UserSearchResponse(BaseModel):
    users: list[UserSearchResult]


class WorkspacePresentationsResponse(BaseModel):
    presentation_ids: list[str]
    presentations: list[PresentationResponse] = []


def _validate_uuid_str(value: str, field: str) -> str:
    """Reject non-UUID strings before they hit the UUID column."""
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=422, detail=f"{field} must be a valid UUID")


class ChangeRoleRequest(BaseModel):
    role: str


class AuditResponse(BaseModel):
    id: str
    actor_id: str
    action: str
    target: str | None
    created_at: str


class AuditListResponse(BaseModel):
    entries: list[AuditResponse]


class AddPresentationRequest(BaseModel):
    presentation_id: str

    @field_validator("presentation_id")
    @classmethod
    def _check_pid(cls, v: str) -> str:
        return _validate_uuid_str(v, "presentation_id")


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "viewer"


class InvitationResponse(BaseModel):
    id: str
    workspace_id: str
    email: str
    role: str
    status: str
    created_at: str


class InvitationListResponse(BaseModel):
    invitations: list[InvitationResponse]


class PendingInvitationResponse(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str
    email: str
    role: str
    created_at: str


class PendingInvitationListResponse(BaseModel):
    invitations: list[PendingInvitationResponse]


# --- endpoints ---


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    req: CreateWorkspaceRequest,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> WorkspaceResponse:
    ws = await db.create_workspace(supabase, name=req.name, owner_id=str(owner_id))
    await db.add_member(supabase, workspace_id=ws["id"], user_id=str(owner_id), role="owner", invited_by=str(owner_id))

    return WorkspaceResponse(id=ws["id"], name=ws["name"], created_at=ws["created_at"])


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> WorkspaceListResponse:
    workspaces = await db.list_workspaces(supabase, owner_id)

    return WorkspaceListResponse(
        workspaces=[
            WorkspaceResponse(
                id=str(w["id"]),
                name=w["name"],
                created_at=w["created_at"],
                role=str(w.get("role", "member")),
            )
            for w in workspaces
        ]
    )


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    ws = await db.get_workspace(supabase, workspace_id, owner_id=owner_id)
    if ws is None:
        raise NotFoundError("Workspace not found")
    await db.delete_workspace(supabase, workspace_id)


@router.get("/search/users", response_model=UserSearchResponse)
async def search_users(
    q: str = Query(default="", max_length=80),
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> UserSearchResponse:
    users = await db.search_users(supabase, q)
    return UserSearchResponse(
        users=[
            UserSearchResult(user_id=u["user_id"], display_name=u["display_name"], email=u["email"])
            for u in users
        ]
    )


@router.get("/{workspace_id}/members", response_model=MemberListResponse)
async def list_members(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> MemberListResponse:
    member = await db.get_member(supabase, workspace_id, owner_id)
    if member is None:
        raise NotFoundError("Workspace not found")
    members = await db.list_members(supabase, workspace_id)
    profiles = await db.list_user_profiles(supabase, [str(m["user_id"]) for m in members])

    return MemberListResponse(
        members=[
            MemberResponse(
                id=str(m["id"]),
                user_id=str(m["user_id"]),
                role=m["role"],
                created_at=m["created_at"],
                display_name=profiles.get(str(m["user_id"]), {}).get("display_name", ""),
                email=profiles.get(str(m["user_id"]), {}).get("email", ""),
            )
            for m in members
        ]
    )


@router.post("/{workspace_id}/invitations", response_model=InvitationResponse, status_code=201)
async def invite_member(
    workspace_id: UUID,
    req: InviteMemberRequest,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> InvitationResponse:
    ws = await db.get_workspace(supabase, workspace_id, owner_id=owner_id)
    if ws is None:
        raise NotFoundError("Workspace not found")

    email = req.email.lower()
    members = await db.list_members(supabase, workspace_id)
    if any(str(m["user_id"]) == str(owner_id) for m in members):
        pass  # owner is always a member

    invite = await db.create_invitation(
        supabase,
        workspace_id=str(workspace_id),
        email=email,
        role=req.role,
        invited_by=str(owner_id),
        status="pending",
    )
    await db.create_audit_entry(
        supabase,
        workspace_id=str(workspace_id),
        actor_id=str(owner_id),
        action="invite_member",
        target=email,
    )
    return InvitationResponse(
        id=str(invite["id"]),
        workspace_id=str(invite["workspace_id"]),
        email=str(invite["email"]),
        role=str(invite["role"]),
        status=str(invite["status"]),
        created_at=str(invite["created_at"]),
    )


@router.get("/{workspace_id}/invitations", response_model=InvitationListResponse)
async def list_workspace_invitations(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> InvitationListResponse:
    ws = await db.get_workspace(supabase, workspace_id, owner_id=owner_id)
    if ws is None:
        raise NotFoundError("Workspace not found")
    invites = await db.list_workspace_invitations(supabase, workspace_id)
    return InvitationListResponse(
        invitations=[
            InvitationResponse(
                id=str(i["id"]),
                workspace_id=str(i["workspace_id"]),
                email=str(i["email"]),
                role=str(i["role"]),
                status=str(i["status"]),
                created_at=str(i["created_at"]),
            )
            for i in invites
        ]
    )


@router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=204)
async def cancel_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    ws = await db.get_workspace(supabase, workspace_id, owner_id=owner_id)
    if ws is None:
        raise NotFoundError("Workspace not found")
    invite = await db.get_invitation(supabase, invitation_id)
    if invite is None or str(invite["workspace_id"]) != str(workspace_id):
        raise NotFoundError("Invitation not found")
    await db.update_invitation_status(supabase, invitation_id, "cancelled")
    await db.create_audit_entry(
        supabase,
        workspace_id=str(workspace_id),
        actor_id=str(owner_id),
        action="cancel_invitation",
        target=str(invitation_id),
    )


@router.get("/invitations/pending", response_model=PendingInvitationListResponse)
async def pending_invitations(
    email: str = Depends(_email),
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> PendingInvitationListResponse:
    invites = await db.list_pending_invitations_for_email(supabase, email.lower())
    workspace_ids = {str(i["workspace_id"]) for i in invites}
    workspaces: dict[str, dict] = {}
    for wid in workspace_ids:
        try:
            w = await db.get_workspace(supabase, UUID(wid))
        except Exception:
            w = None
        if w is not None:
            workspaces[str(w["id"])] = w

    return PendingInvitationListResponse(
        invitations=[
            PendingInvitationResponse(
                id=str(i["id"]),
                workspace_id=str(i["workspace_id"]),
                workspace_name=str(workspaces.get(str(i["workspace_id"]), {}).get("name", "Workspace")),
                email=str(i["email"]),
                role=str(i["role"]),
                created_at=str(i["created_at"]),
            )
            for i in invites
        ]
    )


@router.post("/invitations/{invitation_id}/accept", response_model=MemberResponse)
async def accept_invitation(
    invitation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    email: str = Depends(_email),
    supabase: AsyncClient = Depends(_supabase),
) -> MemberResponse:
    invite = await db.get_invitation(supabase, invitation_id)
    if invite is None:
        raise NotFoundError("Invitation not found")
    if str(invite["email"]).lower() != email.lower():
        raise NotFoundError("Invitation not found")
    if invite["status"] != "pending":
        raise ConflictError("Invitation already handled")

    member = await db.add_member(
        supabase,
        workspace_id=str(invite["workspace_id"]),
        user_id=str(owner_id),
        role=str(invite["role"]),
        invited_by=str(invite.get("invited_by") or ""),
    )
    await db.update_invitation_status(supabase, invitation_id, "accepted")
    await db.create_audit_entry(
        supabase,
        workspace_id=str(invite["workspace_id"]),
        actor_id=str(owner_id),
        action="accept_invitation",
        target=str(invitation_id),
    )
    profiles = await db.list_user_profiles(supabase, [str(owner_id)])
    profile = profiles.get(str(owner_id), {})
    return MemberResponse(
        id=str(member["id"]),
        user_id=str(member["user_id"]),
        role=str(member["role"]),
        created_at=str(member["created_at"]),
        display_name=profile.get("display_name", ""),
        email=profile.get("email", ""),
    )


@router.post("/invitations/{invitation_id}/decline", status_code=204)
async def decline_invitation(
    invitation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    email: str = Depends(_email),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    invite = await db.get_invitation(supabase, invitation_id)
    if invite is None:
        raise NotFoundError("Invitation not found")
    if str(invite["email"]).lower() != email.lower():
        raise NotFoundError("Invitation not found")
    if invite["status"] != "pending":
        raise ConflictError("Invitation already handled")
    await db.update_invitation_status(supabase, invitation_id, "declined")


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def change_role(
    workspace_id: UUID,
    user_id: UUID,
    req: ChangeRoleRequest,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> MemberResponse:
    ws = await db.get_workspace(supabase, workspace_id, owner_id=owner_id)
    if ws is None:
        raise NotFoundError("Workspace not found")
    member = await db.get_member(supabase, workspace_id, user_id)
    if member is None:
        raise NotFoundError("Member not found")
    await db.update_member_role(supabase, workspace_id, user_id, req.role)
    await db.create_audit_entry(
        supabase, workspace_id=str(workspace_id), actor_id=str(owner_id), action="change_role", target=str(user_id), payload={"new_role": req.role}
    )

    profiles = await db.list_user_profiles(supabase, [str(user_id)])
    profile = profiles.get(str(user_id), {})
    return MemberResponse(
        id=str(member["id"]),
        user_id=str(member["user_id"]),
        role=req.role,
        created_at=member["created_at"],
        display_name=profile.get("display_name", ""),
        email=profile.get("email", ""),
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    ws = await db.get_workspace(supabase, workspace_id, owner_id=owner_id)
    if ws is None:
        raise NotFoundError("Workspace not found")
    member = await db.get_member(supabase, workspace_id, user_id)
    if member is None:
        raise NotFoundError("Member not found")
    await db.delete_member(supabase, workspace_id, user_id)
    await db.create_audit_entry(
        supabase, workspace_id=str(workspace_id), actor_id=str(owner_id), action="remove_member", target=str(user_id)
    )


@router.post("/{workspace_id}/leave", status_code=204)
async def leave_workspace(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    """Remove the caller from the workspace. The owner cannot leave."""
    member = await db.get_member(supabase, workspace_id, owner_id)
    if member is None:
        raise NotFoundError("Workspace not found")
    if member["role"] == "owner":
        raise ForbiddenError("The workspace owner cannot leave")
    await db.delete_member(supabase, workspace_id, owner_id)
    await db.create_audit_entry(
        supabase,
        workspace_id=str(workspace_id),
        actor_id=str(owner_id),
        action="leave_workspace",
        target=str(owner_id),
    )


@router.get("/{workspace_id}/presentations", response_model=WorkspacePresentationsResponse)
async def list_workspace_presentations(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> WorkspacePresentationsResponse:
    member = await db.get_member(supabase, workspace_id, owner_id)
    if member is None:
        raise NotFoundError("Workspace not found")
    rows = await db.list_workspace_presentations(supabase, workspace_id)
    ids = [str(r["presentation_id"]) for r in rows]
    presentation_rows = await db.list_presentations_by_ids(supabase, ids)
    presentations = [
        PresentationResponse(
            id=p["id"],
            owner_id=p["owner_id"],
            title=p["title"],
            description=p.get("description"),
            slide_count=p.get("slide_count", 0),
            status=p.get("status", "draft"),
            theme=p.get("theme"),
            created_at=p["created_at"],
            updated_at=p["updated_at"],
        )
        for p in presentation_rows
    ]
    return WorkspacePresentationsResponse(
        presentation_ids=ids,
        presentations=presentations,
    )


@router.post("/{workspace_id}/presentations", status_code=201)
async def add_presentation_to_workspace(
    workspace_id: UUID,
    req: AddPresentationRequest,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> dict[str, str]:
    member = await db.get_member(supabase, workspace_id, owner_id)
    if member is None:
        raise NotFoundError("Workspace not found")
    if member["role"] not in ("owner", "admin"):
        raise ForbiddenError("Only the workspace owner or an admin can manage presentations")
    await db.add_workspace_presentation(supabase, workspace_id=str(workspace_id), presentation_id=req.presentation_id)

    return {"status": "added"}


@router.delete("/{workspace_id}/presentations/{presentation_id}", status_code=204)
async def remove_presentation_from_workspace(
    workspace_id: UUID,
    presentation_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> None:
    member = await db.get_member(supabase, workspace_id, owner_id)
    if member is None:
        raise NotFoundError("Workspace not found")
    if member["role"] not in ("owner", "admin"):
        raise ForbiddenError("Only the workspace owner or an admin can manage presentations")
    await db.delete_workspace_presentation(supabase, workspace_id, presentation_id)
    await db.create_audit_entry(
        supabase,
        workspace_id=str(workspace_id),
        actor_id=str(owner_id),
        action="remove_presentation",
        target=str(presentation_id),
    )


@router.get("/{workspace_id}/audit", response_model=AuditListResponse)
async def get_audit_log(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    supabase: AsyncClient = Depends(_supabase),
) -> AuditListResponse:
    member = await db.get_member(supabase, workspace_id, owner_id)
    if member is None:
        raise NotFoundError("Workspace not found")
    entries = await db.list_audit(supabase, workspace_id)

    return AuditListResponse(
        entries=[AuditResponse(id=str(e["id"]), actor_id=str(e["actor_id"]), action=e["action"], target=e.get("target"), created_at=e["created_at"]) for e in entries]
    )