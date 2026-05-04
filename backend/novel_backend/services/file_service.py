from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import ToolFileEntry
from novel_backend.services.project_service import (
  _project_dir,
  _project_summary_or_404,
  _refresh_project_knowledge_for_paths,
  _touch_project_timestamp,
)
from novel_backend.utils.jsonfile import atomic_write_text

_ALLOWED_EXTENSIONS = {".txt", ".json", ".md"}
_BLOCKED_TOP_LEVEL_DIRS = {".novel-history", "backups"}


def _normalized_relative_path(base_dir: Path, target: Path) -> str:
  return str(target.relative_to(base_dir)).replace("\\", "/")


def _is_blocked_relative_path(relative_path: str) -> bool:
  normalized = relative_path.strip().replace("\\", "/")
  if not normalized:
    return True
  first_part = normalized.split("/", 1)[0]
  return first_part in _BLOCKED_TOP_LEVEL_DIRS


def list_project_files(settings: Settings, project_id: str) -> list[ToolFileEntry]:
  summary = _project_summary_or_404(settings, project_id)
  base_dir = _project_dir(summary)
  items: list[ToolFileEntry] = []
  for path in sorted(base_dir.rglob("*")):
    if not path.is_file():
      continue
    if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
      continue
    relative = path.relative_to(base_dir)
    relative_path = str(relative).replace("\\", "/")
    if _is_blocked_relative_path(relative_path):
      continue
    items.append(
      ToolFileEntry(
        path=relative_path,
        name=path.name,
        size=path.stat().st_size,
        directory=str(relative.parent).replace("\\", "/"),
      )
    )
  return items


def read_project_file(settings: Settings, project_id: str, relative_path: str) -> dict[str, str]:
  summary = _project_summary_or_404(settings, project_id)
  base_dir = _project_dir(summary)
  target = (base_dir / relative_path).resolve()
  if base_dir not in target.parents and target != base_dir:
    raise HTTPException(
      status_code=403,
      detail={"code": "file_access_denied", "message": "文件访问被拒绝"},
    )
  if target.suffix.lower() not in _ALLOWED_EXTENSIONS:
    raise HTTPException(
      status_code=403,
      detail={"code": "file_type_blocked", "message": "当前文件类型不支持直接查看"},
    )
  normalized_path = _normalized_relative_path(base_dir, target)
  if _is_blocked_relative_path(normalized_path):
    raise HTTPException(
      status_code=403,
      detail={"code": "file_access_denied", "message": "当前目录不支持直接查看"},
    )
  if not target.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "file_not_found", "message": "文件不存在"},
    )
  return {
    "path": normalized_path,
    "content": target.read_text(encoding="utf-8"),
  }


def write_project_file(settings: Settings, project_id: str, relative_path: str, content: str) -> dict[str, str]:
  summary = _project_summary_or_404(settings, project_id)
  base_dir = _project_dir(summary)
  target = (base_dir / relative_path).resolve()
  if base_dir not in target.parents and target != base_dir:
    raise HTTPException(
      status_code=403,
      detail={"code": "file_access_denied", "message": "文件访问被拒绝"},
    )
  if target.suffix.lower() not in _ALLOWED_EXTENSIONS:
    raise HTTPException(
      status_code=403,
      detail={"code": "file_type_blocked", "message": "当前文件类型不支持直接编辑"},
    )
  normalized_path = _normalized_relative_path(base_dir, target)
  if _is_blocked_relative_path(normalized_path):
    raise HTTPException(
      status_code=403,
      detail={"code": "file_access_denied", "message": "当前目录不支持直接编辑"},
    )

  target.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_text(target, content)
  updated_at = datetime.now(timezone.utc).isoformat()
  _touch_project_timestamp(settings, summary.id, updated_at)
  _refresh_project_knowledge_for_paths(settings, base_dir, summary.target_chapters, [normalized_path])
  return {
    "path": normalized_path,
    "content": content,
  }
