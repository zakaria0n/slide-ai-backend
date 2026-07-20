"""Presentation generation orchestration.

:class:`GenerationService` ties together the stored presentation, the
generation provider, and the slide repository:

1. create a draft presentation owned by the caller,
2. ask the provider for slides (always "Slide AI" to the caller),
3. persist each slide, then mark the deck ready with its slide count.

Failures roll back: a failed generation leaves no half-written deck.
"""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProviderError, ValidationError
from app.db.repositories.presentation import PresentationRepository
from app.db.repositories.slide import SlideRepository
from app.generation.provider import GenerationProvider
from app.generation.schemas import GenerationRequest, GenerationResult
from app.models.presentation import Presentation as PresentationModel
from app.models.slide import Slide


class GenerationService:
    """Owner-scoped generation workflow."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: GenerationProvider,
    ) -> None:
        self._presentations = PresentationRepository(session)
        self._slides = SlideRepository(session)
        self._provider = provider

    async def generate(
        self,
        owner_id: UUID,
        *,
        request: GenerationRequest,
    ) -> PresentationModel:
        # 1. Draft the presentation.
        title = self._derive_title(request.prompt)
        presentation = PresentationModel(
            owner_id=owner_id,
            title=title,
            description=request.prompt[:5000],
            slide_count=0,
            status="generating",
            theme=request.theme,
        )
        presentation = await self._presentations.add(presentation)

        # 2. Generate slides from the provider.
        try:
            result = await self._provider.generate(request)
        except ProviderError:
            # Roll back the draft so we don't leave a stuck "generating" deck.
            await self._presentations.delete(presentation)
            raise

        # 3. Persist slides and finalize the deck.
        await self._store_slides(presentation.id, owner_id, result)
        presentation.slide_count = len(result.slides)
        presentation.status = "ready"
        saved = await self._presentations.update(presentation)
        return saved

    async def _store_slides(
        self, presentation_id: UUID, owner_id: UUID, result: GenerationResult
    ) -> None:
        for index, slide in enumerate(result.slides):
            row = Slide(
                presentation_id=presentation_id,
                owner_id=owner_id,
                slide_index=index,
                content=json.dumps(slide.model_dump()),
            )
            await self._slides.add(row)

    @staticmethod
    def _derive_title(prompt: str) -> str:
        cleaned = " ".join(prompt.split()).strip()
        if not cleaned:
            raise ValidationError("A topic is required to generate")
        # Use the first sentence / phrase as the deck title.
        head = cleaned.split("\n")[0].split(". ")[0]
        if len(head) > 200:
            head = head[:197].rstrip() + "..."
        return head
