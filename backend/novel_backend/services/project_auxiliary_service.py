from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import model_runtime_should_defer_background
from novel_backend.services.project_service import (
  list_projects,
  refresh_project_knowledge_index,
  refresh_project_model_story_overview,
  refresh_project_system_memory,
)
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_AUXILIARY_SCHEMA_VERSION = "1"
_AUXILIARY_TASK_FILENAME = "auxiliary_tasks.json"
_AUXILIARY_TASKS = ("knowledge_index", "story_overview_model", "system_memory")
_STALE_RUNNING_SECONDS = 20 * 60


def _now() -> datetime:
  return datetime.now(timezone.utc)


def _now_iso() -> str:
  return _now().isoformat()


def _parse_iso_datetime(value: object) -> datetime | None:
  if not isinstance(value, str) or not value.strip():
    return None
  try:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
  except ValueError:
    return None
  if parsed.tzinfo is None:
    return parsed.replace(tzinfo=timezone.utc)
  return parsed.astimezone(timezone.utc)


def _project_by_id(settings: Settings, project_id: str):
  return next((item for item in list_projects(settings) if item.id == project_id), None)


def _state_path(project_path: str | Path) -> Path:
  return Path(project_path) / ".gaoxia" / _AUXILIARY_TASK_FILENAME


def _read_state(project_path: str | Path) -> dict[str, object]:
  payload = read_json(_state_path(project_path), None)
  if not isinstance(payload, dict) or payload.get("schema_version") != _AUXILIARY_SCHEMA_VERSION:
    return {"schema_version": _AUXILIARY_SCHEMA_VERSION, "tasks": {}}
  if not isinstance(payload.get("tasks"), dict):
    payload["tasks"] = {}
  return payload


def _write_state(project_path: str | Path, payload: dict[str, object]) -> None:
  payload["schema_version"] = _AUXILIARY_SCHEMA_VERSION
  payload["updated_at"] = _now_iso()
  atomic_write_json(_state_path(project_path), payload)


def _retry_delay_seconds(retry_count: int) -> int:
  return min(3600, 60 * (2 ** max(0, min(retry_count, 5))))


def enqueue_project_auxiliary_tasks(
  settings: Settings,
  project_id: str,
  *,
  tasks: list[str] | tuple[str, ...] | None = None,
  reason: str = "",
) -> dict[str, object]:
  project = _project_by_id(settings, project_id)
  if project is None:
    return {"status": "missing_project", "project_id": project_id}

  selected_tasks = [item for item in (tasks or _AUXILIARY_TASKS) if item in _AUXILIARY_TASKS]
  if not selected_tasks:
    return {"status": "skipped", "project_id": project_id, "tasks": []}

  state = _read_state(project.path)
  task_state = state.setdefault("tasks", {})
  assert isinstance(task_state, dict)
  now = _now_iso()
  for task_name in selected_tasks:
    current = task_state.get(task_name)
    retry_count = 0
    last_error = ""
    if isinstance(current, dict):
      retry_count = int(current.get("retry_count") or 0)
      last_error = str(current.get("last_error") or "")
    task_state[task_name] = {
      "status": "pending",
      "reason": reason,
      "retry_count": retry_count,
      "last_error": last_error,
      "next_run_at": now,
      "updated_at": now,
    }
  _write_state(project.path, state)
  append_app_log(settings, f"项目 {project_id} 辅助任务已排队：{', '.join(selected_tasks)}")
  return {"status": "queued", "project_id": project_id, "tasks": selected_tasks}


def _task_is_due(payload: dict[str, object], now: datetime) -> bool:
  status = str(payload.get("status") or "")
  if status == "completed":
    return False
  updated_at = _parse_iso_datetime(payload.get("updated_at"))
  if status == "running" and updated_at is not None and now - updated_at < timedelta(seconds=_STALE_RUNNING_SECONDS):
    return False
  next_run_at = _parse_iso_datetime(payload.get("next_run_at"))
  return next_run_at is None or next_run_at <= now


