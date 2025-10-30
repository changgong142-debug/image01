from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


_filename_strip_re = re.compile(r"[^A-Za-z0-9._-]+")


def secure_filename(filename: str) -> str:
    """Return a filename safe for storing on disk."""
    name = Path(filename).name
    if not name:
        return "file"
    name = _filename_strip_re.sub("_", name)
    return name or "file"


def unique_filename(existing: Iterable[str], desired: str) -> str:
    base = Path(desired)
    stem = base.stem
    suffix = base.suffix
    candidate = desired
    counter = 1
    existing_set = set(existing)
    while candidate in existing_set:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate
