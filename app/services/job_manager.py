from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from uuid import uuid4

from fastapi import UploadFile

from app.core import config
from app.models import ImageRecord, JobRecord
from app.services.utils import secure_filename, unique_filename


class JobNotFoundError(Exception):
    pass


class JobManager:
    def __init__(self, jobs_root: Path, temp_root: Path) -> None:
        self.jobs_root = jobs_root
        self.temp_root = temp_root
        self._jobs: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        await self._load_jobs_from_disk()
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup_loop())

    async def shutdown(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task
        await self.clean_temp_dir()

    async def _load_jobs_from_disk(self) -> None:
        for job_dir in self.jobs_root.glob("*"):
            if not job_dir.is_dir():
                continue
            manifest = job_dir / config.JOB_MANIFEST_NAME
            if not manifest.exists():
                continue
            try:
                raw = await asyncio.to_thread(manifest.read_text)
                data = json.loads(raw)
                job = JobRecord.from_dict(data)
                self._reconcile_paths(job)
                async with self._lock:
                    self._jobs[job.job_id] = job
            except Exception:
                # If loading fails, skip the job but ensure directory is not blocking future jobs
                continue

    async def create_job(self, files: Sequence[UploadFile]) -> JobRecord:
        if not files:
            raise ValueError("No files provided")

        now = datetime.now(timezone.utc)
        job_id = uuid4().hex
        job_dir = self.jobs_root / job_id
        originals_dir = job_dir / "originals"
        processed_dir = job_dir / "processed"
        for directory in (originals_dir, processed_dir):
            directory.mkdir(parents=True, exist_ok=True)

        job = JobRecord(job_id=job_id, created_at=now, status="pending")
        stored_names: List[str] = []

        for upload in files:
            filename = upload.filename or "upload"
            safe_name = secure_filename(filename)
            safe_name = unique_filename(stored_names, safe_name)
            stored_names.append(safe_name)

            destination = originals_dir / safe_name
            contents = await upload.read()
            await asyncio.to_thread(destination.write_bytes, contents)
            await upload.close()

            image_id = uuid4().hex
            image_record = ImageRecord(
                image_id=image_id,
                original_filename=filename,
                stored_filename=safe_name,
                original_path=Path("originals") / safe_name,
            )
            job.images.append(image_record)

        async with self._lock:
            self._jobs[job_id] = job
            await self._persist_job(job)

        return job

    async def get_job_snapshot(self, job_id: str) -> JobRecord:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            snapshot = JobRecord.from_dict(job.to_dict())
        self._reconcile_paths(snapshot)
        return snapshot

    async def process_job(self, job_id: str) -> None:
        try:
            async with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    raise JobNotFoundError(job_id)
                if job.status not in {"pending", "processing"}:
                    return
                job.status = "processing"
                await self._persist_job(job)
        except JobNotFoundError:
            return

        job_dir = self.jobs_root / job_id
        processed_dir = job_dir / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        for image in job.images:
            async with self._lock:
                image.status = "processing"
                image.started_at = datetime.now(timezone.utc)
                await self._persist_job(job)

            try:
                original_path = job_dir / image.original_path
                processed_path = processed_dir / image.stored_filename
                await asyncio.to_thread(shutil.copyfile, original_path, processed_path)
                # Simulate some processing time so progress is visible
                await asyncio.sleep(0)

                async with self._lock:
                    image.processed_path = Path("processed") / image.stored_filename
                    image.status = "completed"
                    image.completed_at = datetime.now(timezone.utc)
                    await self._persist_job(job)
            except Exception as exc:  # pragma: no cover - safeguard
                async with self._lock:
                    image.status = "failed"
                    image.error = str(exc)
                    image.completed_at = datetime.now(timezone.utc)
                    job.status = "failed"
                    job.error = "One or more images failed to process"
                    await self._persist_job(job)

        async with self._lock:
            if job.status != "failed":
                job.status = "completed"
            await self._persist_job(job)

    async def mark_downloaded(self, job_id: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            job.downloaded_at = datetime.now(timezone.utc)
            await self._persist_job(job)

    async def clean_temp_dir(self) -> None:
        now = datetime.now(timezone.utc)
        for item in self.temp_root.glob("*"):
            try:
                stat = item.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if (now - mtime).total_seconds() > config.TEMP_FILE_MAX_AGE:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
            except FileNotFoundError:
                continue

    async def cleanup_downloaded_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(seconds=config.DOWNLOADED_JOB_RETENTION)
        jobs_to_remove: List[str] = []
        async with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.downloaded_at and job.downloaded_at < threshold:
                    jobs_to_remove.append(job_id)

        for job_id in jobs_to_remove:
            job_dir = self.jobs_root / job_id
            shutil.rmtree(job_dir, ignore_errors=True)
            async with self._lock:
                self._jobs.pop(job_id, None)

    async def _persist_job(self, job: JobRecord) -> None:
        job_dir = self.jobs_root / job.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        manifest = job_dir / config.JOB_MANIFEST_NAME
        data = json.dumps(job.to_dict(), indent=2)
        await asyncio.to_thread(manifest.write_text, data)

    def _reconcile_paths(self, job: JobRecord) -> None:
        job_dir = self.jobs_root / job.job_id
        for image in job.images:
            if image.original_path.is_absolute():
                try:
                    image.original_path = image.original_path.relative_to(job_dir)
                except ValueError:
                    image.original_path = Path("originals") / Path(image.original_path).name
            if image.processed_path:
                if image.processed_path.is_absolute():
                    try:
                        image.processed_path = image.processed_path.relative_to(job_dir)
                    except ValueError:
                        image.processed_path = Path("processed") / Path(image.processed_path).name

    async def _periodic_cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(config.TEMP_CLEANUP_INTERVAL)
                await self.clean_temp_dir()
                await self.cleanup_downloaded_jobs()
        except asyncio.CancelledError:
            return

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def resolve_original_path(self, job: JobRecord, image: ImageRecord) -> Path:
        job_dir = (self.jobs_root / job.job_id).resolve()
        candidate = (job_dir / image.original_path).resolve()
        if not str(candidate).startswith(str(job_dir)):
            raise PermissionError("Attempted directory traversal")
        return candidate

    def resolve_processed_path(self, job: JobRecord, image: ImageRecord) -> Optional[Path]:
        if not image.processed_path:
            return None
        job_dir = (self.jobs_root / job.job_id).resolve()
        candidate = (job_dir / image.processed_path).resolve()
        if not str(candidate).startswith(str(job_dir)):
            raise PermissionError("Attempted directory traversal")
        return candidate

    async def create_archive(self, job: JobRecord) -> Path:
        archive_fd, archive_path_str = tempfile.mkstemp(prefix=f"{job.job_id}_", suffix=".zip", dir=self.temp_root)
        archive_path = Path(archive_path_str)
        os.close(archive_fd)
        processed_files = []
        for image in job.images:
            processed = self.resolve_processed_path(job, image)
            if processed and processed.exists():
                processed_files.append((processed, image.stored_filename))
        if not processed_files:
            archive_path.unlink(missing_ok=True)
            raise ValueError("No processed images available for download")

        await asyncio.to_thread(self._write_zip_archive, archive_path, processed_files)
        await self.mark_downloaded(job.job_id)
        return archive_path

    def _write_zip_archive(self, archive_path: Path, files: Iterable[tuple[Path, str]]) -> None:
        import zipfile

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, name in files:
                archive.write(path, arcname=name)
