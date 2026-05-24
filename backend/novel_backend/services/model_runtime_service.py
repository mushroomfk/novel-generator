from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from uuid import uuid4

from novel_backend.config import Settings
from novel_backend.models import ModelRuntimeConfig
from novel_backend.services.config_service import load_config
from novel_backend.services.log_service import append_app_log

_BACKGROUND_TASK_PREFIXES: tuple[str, ...] = ()
_PLANNING_TASK_PREFIXES = ("agent_route", "agent_plan")
_EXCLUSIVE_TASK_PREFIXES = (
  "architecture",
  "architecture_step",
  "batch_generate",
  "chapter_auto_repair",
  "chapter_generate",
  "chapter_review",
  "chapter_rewrite",
  "chapter_workflow",
  "continue_project",
)


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _infer_background(task_name: str) -> bool:
  normalized = task_name.strip().lower()
  return any(normalized.startswith(prefix) for prefix in _BACKGROUND_TASK_PREFIXES)


def _infer_priority(task_name: str, background: bool) -> int:
  normalized = task_name.strip().lower()
  if background:
    return 90
  if any(normalized.startswith(prefix) for prefix in _PLANNING_TASK_PREFIXES):
    return 10
  if any(normalized.startswith(prefix) for prefix in _EXCLUSIVE_TASK_PREFIXES):
    return 20
  return 40


@dataclass
class ModelRuntimeTask:
  task_id: str
  task_name: str
  lane: str
  priority: int
  source: str
  project_id: str
  chapter_id: str
  background: bool
  sequence: int
  queued_at: float
  queued_at_iso: str
  started_at: float = 0.0
  started_at_iso: str = ""
  finished_at_iso: str = ""
  queue_wait_seconds: float = 0.0

  def snapshot(self) -> dict[str, object]:
    now = time.monotonic()
    wait_seconds = self.queue_wait_seconds if self.started_at else max(0.0, now - self.queued_at)
    elapsed_seconds = max(0.0, now - self.started_at) if self.started_at else 0.0
    return {
      "task_id": self.task_id,
      "task_name": self.task_name,
      "lane": self.lane,
      "priority": self.priority,
      "source": self.source,
      "project_id": self.project_id,
      "chapter_id": self.chapter_id,
      "background": self.background,
      "queued_at": self.queued_at_iso,
      "started_at": self.started_at_iso,
      "finished_at": self.finished_at_iso,
      "queue_wait_seconds": round(wait_seconds, 3),
      "elapsed_seconds": round(elapsed_seconds, 3),
    }


