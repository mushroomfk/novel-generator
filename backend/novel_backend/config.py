from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode

from novel_backend import __version__


def default_data_dir() -> Path:
  env_data_dir = os.getenv("NOVEL_DATA_DIR")
  if env_data_dir:
    return Path(env_data_dir).expanduser().resolve()

  home = Path.home()
  if sys.platform == "darwin":
    return (home / "Library" / "Application Support" / "NovelGenerator").resolve()
  if sys.platform.startswith("win"):
    appdata = os.getenv("APPDATA")
    if appdata:
      return (Path(appdata) / "NovelGenerator").resolve()

  return (home / ".local" / "share" / "NovelGenerator").resolve()


class Settings(BaseSettings):
  host: str = "127.0.0.1"
  port: int = 18181
  data_dir: Path = Field(default_factory=default_data_dir)
  app_name: str = "NovelGenerator"
  app_version: str = __version__
  started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
  self_evolution_worker_enabled: bool = True
  self_evolution_worker_interval_seconds: int = Field(default=300, ge=30, le=86400)
  auxiliary_worker_enabled: bool = True
  auxiliary_worker_interval_seconds: int = Field(default=180, ge=30, le=86400)
  cors_origins: Annotated[list[str], NoDecode] = Field(
    default_factory=lambda: [
      "http://localhost:1420",
      "http://127.0.0.1:1420",
      "http://tauri.localhost",
      "https://tauri.localhost",
      "tauri://localhost",
    ]
  )

  model_config = SettingsConfigDict(env_prefix="NOVEL_", extra="ignore")

  @field_validator("cors_origins", mode="before")
  @classmethod
  def parse_cors_origins(cls, value: Any) -> list[str]:
    if isinstance(value, str):
      stripped = value.strip()
      if not stripped:
        return []
      if stripped.startswith("["):
        parsed = json.loads(stripped)
        if not isinstance(parsed, list):
          raise ValueError("NOVEL_CORS_ORIGINS must be a JSON array or a comma-separated list")
        return [str(item).strip() for item in parsed if str(item).strip()]
      return [item.strip() for item in stripped.split(",") if item.strip()]
    if isinstance(value, list):
      return [str(item).strip() for item in value if str(item).strip()]
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
  return Settings()


def reset_settings_cache() -> None:
  get_settings.cache_clear()
