"""Unit tests for packaging.py: zip layout and stem-collision handling."""

from __future__ import annotations

import zipfile
from io import BytesIO

from app.packaging import build_zip


def _names(zip_bytes: bytes) -> set[str]:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        return set(archive.namelist())


def test_build_zip_writes_each_recipes_files() -> None:
    rendered = [
        {"Recipe One.md": b"one"},
        {"Recipe Two.md": b"two", "_attachments/Recipe Two.jpg": b"jpeg"},
    ]

    zip_bytes = build_zip(rendered, errors=[])

    assert _names(zip_bytes) == {
        "Recipe One.md",
        "Recipe Two.md",
        "_attachments/Recipe Two.jpg",
    }


def test_build_zip_omits_errors_file_when_nothing_failed() -> None:
    zip_bytes = build_zip([{"Recipe.md": b"x"}], errors=[])
    assert "_errors.txt" not in _names(zip_bytes)


def test_build_zip_includes_errors_file_when_something_failed() -> None:
    zip_bytes = build_zip(
        [{"Recipe.md": b"x"}], errors=["https://example.com/bad: could not fetch page"]
    )

    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        assert "_errors.txt" in archive.namelist()
        content = archive.read("_errors.txt").decode("utf-8")
        assert "https://example.com/bad: could not fetch page" in content


def test_build_zip_deduplicates_colliding_stems() -> None:
    rendered = [
        {"Cookies.md": b"first", "_attachments/Cookies.jpg": b"first-jpg"},
        {"Cookies.md": b"second", "_attachments/Cookies.jpg": b"second-jpg"},
        {"Cookies.md": b"third"},
    ]

    zip_bytes = build_zip(rendered, errors=[])

    names = _names(zip_bytes)
    assert names == {
        "Cookies.md",
        "_attachments/Cookies.jpg",
        "Cookies 1.md",
        "_attachments/Cookies 1.jpg",
        "Cookies 2.md",
    }

    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        assert archive.read("Cookies.md") == b"first"
        assert archive.read("Cookies 1.md") == b"second"
        assert archive.read("Cookies 2.md") == b"third"


def test_colliding_stem_rewrites_the_cover_embed() -> None:
    first = {"Soup.md": b"![[Soup.jpg]]\n", "_attachments/Soup.jpg": b"a"}
    second = {"Soup.md": b"![[Soup.jpg]]\n", "_attachments/Soup.jpg": b"b"}

    with zipfile.ZipFile(BytesIO(build_zip([first, second], []))) as archive:
        assert archive.read("Soup 1.md") == b"![[Soup 1.jpg]]\n"
