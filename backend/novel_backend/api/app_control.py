from __future__ import annotations

import asyncio
import os
import signal

from fastapi import APIRouter, Request

from novel_backend.models import HealthPayload
from novel_backend.services.project_service import project_count

router = APIRouter(prefix="/api/app", tags=["app"])


@router.get("/health")
def health(request: Request):
  settings = request.app.state.settings
  payload = HealthPayload(
    status="ok",
    backend_version=settings.app_version,
    data_dir=str(settings.data_dir),
    started_at=settings.started_at.isoformat(),
    project_count=project_count(settings),
  )
  return {"ok": True, "data": payload.model_dump(mode="json")}


def _terminate_current_process() -> None:
  os.kill(os.getpid(), signal.SIGTERM)


@router.post("/shutdown")
async def shutdown():
  loop = asyncio.get_running_loop()
  loop.call_later(0.15, _terminate_current_process)
  return {"ok": True, "data": {"accepted": True}}
