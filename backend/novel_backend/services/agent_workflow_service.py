from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from novel_backend.models import AgentChatRequest, AgentPlan, AgentPlanAction
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_RUNS_DIRNAME = "runs"
_WORKFLOW_FILENAME = "workflow.json"
_WORKFLOW_SCHEMA_VERSION = "1"
_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "BLOCKED", "TIMED_OUT", "STALLED", "CANCELLED"}
_OPEN_ACTION_STATUSES = {"DISPATCHED", "ACKED", "RUNNING"}
_SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9_.-]+")
_WINDOWS_RESERVED_FILENAMES = {
  "CON",
  "PRN",
  "AUX",
  "NUL",
  *(f"COM{index}" for index in range(1, 10)),
  *(f"LPT{index}" for index in range(1, 10)),
}


def _now() -> datetime:
  return datetime.now(timezone.utc)


def _now_iso() -> str:
  return _now().isoformat()


def _runs_dir(project_dir: Path) -> Path:
  return Path(project_dir) / ".gaoxia" / _RUNS_DIRNAME


def workflow_run_dir(project_dir: Path, task_id: str) -> Path:
  return _runs_dir(project_dir) / str(task_id)


def workflow_path(project_dir: Path, task_id: str) -> Path:
  return workflow_run_dir(project_dir, task_id) / _WORKFLOW_FILENAME


def _safe_filename(value: str) -> str:
  cleaned = _SAFE_FILENAME_PATTERN.sub("_", str(value or "").strip()).strip(" .")
  cleaned = cleaned[:120].strip(" .") or "subtask"
  stem = cleaned.split(".", 1)[0].upper()
  if stem in _WINDOWS_RESERVED_FILENAMES:
    cleaned = f"subtask_{cleaned}"
  return cleaned[:120].strip(" .") or "subtask"


def _compact_message(message: object) -> dict[str, object]:
  role = str(getattr(message, "role", "") or "")
  content = str(getattr(message, "content", "") or "")
  return {
    "role": role,
    "content_preview": content[:600],
    "content_length": len(content),
  }


def _payload_snapshot(payload: AgentChatRequest) -> dict[str, object]:
  return {
    "project_id": payload.project_id,
    "thread_id": payload.thread_id,
    "selected_chapter_id": payload.selected_chapter_id,
    "reference_filenames": list(payload.reference_filenames),
    "active_skill_ids": list(payload.active_skill_ids),
    "style_name": payload.style_name,
    "xp_preset": payload.xp_preset,
    "messages": [_compact_message(item) for item in payload.messages[-8:]],
  }


def _action_snapshot(index: int, action: AgentPlanAction) -> dict[str, object]:
  return {
    "step": index,
    "kind": action.kind,
    "label": action.label,
    "status": "DISPATCHED",
    "task_pack_kind": action.task_pack_kind,
    "chapter_id": action.chapter_id,
    "mode": action.mode,
    "instruction_preview": str(action.instruction or "")[:800],
    "created_at": _now_iso(),
    "updated_at": _now_iso(),
    "acked_at": "",
    "started_at": "",
    "completed_at": "",
    "heartbeat_at": "",
    "message": "",
    "contract": {},
    "output_validation": {},
    "status_history": [
      {
        "status": "DISPATCHED",
        "at": _now_iso(),
        "message": "任务已派发。",
      }
    ],
    "subtasks": [],
  }


def create_agent_workflow_run(
  project_dir: Path,
  *,
  task_id: str,
  payload: AgentChatRequest,
  plan: AgentPlan,
  preflight: dict[str, object] | None = None,
) -> dict[str, object]:
  path = workflow_path(project_dir, task_id)
  path.parent.mkdir(parents=True, exist_ok=True)
  now = _now_iso()
  data = {
    "schema_version": _WORKFLOW_SCHEMA_VERSION,
    "task_id": task_id,
    "project_id": payload.project_id,
    "thread_id": payload.thread_id,
    "status": "RUNNING",
    "interrupt_requested": False,
    "interrupt_requested_at": "",
    "interrupt_message": "",
    "created_at": now,
    "updated_at": now,
    "completed_at": "",
    "plan": plan.model_dump(mode="json"),
    "payload": _payload_snapshot(payload),
    "preflight": preflight or {},
    "actions": [_action_snapshot(index, action) for index, action in enumerate(plan.actions, start=1)],
  }
  atomic_write_json(path, data)
  return data


