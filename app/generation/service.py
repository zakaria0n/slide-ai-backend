"""Presentation generation orchestration.

:class:`GenerationService` ties together the stored presentation, the
specification provider, and the slide repository:

1. create a draft presentation owned by the caller,
2. ask the spec provider (always "Slide AI" to the caller) for a structured
   :class:`PresentationSpec`,
3. persist the spec on the presentation and each slide's content, then mark
   the deck ready with its slide count.

Failures roll back: a failed generation leaves no half-written deck. The
legacy ``SlideResponse`` (title/bullets/notes) is derived from the spec so
existing consumers keep working.
"""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProviderError, ValidationError
from app.db.repositories.presentation import PresentationRepository
from app.db.repositories.slide import SlideRepository
from app.generation.schemas import GenerationRequest
from app.generation.spec import SlideSpec
from app.generation.spec_provider import SpecProvider
from app.models.presentation import Presentation as PresentationModel
from app.models.slide import Slide


class GenerationService:
    """Owner-scoped generation workflow."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: SpecProvider,
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

        # 2. Generate the structured specification from the provider.
        try:
            spec = await self._provider.generate_spec(request)
        except ProviderError:
            # Roll back the draft so we don't leave a stuck "generating" deck.
            await self._presentations.delete(presentation)
            raise

        # 3. Persist the spec + slides and finalize the deck.
        await self._store_spec(presentation, spec, owner_id)
        presentation.slide_count = len(spec.slides)
        presentation.status = "ready"
        presentation.spec = spec.model_dump()
        saved = await self._presentations.update(presentation)
        return saved

    async def _store_spec(
        self, presentation: PresentationModel, spec: object, owner_id: UUID
    ) -> None:
        from app.generation.spec import PresentationSpec

        typed = spec if isinstance(spec, PresentationSpec) else PresentationSpec.model_validate(spec)
        for index, slide in enumerate(typed.slides):
            row = Slide(
                presentation_id=presentation.id,
                owner_id=owner_id,
                slide_index=index,
                content=json.dumps(_slide_to_legacy(slide)),
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


def _slide_to_legacy(slide: SlideSpec) -> dict:
    """Map a spec slide to the legacy Slide content (title/bullets/notes)."""
    title = ""
    bullets: list[str] = []
    notes = slide.notes
    for el in slide.elements:
        if getattr(el, "type", None) == "title" and not title:
            title = getattr(el, "text", "")
        elif getattr(el, "type", None) == "bullets":
            bullets.extend(getattr(el, "items", []))
    return {
        "title": title,
        "bullets": bullets,
        "notes": notes,
        "layout": slide.layout,
    }
