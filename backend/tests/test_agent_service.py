from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  AgentChatRequest,
  AgentMessage,
  AgentPlan,
  AgentPlanAction,
  ChapterGenerateResult,
  ChapterRewriteResult,
  ChapterUpdateRequest,
  CreateProjectRequest,
  KnowledgeImportItem,
  KnowledgeImportRequest,
  ModelConfig,
  ObsidianVaultConfig,
)
from novel_backend.services.agent_service import (
  _build_runtime_state,
  _brainstorm_request,
  _generate_full_architecture,
  _review_project_knowledge,
  _scope_review_knowledge_actions,
  agent_session_stream,
)
from novel_backend.services.agent_contract_service import evaluate_agent_action_contract
from novel_backend.services.agent_trajectory_service import get_agent_trajectory_records
from novel_backend.services.agent_workflow_service import load_agent_workflow_run, request_agent_workflow_interrupt
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services import context_builder as context_builder_module
from novel_backend.services.project_service import (
  create_project,
  get_project_detail,
  import_project_knowledge,
  load_architecture_progress,
  load_project_knowledge_material_contents,
  search_project_knowledge,
  update_project_obsidian_config,
  update_chapter_content,
)


def decode_sse_event(chunk: str) -> tuple[str, object]:
  event_name = "message"
  data = ""
  for raw_line in chunk.strip().splitlines():
    if raw_line.startswith("event:"):
      event_name = raw_line.split(":", 1)[1].strip()
    elif raw_line.startswith("data:"):
      data = raw_line.split(":", 1)[1].strip()
  return event_name, json.loads(data)


async def collect_stream(stream) -> list[tuple[str, object]]:
  events: list[tuple[str, object]] = []
  async for chunk in stream:
    events.append(decode_sse_event(chunk))
  return events


