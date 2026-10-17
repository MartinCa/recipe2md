"""Bundle rendered recipe files into a single in-memory zip. Nothing touches disk."""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath


def _split(path: str) -> tuple[str, str, str]:
    """'_attachments/Title.jpg' -> ('_attachments/', 'Title', '.jpg')."""
    parsed = PurePosixPath(path)
    prefix = "" if parsed.parent == PurePosixPath(".") else f"{parsed.parent}/"
    return prefix, parsed.stem, parsed.suffix


def dedupe_stems(files: dict[str, bytes], used_stems: dict[str, int]) -> dict[str, bytes]:
    """Rename this recipe's files if its stem was already used elsewhere in the batch."""
    stems = {_split(path)[1] for path in files}
    if len(stems) != 1:
        raise ValueError(f"expected exactly one stem across a recipe's files, got {stems}")
    stem = next(iter(stems))

    count = used_stems.get(stem, 0)
    used_stems[stem] = count + 1
    if count == 0:
        return files

    # A recipe literally titled "Soup 1" must not collide with the renamed second "Soup".
    new_stem = f"{stem} {count}"
    while new_stem in used_stems:
        count += 1
        new_stem = f"{stem} {count}"
    used_stems[new_stem] = 1

    renamed = {}
    for path, content in files.items():
        prefix, _, suffix = _split(path)
        if suffix == ".md":
            # Keep the cover embed pointing at this recipe's renamed image.
            content = content.replace(f"![[{stem}.jpg]]".encode(), f"![[{new_stem}.jpg]]".encode())
        renamed[f"{prefix}{new_stem}{suffix}"] = content
    return renamed


def build_zip(rendered: list[dict[str, bytes]], errors: list[str]) -> bytes:
    """Merge each recipe's {path: bytes} into one zip, resolving stem collisions."""
    buffer = io.BytesIO()
    used_stems: dict[str, int] = {}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for files in rendered:
            for path, content in dedupe_stems(files, used_stems).items():
                archive.writestr(path, content)

        if errors:
            archive.writestr("_errors.txt", "\n".join(errors) + "\n")

    return buffer.getvalue()
