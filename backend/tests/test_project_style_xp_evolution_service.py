from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import ChapterUpdateRequest, CreateProjectRequest, ObsidianVaultConfig
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.project_service import create_project, update_chapter_content, update_project_obsidian_config
from novel_backend.services.project_style_xp_evolution_service import (
  build_project_style_xp_prompt,
  load_project_style_xp_state,
  style_xp_evolution_path,
)


class ProjectStyleXpEvolutionServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt")
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self.project = create_project(
      self.settings,
      CreateProjectRequest(name="文风学习", genre="悬疑", target_chapters=3, target_words=30000),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_saved_chapters_activate_repeated_style_and_xp_rules(self) -> None:
    first = (
      "# 第一章 雨夜\n"
      "雨停了。\n"
      "林追握紧钥匙。\n"
      "门后没有声音。\n"
      "他没有回头。\n"
    )
    second = (
      "# 第二章 白门\n"
      "雾散了。\n"
      "林追把钥匙藏进袖口。\n"
      "门内有人轻轻吸气。\n"
      "他还是没有回头。\n"
    )

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content=first, xp_preset="悬疑推进"),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-002",
      ChapterUpdateRequest(content=second, xp_preset="悬疑推进"),
    )

    project_dir = Path(self.project.path)
    self.assertTrue(style_xp_evolution_path(project_dir).exists())
    state = load_project_style_xp_state(project_dir)
    active_rules = [item for item in state["rules"] if item["status"] == "active"]
    self.assertGreaterEqual(len(active_rules), 1)
    self.assertTrue(any(item["kind"] == "style" for item in active_rules))
    self.assertTrue(any(item["kind"] == "xp" for item in active_rules))

    prompt = build_project_style_xp_prompt(project_dir, task_key="chapter")
    self.assertIn("系统学习版文风 / XP", prompt)
    self.assertIn("优先级低于作者明确要求、手工文风和手工 XP", prompt)
    self.assertIn("证据章节 2 个", prompt)

  def test_obsidian_style_xp_properties_enter_prompt_without_body(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-style-xp-properties"
    style_dir = vault_dir / "Style"
    xp_dir = vault_dir / "XP"
    style_dir.mkdir(parents=True)
    xp_dir.mkdir(parents=True)
    (style_dir / "动作停顿规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "chapter_range: 58+",
          "style_rule: 动作之前先给感官锚点，动作之后保留人物短促反应，让每个信息点都贴着可见行动出现。",
          "sentence_rhythm: 长句只用于观察，关键转折使用短句。",
          "imagery: 潮声、灯影和潮湿金属味作为同一组意象反复出现。",
          "dialogue_rule: 对白旁边必须有动作或沉默反应。",
          "avoid_style: 不要用抽象评价代替可见动作。",
          "examples: 林追先听见潮声，再看见灯影压低。",
          "applies_to: 章节生成 / 改稿",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (xp_dir / "线索压力检查.md").write_text(
      "\n".join(
        [
          "---",
          "type: xp_rule",
          "status: canonical",
          "chapter_range: 58+",
          "xp_rule: 每个线索出现后都要保留一个未解释压力。",
          "precheck: 生成前确认本章线索不能提前兑现。",
          "postcheck: 生成后检查章尾是否留下可追问问题。",
          "workflow: 先写可见线索，再写人物反应，最后推迟解释。",
          "avoid_xp: 不要在同一章解释线索来源。",
          "examples: 账本出现，但不说明谁放下。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )

    detail = update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=58,
    )
    self.assertIn("Obsidian 文风 / XP 参考", prompt)
    self.assertIn("动作停顿规则", prompt)
    self.assertIn("文风规则：动作之前先给感官锚点", prompt)
    self.assertIn("禁用写法：不要用抽象评价代替可见动作。", prompt)
    self.assertIn("适用场景：章节生成 / 改稿", prompt)
    self.assertIn("线索压力检查", prompt)
    self.assertIn("XP 规则：每个线索出现后都要保留一个未解释压力。", prompt)
    self.assertIn("生成后检查：生成后检查章尾是否留下可追问问题。", prompt)
    self.assertIn("禁用做法：不要在同一章解释线索来源。", prompt)

    early_prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=57,
    )
    self.assertNotIn("动作停顿规则", early_prompt)
    self.assertNotIn("线索压力检查", early_prompt)

  def test_global_obsidian_style_xp_properties_enter_prompt_without_target_chapter(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-global-style-xp-properties"
    style_dir = vault_dir / "Style"
    xp_dir = vault_dir / "XP"
    style_dir.mkdir(parents=True)
    xp_dir.mkdir(parents=True)
    (style_dir / "全局动作规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "style_rule: 所有章节都先写可见动作，再写人物判断。",
          "avoid_style: 不要用概念词替代场面变化。",
          "examples: 她先停在门边，才意识到潮声变轻。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (xp_dir / "全局复查规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: xp_rule",
          "status: canonical",
          "xp_rule: 每章完成后检查因果链是否由动作推动。",
          "postcheck: 复查最后三段是否留下下一章可追问压力。",
          "avoid_xp: 不要把伏笔解释成设定说明。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (style_dir / "后段专用规则.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "chapter_range: 58+",
          "style_rule: 第 58 章之后才使用潮汐审判意象。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )

    detail = update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    prompt = build_project_style_xp_prompt(Path(self.project.path), project_detail=detail)
    self.assertIn("Obsidian 文风 / XP 参考", prompt)
    self.assertIn("全局动作规则", prompt)
    self.assertIn("文风规则：所有章节都先写可见动作，再写人物判断。", prompt)
    self.assertIn("禁用写法：不要用概念词替代场面变化。", prompt)
    self.assertIn("全局复查规则", prompt)
    self.assertIn("XP 规则：每章完成后检查因果链是否由动作推动。", prompt)
    self.assertIn("生成后检查：复查最后三段是否留下下一章可追问压力。", prompt)
    self.assertNotIn("后段专用规则", prompt)
    self.assertNotIn("潮汐审判意象", prompt)

  def test_chapter_scoped_obsidian_style_xp_rules_outrank_crowded_global_rules(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-crowded-style-xp"
    style_dir = vault_dir / "Style"
    xp_dir = vault_dir / "XP"
    style_dir.mkdir(parents=True)
    xp_dir.mkdir(parents=True)
    for index in range(8):
      (style_dir / f"{index:02d}全局文风规则.md").write_text(
        "\n".join(
          [
            "---",
            "type: style_rule",
            "status: canonical",
            f"style_rule: 全局规则 {index} 要求动作先于判断。",
            "---",
            "",
          ]
        ),
        encoding="utf-8",
      )
    (style_dir / "99第58章专属文风.md").write_text(
      "\n".join(
        [
          "---",
          "type: style_rule",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 58",
          "style_rule: 第58章必须先写银潮灯在雾里失去反光，再写人物判断。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )
    (xp_dir / "99第58章专属复查.md").write_text(
      "\n".join(
        [
          "---",
          "type: xp_rule",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 58",
          "xp_rule: 第58章生成后检查银潮灯线索是否留到章尾。",
          "---",
          "",
        ]
      ),
      encoding="utf-8",
    )

    detail = update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=58,
    )
    self.assertIn("第58章专属文风", prompt)
    self.assertIn("第58章必须先写银潮灯在雾里失去反光", prompt)
    self.assertIn("第58章专属复查", prompt)
    self.assertIn("第58章生成后检查银潮灯线索是否留到章尾", prompt)

    early_prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=57,
    )
    self.assertNotIn("第58章专属文风", early_prompt)
    self.assertNotIn("第58章专属复查", early_prompt)


if __name__ == "__main__":
  unittest.main()
