"""Repository for workspace entities."""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import SqlAlchemyRepository
from app.models.workspace import Workspace, WorkspaceMember, WorkspacePresentation, WorkspaceAudit


class WorkspaceRepository(SqlAlchemyRepository[Workspace]):
    model = Workspace

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_owner(self, owner_id: UUID) -> Sequence[Workspace]:
        stmt = select(Workspace).where(Workspace.owner_id == owner_id).order_by(Workspace.created_at.desc())
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_owned(self, workspace_id: UUID, owner_id: UUID) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.id == workspace_id).where(Workspace.owner_id == owner_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()


class WorkspaceMemberRepository(SqlAlchemyRepository[WorkspaceMember]):
    model = WorkspaceMember

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_workspace(self, workspace_id: UUID) -> Sequence[WorkspaceMember]:
        stmt = select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_member(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMember | None:
        stmt = select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id).where(WorkspaceMember.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()


class WorkspacePresentationRepository(SqlAlchemyRepository[WorkspacePresentation]):
    model = WorkspacePresentation

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_workspace(self, workspace_id: UUID) -> Sequence[UUID]:
        stmt = select(WorkspacePresentation.presentation_id).where(WorkspacePresentation.workspace_id == workspace_id)
        result = await self._session.execute(stmt)
        return [row for row in result.scalars().all()]


class WorkspaceAuditRepository(SqlAlchemyRepository[WorkspaceAudit]):
    model = WorkspaceAudit

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_workspace(self, workspace_id: UUID, limit: int = 50) -> Sequence[WorkspaceAudit]:
        stmt = select(WorkspaceAudit).where(WorkspaceAudit.workspace_id == workspace_id).order_by(WorkspaceAudit.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return result.scalars().all()
