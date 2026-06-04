from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_backend.api import projects as project_api
from novel_backend.api import studio as studio_api
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
  ChapterRewriteRequest,
  ChapterUpdateRequest,
  CreateProjectRequest,
  ModelConfig,
  ObsidianVaultConfig,
  SkillMaterializeRequest,
  SkillPackageImportRequest,
)
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.log_service import append_prompt_history
from novel_backend.services.project_service import create_project, get_project_detail, update_chapter_content, update_project_obsidian_config
from novel_backend.services.self_evolution_service import (
  apply_self_evolution_draft,
  build_project_humanize_evolution_context,
  build_agent_capability_context,
  get_self_evolution_state,
  run_self_evolution_humanize_patrol,
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
from novel_backend.services.project_narrative_state_service import (
  load_project_narrative_state,
  record_project_narrative_state_observation,
)


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

    (self.project_dir / "chapters" / "001.md").write_text(
      "# 第一章 雨夜靠港\n"
      "此外，林追站在旧码头边，空气仿佛凝固。"
      "这不仅仅是一场普通的会面，更是他命运转折的重要一步。"
      "他感到一种说不清的恐惧，内心深处涌起复杂的情绪。"
      "这个眼神意味着真正的危险。总的来说，故事才刚刚开始。",
      encoding="utf-8",
    )
    regression = run_writing_regression_suite(self.settings, self.project_dir)
    self.assertEqual(len(regression["cases"]), 4)
    self.assertIn(regression["status"], {"good", "watch", "risk"})
    benchmark = regression["golden_evaluator_benchmark"]
    self.assertEqual(benchmark["case_count"], 4)
    self.assertGreaterEqual(benchmark["recall"], 0.75)
    self.assertGreaterEqual(benchmark["false_positive_control"], 1.0)
    humanize_ab = regression["humanize_ab_benchmark"]
    self.assertEqual(humanize_ab["case_count"], 3)
    self.assertGreaterEqual(humanize_ab["average_delta"], 20)
    self.assertTrue(humanize_ab["distilled_rules"])
    self.assertIn("project_probe", humanize_ab)
    sample_pool = humanize_ab["project_sample_pool"]
    self.assertGreaterEqual(sample_pool["sample_count"], 1)
    self.assertEqual(sample_pool["samples"][0]["chapter_id"], "chapter-001")
    self.assertTrue(sample_pool["top_issue_labels"])
    self.assertLess(sample_pool["average_score"], 92)
    self.assertTrue(any("真实章节样本池重点" in item for item in humanize_ab["distilled_rules"]))

    append_prompt_history(
      self.settings,
      {
        "task": "chapter_humanize",
        "model": "demo-model",
        "prompt": "去 AI",
        "response": json.dumps(
          {
            "revised": "此外，空气仿佛凝固。这个眼神意味着真正的危险。总的来说，故事才刚刚开始。"
          },
          ensure_ascii=False,
        ),
        "status": "completed",
        "elapsed": 0.1,
      },
    )
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=[
        {
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
        {
          "choices": [
            {
              "message": {
                "content": json.dumps(
                  {
                    "summary": "自然度偏弱，人物声音还不够分开。",
                    "naturalness_score": 62,
                    "ai_flavor_score": 38,
                    "issues": [
                      {
                        "title": "人物声音同质",
                        "detail": "对白都在解释局势，缺少各自回避方式。",
                        "severity": "warning",
                        "evidence": "我们必须",
                      }
                    ],
                    "false_positive_notes": ["少量环境描写可保留，问题是密度过高。"],
                    "distilled_rules": ["对白先按人物目的改，再处理形容词和说话标签。"],
                    "rewrite_principles": ["保留动作后果，少用抽象情绪说明。"],
                    "sample_actions": ["抽查去 AI 历史结果的残留解释句。"],
                  },
                  ensure_ascii=False,
                )
              }
            }
          ]
        },
      ],
    ), patch("novel_backend.services.self_evolution_service._invoke_optional_reviewer_model", return_value=""):
      model_review = run_self_evolution_model_review(self.settings, self.project_dir)
    self.assertEqual(model_review["status"], "model")
    self.assertIn("继续处理候选", model_review["improvement_suggestions"])
    self.assertEqual(model_review["cross_review"]["status"], "not_configured")
    humanize_judge = model_review["humanize_model_judge"]
    self.assertEqual(humanize_judge["status"], "model")
    self.assertEqual(humanize_judge["naturalness_score"], 62)
    self.assertEqual(humanize_judge["history_sample_count"], 1)
    self.assertGreaterEqual(model_review["humanize_rule_update"]["inserted"], 1)
    humanize_context = build_project_humanize_evolution_context(self.project_dir)
    self.assertIn("对白先按人物目的改", humanize_context)
    from novel_backend.services.studio_service import _chapter_humanize_messages

    project_detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in project_detail.chapters if item.id == "chapter-001")
    messages = _chapter_humanize_messages(
      self.settings,
      ChapterRewriteRequest(project_id=self.project.id, chapter_id="chapter-001"),
      project_detail,
      chapter,
      "",
    )
    self.assertIn("项目去 AI 自学习规则", messages[1]["content"])
    self.assertIn("对白先按人物目的改", messages[1]["content"])

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
    self.assertIn("latest_humanize_ab_score", state_after_review["dashboard"])
    self.assertIn("latest_humanize_judge_score", state_after_review["dashboard"])
    self.assertTrue(state_after_review["humanize_evolution_rules"]["rules"])

  def test_humanize_patrol_runs_from_signal_and_waits_during_cooldown(self) -> None:
    (self.project_dir / "chapters" / "001.md").write_text(
      "# 第一章 雨夜靠港\n"
      "此外，林追站在旧码头边，空气仿佛凝固。"
      "这不仅仅是一场普通的会面，更是他命运转折的重要一步。"
      "他感到一种说不清的恐惧，内心深处涌起复杂的情绪。"
      "总的来说，故事才刚刚开始。",
      encoding="utf-8",
    )

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "巡检发现真实章节仍有模型腔。",
                  "naturalness_score": 58,
                  "ai_flavor_score": 42,
                  "issues": [
                    {
                      "title": "意义宣告太密",
                      "detail": "章节把人物行动解释成命运转折。",
                      "severity": "warning",
                      "evidence": "这不仅仅是",
                    }
                  ],
                  "distilled_rules": ["遇到意义宣告，先改成角色看得见的动作后果。"],
                  "rewrite_principles": ["保留事实顺序，只替换解释句。"],
                  "false_positive_notes": [],
                  "sample_actions": [],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      result = run_self_evolution_humanize_patrol(
        self.settings,
        self.project_dir,
        reason="heartbeat",
        force=True,
      )

    self.assertEqual(result["status"], "completed")
    self.assertEqual(result["review"]["status"], "humanize_patrol")
    self.assertEqual(result["humanize_model_judge"]["naturalness_score"], 58)
    self.assertGreaterEqual(result["humanize_rule_update"]["inserted"], 1)

    waiting = run_self_evolution_humanize_patrol(
      self.settings,
      self.project_dir,
      reason="heartbeat",
      force=False,
    )
    self.assertEqual(waiting["status"], "waiting")
    self.assertEqual(waiting["reason"], "cooldown")

    state = get_self_evolution_state(self.settings, self.project_dir)
    self.assertEqual(state["humanize_review_patrol"]["last_status"], "waiting")
    self.assertIn("latest_humanize_patrol_status", state["dashboard"])
    self.assertTrue(state["model_reviews"])

  def test_state_includes_project_narrative_state(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追握住铜钥匙，知道旧船队真相还不能说。"),
    )
    record_project_narrative_state_observation(
      self.project_dir,
      get_project_detail(self.settings, self.project.id),
      "chapter-001",
    )

    state = get_self_evolution_state(self.settings, self.project_dir)

    self.assertIn("narrative_state", state)
    self.assertTrue(state["narrative_state"]["debts"])

  def test_state_refreshes_narrative_cards_from_current_obsidian(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian"
    vault_dir.mkdir()
    note_path = vault_dir / "第1章约束.md"
    note_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 1",
          "chapter_end: 1",
          "required_phrases:",
          "  - 旧约束：铜钥匙必须出现",
          "---",
          "# 第1章约束",
          "第一章约束。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第1章剧情债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 1",
          "chapter_end: 2",
          "---",
          "# 第1章剧情债务",
          "灯塔议会和旧船队背叛线索必须进入林追的行动压力。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "林追人物弧线.md").write_text(
      "\n".join(
        [
          "---",
          "type: character_arc",
          "status: canonical",
          "chapter_start: 1",
          "chapter_end: 2",
          "---",
          "# 林追人物弧线",
          "林追不能立刻相信宋闻，必须保留一次追问。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追握住铜钥匙，知道旧船队真相还不能说。"),
    )
    record_project_narrative_state_observation(
      self.project_dir,
      get_project_detail(self.settings, self.project.id),
      "chapter-001",
    )

    note_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 1",
          "chapter_end: 1",
          "required_phrases:",
          "  - 新约束：灯塔议会必须被点名",
          "---",
          "# 第1章约束",
          "第一章约束已经更新。",
        ]
      ),
      encoding="utf-8",
    )
    detail = get_project_detail(self.settings, self.project.id)
    state = get_self_evolution_state(self.settings, self.project_dir, detail)
    latest_card = state["narrative_state"]["chapter_cards"][-1]

    self.assertIn("新约束：灯塔议会必须被点名", latest_card["obsidian_required"])
    self.assertNotIn("旧约束：铜钥匙必须出现", latest_card["obsidian_required"])
    self.assertTrue(
      any(
        "灯塔议会和旧船队背叛线索" in item.get("content", "")
        for item in latest_card.get("obsidian_narrative_debts", [])
      )
    )
    self.assertTrue(
      any(
        "林追不能立刻相信宋闻" in item.get("current_state", "")
        for item in latest_card.get("obsidian_character_arcs", [])
      )
    )

  def test_capability_context_includes_target_chapter_obsidian_tasks(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian-target-tasks"
    vault_dir.mkdir()
    (vault_dir / "第2章任务.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 2",
          "chapter_end: 2",
          'source_url: "[灯塔议会考据](https://example.com/lighthouse-council)"',
          "required_phrases:",
          "  - 灯塔议会必须施压",
          "forbidden_phrases:",
          "  - 秘密潮门不能曝光",
          "---",
          "# 第2章任务",
          "本章必须让林追意识到灯塔议会正在逼近。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第2章场景卡.md").write_text(
      "\n".join(
        [
          "---",
          "type: scene_plan",
          "status: canonical",
          "chapter: 2",
          "---",
          "# 第2章场景卡",
          "场景一：灯塔议会在码头施压。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第2章债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 2",
          "chapter_end: 3",
          "---",
          "# 第2章债务",
          "旧船队背叛线索必须进入林追的行动压力。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "林追人物弧线.md").write_text(
      "\n".join(
        [
          "---",
          "type: character_arc",
          "status: canonical",
          "chapter_start: 2",
          "chapter_end: 3",
          "---",
          "# 林追人物弧线",
          "林追不能立刻相信宋闻，必须保留一次追问。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第3章债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 3",
          "chapter_end: 3",
          "---",
          "# 第3章债务",
          "第三章才可公开的暗门证据。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    context = build_agent_capability_context(
      self.project_dir,
      project_detail=get_project_detail(self.settings, self.project.id),
      chapter_index=2,
    )

    self.assertIn("目标章节 Obsidian 任务：第 2 章", context)
    self.assertIn("考据来源", context)
    self.assertIn("灯塔议会考据：https://example.com/lighthouse-council", context)
    self.assertIn("灯塔议会必须施压", context)
    self.assertIn("秘密潮门不能曝光", context)
    self.assertIn("第2章场景卡", context)
    self.assertIn("旧船队背叛线索", context)
    self.assertIn("林追不能立刻相信宋闻", context)
    self.assertNotIn("第三章才可公开", context)

  def test_capability_context_includes_obsidian_style_xp_rules(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian-style-xp-capability"
    style_dir = vault_dir / "Style"
    xp_dir = vault_dir / "XP"
    style_dir.mkdir(parents=True)
    xp_dir.mkdir(parents=True)
    (style_dir / "第2章文风规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "chapter_start: 2",
          "chapter_end: 2",
          "style_rule: 第二章的动作必须先贴近潮声，再进入判断。",
          "avoid_style: 不要提前解释银潮灯的来源。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (xp_dir / "第2章复查规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: xp_rule",
          "status: canonical",
          "chapter_start: 2",
          "chapter_end: 2",
          "xp_rule: 第二章生成后检查银潮灯压力是否保留到章尾。",
          "postcheck: 章尾不能解释银潮灯是谁留下。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (style_dir / "全局动作规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "style_rule: 全书都先写可见动作，再写人物判断。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (style_dir / "第4章文风规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "chapter_start: 4",
          "chapter_end: 4",
          "style_rule: 第四章才使用终局祭坛意象。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    detail = get_project_detail(self.settings, self.project.id)

    target_context = build_agent_capability_context(
      self.project_dir,
      project_detail=detail,
      chapter_index=2,
    )
    self.assertIn("目标章节 Obsidian 文风 / XP：第 2 章", target_context)
    self.assertIn("第二章的动作必须先贴近潮声", target_context)
    self.assertIn("第二章生成后检查银潮灯压力", target_context)
    self.assertIn("全书都先写可见动作", target_context)
    self.assertNotIn("终局祭坛意象", target_context)

    early_context = build_agent_capability_context(
      self.project_dir,
      project_detail=detail,
      chapter_index=1,
    )
    self.assertNotIn("第二章的动作必须先贴近潮声", early_context)
    self.assertNotIn("第二章生成后检查银潮灯压力", early_context)

    global_context = build_agent_capability_context(
      self.project_dir,
      project_detail=detail,
    )
    self.assertIn("全局 Obsidian 文风 / XP", global_context)
    self.assertIn("全书都先写可见动作", global_context)
    self.assertNotIn("第二章的动作必须先贴近潮声", global_context)
    self.assertNotIn("终局祭坛意象", global_context)

  def test_capability_context_includes_obsidian_chapter_archive_handoff(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian-archive-handoff"
    (vault_dir / "Archive").mkdir(parents=True)
    (vault_dir / "Archive" / "银潮灯回顾.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: chapter_note",
          "source_ids:",
          "  - chapter-002",
          "chapter_title: 银潮灯回顾",
          "chapter_summary: 林追在银潮灯前确认宋闻隐瞒旧船队账本。",
          "state_changes:",
          "  - 林追不再把宋闻当作单纯同盟。",
          "handoff_to_next:",
          "  - 第3章必须追问账本缺页。",
          "---",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    detail = get_project_detail(self.settings, self.project.id)
    early_context = build_agent_capability_context(
      self.project_dir,
      project_detail=detail,
      chapter_index=1,
    )
    followup_context = build_agent_capability_context(
      self.project_dir,
      project_detail=detail,
      chapter_index=3,
    )

    self.assertNotIn("账本缺页", early_context)
    self.assertIn("目标章节 Obsidian 任务：第 3 章", followup_context)
    self.assertIn("章节档案", followup_context)
    self.assertIn("银潮灯回顾", followup_context)
    self.assertIn("摘要：林追在银潮灯前确认宋闻隐瞒旧船队账本", followup_context)
    self.assertIn("状态变化：林追不再把宋闻当作单纯同盟", followup_context)
    self.assertIn("交接：第3章必须追问账本缺页", followup_context)

  def test_capability_context_scopes_obsidian_maintenance_summary_to_target_chapter(self) -> None:
    state_path = self.project_dir / ".gaoxia" / "learning" / "narrative_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "obsidian_maintenance_suggestions": [
            {
              "id": "current-chapter-clue",
              "title": "整理当前章线索",
              "kind": "create_graph_note",
              "priority": "high",
              "status": "staged",
              "auto_staged": True,
              "source_chapters": [2],
              "suggested_path": "Graph/当前章线索.md",
              "action": "把第二章已经出现的银潮灯线索整理成可复用图谱笔记。",
            },
            {
              "id": "future-reveal",
              "title": "整理未来真相",
              "kind": "create_graph_note",
              "priority": "high",
              "status": "staged",
              "auto_staged": True,
              "source_chapters": [60],
              "suggested_path": "Graph/未来真相.md",
              "action": "把第六十章才开放的真相整理成图谱笔记。",
            },
          ],
          "obsidian_maintenance_summary": {
            "total": 2,
            "needs_action": 2,
            "high_priority": 2,
            "auto_staged": 2,
            "by_status": {"staged": 2},
          },
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    context = build_agent_capability_context(self.project_dir, chapter_index=2)

    self.assertIn("Obsidian 维护摘要：待处理 1，高优先级 1，自动草稿 1。", context)
    self.assertIn("整理当前章线索", context)
    self.assertIn("Graph/当前章线索.md", context)
    self.assertNotIn("整理未来真相", context)
    self.assertNotIn("高优先级 2", context)

  def test_capability_context_includes_multiple_target_chapter_obsidian_tasks(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian-multi-target-tasks"
    vault_dir.mkdir()
    (vault_dir / "第2章任务.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 2",
          "chapter_end: 2",
          "required_phrases:",
          "  - 第二章必须出现银潮灯",
          "---",
          "# 第2章任务",
          "第二章让林追第一次意识到银潮灯不是装饰。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第3章任务.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 3",
          "chapter_end: 3",
          "required_phrases:",
          "  - 第三章必须出现潮门账册",
          "---",
          "# 第3章任务",
          "第三章让潮门账册从传闻变成实物。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第4章任务.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 4",
          "chapter_end: 4",
          "required_phrases:",
          "  - 第四章才可出现终局祭坛",
          "---",
          "# 第4章任务",
          "第四章以后才进入终局祭坛。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    context = build_agent_capability_context(
      self.project_dir,
      project_detail=get_project_detail(self.settings, self.project.id),
      chapter_indexes=[2, 3],
    )

    self.assertIn("目标章节 Obsidian 任务：第 2 章", context)
    self.assertIn("第二章必须出现银潮灯", context)
    self.assertIn("目标章节 Obsidian 任务：第 3 章", context)
    self.assertIn("第三章必须出现潮门账册", context)
    self.assertNotIn("第四章才可出现终局祭坛", context)

  def test_capability_context_refreshes_obsidian_graph_maintenance_from_project_detail(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian-graph-context"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追先在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(self.project_dir)
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(initial_suggestion["status"], "open")
    self.assertFalse(initial_suggestion["auto_staged"])

    (vault_dir / "线索乙.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索乙",
          "宋闻也把 [[潮汐账本]] 当成旧船队背叛线索的一部分。",
        ]
      ),
      encoding="utf-8",
    )
    detail = get_project_detail(self.settings, self.project.id)
    context = build_agent_capability_context(
      self.project_dir,
      project_detail=detail,
      auto_stage_obsidian_drafts=True,
    )

    refreshed_state = load_project_narrative_state(self.project_dir)
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertIn("Graph/", refreshed_suggestion["suggested_path"])
    draft_path = Path(refreshed_suggestion["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertIn("线索乙.md", draft_path.read_text(encoding="utf-8"))
    self.assertIn("Obsidian 维护摘要", context)
    self.assertIn("待处理", context)
    self.assertIn("Obsidian 维护建议", context)
    self.assertIn("Graph/", context)

  def test_studio_self_evolution_api_refreshes_obsidian_maintenance_from_project_detail(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "obsidian-studio-state"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追先在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(self.project_dir)
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(initial_suggestion["status"], "open")

    (vault_dir / "线索乙.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索乙",
          "宋闻也把 [[潮汐账本]] 当成旧船队背叛线索的一部分。",
        ]
      ),
      encoding="utf-8",
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=self.settings)))
    response = studio_api.get_self_evolution(request, self.project.id)
    suggestions = response["data"]["narrative_state"]["obsidian_maintenance_suggestions"]
    refreshed_suggestion = next(
      item
      for item in suggestions
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )

    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertIn("Graph/", refreshed_suggestion["suggested_path"])
    self.assertTrue(Path(refreshed_suggestion["draft_path"]).exists())

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

    def response_state(response: dict[str, object]) -> dict[str, object]:
      meta = response.get("meta") or {}
      state = meta.get("self_evolution") or {}
      self.assertNotIn("self_evolution_error", meta)
      self.assertIn("dashboard", state)
      return state

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
    updated_state = response_state(update_response)
    updated_candidate = next(item for item in updated_state["candidates"]["items"] if item["id"] == candidate_id)
    self.assertEqual(updated_candidate["status"], "rejected")

    accepted_response = project_api.patch_project_self_evolution_candidate(
      request,
      self.project.id,
      skill_candidate["id"],
      project_api.SelfEvolutionCandidateUpdateRequest(status="accepted"),
    )
    draft_id = accepted_response["data"]["draft_id"]
    self.assertTrue(draft_id)
    accepted_state = response_state(accepted_response)
    accepted_candidate = next(item for item in accepted_state["candidates"]["items"] if item["id"] == skill_candidate["id"])
    self.assertEqual(accepted_candidate["status"], "accepted")
    self.assertTrue(any(item["id"] == draft_id for item in accepted_state["drafts"]["items"]))

    draft_status_response = project_api.patch_project_self_evolution_draft(
      request,
      self.project.id,
      draft_id,
      project_api.SelfEvolutionDraftUpdateRequest(status="pending"),
    )
    self.assertEqual(draft_status_response["data"]["status"], "pending")
    draft_status_state = response_state(draft_status_response)
    pending_draft = next(item for item in draft_status_state["drafts"]["items"] if item["id"] == draft_id)
    self.assertEqual(pending_draft["status"], "pending")

    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      apply_response = project_api.post_project_self_evolution_draft_apply(request, self.project.id, draft_id)
    self.assertEqual(apply_response["data"]["status"], "applied")
    self.assertEqual(apply_response["data"]["result"]["type"], "skill")
    applied_state = response_state(apply_response)
    applied_draft = next(item for item in applied_state["drafts"]["items"] if item["id"] == draft_id)
    self.assertEqual(applied_draft["status"], "applied")

    curate_response = project_api.post_project_self_evolution_curate(request, self.project.id)
    self.assertIn("checked_count", curate_response["data"])
    response_state(curate_response)

    regression_response = project_api.post_project_self_evolution_regression(request, self.project.id)
    self.assertEqual(len(regression_response["data"]["cases"]), 4)
    regression_state = response_state(regression_response)
    self.assertTrue(regression_state["writing_regression_runs"])

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
    model_review_state = response_state(model_review_response)
    self.assertTrue(model_review_state["model_reviews"])

    schedule_response = project_api.put_project_self_evolution_schedule(
      request,
      self.project.id,
      project_api.SelfEvolutionScheduleUpdateRequest(enabled=True, interval_hours=24, tasks=["curate"]),
    )
    self.assertTrue(schedule_response["data"]["enabled"])
    schedule_state = response_state(schedule_response)
    self.assertTrue(schedule_state["schedule"]["enabled"])
    schedule_run_response = project_api.post_project_self_evolution_schedule_run(request, self.project.id)
    self.assertEqual(schedule_run_response["data"]["status"], "completed")
    self.assertEqual(schedule_run_response["data"]["ran"][0]["task"], "curate")
    response_state(schedule_run_response)

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
