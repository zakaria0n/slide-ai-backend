"""Pydantic schemas for the files API."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.file_asset import FileAsset


class FileAssetResponse(BaseModel):
    id: UUID
    owner_id: UUID
    filename: str
    storage_path: str
    content_type: str | None
    size_bytes: int
    created_at: datetime

    @classmethod
    def from_model(cls, m: FileAsset) -> "FileAssetResponse":
        return cls(
            id=m.id,
            owner_id=m.owner_id,
            filename=m.filename,
            storage_path=m.storage_path,
            content_type=m.content_type,
            size_bytes=m.size_bytes,
            created_at=m.created_at,
        )


class FileListResponse(BaseModel):
    items: list[FileAssetResponse]
    total: int
