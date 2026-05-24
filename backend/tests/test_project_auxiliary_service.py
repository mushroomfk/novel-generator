from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import CreateProjectRequest
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.project_auxiliary_service import (
  enqueue_project_auxiliary_tasks,
  run_project_auxiliary_tasks,
)
from novel_backend.services.project_service import create_project
from novel_backend.utils.jsonfile import read_json


class ProjectAuxiliaryServiceTestCase(unittest.TestCase):
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
        name="辅助任务测试",
        genre="悬疑",
        target_chapters=3,
        target_words=50000,
      ),
    )

  def test_knowledge_index_embedding_failure_keeps_task_retryable(self) -> None:
    summary = self.create_demo_project()
    Path(summary.path, "core_seed.txt").write_text("主角发现旧案里有一封匿名信。", encoding="utf-8")
    enqueue_project_auxiliary_tasks(
      self.settings,
      summary.id,
      tasks=["knowledge_index"],
      reason="test",
    )

    with (
      patch(
        "novel_backend.services.project_service.embedding_config_signature",
        return_value="test-provider|https://example.test|embed-test|0|8|16|ready",
      ),
      patch(
        "novel_backend.services.project_service.embed_texts",
        side_effect=RuntimeError("embedding down"),
      ),
    ):
      result = run_project_auxiliary_tasks(self.settings, summary.id, force=True)

    self.assertEqual(result["ran"][0]["task"], "knowledge_index")
    self.assertEqual(result["ran"][0]["status"], "failed")
    self.assertIn("embedding down", str(result["ran"][0]["error"]))

    state = read_json(Path(summary.path) / ".gaoxia" / "auxiliary_tasks.json", {})
    task_state = state["tasks"]["knowledge_index"]
    self.assertEqual(task_state["status"], "failed")
    self.assertEqual(task_state["retry_count"], 1)
    self.assertIn("embedding down", task_state["last_error"])
    self.assertTrue(task_state["next_run_at"])

  def test_story_overview_model_failure_keeps_task_retryable(self) -> None:
    summary = self.create_demo_project()
    Path(summary.path, "core_seed.txt").write_text("林晚在雨夜收到旧账本。", encoding="utf-8")
    enqueue_project_auxiliary_tasks(
      self.settings,
      summary.id,
      tasks=["story_overview_model"],
      reason="test",
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
      result = run_project_auxiliary_tasks(self.settings, summary.id, force=True)

    self.assertEqual(result["ran"][0]["task"], "story_overview_model")
    self.assertEqual(result["ran"][0]["status"], "failed")
    self.assertIn("模型总览生成失败", str(result["ran"][0]["error"]))

    state = read_json(Path(summary.path) / ".gaoxia" / "auxiliary_tasks.json", {})
    task_state = state["tasks"]["story_overview_model"]
    self.assertEqual(task_state["status"], "failed")
    self.assertEqual(task_state["retry_count"], 1)
    self.assertIn("模型总览生成失败", task_state["last_error"])
    self.assertTrue(task_state["next_run_at"])
