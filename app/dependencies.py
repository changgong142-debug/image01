from __future__ import annotations

from typing import Optional

from app.services.job_manager import JobManager

_job_manager: Optional[JobManager] = None


def set_job_manager(manager: JobManager) -> None:
    global _job_manager
    _job_manager = manager


def get_job_manager() -> JobManager:
    if _job_manager is None:
        raise RuntimeError("Job manager not initialized")
    return _job_manager
