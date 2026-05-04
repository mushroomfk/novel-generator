from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  CharacterReplicaProfileDetail,
  CharacterReplicaProfileSaveRequest,
  CharacterReplicaProfileSummary,
)
from novel_backend.services.config_service import character_replica_profiles_dir
from novel_backend.utils.jsonfile import atomic_write_json, read_json


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _profile_path(settings: Settings, name: str) -> Path:
  return character_replica_profiles_dir(settings) / f"{name}.json"


def _profile_or_404(settings: Settings, name: str) -> CharacterReplicaProfileDetail:
  path = _profile_path(settings, name)
  if not path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "character_replica_profile_not_found", "message": "人物卡不存在"},
    )
  return CharacterReplicaProfileDetail.model_validate(read_json(path, {}))


def list_character_replica_profiles(settings: Settings) -> list[CharacterReplicaProfileSummary]:
  items: list[CharacterReplicaProfileSummary] = []
  for path in sorted(character_replica_profiles_dir(settings).glob("*.json")):
    payload = read_json(path, {})
    if not isinstance(payload, dict):
      continue
    items.append(
      CharacterReplicaProfileSummary(
        name=str(payload.get("name") or path.stem),
        summary=str(payload.get("summary") or ""),
        updated_at=str(payload.get("updated_at") or "") or None,
      )
    )
  return items


def get_character_replica_profile(settings: Settings, name: str) -> CharacterReplicaProfileDetail:
  return _profile_or_404(settings, name)


def save_character_replica_profile(
  settings: Settings,
  name: str,
  request: CharacterReplicaProfileSaveRequest,
) -> CharacterReplicaProfileDetail:
  profile = CharacterReplicaProfileDetail(
    name=name.strip(),
    focus=request.focus.strip(),
    source_notes=request.source_notes.strip(),
    summary=request.summary.strip(),
    voice_profile=request.voice_profile.strip(),
    mental_models=[item.strip() for item in request.mental_models if item.strip()],
    heuristics=[item.strip() for item in request.heuristics if item.strip()],
    boundaries=[item.strip() for item in request.boundaries if item.strip()],
    disclaimer=request.disclaimer.strip(),
    updated_at=_now_iso(),
  )
  atomic_write_json(_profile_path(settings, name), profile.model_dump(mode="json"))
  return profile


def delete_character_replica_profile(settings: Settings, name: str) -> None:
  path = _profile_path(settings, name)
  if not path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "character_replica_profile_not_found", "message": "人物卡不存在"},
    )
  path.unlink()
