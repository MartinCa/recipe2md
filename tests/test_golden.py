"""Golden-file tests: fixture HTML in, byte-exact expected Markdown out."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models import IngredientGroup, Recipe
from app.render import render
from app.scrape import ScrapeError, scrape

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"

FAKE_JPEG = b"FAKEJPEGBYTES"


def _scrape_fixture(name: str, url: str):
    html = (FIXTURES / name).read_text()
    return scrape(html, url)


@pytest.mark.parametrize(
    ("fixture", "url", "golden_name", "with_image"),
    [
        (
            "english_basic.html",
            "https://example.com/fluffy-pancakes",
            "english_basic.md",
            True,
        ),
        (
            "danish_boller.html",
            "https://example.com/boller-i-karry",
            "danish_boller.md",
            True,
        ),
        (
            "grouped_ingredients.html",
            "https://example.com/layered-chocolate-cake",
            "grouped_ingredients.md",
            False,
        ),
        (
            "no_image.html",
            "https://example.com/simple-tomato-soup",
            "no_image.md",
            False,
        ),
        (
            "imperial_units.html",
            "https://example.com/american-chocolate-chip-cookies",
            "imperial_units.md",
            False,
        ),
        (
            "microdata_directions_missing.html",
            "https://example.com/blondies",
            "microdata_directions_missing.md",
            False,
        ),
    ],
)
def test_render_matches_golden_file(
    fixture: str, url: str, golden_name: str, with_image: bool
) -> None:
    recipe = _scrape_fixture(fixture, url)
    if with_image:
        recipe.image = FAKE_JPEG

    files = render(recipe)

    md_paths = [path for path in files if path.endswith(".md")]
    assert len(md_paths) == 1
    actual_markdown = files[md_paths[0]].decode("utf-8")
    expected_markdown = (GOLDEN / golden_name).read_text()
    assert actual_markdown == expected_markdown

    if with_image:
        assert len(files) == 2
        image_path = next(path for path in files if path != md_paths[0])
        assert image_path.startswith("_attachments/")
        assert image_path.endswith(".jpg")
        assert files[image_path] == FAKE_JPEG
    else:
        assert len(files) == 1


def test_danish_site_gets_comma_decimals_converted() -> None:
    recipe = _scrape_fixture("danish_boller.html", "https://example.com/boller-i-karry")

    all_ingredients = [item for group in recipe.ingredient_groups for item in group.items]
    assert "1.5 spsk karry" in all_ingredients
    # A comma between digits is a decimal separator and must be gone; a comma
    # between words (an ordinary list separator, e.g. "løg, finthakket") stays.
    assert not any(re.search(r"\d,\d", item) for item in all_ingredients)
    assert any("løg, finthakket" in item for item in all_ingredients)


def test_imperial_units_are_detected_but_not_converted() -> None:
    recipe = _scrape_fixture(
        "imperial_units.html", "https://example.com/american-chocolate-chip-cookies"
    )

    assert recipe.needs_metric is True
    all_ingredients = [item for group in recipe.ingredient_groups for item in group.items]
    assert "2 cups all-purpose flour" in all_ingredients
    assert "1 lb butter, softened" in all_ingredients


def test_no_image_omits_the_embed_line_and_attachment() -> None:
    recipe = _scrape_fixture("no_image.html", "https://example.com/simple-tomato-soup")
    assert recipe.image is None

    files = render(recipe)
    assert not any(path.startswith("_attachments/") for path in files)
    markdown = next(content for path, content in files.items() if path.endswith(".md"))
    assert "![[" not in markdown.decode("utf-8")


def test_ingredient_groups_become_bold_subheadings() -> None:
    recipe = _scrape_fixture(
        "grouped_ingredients.html", "https://example.com/layered-chocolate-cake"
    )
    names = [group.name for group in recipe.ingredient_groups]
    assert names == ["Cake", "Frosting"]


def test_microdata_page_with_no_recipeinstructions_yields_empty_directions() -> None:
    # Regression test for smittenkitchen.com: its Jetpack recipe plugin marks up the
    # title, yield, time and each ingredient with itemprop attributes, but the
    # directions div carries no itemprop="recipeInstructions" (or any schema.org
    # signal) at all. recipe-scrapers' generic schema.org fallback has nothing to read
    # for directions in that case, so it correctly comes back empty rather than
    # guessing at which part of the page's freeform HTML is a cooking step -- this is
    # a genuine markup gap on the source site, not a scraper bug. app.pipeline turns
    # this into a "no directions found" warning so it's visible instead of silent.
    recipe = _scrape_fixture("microdata_directions_missing.html", "https://example.com/blondies")
    assert recipe.title == "Blondies, Infinitely Adaptable"
    assert any(group.items for group in recipe.ingredient_groups)
    assert recipe.directions == []


def test_page_with_no_title_or_ingredients_fails_to_scrape() -> None:
    html = (FIXTURES / "unparseable.html").read_text()
    with pytest.raises(ScrapeError):
        scrape(html, "https://example.com/not-a-recipe")


def test_rating_and_migrated_notes_are_rendered() -> None:
    recipe = Recipe(
        title="Soup",
        source_url="",
        ingredient_groups=[IngredientGroup(items=["1 onion"])],
        directions=["Simmer."],
        rating=4.5,
        notes=["Use stock."],
    )

    markdown = render(recipe)["Soup.md"].decode()

    assert "\nrating: 4.5\n" in markdown
    assert "## Notes\n\nUse stock.\n\n## Nutrition" in markdown
