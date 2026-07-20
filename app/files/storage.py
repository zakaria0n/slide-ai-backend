"""Storage gateway abstraction for file uploads.

Decouples the file service from the concrete Supabase Storage client so
it can be unit-tested with a fake. The production implementation wraps
``AsyncStorageClient``; tests inject an in-memory fake.
"""
from __future__ import annotations

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
            file_options=FileOptions(content_type=content_type or "application/octet-stream", upsert=True),
        )

    async def delete(self, path: str) -> None:
        await self._client.storage.from_(self._bucket).remove([path])


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
