from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import HTTPException
from watchfiles import awatch

from novel_backend.config import Settings
from novel_backend.services.project_service import auto_save_project_snapshot, list_projects


class ProjectHistoryWatcher:
  def __init__(self, settings: Settings):
    self._settings = settings
    self._project_tasks: dict[str, asyncio.Task] = {}
    self._project_paths: dict[str, Path] = {}
    self._subscribers: dict[str, set[asyncio.Queue[dict[str, object]]]] = {}
    self._lock = asyncio.Lock()

  async def start(self) -> None:
    for project in list_projects(self._settings):
      await self.register_project(project.id, Path(project.path))

  async def stop(self) -> None:
    async with self._lock:
      tasks = list(self._project_tasks.values())
      self._project_tasks = {}
      self._project_paths = {}

    for task in tasks:
      task.cancel()

    if tasks:
      await asyncio.gather(*tasks, return_exceptions=True)

  async def register_project(self, project_id: str, project_dir: Path) -> None:
    resolved_dir = project_dir.expanduser().resolve()
    async with self._lock:
      existing_dir = self._project_paths.get(project_id)
      if existing_dir == resolved_dir and project_id in self._project_tasks:
        return

      previous_task = self._project_tasks.get(project_id)
      if previous_task is not None:
        previous_task.cancel()

      self._project_paths[project_id] = resolved_dir
      self._project_tasks[project_id] = asyncio.create_task(
        self._watch_project(project_id, resolved_dir),
        name=f"project-history-watch:{project_id}",
      )

  async def unregister_project(self, project_id: str) -> None:
    async with self._lock:
      task = self._project_tasks.pop(project_id, None)
      self._project_paths.pop(project_id, None)
      self._subscribers.pop(project_id, None)

    if task is not None:
      task.cancel()
      await asyncio.gather(task, return_exceptions=True)

  def subscribe(self, project_id: str) -> asyncio.Queue[dict[str, object]]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    subscribers = self._subscribers.setdefault(project_id, set())
    subscribers.add(queue)
    return queue

  def unsubscribe(self, project_id: str, queue: asyncio.Queue[dict[str, object]]) -> None:
    subscribers = self._subscribers.get(project_id)
    if subscribers is None:
      return

    subscribers.discard(queue)
    if not subscribers:
      self._subscribers.pop(project_id, None)

  async def publish_project_event(self, project_id: str, reason: str) -> None:
    payload = {
      "event": "local-history-updated",
      "data": {
        "project_id": project_id,
        "reason": reason,
      },
    }
    for queue in list(self._subscribers.get(project_id, ())):
      await queue.put(payload)

  async def _watch_project(self, project_id: str, project_dir: Path) -> None:
    if not project_dir.exists():
      return

    try:
      async for changes in awatch(project_dir, recursive=True, debounce=1500, step=250):
        if not self._has_relevant_change(project_dir, changes):
          continue

        try:
          auto_save_project_snapshot(self._settings, project_id)
        except HTTPException as error:
          code = error.detail.get("code") if isinstance(error.detail, dict) else None
          if code in {"no_local_changes", "project_not_found"}:
            continue
          raise

        await self.publish_project_event(project_id, "autosave")
    except asyncio.CancelledError:
      raise
    except FileNotFoundError:
      return

  def _has_relevant_change(self, project_dir: Path, changes: set[tuple[object, str]]) -> bool:
    for _change, raw_path in changes:
      if self._is_versioned_path(project_dir, Path(raw_path)):
        return True

    return False

  def _is_versioned_path(self, project_dir: Path, path: Path) -> bool:
    try:
      relative_path = path.resolve().relative_to(project_dir.resolve())
    except ValueError:
      return False

    parts = relative_path.parts
    if len(parts) == 0:
      return False

    if parts[0] in {".novel-history", "backups"}:
      return False

    if len(parts) == 1 and relative_path.name in {
      "core_seed.txt",
      "character_design.txt",
      "character_state.txt",
      "world_building.txt",
      "plot_structure.txt",
      "blueprint.txt",
      "global_summary.txt",
    }:
      return True

    if parts[0] != "chapters":
      return False

    return relative_path.suffix in {".md", ".txt"}


async def close_project_history_watcher(service: ProjectHistoryWatcher | None) -> None:
  if service is None:
    return

  with contextlib.suppress(Exception):
    await service.stop()
