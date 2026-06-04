from __future__ import annotations

import asyncio
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import model_runtime_should_defer_background
from novel_backend.services.project_service import list_projects
from novel_backend.services.self_evolution_service import (
  _load_schedule,
  run_self_evolution_humanize_patrol,
  run_self_evolution_scheduled_tasks,
)


class SelfEvolutionScheduler:
  def __init__(self, settings: Settings):
    self.settings = settings
    self._task: asyncio.Task | None = None
    self._stopped = asyncio.Event()

  async def start(self) -> None:
    if not self.settings.self_evolution_worker_enabled:
      return
    if self._task is not None and not self._task.done():
      return
    self._stopped.clear()
    self._task = asyncio.create_task(self._loop(), name="self-evolution-scheduler")

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
    interval_seconds = max(30, int(self.settings.self_evolution_worker_interval_seconds))
    while not self._stopped.is_set():
      try:
        await self.run_once()
      except Exception as error:
        append_app_log(self.settings, f"自学习后台排程失败：{error}", level="WARNING")
      try:
        await asyncio.wait_for(self._stopped.wait(), timeout=interval_seconds)
      except asyncio.TimeoutError:
        continue

  async def run_once(self) -> dict[str, object]:
    results: list[dict[str, object]] = []
    projects = list_projects(self.settings)
    for project in projects:
      project_dir = Path(project.path)
      try:
        schedule = _load_schedule(project_dir)
        tasks = [str(item) for item in schedule.get("tasks") or []]
        if "model_review" in tasks and model_runtime_should_defer_background(self.settings):
          result = {"status": "deferred", "ran": [], "schedule": schedule}
        else:
          result = await asyncio.to_thread(
            run_self_evolution_scheduled_tasks,
            self.settings,
            project_dir,
            force=False,
          )
        patrol_result: dict[str, object] | None = None
        scheduled_tasks = [
          str(item.get("task") or "")
          for item in result.get("ran") or []
          if isinstance(item, dict)
        ]
        if (
          bool(schedule.get("enabled"))
          and "model_review" in tasks
          and "model_review" not in scheduled_tasks
          and result.get("status") != "deferred"
        ):
          patrol_result = await asyncio.to_thread(
            run_self_evolution_humanize_patrol,
            self.settings,
            project_dir,
            reason="heartbeat",
            force=False,
          )
      except Exception as error:
        append_app_log(self.settings, f"项目 {project.id} 自学习排程失败：{error}", level="WARNING")
        result = {"status": "failed", "error": str(error), "ran": []}
        patrol_result = None
      if result.get("status") in {"completed", "failed"} or (
        isinstance(patrol_result, dict) and patrol_result.get("status") in {"completed", "failed"}
      ):
        results.append(
          {
            "project_id": project.id,
            "project_name": project.name,
            "status": result.get("status", "") if result.get("status") in {"completed", "failed"} else patrol_result.get("status", ""),
            "ran_count": len(result.get("ran") or []) + (1 if isinstance(patrol_result, dict) and patrol_result.get("status") == "completed" else 0),
            "humanize_patrol_status": patrol_result.get("status", "") if isinstance(patrol_result, dict) else "",
          }
        )
    if results:
      append_app_log(self.settings, f"自学习后台排程完成：{len(results)} 个项目有任务变化")
    return {"checked_count": len(projects), "results": results}


async def close_self_evolution_scheduler(scheduler: SelfEvolutionScheduler | None) -> None:
  if scheduler is not None:
    await scheduler.close()
