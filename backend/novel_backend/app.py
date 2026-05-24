from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from novel_backend.api import app_control, config, generate, license, projects, studio
from novel_backend.config import get_settings
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.history_watch_service import ProjectHistoryWatcher, close_project_history_watcher
from novel_backend.services.project_auxiliary_service import (
  ProjectAuxiliaryScheduler,
  close_project_auxiliary_scheduler,
)
from novel_backend.services.self_evolution_scheduler_service import (
  SelfEvolutionScheduler,
  close_self_evolution_scheduler,
)

LOCAL_ORIGIN_PATTERN = r"^(https?:\/\/(localhost|127\.0\.0\.1|tauri\.localhost)(:\d+)?|tauri:\/\/localhost)$"


@asynccontextmanager
async def lifespan(app: FastAPI):
  settings = get_settings()
  initialize_app_storage(settings)
  history_watcher = ProjectHistoryWatcher(settings)
  await history_watcher.start()
  self_evolution_scheduler = SelfEvolutionScheduler(settings)
  await self_evolution_scheduler.start()
  project_auxiliary_scheduler = ProjectAuxiliaryScheduler(settings)
  await project_auxiliary_scheduler.start()
  app.state.settings = settings
  app.state.project_history_watcher = history_watcher
  app.state.self_evolution_scheduler = self_evolution_scheduler
  app.state.project_auxiliary_scheduler = project_auxiliary_scheduler
  try:
    yield
  finally:
    await close_project_auxiliary_scheduler(project_auxiliary_scheduler)
    await close_self_evolution_scheduler(self_evolution_scheduler)
    await close_project_history_watcher(history_watcher)


def _error_payload(message: str, code: str) -> dict[str, object]:
  return {
    "ok": False,
    "error": {
      "code": code,
      "message": message,
    },
  }


def _validation_error_location(loc: object) -> str:
  if not isinstance(loc, (list, tuple)):
    return "请求体"

  parts = [str(part) for part in loc if part != "body"]
  return ".".join(parts) if parts else "请求体"


def _validation_error_message(exc: RequestValidationError) -> str:
  errors = exc.errors()
  if not errors:
    return "请求参数不符合接口要求。"

  messages = []
  for item in errors[:3]:
    location = _validation_error_location(item.get("loc"))
    reason = str(item.get("msg") or "格式不正确")
    messages.append(f"{location}：{reason}")

  suffix = f"；另有 {len(errors) - 3} 个错误" if len(errors) > 3 else ""
  return f"请求参数不符合接口要求：{'；'.join(messages)}{suffix}"


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

  @app.exception_handler(RequestValidationError)
  async def request_validation_exception_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
      status_code=422,
      content=_error_payload(_validation_error_message(exc), "validation_error"),
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
