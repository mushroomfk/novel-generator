from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from novel_backend.models import AgentChatRequest, AgentMessage, AgentPlan, AgentPlanAction
from novel_backend.services.agent_workflow_service import (
  create_agent_workflow_run,
  agent_workflow_interrupt_message,
  heartbeat_agent_workflow_action,
  load_agent_workflow_run,
  mark_stale_agent_workflows,
  record_agent_workflow_subtask,
  request_agent_workflow_interrupt,
  update_agent_workflow_action,
  workflow_summary,
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

  def test_subtask_filename_is_cross_platform_safe(self) -> None:
    self._create_stale_run("task-subtask", action_status="RUNNING", age_seconds=1)

    record_agent_workflow_subtask(
      self.project_dir,
      "task-subtask",
      step=1,
      subtask_id="chapter_generate:writer",
      role="写作 agent",
      capability="生成候选正文。",
      status="RUNNING",
    )

    subtask_files = list((workflow_path(self.project_dir, "task-subtask").parent / "subtasks").glob("*.json"))
    self.assertEqual(len(subtask_files), 1)
    self.assertNotIn(":", subtask_files[0].name)
    self.assertEqual(subtask_files[0].name, "chapter_generate_writer.json")

  def test_subtask_filename_avoids_windows_reserved_names(self) -> None:
    self._create_stale_run("task-windows-reserved", action_status="RUNNING", age_seconds=1)

    record_agent_workflow_subtask(
      self.project_dir,
      "task-windows-reserved",
      step=1,
      subtask_id="CON",
      role="写作 agent",
      capability="生成候选正文。",
      status="RUNNING",
    )

    subtask_files = list((workflow_path(self.project_dir, "task-windows-reserved").parent / "subtasks").glob("*.json"))
    self.assertEqual(len(subtask_files), 1)
    self.assertEqual(subtask_files[0].name, "subtask_CON.json")

  def test_interrupt_request_marks_run_cancelling_and_summary_is_recoverable(self) -> None:
    self._create_stale_run("task-interrupt", action_status="RUNNING", age_seconds=1)

    request_agent_workflow_interrupt(self.project_dir, "task-interrupt", message="作者停止长任务。")

    payload = load_agent_workflow_run(self.project_dir, "task-interrupt")
    assert payload is not None
    self.assertEqual(payload["status"], "CANCELLING")
    self.assertTrue(payload["interrupt_requested"])
    self.assertEqual(agent_workflow_interrupt_message(self.project_dir, "task-interrupt"), "作者停止长任务。")
    summary = workflow_summary(self.project_dir, "task-interrupt")
    self.assertEqual(summary["status"], "CANCELLING")
    self.assertTrue(summary["interrupt_requested"])
    self.assertEqual(summary["actions"][0]["status"], "RUNNING")
    self.assertEqual(summary["actions"][0]["label"], "讨论方向")
    history_statuses = [item["status"] for item in payload["actions"][0]["status_history"]]
    self.assertIn("CANCEL_REQUESTED", history_statuses)

  def test_workflow_summary_exposes_runtime_status_rows(self) -> None:
    payload = AgentChatRequest(
      project_id="project-1",
      messages=[AgentMessage(role="user", content="先分析资料，再续写第 2 章。")],
    )
    plan = AgentPlan(
      id="plan-runtime-status",
      title="运行状态测试",
      summary="验证前端运行状态需要的字段。",
      requires_confirmation=False,
      steps=["分析资料", "续写章节"],
      actions=[
        AgentPlanAction(kind="review_knowledge", label="分析资料", instruction="整理本章资料。"),
        AgentPlanAction(
          kind="chapter_generate",
          label="续写第 2 章",
          chapter_id="chapter-002",
          instruction="接续上一章。",
          task_pack_kind="continuation",
        ),
      ],
    )
    create_agent_workflow_run(self.project_dir, task_id="task-runtime-status", payload=payload, plan=plan)

    update_agent_workflow_action(
      self.project_dir,
      "task-runtime-status",
      step=1,
      status="SUCCEEDED",
      message="资料已整理完成。",
      contract={"status": "pass"},
      output_validation={"status": "pass"},
    )
    update_agent_workflow_action(
      self.project_dir,
      "task-runtime-status",
      step=2,
      status="RUNNING",
      message="正在生成正文。",
    )
    heartbeat_agent_workflow_action(self.project_dir, "task-runtime-status", step=2)
    record_agent_workflow_subtask(
      self.project_dir,
      "task-runtime-status",
      step=2,
      subtask_id="chapter_generate:writer",
      role="写作 agent",
      capability="生成候选正文。",
      status="RUNNING",
      summary="正在写正文候选。",
    )

    summary = workflow_summary(self.project_dir, "task-runtime-status")

    self.assertEqual(summary["status"], "RUNNING")
    self.assertFalse(summary["interrupt_requested"])
    self.assertEqual(summary["action_statuses"], [
      {"step": 1, "kind": "review_knowledge", "status": "SUCCEEDED"},
      {"step": 2, "kind": "chapter_generate", "status": "RUNNING"},
    ])
    self.assertEqual(summary["actions"][0]["label"], "分析资料")
    self.assertEqual(summary["actions"][0]["message"], "资料已整理完成。")
    self.assertEqual(summary["actions"][1]["label"], "续写第 2 章")
    self.assertEqual(summary["actions"][1]["chapter_id"], "chapter-002")
    self.assertEqual(summary["actions"][1]["message"], "正在生成正文。")
    self.assertEqual(summary["actions"][1]["subtasks"][0]["subtask_id"], "chapter_generate:writer")
    self.assertEqual(summary["actions"][1]["subtasks"][0]["status"], "RUNNING")
    self.assertEqual(summary["actions"][1]["subtasks"][0]["summary"], "正在写正文候选。")


if __name__ == "__main__":
  unittest.main()
