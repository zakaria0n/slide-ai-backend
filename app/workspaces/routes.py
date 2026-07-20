"""Workspace routes."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from app.core.exceptions import NotFoundError, UnauthorizedError
from app.db.dependencies import Database
from app.db.repositories.workspace import (
    WorkspaceRepository,
    WorkspaceMemberRepository,
    WorkspacePresentationRepository,
    WorkspaceAuditRepository,
)
from app.models.workspace import Workspace, WorkspaceMember, WorkspacePresentation, WorkspaceAudit

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_bearer = HTTPBearer(auto_error=False)


def _extract_token(creds=Depends(_bearer)) -> str:
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Missing authentication token")
    return creds.credentials


def _owner_id(request: Request, token: str = Depends(_extract_token)) -> UUID:
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise UnauthorizedError("Authentication is not configured")
    return verifier.user_id(token)


def _db(request: Request) -> Database:
    return request.app.state.db


# --- schemas ---


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    created_at: str


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]


class CreateWorkspaceRequest(BaseModel):
    name: str


class MemberResponse(BaseModel):
    id: str
    user_id: str
    role: str
    created_at: str


class MemberListResponse(BaseModel):
    members: list[MemberResponse]


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "viewer"


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


# --- endpoints ---


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    req: CreateWorkspaceRequest,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> WorkspaceResponse:
    session = db.session_factory()
    try:
        ws = Workspace(name=req.name, owner_id=owner_id)
        session.add(ws)
        await session.flush()
        # Add owner as member.
        owner_member = WorkspaceMember(workspace_id=ws.id, user_id=owner_id, role="owner")
        session.add(owner_member)
        await session.commit()
        await session.refresh(ws)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    return WorkspaceResponse(id=str(ws.id), name=ws.name, created_at=ws.created_at.isoformat())


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> WorkspaceListResponse:
    session = db.session_factory()
    try:
        workspaces = await WorkspaceRepository(session).list_for_owner(owner_id)
    finally:
        await session.close()

    return WorkspaceListResponse(
        workspaces=[WorkspaceResponse(id=str(w.id), name=w.name, created_at=w.created_at.isoformat()) for w in workspaces]
    )


@router.get("/{workspace_id}/members", response_model=MemberListResponse)
async def list_members(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> MemberListResponse:
    session = db.session_factory()
    try:
        ws = await WorkspaceRepository(session).get_owned(workspace_id, owner_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        members = await WorkspaceMemberRepository(session).list_for_workspace(workspace_id)
    finally:
        await session.close()

    return MemberListResponse(
        members=[MemberResponse(id=str(m.id), user_id=str(m.user_id), role=m.role, created_at=m.created_at.isoformat()) for m in members]
    )


@router.post("/{workspace_id}/members", status_code=201)
async def add_member(
    workspace_id: UUID,
    req: AddMemberRequest,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> MemberResponse:
    session = db.session_factory()
    try:
        ws = await WorkspaceRepository(session).get_owned(workspace_id, owner_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        member = WorkspaceMember(workspace_id=workspace_id, user_id=UUID(req.user_id), role=req.role, invited_by=owner_id)
        session.add(member)
        audit = WorkspaceAudit(workspace_id=workspace_id, actor_id=owner_id, action="add_member", target=req.user_id)
        session.add(audit)
        await session.commit()
        await session.refresh(member)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    return MemberResponse(id=str(member.id), user_id=str(member.user_id), role=member.role, created_at=member.created_at.isoformat())


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberResponse)
async def change_role(
    workspace_id: UUID,
    user_id: UUID,
    req: ChangeRoleRequest,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> MemberResponse:
    session = db.session_factory()
    try:
        ws = await WorkspaceRepository(session).get_owned(workspace_id, owner_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        member = await WorkspaceMemberRepository(session).get_member(workspace_id, user_id)
        if member is None:
            raise NotFoundError("Member not found")
        member.role = req.role
        audit = WorkspaceAudit(workspace_id=workspace_id, actor_id=owner_id, action="change_role", target=str(user_id), payload={"new_role": req.role})
        session.add(audit)
        await session.commit()
        await session.refresh(member)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    return MemberResponse(id=str(member.id), user_id=str(member.user_id), role=member.role, created_at=member.created_at.isoformat())


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> None:
    session = db.session_factory()
    try:
        ws = await WorkspaceRepository(session).get_owned(workspace_id, owner_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        member = await WorkspaceMemberRepository(session).get_member(workspace_id, user_id)
        if member is None:
            raise NotFoundError("Member not found")
        await session.delete(member)
        audit = WorkspaceAudit(workspace_id=workspace_id, actor_id=owner_id, action="remove_member", target=str(user_id))
        session.add(audit)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@router.post("/{workspace_id}/presentations", status_code=201)
async def add_presentation_to_workspace(
    workspace_id: UUID,
    req: AddPresentationRequest,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> dict[str, str]:
    session = db.session_factory()
    try:
        ws = await WorkspaceRepository(session).get_owned(workspace_id, owner_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        wp = WorkspacePresentation(workspace_id=workspace_id, presentation_id=UUID(req.presentation_id))
        session.add(wp)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    return {"status": "added"}


@router.get("/{workspace_id}/audit", response_model=AuditListResponse)
async def get_audit_log(
    workspace_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    db: Database = Depends(_db),
) -> AuditListResponse:
    session = db.session_factory()
    try:
        ws = await WorkspaceRepository(session).get_owned(workspace_id, owner_id)
        if ws is None:
            raise NotFoundError("Workspace not found")
        entries = await WorkspaceAuditRepository(session).list_for_workspace(workspace_id)
    finally:
        await session.close()

    return AuditListResponse(
        entries=[AuditResponse(id=str(e.id), actor_id=str(e.actor_id), action=e.action, target=e.target, created_at=e.created_at.isoformat()) for e in entries]
    )
