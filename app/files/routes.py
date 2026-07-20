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
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.exceptions import UnauthorizedError
from app.db.dependencies import Database
from app.files.schemas import FileAssetResponse, FileListResponse
from app.files.service import FileService
from app.files.storage import InMemoryStorageGateway, StorageGateway

router = APIRouter(prefix="/files", tags=["files"])

_bearer = HTTPBearer(auto_error=False)


def _extract_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Missing authentication token")
    return creds.credentials


def _db(request: Request) -> Database:
    return request.app.state.db


async def _owner_id(request: Request, token: str = Depends(_extract_token)) -> UUID:
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        raise UnauthorizedError("Authentication is not configured")
    return verifier.user_id(token)


def _storage(request: Request) -> StorageGateway:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        storage = InMemoryStorageGateway()
    return storage


async def _service(
    request: Request,
    db: Database = Depends(_db),
    storage: StorageGateway = Depends(_storage),
) -> FileService:
    session = db.session_factory()
    try:
        yield FileService(session, storage)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@router.post("", response_model=FileAssetResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> FileAssetResponse:
    data = await file.read()
    created = await service.upload(
        owner_id,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type,
    )
    return FileAssetResponse.from_model(created)


@router.get("", response_model=FileListResponse)
async def list_files(
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> FileListResponse:
    items = await service.list_for_owner(owner_id)
    return FileListResponse(
        items=[FileAssetResponse.from_model(m) for m in items],
        total=len(items),
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: UUID,
    owner_id: UUID = Depends(_owner_id),
    service: FileService = Depends(_service),
) -> None:
    await service.delete(file_id, owner_id)
