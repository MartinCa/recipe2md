# recipe2md

A self-hosted web app that turns a recipe URL -- or pasted HTML, for sites that
block server-side fetches -- into Obsidian-ready Markdown, delivered as a zip.

It replaces the URL-import half of [Mealie](https://mealie.io) with something
that emits plain Markdown matching an existing Obsidian recipe vault, without
running a recipe manager: no database, no accounts, no vault writes. Give it a
URL (or several), get back a zip of `.md` files and their cover images that
extracts straight over your vault's `Recipes/` folder.

There is no authentication: put it behind whatever auth proxy you already run.

## Quick start

```bash
docker run --rm -p 8080:8080 ghcr.io/martinca/recipe2md:latest
```

Then open <http://localhost:8080>, paste in a recipe URL (or several, one per
line), and download the zip.

A ready-to-edit [`compose.yaml`](compose.yaml) is included.

### Image tags

Images are published to GHCR when a GitHub release is published, for
`linux/amd64` and `linux/arm64`:

| Tag | Moves | Use it when |
| --- | --- | --- |
| `latest` | every non-prerelease release | you want the newest version |
| `1` | minor/patch releases within that major (only once `v1.0.0` has shipped) | you want a stable major series |
| `1.2` | patch releases within that minor | you want fixes but no feature jumps |
| `1.2.3` | never | you want to pin exactly |
| `sha-<commit>` | never | you need to pin to one commit |

Prereleases (`v1.2.3-rc.1`) publish under their own version tag and do not move
`latest`.

## How it works

