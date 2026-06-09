from __future__ import annotations

import base64
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  AgentArtifact,
  AgentEventBlock,
  AgentExecutionTrace,
  AgentPlan,
  AgentPlanAction,
  AgentStateSummary,
  AgentThreadMessage,
  AgentThreadRecord,
  AgentThreadStoreUpdateRequest,
  AppConfigUpdateRequest,
  ArchitectureWorkspace,
  ArchitectureWorkspaceApplyRequest,
  ChapterReviewRefreshRequest,
  ChapterUpdateRequest,
  CreateProjectRequest,
  EmbeddingConfig,
  EXISTING_NOVEL_IMPORT_BASE64_MAX_LENGTH,
  EXISTING_NOVEL_IMPORT_FILE_MAX_BYTES,
  ExistingNovelImportRequest,
  KnowledgeImportItem,
  KnowledgeImportRequest,
  ModelConfig,
  ObsidianVaultConfig,
  ProjectDreamPromoteRequest,
  ProjectDreamRunRequest,
  ProjectExportRequest,
  ProjectMigrationImportRequest,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
  ProjectRenameRequest,
  ReviewModelConfig,
  SnapshotCreateRequest,
  StyleSaveRequest,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentPatch,
  StoryDocumentUpdateRequest,
)
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.file_service import write_project_file
from novel_backend.services.context_builder import build_project_context_bundle
from novel_backend.api.projects import (
  _chapter_mutation_response,
  _project_action_response,
  router as project_api_router,
  post_project_obsidian_sync,
  post_existing_novel_import,
  post_project_migration_import,
  put_project_obsidian,
)
from novel_backend.services.chapter_auto_repair_service import (
  auto_repair_chapter_after_review,
  chapter_review_needs_auto_repair,
)
from novel_backend.services.chapter_review_service import _obsidian_dimension, _obsidian_evidence_paths
from novel_backend.services.project_distillation_service import (
  build_project_distillation_signature,
  build_distillation_review_text,
  build_task_distillation_prompt_block,
  resolve_task_pack_kind,
)
from novel_backend.services.project_service import (
  _initialize_knowledge_db,
  apply_architecture_workspace,
  create_project,
  create_project_snapshot,
  delete_project,
  export_project_book,
  export_project_migration_package,
  get_project_agent_threads,
  get_project_detail,
  import_project_knowledge,
  import_project_migration_package,
  list_projects,
  open_project_directory,
  promote_project_dream,
  rename_project,
  restore_project_snapshot,
  run_project_dream,
  save_project_agent_threads,
  search_project_knowledge,
  refresh_chapter_review,
  refresh_project_model_story_overview,
  summarize_chapter_review_status,
  update_project_memory,
  update_chapter_content,
  update_chapter_content_with_review_status,
  update_project_obsidian_config,
  update_story_documents,
  update_story_document,
)
from novel_backend.services.project_takeover_service import (
  get_existing_novel_takeover_state,
  import_existing_novel,
  resume_existing_novel_takeover,
  split_existing_novel_chapters,
)
from novel_backend.services.style_service import save_style


class ProjectServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt")
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def create_demo_project(self, name: str = "测试项目"):
    return create_project(
      self.settings,
      CreateProjectRequest(
        name=name,
        genre="悬疑",
        target_chapters=3,
        target_words=50000,
      ),
    )

  def write_chapter(self, project_path: str, index: int, content: str) -> None:
    chapter_path = Path(project_path) / "chapters" / f"{index:03d}.md"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(content, encoding="utf-8")

  def test_story_overview_without_model_cache_keeps_entities_empty(self) -> None:
    summary = self.create_demo_project("本地总览")
    project_dir = Path(summary.path)
    (project_dir / "character_design.txt").write_text(
      "林追：港口里最会追线索的人，擅长开锁，隶属白石商会。\n苏青：掌握旧账本，和林追一起追查潮汐航线。\n",
      encoding="utf-8",
    )
    (project_dir / "blueprint.txt").write_text(
      "雨夜靠港：\nchapter：1\ngoal：林追在旧码头仓库用开锁技巧打开铁门，找到一把铜钥匙，随后闯进白石商会。\n",
      encoding="utf-8",
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库用开锁技巧打开铁门，找到一把铜钥匙，随后闯进白石商会。\n",
    )

    with patch.dict(
      os.environ,
      {
        "NOVEL_MODEL_API_KEY": "",
        "DASHSCOPE_API_KEY": "",
        "ARK_API_KEY": "",
        "NOVEL_API_KEY": "",
        "OPENAI_API_KEY": "",
        "NOVEL_REVIEW_MODEL_API_KEY": "",
        "NOVEL_AUXILIARY_MODEL_API_KEY": "",
      },
    ):
      detail = get_project_detail(self.settings, summary.id)

    documents = {item.key: item.content for item in detail.story_overview.documents}
    self.assertIn("林追", documents["character_design"])
    self.assertEqual(detail.story_overview.model_overview.status, "disabled")
    self.assertEqual(detail.story_overview.characters, [])
    self.assertEqual(detail.story_overview.events, [])
    self.assertEqual(detail.story_overview.locations, [])
    self.assertEqual(detail.story_overview.props, [])
    self.assertEqual(detail.story_overview.skills, [])
    self.assertEqual(detail.story_overview.scenes, [])
    self.assertEqual(detail.story_overview.organizations, [])

  def test_story_overview_uses_validated_model_cache_for_all_sections(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(),
        review_model=ReviewModelConfig(
          enabled=True,
          api_key="real-key",
          base_url="https://model.local/v1",
          model_name="overview-model",
          max_tokens=4096,
        ),
      ),
    )
    summary = self.create_demo_project("模型总览")
    project_dir = Path(summary.path)
    (project_dir / "character_design.txt").write_text(
      (
        "林晚在发布会现场被当众羞辱，这场公开羞辱让证据账本落在陈小雨手里。"
        "林晚隶属明成集团，擅长危机公关。"
      ),
      encoding="utf-8",
    )
    model_content = json.dumps(
      {
        "characters": [
          {
            "name": "林晚",
            "profile": "明成集团创意总监。",
            "current_state": "在发布会现场被当众羞辱。",
            "relationships": ["陈小雨：掌握证据账本"],
            "events": ["公开羞辱"],
            "locations": ["发布会现场"],
            "props": ["证据账本"],
            "skills": ["危机公关"],
            "organizations": ["明成集团"],
            "evidence": ["林晚在发布会现场被当众羞辱"],
          },
          {
            "name": "项目文",
            "profile": "模型误判。",
            "evidence": ["不存在的证据"],
          },
        ],
        "events": [
          {
            "name": "公开羞辱",
            "summary": "林晚在发布会现场被当众羞辱。",
            "related_characters": ["林晚"],
            "evidence": ["这场公开羞辱让证据账本落在陈小雨手里"],
          },
          {
            "name": "黑箱会议",
            "summary": "不存在。",
            "related_characters": ["林晚"],
            "evidence": ["不存在的证据"],
          },
        ],
        "locations": [{"name": "发布会现场", "related_characters": ["林晚"], "evidence": ["发布会现场被当众羞辱"]}],
        "props": [{"name": "证据账本", "related_characters": ["林晚"], "evidence": ["证据账本落在陈小雨手里"]}],
        "skills": [{"name": "危机公关", "related_characters": ["林晚"], "evidence": ["擅长危机公关"]}],
        "organizations": [{"name": "明成集团", "related_characters": ["林晚"], "evidence": ["林晚隶属明成集团"]}],
        "scenes": [],
      },
      ensure_ascii=False,
    )

    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      return_value={"choices": [{"message": {"content": model_content}}]},
    ) as mocked_request:
      detail = get_project_detail(self.settings, summary.id, allow_model_overview=True)

    self.assertEqual(mocked_request.call_count, 1)
    character_names = [item.name for item in detail.story_overview.characters]
    self.assertIn("林晚", character_names)
    self.assertNotIn("项目文", character_names)
    lin_wan = next(item for item in detail.story_overview.characters if item.name == "林晚")
    self.assertIn("公开羞辱", lin_wan.events)
    self.assertIn("发布会现场", lin_wan.locations)
    self.assertIn("证据账本", lin_wan.props)
    self.assertIn("危机公关", lin_wan.skills)
    self.assertIn("明成集团", lin_wan.organizations)
    self.assertIn("公开羞辱", [item.name for item in detail.story_overview.events])
    self.assertNotIn("黑箱会议", [item.name for item in detail.story_overview.events])

    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      side_effect=AssertionError("模型总览缓存有效时不应重复请求"),
    ):
      cached_detail = get_project_detail(self.settings, summary.id)
    self.assertIn("林晚", [item.name for item in cached_detail.story_overview.characters])

    replacement_content = json.dumps(
      {
        "characters": [
          {
            "name": "陈小雨",
            "current_state": "掌握证据账本。",
            "evidence": ["陈小雨手里"],
          }
        ],
        "events": [],
        "locations": [],
        "props": [{"name": "证据账本", "related_characters": ["陈小雨"], "evidence": ["证据账本落在陈小雨手里"]}],
        "skills": [],
        "scenes": [],
        "organizations": [],
      },
      ensure_ascii=False,
    )
    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      return_value={"choices": [{"message": {"content": replacement_content}}]},
    ) as mocked_refresh:
      refreshed_detail = refresh_project_model_story_overview(self.settings, summary.id, force=True)
    self.assertEqual(mocked_refresh.call_count, 1)
    refreshed_names = [item.name for item in refreshed_detail.story_overview.characters]
    self.assertIn("陈小雨", refreshed_names)

  def test_story_overview_uses_primary_model_when_review_model_disabled(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          api_key="real-key",
          base_url="https://primary.local/v1",
          model_name="primary-overview-model",
          max_tokens=4096,
        ),
        review_model=ReviewModelConfig(enabled=False),
      ),
    )
    summary = self.create_demo_project("写作模型总览")
    project_dir = Path(summary.path)
    (project_dir / "character_design.txt").write_text(
      "林晚在发布会现场被当众羞辱，陈小雨拿走证据账本。",
      encoding="utf-8",
    )
    model_content = json.dumps(
      {
        "characters": [
          {
            "name": "林晚",
            "current_state": "在发布会现场被当众羞辱。",
            "relationships": ["陈小雨：拿走证据账本"],
            "events": ["发布会羞辱"],
            "evidence": ["林晚在发布会现场被当众羞辱"],
          }
        ],
        "events": [{"name": "发布会羞辱", "related_characters": ["林晚"], "evidence": ["发布会现场被当众羞辱"]}],
        "locations": [],
        "props": [{"name": "证据账本", "related_characters": ["林晚"], "evidence": ["陈小雨拿走证据账本"]}],
        "skills": [],
        "scenes": [],
        "organizations": [],
      },
      ensure_ascii=False,
    )

    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      return_value={"choices": [{"message": {"content": model_content}}]},
    ) as mocked_request:
      detail = get_project_detail(self.settings, summary.id, allow_model_overview=True)

    self.assertEqual(mocked_request.call_count, 1)
    self.assertEqual(mocked_request.call_args.args[0], "https://primary.local/v1/chat/completions")
    self.assertEqual(mocked_request.call_args.kwargs["payload"]["model"], "primary-overview-model")
    self.assertEqual(mocked_request.call_args.kwargs["timeout"], 240)
    self.assertIn("林晚", [item.name for item in detail.story_overview.characters])
    self.assertIn("发布会羞辱", [item.name for item in detail.story_overview.events])
    self.assertIn("证据账本", [item.name for item in detail.story_overview.props])

  def test_story_overview_review_request_allows_model_overview(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          api_key="real-key",
          base_url="https://primary.local/v1",
          model_name="primary-overview-model",
          max_tokens=4096,
        ),
        review_model=ReviewModelConfig(enabled=False),
      ),
    )
    summary = self.create_demo_project("打开总览触发模型")
    Path(summary.path, "character_design.txt").write_text(
      "林晚在发布会现场被当众羞辱，陈小雨拿走证据账本。",
      encoding="utf-8",
    )
    model_content = json.dumps(
      {
        "characters": [
          {
            "name": "林晚",
            "current_state": "在发布会现场被当众羞辱。",
            "relationships": ["陈小雨：拿走证据账本"],
            "evidence": ["林晚在发布会现场被当众羞辱"],
          }
        ],
        "events": [],
        "locations": [],
        "props": [
          {
            "name": "证据账本",
            "related_characters": ["林晚"],
            "evidence": ["陈小雨拿走证据账本"],
          }
        ],
        "skills": [],
        "scenes": [],
        "organizations": [],
      },
      ensure_ascii=False,
    )

    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      return_value={"choices": [{"message": {"content": model_content}}]},
    ) as mocked_request:
      detail = get_project_detail(self.settings, summary.id, review_characters=True)

    self.assertEqual(mocked_request.call_count, 1)
    self.assertIn("林晚", [item.name for item in detail.story_overview.characters])
    self.assertIn("证据账本", [item.name for item in detail.story_overview.props])

  def test_refresh_story_overview_raises_when_no_model_cache_is_created(self) -> None:
    summary = self.create_demo_project("总览生成失败")
    Path(summary.path, "core_seed.txt").write_text("林晚在雨夜收到旧账本。", encoding="utf-8")

    with patch.dict(
      os.environ,
      {
        "NOVEL_MODEL_API_KEY": "",
        "DASHSCOPE_API_KEY": "",
        "ARK_API_KEY": "",
        "NOVEL_API_KEY": "",
        "OPENAI_API_KEY": "",
        "NOVEL_REVIEW_MODEL_API_KEY": "",
        "NOVEL_AUXILIARY_MODEL_API_KEY": "",
      },
    ):
      with self.assertRaisesRegex(RuntimeError, "模型总览生成失败"):
        refresh_project_model_story_overview(self.settings, summary.id, force=True)

    self.assertFalse((Path(summary.path) / ".gaoxia" / "story_overview_model.json").exists())

  def test_story_overview_model_failure_is_reported_without_local_entities(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(),
        review_model=ReviewModelConfig(
          enabled=True,
          api_key="bad-key",
          base_url="https://model.local/v1",
          model_name="overview-model",
        ),
      ),
    )
    summary = self.create_demo_project("模型失败总览")
    project_dir = Path(summary.path)
    (project_dir / "character_design.txt").write_text(
      "林晚：发布会现场被公开羞辱，陈小雨拿走证据账本。",
      encoding="utf-8",
    )

    with patch(
      "novel_backend.services.project_service.request_json_with_retries",
      side_effect=RuntimeError("模型请求失败: 401 invalid_api_key"),
    ):
      with self.assertRaisesRegex(RuntimeError, "模型总览生成失败.*invalid_api_key"):
        get_project_detail(self.settings, summary.id, review_characters=True)

    detail = get_project_detail(self.settings, summary.id)

    self.assertEqual(detail.story_overview.model_overview.status, "failed")
    self.assertIn("invalid_api_key", detail.story_overview.model_overview.message)
    self.assertNotIn("retry_after", detail.story_overview.model_overview.model_dump())
    self.assertEqual(detail.story_overview.characters, [])
    self.assertEqual(detail.story_overview.events, [])
    self.assertFalse((project_dir / ".gaoxia" / "story_overview_model.json").exists())
    failure_path = project_dir / ".gaoxia" / "story_overview_model_failure.json"
    failure_payload = json.loads(failure_path.read_text(encoding="utf-8"))
    self.assertNotIn("retry_after", failure_payload)

    model_content = json.dumps(
      {
        "characters": [
          {
            "name": "林晚",
            "current_state": "在发布会现场被当众羞辱。",
            "evidence": ["林晚：发布会现场被公开羞辱"],
          }
        ],
        "events": [],
        "locations": [],
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
    ) as retried_request:
      retried_detail = get_project_detail(self.settings, summary.id, review_characters=True)

    self.assertEqual(retried_request.call_count, 1)
    self.assertEqual(retried_detail.story_overview.model_overview.status, "ready")
    self.assertIn("林晚", [item.name for item in retried_detail.story_overview.characters])
    self.assertFalse(failure_path.exists())

  def test_story_overview_model_reads_every_source_chunk(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(),
        review_model=ReviewModelConfig(
          enabled=True,
          api_key="real-key",
          base_url="https://model.local/v1",
          model_name="overview-model",
          max_tokens=4096,
        ),
      ),
    )
    summary = self.create_demo_project("模型分片总览")
    project_dir = Path(summary.path)
    (project_dir / "character_design.txt").write_text(
      "林晚在发布会现场被当众羞辱，危机公关能力被迫公开。\n"
      + "过渡资料。" * 80
      + "\n许诺在地下档案室找到城防图，地下档案室属于北境档案馆。",
      encoding="utf-8",
    )

    def fake_model_response(_endpoint: str, **kwargs):
      prompt_text = kwargs["payload"]["messages"][1]["content"]
      payload = {
        "characters": [],
        "events": [],
        "locations": [],
        "props": [],
        "skills": [],
        "scenes": [],
        "organizations": [],
      }
      if "林晚在发布会现场被当众羞辱" in prompt_text:
        payload["characters"].append(
          {
            "name": "林晚",
            "current_state": "在发布会现场被当众羞辱。",
            "skills": ["危机公关"],
            "evidence": ["林晚在发布会现场被当众羞辱"],
          }
        )
        payload["skills"].append({"name": "危机公关", "related_characters": ["林晚"], "evidence": ["危机公关能力被迫公开"]})
      if "许诺在地下档案室找到城防图" in prompt_text:
        payload["characters"].append(
          {
            "name": "许诺",
            "current_state": "在地下档案室找到城防图。",
            "locations": ["地下档案室"],
            "props": ["城防图"],
            "organizations": ["北境档案馆"],
            "evidence": ["许诺在地下档案室找到城防图"],
          }
        )
        payload["locations"].append({"name": "地下档案室", "related_characters": ["许诺"], "evidence": ["地下档案室属于北境档案馆"]})
        payload["props"].append({"name": "城防图", "related_characters": ["许诺"], "evidence": ["找到城防图"]})
        payload["organizations"].append({"name": "北境档案馆", "related_characters": ["许诺"], "evidence": ["属于北境档案馆"]})
      return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    with (
      patch("novel_backend.services.project_service._MODEL_STORY_OVERVIEW_SOURCE_CHUNK_LIMIT", 100),
      patch("novel_backend.services.project_service.request_json_with_retries", side_effect=fake_model_response) as mocked_request,
    ):
      detail = get_project_detail(self.settings, summary.id, allow_model_overview=True)

    self.assertGreaterEqual(mocked_request.call_count, 2)
    character_names = [item.name for item in detail.story_overview.characters]
    self.assertIn("林晚", character_names)
    self.assertIn("许诺", character_names)
    self.assertIn("地下档案室", [item.name for item in detail.story_overview.locations])
    self.assertIn("城防图", [item.name for item in detail.story_overview.props])
    self.assertIn("北境档案馆", [item.name for item in detail.story_overview.organizations])

  def test_project_detail_includes_distillation_report_and_task_packs(self) -> None:
    summary = self.create_demo_project("蒸馏结构")
    project_dir = Path(summary.path)
    (project_dir / "core_seed.txt").write_text(
      "主角因为一把铜钥匙重新卷入旧船队失踪案。",
      encoding="utf-8",
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追把铜钥匙塞进口袋，听见港务会的人在后面追近。\n",
    )
    import_project_knowledge(
      self.settings,
      summary.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="船队侧记",
            content="旧船队失踪前最后一次靠港时，灯塔议会删掉了靠港记录。",
          ),
        ]
      ),
    )

    detail = get_project_detail(self.settings, summary.id)

    report = detail.story_overview.distillation_report
    self.assertIsNotNone(report)
    self.assertFalse(report.is_stale)
    self.assertTrue(report.source_profile.summary)
    self.assertEqual(report.source_profile.character_notes, [])
    pack_kinds = [item.kind for item in report.packs]
    self.assertIn("continuation", pack_kinds)
    self.assertIn("architecture", pack_kinds)
    continuation_pack = next(item for item in report.packs if item.kind == "continuation")
    self.assertTrue(continuation_pack.must_keep)
    self.assertTrue(continuation_pack.execution_focus)

  def test_project_detail_does_not_persist_generated_distillation(self) -> None:
    summary = self.create_demo_project("详情读取")
    project_dir = Path(summary.path)
    (project_dir / "core_seed.txt").write_text(
      "主角因为一把铜钥匙重新卷入旧船队失踪案。",
      encoding="utf-8",
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追把铜钥匙塞进口袋，听见港务会的人在后面追近。\n",
    )
    distillation_path = project_dir / "project_distillation.json"
    if distillation_path.exists():
      distillation_path.unlink()

    detail = get_project_detail(self.settings, summary.id)

    self.assertIsNotNone(detail.story_overview.distillation_report)
    self.assertFalse(distillation_path.exists())

  def test_distillation_review_text_selects_pack_by_instruction(self) -> None:
    summary = self.create_demo_project("任务包切换")
    project_dir = Path(summary.path)
    (project_dir / "core_seed.txt").write_text(
      "主角因为一把铜钥匙重新卷入旧船队失踪案。",
      encoding="utf-8",
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追把铜钥匙塞进口袋，听见港务会的人在后面追近。\n",
    )
    detail = get_project_detail(self.settings, summary.id)

    architecture_review = build_distillation_review_text(detail, instruction="请按现有资料重新整理整书架构。")
    persona_review = build_distillation_review_text(detail, instruction="我想做人物复刻，看看林追会怎么说。")

    self.assertIn("任务包：architecture", architecture_review)
    self.assertIn("任务包：persona", persona_review)
    self.assertEqual(resolve_task_pack_kind(rewrite_mode="humanize"), "imitation")

  def test_task_distillation_prompt_filters_obsidian_summary_by_chapter_scope(self) -> None:
    summary = self.create_demo_project("蒸馏 Obsidian 章节范围")
    vault_dir = Path(self._temp_dir.name) / "distillation-vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "00-终局真相.md").write_text(
      """---
status: canonical
chapter_range: "3-3"
reveal_after_chapter: 2
---
终局真相：沉船真相来自港务长自导自演。
""",
      encoding="utf-8",
    )
    (vault_dir / "10-当前线索.md").write_text(
      """---
status: canonical
chapter_range: "1-1"
source_url: "[旧码头灯塔记录](https://example.com/lighthouse-ledger)"
foreshadows:
  - 00-终局真相
---
当前线索：旧码头蓝灯只提示林追去仓库，不提前点名[[00-终局真相]]。
""",
      encoding="utf-8",
    )

    detail = update_project_obsidian_config(
      self.settings,
      summary.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )

    early_block = build_task_distillation_prompt_block(
      detail,
      kind="continuation",
      query="第一章旧码头蓝灯",
      chapter_index=1,
    )
    future_block = build_task_distillation_prompt_block(
      detail,
      kind="continuation",
      query="第三章沉船真相",
      chapter_index=3,
    )

    self.assertIn("当前线索", early_block)
    self.assertIn("旧码头蓝灯", early_block)
    self.assertIn("考据来源", early_block)
    self.assertIn("旧码头灯塔记录：https://example.com/lighthouse-ledger", early_block)
    self.assertNotIn("终局真相", early_block)
    self.assertNotIn("沉船真相", early_block)
    self.assertIn("终局真相", future_block)
    self.assertIn("沉船真相", future_block)

  def test_distillation_signature_includes_obsidian_external_references(self) -> None:
    note = SimpleNamespace(
      title="旧码头灯塔记录",
      relative_path="Clues/旧码头灯塔记录.md",
      preview="旧码头蓝灯只提示林追去仓库。",
      updated_at="",
      graph_relations=[],
      resolved_links=[],
      backlinks=[],
      unresolved_links=[],
      ambiguous_links=[],
      external_references=["旧码头灯塔记录：https://example.com/lighthouse-ledger"],
      external_links=["https://example.com/lighthouse-ledger"],
    )
    detail = SimpleNamespace(
      story_overview=SimpleNamespace(
        documents=[],
        materials=[],
        obsidian=SimpleNamespace(notes=[note]),
        memory_entries=[],
      ),
      chapters=[],
    )

    before = build_project_distillation_signature(detail)
    note.external_references = ["更新后的灯塔记录：https://example.com/lighthouse-ledger-v2"]
    note.external_links = ["https://example.com/lighthouse-ledger-v2"]

    self.assertNotEqual(before, build_project_distillation_signature(detail))

  def test_story_overview_without_model_cache_does_not_backfill_main_character(self) -> None:
    summary = self.create_demo_project("无模型主角")
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n夜里在旧码头捡到一把铜钥匙，随后独自返回旅店。\n",
    )

    detail = get_project_detail(self.settings, summary.id)

    self.assertEqual(detail.story_overview.characters, [])
    self.assertEqual(detail.story_overview.scenes, [])

  def test_restore_project_snapshot_recovers_saved_chapter_content(self) -> None:
    summary = self.create_demo_project("快照恢复")
    self.write_chapter(summary.path, 1, "# 第一章\n旧版本正文。\n")

    after_snapshot = create_project_snapshot(
      self.settings,
      summary.id,
      SnapshotCreateRequest(message="保存旧版本"),
    )
    snapshot_id = after_snapshot.local_history.snapshots[0].id

    self.write_chapter(summary.path, 1, "# 第一章\n新版本正文。\n")
    restored = restore_project_snapshot(self.settings, summary.id, snapshot_id)

    restored_chapter = next(item for item in restored.chapters if item.id == "chapter-001")
    self.assertEqual(restored_chapter.content, "# 第一章\n旧版本正文。\n")
    self.assertEqual(restored.local_history.snapshots[0].kind, "restore")

  def test_rename_project_updates_folder_index_and_meta(self) -> None:
    summary = self.create_demo_project("旧标题")
    old_path = Path(summary.path)

    renamed = rename_project(
      self.settings,
      summary.id,
      ProjectRenameRequest(name="新标题"),
    )

    new_path = Path(renamed.path)
    self.assertEqual(renamed.name, "新标题")
    self.assertFalse(old_path.exists())
    self.assertTrue(new_path.exists())
    self.assertIn("新标题", new_path.name)

    project_meta = json.loads((new_path / "project.json").read_text(encoding="utf-8"))
    self.assertEqual(project_meta["name"], "新标题")
    self.assertEqual(project_meta["path"], str(new_path))

    detail = get_project_detail(self.settings, summary.id)
    self.assertEqual(detail.name, "新标题")
    self.assertEqual(detail.path, str(new_path))

  def test_delete_project_removes_index_and_directory(self) -> None:
    summary = self.create_demo_project("待删除作品")
    project_dir = Path(summary.path)

    result = delete_project(self.settings, summary.id)

    self.assertEqual(result.id, summary.id)
    self.assertTrue(result.removed_from_disk)
    self.assertFalse(project_dir.exists())

    with self.assertRaises(HTTPException) as context:
      get_project_detail(self.settings, summary.id)

    self.assertEqual(context.exception.status_code, 404)

  def test_open_project_directory_uses_system_file_manager(self) -> None:
    summary = self.create_demo_project("打开目录")

    with patch("novel_backend.services.project_service.sys.platform", "darwin"):
      with patch("novel_backend.services.project_service.subprocess.run") as mocked_run:
        result = open_project_directory(self.settings, summary.id)

    mocked_run.assert_called_once_with(["open", str(Path(summary.path))], check=True)
    self.assertEqual(result.project_id, summary.id)
    self.assertEqual(result.path, summary.path)
    self.assertTrue(result.opened)

  def test_update_story_document_persists_content(self) -> None:
    summary = self.create_demo_project("设定写入")

    detail = update_story_document(
      self.settings,
      summary.id,
      "world_building",
      StoryDocumentUpdateRequest(content="港口城市每到涨潮时都会打开隐藏航线。"),
    )

    document = next(item for item in detail.story_overview.documents if item.key == "world_building")
    self.assertEqual(document.content, "港口城市每到涨潮时都会打开隐藏航线。")
    self.assertTrue((Path(summary.path) / "world_building.txt").read_text(encoding="utf-8").startswith("港口城市"))

  def test_update_story_documents_updates_multiple_files(self) -> None:
    summary = self.create_demo_project("批量写入")

    detail = update_story_documents(
      self.settings,
      summary.id,
      StoryDocumentBatchUpdateRequest(
        documents=[
          StoryDocumentPatch(key="core_seed", content="失踪航线钥匙引出身世之谜。"),
          StoryDocumentPatch(key="plot_structure", content="前段引案，中段揭密，后段改写秩序。"),
        ]
      ),
    )

    documents = {item.key: item.content for item in detail.story_overview.documents}
    self.assertEqual(documents["core_seed"], "失踪航线钥匙引出身世之谜。")
    self.assertEqual(documents["plot_structure"], "前段引案，中段揭密，后段改写秩序。")

  def test_search_project_knowledge_returns_documents_and_chapters(self) -> None:
    summary = self.create_demo_project("知识检索")
    update_story_document(
      self.settings,
      summary.id,
      "core_seed",
      StoryDocumentUpdateRequest(content="故事核心是失踪航线钥匙和主角身世之谜。"),
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
    )

    hits = search_project_knowledge(self.settings, summary.id, "铜钥匙")

    sections = [item.section for item in hits]
    self.assertTrue(any(section.startswith("第 1 章") for section in sections))
    self.assertTrue(any("铜钥匙" in item.preview for item in hits))

    doc_hits = search_project_knowledge(self.settings, summary.id, "身世之谜")
    self.assertTrue(any(item.source == "架构文件" for item in doc_hits))

  def test_update_chapter_content_persists_and_can_be_cleared(self) -> None:
    summary = self.create_demo_project("章节编辑")

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追回到旧码头。\n"),
    )

    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertTrue(chapter.exists)
    self.assertIn("林追回到旧码头", chapter.content)

    cleared = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content=""),
    )
    cleared_chapter = next(item for item in cleared.chapters if item.id == "chapter-001")
    self.assertFalse(cleared_chapter.exists)

  def test_existing_novel_takeover_imports_chapters_and_report(self) -> None:
    source = (
      "第一章 雨夜靠港\n"
      "林追回到旧码头，发现潮声里藏着旧船队的暗号。\n\n"
      "第二章 铜钥匙\n"
      "陈小雨把铜钥匙交给林追，两人决定去白石商会查旧账。\n"
    )

    result = import_existing_novel(
      self.settings,
      ExistingNovelImportRequest(
        name="旧稿接管",
        genre="悬疑",
        target_chapters=5,
        target_words=80000,
        content=source,
      ),
    )

    self.assertEqual(result.project.name, "旧稿接管")
    self.assertEqual(result.project.target_chapters, 5)
    self.assertEqual(result.report.applied_chapter_count, 2)
    self.assertEqual(result.report.next_chapter_index, 3)
    self.assertGreater(result.report.confidence, 0.5)

    detail = get_project_detail(self.settings, result.project.id)
    first_chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    second_chapter = next(item for item in detail.chapters if item.id == "chapter-002")
    self.assertIn("林追回到旧码头", first_chapter.content)
    self.assertIn("陈小雨把铜钥匙", second_chapter.content)
    project_dir = Path(result.project.path)
    self.assertIn("旧稿接续蓝图", (project_dir / "blueprint.txt").read_text(encoding="utf-8"))
    self.assertIn("接续要求", (project_dir / "global_summary.txt").read_text(encoding="utf-8"))
    self.assertIn("第 3 章", (project_dir / "character_state.txt").read_text(encoding="utf-8"))
    self.assertIn("旧稿接管情节骨架", (project_dir / "plot_structure.txt").read_text(encoding="utf-8"))
    self.assertIn("旧稿接管核心", (project_dir / "core_seed.txt").read_text(encoding="utf-8"))
    self.assertTrue((project_dir / ".gaoxia" / "takeover" / "state.json").exists())
    self.assertTrue((project_dir / ".gaoxia" / "takeover" / "report.md").exists())

    state = get_existing_novel_takeover_state(self.settings, result.project.id)
    self.assertEqual(state.state["status"], "completed")
    self.assertEqual(state.state["stage"], "completed")

    resumed = resume_existing_novel_takeover(self.settings, result.project.id)
    self.assertEqual(resumed.report.applied_chapter_count, 2)

    context_bundle = build_project_context_bundle(
      self.settings,
      result.project.id,
      chapter_id="chapter-003",
      task_instruction="续写第 3 章",
    )
    self.assertIn("旧稿接续简报", context_bundle.context_text)
    self.assertIn("第 3 章", context_bundle.context_text)
    self.assertIn("陈小雨把铜钥匙", context_bundle.context_text)

  def test_existing_novel_takeover_api_route_imports_project(self) -> None:
    matching_routes = [
      route
      for route in project_api_router.routes
      if getattr(route, "path", "") == "/api/projects/takeover/import"
      and "POST" in (getattr(route, "methods", set()) or set())
    ]
    self.assertTrue(matching_routes)
    self.assertEqual(matching_routes[0].endpoint, post_existing_novel_import)

    request = SimpleNamespace(
      app=SimpleNamespace(state=SimpleNamespace(settings=self.settings, project_history_watcher=None))
    )
    payload = asyncio.run(
      post_existing_novel_import(
        request,
        ExistingNovelImportRequest(
          name="旧稿接口接管",
          genre="悬疑",
          target_chapters=4,
          content=(
            "第一章 雨夜靠港\n林追回到旧码头，发现潮声里藏着旧船队的暗号。\n\n"
            "第二章 铜钥匙\n陈小雨把铜钥匙交给林追，两人决定去白石商会查旧账。\n"
          ),
        ),
      )
    )

    self.assertTrue(payload["ok"])
    imported_id = payload["data"]["project"]["id"]
    self.assertEqual(payload["data"]["report"]["next_chapter_index"], 3)
    imported_detail = get_project_detail(self.settings, imported_id)
    second_chapter = next(item for item in imported_detail.chapters if item.id == "chapter-002")
    self.assertIn("陈小雨把铜钥匙", second_chapter.content)

  def test_existing_novel_split_reports_gaps_and_short_sections(self) -> None:
    chapters, warnings, checks = split_existing_novel_chapters(
      "第三章 中段\n太短。\n\n第五章 跳章\n继续。\n"
    )

    self.assertEqual(len(chapters), 2)
    self.assertTrue(any("首个标题章号是 3" in item for item in warnings))
    self.assertTrue(any("缺少：4" in item for item in warnings))
    self.assertTrue(any("章节很短" in item for item in chapters[0]["warnings"]))
    self.assertTrue(any("识别到 2 个章节标题" in item for item in checks))
    self.assertEqual(chapters[0]["end_line"], 3)
    self.assertEqual(chapters[1]["start_line"], 4)

  def test_existing_novel_takeover_resume_repairs_missing_handoff_docs(self) -> None:
    result = import_existing_novel(
      self.settings,
      ExistingNovelImportRequest(
        name="恢复接续文档",
        genre="悬疑",
        target_chapters=4,
        content=(
          "第一章 雨夜靠港\n林追回到旧码头，发现潮声里藏着旧船队的暗号。\n\n"
          "第二章 铜钥匙\n陈小雨把铜钥匙交给林追，两人决定去白石商会查旧账。\n"
        ),
      ),
    )
    project_dir = Path(result.project.path)
    report_path = project_dir / ".gaoxia" / "takeover" / "report.md"
    report_path.unlink()
    (project_dir / "blueprint.txt").write_text("", encoding="utf-8")
    (project_dir / "global_summary.txt").write_text("", encoding="utf-8")
    (project_dir / "character_state.txt").write_text("作者整理的人物状态\n", encoding="utf-8")
    (project_dir / "checkpoint.json").write_text(
      json.dumps({"step": "idle", "chapter_index": 0, "status": "ready"}, ensure_ascii=False),
      encoding="utf-8",
    )

    resumed = resume_existing_novel_takeover(self.settings, result.project.id)

    self.assertEqual(resumed.report.status, "completed")
    self.assertTrue(report_path.exists())
    self.assertIn("旧稿接续蓝图", (project_dir / "blueprint.txt").read_text(encoding="utf-8"))
    self.assertIn("接续要求", (project_dir / "global_summary.txt").read_text(encoding="utf-8"))
    self.assertEqual((project_dir / "character_state.txt").read_text(encoding="utf-8"), "作者整理的人物状态\n")
    checkpoint = json.loads((project_dir / "checkpoint.json").read_text(encoding="utf-8"))
    self.assertEqual(checkpoint["step"], "takeover_completed")

  def test_existing_novel_takeover_resume_preserves_existing_chapter_edits(self) -> None:
    result = import_existing_novel(
      self.settings,
      ExistingNovelImportRequest(
        name="恢复保护章节",
        genre="悬疑",
        target_chapters=4,
        content=(
          "第一章 雨夜靠港\n林追回到旧码头，发现潮声里藏着旧船队的暗号。\n\n"
          "第二章 铜钥匙\n陈小雨把铜钥匙交给林追，两人决定去白石商会查旧账。\n"
        ),
      ),
    )
    project_dir = Path(result.project.path)
    state_path = project_dir / ".gaoxia" / "takeover" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "running"
    state["stage"] = "writing_chapters"
    state["applied_chapter_indexes"] = [1]
    state.pop("report", None)
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    edited_text = "# 第二章 铜钥匙\n作者已经改过第二章，必须保留。\n"
    (project_dir / "chapters" / "002.md").write_text(edited_text, encoding="utf-8")

    resumed = resume_existing_novel_takeover(self.settings, result.project.id)

    self.assertEqual((project_dir / "chapters" / "002.md").read_text(encoding="utf-8"), edited_text)
    self.assertTrue(any("第 2 章已有正文" in item for item in resumed.report.warnings))

  def test_existing_novel_takeover_rejects_more_than_project_chapter_limit(self) -> None:
    source = "\n".join(
      f"第{index}章 标题\n这一章用于测试章节数量上限。"
      for index in range(1, 1002)
    )

    with self.assertRaises(HTTPException) as context:
      import_existing_novel(
        self.settings,
        ExistingNovelImportRequest(
          name="章节过多",
          genre="悬疑",
          content=source,
        ),
      )

    self.assertEqual(context.exception.status_code, 400)
    self.assertEqual(context.exception.detail["code"], "existing_novel_too_many_chapters")

  def test_existing_novel_file_base64_limit_matches_frontend_file_limit(self) -> None:
    expected_base64_length = ((EXISTING_NOVEL_IMPORT_FILE_MAX_BYTES + 2) // 3) * 4
    self.assertEqual(EXISTING_NOVEL_IMPORT_BASE64_MAX_LENGTH, expected_base64_length)

    field = ExistingNovelImportRequest.model_fields["content_base64"]
    max_lengths = [
      getattr(item, "max_length", None)
      for item in field.metadata
    ]
    self.assertIn(expected_base64_length, max_lengths)

  def test_update_chapter_content_generates_chapter_review_report(self) -> None:
    summary = self.create_demo_project("章节核验")
    update_story_documents(
      self.settings,
      summary.id,
      StoryDocumentBatchUpdateRequest(
        documents=[
          StoryDocumentPatch(key="blueprint", content="## 第 1 章《雨夜靠港》\n拿到钥匙并暴露行踪，结尾留下追兵逼近。"),
          StoryDocumentPatch(key="global_summary", content="主线围绕铜钥匙和旧船队旧账推进。"),
        ]
      ),
    )
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="钥匙状态",
            content="林追拿到铜钥匙后不能主动交出或放下。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库拿到铜钥匙，却发现白石商会的人已经追到门外。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    dimension_ids = [item.id for item in review.dimensions]
    self.assertEqual(review.version, "complete")
    self.assertFalse(review.is_stale)
    self.assertIn("consistency", dimension_ids)
    self.assertIn("structure", dimension_ids)
    self.assertIn("plot", dimension_ids)
    self.assertIn("suspense", dimension_ids)
    self.assertIn("language", dimension_ids)
    self.assertIn("continuity", dimension_ids)
    self.assertIn("style", dimension_ids)
    style_dimension = next(item for item in review.dimensions if item.id == "style")
    self.assertEqual(style_dimension.status, "na")
    continuity_dimension = next(item for item in review.dimensions if item.id == "continuity")
    self.assertIn("共享连续性证据", continuity_dimension.summary)
    self.assertTrue(any("手动记忆" in item for item in continuity_dimension.highlights))

  def test_chapter_review_catches_project_memory_forbidden_rules(self) -> None:
    summary = self.create_demo_project("项目记忆核验")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="警告",
            title="别提前揭底",
            content="不要提前揭示沈砚就是主谋。不要把林澈改名为林追。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临低声说沈砚就是主谋，旁边的船工把林澈叫成林追。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    memory_dimension = next(item for item in review.dimensions if item.id == "project_memory")
    self.assertEqual(memory_dimension.status, "risk")
    self.assertTrue(any("触犯项目记忆警告：别提前揭底" in item.title for item in memory_dimension.issues))
    self.assertTrue(any("沈砚" in item.detail and "主谋" in item.detail for item in memory_dimension.issues))
    self.assertTrue(any("林澈 / 叫成 / 林追" in item.detail for item in memory_dimension.issues))

    review_status = summarize_chapter_review_status(detail, "chapter-001")
    self.assertGreaterEqual(review_status["critical_issue_count"], 1)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    safe_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n林追打开密押日志，林澈在码头另一侧记录船号。\n"),
    )
    safe_review = next(item for item in safe_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    safe_memory_dimension = next(item for item in safe_review.dimensions if item.id == "project_memory")
    self.assertNotEqual(safe_memory_dimension.status, "risk")
    self.assertFalse(safe_memory_dimension.issues)

  def test_chapter_review_catches_project_memory_reveal_rule_with_subject_before_marker(self) -> None:
    summary = self.create_demo_project("项目记忆主谋核验")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="沈砚真相暂缓",
            content="沈砚不能被提前揭示为主谋。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临翻开密押日志，终于确认主谋是沈砚。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    memory_dimension = next(item for item in review.dimensions if item.id == "project_memory")
    self.assertEqual(memory_dimension.status, "risk")
    self.assertTrue(any("沈砚真相暂缓" in item.title for item in memory_dimension.issues))
    self.assertTrue(any("沈砚 / 主谋" in item.detail for item in memory_dimension.issues))
    self.assertFalse(any("沈砚就" in item.detail for item in memory_dimension.issues))

  def test_chapter_review_catches_project_memory_custom_identity_reveal_rules(self) -> None:
    summary = self.create_demo_project("项目记忆身份核验")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="隐藏身份暂缓",
            content="林追不能被提前揭示为卧底。苏青不能提前暴露为潮师。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临翻开旧船队档案，确认卧底是林追，苏青则是潮师。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    memory_dimension = next(item for item in review.dimensions if item.id == "project_memory")
    self.assertEqual(memory_dimension.status, "risk")
    self.assertTrue(any("林追 / 卧底" in item.detail for item in memory_dimension.issues))
    self.assertTrue(any("苏青 / 潮师" in item.detail for item in memory_dimension.issues))

    safe_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临翻开旧船队档案，确认林追并不是卧底，苏青没有暴露为潮师。\n"),
    )
    safe_review = next(item for item in safe_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    safe_memory_dimension = next(item for item in safe_review.dimensions if item.id == "project_memory")
    self.assertNotEqual(safe_memory_dimension.status, "risk")
    self.assertFalse(safe_memory_dimension.issues)

  def test_chapter_review_catches_project_memory_transfer_rules(self) -> None:
    summary = self.create_demo_project("项目记忆物品归属核验")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="关键物品归属",
            content="铜钥匙不能被交给白石商会。账册不能交给顾临。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n林追把铜钥匙交给白石商会，又把账册交给顾临。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    memory_dimension = next(item for item in review.dimensions if item.id == "project_memory")
    self.assertEqual(memory_dimension.status, "risk")
    self.assertTrue(any("铜钥匙 / 交给 / 白石商会" in item.detail for item in memory_dimension.issues))
    self.assertTrue(any("账册 / 交给 / 顾临" in item.detail for item in memory_dimension.issues))

    safe_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n林追没有把铜钥匙交给白石商会，也没有把账册交给顾临。\n"),
    )
    safe_review = next(item for item in safe_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    safe_memory_dimension = next(item for item in safe_review.dimensions if item.id == "project_memory")
    self.assertNotEqual(safe_memory_dimension.status, "risk")
    self.assertFalse(safe_memory_dimension.issues)

  def test_chapter_review_catches_project_memory_state_change_rules(self) -> None:
    summary = self.create_demo_project("项目记忆状态核验")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="顾临仍在局内",
            content="顾临不能死亡，也不能叛变。林追不会主动暴露身份。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临在仓库里被杀，林追为了换船票主动暴露身份。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    memory_dimension = next(item for item in review.dimensions if item.id == "project_memory")
    self.assertEqual(memory_dimension.status, "risk")
    self.assertTrue(any("顾临" in item.detail and "被杀" in item.detail for item in memory_dimension.issues))
    self.assertTrue(any("林追" in item.detail and "暴露身份" in item.detail for item in memory_dimension.issues))

    review_status = summarize_chapter_review_status(detail, "chapter-001")
    self.assertGreaterEqual(review_status["critical_issue_count"], 2)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

  def test_chapter_review_becomes_stale_after_project_memory_changes(self) -> None:
    summary = self.create_demo_project("项目记忆过期核验")
    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临在仓库里被杀，林追带着账本离开。\n"),
    )
    initial_review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertFalse(initial_review.is_stale)
    initial_memory_dimension = next(item for item in initial_review.dimensions if item.id == "project_memory")
    self.assertEqual(initial_memory_dimension.status, "na")

    changed = update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="顾临必须存活",
            content="顾临不能死亡。",
          )
        ]
      ),
    )
    stale_review = next(item for item in changed.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertTrue(stale_review.is_stale)

    refreshed, review_error = refresh_chapter_review(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterReviewRefreshRequest(style_name=""),
    )
    self.assertEqual(review_error, "")
    refreshed_review = next(item for item in refreshed.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertFalse(refreshed_review.is_stale)
    memory_dimension = next(item for item in refreshed_review.dimensions if item.id == "project_memory")
    self.assertEqual(memory_dimension.status, "risk")
    self.assertTrue(any("顾临必须存活" in item.title for item in memory_dimension.issues))
    self.assertTrue(any("顾临" in item.detail and "被杀" in item.detail for item in memory_dimension.issues))

  def test_chapter_review_combines_longform_memory_rules_across_multiple_chapters(self) -> None:
    summary = create_project(
      self.settings,
      CreateProjectRequest(
        name="长篇连续性核验",
        genre="悬疑",
        target_chapters=12,
        target_words=120000,
      ),
    )
    update_story_documents(
      self.settings,
      summary.id,
      StoryDocumentBatchUpdateRequest(
        documents=[
          StoryDocumentPatch(key="character_design", content="林追守着铜钥匙追查旧船队。顾临是仍在局内的证人。沈砚的真实身份要留到后段。"),
          StoryDocumentPatch(key="blueprint", content="第 1-12 章围绕铜钥匙、旧船队旧账和沈砚身份疑云推进，前中段不能提前揭开主谋。"),
          StoryDocumentPatch(key="global_summary", content="铜钥匙始终是林追手里的关键物品，白石商会只能追索，不能得到。"),
        ]
      ),
    )
    memory_entries = [
      ProjectMemoryEntryInput(
        category="硬规则",
        title="身份时序",
        content="沈砚不能被提前揭示为主谋。林追不能被提前揭示为卧底。",
      ),
      ProjectMemoryEntryInput(
        category="硬规则",
        title="关键物品归属",
        content="铜钥匙不能被交给白石商会。",
      ),
      ProjectMemoryEntryInput(
        category="硬规则",
        title="人物状态",
        content="顾临不能死亡。林追不会主动暴露身份。",
      ),
    ]
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(entries=memory_entries),
    )

    safe_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(
        content="# 第一章 雾港\n林追在旧码头拿到铜钥匙，只怀疑沈砚和旧账有关，并没有确认谁是主谋。顾临避开追兵后继续留在局内。\n"
      ),
    )
    safe_review_1 = next(item for item in safe_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    safe_dimension_1 = next(item for item in safe_review_1.dimensions if item.id == "project_memory")
    self.assertFalse(safe_review_1.is_stale)
    self.assertNotEqual(safe_dimension_1.status, "risk")
    self.assertFalse(safe_dimension_1.issues)

    safe_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-006",
      ChapterUpdateRequest(
        content="# 第六章 暗潮\n白石商会逼林追交出铜钥匙，但他没有把铜钥匙交给白石商会。林追继续隐瞒身份，苏青也没有确认沈砚的真实立场。\n"
      ),
    )
    safe_review_6 = next(item for item in safe_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-006")
    safe_dimension_6 = next(item for item in safe_review_6.dimensions if item.id == "project_memory")
    self.assertFalse(safe_review_6.is_stale)
    self.assertNotEqual(safe_dimension_6.status, "risk")
    self.assertFalse(safe_dimension_6.issues)

    violated_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-012",
      ChapterUpdateRequest(
        content="# 第十二章 盐仓\n顾临在盐仓被杀。林追为了换通行证主动暴露身份。苏青翻出密押日志，确认主谋是沈砚。林追随后把铜钥匙交给白石商会。\n"
      ),
    )
    violated_review = next(item for item in violated_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-012")
    memory_dimension = next(item for item in violated_review.dimensions if item.id == "project_memory")
    issue_details = "\n".join(item.detail for item in memory_dimension.issues)
    self.assertEqual(memory_dimension.status, "risk")
    self.assertGreaterEqual(len(memory_dimension.issues), 4)
    self.assertIn("沈砚 / 主谋", issue_details)
    self.assertIn("铜钥匙 / 交给 / 白石商会", issue_details)
    self.assertIn("顾临", issue_details)
    self.assertIn("被杀", issue_details)
    self.assertIn("林追", issue_details)
    self.assertIn("暴露身份", issue_details)

    review_status = summarize_chapter_review_status(violated_detail, "chapter-012")
    self.assertGreaterEqual(review_status["critical_issue_count"], 4)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    changed = update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          *memory_entries,
          ProjectMemoryEntryInput(
            category="硬规则",
            title="新人物边界",
            content="苏青不能死亡。",
          ),
        ]
      ),
    )
    stale_reviews = {
      item.chapter_id: item
      for item in changed.story_overview.chapter_reviews
      if item.chapter_id in {"chapter-001", "chapter-006", "chapter-012"}
    }
    self.assertTrue(stale_reviews["chapter-001"].is_stale)
    self.assertTrue(stale_reviews["chapter-006"].is_stale)
    self.assertTrue(stale_reviews["chapter-012"].is_stale)

    refreshed, review_error = refresh_chapter_review(
      self.settings,
      summary.id,
      "chapter-012",
      ChapterReviewRefreshRequest(style_name=""),
    )
    self.assertEqual(review_error, "")
    refreshed_review = next(item for item in refreshed.story_overview.chapter_reviews if item.chapter_id == "chapter-012")
    refreshed_dimension = next(item for item in refreshed_review.dimensions if item.id == "project_memory")
    self.assertFalse(refreshed_review.is_stale)
    self.assertEqual(refreshed_dimension.status, "risk")
    self.assertGreaterEqual(len(refreshed_dimension.issues), 4)

  def test_chapter_review_checks_obsidian_forbidden_phrases_and_staleness(self) -> None:
    summary = self.create_demo_project("Obsidian 章节核验")
    vault_dir = Path(self._temp_dir.name) / "review-vault"
    vault_dir.mkdir()
    note_path = vault_dir / "白石会馆.md"
    note_path.write_text(
      """---
type: location
status: canonical
forbidden_phrases: [白石会馆被烧毁]
required_phrases: [保留地下档案室]
---
# 白石会馆

白石会馆是旧船队暗账的保存地点。
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追赶到白石会馆，却发现白石会馆被烧毁。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    obsidian_dimension = next(item for item in review.dimensions if item.id == "obsidian")
    self.assertEqual(obsidian_dimension.status, "risk")
    self.assertTrue(any("触犯 Obsidian 禁用设定" in item.title for item in obsidian_dimension.issues))
    self.assertTrue(any("缺少 Obsidian 必需设定" in item.title for item in obsidian_dimension.issues))

    note_path.write_text(
      """---
type: location
status: canonical
forbidden_phrases: [白石会馆被改名]
---
# 白石会馆

白石会馆仍保存旧船队暗账。
""",
      encoding="utf-8",
    )

    refreshed = get_project_detail(self.settings, summary.id)
    stale_review = next(item for item in refreshed.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertTrue(stale_review.is_stale)

  def test_chapter_review_staleness_ignores_future_scoped_obsidian_note(self) -> None:
    summary = self.create_demo_project("Obsidian 章节签名")
    vault_dir = Path(self._temp_dir.name) / "review-vault-scoped-signature"
    vault_dir.mkdir()
    current_note_path = vault_dir / "白石会馆.md"
    future_note_path = vault_dir / "终局真相.md"
    current_note_path.write_text(
      """---
type: location
status: canonical
chapter_range: 1-1
required_phrases: [地下档案室]
---
# 白石会馆

白石会馆地下有旧船队档案室。
""",
      encoding="utf-8",
    )
    future_note_path.write_text(
      """---
type: secret
status: canonical
chapter_range: 3-3
reveal_after_chapter: 2
forbidden_phrases: [港务长身份曝光]
---
# 终局真相

终局真相只在第三章以后可用，并反向引用[[白石会馆]]。
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追赶到白石会馆，确认地下档案室还在。\n"),
    )
    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertFalse(review.is_stale)

    future_note_path.write_text(
      """---
type: secret
status: canonical
chapter_range: 3-3
reveal_after_chapter: 2
forbidden_phrases: [港务长另有身份]
---
# 终局真相

终局真相改成第三章以后才揭示的新版本，并继续反向引用[[白石会馆]]。
""",
      encoding="utf-8",
    )
    future_changed = get_project_detail(self.settings, summary.id)
    current_review = next(item for item in future_changed.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertFalse(current_review.is_stale)

    current_note_path.write_text(
      """---
type: location
status: canonical
chapter_range: 1-1
required_phrases: [地下档案室, 旧账册]
---
# 白石会馆

白石会馆地下有旧船队档案室，旧账册不能丢。
""",
      encoding="utf-8",
    )
    current_changed = get_project_detail(self.settings, summary.id)
    stale_review = next(item for item in current_changed.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertTrue(stale_review.is_stale)

  def test_chapter_review_catches_obsidian_forbidden_phrase_without_note_label(self) -> None:
    summary = self.create_demo_project("Obsidian 禁用短语")
    vault_dir = Path(self._temp_dir.name) / "review-vault-global"
    vault_dir.mkdir()
    (vault_dir / "白石会馆.md").write_text(
      """---
type: location
status: canonical
forbidden_phrases: [旧档案室被公开焚毁]
---
# 白石会馆

白石会馆地下保存旧船队暗账。
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在暗巷里听见传闻：旧档案室被公开焚毁。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    obsidian_dimension = next(item for item in review.dimensions if item.id == "obsidian")
    self.assertEqual(obsidian_dimension.status, "risk")
    self.assertTrue(any("触犯 Obsidian 禁用设定：白石会馆" in item.title for item in obsidian_dimension.issues))
    self.assertTrue(any("旧档案室被公开焚毁" in item.detail for item in obsidian_dimension.issues))

  def test_chapter_review_respects_obsidian_chapter_scope(self) -> None:
    summary = self.create_demo_project("Obsidian 章节边界")
    vault_dir = Path(self._temp_dir.name) / "review-vault-chapter-scope"
    vault_dir.mkdir()
    (vault_dir / "终局真相.md").write_text(
      """---
type: secret
status: canonical
chapter_range: 3-3
reveal_after_chapter: 2
forbidden_phrases: [港务长身份曝光]
---
# 终局真相

港务长身份曝光只能在第三章以后处理。
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    early_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n码头谣言里第一次出现港务长身份曝光这句话。\n"),
    )
    early_review = next(item for item in early_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    early_obsidian = next(item for item in early_review.dimensions if item.id == "obsidian")
    self.assertEqual(early_obsidian.status, "na")
    self.assertFalse(any("港务长身份曝光" in item.detail for item in early_obsidian.issues))

    active_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-003",
      ChapterUpdateRequest(content="# 第三章 红灯塔\n林追终于确认港务长身份曝光。\n"),
    )
    active_review = next(item for item in active_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-003")
    active_obsidian = next(item for item in active_review.dimensions if item.id == "obsidian")
    self.assertEqual(active_obsidian.status, "risk")
    self.assertTrue(any("港务长身份曝光" in item.detail for item in active_obsidian.issues))

  def test_chapter_review_checks_required_phrase_for_obsidian_evidence_hit(self) -> None:
    summary = self.create_demo_project("Obsidian 证据必需项")
    vault_dir = Path(self._temp_dir.name) / "review-vault-required"
    vault_dir.mkdir()
    (vault_dir / "港口暗线.md").write_text(
      """---
type: rule
status: canonical
required_phrases: [潮汐密码]
---
# 港口暗线

这份笔记只在 frontmatter 标出本章必须保留的词。
""",
      encoding="utf-8",
    )
    update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在章末第一次听见潮汐密码。\n"),
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追翻开旧账册，避开所有能指向暗号的字眼。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-002")
    obsidian_dimension = next(item for item in review.dimensions if item.id == "obsidian")
    self.assertEqual(obsidian_dimension.status, "watch")
    self.assertTrue(any("缺少 Obsidian 必需设定：港口暗线" in item.title for item in obsidian_dimension.issues))
    self.assertTrue(any("本章证据命中了该笔记" in item.detail for item in obsidian_dimension.issues))

  def test_chapter_review_checks_required_phrase_for_chapter_scoped_obsidian_note(self) -> None:
    summary = self.create_demo_project("Obsidian 当前章必写项")
    vault_dir = Path(self._temp_dir.name) / "review-vault-scoped-required"
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
---
# 第二章任务

第二章必须让银潮灯进入主线。
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追推开仓门，只看见一排没有点亮的油灯。\n"),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-002")
    obsidian_dimension = next(item for item in review.dimensions if item.id == "obsidian")
    self.assertEqual(obsidian_dimension.status, "watch")
    self.assertTrue(any("缺少 Obsidian 必需设定：第二章任务" in item.title for item in obsidian_dimension.issues))
    self.assertTrue(any("银潮灯" in item.detail for item in obsidian_dimension.issues))

    chapter = next(item for item in detail.chapters if item.id == "chapter-002")
    direct_dimension = _obsidian_dimension(detail, chapter, None)
    self.assertTrue(any("Vault 将该笔记绑定到当前章节" in item.detail for item in direct_dimension.issues))

  def test_chapter_review_checks_obsidian_chapter_archive_handoff(self) -> None:
    summary = self.create_demo_project("Obsidian 章节档案交接核验")
    vault_dir = Path(self._temp_dir.name) / "review-vault-chapter-handoff"
    (vault_dir / "Archive").mkdir(parents=True)
    (vault_dir / "Archive" / "第一章回顾.md").write_text(
      """---
type: chapter_note
status: canonical
source_ids:
  - chapter-001
chapter_title: 第一章回顾
chapter_summary: 林追发现宋闻隐瞒旧船队账本。
handoff_to_next:
  - 下一章必须追问账本缺页。
---
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    missing_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追只沿着旧码头追查宋闻，没有提到那页线索。\n"),
    )
    missing_review = next(item for item in missing_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-002")
    missing_obsidian = next(item for item in missing_review.dimensions if item.id == "obsidian")
    self.assertEqual(missing_obsidian.status, "watch")
    self.assertTrue(any("缺少 Obsidian 必需设定：第一章回顾" in item.title for item in missing_obsidian.issues))
    self.assertTrue(any("账本缺页" in item.detail for item in missing_obsidian.issues))
    review_status = summarize_chapter_review_status(missing_detail, "chapter-002")
    self.assertEqual(review_status["obsidian_required_issue_count"], 1)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    satisfied_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追追问宋闻账本缺页，确认那一页被人提前撕走。\n"),
    )
    satisfied_review = next(item for item in satisfied_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-002")
    satisfied_obsidian = next(item for item in satisfied_review.dimensions if item.id == "obsidian")
    self.assertFalse(any("账本缺页" in item.detail for item in satisfied_obsidian.issues))

    later_detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-003",
      ChapterUpdateRequest(content="# 第三章 红灯塔\n林追继续追查旧船队账本的来历。\n"),
    )
    later_review = next(item for item in later_detail.story_overview.chapter_reviews if item.chapter_id == "chapter-003")
    later_obsidian = next(item for item in later_review.dimensions if item.id == "obsidian")
    self.assertFalse(any("账本缺页" in item.detail for item in later_obsidian.issues))

  def test_chapter_review_ignores_soft_obsidian_chapter_archive_handoff(self) -> None:
    summary = self.create_demo_project("Obsidian 章节档案关注提示")
    vault_dir = Path(self._temp_dir.name) / "review-vault-soft-chapter-handoff"
    (vault_dir / "Archive").mkdir(parents=True)
    (vault_dir / "Archive" / "第一章回顾.md").write_text(
      """---
type: chapter_note
status: canonical
source_ids:
  - chapter-001
chapter_title: 第一章回顾
chapter_summary: 林追发现宋闻隐瞒旧船队账本。
handoff_to_next:
  - 下一章关注本章后果：银潮灯、宋闻。
---
""",
      encoding="utf-8",
    )
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追沿着旧码头追查账本来源。\n"),
    )
    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-002")
    obsidian_dimension = next(item for item in review.dimensions if item.id == "obsidian")
    self.assertFalse(any("缺少 Obsidian 必需设定：第一章回顾" in item.title for item in obsidian_dimension.issues))
    review_status = summarize_chapter_review_status(detail, "chapter-002")
    self.assertEqual(review_status["obsidian_required_issue_count"], 0)

  def test_auto_repair_uses_chapter_scoped_obsidian_required_phrase(self) -> None:
    summary = self.create_demo_project("Obsidian 必写项自动修订")
    vault_dir = Path(self._temp_dir.name) / "repair-vault-scoped-required"
    vault_dir.mkdir()
    (vault_dir / "第二章任务.md").write_text(
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
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追推开仓门，只看见一排没有点亮的油灯。\n"),
    )
    review_status = summarize_chapter_review_status(detail, "chapter-002")
    self.assertGreaterEqual(int(review_status["score"]), 65)
    self.assertEqual(review_status["obsidian_required_issue_count"], 1)
    self.assertEqual(review_status["must_repair_issue_count"], 1)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    with patch(
      "novel_backend.services.chapter_auto_repair_service._invoke_model",
      return_value=json.dumps(
        {
          "summary": "加入 Obsidian 必写设定。",
          "changes": ["让银潮灯进入当前章"],
          "revised_content": "# 第二章 旧码头\n林追推开仓门，看见一排没有点亮的油灯。最深处的银潮灯忽然亮起，照出旧船队留下的潮痕。\n",
        },
        ensure_ascii=False,
      ),
    ):
      repaired_detail, review_error, repair_result = auto_repair_chapter_after_review(
        self.settings,
        summary.id,
        "chapter-002",
        detail,
      )

    self.assertEqual(review_error, "")
    self.assertTrue(repair_result.attempted)
    self.assertTrue(repair_result.applied)
    repaired_chapter = next(item for item in repaired_detail.chapters if item.id == "chapter-002")
    self.assertIn("银潮灯", repaired_chapter.content)
    repaired_status = summarize_chapter_review_status(repaired_detail, "chapter-002")
    self.assertEqual(repaired_status["obsidian_required_issue_count"], 0)
    self.assertEqual(repaired_status["must_repair_issue_count"], 0)

  def test_auto_repair_uses_default_second_round_when_first_round_still_has_required_issue(self) -> None:
    summary = self.create_demo_project("Obsidian 多轮自动修订")
    vault_dir = Path(self._temp_dir.name) / "repair-vault-default-second-round"
    vault_dir.mkdir()
    (vault_dir / "第二章任务.md").write_text(
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
    with patch("novel_backend.services.project_service.embed_texts", side_effect=RuntimeError("embedding disabled")):
      update_project_obsidian_config(
        self.settings,
        summary.id,
        ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
      )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 旧码头\n林追推开仓门，只看见一排没有点亮的油灯。\n"),
    )
    review_status = summarize_chapter_review_status(detail, "chapter-002")
    self.assertEqual(review_status["obsidian_required_issue_count"], 1)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    repair_payloads = [
      {
        "summary": "第一次修订调整气氛，但仍遗漏必写项。",
        "changes": ["增加仓门细节"],
        "revised_content": "# 第二章 旧码头\n林追推开仓门，潮气扑面，只看见一排没有点亮的油灯。\n",
      },
      {
        "summary": "第二次修订加入 Obsidian 必写设定。",
        "changes": ["让银潮灯进入当前章"],
        "revised_content": "# 第二章 旧码头\n林追推开仓门，潮气扑面，最深处的银潮灯忽然亮起，照出旧船队留下的潮痕。\n",
      },
    ]

    with patch(
      "novel_backend.services.chapter_auto_repair_service._invoke_model",
      side_effect=[json.dumps(item, ensure_ascii=False) for item in repair_payloads],
    ) as repair_model:
      repaired_detail, review_error, repair_result = auto_repair_chapter_after_review(
        self.settings,
        summary.id,
        "chapter-002",
        detail,
      )

    self.assertEqual(review_error, "")
    self.assertEqual(repair_model.call_count, 2)
    self.assertTrue(repair_result.attempted)
    self.assertTrue(repair_result.applied)
    self.assertEqual(repair_result.rounds_attempted, 2)
    self.assertEqual(repair_result.rounds_applied, 2)
    repaired_chapter = next(item for item in repaired_detail.chapters if item.id == "chapter-002")
    self.assertIn("银潮灯", repaired_chapter.content)
    repaired_status = summarize_chapter_review_status(repaired_detail, "chapter-002")
    self.assertEqual(repaired_status["obsidian_required_issue_count"], 0)
    self.assertEqual(repaired_status["must_repair_issue_count"], 0)

  def test_auto_repair_uses_project_memory_state_rule_issues(self) -> None:
    summary = self.create_demo_project("项目记忆自动修订")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="林追身份边界",
            content="林追不会主动暴露身份。顾临不能死亡。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临在仓库里被杀。林追为了换船票主动暴露身份。\n"),
    )
    review_status = summarize_chapter_review_status(detail, "chapter-001")
    self.assertGreaterEqual(review_status["critical_issue_count"], 2)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    captured_messages: list[dict[str, str]] = []

    def fake_repair_model(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "summary": "改掉项目记忆禁写状态。",
          "changes": ["保留顾临存活", "改成林追隐藏身份"],
          "revised_content": "# 第一章 雾港\n顾临在仓库里负伤昏迷，被林追拖到货箱后藏起。林追没有暴露身份，只用假名换到一张船票。\n",
        },
        ensure_ascii=False,
      )

    with patch("novel_backend.services.chapter_auto_repair_service._invoke_model", side_effect=fake_repair_model):
      repaired_detail, review_error, repair_result = auto_repair_chapter_after_review(
        self.settings,
        summary.id,
        "chapter-001",
        detail,
      )

    self.assertEqual(review_error, "")
    self.assertTrue(repair_result.attempted)
    self.assertTrue(repair_result.applied)
    prompt_text = "\n".join(message["content"] for message in captured_messages)
    self.assertIn("项目记忆规则", prompt_text)
    self.assertIn("林追不会主动暴露身份", prompt_text)
    self.assertIn("顾临不能死亡", prompt_text)
    repaired_chapter = next(item for item in repaired_detail.chapters if item.id == "chapter-001")
    self.assertNotIn("被杀", repaired_chapter.content)
    self.assertNotIn("主动暴露身份", repaired_chapter.content)
    repaired_status = summarize_chapter_review_status(repaired_detail, "chapter-001")
    self.assertEqual(repaired_status["critical_issue_count"], 0)

  def test_auto_repair_uses_project_memory_reveal_rule_issues(self) -> None:
    summary = self.create_demo_project("项目记忆揭示自动修订")
    update_project_memory(
      self.settings,
      summary.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="沈砚主谋暂缓",
            content="沈砚不能被提前揭示为主谋。",
          )
        ]
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雾港\n顾临翻开密押日志，终于确认主谋是沈砚。\n"),
    )
    review_status = summarize_chapter_review_status(detail, "chapter-001")
    self.assertGreaterEqual(review_status["critical_issue_count"], 1)
    self.assertTrue(chapter_review_needs_auto_repair(review_status, score_threshold=65))

    captured_messages: list[dict[str, str]] = []

    def fake_repair_model(_settings, messages, **_kwargs):
      captured_messages.extend(messages)
      return json.dumps(
        {
          "summary": "移除提前揭示主谋的句子。",
          "changes": ["保留密押日志线索", "隐藏沈砚身份"],
          "revised_content": "# 第一章 雾港\n顾临翻开密押日志，只确认有人动过旧船队账册，真正主使仍未露面。\n",
        },
        ensure_ascii=False,
      )

    with patch("novel_backend.services.chapter_auto_repair_service._invoke_model", side_effect=fake_repair_model):
      repaired_detail, review_error, repair_result = auto_repair_chapter_after_review(
        self.settings,
        summary.id,
        "chapter-001",
        detail,
      )

    self.assertEqual(review_error, "")
    self.assertTrue(repair_result.attempted)
    self.assertTrue(repair_result.applied)
    prompt_text = "\n".join(message["content"] for message in captured_messages)
    self.assertIn("项目记忆规则", prompt_text)
    self.assertIn("沈砚不能被提前揭示为主谋", prompt_text)
    self.assertIn("沈砚 / 主谋", prompt_text)
    repaired_chapter = next(item for item in repaired_detail.chapters if item.id == "chapter-001")
    self.assertNotIn("主谋是沈砚", repaired_chapter.content)
    repaired_status = summarize_chapter_review_status(repaired_detail, "chapter-001")
    self.assertEqual(repaired_status["critical_issue_count"], 0)

  def test_chapter_review_obsidian_evidence_prefers_source_key(self) -> None:
    guard_context = SimpleNamespace(
      knowledge_evidence=[
        {
          "source": "Obsidian",
          "source_key": "obsidian:Clues/港口暗线.md",
          "section": "没有路径分隔符的标题",
        },
        {
          "source": "资料库",
          "source_key": "reference:Clues/误入.md",
          "section": "Clues/误入.md",
        },
      ]
    )

    self.assertEqual(_obsidian_evidence_paths(guard_context), {"Clues/港口暗线.md"})

  def test_chapter_review_becomes_stale_after_blueprint_changes(self) -> None:
    summary = self.create_demo_project("核验过期")
    update_story_document(
      self.settings,
      summary.id,
      "blueprint",
      StoryDocumentUpdateRequest(content="## 第 1 章《雨夜靠港》\n拿到铜钥匙并暴露行踪。"),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库拿到铜钥匙。\n"),
    )
    initial_review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertFalse(initial_review.is_stale)

    updated = update_story_document(
      self.settings,
      summary.id,
      "blueprint",
      StoryDocumentUpdateRequest(content="## 第 1 章《雨夜靠港》\n拿到铜钥匙后立刻被追兵堵住退路。"),
    )
    stale_review = next(item for item in updated.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertTrue(stale_review.is_stale)

  def test_update_chapter_content_uses_style_name_for_review(self) -> None:
    summary = self.create_demo_project("文风核验")
    save_style(
      self.settings,
      "冷雾叙事",
      StyleSaveRequest(
        instruction="句子偏短，动作先行，结尾留半步悬念。",
        analysis="动作先行，解释压后。",
        narrative_for_chapter="段尾留半步悬念。",
        source_sample="雾一压下来，街口的人都像被收走了声音。林追没回头，只摸了摸袖口里的钥匙。",
      ),
    )

    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(
        content="# 第一章 雨夜靠港\n雾压住旧码头时，林追已经摸到了袖口里的铜钥匙，却没听见身后的脚步什么时候停了。\n",
        style_name="冷雾叙事",
      ),
    )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    style_dimension = next(item for item in review.dimensions if item.id == "style")
    self.assertEqual(review.style_name, "冷雾叙事")
    self.assertNotEqual(style_dimension.status, "na")

  def test_chapter_review_prefers_independent_review_model(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(api_key="primary-key", base_url="https://primary.local/v1", model_name="primary-model"),
        review_model=ReviewModelConfig(
          enabled=True,
          api_key="review-key",
          base_url="https://review.local/v1",
          model_name="review-model",
        ),
      ),
    )
    summary = self.create_demo_project("独立核验模型")
    captured_payloads = []

    def fake_request(endpoint, api_key, payload):
      captured_payloads.append({"endpoint": endpoint, "api_key": api_key, "payload": payload})
      return {
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "独立评审完成。",
                  "suggestions": ["保留当前追兵压力。"],
                  "consistency": {"summary": "连续性可读。", "strengths": [], "issues": [], "suggestions": []},
                  "structure": {"summary": "结构完整。", "strengths": [], "issues": [], "suggestions": []},
                  "plot": {"summary": "推进清楚。", "strengths": [], "issues": [], "suggestions": []},
                  "suspense": {"summary": "章末有牵引。", "strengths": [], "issues": [], "suggestions": []},
                  "style": {"summary": "文风可接受。", "strengths": [], "issues": [], "suggestions": []},
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      }

    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=fake_request):
      detail = update_chapter_content(
        self.settings,
        summary.id,
        "chapter-001",
        ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库拿到铜钥匙。\n"),
      )

    review = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-001")
    self.assertEqual(review.engine, "review_model")
    self.assertEqual(captured_payloads[0]["endpoint"], "https://review.local/v1/chat/completions")
    self.assertEqual(captured_payloads[0]["api_key"], "review-key")
    self.assertEqual(captured_payloads[0]["payload"]["model"], "review-model")

  def test_update_chapter_content_with_review_status_reports_review_failure(self) -> None:
    summary = self.create_demo_project("核验失败透出")

    with patch("novel_backend.services.project_service.build_chapter_review", side_effect=RuntimeError("model down")):
      detail, review_error = update_chapter_content_with_review_status(
        self.settings,
        summary.id,
        "chapter-001",
        ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库拿到铜钥匙。\n"),
      )

    self.assertIn("章节已保存，但核验失败", review_error)
    self.assertIn("model down", review_error)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertTrue(chapter.exists)
    self.assertEqual(detail.story_overview.chapter_reviews, [])

  def test_chapter_mutation_response_includes_self_evolution_state(self) -> None:
    summary = self.create_demo_project("保存响应携带自学习")
    detail = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(
        content=(
          "# 第一章 雨夜靠港\n"
          "林追在旧码头仓库拿到铜钥匙，却没有说出宋闻的旧船队背叛线索。\n"
        ),
        xp_preset="悬疑推进",
      ),
    )

    payload = _chapter_mutation_response(self.settings, detail)
    meta = payload.get("meta") or {}
    self_evolution = meta.get("self_evolution") or {}
    narrative_state = self_evolution.get("narrative_state") or {}

    self.assertTrue(payload["ok"])
    self.assertEqual(payload["data"]["id"], summary.id)
    self.assertNotIn("self_evolution_error", meta)
    self.assertIn("style_xp_evolution", self_evolution)
    self.assertTrue(narrative_state.get("chapter_cards"))
    self.assertEqual(narrative_state["chapter_cards"][-1]["chapter_id"], "chapter-001")

  def test_project_action_response_includes_self_evolution_state(self) -> None:
    summary = self.create_demo_project("维护响应携带自学习")
    update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(
        content=(
          "# 第一章 雨夜靠港\n"
          "林追在旧码头仓库拿到铜钥匙，却没有说出宋闻的旧船队背叛线索。\n"
        ),
        xp_preset="悬疑推进",
      ),
    )

    payload = _project_action_response(
      self.settings,
      summary.id,
      {"status": "staged", "suggestion_id": "obsidian-maintenance-demo"},
      "Obsidian 维护动作",
    )
    meta = payload.get("meta") or {}
    self_evolution = meta.get("self_evolution") or {}
    narrative_state = self_evolution.get("narrative_state") or {}

    self.assertTrue(payload["ok"])
    self.assertEqual(payload["data"]["status"], "staged")
    self.assertNotIn("self_evolution_error", meta)
    self.assertIn("style_xp_evolution", self_evolution)
    self.assertTrue(narrative_state.get("chapter_cards"))
    self.assertEqual(narrative_state["chapter_cards"][-1]["chapter_id"], "chapter-001")

  def test_obsidian_config_response_includes_self_evolution_state(self) -> None:
    summary = self.create_demo_project("配置响应携带自学习")
    vault_dir = Path(self._temp_dir.name) / "vault-config-response"
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

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=self.settings)))
    payload = put_project_obsidian(
      request,
      summary.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    meta = payload.get("meta") or {}
    self_evolution = meta.get("self_evolution") or {}
    narrative_state = self_evolution.get("narrative_state") or {}
    suggestions = narrative_state.get("obsidian_maintenance_suggestions") or []
    graph_suggestion = next(
      item
      for item in suggestions
      if item.get("kind") == "create_graph_note" and "潮汐账本" in str(item.get("title") or "")
    )

    self.assertTrue(payload["ok"])
    self.assertEqual(payload["data"]["id"], summary.id)
    self.assertTrue(payload["data"]["story_overview"]["obsidian"]["enabled"])
    self.assertNotIn("self_evolution_error", meta)
    self.assertIn("style_xp_evolution", self_evolution)
    self.assertEqual(graph_suggestion["status"], "staged")
    self.assertTrue(graph_suggestion["auto_staged"])
    self.assertIn("Graph/", graph_suggestion["suggested_path"])

  def test_obsidian_sync_response_includes_self_evolution_state(self) -> None:
    summary = self.create_demo_project("同步响应携带自学习")
    vault_dir = Path(self._temp_dir.name) / "vault-sync-response"
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
      summary.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
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

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=self.settings)))
    payload = post_project_obsidian_sync(request, summary.id)
    meta = payload.get("meta") or {}
    self_evolution = meta.get("self_evolution") or {}
    narrative_state = self_evolution.get("narrative_state") or {}
    suggestions = narrative_state.get("obsidian_maintenance_suggestions") or []
    graph_suggestion = next(
      item
      for item in suggestions
      if item.get("kind") == "create_graph_note" and "潮汐账本" in str(item.get("title") or "")
    )

    self.assertTrue(payload["ok"])
    self.assertEqual(payload["data"]["id"], summary.id)
    self.assertNotIn("self_evolution_error", meta)
    self.assertIn("style_xp_evolution", self_evolution)
    self.assertEqual(graph_suggestion["status"], "staged")
    self.assertTrue(graph_suggestion["auto_staged"])
    self.assertIn("Graph/", graph_suggestion["suggested_path"])

  def test_refresh_chapter_review_only_refreshes_saved_content(self) -> None:
    summary = self.create_demo_project("单独刷新核验")
    saved = update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库拿到铜钥匙。\n"),
    )
    original_chapter = next(item for item in saved.chapters if item.id == "chapter-001")

    with patch("novel_backend.services.project_service.build_chapter_review", side_effect=RuntimeError("review offline")):
      detail, review_error = refresh_chapter_review(
        self.settings,
        summary.id,
        "chapter-001",
        ChapterReviewRefreshRequest(style_name="冷雾叙事"),
      )

    self.assertIn("章节核验失败", review_error)
    refreshed_chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertEqual(refreshed_chapter.content, original_chapter.content)

  def test_export_project_book_writes_markdown_file(self) -> None:
    summary = self.create_demo_project("整本导出")
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
    )
    self.write_chapter(
      summary.path,
      2,
      "# 第二章 白石会馆\n他带着钥匙去见旧船队留下的联系人。\n",
    )

    result = export_project_book(
      self.settings,
      summary.id,
      ProjectExportRequest(format="markdown"),
    )

    export_path = Path(result.path)
    self.assertTrue(export_path.exists())
    content = export_path.read_text(encoding="utf-8")
    self.assertIn("# 整本导出", content)
    self.assertIn("# 第一章 雨夜靠港", content)
    self.assertIn("# 第二章 白石会馆", content)
    self.assertEqual(result.chapter_count, 2)

  def test_export_project_book_rejects_empty_project(self) -> None:
    summary = self.create_demo_project("空作品")

    with self.assertRaises(HTTPException) as context:
      export_project_book(
        self.settings,
        summary.id,
        ProjectExportRequest(format="markdown"),
      )

    self.assertEqual(context.exception.status_code, 409)

  def test_export_project_migration_package_includes_complete_project_directory(self) -> None:
    summary = self.create_demo_project("迁移导出")
    project_dir = Path(summary.path)
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
    )
    (project_dir / ".gaoxia" / "custom_state.json").parent.mkdir(parents=True, exist_ok=True)
    (project_dir / ".gaoxia" / "custom_state.json").write_text('{"ok": true}', encoding="utf-8")

    result = export_project_migration_package(self.settings, summary.id)

    package_path = Path(result.path)
    self.assertTrue(package_path.exists())
    self.assertTrue(package_path.name.endswith(".gaoxia-project.zip"))
    with zipfile.ZipFile(package_path) as archive:
      names = set(archive.namelist())
      manifest = json.loads(archive.read(".gaoxia-project.json").decode("utf-8"))

    self.assertEqual(manifest["project"]["id"], summary.id)
    self.assertIn("project/project.json", names)
    self.assertIn("project/chapters/001.md", names)
    self.assertIn("project/knowledge.db", names)
    self.assertIn("project/.novel-history/index.json", names)
    self.assertIn("project/.gaoxia/custom_state.json", names)
    self.assertNotIn(f"project/exports/{package_path.name}", names)

  def test_migration_package_scrubs_external_obsidian_index_but_keeps_project_state(self) -> None:
    summary = self.create_demo_project("外部 Obsidian 迁移")
    project_dir = Path(summary.path)
    vault_dir = Path(self._temp_dir.name) / "external-vault"
    vault_dir.mkdir()
    (vault_dir / "Secrets.md").write_text(
      """---
type: note
status: canonical
---
# 外部 Vault 密档

迁移包不应携带的外部 Obsidian 正文。
""",
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      summary.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    learning_dir = project_dir / ".gaoxia" / "learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    draft_dir = project_dir / ".gaoxia" / "obsidian_drafts" / "Graph"
    draft_dir.mkdir(parents=True, exist_ok=True)
    external_draft_path = draft_dir / "Secrets.md"
    external_draft_path.write_text(
      "# 外部 Vault 密档\n\n迁移包不应携带的外部 Obsidian 正文。\n",
      encoding="utf-8",
    )
    (learning_dir / "narrative_state.json").write_text(
      json.dumps(
        {
          "debts": [
            {
              "id": "debt-project-owned",
              "title": "项目内剧情债务",
              "content": "项目章节留下的铜钥匙承诺。",
            }
          ],
          "obsidian_maintenance_summary": {"total": 1, "needs_action": 1},
          "obsidian_maintenance_suggestions": [
            {
              "id": "obsidian-maintenance-migration",
              "kind": "create_graph_note",
              "title": "外部 Vault 密档维护",
              "status": "staged",
              "reason": "迁移包不应携带的外部 Obsidian 正文。",
              "suggested_path": "Graph/Secrets.md",
              "draft_markdown": "# 外部 Vault 密档\n\n迁移包不应携带的外部 Obsidian 正文。",
            }
          ],
          "obsidian_maintenance_actions": [
            {
              "id": "obsidian-maintenance-action-migration",
              "suggestion_id": "obsidian-maintenance-migration",
              "status": "staged",
              "title": "外部 Vault 密档维护",
              "draft_path": str(external_draft_path),
              "relative_path": "Graph/Secrets.md",
              "vault_path": str(vault_dir / "Secrets.md"),
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (project_dir / "project_distillation.json").write_text(
      json.dumps(
        {
          "generated_at": "2026-06-03T00:00:00+00:00",
          "source_signature": "external-obsidian-signature",
          "is_stale": False,
          "source_profile": {
            "summary": "Obsidian:外部 Vault 密档｜迁移包不应携带的外部 Obsidian 正文。",
            "narrative_rules": [],
            "style_traits": [],
            "core_conflicts": [],
            "character_notes": [],
            "event_notes": [],
            "location_notes": [],
            "prop_notes": [],
            "skill_notes": [],
            "material_notes": [
              "Obsidian:外部 Vault 密档｜迁移包不应携带的外部 Obsidian 正文。",
              "项目内资料｜铜钥匙仍需要保留。",
            ],
          },
          "packs": [
            {
              "kind": "architecture",
              "summary": "用于整书架构。",
              "must_keep": [
                "Obsidian:外部 Vault 密档｜迁移包不应携带的外部 Obsidian 正文。",
                "项目内架构约束：铜钥匙不能丢。",
              ],
              "execution_focus": [],
              "voice_rules": [],
              "blocked_changes": [],
              "prepared_from": ["source_profile", "materials"],
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (learning_dir / "self_evolution_candidates.json").write_text(
      json.dumps(
        {
          "candidates": [
            {
              "id": "candidate-external-vault",
              "kind": "memory",
              "title": "外部 Vault 密档候选",
              "content": "迁移包不应携带的外部 Obsidian 正文。",
              "rationale": "来自外部 Vault 密档。",
              "metadata": {"latest_user": "请分析外部 Vault 密档。"},
            }
          ]
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    (learning_dir / "self_evolution_reviews.jsonl").write_text(
      json.dumps(
        {
          "id": "review-external-vault",
          "latest_user_message": "请分析外部 Vault 密档。",
          "candidates": [
            {
              "kind": "memory",
              "title": "外部 Vault 密档候选",
              "content": "迁移包不应携带的外部 Obsidian 正文。",
              "rationale": "来自外部 Vault 密档。",
            }
          ],
        },
        ensure_ascii=False,
      )
      + "\n",
      encoding="utf-8",
    )
    (learning_dir / "failure_cases.jsonl").write_text(
      json.dumps(
        {
          "id": "failure-external-vault",
          "action_kind": "review_knowledge",
          "summary": "外部 Vault 密档：迁移包不应携带的外部 Obsidian 正文。",
          "latest_user_message": "请分析外部 Vault 密档。",
          "prevention": "下次读取外部 Vault 密档前需要重新同步。",
        },
        ensure_ascii=False,
      )
      + "\n",
      encoding="utf-8",
    )
    (project_dir / ".gaoxia" / "model_review_history.json").write_text(
      json.dumps(
        {
          "id": "model-review-external-vault",
          "title": "外部 Vault 密档模型复盘",
          "content": "迁移包不应携带的外部 Obsidian 正文。",
        },
        ensure_ascii=False,
      )
      + "\n"
      + json.dumps(
        {
          "id": "model-review-external-vault-2",
          "summary": "外部 Vault 密档：迁移包不应携带的外部 Obsidian 正文。",
        },
        ensure_ascii=False,
      )
      + "\n",
      encoding="utf-8",
    )
    save_project_agent_threads(
      self.settings,
      summary.id,
      AgentThreadStoreUpdateRequest(
        active_thread_id="thread-external",
        threads=[
          AgentThreadRecord(
            id="thread-external",
            title="资料分析线程",
            preview="迁移包线程清理验证",
            updated_at="2026-06-03T00:00:00+00:00",
            messages=[
              AgentThreadMessage(role="user", content="先分析资料。"),
              AgentThreadMessage(
                role="assistant",
                content="资料分析已经完成。",
                mode="execution",
                task_pack_kind="architecture",
                execution_trace=[
                  AgentExecutionTrace(
                    step=1,
                    action_kind="review_knowledge",
                    label="分析资料",
                    status="completed",
                    task_pack_kind="architecture",
                    summary="Obsidian:外部 Vault 密档｜迁移包不应携带的外部 Obsidian 正文。",
                    changes=["已分析外部 Vault 密档。"],
                    material_count=1,
                  )
                ],
                event_blocks=[
                  AgentEventBlock(
                    event_type="action_result",
                    title="资料分析",
                    status="completed",
                    summary="外部 Vault 密档：迁移包不应携带的外部 Obsidian 正文。",
                    step=1,
                    action_kind="review_knowledge",
                  )
                ],
                artifacts=[
                  AgentArtifact(
                    kind="knowledge_summary",
                    title="资料库分析",
                    summary="Obsidian:外部 Vault 密档",
                    content_preview="迁移包不应携带的外部 Obsidian 正文。",
                    metadata={"material_count": 1},
                  ),
                  AgentArtifact(
                    kind="chapter_review",
                    title="章节核验",
                    summary="缺少 Obsidian 必需设定：外部 Vault 密档",
                    content_preview="迁移包不应携带的外部 Obsidian 正文。",
                    metadata={"chapter_id": "chapter-001"},
                  ),
                ],
                changes=["已分析外部 Vault 密档。"],
              ),
            ],
          )
        ],
      ),
    )
    workflow_dir = project_dir / ".gaoxia" / "runs" / "run-external"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "workflow.json").write_text(
      json.dumps(
        {
          "schema_version": "1",
          "task_id": "run-external",
          "project_id": summary.id,
          "thread_id": "thread-external",
          "status": "SUCCEEDED",
          "plan": {
            "id": "plan-external",
            "title": "外部 Vault 密档资料分析",
            "summary": "分析迁移包不应携带的外部 Obsidian 正文。",
            "actions": [
              {
                "kind": "review_knowledge",
                "label": "分析外部 Vault 密档",
                "instruction": "读取外部 Vault 密档。",
                "chapter_id": "chapter-001",
              }
            ],
          },
          "payload": {
            "messages": [{"role": "user", "content_preview": "先分析资料。", "content_length": 6}]
          },
          "actions": [
            {
              "step": 1,
              "kind": "review_knowledge",
              "label": "分析外部 Vault 密档",
              "status": "SUCCEEDED",
              "instruction_preview": "迁移包不应携带的外部 Obsidian 正文。",
              "message": "外部 Vault 密档：迁移包不应携带的外部 Obsidian 正文。",
              "contract": {"checks": [{"message": "Obsidian:外部 Vault 密档"}]},
              "output_validation": {"summary": "知识 artifact 包含外部 Vault 密档。"},
              "status_history": [
                {"status": "SUCCEEDED", "message": "已分析外部 Vault 密档。"}
              ],
              "subtasks": [
                {
                  "subtask_id": "review_knowledge:knowledge",
                  "role": "资料分析 agent",
                  "status": "SUCCEEDED",
                  "summary": "外部 Vault 密档：迁移包不应携带的外部 Obsidian 正文。",
                }
              ],
            }
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    subtask_dir = workflow_dir / "subtasks"
    subtask_dir.mkdir(parents=True, exist_ok=True)
    (subtask_dir / "review_knowledge_knowledge.json").write_text(
      json.dumps(
        {
          "task_id": "run-external",
          "step": 1,
          "subtask_id": "review_knowledge:knowledge",
          "role": "资料分析 agent",
          "status": "SUCCEEDED",
          "summary": "外部 Vault 密档：迁移包不应携带的外部 Obsidian 正文。",
          "history": [
            {"status": "SUCCEEDED", "summary": "迁移包不应携带的外部 Obsidian 正文。"}
          ],
        },
        ensure_ascii=False,
      ),
      encoding="utf-8",
    )
    self.assertTrue((project_dir / ".gaoxia" / "threads" / "thread-external.json").exists())
    self.assertTrue((project_dir / ".gaoxia" / "thread_context" / "thread-external.json").exists())
    self.assertTrue((project_dir / ".gaoxia" / "runs" / "run-external" / "workflow.json").exists())
    self.assertTrue((
      project_dir / ".gaoxia" / "runs" / "run-external" / "subtasks" / "review_knowledge_knowledge.json"
    ).exists())

    original_connection = sqlite3.connect(project_dir / "knowledge.db")
    try:
      original_count = original_connection.execute(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE kind = 'obsidian' AND content LIKE ?",
        ("%迁移包不应携带的外部 Obsidian 正文%",),
      ).fetchone()[0]
    finally:
      original_connection.close()
    self.assertGreater(original_count, 0)

    export_result = export_project_migration_package(self.settings, summary.id)
    self.assertTrue(any("Obsidian Vault 位于项目目录外" in item for item in export_result.warnings))

    with zipfile.ZipFile(export_result.path) as archive:
      names = set(archive.namelist())
      manifest = json.loads(archive.read(".gaoxia-project.json").decode("utf-8"))
      sanitized_db_bytes = archive.read("project/knowledge.db")
      sanitized_sync_text = archive.read("project/.gaoxia/obsidian_sync.json").decode("utf-8")
      sanitized_sync_payload = json.loads(sanitized_sync_text)
      sanitized_state_text = archive.read("project/.gaoxia/learning/narrative_state.json").decode("utf-8")
      sanitized_state_payload = json.loads(sanitized_state_text)
      sanitized_distillation_text = archive.read("project/project_distillation.json").decode("utf-8")
      sanitized_distillation_payload = json.loads(sanitized_distillation_text)
      sanitized_candidates_text = archive.read("project/.gaoxia/learning/self_evolution_candidates.json").decode("utf-8")
      sanitized_reviews_text = archive.read("project/.gaoxia/learning/self_evolution_reviews.jsonl").decode("utf-8")
      sanitized_failure_cases_text = archive.read("project/.gaoxia/learning/failure_cases.jsonl").decode("utf-8")
      sanitized_model_review_text = archive.read("project/.gaoxia/model_review_history.json").decode("utf-8")
      sanitized_thread_text = archive.read("project/.gaoxia/threads/thread-external.json").decode("utf-8")
      sanitized_thread_payload = json.loads(sanitized_thread_text)
      sanitized_workflow_text = archive.read("project/.gaoxia/runs/run-external/workflow.json").decode("utf-8")
      sanitized_workflow_payload = json.loads(sanitized_workflow_text)
      sanitized_subtask_text = archive.read(
        "project/.gaoxia/runs/run-external/subtasks/review_knowledge_knowledge.json"
      ).decode("utf-8")
      sanitized_subtask_payload = json.loads(sanitized_subtask_text)

    self.assertIn("project/.gaoxia/obsidian.json", names)
    self.assertIn("project/.gaoxia/obsidian_sync.json", names)
    self.assertIn("project/.gaoxia/learning/narrative_state.json", names)
    self.assertIn("project/.gaoxia/learning/self_evolution_candidates.json", names)
    self.assertIn("project/.gaoxia/learning/self_evolution_reviews.jsonl", names)
    self.assertIn("project/.gaoxia/learning/failure_cases.jsonl", names)
    self.assertIn("project/.gaoxia/model_review_history.json", names)
    self.assertIn("project/project_distillation.json", names)
    self.assertIn("project/.gaoxia/threads/thread-external.json", names)
    self.assertIn("project/.gaoxia/runs/run-external/workflow.json", names)
    self.assertIn("project/.gaoxia/runs/run-external/subtasks/review_knowledge_knowledge.json", names)
    self.assertNotIn("project/.gaoxia/thread_context/thread-external.json", names)
    self.assertNotIn("project/.gaoxia/obsidian_drafts/Graph/Secrets.md", names)
    self.assertNotIn("project/Secrets.md", names)
    self.assertTrue(any("Obsidian Vault 位于项目目录外" in item for item in manifest["warnings"]))
    self.assertEqual(sanitized_sync_payload["vault_path"], str(vault_dir))
    self.assertEqual(sanitized_sync_payload["notes"], [])
    self.assertEqual(sanitized_sync_payload["note_count"], 0)
    self.assertEqual(sanitized_sync_payload["included_count"], 0)
    self.assertEqual(sanitized_sync_payload["link_count"], 0)
    self.assertEqual(sanitized_sync_payload["external_link_count"], 0)
    self.assertEqual(sanitized_sync_payload["source_signature"], "")
    self.assertTrue(any("笔记摘要已从迁移包移除" in item for item in sanitized_sync_payload["warnings"]))
    self.assertNotIn("外部 Vault 密档", sanitized_sync_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_sync_text)
    self.assertEqual(sanitized_state_payload["obsidian_maintenance_suggestions"], [])
    self.assertEqual(sanitized_state_payload["obsidian_maintenance_actions"], [])
    self.assertEqual(sanitized_state_payload["obsidian_maintenance_summary"]["total"], 0)
    self.assertTrue(
      "维护队列已从迁移包移除" in sanitized_state_payload["obsidian_maintenance_summary"]["migration_notice"]
    )
    self.assertIn("项目内剧情债务", sanitized_state_text)
    self.assertNotIn("外部 Vault 密档", sanitized_state_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_state_text)
    self.assertNotIn(str(vault_dir), sanitized_state_text)
    self.assertEqual(sanitized_distillation_payload["source_signature"], "")
    self.assertTrue(sanitized_distillation_payload["is_stale"])
    self.assertEqual(sanitized_distillation_payload["source_profile"]["summary"], "")
    self.assertEqual(
      sanitized_distillation_payload["source_profile"]["material_notes"],
      ["项目内资料｜铜钥匙仍需要保留。"],
    )
    self.assertEqual(
      sanitized_distillation_payload["packs"][0]["must_keep"],
      ["项目内架构约束：铜钥匙不能丢。"],
    )
    self.assertTrue("蒸馏摘要已从迁移包移除" in sanitized_distillation_payload["migration_notice"])
    self.assertNotIn("外部 Vault 密档", sanitized_distillation_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_distillation_text)
    self.assertIn("资料分析记录已从迁移包移除", sanitized_candidates_text)
    self.assertIn("资料分析记录已从迁移包移除", sanitized_reviews_text)
    self.assertIn("资料分析记录已从迁移包移除", sanitized_failure_cases_text)
    self.assertIn("资料分析记录已从迁移包移除", sanitized_model_review_text)
    self.assertNotIn("外部 Vault 密档", sanitized_candidates_text)
    self.assertNotIn("外部 Vault 密档", sanitized_reviews_text)
    self.assertNotIn("外部 Vault 密档", sanitized_failure_cases_text)
    self.assertNotIn("外部 Vault 密档", sanitized_model_review_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_candidates_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_reviews_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_failure_cases_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_model_review_text)
    thread_message = sanitized_thread_payload["messages"][1]
    self.assertIn("资料分析记录已从迁移包移除", thread_message["content"])
    self.assertIn("资料分析记录已从迁移包移除", thread_message["execution_trace"][0]["summary"])
    self.assertEqual(thread_message["artifacts"][0]["content_preview"], "")
    self.assertEqual(thread_message["artifacts"][1]["content_preview"], "")
    self.assertNotIn("外部 Vault 密档", sanitized_thread_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_thread_text)
    self.assertIn("资料分析记录已从迁移包移除", sanitized_workflow_text)
    self.assertEqual(sanitized_workflow_payload["actions"][0]["message"], "外部 Obsidian Vault 的资料分析记录已从迁移包移除，导入后需要重新同步 Vault 并重新分析资料。")
    self.assertEqual(sanitized_workflow_payload["actions"][0]["contract"]["migration_notice"], "外部 Obsidian Vault 的资料分析记录已从迁移包移除，导入后需要重新同步 Vault 并重新分析资料。")
    self.assertEqual(sanitized_subtask_payload["summary"], "外部 Obsidian Vault 的资料分析记录已从迁移包移除，导入后需要重新同步 Vault 并重新分析资料。")
    self.assertNotIn("外部 Vault 密档", sanitized_workflow_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_workflow_text)
    self.assertNotIn("外部 Vault 密档", sanitized_subtask_text)
    self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", sanitized_subtask_text)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as db_temp_dir:
      sanitized_db_path = Path(db_temp_dir) / "knowledge.db"
      sanitized_db_path.write_bytes(sanitized_db_bytes)
      connection = sqlite3.connect(sanitized_db_path)
      try:
        obsidian_source_count = connection.execute(
          "SELECT COUNT(*) FROM knowledge_sources WHERE kind = 'obsidian' OR source = 'Obsidian' OR source_key LIKE 'obsidian:%'"
        ).fetchone()[0]
        obsidian_chunk_count = connection.execute(
          "SELECT COUNT(*) FROM knowledge_chunks WHERE kind = 'obsidian' OR source = 'Obsidian' OR source_key LIKE 'obsidian:%'"
        ).fetchone()[0]
        leaked_count = connection.execute(
          "SELECT COUNT(*) FROM knowledge_chunks WHERE content LIKE ?",
          ("%迁移包不应携带的外部 Obsidian 正文%",),
        ).fetchone()[0]
        source_signature = connection.execute(
          "SELECT state_value FROM knowledge_index_state WHERE state_key = 'source_signature'"
        ).fetchone()[0]
      finally:
        connection.close()

    self.assertEqual(obsidian_source_count, 0)
    self.assertEqual(obsidian_chunk_count, 0)
    self.assertEqual(leaked_count, 0)
    self.assertEqual(source_signature, "")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as target_data_dir:
      target_settings = Settings(data_dir=Path(target_data_dir))
      initialize_app_storage(target_settings)
      import_result = import_project_migration_package(
        target_settings,
        ProjectMigrationImportRequest(
          filename=Path(export_result.path).name,
          content_base64=base64.b64encode(Path(export_result.path).read_bytes()).decode("utf-8"),
        ),
      )
      imported_project_dir = Path(import_result.path)

      self.assertTrue(any("Obsidian Vault 位于项目目录外" in item for item in import_result.warnings))
      self.assertTrue((imported_project_dir / ".gaoxia" / "obsidian.json").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "obsidian_sync.json").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "learning" / "narrative_state.json").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "learning" / "self_evolution_candidates.json").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "learning" / "self_evolution_reviews.jsonl").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "learning" / "failure_cases.jsonl").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "model_review_history.json").exists())
      self.assertTrue((imported_project_dir / "project_distillation.json").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "threads" / "thread-external.json").exists())
      self.assertTrue((imported_project_dir / ".gaoxia" / "runs" / "run-external" / "workflow.json").exists())
      self.assertTrue((
        imported_project_dir / ".gaoxia" / "runs" / "run-external" / "subtasks" / "review_knowledge_knowledge.json"
      ).exists())
      self.assertFalse((imported_project_dir / ".gaoxia" / "thread_context" / "thread-external.json").exists())
      self.assertFalse((imported_project_dir / ".gaoxia" / "obsidian_drafts" / "Graph" / "Secrets.md").exists())
      imported_distillation_text = (imported_project_dir / "project_distillation.json").read_text(encoding="utf-8")
      self.assertIn("项目内资料", imported_distillation_text)
      self.assertNotIn("外部 Vault 密档", imported_distillation_text)
      imported_candidates_text = (
        imported_project_dir / ".gaoxia" / "learning" / "self_evolution_candidates.json"
      ).read_text(encoding="utf-8")
      imported_reviews_text = (
        imported_project_dir / ".gaoxia" / "learning" / "self_evolution_reviews.jsonl"
      ).read_text(encoding="utf-8")
      imported_failure_cases_text = (
        imported_project_dir / ".gaoxia" / "learning" / "failure_cases.jsonl"
      ).read_text(encoding="utf-8")
      imported_model_review_text = (
        imported_project_dir / ".gaoxia" / "model_review_history.json"
      ).read_text(encoding="utf-8")
      self.assertIn("资料分析记录已从迁移包移除", imported_candidates_text)
      self.assertIn("资料分析记录已从迁移包移除", imported_reviews_text)
      self.assertIn("资料分析记录已从迁移包移除", imported_failure_cases_text)
      self.assertIn("资料分析记录已从迁移包移除", imported_model_review_text)
      self.assertNotIn("外部 Vault 密档", imported_candidates_text)
      self.assertNotIn("外部 Vault 密档", imported_reviews_text)
      self.assertNotIn("外部 Vault 密档", imported_failure_cases_text)
      self.assertNotIn("外部 Vault 密档", imported_model_review_text)
      imported_thread_text = (imported_project_dir / ".gaoxia" / "threads" / "thread-external.json").read_text(encoding="utf-8")
      self.assertIn("资料分析记录已从迁移包移除", imported_thread_text)
      self.assertNotIn("外部 Vault 密档", imported_thread_text)
      imported_workflow_text = (
        imported_project_dir / ".gaoxia" / "runs" / "run-external" / "workflow.json"
      ).read_text(encoding="utf-8")
      imported_subtask_text = (
        imported_project_dir / ".gaoxia" / "runs" / "run-external" / "subtasks" / "review_knowledge_knowledge.json"
      ).read_text(encoding="utf-8")
      self.assertIn("资料分析记录已从迁移包移除", imported_workflow_text)
      self.assertNotIn("外部 Vault 密档", imported_workflow_text)
      self.assertNotIn("迁移包不应携带的外部 Obsidian 正文", imported_subtask_text)

  def test_migration_package_keeps_project_internal_obsidian_vault_index(self) -> None:
    summary = self.create_demo_project("项目内 Obsidian 迁移")
    project_dir = Path(summary.path)
    vault_dir = project_dir / "vault"
    vault_dir.mkdir()
    (vault_dir / "Clue.md").write_text(
      """---
type: note
status: canonical
---
# 项目内 Vault 线索

迁移包应该保留的项目内 Obsidian 正文。
""",
      encoding="utf-8",
    )
    update_project_obsidian_config(
      self.settings,
      summary.id,
      ObsidianVaultConfig(enabled=True, vault_path="vault", allowed_statuses=["canonical"]),
    )

    export_result = export_project_migration_package(self.settings, summary.id)
    self.assertFalse(any("Obsidian Vault 位于项目目录外" in item for item in export_result.warnings))

    with zipfile.ZipFile(export_result.path) as archive:
      names = set(archive.namelist())
      db_bytes = archive.read("project/knowledge.db")
      sync_payload = json.loads(archive.read("project/.gaoxia/obsidian_sync.json").decode("utf-8"))

    self.assertIn("project/vault/Clue.md", names)
    self.assertIn("project/.gaoxia/obsidian.json", names)
    self.assertTrue(any("项目内 Vault 线索" in item.get("title", "") for item in sync_payload.get("notes", [])))
    self.assertTrue(any("迁移包应该保留的项目内 Obsidian 正文" in item.get("preview", "") for item in sync_payload.get("notes", [])))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as db_temp_dir:
      db_path = Path(db_temp_dir) / "knowledge.db"
      db_path.write_bytes(db_bytes)
      connection = sqlite3.connect(db_path)
      try:
        obsidian_source_count = connection.execute(
          "SELECT COUNT(*) FROM knowledge_sources WHERE kind = 'obsidian' OR source = 'Obsidian' OR source_key LIKE 'obsidian:%'"
        ).fetchone()[0]
        obsidian_chunk_count = connection.execute(
          "SELECT COUNT(*) FROM knowledge_chunks WHERE kind = 'obsidian' AND content LIKE ?",
          ("%迁移包应该保留的项目内 Obsidian 正文%",),
        ).fetchone()[0]
      finally:
        connection.close()

    self.assertGreater(obsidian_source_count, 0)
    self.assertGreater(obsidian_chunk_count, 0)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as target_data_dir:
      target_settings = Settings(data_dir=Path(target_data_dir))
      initialize_app_storage(target_settings)
      import_result = import_project_migration_package(
        target_settings,
        ProjectMigrationImportRequest(
          filename=Path(export_result.path).name,
          content_base64=base64.b64encode(Path(export_result.path).read_bytes()).decode("utf-8"),
        ),
      )
      imported_project_dir = Path(import_result.path)
      self.assertTrue((imported_project_dir / "vault" / "Clue.md").exists())
      imported_detail = get_project_detail(target_settings, import_result.project.id)
      self.assertEqual(imported_detail.story_overview.obsidian.included_count, 1)
      self.assertFalse(imported_detail.story_overview.obsidian.warnings)

  def test_import_project_migration_package_registers_project_on_new_workspace(self) -> None:
    summary = self.create_demo_project("跨机导入")
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n迁移包应该保留章节正文。\n",
    )
    update_story_document(
      self.settings,
      summary.id,
      "core_seed",
      StoryDocumentUpdateRequest(content="核心种子也要一起迁移。"),
    )
    export_result = export_project_migration_package(self.settings, summary.id)
    package_bytes = Path(export_result.path).read_bytes()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as target_data_dir:
      target_settings = Settings(data_dir=Path(target_data_dir))
      initialize_app_storage(target_settings)
      import_result = import_project_migration_package(
        target_settings,
        ProjectMigrationImportRequest(
          filename=Path(export_result.path).name,
          content_base64=base64.b64encode(package_bytes).decode("utf-8"),
        ),
      )

      self.assertFalse(import_result.id_changed)
      self.assertEqual(import_result.project.id, summary.id)
      self.assertTrue(Path(import_result.path).exists())
      imported_meta = json.loads((Path(import_result.path) / "project.json").read_text(encoding="utf-8"))
      self.assertEqual(imported_meta["id"], summary.id)
      self.assertEqual(imported_meta["path"], import_result.path)

      imported_detail = get_project_detail(target_settings, import_result.project.id)
      imported_chapter = next(item for item in imported_detail.chapters if item.id == "chapter-001")
      self.assertIn("迁移包应该保留章节正文", imported_chapter.content)
      documents = {item.key: item.content for item in imported_detail.story_overview.documents}
      self.assertEqual(documents["core_seed"], "核心种子也要一起迁移。")
      self.assertTrue((Path(import_result.path) / "knowledge.db").exists())

  def test_project_migration_import_api_route_registers_project(self) -> None:
    summary = self.create_demo_project("接口导入")
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n接口导入应该保留章节正文。\n",
    )
    export_result = export_project_migration_package(self.settings, summary.id)
    package_bytes = Path(export_result.path).read_bytes()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as target_data_dir:
      target_settings = Settings(data_dir=Path(target_data_dir))
      initialize_app_storage(target_settings)
      matching_routes = [
        route
        for route in project_api_router.routes
        if getattr(route, "path", "") == "/api/projects/migration/import"
        and "POST" in (getattr(route, "methods", set()) or set())
      ]
      self.assertTrue(matching_routes)
      self.assertEqual(matching_routes[0].endpoint, post_project_migration_import)

      request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=target_settings, project_history_watcher=None))
      )
      payload = asyncio.run(
        post_project_migration_import(
          request,
          ProjectMigrationImportRequest(
            filename=Path(export_result.path).name,
            content_base64=base64.b64encode(package_bytes).decode("utf-8"),
          ),
        )
      )

      self.assertTrue(payload["ok"])
      imported_id = payload["data"]["project"]["id"]
      imported_detail = get_project_detail(target_settings, imported_id)
      imported_chapter = next(item for item in imported_detail.chapters if item.id == "chapter-001")
      self.assertIn("接口导入应该保留章节正文", imported_chapter.content)

  def test_import_project_migration_package_changes_id_when_conflicting(self) -> None:
    summary = self.create_demo_project("同机导入")
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n同一台机器重复导入时不能覆盖原项目。\n",
    )
    export_result = export_project_migration_package(self.settings, summary.id)

    import_result = import_project_migration_package(
      self.settings,
      ProjectMigrationImportRequest(
        filename=Path(export_result.path).name,
        content_base64=base64.b64encode(Path(export_result.path).read_bytes()).decode("utf-8"),
      ),
    )

    self.assertTrue(import_result.id_changed)
    self.assertNotEqual(import_result.project.id, summary.id)
    self.assertTrue(Path(import_result.path).exists())
    self.assertTrue(Path(summary.path).exists())
    self.assertEqual(len(list_projects(self.settings)), 2)

  def test_import_project_knowledge_updates_library_and_search(self) -> None:
    summary = self.create_demo_project("资料导入")

    detail = import_project_knowledge(
      self.settings,
      summary.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="旧船队口述记录",
            content="旧船队每逢大潮都会沿着隐秘航线出海，铜钥匙是唯一的启航凭证。",
          )
        ]
      ),
    )

    material = detail.story_overview.materials[0]
    self.assertEqual(material.title, "旧船队口述记录")
    self.assertIn("铜钥匙", material.preview)

    hits = search_project_knowledge(self.settings, summary.id, "隐秘航线")
    self.assertTrue(any(item.source == "资料库" for item in hits))
    self.assertTrue(any(item.section == "旧船队口述记录" for item in hits))

  def test_imported_source_material_without_model_cache_does_not_populate_graph(self) -> None:
    summary = self.create_demo_project("原著承接")

    import_project_knowledge(
      self.settings,
      summary.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="围城原文节选",
            content=(
              "方鸿渐回到寓所，孙柔嘉冷笑着问他在外面跟谁闲逛。"
              "赵辛楣后来来信，只说方鸿渐的婚姻像穿错的鞋。"
              "孙柔嘉见方鸿渐不答，又把旧事翻出来。"
              "赵辛楣在信末又提到方鸿渐不该再躲着孙柔嘉。"
            ),
          )
        ]
      ),
    )

    detail = get_project_detail(self.settings, summary.id)

    character_names = [item.name for item in detail.story_overview.characters]
    event_names = [item.name for item in detail.story_overview.events]
    self.assertEqual(character_names, [])
    self.assertEqual(event_names, [])
    self.assertEqual(detail.story_overview.materials[0].title, "围城原文节选")

    report = detail.story_overview.distillation_report
    self.assertIsNotNone(report)
    self.assertEqual(report.source_profile.character_notes, [])
    self.assertEqual(report.source_profile.event_notes, [])

  def test_search_project_knowledge_supports_semantic_ranking(self) -> None:
    summary = self.create_demo_project("语义检索")
    import_project_knowledge(
      self.settings,
      summary.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="潮位窗口笔记",
            content="隐秘航线只会在潮位窗口打开，灯塔会在涨潮前五分钟闪三次。",
          )
        ]
      ),
    )

    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(),
        embedding=EmbeddingConfig(
          api_key="embedding-key",
          base_url="https://example.com/v1",
          model_name="text-embedding-3-small",
          retrieval_k=6,
          batch_size=4,
        ),
      ),
    )

    def fake_embed_texts(_settings, texts, *, task_name="embedding"):
      vectors: list[list[float]] = []
      for item in texts:
        if "涨潮时刻" in item or "涨潮前" in item:
          vectors.append([1.0, 0.0, 0.0])
        elif "潮位窗口" in item:
          vectors.append([0.99, 0.01, 0.0])
        else:
          vectors.append([0.0, 1.0, 0.0])
      return vectors

    with patch("novel_backend.services.project_service.embed_texts", side_effect=fake_embed_texts):
      hits = search_project_knowledge(self.settings, summary.id, "涨潮时刻怎么开启")

    self.assertTrue(hits)
    self.assertEqual(hits[0].section, "潮位窗口笔记")
    self.assertIn(hits[0].match_type, {"semantic", "hybrid"})
    with sqlite3.connect(Path(summary.path) / "knowledge.db") as connection:
      row = connection.execute(
        """
        SELECT vector_json, vector_blob, vector_dimension
        FROM knowledge_vectors
        WHERE vector_dimension > 0
        LIMIT 1
        """
      ).fetchone()
    self.assertIsNotNone(row)
    self.assertEqual(row[0], "")
    self.assertTrue(row[1])
    self.assertEqual(row[2], 3)

  def test_knowledge_vector_json_rows_are_migrated_to_binary_storage(self) -> None:
    summary = self.create_demo_project("向量迁移")
    import_project_knowledge(
      self.settings,
      summary.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="潮位窗口笔记",
            content="隐秘航线只会在潮位窗口打开。",
          )
        ]
      ),
    )
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(),
        embedding=EmbeddingConfig(
          api_key="embedding-key",
          base_url="https://example.com/v1",
          model_name="text-embedding-3-small",
          retrieval_k=6,
          batch_size=4,
        ),
      ),
    )

    def fake_embed_texts(_settings, texts, *, task_name="embedding"):
      return [[1.0, 0.0, 0.0] for _item in texts]

    with patch("novel_backend.services.project_service.embed_texts", side_effect=fake_embed_texts):
      search_project_knowledge(self.settings, summary.id, "潮位")

    db_path = Path(summary.path) / "knowledge.db"
    with sqlite3.connect(db_path) as connection:
      chunk_id = connection.execute("SELECT chunk_id FROM knowledge_vectors LIMIT 1").fetchone()[0]
      connection.execute(
        """
        UPDATE knowledge_vectors
        SET vector_json = ?, vector_blob = NULL, vector_dimension = 0
        WHERE chunk_id = ?
        """,
        ("[1.0, 0.0, 0.0]", chunk_id),
      )
      connection.commit()

    _initialize_knowledge_db(db_path)

    with sqlite3.connect(db_path) as connection:
      vector_blob, vector_dimension = connection.execute(
        "SELECT vector_blob, vector_dimension FROM knowledge_vectors WHERE chunk_id = ?",
        (chunk_id,),
      ).fetchone()
    self.assertTrue(vector_blob)
    self.assertEqual(vector_dimension, 3)

  def test_update_chapter_content_refreshes_single_knowledge_source(self) -> None:
    summary = self.create_demo_project("章节增量索引")
    update_chapter_content(
      self.settings,
      summary.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n"),
    )
    update_chapter_content(
      self.settings,
      summary.id,
      "chapter-002",
      ChapterUpdateRequest(content="# 第二章 灯塔影子\n白石商会的人开始追查旧船队记录。\n"),
    )

    with patch(
      "novel_backend.services.project_service._rebuild_project_knowledge",
      side_effect=AssertionError("chapter update should use source refresh"),
    ):
      update_chapter_content(
        self.settings,
        summary.id,
        "chapter-001",
        ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库找到新的潮位线索。\n"),
      )

    with sqlite3.connect(Path(summary.path) / "knowledge.db") as connection:
      chapter_one_rows = connection.execute(
        "SELECT content FROM knowledge_chunks WHERE source_key = ?",
        ("chapter:chapter-001",),
      ).fetchall()
      chapter_two_rows = connection.execute(
        "SELECT content FROM knowledge_chunks WHERE source_key = ?",
        ("chapter:chapter-002",),
      ).fetchall()

    self.assertTrue(any("新的潮位线索" in row[0] for row in chapter_one_rows))
    self.assertFalse(any("铜钥匙" in row[0] for row in chapter_one_rows))
    self.assertTrue(any("白石商会" in row[0] for row in chapter_two_rows))

  def test_write_project_file_refreshes_single_knowledge_source(self) -> None:
    summary = self.create_demo_project("文件增量索引")

    with patch(
      "novel_backend.services.project_service._rebuild_project_knowledge",
      side_effect=AssertionError("file save should use source refresh"),
    ):
      write_project_file(
        self.settings,
        summary.id,
        "world_building.txt",
        "涨潮时隐秘航线会显影，灯塔必须连闪三次。",
      )

    with sqlite3.connect(Path(summary.path) / "knowledge.db") as connection:
      rows = connection.execute(
        "SELECT content FROM knowledge_chunks WHERE source_key = ?",
        ("story:world_building",),
      ).fetchall()

    self.assertTrue(any("隐秘航线" in row[0] for row in rows))

  def test_apply_architecture_workspace_updates_documents_and_targets(self) -> None:
    summary = self.create_demo_project("分步架构写回")

    detail = apply_architecture_workspace(
      self.settings,
      summary.id,
      ArchitectureWorkspaceApplyRequest(
        workspace=ArchitectureWorkspace(
          core_seed="铜钥匙牵出旧船队和主角家族的旧账。",
          character_design="林追追查真相，港务会追杀知情者，旧船队后人掌握潮位线索。",
          world_building="隐秘航线只在灯塔信号和潮位同时满足时开启。",
          plot_structure="前段引案，中段揭密，后段改写秩序。",
          blueprint="## 第 1 章《雨夜靠港》\n拿到钥匙并暴露行踪。",
        ),
        genre="悬疑奇谈",
        target_chapters=5,
        target_words=88000,
      ),
    )

    self.assertEqual(detail.genre, "悬疑奇谈")
    self.assertEqual(detail.target_chapters, 5)
    self.assertEqual(detail.target_words, 88000)
    documents = {item.key: item.content for item in detail.story_overview.documents}
    self.assertIn("铜钥匙", documents["core_seed"])
    self.assertIn("隐秘航线", documents["world_building"])
    self.assertEqual(len(detail.chapters), 5)

  def test_run_project_dream_auto_promotes_candidate_to_system_memory(self) -> None:
    summary = self.create_demo_project("做梦整理")
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )
    update_story_document(
      self.settings,
      summary.id,
      "core_seed",
      StoryDocumentUpdateRequest(content="铜钥匙和失踪航线持续牵出林追的身世。"),
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙，白石商会开始盯上他。\n",
    )

    with patch(
      "novel_backend.services.project_dream_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "这轮做梦反复浮出来的是铜钥匙、身世和白石商会的压迫。",
                  "themes": ["铜钥匙", "身世", "白石商会"],
                  "insights": ["主线始终围绕钥匙和身世绑定推进。", "白石商会正在从外围试探转向正面压迫。"],
                  "open_questions": ["白石商会第一次公开出手要放在哪个阶段？"],
                  "memory_candidates": [
                    {
                      "title": "悬念追踪",
                      "category": "警告",
                      "content": "不要太早揭开铜钥匙和林追身世的绑定关系。",
                      "rationale": "核心悬念已经在种子、章节和组织线里多次出现。",
                      "confidence": 0.86,
                    },
                    {
                      "title": "弱线索",
                      "category": "连续性",
                      "content": "白石商会仍处在外围施压阶段。",
                      "rationale": "这条判断还比较早，但自动化流程应照样沉入系统侧。",
                      "confidence": 0.2,
                    }
                  ],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      detail = run_project_dream(
        self.settings,
        summary.id,
        ProjectDreamRunRequest(focus="聚焦主线悬念"),
      )

    self.assertIsNotNone(detail.story_overview.dream_report)
    self.assertEqual(detail.story_overview.dream_report.engine, "model")
    self.assertIn("铜钥匙", detail.story_overview.dream_report.summary)
    system_memory = [item for item in detail.story_overview.memory_entries if item.source == "auto"]
    self.assertTrue(any("不要太早揭开铜钥匙" in item.content for item in system_memory))
    self.assertTrue(any("白石商会仍处在外围施压阶段" in item.content for item in system_memory))
    self.assertTrue(all(item.promoted_at for item in detail.story_overview.dream_report.memory_candidates))
    auxiliary_state = json.loads((Path(summary.path) / ".gaoxia" / "auxiliary_tasks.json").read_text(encoding="utf-8"))
    self.assertEqual(auxiliary_state["tasks"]["humanize_review"]["status"], "pending")
    self.assertEqual(auxiliary_state["tasks"]["humanize_review"]["reason"], "dream")

  def test_story_change_refreshes_dream_report_automatically(self) -> None:
    summary = self.create_demo_project("梦境自动刷新")
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
    )

    detail = run_project_dream(
      self.settings,
      summary.id,
      ProjectDreamRunRequest(),
    )
    self.assertFalse(detail.story_overview.dream_report.is_stale)

    updated = update_story_document(
      self.settings,
      summary.id,
      "core_seed",
      StoryDocumentUpdateRequest(content="主线从铜钥匙延伸到白石商会和主角家族旧账。"),
    )
    self.assertFalse(updated.story_overview.dream_report.is_stale)
    self.assertEqual(updated.story_overview.dream_report.engine, "heuristic")
    system_memory = [item for item in updated.story_overview.memory_entries if item.source == "auto"]
    self.assertTrue(any(item.id.startswith("dream-") for item in system_memory))

  def test_save_and_load_project_agent_threads(self) -> None:
    summary = self.create_demo_project("线程持久化")

    saved = save_project_agent_threads(
      self.settings,
      summary.id,
      AgentThreadStoreUpdateRequest(
        active_thread_id="thread-1",
        threads=[
          AgentThreadRecord(
            id="thread-1",
            title="续写第一章",
            preview="先判断再续写第一章",
            updated_at="2026-04-17T12:00:00+00:00",
            messages=[
              AgentThreadMessage(role="user", content="续写这一章"),
              AgentThreadMessage(
                role="assistant",
                content="先补架构再续写。",
                mode="plan",
                task_pack_kind="continuation",
                plan=AgentPlan(
                  id="plan-1",
                  title="续写第一章",
                  summary="先补架构再续写。",
                  requires_confirmation=True,
                  steps=["补齐整书架构", "续写第一章"],
                  actions=[
                      AgentPlanAction(kind="generate_architecture", label="补架构"),
                    AgentPlanAction(kind="chapter_workflow", label="续写第一章", task_pack_kind="continuation", chapter_id="chapter-001", mode="draft"),
                  ],
                ),
                execution_trace=[
                  AgentExecutionTrace(
                    step=1,
                    action_kind="generate_architecture",
                    label="补架构",
                    task_pack_kind="architecture",
                    status="completed",
                    summary="整书架构已经写回项目。",
                    changes=["已更新情节骨架"],
                  ),
                ],
                event_blocks=[
                  AgentEventBlock(
                    event_type="plan_generated",
                    title="续写第一章",
                    status="pending",
                    summary="先补架构再续写。",
                    step=1,
                    action_kind="generate_architecture",
                  ),
                ],
                artifacts=[
                  AgentArtifact(
                    kind="architecture_workspace",
                    title="整书架构",
                    summary="整书架构已经写回项目。",
                    content_preview="核心种子\n\n章节蓝图",
                    metadata={"architecture_progress": 5},
                  ),
                ],
                state=AgentStateSummary(
                  project_name="线程持久化",
                  genre="悬疑",
                  discussion_ready=False,
                  architecture_ready=False,
                  architecture_progress=0,
                  document_status={},
                ),
                suggestions=["确认执行"],
              ),
            ],
            suggestions=["确认执行"],
            pending_plan=AgentPlan(
              id="plan-1",
              title="续写第一章",
              summary="先补架构再续写。",
              requires_confirmation=True,
              steps=["补齐整书架构", "续写第一章"],
              actions=[
                AgentPlanAction(kind="generate_architecture", label="补架构"),
                AgentPlanAction(kind="chapter_workflow", label="续写第一章", task_pack_kind="continuation", chapter_id="chapter-001", mode="draft"),
              ],
            ),
          )
        ],
      ),
    )

    self.assertEqual(saved.active_thread_id, "thread-1")
    self.assertEqual(saved.threads[0].messages[1].mode, "plan")

    loaded = get_project_agent_threads(self.settings, summary.id)
    self.assertEqual(loaded.active_thread_id, "thread-1")
    self.assertEqual(len(loaded.threads), 1)
    self.assertEqual(loaded.threads[0].pending_plan.id, "plan-1")
    self.assertEqual(loaded.threads[0].messages[1].suggestions[0], "确认执行")
    self.assertEqual(loaded.threads[0].messages[1].task_pack_kind, "continuation")
    self.assertEqual(loaded.threads[0].messages[1].execution_trace[0].task_pack_kind, "architecture")
    self.assertEqual(loaded.threads[0].messages[1].execution_trace[0].status, "completed")
    self.assertEqual(loaded.threads[0].messages[1].event_blocks[0].event_type, "plan_generated")
    self.assertEqual(loaded.threads[0].messages[1].artifacts[0].kind, "architecture_workspace")

  def test_save_project_agent_threads_removes_stale_thread_files(self) -> None:
    summary = self.create_demo_project("线程清理")
    project_dir = Path(summary.path)

    save_project_agent_threads(
      self.settings,
      summary.id,
      AgentThreadStoreUpdateRequest(
        active_thread_id="thread-1",
        threads=[
          AgentThreadRecord(
            id="thread-1",
            title="线程一",
            preview="线程一预览",
            updated_at="2026-04-17T12:00:00+00:00",
            messages=[AgentThreadMessage(role="user", content="第一轮")],
          ),
          AgentThreadRecord(
            id="thread-2",
            title="线程二",
            preview="线程二预览",
            updated_at="2026-04-17T12:01:00+00:00",
            messages=[AgentThreadMessage(role="user", content="第二轮")],
          ),
        ],
      ),
    )

    save_project_agent_threads(
      self.settings,
      summary.id,
      AgentThreadStoreUpdateRequest(
        active_thread_id="thread-2",
        threads=[
          AgentThreadRecord(
            id="thread-2",
            title="线程二",
            preview="线程二预览",
            updated_at="2026-04-17T12:01:00+00:00",
            messages=[AgentThreadMessage(role="user", content="第二轮")],
          )
        ],
      ),
    )

    self.assertFalse((project_dir / ".gaoxia" / "threads" / "thread-1.json").exists())
    self.assertTrue((project_dir / ".gaoxia" / "threads" / "thread-2.json").exists())


if __name__ == "__main__":
  unittest.main()
