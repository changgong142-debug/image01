from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import api_router, preview_router
from app.core import config
from app.dependencies import set_job_manager
from app.services.job_manager import JobManager

app = FastAPI(title="Image Processing Backend", version="1.0.0")

job_manager = JobManager(jobs_root=config.JOBS_ROOT, temp_root=config.TEMP_ROOT)
set_job_manager(job_manager)


@app.on_event("startup")
async def on_startup() -> None:
    await job_manager.initialize()
    await job_manager.clean_temp_dir()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await job_manager.shutdown()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)
app.include_router(preview_router)
