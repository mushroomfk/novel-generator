from __future__ import annotations

from datetime import datetime, timezone

from novel_backend.utils.sse import encode_sse


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


class AgentEventEmitter:
  def __init__(self, task_id: str, thread_id: str = "") -> None:
    self.task_id = str(task_id or "").strip()
    self.thread_id = str(thread_id or "").strip()
    self._event_index = 0

  def _base(self) -> dict[str, object]:
    self._event_index += 1
    return {
      "task_id": self.task_id,
      "thread_id": self.thread_id,
      "event_id": f"{self.task_id}-{self._event_index}",
      "timestamp": _now_iso(),
    }

  def emit(
    self,
    event_name: str,
    payload: dict[str, object] | None = None,
    *,
    legacy_event: str | None = None,
    legacy_payload: object | None = None,
  ) -> list[str]:
    merged_payload = {
      **self._base(),
      **dict(payload or {}),
    }
    chunks = [encode_sse(event_name, merged_payload)]
    if legacy_event:
      chunks.append(encode_sse(legacy_event, legacy_payload if legacy_payload is not None else merged_payload))
    return chunks

  def session_started(self) -> list[str]:
    return self.emit(
      "session_started",
      {"status": "running"},
      legacy_event="started",
      legacy_payload={"task_id": self.task_id},
    )

  def plan_generated(self, plan: object, reply: str, task_pack_kind: str) -> list[str]:
    return self.emit(
      "plan_generated",
      {
        "plan": plan,
        "reply": reply,
        "task_pack_kind": task_pack_kind,
      },
    )

  def plan_confirm_required(self, plan_id: str) -> list[str]:
    return self.emit(
      "plan_confirm_required",
      {
        "plan_id": plan_id,
        "status": "waiting_confirmation",
      },
    )

  def action_started(
    self,
    *,
    step: int,
    total: int,
    action_kind: str,
    label: str,
    task_pack_kind: str,
  ) -> list[str]:
    return self.emit(
      "action_started",
      {
        "step": step,
        "total": total,
        "action_kind": action_kind,
        "label": label,
        "task_pack_kind": task_pack_kind,
        "status": "running",
      },
      legacy_event="progress",
      legacy_payload={"step": step, "total": total, "message": label},
    )

  def action_result(
    self,
    *,
    step: int,
    total: int,
    action_kind: str,
    label: str,
    task_pack_kind: str,
    trace: object | None = None,
    artifacts: object | None = None,
    changes: object | None = None,
  ) -> list[str]:
    return self.emit(
      "action_result",
      {
        "step": step,
        "total": total,
        "action_kind": action_kind,
        "label": label,
        "task_pack_kind": task_pack_kind,
        "status": "completed",
        "trace": trace,
        "artifacts": artifacts or [],
        "changes": changes or [],
      },
    )

  def action_failed(
    self,
    *,
    step: int,
    total: int,
    action_kind: str,
    label: str,
    task_pack_kind: str,
    message: str,
  ) -> list[str]:
    return self.emit(
      "action_failed",
      {
        "step": step,
        "total": total,
        "action_kind": action_kind,
        "label": label,
        "task_pack_kind": task_pack_kind,
        "status": "failed",
        "message": str(message),
      },
    )

  def subtask_started(
    self,
    *,
    step: int,
    total: int,
    action_kind: str,
    label: str,
    subtask_id: str,
    role: str,
    capability: str,
    parallel_group: str = "",
  ) -> list[str]:
    return self.emit(
      "subtask_started",
      {
        "step": step,
        "total": total,
        "action_kind": action_kind,
        "label": label,
        "subtask_id": subtask_id,
        "role": role,
        "capability": capability,
        "parallel_group": parallel_group,
        "status": "running",
      },
    )

  def subtask_result(
    self,
    *,
    step: int,
    total: int,
    action_kind: str,
    label: str,
    subtask_id: str,
    role: str,
    capability: str,
    parallel_group: str = "",
    summary: str = "",
  ) -> list[str]:
    return self.emit(
      "subtask_result",
      {
        "step": step,
        "total": total,
        "action_kind": action_kind,
        "label": label,
        "subtask_id": subtask_id,
        "role": role,
        "capability": capability,
        "parallel_group": parallel_group,
        "summary": summary,
        "status": "completed",
      },
    )

  def subtask_failed(
    self,
    *,
    step: int,
    total: int,
    action_kind: str,
    label: str,
    subtask_id: str,
    role: str,
    capability: str,
    parallel_group: str = "",
    message: str = "",
  ) -> list[str]:
    return self.emit(
      "subtask_failed",
      {
        "step": step,
        "total": total,
        "action_kind": action_kind,
        "label": label,
        "subtask_id": subtask_id,
        "role": role,
        "capability": capability,
        "parallel_group": parallel_group,
        "message": str(message),
        "status": "failed",
      },
    )

  def state_updated(self, state: object) -> list[str]:
    return self.emit("state_updated", {"state": state})

  def project_updated(self, project_detail: object) -> list[str]:
    return self.emit("project_updated", {"project_detail": project_detail})

  def session_result(self, result_payload: object) -> list[str]:
    return self.emit(
      "session_result",
      {"result": result_payload},
      legacy_event="result",
      legacy_payload=result_payload,
    )

  def session_error(self, message: str) -> list[str]:
    return self.emit(
      "session_error",
      {
        "status": "failed",
        "message": str(message),
      },
      legacy_event="error",
      legacy_payload={"task_id": self.task_id, "message": str(message)},
    )

  def session_finished(self, status: str = "completed") -> list[str]:
    return self.emit(
      "session_finished",
      {"status": status},
      legacy_event="done",
      legacy_payload={"task_id": self.task_id, "status": status},
    )
