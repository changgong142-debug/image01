from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import BaseSettings, Field

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
TEMPLATES_DIR = FRONTEND_DIR / "templates"


class Settings(BaseSettings):
    app_name: str = "Background Removal Service"
    temp_storage_root: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "background_removal_service"
    )
    upload_dir_name: str = "uploads"
    output_dir_name: str = "outputs"
    static_dir: Path = Field(default_factory=lambda: STATIC_DIR)
    templates_dir: Path = Field(default_factory=lambda: TEMPLATES_DIR)
    cors_allow_origins: List[str] = Field(default_factory=lambda: ["*"])
    cors_allow_methods: List[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: List[str] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = False
    rembg_model_name: str = "u2net"

    class Config:
        env_prefix = "APP_"
        env_file = ".env"

    @property
    def upload_dir(self) -> Path:
        return self.temp_storage_root / self.upload_dir_name

    @property
    def output_dir(self) -> Path:
        return self.temp_storage_root / self.output_dir_name

    def ensure_directories(self) -> None:
        for directory in {
            self.temp_storage_root,
            self.upload_dir,
            self.output_dir,
        }:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
