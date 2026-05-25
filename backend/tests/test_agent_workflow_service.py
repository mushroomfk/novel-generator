from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from novel_backend.models import AgentChatRequest, AgentMessage, AgentPlan, AgentPlanAction
from novel_backend.services.agent_workflow_service import (
  create_agent_workflow_run,
  load_agent_workflow_run,
  mark_stale_agent_workflows,
  workflow_path,
)


class AgentWorkflowServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.project_dir = Path(self._temp_dir.name) / "project"
    self.project_dir.mkdir(parents=True, exist_ok=True)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def _create_stale_run(self, task_id: str, *, action_status: str, age_seconds: int) -> None:
    payload = AgentChatRequest(
      project_id="project-1",
      messages=[AgentMessage(role="user", content="处理当前章节。")],
    )
    plan = AgentPlan(
      id=f"plan-{task_id}",
      title="测试计划",
      summary="测试工作流状态。",
      requires_confirmation=False,
      steps=["执行测试动作"],
      actions=[AgentPlanAction(kind="brainstorm", label="讨论方向", instruction="讨论方向。")],
    )
    create_agent_workflow_run(self.project_dir, task_id=task_id, payload=payload, plan=plan)
    path = workflow_path(self.project_dir, task_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    stale_at = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    data["status"] = "RUNNING"
    data["actions"][0]["status"] = action_status
    data["actions"][0]["updated_at"] = stale_at
    data["actions"][0]["heartbeat_at"] = stale_at if action_status == "RUNNING" else ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

  def test_marks_dispatched_action_as_timed_out(self) -> None:
    self._create_stale_run("task-ack-timeout", action_status="DISPATCHED", age_seconds=400)

    marked = mark_stale_agent_workflows(self.project_dir, ack_timeout_seconds=300, stall_timeout_seconds=1200)

    self.assertEqual(len(marked), 1)
    payload = load_agent_workflow_run(self.project_dir, "task-ack-timeout")
    assert payload is not None
    self.assertEqual(payload["status"], "TIMED_OUT")
    self.assertEqual(payload["actions"][0]["status"], "TIMED_OUT")
    self.assertEqual(payload["message"], "存在确认超时任务。")

  def test_marks_running_action_as_stalled(self) -> None:
    self._create_stale_run("task-stalled", action_status="RUNNING", age_seconds=1300)

    marked = mark_stale_agent_workflows(self.project_dir, ack_timeout_seconds=300, stall_timeout_seconds=1200)

    self.assertEqual(len(marked), 1)
    payload = load_agent_workflow_run(self.project_dir, "task-stalled")
    assert payload is not None
    self.assertEqual(payload["status"], "STALLED")
    self.assertEqual(payload["actions"][0]["status"], "STALLED")
    self.assertEqual(payload["message"], "存在执行超时任务。")


if __name__ == "__main__":
  unittest.main()
