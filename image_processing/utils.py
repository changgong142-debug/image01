"""Utility helpers for the image processing service."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .exceptions import UnsupportedImageTypeError

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - handled by raising on use
    Image = None  # type: ignore
    _import_error = exc
else:
    _import_error = None

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _ensure_pillow_installed() -> None:
    if Image is None:  # pragma: no cover - defensive programming
        raise ImportError("Pillow is required to use image processing utilities") from _import_error


def normalize_file_name(path: str | Path) -> str:
    """Normalize an arbitrary file path or name into a filesystem friendly stem.

    The result is lowercase, stripped of leading/trailing underscores, and only
    contains ASCII letters, numbers, hyphens, and underscores.
    """

    stem = Path(path).stem
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_").lower()
    return normalized or "image"


def validate_extension(path: str | Path, allowed_extensions: Iterable[str] | None = None) -> str:
    """Validate that the path has an allowed extension and return it.

    Raises
    ------
    UnsupportedImageTypeError
        If the file extension is not in the allowed set.
    """

    extensions = {ext.lower() for ext in (allowed_extensions or ALLOWED_EXTENSIONS)}
    suffix = Path(path).suffix.lower()
    if suffix not in extensions:
        allowed = ", ".join(sorted(extensions))
        raise UnsupportedImageTypeError(
            f"Unsupported file extension '{suffix}'. Allowed extensions: {allowed}"
        )
    return suffix


def ensure_rgba(image: "Image.Image") -> "Image.Image":
    """Ensure that a Pillow image is in RGBA mode."""

    _ensure_pillow_installed()
    if image.mode == "RGBA":
        return image
    return image.convert("RGBA")
