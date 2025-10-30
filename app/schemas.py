from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class JobCreatedResponse(BaseModel):
    job_id: str
    status_url: str
    download_url: str


class ImageStatus(BaseModel):
    image_id: str
    filename: str
    status: str
    error: Optional[str] = None
    original_url: str
    processed_url: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    total: int
    processed: int
    failed: int
    pending: int
    progress: float
    images: List[ImageStatus]

    class Config:
        allow_population_by_field_name = True
