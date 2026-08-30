"""Presentation generation orchestration.

:class:`GenerationService` ties together the stored presentation and the
specification provider:

1. create a draft presentation owned by the caller,
2. ask the spec provider (always "Slide AI" to the caller) for a structured
   :class:`PresentationSpec`,
3. persist the spec on the presentation, then mark the deck ready with its
   slide count.

Failures are best-effort cleaned up: a failed generation leaves no
stuck "generating" deck.
"""
from __future__ import annotations

from uuid import UUID

from supabase import AsyncClient

import app.db as db
from app.core.exceptions import ProviderError, ValidationError
from app.generation.schemas import GenerationRequest
from app.generation.spec import PresentationSpec
from app.generation.spec_provider import SpecProvider


class GenerationService:
    """Owner-scoped generation workflow."""

    def __init__(
        self,
        client: AsyncClient,
        *,
        provider: SpecProvider,
    ) -> None:
        self._client = client
        self._provider = provider

    async def generate(
        self,
        owner_id: UUID,
        *,
        request: GenerationRequest,
    ) -> dict:
        # 1. Draft the presentation.
        title = self._derive_title(request.prompt)
        row = await db.create_presentation(
            self._client,
            owner_id=str(owner_id),
            title=title,
            description=request.prompt[:5000],
            slide_count=0,
            status="generating",
            theme=request.theme,
        )
        presentation_id = UUID(row["id"])

        # 2. Resolve a template when the caller didn't pick one, so the
        # keyword-based classifier still guides the deck structure.
        if not request.template_name:
            from app.templates.selector import select_template

            family = select_template(request.prompt)
            request = request.model_copy(update={"template_name": family.name})

        # 3. Generate the structured specification from the provider.
        try:
            spec = await self._provider.generate_spec(request)
        except (ProviderError, ValidationError):
            # Includes an invalid model selection — never leave a stuck
            # "generating" deck behind.
            await db.delete_presentation(self._client, presentation_id)
            raise

        # 4. Persist the spec and finalize the deck.
        saved = await db.update_presentation(
            self._client,
            presentation_id,
            spec=spec.model_dump(),
            slide_count=len(spec.slides),
            status="ready",
        )
        return saved  # type: ignore[return-value]

    @staticmethod
    def _derive_title(prompt: str) -> str:
        cleaned = " ".join(prompt.split()).strip()
        if not cleaned:
            raise ValidationError("A topic is required to generate")
        head = cleaned.split("\n")[0].split(". ")[0]
        if len(head) > 200:
            head = head[:197].rstrip() + "..."
        return head