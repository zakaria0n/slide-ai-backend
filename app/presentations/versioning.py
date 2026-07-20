"""Versioning helpers for presentations."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.presentation_version import PresentationVersionRepository
from app.generation.spec import PresentationSpec


def _spec_hash(spec: PresentationSpec) -> str:
    return json.dumps(spec.model_dump(), sort_keys=True)


async def snapshot_if_changed(
    session: AsyncSession,
    presentation_id: object,
    owner_id: object,
    spec: PresentationSpec,
    note: str = "auto-save",
) -> None:
    """Create a version snapshot only if the spec differs from the latest."""
    repo = PresentationVersionRepository(session)
    latest_hash = await repo.get_latest_spec_hash(presentation_id)  # type: ignore[arg-type]
    new_hash = _spec_hash(spec)

    if latest_hash == new_hash:
        return  # no change, skip snapshot

    from app.models.presentation_version import PresentationVersion
    version = PresentationVersion(
        presentation_id=presentation_id,  # type: ignore[arg-type]
        owner_id=owner_id,  # type: ignore[arg-type]
        spec=spec.model_dump(),
        version_note=note,
        slide_count=len(spec.slides),
    )
    session.add(version)
