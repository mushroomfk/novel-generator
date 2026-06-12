from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  AppConfigUpdateRequest,
  ChapterUpdateRequest,
  CreateProjectRequest,
  KnowledgeSearchResult,
  ModelConfig,
  ObsidianVaultConfig,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
  ReviewModelConfig,
)
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.context_builder import (
  _context_budget_limit,
  build_project_context_bundle,
  build_prompt_support,
  explicit_length_target,
)
from novel_backend.services.project_distillation_service import build_task_distillation_prompt_block
from novel_backend.services.project_service import (
  create_project,
  get_project_detail,
  import_project_knowledge,
  update_chapter_content,
  update_project_obsidian_config,
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

  def test_architecture_context_uses_lightweight_knowledge_search(self) -> None:
    with patch("novel_backend.services.context_builder.search_project_knowledge", return_value=[]) as mocked_search:
      build_project_context_bundle(
        self.settings,
        self.project.id,
        knowledge_query="铜钥匙",
        task_pack_kind="architecture",
      )

    self.assertEqual(mocked_search.call_count, 1)
    self.assertFalse(mocked_search.call_args.kwargs["ensure_current"])
    self.assertFalse(mocked_search.call_args.kwargs["include_semantic"])

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

  def test_project_context_bundle_keeps_final_text_under_context_limit(self) -> None:
    with patch("novel_backend.services.context_builder._context_budget_limit", return_value=900):
      bundle = build_project_context_bundle(
        self.settings,
        self.project.id,
        chapter_id="chapter-001",
        knowledge_query="铜钥匙",
        task_instruction="请继续续写这一章。",
      )

    self.assertIsNotNone(bundle.budget_report)
    self.assertLessEqual(len(bundle.context_text), bundle.budget_report.limit_chars)
    self.assertEqual(bundle.budget_report.final_chars, len(bundle.context_text))
    self.assertFalse(any(item.block == "完整上下文" for item in bundle.budget_report.trimmed_blocks))
    self.assertGreater(len(bundle.context_lines), 1)
    self.assertIn("林追不能主动暴露真实身份", bundle.context_text)

  def test_context_budget_limit_expands_with_large_model_capacity_signal(self) -> None:
    base_limit = _context_budget_limit("continuation", model_max_tokens=8192)
    expanded_limit = _context_budget_limit("continuation", model_max_tokens=64000)

    self.assertGreater(expanded_limit, base_limit)
    self.assertLessEqual(expanded_limit, 42_000)

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

  def test_project_context_bundle_expands_obsidian_graph_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    (vault_dir / "林追.md").write_text(
      """---
type: character
status: canonical
related_organizations:
  - 灯塔议会
---
# 林追

林追正在调查[[灯塔议会]]。

必须出现：铜钥匙
禁止出现：林追主动交出铜钥匙
""",
      encoding="utf-8",
    )
    (vault_dir / "灯塔议会.md").write_text(
      """---
type: organization
status: canonical
---
# 灯塔议会

灯塔议会掌握旧码头靠港记录。
""",
      encoding="utf-8",
    )
    (vault_dir / "无关笔记.md").write_text(
      """---
type: note
status: canonical
---
这份笔记记录另一个城市的天气。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="写林追继续追查铜钥匙。",
    )

    self.assertIn("Obsidian 设定笔记：", bundle.context_text)
    self.assertIn("林追", bundle.context_text)
    self.assertIn("关联笔记：灯塔议会", bundle.context_text)
    self.assertIn("关系：相关组织 -> 灯塔议会", bundle.context_text)
    self.assertIn("被引用：林追", bundle.context_text)
    self.assertIn("本章 Obsidian 设定检查清单：", bundle.context_text)
    self.assertIn("来源｜林追（林追.md）", bundle.context_text)
    self.assertIn("必须出现：铜钥匙", bundle.context_text)
    self.assertIn("禁止出现：林追主动交出铜钥匙", bundle.context_text)
    self.assertIn("本章 Obsidian 写作约束：", bundle.context_text)
    self.assertIn("必须包含｜林追", bundle.context_text)
    self.assertIn("铜钥匙", bundle.context_text)
    self.assertIn("禁止出现｜林追", bundle.context_text)
    self.assertIn("林追主动交出铜钥匙", bundle.context_text)
    self.assertNotIn("无关笔记", bundle.context_text)

  def test_project_context_bundle_includes_safe_obsidian_embed_previews(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-embed-preview"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Plans" / "潮声场景卡.md").write_text(
      """---
status: canonical
chapter_range: 1
---
# 潮声场景卡

林追在旧码头听到潮声异常，并把铜钥匙藏进袖口。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "终局真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 2
---
# 终局真相

沉船答案只允许第三章之后出现。
""",
      encoding="utf-8",
    )
    (vault_dir / "第一章计划.md").write_text(
      """---
status: canonical
chapter_range: 1
---
# 第一章计划

第一章计划要使用潮声异常场景卡。

![[Plans/潮声场景卡]]
![[Secrets/终局真相]]
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="按照第一章计划写林追在旧码头听到潮声异常。",
    )

    self.assertIn("嵌入预览：潮声场景卡", bundle.context_text)
    self.assertIn("林追在旧码头听到潮声异常", bundle.context_text)
    self.assertNotIn("终局真相", bundle.context_text)
    self.assertNotIn("沉船答案", bundle.context_text)

  def test_project_context_bundle_includes_obsidian_external_links(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-external-links"
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "旧码头考据.md").write_text(
      """---
status: canonical
chapter_range: 1-1
summary: 旧码头水利史影响铜钥匙线索。
source_url: "[旧码头水利史档案](https://example.com/old-harbor-waterworks)"
---
# 旧码头考据

第一章只需要知道旧码头水利史。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "终局考据.md").write_text(
      """---
status: canonical
reveal_after_chapter: 2
source_url: "[终局考据档案](https://example.com/final-truth)"
---
# 终局考据

沉船答案只能第三章以后出现。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="写第一章旧码头水利史和铜钥匙。",
    )

    self.assertIn("考据来源：旧码头水利史档案：https://example.com/old-harbor-waterworks", bundle.context_text)
    self.assertNotIn("https://example.com/final-truth", bundle.context_text)
    self.assertNotIn("沉船答案", bundle.context_text)

  def test_project_context_bundle_renders_canvas_relations_with_note_titles(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-title"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Plans").mkdir()
    (vault_dir / "Maps").mkdir()
    (vault_dir / "Clues" / "clue-001.md").write_text(
      """---
title: 铜钥匙线索
status: canonical
chapter_range: 1-3
---
# 铜钥匙线索

林追在旧码头仓库找到铜钥匙。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "plan-002.md").write_text(
      """---
title: 第二章会馆计划
status: canonical
chapter_range: 1-3
---
# 第二章会馆计划

铜钥匙会把林追引到白石会馆。
""",
      encoding="utf-8",
    )
    (vault_dir / "Maps" / "关系图.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "clue", "type": "file", "file": "../Clues/clue-001.md"},
            {"id": "plan", "type": "file", "file": "../Plans/plan-002.md"},
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nchapter_range:: 1-3\nsummary:: 关系图记录铜钥匙线索如何推动第二章会馆计划。\nkeywords:: 关系图 铜钥匙 会馆计划",
            },
          ],
          "edges": [
            {"id": "edge-1", "fromNode": "clue", "toNode": "plan", "label": "推动"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="参考关系图，写铜钥匙如何推动会馆计划。",
    )

    self.assertIn("关系：推动：铜钥匙线索 -> 第二章会馆计划", bundle.context_text)
    self.assertNotIn("推动：clue-001 -> Plans/plan-002.md", bundle.context_text)

  def test_project_context_bundle_uses_previous_chapter_tail_for_obsidian_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    for index in range(9):
      (vault_dir / f"00无关-{index}.md").write_text(
        f"""---
type: note
status: canonical
---
# 无关笔记 {index}

这份笔记记录别的城市。
""",
        encoding="utf-8",
      )
    (vault_dir / "白石会馆.md").write_text(
      """---
type: location
status: canonical
---
# 白石会馆

白石会馆掌握旧船队暗账。
""",
      encoding="utf-8",
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在章末走进白石会馆，听见旧船队账册被合上。\n"),
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-002",
      task_instruction="继续写下一章。",
    )

    self.assertIn("白石会馆掌握旧船队暗账", bundle.context_text)

  def test_project_context_bundle_selects_obsidian_notes_by_frontmatter_constraints(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-frontmatter-constraints"
    vault_dir.mkdir()
    for index in range(9):
      (vault_dir / f"00无关-{index}.md").write_text(
        f"""---
type: note
status: canonical
---
# 无关笔记 {index}

这份笔记记录另一个城市。
""",
        encoding="utf-8",
      )
    (vault_dir / "99规则.md").write_text(
      """---
type: rule
status: canonical
required_phrases: [潮汐密码]
forbidden_phrases: [潮汐密码被公开破解]
---
# 港口暗线

这份笔记的正文没有写出关键约束词。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-002",
      task_instruction="下一章让潮汐密码第一次进入主线。",
    )

    self.assertIn("港口暗线", bundle.context_text)
    self.assertIn("本章 Obsidian 写作约束：", bundle.context_text)
    self.assertIn("必须包含｜港口暗线", bundle.context_text)
    self.assertIn("潮汐密码", bundle.context_text)
    self.assertIn("禁止出现｜港口暗线", bundle.context_text)
    self.assertIn("潮汐密码被公开破解", bundle.context_text)

  def test_project_context_bundle_prioritizes_chapter_scoped_obsidian_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-scoped-priority"
    vault_dir.mkdir()
    for index in range(9):
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
forbidden_phrases: [银潮灯提前熄灭]
---
# 第二章任务

第二章必须让银潮灯进入主线。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-002",
      task_instruction="继续写下一章。",
    )

    self.assertIn("来源｜第二章任务（99第二章任务.md）", bundle.context_text)
    self.assertIn("本章 Obsidian 写作约束：", bundle.context_text)
    self.assertIn("必须包含｜第二章任务", bundle.context_text)
    self.assertIn("银潮灯", bundle.context_text)
    self.assertIn("禁止出现｜第二章任务", bundle.context_text)
    self.assertIn("银潮灯提前熄灭", bundle.context_text)

  def test_project_context_bundle_filters_obsidian_notes_by_chapter_scope(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-scope"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
type: clue
status: canonical
chapter_range: 1-10
aliases: [当前潮标, "[[未来真相]]", 未来真相]
keywords: [青铜潮标, "[[未来真相]]", 未来真相]
required_phrases: [青铜潮标, "[[未来真相|潮声异常]]", "不要写未来真相"]
forbidden_phrases: ["[[未来真相]]", "[未来真相](未来真相.md)", 未来真相]
foreshadows:
  - 未来真相
related_locations:
  - 旧码头
---
# 当前线索

青铜潮标指向旧码头仓库，不提前点名[[未来真相]]。
另一个 Obsidian 内链写法是 [潮声异常](未来真相.md)，不能写 [未来真相](未来真相.md)。
普通正文里也可能直接写未来真相这个纯文本名称。
""",
      encoding="utf-8",
    )
    (vault_dir / "旧码头.md").write_text(
      """---
type: location
status: canonical
chapter_range: 1-10
---
# 旧码头

旧码头仓库保存青铜潮标。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
type: secret
status: canonical
chapter_range: 70-80
required_phrases: [沉船真相]
forbidden_phrases: [提前公开沉船真相]
---
# 未来真相

沉船真相来自第七十章以后才会出现的证据，并反向引用[[当前线索]]。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-002",
      knowledge_query="青铜潮标 沉船真相",
      task_instruction="继续写青铜潮标，不提前公开沉船真相。",
    )

    self.assertIn("当前线索", bundle.context_text)
    self.assertIn("青铜潮标", bundle.context_text)
    self.assertIn("潮声异常", bundle.context_text)
    self.assertIn("适用章节：第 1-10 章", bundle.context_text)
    self.assertIn("关系：相关地点 -> 旧码头", bundle.context_text)
    self.assertIn("未开放设定", bundle.context_text)
    self.assertNotIn("未来真相", bundle.context_text)
    self.assertNotIn("[未来真相](未来真相.md)", bundle.context_text)
    self.assertNotIn("伏笔 -> 未来真相", bundle.context_text)
    self.assertNotIn("被引用：未来真相", bundle.context_text)
    self.assertNotIn("沉船真相来自第七十章以后", bundle.context_text)
    self.assertFalse(any(item.source_key.endswith("未来真相.md") for item in bundle.knowledge_hits))

  def test_project_context_bundle_drops_unmatched_obsidian_knowledge_hits_for_target_chapter(self) -> None:
    stale_hit = KnowledgeSearchResult(
      source="Obsidian",
      source_key="obsidian:Secrets/第七十章终局真相.md",
      section="第七十章终局真相 · Secrets/第七十章终局真相.md",
      preview="终局真相只能在第七十章之后出现。",
      score=1.0,
      match_type="keyword",
    )

    with patch("novel_backend.services.context_builder.search_project_knowledge", return_value=[stale_hit]):
      bundle = build_project_context_bundle(
        self.settings,
        self.project.id,
        chapter_id="chapter-001",
        knowledge_query="终局真相",
        task_instruction="继续写第一章。",
      )

    self.assertEqual(bundle.knowledge_hits, [])
    self.assertNotIn("终局真相只能在第七十章之后出现", bundle.context_text)

  def test_project_context_bundle_passes_chapter_to_knowledge_search_before_filtering(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-context-search-scope"
    vault_dir.mkdir()
    for index in range(24):
      (vault_dir / f"未来证词{index:02d}.md").write_text(
        f"""---
status: canonical
reveal_after_chapter: 2
---
# 未来证词{index:02d}

潮汐证词 潮汐证词 潮汐证词 潮汐证词。
""",
        encoding="utf-8",
      )
    (vault_dir / "当前证词.md").write_text(
      """---
status: canonical
chapter_range: 1-1
---
# 当前证词

当前潮汐证词只能服务第一章。
""",
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      knowledge_query="潮汐证词",
      knowledge_limit=1,
      task_instruction="继续写第一章，只能使用当前可见证词。",
    )

    self.assertEqual(len(bundle.knowledge_hits), 1)
    self.assertIn("当前证词", bundle.knowledge_hits[0].section)
    self.assertIn("当前潮汐证词", bundle.knowledge_hits[0].preview)
    self.assertNotIn("未来证词", bundle.knowledge_hits[0].section)

  def test_project_context_bundle_ignores_model_overview_cache_for_chapter_scope(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          api_key="real-key",
          base_url="https://model.local/v1",
          model_name="overview-model",
          max_tokens=4096,
        ),
        review_model=ReviewModelConfig(enabled=False),
      ),
    )
    vault_dir = Path(self._temp_dir.name) / "vault-context-model-cache-scope"
    vault_dir.mkdir()
    (vault_dir / "第八十章终局祭坛.md").write_text(
      """---
type: location
status: canonical
reveal_after_chapter: 60
---
# 第八十章终局祭坛

终局祭坛只能在第六十一章以后进入正文。
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    model_content = json.dumps(
      {
        "characters": [],
        "events": [],
        "locations": [
          {
            "name": "终局祭坛",
            "summary": "终局祭坛只能在第六十一章以后进入正文。",
            "related_characters": [],
            "evidence": ["终局祭坛只能在第六十一章以后进入正文"],
          }
        ],
        "props": [],
        "skills": [],
        "scenes": [],
        "organizations": [],
      },
      ensure_ascii=False,
    )
    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      return_value={"choices": [{"message": {"content": model_content}}]},
    ):
      overview_detail = get_project_detail(self.settings, self.project.id, allow_model_overview=True)
    self.assertIn("终局祭坛", [item.name for item in overview_detail.story_overview.locations])
    overview_memory_text = "\n".join(
      item.content for item in overview_detail.story_overview.memory_entries
    )
    self.assertNotIn("终局祭坛", overview_memory_text)
    continuation_pack = next(
      item
      for item in overview_detail.story_overview.distillation_report.packs
      if item.kind == "continuation"
    )
    self.assertNotIn("终局祭坛", "\n".join(continuation_pack.must_keep + continuation_pack.execution_focus))
    self.assertEqual(overview_detail.story_overview.distillation_report.source_profile.location_notes, [])
    continuation_distillation = build_task_distillation_prompt_block(
      overview_detail,
      kind="continuation",
      query="终局祭坛",
    )
    architecture_distillation = build_task_distillation_prompt_block(
      overview_detail,
      kind="architecture",
      query="终局祭坛",
    )
    self.assertNotIn("终局祭坛", continuation_distillation)
    self.assertIn("终局祭坛", architecture_distillation)

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      knowledge_query="终局祭坛",
      task_instruction="继续写第一章，不能提前揭示未来地点。",
    )

    self.assertNotIn("终局祭坛", bundle.context_text)
    self.assertNotIn("第六十一章以后进入正文", bundle.context_text)

  def test_project_context_bundle_includes_obsidian_graph_warnings_in_checklist(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-checklist"
    vault_dir.mkdir()
    (vault_dir / "灯塔.md").write_text(
      """---
type: place
status: canonical
aliases: [灯塔]
---
# 北岸灯塔

北岸灯塔记录旧航线。
""",
      encoding="utf-8",
    )
    (vault_dir / "灯塔副本.md").write_text(
      """---
type: place
status: canonical
aliases: [灯塔]
---
# 南岸灯塔

南岸灯塔记录新航线。
""",
      encoding="utf-8",
    )
    (vault_dir / "港口规则.md").write_text(
      """---
type: rule
status: canonical
---
# 港口规则

港口规则要求林追在旧码头核对[[灯塔]]和[[失踪船队]]。

必须出现：旧码头核对
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-001",
      task_instruction="写林追去旧码头核对港口规则。",
    )

    self.assertIn("本章 Obsidian 设定检查清单：", bundle.context_text)
    self.assertIn("来源｜港口规则（港口规则.md）", bundle.context_text)
    self.assertIn("必须出现：旧码头核对", bundle.context_text)
    self.assertIn("图谱注意：", bundle.context_text)
    self.assertIn("歧义双链 灯塔", bundle.context_text)
    self.assertIn("未解析双链 失踪船队", bundle.context_text)

  def test_project_context_bundle_selects_obsidian_notes_by_chinese_overlap_without_title(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chinese-overlap"
    vault_dir.mkdir()
    for index in range(9):
      (vault_dir / f"00无关-{index}.md").write_text(
        f"""---
type: note
status: canonical
---
# 无关笔记 {index}

这份笔记记录另一个城市的天气和街道。
""",
        encoding="utf-8",
      )
    (vault_dir / "99黑盐仓库.md").write_text(
      """---
type: location
status: canonical
---
# 黑盐仓库

走私组织把旧船队暗账藏在黑盐仓库，账册第一页只写潮汐编号。

必须出现：黑盐仓库
""",
      encoding="utf-8",
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在章末发现旧船队账册第一页缺了潮汐编号。\n"),
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-002",
      task_instruction="继续写下一章。",
    )

    self.assertIn("黑盐仓库", bundle.context_text)
    self.assertIn("旧船队暗账", bundle.context_text)
    self.assertIn("本章 Obsidian 写作约束：", bundle.context_text)
    self.assertIn("必须包含｜黑盐仓库", bundle.context_text)

  def test_prompt_support_includes_preset_and_xp(self) -> None:
    support = build_prompt_support(self.settings, task_key="chapter", xp_name="悬疑推进")

    self.assertIn("提示词方案：", support)
    self.assertIn("XP 预设：", support)

  def test_prompt_support_includes_project_style_xp_evolution(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-002",
      ChapterUpdateRequest(
        content="# 第二章 白石商会\n雾散了。\n林追把钥匙藏进袖口。\n门内有人轻轻吸气。\n他没有回头。\n",
      ),
    )

    support = build_prompt_support(self.settings, task_key="chapter", project_id=self.project.id)

    self.assertIn("系统学习版文风 / XP", support)
    self.assertIn("优先级低于作者明确要求、手工文风和手工 XP", support)

  def test_prompt_support_reads_chapter_safe_obsidian_style_xp_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-style-xp"
    (vault_dir / "Style").mkdir(parents=True)
    (vault_dir / "XP").mkdir(parents=True)
    (vault_dir / "Style" / "冷雾叙事.md").write_text(
      """---
type: style_rule
status: canonical
tags: [文风]
chapter_range: 2+
summary: 句子短，动作后接感知，不提前解释真相。
forbidden_phrases: [直接解释真相]
---
# 冷雾叙事
""",
      encoding="utf-8",
    )
    (vault_dir / "XP" / "悬疑推进.md").write_text(
      """---
type: xp_rule
status: canonical
tags: [XP]
chapter: 2
summary: 每场必须留下一个未被角色完全理解的线索。
required_phrases: [潮声异常]
---
# 悬疑推进
""",
      encoding="utf-8",
    )
    (vault_dir / "Style" / "未来文风.md").write_text(
      """---
type: style_rule
status: canonical
tags: [文风]
reveal_after_chapter: 5
summary: 终局绽放式长句可以大量使用。
---
# 未来文风
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    support = build_prompt_support(
      self.settings,
      task_key="chapter",
      project_id=self.project.id,
      chapter_id="chapter-002",
    )

    self.assertIn("Obsidian 文风 / XP 参考", support)
    self.assertIn("冷雾叙事", support)
    self.assertIn("句子短，动作后接感知", support)
    self.assertIn("悬疑推进", support)
    self.assertIn("潮声异常", support)
    self.assertNotIn("终局绽放式长句", support)

  def test_prompt_support_reads_properties_only_obsidian_style_xp_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-style-xp-properties"
    (vault_dir / "Style").mkdir(parents=True)
    (vault_dir / "XP").mkdir(parents=True)
    (vault_dir / "Style" / "短促感知.md").write_text(
      """---
type: style_rule
status: canonical
tags: [文风]
chapter_range: 2+
style_rule: 句子保持短促，动作后接感知，不解释谜底。
sentence_rhythm: 每段只推进一个动作或一次发现。
imagery: 潮声、铁锈味和冷光反复出现。
avoid_style: 不写全知视角解释。
examples: 门响了一下，水声在锁眼里晃。
---
# 短促感知
""",
      encoding="utf-8",
    )
    (vault_dir / "XP" / "线索压力.md").write_text(
      """---
type: xp_rule
status: canonical
tags: [XP]
chapter: 2
xp_rule: 每场保留一个角色没有完全理解的线索。
precheck: 开场前确认本场要推进哪条疑问。
postcheck: 收尾检查是否留下未解释动作。
required_phrases: [潮声异常]
---
# 线索压力
""",
      encoding="utf-8",
    )
    (vault_dir / "Style" / "终局铺张.md").write_text(
      """---
type: style_rule
status: canonical
tags: [文风]
reveal_after_chapter: 5
style_rule: 终局可以使用铺张长句和完整解释。
---
# 终局铺张
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        self.project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    support = build_prompt_support(
      self.settings,
      task_key="chapter",
      project_id=self.project.id,
      chapter_id="chapter-002",
    )

    self.assertIn("Obsidian 文风 / XP 参考", support)
    self.assertIn("短促感知", support)
    self.assertIn("句子保持短促", support)
    self.assertIn("潮声、铁锈味和冷光", support)
    self.assertIn("线索压力", support)
    self.assertIn("每场保留一个角色没有完全理解的线索", support)
    self.assertIn("潮声异常", support)
    self.assertNotIn("终局可以使用铺张长句", support)