class AgentServiceTestCase(unittest.TestCase):
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
        name="Agent 回归",
        genre="悬疑",
        target_chapters=3,
        target_words=30000,
      ),
    )
    self._chapter_review_patcher = patch(
      "novel_backend.services.project_service.build_chapter_review",
      side_effect=RuntimeError("skip chapter review in agent tests"),
    )
    self._chapter_review_patcher.start()
    self.addCleanup(self._chapter_review_patcher.stop)
    self._embedding_signature_patcher = patch(
      "novel_backend.services.project_service.embedding_config_signature",
      return_value="agent-tests:not-ready",
    )
    self._embedding_signature_patcher.start()
    self.addCleanup(self._embedding_signature_patcher.stop)
    self._embedding_request_patcher = patch(
      "novel_backend.services.project_service.embed_texts",
      side_effect=RuntimeError("skip embedding in agent tests"),
    )
    self._embedding_request_patcher.start()
    self.addCleanup(self._embedding_request_patcher.stop)
    self._rerank_patcher = patch(
      "novel_backend.services.project_service.rerank_documents",
      return_value=[],
    )
    self._rerank_patcher.start()
    self.addCleanup(self._rerank_patcher.stop)
    self._context_search_patcher = patch(
      "novel_backend.services.context_builder.search_project_knowledge",
      return_value=[],
    )
    self._context_search_patcher.start()
    self.addCleanup(self._context_search_patcher.stop)
    self._guard_search_patcher = patch(
      "novel_backend.services.continuity_guard_service.search_project_knowledge_evidence",
      return_value=[],
    )
    self._guard_search_patcher.start()
    self.addCleanup(self._guard_search_patcher.stop)
    self._narrative_model_patcher = patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      side_effect=RuntimeError("skip narrative model editor in agent tests"),
    )
    self._narrative_model_patcher.start()
    self.addCleanup(self._narrative_model_patcher.stop)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def _write_chapter_without_review(self, chapter_id: str, content: str) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      chapter_id,
      ChapterUpdateRequest(content=content),
    )

  def _write_custom_skill(self, skill_id: str, name: str, *, scenes: list[str] | None = None, body_note: str = "") -> Path:
    skill_path = self.settings.data_dir / "skills" / "user-skills" / skill_id / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    scene_lines = "\n".join(f"  - {item}" for item in (scenes or ["章节"]))
    note = body_note or "处理对白时保留人物口气，不把人物写成一个声线。"
    skill_path.write_text(
      (
        "---\n"
        f"name: {name}\n"
        f"description: {note}\n"
        "version: 0.1.0\n"
        f"skill_id: {skill_id}\n"
        "section_id: user-skills\n"
        "section_title: 用户沉淀\n"
        "section_description: 聊天里沉淀下来的可复用技能。\n"
        "category: 用户技能\n"
        "badge: 沉\n"
        "accent: smoke\n"
        "source: custom\n"
        "panel: conversation-skill\n"
        "requires_project: true\n"
        "requires_chapter: true\n"
        "scenes:\n"
        f"{scene_lines}\n"
        "usage:\n"
        f"  - {note}\n"
        "limitations:\n"
        "  - 只覆盖当前测试场景。\n"
        "---\n"
        f"# {name}\n\n"
        "## 适用场景\n"
        f"- {note}\n\n"
        "## 输入要求\n"
        "- 给出目标章节和处理重点。\n\n"
        "## 执行步骤\n"
        "1. 识别需要处理的语气问题。\n"
        "2. 按人物关系保留对白差异。\n"
        "3. 回看剧情事实没有变化。\n\n"
        "## 输出要求\n"
        "- 直接给处理结果。\n\n"
        "## 边界\n"
        "- 不改剧情事实。\n"
      ),
      encoding="utf-8",
    )
    return skill_path

  def test_write_request_returns_confirm_plan_when_architecture_missing(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="续写这一章")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    self.assertEqual(result_event[1]["task_pack_kind"], "continuation")
    self.assertEqual(result_event[1]["plan"]["actions"][0]["kind"], "generate_architecture")
    self.assertEqual(result_event[1]["plan"]["actions"][0]["task_pack_kind"], "architecture")
    self.assertEqual(result_event[1]["plan"]["actions"][1]["kind"], "chapter_generate")
    self.assertEqual(result_event[1]["plan"]["actions"][1]["task_pack_kind"], "continuation")
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(action_kinds, ["generate_architecture", "chapter_generate", "rewrite_chapter", "consistency_check"])
    self.assertEqual(result_event[1]["plan"]["actions"][2]["mode"], "humanize")
    self.assertIn("计划步骤：", result_event[1]["reply"])

  def test_rewrite_whole_chapter_uses_segment_generation_plan(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="重新第一章")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    actions = result_event[1]["plan"]["actions"]
    chapter_action = next(item for item in actions if item["kind"] == "chapter_generate")
    self.assertEqual(chapter_action["label"], "重写第 1 章正文")
    self.assertTrue(chapter_action["replace_existing"])
    self.assertNotIn("修订第 1 章", [item["label"] for item in actions])

  def test_write_request_can_skip_supervised_longform_steps(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="只生成初稿，不要改稿不要检查。续写这一章")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(action_kinds, ["generate_architecture", "chapter_generate"])

  def test_draft_workflow_uses_longform_supervision_steps(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "续写当前章节",
          "summary": "用章节工作流续写正文。",
          "actions": [
            {
              "kind": "chapter_workflow",
              "label": "续写当前章节",
              "instruction": "续写这一章。",
              "chapter_target": "selected",
              "mode": "draft",
            }
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[AgentMessage(role="user", content="续写这一章正文。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    plan = result_event[1]["plan"]
    action_kinds = [item["kind"] for item in plan["actions"]]
    self.assertTrue(plan["requires_confirmation"])
    self.assertEqual(action_kinds, ["generate_architecture", "chapter_workflow", "rewrite_chapter", "consistency_check"])
    self.assertEqual(plan["actions"][1]["mode"], "draft")
    self.assertEqual(plan["actions"][2]["mode"], "humanize")

  def test_active_builtin_draft_skill_routes_heuristic_plan_to_chapter_workflow(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=False,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              active_skill_ids=["chapter-draft"],
              messages=[AgentMessage(role="user", content="先看当前状态，续写这一章。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    plan = result_event[1]["plan"]
    action_kinds = [item["kind"] for item in plan["actions"]]
    self.assertEqual(action_kinds, ["generate_architecture", "chapter_workflow", "rewrite_chapter", "consistency_check"])
    self.assertEqual(plan["actions"][1]["mode"], "draft")
    self.assertEqual(plan["actions"][2]["mode"], "humanize")

  def test_active_builtin_humanize_skill_overrides_model_rewrite_mode(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追说：我们不能回头。\n",
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "修订当前章节",
          "summary": "模型先给出普通润色计划。",
          "actions": [
            {
              "kind": "rewrite_chapter",
              "label": "润色当前章节",
              "instruction": "修订这一章。",
              "chapter_target": "selected",
              "mode": "polish",
            }
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              active_skill_ids=["chapter-humanize"],
              messages=[AgentMessage(role="user", content="这章改成更自然的正文。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    plan = result_event[1]["plan"]
    action_kinds = [item["kind"] for item in plan["actions"]]
    self.assertEqual(action_kinds, ["generate_architecture", "rewrite_chapter", "consistency_check"])
    self.assertEqual(plan["actions"][1]["mode"], "humanize")

  def test_rewrite_request_gets_continuity_review_step(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追说：我们不能回头。\n",
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="这次给第一章去 AI，注意对白别写成一个口气。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(action_kinds, ["generate_architecture", "rewrite_chapter", "consistency_check"])
    self.assertEqual(result_event[1]["plan"]["actions"][1]["mode"], "humanize")

  def test_empty_project_can_start_architecture_plan_from_execution_panel(self) -> None:
    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            messages=[AgentMessage(role="user", content="先看当前状态，帮我把整书架构补齐。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    self.assertEqual(result_event[1]["plan"]["actions"][0]["kind"], "generate_architecture")
    self.assertIn("整书架构", result_event[1]["plan"]["title"])

  def test_brainstorm_request_resolves_target_chapter_from_user_message(self) -> None:
    runtime = _build_runtime_state(self.settings, self.project.id)
    request = _brainstorm_request(
      runtime,
      AgentChatRequest(
        project_id=self.project.id,
        messages=[AgentMessage(role="user", content="先讨论第 2 章下一步该怎么推。")],
      ),
    )
    self.assertEqual(request.chapter_id, "chapter-002")

  def test_architecture_plan_prepends_knowledge_review_when_requested(self) -> None:
    import_project_knowledge(
      self.settings,
      self.project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="码头旧档案",
            content="旧船队失踪前最后一次靠港，港务会删掉了两页登记记录。",
          ),
        ]
      ),
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            messages=[AgentMessage(role="user", content="先把资料库的资料分析完，再补整书架构。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    self.assertEqual(result_event[1]["task_pack_kind"], "architecture")
    self.assertEqual(result_event[1]["plan"]["actions"][0]["kind"], "review_knowledge")
    self.assertEqual(result_event[1]["plan"]["actions"][0]["task_pack_kind"], "architecture")
    self.assertEqual(result_event[1]["plan"]["actions"][1]["kind"], "generate_architecture")
    self.assertEqual(result_event[1]["plan"]["actions"][1]["task_pack_kind"], "architecture")
    self.assertIn("先通读资料库和 Obsidian 里的 1 份资料", result_event[1]["reply"])

  def test_full_architecture_saves_each_step_and_resumes_after_failure(self) -> None:
    instruction = "重新生成整书架构"
    runtime = _build_runtime_state(self.settings, self.project.id)
    first_calls: list[str] = []

    def fail_on_character_state(_settings, payload, _task_id, *_args):
      first_calls.append(payload.step)
      if payload.step == "character_state":
        raise RuntimeError("network down")
      return SimpleNamespace(content=f"{payload.step} 内容")

    with patch("novel_backend.services.agent_service._generate_architecture_step", side_effect=fail_on_character_state):
      with self.assertRaises(RuntimeError):
        _generate_full_architecture(self.settings, runtime, instruction, [], "task-architecture")

    self.assertEqual(first_calls, ["core_seed", "character_design", "world_building", "plot_structure", "character_state"])
    project_dir = Path(self.project.path)
    self.assertEqual((project_dir / "core_seed.txt").read_text(encoding="utf-8"), "core_seed 内容")
    self.assertEqual((project_dir / "plot_structure.txt").read_text(encoding="utf-8"), "plot_structure 内容")
    self.assertFalse((project_dir / "character_state.txt").read_text(encoding="utf-8").strip())

    progress = load_architecture_progress(self.settings, self.project.id)
    self.assertIsNotNone(progress)
    assert progress is not None
    self.assertEqual(progress["failed_step"], "character_state")
    self.assertEqual(progress["completed_steps"], ["core_seed", "character_design", "world_building", "plot_structure"])

    second_calls: list[str] = []

    def resume_from_failed_step(_settings, payload, _task_id, *_args):
      second_calls.append(payload.step)
      return SimpleNamespace(content=f"{payload.step} 新内容")

    resumed_runtime = _build_runtime_state(self.settings, self.project.id)
    with patch("novel_backend.services.agent_service._generate_architecture_step", side_effect=resume_from_failed_step):
      _detail, workspace = _generate_full_architecture(self.settings, resumed_runtime, instruction, [], "task-architecture-2")

    self.assertEqual(second_calls, ["character_state", "blueprint", "global_summary"])
    self.assertEqual(workspace.character_state, "character_state 新内容")
    self.assertEqual((project_dir / "blueprint.txt").read_text(encoding="utf-8"), "blueprint 新内容")
    self.assertIsNone(load_architecture_progress(self.settings, self.project.id))

  def test_full_architecture_reuses_single_context_snapshot(self) -> None:
    runtime = _build_runtime_state(self.settings, self.project.id)
    snapshot_queries: list[str] = []

    def build_snapshot(*args, **kwargs):
      snapshot_queries.append(str(kwargs.get("knowledge_query") or ""))
      return context_builder_module.build_project_context_bundle(*args, **kwargs)

    def fake_model(_settings, _messages, *, task_name: str, **_kwargs):
      return json.dumps(
        {
          "headline": "已生成",
          "summary": "已生成",
          "content": f"{task_name} 内容",
          "checklist": [],
        },
        ensure_ascii=False,
      )

    with patch("novel_backend.services.agent_service.build_project_context_bundle", side_effect=build_snapshot), patch(
      "novel_backend.services.generation_service.build_project_context_bundle",
      side_effect=AssertionError("整书架构步骤不应重复构建项目上下文"),
    ), patch("novel_backend.services.generation_service._invoke_model", side_effect=fake_model):
      _generate_full_architecture(self.settings, runtime, "重新生成整书架构", [], "task-context-snapshot")

    self.assertEqual(len(snapshot_queries), 1)
    self.assertIn("核心种子", snapshot_queries[0])

  def test_full_architecture_queues_auxiliary_refresh_once_after_success(self) -> None:
    runtime = _build_runtime_state(self.settings, self.project.id)

    def fake_step(_settings, payload, _task_id, *_args):
      return SimpleNamespace(content=f"{payload.step} 内容")

    with patch("novel_backend.services.agent_service._generate_architecture_step", side_effect=fake_step), patch(
      "novel_backend.services.agent_service.enqueue_project_auxiliary_tasks",
      return_value={"status": "queued"},
    ) as mocked_enqueue:
      _generate_full_architecture(self.settings, runtime, "重新生成整书架构", [], "task-refresh-once")

    self.assertEqual(mocked_enqueue.call_count, 1)
    self.assertEqual(mocked_enqueue.call_args.kwargs["reason"], "architecture_completed")
    self.assertEqual(mocked_enqueue.call_args.kwargs["tasks"], ["knowledge_index", "story_overview_model", "system_memory"])

  def test_model_first_planner_prefers_architecture_over_chapter_keyword_overlap(self) -> None:
    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "整理整书架构",
          "summary": "先分析资料库，再重新整理整书架构。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "review_knowledge",
              "label": "分析资料库",
              "instruction": "把资料库的资料分析完，再重新弄续写架构",
            },
            {
              "kind": "generate_architecture",
              "label": "生成整书架构",
              "instruction": "把资料库的资料分析完，再重新弄续写架构",
            },
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="把资料库的资料分析完，再重新弄续写架构")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(action_kinds, ["review_knowledge", "generate_architecture"])

  def test_long_agent_message_is_accepted_and_compacted_for_planner(self) -> None:
    long_text = "帮我完善整书架构。\n\n" + "\n\n".join(
      f"中段资料第 {index} 段，角色和线索还需要继续整理，旧船队沿着隐秘航线推进。"
      for index in range(1800)
    ) + "\n\n结尾要求：第一章保留铜钥匙，资料尾部暗号是潮汐尾码。"
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "整理整书架构",
          "summary": "长文本输入已压缩后用于规划。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "generate_architecture",
              "label": "生成整书架构",
              "instruction": "完善整书架构。",
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content=long_text)],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    self.assertTrue(result_event[1]["changes"])
    self.assertIn("导入项目资料库", result_event[1]["changes"][0])
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(action_kinds, ["review_knowledge", "generate_architecture"])
    current_user_messages = [
      item["content"]
      for item in captured_messages
      if item["role"] == "user" and item["content"].startswith("当前用户消息：")
    ]
    self.assertEqual(len(current_user_messages), 1)
    self.assertIn("[长文本压缩", current_user_messages[0])
    self.assertIn("资料尾部暗号是潮汐尾码", current_user_messages[0])
    self.assertLess(len(current_user_messages[0]), 2600)
    reference_messages = [
      item["content"]
      for item in captured_messages
      if item["role"] == "system" and "本轮已导入参考资料" in item["content"]
    ]
    self.assertTrue(reference_messages)

    detail = get_project_detail(self.settings, self.project.id)
    auto_materials = [
      item
      for item in detail.story_overview.materials
      if item.title.startswith("Agent长输入-")
    ]
    self.assertGreaterEqual(len(auto_materials), 2)
    hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "潮汐尾码",
      include_semantic=False,
    )
    self.assertTrue(any(item.source == "资料库" for item in hits))
    self.assertTrue(any(item.section.startswith("Agent长输入-") for item in hits))

  def test_long_agent_message_filters_unrelated_noise_before_importing_materials(self) -> None:
    noise = "\n".join(
      f"Traceback frame {index}: node_modules/demo/app.js ERROR TypeError console.error {{status: 500}}"
      for index in range(700)
    )
    story_material = "\n\n".join(
      f"章节素材 {index}：林追在旧码头发现潮汐尾码，人物动机和旧船队隐秘航线继续推进。"
      for index in range(900)
    )
    long_text = (
      "帮我完善整书架构，下面素材和报错混在一起，入库时只保留小说资料。\n\n"
      f"{noise}\n\n{story_material}\n\n{noise}"
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "整理整书架构",
          "summary": "读取筛选后的资料后规划架构。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "generate_architecture",
              "label": "生成整书架构",
              "instruction": "完善整书架构。",
            }
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content=long_text)],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertTrue(result_event[1]["changes"])
    self.assertIn("跳过", result_event[1]["changes"][0])
    materials = [
      item
      for item in load_project_knowledge_material_contents(self.settings, self.project.id, limit=20)
      if item["title"].startswith("Agent长输入-")
    ]
    self.assertTrue(materials)
    imported_text = "\n".join(item["content"] for item in materials)
    self.assertIn("潮汐尾码", imported_text)
    self.assertNotIn("Traceback frame", imported_text)
    self.assertNotIn("node_modules/demo", imported_text)

    hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "旧船队隐秘航线",
      include_semantic=False,
    )
    self.assertTrue(any(item.section.startswith("Agent长输入-") for item in hits))

  def test_unrelated_long_agent_message_is_not_imported_as_material(self) -> None:
    long_text = "帮我看这段报错，不要作为小说资料保存。\n\n" + "\n".join(
      f"Traceback frame {index}: node_modules/demo/app.js ERROR TypeError console.error {{status: 500}}"
      for index in range(900)
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "reply",
          "reply": "这段内容更像技术报错，不适合写入小说资料库。",
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content=long_text)],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("未写入资料库", result_event[1]["changes"][0])
    materials = [
      item
      for item in load_project_knowledge_material_contents(self.settings, self.project.id, limit=20)
      if item["title"].startswith("Agent长输入-")
    ]
    self.assertEqual(materials, [])

  def test_brainstorm_request_compacts_long_agent_messages(self) -> None:
    runtime = _build_runtime_state(self.settings, self.project.id)
    long_text = (
      "先讨论第 1 章怎么推进。\n"
      + ("人物关系说明，码头线索和追兵压力需要并行。" * 1000)
      + "\n尾部要求：不要提前解释真相。"
    )

    request = _brainstorm_request(
      runtime,
      AgentChatRequest(
        project_id=self.project.id,
        messages=[
          AgentMessage(
            role="user",
            content=long_text,
            original_length=len(long_text),
            summary="讨论第 1 章推进方式，尾部要求不要提前解释真相。",
          )
        ],
      ),
    )

    self.assertEqual(len(request.messages), 1)
    self.assertLessEqual(len(request.messages[0].content), 3800)
    self.assertIn("[长文本压缩", request.messages[0].content)
    self.assertIn("不要提前解释真相", request.messages[0].content)

  def test_model_planner_receives_skill_catalog_context(self) -> None:
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "整理整书架构",
          "summary": "读取技能目录后规划架构。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "generate_architecture",
              "label": "生成整书架构",
              "instruction": "完善整书架构。",
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="帮我完善整书架构")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    joined_context = "\n".join(item["content"] for item in captured_messages)
    self.assertIn("可用技能目录", joined_context)
    self.assertIn("去 AI", joined_context)
    self.assertIn("Agent action:chapter_workflow/draft，需要确认", joined_context)
    self.assertIn("Agent action:rewrite_chapter/humanize，需要确认", joined_context)
    self.assertIn("Agent action:consistency_check，无需确认", joined_context)

  def test_model_planner_receives_self_evolution_capability_rules(self) -> None:
    project_dir = Path(self.project.path)
    learning_dir = project_dir / ".gaoxia" / "learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    (learning_dir / "agent_capability_rules.json").write_text(
      json.dumps(
        {
          "schema_version": 1,
          "updated_at": "2026-05-22T00:00:00+00:00",
          "rules": [
            {
              "id": "cap-review-knowledge",
              "title": "资料优先调用规则",
              "content": "用户要求先看资料时，计划必须先放 review_knowledge。",
              "confidence": 0.91,
              "seen_count": 3,
              "last_seen_at": "2026-05-22T00:00:00+00:00",
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "分析资料",
          "summary": "按自学习规则先分析资料。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "review_knowledge",
              "label": "分析资料",
              "instruction": "先看资料再处理。",
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="先看资料再处理后面的规划。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    joined_context = "\n".join(item["content"] for item in captured_messages)
    self.assertIn("Agent 自学习调用规则", joined_context)
    self.assertIn("用户要求先看资料时，计划必须先放 review_knowledge", joined_context)

  def test_model_planner_hides_future_obsidian_suggestions_for_chapter_task(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-agent-capability-scope"
    vault_dir.mkdir()
    (vault_dir / "后段线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 58-60 章",
          "---",
          "# 后段线索",
          "第 58 章后，林追才会把 [[终局祭坛]] 和幕后组织联系起来。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "生成第一章正文",
          "summary": "用户要求写第一章。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成第一章初稿",
              "instruction": "",
              "chapter_target": "next",
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[AgentMessage(role="user", content="写第一章")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    joined_context = "\n".join(item["content"] for item in captured_messages)
    self.assertIn("Obsidian 维护摘要", joined_context)
    self.assertNotIn("终局祭坛", joined_context)
    self.assertNotIn("Graph/终局祭坛.md", joined_context)

  def test_model_planner_capability_scope_prefers_generation_target_chapter(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-agent-capability-target"
    vault_dir.mkdir()
    (vault_dir / "第二章线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 2 章",
          "---",
          "# 第二章线索",
          "第二章会第一次提到 [[银潮灯]]，第一章只保留空白。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "生成第二章正文",
          "summary": "用户先参考第一章，再生成第二章。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成第二章初稿",
              "instruction": "",
              "chapter_index": 2,
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[AgentMessage(role="user", content="先检查第一章信息，再生成第二章内容。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    joined_context = "\n".join(item["content"] for item in captured_messages)
    self.assertIn("Graph/银潮灯.md", joined_context)
    self.assertIn("银潮灯", joined_context)

  def test_model_planner_capability_scope_reads_chapter_range(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-agent-capability-range"
    vault_dir.mkdir()
    (vault_dir / "第二章任务.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 2 章",
          "required_phrases:",
          "  - 第二章必须出现银潮灯",
          "---",
          "# 第二章任务",
          "第二章会第一次提到 [[银潮灯]]。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第三章任务.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 3 章",
          "required_phrases:",
          "  - 第三章必须出现潮门账册",
          "---",
          "# 第三章任务",
          "第三章让潮门账册从传闻变成实物。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "生成第二到三章正文",
          "summary": "先生成第二章，再处理第三章。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成第二章初稿",
              "instruction": "",
              "chapter_index": 2,
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="生成第2到3章正文，先从第二章开始。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    joined_context = "\n".join(item["content"] for item in captured_messages)
    self.assertIn("目标章节 Obsidian 任务：第 2 章", joined_context)
    self.assertIn("第二章必须出现银潮灯", joined_context)
    self.assertIn("目标章节 Obsidian 任务：第 3 章", joined_context)
    self.assertIn("第三章必须出现潮门账册", joined_context)
    generation_actions = [item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate"]
    self.assertEqual([item["chapter_id"] for item in generation_actions], ["chapter-002", "chapter-003"])

  def test_heuristic_write_plan_expands_chapter_range(self) -> None:
    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            messages=[AgentMessage(role="user", content="写第2到3章正文，先从第二章开始。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    generation_actions = [item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate"]
    self.assertEqual([item["chapter_id"] for item in generation_actions], ["chapter-002", "chapter-003"])
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(
      action_kinds,
      [
        "generate_architecture",
        "chapter_generate",
        "rewrite_chapter",
        "consistency_check",
        "chapter_generate",
        "rewrite_chapter",
        "consistency_check",
      ],
    )

  def test_heuristic_write_plan_rejects_large_chapter_range(self) -> None:
    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            messages=[AgentMessage(role="user", content="写第1到4章正文。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "reply")
    self.assertIn("最多支持 3 章", result_event[1]["reply"])

  def test_model_planner_capability_scope_keeps_chapter_range_for_blueprint_request(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-agent-capability-blueprint-range"
    vault_dir.mkdir()
    (vault_dir / "第二章蓝图约束.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: chapter_plan",
          "chapter_range: 第 2 章",
          "required_phrases:",
          "  - 第二章蓝图必须保留银潮灯",
          "---",
          "# 第二章蓝图约束",
          "第二章规划必须让银潮灯进入主线。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第三章蓝图约束.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: chapter_plan",
          "chapter_range: 第 3 章",
          "required_phrases:",
          "  - 第三章蓝图必须保留潮门账册",
          "---",
          "# 第三章蓝图约束",
          "第三章规划必须让潮门账册变成实物。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    captured_messages: list[dict[str, str]] = []

    def fake_invoke(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "mode": "plan",
          "title": "规划第二到三章蓝图",
          "summary": "整理第二到三章蓝图。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "continue_project",
              "label": "扩写后续章节规划",
              "instruction": "",
              "new_chapters": 2,
            }
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="整理第2到3章蓝图，先看这两章的 Obsidian 计划。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    joined_context = "\n".join(item["content"] for item in captured_messages)
    self.assertIn("目标章节 Obsidian 任务：第 2 章", joined_context)
    self.assertIn("第二章蓝图必须保留银潮灯", joined_context)
    self.assertIn("目标章节 Obsidian 任务：第 3 章", joined_context)
    self.assertIn("第三章蓝图必须保留潮门账册", joined_context)

  def test_model_planner_review_step_counts_only_target_chapter_obsidian_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-agent-review-step-scope"
    vault_dir.mkdir()
    (vault_dir / "第一章线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 1 章",
          "---",
          "# 第一章线索",
          "林追只能看到潮位编号。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "后段真相.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: secret",
          "chapter_range: 第 58-60 章",
          "---",
          "# 后段真相",
          "第 58 章以后才能确认幕后组织。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    project_dir = Path(self.project.path)
    for filename in ("core_seed.txt", "character_design.txt", "world_building.txt", "plot_structure.txt", "blueprint.txt"):
      (project_dir / filename).write_text("林追追查港口旧案。", encoding="utf-8")

    def fake_invoke(_settings, _messages, **_kwargs):
      return json.dumps(
        {
          "mode": "plan",
          "title": "分析资料并生成第一章",
          "summary": "先分析资料，再写第一章。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "review_knowledge",
              "label": "分析资料库",
              "instruction": "先分析资料，再写第一章。",
            },
            {
              "kind": "chapter_generate",
              "label": "生成第一章初稿",
              "instruction": "",
              "chapter_target": "next",
            },
          ],
        },
        ensure_ascii=False,
      )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=fake_invoke,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="先分析资料，再写第一章。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    steps_text = "\n".join(result_event[1]["plan"]["steps"])
    self.assertIn("第 1 章可用的资料库和 Obsidian 里的 1 份资料", steps_text)
    self.assertNotIn("2 份资料", steps_text)

  def test_model_plan_respects_user_explicit_chapter_over_selected_chapter(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n",
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "生成当前章节",
          "summary": "模型误把目标章节写成当前选中章节。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成当前章节正文",
              "instruction": "继续当前章节。",
              "chapter_target": "selected",
              "chapter_index": 0,
            }
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[AgentMessage(role="user", content="参考第一章，生成第二章内容。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    chapter_action = next(item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate")
    self.assertEqual(chapter_action["chapter_id"], "chapter-002")
    self.assertEqual(chapter_action["label"], "生成第 2 章正文")
    self.assertEqual(chapter_action["instruction"], "参考第一章，生成第二章内容。")
    self.assertIn("第 2 章", result_event[1]["reply"])

  def test_model_plan_uses_action_specific_chapter_when_reference_chapter_appears_first(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n",
    )

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "生成当前章节",
          "summary": "模型没有填目标章节。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成当前章节正文",
              "instruction": "继续当前章节。",
              "chapter_target": "selected",
              "chapter_index": 0,
            }
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[AgentMessage(role="user", content="先检查第一章信息，再生成第二章内容。")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    chapter_action = next(item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate")
    self.assertEqual(chapter_action["chapter_id"], "chapter-002")
    self.assertEqual(chapter_action["label"], "生成第 2 章正文")

  def test_model_plan_can_chain_rewrite_after_new_chapter_generation(self) -> None:
    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "生成第一章正文并进行后续处理",
          "summary": "用户明确要求写第一章，按章节工作流执行初稿生成、去AI化和一致性检查。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成第一章初稿",
              "instruction": "",
              "chapter_target": "next",
              "chapter_index": 0,
              "chapter_title": "第 1 章",
              "mode": "draft",
            },
            {
              "kind": "rewrite_chapter",
              "label": "去AI化处理",
              "instruction": "",
              "chapter_target": "last_written",
              "mode": "humanize",
            },
            {
              "kind": "consistency_check",
              "label": "一致性检查",
              "instruction": "",
              "chapter_target": "last_written",
            },
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="写第一章")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    self.assertNotIn("当前规划指向了一个不存在或不可处理的章节", result_event[1]["reply"])
    action_kinds = [item["kind"] for item in result_event[1]["plan"]["actions"]]
    self.assertEqual(action_kinds, ["generate_architecture", "chapter_generate", "rewrite_chapter", "consistency_check"])
    chapter_actions = [item for item in result_event[1]["plan"]["actions"] if item["chapter_id"]]
    self.assertTrue(chapter_actions)
    self.assertEqual({item["chapter_id"] for item in chapter_actions}, {"chapter-001"})
    self.assertEqual(result_event[1]["plan"]["actions"][2]["mode"], "humanize")

  def test_model_plan_uses_project_chapter_budget_for_standard_chapter_generation(self) -> None:
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="章节容量",
        genre="悬疑",
        target_chapters=30,
        target_words=200000,
      ),
    )
    project_dir = Path(project.path)
    for filename in ("core_seed.txt", "character_design.txt", "world_building.txt", "plot_structure.txt", "blueprint.txt"):
      (project_dir / filename).write_text("林晚追查职场陷害真相。", encoding="utf-8")

    with patch(
      "novel_backend.services.agent_service._planner_available",
      return_value=True,
    ), patch(
      "novel_backend.services.agent_service._invoke_model",
      return_value=json.dumps(
        {
          "mode": "plan",
          "title": "生成第一章正文",
          "summary": "用户要求写第一章。",
          "requires_confirmation": True,
          "actions": [
            {
              "kind": "chapter_generate",
              "label": "生成第一章初稿",
              "instruction": "",
              "chapter_target": "next",
              "target_words": 0,
            }
          ],
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=project.id,
              messages=[AgentMessage(role="user", content="写第一章")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    chapter_action = next(item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate")
    self.assertEqual(chapter_action["chapter_id"], "chapter-001")
    self.assertEqual(chapter_action["target_words"], 6667)

  def test_auto_matches_custom_skill_for_natural_language_plan(self) -> None:
    self._write_custom_skill(
      "user-dialogue-humanize",
      "对白去 AI",
      scenes=["去 AI", "对白"],
      body_note="去 AI 时保留人物对白差异。",
    )
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追说：我们不能回头。\n",
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="这次给第一章去 AI，注意对白别写成一个口气。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    action_skill_ids = [
      skill_id
      for action in result_event[1]["plan"]["actions"]
      for skill_id in action.get("skill_ids", [])
    ]
    self.assertIn("user-dialogue-humanize", action_skill_ids)

  def test_natural_language_skill_optimization_creates_custom_skill_after_confirmation(self) -> None:
    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[
              AgentMessage(
                role="user",
                content="以后我提章节去 AI，你都按保剧情、先识别模板腔、再保留人物对白差异的方式处理。",
              )
            ],
          ),
        )
      )
    )
    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "plan")
    self.assertEqual(result_event[1]["plan"]["actions"][0]["kind"], "skill_optimize")

    approved_plan = AgentPlan.model_validate(result_event[1]["plan"])
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=RuntimeError("skip-model"),
    ):
      execute_events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(
                  role="user",
                  content="以后我提章节去 AI，你都按保剧情、先识别模板腔、再保留人物对白差异的方式处理。",
                ),
                AgentMessage(role="assistant", content=result_event[1]["reply"]),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=approved_plan,
            ),
          )
        )
      )

    execute_result = next(item for item in execute_events if item[0] == "result")
    self.assertEqual(execute_result[1]["mode"], "execution")
    self.assertIn("用户技能", execute_result[1]["reply"])
    self.assertEqual(execute_result[1]["artifacts"][0]["kind"], "user_skill")
    saved_path = execute_result[1]["artifacts"][0]["metadata"]["saved_path"]
    self.assertTrue(Path(saved_path).exists())

  def test_knowledge_review_reuses_distillation_report_before_model_analysis(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "agent-distillation-empty-vault"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    import_project_knowledge(
      self.settings,
      self.project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="船队侧记",
            content="旧船队失踪前最后一次靠港时，灯塔议会删掉了靠港记录。",
          ),
        ]
      ),
    )
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追把铜钥匙塞进口袋，准备回旧码头。\n",
    )
    runtime = _build_runtime_state(self.settings, self.project.id)

    with patch(
      "novel_backend.services.agent_service._invoke_model",
      side_effect=AssertionError("不该走独立资料分析模型调用"),
    ):
      summary, material_count = _review_project_knowledge(
        self.settings,
        runtime,
        "先把资料库分析完，再重新整理整书架构。",
      )

    self.assertEqual(material_count, 1)
    self.assertIn("任务包：architecture", summary)
    self.assertIn("资料库要点：", summary)

  def test_knowledge_review_filters_obsidian_notes_for_target_chapter(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "agent-obsidian-vault"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
type: clue
status: canonical
chapter_range: 1-1
foreshadows:
  - 终局真相
---
# 当前线索

林追只知道潮汐编号还没有解开，答案不要提前写成[[终局真相]]。
""",
      encoding="utf-8",
    )
    (vault_dir / "终局真相.md").write_text(
      """---
type: secret
status: canonical
chapter_range: 3-3
reveal_after_chapter: 2
---
# 终局真相

沉船真相只能在第三章以后公开，并反向引用[[当前线索]]。
""",
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    runtime = _build_runtime_state(self.settings, self.project.id)
    captured_prompts: list[str] = []

    def fake_model(_settings, messages, **_kwargs):
      prompt = "\n\n".join(str(item.get("content") or "") for item in messages)
      captured_prompts.append(prompt)
      return "资料分析完成。"

    with patch("novel_backend.services.agent_service._invoke_model", side_effect=fake_model):
      summary, material_count = _review_project_knowledge(
        self.settings,
        runtime,
        "先分析资料，再写第一章。",
        task_pack_kind="continuation",
        chapter_index=1,
      )

    self.assertEqual(material_count, 1)
    combined_text = "\n".join([summary, *captured_prompts])
    self.assertIn("当前线索", combined_text)
    self.assertNotIn("终局真相", combined_text)
    self.assertNotIn("沉船真相", combined_text)

  def test_knowledge_review_includes_target_context_pending_soft_constraints(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "agent-knowledge-review-pending"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    project_dir = Path(self.project.path)
    style_path = project_dir / ".gaoxia" / "learning" / "style_xp_evolution.json"
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "updated_at": "2026-06-03T00:00:00+00:00",
          "active_version": 1,
          "rules": [
            {
              "id": "style-visible-causality",
              "kind": "style",
              "signal": "manual-test-style",
              "status": "active",
              "content": "动作停顿之间保留可见因果。",
              "confidence": 0.82,
              "evidence_count": 2,
              "source_chapter_ids": ["chapter-001", "chapter-002"],
            },
            {
              "id": "xp-ending-pressure",
              "kind": "xp",
              "signal": "manual-test-xp",
              "status": "active",
              "content": "生成后确认线索压力留到章尾。",
              "confidence": 0.76,
              "evidence_count": 2,
              "source_chapter_ids": ["chapter-001", "chapter-002"],
            },
          ],
          "observations": [],
        },
        ensure_ascii=False,
        indent=2,
      ),
      encoding="utf-8",
    )
    import_project_knowledge(
      self.settings,
      self.project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="线索记录",
            content="第三章需要让铜钥匙线索继续推动林追的选择。",
          ),
        ]
      ),
    )
    runtime = _build_runtime_state(self.settings, self.project.id)
    captured_prompts: list[str] = []

    def fake_model(_settings, messages, **_kwargs):
      prompt = "\n\n".join(str(item.get("content") or "") for item in messages)
      captured_prompts.append(prompt)
      return "资料分析完成。"

    with patch("novel_backend.services.agent_service._invoke_model", side_effect=fake_model):
      summary, material_count = _review_project_knowledge(
        self.settings,
        runtime,
        "先分析资料，再写第三章。",
        task_pack_kind="continuation",
        chapter_index=3,
      )

    self.assertEqual(material_count, 1)
    combined_text = "\n".join([summary, *captured_prompts])
    self.assertIn("目标章节上下文", combined_text)
    self.assertIn("Obsidian 待审软约束", combined_text)
    self.assertIn("[文风]", combined_text)
    self.assertIn("[XP]", combined_text)
    self.assertIn("动作停顿之间保留可见因果", combined_text)
    self.assertIn("生成后确认线索压力留到章尾", combined_text)

  def test_knowledge_review_prioritizes_chapter_scoped_obsidian_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "agent-obsidian-priority-vault"
    vault_dir.mkdir()
    for index in range(12):
      (vault_dir / f"00无关-{index}.md").write_text(
        f"""---
type: note
status: canonical
---
# 无关笔记 {index}

这份笔记记录另一个城市的天气。
""",
        encoding="utf-8",
      )
    (vault_dir / "99第二章任务.md").write_text(
      """---
type: clue
status: canonical
chapter_range: 2-2
required_phrases: [银潮灯]
---
# 第二章任务

第二章必须让银潮灯进入主线。
""",
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    runtime = _build_runtime_state(self.settings, self.project.id)
    captured_prompts: list[str] = []

    def fake_model(_settings, messages, **_kwargs):
      prompt = "\n\n".join(str(item.get("content") or "") for item in messages)
      captured_prompts.append(prompt)
      return "资料分析完成。"

    with patch("novel_backend.services.agent_service._invoke_model", side_effect=fake_model):
      summary, material_count = _review_project_knowledge(
        self.settings,
        runtime,
        "先分析资料，再写第二章。",
        task_pack_kind="continuation",
        chapter_index=2,
      )

    self.assertEqual(material_count, 13)
    combined_text = "\n".join([summary, *captured_prompts])
    self.assertIn("第二章任务", combined_text)
    self.assertIn("银潮灯", combined_text)

  def test_review_knowledge_action_inherits_next_chapter_scope(self) -> None:
    actions = _scope_review_knowledge_actions([
      AgentPlanAction(kind="review_knowledge", label="分析资料库"),
      AgentPlanAction(kind="chapter_generate", label="生成第二章", chapter_id="chapter-002"),
    ])
    self.assertEqual(actions[0].chapter_id, "chapter-002")

    architecture_actions = _scope_review_knowledge_actions([
      AgentPlanAction(kind="review_knowledge", label="分析资料库"),
      AgentPlanAction(kind="generate_architecture", label="生成整书架构"),
      AgentPlanAction(kind="chapter_generate", label="生成第二章", chapter_id="chapter-002"),
    ])
    self.assertEqual(architecture_actions[0].chapter_id, "")

  def test_review_knowledge_contract_counts_only_target_chapter_obsidian_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "agent-contract-obsidian-vault"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-1
---
当前线索：林追只知道潮汐编号。
""",
      encoding="utf-8",
    )
    (vault_dir / "终局真相.md").write_text(
      """---
status: canonical
chapter_range: 3-3
reveal_after_chapter: 2
---
终局真相：沉船真相来自港务长自导自演。
""",
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    runtime = _build_runtime_state(self.settings, self.project.id)
    plan = AgentPlan(
      id="plan-review-contract",
      title="分析资料",
      summary="分析资料后写第一章",
      actions=[AgentPlanAction(kind="review_knowledge", label="分析资料库", chapter_id="chapter-001")],
    )

    report = evaluate_agent_action_contract(
      self.settings,
      runtime,
      plan,
      plan.actions[0],
    )

    knowledge_check = next(item for item in report["checks"] if item["id"] == "knowledge_materials")
    self.assertEqual(knowledge_check["status"], "pass")
    self.assertIn("第 1 章可用资料数量：1", knowledge_check["message"])

  def test_discussion_request_does_not_persist_summary_without_confirmation(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "reply": "先把主角和铜钥匙的关系定死，再补追兵怎么逼近。",
                  "suggestions": ["主角为什么不能交出钥匙"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[AgentMessage(role="user", content="聊聊这本书的方向")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "execution")
    self.assertTrue(result_event[1]["can_save_discussion_summary"])
    self.assertEqual(result_event[1]["changes"], [])
    artifact_kinds = [item["kind"] for item in result_event[1]["artifacts"]]
    self.assertIn("learning_review", artifact_kinds)
    learning_artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "learning_review")
    self.assertGreaterEqual(learning_artifact["metadata"]["memory_candidate_count"], 1)

    detail = get_project_detail(self.settings, self.project.id)
    manual_entries = [item for item in detail.story_overview.memory_entries if item.source == "manual"]
    self.assertEqual(manual_entries, [])

    trajectories = get_agent_trajectory_records(self.settings, tail=10)["records"]
    self.assertEqual(trajectories[0]["status"], "completed")
    self.assertEqual(trajectories[0]["project_id"], self.project.id)

  def test_approved_plan_executes_and_updates_chapter(self) -> None:
    plan = AgentPlan(
      id="plan-test",
      title="续写第 1 章",
      summary="先写正文",
      requires_confirmation=True,
      steps=["续写第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="续写第 1 章",
          chapter_id="chapter-001",
          instruction="保留港口悬疑气氛。",
          target_words=1200,
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._generate_chapter",
      return_value=ChapterGenerateResult(
        task_id="chapter-generate-task",
        headline="正文已生成",
        summary="这一版先把追兵压近，再把钥匙用途露半格。",
        content="# 第一章 雨夜靠港\n他把钥匙塞进口袋，听见潮声后面有人跟来。\n",
        next_action="继续收紧追兵视角。",
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="续写这一章"),
                AgentMessage(role="assistant", content="先写正文"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "execution")
    self.assertIn("已经生成并写回项目", result_event[1]["reply"])
    self.assertIn("已更新第 1 章《第一章 雨夜靠港》正文", result_event[1]["changes"])
    event_blocks = result_event[1]["event_blocks"]
    self.assertEqual(event_blocks[-1]["event_type"], "session_result")
    self.assertEqual(event_blocks[-1]["title"], "执行结果")
    self.assertIn("已经生成并写回项目", event_blocks[-1]["summary"])
    workflow_artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "workflow_run")
    workflow_path = Path(workflow_artifact["metadata"]["path"])
    self.assertTrue(workflow_path.exists())
    workflow_payload = json.loads(workflow_path.read_text(encoding="utf-8"))
    self.assertEqual(workflow_payload["status"], "SUCCEEDED")
    self.assertEqual(workflow_payload["actions"][0]["status"], "SUCCEEDED")
    self.assertEqual(workflow_payload["actions"][0]["contract"]["status"], "pass")
    self.assertEqual(workflow_payload["actions"][0]["output_validation"]["status"], "pass")
    subtask_dir = workflow_path.parent / "subtasks"
    self.assertTrue(any(subtask_dir.glob("*.json")))

    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("他把钥匙塞进口袋", chapter.content)

  def test_approved_plan_stops_after_workflow_interrupt_request(self) -> None:
    plan = AgentPlan(
      id="plan-interrupt",
      title="两步讨论",
      summary="第一步完成后停止。",
      requires_confirmation=True,
      steps=["讨论第一步", "讨论第二步"],
      actions=[
        AgentPlanAction(kind="brainstorm", label="讨论第一步", instruction="讨论第一步。"),
        AgentPlanAction(kind="brainstorm", label="讨论第二步", instruction="讨论第二步。"),
      ],
    )
    calls: list[str] = []

    def fake_brainstorm(settings, request, task_id):
      calls.append(str(task_id))
      if len(calls) == 1:
        project = get_project_detail(settings, self.project.id)
        request_agent_workflow_interrupt(Path(project.path), task_id, message="作者停止长任务。")
      return SimpleNamespace(reply=f"讨论完成 {len(calls)}", suggestions=[], skill_candidate=None)

    with patch("novel_backend.services.agent_service._generate_brainstorm", side_effect=fake_brainstorm):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[
                AgentMessage(role="user", content="连续讨论两步"),
                AgentMessage(role="assistant", content="准备执行两步讨论。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    self.assertEqual(len(calls), 1)
    self.assertTrue(any(item[0] == "action_result" and item[1]["label"] == "讨论第一步" for item in events))
    self.assertFalse(any(item[0] == "action_started" and item[1]["label"] == "讨论第二步" for item in events))
    finished_event = next(item for item in events if item[0] == "session_finished")
    self.assertEqual(finished_event[1]["status"], "cancelled")
    task_id = next(item[1]["task_id"] for item in events if item[0] == "session_started")
    project = get_project_detail(self.settings, self.project.id)
    workflow_payload = load_agent_workflow_run(Path(project.path), task_id)
    assert workflow_payload is not None
    self.assertEqual(workflow_payload["status"], "CANCELLED")
    self.assertEqual(workflow_payload["actions"][0]["status"], "SUCCEEDED")
    self.assertEqual(workflow_payload["actions"][1]["status"], "CANCELLED")

  def test_chapter_generate_reports_obsidian_maintenance_artifact(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "agent-obsidian-vault"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    plan = AgentPlan(
      id="plan-write-with-obsidian-maintenance",
      title="写第一章",
      summary="生成正文并写回项目。",
      requires_confirmation=True,
      steps=["写第一章"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="写第一章",
          chapter_id="chapter-001",
          instruction="写第一章正文。",
          target_words=1200,
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._generate_chapter",
      return_value=ChapterGenerateResult(
        task_id="chapter-generate-task",
        headline="正文已生成",
        summary="第一章已经写出追兵和旧码头线索。",
        content="# 第一章 雨夜靠港\n林追在旧码头握住铜钥匙，银潮灯照见旧船队徽记。\n",
        next_action="",
      ),
    ), patch("novel_backend.services.project_narrative_state_service._model_available", return_value=False):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="写第一章正文"),
                AgentMessage(role="assistant", content="生成正文并写回项目。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("已生成第 1 章相关 Obsidian 维护产物 1 条", result_event[1]["changes"])
    obsidian_artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "obsidian_maintenance")
    self.assertEqual(obsidian_artifact["metadata"]["chapter_index"], 1)
    self.assertEqual(obsidian_artifact["metadata"]["item_count"], 1)
    self.assertIn("ChapterNotes/第001章", obsidian_artifact["content_preview"])
    self.assertIn("待审草稿", obsidian_artifact["content_preview"])

  def test_approved_multi_chapter_plan_refreshes_knowledge_summary_per_chapter(self) -> None:
    plan = AgentPlan(
      id="plan-multi-chapter-knowledge",
      title="分析资料并写第 2 到 3 章",
      summary="先分析资料，再逐章写正文。",
      requires_confirmation=True,
      steps=["分析资料", "写第 2 章", "写第 3 章"],
      actions=[
        AgentPlanAction(
          kind="review_knowledge",
          label="分析资料库",
          instruction="先分析资料，再写第2到3章正文。",
        ),
        AgentPlanAction(
          kind="chapter_generate",
          label="写第 2 章",
          chapter_id="chapter-002",
          instruction="写第2到3章正文。",
          target_words=1200,
        ),
        AgentPlanAction(
          kind="chapter_generate",
          label="写第 3 章",
          chapter_id="chapter-003",
          instruction="写第2到3章正文。",
          target_words=1200,
        ),
      ],
    )
    review_chapter_indexes: list[int] = []
    generated_instructions: dict[str, str] = {}

    def fake_review(_settings, _runtime, _instruction, *, task_pack_kind: str = "", chapter_index: int = 0):
      review_chapter_indexes.append(chapter_index)
      return f"第 {chapter_index} 章资料摘要", 1

    def fake_generate(_settings, request, _task_id):
      generated_instructions[request.chapter_id] = request.instruction
      chapter_index = int(request.chapter_id.rsplit("-", 1)[1])
      return ChapterGenerateResult(
        task_id=f"chapter-generate-{chapter_index}",
        headline="正文已生成",
        summary=f"已生成第 {chapter_index} 章。",
        content=f"# 第{chapter_index}章\n正文使用第 {chapter_index} 章资料摘要。\n",
        next_action="",
      )

    with patch("novel_backend.services.agent_service._review_project_knowledge", side_effect=fake_review), patch(
      "novel_backend.services.agent_service._generate_chapter",
      side_effect=fake_generate,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[
                AgentMessage(role="user", content="先分析资料，再写第2到3章正文。"),
                AgentMessage(role="assistant", content="先分析资料，再逐章写正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "execution")
    self.assertEqual(review_chapter_indexes, [2, 3])
    self.assertIn("第 2 章资料摘要", generated_instructions["chapter-002"])
    self.assertIn("第 3 章资料摘要", generated_instructions["chapter-003"])
    self.assertNotIn("第 2 章资料摘要", generated_instructions["chapter-003"])
    self.assertIn("已按第 3 章刷新资料库和 Obsidian 分析", result_event[1]["changes"])

  def test_approved_plan_injects_active_custom_skill_into_chapter_generation(self) -> None:
    self._write_custom_skill(
      "user-dialogue-voice",
      "对白整理",
      scenes=["对白", "章节"],
      body_note="处理对白时保留人物口气，不把人物写成一个声线。",
    )
    captured_instruction = ""
    plan = AgentPlan(
      id="plan-custom-skill",
      title="续写第 1 章",
      summary="按用户技能续写正文。",
      requires_confirmation=True,
      steps=["续写第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="续写第 1 章",
          chapter_id="chapter-001",
          instruction="让对白保持紧张。",
          target_words=1200,
        )
      ],
    )

    def fake_generate(_settings, request, _task_id):
      nonlocal captured_instruction
      captured_instruction = request.instruction
      return ChapterGenerateResult(
        task_id="chapter-generate-task",
        headline="正文已生成",
        summary="这一版保留对白差异。",
        content="# 第一章 雨夜靠港\n林追没有回答，只把钥匙握得更紧。\n",
        next_action="继续处理对白。",
      )

    with patch(
      "novel_backend.services.agent_service._generate_chapter",
      side_effect=fake_generate,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              active_skill_ids=["user-dialogue-voice"],
              messages=[
                AgentMessage(role="user", content="续写这一章，使用对白整理。"),
                AgentMessage(role="assistant", content="直接续写正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("处理对白时保留人物口气", captured_instruction)
    self.assertIn("已启用用户技能：对白整理", result_event[1]["changes"])

  def test_execution_suggests_saving_reusable_skill_from_natural_language(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追说：我们不能回头。\n",
    )
    plan = AgentPlan(
      id="plan-suggest-skill",
      title="去 AI 第 1 章",
      summary="按要求修订正文。",
      requires_confirmation=True,
      steps=["去 AI 并写回第 1 章"],
      actions=[
        AgentPlanAction(
          kind="rewrite_chapter",
          label="去 AI 第 1 章",
          chapter_id="chapter-001",
          mode="humanize",
          instruction="保剧情，先检查模板腔，再整理对白口气，然后输出保剧情的改稿方式，最后保留事实。",
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._rewrite_chapter",
      return_value=ChapterRewriteResult(
        task_id="rewrite-task",
        headline="已处理",
        summary="保留剧情，只调整模板腔和对白口气。",
        original="# 第一章\n林追说：我们不能回头。\n",
        revised="# 第一章\n林追压低声音：不能回头。\n",
        changes=["检查模板腔", "整理对白口气", "保留剧情事实"],
      ),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(
                  role="user",
                  content="这次处理章节去 AI：先检查模板腔，再整理对白口气，然后输出保剧情的改稿方式，最后保留事实。",
                ),
                AgentMessage(role="assistant", content="按这套方式处理。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("把这套处理方式保存成用户技能。", result_event[1]["suggestions"])
    learning_artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "learning_review")
    self.assertEqual(learning_artifact["metadata"]["skill_candidate_count"], 1)

  def test_approved_plan_executes_knowledge_review_before_architecture(self) -> None:
    plan = AgentPlan(
      id="plan-knowledge-review",
      title="先分析资料库再补架构",
      summary="先分析资料库，再执行架构。",
      requires_confirmation=True,
      steps=["先分析资料库", "补齐整书架构"],
      actions=[
        AgentPlanAction(
          kind="review_knowledge",
          label="分析资料库",
          instruction="请把资料库的资料分析完，再重新整理架构。",
        ),
        AgentPlanAction(
          kind="generate_architecture",
          label="生成整书架构",
          instruction="请把资料库的资料分析完，再重新整理架构。",
        ),
      ],
    )

    with patch(
      "novel_backend.services.agent_service._review_project_knowledge",
      return_value=("已确认事实：\n- 旧船队名单被改写。", 1),
    ) as mock_review, patch(
      "novel_backend.services.agent_service._generate_full_architecture",
      return_value=(get_project_detail(self.settings, self.project.id), None),
    ) as mock_generate:
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              messages=[
                AgentMessage(role="user", content="请把资料库的资料分析完，再重新整理架构。"),
                AgentMessage(role="assistant", content="先分析资料库，再补架构。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "execution")
    self.assertEqual(result_event[1]["task_pack_kind"], "architecture")
    self.assertIn("本轮按 architecture 任务包执行", result_event[1]["changes"])
    self.assertEqual(result_event[1]["execution_trace"][0]["task_pack_kind"], "architecture")
    self.assertEqual(result_event[1]["execution_trace"][0]["action_kind"], "review_knowledge")
    self.assertEqual(result_event[1]["execution_trace"][1]["action_kind"], "generate_architecture")
    self.assertIn("已先分析资料库和 Obsidian 1 份资料", result_event[1]["reply"])
    self.assertIn("已分析资料库和 Obsidian 1 份资料", result_event[1]["changes"])
    self.assertTrue(mock_review.called)
    self.assertIn("资料库分析结论", mock_generate.call_args.args[2])

  def test_write_plan_carries_style_xp_and_chapter_constraints(self) -> None:
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            style_name="冷雾叙事",
            xp_preset="悬疑推进",
            characters_involved="林追、白石",
            key_items="铜钥匙",
            scene_location="旧码头仓库",
            time_constraint="涨潮前一小时",
            messages=[AgentMessage(role="user", content="续写这一章")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    chapter_action = result_event[1]["plan"]["actions"][1]
    self.assertEqual(chapter_action["kind"], "chapter_generate")
    self.assertEqual(chapter_action["style_name"], "冷雾叙事")
    self.assertEqual(chapter_action["xp_preset"], "悬疑推进")
    self.assertEqual(chapter_action["characters_involved"], "林追、白石")
    self.assertEqual(chapter_action["key_items"], "铜钥匙")
    self.assertEqual(chapter_action["scene_location"], "旧码头仓库")
    self.assertEqual(chapter_action["time_constraint"], "涨潮前一小时")

  def test_approved_chapter_generate_uses_partial_pipeline(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.6-plus",
      ),
    )
    self._write_chapter_without_review(
      "chapter-001",
      "# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n",
    )
    plan = AgentPlan(
      id="plan-single-pipeline",
      title="续写第 1 章",
      summary="直接续写正文。",
      requires_confirmation=True,
      steps=["续写第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="续写第 1 章",
          chapter_id="chapter-001",
          instruction="让门外白光逼近。",
          target_words=1200,
        )
      ],
    )
    brief_response = {
      "choices": [
        {
          "message": {
            "content": json.dumps(
              {
                "summary": "继续承接仓库门外的危险。",
                "last_state": ["林追在仓库内，手里有铜钥匙"],
                "active_characters": ["林追"],
                "open_threads": ["门外白光逼近"],
                "next_beat": "让门外危险更近一步。",
                "hard_constraints": ["林追不能放下铜钥匙"],
                "avoid_conflicts": ["不要提前揭开钥匙用途"],
                "next_action": "继续写门外动静。",
              },
              ensure_ascii=False,
            )
          }
        }
      ]
    }
    partial_response = {
      "choices": [
        {
          "message": {
            "content": "门缝里亮光一闪，林追把铜钥匙扣进掌心，听见墙外有人停住了呼吸。\n"
          }
        }
      ]
    }
    judge_response = {
      "choices": [
        {
          "message": {
            "content": json.dumps(
              {
                "summary": "没有发现硬冲突。",
                "passed": True,
                "conflicts": [],
                "rewrite_focus": [],
                "next_action": "下一段让林追决定去留。",
              },
              ensure_ascii=False,
            )
          }
        }
      ]
    }
    brief_returned = False
    captured_payloads: list[dict[str, object]] = []

    def fake_request(_endpoint, _api_key, payload):
      nonlocal brief_returned
      captured_payloads.append(payload)
      if payload["messages"][-1].get("partial"):
        return partial_response
      if not brief_returned:
        brief_returned = True
        return brief_response
      return judge_response

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=fake_request,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="续写这一章"),
                AgentMessage(role="assistant", content="直接续写正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["mode"], "execution")
    self.assertGreaterEqual(len(captured_payloads), 3)
    self.assertTrue(captured_payloads[0]["enable_thinking"])
    partial_payloads = [
      item for item in captured_payloads if item["messages"][-1].get("partial")
    ]
    self.assertGreaterEqual(len(partial_payloads), 1)
    self.assertTrue(all(item["enable_thinking"] is False for item in partial_payloads))
    self.assertTrue(any(item.get("enable_thinking") for item in captured_payloads[1:]))
    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("门缝里亮光一闪", chapter.content)


if __name__ == "__main__":
  unittest.main()