def _run_task(settings: Settings, project_id: str, task_name: str) -> None:
  if task_name == "knowledge_index":
    refresh_project_knowledge_index(settings, project_id)
    return
  if task_name == "story_overview_model":
    refresh_project_model_story_overview(settings, project_id, force=True)
    return
  if task_name == "system_memory":
    refresh_project_system_memory(settings, project_id, focus="辅助任务刷新")
    return
  raise RuntimeError(f"未知辅助任务：{task_name}")


def run_project_auxiliary_tasks(
  settings: Settings,
  project_id: str,
  *,
  force: bool = False,
) -> dict[str, object]:
  project = _project_by_id(settings, project_id)
  if project is None:
    return {"status": "missing_project", "project_id": project_id, "ran": []}

  state = _read_state(project.path)
  task_state = state.setdefault("tasks", {})
  assert isinstance(task_state, dict)
  now = _now()
  ran: list[dict[str, object]] = []
  if not force and model_runtime_should_defer_background(settings):
    return {"status": "deferred", "project_id": project_id, "ran": []}
  for task_name in _AUXILIARY_TASKS:
    current = task_state.get(task_name)
    if not isinstance(current, dict):
      continue
    if not force and not _task_is_due(current, now):
      continue

    current["status"] = "running"
    current["updated_at"] = _now_iso()
    _write_state(project.path, state)
    try:
      _run_task(settings, project_id, task_name)
    except Exception as error:
      retry_count = int(current.get("retry_count") or 0) + 1
      current.update(
        {
          "status": "failed",
          "retry_count": retry_count,
          "last_error": str(error),
          "next_run_at": (_now() + timedelta(seconds=_retry_delay_seconds(retry_count))).isoformat(),
          "updated_at": _now_iso(),
        }
      )
      append_app_log(settings, f"项目 {project_id} 辅助任务 {task_name} 失败：{error}", level="WARNING")
      ran.append({"task": task_name, "status": "failed", "error": str(error)})
    else:
      current.update(
        {
          "status": "completed",
          "retry_count": 0,
          "last_error": "",
          "next_run_at": "",
          "updated_at": _now_iso(),
        }
      )
      append_app_log(settings, f"项目 {project_id} 辅助任务 {task_name} 完成")
      ran.append({"task": task_name, "status": "completed"})
    _write_state(project.path, state)

  return {"status": "completed", "project_id": project_id, "ran": ran}


def run_due_project_auxiliary_tasks(settings: Settings) -> dict[str, object]:
  results: list[dict[str, object]] = []
  for project in list_projects(settings):
    result = run_project_auxiliary_tasks(settings, project.id, force=False)
    if result.get("ran"):
      results.append(result)
  if results:
    append_app_log(settings, f"辅助任务巡检完成：{len(results)} 个项目有任务变化")
  return {"checked_count": len(list_projects(settings)), "results": results}


class ProjectAuxiliaryScheduler:
  def __init__(self, settings: Settings):
    self.settings = settings
    self._task: asyncio.Task | None = None
    self._stopped = asyncio.Event()

  async def start(self) -> None:
    if not self.settings.auxiliary_worker_enabled:
      return
    if self._task is not None and not self._task.done():
      return
    self._stopped.clear()
    self._task = asyncio.create_task(self._loop(), name="project-auxiliary-scheduler")

  async def close(self) -> None:
    self._stopped.set()
    if self._task is None:
      return
    self._task.cancel()
    try:
      await self._task
    except asyncio.CancelledError:
      pass
    self._task = None

  async def _loop(self) -> None:
    interval_seconds = max(30, int(self.settings.auxiliary_worker_interval_seconds))
    while not self._stopped.is_set():
      try:
        await asyncio.to_thread(run_due_project_auxiliary_tasks, self.settings)
      except Exception as error:
        append_app_log(self.settings, f"辅助任务巡检失败：{error}", level="WARNING")
      try:
        await asyncio.wait_for(self._stopped.wait(), timeout=interval_seconds)
      except asyncio.TimeoutError:
        continue


async def close_project_auxiliary_scheduler(scheduler: ProjectAuxiliaryScheduler | None) -> None:
  if scheduler is not None:
    await scheduler.close()
