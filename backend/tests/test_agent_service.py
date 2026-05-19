from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  AppConfigUpdateRequest,
  AgentChatRequest,
  AgentMessage,
  AgentThreadMessage,
  AgentThreadRecord,
  AgentThreadStoreUpdateRequest,
  AgentPlan,
  AgentPlanAction,
  BrainstormResult,
  ChapterGenerateResult,
  ChapterAutoRepairConfig,
  ChapterReviewDimension,
  ChapterReviewIssue,
  ChapterReviewReport,
  ChapterRewriteResult,
  ChapterUpdateRequest,
  CreateProjectRequest,
  KnowledgeImportItem,
  KnowledgeImportRequest,
  ModelConfig,
)
from novel_backend.services.agent_service import _build_runtime_state, _review_project_knowledge, agent_session_stream
from novel_backend.services.agent_trajectory_service import get_agent_trajectory_records
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.project_service import (
  create_project,
  save_project_agent_threads,
  get_project_detail,
  import_project_knowledge,
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

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

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
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n旧码头重新亮灯，主角被迫回港。\n"),
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
    self.assertEqual(result_event[1]["plan"]["actions"][1]["target_words"], 3500)
    self.assertIn("计划步骤：", result_event[1]["reply"])

  def test_write_request_respects_explicit_word_count(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n旧码头重新亮灯，主角被迫回港。\n"),
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="续写这一章，写1000字。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    chapter_action = next(item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate")
    self.assertEqual(chapter_action["target_words"], 1000)

  def test_write_request_full_chapter_uses_remaining_project_capacity(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n旧码头重新亮灯，主角被迫回港。\n"),
    )

    events = asyncio.run(
      collect_stream(
        agent_session_stream(
          self.settings,
          AgentChatRequest(
            project_id=self.project.id,
            selected_chapter_id="chapter-001",
            messages=[AgentMessage(role="user", content="把这一章扩成完整章。")],
          ),
        )
      )
    )

    result_event = next(item for item in events if item[0] == "result")
    chapter_action = next(item for item in result_event[1]["plan"]["actions"] if item["kind"] == "chapter_generate")
    self.assertGreaterEqual(chapter_action["target_words"], 9_000)
    self.assertLessEqual(chapter_action["target_words"], 10_000)

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
    self.assertIn("先通读资料库里的 1 份资料", result_event[1]["reply"])

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

  def test_model_plan_respects_user_explicit_chapter_over_selected_chapter(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n"),
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
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n"),
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

  def test_auto_matches_custom_skill_for_natural_language_plan(self) -> None:
    self._write_custom_skill(
      "user-dialogue-humanize",
      "对白去 AI",
      scenes=["去 AI", "对白"],
      body_note="去 AI 时保留人物对白差异。",
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追说：我们不能回头。\n"),
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
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追把铜钥匙塞进口袋，准备回旧码头。\n"),
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

  def test_agent_session_recovers_relevant_chunks_from_long_thread_message(self) -> None:
    long_content = "开头。" + ("潮声里反复出现旧码头的铜钥匙。" * 520) + "星核密钥藏在第七层钟楼。结尾。"
    self.assertGreater(len(long_content), 6000)
    save_project_agent_threads(
      self.settings,
      self.project.id,
      AgentThreadStoreUpdateRequest(
        active_thread_id="thread-long",
        threads=[
          AgentThreadRecord(
            id="thread-long",
            title="长线程",
            preview="长线程预览",
            updated_at="2026-05-15T12:00:00+00:00",
            messages=[AgentThreadMessage(id="message-long", role="user", content=long_content)],
          )
        ],
      ),
    )

    def fake_brainstorm(_settings, request, _task_id):
      self.assertIn("第七层钟楼", request.extra_context)
      return BrainstormResult(task_id="brainstorm-task", reply="已读取长线程片段。")

    with patch("novel_backend.services.agent_service._generate_brainstorm", side_effect=fake_brainstorm):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              thread_id="thread-long",
              messages=[AgentMessage(id="message-long", role="user", content="聊聊星核密钥")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["reply"], "已读取长线程片段。")

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
    self.assertTrue(any("章节核验：" in item for item in result_event[1]["changes"]))
    chapter_artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "chapter_content")
    self.assertIn("review_score", chapter_artifact["metadata"])

    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("他把钥匙塞进口袋", chapter.content)

  def test_approved_plan_auto_repairs_low_review_score(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          api_key="test-key",
          base_url="https://example.com/v1",
          model_name="demo-model",
        ),
        chapter_auto_repair=ChapterAutoRepairConfig(max_rounds=2),
      ),
    )
    plan = AgentPlan(
      id="plan-auto-repair",
      title="续写第 1 章",
      summary="写正文并根据核验修订。",
      requires_confirmation=True,
      steps=["续写第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="续写第 1 章",
          chapter_id="chapter-001",
          instruction="保留港口追兵压力。",
          target_words=1200,
        )
      ],
    )
    risk_review = ChapterReviewReport(
      chapter_id="chapter-001",
      chapter_index=1,
      chapter_title="第一章 雨夜靠港",
      engine="test",
      status="risk",
      overall_score=52,
      summary="冲突压力不足，章末悬念偏弱。",
      dimensions=[
        ChapterReviewDimension(
          id="structure",
          label="结构与节奏",
          score=50,
          status="risk",
          summary="压力推进不足。",
          issues=[
            ChapterReviewIssue(level="warning", title="冲突抬升不够", detail="追兵没有形成明确阻力。"),
          ],
        )
      ],
    )
    second_risk_review = risk_review.model_copy(
      update={
        "overall_score": 61,
        "summary": "追兵压力有所加强，但结尾问题仍不足。",
      }
    )
    good_review = ChapterReviewReport(
      chapter_id="chapter-001",
      chapter_index=1,
      chapter_title="第一章 雨夜靠港",
      engine="test",
      status="good",
      overall_score=88,
      summary="压力和章末悬念已经补足。",
      dimensions=[
        ChapterReviewDimension(
          id="structure",
          label="结构与节奏",
          score=88,
          status="good",
          summary="冲突更清楚。",
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._generate_chapter",
      return_value=ChapterGenerateResult(
        task_id="chapter-generate-task",
        headline="正文已生成",
        summary="这一版先写钥匙出场。",
        content="# 第一章 雨夜靠港\n林追把钥匙塞进口袋，雨声淹过码头。\n",
        next_action="继续收紧追兵视角。",
      ),
    ), patch(
      "novel_backend.services.project_service.build_chapter_review",
      side_effect=[risk_review, second_risk_review, good_review],
    ), patch(
      "novel_backend.services.chapter_auto_repair_service._invoke_model",
      side_effect=[
        json.dumps(
          {
            "summary": "先补强追兵阻力。",
            "changes": ["让追兵贴近仓库门"],
            "revised_content": "# 第一章 雨夜靠港\n林追把钥匙塞进口袋，雨声淹过码头。仓库门外的脚步停住，探照灯贴着门缝扫进来。\n",
          },
          ensure_ascii=False,
        ),
        json.dumps(
          {
            "summary": "再补上章末悬念。",
            "changes": ["章末保留钥匙异动"],
            "revised_content": "# 第一章 雨夜靠港\n林追把钥匙塞进口袋，雨声淹过码头。仓库门外的脚步停住，探照灯贴着门缝扫进来。\n钥匙忽然在掌心发热。\n",
          },
          ensure_ascii=False,
        ),
      ],
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
    self.assertIn("自动修订", result_event[1]["reply"])
    self.assertIn("自动修订 2 轮", result_event[1]["reply"])
    self.assertTrue(any("自动修订" in item for item in result_event[1]["changes"]))
    chapter_artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "chapter_content")
    self.assertTrue(chapter_artifact["metadata"]["review_auto_repair_applied"])
    self.assertEqual(chapter_artifact["metadata"]["review_auto_repair_rounds_applied"], 2)
    self.assertEqual(chapter_artifact["metadata"]["review_score"], 88)
    self.assertIn("钥匙忽然在掌心发热", chapter_artifact["content_preview"])

    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("钥匙忽然在掌心发热", chapter.content)

  def test_approved_plan_reports_chapter_review_failure(self) -> None:
    plan = AgentPlan(
      id="plan-review-failure",
      title="续写第 1 章",
      summary="写正文并写回。",
      requires_confirmation=True,
      steps=["续写第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="chapter_generate",
          label="续写第 1 章",
          chapter_id="chapter-001",
          instruction="让追兵靠近。",
          target_words=1200,
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._generate_chapter",
      return_value=ChapterGenerateResult(
        task_id="chapter-generate-task",
        headline="正文已生成",
        summary="追兵已经靠近。",
        content="# 第一章 雨夜靠港\n林追刚扣好门闩，外面的白光就贴上了窗。\n",
        next_action="重新核验本章。",
      ),
    ), patch(
      "novel_backend.services.project_service.build_chapter_review",
      side_effect=RuntimeError("review offline"),
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
                AgentMessage(role="assistant", content="写回正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("章节已保存，但核验失败", result_event[1]["reply"])
    self.assertTrue(any("review offline" in item for item in result_event[1]["changes"]))
    self.assertIn("重新运行章节核验。", result_event[1]["suggestions"])

    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("白光就贴上了窗", chapter.content)

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
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追说：我们不能回头。\n"),
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

  def test_rewrite_auto_completes_when_model_overclaims_length(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n旧码头重新亮灯，主角被迫回港。\n"),
    )
    plan = AgentPlan(
      id="plan-rewrite-length",
      title="重写第 1 章",
      summary="按要求修订正文。",
      requires_confirmation=True,
      steps=["修订第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="rewrite_chapter",
          label="修订第 1 章",
          chapter_id="chapter-001",
          mode="finalize",
          instruction="重写第一章",
        )
      ],
    )
    good_review = ChapterReviewReport(
      chapter_id="chapter-001",
      chapter_index=1,
      chapter_title="第一章",
      engine="test",
      status="good",
      overall_score=86,
      summary="正文保存后可继续扩展。",
      dimensions=[
        ChapterReviewDimension(
          id="structure",
          label="结构与节奏",
          score=86,
          status="good",
          summary="基本顺畅。",
        )
      ],
    )
    completed_text = "# 第一章\n" + ("追兵逼近。" * 2000)
    captured_completion_target = 0

    def fake_completion(_settings, **kwargs):
      nonlocal captured_completion_target
      captured_completion_target = int(kwargs.get("target_words") or 0)
      return {
        "headline": "章节已补足",
        "summary": "已接续短稿补足章节容量。",
        "content": completed_text,
        "next_action": "复查本章。",
        "scenes": [],
        "checklist": [],
      }

    with patch(
      "novel_backend.services.agent_service._rewrite_chapter",
      return_value=ChapterRewriteResult(
        task_id="rewrite-task",
        headline="已处理",
        summary="少年在旧码头遭遇追兵，章节主事件已整理。",
        original="# 第一章\n旧码头重新亮灯，主角被迫回港。\n",
        revised="# 第一章\n旧码头重新亮灯，林追把铜钥匙塞进口袋，听见门外有人停步。\n",
        changes=[
          "将原约2000字短稿扩展为完整章节（约15000字），严格遵循上、中、下三段结构。",
          "新增追兵逼近和铜钥匙异动。",
        ],
      ),
    ), patch(
      "novel_backend.services.project_service.build_chapter_review",
      return_value=good_review,
    ), patch(
      "novel_backend.services.agent_service._run_continuation_pipeline",
      side_effect=fake_completion,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="重写第一章"),
                AgentMessage(role="assistant", content="修订正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("自动续写补足章节容量", result_event[1]["reply"])
    self.assertIn("保存校验", result_event[1]["reply"])
    self.assertNotIn("约15000字", result_event[1]["reply"])
    self.assertIn("新增追兵逼近", result_event[1]["reply"])
    self.assertGreater(captured_completion_target, 0)

    artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "rewrite_report")
    self.assertEqual(artifact["metadata"]["length_status"], "checked")
    self.assertTrue(artifact["metadata"]["length_completion_applied"])
    self.assertLessEqual(captured_completion_target, 4500)
    self.assertGreaterEqual(
      artifact["metadata"]["saved_word_count"],
      int(artifact["metadata"]["length_target_words"] * 0.9),
    )
    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertEqual(chapter.content, completed_text)

  def test_rewrite_restores_original_when_length_completion_fails_before_any_saved_chunk(self) -> None:
    original_content = "# 第一章\n旧码头重新亮灯，主角被迫回港。\n"
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content=original_content),
    )
    plan = AgentPlan(
      id="plan-rewrite-length-fail",
      title="重写第 1 章",
      summary="按要求修订正文。",
      requires_confirmation=True,
      steps=["修订第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="rewrite_chapter",
          label="修订第 1 章",
          chapter_id="chapter-001",
          mode="finalize",
          instruction="重写第一章",
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._rewrite_chapter",
      return_value=ChapterRewriteResult(
        task_id="rewrite-task",
        headline="已处理",
        summary="少年在旧码头遭遇追兵，章节主事件已整理。",
        original=original_content,
        revised="# 第一章\n旧码头重新亮灯，林追把铜钥匙塞进口袋，听见门外有人停步。\n",
        changes=["新增追兵逼近。"],
      ),
    ), patch(
      "novel_backend.services.agent_service._run_continuation_pipeline",
      side_effect=RuntimeError("模型请求超时"),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="重写第一章"),
                AgentMessage(role="assistant", content="修订正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("自动续写补足章节容量失败", result_event[1]["reply"])
    self.assertIn("已恢复本轮改稿前正文", result_event[1]["reply"])
    artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "rewrite_report")
    self.assertTrue(artifact["metadata"]["length_completion_attempted"])
    self.assertFalse(artifact["metadata"]["length_completion_applied"])
    self.assertTrue(artifact["metadata"]["length_completion_restored_original"])
    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertEqual(chapter.content, original_content)

  def test_rewrite_restores_empty_original_when_length_completion_fails(self) -> None:
    original_content = ""
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content=original_content),
    )
    plan = AgentPlan(
      id="plan-rewrite-empty-length-fail",
      title="重写第 1 章",
      summary="按要求修订正文。",
      requires_confirmation=True,
      steps=["修订第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="rewrite_chapter",
          label="修订第 1 章",
          chapter_id="chapter-001",
          mode="finalize",
          instruction="重写第一章",
        )
      ],
    )

    with patch(
      "novel_backend.services.agent_service._rewrite_chapter",
      return_value=ChapterRewriteResult(
        task_id="rewrite-task",
        headline="已处理",
        summary="少年在旧码头遭遇追兵，章节主事件已整理。",
        original=original_content,
        revised="# 第一章\n旧码头重新亮灯，林追把铜钥匙塞进口袋，听见门外有人停步。\n",
        changes=["新增追兵逼近。"],
      ),
    ), patch(
      "novel_backend.services.agent_service._run_continuation_pipeline",
      side_effect=RuntimeError("模型请求超时"),
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="重写第一章"),
                AgentMessage(role="assistant", content="修订正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("自动续写补足章节容量失败", result_event[1]["reply"])
    artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "rewrite_report")
    self.assertFalse(artifact["metadata"]["length_completion_applied"])
    self.assertTrue(artifact["metadata"]["length_completion_restored_original"])
    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertEqual(chapter.content, original_content)

  def test_rewrite_restores_original_when_length_completion_fails_after_partial_chunk(self) -> None:
    original_content = "# 第一章\n旧码头重新亮灯，主角被迫回港。\n"
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content=original_content),
    )
    plan = AgentPlan(
      id="plan-rewrite-length-partial-fail",
      title="重写第 1 章",
      summary="按要求修订正文。",
      requires_confirmation=True,
      steps=["修订第 1 章并写回项目"],
      actions=[
        AgentPlanAction(
          kind="rewrite_chapter",
          label="修订第 1 章",
          chapter_id="chapter-001",
          mode="finalize",
          instruction="重写第一章",
        )
      ],
    )
    partial_text = "# 第一章\n" + ("追兵逼近。" * 500)
    calls = 0

    def fake_completion(_settings, **_kwargs):
      nonlocal calls
      calls += 1
      if calls == 1:
        return {
          "headline": "章节继续扩写",
          "summary": "先补一段追兵压力。",
          "content": partial_text,
          "next_action": "继续补足。",
          "scenes": [],
          "checklist": [],
        }
      raise RuntimeError("模型请求超时")

    with patch(
      "novel_backend.services.agent_service._rewrite_chapter",
      return_value=ChapterRewriteResult(
        task_id="rewrite-task",
        headline="已处理",
        summary="少年在旧码头遭遇追兵，章节主事件已整理。",
        original=original_content,
        revised="# 第一章\n旧码头重新亮灯，林追把铜钥匙塞进口袋，听见门外有人停步。\n",
        changes=["新增追兵逼近。"],
      ),
    ), patch(
      "novel_backend.services.agent_service._run_continuation_pipeline",
      side_effect=fake_completion,
    ):
      events = asyncio.run(
        collect_stream(
          agent_session_stream(
            self.settings,
            AgentChatRequest(
              project_id=self.project.id,
              selected_chapter_id="chapter-001",
              messages=[
                AgentMessage(role="user", content="重写第一章"),
                AgentMessage(role="assistant", content="修订正文。"),
                AgentMessage(role="user", content="确认执行"),
              ],
              approved_plan=plan,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("自动续写补足章节容量失败", result_event[1]["reply"])
    self.assertIn("已恢复本轮改稿前正文", result_event[1]["reply"])
    artifact = next(item for item in result_event[1]["artifacts"] if item["kind"] == "rewrite_report")
    self.assertEqual(artifact["metadata"]["length_completion_rounds_applied"], 1)
    self.assertFalse(artifact["metadata"]["length_completion_applied"])
    self.assertTrue(artifact["metadata"]["length_completion_restored_original"])
    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertEqual(chapter.content, original_content)
    self.assertNotIn("追兵逼近。" * 100, chapter.content)

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
    self.assertIn("已先分析资料库 1 份资料", result_event[1]["reply"])
    self.assertIn("已分析资料库 1 份资料", result_event[1]["changes"])
    self.assertTrue(mock_review.called)
    self.assertIn("资料库分析结论", mock_generate.call_args.args[2])

  def test_write_plan_carries_style_xp_and_chapter_constraints(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n旧码头重新亮灯，主角被迫回港。\n"),
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

  def test_approved_chapter_generate_emits_subtask_events(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.6-plus",
      ),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n"),
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
    with patch(
      "novel_backend.services.studio_service._run_continuation_pipeline",
      return_value={
        "headline": "章节初稿已生成",
        "summary": "已并行生成 3 个候选并完成审校。",
        "content": "# 第一章\n林追在旧码头仓库找到一把铜钥匙。\n门缝里亮光一闪，林追把铜钥匙扣进掌心，听见墙外有人停住了呼吸。\n",
        "next_action": "下一段让林追决定去留。",
      },
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
    subtask_started = [item for item in events if item[0] == "subtask_started"]
    self.assertGreaterEqual(len(subtask_started), 4)
    roles = [item[1]["role"] for item in subtask_started]
    self.assertIn("写作 agent", roles)
    self.assertIn("连续性审校 agent", roles)
    self.assertIn("人物口气审校 agent", roles)
    self.assertIn("可读性审校 agent", roles)
    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("门缝里亮光一闪", chapter.content)


if __name__ == "__main__":
  unittest.main()
