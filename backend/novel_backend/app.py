from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from novel_backend.api import app_control, config, generate, license, projects, studio
from novel_backend.config import get_settings
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.history_watch_service import ProjectHistoryWatcher, close_project_history_watcher

LOCAL_ORIGIN_PATTERN = r"^(https?:\/\/(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?|tauri:\/\/localhost)$"


@asynccontextmanager
async def lifespan(app: FastAPI):
  settings = get_settings()
  initialize_app_storage(settings)
  history_watcher = ProjectHistoryWatcher(settings)
  await history_watcher.start()
  app.state.settings = settings
  app.state.project_history_watcher = history_watcher
  try:
    yield
  finally:
    await close_project_history_watcher(history_watcher)


def _error_payload(message: str, code: str) -> dict[str, object]:
  return {
    "ok": False,
    "error": {
      "code": code,
      "message": message,
    },
  }


def create_app() -> FastAPI:
  settings = get_settings()
  app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
  )
  app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=LOCAL_ORIGIN_PATTERN,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  )

  @app.exception_handler(HTTPException)
  async def http_exception_handler(_request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
      return JSONResponse(
        status_code=exc.status_code,
        content={
          "ok": False,
          "error": {
            "code": exc.detail.get("code", "http_error"),
            "message": exc.detail.get("message", "请求失败"),
          },
        },
      )

    return JSONResponse(
      status_code=exc.status_code,
      content=_error_payload(str(exc.detail), "http_error"),
    )

  @app.exception_handler(Exception)
  async def generic_exception_handler(_request: Request, exc: Exception):
    return JSONResponse(
      status_code=500,
      content=_error_payload(str(exc), "internal_error"),
    )

  app.include_router(app_control.router)
  app.include_router(projects.router)
  app.include_router(config.router)
  app.include_router(license.router)
  app.include_router(generate.router)
  app.include_router(studio.router)
  return app


app = create_app()
