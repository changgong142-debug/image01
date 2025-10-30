from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from image_processing import ImageProcessingService


def _image_to_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def transparent_remover(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image_rgba = image.convert("RGBA")
        transparent = Image.new("RGBA", image_rgba.size, (0, 0, 0, 0))
    return _image_to_bytes(transparent)


def failing_remover(image_bytes: bytes) -> bytes:
    raise ValueError("simulated failure")


def create_sample_jpg(path: Path, size: tuple[int, int] = (10, 10)) -> Path:
    image = Image.new("RGB", size, (255, 0, 0))
    image_path = path / "sample.jpg"
    image.save(image_path, format="JPEG")
    return image_path


def test_jpg_converted_to_transparent_png(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    service = ImageProcessingService(storage_root=storage_root, remover=transparent_remover)
    jpg_path = create_sample_jpg(tmp_path)

    job_result = service.process_batch([jpg_path])

    assert job_result.status == "completed"
    assert job_result.job_id
    assert len(job_result.images) == 1

    metadata = job_result.images[0]
    assert metadata.status == "completed"
    assert metadata.output_path is not None
    output_path = Path(metadata.output_path)
    assert output_path.exists()
    assert output_path.suffix.lower() == ".png"

    with Image.open(output_path) as processed:
        assert processed.mode == "RGBA"
        assert processed.size == (10, 10)
        alpha_channel = processed.getchannel("A")
        assert alpha_channel.getextrema() == (0, 0)

    job_dir = storage_root / job_result.job_id
    job_summary_path = job_dir / "job.json"
    metadata_file = job_dir / "metadata" / f"{metadata.normalized_name}.json"

    with job_summary_path.open("r", encoding="utf-8") as fh:
        job_summary = json.load(fh)
    assert job_summary["status"] == "completed"
    assert job_summary["images"][0]["status"] == "completed"

    with metadata_file.open("r", encoding="utf-8") as fh:
        metadata_json = json.load(fh)
    assert metadata_json["output_path"] == metadata.output_path
    assert metadata_json["status"] == "completed"


def test_background_removal_failure_updates_metadata(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    service = ImageProcessingService(storage_root=storage_root, remover=failing_remover)
    jpg_path = create_sample_jpg(tmp_path)

    job_result = service.process_batch([jpg_path])

    assert job_result.status == "failed"
    metadata = job_result.images[0]
    assert metadata.status == "failed"
    assert "Background removal failed" in metadata.error

    job_dir = storage_root / job_result.job_id
    metadata_file = job_dir / "metadata" / f"{metadata.normalized_name}.json"
    with metadata_file.open("r", encoding="utf-8") as fh:
        metadata_json = json.load(fh)
    assert metadata_json["status"] == "failed"
    assert "Background removal failed" in metadata_json["error"]


def test_invalid_extension_is_rejected(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    service = ImageProcessingService(storage_root=storage_root, remover=transparent_remover)
    invalid_path = tmp_path / "image.gif"
    invalid_path.write_bytes(b"not an image")

    job_result = service.process_batch([invalid_path])

    assert job_result.status == "failed"
    metadata = job_result.images[0]
    assert metadata.status == "failed"
    assert "Unsupported file extension" in metadata.error

    job_dir = storage_root / job_result.job_id
    metadata_file = job_dir / "metadata" / f"{metadata.normalized_name}.json"
    with metadata_file.open("r", encoding="utf-8") as fh:
        metadata_json = json.load(fh)
    assert metadata_json["status"] == "failed"
    assert "Unsupported file extension" in metadata_json["error"]