class ModelRuntimeManager:
  def __init__(self) -> None:
    self._condition = threading.Condition()
    self._waiting: list[ModelRuntimeTask] = []
    self._active: list[ModelRuntimeTask] = []
    self._sequence = 0
    self._last_foreground_finished_at = time.monotonic()
    self._cooldown_until: dict[str, float] = {}
    self._cooldown_reason: dict[str, str] = {}

  def create_task(
    self,
    *,
    task_name: str,
    lane: str,
    priority: int | None = None,
    source: str = "",
    project_id: str = "",
    chapter_id: str = "",
    background: bool | None = None,
  ) -> ModelRuntimeTask:
    normalized_lane = lane.strip().lower() or "chat"
    if normalized_lane not in {"chat", "retrieval"}:
      normalized_lane = "chat"
    resolved_background = _infer_background(task_name) if background is None else bool(background)
    with self._condition:
      self._sequence += 1
      sequence = self._sequence
    return ModelRuntimeTask(
      task_id=str(uuid4()),
      task_name=task_name,
      lane=normalized_lane,
      priority=_infer_priority(task_name, resolved_background) if priority is None else int(priority),
      source=source,
      project_id=project_id,
      chapter_id=chapter_id,
      background=resolved_background,
      sequence=sequence,
      queued_at=time.monotonic(),
      queued_at_iso=_now_iso(),
    )

  def acquire(self, settings: Settings, task: ModelRuntimeTask) -> None:
    config = load_config(settings).model_runtime
    with self._condition:
      if task.background and not config.background_model_enabled:
        raise RuntimeError("后台模型任务已关闭")
      if task.background and self._cooldown_active_locked(task.lane):
        reason = self._cooldown_reason.get(task.lane, "模型服务暂时不可用")
        raise RuntimeError(f"后台模型任务等待冷却：{reason}")
      if len(self._waiting) >= config.max_queue_size:
        raise RuntimeError("模型任务队列已满")
      if config.queue_policy == "reject" and not self._can_start_locked(task, config):
        raise RuntimeError("模型运行通道忙，当前配置不等待排队")

      self._waiting.append(task)
      self._condition.notify_all()
      while not self._can_start_locked(task, config):
        self._condition.wait(timeout=1.0)
        config = load_config(settings).model_runtime
        if task.background and not config.background_model_enabled:
          self._remove_waiting_locked(task)
          self._condition.notify_all()
          raise RuntimeError("后台模型任务已关闭")
        if task.background and self._cooldown_active_locked(task.lane):
          self._remove_waiting_locked(task)
          self._condition.notify_all()
          reason = self._cooldown_reason.get(task.lane, "模型服务暂时不可用")
          raise RuntimeError(f"后台模型任务等待冷却：{reason}")

      self._remove_waiting_locked(task)
      task.started_at = time.monotonic()
      task.started_at_iso = _now_iso()
      task.queue_wait_seconds = max(0.0, task.started_at - task.queued_at)
      self._active.append(task)

  def release(self, settings: Settings, task: ModelRuntimeTask, *, status: str) -> None:
    with self._condition:
      self._active = [item for item in self._active if item.task_id != task.task_id]
      task.finished_at_iso = _now_iso()
      if task.lane == "chat" and not task.background and not self._foreground_active_locked():
        self._last_foreground_finished_at = time.monotonic()
      self._condition.notify_all()
    if task.queue_wait_seconds >= 0.5:
      append_app_log(
        settings,
        (
          f"模型任务 {task.task_name} {status}，排队等待 "
          f"{task.queue_wait_seconds:.3f}s，通道 {task.lane}"
        ),
      )

  def mark_cooldown(self, lane: str, seconds: int, reason: str) -> None:
    if seconds <= 0:
      return
    normalized_lane = lane.strip().lower() or "chat"
    with self._condition:
      self._cooldown_until[normalized_lane] = max(
        self._cooldown_until.get(normalized_lane, 0.0),
        time.monotonic() + seconds,
      )
      self._cooldown_reason[normalized_lane] = reason
      self._condition.notify_all()

  def should_defer_background(self, settings: Settings) -> bool:
    config = load_config(settings).model_runtime
    with self._condition:
      if not config.background_model_enabled:
        return True
      if self._cooldown_active_locked("chat") or self._cooldown_active_locked("retrieval"):
        return True
      if self._foreground_active_locked() or self._foreground_waiting_locked():
        return True
      if self._retrieval_active_locked() or self._retrieval_waiting_locked():
        return True
      return self._idle_seconds_locked() < config.background_requires_idle_seconds

  def state(self, settings: Settings | None = None) -> dict[str, object]:
    config = load_config(settings).model_runtime if settings is not None else ModelRuntimeConfig()
    with self._condition:
      active = [item.snapshot() for item in self._active]
      waiting = [item.snapshot() for item in sorted(self._waiting, key=self._task_sort_key)]
      cooldowns = {
        lane: {
          "active": until > time.monotonic(),
          "remaining_seconds": max(0, int(until - time.monotonic())),
          "reason": self._cooldown_reason.get(lane, ""),
        }
        for lane, until in self._cooldown_until.items()
        if until > time.monotonic()
      }
      foreground_busy = self._foreground_active_locked() or self._foreground_waiting_locked()
      retrieval_busy = self._retrieval_active_locked() or self._retrieval_waiting_locked()
      return {
        "active": active,
        "waiting": waiting,
        "active_count": len(active),
        "waiting_count": len(waiting),
        "foreground_busy": foreground_busy,
        "retrieval_busy": retrieval_busy,
        "idle_seconds": round(self._idle_seconds_locked(), 3),
        "cooldowns": cooldowns,
        "config": config.model_dump(mode="json"),
      }

  def _can_start_locked(self, task: ModelRuntimeTask, config: ModelRuntimeConfig) -> bool:
    lane_waiting = [item for item in self._waiting if item.lane == task.lane]
    if lane_waiting and min(lane_waiting, key=self._task_sort_key).task_id != task.task_id:
      return False

    if task.lane == "chat":
      if self._active_lane_count_locked("chat") >= config.max_chat_concurrency:
        return False
      if task.background:
        if self._foreground_active_locked() or self._foreground_waiting_locked():
          return False
        return self._idle_seconds_locked() >= config.background_requires_idle_seconds
      return True

    if self._active_lane_count_locked("retrieval") >= config.max_retrieval_concurrency:
      return False
    if self._foreground_active_locked() or self._foreground_waiting_locked():
      return False
    if task.background:
      return self._idle_seconds_locked() >= config.background_requires_idle_seconds
    return True

  def _task_sort_key(self, task: ModelRuntimeTask) -> tuple[int, int]:
    return (task.priority, task.sequence)

  def _remove_waiting_locked(self, task: ModelRuntimeTask) -> None:
    self._waiting = [item for item in self._waiting if item.task_id != task.task_id]

  def _active_lane_count_locked(self, lane: str) -> int:
    return sum(1 for item in self._active if item.lane == lane)

  def _foreground_active_locked(self) -> bool:
    return any(item.lane == "chat" and not item.background for item in self._active)

  def _foreground_waiting_locked(self) -> bool:
    return any(item.lane == "chat" and not item.background for item in self._waiting)

  def _retrieval_active_locked(self) -> bool:
    return any(item.lane == "retrieval" for item in self._active)

  def _retrieval_waiting_locked(self) -> bool:
    return any(item.lane == "retrieval" for item in self._waiting)

  def _idle_seconds_locked(self) -> float:
    if self._foreground_active_locked():
      return 0.0
    return max(0.0, time.monotonic() - self._last_foreground_finished_at)

  def _cooldown_active_locked(self, lane: str) -> bool:
    return self._cooldown_until.get(lane, 0.0) > time.monotonic()


