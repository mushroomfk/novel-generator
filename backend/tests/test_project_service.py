from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
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
  KnowledgeImportItem,
  KnowledgeImportRequest,
  ModelConfig,
  ProjectDreamPromoteRequest,
  ProjectDreamRunRequest,
  ProjectExportRequest,
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
from novel_backend.services.project_distillation_service import build_distillation_review_text, resolve_task_pack_kind
from novel_backend.services.project_service import (
  _initialize_knowledge_db,
  apply_architecture_workspace,
  create_project,
  create_project_snapshot,
  delete_project,
  export_project_book,
  get_project_agent_threads,
  get_project_detail,
  import_project_knowledge,
  open_project_directory,
  promote_project_dream,
  rename_project,
  restore_project_snapshot,
  run_project_dream,
  save_project_agent_threads,
  search_project_knowledge,
  refresh_chapter_review,
  refresh_project_model_story_overview,
  update_project_memory,
  update_chapter_content,
  update_chapter_content_with_review_status,
  update_story_documents,
  update_story_document,
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

  def test_story_overview_without_model_cache_does_not_extract_graph(self) -> None:
    summary = self.create_demo_project("无模型总览")
    project_dir = Path(summary.path)
    (project_dir / "character_design.txt").write_text(
      "林追：港口里最会追线索的人，擅长开锁，习惯在黑夜里行动。\n",
      encoding="utf-8",
    )
    self.write_chapter(
      summary.path,
      1,
      "# 第一章 雨夜靠港\n林追在旧码头仓库用开锁技巧打开铁门，找到一把铜钥匙，随后闯进白石商会。\n",
    )

    detail = get_project_detail(self.settings, summary.id)

    documents = {item.key: item.content for item in detail.story_overview.documents}
    self.assertIn("林追", documents["character_design"])
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
