from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent
STORAGE_ROOT = PROJECT_ROOT / "storage"
JOBS_ROOT = STORAGE_ROOT / "jobs"
TEMP_ROOT = STORAGE_ROOT / "temp"
JOB_MANIFEST_NAME = "job.json"

# Cleanup intervals (in seconds)
TEMP_CLEANUP_INTERVAL = 60 * 30  # every 30 minutes
TEMP_FILE_MAX_AGE = 60 * 60  # remove temp files older than 1 hour
DOWNLOADED_JOB_RETENTION = 60 * 60 * 12  # keep downloaded jobs for 12 hours
