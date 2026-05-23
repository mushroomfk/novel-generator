from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_backend.api import projects as project_api
from novel_backend.config import Settings
from novel_backend.models import (
  AgentArtifact,
  AgentChatRequest,
  AgentChatResult,
  AgentExecutionTrace,
  AgentMessage,
  AgentPlan,
  AgentPlanAction,
  BrainstormMessage,
  CreateProjectRequest,
  ModelConfig,
  SkillMaterializeRequest,
  SkillPackageImportRequest,
)
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.project_service import create_project
from novel_backend.services.self_evolution_service import (
  apply_self_evolution_draft,
  build_agent_capability_context,
  get_self_evolution_state,
  run_self_evolution_model_review,
  run_self_evolution_scheduled_tasks,
  run_writing_regression_suite,
  run_self_evolution_cycle,
  update_self_evolution_schedule,
  update_self_evolution_candidate_status,
)
from novel_backend.services.self_evolution_scheduler_service import SelfEvolutionScheduler
from novel_backend.services.skill_service import (
  export_skill_package,
  import_skill_package,
  list_skill_versions,
  materialize_skill,
  promote_skill_to_global,
  rollback_skill_version,
)
from novel_backend.services.skill_usage_service import get_skill_usage_state
from novel_backend.services.project_memory_service import load_manual_project_memory


class SelfEvolutionServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )
    self.project = create_project(
      self.settings,
      CreateProjectRequest(
        name="自学习回归",
        genre="悬疑",
        target_chapters=3,
        target_words=30000,
      ),
    )
    self.project_dir = Path(self.project.path)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_cycle_records_candidates_rules_usage_and_writing_evaluation(self) -> None:
    plan = AgentPlan(
      id="plan-self-evolution",
      title="续写第 1 章",
      summary="先补架构再写正文。",
      requires_confirmation=True,
      steps=["分析资料", "补架构", "写正文"],
      actions=[
        AgentPlanAction(kind="review_knowledge", label="分析资料", instruction="先看资料"),
        AgentPlanAction(kind="generate_architecture", label="补架构", instruction="补齐架构"),
        AgentPlanAction(
          kind="chapter_generate",
          label="写第 1 章",
          chapter_id="chapter-001",
          instruction="按港口悬疑写。",
          skill_ids=["user-harbor-flow"],
        ),
      ],
    )
    payload = AgentChatRequest(
      project_id=self.project.id,
      thread_id="thread-1",
      active_skill_ids=["user-harbor-flow"],
      messages=[
        AgentMessage(role="user", content="以后写港口追索章节，都按先看资料、再补架构、最后写正文的流程。")
      ],
    )
    result = AgentChatResult(
      task_id="task-self-evolution",
      mode="execution",
      reply="第 1 章已经写回项目。",
      state={
        "project_name": "自学习回归",
        "genre": "悬疑",
      },
      thread_id="thread-1",
      task_pack_kind="continuation",
      execution_trace=[
        AgentExecutionTrace(step=1, action_kind="review_knowledge", label="分析资料", status="completed"),
        AgentExecutionTrace(step=2, action_kind="generate_architecture", label="补架构", status="completed"),
        AgentExecutionTrace(step=3, action_kind="chapter_generate", label="写第 1 章", status="completed"),
      ],
      artifacts=[
        AgentArtifact(kind="knowledge_summary", title="资料分析", summary="已分析资料。"),
        AgentArtifact(
          kind="chapter_content",
          title="第 1 章",
          summary="正文已生成。",
          metadata={"chapter_id": "chapter-001", "chapter_index": 1},
        ),
      ],
      suggestions=["把这套处理方式保存成用户技能。"],
      changes=["已更新第 1 章正文"],
      can_save_discussion_summary=True,
    )

    artifact = run_self_evolution_cycle(
      self.settings,
      self.project_dir,
      payload=payload,
      plan=plan,
      result=result,
    )

    self.assertEqual(artifact.kind, "self_evolution_review")
    self.assertGreaterEqual(artifact.metadata["candidate_count"], 1)
    self.assertGreaterEqual(artifact.metadata["capability_rule_count"], 1)
    self.assertEqual(artifact.metadata["skill_usage_count"], 1)
    self.assertGreater(float(artifact.metadata["writing_score"]), 0)

    state = get_self_evolution_state(self.settings, self.project_dir)
    candidates = state["candidates"]["items"]
    self.assertTrue(any(item["kind"] == "skill" for item in candidates))
    self.assertTrue(any(item["kind"] == "capability" for item in candidates))
    self.assertTrue(state["capability_rules"]["rules"])
    self.assertTrue(state["writing_evaluations"])
    self.assertIn("quality_dimensions", state["writing_evaluations"][0])
    self.assertIn("trends", state["dashboard"])
    self.assertTrue(state["dashboard"]["trends"]["writing_scores"])
    capability_context = build_agent_capability_context(self.project_dir)
    self.assertIn("Agent 自学习调用规则", capability_context)
    self.assertIn("资料优先调用规则", capability_context)

    usage_records = state["skill_usage"]["records"]
    usage = next(item for item in usage_records if item["skill_id"] == "user-harbor-flow")
    self.assertEqual(usage["use_count"], 1)
    self.assertEqual(usage["success_count"], 1)

    memory_candidate = next(item for item in candidates if item["kind"] == "memory")
    updated = update_self_evolution_candidate_status(self.project_dir, memory_candidate["id"], "accepted")
    self.assertEqual(updated["status"], "accepted")
    self.assertTrue(updated["draft_id"])

    state_after_accept = get_self_evolution_state(self.settings, self.project_dir)
    draft = next(item for item in state_after_accept["drafts"]["items"] if item["id"] == updated["draft_id"])
    self.assertEqual(draft["kind"], "memory")
    self.assertEqual(draft["status"], "pending")

    applied = apply_self_evolution_draft(self.settings, self.project_dir, draft["id"])
    self.assertEqual(applied["status"], "applied")
    self.assertEqual(applied["result"]["type"], "memory")
    manual_entries = load_manual_project_memory(self.project_dir)
    self.assertTrue(any(memory_candidate["content"] in item.content for item in manual_entries))

    regression = run_writing_regression_suite(self.settings, self.project_dir)
    self.assertEqual(len(regression["cases"]), 4)
    self.assertIn(regression["status"], {"good", "watch", "risk"})

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "审查完成",
                  "failure_causes": ["没有明显失败"],
                  "improvement_suggestions": ["继续处理候选"],
                  "skill_actions": ["应用技能草案"],
                  "capability_actions": ["保留资料优先规则"],
                  "risk_notes": [],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ), patch("novel_backend.services.self_evolution_service._invoke_optional_reviewer_model", return_value=""):
      model_review = run_self_evolution_model_review(self.settings, self.project_dir)
    self.assertEqual(model_review["status"], "model")
    self.assertIn("继续处理候选", model_review["improvement_suggestions"])
    self.assertEqual(model_review["cross_review"]["status"], "not_configured")

    schedule = update_self_evolution_schedule(
      self.project_dir,
      {"enabled": True, "tasks": ["curate", "regression"], "interval_hours": 24},
    )
    self.assertTrue(schedule["enabled"])
    scheduler_result = asyncio.run(SelfEvolutionScheduler(self.settings).run_once())
    self.assertEqual(scheduler_result["checked_count"], 1)
    self.assertEqual(scheduler_result["results"][0]["status"], "completed")
    scheduled = run_self_evolution_scheduled_tasks(self.settings, self.project_dir, force=True)
    self.assertEqual(scheduled["status"], "completed")
    self.assertEqual([item["task"] for item in scheduled["ran"]], ["curate", "regression"])
    waiting = run_self_evolution_scheduled_tasks(self.settings, self.project_dir)
    self.assertEqual(waiting["status"], "waiting")

    state_after_review = get_self_evolution_state(self.settings, self.project_dir)
    self.assertTrue(state_after_review["writing_regression_runs"])
    self.assertTrue(state_after_review["model_reviews"])
    self.assertIn("pending_draft_count", state_after_review["dashboard"])

  def test_failed_cycle_records_failure_case_library_and_context(self) -> None:
    plan = AgentPlan(
      id="plan-self-evolution-failed",
      title="生成失败样本",
      summary="生成章节时失败。",
      requires_confirmation=True,
      steps=["写正文"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="写第 1 章",
          chapter_id="chapter-001",
          instruction="写正文",
        ),
      ],
    )
    payload = AgentChatRequest(
      project_id=self.project.id,
      thread_id="thread-failed",
      messages=[AgentMessage(role="user", content="写第一章，但当前章节材料不完整。")],
    )
    result = AgentChatResult(
      task_id="task-self-evolution-failed",
      mode="execution",
      reply="章节生成失败，缺少可用输入。",
      state={"project_name": "自学习回归"},
      thread_id="thread-failed",
      execution_trace=[
        AgentExecutionTrace(
          step=1,
          action_kind="chapter_generate",
          label="写第 1 章",
          status="failed",
          summary="缺少章节蓝图和当前章节正文。",
        ),
      ],
      artifacts=[],
      suggestions=[],
      changes=[],
    )

    artifact = run_self_evolution_cycle(
      self.settings,
      self.project_dir,
      payload=payload,
      plan=plan,
      result=result,
    )

    self.assertEqual(artifact.kind, "self_evolution_review")
    state = get_self_evolution_state(self.settings, self.project_dir)
    self.assertTrue(state["failure_cases"])
    self.assertEqual(state["dashboard"]["failure_case_count"], 1)
    self.assertEqual(state["dashboard"]["failure_case_groups"][0]["action_kind"], "chapter_generate")
    self.assertEqual(state["failure_cases"][0]["action_kind"], "chapter_generate")
    context = build_agent_capability_context(self.project_dir)
    self.assertIn("Agent 失败案例提醒", context)
    self.assertIn("chapter_generate", context)

  def test_self_evolution_project_api_reads_updates_and_curates(self) -> None:
    plan = AgentPlan(
      id="plan-self-evolution-api",
      title="资料分析",
      summary="先分析资料。",
      requires_confirmation=True,
      steps=["分析资料"],
      actions=[
        AgentPlanAction(kind="review_knowledge", label="分析资料", instruction="先看资料"),
      ],
    )
    payload = AgentChatRequest(
      project_id=self.project.id,
      thread_id="thread-api",
      messages=[
        AgentMessage(role="user", content="以后遇到资料分析，都先整理事实再继续。")
      ],
    )
    result = AgentChatResult(
      task_id="task-self-evolution-api",
      mode="execution",
      reply="已分析资料。",
      state={"project_name": "自学习回归"},
      thread_id="thread-api",
      execution_trace=[
        AgentExecutionTrace(step=1, action_kind="review_knowledge", label="分析资料", status="completed"),
      ],
      artifacts=[AgentArtifact(kind="knowledge_summary", title="资料分析", summary="已分析资料。")],
      suggestions=["把这套处理方式保存成用户技能。"],
      can_save_discussion_summary=True,
    )
    run_self_evolution_cycle(
      self.settings,
      self.project_dir,
      payload=payload,
      plan=plan,
      result=result,
    )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=self.settings)))

    state_response = project_api.get_project_self_evolution(request, self.project.id)
    state_payload = state_response["data"]
    candidate_id = state_payload["candidates"]["items"][0]["id"]
    skill_candidate = next(item for item in state_payload["candidates"]["items"] if item["kind"] == "skill")
    self.assertTrue(state_payload["capability_rules"]["rules"])

    update_response = project_api.patch_project_self_evolution_candidate(
      request,
      self.project.id,
      candidate_id,
      project_api.SelfEvolutionCandidateUpdateRequest(status="rejected"),
    )
    self.assertEqual(update_response["data"]["status"], "rejected")

    accepted_response = project_api.patch_project_self_evolution_candidate(
      request,
      self.project.id,
      skill_candidate["id"],
      project_api.SelfEvolutionCandidateUpdateRequest(status="accepted"),
    )
    draft_id = accepted_response["data"]["draft_id"]
    self.assertTrue(draft_id)

    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      apply_response = project_api.post_project_self_evolution_draft_apply(request, self.project.id, draft_id)
    self.assertEqual(apply_response["data"]["status"], "applied")
    self.assertEqual(apply_response["data"]["result"]["type"], "skill")

    curate_response = project_api.post_project_self_evolution_curate(request, self.project.id)
    self.assertIn("checked_count", curate_response["data"])

    regression_response = project_api.post_project_self_evolution_regression(request, self.project.id)
    self.assertEqual(len(regression_response["data"]["cases"]), 4)

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "API 审查完成",
                  "failure_causes": [],
                  "improvement_suggestions": ["继续观察写作回归"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ), patch("novel_backend.services.self_evolution_service._invoke_optional_reviewer_model", return_value=""):
      model_review_response = project_api.post_project_self_evolution_model_review(request, self.project.id)
    self.assertIn(model_review_response["data"]["status"], {"model", "model_incomplete"})
    self.assertIn("cross_review", model_review_response["data"])

    schedule_response = project_api.put_project_self_evolution_schedule(
      request,
      self.project.id,
      project_api.SelfEvolutionScheduleUpdateRequest(enabled=True, interval_hours=24, tasks=["curate"]),
    )
    self.assertTrue(schedule_response["data"]["enabled"])
    schedule_run_response = project_api.post_project_self_evolution_schedule_run(request, self.project.id)
    self.assertEqual(schedule_run_response["data"]["status"], "completed")
    self.assertEqual(schedule_run_response["data"]["ran"][0]["task"], "curate")

  def test_materialized_skill_records_patch_usage(self) -> None:
    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      created = materialize_skill(
        self.settings,
        SkillMaterializeRequest(
          project_id=self.project.id,
          messages=[
            BrainstormMessage(role="user", content="以后处理章节去 AI，都按先看剧情事实、再处理模板腔、最后检查人物对白差异。"),
            BrainstormMessage(role="assistant", content="可以，按这个流程整理。"),
          ],
          action="create",
          selected_chapter_id="chapter-001",
        ),
      )

    usage_state = get_skill_usage_state(self.settings)
    record = next(item for item in usage_state["records"] if item["skill_id"] == created.skill.id)
    self.assertEqual(record["patch_count"], 1)
    self.assertEqual(record["last_patch_action"], "create")

    usage_path = self.settings.data_dir / "skills" / ".usage.json"
    self.assertTrue(usage_path.exists())
    payload = json.loads(usage_path.read_text(encoding="utf-8"))
    self.assertIn(created.skill.id, payload["records"])

    versions = list_skill_versions(self.settings, created.skill.id)
    self.assertEqual(versions["skill_id"], created.skill.id)
    self.assertTrue(versions["items"])
    self.assertIn("diff_from_current", versions["items"][0])

    promoted = promote_skill_to_global(self.settings, created.skill.id)
    self.assertEqual(promoted["scope"], "global")
    self.assertIn("diff", promoted)

    versions_after_promote = list_skill_versions(self.settings, created.skill.id)
    rollback_target = next(
      item for item in versions_after_promote["items"]
      if item["reason"] == "before_promote_global"
    )
    rolled_back = rollback_skill_version(self.settings, created.skill.id, rollback_target["id"])
    self.assertEqual(rolled_back["rolled_back_to"], rollback_target["id"])

    package = export_skill_package(self.settings, created.skill.id)
    self.assertEqual(package["type"], "gaoxia_skill_package")
    imported = import_skill_package(
      self.settings,
      SkillPackageImportRequest(package=package, strategy="create_copy"),
    )
    self.assertNotEqual(imported["skill_id"], created.skill.id)
    imported_versions = list_skill_versions(self.settings, imported["skill_id"])
    self.assertTrue(imported_versions["items"])

    usage_state_after = get_skill_usage_state(self.settings)
    updated_record = next(item for item in usage_state_after["records"] if item["skill_id"] == created.skill.id)
    self.assertGreaterEqual(updated_record["patch_count"], 3)
    self.assertEqual(updated_record["last_patch_action"], "rollback")


if __name__ == "__main__":
  unittest.main()
