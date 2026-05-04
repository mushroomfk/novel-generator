from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import BrainstormMessage, CreateProjectRequest, ModelConfig, SkillMaterializeRequest
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.project_service import create_project
from novel_backend.services.skill_service import list_skill_catalog, materialize_skill, suggest_reusable_skill


class SkillServiceTestCase(unittest.TestCase):
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
        name="技能沉淀回归",
        genre="港口悬疑",
        target_chapters=5,
        target_words=80000,
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_list_skill_catalog_reads_seeded_skill_files(self) -> None:
    catalog = list_skill_catalog(self.settings)

    self.assertIn("全部", catalog.filters)
    self.assertIn("章节", catalog.filters)
    self.assertGreaterEqual(len(catalog.sections), 3)

    first_section = catalog.sections[0]
    self.assertEqual(first_section.title, "核心技能")
    skill_ids = [item.id for section in catalog.sections for item in section.items]
    self.assertIn("brainstorm", skill_ids)
    self.assertIn("architecture-stepper", skill_ids)
    self.assertIn("character-replica", skill_ids)

    consistency = next(item for section in catalog.sections for item in section.items if item.id == "consistency")
    self.assertTrue(consistency.requires_project)
    self.assertTrue(consistency.requires_chapter)

    character_replica = next(item for section in catalog.sections for item in section.items if item.id == "character-replica")
    self.assertFalse(character_replica.requires_project)
    self.assertFalse(character_replica.requires_chapter)

    chapter_scenes = next(item for section in catalog.sections for item in section.items if item.id == "chapter-scenes")
    self.assertEqual(chapter_scenes.behavior.panel, "chapter-workflow")
    self.assertEqual(chapter_scenes.behavior.mode, "scenes")

  def test_list_skill_catalog_reads_custom_markdown_skill(self) -> None:
    skill_path = self.settings.data_dir / "skills" / "user-skills" / "user-harbor-rewrite" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
      (
        "---\n"
        "name: 港口去腔整理\n"
        "description: 只动语言和节奏，不改剧情事实。\n"
        "version: 0.1.0\n"
        "skill_id: user-harbor-rewrite\n"
        "section_id: user-skills\n"
        "section_title: 用户沉淀\n"
        "section_description: 聊天里沉淀下来的可复用技能。\n"
        "category: 用户技能\n"
        "badge: 沉\n"
        "accent: smoke\n"
        "source: custom\n"
        "panel: conversation-skill\n"
        "updated_at: 2026-04-17T10:00:00+00:00\n"
        "verification_summary: 已完成一次本地自检。\n"
        "requires_project: true\n"
        "requires_chapter: true\n"
        "scenes:\n"
        "  - 去 AI\n"
        "  - 语言整理\n"
        "usage:\n"
        "  - 适合保剧情只动语言。\n"
        "limitations:\n"
        "  - 古风对白约束还不够细。\n"
        "---\n"
        "# 港口去腔整理\n\n"
        "## 适用场景\n- 适合保剧情只动语言。\n\n"
        "## 输入要求\n- 给出章节和重点。\n\n"
        "## 执行步骤\n1. 先识别模板腔。\n2. 再压句。\n3. 最后回看事实是否没动。\n\n"
        "## 输出要求\n- 先给结论，再给修改点。\n\n"
        "## 边界\n- 古风对白约束还不够细。\n"
      ),
      encoding="utf-8",
    )

    catalog = list_skill_catalog(self.settings)
    user_section = next(section for section in catalog.sections if section.id == "user-skills")
    item = next(skill for skill in user_section.items if skill.id == "user-harbor-rewrite")

    self.assertEqual(user_section.title, "用户沉淀")
    self.assertEqual(item.behavior.panel, "conversation-skill")
    self.assertEqual(item.source, "custom")
    self.assertTrue(item.requires_chapter)
    self.assertIn("适合保剧情只动语言。", item.usage)
    self.assertIn("古风对白约束还不够细。", item.limitations)

  def test_materialize_skill_creates_and_updates_custom_skill(self) -> None:
    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      created = materialize_skill(
        self.settings,
        SkillMaterializeRequest(
          project_id=self.project.id,
          messages=[
            BrainstormMessage(role="user", content="以后我提章节去 AI，你都按保剧情、先揪模板腔、再压句、最后复核事实的顺序处理。"),
            BrainstormMessage(role="assistant", content="可以，先判断哪里是模板腔，再逐段压短解释句，最后核对剧情事实和人物关系没变。"),
          ],
          action="create",
          selected_chapter_id="chapter-001",
        ),
      )

    self.assertEqual(created.action, "create")
    self.assertTrue(created.saved_path.endswith("SKILL.md"))
    self.assertTrue(Path(created.saved_path).exists())
    self.assertEqual(created.skill.behavior.panel, "conversation-skill")
    self.assertTrue(created.skill.requires_chapter)
    self.assertIn("## 最近一次回归", created.skill_markdown)
    self.assertTrue(created.verification.checks)

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": (
                '{"name":"以后我提章节去 AI","description":"保剧情前提下整理章节去 AI 的固定流程。",'
                '"category":"用户技能","scenes":["去 AI","章节"],'
                '"usage":["适合章节正文去 AI。"],"limitations":["古风文本还需要继续补规则。"],'
                '"body_markdown":"# 以后我提章节去 AI\\n\\n## 适用场景\\n- 适合章节正文去 AI。\\n\\n'
                '## 输入要求\\n- 给出章节正文和不能动的信息。\\n\\n'
                '## 执行步骤\\n1. 先识别模板腔。\\n2. 再压句并收紧解释。\\n3. 最后保留人物口气，不把对白改成一个声线。\\n\\n'
                '## 输出要求\\n- 先给判断，再给修订建议。\\n\\n## 边界\\n- 古风文本还需要继续补规则。"}'
              )
            }
          }
        ]
      },
    ):
      updated = materialize_skill(
        self.settings,
        SkillMaterializeRequest(
          project_id=self.project.id,
          messages=[
            BrainstormMessage(role="user", content="这套技能再补一条，处理对白时别把人物口气磨平。"),
            BrainstormMessage(role="assistant", content="可以并进去，语言收紧时保留人物口气，不把对白改成一个声线。"),
          ],
          action="iterate",
          skill_id=created.skill.id,
          skill_name=created.skill.name,
          selected_chapter_id="",
        ),
      )

    self.assertEqual(updated.action, "iterate")
    self.assertEqual(updated.skill.id, created.skill.id)
    self.assertTrue(updated.skill.requires_chapter)
    self.assertIn("version: 0.1.1", updated.skill_markdown)
    self.assertIn("保留人物口气", updated.skill_markdown)

  def test_materialize_skill_update_failure_keeps_existing_file(self) -> None:
    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      created = materialize_skill(
        self.settings,
        SkillMaterializeRequest(
          project_id=self.project.id,
          messages=[
            BrainstormMessage(role="user", content="以后我提章节去 AI，你都按保剧情、先揪模板腔、再压句、最后复核事实的顺序处理。"),
            BrainstormMessage(role="assistant", content="可以，先判断哪里是模板腔，再逐段压短解释句，最后核对剧情事实和人物关系没变。"),
          ],
          action="create",
          selected_chapter_id="chapter-001",
        ),
      )

    original_markdown = Path(created.saved_path).read_text(encoding="utf-8")

    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("model-down")):
      with self.assertRaises(HTTPException) as raised:
        materialize_skill(
          self.settings,
          SkillMaterializeRequest(
            project_id=self.project.id,
            messages=[
              BrainstormMessage(role="user", content="再补一条：处理对白时别把人物口气磨平。"),
              BrainstormMessage(role="assistant", content="可以并进去，保留人物口气。"),
            ],
            action="iterate",
            skill_id=created.skill.id,
            skill_name=created.skill.name,
            selected_chapter_id="",
          ),
        )

    self.assertEqual(raised.exception.status_code, 502)
    self.assertEqual(raised.exception.detail["code"], "skill_materialize_failed")
    self.assertIn("原技能未改动", raised.exception.detail["message"])
    self.assertEqual(Path(created.saved_path).read_text(encoding="utf-8"), original_markdown)

  def test_suggest_reusable_skill_prefers_existing_custom_skill_for_iteration(self) -> None:
    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      created = materialize_skill(
        self.settings,
        SkillMaterializeRequest(
          project_id=self.project.id,
          messages=[
            BrainstormMessage(role="user", content="以后碰到章节去 AI，就按保剧情、压句、回查事实这套流程做。"),
            BrainstormMessage(role="assistant", content="可以整理成固定流程：先识别模板腔，再压短句子，最后核对事实不动。"),
          ],
          action="create",
          selected_chapter_id="chapter-001",
        ),
      )

    suggestion = suggest_reusable_skill(
      self.settings,
      [
        BrainstormMessage(role="user", content="这次还是章节去 AI，不过再加一条：对白别写成一个口气。"),
        BrainstormMessage(role="assistant", content="可以把对白口气也纳入这套流程。"),
      ],
      "可以把对白口气也纳入这套流程。",
      created.skill.id,
    )

    self.assertIsNotNone(suggestion)
    self.assertEqual(suggestion.action, "iterate")
    self.assertEqual(suggestion.target_skill_id, created.skill.id)


if __name__ == "__main__":
  unittest.main()
