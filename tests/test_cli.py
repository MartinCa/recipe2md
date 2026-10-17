"""Tests for the CLI: the scrape smoke test and the Mealie migration subcommand."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.cli import _build_parser, main
from tests.conftest import FIXTURES


def _fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_build_parser_parses_scrape_args() -> None:
    args = _build_parser().parse_args(
        ["scrape", "https://a.example.com", "https://b.example.com", "--out", "somewhere"]
    )
    assert args.command == "scrape"
    assert args.urls == ["https://a.example.com", "https://b.example.com"]
    assert args.out == Path("somewhere")


def test_build_parser_parses_mealie_migrate_args() -> None:
    args = _build_parser().parse_args(
        ["mealie-migrate", "https://mealie.example.com", "--token", "secret", "--out", "out-dir"]
    )
    assert args.command == "mealie-migrate"
    assert args.base_url == "https://mealie.example.com"
    assert args.token == "secret"
    assert args.out == Path("out-dir")


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args([])


@respx.mock
def test_main_scrape_writes_files_and_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")  # skip real DNS; respx mocks the HTTP layer
    respx.get("https://example.com/simple-tomato-soup").mock(
        return_value=httpx.Response(200, text=_fixture_html("no_image.html"))
    )

    exit_code = main(["scrape", "https://example.com/simple-tomato-soup", "--out", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "Simple Tomato Soup.md").exists()


@respx.mock
def test_main_scrape_returns_one_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")
    respx.get("https://example.com/broken").mock(return_value=httpx.Response(500))

    exit_code = main(["scrape", "https://example.com/broken", "--out", str(tmp_path)])

    assert exit_code == 1


@respx.mock
def test_main_mealie_migrate_writes_files_and_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")
    respx.get("https://mealie.example.com/api/recipes", params={"page": "1", "perPage": "50"}).mock(
        return_value=httpx.Response(200, json={"items": [{"slug": "soup"}], "next": None})
    )
    respx.get("https://mealie.example.com/api/recipes/soup").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Soup",
                "recipeIngredient": [{"title": "", "display": "1 onion"}],
                "recipeInstructions": [{"text": "Simmer."}],
            },
        )
    )

    exit_code = main(
        [
            "mealie-migrate",
            "https://mealie.example.com",
            "--token",
            "secret",
            "--out",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "Soup.md").exists()


@respx.mock
def test_main_mealie_migrate_reports_failure_when_the_api_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")
    respx.get("https://mealie.example.com/api/recipes", params={"page": "1", "perPage": "50"}).mock(
        return_value=httpx.Response(500)
    )

    exit_code = main(
        [
            "mealie-migrate",
            "https://mealie.example.com",
            "--token",
            "secret",
            "--out",
            str(tmp_path),
        ]
    )

    assert exit_code == 1


def test_main_mealie_migrate_requires_a_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEALIE_API_TOKEN", raising=False)
    args = ["mealie-migrate", "https://mealie.example.com", "--out", str(tmp_path)]

    assert main(args) == 1
