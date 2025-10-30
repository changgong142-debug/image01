from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Union

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

if settings.static_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
else:
    logger.warning("Static directory '%s' does not exist.", settings.static_dir)


async def _ensure_rembg_models() -> None:
    """Download required rembg model assets on first run."""

    def _download() -> None:
        try:
            from rembg import new_session

            new_session(model_name=settings.rembg_model_name)
        except Exception:  # pragma: no cover - best effort warm-up
            logger.exception("Failed to initialize rembg model session.")

    await asyncio.to_thread(_download)


@app.on_event("startup")
async def on_startup() -> None:
    settings.ensure_directories()
    await _ensure_rembg_models()


@app.get("/", include_in_schema=False)
async def read_index() -> Union[FileResponse, JSONResponse]:
    index_file: Path = settings.static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"message": "Service is running"})


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
