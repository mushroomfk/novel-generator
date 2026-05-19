from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import CreateProjectRequest
from novel_backend.services.agent_trajectory_service import append_agent_trajectory
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.log_service import append_prompt_history
from novel_backend.services.project_service import create_project
from novel_backend.services.self_evolution_service import build_self_evolution_report


class SelfEvolutionServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self.project = create_project(
      self.settings,
      CreateProjectRequest(
        name="自我进化回归",
        genre="港口悬疑",
        target_chapters=5,
        target_words=80000,
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def _append_learning_review(self, payload: dict[str, object]) -> None:
    path = Path(self.project.path) / ".gaoxia" / "learning" / "reviews.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
      handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

  def test_build_self_evolution_report_collects_candidates_from_project_records(self) -> None:
    self._append_learning_review(
      {
        "id": "learning-001",
        "project_id": self.project.id,
        "task_id": "task-learning",
        "generated_at": "2026-05-05T00:00:00+00:00",
        "latest_user_message": "以后章节低分时自动修订，并把经验沉淀成技能。",
        "plan": {"title": "章节修订回顾"},
        "skill_candidates": [
          {
            "id": "skill-001",
            "title": "章节低分修订经验",
            "content": "低分章节先看连续性，再处理人物口气，最后复查分数。",
            "rationale": "自动修订产生了可复用步骤。",
            "confidence": 0.78,
          }
        ],
        "memory_candidates": [
          {
            "id": "memory-001",
            "title": "作者流程偏好",
            "content": "每章写完后都要做章节核验和修订。",
            "rationale": "这是长期偏好，但仍需确认。",
            "confidence": 0.72,
          }
        ],
      }
    )
    append_agent_trajectory(
      self.settings,
      {
        "task_id": "task-failed",
        "project_id": self.project.id,
        "thread_id": "thread-1",
        "status": "failed",
        "error": "章节生成工具失败",
        "latest_user_message": "继续生成下一章",
        "plan": {
          "id": "plan-failed",
          "title": "生成下一章",
          "actions": [{"kind": "chapter_generate", "label": "生成正文"}],
        },
        "execution_trace": [],
        "artifacts": [],
        "changes": [],
        "suggestions": [],
      },
    )
    append_agent_trajectory(
      self.settings,
      {
        "task_id": "task-review",
        "project_id": self.project.id,
        "thread_id": "thread-1",
        "status": "completed",
        "error": "",
        "latest_user_message": "写完后检查这一章",
        "plan": {
          "id": "plan-review",
          "title": "章节核验",
          "actions": [{"kind": "chapter_generate", "label": "生成正文"}],
        },
        "execution_trace": [],
        "artifacts": [
          {
            "kind": "chapter_content",
            "title": "第 1 章《雨夜靠港》",
            "summary": "核验后发现人物口气和连续性问题。",
            "metadata": {
              "review_score": 58,
              "review_status": "risk",
              "review_auto_repair_applied": True,
              "review_auto_repair_summary": "已修订人物口气和连续性。",
              "review_auto_repair_reason": "分数低于阈值。",
            },
          }
        ],
        "changes": [],
        "suggestions": [],
      },
    )
    append_prompt_history(
      self.settings,
      {
        "task": "章节生成",
        "model": "demo-model",
        "prompt": "请生成章节",
        "response": "",
        "status": "failed",
        "error": "模型超时",
        "error_kind": "timeout",
        "error_title": "模型调用超时",
        "error_user_action": "检查模型服务后重试。",
      },
    )

    report = build_self_evolution_report(self.settings, self.project.id)

    self.assertEqual(report.project_id, self.project.id)
    self.assertEqual(report.learning_review_count, 1)
    self.assertEqual(report.trajectory_count, 2)
    self.assertEqual(report.prompt_failure_count, 1)
    self.assertGreater(report.skill_curation.total, 0)
    kinds = {item.kind for item in report.candidates}
    self.assertIn("skill", kinds)
    self.assertIn("memory", kinds)
    self.assertIn("prompt", kinds)
    self.assertIn("review", kinds)
    self.assertTrue(any("章节低分修订经验" in item.title for item in report.candidates))
    self.assertTrue(any("章节核验样本" in item.title for item in report.candidates))


if __name__ == "__main__":
  unittest.main()
