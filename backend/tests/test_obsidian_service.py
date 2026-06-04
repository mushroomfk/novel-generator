from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import CreateProjectRequest, ObsidianVaultConfig
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.project_service import (
  create_project,
  get_project_detail,
  load_project_obsidian_note_contents,
  search_project_knowledge,
  search_project_knowledge_evidence,
  sync_project_obsidian,
  update_project_obsidian_config,
)
from novel_backend.services.obsidian_service import _candidate_note_paths, select_obsidian_notes_for_query


class ObsidianServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt")
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def create_demo_project(self):
    return create_project(
      self.settings,
      CreateProjectRequest(
        name="Obsidian 项目",
        genre="悬疑",
        target_chapters=3,
        target_words=60000,
      ),
    )

  def test_obsidian_vault_notes_enter_overview_and_knowledge_index(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    character_dir = vault_dir / "Characters"
    organization_dir = vault_dir / "Organizations"
    character_dir.mkdir(parents=True)
    organization_dir.mkdir(parents=True)
    (character_dir / "林追.md").write_text(
      """---
type: character
status: canonical
aliases: [林侦探]
tags: [人物, 主角]
usable_by_ai: true
required_phrases: [铜钥匙]
forbidden_phrases: [林追主动交出铜钥匙]
---
# 林追

林追在旧码头得到铜钥匙，正在追查[[灯塔议会]]删改靠港记录的事。 #线索
""",
      encoding="utf-8",
    )
    (organization_dir / "灯塔议会.md").write_text(
      """---
type: organization
status: canonical
aliases: [灯塔]
---
# 灯塔议会

灯塔议会掌握靠港记录，成员曾提到[[失落港口]]。
""",
      encoding="utf-8",
    )
    (vault_dir / "废案.md").write_text(
      """---
status: draft
---
废案里说铜钥匙已经丢失。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          include_patterns=["**/*.md"],
          exclude_patterns=[".obsidian/**"],
          allowed_statuses=["canonical"],
          excluded_statuses=["draft"],
        ),
      )
      hits = search_project_knowledge(self.settings, summary.id, "铜钥匙", include_semantic=False)

    obsidian = detail.story_overview.obsidian
    self.assertTrue(obsidian.enabled)
    self.assertEqual(obsidian.included_count, 2)
    self.assertEqual(obsidian.skipped_count, 1)
    self.assertEqual(obsidian.resolved_link_count, 1)
    self.assertEqual(obsidian.unresolved_link_count, 1)
    lin_zhui = next(item for item in obsidian.notes if item.title == "林追")
    lighthouse = next(item for item in obsidian.notes if item.title == "灯塔议会")
    self.assertIn("灯塔议会", lin_zhui.links)
    self.assertIn("Organizations/灯塔议会.md", lin_zhui.resolved_links)
    self.assertIn("线索", lin_zhui.tags)
    self.assertIn("铜钥匙", lin_zhui.required_phrases)
    self.assertIn("林追主动交出铜钥匙", lin_zhui.forbidden_phrases)
    self.assertIn("Characters/林追.md", lighthouse.backlinks)
    self.assertIn("失落港口", lighthouse.unresolved_links)

    self.assertTrue(any(item.source == "Obsidian" and "林追" in item.section for item in hits))
    self.assertTrue(any("禁止出现：林追主动交出铜钥匙" in item.preview for item in hits))
    self.assertFalse(any("废案" in item.preview for item in hits))

    db_path = Path(summary.path) / "knowledge.db"
    connection = sqlite3.connect(db_path)
    try:
      rows = connection.execute(
        "SELECT source, kind, section FROM knowledge_chunks WHERE kind = 'obsidian'"
      ).fetchall()
    finally:
      connection.close()
    self.assertGreaterEqual(len(rows), 1)
    self.assertEqual(rows[0][0], "Obsidian")
    self.assertTrue(any("林追" in row[2] for row in rows))

    refreshed = get_project_detail(self.settings, summary.id)
    self.assertEqual(refreshed.story_overview.obsidian.included_count, 2)

  def test_obsidian_exclude_patterns_match_common_vault_folder_casing(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-exclude-casing"
    for folder in ("Notes", "Templates", ".OBSIDIAN", ".Trash", "Drafts"):
      (vault_dir / folder).mkdir(parents=True)
    (vault_dir / "Notes" / "正式人物.md").write_text(
      """---
status: canonical
---
# 正式人物

正式人物资料说明可进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "Templates" / "章节模板.md").write_text(
      """---
status: canonical
---
# 章节模板

zztemplatecasingalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / ".OBSIDIAN" / "插件状态.md").write_text(
      """---
status: canonical
---
# 插件状态

zzobsidiancasingalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / ".Trash" / "旧设定.md").write_text(
      """---
status: canonical
---
# 旧设定

zztrashcasingalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "Drafts" / "显式正式草稿.md").write_text(
      """---
status: canonical
---
# 显式正式草稿

zzdraftpatternalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          exclude_patterns=[".obsidian/**", ".trash/**", "templates/**", "drafts/**"],
        ),
      )
      hits = search_project_knowledge(self.settings, project.id, "正式人物资料 模板 插件 旧设定", include_semantic=False)

    with sqlite3.connect(Path(project.path) / "knowledge.db") as connection:
      disabled_rows = connection.execute(
        """
        SELECT chunk_id FROM knowledge_chunks
        WHERE content LIKE ? OR content LIKE ? OR content LIKE ? OR content LIKE ?
        """,
        (
          "%zztemplatecasingalpha%",
          "%zzobsidiancasingalpha%",
          "%zztrashcasingalpha%",
          "%zzdraftpatternalpha%",
        ),
      ).fetchall()

    note_titles = {item.title for item in detail.story_overview.obsidian.notes}
    self.assertIn("正式人物", note_titles)
    self.assertNotIn("章节模板", note_titles)
    self.assertNotIn("插件状态", note_titles)
    self.assertNotIn("旧设定", note_titles)
    self.assertNotIn("显式正式草稿", note_titles)
    self.assertEqual(disabled_rows, [])
    self.assertTrue(any(item.source == "Obsidian" and "正式人物" in item.section for item in hits))
    self.assertFalse(any("zztemplatecasingalpha" in item.preview for item in hits))

  def test_obsidian_max_notes_applies_after_stable_path_sorting(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-max-notes"
    vault_dir.mkdir()
    note_paths = [
      vault_dir / "z-last.md",
      vault_dir / "m-middle.md",
      vault_dir / "a-first.md",
    ]
    for path in note_paths:
      path.write_text(
        """---
status: canonical
---
# {title}

{title} 资料说明会参与 max_notes 排序。
""".format(title=path.stem),
        encoding="utf-8",
      )

    original_rglob = Path.rglob

    def unordered_rglob(self: Path, pattern: str):
      if self == vault_dir and pattern == "*":
        return iter(note_paths)
      return original_rglob(self, pattern)

    config = ObsidianVaultConfig(
      enabled=True,
      vault_path=str(vault_dir),
      allowed_statuses=["canonical"],
      max_notes=2,
    )
    with patch.object(Path, "rglob", unordered_rglob):
      candidate_paths = [
        path.relative_to(vault_dir).as_posix()
        for path in _candidate_note_paths(vault_dir, config)
      ]
      with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
        detail = update_project_obsidian_config(self.settings, project.id, config)

    note_paths_in_state = [item.relative_path for item in detail.story_overview.obsidian.notes]
    self.assertEqual(candidate_paths, ["a-first.md", "m-middle.md"])
    self.assertEqual(note_paths_in_state, ["a-first.md", "m-middle.md"])
    self.assertEqual(detail.story_overview.obsidian.included_count, 2)
    self.assertEqual(detail.story_overview.obsidian.skipped_count, 1)
    self.assertTrue(any("匹配到 3 篇候选笔记" in warning for warning in detail.story_overview.obsidian.warnings))
    (vault_dir / "zz-after-limit.md").write_text(
      """---
status: canonical
---
# zz-after-limit

zz-after-limit 资料说明不会进入前两篇，但会更新同步摘要。
""",
      encoding="utf-8",
    )

    refreshed = get_project_detail(self.settings, project.id)
    self.assertEqual([item.relative_path for item in refreshed.story_overview.obsidian.notes], ["a-first.md", "m-middle.md"])
    self.assertEqual(refreshed.story_overview.obsidian.skipped_count, 2)
    self.assertTrue(any("匹配到 4 篇候选笔记" in warning for warning in refreshed.story_overview.obsidian.warnings))

  def test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-summary-keywords"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
summary: 青铜潮标提示[[未来真相]]，纯文本也写到未来真相，但第一章只能写成潮声异常。
aliases: [当前潮标, "[[未来真相]]", 未来真相]
tags: [当前标签, 终局暗标签, "[[终局暗标签]]"]
keywords: [潮标密钥, "[[未来真相]]", "[潮声异常](未来真相.md)", 未来真相]
required_phrases: [潮声异常, "[[未来真相|潮声异常]]", "不要写未来真相"]
forbidden_phrases: ["[[未来真相]]", "[未来真相](未来真相.md)", 未来真相]
chapter_range: 1-2
---
# 当前线索

本章只写潮声异常，不解释终局答案，也不能写未来真相这个纯文本名称。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

未来真相只能在第六十一章以后公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "终局暗标签.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 终局暗标签

终局暗标签只能在第六十一章以后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标密钥",
        include_semantic=False,
        chapter_index=1,
      )
      safe_evidence = search_project_knowledge_evidence(
        self.settings,
        project.id,
        "潮声异常",
        chapter_index=1,
      )
      hidden_future_evidence = search_project_knowledge_evidence(
        self.settings,
        project.id,
        "未来真相",
        chapter_index=1,
      )

    current_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "当前线索")
    self.assertEqual(current_note.summary, "青铜潮标提示[[未来真相]]，纯文本也写到未来真相，但第一章只能写成潮声异常。")
    self.assertIn("终局暗标签", current_note.tags)
    self.assertIn("[[终局暗标签]]", current_note.tags)
    self.assertIn("潮标密钥", current_note.keywords)
    self.assertIn("[[未来真相]]", current_note.aliases)
    self.assertIn("未来真相", current_note.aliases)
    self.assertIn("[[未来真相]]", current_note.keywords)
    self.assertIn("未来真相", current_note.keywords)
    self.assertIn("[[未来真相]]", current_note.forbidden_phrases)
    self.assertIn("未来真相", current_note.forbidden_phrases)
    selected = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "潮标密钥",
      limit=1,
      chapter_index=1,
    )
    self.assertEqual([item.title for item in selected], ["当前线索"])

    self.assertTrue(any(item.source == "Obsidian" and "当前线索" in item.section for item in hits))
    self.assertTrue(any("青铜潮标" in item.preview for item in hits))
    self.assertFalse(any("未来真相" in item.preview for item in hits))
    self.assertTrue(any(str(item.get("source") or "") == "Obsidian" for item in safe_evidence))
    self.assertFalse(any("未来真相" in str(item.get("content") or "") for item in safe_evidence))
    self.assertEqual(hidden_future_evidence, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="潮标密钥",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["当前线索"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertNotIn("未来真相", early_note_contents[0]["content"])
    self.assertNotIn("终局暗标签", early_note_contents[0]["content"])
    self.assertNotIn("[[终局暗标签]]", early_note_contents[0]["content"])
    self.assertNotIn("[[未来真相]]", early_note_contents[0]["content"])
    self.assertNotIn("[未来真相](未来真相.md)", early_note_contents[0]["content"])

  def test_obsidian_block_references_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-block-references"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
summary: 当前线索需要查看[[旧码头^dock]]，但不能提前写[[未来真相^secret]]。
source_notes:
  - "[[旧码头^dock]]"
  - "[[未来真相^secret]]"
---
# 当前线索

当前线索需要查看[[旧码头^dock|旧码头仓库]]，但不能提前写[[未来真相^secret]]。
""",
      encoding="utf-8",
    )
    (vault_dir / "旧码头.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 旧码头

旧码头仓库保留青铜潮标。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

未来真相只能在第六十一章以后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    dock_note = next(item for item in obsidian.notes if item.title == "旧码头")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("旧码头", current_note.links)
    self.assertIn("旧码头.md", current_note.resolved_links)
    self.assertIn("未来真相", current_note.links)
    self.assertIn("未来真相.md", current_note.resolved_links)
    self.assertIn("当前线索.md", dock_note.backlinks)
    self.assertIn("当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> 旧码头", current_note.graph_relations)
    self.assertIn("来源笔记 -> 未来真相", current_note.graph_relations)

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="旧码头仓库",
    )
    self.assertEqual({item["title"] for item in early_note_contents}, {"当前线索", "旧码头"})
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[[旧码头^dock|旧码头仓库]]", current_content)
    self.assertIn("来源笔记 -> 旧码头", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("未来真相", current_content)
    self.assertNotIn("[[未来真相^secret]]", current_content)
    self.assertNotIn("来源笔记 -> 未来真相", current_content)

  def test_obsidian_same_note_links_do_not_create_graph_noise(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-same-note-links"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[当前线索#内部索引]]"
  - "[回看](当前线索.md#内部索引)"
  - "[[旧码头]]"
---
# 当前线索

正文会跳到[[当前线索#内部索引]]和[[当前线索^scene-a]]，也参考[[旧码头]]与[同页](#内部索引)。

## 来源笔记

- [[当前线索#内部索引]]
- [回看](当前线索.md#内部索引)
- [[旧码头]]

## 内部索引

^scene-a
""",
      encoding="utf-8",
    )
    (vault_dir / "旧码头.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 旧码头

旧码头记录潮汐线索。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    dock_note = next(item for item in obsidian.notes if item.title == "旧码头")
    self.assertIn("旧码头", current_note.links)
    self.assertIn("旧码头.md", current_note.resolved_links)
    self.assertIn("当前线索.md", dock_note.backlinks)
    self.assertNotIn("当前线索", current_note.links)
    self.assertNotIn("当前线索.md", current_note.links)
    self.assertNotIn("当前线索.md", current_note.resolved_links)
    self.assertNotIn("当前线索.md", current_note.backlinks)
    self.assertIn("来源笔记 -> 旧码头", current_note.graph_relations)
    self.assertNotIn("来源笔记 -> 当前线索", current_note.graph_relations)
    self.assertNotIn("来源笔记 -> 当前线索.md", current_note.graph_relations)

  def test_obsidian_relative_wiki_links_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-relative-wiki-links"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir()
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[../Characters/林追]]"
---
# 当前线索

正文联系[[../Characters/林追|林追]]，不要提前写[[../Secrets/未来真相|终局答案]]。

## 伏笔

- [[../Secrets/未来真相|终局答案]]
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

终局答案只能在第六十一章以后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "终局答案",
        include_semantic=False,
        chapter_index=1,
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追", current_note.links)
    self.assertIn("Characters/林追.md", current_note.resolved_links)
    self.assertIn("Secrets/未来真相", current_note.links)
    self.assertIn("Secrets/未来真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来真相", current_note.graph_relations)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追",
    )
    self.assertEqual({item["title"] for item in early_note_contents}, {"当前线索", "林追"})
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[[../Characters/林追|林追]]", current_content)
    self.assertIn("来源笔记 -> Characters/林追", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("Secrets/未来真相", current_content)
    self.assertNotIn("[[../Secrets/未来真相|终局答案]]", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来真相", current_content)

  def test_obsidian_percent_encoded_wiki_links_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-encoded-wiki-links"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir()
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[../Characters/林%20追]]"
---
# 当前线索

正文联系[[../Characters/林%20追|林追]]，不要提前写[[../Secrets/未来%20真相|终局答案]]。

## 伏笔

- [[../Secrets/未来%20真相|终局答案]]
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林 追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林 追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来 真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来 真相

终局答案只能在第六十一章以后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "终局答案",
        include_semantic=False,
        chapter_index=1,
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林 追")
    future_note = next(item for item in obsidian.notes if item.title == "未来 真相")
    self.assertIn("Characters/林 追", current_note.links)
    self.assertIn("Characters/林 追.md", current_note.resolved_links)
    self.assertIn("Secrets/未来 真相", current_note.links)
    self.assertIn("Secrets/未来 真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林 追", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来 真相", current_note.graph_relations)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追",
    )
    self.assertEqual({item["title"] for item in early_note_contents}, {"当前线索", "林 追"})
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[[../Characters/林%20追|林追]]", current_content)
    self.assertIn("来源笔记 -> Characters/林 追", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("Secrets/未来 真相", current_content)
    self.assertNotIn("[[../Secrets/未来%20真相|终局答案]]", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来 真相", current_content)

  def test_obsidian_percent_encoded_reserved_path_chars_do_not_split_targets(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-encoded-reserved-path-chars"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir()
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[../Characters/林%23追]]"
related_characters:
  - "[林追](../Characters/林%23追.md)"
---
# 当前线索

正文联系[[../Characters/林%23追|林追]]，也记录[林追档案](../Characters/林%23追.md)，不要提前写[[../Secrets/未来%5E真相|终局答案]]。

## 伏笔

- [终局答案](../Secrets/未来%5E真相.md)
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林#追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林#追

林追正在查带特殊编号的旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来^真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来^真相

终局答案只能在第六十一章以后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "终局答案",
        include_semantic=False,
        chapter_index=1,
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林#追")
    future_note = next(item for item in obsidian.notes if item.title == "未来^真相")
    self.assertIn("Characters/林#追", current_note.links)
    self.assertIn("Characters/林#追.md", current_note.links)
    self.assertIn("Characters/林#追.md", current_note.resolved_links)
    self.assertIn("Secrets/未来^真相", current_note.links)
    self.assertIn("Secrets/未来^真相.md", current_note.links)
    self.assertIn("Secrets/未来^真相.md", current_note.resolved_links)
    self.assertNotIn("Characters/林", current_note.unresolved_links)
    self.assertNotIn("Secrets/未来", current_note.unresolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林#追", current_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林#追.md", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来^真相.md", current_note.graph_relations)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追",
    )
    self.assertEqual({item["title"] for item in early_note_contents}, {"当前线索", "林#追"})
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[[../Characters/林%23追|林追]]", current_content)
    self.assertIn("[林追档案](../Characters/林%23追.md)", current_content)
    self.assertIn("来源笔记 -> Characters/林#追", current_content)
    self.assertIn("相关人物 -> Characters/林#追.md", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("Secrets/未来^真相", current_content)
    self.assertNotIn("[[../Secrets/未来%5E真相|终局答案]]", current_content)
    self.assertNotIn("[终局答案](../Secrets/未来%5E真相.md)", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来^真相.md", current_content)

  def test_obsidian_links_outside_vault_do_not_create_graph_noise(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-outside-links"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[../Outside/旧设定]]"
  - "[[Characters/林追]]"
related_notes:
  - "[外部资料](../Outside/旧设定.md)"
---
# 当前线索

正文联系[[Characters/林追|林追]]，但不应把[[../Outside/旧设定|外部旧设定]]当成 Vault 缺失笔记。

## 相关人物

- [林追](Characters/林追.md)
- [外部资料](../Outside/旧设定.md)
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    self.assertIn("Characters/林追", current_note.links)
    self.assertIn("Characters/林追.md", current_note.links)
    self.assertIn("Characters/林追.md", current_note.resolved_links)
    self.assertIn("当前线索.md", character_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追", current_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追.md", current_note.graph_relations)
    self.assertFalse(any("Outside" in value for value in current_note.links))
    self.assertFalse(any("Outside" in value for value in current_note.unresolved_links))
    self.assertFalse(any("Outside" in value for value in current_note.graph_relations))
    self.assertFalse(any("旧设定" in issue.title for issue in obsidian.issues))

  def test_obsidian_wiki_dot_segments_normalize_and_cannot_escape_vault(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-wiki-dot-segments"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[Clues/../Characters/林追]]"
  - "[[Clues/../../Outside/旧设定]]"
---
# 当前线索

正文联系[[Clues/../Characters/林追|林追]]，但不应把[[Clues/../../Outside/旧设定|外部旧设定]]当成 Vault 缺失笔记。

## 相关人物

- [[Clues/../Characters/林追.md]]
- [[Clues/../../Outside/旧设定.md]]
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    self.assertIn("Characters/林追", current_note.links)
    self.assertIn("Characters/林追.md", current_note.links)
    self.assertIn("Characters/林追.md", current_note.resolved_links)
    self.assertIn("当前线索.md", character_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追", current_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追.md", current_note.graph_relations)
    self.assertFalse(any("../" in value for value in current_note.links))
    self.assertFalse(any("Outside" in value for value in current_note.unresolved_links))
    self.assertFalse(any("Outside" in value for value in current_note.graph_relations))
    self.assertFalse(any("旧设定" in issue.title for issue in obsidian.issues))

  def test_obsidian_root_relative_links_resolve_and_cannot_escape_vault(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-root-relative-links"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Outside").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[[/Characters/林追]]"
  - "[[/../Outside/旧设定]]"
related_characters:
  - "[林追](/Characters/林追.md)"
related_notes:
  - "[外部资料](/../Outside/旧设定.md)"
---
# 当前线索

正文联系[[/Characters/林追|林追]]和[林追档案](/Characters/林追.md)，但不应把[[/../Outside/旧设定|外部旧设定]]当成 Vault 内部链接。

## 相关人物

- [[/Clues/../Characters/林追.md]]
- [外部资料](/Clues/../../Outside/旧设定.md)
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Outside" / "旧设定.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 旧设定

这份笔记存在，但不能被越界根路径误连。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    outside_note = next(item for item in obsidian.notes if item.title == "旧设定")
    self.assertIn("Characters/林追", current_note.links)
    self.assertIn("Characters/林追.md", current_note.links)
    self.assertIn("Characters/林追.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertNotIn("Clues/当前线索.md", outside_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追", current_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追.md", current_note.graph_relations)
    self.assertFalse(any(value.startswith("/") for value in current_note.links))
    self.assertFalse(any("../" in value for value in current_note.links))
    self.assertFalse(any("Outside" in value for value in current_note.links))
    self.assertFalse(any("Outside" in value for value in current_note.unresolved_links))
    self.assertFalse(any("Outside" in value for value in current_note.graph_relations))

  def test_obsidian_markdown_links_with_parentheses_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-parentheses"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "[林追旧档](../Characters/林追(旧).md)"
foreshadows:
  - "[终局答案](../Secrets/未来(真相).md)"
---
# 当前线索

正文联系[林追旧档](../Characters/林追(旧).md)，但不要提前写[终局答案](../Secrets/未来(真相).md)。

## 相关人物

- [林追旧档](../Characters/林追(旧).md)
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追(旧).md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追旧档

林追旧档记录旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来(真相).md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

未来真相只能在第六十章后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追旧档")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追(旧).md", current_note.links)
    self.assertIn("Secrets/未来(真相).md", current_note.links)
    self.assertIn("Characters/林追(旧).md", current_note.resolved_links)
    self.assertIn("Secrets/未来(真相).md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追(旧).md", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来(真相).md", current_note.graph_relations)

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追旧档",
    )
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[林追旧档](../Characters/林追(旧).md)", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("未来(真相)", current_content)
    self.assertNotIn("[终局答案](../Secrets/未来(真相).md)", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来(真相).md", current_content)

  def test_obsidian_markdown_links_unescape_targets_and_strip_titles(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-escaped-targets"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - '[林追旧档](../Characters/林追\\(旧\\).md "旧档")'
foreshadows:
  - '[终局答案](../Secrets/未来真相 "终局")'
---
# 当前线索

正文联系[林追旧档](../Characters/林追\\(旧\\).md "旧档")，但不要提前写[终局答案](../Secrets/未来真相 "终局")。

## 相关人物

- [林追旧档](../Characters/林追\\(旧\\).md "旧档")
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追(旧).md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追旧档

林追旧档记录旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

未来真相只能在第六十章后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追旧档")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追(旧).md", current_note.links)
    self.assertIn("Secrets/未来真相", current_note.links)
    self.assertNotIn("Characters/林追/(旧/).md", current_note.links)
    self.assertFalse(any("终局" in link for link in current_note.links))
    self.assertIn("Characters/林追(旧).md", current_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追(旧).md", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来真相", current_note.graph_relations)

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追旧档",
    )
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[林追旧档](../Characters/林追\\(旧\\).md \"旧档\")", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("未来真相", current_content)
    self.assertNotIn("[终局答案](../Secrets/未来真相 \"终局\")", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来真相", current_content)

  def test_obsidian_html_anchor_links_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-html-anchors"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 当前线索

正文联系 <a href="../Characters/林追.md">林追HTML</a>。
但不能提前解释 <a href="../Secrets/未来真相.md" title="终局">终局HTML</a>。
附件来源 <a href="资料/访谈.pdf">访谈HTML</a> 不应进入章节资料。

## 相关人物

- <a href="../Characters/林追.md">林追HTML</a>
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局HTML]
---
# 未来真相

未来真相只能在第六十章后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      attachment_hits = search_project_knowledge(
        self.settings,
        project.id,
        "访谈HTML",
        include_semantic=False,
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追.md", current_note.links)
    self.assertIn("Secrets/未来真相.md", current_note.links)
    self.assertNotIn("资料/访谈.pdf", current_note.links)
    self.assertIn("Characters/林追.md", current_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("相关人物 -> Characters/林追.md", current_note.graph_relations)
    self.assertNotIn("访谈HTML", current_note.preview)
    self.assertFalse(any("访谈HTML" in item.preview for item in attachment_hits))

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追HTML",
    )
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("林追HTML", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局HTML", current_content)
    self.assertNotIn("未来真相", current_content)
    self.assertNotIn("访谈HTML", current_content)
    self.assertNotIn("资料/访谈.pdf", current_content)

  def test_obsidian_uri_links_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-obsidian-uri-links"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
source_notes:
  - "obsidian://open?vault=Demo&file=Characters%2F林追.md&heading=人物页"
foreshadows:
  - "[终局URI](obsidian://advanced-uri?vault=Demo&filepath=Secrets%2F未来真相.md&heading=终局答案)"
---
# 当前线索

正文联系[林追URI](obsidian://open?vault=Demo&file=Characters%2F林追.md)。
但不能提前解释[终局URI](obsidian://advanced-uri?vault=Demo&filepath=Secrets%2F未来真相.md&heading=终局答案)。
HTML 联系 <a href="obsidian://open?vault=Demo&file=Characters%2F林追.md">林追HTML</a>。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
aliases: [终局URI]
reveal_after_chapter: 60
---
# 未来真相

## 终局答案

未来真相只能在第六十章后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追.md", current_note.links)
    self.assertIn("Secrets/未来真相.md", current_note.links)
    self.assertIn("Characters/林追.md", current_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("来源笔记 -> Characters/林追.md", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来真相.md", current_note.graph_relations)

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追URI",
    )
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("林追URI", current_content)
    self.assertIn("林追HTML", current_content)
    self.assertIn("来源笔记：[[Characters/林追.md#人物页]]", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局URI", current_content)
    self.assertNotIn("未来真相", current_content)
    self.assertNotIn("obsidian://advanced-uri", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来真相.md", current_content)

  def test_obsidian_markdown_reference_links_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-reference-links"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 当前线索

正文联系[林追旧档][old]，但不要提前写[终局答案][future]。

## 相关人物

- [林追旧档][old]

## 伏笔

- [终局答案][future]

[old]: ../Characters/林追\\(旧\\).md "旧档"
[future]: ../Secrets/未来真相 "终局"
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追(旧).md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追旧档

林追旧档记录旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

未来真相只能在第六十章后公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追旧档")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追(旧).md", current_note.links)
    self.assertIn("Secrets/未来真相", current_note.links)
    self.assertIn("Characters/林追(旧).md", current_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertIn("相关人物 -> Characters/林追(旧).md", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来真相", current_note.graph_relations)

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追旧档",
    )
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[林追旧档][old]", current_content)
    self.assertIn("[old]: ../Characters/林追\\(旧\\).md \"旧档\"", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("未来真相", current_content)
    self.assertNotIn("[终局答案][future]", current_content)
    self.assertNotIn("[future]: ../Secrets/未来真相 \"终局\"", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来真相", current_content)

  def test_obsidian_markdown_shortcut_reference_links_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-shortcut-reference-links"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 当前线索

正文联系[林追旧档]，已有双链[[林追旧档]]，但不要提前写[终局答案]。脚注不要生成关系[^future-footnote]，脚注里的双链也不要生成关系[^future-wiki]。

## 相关人物

- [林追旧档]

## 伏笔

- [终局答案]

[林追旧档]: ../Characters/林追\\(旧\\).md "旧档"
[终局答案]: ../Secrets/未来真相 "终局"
[^future-footnote]: ../Secrets/脚注真相 "脚注"
[^future-wiki]: [[脚注真相]]
    这行缩进续写也不应进入图谱：[[未来真相]]
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追(旧).md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追旧档

林追旧档记录旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

未来真相只能在第六十章后公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "脚注真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [脚注]
---
# 脚注真相

脚注真相不应因为 Markdown 脚注进入图谱关系。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追旧档")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    footnote_note = next(item for item in obsidian.notes if item.title == "脚注真相")
    self.assertIn("Characters/林追(旧).md", current_note.links)
    self.assertIn("Secrets/未来真相", current_note.links)
    self.assertNotIn("脚注真相", current_note.links)
    self.assertNotIn("Secrets/脚注真相", current_note.links)
    self.assertIn("Characters/林追(旧).md", current_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", current_note.resolved_links)
    self.assertNotIn("Secrets/脚注真相.md", current_note.resolved_links)
    self.assertIn("Clues/当前线索.md", character_note.backlinks)
    self.assertIn("Clues/当前线索.md", future_note.backlinks)
    self.assertNotIn("Clues/当前线索.md", footnote_note.backlinks)
    self.assertIn("相关人物 -> Characters/林追(旧).md", current_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来真相", current_note.graph_relations)

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追旧档",
    )
    current_content = next(item["content"] for item in early_note_contents if item["title"] == "当前线索")
    self.assertIn("[林追旧档]", current_content)
    self.assertIn("[[林追旧档]]", current_content)
    self.assertIn("[林追旧档]: ../Characters/林追\\(旧\\).md \"旧档\"", current_content)
    self.assertIn("未开放设定", current_content)
    self.assertNotIn("[^future-footnote]", current_content)
    self.assertNotIn("[^future-wiki]", current_content)
    self.assertNotIn("脚注真相", current_content)
    self.assertNotIn("终局答案", current_content)
    self.assertNotIn("未来真相", current_content)
    self.assertNotIn("[终局答案]", current_content)
    self.assertNotIn("[终局答案]: ../Secrets/未来真相 \"终局\"", current_content)
    self.assertNotIn("伏笔 -> Secrets/未来真相", current_content)

  def test_obsidian_inline_properties_drive_metadata_graph_and_scope(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-inline-properties"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "林追.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 林追

林追正在追查旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "线索甲.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 线索甲

线索甲记录旧账册上的潮汐编号。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
usable_by_ai: true
reveal_after_chapter: 70
---
# 未来真相

未来真相只能在后段公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "内联属性.md").write_text(
      """# 内联属性

status:: canonical
usable_by_ai:: true
summary:: 潮标摘要提示[[未来真相]]，但第五十八章只写潮声异常。
keywords:: 潮标密钥, 夜潮账册
aliases:: 潮标内联
tags:: 线索, 自动整理
chapter_range:: 58-60
reveal_after_chapter:: 57
required_phrases:: 潮声异常
forbidden_phrases:: 提前公开沉船真相
source_notes:: [[当前线索]]
related_characters:: [[林追]]

正文只记录第五十八章可见的潮标状态。
""",
      encoding="utf-8",
    )
    (vault_dir / "内联嵌套链接.md").write_text(
      """# 内联嵌套链接

status:: canonical
usable_by_ai:: true
chapter_range:: 58+

正文里用 [source_notes:: [当前线索, 潮标](当前线索.md)] 记录来源，也用 (related_characters:: [林追, 主角](林追.md)) 记录人物。
depends_on:: [[线索甲|账册, 初证]]
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标密钥",
        include_semantic=False,
        chapter_index=57,
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标密钥",
        include_semantic=False,
        chapter_index=58,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "内联属性")
    self.assertEqual(note.status, "canonical")
    self.assertTrue(note.usable_by_ai)
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (58, 60, 57))
    self.assertIn("潮标密钥", note.keywords)
    self.assertIn("夜潮账册", note.keywords)
    self.assertIn("潮标内联", note.aliases)
    self.assertIn("线索", note.tags)
    self.assertIn("潮声异常", note.required_phrases)
    self.assertIn("提前公开沉船真相", note.forbidden_phrases)
    self.assertIn("当前线索", note.links)
    self.assertIn("林追", note.links)
    self.assertIn("当前线索.md", note.resolved_links)
    self.assertIn("林追.md", note.resolved_links)
    self.assertIn("来源笔记 -> 当前线索", note.graph_relations)
    self.assertIn("相关人物 -> 林追", note.graph_relations)
    nested_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "内联嵌套链接")
    current_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "当前线索")
    clue_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "线索甲")
    character_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "林追")
    self.assertIn("当前线索.md", nested_note.links)
    self.assertIn("林追.md", nested_note.links)
    self.assertIn("线索甲", nested_note.links)
    self.assertIn("来源笔记 -> 当前线索.md", nested_note.graph_relations)
    self.assertIn("相关人物 -> 林追.md", nested_note.graph_relations)
    self.assertIn("依赖 -> 线索甲", nested_note.graph_relations)
    self.assertIn("当前线索.md", nested_note.resolved_links)
    self.assertIn("林追.md", nested_note.resolved_links)
    self.assertIn("线索甲.md", nested_note.resolved_links)
    self.assertIn("内联嵌套链接.md", current_note.backlinks)
    self.assertIn("内联嵌套链接.md", clue_note.backlinks)
    self.assertIn("内联嵌套链接.md", character_note.backlinks)
    self.assertEqual(early_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "内联属性" in item.section for item in scoped_hits))

    scoped_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=58,
      query="潮标密钥",
    )
    inline_content = next(item for item in scoped_note_contents if item["title"] == "内联属性")
    self.assertIn("未开放设定", inline_content["content"])
    self.assertNotIn("未来真相", inline_content["content"])

  def test_obsidian_dataview_inline_fields_inside_paragraphs_drive_metadata(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-dataview-inline-fields"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "林追.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 林追

林追正在追查旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
usable_by_ai: true
reveal_after_chapter: 70
---
# 未来真相

未来真相只能在后段公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "自然段属性.md").write_text(
      """# 自然段属性

这条笔记 (status:: canonical) 可供模型读取 [usable_by_ai:: true]。
它的摘要是 [summary:: 潮标段落提示[[未来真相]]，但第五十八章只写潮声异常]。
检索词放在自然句里 [keywords:: 潮标密钥, 夜潮账册]，别名写成 (aliases:: 段落属性)。
关系也写在句子中：[source_notes:: [[当前线索]]]，[related_characters:: [[林追]]]。
章节限制写成 [chapter_range:: 58-60] 和 (reveal_after_chapter:: 57)。
本章要求 [required_phrases:: 潮声异常]，禁止 [forbidden_phrases:: 提前公开沉船真相]。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标密钥",
        include_semantic=False,
        chapter_index=57,
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标密钥",
        include_semantic=False,
        chapter_index=58,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "自然段属性")
    self.assertEqual(note.status, "canonical")
    self.assertTrue(note.usable_by_ai)
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (58, 60, 57))
    self.assertIn("潮标密钥", note.keywords)
    self.assertIn("夜潮账册", note.keywords)
    self.assertIn("段落属性", note.aliases)
    self.assertIn("潮声异常", note.required_phrases)
    self.assertIn("提前公开沉船真相", note.forbidden_phrases)
    self.assertIn("当前线索", note.links)
    self.assertIn("林追", note.links)
    self.assertIn("当前线索.md", note.resolved_links)
    self.assertIn("林追.md", note.resolved_links)
    self.assertIn("来源笔记 -> 当前线索", note.graph_relations)
    self.assertIn("相关人物 -> 林追", note.graph_relations)
    self.assertEqual(early_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "自然段属性" in item.section for item in scoped_hits))

    scoped_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=58,
      query="潮标密钥",
    )
    paragraph_content = next(item for item in scoped_note_contents if item["title"] == "自然段属性")
    self.assertIn("未开放设定", paragraph_content["content"])
    self.assertNotIn("未来真相", paragraph_content["content"])

  def test_obsidian_ai_visibility_accepts_aliases_and_no_ai_flags(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-ai-visibility"
    vault_dir.mkdir()
    (vault_dir / "中文可用.md").write_text(
      """---
status: canonical
AI可用: 是
---
# 中文可用

潮标可用资料说明第五十八章可以引用。
""",
      encoding="utf-8",
    )
    (vault_dir / "反向允许.md").write_text(
      """---
status: canonical
no_ai: false
---
# 反向允许

反向允许资料说明作者明确没有禁止 AI 使用。
""",
      encoding="utf-8",
    )
    (vault_dir / "段落AI可用.md").write_text(
      """# 段落AI可用

这条笔记 [status:: canonical] 并且 [AI可用:: 是]。
段落可用资料说明写作模型可以读取自然句里的属性。
""",
      encoding="utf-8",
    )
    (vault_dir / "标签可用.md").write_text(
      """---
status: canonical
tags: [AI可用]
---
# 标签可用

标签可用资料说明作者用标签允许 AI 使用。
""",
      encoding="utf-8",
    )
    (vault_dir / "正文标签可用.md").write_text(
      """# 正文标签可用

status:: canonical

正文标签可用资料说明作者只在正文里写 #AI可用 标签。
""",
      encoding="utf-8",
    )
    (vault_dir / "反向禁用.md").write_text(
      """---
status: canonical
no_ai: true
---
# 反向禁用

沉箱暗号不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "中文禁用.md").write_text(
      """---
status: canonical
AI不可用: 是
---
# 中文禁用

赤锚密钥不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "标签禁用.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags: [no-ai]
---
# 标签禁用

潮闸暗格不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "禁用画布.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "a",
              "type": "text",
              "text": "status:: canonical\nAI不可用:: 是\n画布暗门不应该进入知识索引。",
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      disabled_hits = search_project_knowledge(
        self.settings,
        project.id,
        "沉箱暗号 赤锚密钥 潮闸暗格 画布暗门",
        include_semantic=False,
      )
      enabled_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标可用资料 反向允许资料 段落可用资料 标签可用资料 正文标签可用资料",
        include_semantic=False,
      )

    note_titles = {item.title for item in detail.story_overview.obsidian.notes}
    self.assertIn("中文可用", note_titles)
    self.assertIn("反向允许", note_titles)
    self.assertIn("段落AI可用", note_titles)
    self.assertIn("标签可用", note_titles)
    self.assertIn("正文标签可用", note_titles)
    self.assertNotIn("反向禁用", note_titles)
    self.assertNotIn("中文禁用", note_titles)
    self.assertNotIn("标签禁用", note_titles)
    self.assertNotIn("禁用画布", note_titles)
    self.assertEqual(disabled_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "中文可用" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "反向允许" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "段落AI可用" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "标签可用" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正文标签可用" in item.section for item in enabled_hits))

  def test_obsidian_status_tags_fill_missing_status_without_overriding_explicit_status(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-status-tags"
    vault_dir.mkdir()
    (vault_dir / "正式设定").mkdir()
    (vault_dir / "Drafts").mkdir()
    (vault_dir / "Private").mkdir()
    (vault_dir / "正式标签.md").write_text(
      """---
tags: [正式, AI可用]
---
# 正式标签

正式标签资料说明作者只用标签声明这是正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "正文正式标签.md").write_text(
      """# 正文正式标签

#canonical #AI可用

正文正式标签资料说明作者在正文标签里声明正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "草稿标签.md").write_text(
      """---
tags: [草稿, AI可用]
---
# 草稿标签

zzdraftnotealpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "私密标签.md").write_text(
      """# 私密标签

#private #AI可用

zzprivatenotealpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "显式状态优先.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags: [草稿]
---
# 显式状态优先

显式状态资料说明状态字段优先于标签推断。
""",
      encoding="utf-8",
    )
    (vault_dir / "正式画布.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "a",
              "type": "text",
              "text": "#canonical #AI可用\n正式画布资料说明 Canvas 也能用标签声明正式资料。",
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (vault_dir / "草稿画布.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "a",
              "type": "text",
              "text": "#draft #AI可用\nzzdraftalpha 不应该进入知识索引。",
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (vault_dir / "正式设定" / "正式目录.md").write_text(
      """---
tags: [AI可用]
---
# 正式目录

正式目录资料说明作者只用目录声明这是正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "Drafts" / "草稿目录.md").write_text(
      """---
tags: [AI可用]
---
# 草稿目录

zzdraftpathalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "Private" / "私密目录.md").write_text(
      """# 私密目录

#AI可用

zzprivatepathalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "Drafts" / "显式目录状态优先.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 显式目录状态优先

显式目录状态资料说明状态字段优先于目录推断。
""",
      encoding="utf-8",
    )
    (vault_dir / "Drafts" / "草稿目录画布.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "a",
              "type": "text",
              "text": "#AI可用\nzzdraftcanvaspathalpha 不应该进入知识索引。",
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      enabled_hits = search_project_knowledge(
        self.settings,
        project.id,
        "正式标签资料 正文正式标签资料 显式状态资料 正式画布资料 正式目录资料 显式目录状态资料",
        include_semantic=False,
      )
    with sqlite3.connect(Path(project.path) / "knowledge.db") as connection:
      disabled_rows = connection.execute(
        """
        SELECT chunk_id FROM knowledge_chunks
        WHERE content LIKE ? OR content LIKE ? OR content LIKE ? OR content LIKE ? OR content LIKE ? OR content LIKE ?
        """,
        (
          "%zzdraftnotealpha%",
          "%zzprivatenotealpha%",
          "%zzdraftalpha%",
          "%zzdraftpathalpha%",
          "%zzprivatepathalpha%",
          "%zzdraftcanvaspathalpha%",
        ),
      ).fetchall()

    note_titles = {item.title for item in detail.story_overview.obsidian.notes}
    self.assertIn("正式标签", note_titles)
    self.assertIn("正文正式标签", note_titles)
    self.assertIn("显式状态优先", note_titles)
    self.assertIn("正式画布", note_titles)
    self.assertIn("正式目录", note_titles)
    self.assertIn("显式目录状态优先", note_titles)
    self.assertNotIn("草稿标签", note_titles)
    self.assertNotIn("私密标签", note_titles)
    self.assertNotIn("草稿画布", note_titles)
    self.assertNotIn("草稿目录", note_titles)
    self.assertNotIn("私密目录", note_titles)
    self.assertNotIn("草稿目录画布", note_titles)
    self.assertEqual(disabled_rows, [])
    self.assertTrue(any(item.source == "Obsidian" and "正式标签" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正文正式标签" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "显式状态优先" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正式画布" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正式目录" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "显式目录状态优先" in item.section for item in enabled_hits))

  def test_obsidian_explicit_status_values_use_aliases_for_filtering(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-status-aliases"
    (vault_dir / "正式设定").mkdir(parents=True)
    (vault_dir / "Drafts").mkdir()
    (vault_dir / "正式设定" / "中文正式状态.md").write_text(
      """---
status: 正式设定
usable_by_ai: true
---
# 中文正式状态

中文正式状态资料说明作者用中文状态别名标记正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "英文正式状态.md").write_text(
      """---
status: official
usable_by_ai: true
---
# 英文正式状态

英文正式状态资料说明作者用英文状态别名标记正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "Drafts" / "显式正式状态.md").write_text(
      """---
status: final
usable_by_ai: true
---
# 显式正式状态

显式正式状态资料说明显式状态别名优先于草稿目录。
""",
      encoding="utf-8",
    )
    (vault_dir / "正式设定" / "显式草稿状态.md").write_text(
      """---
status: wip
usable_by_ai: true
---
# 显式草稿状态

zzwipstatusalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "归档状态.md").write_text(
      """---
status: archived
usable_by_ai: true
---
# 归档状态

zzarchivedstatusalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          excluded_statuses=["draft", "deprecated"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      enabled_hits = search_project_knowledge(
        self.settings,
        project.id,
        "中文正式状态资料 英文正式状态资料 显式正式状态资料",
        include_semantic=False,
      )
    with sqlite3.connect(Path(project.path) / "knowledge.db") as connection:
      disabled_rows = connection.execute(
        """
        SELECT chunk_id FROM knowledge_chunks
        WHERE content LIKE ? OR content LIKE ?
        """,
        ("%zzwipstatusalpha%", "%zzarchivedstatusalpha%"),
      ).fetchall()

    note_titles = {item.title for item in detail.story_overview.obsidian.notes}
    self.assertIn("中文正式状态", note_titles)
    self.assertIn("英文正式状态", note_titles)
    self.assertIn("显式正式状态", note_titles)
    self.assertNotIn("显式草稿状态", note_titles)
    self.assertNotIn("归档状态", note_titles)
    self.assertEqual(disabled_rows, [])
    self.assertTrue(any(item.source == "Obsidian" and "中文正式状态" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "英文正式状态" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "显式正式状态" in item.section for item in enabled_hits))

  def test_obsidian_status_boolean_properties_drive_filtering_when_status_missing(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-status-booleans"
    vault_dir.mkdir()
    (vault_dir / "正式属性.md").write_text(
      """---
canonical: true
usable_by_ai: true
---
# 正式属性

正式属性资料说明作者只用布尔属性标记正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "发布属性.md").write_text(
      """---
published: yes
usable_by_ai: true
---
# 发布属性

发布属性资料说明作者用发布布尔属性标记正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "正文正式属性.md").write_text(
      """# 正文正式属性

canonical:: true
AI可用:: 是

正文正式属性资料说明作者用正文内联布尔属性标记正式资料。
""",
      encoding="utf-8",
    )
    (vault_dir / "显式状态仍优先.md").write_text(
      """---
status: canonical
draft: true
usable_by_ai: true
---
# 显式状态仍优先

显式状态仍优先资料说明 status 字段优先于布尔属性。
""",
      encoding="utf-8",
    )
    (vault_dir / "草稿属性.md").write_text(
      """---
draft: true
usable_by_ai: true
---
# 草稿属性

zzdraftpropertyalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "私密属性.md").write_text(
      """---
private: true
usable_by_ai: true
---
# 私密属性

zzprivatepropertyalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "归档属性.md").write_text(
      """---
archived: true
usable_by_ai: true
---
# 归档属性

zzarchivedpropertyalpha 不应该进入知识索引。
""",
      encoding="utf-8",
    )
    (vault_dir / "布尔正式画布.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "a",
              "type": "text",
              "text": "canonical:: true\nAI可用:: 是\n布尔正式画布资料说明 Canvas 也能用布尔属性声明正式资料。",
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (vault_dir / "布尔草稿画布.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "a",
              "type": "text",
              "text": "draft:: true\nAI可用:: 是\nzzdraftcanvaspropertyalpha 不应该进入知识索引。",
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          excluded_statuses=["draft", "private", "deprecated"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      enabled_hits = search_project_knowledge(
        self.settings,
        project.id,
        "正式属性资料 发布属性资料 正文正式属性资料 显式状态仍优先资料 布尔正式画布资料",
        include_semantic=False,
      )
    with sqlite3.connect(Path(project.path) / "knowledge.db") as connection:
      disabled_rows = connection.execute(
        """
        SELECT chunk_id FROM knowledge_chunks
        WHERE content LIKE ? OR content LIKE ? OR content LIKE ? OR content LIKE ?
        """,
        (
          "%zzdraftpropertyalpha%",
          "%zzprivatepropertyalpha%",
          "%zzarchivedpropertyalpha%",
          "%zzdraftcanvaspropertyalpha%",
        ),
      ).fetchall()

    note_titles = {item.title for item in detail.story_overview.obsidian.notes}
    self.assertIn("正式属性", note_titles)
    self.assertIn("发布属性", note_titles)
    self.assertIn("正文正式属性", note_titles)
    self.assertIn("显式状态仍优先", note_titles)
    self.assertIn("布尔正式画布", note_titles)
    self.assertNotIn("草稿属性", note_titles)
    self.assertNotIn("私密属性", note_titles)
    self.assertNotIn("归档属性", note_titles)
    self.assertNotIn("布尔草稿画布", note_titles)
    self.assertEqual(disabled_rows, [])
    self.assertTrue(any(item.source == "Obsidian" and "正式属性" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "发布属性" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正文正式属性" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "显式状态仍优先" in item.section for item in enabled_hits))
    self.assertTrue(any(item.source == "Obsidian" and "布尔正式画布" in item.section for item in enabled_hits))

  def test_obsidian_visible_callout_tasks_drive_inline_metadata_and_constraints(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-callout-tasks"
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 林追

林追正在追查旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
usable_by_ai: true
reveal_after_chapter: 70
---
# 未来真相

未来真相只能在后段公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "第058章任务卡.md").write_text(
      """# 第058章任务卡

> [!note] 第五十八章任务
> - [!] status:: canonical
> - [?] usable_by_ai:: true
> - [>] summary:: 可见任务卡提示
> - [/] keywords:: 潮标任务, 码头暗号
> - [-] chapter_range:: 58
> - [!] source_notes:: [[Clues/当前线索]]
> - [?] related_characters:: [[Characters/林追]]
> - [>] required_phrases:: 潮声异常
> - [!] forbidden_phrases:: 提前公开沉船真相
>
> ## 必须包含
> - [>] 旧码头暗号
>
> ## 禁止出现
> - [?] 终局答案
>
> ## 来源笔记
> - [!] [[Clues/当前线索]]
> - [?] [[Secrets/未来真相]]
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          include_without_status=False,
          require_usable_by_ai=True,
        ),
      )
      early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标任务",
        include_semantic=False,
        chapter_index=57,
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "潮标任务",
        include_semantic=False,
        chapter_index=58,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "第058章任务卡")
    self.assertEqual(note.status, "canonical")
    self.assertTrue(note.usable_by_ai)
    self.assertEqual((note.chapter_start, note.chapter_end), (58, 58))
    self.assertIn("潮标任务", note.keywords)
    self.assertIn("码头暗号", note.keywords)
    self.assertIn("潮声异常", note.required_phrases)
    self.assertIn("旧码头暗号", note.required_phrases)
    self.assertIn("提前公开沉船真相", note.forbidden_phrases)
    self.assertIn("终局答案", note.forbidden_phrases)
    self.assertIn("Clues/当前线索", note.links)
    self.assertIn("Characters/林追", note.links)
    self.assertIn("Secrets/未来真相", note.links)
    self.assertIn("Clues/当前线索.md", note.resolved_links)
    self.assertIn("Characters/林追.md", note.resolved_links)
    self.assertIn("Secrets/未来真相.md", note.resolved_links)
    self.assertIn("来源笔记 -> Clues/当前线索", note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追", note.graph_relations)
    self.assertIn("来源笔记 -> Secrets/未来真相", note.graph_relations)
    self.assertEqual(early_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "第058章任务卡" in item.section for item in scoped_hits))

    scoped_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=58,
      query="潮标任务",
    )
    callout_content = next(item for item in scoped_note_contents if item["title"] == "第058章任务卡")
    self.assertIn("未开放设定", callout_content["content"])
    self.assertIn("旧码头暗号", callout_content["content"])
    self.assertNotIn("未来真相", callout_content["content"])

  def test_obsidian_markdown_tables_feed_chapter_contract_context_and_graph(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-table-contract"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "遗言线索.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 遗言线索

遗言线索必须把林追推向黑盐仓库。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 林追

林追在第五十八章必须重新判断宋闻。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

未来真相不能进入第五十八章。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第058章表格合同.md").write_text(
      """---
type: chapter_contract
status: canonical
chapter_range: 58
---
# 第058章表格合同

| 章节目标 | 必须节拍 | 禁写动作 | 验收项 | 证据来源 | 相关人物 |
| --- | --- | --- | --- | --- | --- |
| 让遗言逼迫林追选择黑盐仓库 | 林追发现遗言断句<br>宋闻沉默暴露方向 | 直接公布铜钥匙最终身份 | 章尾留下黑盐仓库选择\\|旧账缺页 | [[Clues/遗言线索]]；[[Secrets/未来真相]] | [[Characters/林追]] |
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "黑盐仓库选择",
        include_semantic=False,
        chapter_index=58,
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        project.id,
        chapter_index=58,
        query="黑盐仓库选择",
      )

    obsidian = detail.story_overview.obsidian
    contract_note = next(item for item in obsidian.notes if item.title == "第058章表格合同")
    clue_note = next(item for item in obsidian.notes if item.title == "遗言线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("章节目标：让遗言逼迫林追选择黑盐仓库", contract_note.preview)
    self.assertIn("必须完成的节拍：林追发现遗言断句；宋闻沉默暴露方向", contract_note.preview)
    self.assertIn("证据来源 -> Clues/遗言线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Secrets/未来真相", contract_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追", contract_note.graph_relations)
    self.assertIn("Plans/第058章表格合同.md", clue_note.backlinks)
    self.assertIn("Plans/第058章表格合同.md", character_note.backlinks)
    self.assertIn("Plans/第058章表格合同.md", future_note.backlinks)
    self.assertTrue(any(item.source == "Obsidian" and "第058章表格合同" in item.section for item in scoped_hits))

    scoped_content = next(item["content"] for item in scoped_contents if item["title"] == "第058章表格合同")
    self.assertIn("章节目标：让遗言逼迫林追选择黑盐仓库", scoped_content)
    self.assertIn("必须完成的节拍：林追发现遗言断句；宋闻沉默暴露方向", scoped_content)
    self.assertIn("禁止动作：直接公布铜钥匙最终身份", scoped_content)
    self.assertIn("验收项：章尾留下黑盐仓库选择|旧账缺页", scoped_content)
    self.assertNotIn("验收项：章尾留下黑盐仓库选择\\|旧账缺页", scoped_content)
    self.assertIn("证据来源 -> Clues/遗言线索", scoped_content)
    self.assertIn("相关人物 -> Characters/林追", scoped_content)
    self.assertIn("未开放设定", scoped_content)
    self.assertNotIn("未来真相", scoped_content)

  def test_obsidian_canvas_text_tables_feed_chapter_contract_context_and_graph(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-table-contract"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "画布线索.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 画布线索

画布线索要求林追回到旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 林追

林追需要在旧码头重新判断遗言。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

未来真相不能进入第五十八章。
""",
      encoding="utf-8",
    )
    canvas_text = """title:: 第058章画布表格合同
status:: canonical
chapter_range:: 58

| 章节目标 | 验收项 | 证据来源 | 相关人物 |
| --- | --- | --- | --- |
| 让画布合同推动林追回到旧码头 | 章尾保留旧码头选择\\|账册未翻完 | [[Clues/画布线索]]；[[Secrets/未来真相]] | [[Characters/林追]] |
"""
    (vault_dir / "Plans" / "第058章画布表格合同.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "contract",
              "type": "text",
              "text": canvas_text,
              "x": 0,
              "y": 0,
              "width": 520,
              "height": 280,
            }
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "旧码头选择",
        include_semantic=False,
        chapter_index=58,
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        project.id,
        chapter_index=58,
        query="旧码头选择",
      )

    obsidian = detail.story_overview.obsidian
    contract_note = next(item for item in obsidian.notes if item.title == "第058章画布表格合同")
    clue_note = next(item for item in obsidian.notes if item.title == "画布线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("章节目标：让画布合同推动林追回到旧码头", contract_note.preview)
    self.assertIn("证据来源 -> Clues/画布线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Secrets/未来真相", contract_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追", contract_note.graph_relations)
    self.assertIn("Plans/第058章画布表格合同.canvas", clue_note.backlinks)
    self.assertIn("Plans/第058章画布表格合同.canvas", character_note.backlinks)
    self.assertIn("Plans/第058章画布表格合同.canvas", future_note.backlinks)
    self.assertTrue(any(item.source == "Obsidian" and "第058章画布表格合同" in item.section for item in scoped_hits))

    scoped_content = next(item["content"] for item in scoped_contents if item["title"] == "第058章画布表格合同")
    self.assertIn("章节目标：让画布合同推动林追回到旧码头", scoped_content)
    self.assertIn("验收项：章尾保留旧码头选择|账册未翻完", scoped_content)
    self.assertNotIn("验收项：章尾保留旧码头选择\\|账册未翻完", scoped_content)
    self.assertIn("证据来源 -> Clues/画布线索", scoped_content)
    self.assertIn("相关人物 -> Characters/林追", scoped_content)
    self.assertIn("未开放设定", scoped_content)
    self.assertNotIn("未来真相", scoped_content)

  def test_obsidian_visible_callout_tables_feed_chapter_contract_context_and_graph(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-callout-table-contract"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "呼吸线索.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 呼吸线索

呼吸线索要求林追在旧码头停顿。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 林追

林追需要看见宋闻的呼吸停顿。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

未来真相不能进入第五十八章。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第058章callout表格合同.md").write_text(
      """---
type: chapter_contract
status: canonical
chapter_range: 58
---
# 第058章callout表格合同

> [!note] 本章合同
> | 章节目标 | 验收项 | 证据来源 | 相关人物 |
> | --- | --- | --- | --- |
> | 让呼吸停顿推动林追追问宋闻 | 章尾保留呼吸停顿选择\\|潮声异常 | [[Clues/呼吸线索]]；[[Secrets/未来真相]] | [[Characters/林追]] |
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "呼吸停顿选择",
        include_semantic=False,
        chapter_index=58,
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        project.id,
        chapter_index=58,
        query="呼吸停顿选择",
      )

    obsidian = detail.story_overview.obsidian
    contract_note = next(item for item in obsidian.notes if item.title == "第058章callout表格合同")
    clue_note = next(item for item in obsidian.notes if item.title == "呼吸线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("章节目标：让呼吸停顿推动林追追问宋闻", contract_note.preview)
    self.assertIn("证据来源 -> Clues/呼吸线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Secrets/未来真相", contract_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追", contract_note.graph_relations)
    self.assertIn("Plans/第058章callout表格合同.md", clue_note.backlinks)
    self.assertIn("Plans/第058章callout表格合同.md", character_note.backlinks)
    self.assertIn("Plans/第058章callout表格合同.md", future_note.backlinks)
    self.assertTrue(any(item.source == "Obsidian" and "第058章callout表格合同" in item.section for item in scoped_hits))

    scoped_content = next(item["content"] for item in scoped_contents if item["title"] == "第058章callout表格合同")
    self.assertIn("章节目标：让呼吸停顿推动林追追问宋闻", scoped_content)
    self.assertIn("验收项：章尾保留呼吸停顿选择|潮声异常", scoped_content)
    self.assertNotIn("验收项：章尾保留呼吸停顿选择\\|潮声异常", scoped_content)
    self.assertIn("证据来源 -> Clues/呼吸线索", scoped_content)
    self.assertIn("相关人物 -> Characters/林追", scoped_content)
    self.assertIn("未开放设定", scoped_content)
    self.assertNotIn("未来真相", scoped_content)

  def test_obsidian_frontmatter_object_lists_feed_chapter_plan_context(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-frontmatter-object-list-plan"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Clues" / "潮账线索.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 潮账线索

潮账线索指向旧船队背叛。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 林追

林追必须在第五十八章保留对宋闻的怀疑。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第058章对象合同.md").write_text(
      """---
type: chapter_contract
status: canonical
chapter_range: 58
required_beats: [{goal: 潮师交出假账册, evidence_sources: [{source_note: [[Clues/潮账线索]], reason: flow mapping evidence}], acceptance: 账册不能被完全解释}]
scenes:
  - goal: >
      林追在旧码头逼问宋闻，
      并保留对潮账线索的怀疑。
    conflict: 宋闻只交出[[Clues/潮账线索]]
    payoff: 银潮灯第一次失灵
    character_checks:
      - character: 林追
        check: 不能立刻相信宋闻
    evidence_sources:
      - source_note: [[Clues/潮账线索]]
        reason: >
          潮账线索推动本章选择，
          但不能提前揭示背叛者。
  - goal: 潮师公开否认账册
    evidence_sources:
      - [[Clues/潮账线索]]
      - [林追](../Characters/林追.md)
  - {goal: 林追把假账册交给潮师试探, evidence_sources: [{source_note: [[Clues/潮账线索]], reason: flow mapping list item}], payoff: 潮师避开账册缺页}
  -
    goal: 宋闻在潮声里留下第二个疑点
    conflict: >
      疑点只指向账册缺页，
      不能提前确认背叛者。
    evidence_sources:
      -
        source_note: [[Clues/潮账线索]]
        reason: 空标记对象列表仍要可读
character_checks:
  - character: 林追
    check: 不能立刻相信宋闻
debts_to_advance:
  - debt: 旧船队背叛
    action: 让潮账线索进入林追压力
---
# 第058章对象合同
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "银潮灯第一次失灵",
        include_semantic=False,
        chapter_index=58,
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        project.id,
        chapter_index=58,
        query="银潮灯第一次失灵",
      )

    contract_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "第058章对象合同")
    clue_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "潮账线索")
    character_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "林追")
    self.assertIn("Clues/潮账线索", contract_note.links)
    self.assertIn("Characters/林追.md", contract_note.links)
    self.assertIn("来源笔记 -> Clues/潮账线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Clues/潮账线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Characters/林追.md", contract_note.graph_relations)
    self.assertIn("Plans/第058章对象合同.md", clue_note.backlinks)
    self.assertIn("Plans/第058章对象合同.md", character_note.backlinks)
    self.assertTrue(any(item.source == "Obsidian" and "第058章对象合同" in item.section for item in scoped_hits))

    scoped_content = next(item["content"] for item in scoped_contents if item["title"] == "第058章对象合同")
    self.assertIn("必须完成的节拍：", scoped_content)
    self.assertIn("目标：潮师交出假账册", scoped_content)
    self.assertIn("证据来源：来源笔记：[[Clues/潮账线索]]；理由：flow mapping evidence", scoped_content)
    self.assertIn("验收：账册不能被完全解释", scoped_content)
    self.assertIn("目标：林追把假账册交给潮师试探", scoped_content)
    self.assertIn("证据来源：来源笔记：[[Clues/潮账线索]]；理由：flow mapping list item", scoped_content)
    self.assertIn("兑现：潮师避开账册缺页", scoped_content)
    self.assertIn("目标：林追在旧码头逼问宋闻", scoped_content)
    self.assertIn("并保留对潮账线索的怀疑。", scoped_content)
    self.assertIn("冲突：宋闻只交出[[Clues/潮账线索]]", scoped_content)
    self.assertIn("兑现：银潮灯第一次失灵", scoped_content)
    self.assertIn("人物检查：人物：林追；检查：不能立刻相信宋闻", scoped_content)
    self.assertIn(
      "证据来源：来源笔记：[[Clues/潮账线索]]；理由：潮账线索推动本章选择， 但不能提前揭示背叛者。",
      scoped_content,
    )
    self.assertIn("目标：宋闻在潮声里留下第二个疑点", scoped_content)
    self.assertIn("冲突：疑点只指向账册缺页， 不能提前确认背叛者。", scoped_content)
    self.assertIn("证据来源：来源笔记：[[Clues/潮账线索]]；理由：空标记对象列表仍要可读", scoped_content)
    self.assertIn("证据来源：[[Clues/潮账线索]]", scoped_content)
    self.assertIn("证据来源：[林追](../Characters/林追.md)", scoped_content)
    self.assertIn("人物检查：人物：林追；检查：不能立刻相信宋闻", scoped_content)
    self.assertIn("必须推进的债务：债务：旧船队背叛；动作：让潮账线索进入林追压力", scoped_content)

  def test_obsidian_frontmatter_nested_mapping_feeds_chapter_plan_context(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-frontmatter-nested-mapping-plan"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Clues").mkdir(parents=True)
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir(parents=True)
    (vault_dir / "Clues" / "嵌套线索.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 嵌套线索

嵌套线索指向盐账缺页。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 林追

林追必须在盐账缺页里保持怀疑。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

未来真相要到第七十一章以后才可公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "嵌套合同.md").write_text(
      """---
type: chapter_contract
status: canonical
chapter_contract:
  chapter_range: 58
  objective: 让嵌套合同推动林追检查盐账
  required_beats:
    - goal: 林追查看[[Clues/嵌套线索]]
      evidence_sources:
        - source_note: [[Clues/嵌套线索]]
          reason: 嵌套对象证据
  acceptance_checks:
    - 章尾保留盐账疑点
  evidence_sources:
    - [[Clues/嵌套线索]]
    - [[Secrets/未来真相]]
  related_characters:
    - [[Characters/林追]]
---
# 嵌套合同
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        project.id,
        "嵌套合同推动林追检查盐账",
        include_semantic=False,
        chapter_index=58,
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        project.id,
        chapter_index=58,
        query="嵌套合同推动林追检查盐账",
      )

    obsidian = detail.story_overview.obsidian
    contract_note = next(item for item in obsidian.notes if item.title == "嵌套合同")
    clue_note = next(item for item in obsidian.notes if item.title == "嵌套线索")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertEqual((contract_note.chapter_start, contract_note.chapter_end), (58, 58))
    self.assertIn("章节目标：让嵌套合同推动林追检查盐账", contract_note.preview)
    self.assertIn("Clues/嵌套线索", contract_note.links)
    self.assertIn("Characters/林追", contract_note.links)
    self.assertIn("Secrets/未来真相", contract_note.links)
    self.assertIn("来源笔记 -> Clues/嵌套线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Clues/嵌套线索", contract_note.graph_relations)
    self.assertIn("证据来源 -> Secrets/未来真相", contract_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追", contract_note.graph_relations)
    self.assertIn("Plans/嵌套合同.md", clue_note.backlinks)
    self.assertIn("Plans/嵌套合同.md", character_note.backlinks)
    self.assertIn("Plans/嵌套合同.md", future_note.backlinks)
    self.assertTrue(any(item.source == "Obsidian" and "嵌套合同" in item.section for item in scoped_hits))

    scoped_content = next(item["content"] for item in scoped_contents if item["title"] == "嵌套合同")
    self.assertIn("章节目标：让嵌套合同推动林追检查盐账", scoped_content)
    self.assertIn("必须完成的节拍：目标：林追查看[[Clues/嵌套线索]]", scoped_content)
    self.assertIn("证据来源：来源笔记：[[Clues/嵌套线索]]；理由：嵌套对象证据", scoped_content)
    self.assertIn("验收项：章尾保留盐账疑点", scoped_content)
    self.assertIn("证据来源 -> Clues/嵌套线索", scoped_content)
    self.assertIn("相关人物 -> Characters/林追", scoped_content)
    self.assertIn("未开放设定", scoped_content)
    self.assertNotIn("未来真相", scoped_content)

  def test_obsidian_markdown_internal_links_are_graph_safe_by_chapter(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-links"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

第一章只能写 [潮声异常](未来真相.md)，不能提前写 [未来真相](未来真相.md)。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

终局答案在第六十一章以后才可公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "未来真相",
        include_semantic=False,
        chapter_index=1,
      )

    current_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "未来真相")
    self.assertIn("未来真相.md", current_note.links)
    self.assertIn("未来真相.md", current_note.resolved_links)
    self.assertIn("当前线索.md", future_note.backlinks)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="潮声异常",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["当前线索"])
    self.assertIn("潮声异常", early_note_contents[0]["content"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertNotIn("未来真相", early_note_contents[0]["content"])
    self.assertNotIn("未来真相.md", early_note_contents[0]["content"])

  def test_obsidian_canvas_file_nodes_enter_graph_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

第一章只写潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

终局答案在第六十一章以后才可公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "人物关系图.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "current", "type": "file", "file": "当前线索.md"},
            {"id": "future", "type": "file", "file": "未来真相.md"},
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nusable_by_ai:: true\nsummary:: 人物关系图只说明当前关系。\nkeywords:: 关系图索引\nsource_notes:: [[当前线索.md]]\nsource_chapters:: 1, 2\n适用章节：1-2\n必须出现：潮声异常\nCanvas 提醒：第一章只写可见异常。",
            },
          ],
          "edges": [
            {"id": "edge-1", "fromNode": "current", "toNode": "future", "label": "揭示沉船真相"},
            {"id": "edge-2", "fromNode": "note", "toNode": "current", "label": "约束"},
            {"id": "edge-3", "fromNode": "current", "toNode": "current", "label": "未来真相校验"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "未来真相",
        include_semantic=False,
        chapter_index=1,
      )

    obsidian = detail.story_overview.obsidian
    self.assertEqual(obsidian.included_count, 3)
    canvas_note = next(item for item in obsidian.notes if item.title == "人物关系图")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertEqual(canvas_note.note_type, "canvas")
    self.assertEqual(canvas_note.status, "canonical")
    self.assertEqual(canvas_note.source_chapters, [1, 2])
    self.assertIn("关系图索引", canvas_note.keywords)
    self.assertIn("当前线索.md", canvas_note.links)
    self.assertIn("未来真相.md", canvas_note.links)
    self.assertIn("来源笔记 -> 当前线索.md", canvas_note.graph_relations)
    self.assertIn("未来真相校验：当前线索 -> 当前线索.md", canvas_note.graph_relations)
    self.assertIn("揭示沉船真相：当前线索 -> 未来真相.md", canvas_note.graph_relations)
    self.assertIn("当前线索.md", canvas_note.resolved_links)
    self.assertIn("未来真相.md", canvas_note.resolved_links)
    self.assertIn("人物关系图.canvas", current_note.backlinks)
    self.assertIn("人物关系图.canvas", future_note.backlinks)
    self.assertIn("必须出现：潮声异常", canvas_note.preview)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="人物关系图",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["人物关系图"])
    self.assertIn("潮声异常", early_note_contents[0]["content"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertIn("未开放设定校验：当前线索 -> 当前线索.md", early_note_contents[0]["content"])
    self.assertIn("未开放关系", early_note_contents[0]["content"])
    self.assertNotIn("揭示沉船真相", early_note_contents[0]["content"])
    self.assertNotIn("未来真相校验", early_note_contents[0]["content"])
    self.assertNotIn("未来真相", early_note_contents[0]["content"])
    self.assertNotIn("未来真相.md", early_note_contents[0]["content"])

  def test_obsidian_canvas_relative_file_nodes_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-relative"
    (vault_dir / "Canvases").mkdir(parents=True)
    (vault_dir / "Clues").mkdir()
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

第一章只写潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

终局答案在第六十一章以后才可公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "Canvases" / "关系图.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "current", "type": "file", "file": "../Clues/当前线索.md"},
            {"id": "future", "type": "file", "file": "../Secrets/未来真相.md"},
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nsummary:: 关系图只说明当前线索。\nkeywords:: 关系图索引\nchapter_range:: 1-2\n必须出现：潮声异常",
            },
          ],
          "edges": [
            {"id": "edge-1", "fromNode": "current", "toNode": "future", "label": "揭示终局答案"},
            {"id": "edge-2", "fromNode": "note", "toNode": "current", "label": "约束"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "终局答案",
        include_semantic=False,
        chapter_index=1,
      )

    obsidian = detail.story_overview.obsidian
    canvas_note = next(item for item in obsidian.notes if item.title == "关系图")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Clues/当前线索.md", canvas_note.links)
    self.assertIn("Secrets/未来真相.md", canvas_note.links)
    self.assertIn("Clues/当前线索.md", canvas_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", canvas_note.resolved_links)
    self.assertIn("揭示终局答案：当前线索 -> Secrets/未来真相.md", canvas_note.graph_relations)
    self.assertIn("Canvases/关系图.canvas", current_note.backlinks)
    self.assertIn("Canvases/关系图.canvas", future_note.backlinks)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="关系图索引",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["关系图"])
    self.assertIn("潮声异常", early_note_contents[0]["content"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertIn("未开放关系", early_note_contents[0]["content"])
    self.assertNotIn("揭示终局答案", early_note_contents[0]["content"])
    self.assertNotIn("终局答案", early_note_contents[0]["content"])
    self.assertNotIn("Secrets/未来真相", early_note_contents[0]["content"])
    self.assertNotIn("../Secrets/未来真相", early_note_contents[0]["content"])

  def test_obsidian_canvas_file_node_subpaths_enter_context_without_graph_noise(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-subpaths"
    (vault_dir / "Canvases").mkdir(parents=True)
    (vault_dir / "Plans").mkdir()
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Plans" / "第58章合同.md").write_text(
      """---
status: canonical
chapter_range: 58-59
---
# 第58章合同

## 合同核验小节

这一章必须核验潮汐暗账。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局答案]
---
# 未来真相

## 终局答案小节

这段不能进入第五十八章。
""",
      encoding="utf-8",
    )
    (vault_dir / "Canvases" / "章节板.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "current-plan",
              "type": "file",
              "file": "../Plans/第58章合同.md",
              "subpath": "#合同核验小节",
            },
            {
              "id": "future-plan",
              "type": "file",
              "file": "../Secrets/未来真相.md#终局答案小节",
            },
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nsummary:: 章节板记录第五十八章合同。\nkeywords:: 合同核验小节\nchapter_range:: 58\n必须出现：潮汐暗账",
            },
          ],
          "edges": [
            {"id": "edge-1", "fromNode": "note", "toNode": "current-plan", "label": "当前章合同"},
            {"id": "edge-2", "fromNode": "current-plan", "toNode": "future-plan", "label": "禁止提前解释终局答案"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      subpath_hits = search_project_knowledge(
        self.settings,
        project.id,
        "合同核验小节",
        include_semantic=False,
        chapter_index=58,
      )
      future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "终局答案小节",
        include_semantic=False,
        chapter_index=58,
      )

    canvas_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "章节板")
    self.assertIn("Plans/第58章合同.md", canvas_note.links)
    self.assertIn("Secrets/未来真相.md", canvas_note.links)
    self.assertNotIn("Plans/第58章合同.md#合同核验小节", canvas_note.links)
    self.assertTrue(any(
      item.startswith("当前章合同：") and item.endswith("-> Plans/第58章合同.md")
      for item in canvas_note.graph_relations
    ))
    self.assertIn("禁止提前解释终局答案：第58章合同 -> Secrets/未来真相.md", canvas_note.graph_relations)
    self.assertTrue(any(item.source == "Obsidian" and "章节板" in item.section for item in subpath_hits))
    self.assertEqual(future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=58,
      query="合同核验小节",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["章节板"])
    self.assertIn("Canvas 文件节点", early_note_contents[0]["content"])
    self.assertIn("[[Plans/第58章合同.md#合同核验小节]]", early_note_contents[0]["content"])
    self.assertIn("潮汐暗账", early_note_contents[0]["content"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertIn("未开放关系", early_note_contents[0]["content"])
    self.assertNotIn("终局答案", early_note_contents[0]["content"])
    self.assertNotIn("终局答案小节", early_note_contents[0]["content"])
    self.assertNotIn("Secrets/未来真相", early_note_contents[0]["content"])

  def test_obsidian_canvas_inline_title_enters_summary_and_knowledge_index(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-title"
    vault_dir.mkdir()
    (vault_dir / "graph.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "note",
              "type": "text",
              "text": (
                "status:: canonical\n"
                "title:: 人物关系索引\n"
                "aliases:: 关系总图\n"
                "summary:: 记录林追与灯塔议会的当前关系。\n"
                "keywords:: 林追 灯塔议会\n"
                "chapter_range:: 1-2\n"
                "必须出现：铜钥匙"
              ),
            },
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      hits = search_project_knowledge(
        self.settings,
        project.id,
        "人物关系索引",
        include_semantic=False,
        chapter_index=1,
      )

    canvas_note = next(item for item in detail.story_overview.obsidian.notes if item.relative_path == "graph.canvas")
    self.assertEqual(canvas_note.title, "人物关系索引")
    self.assertIn("关系总图", canvas_note.aliases)
    self.assertIn("林追 灯塔议会", canvas_note.keywords)
    self.assertEqual(canvas_note.chapter_start, 1)
    self.assertEqual(canvas_note.chapter_end, 2)
    self.assertTrue(any(item.source == "Obsidian" and "人物关系索引" in item.section for item in hits))

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="关系总图",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["人物关系索引"])
    self.assertIn("Obsidian 笔记：人物关系索引", early_note_contents[0]["content"])
    self.assertIn("铜钥匙", early_note_contents[0]["content"])

  def test_obsidian_canvas_group_nodes_enter_context_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-groups"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

第一章只写铜钥匙和旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

终局答案在第六十一章以后才可公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "分组图.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "group-current", "type": "group", "label": "第一章线索组", "x": 0, "y": 0, "width": 180, "height": 150},
            {"id": "current", "type": "file", "file": "当前线索.md", "x": 30, "y": 30, "width": 80, "height": 80},
            {"id": "group-future", "type": "group", "label": "未来真相", "x": 220, "y": 0, "width": 180, "height": 150},
            {"id": "future", "type": "file", "file": "未来真相.md", "x": 250, "y": 30, "width": 80, "height": 80},
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nsummary:: 分组图只公开当前线索组。\nkeywords:: 分组索引\nchapter_range:: 1-2\n必须出现：铜钥匙",
              "x": 0,
              "y": 190,
              "width": 220,
              "height": 120,
            },
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "未来真相",
        include_semantic=False,
        chapter_index=1,
      )

    canvas_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "分组图")
    self.assertIn("当前线索.md", canvas_note.links)
    self.assertIn("未来真相.md", canvas_note.links)
    self.assertIn("Canvas 分组：第一章线索组 -> 当前线索.md", canvas_note.graph_relations)
    self.assertIn("Canvas 分组：未来真相 -> 未来真相.md", canvas_note.graph_relations)
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="分组索引",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["分组图"])
    self.assertIn("Canvas 分组", early_note_contents[0]["content"])
    self.assertIn("第一章线索组", early_note_contents[0]["content"])
    self.assertIn("当前线索", early_note_contents[0]["content"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertNotIn("未来真相", early_note_contents[0]["content"])
    self.assertNotIn("未来真相.md", early_note_contents[0]["content"])

  def test_obsidian_canvas_hidden_nodes_do_not_drop_visible_canvas(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-hidden-nodes"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

第一章只写铜钥匙和公开节点线索。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

隐藏节点真相只能后段公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "节点隔离.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "current", "type": "file", "file": "当前线索.md", "x": 0, "y": 0, "width": 90, "height": 80},
            {
              "id": "visible-text",
              "type": "text",
              "text": "status:: canonical\nsummary:: Canvas 公开节点只说明当前线索。\nkeywords:: 公开关系图\nchapter_range:: 1-2\nsource_notes:: [[当前线索]]\nrequired_phrases:: 公开节点线索\n#公开节点标签\n<details><summary>Canvas 公开折叠</summary>\ndraft:: false\nrequired_phrases:: Canvas公开折叠线索\n#Canvas公开折叠标签\n</details>\n<details><summary>Canvas 草稿折叠</summary>\ndraft:: true\nsource_notes:: [[未来真相]]\nrequired_phrases:: Canvas草稿折叠真相\n#Canvas草稿折叠隐藏标签\n</details>",
              "x": 120,
              "y": 0,
              "width": 220,
              "height": 140,
            },
            {
              "id": "hidden-text",
              "type": "text",
              "text": "no_ai:: true\nsource_notes:: [[未来真相]]\nrequired_phrases:: 隐藏节点真相\n#隐藏节点标签",
              "x": 120,
              "y": 180,
              "width": 220,
              "height": 100,
            },
            {
              "id": "visible-false-flag",
              "type": "text",
              "text": "no_ai:: false\nstatus:: canonical\nsummary:: Canvas false 标记节点仍然可见。\nkeywords:: false可见图\nrequired_phrases:: false标记可见线索\n#false可见标签",
              "x": 0,
              "y": 180,
              "width": 220,
              "height": 100,
            },
            {"id": "secret-group", "type": "group", "label": "no-ai", "x": 380, "y": 0, "width": 160, "height": 140},
            {"id": "future", "type": "file", "file": "未来真相.md", "x": 400, "y": 30, "width": 80, "height": 80},
          ],
          "edges": [
            {"id": "edge-current", "fromNode": "visible-text", "toNode": "current", "label": "支持当前"},
            {"id": "edge-hidden-text", "fromNode": "hidden-text", "toNode": "current", "label": "隐藏支持"},
            {"id": "edge-hidden-group", "fromNode": "current", "toNode": "future", "label": "未来关系"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      visible_hits = search_project_knowledge(
        self.settings,
        project.id,
        "公开关系图",
        include_semantic=False,
        chapter_index=1,
      )
      hidden_hits = search_project_knowledge(
        self.settings,
        project.id,
        "隐藏节点真相",
        include_semantic=False,
        chapter_index=1,
      )

    canvas_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "节点隔离")
    current_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "未来真相")
    self.assertIn("当前线索.md", canvas_note.links)
    self.assertNotIn("未来真相.md", canvas_note.links)
    self.assertIn("当前线索.md", canvas_note.resolved_links)
    self.assertNotIn("未来真相.md", canvas_note.resolved_links)
    self.assertIn("公开节点标签", canvas_note.tags)
    self.assertIn("Canvas公开折叠标签", canvas_note.tags)
    self.assertIn("false可见标签", canvas_note.tags)
    self.assertNotIn("隐藏节点标签", canvas_note.tags)
    self.assertNotIn("Canvas草稿折叠隐藏标签", canvas_note.tags)
    self.assertIn("公开节点线索", canvas_note.required_phrases)
    self.assertIn("Canvas公开折叠线索", canvas_note.required_phrases)
    self.assertIn("false标记可见线索", canvas_note.required_phrases)
    self.assertNotIn("隐藏节点真相", canvas_note.required_phrases)
    self.assertNotIn("Canvas草稿折叠真相", canvas_note.required_phrases)
    self.assertIn("节点隔离.canvas", current_note.backlinks)
    self.assertNotIn("节点隔离.canvas", future_note.backlinks)
    self.assertTrue(any(item.source == "Obsidian" and "节点隔离" in item.section for item in visible_hits))
    self.assertEqual(hidden_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="公开关系图",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["节点隔离"])
    self.assertIn("公开节点线索", early_note_contents[0]["content"])
    self.assertIn("Canvas公开折叠线索", early_note_contents[0]["content"])
    self.assertIn("false标记可见线索", early_note_contents[0]["content"])
    self.assertNotIn("隐藏节点真相", early_note_contents[0]["content"])
    self.assertNotIn("Canvas草稿折叠真相", early_note_contents[0]["content"])
    self.assertNotIn("未来真相", early_note_contents[0]["content"])

  def test_obsidian_canvas_link_nodes_enter_search_without_graph_noise(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-links"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

第一章只写旧码头水利史和铜钥匙。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
---
# 未来真相

终局答案在第六十一章以后才可公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "考据链接.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "current", "type": "file", "file": "当前线索.md", "x": 0, "y": 0, "width": 90, "height": 80},
            {
              "id": "research",
              "type": "link",
              "url": "https://example.com/old-harbor-waterworks",
              "label": "旧码头水利史",
              "x": 140,
              "y": 0,
              "width": 160,
              "height": 80,
            },
            {
              "id": "future-link",
              "type": "link",
              "url": "https://example.com/locked-reference",
              "label": "未来真相外部考据",
              "x": 140,
              "y": 110,
              "width": 160,
              "height": 80,
            },
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nsummary:: 外部链接只作为考据入口。\nkeywords:: 旧码头水利史\nchapter_range:: 1-2\n必须出现：铜钥匙",
              "x": 0,
              "y": 220,
              "width": 220,
              "height": 120,
            },
          ],
          "edges": [
            {"id": "edge-1", "fromNode": "research", "toNode": "current", "label": "考据支持"},
            {"id": "edge-2", "fromNode": "current", "toNode": "future-link", "label": "外部参考"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      research_hits = search_project_knowledge(
        self.settings,
        project.id,
        "old-harbor-waterworks",
        include_semantic=False,
        chapter_index=1,
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "未来真相",
        include_semantic=False,
        chapter_index=1,
      )

    canvas_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "考据链接")
    self.assertIn("当前线索.md", canvas_note.links)
    self.assertIn("https://example.com/old-harbor-waterworks", canvas_note.external_links)
    self.assertIn("https://example.com/locked-reference", canvas_note.external_links)
    self.assertIn("旧码头水利史：https://example.com/old-harbor-waterworks", canvas_note.external_references)
    self.assertIn("未来真相外部考据：https://example.com/locked-reference", canvas_note.external_references)
    self.assertNotIn("https://example.com/old-harbor-waterworks", canvas_note.links)
    self.assertNotIn("https://example.com/locked-reference", canvas_note.links)
    self.assertIn("考据支持：旧码头水利史 -> 当前线索.md", canvas_note.graph_relations)
    self.assertTrue(any(item.source == "Obsidian" and "考据链接" in item.section for item in research_hits))
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="旧码头水利史",
    )
    self.assertEqual([item["title"] for item in early_note_contents], ["考据链接"])
    self.assertIn("Canvas 链接节点", early_note_contents[0]["content"])
    self.assertIn("外部来源：", early_note_contents[0]["content"])
    self.assertIn("旧码头水利史：https://example.com/old-harbor-waterworks", early_note_contents[0]["content"])
    self.assertIn("https://example.com/old-harbor-waterworks", early_note_contents[0]["content"])
    self.assertIn("旧码头水利史", early_note_contents[0]["content"])
    self.assertIn("未开放设定", early_note_contents[0]["content"])
    self.assertNotIn("未来真相", early_note_contents[0]["content"])

  def test_obsidian_canvas_uri_link_nodes_resolve_and_stay_chapter_safe(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-canvas-uri-links"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Clues").mkdir()
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 当前线索

当前线索要联系林追。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
chapter_range: 1-10
---
# 林追

## 人物页

林追正在查旧码头账册。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 60
aliases: [终局URI]
---
# 未来真相

## 终局答案

终局答案不能提前公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "URI关系.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "current", "type": "file", "file": "Clues/当前线索.md", "x": 0, "y": 0, "width": 120, "height": 80},
            {
              "id": "lin-uri",
              "type": "link",
              "url": "obsidian://open?vault=Demo&file=Characters%2F%E6%9E%97%E8%BF%BD.md&heading=%E4%BA%BA%E7%89%A9%E9%A1%B5",
              "label": "林追URI",
              "x": 160,
              "y": 0,
              "width": 140,
              "height": 80,
            },
            {
              "id": "future-uri",
              "type": "link",
              "url": "obsidian://advanced-uri?vault=Demo&filepath=Secrets%2F%E6%9C%AA%E6%9D%A5%E7%9C%9F%E7%9B%B8.md&heading=%E7%BB%88%E5%B1%80%E7%AD%94%E6%A1%88",
              "label": "终局URI",
              "x": 160,
              "y": 120,
              "width": 140,
              "height": 80,
            },
            {
              "id": "lin-uri-origin",
              "type": "link",
              "url": "obsidian://open?vault=Demo&file=Characters%2F%E6%9E%97%E8%BF%BD.md&heading=%E4%BA%BA%E7%89%A9%E9%A1%B5",
              "x": 340,
              "y": 0,
              "width": 140,
              "height": 80,
            },
            {
              "id": "future-uri-origin",
              "type": "link",
              "url": "obsidian://advanced-uri?vault=Demo&filepath=Secrets%2F%E6%9C%AA%E6%9D%A5%E7%9C%9F%E7%9B%B8.md&heading=%E7%BB%88%E5%B1%80%E7%AD%94%E6%A1%88",
              "x": 340,
              "y": 120,
              "width": 140,
              "height": 80,
            },
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nsummary:: URI 关系板记录林追URI。\nkeywords:: 林追URI\nchapter_range:: 1-10",
              "x": 0,
              "y": 220,
              "width": 220,
              "height": 120,
            },
          ],
          "edges": [
            {"id": "edge-1", "fromNode": "current", "toNode": "lin-uri", "label": "资料跳转"},
            {"id": "edge-2", "fromNode": "current", "toNode": "future-uri", "label": "禁提前"},
            {"id": "edge-3", "fromNode": "lin-uri-origin", "toNode": "current", "label": "反向证据"},
            {"id": "edge-4", "fromNode": "future-uri-origin", "toNode": "current", "label": "未来倒灌"},
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_future_hits = search_project_knowledge(
        self.settings,
        project.id,
        "终局答案",
        include_semantic=False,
        chapter_index=1,
      )

    obsidian = detail.story_overview.obsidian
    canvas_note = next(item for item in obsidian.notes if item.title == "URI关系")
    lin_note = next(item for item in obsidian.notes if item.title == "林追")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Characters/林追.md", canvas_note.links)
    self.assertIn("Secrets/未来真相.md", canvas_note.links)
    self.assertIn("Characters/林追.md", canvas_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", canvas_note.resolved_links)
    self.assertIn("URI关系.canvas", lin_note.backlinks)
    self.assertIn("URI关系.canvas", future_note.backlinks)
    self.assertIn("资料跳转：当前线索 -> Characters/林追.md", canvas_note.graph_relations)
    self.assertIn("禁提前：当前线索 -> Secrets/未来真相.md", canvas_note.graph_relations)
    self.assertIn("反向证据：林追 -> Clues/当前线索.md", canvas_note.graph_relations)
    self.assertIn("未来倒灌：未来真相 -> Clues/当前线索.md", canvas_note.graph_relations)
    self.assertFalse(any("lin-uri-origin" in value for value in canvas_note.graph_relations))
    self.assertFalse(any("future-uri-origin" in value for value in canvas_note.graph_relations))
    self.assertFalse(any("obsidian://" in value for value in canvas_note.external_links))
    self.assertEqual(early_future_hits, [])

    early_note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      chapter_index=1,
      query="林追URI",
    )
    canvas_content = next(item["content"] for item in early_note_contents if item["title"] == "URI关系")
    self.assertIn("Canvas 内部链接节点", canvas_content)
    self.assertIn("[[Characters/林追.md#人物页]]", canvas_content)
    self.assertIn("资料跳转：当前线索 -> Characters/林追.md", canvas_content)
    self.assertIn("反向证据：林追 -> Clues/当前线索.md", canvas_content)
    self.assertIn("未开放设定", canvas_content)
    self.assertNotIn("终局URI", canvas_content)
    self.assertNotIn("Secrets/未来真相", canvas_content)
    self.assertNotIn("future-uri-origin", canvas_content)
    self.assertNotIn("lin-uri-origin", canvas_content)
    self.assertNotIn("obsidian://advanced-uri", canvas_content)
    self.assertNotIn("禁提前：当前线索 -> Secrets/未来真相.md", canvas_content)
    self.assertNotIn("未来倒灌：未来真相 -> Clues/当前线索.md", canvas_content)

  def test_obsidian_markdown_external_links_enter_metadata_without_graph_noise(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-markdown-external-links"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
chapter_range: 1-2
---
# 当前线索

铜钥匙来自旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "旧码头考据.md").write_text(
      """---
status: canonical
chapter_range: 1-2
source_url: https://example.com/tide-ledger
reference_links:
  - "[港口水利档](https://example.com/old-harbor-waterworks)"
  - https://example.com/tide-tax-record?year=1890
references:
  - title: 县志码头条
    url: https://example.com/county-gazetteer
sources:
  - name: 船运档案
    link: https://example.com/shipping-archive
资料来源: https://example.com/local-museum
考据来源:
  - "[旧港灯塔碑](https://example.com/lighthouse-stele)"
related_notes: [[当前线索]]
---
# 旧码头考据

正文内联也可写考据入口。
research_links:: [潮汐税制](https://example.com/tide-tax)
HTML 来源：<a href="https://example.com/html-source">旧港 HTML 档</a>
附件不应进入外部考据字段：[访谈PDF](资料/访谈.pdf)
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      research_hits = search_project_knowledge(
        self.settings,
        project.id,
        "old-harbor-waterworks",
        include_semantic=False,
        chapter_index=1,
      )
      labeled_research_hits = search_project_knowledge(
        self.settings,
        project.id,
        "港口水利档",
        include_semantic=False,
        chapter_index=1,
      )

    research_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "旧码头考据")
    self.assertEqual(detail.story_overview.obsidian.external_link_count, 9)
    self.assertIn("当前线索", research_note.links)
    self.assertEqual(
      research_note.external_links,
      [
        "https://example.com/tide-ledger",
        "https://example.com/old-harbor-waterworks",
        "https://example.com/tide-tax-record?year=1890",
        "https://example.com/county-gazetteer",
        "https://example.com/shipping-archive",
        "https://example.com/local-museum",
        "https://example.com/lighthouse-stele",
        "https://example.com/tide-tax",
        "https://example.com/html-source",
      ],
    )
    self.assertEqual(
      research_note.external_references,
      [
        "来源链接：https://example.com/tide-ledger",
        "港口水利档：https://example.com/old-harbor-waterworks",
        "参考链接：https://example.com/tide-tax-record?year=1890",
        "县志码头条：https://example.com/county-gazetteer",
        "船运档案：https://example.com/shipping-archive",
        "来源链接：https://example.com/local-museum",
        "旧港灯塔碑：https://example.com/lighthouse-stele",
        "潮汐税制：https://example.com/tide-tax",
        "旧港 HTML 档：https://example.com/html-source",
      ],
    )
    self.assertFalse(any(link.startswith("https://") for link in research_note.links))
    self.assertFalse(any("https://example.com" in relation for relation in research_note.graph_relations))
    self.assertIn("关联笔记 -> 当前线索", research_note.graph_relations)
    self.assertTrue(any(item.source == "Obsidian" and "旧码头考据" in item.section for item in research_hits))
    self.assertTrue(any(item.source == "Obsidian" and "旧码头考据" in item.section for item in labeled_research_hits))

    note_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=1,
      query="old-harbor-waterworks",
    )
    self.assertEqual([item["title"] for item in note_contents], ["旧码头考据"])
    self.assertIn("外部链接：", note_contents[0]["content"])
    self.assertIn("外部来源：", note_contents[0]["content"])
    self.assertIn("港口水利档：https://example.com/old-harbor-waterworks", note_contents[0]["content"])
    self.assertIn("https://example.com/old-harbor-waterworks", note_contents[0]["content"])
    self.assertNotIn("资料/访谈.pdf", note_contents[0]["content"])

  def test_obsidian_infers_chapter_scope_from_note_and_canvas_paths(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-path-scope"
    chapter_dir = vault_dir / "Chapters"
    canvas_dir = vault_dir / "Canvases"
    chapter_dir.mkdir(parents=True)
    canvas_dir.mkdir(parents=True)
    (chapter_dir / "第58章-母亲遗言.md").write_text(
      """---
status: canonical
---
# 母亲遗言

母亲遗言改变林追判断，不能提前进入第一章。
""",
      encoding="utf-8",
    )
    (chapter_dir / "第59-60章-潮汐账本.md").write_text(
      """---
status: canonical
---
# 潮汐账本

潮汐账本在第五十九章和第六十章连续推进。
""",
      encoding="utf-8",
    )
    (chapter_dir / "第58～60章-波浪区间.md").write_text(
      """---
status: canonical
---
# 波浪区间

波浪区间计划只在第五十八章到第六十章可用。
""",
      encoding="utf-8",
    )
    (canvas_dir / "chapter-61关系.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {"id": "note", "type": "text", "text": "必须出现：终局背叛"},
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (chapter_dir / "第62章-后续档案.md").write_text(
      """---
status: canonical
reveal_after_chapter: 61
---
# 后续档案

这份章节档案在第六十二章后可以继续给后文使用。
""",
      encoding="utf-8",
    )
    (vault_dir / "标签线索.md").write_text(
      """---
status: canonical
tags: [第58章]
---
# 标签线索

作者只用标签标明第五十八章，正文不再重复维护章节字段。
""",
      encoding="utf-8",
    )
    (vault_dir / "标签区间.md").write_text(
      """---
status: canonical
tags: [Ch59-60]
---
# 标签区间

作者用英文短标签标明第五十九章到第六十章。
""",
      encoding="utf-8",
    )
    (vault_dir / "中文波浪标签.md").write_text(
      """---
status: canonical
tags: [第58～60章]
---
# 中文波浪标签

作者用中文全角波浪线标签标明第五十八章到第六十章。
""",
      encoding="utf-8",
    )
    (vault_dir / "英文波浪标签.md").write_text(
      """---
status: canonical
tags: [Ch58～60]
---
# 英文波浪标签

作者用英文短标签和全角波浪线标明第五十八章到第六十章。
""",
      encoding="utf-8",
    )
    (vault_dir / "标签剧透.md").write_text(
      """---
status: canonical
tags: [第61章后可用]
---
# 标签剧透

这条真相只允许第六十一章之后使用。
""",
      encoding="utf-8",
    )
    (vault_dir / "空格标签.md").write_text(
      """---
status: canonical
tags: "#人物 #第58章 #剧透/57"
---
# 空格标签

这篇笔记用 Obsidian 常见的空格分隔标签标明第五十八章。
""",
      encoding="utf-8",
    )
    (vault_dir / "正文属性标签.md").write_text(
      """---
status: canonical
---
# 正文属性标签

tags:: #支线 #第59章

这篇笔记用正文属性里的空格分隔标签标明第五十九章。
""",
      encoding="utf-8",
    )
    (vault_dir / "开放标签.md").write_text(
      """---
status: canonical
tags: [第58章起]
---
# 开放标签

开放标签资料从第五十八章起可用，后续章节仍可引用。
""",
      encoding="utf-8",
    )
    (vault_dir / "英文开放标签.md").write_text(
      """---
status: canonical
tags: [Ch58+]
---
# 英文开放标签

英文开放标签资料从第五十八章起可用。
""",
      encoding="utf-8",
    )
    (vault_dir / "层级计划标签.md").write_text(
      """---
status: canonical
tags: [章节计划/62]
---
# 层级计划标签

层级计划标签资料只在第六十二章可用。
""",
      encoding="utf-8",
    )
    (vault_dir / "层级合同标签.md").write_text(
      """---
status: canonical
tags: [章节合同/63-64]
---
# 层级合同标签

层级合同标签资料只在第六十三章到第六十四章可用。
""",
      encoding="utf-8",
    )
    (vault_dir / "英文场景计划标签.md").write_text(
      """---
status: canonical
tags: [scene-plan/65]
---
# 英文场景计划标签

英文场景计划标签资料只在第六十五章可用。
""",
      encoding="utf-8",
    )
    (vault_dir / "开放属性.md").write_text(
      """---
status: canonical
chapter_range: 58+
---
# 开放属性

开放属性资料从第五十八章起可用。
""",
      encoding="utf-8",
    )
    (vault_dir / "正文开放属性.md").write_text(
      """---
status: canonical
---
# 正文开放属性

chapter_range:: 第59章以后

正文开放属性资料从第五十九章起可用。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "母亲遗言",
        include_semantic=False,
        chapter_index=1,
      )
      chapter_58_hits = search_project_knowledge(
        self.settings,
        project.id,
        "母亲遗言",
        include_semantic=False,
        chapter_index=58,
      )
      tag_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "标签线索",
        include_semantic=False,
        chapter_index=57,
      )
      tag_chapter_58_hits = search_project_knowledge(
        self.settings,
        project.id,
        "标签线索",
        include_semantic=False,
        chapter_index=58,
      )
      wave_path_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "波浪区间计划",
        include_semantic=False,
        chapter_index=57,
      )
      wave_path_mid_hits = search_project_knowledge(
        self.settings,
        project.id,
        "波浪区间计划",
        include_semantic=False,
        chapter_index=59,
      )
      wave_path_late_hits = search_project_knowledge(
        self.settings,
        project.id,
        "波浪区间计划",
        include_semantic=False,
        chapter_index=61,
      )
      wave_tag_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "中文波浪标签",
        include_semantic=False,
        chapter_index=57,
      )
      wave_tag_mid_hits = search_project_knowledge(
        self.settings,
        project.id,
        "中文波浪标签",
        include_semantic=False,
        chapter_index=59,
      )
      english_wave_tag_mid_hits = search_project_knowledge(
        self.settings,
        project.id,
        "英文波浪标签",
        include_semantic=False,
        chapter_index=59,
      )
      space_tag_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "空格标签",
        include_semantic=False,
        chapter_index=57,
      )
      space_tag_chapter_58_hits = search_project_knowledge(
        self.settings,
        project.id,
        "空格标签",
        include_semantic=False,
        chapter_index=58,
      )
      inline_space_tag_chapter_58_hits = search_project_knowledge(
        self.settings,
        project.id,
        "正文属性标签",
        include_semantic=False,
        chapter_index=58,
      )
      inline_space_tag_chapter_59_hits = search_project_knowledge(
        self.settings,
        project.id,
        "正文属性标签",
        include_semantic=False,
        chapter_index=59,
      )
      tag_reveal_blocked_hits = search_project_knowledge(
        self.settings,
        project.id,
        "标签剧透",
        include_semantic=False,
        chapter_index=61,
      )
      tag_reveal_open_hits = search_project_knowledge(
        self.settings,
        project.id,
        "标签剧透",
        include_semantic=False,
        chapter_index=62,
      )
      open_tag_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "开放标签资料",
        include_semantic=False,
        chapter_index=57,
      )
      open_tag_late_hits = search_project_knowledge(
        self.settings,
        project.id,
        "开放标签资料",
        include_semantic=False,
        chapter_index=80,
      )
      open_english_late_hits = search_project_knowledge(
        self.settings,
        project.id,
        "英文开放标签资料",
        include_semantic=False,
        chapter_index=80,
      )
      layered_plan_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "层级计划标签资料",
        include_semantic=False,
        chapter_index=61,
      )
      layered_plan_hits = search_project_knowledge(
        self.settings,
        project.id,
        "层级计划标签资料",
        include_semantic=False,
        chapter_index=62,
      )
      layered_contract_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "层级合同标签资料",
        include_semantic=False,
        chapter_index=62,
      )
      layered_contract_hits = search_project_knowledge(
        self.settings,
        project.id,
        "层级合同标签资料",
        include_semantic=False,
        chapter_index=64,
      )
      english_scene_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "英文场景计划标签资料",
        include_semantic=False,
        chapter_index=64,
      )
      english_scene_hits = search_project_knowledge(
        self.settings,
        project.id,
        "英文场景计划标签资料",
        include_semantic=False,
        chapter_index=65,
      )
      open_property_early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "开放属性资料",
        include_semantic=False,
        chapter_index=57,
      )
      open_property_late_hits = search_project_knowledge(
        self.settings,
        project.id,
        "开放属性资料",
        include_semantic=False,
        chapter_index=80,
      )
      open_body_blocked_hits = search_project_knowledge(
        self.settings,
        project.id,
        "正文开放属性资料",
        include_semantic=False,
        chapter_index=58,
      )
      open_body_late_hits = search_project_knowledge(
        self.settings,
        project.id,
        "正文开放属性资料",
        include_semantic=False,
        chapter_index=80,
      )

    legacy_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "母亲遗言")
    range_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "潮汐账本")
    canvas_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "chapter-61关系")
    archive_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "后续档案")
    tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "标签线索")
    tag_range_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "标签区间")
    wave_path_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "波浪区间")
    wave_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "中文波浪标签")
    english_wave_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "英文波浪标签")
    tag_reveal_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "标签剧透")
    space_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "空格标签")
    inline_space_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "正文属性标签")
    open_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "开放标签")
    open_english_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "英文开放标签")
    layered_plan_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "层级计划标签")
    layered_contract_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "层级合同标签")
    english_scene_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "英文场景计划标签")
    open_property_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "开放属性")
    open_body_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "正文开放属性")
    self.assertEqual((legacy_note.chapter_start, legacy_note.chapter_end), (58, 58))
    self.assertEqual((range_note.chapter_start, range_note.chapter_end), (59, 60))
    self.assertEqual((canvas_note.chapter_start, canvas_note.chapter_end), (61, 61))
    self.assertEqual((archive_note.chapter_start, archive_note.chapter_end, archive_note.reveal_after_chapter), (0, 0, 61))
    self.assertEqual((tag_note.chapter_start, tag_note.chapter_end), (58, 58))
    self.assertEqual((tag_range_note.chapter_start, tag_range_note.chapter_end), (59, 60))
    self.assertEqual((wave_path_note.chapter_start, wave_path_note.chapter_end), (58, 60))
    self.assertEqual((wave_tag_note.chapter_start, wave_tag_note.chapter_end), (58, 60))
    self.assertEqual((english_wave_tag_note.chapter_start, english_wave_tag_note.chapter_end), (58, 60))
    self.assertEqual((tag_reveal_note.chapter_start, tag_reveal_note.chapter_end, tag_reveal_note.reveal_after_chapter), (0, 0, 61))
    self.assertEqual((space_tag_note.chapter_start, space_tag_note.chapter_end, space_tag_note.reveal_after_chapter), (58, 58, 57))
    self.assertEqual((inline_space_tag_note.chapter_start, inline_space_tag_note.chapter_end), (59, 59))
    self.assertEqual((open_tag_note.chapter_start, open_tag_note.chapter_end), (58, 0))
    self.assertEqual((open_english_note.chapter_start, open_english_note.chapter_end), (58, 0))
    self.assertEqual((layered_plan_note.chapter_start, layered_plan_note.chapter_end), (62, 62))
    self.assertEqual((layered_contract_note.chapter_start, layered_contract_note.chapter_end), (63, 64))
    self.assertEqual((english_scene_note.chapter_start, english_scene_note.chapter_end), (65, 65))
    self.assertEqual(layered_plan_note.note_type, "chapter_plan")
    self.assertEqual(layered_contract_note.note_type, "chapter_contract")
    self.assertEqual(english_scene_note.note_type, "chapter_plan")
    self.assertEqual((open_property_note.chapter_start, open_property_note.chapter_end), (58, 0))
    self.assertEqual((open_body_note.chapter_start, open_body_note.chapter_end), (59, 0))
    self.assertIn("人物", space_tag_note.tags)
    self.assertIn("第58章", space_tag_note.tags)
    self.assertIn("剧透/57", space_tag_note.tags)
    self.assertIn("支线", inline_space_tag_note.tags)
    self.assertIn("第59章", inline_space_tag_note.tags)
    self.assertIn("第58～60章", wave_tag_note.tags)
    self.assertIn("Ch58～60", english_wave_tag_note.tags)
    self.assertIn("第58章起", open_tag_note.tags)
    self.assertIn("Ch58+", open_english_note.tags)
    self.assertEqual(early_hits, [])
    self.assertEqual(tag_early_hits, [])
    self.assertEqual(wave_path_early_hits, [])
    self.assertEqual(wave_path_late_hits, [])
    self.assertEqual(wave_tag_early_hits, [])
    self.assertEqual(space_tag_early_hits, [])
    self.assertFalse(any(item.source == "Obsidian" and "正文属性标签" in item.section for item in inline_space_tag_chapter_58_hits))
    self.assertFalse(any(item.source == "Obsidian" and "标签剧透" in item.section for item in tag_reveal_blocked_hits))
    self.assertEqual(open_tag_early_hits, [])
    self.assertEqual(open_property_early_hits, [])
    self.assertFalse(any(item.source == "Obsidian" and "正文开放属性" in item.section for item in open_body_blocked_hits))
    self.assertFalse(any(item.source == "Obsidian" and "层级计划标签" in item.section for item in layered_plan_early_hits))
    self.assertFalse(any(item.source == "Obsidian" and "层级合同标签" in item.section for item in layered_contract_early_hits))
    self.assertFalse(any(item.source == "Obsidian" and "英文场景计划标签" in item.section for item in english_scene_early_hits))
    self.assertTrue(any(item.source == "Obsidian" and "母亲遗言" in item.section for item in chapter_58_hits))
    self.assertTrue(any(item.source == "Obsidian" and "标签线索" in item.section for item in tag_chapter_58_hits))
    self.assertTrue(any(item.source == "Obsidian" and "波浪区间" in item.section for item in wave_path_mid_hits))
    self.assertTrue(any(item.source == "Obsidian" and "中文波浪标签" in item.section for item in wave_tag_mid_hits))
    self.assertTrue(any(item.source == "Obsidian" and "英文波浪标签" in item.section for item in english_wave_tag_mid_hits))
    self.assertTrue(any(item.source == "Obsidian" and "空格标签" in item.section for item in space_tag_chapter_58_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正文属性标签" in item.section for item in inline_space_tag_chapter_59_hits))
    self.assertTrue(any(item.source == "Obsidian" and "标签剧透" in item.section for item in tag_reveal_open_hits))
    self.assertTrue(any(item.source == "Obsidian" and "开放标签" in item.section for item in open_tag_late_hits))
    self.assertTrue(any(item.source == "Obsidian" and "英文开放标签" in item.section for item in open_english_late_hits))
    self.assertTrue(any(item.source == "Obsidian" and "层级计划标签" in item.section for item in layered_plan_hits))
    self.assertTrue(any(item.source == "Obsidian" and "层级合同标签" in item.section for item in layered_contract_hits))
    self.assertTrue(any(item.source == "Obsidian" and "英文场景计划标签" in item.section for item in english_scene_hits))
    self.assertTrue(any(item.source == "Obsidian" and "开放属性" in item.section for item in open_property_late_hits))
    self.assertTrue(any(item.source == "Obsidian" and "正文开放属性" in item.section for item in open_body_late_hits))

    chapter_58_contents = load_project_obsidian_note_contents(
      self.settings,
      project.id,
      limit=1,
      chapter_index=58,
      query="母亲遗言",
    )
    self.assertEqual([item["title"] for item in chapter_58_contents], ["母亲遗言"])
    self.assertIn("适用章节：第 58 章", chapter_58_contents[0]["content"])

  def test_obsidian_reveal_after_notes_rank_for_unlocked_chapters(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-reveal-ranking"
    chapter_dir = vault_dir / "ChapterNotes"
    chapter_dir.mkdir(parents=True)
    (vault_dir / "AAA全局资料.md").write_text(
      """---
status: canonical
---
# AAA全局资料

这是一份全书通用资料。
""",
      encoding="utf-8",
    )
    (chapter_dir / "第057章-潮汐档案.md").write_text(
      """---
status: canonical
type: chapter_note
source_chapters:
  - 57
reveal_after_chapter: 57
---
# 第 057 章 潮汐档案

第五十七章确认潮汐账本已经被调包，下一章需要承接这个事实。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    archive_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "第 057 章 潮汐档案")
    self.assertEqual((archive_note.chapter_start, archive_note.chapter_end, archive_note.reveal_after_chapter), (0, 0, 57))
    early_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "完全无关查询",
      limit=2,
      chapter_index=57,
    )
    unlocked_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "完全无关查询",
      limit=1,
      chapter_index=58,
    )
    later_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "完全无关查询",
      limit=1,
      chapter_index=80,
    )

    self.assertNotIn("第 057 章 潮汐档案", [item.title for item in early_notes])
    self.assertEqual([item.title for item in unlocked_notes], ["第 057 章 潮汐档案"])
    self.assertEqual([item.title for item in later_notes], ["第 057 章 潮汐档案"])

  def test_obsidian_chapter_source_ids_infer_open_ended_chapter_scope(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-source-id-scope"
    archive_dir = vault_dir / "Archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "作者整理的银潮灯回顾.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 作者改写后的章节档案
source_ids:
  - chapter-058
---
# 作者整理的银潮灯回顾

银潮灯回顾记录林追和宋闻在旧码头重新判断旧船队记录。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "银潮灯回顾",
        include_semantic=False,
        chapter_index=10,
      )
      later_hits = search_project_knowledge(
        self.settings,
        project.id,
        "银潮灯回顾",
        include_semantic=False,
        chapter_index=60,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "作者整理的银潮灯回顾")
    self.assertEqual(note.source_ids, ["chapter-058"])
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (58, 0, 0))
    self.assertFalse(any(item.source == "Obsidian" and "银潮灯回顾" in item.section for item in early_hits))
    self.assertTrue(any(item.source == "Obsidian" and "银潮灯回顾" in item.section for item in later_hits))

  def test_obsidian_chapter_source_ids_override_single_chapter_filename_scope(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-source-id-filename-scope"
    archive_dir = vault_dir / "Archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "第058章-银潮灯回顾.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 第 58 章后续仍要读取的章节档案
source_ids:
  - chapter-058
---
# 第058章-银潮灯回顾

银潮灯回顾记录宋闻隐瞒旧船队账册。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      chapter_59_hits = search_project_knowledge(
        self.settings,
        project.id,
        "旧船队账册",
        include_semantic=False,
        chapter_index=59,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "第058章-银潮灯回顾")
    self.assertEqual(note.source_ids, ["chapter-058"])
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (58, 0, 0))
    self.assertTrue(any(item.source == "Obsidian" and "第058章-银潮灯回顾" in item.section for item in chapter_59_hits))

  def test_obsidian_chapter_note_properties_feed_context_body(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-properties"
    archive_dir = vault_dir / "Archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "银潮灯回顾.md").write_text(
      """---
status: canonical
type: chapter_note
source_ids:
  - chapter-058
chapter_title: 银潮灯回顾
chapter_summary: 林追在银潮灯前确认宋闻隐瞒旧船队账本。
chapter_events:
  - 宋闻交出半页潮汐账本。
state_changes:
  - 林追不再把宋闻当作单纯同盟。
handoff_to_next:
  - 第59章必须追问账本缺页。
chapter_excerpt:
  - 银潮灯照出两人的判断差异。
---
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_hits = search_project_knowledge(
        self.settings,
        project.id,
        "账本缺页",
        include_semantic=False,
        chapter_index=10,
      )
      later_hits = search_project_knowledge(
        self.settings,
        project.id,
        "账本缺页",
        include_semantic=False,
        chapter_index=59,
      )
      contents = load_project_obsidian_note_contents(
        self.settings,
        project.id,
        limit=1,
        chapter_index=59,
        query="账本缺页",
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "银潮灯回顾")
    self.assertEqual(note.source_ids, ["chapter-058"])
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (58, 0, 0))
    self.assertFalse(any(item.source == "Obsidian" and "账本缺页" in item.preview for item in early_hits))
    self.assertTrue(any(item.source == "Obsidian" and "账本缺页" in item.preview for item in later_hits))
    self.assertEqual([item["title"] for item in contents], ["银潮灯回顾"])
    self.assertIn("章节摘要：林追在银潮灯前确认宋闻隐瞒旧船队账本", contents[0]["content"])
    self.assertIn("关键事件：宋闻交出半页潮汐账本", contents[0]["content"])
    self.assertIn("章节交接：第59章必须追问账本缺页", contents[0]["content"])
    self.assertIn("正文摘录：银潮灯照出两人的判断差异", contents[0]["content"])

  def test_obsidian_multi_chapter_source_ids_use_latest_chapter_scope(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-multi-source-id-scope"
    archive_dir = vault_dir / "Archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "第058章-双章合并档案.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 第 58 章和第 60 章合并整理后的档案
source_ids:
  - chapter-058
  - chapter-060
---
# 双章合并档案

银潮灯在第 60 章才确认和旧船队账册同源。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      chapter_59_hits = search_project_knowledge(
        self.settings,
        project.id,
        "双章合并档案",
        include_semantic=False,
        chapter_index=59,
      )
      chapter_58_hits = search_project_knowledge(
        self.settings,
        project.id,
        "双章合并档案",
        include_semantic=False,
        chapter_index=58,
      )
      chapter_60_hits = search_project_knowledge(
        self.settings,
        project.id,
        "双章合并档案",
        include_semantic=False,
        chapter_index=60,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "双章合并档案")
    self.assertEqual(note.source_ids, ["chapter-058", "chapter-060"])
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (60, 0, 0))
    self.assertFalse(any(item.source == "Obsidian" and "双章合并档案" in item.section for item in chapter_58_hits))
    self.assertFalse(any(item.source == "Obsidian" and "双章合并档案" in item.section for item in chapter_59_hits))
    self.assertTrue(any(item.source == "Obsidian" and "双章合并档案" in item.section for item in chapter_60_hits))

  def test_obsidian_source_id_aliases_infer_latest_chapter_scope(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-source-id-alias-scope"
    archive_dir = vault_dir / "Archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "缩写来源档案.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 作者用缩写来源 ID 整理的章节档案
source_ids:
  - ch058
  - Chap 060
  - archive-ch061
---
# 缩写来源档案

缩写来源档案记录旧船队账册到第 60 章才公开的证据。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      chapter_59_hits = search_project_knowledge(
        self.settings,
        project.id,
        "缩写来源档案",
        include_semantic=False,
        chapter_index=59,
      )
      chapter_60_hits = search_project_knowledge(
        self.settings,
        project.id,
        "缩写来源档案",
        include_semantic=False,
        chapter_index=60,
      )

    note = next(item for item in detail.story_overview.obsidian.notes if item.title == "缩写来源档案")
    self.assertEqual(note.source_ids, ["ch058", "Chap 060", "archive-ch061"])
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (60, 0, 0))
    self.assertFalse(any(item.source == "Obsidian" and "缩写来源档案" in item.section for item in chapter_59_hits))
    self.assertTrue(any(item.source == "Obsidian" and "缩写来源档案" in item.section for item in chapter_60_hits))

  def test_obsidian_source_chapters_infer_scope_without_reveal_field(self) -> None:
    project = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-source-chapters-scope"
    archive_dir = vault_dir / "Archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "作者整理的双章来源.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 作者保留 source_chapters 但删除剧透字段
source_chapters: [58, 60]
---
# 作者整理的双章来源

银潮灯在第 60 章才确认和旧船队账册同源。
""",
      encoding="utf-8",
    )
    (archive_dir / "作者只保留正文来源章节.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 作者只在正文保留来源章节
---
# 作者只保留正文来源章节

来源章节：第 58 章、第 60 章
旧船队账册的最终来源到第 60 章才公开。
""",
      encoding="utf-8",
    )
    (archive_dir / "作者使用中文来源别名.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 作者用中文来源章节别名维护档案
章节来源:
  - 第58章
  - 第60章
---
# 作者使用中文来源别名

中文来源别名档案记录黑盐仓库到第 60 章才公开。
""",
      encoding="utf-8",
    )
    (archive_dir / "作者正文使用来源章.md").write_text(
      """---
status: canonical
type: chapter_note
summary: 作者只在正文保留来源章
---
# 作者正文使用来源章

来源章：第 58 章、第 60 章
黑盐仓库的最终来源到第 60 章才公开。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        project.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      chapter_59_hits = search_project_knowledge(
        self.settings,
        project.id,
        "旧船队账册",
        include_semantic=False,
        chapter_index=59,
      )
      chapter_60_hits = search_project_knowledge(
        self.settings,
        project.id,
        "旧船队账册",
        include_semantic=False,
        chapter_index=60,
      )
      chapter_59_alias_hits = search_project_knowledge(
        self.settings,
        project.id,
        "黑盐仓库",
        include_semantic=False,
        chapter_index=59,
      )
      chapter_60_alias_hits = search_project_knowledge(
        self.settings,
        project.id,
        "黑盐仓库",
        include_semantic=False,
        chapter_index=60,
      )

    frontmatter_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "作者整理的双章来源")
    body_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "作者只保留正文来源章节")
    alias_frontmatter_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "作者使用中文来源别名")
    alias_body_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "作者正文使用来源章")
    self.assertEqual(frontmatter_note.source_chapters, [58, 60])
    self.assertEqual(body_note.source_chapters, [58, 60])
    self.assertEqual(alias_frontmatter_note.source_chapters, [58, 60])
    self.assertEqual(alias_body_note.source_chapters, [58, 60])
    self.assertEqual((frontmatter_note.chapter_start, frontmatter_note.chapter_end, frontmatter_note.reveal_after_chapter), (60, 0, 0))
    self.assertEqual((body_note.chapter_start, body_note.chapter_end, body_note.reveal_after_chapter), (60, 0, 0))
    self.assertEqual((alias_frontmatter_note.chapter_start, alias_frontmatter_note.chapter_end, alias_frontmatter_note.reveal_after_chapter), (60, 0, 0))
    self.assertEqual((alias_body_note.chapter_start, alias_body_note.chapter_end, alias_body_note.reveal_after_chapter), (60, 0, 0))
    self.assertFalse(any(item.source == "Obsidian" and "旧船队账册" in item.preview for item in chapter_59_hits))
    self.assertTrue(any(item.source == "Obsidian" and "旧船队账册" in item.preview for item in chapter_60_hits))
    self.assertFalse(any(item.source == "Obsidian" and "黑盐仓库" in item.preview for item in chapter_59_alias_hits))
    self.assertTrue(any(item.source == "Obsidian" and "黑盐仓库" in item.preview for item in chapter_60_alias_hits))

  def test_obsidian_extracts_constraints_from_note_body(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    (vault_dir / "林追.md").write_text(
      """---
type: character
status: canonical
---
# 林追

必须出现：铜钥匙、灯塔暗号
- 禁止出现：林追主动交出铜钥匙；港务会公开认罪

## 必须包含

- 夜潮账册

## 禁止出现

- 旧船队主动返港
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      hits = search_project_knowledge(self.settings, summary.id, "夜潮账册", include_semantic=False)

    note = detail.story_overview.obsidian.notes[0]
    self.assertEqual(note.title, "林追")
    self.assertIn("铜钥匙", note.required_phrases)
    self.assertIn("灯塔暗号", note.required_phrases)
    self.assertIn("夜潮账册", note.required_phrases)
    self.assertIn("林追主动交出铜钥匙", note.forbidden_phrases)
    self.assertIn("港务会公开认罪", note.forbidden_phrases)
    self.assertIn("旧船队主动返港", note.forbidden_phrases)
    self.assertTrue(any("必须包含：铜钥匙" in item.preview for item in hits))
    self.assertTrue(any("禁止出现：林追主动交出铜钥匙" in item.preview for item in hits))

  def test_obsidian_frontmatter_keys_accept_common_property_name_variants(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    (vault_dir / "潮师.md").write_text(
      """---
Title: 潮师
Type: character
Status: Canonical
Aliases:
  - 夜潮师
Tags:
  - 人物
Usable By AI: true
Chapter-Range: 58-60
Reveal After Chapter: 57
Required Phrases:
  - 夜潮账册
Forbidden-Phrases:
  - 提前公开沉船真相
---
# 潮师

潮师只在中段揭示，掌握旧船队沉船真相。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")), patch(
      "novel_backend.services.project_service.rerank_documents",
      return_value=[],
    ):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          require_usable_by_ai=True,
        ),
      )
      early_evidence = search_project_knowledge_evidence(
        self.settings,
        summary.id,
        "夜潮账册",
        chapter_index=57,
      )
      active_evidence = search_project_knowledge_evidence(
        self.settings,
        summary.id,
        "夜潮账册",
        chapter_index=58,
      )

    obsidian = detail.story_overview.obsidian
    self.assertEqual(obsidian.included_count, 1)
    note = obsidian.notes[0]
    self.assertEqual(note.title, "潮师")
    self.assertEqual(note.note_type, "character")
    self.assertEqual(note.status, "Canonical")
    self.assertIn("夜潮师", note.aliases)
    self.assertIn("人物", note.tags)
    self.assertIn("夜潮账册", note.required_phrases)
    self.assertIn("提前公开沉船真相", note.forbidden_phrases)
    self.assertEqual(note.chapter_start, 58)
    self.assertEqual(note.chapter_end, 60)
    self.assertEqual(note.reveal_after_chapter, 57)
    self.assertFalse(any(str(item.get("source_key", "")).endswith("潮师.md") for item in early_evidence))
    self.assertTrue(any(str(item.get("source_key", "")).endswith("潮师.md") for item in active_evidence))

  def test_obsidian_infers_note_type_from_common_folders_when_type_is_missing(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-folder-types"
    for folder in ("Characters", "Locations", "Plans", "ChapterContracts", "Debts", "CharacterArcs", "Style", "XP"):
      (vault_dir / folder).mkdir(parents=True)
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 林追

林追正在追查旧码头。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "灯塔议会.md").write_text(
      """---
type: organization
status: canonical
usable_by_ai: true
---
# 灯塔议会

灯塔议会掌握靠港记录。
""",
      encoding="utf-8",
    )
    (vault_dir / "Locations" / "旧码头.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 旧码头

旧码头夜里有潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第058章计划.md").write_text(
      """---
status: canonical
usable_by_ai: true
chapter_range: 58
objective: 让林追确认潮声异常
required_beats:
  - 林追回到旧码头
acceptance_checks:
  - 章节末尾保留下一章追问
---
# 第058章计划
""",
      encoding="utf-8",
    )
    (vault_dir / "ChapterContracts" / "第058章合同.md").write_text(
      """---
status: canonical
usable_by_ai: true
chapter_range: 58
objective: 让林追把旧码头压力带入下一章
---
# 第058章合同
""",
      encoding="utf-8",
    )
    (vault_dir / "Debts" / "沉船伏笔.md").write_text(
      """---
status: canonical
usable_by_ai: true
chapter_range: 58+
debt_content: 潮声异常必须后续兑现
next_required_action: 第五十八章只推进，不解释
---
# 沉船伏笔
""",
      encoding="utf-8",
    )
    (vault_dir / "CharacterArcs" / "林追状态.md").write_text(
      """---
status: canonical
usable_by_ai: true
chapter_range: 58+
character: 林追
current_state: 怀疑潮声来自旧账本
required_next_check: 后续检查林追是否过早公开真相
---
# 林追状态
""",
      encoding="utf-8",
    )
    (vault_dir / "Style" / "短句规则.md").write_text(
      """---
status: canonical
usable_by_ai: true
style_rule: 压低解释性总结
---
# 短句规则
""",
      encoding="utf-8",
    )
    (vault_dir / "XP" / "生成检查.md").write_text(
      """---
status: canonical
usable_by_ai: true
xp_rule: 生成后检查伏笔是否过早解释
---
# 生成检查
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          require_usable_by_ai=True,
        ),
      )

    notes = {item.relative_path: item for item in detail.story_overview.obsidian.notes}
    self.assertEqual(notes["Characters/林追.md"].note_type, "character")
    self.assertEqual(notes["Characters/灯塔议会.md"].note_type, "organization")
    self.assertEqual(notes["Locations/旧码头.md"].note_type, "location")
    self.assertEqual(notes["Plans/第058章计划.md"].note_type, "chapter_plan")
    self.assertEqual(notes["ChapterContracts/第058章合同.md"].note_type, "chapter_contract")
    self.assertEqual(notes["Debts/沉船伏笔.md"].note_type, "plot_debt")
    self.assertEqual(notes["CharacterArcs/林追状态.md"].note_type, "character_arc")
    self.assertEqual(notes["Style/短句规则.md"].note_type, "style_rule")
    self.assertEqual(notes["XP/生成检查.md"].note_type, "xp_rule")
    self.assertIn("章节目标：让林追确认潮声异常", notes["Plans/第058章计划.md"].preview)
    self.assertIn("章节目标：让林追把旧码头压力带入下一章", notes["ChapterContracts/第058章合同.md"].preview)
    self.assertIn("债务内容：潮声异常必须后续兑现", notes["Debts/沉船伏笔.md"].preview)
    self.assertIn("当前状态：怀疑潮声来自旧账本", notes["CharacterArcs/林追状态.md"].preview)

  def test_obsidian_infers_note_type_from_nested_tags_without_title_guessing(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-nested-tag-types"
    vault_dir.mkdir(parents=True)
    (vault_dir / "林追标签.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags: [人物/主角]
---
# 林追标签
""",
      encoding="utf-8",
    )
    (vault_dir / "正文全角人物标签.md").write_text(
      """---
status: canonical
usable_by_ai: true
---
# 正文全角人物标签

这篇人物笔记只在正文写全角分层标签。 #人物／主角
""",
      encoding="utf-8",
    )
    (vault_dir / "多行井号人物标签.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags:
  - #人物/配角
  - #第58章
---
# 多行井号人物标签
""",
      encoding="utf-8",
    )
    (vault_dir / "第058章标签计划.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags: [章节计划/58]
chapter_range: 58
objective: 让潮声异常变成行动压力
---
# 第058章标签计划
""",
      encoding="utf-8",
    )
    (vault_dir / "沉船标签债务.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags: [剧情债务/伏笔]
debt_content: 沉船账册必须后续兑现
---
# 沉船标签债务
""",
      encoding="utf-8",
    )
    (vault_dir / "误判保护.md").write_text(
      """---
status: canonical
usable_by_ai: true
tags: [非人物/主题]
---
# 误判保护
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          require_usable_by_ai=True,
        ),
      )

    notes = {item.relative_path: item for item in detail.story_overview.obsidian.notes}
    self.assertEqual(notes["林追标签.md"].note_type, "character")
    self.assertEqual(notes["正文全角人物标签.md"].note_type, "character")
    self.assertEqual(notes["多行井号人物标签.md"].note_type, "character")
    self.assertEqual(notes["多行井号人物标签.md"].chapter_start, 58)
    self.assertEqual(notes["多行井号人物标签.md"].chapter_end, 58)
    self.assertIn("人物/配角", notes["多行井号人物标签.md"].tags)
    self.assertIn("第58章", notes["多行井号人物标签.md"].tags)
    self.assertEqual(notes["第058章标签计划.md"].note_type, "chapter_plan")
    self.assertEqual(notes["沉船标签债务.md"].note_type, "plot_debt")
    self.assertEqual(notes["误判保护.md"].note_type, "")
    self.assertIn("章节目标：让潮声异常变成行动压力", notes["第058章标签计划.md"].preview)
    self.assertIn("债务内容：沉船账册必须后续兑现", notes["沉船标签债务.md"].preview)

  def test_obsidian_scans_explicit_type_multiselect_before_folder_fallback(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-type-multiselect"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "多选类型人物.md").write_text(
      """---
status: canonical
usable_by_ai: true
type: [主角, 人物]
---
# 多选类型人物
""",
      encoding="utf-8",
    )
    (vault_dir / "多选类型计划.md").write_text(
      """---
status: canonical
usable_by_ai: true
type: [临时, 章节计划]
chapter_range: 58
objective: 让林追把账册线索转成行动
---
# 多选类型计划
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "自定义类型.md").write_text(
      """---
status: canonical
usable_by_ai: true
type: [自定义分类]
---
# 自定义类型
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          require_usable_by_ai=True,
        ),
      )

    notes = {item.relative_path: item for item in detail.story_overview.obsidian.notes}
    self.assertEqual(notes["多选类型人物.md"].note_type, "character")
    self.assertEqual(notes["多选类型计划.md"].note_type, "chapter_plan")
    self.assertEqual(notes["Characters/自定义类型.md"].note_type, "自定义分类")
    self.assertIn("章节目标：让林追把账册线索转成行动", notes["多选类型计划.md"].preview)

  def test_obsidian_frontmatter_flow_lists_keep_quoted_commas_and_wiki_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-flow-lists"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "逗号属性.md").write_text(
      """---
status: canonical
aliases: ["潮师, 守账人", "夜潮师"]
keywords: ["旧船队, 暗账", "潮声异常"]
source_notes: ["[[当前线索]]", "未建笔记, 占位"]
required_phrases: ["潮声异常, 不得提前解释", "铜钥匙"]
forbidden_phrases: ["提前公开沉船真相, 港务会认罪"]
---
# 逗号属性

这篇笔记用带逗号的 Obsidian Properties。
""",
      encoding="utf-8",
    )
    (vault_dir / "分号属性.md").write_text(
      """---
status: canonical
aliases: 潮师；守账人
keywords: 旧船队；暗账
source_notes: 当前线索；未建笔记
required_phrases: 潮声异常；不得提前解释
forbidden_phrases: 提前公开沉船真相; 港务会认罪
tags: "人物；第58章"
---
# 分号属性

这篇笔记用分号分隔 Obsidian Properties。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    note = next(item for item in obsidian.notes if item.title == "逗号属性")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    self.assertIn("潮师, 守账人", note.aliases)
    self.assertIn("夜潮师", note.aliases)
    self.assertNotIn("潮师", note.aliases)
    self.assertIn("旧船队, 暗账", note.keywords)
    self.assertIn("潮声异常", note.keywords)
    self.assertIn("潮声异常, 不得提前解释", note.required_phrases)
    self.assertIn("铜钥匙", note.required_phrases)
    self.assertNotIn("不得提前解释", note.required_phrases)
    self.assertIn("提前公开沉船真相, 港务会认罪", note.forbidden_phrases)
    self.assertIn("当前线索", note.links)
    self.assertIn("未建笔记, 占位", note.links)
    self.assertIn("当前线索.md", note.resolved_links)
    self.assertIn("未建笔记, 占位", note.unresolved_links)
    self.assertIn("逗号属性.md", current_note.backlinks)

    semicolon_note = next(item for item in obsidian.notes if item.title == "分号属性")
    self.assertIn("潮师", semicolon_note.aliases)
    self.assertIn("守账人", semicolon_note.aliases)
    self.assertNotIn("潮师；守账人", semicolon_note.aliases)
    self.assertIn("旧船队", semicolon_note.keywords)
    self.assertIn("暗账", semicolon_note.keywords)
    self.assertIn("潮声异常", semicolon_note.required_phrases)
    self.assertIn("不得提前解释", semicolon_note.required_phrases)
    self.assertIn("提前公开沉船真相", semicolon_note.forbidden_phrases)
    self.assertIn("港务会认罪", semicolon_note.forbidden_phrases)
    self.assertIn("当前线索", semicolon_note.links)
    self.assertIn("未建笔记", semicolon_note.links)
    self.assertIn("当前线索.md", semicolon_note.resolved_links)
    self.assertIn("未建笔记", semicolon_note.unresolved_links)
    self.assertIn("人物", semicolon_note.tags)
    self.assertIn("第58章", semicolon_note.tags)
    self.assertEqual((semicolon_note.chapter_start, semicolon_note.chapter_end), (58, 58))
    self.assertIn("分号属性.md", current_note.backlinks)

  def test_obsidian_frontmatter_block_scalars_feed_summary_terms_and_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-block-scalars"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

后段真相不能提前进入第五十八章。
""",
      encoding="utf-8",
    )
    (vault_dir / "多行属性.md").write_text(
      """---
status: canonical
summary: >
  第五十八章只公开[[当前线索]]。
  [[未来真相]]仍保持未开放。
keywords: |
  潮声异常
  夜潮账册
source_notes: |
  [[当前线索]]
  [[未来真相]]
required_phrases: |
  潮声异常
  铜钥匙
---
# 多行属性

正文只记录当前章节可写内容。
""",
      encoding="utf-8",
    )
    (vault_dir / "缩进标记属性.md").write_text(
      """---
status: canonical
summary: >2-
    第五十八章只公开[[当前线索]]。
keywords: |2-
    潮声异常
    夜潮账册
source_notes: |2-
    [[当前线索]]
required_phrases: >2-
    潮声异常 不得提前解释
---
# 缩进标记属性

正文只记录带缩进标记的多行属性。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        summary.id,
        chapter_index=58,
        query="潮声异常",
      )

    obsidian = detail.story_overview.obsidian
    note = next(item for item in obsidian.notes if item.title == "多行属性")
    indent_note = next(item for item in obsidian.notes if item.title == "缩进标记属性")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("第五十八章只公开[[当前线索]]。 [[未来真相]]仍保持未开放。", note.summary)
    self.assertIn("潮声异常", note.keywords)
    self.assertIn("夜潮账册", note.keywords)
    self.assertIn("潮声异常", note.required_phrases)
    self.assertIn("铜钥匙", note.required_phrases)
    self.assertIn("当前线索", note.links)
    self.assertIn("未来真相", note.links)
    self.assertIn("多行属性.md", current_note.backlinks)
    self.assertIn("多行属性.md", future_note.backlinks)
    self.assertIn("第五十八章只公开[[当前线索]]。", indent_note.summary)
    self.assertIn("潮声异常", indent_note.keywords)
    self.assertIn("夜潮账册", indent_note.keywords)
    self.assertIn("潮声异常 不得提前解释", indent_note.required_phrases)
    self.assertIn("当前线索", indent_note.links)
    self.assertIn("缩进标记属性.md", current_note.backlinks)
    scoped_note = next(item for item in scoped_contents if item["title"] == "多行属性")
    self.assertIn("未开放设定", scoped_note["content"])
    self.assertNotIn("未来真相", scoped_note["content"])
    self.assertNotIn("来源笔记 -> 未来真相", scoped_note["content"])
    indent_scoped_note = next(item for item in scoped_contents if item["title"] == "缩进标记属性")
    self.assertIn("潮声异常 不得提前解释", indent_scoped_note["content"])

  def test_obsidian_frontmatter_sequence_block_scalars_feed_metadata(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-sequence-block-scalars"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

后段真相不能提前进入第五十八章。
""",
      encoding="utf-8",
    )
    (vault_dir / "列表多行属性.md").write_text(
      """---
status: canonical
chapter_range: 58
keywords:
  - |
    潮声异常
    夜潮账册
source_notes:
  - >
    [[当前线索]]
  - |
    [[未来真相]]
required_phrases:
  - >
    潮声异常 不得提前解释
  - |
    铜钥匙
    盐账缺页
forbidden_phrases:
  - >
    提前公开[[未来真相]]
---
# 列表多行属性

正文只记录当前章节可见内容。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        summary.id,
        chapter_index=58,
        query="潮声异常",
      )

    obsidian = detail.story_overview.obsidian
    note = next(item for item in obsidian.notes if item.title == "列表多行属性")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("潮声异常", note.keywords)
    self.assertIn("夜潮账册", note.keywords)
    self.assertIn("潮声异常 不得提前解释", note.required_phrases)
    self.assertIn("铜钥匙", note.required_phrases)
    self.assertIn("盐账缺页", note.required_phrases)
    self.assertIn("提前公开[[未来真相]]", note.forbidden_phrases)
    self.assertIn("当前线索", note.links)
    self.assertIn("未来真相", note.links)
    self.assertIn("列表多行属性.md", current_note.backlinks)
    self.assertIn("列表多行属性.md", future_note.backlinks)

    scoped_note = next(item for item in scoped_contents if item["title"] == "列表多行属性")
    self.assertIn("潮声异常 不得提前解释", scoped_note["content"])
    self.assertIn("铜钥匙", scoped_note["content"])
    self.assertIn("盐账缺页", scoped_note["content"])
    self.assertIn("未开放设定", scoped_note["content"])
    self.assertNotIn("未来真相", scoped_note["content"])

  def test_obsidian_frontmatter_inline_comments_do_not_pollute_values(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-inline-comments"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "注释属性.md").write_text(
      """---
status: canonical # 正式设定
title: "潮师 # 守账人" # 标题里保留井号
aliases: ["潮师 # 守账人", 夜潮师] # 别名说明
keywords: [潮声异常, 夜潮账册] # 检索词说明
source_notes: [[当前线索#局部]] # 来源说明
chapter_range: 58-60 # 中段可用
reveal_after_chapter: 57 # 第五十八章起可用
required_phrases:
  - 潮声异常 # 必写说明
  - "铜钥匙 # 标识" # 引号里的井号保留
forbidden_phrases:
  - 提前公开沉船真相 # 禁写说明
---
# 注释属性

正文只记录当前章节可见内容。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(
          enabled=True,
          vault_path=str(vault_dir),
          allowed_statuses=["canonical"],
          include_without_status=False,
        ),
      )
      early_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "潮声异常",
        include_semantic=False,
        chapter_index=57,
      )
      scoped_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "潮声异常",
        include_semantic=False,
        chapter_index=58,
      )

    obsidian = detail.story_overview.obsidian
    note = next(item for item in obsidian.notes if item.relative_path == "注释属性.md")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    self.assertEqual(note.status, "canonical")
    self.assertEqual(note.title, "潮师 # 守账人")
    self.assertIn("潮师 # 守账人", note.aliases)
    self.assertIn("夜潮师", note.aliases)
    self.assertIn("潮声异常", note.keywords)
    self.assertEqual((note.chapter_start, note.chapter_end, note.reveal_after_chapter), (58, 60, 57))
    self.assertIn("潮声异常", note.required_phrases)
    self.assertIn("铜钥匙 # 标识", note.required_phrases)
    self.assertNotIn("必写说明", note.required_phrases)
    self.assertIn("提前公开沉船真相", note.forbidden_phrases)
    self.assertIn("当前线索", note.links)
    self.assertIn("当前线索.md", note.resolved_links)
    self.assertIn("注释属性.md", current_note.backlinks)
    self.assertFalse(any(item.source_key.endswith("注释属性.md") for item in early_hits))
    self.assertTrue(any(item.source == "Obsidian" and "潮师 # 守账人" in item.section for item in scoped_hits))

  def test_obsidian_extracts_frontmatter_relationship_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    character_dir = vault_dir / "Characters"
    clue_dir = vault_dir / "Clues"
    graph_dir = vault_dir / "Graph"
    character_dir.mkdir(parents=True)
    clue_dir.mkdir()
    graph_dir.mkdir()
    (character_dir / "林追.md").write_text(
      """---
status: canonical
type: character
---
# 林追

林追负责追查旧船队线索。
""",
      encoding="utf-8",
    )
    (vault_dir / "线索甲.md").write_text(
      """---
status: canonical
type: clue
---
# 线索甲

旧账册里只有潮汐编号。
""",
      encoding="utf-8",
    )
    (clue_dir / "线索乙.md").write_text(
      """---
status: canonical
type: clue
---
# 线索乙

线索乙记录另一条旧航线。
""",
      encoding="utf-8",
    )
    (vault_dir / "Graph-潮汐账本.md").write_text(
      """---
status: canonical
type: graph_note
aliases:
  - 潮汐账本
source_notes:
  - 线索甲.md
related_characters:
  - "[[Characters/林追]]"
---
# 潮汐账本

这份笔记只在 frontmatter 里维护来源关系。
""",
      encoding="utf-8",
    )
    (graph_dir / "Markdown关系.md").write_text(
      """---
status: canonical
type: graph_note
source_notes:
  - "[线索乙](../Clues/线索乙.md)"
related_characters:
  - "[林追](../Characters/林追.md)"
---
# Markdown关系

这份笔记用 Markdown 内链维护 Properties 关系。
""",
      encoding="utf-8",
    )
    (graph_dir / "Markdown逗号关系.md").write_text(
      """---
status: canonical
type: graph_note
source_notes: "[线索乙, 潮账](../Clues/线索乙.md)"
related_characters:
  - "[林追, 主角](../Characters/林追.md)"
depends_on: "[[线索甲|账册, 初证]]"
---
# Markdown逗号关系

这份笔记的关系链接标签里带逗号。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    graph_note = next(item for item in obsidian.notes if item.title == "潮汐账本")
    markdown_graph_note = next(item for item in obsidian.notes if item.title == "Markdown关系")
    markdown_comma_graph_note = next(item for item in obsidian.notes if item.title == "Markdown逗号关系")
    clue_note = next(item for item in obsidian.notes if item.title == "线索甲")
    second_clue_note = next(item for item in obsidian.notes if item.title == "线索乙")
    character_note = next(item for item in obsidian.notes if item.title == "林追")
    self.assertIn("线索甲.md", graph_note.links)
    self.assertIn("Characters/林追", graph_note.links)
    self.assertIn("线索甲.md", graph_note.resolved_links)
    self.assertIn("Characters/林追.md", graph_note.resolved_links)
    self.assertIn("Clues/线索乙.md", markdown_graph_note.links)
    self.assertIn("Characters/林追.md", markdown_graph_note.links)
    self.assertIn("来源笔记 -> Clues/线索乙.md", markdown_graph_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追.md", markdown_graph_note.graph_relations)
    self.assertIn("Clues/线索乙.md", markdown_graph_note.resolved_links)
    self.assertIn("Characters/林追.md", markdown_graph_note.resolved_links)
    self.assertIn("Clues/线索乙.md", markdown_comma_graph_note.links)
    self.assertIn("Characters/林追.md", markdown_comma_graph_note.links)
    self.assertIn("线索甲", markdown_comma_graph_note.links)
    self.assertIn("来源笔记 -> Clues/线索乙.md", markdown_comma_graph_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追.md", markdown_comma_graph_note.graph_relations)
    self.assertIn("依赖 -> 线索甲", markdown_comma_graph_note.graph_relations)
    self.assertIn("Clues/线索乙.md", markdown_comma_graph_note.resolved_links)
    self.assertIn("Characters/林追.md", markdown_comma_graph_note.resolved_links)
    self.assertIn("线索甲.md", markdown_comma_graph_note.resolved_links)
    self.assertIn("Graph-潮汐账本.md", clue_note.backlinks)
    self.assertIn("Graph/Markdown关系.md", second_clue_note.backlinks)
    self.assertIn("Graph/Markdown逗号关系.md", clue_note.backlinks)
    self.assertIn("Graph/Markdown逗号关系.md", second_clue_note.backlinks)
    self.assertIn("Graph-潮汐账本.md", character_note.backlinks)
    self.assertIn("Graph/Markdown关系.md", character_note.backlinks)
    self.assertIn("Graph/Markdown逗号关系.md", character_note.backlinks)

  def test_obsidian_frontmatter_relationship_subpaths_enter_context_without_graph_noise(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-relationship-subpaths"
    plan_dir = vault_dir / "Plans"
    secret_dir = vault_dir / "Secrets"
    graph_dir = vault_dir / "Graph"
    plan_dir.mkdir(parents=True)
    secret_dir.mkdir()
    graph_dir.mkdir()
    (plan_dir / "第58章合同.md").write_text(
      """---
status: canonical
type: chapter_contract
chapter_range: 58-59
---
# 第58章合同

## 合同核验小节

第58章必须保留潮汐暗账。

## 兑现检查

核对潮汐暗账与人物选择。
""",
      encoding="utf-8",
    )
    (secret_dir / "未来真相.md").write_text(
      """---
status: canonical
aliases:
  - 终局答案
reveal_after_chapter: 60
---
# 未来真相

## 终局答案小节

终局答案不能提前公开。
""",
      encoding="utf-8",
    )
    (graph_dir / "章节关系.md").write_text(
      """---
status: canonical
type: graph_note
chapter_range: 58
source_notes:
  - "[合同小节](../Plans/第58章合同.md#合同核验小节)"
  - "[未来小节](../Secrets/未来真相.md#终局答案小节)"
depends_on:
  - "[[../Plans/第58章合同#兑现检查]]"
---
# 章节关系

这份笔记只用 frontmatter 维护小节关系。必须出现：潮汐暗账。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      current_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "合同核验小节",
        include_semantic=False,
        chapter_index=58,
      )
      future_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "终局答案小节",
        include_semantic=False,
        chapter_index=58,
      )
      scoped_contents = load_project_obsidian_note_contents(
        self.settings,
        summary.id,
        chapter_index=58,
        query="合同核验小节",
        limit=8,
      )

    obsidian = detail.story_overview.obsidian
    relation_note = next(item for item in obsidian.notes if item.title == "章节关系")
    plan_note = next(item for item in obsidian.notes if item.title == "第58章合同")
    secret_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Plans/第58章合同.md", relation_note.links)
    self.assertIn("Plans/第58章合同", relation_note.links)
    self.assertIn("Secrets/未来真相.md", relation_note.links)
    self.assertFalse(any("#合同核验小节" in link for link in relation_note.links))
    self.assertFalse(any("#兑现检查" in link for link in relation_note.links))
    self.assertIn("来源笔记 -> Plans/第58章合同.md", relation_note.graph_relations)
    self.assertIn("来源笔记 -> Secrets/未来真相.md", relation_note.graph_relations)
    self.assertIn("依赖 -> Plans/第58章合同", relation_note.graph_relations)
    self.assertIn("Graph/章节关系.md", plan_note.backlinks)
    self.assertIn("Graph/章节关系.md", secret_note.backlinks)
    self.assertTrue(any(item.source_key.endswith("Graph/章节关系.md") for item in current_hits))
    self.assertFalse(any(item.source_key.endswith("Graph/章节关系.md") for item in future_hits))
    relation_content = next(item for item in scoped_contents if item["title"] == "章节关系")
    self.assertIn("关系小节", relation_content["content"])
    self.assertIn("[[Plans/第58章合同.md#合同核验小节]]", relation_content["content"])
    self.assertIn("[[Plans/第58章合同#兑现检查]]", relation_content["content"])
    self.assertIn("未开放设定", relation_content["content"])
    self.assertNotIn("终局答案", relation_content["content"])
    self.assertNotIn("Secrets/未来真相", relation_content["content"])

  def test_obsidian_extracts_common_graph_property_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-common-graph-properties"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Locations").mkdir()
    (vault_dir / "Props").mkdir()
    (vault_dir / "Organizations").mkdir()
    (vault_dir / "Clues").mkdir()
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
type: character
---
# 林追

林追继续追查旧航线。
""",
      encoding="utf-8",
    )
    (vault_dir / "Locations" / "旧码头.md").write_text(
      """---
status: canonical
type: location
---
# 旧码头

旧码头是第一批线索出现的地方。
""",
      encoding="utf-8",
    )
    (vault_dir / "Props" / "铜钥匙.md").write_text(
      """---
status: canonical
type: prop
---
# 铜钥匙

铜钥匙能打开潮汐账本。
""",
      encoding="utf-8",
    )
    (vault_dir / "Organizations" / "灯塔议会.md").write_text(
      """---
status: canonical
type: organization
---
# 灯塔议会

灯塔议会删改靠港记录。
""",
      encoding="utf-8",
    )
    (vault_dir / "Clues" / "第一章线索.md").write_text(
      """---
status: canonical
type: clue
---
# 第一章线索

旧码头蓝灯指向潮汐账本。
""",
      encoding="utf-8",
    )
    (vault_dir / "终局真相.md").write_text(
      """---
status: canonical
type: secret
reveal_after_chapter: 70
---
# 终局真相

终局真相只能在后段确认。
""",
      encoding="utf-8",
    )
    (vault_dir / "Plot").mkdir()
    (vault_dir / "Plot" / "潮汐账本线.md").write_text(
      """---
status: canonical
type: plot_thread
depends_on:
  - "[[Clues/第一章线索]]"
foreshadows:
  - 终局真相
payoffs:
  - Clues/第一章线索
related_locations:
  - "[[Locations/旧码头]]"
related_props:
  - Props/铜钥匙.md
related_organizations:
  - 灯塔议会
characters:
  - Characters/林追
---
# 潮汐账本线

这条线用常见 Obsidian Properties 维护图谱关系。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    thread_note = next(item for item in obsidian.notes if item.title == "潮汐账本线")
    self.assertIn("Clues/第一章线索", thread_note.links)
    self.assertIn("终局真相", thread_note.links)
    self.assertIn("Locations/旧码头", thread_note.links)
    self.assertIn("Props/铜钥匙.md", thread_note.links)
    self.assertIn("灯塔议会", thread_note.links)
    self.assertIn("Characters/林追", thread_note.links)
    self.assertIn("依赖 -> Clues/第一章线索", thread_note.graph_relations)
    self.assertIn("伏笔 -> 终局真相", thread_note.graph_relations)
    self.assertIn("兑现 -> Clues/第一章线索", thread_note.graph_relations)
    self.assertIn("相关地点 -> Locations/旧码头", thread_note.graph_relations)
    self.assertIn("相关道具 -> Props/铜钥匙.md", thread_note.graph_relations)
    self.assertIn("相关组织 -> 灯塔议会", thread_note.graph_relations)
    self.assertIn("人物 -> Characters/林追", thread_note.graph_relations)
    self.assertIn("Clues/第一章线索.md", thread_note.resolved_links)
    self.assertIn("终局真相.md", thread_note.resolved_links)
    self.assertIn("Locations/旧码头.md", thread_note.resolved_links)
    self.assertIn("Props/铜钥匙.md", thread_note.resolved_links)
    self.assertIn("Organizations/灯塔议会.md", thread_note.resolved_links)
    self.assertIn("Characters/林追.md", thread_note.resolved_links)
    for title in ("第一章线索", "终局真相", "旧码头", "铜钥匙", "灯塔议会", "林追"):
      note = next(item for item in obsidian.notes if item.title == title)
      self.assertIn("Plot/潮汐账本线.md", note.backlinks)

  def test_obsidian_body_relationship_sections_drive_graph_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-body-relationship-sections"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Locations").mkdir()
    (vault_dir / "Clues").mkdir()
    (vault_dir / "Secrets").mkdir()
    (vault_dir / "Characters" / "林追.md").write_text(
      """---
status: canonical
---
# 林追

林追负责追查旧码头线索。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "宋闻.md").write_text(
      """---
status: canonical
---
# 宋闻

宋闻只作为旁证出现。
""",
      encoding="utf-8",
    )
    (vault_dir / "Locations" / "旧码头.md").write_text(
      """---
status: canonical
---
# 旧码头

旧码头是第五十八章的关键地点。
""",
      encoding="utf-8",
    )
    (vault_dir / "Clues" / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "Secrets" / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

未来真相只能在后段公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "章节小节关系.md").write_text(
      """---
status: canonical
chapter_range: 58-60
reveal_after_chapter: 57
---
# 章节小节关系

这篇笔记用小节整理关系，不写关系 Properties。

## 来源笔记

- [[Clues/当前线索]]

## 相关人物

- [[Characters/林追]]
- 宋闻：只作为旁证

相关地点：[[Locations/旧码头]]

## 伏笔

- [[Secrets/未来真相]]
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      early_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "未来真相",
        include_semantic=False,
        chapter_index=58,
      )
      active_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "旧码头",
        include_semantic=False,
        chapter_index=58,
      )

    obsidian = detail.story_overview.obsidian
    section_note = next(item for item in obsidian.notes if item.title == "章节小节关系")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    lin_zhui_note = next(item for item in obsidian.notes if item.title == "林追")
    song_wen_note = next(item for item in obsidian.notes if item.title == "宋闻")
    location_note = next(item for item in obsidian.notes if item.title == "旧码头")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("Clues/当前线索", section_note.links)
    self.assertIn("Characters/林追", section_note.links)
    self.assertIn("宋闻", section_note.links)
    self.assertIn("Locations/旧码头", section_note.links)
    self.assertIn("Secrets/未来真相", section_note.links)
    self.assertIn("来源笔记 -> Clues/当前线索", section_note.graph_relations)
    self.assertIn("相关人物 -> Characters/林追", section_note.graph_relations)
    self.assertIn("相关人物 -> 宋闻", section_note.graph_relations)
    self.assertIn("相关地点 -> Locations/旧码头", section_note.graph_relations)
    self.assertIn("伏笔 -> Secrets/未来真相", section_note.graph_relations)
    self.assertIn("Clues/当前线索.md", section_note.resolved_links)
    self.assertIn("Characters/林追.md", section_note.resolved_links)
    self.assertIn("Characters/宋闻.md", section_note.resolved_links)
    self.assertIn("Locations/旧码头.md", section_note.resolved_links)
    self.assertIn("Secrets/未来真相.md", section_note.resolved_links)
    for note in (current_note, lin_zhui_note, song_wen_note, location_note, future_note):
      self.assertIn("章节小节关系.md", note.backlinks)
    self.assertEqual(early_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "章节小节关系" in item.section for item in active_hits))

    scoped_note_contents = load_project_obsidian_note_contents(
      self.settings,
      summary.id,
      chapter_index=58,
      query="章节小节关系",
    )
    section_content = next(item for item in scoped_note_contents if item["title"] == "章节小节关系")
    self.assertIn("旧码头", section_content["content"])
    self.assertIn("未开放设定", section_content["content"])
    self.assertNotIn("未来真相", section_content["content"])
    self.assertNotIn("伏笔 -> Secrets/未来真相", section_content["content"])

  def test_obsidian_ignores_comments_and_code_blocks_for_ai_context_and_graph(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-hidden-body-regions"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

沉船真相只允许后段使用。
""",
      encoding="utf-8",
    )
    (vault_dir / "可见笔记.md").write_text(
      """---
status: canonical
chapter_range: 58
---
# 可见笔记

这一章只写潮声异常。
source_notes:: [[当前线索]]
required_phrases:: 潮声异常
#可见标签

%% 私密备注：[[未来真相]] 沉船真相
required_phrases:: 暗处真相
#隐藏标签
%%

```text
source_notes:: [[未来真相]]
required_phrases:: 暗处真相
#隐藏标签
[[未来真相]]
```

<!-- HTML 私密备注：[[未来真相]] 沉船真相
source_notes:: [[未来真相]]
required_phrases:: 暗处真相
#隐藏标签
-->

行内代码示例：`source_notes:: [[未来真相]] required_phrases:: 暗处真相 #隐藏标签 [summary:: 沉船真相] %% 注释占位 %%`

删除线示例：~~source_notes:: [[未来真相]] required_phrases:: 废弃真相 #废弃标签 [summary:: 沉船真相]~~
HTML 删除示例：<del>[[未来真相]] #废弃标签 required_phrases:: 废弃真相</del>
HTML 删除示例：<s>[[未来真相]] #废弃标签</s>
HTML 删除示例：<strike>[[未来真相]] #废弃标签</strike>

<details><summary>公开资料</summary>
source_notes:: [[当前线索]]
required_phrases:: 公开折叠线索
#折叠可见标签
draft:: false
<!-- no_ai:: true 这行在 HTML 注释里，不能隐藏公开折叠正文 -->
%% AI不可用:: 是 这行在 Obsidian 注释里，不能隐藏公开折叠正文 %%
</details>

<details><summary>剧透</summary>
source_notes:: [[未来真相]]
required_phrases:: 折叠真相
#折叠隐藏标签
[summary:: 折叠沉船真相]
</details>

<details class="no-ai"><summary>暂存资料</summary>
source_notes:: [[未来真相]]
required_phrases:: 暂存真相
#暂存隐藏标签
</details>

<details><summary>普通折叠标题</summary>
no_ai:: true
source_notes:: [[未来真相]]
required_phrases:: 正文折叠真相
#正文折叠隐藏标签
</details>

<details><summary>属性折叠标题</summary>
AI不可用:: 是
source_notes:: [[未来真相]]
required_phrases:: 属性折叠真相
#属性折叠隐藏标签
</details>

<details><summary>草稿折叠标题</summary>
draft:: true
source_notes:: [[未来真相]]
required_phrases:: 草稿折叠真相
#草稿折叠隐藏标签
</details>

<details><summary>私密折叠标题</summary>
private:: true
source_notes:: [[未来真相]]
required_phrases:: 私密折叠真相
#私密折叠隐藏标签
</details>

<details><summary>归档折叠标题</summary>
archived:: true
source_notes:: [[未来真相]]
required_phrases:: 归档折叠真相
#归档折叠隐藏标签
</details>
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      hidden_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "暗处真相",
        include_semantic=False,
        chapter_index=58,
      )
      visible_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "潮声异常",
        include_semantic=False,
        chapter_index=58,
      )
      body_hidden_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "正文折叠真相 属性折叠真相 草稿折叠真相 私密折叠真相 归档折叠真相",
        include_semantic=False,
        chapter_index=58,
      )

    obsidian = detail.story_overview.obsidian
    visible_note = next(item for item in obsidian.notes if item.title == "可见笔记")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("当前线索", visible_note.links)
    self.assertNotIn("未来真相", visible_note.links)
    self.assertIn("来源笔记 -> 当前线索", visible_note.graph_relations)
    self.assertNotIn("来源笔记 -> 未来真相", visible_note.graph_relations)
    self.assertIn("当前线索.md", visible_note.resolved_links)
    self.assertNotIn("未来真相.md", visible_note.resolved_links)
    self.assertIn("可见标签", visible_note.tags)
    self.assertIn("折叠可见标签", visible_note.tags)
    self.assertNotIn("隐藏标签", visible_note.tags)
    self.assertNotIn("废弃标签", visible_note.tags)
    self.assertNotIn("折叠隐藏标签", visible_note.tags)
    self.assertNotIn("暂存隐藏标签", visible_note.tags)
    self.assertNotIn("正文折叠隐藏标签", visible_note.tags)
    self.assertNotIn("属性折叠隐藏标签", visible_note.tags)
    self.assertNotIn("草稿折叠隐藏标签", visible_note.tags)
    self.assertNotIn("私密折叠隐藏标签", visible_note.tags)
    self.assertNotIn("归档折叠隐藏标签", visible_note.tags)
    self.assertIn("潮声异常", visible_note.required_phrases)
    self.assertIn("公开折叠线索", visible_note.required_phrases)
    self.assertNotIn("暗处真相", visible_note.required_phrases)
    self.assertNotIn("废弃真相", visible_note.required_phrases)
    self.assertNotIn("折叠真相", visible_note.required_phrases)
    self.assertNotIn("暂存真相", visible_note.required_phrases)
    self.assertNotIn("正文折叠真相", visible_note.required_phrases)
    self.assertNotIn("属性折叠真相", visible_note.required_phrases)
    self.assertNotIn("草稿折叠真相", visible_note.required_phrases)
    self.assertNotIn("私密折叠真相", visible_note.required_phrases)
    self.assertNotIn("归档折叠真相", visible_note.required_phrases)
    self.assertIn("可见笔记.md", current_note.backlinks)
    self.assertNotIn("可见笔记.md", future_note.backlinks)
    self.assertNotIn("沉船真相", visible_note.preview)
    self.assertNotIn("暗处真相", visible_note.preview)
    self.assertNotIn("废弃真相", visible_note.preview)
    self.assertNotIn("折叠真相", visible_note.preview)
    self.assertNotIn("暂存真相", visible_note.preview)
    self.assertNotIn("正文折叠真相", visible_note.preview)
    self.assertNotIn("属性折叠真相", visible_note.preview)
    self.assertNotIn("草稿折叠真相", visible_note.preview)
    self.assertNotIn("私密折叠真相", visible_note.preview)
    self.assertNotIn("归档折叠真相", visible_note.preview)
    self.assertNotIn("HTML 私密备注", visible_note.preview)
    self.assertFalse(any("暗处真相" in item.preview or "沉船真相" in item.preview for item in hidden_hits))
    self.assertFalse(any(
      "正文折叠真相" in item.preview
      or "属性折叠真相" in item.preview
      or "草稿折叠真相" in item.preview
      or "私密折叠真相" in item.preview
      or "归档折叠真相" in item.preview
      for item in body_hidden_hits
    ))
    self.assertTrue(any(item.source == "Obsidian" and "可见笔记" in item.section for item in visible_hits))

    scoped_note_contents = load_project_obsidian_note_contents(
      self.settings,
      summary.id,
      chapter_index=58,
      query="可见笔记",
    )
    visible_content = next(item for item in scoped_note_contents if item["title"] == "可见笔记")
    self.assertIn("潮声异常", visible_content["content"])
    self.assertIn("公开折叠线索", visible_content["content"])
    self.assertNotIn("沉船真相", visible_content["content"])
    self.assertNotIn("暗处真相", visible_content["content"])
    self.assertNotIn("折叠沉船真相", visible_content["content"])
    self.assertNotIn("暂存真相", visible_content["content"])
    self.assertNotIn("正文折叠真相", visible_content["content"])
    self.assertNotIn("属性折叠真相", visible_content["content"])
    self.assertNotIn("草稿折叠真相", visible_content["content"])
    self.assertNotIn("私密折叠真相", visible_content["content"])
    self.assertNotIn("归档折叠真相", visible_content["content"])
    self.assertNotIn("未来真相", visible_content["content"])
    self.assertNotIn("隐藏标签", visible_content["content"])
    self.assertNotIn("折叠隐藏标签", visible_content["content"])
    self.assertNotIn("暂存隐藏标签", visible_content["content"])
    self.assertNotIn("正文折叠隐藏标签", visible_content["content"])
    self.assertNotIn("属性折叠隐藏标签", visible_content["content"])
    self.assertNotIn("草稿折叠隐藏标签", visible_content["content"])
    self.assertNotIn("私密折叠隐藏标签", visible_content["content"])
    self.assertNotIn("归档折叠隐藏标签", visible_content["content"])
    self.assertNotIn("HTML 私密备注", visible_content["content"])

  def test_obsidian_hidden_callouts_do_not_feed_ai_context_and_graph(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-hidden-callouts"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮声异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "未来真相.md").write_text(
      """---
status: canonical
reveal_after_chapter: 70
---
# 未来真相

沉船真相只能在后段公开。
""",
      encoding="utf-8",
    )
    (vault_dir / "呼吸笔记.md").write_text(
      """---
status: canonical
chapter_range: 58
---
# 呼吸笔记

正文只记录当前章节可见内容。

> [!spoiler] 终局
> source_notes:: [[未来真相]]
> required_phrases:: 暗处真相
> #隐藏标签
> 沉船真相不能进入第五十八章。
>
> [!note] 同块提示
> source_notes:: [[未来真相]]
> required_phrases:: 同块暗处真相
> #同块隐藏标签

> [!note] 可见提醒
> source_notes:: [[当前线索]]
> required_phrases:: 潮声异常
> #可见标签
> > [!spoiler] 嵌套终局
> > source_notes:: [[未来真相]]
> > required_phrases:: 嵌套暗处真相
> > #嵌套隐藏标签
> required_phrases:: 嵌套后公开线索
> #嵌套后可见标签
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      hidden_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "暗处真相",
        include_semantic=False,
        chapter_index=58,
      )
      visible_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "潮声异常",
        include_semantic=False,
        chapter_index=58,
      )

    obsidian = detail.story_overview.obsidian
    visible_note = next(item for item in obsidian.notes if item.title == "呼吸笔记")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    future_note = next(item for item in obsidian.notes if item.title == "未来真相")
    self.assertIn("当前线索", visible_note.links)
    self.assertNotIn("未来真相", visible_note.links)
    self.assertIn("来源笔记 -> 当前线索", visible_note.graph_relations)
    self.assertNotIn("来源笔记 -> 未来真相", visible_note.graph_relations)
    self.assertIn("当前线索.md", visible_note.resolved_links)
    self.assertNotIn("未来真相.md", visible_note.resolved_links)
    self.assertIn("可见标签", visible_note.tags)
    self.assertIn("嵌套后可见标签", visible_note.tags)
    self.assertNotIn("隐藏标签", visible_note.tags)
    self.assertNotIn("同块隐藏标签", visible_note.tags)
    self.assertNotIn("嵌套隐藏标签", visible_note.tags)
    self.assertIn("潮声异常", visible_note.required_phrases)
    self.assertIn("嵌套后公开线索", visible_note.required_phrases)
    self.assertNotIn("暗处真相", visible_note.required_phrases)
    self.assertNotIn("同块暗处真相", visible_note.required_phrases)
    self.assertNotIn("嵌套暗处真相", visible_note.required_phrases)
    self.assertIn("呼吸笔记.md", current_note.backlinks)
    self.assertNotIn("呼吸笔记.md", future_note.backlinks)
    self.assertNotIn("沉船真相", visible_note.preview)
    self.assertNotIn("暗处真相", visible_note.preview)
    self.assertNotIn("嵌套暗处真相", visible_note.preview)
    self.assertFalse(any("暗处真相" in item.preview or "沉船真相" in item.preview for item in hidden_hits))
    self.assertTrue(any(item.source == "Obsidian" and "呼吸笔记" in item.section for item in visible_hits))

    scoped_note_contents = load_project_obsidian_note_contents(
      self.settings,
      summary.id,
      chapter_index=58,
      query="呼吸笔记",
    )
    visible_content = next(item for item in scoped_note_contents if item["title"] == "呼吸笔记")
    self.assertIn("潮声异常", visible_content["content"])
    self.assertIn("嵌套后公开线索", visible_content["content"])
    self.assertNotIn("沉船真相", visible_content["content"])
    self.assertNotIn("暗处真相", visible_content["content"])
    self.assertNotIn("同块暗处真相", visible_content["content"])
    self.assertNotIn("嵌套暗处真相", visible_content["content"])
    self.assertNotIn("未来真相", visible_content["content"])
    self.assertNotIn("隐藏标签", visible_content["content"])
    self.assertNotIn("嵌套隐藏标签", visible_content["content"])
    self.assertNotIn("同块隐藏标签", visible_content["content"])

  def test_obsidian_ignores_attachment_embeds_but_keeps_note_embeds(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-attachment-embeds"
    vault_dir.mkdir()
    (vault_dir / "当前线索.md").write_text(
      """---
status: canonical
---
# 当前线索

当前线索只说明潮汐编号异常。
""",
      encoding="utf-8",
    )
    (vault_dir / "关系图.canvas").write_text(
      json.dumps(
        {
          "nodes": [
            {
              "id": "note",
              "type": "text",
              "text": "status:: canonical\nsummary:: 关系图只记录当前线索。",
            },
          ],
          "edges": [],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (vault_dir / "嵌入清单.md").write_text(
      """---
status: canonical
---
# 嵌入清单

正文会嵌入当前线索。
![[当前线索]]
![[关系图.canvas]]
![[images/旧地图.png]]
![[资料/访谈.pdf]]
![潮汐图](assets/tide-map.png)
[访谈PDF](资料/访谈.pdf)
[录音附件](assets/tide-audio.mp3 "素材")
[附件引用PDF][访谈附件]
<img src="assets/secret-map.png" alt="密图HTML">
<audio controls src="assets/secret-audio.mp3">录音HTML</audio>
<iframe src="资料/访谈.pdf" title="访谈HTML"></iframe>

[访谈附件]: 资料/访谈.pdf

source_notes:: [[当前线索]], [[资料/访谈.pdf]]

## 来源笔记

- ![[当前线索]]
- ![[资料/访谈.pdf]]
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      attachment_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "旧地图 访谈 潮汐图 访谈PDF 录音附件 附件引用PDF 密图HTML 录音HTML 访谈HTML",
        include_semantic=False,
      )

    obsidian = detail.story_overview.obsidian
    embedded_note = next(item for item in obsidian.notes if item.title == "嵌入清单")
    current_note = next(item for item in obsidian.notes if item.title == "当前线索")
    canvas_note = next(item for item in obsidian.notes if item.title == "关系图")
    self.assertIn("当前线索", embedded_note.links)
    self.assertIn("关系图.canvas", embedded_note.links)
    self.assertIn("当前线索", embedded_note.embedded_links)
    self.assertIn("关系图.canvas", embedded_note.embedded_links)
    self.assertNotIn("images/旧地图.png", embedded_note.links)
    self.assertNotIn("资料/访谈.pdf", embedded_note.links)
    self.assertNotIn("assets/tide-audio.mp3", embedded_note.links)
    self.assertNotIn("images/旧地图.png", embedded_note.embedded_links)
    self.assertNotIn("资料/访谈.pdf", embedded_note.embedded_links)
    self.assertIn("当前线索.md", embedded_note.resolved_links)
    self.assertIn("关系图.canvas", embedded_note.resolved_links)
    self.assertNotIn("资料/访谈.pdf", embedded_note.unresolved_links)
    self.assertIn("来源笔记 -> 当前线索", embedded_note.graph_relations)
    self.assertNotIn("来源笔记 -> 资料/访谈.pdf", embedded_note.graph_relations)
    self.assertIn("嵌入清单.md", current_note.backlinks)
    self.assertIn("嵌入清单.md", canvas_note.backlinks)
    self.assertNotIn("旧地图", embedded_note.preview)
    self.assertNotIn("访谈", embedded_note.preview)
    self.assertNotIn("潮汐图", embedded_note.preview)
    self.assertNotIn("录音附件", embedded_note.preview)
    self.assertNotIn("附件引用PDF", embedded_note.preview)
    self.assertNotIn("密图HTML", embedded_note.preview)
    self.assertNotIn("录音HTML", embedded_note.preview)
    self.assertNotIn("访谈HTML", embedded_note.preview)
    self.assertFalse(any(
      "旧地图" in item.preview
      or "访谈" in item.preview
      or "潮汐图" in item.preview
      or "录音附件" in item.preview
      or "附件引用PDF" in item.preview
      or "密图HTML" in item.preview
      or "录音HTML" in item.preview
      or "访谈HTML" in item.preview
      for item in attachment_hits
    ))

    note_contents = load_project_obsidian_note_contents(
      self.settings,
      summary.id,
      query="嵌入清单",
    )
    embedded_content = next(item for item in note_contents if item["title"] == "嵌入清单")
    self.assertIn("当前线索", embedded_content["content"])
    self.assertIn("关系图.canvas", embedded_content["content"])
    self.assertNotIn("旧地图", embedded_content["content"])
    self.assertNotIn("访谈", embedded_content["content"])
    self.assertNotIn("潮汐图", embedded_content["content"])
    self.assertNotIn("录音附件", embedded_content["content"])
    self.assertNotIn("附件引用PDF", embedded_content["content"])
    self.assertNotIn("密图HTML", embedded_content["content"])
    self.assertNotIn("录音HTML", embedded_content["content"])
    self.assertNotIn("访谈HTML", embedded_content["content"])

  def test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    (vault_dir / "未来真相.md").write_text(
      """---
type: secret
status: canonical
chapter_range: 第58章-第60章
reveal_after_chapter: 57
required_phrases: [沉船真相]
---
# 未来真相

沉船真相只能在中段公开，来源会反向引用[[当前线索]]。
""",
      encoding="utf-8",
    )
    (vault_dir / "当前线索.md").write_text(
      """---
type: clue
status: canonical
chapter_range: 1-57
foreshadows:
  - 未来真相
---
# 当前线索

当前线索只说明潮汐编号还没有解开，真正答案不要提前点名[[未来真相]]。
""",
      encoding="utf-8",
    )
    (vault_dir / "支线暗号.md").write_text(
      """---
type: clue
status: canonical
---
# 支线暗号

适用章节：第十章-第十二章
第九章后可用
必须出现：潮声暗号
""",
      encoding="utf-8",
    )
    (vault_dir / "标签线索.md").write_text(
      """---
type: clue
status: canonical
tags: [章节/20-22, 剧透/19]
---
# 标签线索

这类笔记只靠 Obsidian 标签声明可用范围。
""",
      encoding="utf-8",
    )
    (vault_dir / "正文标签线索.md").write_text(
      """---
type: clue
status: canonical
---
# 正文标签线索

这条线索用正文标签标记。 #适用章节/30-31 #剧透/29
""",
      encoding="utf-8",
    )
    (vault_dir / "正文全角标签线索.md").write_text(
      """---
type: clue
status: canonical
---
# 正文全角标签线索

全角标签资料只在第四十章到第四十二章可见。 #适用章节／40～42 #剧透／39
""",
      encoding="utf-8",
    )
    (vault_dir / "未引号井号标签线索.md").write_text(
      """---
type: clue
status: canonical
tags: #章节/44-45 #剧透/43
---
# 未引号井号标签线索

未引号井号标签资料只在第四十四章到第四十五章可见。
""",
      encoding="utf-8",
    )
    for index in range(30):
      (vault_dir / f"00未来拥堵{index:02d}.md").write_text(
        f"""---
type: clue
status: canonical
chapter_range: 90-91
---
# 未来拥堵{index:02d}

幽蓝灯塔只在后段公开。
""",
        encoding="utf-8",
      )
    (vault_dir / "zz当前拥堵.md").write_text(
      """---
type: clue
status: canonical
chapter_range: 57
---
# 当前拥堵

幽蓝灯塔在本章只能作为误导线索出现。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")), patch(
      "novel_backend.services.project_service.rerank_documents",
      return_value=[],
    ):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      hits = search_project_knowledge(self.settings, summary.id, "沉船真相", include_semantic=False)
      early_future_search_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "未来真相",
        include_semantic=False,
        chapter_index=57,
      )
      early_current_search_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "当前线索",
        include_semantic=False,
        chapter_index=57,
      )
      crowded_search_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "幽蓝灯塔",
        limit=1,
        include_semantic=False,
        chapter_index=57,
      )
      active_future_search_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "未来真相",
        include_semantic=False,
        chapter_index=58,
      )
      early_evidence = search_project_knowledge_evidence(
        self.settings,
        summary.id,
        "沉船真相",
        chapter_index=57,
      )
      active_evidence = search_project_knowledge_evidence(
        self.settings,
        summary.id,
        "沉船真相",
        chapter_index=58,
      )
      early_current_evidence = search_project_knowledge_evidence(
        self.settings,
        summary.id,
        "当前线索",
        chapter_index=57,
      )
      crowded_evidence = search_project_knowledge_evidence(
        self.settings,
        summary.id,
        "幽蓝灯塔",
        limit=1,
        candidate_limit=1,
        chapter_index=57,
      )
      early_note_contents = load_project_obsidian_note_contents(
        self.settings,
        summary.id,
        chapter_index=57,
        query="当前线索",
      )
      fullwidth_tag_early_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "全角标签资料",
        include_semantic=False,
        chapter_index=39,
      )
      fullwidth_tag_mid_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "全角标签资料",
        include_semantic=False,
        chapter_index=40,
      )
      unquoted_hash_tag_early_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "未引号井号标签资料",
        include_semantic=False,
        chapter_index=43,
      )
      unquoted_hash_tag_mid_hits = search_project_knowledge(
        self.settings,
        summary.id,
        "未引号井号标签资料",
        include_semantic=False,
        chapter_index=44,
      )

    future_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "未来真相")
    side_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "支线暗号")
    tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "标签线索")
    inline_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "正文标签线索")
    fullwidth_inline_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "正文全角标签线索")
    unquoted_hash_tag_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "未引号井号标签线索")
    self.assertEqual(future_note.chapter_start, 58)
    self.assertEqual(future_note.chapter_end, 60)
    self.assertEqual(future_note.reveal_after_chapter, 57)
    self.assertEqual(side_note.chapter_start, 10)
    self.assertEqual(side_note.chapter_end, 12)
    self.assertEqual(side_note.reveal_after_chapter, 9)
    self.assertEqual(tag_note.chapter_start, 20)
    self.assertEqual(tag_note.chapter_end, 22)
    self.assertEqual(tag_note.reveal_after_chapter, 19)
    self.assertEqual(inline_tag_note.chapter_start, 30)
    self.assertEqual(inline_tag_note.chapter_end, 31)
    self.assertEqual(inline_tag_note.reveal_after_chapter, 29)
    self.assertEqual(fullwidth_inline_tag_note.chapter_start, 40)
    self.assertEqual(fullwidth_inline_tag_note.chapter_end, 42)
    self.assertEqual(fullwidth_inline_tag_note.reveal_after_chapter, 39)
    self.assertIn("适用章节／40～42", fullwidth_inline_tag_note.tags)
    self.assertIn("剧透／39", fullwidth_inline_tag_note.tags)
    self.assertEqual(unquoted_hash_tag_note.chapter_start, 44)
    self.assertEqual(unquoted_hash_tag_note.chapter_end, 45)
    self.assertEqual(unquoted_hash_tag_note.reveal_after_chapter, 43)
    self.assertIn("章节/44-45", unquoted_hash_tag_note.tags)
    self.assertIn("剧透/43", unquoted_hash_tag_note.tags)
    self.assertTrue(any("适用章节：第 58-60 章" in item.preview for item in hits))
    self.assertTrue(any("剧透边界：第 57 章后可用" in item.preview for item in hits))
    self.assertEqual(early_future_search_hits, [])
    self.assertEqual(fullwidth_tag_early_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "正文全角标签线索" in item.section for item in fullwidth_tag_mid_hits))
    self.assertEqual(unquoted_hash_tag_early_hits, [])
    self.assertTrue(any(item.source == "Obsidian" and "未引号井号标签线索" in item.section for item in unquoted_hash_tag_mid_hits))
    self.assertTrue(any(item.source_key.endswith("当前线索.md") for item in early_current_search_hits))
    self.assertFalse(any("未来真相" in item.preview for item in early_current_search_hits))
    self.assertEqual(len(crowded_search_hits), 1)
    self.assertTrue(crowded_search_hits[0].source_key.endswith("zz当前拥堵.md"))
    self.assertFalse("未来拥堵" in crowded_search_hits[0].preview)
    self.assertTrue(any(item.source_key.endswith("未来真相.md") for item in active_future_search_hits))
    self.assertFalse(any(str(item.get("source_key", "")).endswith("未来真相.md") for item in early_evidence))
    self.assertTrue(any(str(item.get("source_key", "")).endswith("未来真相.md") for item in active_evidence))
    self.assertTrue(any(str(item.get("source_key", "")).endswith("当前线索.md") for item in early_current_evidence))
    self.assertEqual(len(crowded_evidence), 1)
    self.assertTrue(str(crowded_evidence[0].get("source_key", "")).endswith("zz当前拥堵.md"))
    self.assertFalse("未来拥堵" in str(crowded_evidence[0].get("content", "")))
    self.assertFalse(any("未来真相" in str(item.get("content", "")) for item in early_current_evidence))
    self.assertFalse(any("伏笔 -> 未来真相" in str(item.get("content", "")) for item in early_current_evidence))
    self.assertFalse(any("双链：未来真相" in str(item.get("content", "")) for item in early_current_evidence))
    self.assertFalse(any("沉船真相" in str(item.get("content", "")) for item in early_current_evidence))
    self.assertTrue(any(item.get("title") == "当前线索" for item in early_note_contents))
    self.assertFalse(any("未来真相" in str(item.get("content", "")) for item in early_note_contents))
    self.assertFalse(any("伏笔 -> 未来真相" in str(item.get("content", "")) for item in early_note_contents))

    early_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "沉船真相",
      chapter_index=57,
    )
    active_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "沉船真相",
      chapter_index=58,
    )
    unmatched_active_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "完全无关的查询",
      chapter_index=58,
    )
    expired_notes = select_obsidian_notes_for_query(
      detail.story_overview.obsidian.notes,
      "沉船真相",
      chapter_index=61,
    )

    self.assertFalse(any(item.title == "未来真相" for item in early_notes))
    self.assertTrue(any(item.title == "未来真相" for item in active_notes))
    self.assertEqual(unmatched_active_notes[0].title, "未来真相")
    self.assertFalse(any(item.title == "未来真相" for item in expired_notes))

  def test_obsidian_sync_reflects_note_changes(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    note_path = vault_dir / "世界规则.md"
    note_path.write_text(
      """---
type: world_rule
status: canonical
---
潮位窗口每三天打开一次。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      note_path.write_text(
        """---
type: world_rule
status: canonical
---
潮位窗口每七天打开一次。
""",
        encoding="utf-8",
      )
      detail = sync_project_obsidian(self.settings, summary.id)
      hits = search_project_knowledge(self.settings, summary.id, "每七天", include_semantic=False)

    self.assertEqual(detail.story_overview.obsidian.included_count, 1)
    self.assertTrue(any("每七天" in item.preview for item in hits))

  def test_obsidian_state_auto_refreshes_when_vault_file_changes(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    note_path = vault_dir / "人物.md"
    note_path.write_text(
      """---
type: character
status: canonical
---
林追还没有得到夜航图。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    note_path.write_text(
      """---
type: character
status: canonical
---
林追已经得到夜航图，并把它藏进铜钥匙盒。
""",
      encoding="utf-8",
    )

    refreshed = get_project_detail(self.settings, summary.id)
    obsidian = refreshed.story_overview.obsidian
    self.assertEqual(obsidian.included_count, 1)
    self.assertIn("已经得到夜航图", obsidian.notes[0].preview)
    sync_path = Path(summary.path) / ".gaoxia" / "obsidian_sync.json"
    self.assertTrue(sync_path.exists())
    self.assertTrue(obsidian.source_signature)

  def test_obsidian_sync_reports_duplicate_labels_and_ambiguous_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Organizations").mkdir(parents=True)
    (vault_dir / "线索.md").write_text(
      """---
status: canonical
---
码头账本里反复提到[[白石]]。
""",
      encoding="utf-8",
    )
    (vault_dir / "Characters" / "白石.md").write_text(
      """---
title: 白石
status: canonical
---
白石是旧船队幸存者。
""",
      encoding="utf-8",
    )
    (vault_dir / "Organizations" / "白石商会.md").write_text(
      """---
title: 白石
status: canonical
aliases: [白石商会]
---
白石商会控制仓储路线。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_note_contents = load_project_obsidian_note_contents(
        self.settings,
        summary.id,
        chapter_index=1,
        query="码头账本",
      )

    obsidian = detail.story_overview.obsidian
    clue = next(item for item in obsidian.notes if item.title == "线索")
    self.assertIn("白石", clue.ambiguous_links)
    self.assertNotIn("Characters/白石.md", clue.resolved_links)
    self.assertGreaterEqual(obsidian.duplicate_label_count, 1)
    self.assertEqual(obsidian.ambiguous_link_count, 1)
    self.assertTrue(any("重复标题" in item for item in obsidian.warnings))
    self.assertTrue(any("歧义双链" in item for item in obsidian.warnings))
    issue_titles = [item.title for item in obsidian.issues]
    self.assertTrue(any(title.startswith("重复命名：白石") for title in issue_titles))
    self.assertIn("歧义双链：白石", issue_titles)
    ambiguous_issue = next(item for item in obsidian.issues if item.title == "歧义双链：白石")
    self.assertIn("线索.md", ambiguous_issue.notes)
    scoped_clue = next(item for item in scoped_note_contents if item["title"] == "线索")
    self.assertIn("歧义双链：白石", scoped_clue["content"])

  def test_obsidian_sync_reports_chapter_scope_mismatch_for_resolved_links(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-scope-mismatch"
    (vault_dir / "Graph").mkdir(parents=True)
    (vault_dir / "Graph" / "潮汐账本.md").write_text(
      """---
status: canonical
type: graph_note
chapter_range: 第 58-60 章
---
# 潮汐账本

潮汐账本在中段揭开旧船队账页。
""",
      encoding="utf-8",
    )
    (vault_dir / "后段线索.md").write_text(
      """---
status: canonical
type: clue
chapter_range: 第 80-82 章
---
# 后段线索

第八十章后，林追再次追到[[潮汐账本]]。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    clue = next(item for item in obsidian.notes if item.title == "后段线索")
    self.assertIn("Graph/潮汐账本.md", clue.resolved_links)
    issue = next(item for item in obsidian.issues if item.kind == "scope_mismatch")
    self.assertEqual(issue.title, "章节范围不匹配：潮汐账本")
    self.assertIn("后段线索.md", issue.notes)
    self.assertIn("Graph/潮汐账本.md", issue.notes)
    self.assertTrue(any("章节范围不匹配" in item for item in obsidian.warnings))

  def test_obsidian_sync_reports_scope_mismatch_when_global_source_links_scoped_target(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-global-source-scope-mismatch"
    (vault_dir / "Graph").mkdir(parents=True)
    (vault_dir / "Graph" / "终局背叛.md").write_text(
      """---
status: canonical
type: graph_note
reveal_after_chapter: 70
---
# 终局背叛

终局背叛只能在第七十章后进入上下文。
""",
      encoding="utf-8",
    )
    (vault_dir / "人物总览.md").write_text(
      """---
status: canonical
type: character_index
---
# 人物总览

林追的人物线在全书都会引用 [[终局背叛]]。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    obsidian = detail.story_overview.obsidian
    source = next(item for item in obsidian.notes if item.title == "人物总览")
    self.assertIn("Graph/终局背叛.md", source.resolved_links)
    issue = next(item for item in obsidian.issues if item.kind == "scope_mismatch")
    self.assertEqual(issue.title, "章节范围不匹配：终局背叛")
    self.assertIn("人物总览.md", issue.notes)
    self.assertIn("Graph/终局背叛.md", issue.notes)
    self.assertIn("第 1 章可用", issue.message)

  def test_obsidian_sync_does_not_count_unresolved_links_as_orphans(self) -> None:
    summary = self.create_demo_project()
    vault_dir = Path(self._temp_dir.name) / "vault-unresolved-not-orphan"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      """---
status: canonical
---
线索甲反复提到[[潮汐账本]]，但目标笔记还没有建立。
""",
      encoding="utf-8",
    )
    (vault_dir / "线索乙.md").write_text(
      """---
status: canonical
---
线索乙也提到[[潮汐账本]]，等待作者确认是否成为正式设定。
""",
      encoding="utf-8",
    )

    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      detail = update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )
      scoped_note_contents = load_project_obsidian_note_contents(
        self.settings,
        summary.id,
        chapter_index=1,
        query="线索甲",
      )

    obsidian = detail.story_overview.obsidian
    self.assertEqual(obsidian.unresolved_link_count, 2)
    self.assertEqual(obsidian.orphan_count, 0)
    issue_titles = [item.title for item in obsidian.issues]
    self.assertIn("未解析双链：潮汐账本", issue_titles)
    self.assertFalse(any(title.startswith("孤立笔记") for title in issue_titles))
    scoped_clue = next(item for item in scoped_note_contents if item["title"] == "线索甲")
    self.assertIn("未解析双链：潮汐账本", scoped_clue["content"])


if __name__ == "__main__":
  unittest.main()
