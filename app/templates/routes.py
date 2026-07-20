"""Template routes.

- ``GET /templates``          list families
- ``GET /templates/suggest``   recommend family from query
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.templates.library import list_templates, TemplateFamily
from app.templates.selector import select_template

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateSlideResponse(BaseModel):
    layout: str
    purpose: str
    element_hints: list[str]


class TemplateResponse(BaseModel):
    name: str
    description: str
    slides: list[TemplateSlideResponse]

    @classmethod
    def from_family(cls, family: TemplateFamily) -> "TemplateResponse":
        return cls(
            name=family.name,
            description=family.description,
            slides=[
                TemplateSlideResponse(
                    layout=s.layout,
                    purpose=s.purpose,
                    element_hints=s.element_hints,
                )
                for s in family.slides
            ],
        )


class TemplateListResponse(BaseModel):
    templates: list[TemplateResponse]


class TemplateSuggestResponse(BaseModel):
    template: TemplateResponse


@router.get("", response_model=TemplateListResponse)
async def list_templates_endpoint() -> TemplateListResponse:
    """List all available template families."""
    families = list_templates()
    return TemplateListResponse(
        templates=[TemplateResponse.from_family(f) for f in families]
    )


@router.get("/suggest", response_model=TemplateSuggestResponse)
async def suggest_template(
    q: str = Query("", description="Prompt or topic to classify"),
) -> TemplateSuggestResponse:
    """Suggest a template family based on a query string."""
    family = select_template(q)
    return TemplateSuggestResponse(
        template=TemplateResponse.from_family(family)
    )
