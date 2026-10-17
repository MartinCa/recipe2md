"""Recipe -> {relative_path: bytes}.

This is the one structural rule the whole app hangs off: render() is a pure
function of a Recipe. Nothing here touches the network or the filesystem, and no
other module is allowed to generate Markdown -- not a route, not the CLI.

The output format is fixed by an existing Obsidian vault convention (the Recipe
View plugin keys off document position and list type, not just heading names) --
see the brief before changing anything here.
"""

from __future__ import annotations

import json
import re

from app.models import IngredientGroup, Recipe
from app.normalise import format_time, sanitise_filename

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def render(recipe: Recipe) -> dict[str, bytes]:
    """Return {relative_path: content} for one recipe: the .md and, maybe, its image."""
    stem = sanitise_filename(recipe.title)

    lines: list[str] = [*_frontmatter_lines(recipe), ""]

    # The plugin takes the first image not under a heading as the thumbnail, so it
    # must come before "## Ingredients" -- and a missing image means no line at all,
    # never a dead ``![[]]``.
    if recipe.image is not None:
        lines.append(f"![[{stem}.jpg]]")
        lines.append("")

    if recipe.description:
        lines.append(recipe.description)
        lines.append("")

    lines.extend(_ingredients_lines(recipe.ingredient_groups))
    lines.append("")
    lines.extend(_directions_lines(recipe.directions))
    lines.append("")
    lines.extend(_notes_lines(recipe.notes))
    lines.extend(_nutrition_lines(recipe.nutrients))

    markdown = "\n".join(lines).rstrip("\n") + "\n"

    files = {f"{stem}.md": markdown.encode("utf-8")}
    if recipe.image is not None:
        files[f"_attachments/{stem}.jpg"] = recipe.image
    return files


def _field(key: str, value: str) -> str:
    return f"{key}: {value}" if value else f"{key}:"


def _yaml_scalar(value: str) -> str:
    """Quote a frontmatter string only when a bare YAML scalar wouldn't round-trip."""
    needs_quoting = (
        value == ""
        or value != value.strip()
        or value[0] in "\"'[]{}#&*!|>%@`,"
        or ": " in value
        or value.endswith(":")
    )
    return json.dumps(value) if needs_quoting else value


def _frontmatter_lines(recipe: Recipe) -> list[str]:
    time_text = format_time(recipe.time_minutes, recipe.language)
    tags = ["recipe", *(["needs-metric"] if recipe.needs_metric else [])]

    lines = [
        "---",
        _field("source", _yaml_scalar(recipe.source_url)),
        _field("author", _yaml_scalar(recipe.author) if recipe.author else ""),
        _field("lang", recipe.language),
        _field("cuisine", _yaml_scalar(recipe.cuisine) if recipe.cuisine else ""),
        _field("servings", str(recipe.servings) if recipe.servings is not None else ""),
        _field("time", time_text or ""),
        _field("rating", f"{recipe.rating:g}" if recipe.rating else ""),
        "tags:",
        *(f"  - {tag}" for tag in tags),
        "---",
    ]
    return lines


def _ingredients_lines(groups: list[IngredientGroup]) -> list[str]:
    # Groups are bold text, never headings: an H2 inside Ingredients would end the section
    # as far as the plugin is concerned.
    lines = ["## Ingredients", ""]
    for index, group in enumerate(groups):
        if index > 0:
            lines.append("")
        if group.name:
            lines.append(f"**{group.name}**")
        lines.extend(f"- {item}" for item in group.items)
    return lines


def _directions_lines(directions: list[str]) -> list[str]:
    lines = ["## Directions", ""]
    lines.extend(f"{position}. {step}" for position, step in enumerate(directions, start=1))
    return lines


def _notes_lines(notes: list[str]) -> list[str]:
    """Where the user writes after cooking -- always present, empty unless notes were migrated."""
    lines = ["## Notes", ""]
    for note in notes:
        lines.extend([note, ""])
    return lines


def _nutrition_lines(nutrients: dict[str, str]) -> list[str]:
    lines = ["## Nutrition"]
    if not nutrients:
        return lines
    lines.append("")
    lines.append("| Nutrient | Quantity |")
    lines.append("| -------- | -------- |")
    lines.extend(f"| {_prettify_nutrient_key(key)} | {value} |" for key, value in nutrients.items())
    return lines


def _prettify_nutrient_key(key: str) -> str:
    """schema.org's camelCase nutrition keys ('fatContent') -> table labels ('Fat')."""
    if key.endswith("Content"):
        key = key[: -len("Content")]
    words = _CAMEL_BOUNDARY.sub(" ", key)
    return words[:1].upper() + words[1:] if words else words
