"""Image processing service wrapping rembg and Pillow utilities."""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

from .exceptions import BackgroundRemovalError, UnsupportedImageTypeError
from .utils import ensure_rgba, normalize_file_name, validate_extension

try:
    from PIL import Image, UnidentifiedImageError
except ImportError as exc:  # pragma: no cover - handled by raising on init
    Image = None  # type: ignore
    UnidentifiedImageError = RuntimeError  # type: ignore
    _pillow_import_error = exc
else:
    _pillow_import_error = None

try:  # pragma: no cover - optional dependency
    from rembg import new_session, remove as rembg_remove
except ImportError:  # pragma: no cover - handled when building default remover
    rembg_remove = None  # type: ignore
    new_session = None  # type: ignore

RemoverFunc = Callable[[bytes], "Image.Image" | bytes | bytearray]


@dataclass(slots=True)
class ImageMetadata:
    """Represents the processing state for a single image within a job."""

    source_path: str
    output_path: str | None
    normalized_name: str
    status: str = "pending"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "output_path": self.output_path,
            "normalized_name": self.normalized_name,
            "status": self.status,
            "error": self.error,
        }


@dataclass(slots=True)
class JobResult:
    """Represents the result for a batch processing job."""

    job_id: str
    status: str
    images: List[ImageMetadata] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "images": [image.to_dict() for image in self.images],
        }


class ImageProcessingService:
    """High-level service coordinating image background removal and storage."""

    def __init__(self, storage_root: str | Path, remover: RemoverFunc | None = None):
        if Image is None:  # pragma: no cover - defensive guard if Pillow missing
            raise ImportError("Pillow is required for ImageProcessingService") from _pillow_import_error

        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._remover = remover or self._build_default_remover()

    def process_batch(self, image_paths: Sequence[str | Path]) -> JobResult:
        """Process a batch of images, generating a unique job and metadata files."""

        resolved_paths = list(image_paths)
        job_id = uuid.uuid4().hex
        job_dir = self.storage_root / job_id
        output_dir = job_dir / "outputs"
        metadata_dir = job_dir / "metadata"

        output_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)

        results: List[ImageMetadata] = []
        used_names: set[str] = set()

        for index, path in enumerate(resolved_paths):
            metadata = self._process_single_image(path, output_dir, used_names, index)
            results.append(metadata)
            self._write_metadata_file(metadata_dir, metadata, index)

        job_status = self._derive_job_status(results)
        job_result = JobResult(job_id=job_id, status=job_status, images=results)
        self._write_job_summary(job_dir, job_result)
        return job_result

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _build_default_remover(self) -> RemoverFunc:
        if rembg_remove is None:  # pragma: no cover - dependency may be missing
            raise ImportError(
                "rembg is required unless a custom remover function is provided"
            )

        session = new_session() if new_session is not None else None

        def _remove(image_bytes: bytes) -> bytes:
            if session is not None:
                return rembg_remove(image_bytes, session=session)
            return rembg_remove(image_bytes)

        return _remove

    def _process_single_image(
        self,
        image_path: str | Path,
        output_dir: Path,
        used_names: set[str],
        index: int,
    ) -> ImageMetadata:
        path = Path(image_path)
        normalized_base = normalize_file_name(path)
        unique_name = self._build_unique_name(normalized_base, used_names, index)
        output_path = output_dir / f"{unique_name}.png"

        metadata = ImageMetadata(
            source_path=str(path),
            output_path=str(output_path),
            normalized_name=unique_name,
        )

        try:
            validate_extension(path)
            with Image.open(path) as image:
                rgba_image = ensure_rgba(image)
                remove_input = self._image_to_bytes(rgba_image)

            background_removed = self._remove_background(remove_input)
            self._save_image(background_removed, output_path)
            metadata.status = "completed"
        except (UnsupportedImageTypeError, FileNotFoundError, UnidentifiedImageError, OSError, BackgroundRemovalError) as exc:
            metadata.status = "failed"
            metadata.error = str(exc)
        except Exception as exc:  # pragma: no cover - unexpected guard
            metadata.status = "failed"
            metadata.error = f"Unexpected processing error: {exc}"

        return metadata

    def _remove_background(self, image_bytes: bytes) -> Image.Image:
        try:
            output = self._remover(image_bytes)
        except Exception as exc:  # pragma: no cover - remover specific
            raise BackgroundRemovalError("Background removal failed") from exc

        if isinstance(output, Image.Image):
            return ensure_rgba(output).copy()
        if isinstance(output, (bytes, bytearray)):
            with Image.open(io.BytesIO(output)) as img:
                converted = ensure_rgba(img)
                return converted.copy()

        raise BackgroundRemovalError(
            "Background removal function returned unsupported data type"
        )

    @staticmethod
    def _image_to_bytes(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _save_image(self, image: Image.Image, path: Path) -> None:
        ensure_rgba(image).save(path, format="PNG")

    @staticmethod
    def _build_unique_name(base: str, used_names: set[str], index: int) -> str:
        if base not in used_names:
            used_names.add(base)
            return base

        candidate = base
        counter = 1
        while candidate in used_names:
            candidate = f"{base}_{counter}"
            counter += 1
        used_names.add(candidate)
        return candidate

    @staticmethod
    def _derive_job_status(images: Iterable[ImageMetadata]) -> str:
        statuses = [metadata.status for metadata in images]
        if not statuses:
            return "completed"
        if all(status == "completed" for status in statuses):
            return "completed"
        if any(status == "completed" for status in statuses):
            return "partial"
        return "failed"

    @staticmethod
    def _write_metadata_file(metadata_dir: Path, metadata: ImageMetadata, index: int) -> None:
        filename = metadata.normalized_name or f"image_{index}"
        path = metadata_dir / f"{filename}.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(metadata.to_dict(), file, indent=2)

    @staticmethod
    def _write_job_summary(job_dir: Path, job_result: JobResult) -> None:
        summary_path = job_dir / "job.json"
        with summary_path.open("w", encoding="utf-8") as file:
            json.dump(job_result.to_dict(), file, indent=2)
