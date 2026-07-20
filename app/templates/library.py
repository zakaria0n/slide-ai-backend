"""Template families for structured slide generation.

Each family defines a sequence of slides with layout hints so the spec
generator (or template override) can produce a coherent deck structure.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TemplateSlide:
    layout: str
    purpose: str
    element_hints: list[str] = field(default_factory=list)


@dataclass
class TemplateFamily:
    name: str
    description: str
    classify_keywords: list[str] = field(default_factory=list)
    slides: list[TemplateSlide] = field(default_factory=list)


TEMPLATES: list[TemplateFamily] = [
    TemplateFamily(
        name="startup_pitch",
        description="Standard investor pitch deck structure",
        classify_keywords=["startup", "pitch", "investor", "funding", "venture", "series", "seed", "raise"],
        slides=[
            TemplateSlide("hero", "Cover", ["title", "subtitle"]),
            TemplateSlide("section", "Problem", ["title", "paragraph"]),
            TemplateSlide("cards", "Solution", ["title", "cards"]),
            TemplateSlide("statistics", "Market / Traction", ["title", "statistics"]),
            TemplateSlide("comparison", "Competition", ["title", "comparison"]),
            TemplateSlide("team", "Team", ["title", "team"]),
            TemplateSlide("pricing", "Business Model", ["title", "pricing"]),
            TemplateSlide("timeline", "Roadmap", ["title", "timeline"]),
            TemplateSlide("cta", "Ask / CTA", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Thank You", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="education",
        description="Educational lecture or course overview",
        classify_keywords=["education", "lecture", "course", "lesson", "teaching", "academic", "university", "school", "training"],
        slides=[
            TemplateSlide("hero", "Title Slide", ["title", "subtitle"]),
            TemplateSlide("agenda", "Outline", ["title", "agenda"]),
            TemplateSlide("title", "Learning Objectives", ["title", "bullets"]),
            TemplateSlide("title", "Key Concept 1", ["title", "paragraph"]),
            TemplateSlide("image-left", "Visual Explanation", ["title", "image", "paragraph"]),
            TemplateSlide("bullets", "Key Points", ["title", "bullets"]),
            TemplateSlide("statistics", "Data & Evidence", ["title", "statistics"]),
            TemplateSlide("quote", "Expert Quote", ["title", "quote"]),
            TemplateSlide("conclusion", "Summary", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Q&A", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="finance",
        description="Financial report or earnings deck",
        classify_keywords=["finance", "financial", "earnings", "revenue", "profit", "budget", "quarterly", "annual report", "fiscal"],
        slides=[
            TemplateSlide("hero", "Report Title", ["title", "subtitle"]),
            TemplateSlide("statistics", "Key Metrics", ["title", "statistics"]),
            TemplateSlide("chart", "Revenue Trend", ["title", "chart"]),
            TemplateSlide("table", "Financial Summary", ["title", "table"]),
            TemplateSlide("comparison", "YoY Comparison", ["title", "comparison"]),
            TemplateSlide("cards", "Segment Breakdown", ["title", "cards"]),
            TemplateSlide("timeline", "Historical Performance", ["title", "timeline"]),
            TemplateSlide("swot", "SWOT Analysis", ["title", "swot"]),
            TemplateSlide("conclusion", "Outlook", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Thank You", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="medical",
        description="Medical research or clinical presentation",
        classify_keywords=["medical", "clinical", "health", "diagnosis", "treatment", "research", "patient", "drug", "therapy"],
        slides=[
            TemplateSlide("hero", "Study Title", ["title", "subtitle"]),
            TemplateSlide("bullets", "Background", ["title", "bullets"]),
            TemplateSlide("title", "Objective", ["title", "paragraph"]),
            TemplateSlide("process", "Methodology", ["title", "process"]),
            TemplateSlide("statistics", "Results", ["title", "statistics"]),
            TemplateSlide("table", "Data Summary", ["title", "table"]),
            TemplateSlide("comparison", "Treatment Groups", ["title", "comparison"]),
            TemplateSlide("quote", "Conclusion", ["title", "quote"]),
            TemplateSlide("conclusion", "Implications", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Thank You", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="marketing",
        description="Marketing campaign or brand strategy",
        classify_keywords=["marketing", "campaign", "brand", "advertising", "social media", "content strategy", "growth", "audience"],
        slides=[
            TemplateSlide("hero", "Campaign Overview", ["title", "subtitle"]),
            TemplateSlide("statistics", "Market Landscape", ["title", "statistics"]),
            TemplateSlide("cards", "Audience Segments", ["title", "cards"]),
            TemplateSlide("process", "Strategy Framework", ["title", "process"]),
            TemplateSlide("gallery", "Creative Assets", ["title", "gallery"]),
            TemplateSlide("timeline", "Campaign Timeline", ["title", "timeline"]),
            TemplateSlide("comparison", "Competitor Analysis", ["title", "comparison"]),
            TemplateSlide("pricing", "Budget Allocation", ["title", "pricing"]),
            TemplateSlide("cta", "Call to Action", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Thank You", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="product",
        description="Product launch or feature demo deck",
        classify_keywords=["product", "launch", "feature", "release", "update", "demo", "prototype", "mvp", "roadmap"],
        slides=[
            TemplateSlide("hero", "Product Title", ["title", "subtitle"]),
            TemplateSlide("image-left", "Product Overview", ["title", "image", "paragraph"]),
            TemplateSlide("cards", "Key Features", ["title", "cards"]),
            TemplateSlide("process", "How It Works", ["title", "process"]),
            TemplateSlide("comparison", "Before / After", ["title", "comparison"]),
            TemplateSlide("statistics", "Performance Metrics", ["title", "statistics"]),
            TemplateSlide("timeline", "Development Timeline", ["title", "timeline"]),
            TemplateSlide("pricing", "Pricing Plans", ["title", "pricing"]),
            TemplateSlide("cta", "Get Started", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Thank You", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="research",
        description="Research findings or academic paper presentation",
        classify_keywords=["research", "paper", "study", "findings", "hypothesis", "experiment", "analysis", "publication"],
        slides=[
            TemplateSlide("hero", "Paper Title", ["title", "subtitle"]),
            TemplateSlide("bullets", "Abstract / Introduction", ["title", "bullets"]),
            TemplateSlide("title", "Literature Review", ["title", "paragraph"]),
            TemplateSlide("process", "Methodology", ["title", "process"]),
            TemplateSlide("statistics", "Results", ["title", "statistics"]),
            TemplateSlide("table", "Data Tables", ["title", "table"]),
            TemplateSlide("quote", "Discussion", ["title", "quote"]),
            TemplateSlide("conclusion", "Conclusions", ["title", "paragraph"]),
            TemplateSlide("bullets", "Future Work", ["title", "bullets"]),
            TemplateSlide("thank-you", "Questions", ["title", "subtitle"]),
        ],
    ),
    TemplateFamily(
        name="generic",
        description="General purpose presentation",
        classify_keywords=[],
        slides=[
            TemplateSlide("hero", "Title", ["title", "subtitle"]),
            TemplateSlide("title", "Overview", ["title", "paragraph"]),
            TemplateSlide("bullets", "Key Points", ["title", "bullets"]),
            TemplateSlide("cards", "Details", ["title", "cards"]),
            TemplateSlide("statistics", "Data", ["title", "statistics"]),
            TemplateSlide("quote", "Highlight", ["title", "quote"]),
            TemplateSlide("conclusion", "Summary", ["title", "paragraph"]),
            TemplateSlide("thank-you", "Thank You", ["title", "subtitle"]),
        ],
    ),
]


def list_templates() -> list[TemplateFamily]:
    return TEMPLATES


def get_template(name: str) -> TemplateFamily | None:
    for t in TEMPLATES:
        if t.name == name:
            return t
    return None
