"""File upload business logic.

Owner-scoped: every file belongs to the caller (JWT ``sub``). Uploads
stream to Supabase Storage via the :class:`StorageGateway`; metadata is
recorded in the ``file_assets`` table. Deletion removes both the storage
object and the metadata row.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.db.repositories.file_asset import FileAssetRepository
from app.files.storage import StorageGateway
from app.models.file_asset import FileAsset

_BUCKET = "presentation-assets"
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
_ALLOWED_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pptx", ".ppt", ".docx", ".doc", ".txt", ".csv", ".md",
    ".svg", ".mp3", ".mp4",
}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = _UNSAFE.sub("_", name.strip()) or "file"
    return base[:200]


class FileService:
    """Owner-scoped file operations."""

    def __init__(self, session: AsyncSession, storage: StorageGateway) -> None:
        self._repo = FileAssetRepository(session)
        self._storage = storage

    async def upload(
        self, owner_id: UUID, *, filename: str, data: bytes, content_type: str | None
    ) -> FileAsset:
        if not data:
            raise ValidationError("File is empty")
        if len(data) > _MAX_BYTES:
            raise ValidationError("File exceeds the 50 MB limit")
        ext = _ext(filename)
        if ext not in _ALLOWED_EXT:
            raise ValidationError(f"File type '{ext or 'unknown'}' is not allowed")

        safe = _safe_filename(filename)
        storage_path = f"{owner_id}/{uuid4()}-{safe}"
        await self._storage.upload(storage_path, data, content_type=content_type)

        model = FileAsset(
            owner_id=owner_id,
            filename=safe,
            storage_path=storage_path,
            content_type=content_type,
            size_bytes=len(data),
        )
        return await self._repo.add(model)

    async def list_for_owner(self, owner_id: UUID) -> Sequence[FileAsset]:
        return await self._repo.list_for_owner(owner_id)

    async def get(self, file_id: UUID, owner_id: UUID) -> FileAsset:
        model = await self._repo.get(file_id)
        if model is None or model.owner_id != owner_id:
            raise NotFoundError("File not found")
        return model

    async def delete(self, file_id: UUID, owner_id: UUID) -> None:
        model = await self._require_owned(file_id, owner_id)
        try:
            await self._storage.delete(model.storage_path)
        except Exception:
            # Best-effort: the metadata row is the source of truth for the
            # listing, so removing it even if storage delete failed keeps
            # the UI consistent.
            pass
        await self._repo.delete(model)

    async def _require_owned(self, file_id: UUID, owner_id: UUID) -> FileAsset:
        model = await self._repo.get(file_id)
        if model is None or model.owner_id != owner_id:
            raise NotFoundError("File not found")
        return model


def _ext(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]
