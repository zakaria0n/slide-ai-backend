"""Pydantic schemas for the files API."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FileAssetResponse(BaseModel):
    id: UUID
    owner_id: UUID
    filename: str
    storage_path: str
    content_type: str | None
    size_bytes: int
    created_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "FileAssetResponse":
        created_at = d["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            id=UUID(d["id"]),
            owner_id=UUID(d["owner_id"]),
            filename=d["filename"],
            storage_path=d["storage_path"],
            content_type=d.get("content_type"),
            size_bytes=d.get("size_bytes", 0),
            created_at=created_at,
        )


class FileListResponse(BaseModel):
    items: list[FileAssetResponse]
    total: int


class FileUrlResponse(BaseModel):
    url: str
    expires_in: int