def load_agent_workflow_run(project_dir: Path, task_id: str) -> dict[str, object] | None:
  data = read_json(workflow_path(project_dir, task_id), None)
  return data if isinstance(data, dict) else None


def _save_workflow(project_dir: Path, task_id: str, data: dict[str, object]) -> dict[str, object]:
  data["schema_version"] = _WORKFLOW_SCHEMA_VERSION
  data["updated_at"] = _now_iso()
  atomic_write_json(workflow_path(project_dir, task_id), data)
  return data


def _action_by_step(data: dict[str, object], step: int) -> dict[str, object] | None:
  actions = data.get("actions")
  if not isinstance(actions, list):
    return None
  for item in actions:
    if isinstance(item, dict) and int(item.get("step") or 0) == int(step):
      return item
  return None


def _append_status_history(target: dict[str, object], *, status: str, at: str, message: str) -> None:
  history = target.setdefault("status_history", [])
  if isinstance(history, list):
    history.append({"status": status, "at": at, "message": message})
    target["status_history"] = history[-80:]


def request_agent_workflow_interrupt(
  project_dir: Path,
  task_id: str,
  *,
  message: str = "用户请求停止当前执行。",
) -> dict[str, object]:
  data = load_agent_workflow_run(project_dir, task_id)
  if data is None:
    return {"task_id": task_id, "status": "missing"}
  if str(data.get("status") or "") in _TERMINAL_STATUSES:
    return data
  now = _now_iso()
  interrupt_message = str(message or "").strip() or "用户请求停止当前执行。"
  data["interrupt_requested"] = True
  data["interrupt_requested_at"] = now
  data["interrupt_message"] = interrupt_message
  data["status"] = "CANCELLING"
  _append_status_history(data, status="CANCELLING", at=now, message=interrupt_message)
  actions = data.get("actions")
  if isinstance(actions, list):
    for action in actions:
      if not isinstance(action, dict):
        continue
      if str(action.get("status") or "") in _OPEN_ACTION_STATUSES:
        _append_status_history(action, status="CANCEL_REQUESTED", at=now, message=interrupt_message)
        action["updated_at"] = now
  return _save_workflow(project_dir, task_id, data)


def agent_workflow_interrupt_message(project_dir: Path, task_id: str) -> str:
  data = load_agent_workflow_run(project_dir, task_id)
  if not isinstance(data, dict):
    return ""
  status = str(data.get("status") or "")
  if status == "CANCELLED":
    return str(data.get("message") or data.get("interrupt_message") or "执行已停止。")
  if bool(data.get("interrupt_requested")) and status not in _TERMINAL_STATUSES:
    return str(data.get("interrupt_message") or "用户请求停止当前执行。")
  return ""


def update_agent_workflow_preflight(project_dir: Path, task_id: str, preflight: dict[str, object]) -> dict[str, object]:
  data = load_agent_workflow_run(project_dir, task_id)
  if data is None:
    return {}
  data["preflight"] = preflight
  status = str(preflight.get("status") or "")
  if status == "blocked":
    data["status"] = "BLOCKED"
  return _save_workflow(project_dir, task_id, data)


def update_agent_workflow_action(
  project_dir: Path,
  task_id: str,
  *,
  step: int,
  status: str,
  message: str = "",
  contract: dict[str, object] | None = None,
  output_validation: dict[str, object] | None = None,
) -> dict[str, object]:
  data = load_agent_workflow_run(project_dir, task_id)
  if data is None:
    return {}
  action = _action_by_step(data, step)
  if action is None:
    return data
  normalized_status = str(status or "").strip().upper() or "RUNNING"
  now = _now_iso()
  action["status"] = normalized_status
  action["updated_at"] = now
  action["message"] = message
  if normalized_status == "ACKED":
    action["acked_at"] = action.get("acked_at") or now
  if normalized_status == "RUNNING":
    action["started_at"] = action.get("started_at") or now
    action["heartbeat_at"] = now
  if normalized_status in _TERMINAL_STATUSES:
    action["completed_at"] = action.get("completed_at") or now
  if contract is not None:
    action["contract"] = contract
  if output_validation is not None:
    action["output_validation"] = output_validation
  history = action.setdefault("status_history", [])
  if isinstance(history, list):
    history.append({"status": normalized_status, "at": now, "message": message})
    action["status_history"] = history[-80:]
  if normalized_status in {"FAILED", "BLOCKED", "TIMED_OUT", "STALLED", "CANCELLED"}:
    data["status"] = normalized_status
  elif data.get("status") not in _TERMINAL_STATUSES and data.get("status") != "CANCELLING":
    data["status"] = "RUNNING"
  return _save_workflow(project_dir, task_id, data)


