from __future__ import annotations

from fastapi import APIRouter, Request

from novel_backend.models import AppConfigUpdateRequest
from novel_backend.services.config_service import load_config, save_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config(request: Request):
  settings = request.app.state.settings
  payload = load_config(settings)
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.put("")
def update_config(request: Request, config_update: AppConfigUpdateRequest):
  settings = request.app.state.settings
  payload = save_config(settings, config_update)
  return {"ok": True, "data": payload.model_dump(mode="json")}
