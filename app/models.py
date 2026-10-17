"""Data shapes shared across scraping, rendering, and the web layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IngredientGroup:
    """One ingredient sub-list. ``name`` is ``None`` for an unnamed/default group."""

    items: list[str]
    name: str | None = None


@dataclass
class Recipe:
    """A scraped recipe, already normalised, ready to be rendered to Markdown."""

    title: str
    source_url: str
    ingredient_groups: list[IngredientGroup]
    directions: list[str]
    author: str | None = None
    language: str = "en"
    cuisine: str | None = None
    servings: int | None = None
    time_minutes: int | None = None
    description: str | None = None
    nutrients: dict[str, str] = field(default_factory=dict)
    rating: float | None = None
    notes: list[str] = field(default_factory=list)
    """Pre-existing notes (e.g. migrated from Mealie); scraped recipes leave this empty."""
    needs_metric: bool = False
    image_url: str | None = None
    image: bytes | None = None
    """Processed (JPEG, resized, EXIF-stripped) image bytes, if a cover image was fetched."""


@dataclass
class ScrapeOutcome:
    """The result of processing one URL: a rendered recipe, or why it failed."""

    url: str
    files: dict[str, bytes] | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
