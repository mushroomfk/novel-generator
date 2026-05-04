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
  StoryDocumentUpdateRequest,
)
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.context_builder import build_project_context_bundle
from novel_backend.services.project_service import (
  create_project,
  get_project_detail,
  update_chapter_content,
  update_project_memory,
  update_story_document,
)


class ProjectMemoryServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self.project = create_project(
      self.settings,
      CreateProjectRequest(name="项目记忆测试", genre="悬疑", target_chapters=3, target_words=50000),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "world_building",
      StoryDocumentUpdateRequest(content="铜钥匙只能在涨潮前一小时启用，错过窗口就会失效。"),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "blueprint",
      StoryDocumentUpdateRequest(content="第一章拿到铜钥匙，第二章试探白石商会，第三章追查失踪航线。"),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n"),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_update_project_memory_persists_entries_and_surfaces_in_context(self) -> None:
    initial_detail = get_project_detail(self.settings, self.project.id)
    auto_entries = [
      item for item in initial_detail.story_overview.memory_entries
      if item.source == "auto"
    ]
    self.assertTrue(auto_entries)

    detail = update_project_memory(
      self.settings,
      self.project.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(category="硬规则", title="世界规则", content="铜钥匙只能在涨潮前一小时启用。"),
          ProjectMemoryEntryInput(category="警告", title="别写偏", content="不要把主角写成主动暴露身份的人。"),
        ]
      ),
    )

    manual_entries = [
      item for item in detail.story_overview.memory_entries
      if item.source == "manual"
    ]
    auto_entries = [
      item for item in detail.story_overview.memory_entries
      if item.source == "auto"
    ]
    self.assertEqual(len(manual_entries), 2)
    self.assertTrue(auto_entries)

    reloaded = get_project_detail(self.settings, self.project.id)
    reloaded_manual = [
      item for item in reloaded.story_overview.memory_entries
      if item.source == "manual"
    ]
    reloaded_auto = [
      item for item in reloaded.story_overview.memory_entries
      if item.source == "auto"
    ]
    self.assertEqual(reloaded_manual[0].category, "硬规则")
    self.assertTrue(any(item.title == "最近推进" for item in reloaded_auto))

    bundle = build_project_context_bundle(self.settings, self.project.id)
    self.assertIn("项目记忆：", bundle.context_text)
    self.assertIn("作者明确要求 / 硬规则 / 世界规则", bundle.context_text)
    self.assertIn("系统整理 / 连续性 / 最近推进", bundle.context_text)
    self.assertIn("铜钥匙只能在涨潮前一小时启用", bundle.context_text)

  def test_project_memory_creates_editable_files_and_audit_log(self) -> None:
    update_project_memory(
      self.settings,
      self.project.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(category="硬规则", title="世界规则", content="铜钥匙只能在涨潮前一小时启用。"),
          ProjectMemoryEntryInput(category="警告", title="别写偏", content="不要把主角写成主动暴露身份的人。"),
        ]
      ),
    )

    project_dir = Path(self.project.path)
    memory_dir = project_dir / "project_memory"
    manual_files = sorted((memory_dir / "author").rglob("*.md"))
    auto_files = sorted((memory_dir / "system").rglob("*.md"))
    audit_path = memory_dir / "audit.jsonl"

    self.assertGreaterEqual(len(manual_files), 2)
    self.assertTrue(any("canon" in item.parts for item in manual_files))
    self.assertTrue(any(item.name == "auto-recent-progress.md" for item in auto_files))
    self.assertTrue(audit_path.exists())

    audit_text = audit_path.read_text(encoding="utf-8")
    self.assertIn("manual_update", audit_text)
    self.assertIn("auto_sync", audit_text)

  def test_direct_memory_file_edit_surfaces_in_context(self) -> None:
    update_project_memory(
      self.settings,
      self.project.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(category="警告", title="别写偏", content="不要把主角写成主动暴露身份的人。"),
        ]
      ),
    )

    project_dir = Path(self.project.path)
    memory_file = next((project_dir / "project_memory" / "author" / "warnings").glob("*.md"))
    text = memory_file.read_text(encoding="utf-8")
    head, _separator, _body = text.partition("\n---\n")
    memory_file.write_text(
      f"{head}\n---\n\n人工改过的记忆会进上下文。\n",
      encoding="utf-8",
    )

    bundle = build_project_context_bundle(self.settings, self.project.id)
    self.assertIn("人工改过的记忆会进上下文", bundle.context_text)
    audit_text = (project_dir / "project_memory" / "audit.jsonl").read_text(encoding="utf-8")
    self.assertIn("external_edit", audit_text)