1. Paste one or more recipe URLs into the form.
2. recipe2md fetches each page (or parses the HTML you pasted), scrapes it with
   [recipe-scrapers](https://github.com/hhursev/recipe-scrapers) -- which
   understands hundreds of recipe sites by name, and falls back to generic
   schema.org `Recipe` markup for everything else -- and normalises quantities,
   units, and the filename.
3. Every successfully scraped recipe becomes a Markdown file (see
   [Markdown output](#markdown-output) below) plus, if a cover image was
   fetched, a resized/re-encoded JPEG.
4. Everything is zipped in memory and sent back as a download. The container
   never writes to disk, which is why `read_only: true` works in the compose
   file.

### The pasted-HTML path

Some sites (Cloudflare-protected ones especially) block the server-side fetch.
For those, open the recipe in your own browser, expand **Paste HTML instead**
on the form, and paste in `document.documentElement.outerHTML` -- not
view-source, since many recipe sites render their content with JavaScript
after the page loads. A bookmarklet on the form copies it to your clipboard in
one click. Pasted HTML is only valid together with exactly one URL.

### Batches and partial failures

Submitting several URLs scrapes them concurrently (bounded by
`SCRAPE_CONCURRENCY`, so this doesn't hammer someone else's server). A failure
on one URL never aborts the batch: as long as at least one recipe succeeds,
you get a zip containing every recipe that worked, plus a `_errors.txt`
listing the URL and reason for anything that didn't -- including a cover image
that failed to fetch (403s are common; the original image URL is included so
you can grab it by hand). If every URL fails, the form re-renders with the
errors and your input -- including any pasted HTML -- preserved.

## Markdown output

The output format is fixed to match an existing Obsidian vault convention: the
[Recipe View](https://github.com/mgmeyers/obsidian-recipe-view) plugin keys
off document position and list type, not just heading names.

````markdown
---
source: https://example.com/boller-i-karry
author: Example Author
lang: da
cuisine: dansk
servings: 4
time: 45 min
rating:
tags:
  - recipe
---

![[Boller i Karry.jpg]]

Optional description from the scraper.

## Ingredients

**Boller**
- 500 g hakket svinekød
- 1 løg, finthakket

**Sauce**
- 3 dl kokosmælk
- 1.5 spsk karry

## Directions

1. Rør farsen sammen og form små boller.
2. Kog bollerne i letsaltet vand i 10 min.

## Notes

## Nutrition

| Nutrient | Quantity |
| -------- | -------- |
| Calories | 420 kcal |
````

A few rules worth knowing if a recipe looks unexpected:

- **No image** means no `![[...]]` line at all, never a dead embed.
- **Ingredients are plain bullets**, never `- [ ]` checkboxes -- the plugin
  adds its own cross-out, and checkboxes conflict with that.
- **Decimal separator is always a dot.** `1,5 dl` becomes `1.5 dl`, and
  fractions (`½`, `1 1/2`, ...) become decimals too -- the plugin's scaling
  parser silently skips comma decimals, so a doubled recipe would come out
  wrong with no error.
- **Imperial units are detected, not converted.** Cup-to-gram conversion is
  ingredient-dependent and lossy, so a recipe using cups, oz, lb, or °F gets a
  `needs-metric` tag instead of a guessed conversion. Convert by hand.
- **`## Notes` is always present and always empty** -- it's where you write
  after cooking.

### Zip layout

```
recipes-20260816-143022.zip
├── Boller i Karry.md
├── Gochujang Caramel Cookies.md
├── _attachments/
│   ├── Boller i Karry.jpg
│   └── Gochujang Caramel Cookies.jpg
└── _errors.txt          (only when something failed)
```

Extract it straight over your vault's `Recipes/` folder. Name collisions
within one zip (two recipes with the same title) get ` 1`, ` 2` appended to
the stem, keeping the Markdown file and its image in sync.

## Configuration

Everything is configured with environment variables; there is no `.env` file
in the image.

| Variable | Default | Description |
| --- | --- | --- |
| `MAX_HTML_BYTES` | `5242880` | Reject larger pastes and fetched pages (5 MiB). |
| `MAX_URLS_PER_BATCH` | `25` | Bound one request. |
| `REQUEST_TIMEOUT` | `20` | Per-request timeout in seconds. |
| `SCRAPE_CONCURRENCY` | `4` | Parallel scrapes per batch. |
| `USER_AGENT` | `recipe2md/<version>` | Sent on every outbound fetch. |
| `IMAGE_MAX_EDGE` | `1600` | Long-edge cap for cover images, in pixels. |
| `IMAGE_QUALITY` | `85` | JPEG quality used when re-encoding cover images. |
| `ALLOW_PRIVATE_URLS` | `false` | Disable the SSRF guard. Only enable this if you intend to scrape hosts on your own network. |
| `LOG_LEVEL` | `INFO` | Python log level. |

`HOST` and `PORT` are read by the container entrypoint, not the app --
running uvicorn yourself means passing `--host`/`--port` directly.

### The SSRF guard

recipe2md fetches whatever URL you give it, from inside your network. Treat
every URL as hostile input: before every request (including the initial one
and every redirect hop, capped at 5), it resolves the hostname and rejects
loopback, link-local, RFC1918, RFC4193, and `0.0.0.0/8` addresses, unless
`ALLOW_PRIVATE_URLS=true`. The same guard covers cover-image fetches.

## HTTP API

| Route | Purpose |
| --- | --- |
| `GET /` | The form. |
| `POST /scrape` | Scrape, render, and return a zip (`application/x-www-form-urlencoded`, fields `urls` and `html`). |
| `GET /healthz` | `{"status": "ok"}`. |
| `/static/*` | CSS/JS. |

## Command line

Two commands live outside the web app, sharing the same rendering pipeline as
`POST /scrape`:

```bash
# Scrape one or more URLs straight to a directory -- handy for a quick check
# without going through the browser.
uv run python -m app.cli scrape https://example.com/a-recipe --out ./out

# Migrate every recipe out of a Mealie instance. Reads GET /api/recipes for
# slugs and GET /api/recipes/{slug} for detail, mapping orgURL -> source,
# recipeYield -> servings, and totalTime -> time.
uv run python -m app.cli mealie-migrate https://mealie.example.com \
  --token "$MEALIE_API_TOKEN" --out ./out
```

Mealie's own asset-serving path varies by version, so image migration only
picks up cover images whose `image` field is already an absolute URL; anything
else is left for you to re-attach by hand.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest --cov
uv run uvicorn app.main:app --reload
```

Tests never touch the network -- every fetch is mocked with
[respx](https://lundberg.github.io/respx/), and golden-file tests in
`tests/golden/` assert exact-string equality against fixture HTML in
`tests/fixtures/`.

### Git hooks

Local hooks are managed by [lefthook](https://lefthook.dev/) from the shared
[`MartinCa/lefthook-configs`](https://github.com/MartinCa/lefthook-configs)
fragments pinned at `v2.0.0` in `lefthook.yml`. Install once per clone:

```bash
uv tool install lefthook@2.1.12  # standalone binary into uv's tool bin dir (default ~/.local/bin)
lefthook install                 # idempotent, safe to re-run
```

Pre-commit runs `uvx ruff check --fix` and `uvx ruff format` on staged Python
(re-staging fixes), a `betterleaks` secret scan of the staged diff, and a
`zizmor` audit of staged workflow files; commit-msg enforces Conventional
Commits. `lefthook`, `betterleaks`, and `zizmor` must be on `PATH`, and
`LEFTHOOK=0 git commit` skips the hooks as a last resort. See `AGENTS.md` for
the exact hooks-vs-CI enforcement split.

### Layout

```
app/
├── main.py        FastAPI app factory and routes
├── cli.py         The scrape smoke test and the Mealie migration command
├── config.py      pydantic-settings
├── models.py      Recipe, ScrapeOutcome
├── scrape.py      recipe-scrapers wrapper
├── normalise.py   decimals, fractions, units, language, filenames
├── render.py      Recipe -> {path: bytes} -- the one structural rule
├── images.py      fetch, resize, strip EXIF
├── fetching.py    URL fetch with the SSRF guard
├── mealie.py      Mealie API client and JSON-to-Recipe mapping
├── packaging.py   dict of files -> zip bytes
├── pipeline.py    per-URL orchestration shared by the route and the CLI
├── static/
└── templates/
```

`render()` is a pure function of a `Recipe` and is the only thing allowed to
generate Markdown -- not a route, not the CLI. Everything else exists to
either build a `Recipe` or consume `render()`'s output.

## License

MIT
