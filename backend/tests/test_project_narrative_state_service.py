from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  ChapterUpdateRequest,
  CreateProjectRequest,
  ObsidianVaultConfig,
  StoryDocumentUpdateRequest,
  StoryEntityReference,
)
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.continuity_guard_service import build_continuity_guard_context
from novel_backend.services.context_builder import build_project_context_bundle
from novel_backend.services.chapter_auto_repair_service import chapter_review_needs_auto_repair
from novel_backend.services.project_narrative_state_service import (
  _attach_maintenance_action_status,
  _obsidian_link_target_without_suffix,
  _obsidian_maintenance_summary,
  _text_content_hash,
  build_project_narrative_state_prompt,
  load_project_narrative_state,
  narrative_state_path,
  obsidian_maintenance_suggestion_available_for_chapter,
  record_project_narrative_state_observation,
  refresh_project_narrative_state_chapter_cards,
)
from novel_backend.services.project_style_xp_evolution_service import (
  build_project_style_xp_prompt,
  style_xp_evolution_path,
)
from novel_backend.services.self_evolution_service import build_agent_capability_context
from novel_backend.services.project_service import (
  create_project,
  confirm_project_obsidian_maintenance_merge,
  confirm_project_obsidian_maintenance_merges,
  get_project_detail,
  ignore_project_obsidian_maintenance_note,
  ignore_project_obsidian_maintenance_notes,
  publish_project_obsidian_maintenance_note,
  publish_project_obsidian_maintenance_notes,
  reopen_project_obsidian_maintenance_notes,
  reopen_project_obsidian_maintenance_note,
  search_project_knowledge,
  summarize_chapter_review_status,
  stage_project_obsidian_maintenance_draft,
  stage_project_obsidian_maintenance_drafts,
  sync_project_obsidian,
  update_chapter_content,
  update_project_obsidian_config,
  update_story_document,
)


class ProjectNarrativeStateServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt")
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self.project = create_project(
      self.settings,
      CreateProjectRequest(name="长篇账本", genre="悬疑", target_chapters=80, target_words=500000),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "character_design",
      StoryDocumentUpdateRequest(content="林追：追查旧船队真相的人。\n宋闻：知道铜钥匙身份秘密的人。"),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "plot_structure",
      StoryDocumentUpdateRequest(content="前段埋下铜钥匙身份秘密，中段揭开旧船队背叛线索，后段兑现真相。"),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "blueprint",
      StoryDocumentUpdateRequest(
        content="\n".join(
          f"第 {index} 章：推进铜钥匙线索，压住宋闻背叛秘密。"
          for index in range(1, 81)
        )
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_obsidian_link_target_uses_vault_slashes_on_windows_paths(self) -> None:
    self.assertEqual(
      _obsidian_link_target_without_suffix("Characters\\林追.md"),
      "Characters/林追",
    )

  def test_saved_chapter_updates_narrative_state_and_context_prompt(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-057",
      ChapterUpdateRequest(
        content=(
          "# 第五十七章 铜钥匙\n"
          "林追终于确认铜钥匙藏着旧船队身份秘密。\n"
          "宋闻没有说出背叛线索，只把真相的答案压回掌心。\n"
        ),
      ),
    )

    project_dir = Path(self.project.path)
    self.assertTrue(narrative_state_path(project_dir).exists())
    state = load_project_narrative_state(project_dir)
    self.assertTrue(state["debts"])
    self.assertTrue(any("铜钥匙" in item["content"] for item in state["debts"]))
    self.assertTrue(state["character_arcs"])
    self.assertTrue(any(item["name"] == "林追" for item in state["character_arcs"]))

    detail = get_project_detail(self.settings, self.project.id)
    prompt = build_project_narrative_state_prompt(project_dir, detail, "chapter-058")
    self.assertIn("叙事状态账本", prompt)
    self.assertIn("章节任务卡：第 58/80 章", prompt)
    self.assertIn("剧情债务", prompt)
    self.assertIn("人物弧线检查", prompt)

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-058",
      task_instruction="写第 58 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("叙事状态账本", bundle.context_text)
    self.assertIn("章节任务卡：第 58/80 章", bundle.context_text)

  def test_chapter_50_continuity_contract_merges_internal_state_and_recent_history(self) -> None:
    update_story_document(
      self.settings,
      self.project.id,
      "character_state",
      StoryDocumentUpdateRequest(content="第 49 章后，林追仍怀疑宋闻，不能突然完全信任他。"),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "global_summary",
      StoryDocumentUpdateRequest(content="旧船队背叛线已经浮出水面，母亲遗言还没有被完整解释。"),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-049",
      ChapterUpdateRequest(
        content=(
          "# 第四十九章 遗言断句\n"
          "林追在潮账里发现母亲遗言被宋闻删去半句。\n"
          "宋闻没有解释，只让他去找银潮灯背后的旧船队名单。\n"
        ),
      ),
    )
    model_payload = {
      "summary": "第 49 章把母亲遗言和旧船队名单并到同一条主线。",
      "debt_updates": [
        {
          "title": "母亲遗言",
          "kind": "promise",
          "status": "open",
          "content": "母亲遗言里缺失的半句必须改变林追对宋闻的判断。",
          "evidence": ["林追在潮账里发现母亲遗言被宋闻删去半句。"],
          "related_characters": ["林追", "宋闻"],
          "expected_payoff_range": [50, 54],
          "next_required_action": "第 50 章需要让遗言半句产生可见后果。",
          "risk_level": "high",
          "confidence": 0.9,
        }
      ],
      "character_arc_updates": [
        {
          "name": "林追",
          "phase": "信任摇摆",
          "current_state": "林追已经怀疑宋闻删改遗言。",
          "evidence": ["母亲遗言被宋闻删去半句。"],
          "unresolved_pressure": "林追想利用宋闻，但不能完全相信宋闻。",
          "required_next_check": "第 50 章检查林追是否仍保留对宋闻的怀疑。",
          "confidence": 0.86,
        }
      ],
      "contract_review": {
        "target_chapter_id": "chapter-049",
        "target_chapter_index": 49,
        "status": "passed",
        "score": 84,
        "passed": True,
        "satisfied": ["母亲遗言进入主线"],
        "missed": [],
        "revision_focus": [],
        "evidence": ["母亲遗言被宋闻删去半句。"],
      },
      "next_chapter_contract": {
        "target_chapter_id": "chapter-050",
        "target_chapter_index": 50,
        "objective": "让遗言半句逼迫林追重新判断宋闻，同时推进旧船队名单。",
        "required_beats": ["遗言半句造成一次行动选择", "林追和宋闻发生一次信任冲突"],
        "debts_to_advance": ["母亲遗言", "旧船队名单"],
        "debts_to_protect": ["最终背叛者身份"],
        "character_checks": ["林追不能突然完全信任宋闻"],
        "style_checks": ["保持悬疑压力，不直接解释最终背叛者"],
        "forbidden_moves": ["不要让宋闻直接交代完整真相"],
        "acceptance_checks": ["章末留下下一步调查银潮灯的选择"],
        "evidence_sources": ["第 49 章正文", "第 50 章蓝图"],
        "risk_notes": ["中段不能新增孤立悬念"],
      },
      "risk_notes": ["第 50 章需要处理遗言后果，不能重置为普通追查。"],
    }

    with patch(
      "novel_backend.services.project_narrative_state_service._model_available",
      return_value=True,
    ), patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      return_value=(json.dumps(model_payload, ensure_ascii=False), "review_model"),
    ):
      record_project_narrative_state_observation(
        Path(self.project.path),
        get_project_detail(self.settings, self.project.id),
        "chapter-049",
        settings=self.settings,
      )

    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-050")
    guard_context = build_continuity_guard_context(
      self.settings,
      project_id=self.project.id,
      project_detail=detail,
      chapter=chapter,
      instruction="写第 50 章，承接第 49 章遗言断句。",
    )

    self.assertIn("章节连续性合同", guard_context.contract_text)
    self.assertIn("第 50 / 80 章", guard_context.contract_text)
    self.assertIn("中段", guard_context.contract_text)
    self.assertIn("人物当前状态", guard_context.contract_text)
    self.assertIn("林追仍怀疑宋闻", guard_context.contract_text)
    self.assertIn("全书已发生事实", guard_context.contract_text)
    self.assertIn("第 49 章末尾", guard_context.contract_text)
    self.assertIn("章节合同", guard_context.contract_text)
    self.assertIn("遗言半句造成一次行动选择", guard_context.contract_text)
    self.assertIn("人物弧线检查", guard_context.contract_text)
    self.assertIn("连续性合同", guard_context.evidence_text)

    broken_detail = update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-050",
      ChapterUpdateRequest(content="# 第五十章 银潮灯\n码头起雾，陌生船工搬走货箱。\n"),
    )
    broken_review = next(item for item in broken_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-050")
    contract_dimension = next(item for item in broken_review.dimensions if item.id == "continuity_contract")
    self.assertTrue(any(item.title.startswith("缺少连续性合同项") for item in contract_dimension.issues))
    review_status = summarize_chapter_review_status(broken_detail, "chapter-050")
    self.assertGreaterEqual(review_status["continuity_contract_issue_count"], 1)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

  def test_active_style_xp_rules_generate_obsidian_maintenance_suggestions(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-style-xp-maintenance"
    vault_dir.mkdir()
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    style_note = next(
      item for item in state["obsidian_maintenance_suggestions"] if item["kind"] == "create_style_rule_note"
    )
    xp_note = next(
      item for item in state["obsidian_maintenance_suggestions"] if item["kind"] == "create_xp_rule_note"
    )
    self.assertEqual(style_note["priority"], "low")
    self.assertEqual(xp_note["priority"], "low")
    self.assertTrue(style_note["suggested_path"].startswith("Style/"))
    self.assertTrue(xp_note["suggested_path"].startswith("XP/"))
    self.assertIn("type: style_rule", style_note["draft_markdown"])
    self.assertIn("type: xp_rule", xp_note["draft_markdown"])
    self.assertIn("style_rule:", style_note["draft_markdown"])
    self.assertIn("applies_to:", style_note["draft_markdown"])
    self.assertIn("evidence_count:", style_note["draft_markdown"])
    self.assertIn("confidence:", style_note["draft_markdown"])
    self.assertIn("xp_rule:", xp_note["draft_markdown"])
    self.assertIn("postcheck:", xp_note["draft_markdown"])
    self.assertIn("source_chapters:", style_note["draft_markdown"])
    self.assertIn("reveal_after_chapter: 1", style_note["draft_markdown"])
    self.assertIn("gaoxia_maintenance_id:", style_note["draft_markdown"])

    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, style_note["id"])
    self.assertEqual(staged["status"], "staged")
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, style_note["id"])
    self.assertEqual(published["status"], "published")
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == published["vault_relative_path"]
    )
    self.assertEqual(published_note.note_type, "style_rule")
    prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=3,
    )
    self.assertIn("Obsidian 文风 / XP 参考", prompt)
    self.assertIn(published["vault_relative_path"], prompt)

    vault_note_path = Path(published["vault_path"])
    published_text = vault_note_path.read_text(encoding="utf-8")
    self.assertIn("source_ids:", published_text)
    self.assertIn("style_rule:", published_text)
    self.assertIn("applies_to:", published_text)
    edited_lines = []
    for line in published_text.splitlines():
      if line.startswith("gaoxia_maintenance_id:") or line.startswith("gaoxia_maintenance_kind:"):
        continue
      if line.startswith("summary:"):
        edited_lines.append('summary: "动作、停顿和物件之间保持可见衔接"')
      elif line.startswith("style_rule:"):
        edited_lines.append('style_rule: "动作、停顿和物件之间保持可见衔接。"')
      elif line.startswith("# "):
        edited_lines.append("# 作者整理后的文风原则")
      elif line.startswith("文风规则："):
        edited_lines.append("文风规则：动作、停顿和物件之间保持可见衔接。")
      elif line.startswith("识别依据："):
        edited_lines.append("识别依据：作者已人工整理为正式文风原则。")
      else:
        edited_lines.append(line)
    renamed_style_path = vault_dir / "Style" / "作者整理后的文风原则.md"
    renamed_style_path.parent.mkdir(parents=True, exist_ok=True)
    vault_note_path.rename(renamed_style_path)
    renamed_style_path.write_text("\n".join(edited_lines) + "\n", encoding="utf-8")
    edited_detail = sync_project_obsidian(self.settings, self.project.id)
    edited_prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=edited_detail,
      chapter_index=3,
    )
    self.assertIn("动作、停顿和物件之间保持可见衔接", edited_prompt)
    edited_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["id"] == style_note["id"]
        for item in edited_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_pending_style_xp_draft_preview_enters_agent_context(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-style-xp-pending-preview"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    project_dir = Path(self.project.path)
    style_path = style_xp_evolution_path(project_dir)
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "updated_at": "2026-06-01T00:00:00+00:00",
          "active_version": 1,
          "rules": [
            {
              "id": "style-visible-causality",
              "kind": "style",
              "signal": "manual-test-style",
              "status": "active",
              "content": "动作停顿之间保留可见因果。",
              "rationale": "第 1 章和第 2 章都用动作承接信息。",
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
              "rationale": "第 1 章和第 2 章都在章尾保留压力。",
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

    detail = get_project_detail(self.settings, self.project.id)
    pending_prompt = build_project_narrative_state_prompt(
      project_dir,
      detail,
      "chapter-003",
    )
    self.assertIn("Obsidian 待审软约束", pending_prompt)
    self.assertIn("[文风]", pending_prompt)
    self.assertIn("[XP]", pending_prompt)
    self.assertIn("Obsidian 待审草稿", pending_prompt)
    self.assertIn("文风预览", pending_prompt)
    self.assertIn("规则：动作停顿之间保留可见因果。", pending_prompt)
    self.assertIn("适用：章节生成 / 改稿", pending_prompt)
    self.assertIn("XP预览", pending_prompt)
    self.assertIn("规则：生成后确认线索压力留到章尾。", pending_prompt)
    self.assertIn("证据：2条", pending_prompt)

    capability_context = build_agent_capability_context(
      project_dir,
      project_detail=detail,
      chapter_index=3,
    )
    self.assertIn("目标章节 Obsidian 待审软约束：第 3 章。", capability_context)
    self.assertIn("[文风]", capability_context)
    self.assertIn("[XP]", capability_context)
    self.assertIn("Obsidian 维护建议", capability_context)
    self.assertIn("文风预览", capability_context)
    self.assertIn("XP预览", capability_context)
    self.assertIn("动作停顿之间保留可见因果", capability_context)
    self.assertIn("生成后确认线索压力留到章尾", capability_context)

    state = load_project_narrative_state(project_dir)
    style_note = next(
      item for item in state["obsidian_maintenance_suggestions"] if item["kind"] == "create_style_rule_note"
    )
    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, style_note["id"])
    staged_path = Path(staged["draft_path"])
    original_text = staged_path.read_text(encoding="utf-8")
    try:
      staged_path.write_text(
        "\n".join(
          [
            "# 作者手工整理的文风规则",
            "",
            "来源章节：第 1 章、第 2 章",
            "文风规则：动作和停顿之间要留下可见因果。",
            "使用建议：改稿时先看人物动作是否承担信息。",
            "",
          ]
        ),
        encoding="utf-8",
      )
      body_only_detail = get_project_detail(self.settings, self.project.id)
      body_only_context = build_agent_capability_context(
        project_dir,
        project_detail=body_only_detail,
        chapter_index=3,
      )
      self.assertIn("文风预览", body_only_context)
      self.assertIn("动作和停顿之间要留下可见因果", body_only_context)
      self.assertIn("改稿时先看人物动作是否承担信息", body_only_context)
    finally:
      staged_path.write_text(original_text, encoding="utf-8")

  def test_style_xp_maintenance_uses_latest_source_chapter_boundary(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-style-xp-late-source"
    vault_dir.mkdir()
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 雨账\n"
          "雨停了。\n"
          "林追握紧钥匙。\n"
          "门后没有声音。\n"
          "他没有回头。\n"
        ),
        xp_preset="悬疑推进",
      ),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-060",
      ChapterUpdateRequest(
        content=(
          "# 第六十章 白门\n"
          "雾散了。\n"
          "林追把钥匙藏进袖口。\n"
          "门内有人轻轻吸气。\n"
          "他还是没有回头。\n"
        ),
        xp_preset="悬疑推进",
      ),
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    style_note = next(
      item for item in state["obsidian_maintenance_suggestions"] if item["kind"] == "create_style_rule_note"
    )
    xp_note = next(
      item for item in state["obsidian_maintenance_suggestions"] if item["kind"] == "create_xp_rule_note"
    )
    self.assertIn("source_chapters:", style_note["draft_markdown"])
    self.assertIn("  - 58", style_note["draft_markdown"])
    self.assertIn("  - 60", style_note["draft_markdown"])
    self.assertIn("reveal_after_chapter: 59", style_note["draft_markdown"])
    self.assertIn("reveal_after_chapter: 59", xp_note["draft_markdown"])
    self.assertFalse(
      obsidian_maintenance_suggestion_available_for_chapter(
        style_note,
        59,
        Path(self.project.path),
      )
    )
    self.assertTrue(
      obsidian_maintenance_suggestion_available_for_chapter(
        style_note,
        60,
        Path(self.project.path),
      )
    )

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, style_note["id"])
    detail = get_project_detail(self.settings, self.project.id)
    chapter_59_prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=59,
    )
    self.assertNotIn(published["vault_relative_path"], chapter_59_prompt)
    chapter_60_prompt = build_project_style_xp_prompt(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=60,
    )
    self.assertIn(published["vault_relative_path"], chapter_60_prompt)

  def test_model_editor_adds_chapter_contract_to_next_chapter_prompt(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-057",
      ChapterUpdateRequest(
        content=(
          "# 第五十七章 铜钥匙\n"
          "林追终于确认铜钥匙藏着旧船队身份秘密。\n"
          "宋闻承认母亲遗言里还压着旧船队背叛线索。\n"
        ),
      ),
    )
    model_payload = {
      "summary": "第 57 章把铜钥匙和母亲遗言并到同一条主线。",
      "debt_updates": [
        {
          "title": "母亲遗言",
          "kind": "promise",
          "status": "open",
          "content": "母亲遗言里还有旧船队背叛线索。",
          "evidence": ["宋闻承认母亲遗言里还压着旧船队背叛线索。"],
          "related_characters": ["林追", "宋闻"],
          "expected_payoff_range": [58, 64],
          "next_required_action": "第 58 章需要让遗言线索产生可见后果。",
          "risk_level": "high",
          "confidence": 0.86,
        }
      ],
      "character_arc_updates": [
        {
          "name": "林追",
          "phase": "选择转向",
          "current_state": "林追已经确认铜钥匙身份秘密。",
          "evidence": ["林追终于确认铜钥匙藏着旧船队身份秘密。"],
          "unresolved_pressure": "林追需要决定是否相信宋闻。",
          "required_next_check": "第 58 章检查林追是否因遗言改变行动。",
          "confidence": 0.82,
        }
      ],
      "contract_review": {
        "target_chapter_id": "chapter-057",
        "target_chapter_index": 57,
        "status": "passed",
        "score": 84,
        "passed": True,
        "satisfied": ["铜钥匙身份秘密已经推进"],
        "missed": [],
        "revision_focus": [],
        "evidence": ["林追终于确认铜钥匙藏着旧船队身份秘密。"],
      },
      "next_chapter_contract": {
        "target_chapter_id": "chapter-058",
        "target_chapter_index": 58,
        "objective": "让母亲遗言逼迫林追重新判断宋闻，同时推进旧船队背叛线。",
        "required_beats": ["遗言出现可验证的新信息", "林追和宋闻发生一次立场碰撞"],
        "debts_to_advance": ["母亲遗言", "旧船队背叛线索"],
        "debts_to_protect": ["铜钥匙最终身份"],
        "character_checks": ["林追不能无条件相信宋闻"],
        "style_checks": ["保留悬疑压力，不直接解释最终真相"],
        "forbidden_moves": ["不要让遗言只作为气氛词出现"],
        "acceptance_checks": ["章末留下一个新的行动选择"],
        "evidence_sources": ["第 57 章正文", "第 58 章蓝图"],
        "risk_notes": ["中段不能新增孤立悬念"],
      },
      "risk_notes": ["第 58 章需要兑现推进，不能重复追查。"],
    }

    with patch(
      "novel_backend.services.project_narrative_state_service._model_available",
      return_value=True,
    ), patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      return_value=(json.dumps(model_payload, ensure_ascii=False), "review_model"),
    ):
      state = record_project_narrative_state_observation(
        Path(self.project.path),
        get_project_detail(self.settings, self.project.id),
        "chapter-057",
        settings=self.settings,
      )

    self.assertTrue(state["model_reviews"])
    self.assertTrue(state["chapter_contracts"])
    self.assertTrue(any(item["target_chapter_id"] == "chapter-058" for item in state["chapter_contracts"]))
    self.assertTrue(any("母亲遗言" in item["title"] for item in state["debts"]))

    detail = get_project_detail(self.settings, self.project.id)
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")
    self.assertIn("章节合同", prompt)
    self.assertIn("母亲遗言", prompt)
    self.assertIn("不要让遗言只作为气氛词出现", prompt)

  def test_model_chapter_contract_becomes_obsidian_plan_draft(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-contract-draft"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-057",
      ChapterUpdateRequest(
        content=(
          "# 第五十七章 铜钥匙\n"
          "林追终于确认铜钥匙藏着旧船队身份秘密。\n"
          "宋闻承认母亲遗言里还压着旧船队背叛线索。\n"
        ),
      ),
    )
    model_payload = {
      "summary": "第 57 章把铜钥匙和母亲遗言并到同一条主线。",
      "debt_updates": [],
      "character_arc_updates": [],
      "contract_review": {
        "target_chapter_id": "chapter-057",
        "target_chapter_index": 57,
        "status": "passed",
        "score": 84,
        "passed": True,
        "satisfied": ["铜钥匙身份秘密已经推进"],
        "missed": [],
        "revision_focus": [],
        "evidence": ["林追终于确认铜钥匙藏着旧船队身份秘密。"],
      },
      "next_chapter_contract": {
        "target_chapter_id": "chapter-058",
        "target_chapter_index": 58,
        "objective": "让母亲遗言逼迫林追重新判断宋闻，同时推进旧船队背叛线。",
        "required_beats": ["遗言出现可验证的新信息", "林追和宋闻发生一次立场碰撞"],
        "debts_to_advance": ["母亲遗言", "旧船队背叛线索"],
        "debts_to_protect": ["铜钥匙最终身份"],
        "character_checks": ["林追不能无条件相信宋闻"],
        "style_checks": ["保留悬疑压力，不直接解释最终真相"],
        "forbidden_moves": ["不要让遗言只作为气氛词出现"],
        "acceptance_checks": ["章末留下一个新的行动选择"],
        "evidence_sources": ["第 57 章正文", "第 58 章蓝图"],
        "risk_notes": ["中段不能新增孤立悬念"],
      },
      "risk_notes": ["第 58 章需要兑现推进，不能重复追查。"],
    }

    with patch(
      "novel_backend.services.project_narrative_state_service._model_available",
      return_value=True,
    ), patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      return_value=(json.dumps(model_payload, ensure_ascii=False), "review_model"),
    ):
      state = record_project_narrative_state_observation(
        Path(self.project.path),
        get_project_detail(self.settings, self.project.id),
        "chapter-057",
        settings=self.settings,
      )

    contract_note = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_contract_note"
    )
    self.assertEqual(contract_note["priority"], "medium")
    self.assertEqual(contract_note["status"], "staged")
    self.assertTrue(contract_note["auto_staged"])
    self.assertTrue(contract_note["suggested_path"].startswith("Plans/第058章-章节合同-"))
    self.assertIn("type: chapter_contract", contract_note["draft_markdown"])
    self.assertIn("chapter_range: 第 58 章", contract_note["draft_markdown"])
    self.assertIn("source_chapters:", contract_note["draft_markdown"])
    self.assertIn("gaoxia_maintenance_id:", contract_note["draft_markdown"])
    self.assertIn("gaoxia_maintenance_kind: create_chapter_contract_note", contract_note["draft_markdown"])
    self.assertIn("让母亲遗言逼迫林追重新判断宋闻", contract_note["draft_markdown"])
    self.assertIn("遗言出现可验证的新信息", contract_note["draft_markdown"])
    draft_path = Path(contract_note["draft_path"])
    self.assertTrue(draft_path.exists())
    draft_text = draft_path.read_text(encoding="utf-8")
    self.assertIn("不要让遗言只作为气氛词出现", draft_text)

    detail = get_project_detail(self.settings, self.project.id)
    pending_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")
    self.assertIn("Obsidian 待审软约束", pending_prompt)
    self.assertIn("[章节合同] 整理章节合同：第 58 章", pending_prompt)
    self.assertIn("Obsidian 待审草稿", pending_prompt)
    self.assertIn("待审草稿只提示资料维护状态，不能当作 Vault 正式设定引用。", pending_prompt)
    self.assertIn("整理章节合同：第 58 章", pending_prompt)
    self.assertIn("Plans/第058章-章节合同-", pending_prompt)
    self.assertIn("合同预览", pending_prompt)
    self.assertIn("目标：让母亲遗言逼迫林追重新判断宋闻", pending_prompt)
    self.assertIn("节拍：遗言出现可验证的新信息", pending_prompt)
    self.assertIn("禁写：不要让遗言只作为气氛词出现", pending_prompt)
    self.assertIn("验收：章末留下一个新的行动选择", pending_prompt)
    chapter_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-058",
      task_pack_kind="chapter",
      task_instruction="写第 58 章",
    )
    self.assertIn("Obsidian 待审软约束", chapter_bundle.context_text)
    self.assertIn("[章节合同] 整理章节合同：第 58 章", chapter_bundle.context_text)
    capability_context = build_agent_capability_context(
      Path(self.project.path),
      project_detail=detail,
      auto_stage_obsidian_drafts=True,
      chapter_index=58,
    )
    self.assertIn("目标章节 Obsidian 待审软约束：第 58 章。", capability_context)
    self.assertIn("[章节合同] 整理章节合同：第 58 章", capability_context)
    self.assertIn("Obsidian 维护建议", capability_context)
    self.assertIn("整理章节合同：第 58 章", capability_context)
    self.assertIn("合同预览", capability_context)
    self.assertIn("目标：让母亲遗言逼迫林追重新判断宋闻", capability_context)
    self.assertIn("节拍：遗言出现可验证的新信息", capability_context)

    body_only_contract = (
      "# 第 58 章章节合同\n"
      "来源章节：第 57 章\n"
      "章节目标：让林追把遗言转成当下可验证的选择。\n\n"
      "必须完成的节拍：\n"
      "- 遗言提供另一个可查证物件\n\n"
      "禁止动作：\n"
      "- 不要直接公开铜钥匙身份\n\n"
      "验收项：\n"
      "- 章末让林追做出下一步行动选择\n"
    )
    try:
      draft_path.write_text(body_only_contract, encoding="utf-8")
      body_only_detail = get_project_detail(self.settings, self.project.id)
      body_only_prompt = build_project_narrative_state_prompt(Path(self.project.path), body_only_detail, "chapter-058")
      self.assertIn("合同预览", body_only_prompt)
      self.assertIn("目标：让林追把遗言转成当下可验证的选择。", body_only_prompt)
      self.assertIn("节拍：遗言提供另一个可查证物件", body_only_prompt)
      self.assertIn("禁写：不要直接公开铜钥匙身份", body_only_prompt)
      self.assertIn("验收：章末让林追做出下一步行动选择", body_only_prompt)
      body_only_capability = build_agent_capability_context(
        Path(self.project.path),
        project_detail=body_only_detail,
        auto_stage_obsidian_drafts=True,
        chapter_index=58,
      )
      self.assertIn("合同预览", body_only_capability)
      self.assertIn("目标：让林追把遗言转成当下可验证的选择。", body_only_capability)
      self.assertIn("节拍：遗言提供另一个可查证物件", body_only_capability)

      flow_frontmatter_contract = "\n".join(
        [
          "---",
          "type: chapter_contract",
          "status: canonical",
          "chapter_range: 第 58 章 # 手工改成更紧凑的写法",
          "objective: >",
          "  让林追先验证遗言真假，",
          "  再决定是否继续追查宋闻。",
          "required_beats: [{goal: 林追先确认遗言来源, evidence_sources: [{source_note: [[Clues/母亲遗言]], reason: 先验证来源}], acceptance: 不能提前公开铜钥匙身份}]",
          "forbidden_moves:",
          "  - {action: 直接公开铜钥匙身份, reason: 终局信息不能前置}",
          "acceptance_checks: [章末必须留下下一步行动选择, 宋闻必须保留可疑空间]",
          "---",
          "# 第 58 章章节合同",
          "",
          "作者手工改成 flow mapping 和 block scalar。",
        ]
      )
      draft_path.write_text(flow_frontmatter_contract, encoding="utf-8")
      flow_detail = get_project_detail(self.settings, self.project.id)
      flow_prompt = build_project_narrative_state_prompt(Path(self.project.path), flow_detail, "chapter-058")
      self.assertIn("[章节合同] 整理章节合同：第 58 章", flow_prompt)
      self.assertIn("合同预览", flow_prompt)
      self.assertIn("目标：让林追先验证遗言真假，", flow_prompt)
      self.assertIn("再决定是否继续追查宋闻。", flow_prompt)
      self.assertIn("节拍：目标：林追先确认遗言来源", flow_prompt)
      self.assertIn("禁写：动作：直接公开铜钥匙身份；理由：终局信息不能前置", flow_prompt)
      self.assertIn("验收：章末必须留下下一步行动选择", flow_prompt)
      flow_capability = build_agent_capability_context(
        Path(self.project.path),
        project_detail=flow_detail,
        auto_stage_obsidian_drafts=True,
        chapter_index=58,
      )
      self.assertIn("[章节合同] 整理章节合同：第 58 章", flow_capability)
      self.assertIn("合同预览", flow_capability)
      self.assertIn("目标：让林追先验证遗言真假，", flow_capability)
      self.assertIn("再决定是否继续追查宋闻。", flow_capability)
      self.assertIn("节拍：目标：林追先确认遗言来源", flow_capability)
    finally:
      draft_path.write_text(draft_text, encoding="utf-8")

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, contract_note["id"])
    self.assertEqual(published["status"], "published")
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == published["vault_relative_path"]
    )
    self.assertEqual(published_note.note_type, "chapter_contract")
    self.assertEqual((published_note.chapter_start, published_note.chapter_end), (58, 58))

    published_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")
    self.assertIn("Obsidian 章节计划", published_prompt)
    self.assertIn(published["vault_relative_path"], published_prompt)
    self.assertIn("遗言出现可验证的新信息", published_prompt)
    self.assertIn("铜钥匙最终身份", published_prompt)
    self.assertIn("不要让遗言只作为气氛词出现", published_prompt)
    self.assertIn("章末留下一个新的行动选择", published_prompt)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["id"] == contract_note["id"]
        for item in refreshed_state["obsidian_maintenance_suggestions"]
      )
    )

    vault_note_path = vault_dir / Path(str(published["vault_relative_path"]))
    edited_text = vault_note_path.read_text(encoding="utf-8")
    edited_text = edited_text.replace(
      "让母亲遗言逼迫林追重新判断宋闻，同时推进旧船队背叛线。",
      "让林追把母亲遗言转成当下可验证的选择。",
    ).replace(
      "遗言出现可验证的新信息",
      "遗言提供另一个可查证物件",
    )
    self.assertIn("source_ids:", edited_text)
    edited_text = "\n".join(
      line
      for line in edited_text.splitlines()
      if not line.startswith("gaoxia_maintenance_id:")
      and not line.startswith("gaoxia_maintenance_kind:")
    ) + "\n"
    vault_note_path.write_text(edited_text, encoding="utf-8")
    edited_detail = sync_project_obsidian(self.settings, self.project.id)
    edited_prompt = build_project_narrative_state_prompt(
      Path(self.project.path),
      edited_detail,
      "chapter-058",
    )
    self.assertNotIn("gaoxia_maintenance_id:", vault_note_path.read_text(encoding="utf-8"))
    self.assertIn("让林追把母亲遗言转成当下可验证的选择", edited_prompt)
    self.assertIn("遗言提供另一个可查证物件", edited_prompt)

    edited_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["id"] == contract_note["id"]
        for item in edited_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_narrative_state_prompt_includes_chapter_scoped_obsidian_guidance(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault"
    vault_dir.mkdir()
    (vault_dir / "母亲遗言.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 60",
          'source_url: "[潮汐档案](https://example.com/tide-archive)"',
          "required_phrases:",
          "  - 母亲遗言必须改变林追判断",
          "forbidden_phrases:",
          "  - 宋闻直接说出最终背叛者",
          "---",
          "# 母亲遗言",
          "第 58 章应推进母亲遗言线索，保留铜钥匙身份秘密。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "终局背叛.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 70",
          "required_phrases:",
          "  - 第七十章才揭露真正背叛者",
          "---",
          "# 终局背叛",
          "这份笔记只给后段章节使用。",
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
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")

    self.assertIn("Obsidian 章节来源", prompt)
    self.assertIn("母亲遗言", prompt)
    self.assertIn("Obsidian 考据来源", prompt)
    self.assertIn("潮汐档案：https://example.com/tide-archive", prompt)
    self.assertIn("Obsidian 必写项", prompt)
    self.assertIn("母亲遗言必须改变林追判断", prompt)
    self.assertIn("Obsidian 禁写项", prompt)
    self.assertIn("宋闻直接说出最终背叛者", prompt)
    self.assertNotIn("第七十章才揭露真正背叛者", prompt)

  def test_narrative_state_prompt_includes_obsidian_chapter_plan_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-plan"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Plans" / "第058章场景卡.md").write_text(
      "\n".join(
        [
          "---",
          "type: chapter_plan",
          "status: canonical",
          "chapter: 58",
          "required_phrases:",
          "  - 潮声异常",
          "forbidden_phrases:",
          "  - 直接解释铜钥匙来源",
          "---",
          "# 第058章场景卡",
          "场景一：林追在潮汐会客室听见潮声异常。",
          "场景二：宋闻用半句遗言逼林追改变路线。",
          "章尾：留下一个只能去黑盐仓库验证的选择。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第070章终局计划.md").write_text(
      "\n".join(
        [
          "---",
          "type: chapter_plan",
          "status: canonical",
          "chapter: 70",
          "---",
          "# 第070章终局计划",
          "终局祭坛公开真正背叛者。",
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
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")

    self.assertIn("Obsidian 章节计划", prompt)
    self.assertIn("第058章场景卡", prompt)
    self.assertIn("潮汐会客室", prompt)
    self.assertIn("潮声异常", prompt)
    self.assertIn("黑盐仓库", prompt)
    self.assertNotIn("终局祭坛公开真正背叛者", prompt)

  def test_narrative_state_prompt_reads_obsidian_chapter_contract_properties(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-contract-properties"
    (vault_dir / "Plans").mkdir(parents=True)
    (vault_dir / "Clues").mkdir()
    (vault_dir / "Clues" / "遗言线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_range: 58+",
          "---",
          "# 遗言线索",
          "遗言线索必须把林追推向新的行动选择。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第058章合同.md").write_text(
      "\n".join(
        [
          "---",
          "type: chapter_contract",
          "status: canonical",
          "chapter: 58",
          "objective: 遗言线索必须变成行动压力",
          "required_beats:",
          "  - 林追在潮汐会客室发现遗言断句",
          "  - 宋闻用沉默暴露黑盐仓库方向",
          "debts_to_advance:",
          "  - 铜钥匙身份线必须向旧船队靠近",
          "character_checks:",
          "  - 林追不能无条件相信宋闻",
          "style_checks:",
          "  - 对话短促，保留误解空间",
          "forbidden_moves:",
          "  - 直接公布铜钥匙最终身份",
          "acceptance_checks:",
          "  - 章尾必须留下黑盐仓库选择",
          "evidence_sources:",
          "  - \"[[Clues/遗言线索]]\"",
          "---",
          "# 第058章合同",
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
    contract_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "第058章合同")
    self.assertIn("Clues/遗言线索", contract_note.links)
    self.assertIn("Clues/遗言线索.md", contract_note.resolved_links)
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")

    self.assertIn("Obsidian 章节计划", prompt)
    self.assertIn("第058章合同", prompt)
    self.assertIn("章节目标：遗言线索必须变成行动压力", prompt)
    self.assertIn("林追在潮汐会客室发现遗言断句", prompt)
    self.assertIn("宋闻用沉默暴露黑盐仓库方向", prompt)
    self.assertIn("直接公布铜钥匙最终身份", prompt)
    self.assertIn("章尾必须留下黑盐仓库选择", prompt)

  def test_narrative_state_prompt_uses_obsidian_chapter_archive_handoff(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-archive-handoff"
    (vault_dir / "Archive").mkdir(parents=True)
    (vault_dir / "Archive" / "银潮灯回顾.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: chapter_note",
          "source_ids:",
          "  - chapter-058",
          "chapter_title: 银潮灯回顾",
          "chapter_summary: 林追在银潮灯前确认宋闻隐瞒旧船队账本。",
          "chapter_events:",
          "  - 宋闻交出半页潮汐账本。",
          "state_changes:",
          "  - 林追不再把宋闻当作单纯同盟。",
          "handoff_to_next:",
          "  - 第59章必须追问账本缺页。",
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
    early_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-010")
    followup_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-059")
    followup_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-059",
      task_instruction="写第59章",
    )

    self.assertNotIn("账本缺页", early_prompt)
    self.assertIn("Obsidian 章节档案", followup_prompt)
    self.assertIn("银潮灯回顾", followup_prompt)
    self.assertIn("摘要：林追在银潮灯前确认宋闻隐瞒旧船队账本", followup_prompt)
    self.assertIn("状态变化：林追不再把宋闻当作单纯同盟", followup_prompt)
    self.assertIn("章节交接：第59章必须追问账本缺页", followup_prompt)
    self.assertIn("Obsidian 章节档案", followup_bundle.context_text)

  def test_narrative_state_prompt_imports_obsidian_debt_and_arc_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-narrative-notes"
    (vault_dir / "Debts").mkdir(parents=True)
    (vault_dir / "CharacterArcs").mkdir(parents=True)
    (vault_dir / "Debts" / "母亲遗言债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 64",
          "tags:",
          "  - 剧情债务",
          "---",
          "# 母亲遗言债务",
          "母亲遗言里还有旧船队背叛线索，林追必须在第58章后持续追问宋闻。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "CharacterArcs" / "林追信任弧线.md").write_text(
      "\n".join(
        [
          "---",
          "type: character_arc",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 64",
          "tags:",
          "  - 人物弧线",
          "---",
          "# 林追信任弧线",
          "林追当前不能无条件相信宋闻，下一次行动要体现怀疑。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Debts" / "终局祭坛债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 70",
          "tags:",
          "  - 剧情债务",
          "---",
          "# 终局祭坛债务",
          "终局祭坛公开真正背叛者。",
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
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")

    self.assertIn("本章必须处理或明确推进的剧情债务", prompt)
    self.assertIn("母亲遗言里还有旧船队背叛线索", prompt)
    self.assertIn("人物弧线检查", prompt)
    self.assertIn("林追当前不能无条件相信宋闻", prompt)
    self.assertNotIn("终局祭坛公开真正背叛者", prompt)

  def test_narrative_state_reads_obsidian_debt_and_arc_properties(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-narrative-properties"
    (vault_dir / "Debts").mkdir(parents=True)
    (vault_dir / "CharacterArcs").mkdir(parents=True)
    (vault_dir / "Debts" / "母亲遗言债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 64",
          "debt_content: 母亲遗言必须转成对宋闻的追问压力",
          "debt_status: touched",
          "risk_level: high",
          "expected_payoff_range: 58-62",
          "next_required_action: 第58章必须让林追逼问宋闻遗言断句",
          "related_characters:",
          "  - 林追",
          "  - 宋闻",
          "tags:",
          "  - 剧情债务",
          "---",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "CharacterArcs" / "林追信任弧线.md").write_text(
      "\n".join(
        [
          "---",
          "type: character_arc",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 64",
          "character: 林追",
          "phase: 信任摇摆",
          "current_state: 林追把宋闻当成线索来源，但不能放下戒备",
          "unresolved_pressure: 宋闻每次沉默都要让林追付出验证动作",
          "required_next_check: 接受宋闻信息前必须出现一次主动验证",
          "tags:",
          "  - 人物弧线",
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
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(content="# 第五十八章 母亲遗言\n林追开始怀疑宋闻隐瞒了遗言断句。\n"),
    )

    state = load_project_narrative_state(Path(self.project.path))
    debt = next(item for item in state["debts"] if "obsidian_debt" in item.get("source_names", []))
    self.assertIn("母亲遗言必须转成对宋闻的追问压力", debt["content"])
    self.assertEqual(debt["status"], "touched")
    self.assertEqual(debt["risk_level"], "high")
    self.assertEqual(debt["expected_payoff_range"], [58, 62])
    self.assertIn("第58章必须让林追逼问宋闻遗言断句", debt["next_required_action"])
    self.assertEqual(debt["related_characters"], ["林追", "宋闻"])
    arc = next(item for item in state["character_arcs"] if "obsidian_arc" in item.get("source_names", []))
    self.assertEqual(arc["name"], "林追")
    self.assertEqual(arc["phase"], "信任摇摆")
    self.assertIn("林追把宋闻当成线索来源", arc["current_state"])
    self.assertIn("宋闻每次沉默", arc["unresolved_pressure"])
    self.assertIn("主动验证", arc["required_next_check"])

    prompt = build_project_narrative_state_prompt(
      Path(self.project.path),
      get_project_detail(self.settings, self.project.id),
      "chapter-058",
    )
    self.assertIn("Obsidian 剧情债务", prompt)
    self.assertIn("母亲遗言必须转成对宋闻的追问压力", prompt)
    self.assertIn("Obsidian 人物弧线", prompt)
    self.assertIn("接受宋闻信息前必须出现一次主动验证", prompt)

  def test_saved_chapter_persists_obsidian_debt_and_arc_notes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-narrative-state"
    (vault_dir / "Debts").mkdir(parents=True)
    (vault_dir / "CharacterArcs").mkdir(parents=True)
    (vault_dir / "Debts" / "母亲遗言债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 64",
          "tags:",
          "  - 剧情债务",
          "---",
          "# 母亲遗言债务",
          "母亲遗言里还有旧船队背叛线索，林追必须在第58章后持续追问宋闻。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "CharacterArcs" / "林追信任弧线.md").write_text(
      "\n".join(
        [
          "---",
          "type: character_arc",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 64",
          "tags:",
          "  - 人物弧线",
          "---",
          "# 林追信任弧线",
          "林追当前不能无条件相信宋闻，下一次行动要体现怀疑。",
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
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 母亲遗言\n"
          "林追听见宋闻转述母亲遗言，却仍怀疑旧船队背叛线索另有来源。\n"
        ),
      ),
    )

    state = load_project_narrative_state(Path(self.project.path))
    self.assertTrue(
      any(
        "obsidian_debt" in item.get("source_names", []) and "母亲遗言里还有旧船队背叛线索" in item.get("content", "")
        for item in state["debts"]
      )
    )
    self.assertTrue(
      any(
        item.get("name") == "林追" and "obsidian_arc" in item.get("source_names", [])
        for item in state["character_arcs"]
      )
    )
    latest_card = next(
      item
      for item in state["chapter_cards"]
      if item.get("chapter_id") == "chapter-058"
    )
    self.assertTrue(
      any(
        "母亲遗言里还有旧船队背叛线索" in item.get("content", "")
        for item in latest_card.get("obsidian_narrative_debts", [])
      )
    )
    self.assertTrue(
      any(
        item.get("name") == "林追" and "林追当前不能无条件相信宋闻" in item.get("current_state", "")
        for item in latest_card.get("obsidian_character_arcs", [])
      )
    )
    prompt = build_project_narrative_state_prompt(
      Path(self.project.path),
      get_project_detail(self.settings, self.project.id),
      "chapter-058",
    )
    self.assertIn("Obsidian 剧情债务", prompt)
    self.assertIn("Obsidian 人物弧线", prompt)

  def test_narrative_state_prompt_keeps_obsidian_guidance_without_blueprint_or_debts(self) -> None:
    update_story_document(
      self.settings,
      self.project.id,
      "plot_structure",
      StoryDocumentUpdateRequest(content=""),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "blueprint",
      StoryDocumentUpdateRequest(content=""),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "global_summary",
      StoryDocumentUpdateRequest(content=""),
    )
    update_story_document(
      self.settings,
      self.project.id,
      "character_state",
      StoryDocumentUpdateRequest(content=""),
    )
    vault_dir = Path(self._temp_dir.name) / "vault-only"
    vault_dir.mkdir()
    (vault_dir / "第58章设定.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 58",
          "required_phrases:",
          "  - 遗言线索必须推动行动",
          "---",
          "# 第58章设定",
          "这一章只需要沿着 Obsidian 的正式设定推进。",
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
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")

    self.assertIn("叙事状态账本", prompt)
    self.assertIn("Obsidian 章节来源", prompt)
    self.assertIn("遗言线索必须推动行动", prompt)

  def test_narrative_state_records_obsidian_completion_status(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-progress"
    vault_dir.mkdir()
    (vault_dir / "第58章执行清单.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 58",
          "required_phrases:",
          "  - 银潮灯",
          "  - 母亲遗言必须改变林追判断",
          "forbidden_phrases:",
          "  - 宋闻直接说出最终背叛者",
          "---",
          "# 第58章执行清单",
          "第 58 章需要兑现银潮灯，但继续保护最终背叛者。",
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
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追看见银潮灯亮起，却听见宋闻直接说出最终背叛者。\n"
        ),
      ),
    )

    state = load_project_narrative_state(Path(self.project.path))
    card = next(item for item in state["chapter_cards"] if item["chapter_id"] == "chapter-058")

    self.assertTrue(any("银潮灯" in item for item in card["obsidian_required_satisfied"]))
    self.assertTrue(any("母亲遗言必须改变林追判断" in item for item in card["obsidian_required_missing"]))
    self.assertTrue(any("宋闻直接说出最终背叛者" in item for item in card["obsidian_forbidden_violations"]))
    self.assertTrue(any("Obsidian 必写项未完成" in item["title"] for item in state["debts"]))
    self.assertTrue(any("Obsidian 禁写项已触犯" in item["title"] for item in state["debts"]))

    detail = get_project_detail(self.settings, self.project.id)
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")
    self.assertIn("Obsidian 已满足必写项", prompt)
    self.assertIn("银潮灯", prompt)
    self.assertIn("Obsidian 未完成必写项", prompt)
    self.assertIn("母亲遗言必须改变林追判断", prompt)
    self.assertIn("Obsidian 已触犯禁写项", prompt)
    self.assertIn("宋闻直接说出最终背叛者", prompt)

    next_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-059")
    self.assertIn("本章必须处理或明确推进的剧情债务", next_prompt)
    self.assertIn("Obsidian 必写项未完成", next_prompt)
    self.assertIn("Obsidian 禁写项已触犯", next_prompt)

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "银潮灯在仓门后亮起，母亲遗言必须改变林追判断。\n"
        ),
      ),
    )
    repaired_state = load_project_narrative_state(Path(self.project.path))
    obsidian_debts = [
      item
      for item in repaired_state["debts"]
      if str(item["title"]).startswith("Obsidian ")
    ]
    self.assertTrue(obsidian_debts)
    self.assertTrue(all(item["status"] == "paid" for item in obsidian_debts))
    repaired_detail = get_project_detail(self.settings, self.project.id)
    repaired_next_prompt = build_project_narrative_state_prompt(Path(self.project.path), repaired_detail, "chapter-059")
    self.assertNotIn("Obsidian 必写项未完成", repaired_next_prompt)
    self.assertNotIn("Obsidian 禁写项已触犯", repaired_next_prompt)

  def test_narrative_state_suggests_obsidian_notes_for_untracked_debts(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-maintenance"
    vault_dir.mkdir()
    (vault_dir / "Characters").mkdir()
    (vault_dir / "Characters" / "宋闻.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character",
          "---",
          "# 宋闻",
          "宋闻把旧船队背叛线索藏进母亲遗言。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "港口天气.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: setting",
          "---",
          "# 港口天气",
          "港口天气只记录风雨，不记录铜钥匙身份秘密。",
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
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 铜钥匙\n"
          "林追终于确认铜钥匙藏着旧船队身份秘密。\n"
          "宋闻把旧船队背叛线索压进母亲遗言，没有给出答案。\n"
        ),
      ),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestions = state["obsidian_maintenance_suggestions"]
    summary = state["obsidian_maintenance_summary"]

    self.assertTrue(suggestions)
    self.assertEqual(summary["total"], len(suggestions))
    self.assertGreaterEqual(summary["needs_action"], 1)
    self.assertGreaterEqual(summary["auto_staged"], 1)
    self.assertTrue(summary["top_items"])
    plot_note = next(item for item in suggestions if item["kind"] == "create_plot_note")
    self.assertIn("Plot/", plot_note["suggested_path"])
    self.assertIn("type: plot_debt", plot_note["draft_markdown"])
    self.assertIn("source_ids:", plot_note["draft_markdown"])
    self.assertIn("debt_content:", plot_note["draft_markdown"])
    self.assertIn("debt_status:", plot_note["draft_markdown"])
    self.assertIn("risk_level:", plot_note["draft_markdown"])
    self.assertIn("next_required_action:", plot_note["draft_markdown"])
    self.assertIn("related_characters:", plot_note["draft_markdown"])
    self.assertIn("相关人物：[[宋闻]]", plot_note["draft_markdown"])
    self.assertIn("后续处理", plot_note["draft_markdown"])
    self.assertEqual(plot_note["status"], "staged")
    self.assertTrue(plot_note["auto_staged"])
    auto_draft_path = Path(plot_note["draft_path"])
    self.assertTrue(auto_draft_path.exists())
    self.assertTrue(str(auto_draft_path).startswith(str(Path(self.project.path) / ".gaoxia" / "obsidian_drafts")))
    auto_draft_text = auto_draft_path.read_text(encoding="utf-8")
    self.assertIn("source_chapters:", auto_draft_text)
    self.assertIn("reveal_after_chapter: 57", auto_draft_text)
    self.assertIn("expected_payoff_range:", auto_draft_text)
    self.assertIn("debt_content:", auto_draft_text)
    self.assertNotIn("chapter_range:", auto_draft_text)
    self.assertTrue(
      any(
        item.get("suggestion_id") == plot_note["id"] and item.get("auto_staged") is True
        for item in state["obsidian_maintenance_actions"]
      )
    )

    capability_context = build_agent_capability_context(Path(self.project.path))
    self.assertIn("Obsidian 维护建议", capability_context)
    self.assertIn("建议笔记 Plot/", capability_context)

    detail = get_project_detail(self.settings, self.project.id)
    next_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-059")
    self.assertIn("Obsidian 待审草稿", next_prompt)
    self.assertIn("不能当作 Vault 正式设定引用", next_prompt)
    self.assertIn("Plot/", next_prompt)

    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-059",
      task_instruction="写第 59 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("Obsidian 待审草稿", bundle.context_text)
    self.assertIn("不能当作 Vault 正式设定引用", bundle.context_text)

    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, plot_note["id"])
    draft_path = Path(staged["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertTrue(str(draft_path).startswith(str(Path(self.project.path) / ".gaoxia" / "obsidian_drafts")))
    self.assertIn("type: plot_debt", draft_path.read_text(encoding="utf-8"))
    draft_path.write_text(draft_path.read_text(encoding="utf-8") + "\n审校备注：发布前人工确认。\n", encoding="utf-8")
    staged_state = load_project_narrative_state(Path(self.project.path))
    staged_suggestion = next(
      item
      for item in staged_state["obsidian_maintenance_suggestions"]
      if item["id"] == plot_note["id"]
    )
    self.assertEqual(staged_suggestion["status"], "staged")
    self.assertIn("obsidian_drafts", staged_suggestion["draft_path"])

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, plot_note["id"])
    self.assertEqual(published["status"], "published")
    vault_note_path = Path(published["vault_path"])
    self.assertTrue(vault_note_path.exists())
    vault_note_path.resolve().relative_to(vault_dir.resolve())
    self.assertIn("审校备注：发布前人工确认", vault_note_path.read_text(encoding="utf-8"))

    published_detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in published_detail.story_overview.obsidian.notes
      if item.relative_path == published["vault_relative_path"]
    )
    self.assertIn("宋闻", published_note.links)
    self.assertIn("Characters/宋闻.md", published_note.resolved_links)
    self.assertTrue(
      any(
        item.relative_path == published["vault_relative_path"]
        for item in published_detail.story_overview.obsidian.notes
      )
    )
    hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "审校备注",
      include_semantic=False,
    )
    self.assertTrue(any(item.source == "Obsidian" for item in hits))

    published_text = vault_note_path.read_text(encoding="utf-8")
    self.assertIn("source_ids:", published_text)
    self.assertIn("debt_content:", published_text)
    self.assertIn("debt_status:", published_text)
    self.assertIn("risk_level:", published_text)
    self.assertIn("next_required_action:", published_text)
    published_prompt = build_project_narrative_state_prompt(Path(self.project.path), published_detail, "chapter-059")
    self.assertIn("Obsidian 剧情债务", published_prompt)
    self.assertIn("母亲遗言", published_prompt)
    edited_lines = []
    for line in published_text.splitlines():
      if line.startswith("gaoxia_maintenance_id:") or line.startswith("gaoxia_maintenance_kind:"):
        continue
      if line.startswith("# "):
        edited_lines.append("# 改写后的追踪项")
      else:
        edited_lines.append(line)
    renamed_debt_path = vault_dir / "Plot" / "改写后的追踪项.md"
    vault_note_path.rename(renamed_debt_path)
    renamed_debt_path.write_text("\n".join(edited_lines) + "\n", encoding="utf-8")
    sync_project_obsidian(self.settings, self.project.id)
    renamed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["id"] == plot_note["id"]
        for item in renamed_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_character_maintenance_draft_uses_source_chapter_boundary(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-character-boundary"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 母亲遗言\n"
          "宋闻在这一章才承认母亲遗言压着旧船队背叛线索，没有给出最终答案。\n"
        ),
      ),
    )

    state = load_project_narrative_state(Path(self.project.path))
    character_note = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_character_note" and "宋闻" in item["title"]
    )
    self.assertEqual(character_note["status"], "staged")
    self.assertIn("Characters/宋闻.md", character_note["suggested_path"])
    self.assertIn("source_chapters:", character_note["draft_markdown"])
    self.assertIn("reveal_after_chapter: 57", character_note["draft_markdown"])
    self.assertIn("character:", character_note["draft_markdown"])
    self.assertIn("current_state:", character_note["draft_markdown"])
    self.assertIn("required_next_check:", character_note["draft_markdown"])
    self.assertIn("  - 人物状态", character_note["draft_markdown"])

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, character_note["id"])
    self.assertEqual(published["status"], "published")
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == "Characters/宋闻.md"
    )
    self.assertEqual(published_note.reveal_after_chapter, 57)

    early_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-010",
      knowledge_query="宋闻",
      task_instruction="回修第 10 章。",
      task_pack_kind="continuation",
    )
    self.assertNotIn("来源｜宋闻（Characters/宋闻.md）", early_bundle.context_text)
    self.assertNotIn("剧透边界：第 57 章后可用", early_bundle.context_text)

    future_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-058",
      knowledge_query="宋闻",
      task_instruction="写第 58 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("来源｜宋闻（Characters/宋闻.md）", future_bundle.context_text)
    self.assertIn("剧透边界：第 57 章后可用", future_bundle.context_text)
    future_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")
    self.assertIn("Obsidian 人物弧线", future_prompt)
    self.assertIn("宋闻", future_prompt)

    character_path = Path(published["vault_path"])
    character_text = character_path.read_text(encoding="utf-8")
    self.assertIn("source_ids:", character_text)
    self.assertIn("character:", character_text)
    self.assertIn("current_state:", character_text)
    self.assertIn("required_next_check:", character_text)
    edited_lines = []
    for line in character_text.splitlines():
      if line.startswith("gaoxia_maintenance_id:") or line.startswith("gaoxia_maintenance_kind:"):
        continue
      if line.startswith("# "):
        edited_lines.append("# 旧船队证人")
      else:
        edited_lines.append(line)
    renamed_character_path = vault_dir / "Characters" / "旧船队证人.md"
    character_path.rename(renamed_character_path)
    renamed_character_path.write_text("\n".join(edited_lines) + "\n", encoding="utf-8")
    sync_project_obsidian(self.settings, self.project.id)
    renamed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["id"] == character_note["id"]
        for item in renamed_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_published_plot_debt_note_visible_after_source_before_payoff(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-plot-boundary"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-020",
      ChapterUpdateRequest(
        content=(
          "# 第二十章 潮汐账本\n"
          "林追发现潮汐账本秘密还没有答案，宋闻把旧船队背叛线索藏进账页。\n"
        ),
      ),
    )

    state = load_project_narrative_state(Path(self.project.path))
    plot_note = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_plot_note" and "潮汐账本" in item["draft_markdown"]
    )
    self.assertIn("reveal_after_chapter: 19", plot_note["draft_markdown"])
    self.assertIn("expected_payoff_range:", plot_note["draft_markdown"])
    self.assertNotIn("chapter_range:", plot_note["draft_markdown"])

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, plot_note["id"])
    self.assertEqual(published["status"], "published")
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == published["vault_relative_path"]
    )
    self.assertEqual(published_note.chapter_start, 0)
    self.assertEqual(published_note.chapter_end, 0)
    self.assertEqual(published_note.reveal_after_chapter, 19)

    early_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-010",
      knowledge_query="潮汐账本",
      task_instruction="回修第 10 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("Obsidian 设定笔记：\n无", early_bundle.context_text)
    self.assertNotIn(f"（{published['vault_relative_path']}）", early_bundle.context_text)

    followup_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-021",
      knowledge_query="潮汐账本",
      task_instruction="写第 21 章。",
      task_pack_kind="continuation",
    )
    self.assertIn(f"（{published['vault_relative_path']}）", followup_bundle.context_text)
    self.assertIn("潮汐账本秘密还没有答案", followup_bundle.context_text)
    self.assertIn("剧透边界：第 19 章后可用", followup_bundle.context_text)

  def test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note"
    vault_dir.mkdir()
    (vault_dir / "Clues").mkdir()
    (vault_dir / "Plans").mkdir()
    (vault_dir / "Debts").mkdir()
    (vault_dir / "CharacterArcs").mkdir()
    (vault_dir / "Clues" / "铜钥匙线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 铜钥匙线索",
          "铜钥匙线索会把林追带回旧码头。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Plans" / "第58章场景卡.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: scene_plan",
          "chapter_start: 58",
          "chapter_end: 58",
          "---",
          "# 第58章场景卡",
          "场景一：银潮灯前确认旧船队记录。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Debts" / "旧船队背叛.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: narrative_debt",
          "chapter_start: 58",
          "chapter_end: 60",
          "---",
          "# 旧船队背叛",
          "旧船队背叛线索必须进入林追压力，不能只当背景气氛。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "CharacterArcs" / "林追信任.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character_arc",
          "chapter_start: 58",
          "chapter_end: 60",
          "---",
          "# 林追信任",
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
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追和宋闻在银潮灯前决定回到旧码头。\n"
          "银潮灯的光照出两人对旧船队记录的不同判断。\n"
        ),
      ),
    )
    detail_with_entities = get_project_detail(self.settings, self.project.id)
    detail_with_entities.story_overview.locations = [StoryEntityReference(name="旧码头")]
    detail_with_entities.story_overview.props = [StoryEntityReference(name="银潮灯")]
    detail_with_entities.story_overview.organizations = [StoryEntityReference(name="旧船队")]
    record_project_narrative_state_observation(Path(self.project.path), detail_with_entities, "chapter-058")

    state = load_project_narrative_state(Path(self.project.path))
    chapter_note = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    self.assertEqual(chapter_note["priority"], "medium")
    self.assertEqual(chapter_note["status"], "staged")
    self.assertTrue(chapter_note["auto_staged"])
    self.assertTrue(chapter_note["suggested_path"].startswith("ChapterNotes/第058章-"))
    self.assertIn("type: chapter_note", chapter_note["draft_markdown"])
    self.assertIn("chapter_index: 58", chapter_note["draft_markdown"])
    self.assertIn("chapter_title:", chapter_note["draft_markdown"])
    self.assertIn("chapter_summary:", chapter_note["draft_markdown"])
    self.assertIn("handoff_to_next:", chapter_note["draft_markdown"])
    self.assertIn("下一章关注本章后果", chapter_note["draft_markdown"])
    self.assertIn("chapter_excerpt:", chapter_note["draft_markdown"])
    self.assertIn("source_chapter_hash:", chapter_note["draft_markdown"])
    self.assertIn("source_chapters:", chapter_note["draft_markdown"])
    self.assertIn("source_notes:", chapter_note["draft_markdown"])
    self.assertIn("Clues/铜钥匙线索.md", chapter_note["draft_markdown"])
    self.assertIn("Plans/第58章场景卡.md", chapter_note["draft_markdown"])
    self.assertIn("Debts/旧船队背叛.md", chapter_note["draft_markdown"])
    self.assertIn("CharacterArcs/林追信任.md", chapter_note["draft_markdown"])
    self.assertIn("reveal_after_chapter: 57", chapter_note["draft_markdown"])
    self.assertIn("related_characters:", chapter_note["draft_markdown"])
    self.assertIn("related_locations:", chapter_note["draft_markdown"])
    self.assertIn("related_props:", chapter_note["draft_markdown"])
    self.assertIn("related_organizations:", chapter_note["draft_markdown"])
    self.assertIn("相关地点：[[旧码头]]", chapter_note["draft_markdown"])
    self.assertIn("相关道具：[[银潮灯]]", chapter_note["draft_markdown"])
    self.assertIn("相关组织：[[旧船队]]", chapter_note["draft_markdown"])
    self.assertIn("本章 Obsidian 章节计划", chapter_note["draft_markdown"])
    self.assertIn("银潮灯前确认旧船队记录", chapter_note["draft_markdown"])
    self.assertIn("本章 Obsidian 剧情债务", chapter_note["draft_markdown"])
    self.assertIn("旧船队背叛线索必须进入林追压力", chapter_note["draft_markdown"])
    self.assertIn("本章 Obsidian 人物弧线", chapter_note["draft_markdown"])
    self.assertIn("林追不能立刻相信宋闻", chapter_note["draft_markdown"])
    self.assertIn("下一章交接", chapter_note["draft_markdown"])
    self.assertIn("章节正文摘录", chapter_note["draft_markdown"])
    self.assertNotIn("chapter_range:", chapter_note["draft_markdown"])
    draft_path = Path(chapter_note["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertIn("章节保存后自动生成的待审档案", draft_path.read_text(encoding="utf-8"))

    pending_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail_with_entities, "chapter-059")
    self.assertIn("Obsidian 待审软约束", pending_prompt)
    self.assertIn("[章节档案] 整理章节档案：第 58 章《", pending_prompt)
    self.assertIn("Obsidian 待审草稿", pending_prompt)
    self.assertIn("不能当作 Vault 正式设定引用", pending_prompt)
    self.assertIn("草稿预览", pending_prompt)
    self.assertIn("摘要：第五十八章 银潮灯 林追和宋闻在银潮灯前决定回到旧码头", pending_prompt)
    self.assertIn("交接：下一章关注本章后果", pending_prompt)
    self.assertEqual(pending_prompt.count("草稿预览"), 1)
    followup_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-059",
      task_pack_kind="chapter",
      task_instruction="写第 59 章",
    )
    self.assertIn("Obsidian 待审软约束", followup_bundle.context_text)
    self.assertIn("[章节档案] 整理章节档案：第 58 章《", followup_bundle.context_text)
    followup_capability = build_agent_capability_context(
      Path(self.project.path),
      project_detail=detail_with_entities,
      auto_stage_obsidian_drafts=True,
      chapter_index=59,
    )
    self.assertIn("目标章节 Obsidian 待审软约束：第 59 章。", followup_capability)
    self.assertIn("[章节档案] 整理章节档案：第 58 章《", followup_capability)
    self.assertIn("交接：下一章关注本章后果", followup_capability)

    original_draft_text = draft_path.read_text(encoding="utf-8")
    draft_path.write_text(
      "\n".join(
        [
          "# 第 58 章 作者整理档案",
          "",
          "来源章节：第 58 章",
          "章节摘要：林追手写保留旧码头第二层线索。",
          "",
          "下一章交接：",
          "- 下一章追问账册封泥",
          "",
          "未完成的 Obsidian 必写项：",
          "- 林追必须追问宋闻",
          "",
          "章节正文摘录：",
          "- 银潮灯照出旧船队记录",
        ]
      ),
      encoding="utf-8",
    )
    body_only_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail_with_entities, "chapter-059")
    self.assertIn("[章节档案] 整理章节档案：第 58 章《", body_only_prompt)
    self.assertIn("草稿预览", body_only_prompt)
    self.assertIn("摘要：林追手写保留旧码头第二层线索。", body_only_prompt)
    self.assertIn("交接：下一章追问账册封泥", body_only_prompt)
    self.assertIn("未完成：林追必须追问宋闻", body_only_prompt)
    self.assertEqual(body_only_prompt.count("草稿预览"), 1)
    draft_path.write_text(original_draft_text, encoding="utf-8")

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, chapter_note["id"])
    self.assertEqual(published["status"], "published")
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == published["vault_relative_path"]
    )
    self.assertEqual(published_note.note_type, "chapter_note")
    self.assertTrue(published_note.source_chapter_hash)
    self.assertEqual((published_note.chapter_start, published_note.chapter_end, published_note.reveal_after_chapter), (0, 0, 57))
    self.assertIn("来源笔记 -> Clues/铜钥匙线索.md", published_note.graph_relations)
    self.assertIn("来源笔记 -> Plans/第58章场景卡.md", published_note.graph_relations)
    self.assertIn("来源笔记 -> Debts/旧船队背叛.md", published_note.graph_relations)
    self.assertIn("来源笔记 -> CharacterArcs/林追信任.md", published_note.graph_relations)
    self.assertIn("相关地点 -> 旧码头", published_note.graph_relations)
    self.assertIn("相关道具 -> 银潮灯", published_note.graph_relations)
    self.assertIn("相关组织 -> 旧船队", published_note.graph_relations)

    early_hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "银潮灯",
      include_semantic=False,
      chapter_index=10,
    )
    followup_hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "银潮灯",
      include_semantic=False,
      chapter_index=59,
    )
    self.assertFalse(any(item.source == "Obsidian" and published["vault_relative_path"] in item.section for item in early_hits))
    self.assertTrue(any(item.source == "Obsidian" and published["vault_relative_path"] in item.section for item in followup_hits))

    followup_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-059",
      knowledge_query="银潮灯",
      task_instruction="写第 59 章，承接银潮灯。",
      task_pack_kind="continuation",
    )
    self.assertIn(published["vault_relative_path"], followup_bundle.context_text)
    self.assertIn("章节摘要：", followup_bundle.context_text)
    self.assertIn("下一章关注本章后果", followup_bundle.context_text)
    self.assertIn("正文摘录：", followup_bundle.context_text)
    self.assertIn("第 57 章后可用", followup_bundle.context_text)

  def test_obsidian_chapter_note_backlog_keeps_many_saved_chapters_visible(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-backlog"
    vault_dir.mkdir()
    for index in range(1, 13):
      update_chapter_content(
        self.settings,
        self.project.id,
        f"chapter-{index:03d}",
        ChapterUpdateRequest(
          content=(
            f"# 第{index}章 船坞记录\n"
            f"林追在第 {index} 页账册里确认旧船队靠港记录。\n"
            f"宋闻把第 {index} 次盘问写进随身簿册。\n"
          ),
        ),
      )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    chapter_notes = [
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
    ]
    chapter_paths = [str(item.get("suggested_path") or "") for item in chapter_notes]
    self.assertGreaterEqual(len(chapter_notes), 12)
    self.assertTrue(any(path.startswith("ChapterNotes/第001章-") for path in chapter_paths))
    self.assertTrue(any(path.startswith("ChapterNotes/第012章-") for path in chapter_paths))
    self.assertGreaterEqual(state["obsidian_maintenance_summary"]["total"], 12)
    self.assertGreaterEqual(
      sum(1 for item in chapter_notes if item.get("status") in {"open", "staged"}),
      12,
    )

  def test_pending_obsidian_drafts_prioritize_target_chapter(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-target-draft-priority"
    vault_dir.mkdir()
    for index in range(1, 13):
      update_chapter_content(
        self.settings,
        self.project.id,
        f"chapter-{index:03d}",
        ChapterUpdateRequest(
          content=(
            f"# 第{index}章 目标章节维护\n"
            f"林追在第 {index} 章整理旧船队账册。\n"
            f"宋闻确认第 {index} 章的铜钥匙线索仍未关闭。\n"
          ),
        ),
      )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    detail = get_project_detail(self.settings, self.project.id)
    prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-010")
    prompt_lines = prompt.splitlines()
    draft_index = prompt_lines.index("Obsidian 待审草稿：")
    first_prompt_draft = next(line for line in prompt_lines[draft_index + 1:] if line.startswith("- "))
    self.assertIn("整理章节档案：第 10 章", first_prompt_draft)
    self.assertIn("来源第 10 章", first_prompt_draft)

    capability_context = build_agent_capability_context(
      Path(self.project.path),
      project_detail=detail,
      chapter_index=10,
    )
    context_lines = capability_context.splitlines()
    suggestion_index = context_lines.index("Obsidian 维护建议：")
    first_context_suggestion = next(line for line in context_lines[suggestion_index + 1:] if line.startswith("- "))
    self.assertIn("整理章节档案：第 10 章", first_context_suggestion)
    self.assertIn("来源第 10 章", first_context_suggestion)

  def test_obsidian_maintenance_source_chapters_open_after_latest_source(self) -> None:
    project_dir = Path(self.project.path)
    source_only = {
      "kind": "repair_graph_link",
      "title": "跨章图谱修复",
      "status": "open",
      "priority": "high",
      "source_chapters": [58, 60],
      "draft_markdown": "",
    }
    self.assertFalse(obsidian_maintenance_suggestion_available_for_chapter(source_only, 59, project_dir))
    self.assertTrue(obsidian_maintenance_suggestion_available_for_chapter(source_only, 60, project_dir))

    draft_only = {
      "kind": "create_graph_note",
      "title": "双章来源草稿",
      "status": "open",
      "priority": "high",
      "source_chapters": [],
      "draft_markdown": "\n".join(
        [
          "---",
          "type: graph_note",
          "status: canonical",
          "source_chapters: [58, 60]",
          "---",
          "# 双章来源草稿",
          "",
          "来源章节：第 58 章、第 60 章",
        ]
      ),
    }
    self.assertFalse(obsidian_maintenance_suggestion_available_for_chapter(draft_only, 59, project_dir))
    self.assertTrue(obsidian_maintenance_suggestion_available_for_chapter(draft_only, 60, project_dir))

    body_only = {
      **draft_only,
      "draft_markdown": "\n".join(
        [
          "# 作者改过的双章来源草稿",
          "",
          "来源章节：第 58 章、第 60 章",
          "作者删除了 frontmatter，但保留了正文来源章节。",
        ]
      ),
    }
    self.assertFalse(obsidian_maintenance_suggestion_available_for_chapter(body_only, 59, project_dir))
    self.assertTrue(obsidian_maintenance_suggestion_available_for_chapter(body_only, 60, project_dir))

    state_path = narrative_state_path(project_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "revision": 1,
          "obsidian_maintenance_summary": {"total": 1, "needs_action": 1, "high_priority": 1},
          "obsidian_maintenance_suggestions": [
            {
              **source_only,
              "id": "future-source",
              "action": "第 60 章资料公开后再处理。",
              "suggested_path": "",
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    early_context = build_agent_capability_context(project_dir, chapter_index=59)
    later_context = build_agent_capability_context(project_dir, chapter_index=60)
    self.assertNotIn("跨章图谱修复", early_context)
    self.assertIn("跨章图谱修复", later_context)

    state_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "revision": 2,
          "obsidian_maintenance_summary": {"total": 1, "needs_action": 1, "high_priority": 1},
          "obsidian_maintenance_suggestions": [
            {
              **source_only,
              "id": "future-missing-draft",
              "status": "draft_missing",
              "draft_path": str(project_dir / ".gaoxia" / "obsidian_drafts" / "Graph" / "future-source.md"),
              "action": "第 60 章资料公开后再处理。",
              "suggested_path": "Graph/未来图谱.md",
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    detail = get_project_detail(self.settings, self.project.id)
    early_prompt = build_project_narrative_state_prompt(project_dir, detail, "chapter-059")
    later_prompt = build_project_narrative_state_prompt(project_dir, detail, "chapter-060")
    self.assertNotIn("跨章图谱修复", early_prompt)
    self.assertNotIn("Graph/未来图谱.md", early_prompt)
    self.assertIn("跨章图谱修复", later_prompt)
    self.assertIn("Graph/未来图谱.md", later_prompt)

    state_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "revision": 3,
          "obsidian_maintenance_summary": {"total": 1, "needs_action": 1, "high_priority": 1},
          "obsidian_maintenance_suggestions": [
            {
              **body_only,
              "id": "future-body-only-draft",
              "action": "作者删掉 frontmatter 后仍按正文来源章节过滤。",
              "suggested_path": "Graph/正文来源图谱.md",
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    body_early_prompt = build_project_narrative_state_prompt(project_dir, detail, "chapter-059")
    body_later_prompt = build_project_narrative_state_prompt(project_dir, detail, "chapter-060")
    self.assertNotIn("双章来源草稿", body_early_prompt)
    self.assertNotIn("Graph/正文来源图谱.md", body_early_prompt)
    self.assertIn("双章来源草稿", body_later_prompt)
    self.assertIn("Graph/正文来源图谱.md", body_later_prompt)
    self.assertNotIn("草稿预览", body_later_prompt)

  def test_stage_obsidian_maintenance_drafts_saves_visible_backlog(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-maintenance-stage-batch"
    vault_dir.mkdir()
    for index in range(1, 15):
      update_chapter_content(
        self.settings,
        self.project.id,
        f"chapter-{index:03d}",
        ChapterUpdateRequest(
          content=(
            f"# 第{index}章 旧码头记录\n"
            f"林追把第 {index} 份旧码头靠港记录放进银潮灯下。\n"
            f"宋闻确认第 {index} 个旧船队印记仍然有效。\n"
          ),
        ),
      )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    chapter_note_ids = [
      item["id"]
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
    ]
    self.assertGreaterEqual(len(chapter_note_ids), 14)

    result = stage_project_obsidian_maintenance_drafts(
      self.settings,
      self.project.id,
      suggestion_ids=chapter_note_ids,
      limit=80,
    )
    self.assertGreaterEqual(result["staged_count"], 2)
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_notes = [
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["id"] in chapter_note_ids
    ]
    self.assertTrue(refreshed_notes)
    self.assertTrue(all(item["status"] == "staged" for item in refreshed_notes))
    self.assertTrue(all(Path(str(item["draft_path"])).exists() for item in refreshed_notes))

  def test_ignore_obsidian_maintenance_notes_hides_visible_backlog(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-maintenance-ignore-batch"
    vault_dir.mkdir()
    for index in range(1, 7):
      update_chapter_content(
        self.settings,
        self.project.id,
        f"chapter-{index:03d}",
        ChapterUpdateRequest(
          content=(
            f"# 第{index}章 暂缓档案\n"
            f"林追把第 {index} 份旧码头靠港记录暂时压进档案盒。\n"
            f"宋闻确认第 {index} 个旧船队印记还不能公开。\n"
          ),
        ),
      )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    chapter_note_ids = [
      item["id"]
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
    ][:5]
    self.assertEqual(len(chapter_note_ids), 5)

    result = ignore_project_obsidian_maintenance_notes(
      self.settings,
      self.project.id,
      suggestion_ids=chapter_note_ids,
      limit=10,
    )

    self.assertEqual(result["ignored_count"], 5)
    self.assertEqual(result["skipped_count"], 0)
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_notes = [
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["id"] in chapter_note_ids
    ]
    self.assertTrue(refreshed_notes)
    self.assertTrue(all(item["status"] == "ignored" for item in refreshed_notes))
    self.assertGreaterEqual(refreshed_state["obsidian_maintenance_summary"]["by_status"]["ignored"], 5)

  def test_reopen_obsidian_maintenance_notes_restores_visible_backlog(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-maintenance-reopen-batch"
    vault_dir.mkdir()
    for index in range(1, 7):
      update_chapter_content(
        self.settings,
        self.project.id,
        f"chapter-{index:03d}",
        ChapterUpdateRequest(
          content=(
            f"# 第{index}章 恢复档案\n"
            f"林追把第 {index} 份旧码头记录重新交给宋闻核对。\n"
            f"宋闻确认第 {index} 个旧船队印记应该回到维护列表。\n"
          ),
        ),
      )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    chapter_note_ids = [
      item["id"]
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
    ][:5]
    self.assertEqual(len(chapter_note_ids), 5)

    ignored = ignore_project_obsidian_maintenance_notes(
      self.settings,
      self.project.id,
      suggestion_ids=chapter_note_ids,
      limit=10,
    )
    self.assertEqual(ignored["ignored_count"], 5)

    reopened = reopen_project_obsidian_maintenance_notes(
      self.settings,
      self.project.id,
      suggestion_ids=chapter_note_ids[:3],
      limit=10,
    )

    self.assertEqual(reopened["reopened_count"], 3)
    self.assertEqual(reopened["skipped_count"], 0)
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_by_id = {
      item["id"]: item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["id"] in chapter_note_ids
    }
    self.assertEqual(len(refreshed_by_id), 5)
    self.assertTrue(all(refreshed_by_id[item_id]["status"] == "open" for item_id in chapter_note_ids[:3]))
    self.assertTrue(all(refreshed_by_id[item_id]["status"] == "ignored" for item_id in chapter_note_ids[3:]))
    self.assertGreaterEqual(refreshed_state["obsidian_maintenance_summary"]["by_status"]["ignored"], 2)

  def test_publish_obsidian_maintenance_notes_publishes_staged_drafts_to_vault(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-maintenance-publish-batch"
    vault_dir.mkdir()
    for index in range(1, 5):
      update_chapter_content(
        self.settings,
        self.project.id,
        f"chapter-{index:03d}",
        ChapterUpdateRequest(
          content=(
            f"# 第{index}章 批量档案\n"
            f"林追把第 {index} 份旧码头靠港记录归进银潮灯档案。\n"
            f"宋闻确认第 {index} 个旧船队印记还在账册里。\n"
          ),
        ),
      )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    chapter_note_ids = [
      item["id"]
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
    ][:4]
    self.assertEqual(len(chapter_note_ids), 4)

    stage_project_obsidian_maintenance_drafts(
      self.settings,
      self.project.id,
      suggestion_ids=chapter_note_ids,
      limit=10,
    )
    result = publish_project_obsidian_maintenance_notes(
      self.settings,
      self.project.id,
      suggestion_ids=chapter_note_ids,
      limit=10,
    )

    self.assertEqual(result["published_count"], 4)
    self.assertEqual(result["skipped_count"], 0)
    for item in result["published"]:
      relative_path = str(item["vault_relative_path"])
      target_path = vault_dir / relative_path
      self.assertTrue(target_path.exists(), relative_path)
      self.assertIn("source_chapter_hash", target_path.read_text(encoding="utf-8"))
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_notes = [
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["id"] in chapter_note_ids
    ]
    self.assertFalse(any(item["status"] not in {"published"} for item in refreshed_notes))
    published_actions = [
      item
      for item in refreshed_state["obsidian_maintenance_actions"]
      if item.get("suggestion_id") in chapter_note_ids and item.get("status") == "published"
    ]
    self.assertEqual(len(published_actions), 4)

    hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "旧码头靠港记录",
      limit=8,
      include_semantic=False,
      chapter_index=5,
    )
    self.assertTrue(any(item.source == "Obsidian" and "ChapterNotes/" in item.section for item in hits))

  def test_generated_chapter_note_hash_detects_outdated_vault_note_without_action(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-hash"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追在银潮灯前看见旧码头潮痕。\n"
          "宋闻把旧船队记录藏回袖中。\n"
        ),
      ),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_note = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    initial_draft = str(initial_note["draft_markdown"])
    initial_hash = next(
      line.split(":", 1)[1].strip()
      for line in initial_draft.splitlines()
      if line.startswith("source_chapter_hash:")
    )
    note_path = vault_dir / "ChapterNotes" / "第058章-银潮灯.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(initial_draft + "\n", encoding="utf-8")
    sync_project_obsidian(self.settings, self.project.id)

    synced_state = refresh_project_narrative_state_chapter_cards(
      Path(self.project.path),
      get_project_detail(self.settings, self.project.id),
      persist=True,
    )
    self.assertFalse(
      any(
        item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
        for item in synced_state["obsidian_maintenance_suggestions"]
      )
    )

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 雨窗账册\n"
          "林追在雨窗账册里确认旧船队记录已经被改写。\n"
          "宋闻第一次承认自己见过账册封泥。\n"
        ),
      ),
    )
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_note = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    self.assertEqual(refreshed_note["status"], "staged")
    self.assertTrue(refreshed_note["auto_staged"])
    self.assertIn("章节档案已经发布", refreshed_note["reason"])
    self.assertIn("雨窗账册里确认旧船队记录已经被改写", refreshed_note["draft_markdown"])
    self.assertNotIn(f"source_chapter_hash: {initial_hash}", refreshed_note["draft_markdown"])
    self.assertNotIn("ChapterNotes/第058章-银潮灯.md", refreshed_note["draft_markdown"])

  def test_chapter_note_source_ids_match_after_author_reorganizes_vault_note(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-source-ids"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追在银潮灯前看见旧码头潮痕。\n"
          "宋闻把旧船队记录藏回袖中。\n"
        ),
      ),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_note = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, initial_note["id"])
    vault_note_path = Path(published["vault_path"])
    published_text = vault_note_path.read_text(encoding="utf-8")
    self.assertIn("source_ids:", published_text)
    edited_lines = []
    skipping_source_chapters = False
    for line in published_text.splitlines():
      if skipping_source_chapters:
        if line.startswith("  - "):
          continue
        skipping_source_chapters = False
      if (
        line.startswith("gaoxia_maintenance_id:")
        or line.startswith("gaoxia_maintenance_kind:")
        or line.startswith("reveal_after_chapter:")
        or line.startswith("source_chapter_hash:")
      ):
        continue
      if line.startswith("source_chapters:"):
        skipping_source_chapters = True
        continue
      if line.startswith("type:"):
        edited_lines.append("type: author_archive")
      elif line.startswith("summary:"):
        edited_lines.append('summary: "作者整理后的第 58 章回顾"')
      elif line.startswith("# "):
        edited_lines.append("# 作者整理后的银潮灯回顾")
      else:
        edited_lines.append(line)
    reorganized_path = vault_dir / "Archive" / "作者整理后的银潮灯回顾.md"
    reorganized_path.parent.mkdir(parents=True)
    vault_note_path.rename(reorganized_path)
    reorganized_path.write_text(
      "\n".join(edited_lines).rstrip()
      + "\n\n作者补记：银潮灯回顾确认林追在旧码头重新判断旧船队记录。\n",
      encoding="utf-8",
    )

    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
        for item in refreshed_state["obsidian_maintenance_suggestions"]
      )
    )
    detail = get_project_detail(self.settings, self.project.id)
    archive_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == "Archive/作者整理后的银潮灯回顾.md"
    )
    self.assertEqual(archive_note.source_ids, ["chapter-058"])
    self.assertEqual((archive_note.chapter_start, archive_note.chapter_end, archive_note.reveal_after_chapter), (58, 0, 0))
    early_hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "银潮灯回顾",
      include_semantic=False,
      chapter_index=10,
    )
    later_hits = search_project_knowledge(
      self.settings,
      self.project.id,
      "银潮灯回顾",
      include_semantic=False,
      chapter_index=60,
    )
    self.assertFalse(any(item.source == "Obsidian" and "银潮灯回顾" in item.section for item in early_hits))
    self.assertTrue(any(item.source == "Obsidian" and "银潮灯回顾" in item.section for item in later_hits))

  def test_chapter_note_source_chapters_match_after_author_removes_source_ids(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-source-chapters"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追在银潮灯前看见旧码头潮痕。\n"
          "宋闻把旧船队记录藏回袖中。\n"
        ),
      ),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_note = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, initial_note["id"])
    vault_note_path = Path(published["vault_path"])
    published_text = vault_note_path.read_text(encoding="utf-8")
    self.assertIn("source_ids:", published_text)
    self.assertIn("source_chapters:", published_text)

    edited_lines = []
    skipping_source_ids = False
    for line in published_text.splitlines():
      if skipping_source_ids:
        if line.startswith("  - "):
          continue
        skipping_source_ids = False
      if (
        line.startswith("gaoxia_maintenance_id:")
        or line.startswith("gaoxia_maintenance_kind:")
        or line.startswith("reveal_after_chapter:")
        or line.startswith("source_chapter_hash:")
      ):
        continue
      if line.startswith("source_ids:"):
        skipping_source_ids = True
        continue
      if line.startswith("type:"):
        edited_lines.append("type: author_archive")
      elif line.startswith("summary:"):
        edited_lines.append('summary: "作者只保留来源章节的第 58 章回顾"')
      elif line.startswith("# "):
        edited_lines.append("# 只保留来源章节的银潮灯回顾")
      else:
        edited_lines.append(line)

    reorganized_path = vault_dir / "Archive" / "只保留来源章节的银潮灯回顾.md"
    reorganized_path.parent.mkdir(parents=True)
    vault_note_path.rename(reorganized_path)
    reorganized_path.write_text(
      "\n".join(edited_lines).rstrip()
      + "\n\n作者补记：银潮灯回顾保留来源章节，但不保留来源 ID。\n",
      encoding="utf-8",
    )

    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
        for item in refreshed_state["obsidian_maintenance_suggestions"]
      )
    )
    detail = get_project_detail(self.settings, self.project.id)
    archive_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == "Archive/只保留来源章节的银潮灯回顾.md"
    )
    self.assertEqual(archive_note.source_ids, [])
    self.assertEqual(archive_note.source_chapters, [58])
    self.assertEqual((archive_note.chapter_start, archive_note.chapter_end, archive_note.reveal_after_chapter), (58, 0, 0))

  def test_published_chapter_note_reports_outdated_after_saved_chapter_changes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-outdated"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追在银潮灯前看见旧码头潮痕。\n"
          "宋闻把旧船队记录藏回袖中。\n"
        ),
      ),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_note = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, initial_note["id"])
    published_path = Path(published["vault_path"])
    self.assertIn("银潮灯前看见旧码头潮痕", published_path.read_text(encoding="utf-8"))

    after_publish_state = refresh_project_narrative_state_chapter_cards(
      Path(self.project.path),
      get_project_detail(self.settings, self.project.id),
      persist=True,
    )
    self.assertFalse(
      any(
        item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
        for item in after_publish_state["obsidian_maintenance_suggestions"]
      )
    )

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 雨窗账册\n"
          "林追在雨窗账册里确认旧船队记录已经被改写。\n"
          "宋闻第一次承认自己见过账册封泥。\n"
        ),
      ),
    )
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_note = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    self.assertEqual(refreshed_note["status"], "published_outdated")
    self.assertTrue(refreshed_note["published_outdated"])
    self.assertEqual(refreshed_note["vault_relative_path"], published["vault_relative_path"])
    self.assertIn("章节档案已经发布", refreshed_note["reason"])
    self.assertIn("雨窗账册里确认旧船队记录已经被改写", refreshed_note["draft_markdown"])
    self.assertNotIn("雨窗账册里确认旧船队记录已经被改写", published_path.read_text(encoding="utf-8"))
    self.assertEqual(refreshed_state["obsidian_maintenance_summary"]["by_status"]["published_outdated"], 1)

    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, refreshed_note["id"])
    self.assertTrue(str(staged.get("merge_draft_path") or "").strip())
    self.assertEqual(staged["vault_path"], str(published_path))
    self.assertEqual(staged["vault_relative_path"], published["vault_relative_path"])
    merge_draft_path = Path(str(staged.get("merge_draft_path") or ""))
    self.assertTrue(merge_draft_path.exists())
    self.assertIn("_updates", merge_draft_path.parts)
    merge_text = merge_draft_path.read_text(encoding="utf-8")
    self.assertIn("type: obsidian_update_review", merge_text)
    self.assertIn(f"target_note: {published['vault_relative_path']}", merge_text)
    self.assertIn(f"suggested_note: {staged['relative_path']}", merge_text)
    self.assertIn(f"正式 Vault 笔记：`{published['vault_relative_path']}`", merge_text)
    self.assertIn(f"系统建议路径：`{staged['relative_path']}`", merge_text)
    self.assertIn("Vault 当前内容", merge_text)
    self.assertIn("银潮灯前看见旧码头潮痕", merge_text)
    self.assertIn("系统新版草稿", merge_text)
    self.assertIn("雨窗账册里确认旧船队记录已经被改写", merge_text)
    staged_state = load_project_narrative_state(Path(self.project.path))
    staged_note = next(
      item
      for item in staged_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    self.assertEqual(staged_note["merge_draft_path"], str(merge_draft_path))
    self.assertEqual(staged_note["vault_path"], str(published_path))
    self.assertEqual(staged_note["vault_relative_path"], published["vault_relative_path"])

    with self.assertRaises(ValueError):
      confirm_project_obsidian_maintenance_merge(self.settings, self.project.id, refreshed_note["id"])

    staged_draft_text = Path(staged["draft_path"]).read_text(encoding="utf-8")
    published_path.write_text(staged_draft_text, encoding="utf-8")
    confirmed = confirm_project_obsidian_maintenance_merge(self.settings, self.project.id, refreshed_note["id"])
    self.assertEqual(confirmed["status"], "published")
    self.assertEqual(confirmed["vault_relative_path"], published["vault_relative_path"])
    self.assertFalse(confirmed["published_from_manual_edits"])

    confirmed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
        for item in confirmed_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_confirm_obsidian_maintenance_merges_handles_visible_batch(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-batch-confirm"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    for chapter_id, title, body in (
      ("chapter-058", "银潮灯", "林追在银潮灯前看见旧码头潮痕。"),
      ("chapter-059", "铜钥匙", "宋闻把铜钥匙藏进旧船队账页。"),
    ):
      update_chapter_content(
        self.settings,
        self.project.id,
        chapter_id,
        ChapterUpdateRequest(content=f"# {title}\n{body}\n"),
      )

    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_notes = [
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and item["source_chapters"][0] in {58, 59}
    ]
    self.assertEqual(len(initial_notes), 2)
    published_by_chapter = {
      item["source_chapters"][0]: publish_project_obsidian_maintenance_note(self.settings, self.project.id, item["id"])
      for item in initial_notes
    }
    for published in published_by_chapter.values():
      self.assertTrue(Path(published["vault_path"]).exists())

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(content="# 雨窗账册\n林追在雨窗账册里确认旧船队记录已经被改写。\n"),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-059",
      ChapterUpdateRequest(content="# 密钥账页\n宋闻承认铜钥匙对应另一份账页。\n"),
    )
    outdated_state = load_project_narrative_state(Path(self.project.path))
    outdated_notes = [
      item
      for item in outdated_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
      and item["source_chapters"][0] in {58, 59}
      and item["status"] == "published_outdated"
    ]
    self.assertEqual(len(outdated_notes), 2)

    staged = stage_project_obsidian_maintenance_drafts(
      self.settings,
      self.project.id,
      suggestion_ids=[item["id"] for item in outdated_notes],
      limit=2,
    )
    self.assertEqual(staged["merge_draft_count"], 2)
    staged_state = load_project_narrative_state(Path(self.project.path))
    staged_notes = [
      item
      for item in staged_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note"
      and item["source_chapters"][0] in {58, 59}
      and item.get("merge_draft_path")
    ]
    self.assertEqual(len(staged_notes), 2)
    for item in staged_notes:
      draft_text = Path(item["draft_path"]).read_text(encoding="utf-8")
      Path(item["vault_path"]).write_text(draft_text, encoding="utf-8")

    confirmed = confirm_project_obsidian_maintenance_merges(
      self.settings,
      self.project.id,
      suggestion_ids=[item["id"] for item in staged_notes],
      limit=2,
    )
    self.assertEqual(confirmed["confirmed_count"], 2)
    self.assertEqual(confirmed["skipped_count"], 0)
    self.assertEqual(
      {item["vault_relative_path"] for item in confirmed["confirmed"]},
      {published_by_chapter[58]["vault_relative_path"], published_by_chapter[59]["vault_relative_path"]},
    )

    confirmed_state = load_project_narrative_state(Path(self.project.path))
    self.assertFalse(
      any(
        item["kind"] == "create_chapter_note" and item["source_chapters"][0] in {58, 59}
        for item in confirmed_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_auto_staged_chapter_note_draft_updates_when_saved_chapter_changes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-refresh"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 银潮灯\n"
          "林追在银潮灯前看见旧码头潮痕。\n"
          "宋闻把旧船队记录藏回袖中。\n"
        ),
      ),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_note = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    draft_path = Path(initial_note["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertIn("银潮灯前看见旧码头潮痕", draft_path.read_text(encoding="utf-8"))

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 雨窗账册\n"
          "林追在雨窗账册里确认旧船队记录已经被改写。\n"
          "宋闻第一次承认自己见过账册封泥。\n"
        ),
      ),
    )
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_note = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    self.assertTrue(refreshed_note["auto_staged"])
    self.assertFalse(refreshed_note["manual_draft_edits"])
    refreshed_draft_path = Path(refreshed_note["draft_path"])
    self.assertNotEqual(refreshed_draft_path, draft_path)
    self.assertTrue(refreshed_draft_path.exists())
    self.assertFalse(draft_path.exists())
    self.assertIn("雨窗账册", refreshed_draft_path.name)
    refreshed_text = refreshed_draft_path.read_text(encoding="utf-8")
    self.assertIn("雨窗账册里确认旧船队记录已经被改写", refreshed_text)
    self.assertNotIn("银潮灯前看见旧码头潮痕", refreshed_text)

  def test_auto_staged_chapter_note_draft_preserves_manual_edits(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-chapter-note-manual"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 初稿线索\n"
          "林追在初稿线索里确认旧码头潮痕。\n"
          "宋闻暂时不说账册封泥。\n"
        ),
      ),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_note = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    draft_path = Path(initial_note["draft_path"])
    draft_path.write_text(
      draft_path.read_text(encoding="utf-8") + "\n人工备注：这一章档案要保留作者判断。\n",
      encoding="utf-8",
    )

    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 新稿线索\n"
          "林追在新稿线索里确认账册封泥来自旧船队。\n"
          "宋闻改口承认自己隐瞒过一次见证。\n"
        ),
      ),
    )
    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_note = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_chapter_note" and "第 58 章" in item["title"]
    )
    self.assertTrue(refreshed_note["manual_draft_edits"])
    self.assertEqual(Path(refreshed_note["draft_path"]), draft_path)
    preserved_text = draft_path.read_text(encoding="utf-8")
    self.assertIn("人工备注：这一章档案要保留作者判断。", preserved_text)
    self.assertIn("初稿线索里确认旧码头潮痕", preserved_text)
    self.assertNotIn("新稿线索里确认账册封泥", preserved_text)

  def test_narrative_state_turns_repeated_unresolved_obsidian_links_into_drafts(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-maintenance"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在港口第一次看到 [[潮汐账本]] 的影子。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "线索乙.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索乙",
          "宋闻也把 [[潮汐账本]] 当成旧船队秘密的一部分。",
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
      "chapter-058",
      ChapterUpdateRequest(
        content=(
          "# 第五十八章 潮汐账本\n"
          "林追和宋闻都意识到潮汐账本牵着旧船队背叛线索。\n"
        ),
      ),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertFalse(
      any(
        item["kind"] == "create_graph_note" and "孤立笔记" in item["title"]
        for item in state["obsidian_maintenance_suggestions"]
      )
    )

    self.assertEqual(suggestion["priority"], "medium")
    self.assertEqual(suggestion["status"], "staged")
    self.assertTrue(suggestion["auto_staged"])
    self.assertIn("Graph/", suggestion["suggested_path"])
    self.assertIn("type: graph_note", suggestion["draft_markdown"])
    self.assertIn("aliases:", suggestion["draft_markdown"])
    self.assertIn("source_notes:", suggestion["draft_markdown"])
    self.assertIn("[[线索甲]]", suggestion["draft_markdown"])

    draft_path = Path(suggestion["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertTrue(str(draft_path).startswith(str(Path(self.project.path) / ".gaoxia" / "obsidian_drafts")))
    self.assertIn("发布前确认", draft_path.read_text(encoding="utf-8"))

    capability_context = build_agent_capability_context(Path(self.project.path))
    self.assertIn("Obsidian 维护建议", capability_context)
    self.assertIn("潮汐账本", capability_context)

    detail = get_project_detail(self.settings, self.project.id)
    next_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-059")
    self.assertIn("Obsidian 待审草稿", next_prompt)
    self.assertIn("Graph/", next_prompt)

  def test_obsidian_sync_refreshes_graph_maintenance_without_chapter_save(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-sync-graph"
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

    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_graph_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(initial_graph_suggestion["status"], "open")
    self.assertFalse(initial_graph_suggestion["auto_staged"])

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
    sync_project_obsidian(self.settings, self.project.id)

    synced_state = load_project_narrative_state(Path(self.project.path))
    synced_suggestion = next(
      item
      for item in synced_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(synced_suggestion["priority"], "medium")
    self.assertEqual(synced_suggestion["status"], "staged")
    self.assertTrue(synced_suggestion["auto_staged"])
    self.assertIn("Graph/", synced_suggestion["suggested_path"])
    draft_path = Path(synced_suggestion["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertIn("source_notes:", draft_path.read_text(encoding="utf-8"))

  def test_orphan_obsidian_notes_generate_graph_index_draft(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-orphan-graph"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Locations").mkdir(parents=True)
    (vault_dir / "Characters" / "林追.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character",
          "chapter_range: 第 58-60 章",
          "---",
          "# 林追",
          "林追正在追查旧船队背叛线索。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Locations" / "潮汐码头.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: location",
          "chapter_range: 第 58-60 章",
          "---",
          "# 潮汐码头",
          "潮汐码头保存着旧船队账页。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "孤立笔记" in item["title"]
    )
    self.assertEqual(suggestion["priority"], "medium")
    self.assertEqual(suggestion["status"], "staged")
    self.assertTrue(suggestion["auto_staged"])
    self.assertTrue(suggestion["suggested_path"].startswith("Graph/孤立笔记整理-"))
    self.assertTrue(suggestion["suggested_path"].endswith(".md"))
    self.assertIn("type: graph_index", suggestion["draft_markdown"])
    self.assertIn("chapter_range: 第 58-60 章", suggestion["draft_markdown"])
    self.assertIn("source_notes:", suggestion["draft_markdown"])
    self.assertIn("Characters/林追.md", suggestion["draft_markdown"])
    self.assertIn("Locations/潮汐码头.md", suggestion["draft_markdown"])
    self.assertIn("[[Characters/林追]]", suggestion["draft_markdown"])
    self.assertIn("[[Locations/潮汐码头]]", suggestion["draft_markdown"])

    draft_path = Path(suggestion["draft_path"])
    self.assertTrue(draft_path.exists())
    self.assertIn("孤立笔记整理", draft_path.read_text(encoding="utf-8"))

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    detail = get_project_detail(self.settings, self.project.id)
    index_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == published["vault_relative_path"]
    )
    character_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "林追")
    location_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "潮汐码头")
    self.assertIn("Characters/林追.md", index_note.resolved_links)
    self.assertIn("Locations/潮汐码头.md", index_note.resolved_links)
    self.assertIn(published["vault_relative_path"], character_note.backlinks)
    self.assertIn(published["vault_relative_path"], location_note.backlinks)

  def test_new_orphan_notes_after_published_graph_index_get_new_draft(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-orphan-graph-next"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Locations").mkdir(parents=True)
    (vault_dir / "Items").mkdir(parents=True)
    (vault_dir / "Characters" / "林追.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character",
          "---",
          "# 林追",
          "林追正在追查旧船队背叛线索。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Locations" / "潮汐码头.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: location",
          "---",
          "# 潮汐码头",
          "潮汐码头保存着旧船队账页。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "孤立笔记" in item["title"]
    )
    first_path = initial_suggestion["suggested_path"]
    first_published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, initial_suggestion["id"])

    (vault_dir / "Characters" / "宋闻.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character",
          "---",
          "# 宋闻",
          "宋闻知道铜钥匙身份秘密。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "Items" / "铜钥匙.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: item",
          "---",
          "# 铜钥匙",
          "铜钥匙能打开旧船队的账本暗格。",
        ]
      ),
      encoding="utf-8",
    )
    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    next_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note"
      and "孤立笔记" in item["title"]
      and "Characters/宋闻.md" in item["draft_markdown"]
    )
    self.assertEqual(next_suggestion["status"], "staged")
    self.assertTrue(next_suggestion["auto_staged"])
    self.assertNotEqual(next_suggestion["suggested_path"], first_path)
    self.assertNotEqual(next_suggestion["suggested_path"], first_published["vault_relative_path"])
    self.assertIn("Items/铜钥匙.md", next_suggestion["draft_markdown"])

    next_published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, next_suggestion["id"])
    detail = get_project_detail(self.settings, self.project.id)
    song_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "宋闻")
    key_note = next(item for item in detail.story_overview.obsidian.notes if item.title == "铜钥匙")
    self.assertIn(next_published["vault_relative_path"], song_note.backlinks)
    self.assertIn(next_published["vault_relative_path"], key_note.backlinks)

  def test_auto_staged_orphan_graph_index_updates_when_source_scope_changes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-orphan-graph-scope-update"
    (vault_dir / "Characters").mkdir(parents=True)
    (vault_dir / "Locations").mkdir(parents=True)
    character_path = vault_dir / "Characters" / "林追.md"
    location_path = vault_dir / "Locations" / "潮汐码头.md"
    character_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character",
          "---",
          "# 林追",
          "林追正在追查旧船队背叛线索。",
        ]
      ),
      encoding="utf-8",
    )
    location_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: location",
          "---",
          "# 潮汐码头",
          "潮汐码头保存着旧船队账页。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "孤立笔记" in item["title"]
    )
    draft_path = Path(initial_suggestion["draft_path"])
    self.assertEqual(initial_suggestion["status"], "staged")
    self.assertNotIn("chapter_range:", draft_path.read_text(encoding="utf-8"))

    character_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: character",
          "chapter_range: 第 58-60 章",
          "---",
          "# 林追",
          "林追正在追查旧船队背叛线索。",
        ]
      ),
      encoding="utf-8",
    )
    location_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: location",
          "chapter_range: 第 58-60 章",
          "---",
          "# 潮汐码头",
          "潮汐码头保存着旧船队账页。",
        ]
      ),
      encoding="utf-8",
    )
    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["id"] == initial_suggestion["id"]
    )
    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertEqual(Path(refreshed_suggestion["draft_path"]), draft_path)
    refreshed_text = draft_path.read_text(encoding="utf-8")
    self.assertIn("chapter_range: 第 58-60 章", refreshed_text)
    self.assertIn("Characters/林追.md", refreshed_text)
    self.assertIn("Locations/潮汐码头.md", refreshed_text)

  def test_graph_maintenance_draft_inherits_source_chapter_scope(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-scope"
    vault_dir.mkdir()
    (vault_dir / "后段线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 58-60 章",
          "reveal_after_chapter: 57",
          "---",
          "# 后段线索",
          "林追在后段才会确认 [[潮汐账本]] 指向旧船队背叛真相。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertIn("chapter_range: 第 58-60 章", suggestion["draft_markdown"])
    self.assertIn("reveal_after_chapter: 57", suggestion["draft_markdown"])

    publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == "Graph/潮汐账本.md"
    )
    self.assertEqual(published_note.chapter_start, 58)
    self.assertEqual(published_note.chapter_end, 60)
    self.assertEqual(published_note.reveal_after_chapter, 57)

    early_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-010",
      knowledge_query="潮汐账本",
      task_instruction="写第 10 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("Obsidian 设定笔记：\n无", early_bundle.context_text)
    self.assertNotIn("后段线索", early_bundle.context_text)
    self.assertNotIn("潮汐账本 指向旧船队背叛真相", early_bundle.context_text)

    target_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-058",
      knowledge_query="潮汐账本",
      task_instruction="写第 58 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("Obsidian 设定笔记：", target_bundle.context_text)
    self.assertIn("潮汐账本", target_bundle.context_text)

  def test_graph_maintenance_draft_uses_spoiler_boundary_for_disjoint_source_scopes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-disjoint-scope"
    vault_dir.mkdir()
    (vault_dir / "早段线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 1-3 章",
          "---",
          "# 早段线索",
          "林追只在早段听过 [[潮汐账本]] 这个名字。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "后段线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 58-60 章",
          "---",
          "# 后段线索",
          "林追在后段才会确认 [[潮汐账本]] 指向旧船队背叛真相。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertNotIn("chapter_range: 第 1-60 章", suggestion["draft_markdown"])
    self.assertIn("reveal_after_chapter: 57", suggestion["draft_markdown"])

    draft_detail = get_project_detail(self.settings, self.project.id)
    early_prompt = build_project_narrative_state_prompt(Path(self.project.path), draft_detail, "chapter-002")
    self.assertNotIn("Obsidian 待审草稿", early_prompt)
    self.assertNotIn("Graph/潮汐账本.md", early_prompt)
    future_prompt = build_project_narrative_state_prompt(Path(self.project.path), draft_detail, "chapter-058")
    self.assertIn("Obsidian 待审草稿", future_prompt)
    self.assertIn("Graph/潮汐账本.md", future_prompt)
    early_capability = build_agent_capability_context(
      Path(self.project.path),
      project_detail=draft_detail,
      chapter_index=2,
    )
    self.assertIn("Obsidian 维护摘要", early_capability)
    self.assertNotIn("Graph/潮汐账本.md", early_capability)
    future_capability = build_agent_capability_context(
      Path(self.project.path),
      project_detail=draft_detail,
      chapter_index=58,
    )
    self.assertIn("Graph/潮汐账本.md", future_capability)

    publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == "Graph/潮汐账本.md"
    )
    self.assertEqual(published_note.chapter_start, 0)
    self.assertEqual(published_note.chapter_end, 0)
    self.assertEqual(published_note.reveal_after_chapter, 57)

    early_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-002",
      knowledge_query="潮汐账本",
      task_instruction="写第 2 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("早段线索", early_bundle.context_text)
    self.assertNotIn("后段线索", early_bundle.context_text)
    self.assertNotIn("旧船队背叛真相", early_bundle.context_text)

    future_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-058",
      knowledge_query="潮汐账本",
      task_instruction="写第 58 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("后段线索", future_bundle.context_text)
    self.assertIn("潮汐账本", future_bundle.context_text)

  def test_graph_maintenance_draft_uses_latest_boundary_for_open_source_scopes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-open-source-scope"
    vault_dir.mkdir()
    (vault_dir / "第58章线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 58+",
          "---",
          "# 第58章线索",
          "林追只在第58章听见 [[潮汐账本]] 这个名字。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第60章真相.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 60+",
          "---",
          "# 第60章真相",
          "林追到第60章才确认 [[潮汐账本]] 指向旧船队背叛真相。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertNotIn("chapter_start: 58", suggestion["draft_markdown"])
    self.assertIn("reveal_after_chapter: 59", suggestion["draft_markdown"])

    draft_detail = get_project_detail(self.settings, self.project.id)
    mid_prompt = build_project_narrative_state_prompt(Path(self.project.path), draft_detail, "chapter-059")
    self.assertNotIn("Obsidian 待审草稿", mid_prompt)
    self.assertNotIn("Graph/潮汐账本.md", mid_prompt)
    future_prompt = build_project_narrative_state_prompt(Path(self.project.path), draft_detail, "chapter-060")
    self.assertIn("Obsidian 待审草稿", future_prompt)
    self.assertIn("Graph/潮汐账本.md", future_prompt)

    mid_capability = build_agent_capability_context(
      Path(self.project.path),
      project_detail=draft_detail,
      chapter_index=59,
    )
    self.assertNotIn("Graph/潮汐账本.md", mid_capability)
    future_capability = build_agent_capability_context(
      Path(self.project.path),
      project_detail=draft_detail,
      chapter_index=60,
    )
    self.assertIn("Graph/潮汐账本.md", future_capability)

    publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    detail = get_project_detail(self.settings, self.project.id)
    published_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.relative_path == "Graph/潮汐账本.md"
    )
    self.assertEqual(published_note.chapter_start, 0)
    self.assertEqual(published_note.chapter_end, 0)
    self.assertEqual(published_note.reveal_after_chapter, 59)

    mid_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-059",
      knowledge_query="潮汐账本",
      task_instruction="写第 59 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("第58章线索", mid_bundle.context_text)
    self.assertNotIn("第60章真相", mid_bundle.context_text)
    self.assertNotIn("旧船队背叛真相", mid_bundle.context_text)

    future_bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-060",
      knowledge_query="潮汐账本",
      task_instruction="写第 60 章。",
      task_pack_kind="continuation",
    )
    self.assertIn("第60章真相", future_bundle.context_text)
    self.assertIn("潮汐账本", future_bundle.context_text)

  def test_narrative_state_reports_obsidian_scope_mismatch_as_graph_repair(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-scope-mismatch"
    (vault_dir / "Graph").mkdir(parents=True)
    (vault_dir / "Graph" / "潮汐账本.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: graph_note",
          "chapter_range: 第 58-60 章",
          "---",
          "# 潮汐账本",
          "潮汐账本在中段指向旧船队账页。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "后段线索.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "chapter_range: 第 80-82 章",
          "---",
          "# 后段线索",
          "第八十章后，林追再次追到 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "repair_graph_link" and "章节范围不匹配" in item["title"]
    )
    self.assertEqual(suggestion["priority"], "high")
    self.assertEqual(suggestion["status"], "open")
    self.assertIn("调整目标笔记章节范围", suggestion["action"])
    self.assertEqual(suggestion["draft_markdown"], "")
    summary = state["obsidian_maintenance_summary"]
    self.assertGreaterEqual(summary["high_priority"], 1)
    self.assertEqual(summary["top_items"][0]["id"], suggestion["id"])
    capability_context = build_agent_capability_context(Path(self.project.path))
    self.assertIn("章节范围不匹配", capability_context)
    self.assertIn("潮汐账本", capability_context)

  def test_pending_obsidian_draft_prompt_respects_manual_frontmatter_scope(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-manual-scope"
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertNotIn("reveal_after_chapter", suggestion["draft_markdown"])

    draft_path = Path(suggestion["draft_path"])
    draft_text = draft_path.read_text(encoding="utf-8")
    draft_path.write_text(
      draft_text.replace("usable_by_ai: true\n", "usable_by_ai: true\ntags: [第58章起, 剧透/57]\n", 1),
      encoding="utf-8",
    )

    detail = get_project_detail(self.settings, self.project.id)
    early_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-010")
    self.assertNotIn("Obsidian 待审草稿", early_prompt)
    self.assertNotIn("Graph/潮汐账本.md", early_prompt)

    future_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-058")
    self.assertIn("Obsidian 待审草稿", future_prompt)
    self.assertIn("Graph/潮汐账本.md", future_prompt)
    later_prompt = build_project_narrative_state_prompt(Path(self.project.path), detail, "chapter-080")
    self.assertIn("Obsidian 待审草稿", later_prompt)
    self.assertIn("Graph/潮汐账本.md", later_prompt)

  def test_ignored_obsidian_maintenance_inherits_by_path_and_skips_auto_stage(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-ignore-graph"
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

    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(initial_suggestion["status"], "open")
    ignored = ignore_project_obsidian_maintenance_note(self.settings, self.project.id, initial_suggestion["id"])
    self.assertEqual(ignored["status"], "ignored")

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
    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(refreshed_suggestion["status"], "ignored")
    self.assertTrue(refreshed_suggestion["status_inherited_from_path"])
    self.assertFalse(refreshed_suggestion["auto_staged"])
    self.assertEqual(refreshed_suggestion["draft_path"], "")
    summary = refreshed_state["obsidian_maintenance_summary"]
    self.assertGreaterEqual(summary["by_status"]["ignored"], 1)
    self.assertNotIn(
      refreshed_suggestion["id"],
      [str(item.get("id") or "") for item in summary["top_items"]],
    )
    context = build_agent_capability_context(Path(self.project.path))
    self.assertIn("Obsidian 维护摘要", context)
    self.assertIn("已忽略", context)
    self.assertNotIn("潮汐账本", context)

  def test_reopened_obsidian_maintenance_reenters_auto_stage(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-reopen-graph"
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

    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    ignore_project_obsidian_maintenance_note(self.settings, self.project.id, initial_suggestion["id"])
    ignored_state = load_project_narrative_state(Path(self.project.path))
    ignored_suggestion = next(
      item
      for item in ignored_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(ignored_suggestion["status"], "ignored")

    reopened = reopen_project_obsidian_maintenance_note(self.settings, self.project.id, ignored_suggestion["id"])
    self.assertEqual(reopened["status"], "open")
    reopened_state = load_project_narrative_state(Path(self.project.path))
    reopened_suggestion = next(
      item
      for item in reopened_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(reopened_suggestion["status"], "open")
    self.assertEqual(reopened_state["obsidian_maintenance_summary"]["by_status"]["ignored"], 0)

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
    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertTrue(Path(refreshed_suggestion["draft_path"]).exists())
    context = build_agent_capability_context(Path(self.project.path))
    self.assertIn("潮汐账本", context)

  def test_auto_staged_graph_draft_updates_when_unedited_source_list_changes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-draft-update"
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    initial_draft_path = Path(initial_suggestion["draft_path"])
    self.assertEqual(initial_suggestion["status"], "staged")
    self.assertIn("线索乙.md", initial_draft_path.read_text(encoding="utf-8"))
    self.assertNotIn("线索丙.md", initial_draft_path.read_text(encoding="utf-8"))

    (vault_dir / "线索丙.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索丙",
          "第三条来源也把 [[潮汐账本]] 指向旧船队背叛线索。",
        ]
      ),
      encoding="utf-8",
    )
    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    refreshed_draft_path = Path(refreshed_suggestion["draft_path"])
    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertEqual(refreshed_draft_path, initial_draft_path)
    refreshed_text = refreshed_draft_path.read_text(encoding="utf-8")
    self.assertIn("线索甲.md", refreshed_text)
    self.assertIn("线索乙.md", refreshed_text)
    self.assertIn("线索丙.md", refreshed_text)

  def test_auto_staged_graph_draft_reports_missing_file_and_can_be_saved_again(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-draft-missing"
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    draft_path = Path(initial_suggestion["draft_path"])
    draft_path.unlink()

    refreshed = refresh_project_narrative_state_chapter_cards(
      Path(self.project.path),
      get_project_detail(self.settings, self.project.id),
      persist=True,
    )
    missing_suggestion = next(
      item
      for item in refreshed["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(missing_suggestion["status"], "draft_missing")
    self.assertTrue(missing_suggestion["draft_missing"])
    self.assertEqual(Path(missing_suggestion["draft_path"]), draft_path)

    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, missing_suggestion["id"])
    self.assertEqual(Path(staged["draft_path"]), draft_path)
    self.assertTrue(draft_path.exists())
    staged_state = load_project_narrative_state(Path(self.project.path))
    staged_suggestion = next(
      item
      for item in staged_state["obsidian_maintenance_suggestions"]
      if item["id"] == missing_suggestion["id"]
    )
    self.assertEqual(staged_suggestion["status"], "staged")
    self.assertFalse(staged_suggestion["draft_missing"])

  def test_published_graph_maintenance_reports_missing_vault_note_and_can_publish_again(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-published-missing"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    published_path = Path(published["vault_path"])
    self.assertTrue(published_path.exists())
    published_path.unlink()
    sync_project_obsidian(self.settings, self.project.id)

    missing_state = load_project_narrative_state(Path(self.project.path))
    missing_suggestion = next(
      item
      for item in missing_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(missing_suggestion["status"], "published_missing")
    self.assertTrue(missing_suggestion["published_missing"])
    self.assertEqual(missing_suggestion["vault_relative_path"], published["vault_relative_path"])
    missing_summary = missing_state["obsidian_maintenance_summary"]
    self.assertGreaterEqual(missing_summary["by_status"]["published_missing"], 1)
    self.assertGreaterEqual(missing_summary["needs_action"], 1)
    self.assertEqual(missing_summary["top_items"][0]["status"], "published_missing")

    republished = publish_project_obsidian_maintenance_note(self.settings, self.project.id, missing_suggestion["id"])
    self.assertEqual(republished["status"], "published")
    self.assertEqual(republished["vault_relative_path"], published["vault_relative_path"])
    self.assertTrue(Path(republished["vault_path"]).exists())

  def test_moved_published_obsidian_note_rebinds_vault_path_without_missing(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-published-moved"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    old_path = Path(published["vault_path"])
    new_path = vault_dir / "Graph" / "Moved" / "潮汐账本.md"
    new_path.parent.mkdir(parents=True)
    old_path.rename(new_path)

    sync_project_obsidian(self.settings, self.project.id)

    moved_state = load_project_narrative_state(Path(self.project.path))
    latest_action = next(
      item
      for item in reversed(moved_state["obsidian_maintenance_actions"])
      if item.get("suggestion_id") == suggestion["id"] and item.get("status") == "published"
    )
    self.assertEqual(latest_action["vault_relative_path"], "Graph/Moved/潮汐账本.md")
    self.assertEqual(latest_action["relative_path"], "Graph/Moved/潮汐账本.md")
    self.assertEqual(latest_action["moved_from_vault_relative_path"], published["vault_relative_path"])
    self.assertTrue(str(latest_action.get("rebound_from_action_id") or "").startswith("obsidian-maintenance-action-"))
    self.assertTrue(new_path.exists())
    detail = get_project_detail(self.settings, self.project.id)
    moved_note = next(
      item
      for item in detail.story_overview.obsidian.notes
      if item.title == "潮汐账本"
    )
    self.assertEqual(moved_note.relative_path, "Graph/Moved/潮汐账本.md")
    self.assertFalse(
      any(
        item.get("kind") == "create_graph_note"
        and item.get("published_missing")
        and "潮汐账本" in item.get("title", "")
        for item in moved_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_moved_and_edited_published_obsidian_note_rebinds_by_identity(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-published-moved-edited"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertIn(f"gaoxia_maintenance_id: {suggestion['id']}", suggestion["draft_markdown"])
    self.assertIn("gaoxia_maintenance_kind: create_graph_note", suggestion["draft_markdown"])
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    old_path = Path(published["vault_path"])
    new_path = vault_dir / "Graph" / "Renamed" / "潮汐账本-作者整理.md"
    new_path.parent.mkdir(parents=True)
    text = old_path.read_text(encoding="utf-8")
    old_path.rename(new_path)
    edited_text = text.rstrip() + "\n\n作者补记：这份账本后来被移动并增补来源说明。\n"
    new_path.write_text(edited_text, encoding="utf-8")

    sync_project_obsidian(self.settings, self.project.id)

    moved_state = load_project_narrative_state(Path(self.project.path))
    latest_action = next(
      item
      for item in reversed(moved_state["obsidian_maintenance_actions"])
      if item.get("suggestion_id") == suggestion["id"] and item.get("status") == "published"
    )
    self.assertEqual(latest_action["vault_relative_path"], "Graph/Renamed/潮汐账本-作者整理.md")
    self.assertEqual(latest_action["rebound_match"], "maintenance_id")
    self.assertEqual(latest_action["gaoxia_maintenance_id"], suggestion["id"])
    self.assertTrue(latest_action["published_from_manual_edits"])
    self.assertEqual(latest_action["published_content_hash"], _text_content_hash(edited_text))
    self.assertFalse(
      any(
        item.get("kind") == "create_graph_note"
        and item.get("published_missing")
        and "潮汐账本" in item.get("title", "")
        for item in moved_state["obsidian_maintenance_suggestions"]
      )
    )

  def test_publish_readds_missing_maintenance_identity_before_vault_write(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-published-identity-restored"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, suggestion["id"])
    draft_path = Path(staged["draft_path"])
    draft_text = draft_path.read_text(encoding="utf-8")
    draft_without_identity = "\n".join(
      line
      for line in draft_text.splitlines()
      if not line.startswith("gaoxia_maintenance_id:")
      and not line.startswith("gaoxia_maintenance_kind:")
    ) + "\n"
    draft_path.write_text(draft_without_identity, encoding="utf-8")

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    published_path = Path(published["vault_path"])
    published_text = published_path.read_text(encoding="utf-8")
    self.assertIn(f"gaoxia_maintenance_id: {suggestion['id']}", published_text)
    self.assertIn("gaoxia_maintenance_kind: create_graph_note", published_text)

    moved_path = vault_dir / "Graph" / "Renamed" / "潮汐账本-发布时恢复身份.md"
    moved_path.parent.mkdir(parents=True)
    published_path.rename(moved_path)
    edited_text = published_text.rstrip() + "\n\n作者补记：发布前身份字段曾被删掉，发布时已恢复。\n"
    moved_path.write_text(edited_text, encoding="utf-8")

    sync_project_obsidian(self.settings, self.project.id)

    moved_state = load_project_narrative_state(Path(self.project.path))
    latest_action = next(
      item
      for item in reversed(moved_state["obsidian_maintenance_actions"])
      if item.get("suggestion_id") == suggestion["id"] and item.get("status") == "published"
    )
    self.assertEqual(latest_action["vault_relative_path"], "Graph/Renamed/潮汐账本-发布时恢复身份.md")
    self.assertEqual(latest_action["rebound_match"], "maintenance_id")

  def test_moved_and_edited_published_obsidian_note_keeps_missing_when_identity_is_duplicated(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-published-moved-duplicate-identity"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, suggestion["id"])
    old_path = Path(published["vault_path"])
    new_path = vault_dir / "Graph" / "Renamed" / "潮汐账本-作者整理.md"
    duplicate_path = vault_dir / "Graph" / "Duplicate" / "潮汐账本-重复身份.md"
    new_path.parent.mkdir(parents=True)
    duplicate_path.parent.mkdir(parents=True)
    text = old_path.read_text(encoding="utf-8")
    old_path.rename(new_path)
    new_path.write_text(text.rstrip() + "\n\n作者补记：这份账本被移动后改过正文。\n", encoding="utf-8")
    duplicate_path.write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: graph",
          f"gaoxia_maintenance_id: {suggestion['id']}",
          "gaoxia_maintenance_kind: create_graph_note",
          "---",
          "# 潮汐账本重复身份",
          "这是另一份带相同维护身份的手工笔记。",
        ]
      )
      + "\n",
      encoding="utf-8",
    )

    sync_project_obsidian(self.settings, self.project.id)

    moved_state = load_project_narrative_state(Path(self.project.path))
    published_actions = [
      item
      for item in moved_state["obsidian_maintenance_actions"]
      if item.get("suggestion_id") == suggestion["id"] and item.get("status") == "published"
    ]
    self.assertEqual(len(published_actions), 1)
    latest_action = published_actions[-1]
    self.assertEqual(latest_action["vault_relative_path"], published["vault_relative_path"])
    self.assertNotIn("rebound_match", latest_action)

  def test_published_generated_obsidian_note_reports_outdated_without_flagging_manual_vault_edits(self) -> None:
    project_dir = Path(self.project.path)
    vault_dir = Path(self._temp_dir.name) / "vault-graph-published-outdated"
    (vault_dir / "Graph").mkdir(parents=True)
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    published_text = "\n".join(
      [
        "---",
        "status: canonical",
        "type: graph_note",
        "---",
        "# 潮汐账本",
        "林追在旧账册里看见 [[线索甲]]。",
      ]
    ) + "\n"
    updated_text = "\n".join(
      [
        "---",
        "status: canonical",
        "type: graph_note",
        "---",
        "# 潮汐账本",
        "林追在旧账册里看见 [[线索甲]]。",
        "宋闻也把 [[线索乙]] 当成旧船队背叛线索。",
      ]
    ) + "\n"
    vault_note = vault_dir / "Graph" / "潮汐账本.md"
    vault_note.write_text(published_text, encoding="utf-8")
    draft_path = project_dir / ".gaoxia" / "obsidian_drafts" / "Graph" / "潮汐账本.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(published_text, encoding="utf-8")
    published_hash = _text_content_hash(published_text)
    state = {
      "obsidian_maintenance_actions": [
        {
          "id": "obsidian-maintenance-action-published",
          "suggestion_id": "graph-note",
          "status": "published",
          "title": "整理 Obsidian 图谱：潮汐账本",
          "draft_path": str(draft_path),
          "relative_path": "Graph/潮汐账本.md",
          "vault_path": str(vault_note),
          "vault_relative_path": "Graph/潮汐账本.md",
          "draft_content_hash": published_hash,
          "published_content_hash": published_hash,
          "published_from_manual_edits": False,
        }
      ]
    }
    suggestions = [
      {
        "id": "graph-note",
        "kind": "create_graph_note",
        "priority": "medium",
        "title": "整理 Obsidian 图谱：潮汐账本",
        "suggested_path": "Graph/潮汐账本.md",
        "draft_markdown": updated_text,
      }
    ]

    hydrated = _attach_maintenance_action_status(suggestions, state, project_dir)
    self.assertEqual(hydrated[0]["status"], "published_outdated")
    self.assertTrue(hydrated[0]["published_outdated"])
    summary = _obsidian_maintenance_summary(hydrated)
    self.assertEqual(summary["by_status"]["published_outdated"], 1)
    self.assertEqual(summary["needs_action"], 1)
    self.assertEqual(summary["top_items"][0]["status"], "published_outdated")

    vault_note.write_text(published_text + "\n人工修订：作者已经合并新版关系。\n", encoding="utf-8")
    hydrated_after_manual_edit = _attach_maintenance_action_status(suggestions, state, project_dir)
    self.assertEqual(hydrated_after_manual_edit[0]["status"], "published")
    self.assertFalse(hydrated_after_manual_edit[0]["published_outdated"])

  def test_auto_staged_graph_draft_preserves_manual_edits_when_source_list_changes(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-graph-draft-manual"
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    initial_suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    draft_path = Path(initial_suggestion["draft_path"])
    draft_path.write_text(
      draft_path.read_text(encoding="utf-8") + "\n人工备注：这个图谱节点需要改成组织设定。\n",
      encoding="utf-8",
    )
    refresh_project_narrative_state_chapter_cards(
      Path(self.project.path),
      get_project_detail(self.settings, self.project.id),
      persist=True,
    )
    manually_edited_state = load_project_narrative_state(Path(self.project.path))
    manually_edited_suggestion = next(
      item
      for item in manually_edited_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(manually_edited_suggestion["status"], "staged")
    self.assertTrue(manually_edited_suggestion["manual_draft_edits"])

    (vault_dir / "线索丙.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索丙",
          "第三条来源也把 [[潮汐账本]] 指向旧船队背叛线索。",
        ]
      ),
      encoding="utf-8",
    )
    sync_project_obsidian(self.settings, self.project.id)

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    draft_text = draft_path.read_text(encoding="utf-8")
    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertTrue(refreshed_suggestion["status_inherited_from_path"])
    self.assertTrue(refreshed_suggestion["manual_draft_edits"])
    self.assertEqual(Path(refreshed_suggestion["draft_path"]), draft_path)
    self.assertIn("人工备注：这个图谱节点需要改成组织设定。", draft_text)
    self.assertNotIn("线索丙.md", draft_text)

    published = publish_project_obsidian_maintenance_note(self.settings, self.project.id, refreshed_suggestion["id"])
    published_text = Path(published["vault_path"]).read_text(encoding="utf-8")
    self.assertIn("人工备注：这个图谱节点需要改成组织设定。", published_text)
    self.assertNotIn("线索丙.md", published_text)

  def test_stage_obsidian_maintenance_draft_preserves_existing_manual_edits(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-stage-preserve"
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
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
    suggestion = next(
      item
      for item in initial_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    draft_path = Path(suggestion["draft_path"])
    draft_path.write_text(
      draft_path.read_text(encoding="utf-8") + "\n人工备注：发布前改成组织设定。\n",
      encoding="utf-8",
    )

    staged = stage_project_obsidian_maintenance_draft(self.settings, self.project.id, suggestion["id"])

    self.assertTrue(staged["preserved_existing_draft"])
    draft_text = draft_path.read_text(encoding="utf-8")
    self.assertIn("人工备注：发布前改成组织设定。", draft_text)
    self.assertEqual(Path(staged["draft_path"]), draft_path)
    staged_state = load_project_narrative_state(Path(self.project.path))
    staged_suggestion = next(
      item
      for item in staged_state["obsidian_maintenance_suggestions"]
      if item["id"] == suggestion["id"]
    )
    self.assertEqual(staged_suggestion["status"], "staged")
    self.assertTrue(staged_suggestion["preserved_existing_draft"])
    self.assertTrue(staged_suggestion["manual_draft_edits"])
    latest_action = next(
      item
      for item in reversed(staged_state["obsidian_maintenance_actions"])
      if item.get("suggestion_id") == suggestion["id"]
    )
    self.assertTrue(latest_action["preserved_existing_draft"])

  def test_context_generation_refreshes_graph_maintenance_after_vault_change(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-context-graph"
    vault_dir.mkdir()
    (vault_dir / "线索甲.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "type: clue",
          "---",
          "# 线索甲",
          "林追在旧账册里看见 [[潮汐账本]]。",
        ]
      ),
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    initial_state = load_project_narrative_state(Path(self.project.path))
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
    bundle = build_project_context_bundle(
      self.settings,
      self.project.id,
      chapter_id="chapter-059",
      task_instruction="写第 59 章。",
      task_pack_kind="continuation",
    )

    refreshed_state = load_project_narrative_state(Path(self.project.path))
    refreshed_suggestion = next(
      item
      for item in refreshed_state["obsidian_maintenance_suggestions"]
      if item["kind"] == "create_graph_note" and "潮汐账本" in item["title"]
    )
    self.assertEqual(refreshed_suggestion["status"], "staged")
    self.assertTrue(refreshed_suggestion["auto_staged"])
    self.assertIn("Graph/", refreshed_suggestion["suggested_path"])
    self.assertTrue(Path(refreshed_suggestion["draft_path"]).exists())
    self.assertIn("Obsidian 待审草稿", bundle.context_text)
    self.assertIn("Graph/", bundle.context_text)

  def test_model_editor_receives_obsidian_guidance_for_next_chapter(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-model"
    vault_dir.mkdir()
    (vault_dir / "第58章合同.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 58",
          "required_phrases:",
          "  - 遗言线索必须造成一次行动选择",
          "forbidden_phrases:",
          "  - 直接公布铜钥匙最终身份",
          "---",
          "# 第58章合同",
          "第 58 章写作时必须让遗言线索变成行动压力。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第58章场景卡.md").write_text(
      "\n".join(
        [
          "---",
          "type: scene_plan",
          "status: canonical",
          "chapter: 58",
          "---",
          "# 第58章场景卡",
          "场景一：遗言线索逼林追立刻改变行动。",
          "场景二：宋闻必须回避一个关键问题。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第58章母亲遗言债务.md").write_text(
      "\n".join(
        [
          "---",
          "type: narrative_debt",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 62",
          "---",
          "# 第58章母亲遗言债务",
          "母亲遗言还有旧船队背叛线索，林追必须追问宋闻。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "林追信任弧线.md").write_text(
      "\n".join(
        [
          "---",
          "type: character_arc",
          "status: canonical",
          "chapter_start: 58",
          "chapter_end: 62",
          "---",
          "# 林追信任弧线",
          "林追不能无条件相信宋闻，下一次行动要保留怀疑。",
        ]
      ),
      encoding="utf-8",
    )
    (vault_dir / "第72章合同.md").write_text(
      "\n".join(
        [
          "---",
          "status: canonical",
          "chapter_start: 72",
          "required_phrases:",
          "  - 第七十二章终局证言",
          "---",
          "# 第72章合同",
          "后段真相。",
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
      "chapter-057",
      ChapterUpdateRequest(
        content=(
          "# 第五十七章 铜钥匙\n"
          "林追终于确认铜钥匙藏着旧船队身份秘密。\n"
          "宋闻承认母亲遗言里还压着旧船队背叛线索。\n"
        ),
      ),
    )
    captured: dict[str, object] = {}

    def fake_invoke(_settings, messages):
      captured["system"] = messages[0]["content"]
      captured["payload"] = json.loads(messages[1]["content"])
      return (
        json.dumps(
          {
            "summary": "已读取 Obsidian 下一章约束。",
            "debt_updates": [],
            "character_arc_updates": [],
            "contract_review": {},
            "next_chapter_contract": {},
            "risk_notes": [],
          },
          ensure_ascii=False,
        ),
        "review_model",
      )

    with patch(
      "novel_backend.services.project_narrative_state_service._model_available",
      return_value=True,
    ), patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      side_effect=fake_invoke,
    ):
      record_project_narrative_state_observation(
        Path(self.project.path),
        get_project_detail(self.settings, self.project.id),
        "chapter-057",
        settings=self.settings,
      )

    payload = captured["payload"]
    next_obsidian = payload["obsidian_next_chapter"]
    self.assertIn("遗言线索必须造成一次行动选择", next_obsidian["required"])
    self.assertIn("直接公布铜钥匙最终身份", next_obsidian["forbidden"])
    self.assertTrue(next_obsidian["chapter_plans"])
    self.assertIn("遗言线索逼林追立刻改变行动", next_obsidian["chapter_plans"][0]["plan_lines"][0])
    self.assertTrue(next_obsidian["narrative_debts"])
    self.assertIn("母亲遗言还有旧船队背叛线索", next_obsidian["narrative_debts"][0]["content"])
    self.assertTrue(next_obsidian["character_arcs"])
    self.assertIn("林追不能无条件相信宋闻", next_obsidian["character_arcs"][0]["current_state"])
    self.assertIn("剧情债务、人物弧线", captured["system"])
    self.assertNotIn("第七十二章终局证言", next_obsidian["required"])


if __name__ == "__main__":
  unittest.main()
