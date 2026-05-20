from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import (
  ChapterUpdateRequest,
  CreateProjectRequest,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
)
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.context_builder import build_project_context_bundle, build_prompt_support, explicit_length_target
from novel_backend.services.project_service import (
  create_project,
  import_project_knowledge,
  update_chapter_content,
  update_project_memory,
  update_story_document,
)
from novel_backend.models import KnowledgeImportItem, KnowledgeImportRequest, StoryDocumentUpdateRequest


class ContextBuilderTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self.project = create_project(
      self.settings,
      CreateProjectRequest(name="上下文测试", genre="悬疑", target_chapters=3, target_words=50000),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "core_seed",
      StoryDocumentUpdateRequest(content="失踪航线钥匙会暴露主角的真实身世。"),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "blueprint",
      StoryDocumentUpdateRequest(content="第一章拿到钥匙，第二章试探白石商会。"),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n"),
    )
    update_project_memory(
      self.settings,
      self.project.id,
      ProjectMemoryUpdateRequest(
        entries=[ProjectMemoryEntryInput(category="硬规则", title="作者要求", content="林追不能主动暴露真实身份。")]
      ),
    )
    import_project_knowledge(
      self.settings,
      self.project.id,
      KnowledgeImportRequest(
        items=[KnowledgeImportItem(title="旧船队记录", content="铜钥匙是隐秘航线的启航凭证。")]
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_project_context_bundle_includes_documents_chapter_and_knowledge(self) -> None:
    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      include_blueprint=True,
      include_character_state=True,
      chapter_id="chapter-001",
      knowledge_query="铜钥匙",
      task_instruction="请继续续写这一章。",
    )

    self.assertIn("核心种子：失踪航线钥匙", bundle.context_text)
    self.assertIn("章节容量校验：全书目标 50000 字 / 3 章", bundle.context_text)
    self.assertIn("本章目前明显偏短", bundle.context_text)
    self.assertIn("当前章节：第 1 章《第一章 雨夜靠港》", bundle.context_text)
    self.assertIn("作者明确要求 / 硬规则 / 作者要求", bundle.context_text)
    self.assertIn("系统整理 / 连续性 / 最近推进", bundle.context_text)
    self.assertIn("任务蒸馏：", bundle.context_text)
    self.assertIn("continuation 任务包", bundle.context_text)
    self.assertIn("检索线索：", bundle.context_text)
    self.assertGreaterEqual(len(bundle.knowledge_hits), 1)
    self.assertIsNotNone(bundle.budget_report)
    self.assertEqual(bundle.budget_report.trimmed_blocks, [])

  def test_explicit_length_target_accepts_common_chinese_word_counts(self) -> None:
    cases = {
      "写15000字": 15_000,
      "写1万字": 10_000,
      "写1.5万字": 15_000,
      "写1万5千字": 15_000,
      "写一万五千字": 15_000,
      "写一万五字": 15_000,
      "写三千五百字": 3_500,
      "写三千五字": 3_500,
      "写三千零五字": 3_005,
      "写十万字": 30_000,
      "当前正文约3870字，远低于15000字目标，需完整重写": 15_000,
      "将原约2000字短稿扩展为完整章节（约15000字）": 15_000,
    }

    for instruction, expected in cases.items():
      with self.subTest(instruction=instruction):
        self.assertEqual(explicit_length_target(instruction), expected)

    self.assertEqual(explicit_length_target("保存校验：当前正文约 3870 字。"), 0)
    self.assertEqual(explicit_length_target("当前正文仅约3870字，需完整重写"), 0)

  def test_project_context_bundle_trims_oversized_chapter_body(self) -> None:
    long_body = "# 第一章 雨夜靠港\n" + "\n".join(
      f"林追在旧码头仓库第 {index} 次确认铜钥匙还在掌心，门外白光继续逼近。"
      for index in range(900)
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content=long_body),
    )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="请继续续写这一章。",
    )

    self.assertIsNotNone(bundle.budget_report)
    trimmed_blocks = bundle.budget_report.trimmed_blocks
    self.assertTrue(any(item.block == "当前章节正文" for item in trimmed_blocks))
    self.assertIn("当前章节正文中间内容已按上下文预算缩短", bundle.context_text)
    self.assertLess(len(bundle.context_text), len(long_body))

  def test_project_context_bundle_includes_reference_blocks_from_imported_source(self) -> None:
    import_project_knowledge(
      self.settings,
      self.project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="围城原文节选",
            content=(
              "方鸿渐回到寓所，孙柔嘉冷笑着问他在外面跟谁闲逛。"
              "赵辛楣后来来信，只说方鸿渐的婚姻像穿错的鞋。"
            ),
          )
        ]
      ),
    )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="接着原文续写。",
    )

    self.assertIn("参考人物：", bundle.context_text)
    self.assertIn("方鸿渐", bundle.context_text)
    self.assertIn("孙柔嘉", bundle.context_text)
    self.assertIn("参考事件：", bundle.context_text)
    self.assertIn("围城原文节选", bundle.context_text)
    self.assertIn("原作承接提醒：", bundle.context_text)

  def test_prompt_support_includes_preset_and_xp(self) -> None:
    support = build_prompt_support(self.settings, task_key="chapter", xp_name="悬疑推进")

    self.assertIn("提示词方案：", support)
    self.assertIn("XP 预设：", support)
