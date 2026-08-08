"""Storage gateway abstraction for file uploads.

Decouples the file service from the concrete Supabase Storage client so
it can be unit-tested with a fake. The production implementation wraps
``AsyncStorageClient``; tests inject an in-memory fake.
"""
from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Protocol


class StorageGateway(ABC):
    """Object-storage operations needed by the file service."""

    @abstractmethod
    async def upload(
        self, path: str, data: bytes, *, content_type: str | None
    ) -> None:
        """Store ``data`` at ``path``."""

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Remove the object at ``path`` (best-effort)."""

    @abstractmethod
    async def create_signed_url(self, path: str, *, expires_in: int = 3600) -> str:
        """Return a time-limited URL for reading the object at ``path``."""


class SupabaseStorageGateway(StorageGateway):
    """StorageGateway backed by a Supabase ``AsyncStorageClient``."""

    def __init__(self, client: object, bucket: str = "presentation-assets") -> None:
        self._client = client
        self._bucket = bucket

    async def upload(
        self, path: str, data: bytes, *, content_type: str | None
    ) -> None:
        from storage3.types import FileOptions

        await self._client.storage.from_(self._bucket).upload(
            path,
            data,
            file_options=FileOptions(
                content_type=content_type or "application/octet-stream",
                upsert="true",
            ),
        )

    async def delete(self, path: str) -> None:
        await self._client.storage.from_(self._bucket).remove([path])

    async def create_signed_url(self, path: str, *, expires_in: int = 3600) -> str:
        res = await self._client.storage.from_(self._bucket).create_signed_url(
            path, expires_in=expires_in
        )
        if isinstance(res, (list, tuple)):
            res = res[0] if res else {}
        url = getattr(res, "signed_url", None)
        if not url and isinstance(res, dict):
            url = res.get("signedURL") or res.get("signed_url")
        return str(url or res)


class InMemoryStorageGateway(StorageGateway):
    """Volatile in-memory store for tests and offline development."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def upload(
        self, path: str, data: bytes, *, content_type: str | None
    ) -> None:
        self._objects[path] = data

    async def delete(self, path: str) -> None:
        self._objects.pop(path, None)

    async def create_signed_url(self, path: str, *, expires_in: int = 3600) -> str:
        data = self._objects.get(path)
        if data is None:
            return ""
        return "data:application/octet-stream;base64," + base64.b64encode(data).decode()