def heartbeat_agent_workflow_action(project_dir: Path, task_id: str, *, step: int) -> dict[str, object]:
  data = load_agent_workflow_run(project_dir, task_id)
  if data is None:
    return {}
  action = _action_by_step(data, step)
  if action is None:
    return data
  now = _now_iso()
  action["heartbeat_at"] = now
  action["updated_at"] = now
  history = action.setdefault("status_history", [])
  if isinstance(history, list):
    history.append({"status": "RUNNING", "at": now, "message": "heartbeat"})
    action["status_history"] = history[-80:]
  return _save_workflow(project_dir, task_id, data)


def record_agent_workflow_subtask(
  project_dir: Path,
  task_id: str,
  *,
  step: int,
  subtask_id: str,
  role: str,
  capability: str,
  status: str,
  parallel_group: str = "",
  summary: str = "",
  allowed_outputs: list[str] | None = None,
) -> dict[str, object]:
  data = load_agent_workflow_run(project_dir, task_id)
  if data is None:
    return {}
  action = _action_by_step(data, step)
  if action is None:
    return data
  normalized_status = str(status or "").strip().upper() or "RUNNING"
  now = _now_iso()
  subtask = {
    "subtask_id": subtask_id,
    "role": role,
    "capability": capability,
    "parallel_group": parallel_group,
    "status": normalized_status,
    "summary": summary,
    "allowed_outputs": list(allowed_outputs or []),
    "updated_at": now,
  }
  subtasks = action.setdefault("subtasks", [])
  if not isinstance(subtasks, list):
    subtasks = []
  matched = False
  for index, item in enumerate(subtasks):
    if isinstance(item, dict) and item.get("subtask_id") == subtask_id:
      created_at = item.get("created_at") or now
      subtasks[index] = {**item, **subtask, "created_at": created_at}
      matched = True
      break
  if not matched:
    subtasks.append({**subtask, "created_at": now})
  action["subtasks"] = subtasks
  subtask_dir = workflow_run_dir(project_dir, task_id) / "subtasks"
  subtask_dir.mkdir(parents=True, exist_ok=True)
  subtask_path = subtask_dir / f"{_safe_filename(subtask_id)}.json"
  existing = read_json(subtask_path, None)
  history = existing.get("history") if isinstance(existing, dict) else []
  if not isinstance(history, list):
    history = []
  history.append({"status": normalized_status, "at": now, "summary": summary})
  atomic_write_json(
    subtask_path,
    {
      **subtask,
      "task_id": task_id,
      "step": step,
      "history": history[-80:],
    },
  )
  return _save_workflow(project_dir, task_id, data)


def complete_agent_workflow_run(
  project_dir: Path,
  task_id: str,
  *,
  status: str,
  message: str = "",
) -> dict[str, object]:
  data = load_agent_workflow_run(project_dir, task_id)
  if data is None:
    return {}
  normalized_status = str(status or "").strip().upper() or "SUCCEEDED"
  if normalized_status == "CANCELLED":
    now = _now_iso()
    actions = data.get("actions")
    if isinstance(actions, list):
      for action in actions:
        if not isinstance(action, dict):
          continue
        if str(action.get("status") or "") in _OPEN_ACTION_STATUSES:
          action["status"] = "CANCELLED"
          action["updated_at"] = now
          action["completed_at"] = action.get("completed_at") or now
          action["message"] = message or str(data.get("interrupt_message") or "执行已停止。")
          _append_status_history(action, status="CANCELLED", at=now, message=str(action["message"]))
  data["status"] = normalized_status
  data["completed_at"] = _now_iso()
  data["message"] = message
  return _save_workflow(project_dir, task_id, data)