_MANAGER = ModelRuntimeManager()


@contextmanager
def model_runtime_slot(
  settings: Settings,
  *,
  lane: str,
  task_name: str,
  priority: int | None = None,
  source: str = "",
  project_id: str = "",
  chapter_id: str = "",
  background: bool | None = None,
):
  task = _MANAGER.create_task(
    task_name=task_name,
    lane=lane,
    priority=priority,
    source=source,
    project_id=project_id,
    chapter_id=chapter_id,
    background=background,
  )
  _MANAGER.acquire(settings, task)
  try:
    yield task
  except Exception:
    _MANAGER.release(settings, task, status="failed")
    raise
  else:
    _MANAGER.release(settings, task, status="completed")


def get_model_runtime_state(settings: Settings) -> dict[str, object]:
  return _MANAGER.state(settings)


def model_runtime_should_defer_background(settings: Settings) -> bool:
  return _MANAGER.should_defer_background(settings)


def mark_model_runtime_cooldown(settings: Settings, lane: str, reason: str) -> None:
  config = load_config(settings).model_runtime
  _MANAGER.mark_cooldown(lane, int(config.provider_cooldown_seconds), reason)


def reset_model_runtime_for_tests() -> None:
  global _MANAGER
  _MANAGER = ModelRuntimeManager()
