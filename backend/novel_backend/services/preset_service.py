from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  PromptPresetCreateRequest,
  PromptPresetDetail,
  PromptPresetSummary,
  PromptPresetUpdateRequest,
  XPPreset,
  XPPresetCreateRequest,
  XPPresetUpdateRequest,
)
from novel_backend.services.config_service import (
  active_prompt_preset_path,
  prompt_presets_dir,
  xp_presets_path,
)
from novel_backend.utils.jsonfile import atomic_write_json, read_json


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _preset_path(settings: Settings, name: str) -> Path:
  return prompt_presets_dir(settings) / f"{name}.json"


def _preset_or_404(settings: Settings, name: str) -> PromptPresetDetail:
  path = _preset_path(settings, name)
  if not path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "preset_not_found", "message": "提示词方案不存在"},
    )
  return PromptPresetDetail.model_validate(read_json(path, {}))


def list_prompt_presets(settings: Settings) -> dict[str, object]:
  items: list[PromptPresetSummary] = []
  for path in sorted(prompt_presets_dir(settings).glob("*.json")):
    if path.name.startswith("_"):
      continue
    payload = read_json(path, {})
    if not isinstance(payload, dict):
      continue
    items.append(
      PromptPresetSummary(
        name=str(payload.get("name") or path.stem),
        description=str(payload.get("description") or ""),
        updated_at=str(payload.get("updated_at") or "") or None,
      )
    )

  active_payload = read_json(active_prompt_preset_path(settings), {})
  active_name = str(active_payload.get("name") or "")
  return {
    "presets": items,
    "active_preset": active_name,
  }


def create_prompt_preset(settings: Settings, request: PromptPresetCreateRequest) -> PromptPresetDetail:
  path = _preset_path(settings, request.name)
  if path.exists():
    raise HTTPException(
      status_code=409,
      detail={"code": "preset_exists", "message": "提示词方案已存在"},
    )

  payload = PromptPresetDetail(
    name=request.name.strip(),
    description=request.description.strip(),
    prompts={},
    updated_at=_now_iso(),
  )
  atomic_write_json(path, payload.model_dump(mode="json"))
  return payload


def get_prompt_preset(settings: Settings, name: str) -> PromptPresetDetail:
  return _preset_or_404(settings, name)


def activate_prompt_preset(settings: Settings, name: str) -> dict[str, str]:
  preset = _preset_or_404(settings, name)
  atomic_write_json(
    active_prompt_preset_path(settings),
    {"name": preset.name, "updated_at": _now_iso()},
  )
  return {"name": preset.name}


def update_prompt_preset(settings: Settings, name: str, request: PromptPresetUpdateRequest) -> PromptPresetDetail:
  preset = _preset_or_404(settings, name)
  updated = preset.model_copy(
    update={
      "description": request.description if request.description is not None else preset.description,
      "prompts": request.prompts if request.prompts is not None else preset.prompts,
      "updated_at": _now_iso(),
    }
  )
  atomic_write_json(_preset_path(settings, name), updated.model_dump(mode="json"))
  return updated


def delete_prompt_preset(settings: Settings, name: str) -> None:
  path = _preset_path(settings, name)
  if not path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "preset_not_found", "message": "提示词方案不存在"},
    )
  path.unlink()

  active_payload = read_json(active_prompt_preset_path(settings), {})
  if str(active_payload.get("name") or "") == name:
    presets = list_prompt_presets(settings)["presets"]
    next_name = presets[0].name if presets else ""
    atomic_write_json(
      active_prompt_preset_path(settings),
      {"name": next_name, "updated_at": _now_iso()},
    )


def get_active_prompt_instruction(settings: Settings, task_key: str) -> str:
  active_payload = read_json(active_prompt_preset_path(settings), {})
  active_name = str(active_payload.get("name") or "")
  if not active_name:
    return ""
  try:
    preset = _preset_or_404(settings, active_name)
  except HTTPException:
    return ""
  return str(preset.prompts.get(task_key) or "").strip()


def list_xp_presets(settings: Settings) -> list[XPPreset]:
  payload = read_json(xp_presets_path(settings), [])
  if not isinstance(payload, list):
    return []
  return [XPPreset.model_validate(item) for item in payload if isinstance(item, dict)]


def create_xp_preset(settings: Settings, request: XPPresetCreateRequest) -> XPPreset:
  presets = list_xp_presets(settings)
  if any(item.name == request.name.strip() for item in presets):
    raise HTTPException(
      status_code=409,
      detail={"code": "xp_preset_exists", "message": "XP 预设已存在"},
    )
  next_item = XPPreset(name=request.name.strip(), content=request.content.strip())
  atomic_write_json(
    xp_presets_path(settings),
    [item.model_dump(mode="json") for item in [*presets, next_item]],
  )
  return next_item


def update_xp_preset(settings: Settings, name: str, request: XPPresetUpdateRequest) -> XPPreset:
  presets = list_xp_presets(settings)
  updated_item: XPPreset | None = None
  next_items: list[XPPreset] = []

  for item in presets:
    if item.name != name:
      next_items.append(item)
      continue

    new_name = request.name.strip() if request.name is not None else item.name
    if new_name != name and any(existing.name == new_name for existing in presets):
      raise HTTPException(
        status_code=409,
        detail={"code": "xp_preset_exists", "message": "XP 预设名称已存在"},
      )
    updated_item = XPPreset(
      name=new_name,
      content=request.content.strip() if request.content is not None else item.content,
    )
    next_items.append(updated_item)

  if updated_item is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "xp_preset_not_found", "message": "XP 预设不存在"},
    )

  atomic_write_json(xp_presets_path(settings), [item.model_dump(mode="json") for item in next_items])
  return updated_item


def delete_xp_preset(settings: Settings, name: str) -> None:
  presets = list_xp_presets(settings)
  next_items = [item for item in presets if item.name != name]
  if len(next_items) == len(presets):
    raise HTTPException(
      status_code=404,
      detail={"code": "xp_preset_not_found", "message": "XP 预设不存在"},
    )
  atomic_write_json(xp_presets_path(settings), [item.model_dump(mode="json") for item in next_items])
