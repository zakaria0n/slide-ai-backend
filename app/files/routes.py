"""File upload routes.

Endpoints (all owner-scoped, require a Bearer access token):
- ``POST   /files``             upload a file (multipart ``file`` field)
- ``GET    /files``             list the caller's files
- ``DELETE /files/{id}``        delete a file (storage object + metadata)

Routes contain no business logic; they delegate to :class:`FileService`.
The storage gateway is resolved from app state (Supabase Storage in
production, in-memory otherwise).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from supabase import AsyncClient

from app.api.deps import extract_token, owner_id, supabase
from app.files.schemas import FileAssetResponse, FileListResponse, FileUrlResponse
from app.files.service import FileService
from app.files.storage import InMemoryStorageGateway, StorageGateway

router = APIRouter(prefix="/files", tags=["files"])

_extract_token = extract_token
_supabase = supabase
_owner_id = owner_id


def _storage(request: Request) -> StorageGateway:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        storage = InMemoryStorageGateway()
    return storage


async def _service(
    supabase: AsyncClient = Depends(_supabase),
    storage: StorageGateway = Depends(_storage),
) -> FileService:
    yield FileService(supabase, storage)


@router.post("", response_model=FileAssetResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> FileAssetResponse:
    data = await file.read()
    row = await service.upload(
        owner_id,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type,
    )
    return FileAssetResponse.from_dict(row)


@router.get("", response_model=FileListResponse)
async def list_files(
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> FileListResponse:
    items = await service.list_for_owner(owner_id)
    return FileListResponse(
        items=[FileAssetResponse.from_dict(m) for m in items],
        total=len(items),
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> None:
    await service.delete(file_id, owner_id)


@router.get("/{file_id}/url", response_model=FileUrlResponse)
async def get_file_url(
    file_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> FileUrlResponse:
    """Return a short-lived (1 hour) signed URL for an owned file asset."""
    data = await service.signed_url(file_id, owner_id, expires_in=3600)
    return FileUrlResponse(**data)