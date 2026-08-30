"""File upload business logic.

Owner-scoped: every file belongs to the caller (JWT ``sub``). Uploads
stream to Supabase Storage via the :class:`StorageGateway`; metadata is
recorded in the ``file_assets`` table. Deletion removes both the storage
object and the metadata row.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID, uuid4

from supabase import AsyncClient

import app.db as db
from app.core.exceptions import NotFoundError, ValidationError
from app.files.storage import StorageGateway

_BUCKET = "presentation-assets"
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
_ALLOWED_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pptx", ".ppt", ".docx", ".doc", ".txt", ".csv", ".md",
    ".svg", ".mp3", ".mp4", ".webm", ".wav", ".m4a", ".ogg",
}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    base = _UNSAFE.sub("_", name.strip()) or "file"
    return base[:200]


class FileService:
    """Owner-scoped file operations."""

    def __init__(self, client: AsyncClient, storage: StorageGateway) -> None:
        self._client = client
        self._storage = storage

    async def upload(
        self, owner_id: UUID, *, filename: str, data: bytes, content_type: str | None
    ) -> dict:
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

        return await db.create_file_asset(
            self._client,
            owner_id=str(owner_id),
            filename=safe,
            storage_path=storage_path,
            content_type=content_type,
            size_bytes=len(data),
        )

    async def list_for_owner(self, owner_id: UUID) -> Sequence[dict]:
        return await db.list_file_assets(self._client, owner_id)

    async def get(self, file_id: UUID, owner_id: UUID) -> dict:
        row = await db.get_file_asset(self._client, file_id)
        if row is None or row["owner_id"] != str(owner_id):
            raise NotFoundError("File not found")
        return row

    async def signed_url(
        self, file_id: UUID, owner_id: UUID, *, expires_in: int = 3600
    ) -> dict:
        row = await self._require_owned(file_id, owner_id)
        url = await self._storage.create_signed_url(
            row["storage_path"], expires_in=expires_in
        )
        return {"url": url, "expires_in": expires_in}

    async def delete(self, file_id: UUID, owner_id: UUID) -> None:
        row = await self._require_owned(file_id, owner_id)
        try:
            await self._storage.delete(row["storage_path"])
        except Exception:
            pass
        await db.delete_file_asset(self._client, file_id)

    async def _require_owned(self, file_id: UUID, owner_id: UUID) -> dict:
        row = await db.get_file_asset(self._client, file_id)
        if row is None or row["owner_id"] != str(owner_id):
            raise NotFoundError("File not found")
        return row


async def resolve_spec_image_urls(
    client: AsyncClient,
    storage,
    spec,
    owner_id: UUID,
    *,
    expires_in: int = 24 * 3600,
):
    """Replace expiring image srcs with fresh signed URLs.

    Image elements carry a stable ``file_id``; their ``src`` is a signed URL
    that expires. Walk the spec, and for every image with a file_id owned by
    ``owner_id`` mint a fresh URL (default 24h — enough for any render or
    export). Unknown/unowned ids are left untouched.
    """
    from app.generation.spec import ImageElement
    from uuid import UUID as _UUID

    cache: dict[str, str] = {}
    for slide in spec.slides:
        for i, el in enumerate(slide.elements):
            if not isinstance(el, ImageElement):
                continue
            fid = el.file_id
            if not fid or el.src is None:
                continue
            try:
                file_uuid = _UUID(fid)
            except ValueError:
                continue
            if fid not in cache:
                row = await db.get_file_asset(client, file_uuid)
                if row is None or row["owner_id"] != str(owner_id):
                    cache[fid] = el.src
                else:
                    try:
                        info = await storage.create_signed_url(row["storage_path"], expires_in=expires_in)
                        cache[fid] = info if isinstance(info, str) else info.get("url", el.src)
                    except Exception:
                        cache[fid] = el.src
            slide.elements[i] = el.model_copy(update={"src": cache[fid]})
    return spec


def _ext(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]