def mark_stale_agent_workflows(
  project_dir: Path,
  *,
  ack_timeout_seconds: int = 300,
  stall_timeout_seconds: int = 1200,
) -> list[dict[str, object]]:
  marked: list[dict[str, object]] = []
  root = _runs_dir(project_dir)
  if not root.exists():
    return marked
  now = _now()
  for path in root.glob(f"*/{_WORKFLOW_FILENAME}"):
    data = read_json(path, None)
    if not isinstance(data, dict) or str(data.get("status") or "") in _TERMINAL_STATUSES:
      continue
    changed = False
    terminal_status = ""
    actions = data.get("actions")
    if not isinstance(actions, list):
      continue
    for action in actions:
      if not isinstance(action, dict):
        continue
      status = str(action.get("status") or "")
      updated_at_raw = str(action.get("updated_at") or action.get("created_at") or "")
      try:
        updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
      except ValueError:
        continue
      if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
      age = now - updated_at.astimezone(timezone.utc)
      marked_at = _now_iso()
      if status == "DISPATCHED" and age > timedelta(seconds=ack_timeout_seconds):
        action["status"] = "TIMED_OUT"
        action["updated_at"] = marked_at
        action["completed_at"] = action.get("completed_at") or marked_at
        action["message"] = "任务派发后未确认。"
        history = action.setdefault("status_history", [])
        if isinstance(history, list):
          history.append({"status": "TIMED_OUT", "at": marked_at, "message": action["message"]})
          action["status_history"] = history[-80:]
        terminal_status = "TIMED_OUT" if terminal_status != "STALLED" else terminal_status
        changed = True
      elif status == "RUNNING" and age > timedelta(seconds=stall_timeout_seconds):
        action["status"] = "STALLED"
        action["updated_at"] = marked_at
        action["completed_at"] = action.get("completed_at") or marked_at
        action["message"] = "任务运行中长时间没有心跳。"
        history = action.setdefault("status_history", [])
        if isinstance(history, list):
          history.append({"status": "STALLED", "at": marked_at, "message": action["message"]})
          action["status_history"] = history[-80:]
        terminal_status = "STALLED"
        changed = True
    if changed:
      data["status"] = terminal_status or "STALLED"
      data["updated_at"] = _now_iso()
      data["completed_at"] = data.get("completed_at") or data["updated_at"]
      data["message"] = "存在执行超时任务。" if data["status"] == "STALLED" else "存在确认超时任务。"
      atomic_write_json(path, data)
      marked.append(data)
  return marked


def workflow_summary(project_dir: Path, task_id: str) -> dict[str, Any]:
  data = load_agent_workflow_run(project_dir, task_id)
  if not isinstance(data, dict):
    return {"task_id": task_id, "status": "missing"}
  actions = data.get("actions")
  action_statuses = [
    {
      "step": item.get("step"),
      "kind": item.get("kind"),
      "status": item.get("status"),
    }
    for item in actions
    if isinstance(item, dict)
  ] if isinstance(actions, list) else []
  action_details = [
    {
      "step": item.get("step"),
      "kind": item.get("kind"),
      "label": item.get("label"),
      "status": item.get("status"),
      "message": item.get("message"),
      "task_pack_kind": item.get("task_pack_kind"),
      "chapter_id": item.get("chapter_id"),
      "mode": item.get("mode"),
      "updated_at": item.get("updated_at"),
      "subtasks": [
        {
          "subtask_id": subtask.get("subtask_id"),
          "role": subtask.get("role"),
          "capability": subtask.get("capability"),
          "parallel_group": subtask.get("parallel_group"),
          "status": subtask.get("status"),
          "summary": subtask.get("summary"),
          "updated_at": subtask.get("updated_at"),
        }
        for subtask in item.get("subtasks", [])
        if isinstance(subtask, dict)
      ] if isinstance(item.get("subtasks"), list) else [],
    }
    for item in actions
    if isinstance(item, dict)
  ] if isinstance(actions, list) else []
  return {
    "task_id": task_id,
    "status": data.get("status", ""),
    "message": data.get("message", ""),
    "interrupt_requested": bool(data.get("interrupt_requested")),
    "interrupt_requested_at": data.get("interrupt_requested_at", ""),
    "interrupt_message": data.get("interrupt_message", ""),
    "updated_at": data.get("updated_at", ""),
    "completed_at": data.get("completed_at", ""),
    "path": str(workflow_path(project_dir, task_id)),
    "action_statuses": action_statuses,
    "actions": action_details,
  }
