from __future__ import annotations

from fastapi import APIRouter, Request

from novel_backend.models import LicenseImportRequest
from novel_backend.services.license_service import import_license, validate_license

router = APIRouter(prefix="/api/license", tags=["license"])


@router.get("/validate")
def get_license_status(request: Request):
  settings = request.app.state.settings
  payload = validate_license(settings)
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.post("/import")
def post_license(request: Request, license_request: LicenseImportRequest):
  settings = request.app.state.settings
  payload = import_license(settings, license_request.content)
  return {"ok": True, "data": payload.model_dump(mode="json")}
