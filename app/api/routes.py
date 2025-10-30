from __future__ import annotations

import mimetypes
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.dependencies import get_job_manager
from app.models import ImageRecord, JobRecord
from app.schemas import ImageStatus, JobCreatedResponse, JobStatusResponse
from app.services.job_manager import JobManager, JobNotFoundError

api_router = APIRouter(prefix="/api/v1", tags=["jobs"])
preview_router = APIRouter(prefix="/preview", tags=["previews"])


def _validate_uploads(files: List[UploadFile]) -> None:
    invalid = [file.filename or "" for file in files if not (file.content_type or "").startswith("image/")]
    if invalid:
        names = ", ".join(invalid)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type for: {names}",
        )


def _build_image_status(request: Request, job: JobRecord, image: ImageRecord) -> ImageStatus:
    job_id = job.job_id
    original_url = request.url_for("get_original_preview", job_id=job_id, image_id=image.image_id)
    processed_url: Optional[str] = None
    if image.status == "completed" and image.processed_path:
        processed_url = request.url_for("get_processed_preview", job_id=job_id, image_id=image.image_id)
    return ImageStatus(
        image_id=image.image_id,
        filename=image.original_filename,
        status=image.status,
        error=image.error,
        original_url=original_url,
        processed_url=processed_url,
    )


@api_router.post("/jobs", status_code=status.HTTP_201_CREATED, response_model=JobCreatedResponse, name="create_job")
async def upload_images(
    background_tasks: BackgroundTasks,
    request: Request,
    files: List[UploadFile] = File(...),
    job_manager: JobManager = Depends(get_job_manager),
) -> JobCreatedResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")
    _validate_uploads(files)

    job = await job_manager.create_job(files)
    background_tasks.add_task(job_manager.process_job, job.job_id)

    status_url = request.url_for("get_job_status", job_id=job.job_id)
    download_url = request.url_for("download_job_archive", job_id=job.job_id)

    return JobCreatedResponse(job_id=job.job_id, status_url=status_url, download_url=download_url)


@api_router.get("/jobs/{job_id}", response_model=JobStatusResponse, name="get_job_status")
async def get_job_status_endpoint(job_id: str, request: Request, job_manager: JobManager = Depends(get_job_manager)) -> JobStatusResponse:
    try:
        job = await job_manager.get_job_snapshot(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    total = job.total_images
    processed = job.processed_count
    failed = job.failed_count
    pending = job.pending_count
    progress = processed / total if total else 0.0

    images = [_build_image_status(request, job, image) for image in job.images]

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at,
        total=total,
        processed=processed,
        failed=failed,
        pending=pending,
        progress=progress,
        images=images,
    )


@api_router.get(
    "/jobs/{job_id}/images/{image_id}",
    response_class=FileResponse,
    name="download_processed_image",
)
async def download_processed_image(job_id: str, image_id: str, job_manager: JobManager = Depends(get_job_manager)) -> FileResponse:
    try:
        job = await job_manager.get_job_snapshot(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    image = next((item for item in job.images if item.image_id == image_id), None)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    try:
        processed_path = job_manager.resolve_processed_path(job, image)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid image path")
    if not processed_path or not processed_path.exists():
        if image.status == "failed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Image processing failed")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not processed yet")

    media_type, _ = mimetypes.guess_type(image.stored_filename)
    return FileResponse(
        processed_path,
        media_type=media_type or "application/octet-stream",
        filename=image.stored_filename,
    )


@api_router.get("/jobs/{job_id}/download", response_class=FileResponse, name="download_job_archive")
async def download_job_archive(job_id: str, job_manager: JobManager = Depends(get_job_manager)) -> FileResponse:
    try:
        job = await job_manager.get_job_snapshot(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status not in {"processing", "completed", "failed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job has not started processing")

    try:
        archive_path = await job_manager.create_archive(job)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid image path")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    background_task = BackgroundTask(archive_path.unlink, missing_ok=True)
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{job.job_id}.zip",
        background=background_task,
    )


@preview_router.get(
    "/jobs/{job_id}/originals/{image_id}",
    response_class=FileResponse,
    name="get_original_preview",
)
async def get_original_preview(job_id: str, image_id: str, job_manager: JobManager = Depends(get_job_manager)) -> FileResponse:
    try:
        job = await job_manager.get_job_snapshot(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    image = next((item for item in job.images if item.image_id == image_id), None)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    try:
        original_path = job_manager.resolve_original_path(job, image)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid image path")
    if not original_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    media_type, _ = mimetypes.guess_type(image.original_filename)
    return FileResponse(
        original_path,
        media_type=media_type or "application/octet-stream",
        filename=image.original_filename,
    )


@preview_router.get(
    "/jobs/{job_id}/processed/{image_id}",
    response_class=FileResponse,
    name="get_processed_preview",
)
async def get_processed_preview(job_id: str, image_id: str, job_manager: JobManager = Depends(get_job_manager)) -> FileResponse:
    try:
        job = await job_manager.get_job_snapshot(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    image = next((item for item in job.images if item.image_id == image_id), None)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    try:
        processed_path = job_manager.resolve_processed_path(job, image)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid image path")
    if not processed_path or not processed_path.exists():
        if image.status == "failed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Image processing failed")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not processed yet")

    media_type, _ = mimetypes.guess_type(image.stored_filename)
    return FileResponse(
        processed_path,
        media_type=media_type or "application/octet-stream",
        filename=image.stored_filename,
    )
