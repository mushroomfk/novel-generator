from __future__ import annotations

from fastapi import HTTPException, Request

from novel_backend.services.license_service import validate_license


def require_valid_license(request: Request) -> None:
  settings = request.app.state.settings
  result = validate_license(settings)
  if result.valid:
    return

  raise HTTPException(
    status_code=403,
    detail={
      "code": "license_required",
      "message": f"请先导入有效许可证：{result.reason}",
    },
  )
