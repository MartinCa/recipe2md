"""Mealie migration: read every recipe from a Mealie instance's API, render, write to disk.

A CLI-only tool (see app/cli.py), not a route. Mealie's own JSON already carries
structured data, so this bypasses recipe-scrapers entirely and builds a Recipe
straight from the API response, then writes through the same render() everything
else uses.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import httpx
import isodate

from app.config import Settings
from app.images import process_image
from app.models import IngredientGroup, Recipe
from app.normalise import (
    contains_imperial_units,
    normalise_language,
    normalise_quantities,
    parse_servings,
)
from app.packaging import _dedupe
from app.render import render

logger = logging.getLogger(__name__)

_LEADING_INT = re.compile(r"\d+")


class MealieError(Exception):
    """Raised when the Mealie API can't be listed or read."""


async def list_slugs(client: httpx.AsyncClient) -> list[str]:
    """Every recipe slug in the instance, paging through GET /api/recipes."""
    slugs: list[str] = []
    page = 1
    while True:
        response = await client.get("/api/recipes", params={"page": page, "perPage": 50})
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") or []
        if not items:
            break
        slugs.extend(item["slug"] for item in items)
        if not payload.get("next"):
            break
        page += 1
    return slugs


async def fetch_recipe(client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
    response = await client.get(f"/api/recipes/{slug}")
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def to_recipe(data: dict[str, Any]) -> Recipe:
    """Map a GET /api/recipes/{slug} payload onto our Recipe model."""
    title = data.get("name")
    if not title:
        raise MealieError(f"recipe {data.get('slug')!r} has no name")

    ingredient_groups = _ingredient_groups(data.get("recipeIngredient") or [])
    directions = [
        normalise_quantities(text)
        for step in (data.get("recipeInstructions") or [])
        if (text := _step_text(step))
    ]
    nutrients = {key: str(value) for key, value in (data.get("nutrition") or {}).items() if value}
    all_text = [*(item for group in ingredient_groups for item in group.items), *directions]

    return Recipe(
        title=title,
        source_url=data.get("orgURL") or "",
        ingredient_groups=ingredient_groups,
        directions=directions,
        language=normalise_language(None),
        servings=parse_servings(data.get("recipeYield")) or _servings(data),
        time_minutes=_parse_minutes(data.get("totalTime")),
        description=data.get("description") or None,
        nutrients=nutrients,
        needs_metric=contains_imperial_units(all_text),
        rating=data.get("rating") or None,
        notes=_notes(data.get("notes") or []),
    )


def _servings(data: dict[str, Any]) -> int | None:
    """Fall back to Mealie's numeric ``recipeServings`` when ``recipeYield`` text is empty."""
    servings = data.get("recipeServings")
    return int(servings) if isinstance(servings, int | float) and servings >= 1 else None


def _step_text(step: dict[str, Any]) -> str:
    """A step's text, with its section title (Mealie's per-step ``title``) kept as a bold lead."""
    text = (step.get("text") or "").strip()
    title = (step.get("title") or "").strip()
    return f"**{title}** {text}" if text and title else text


def _notes(notes: list[dict[str, Any]]) -> list[str]:
    result = []
    for note in notes:
        text = (note.get("text") or "").strip()
        title = (note.get("title") or "").strip()
        if text:
            result.append(f"**{title}**\n{text}" if title else text)
    return result


def _ingredient_groups(items: list[dict[str, Any]]) -> list[IngredientGroup]:
    """Mealie marks a new ingredient section with a non-empty ``title`` on that item."""
    groups: list[IngredientGroup] = []
    current: IngredientGroup | None = None

    for item in items:
        title = (item.get("title") or "").strip()
        if title or current is None:
            current = IngredientGroup(name=title or None, items=[])
            groups.append(current)

        text = _ingredient_text(item)
        if text:
            current.items.append(normalise_quantities(text))

    return [group for group in groups if group.items]


def _ingredient_text(item: dict[str, Any]) -> str:
    """``display`` is empty on older Mealie versions; rebuild it from the structured parts."""
    display = (item.get("display") or "").strip()
    if display:
        return display

    quantity = item.get("quantity")
    parts = [
        f"{quantity:g}" if isinstance(quantity, int | float) and quantity else "",
        ((item.get("unit") or {}).get("name") or "") if quantity else "",
        (item.get("food") or {}).get("name") or "",
        item.get("note") or "",
    ]
    return (
        " ".join(part.strip() for part in parts if part.strip())
        or (item.get("originalText") or "").strip()
    )


def _parse_minutes(value: str | None) -> int | None:
    """Mealie stores time as either an ISO 8601 duration ('PT45M') or free text ('45 min')."""
    if not value:
        return None
    try:
        duration = isodate.parse_duration(value)
        return int(duration.total_seconds() // 60)
    except ValueError:  # covers isodate.ISO8601Error, which subclasses it
        pass
    match = _LEADING_INT.search(value)
    return int(match.group()) if match else None


def _image_path(data: dict[str, Any]) -> str | None:
    """Mealie serves every recipe's cover as WebP at a fixed path keyed by recipe id."""
    if data.get("image") and data.get("id"):
        return f"/api/media/recipes/{data['id']}/images/original.webp"
    return None


async def migrate_from_mealie(base_url: str, token: str, out_dir: Path, settings: Settings) -> int:
    """Render every recipe from a Mealie instance into out_dir. Returns the failure count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}", "User-Agent": settings.user_agent}
    failures = 0
    used_stems: dict[str, int] = {}

    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=settings.request_timeout
    ) as client:
        try:
            slugs = await list_slugs(client)
        except httpx.HTTPError as exc:
            raise MealieError(f"could not list recipes: {exc}") from exc

        for slug in slugs:
            try:
                data = await fetch_recipe(client, slug)
                recipe = to_recipe(data)

                image_path = _image_path(data)
                if image_path:
                    try:
                        response = await client.get(image_path)
                        response.raise_for_status()
                        recipe.image = process_image(
                            response.content,
                            max_edge=settings.image_max_edge,
                            quality=settings.image_quality,
                        )
                    except Exception as exc:  # a failed image fetch is not a failed migration
                        logger.info("image fetch failed for %s: %s", slug, exc)

                files = _dedupe(render(recipe), used_stems)
            except Exception:
                logger.exception("failed to migrate recipe %r", slug)
                failures += 1
                continue

            for relative_path, content in files.items():
                destination = out_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            logger.info("migrated %s", slug)

    return failures
