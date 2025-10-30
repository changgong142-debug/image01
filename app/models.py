from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ImageRecord:
    image_id: str
    original_filename: str
    stored_filename: str
    original_path: Path
    processed_path: Optional[Path] = None
    status: str = "pending"
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_id": self.image_id,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "original_path": str(self.original_path),
            "processed_path": str(self.processed_path) if self.processed_path else None,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageRecord":
        return cls(
            image_id=data["image_id"],
            original_filename=data["original_filename"],
            stored_filename=data["stored_filename"],
            original_path=Path(data["original_path"]),
            processed_path=Path(data["processed_path"]) if data.get("processed_path") else None,
            status=data.get("status", "pending"),
            error=data.get("error"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
        )


@dataclass
class JobRecord:
    job_id: str
    created_at: datetime
    status: str = "pending"
    images: List[ImageRecord] = field(default_factory=list)
    error: Optional[str] = None
    downloaded_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "images": [image.to_dict() for image in self.images],
            "error": self.error,
            "downloaded_at": self.downloaded_at.isoformat() if self.downloaded_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobRecord":
        return cls(
            job_id=data["job_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            status=data.get("status", "pending"),
            images=[ImageRecord.from_dict(item) for item in data.get("images", [])],
            error=data.get("error"),
            downloaded_at=datetime.fromisoformat(data["downloaded_at"]) if data.get("downloaded_at") else None,
        )

    @property
    def total_images(self) -> int:
        return len(self.images)

    @property
    def processed_count(self) -> int:
        return sum(1 for image in self.images if image.status == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for image in self.images if image.status == "failed")

    @property
    def pending_count(self) -> int:
        return sum(1 for image in self.images if image.status in {"pending", "processing"})
