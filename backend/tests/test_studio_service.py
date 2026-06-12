from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  AppConfigUpdateRequest,
  BatchGenerateRequest,
  BlueprintGenerateRequest,
  BrainstormRequest,
  BrainstormMessage,
  CharacterReplicaRequest,
  ChapterGenerateRequest,
  ChapterGenerateResult,
  ChapterReviewDimension,
  ChapterReviewIssue,
  ChapterReviewReport,
  ChapterRewriteRequest,
  ChapterUpdateRequest,
  ContinueProjectRequest,
  CreateProjectRequest,
  EmbeddingConfig,
  ModelConfig,
  ObsidianVaultConfig,
  ProjectDreamRunRequest,
  PromptPresetCreateRequest,
  PromptPresetUpdateRequest,
  SkillMaterializeRequest,
  StyleCalibrateRequest,
  StyleReferenceImportRequest,
  StyleReferenceItem,
  StyleSaveRequest,
  StyleAnalyzeRequest,
  StyleDNAAnalyzeRequest,
)
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.file_service import list_project_files, read_project_file, write_project_file
from novel_backend.services.preset_service import (
  activate_prompt_preset,
  create_prompt_preset,
  get_active_prompt_instruction,
  update_prompt_preset,
)
from novel_backend.services.project_service import (
  create_project,
  get_project_detail,
  run_project_dream,
  update_chapter_content,
  update_project_obsidian_config,
)
from novel_backend.services.config_service import save_config
from novel_backend.services.style_service import (
  build_style_reference_text,
  get_style,
  import_style_references,
  rollback_style_calibration,
  save_style,
  search_style_references,
)
from novel_backend.services.skill_service import materialize_skill
from novel_backend.services.studio_service import (
  batch_generate_stream,
  blueprint_stream,
  brainstorm_stream,
  character_replica_stream,
  chapter_generate_prompt_preview,
  chapter_generate_stream,
  chapter_rewrite_stream,
  continue_project_stream,
  style_analyze_stream,
  style_analyze_dna_stream,
  style_calibrate_narrative_stream,
  style_calibrate_stream,
)


def decode_sse_event(chunk: str) -> tuple[str, object]:
  event_name = "message"
  data = ""
  for raw_line in chunk.strip().splitlines():
    if raw_line.startswith("event:"):
      event_name = raw_line.split(":", 1)[1].strip()
    elif raw_line.startswith("data:"):
      data = raw_line.split(":", 1)[1].strip()
  return event_name, json.loads(data)


async def collect_stream(stream) -> list[tuple[str, object]]:
  events: list[tuple[str, object]] = []
  async for chunk in stream:
    events.append(decode_sse_event(chunk))
  return events


class StudioServiceTestCase(unittest.TestCase):
  def _fake_chapter_review(self, _settings, detail, chapter_id: str, *, style_name: str = "") -> ChapterReviewReport:
    chapter = next(item for item in detail.chapters if item.id == chapter_id)
    return ChapterReviewReport(
      chapter_id=chapter.id,
      chapter_index=chapter.index,
      chapter_title=chapter.title,
      version="complete",
      engine="studio-test",
      status="good",
      overall_score=88,
      summary="测试环境跳过模型审查。",
      style_name=style_name,
      updated_at="2026-05-23T00:00:00+00:00",
      source_signature=f"studio-test:{chapter.id}:{style_name}",
    )

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
        name="工作室回归",
        genre="悬疑幻想",
        target_chapters=3,
        target_words=60000,
      ),
    )
    self._chapter_review_patcher = patch(
      "novel_backend.services.project_service.build_chapter_review",
      side_effect=self._fake_chapter_review,
    )
    self._chapter_review_patcher.start()
    self.addCleanup(self._chapter_review_patcher.stop)
    self._embedding_signature_patcher = patch(
      "novel_backend.services.project_service.embedding_config_signature",
      return_value="studio-tests:not-ready",
    )
    self._embedding_signature_patcher.start()
    self.addCleanup(self._embedding_signature_patcher.stop)
    self._embedding_request_patcher = patch(
      "novel_backend.services.project_service.embed_texts",
      side_effect=RuntimeError("skip embedding in studio tests"),
    )
    self._embedding_request_patcher.start()
    self.addCleanup(self._embedding_request_patcher.stop)
    self._rerank_patcher = patch(
      "novel_backend.services.project_service.rerank_documents",
      return_value=[],
    )
    self._rerank_patcher.start()
    self.addCleanup(self._rerank_patcher.stop)
    self._narrative_model_patcher = patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      side_effect=RuntimeError("skip narrative model editor in studio tests"),
    )
    self._narrative_model_patcher.start()
    self.addCleanup(self._narrative_model_patcher.stop)
    self.project_dir = Path(self.project.path)
    (self.project_dir / "core_seed.txt").write_text("海港旧航线和铜钥匙牵出主角身世。", encoding="utf-8")
    (self.project_dir / "plot_structure.txt").write_text("前段引案，中段追索，后段改写秩序。", encoding="utf-8")
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n"),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_brainstorm_stream_returns_reply_and_suggestions(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "reply": "这轮先把钥匙为什么会暴露主角身份说清楚，再决定追兵怎么进场。",
                  "suggestions": ["钥匙和家族的关系是什么", "追兵第一次露面放在哪一幕"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_stream(
          brainstorm_stream(
            self.settings,
            BrainstormRequest(
              project_id=self.project.id,
              messages=[BrainstormMessage(role="user", content="这本书下一步该先推什么？")],
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("钥匙", result_event[1]["reply"])
    self.assertEqual(len(result_event[1]["suggestions"]), 2)
    self.assertIn("skill_candidate", result_event[1])

  def test_brainstorm_stream_injects_custom_skill_prompt(self) -> None:
    with patch("novel_backend.services.generation_service._request_chat_completion", side_effect=RuntimeError("skip-model")):
      created = materialize_skill(
        self.settings,
        SkillMaterializeRequest(
          project_id=self.project.id,
          messages=[
            BrainstormMessage(role="user", content="以后碰到章节去 AI，都按保剧情、压句、回查事实这套流程来。"),
            BrainstormMessage(role="assistant", content="可以，先识别模板腔，再压句，最后回看事实和人物关系。"),
          ],
          action="create",
          selected_chapter_id="chapter-001",
        ),
      )

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "reply": "这轮先按既定技能处理对白和模板腔，再回看剧情事实。",
                  "suggestions": ["对白里哪一句最像模型腔", "哪些信息绝对不能改动"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ) as mocked_request:
      asyncio.run(
        collect_stream(
          brainstorm_stream(
            self.settings,
            BrainstormRequest(
              project_id=self.project.id,
              skill_id=created.skill.id,
              messages=[BrainstormMessage(role="user", content="这一章先按刚才那套技能处理。")],
              include_blueprint=True,
              include_character_state=True,
            ),
          )
        )
      )

    sent_prompt = "\n\n".join(
      str(item.get("content") or "")
      for item in mocked_request.call_args.args[2]["messages"]
    )
    self.assertIn("当前启用用户技能", sent_prompt)
    self.assertIn(created.skill.name, sent_prompt)

  def test_brainstorm_stream_uses_chapter_context_and_project_style_xp_support(self) -> None:
    vault_dir = Path(self._temp_dir.name) / "vault-brainstorm-style-xp"
    vault_dir.mkdir()
    update_project_obsidian_config(
      self.settings,
      self.project.id,
      ObsidianVaultConfig(enabled=True, vault_path=str(vault_dir), allowed_statuses=["canonical"]),
    )
    style_path = self.project_dir / ".gaoxia" / "learning" / "style_xp_evolution.json"
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text(
      json.dumps(
        {
          "schema_version": 1,
          "updated_at": "2026-06-03T00:00:00+00:00",
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

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "reply": "先把这一章的主冲突压实，再决定下一步揭示顺序。",
                  "suggestions": ["主冲突是哪一个选择", "章尾压力要落在哪个信息点"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ) as mocked_request:
      asyncio.run(
        collect_stream(
          brainstorm_stream(
            self.settings,
            BrainstormRequest(
              project_id=self.project.id,
              chapter_id="chapter-003",
              messages=[BrainstormMessage(role="user", content="第 3 章下一步该怎么推？")],
              include_blueprint=True,
              include_character_state=True,
            ),
          )
        )
      )

    sent_prompt = "\n\n".join(
      str(item.get("content") or "")
      for item in mocked_request.call_args.args[2]["messages"]
    )
    self.assertIn("Obsidian 待审软约束", sent_prompt)
    self.assertIn("[文风]", sent_prompt)
    self.assertIn("[XP]", sent_prompt)
    self.assertIn("系统学习版文风 / XP", sent_prompt)
    self.assertIn("动作停顿之间保留可见因果", sent_prompt)
    self.assertIn("生成后确认线索压力留到章尾", sent_prompt)

  def test_character_replica_stream_returns_structured_result(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "乔布斯视角已经整理好。",
                  "summary": "重点不是信息更多，而是先把开头的选择和冲突压得更准。",
                  "voice_profile": "说话会先切核心问题，讨厌平铺直叙和功能堆砌。",
                  "mental_models": [
                    "先判断什么是作品里真正重要的那一个体验。",
                    "聚焦比堆料更重要，宁可删掉次要设定。",
                    "开头要立刻让读者感到这件事非看不可。",
                  ],
                  "heuristics": [
                    "每一章先确认主冲突，不要同时讲三件事。",
                    "信息揭示只留最能推高张力的那部分。",
                    "人物选择要比设定说明先出现。",
                  ],
                  "boundaries": [
                    "这是基于公开表达提炼的近似视角，不等于人物本人。",
                    "对具体文学题材的偏好不一定完整可见。",
                  ],
                  "answer": "如果用乔布斯的视角看，你这一章开头的问题不是信息少，而是主选择不够早。先把主角必须立刻做决定的那一下提前。",
                  "disclaimer": "这是根据公开表达和你给的上下文整理出的近似视角。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ) as mocked_request:
      events = asyncio.run(
        collect_stream(
          character_replica_stream(
            self.settings,
            CharacterReplicaRequest(
              persona_name="乔布斯",
              question="如果用他的视角看，我这一章开头该怎么改？",
              focus="只看开头的取舍和冲突。",
              project_id=self.project.id,
              chapter_id="chapter-001",
              include_project_context=True,
              include_chapter_context=True,
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("乔布斯", result_event[1]["headline"])
    self.assertEqual(len(result_event[1]["mental_models"]), 3)
    self.assertIn("主角必须立刻做决定", result_event[1]["answer"])

    sent_prompt = "\n\n".join(
      str(item.get("content") or "")
      for item in mocked_request.call_args.args[2]["messages"]
    )
    self.assertIn("当前章节：第 1 章《第一章 雨夜靠港》", sent_prompt)
    self.assertIn("人物名称：乔布斯", sent_prompt)

  def test_blueprint_stream_returns_outline(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "章节规划已经整理出来。",
                  "summary": "前两章先做线索建立和追兵逼近。",
                  "blueprint": "## 第 1 章《雨夜靠港》\n建立钥匙线索。\n\n## 第 2 章《白石会馆》\n扩大追索范围。",
                  "chapters": [
                    {"chapter_id": "chapter-001", "title": "雨夜靠港", "goal": "建立钥匙线索", "hook": "追兵露头"},
                    {"chapter_id": "chapter-002", "title": "白石会馆", "goal": "扩大追索范围", "hook": "身份暴露"},
                  ],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_stream(
          blueprint_stream(
            self.settings,
            BlueprintGenerateRequest(project_id=self.project.id, instruction="先把前两章理顺。"),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["chapters"][0]["chapter_id"], "chapter-001")
    self.assertIn("白石会馆", result_event[1]["blueprint"])

  def test_blueprint_stream_includes_recent_dream_summary(self) -> None:
    with patch(
      "novel_backend.services.project_dream_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "这轮做梦一直在提醒：铜钥匙、失踪航线和身世三条线必须继续绑在一起。",
                  "themes": ["铜钥匙", "失踪航线", "身世"],
                  "insights": ["主线的吸引力来自钥匙和身世同时推进。"],
                  "open_questions": ["主角什么时候第一次意识到钥匙和家族有关？"],
                  "memory_candidates": [],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      run_project_dream(self.settings, self.project.id, ProjectDreamRunRequest())

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "章节规划已经整理出来。",
                  "summary": "前两章先做线索建立和追兵逼近。",
                  "blueprint": "## 第 1 章《雨夜靠港》\n建立钥匙线索。",
                  "chapters": [
                    {"chapter_id": "chapter-001", "title": "雨夜靠港", "goal": "建立钥匙线索", "hook": "追兵露头"},
                  ],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ) as mocked_request:
      asyncio.run(
        collect_stream(
          blueprint_stream(
            self.settings,
            BlueprintGenerateRequest(project_id=self.project.id, instruction="继续整理前两章蓝图。"),
          )
        )
      )

    sent_prompt = "\n\n".join(
      str(item.get("content") or "")
      for item in mocked_request.call_args.args[2]["messages"]
    )
    self.assertIn("最近梦境线索：这轮做梦一直在提醒：铜钥匙、失踪航线和身世三条线必须继续绑在一起。", sent_prompt)

  def test_chapter_humanize_stream_returns_quality_report(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(
        content=(
          "# 第一章 雨夜靠港\n"
          "此外，林追在旧码头仓库找到一把铜钥匙，这不仅仅是一条线索，更是他命运转折的重要一步。"
          "总的来说，这意味着故事真正开始了。\n"
        )
      ),
    )

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "这章的模板腔已经压下去了。",
                  "summary": "情节不动，只把宣告句和总结句换成了动作和细节。",
                  "revised": (
                    "# 第一章 雨夜靠港\n"
                    "林追在旧码头仓库找到一把铜钥匙。雨顺着屋檐往下滴，他把钥匙攥紧，没有立刻出门。\n"
                  ),
                  "changes": [
                    "删掉了总结句",
                    "把抽象判断改成动作细节",
                    "压短了开头的说明腔",
                  ],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ) as mocked_request:
      events = asyncio.run(
        collect_stream(
          chapter_rewrite_stream(
            self.settings,
            ChapterRewriteRequest(
              project_id=self.project.id,
              chapter_id="chapter-001",
              instruction="保留冷硬气质，不要写成散文。",
            ),
            "humanize",
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    quality_report = result_event[1]["quality_report"]
    self.assertGreater(quality_report["after_score"], quality_report["before_score"])
    self.assertGreaterEqual(quality_report["delta"], 20)
    self.assertIn("本地评分", quality_report["summary"])

    sent_prompt = "\n\n".join(
      str(item.get("content") or "")
      for item in mocked_request.call_args.args[2]["messages"]
    )
    self.assertIn("参考内置中文去痕规则", sent_prompt)
    self.assertIn("优先处理这些问题", sent_prompt)

  def test_chapter_humanize_stream_rejects_summary_like_revision(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(
        content="# 第一章 雨夜靠港\n"
        + (
          "林追沿着码头往前走，雨水顺着仓库铁皮滴下来。他没有立刻进门，只把铜钥匙握在掌心。\n"
          * 40
        ),
      ),
    )

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "已处理。",
                  "summary": "把章节缩成摘要。",
                  "revised": "# 第一章 雨夜靠港\n林追到了仓库，拿着钥匙继续调查。",
                  "changes": ["删减冗余信息"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_stream(
          chapter_rewrite_stream(
            self.settings,
            ChapterRewriteRequest(
              project_id=self.project.id,
              chapter_id="chapter-001",
            ),
            "humanize",
          )
        )
      )

    error_event = next(item for item in events if item[0] == "error")
    done_event = next(item for item in events if item[0] == "done")
    self.assertIn("明显短于原文", error_event[1]["message"])
    self.assertEqual(done_event[1]["status"], "failed")

  def test_batch_generate_stream_writes_chapters(self) -> None:
    save_style(
      self.settings,
      "冷雾叙事",
      StyleSaveRequest(
        instruction="句子偏短，动作先行。",
        analysis="短句推进。",
        narrative_for_chapter="章末留半步悬念。",
        source_sample="雾压下来时，林追没有停。钥匙发凉，脚步声已经追近。",
      ),
    )
    review_responses = [
      {
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "第 1 章核验通过。",
                  "consistency": {"summary": "一致性在线。", "strengths": ["人物线清楚"], "issues": [], "suggestions": []},
                  "structure": {"summary": "节奏顺。", "strengths": ["结尾有钩子"], "issues": [], "suggestions": []},
                  "plot": {"summary": "主线有推进。", "strengths": ["钥匙出场"], "issues": [], "suggestions": []},
                  "suspense": {"summary": "悬念已挂上。", "strengths": ["探照灯逼近"], "issues": [], "suggestions": []},
                  "style": {"summary": "文风贴合。", "strengths": ["短句推进"], "issues": [], "suggestions": []},
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
      {
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "第 2 章核验通过。",
                  "consistency": {"summary": "一致性在线。", "strengths": ["人物线延续"], "issues": [], "suggestions": []},
                  "structure": {"summary": "结构完整。", "strengths": ["会馆试探成立"], "issues": [], "suggestions": []},
                  "plot": {"summary": "剧情推进有效。", "strengths": ["旧船队联系人出场"], "issues": [], "suggestions": []},
                  "suspense": {"summary": "压力感还在。", "strengths": ["身份压力加重"], "issues": [], "suggestions": []},
                  "style": {"summary": "文风贴合。", "strengths": ["会馆段落保持短句"], "issues": [], "suggestions": []},
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ]

    generated_results = [
      ChapterGenerateResult(
        task_id="batch-1",
        headline="第 1 章初稿",
        summary="写出钥匙出场和危机信号。",
        content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙，远处有人点亮探照灯。\n",
        next_action="下一章让追兵靠近。",
      ),
      ChapterGenerateResult(
        task_id="batch-2",
        headline="第 2 章初稿",
        summary="写出会馆试探和身份压力。",
        content="# 第二章 白石会馆\n林追带着钥匙去白石会馆试探旧船队留下的联系人。\n",
        next_action="下一章让对立方出手。",
      ),
    ]

    with patch("novel_backend.services.studio_service._generate_chapter", side_effect=generated_results), patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=review_responses,
    ):
      events = asyncio.run(
        collect_stream(
          batch_generate_stream(
            self.settings,
            BatchGenerateRequest(
              project_id=self.project.id,
              start_chapter=1,
              end_chapter=2,
              instruction="连着生成前两章。",
              style_name="冷雾叙事",
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(len(result_event[1]["generated"]), 2)
    self.assertIn("核验", result_event[1]["generated"][0]["status"])
    self.assertGreater(result_event[1]["generated"][0]["review_score"], 0)
    self.assertEqual(result_event[1]["generated"][1]["review_status"], "good")

    detail = get_project_detail(self.settings, self.project.id)
    chapter_2 = next(item for item in detail.chapters if item.id == "chapter-002")
    review_2 = next(item for item in detail.story_overview.chapter_reviews if item.chapter_id == "chapter-002")
    self.assertTrue(chapter_2.exists)
    self.assertIn("白石会馆", chapter_2.content)
    self.assertEqual(review_2.style_name, "冷雾叙事")

  def test_batch_generate_stream_resumes_completed_task_without_regenerating(self) -> None:
    generated_results = [
      ChapterGenerateResult(
        task_id="batch-1",
        headline="第 1 章初稿",
        summary="写出钥匙出场。",
        content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
        next_action="下一章让追兵靠近。",
      ),
      ChapterGenerateResult(
        task_id="batch-2",
        headline="第 2 章初稿",
        summary="写出会馆试探。",
        content="# 第二章 白石会馆\n林追带着钥匙去白石会馆试探旧船队联系人。\n",
        next_action="下一章让对立方出手。",
      ),
    ]

    def fake_review(_settings, _detail, chapter_id, **_kwargs):
      chapter_index = 1 if chapter_id == "chapter-001" else 2
      return ChapterReviewReport(
        chapter_id=chapter_id,
        chapter_index=chapter_index,
        chapter_title=f"第 {chapter_index} 章",
        engine="test",
        status="good",
        overall_score=91,
        summary="章节核验通过。",
        dimensions=[
          ChapterReviewDimension(
            id="consistency",
            label="一致性",
            score=91,
            status="good",
            summary="人物、事件和道具状态一致。",
          )
        ],
      )

    first_request = BatchGenerateRequest(
      project_id=self.project.id,
      start_chapter=1,
      end_chapter=2,
      instruction="连着生成前两章。",
    )
    with patch("novel_backend.services.studio_service._generate_chapter", side_effect=generated_results), patch(
      "novel_backend.services.project_service.build_chapter_review",
      side_effect=fake_review,
    ):
      first_events = asyncio.run(collect_stream(batch_generate_stream(self.settings, first_request)))

    task_id = str(first_events[0][1]["task_id"])
    self.assertTrue(first_events[0][1]["resumable"])
    self.assertEqual(first_events[-1], ("done", {"task_id": task_id, "status": "completed"}))
    state_path = self.settings.data_dir / "batch_tasks" / f"{task_id}.json"
    self.assertTrue(state_path.exists())

    with patch("novel_backend.services.studio_service._generate_chapter") as mocked_generate:
      resumed_events = asyncio.run(
        collect_stream(
          batch_generate_stream(
            self.settings,
            BatchGenerateRequest(
              project_id=self.project.id,
              start_chapter=1,
              end_chapter=2,
              instruction="连着生成前两章。",
              task_id=task_id,
              comment="人工确认前两章可用，继续查看状态。",
            ),
          )
        )
      )

    mocked_generate.assert_not_called()
    progress_messages = [str(item[1].get("message") or "") for item in resumed_events if item[0] == "progress"]
    self.assertTrue(any("第 1 章已完成，跳过" in item for item in progress_messages))
    self.assertTrue(any("第 2 章已完成，跳过" in item for item in progress_messages))
    resumed_result = next(item for item in resumed_events if item[0] == "result")
    self.assertEqual(len(resumed_result[1]["generated"]), 2)
    self.assertEqual(resumed_events[-1], ("done", {"task_id": task_id, "status": "completed"}))

  def test_batch_generate_stream_auto_repairs_low_review_score(self) -> None:
    risk_review = ChapterReviewReport(
      chapter_id="chapter-001",
      chapter_index=1,
      chapter_title="第一章 雨夜靠港",
      engine="test",
      status="risk",
      overall_score=54,
      summary="章末悬念偏弱。",
      dimensions=[
        ChapterReviewDimension(
          id="suspense",
          label="悬念与钩子",
          score=48,
          status="risk",
          summary="结尾没有留下新的不安。",
          issues=[
            ChapterReviewIssue(level="warning", title="章末悬念偏弱", detail="最后一句没有形成新问题。"),
          ],
        )
      ],
    )
    good_review = ChapterReviewReport(
      chapter_id="chapter-001",
      chapter_index=1,
      chapter_title="第一章 雨夜靠港",
      engine="test",
      status="good",
      overall_score=90,
      summary="章末悬念已经成立。",
      dimensions=[
        ChapterReviewDimension(
          id="suspense",
          label="悬念与钩子",
          score=90,
          status="good",
          summary="结尾留下新问题。",
        )
      ],
    )

    with patch(
      "novel_backend.services.studio_service._generate_chapter",
      return_value=ChapterGenerateResult(
        task_id="batch-1",
        headline="第 1 章初稿",
        summary="写出钥匙出场。",
        content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
        next_action="下一章让追兵靠近。",
      ),
    ), patch(
      "novel_backend.services.project_service.build_chapter_review",
      side_effect=[risk_review, good_review],
    ), patch(
      "novel_backend.services.chapter_auto_repair_service._invoke_model",
      return_value=json.dumps(
        {
          "summary": "补上章末异动。",
          "changes": ["让铜钥匙在结尾出现反常"],
          "revised_content": "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。门外脚步声停住时，钥匙自己转了半圈。\n",
        },
        ensure_ascii=False,
      ),
    ):
      events = asyncio.run(
        collect_stream(
          batch_generate_stream(
            self.settings,
            BatchGenerateRequest(
              project_id=self.project.id,
              start_chapter=1,
              end_chapter=1,
              instruction="写第一章。",
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    generated = result_event[1]["generated"][0]
    self.assertTrue(generated["review_auto_repair_attempted"])
    self.assertTrue(generated["review_auto_repair_applied"])
    self.assertEqual(generated["review_score"], 90)
    self.assertIn("已自动修订", generated["status"])
    self.assertIn("钥匙自己转了半圈", generated["preview"])

    detail = get_project_detail(self.settings, self.project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    self.assertIn("钥匙自己转了半圈", chapter.content)

  def test_continue_project_stream_updates_targets_and_documents(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "后续规划已经展开。",
                  "summary": "新增两章承接旧船队真相。",
                  "plot_structure": "中段加入旧船队口供，后段引出最终航线。",
                  "world_building": "隐秘航线只会在潮位和灯塔信号同时满足时开启。",
                  "character_design": "主角与旧船队后人形成临时联盟。",
                  "character_state": "林追开始怀疑自己的家族并非受害者。",
                  "blueprint": "## 第 4 章《旧船队口供》\n拿到证词。\n\n## 第 5 章《潮位窗口》\n逼近最终真相。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_stream(
          continue_project_stream(
            self.settings,
            ContinueProjectRequest(project_id=self.project.id, new_chapters=2, instruction="继续扩到五章。"),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["target_chapters"], 5)

    detail = get_project_detail(self.settings, self.project.id)
    self.assertEqual(detail.target_chapters, 5)
    blueprint = next(item for item in detail.story_overview.documents if item.key == "blueprint")
    self.assertIn("潮位窗口", blueprint.content)

  def test_chapter_generate_stream_uses_standard_single_candidate_pipeline(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.6-plus",
      ),
    )
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n"),
    )

    def fake_pipeline(_settings, **kwargs):
      self.assertEqual(kwargs["candidate_count"], 1)
      self.assertEqual(kwargs["task_name_prefix"], "chapter_generate")
      self.assertTrue(kwargs["complete_chapter"])
      return {
        "headline": "章节初稿已修订",
        "summary": "已按标准模式生成候选，并完成审校。",
        "content": (
          "# 第一章 雨夜靠港\n"
          "林追在旧码头仓库找到一把铜钥匙。\n"
          "仓库门缝里又刮进一线白光，林追拇指按在铜钥匙的齿上，像是先拿住了自己。"
          "那股看不见的人气已经贴到了门边。\n"
        ),
        "next_action": "下一段让林追做选择。",
      }

    with patch("novel_backend.services.studio_service._run_continuation_pipeline", side_effect=fake_pipeline):
      events = asyncio.run(
        collect_stream(
          chapter_generate_stream(
            self.settings,
            ChapterGenerateRequest(
              project_id=self.project.id,
              chapter_id="chapter-001",
              instruction="让追兵先在门外逼近，不要马上撞进来。",
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("那股看不见的人气已经贴到了门边", result_event[1]["content"])
    self.assertIn("标准模式生成候选", result_event[1]["summary"])

  def test_chapter_generate_prompt_preview_returns_editable_prompt_without_model_call(self) -> None:
    update_chapter_content(
      self.settings,
      self.project.id,
      "chapter-001",
      ChapterUpdateRequest(content="# 第一章 雨夜靠港\n林追握住铜钥匙，听见门外脚步停住。\n"),
    )

    with patch("novel_backend.services.generation_service._request_chat_completion") as request_mock:
      preview = chapter_generate_prompt_preview(
        self.settings,
        ChapterGenerateRequest(
          project_id=self.project.id,
          chapter_id="chapter-001",
          instruction="让追兵先在门外逼近，不要马上撞进来。",
          characters_involved="林追",
          key_items="铜钥匙",
        ),
      )

    request_mock.assert_not_called()
    self.assertEqual(preview.chapter_id, "chapter-001")
    self.assertIn("连续性证据包", preview.editable_prompt)
    self.assertIn("让追兵先在门外逼近", preview.editable_prompt)
    self.assertIn("[system]", preview.prompt_text)
    self.assertEqual(preview.messages[-1].role, "user")

  def test_chapter_generate_stream_respects_explicit_target_words(self) -> None:
    def fake_pipeline(_settings, **kwargs):
      self.assertEqual(kwargs["target_words"], 900)
      self.assertFalse(kwargs["prefer_project_budget"])
      self.assertFalse(kwargs["complete_chapter"])
      self.assertEqual(kwargs["prompt_override"], "用户改写后的完整提示词")
      return {
        "headline": "短章节测试",
        "summary": "已按调用方目标长度生成。",
        "content": "# 第一章 雨夜靠港\n林追按住铜钥匙，听见门外的脚步声停在雨里。\n",
        "next_action": "继续推进。",
      }

    with patch("novel_backend.services.studio_service._run_continuation_pipeline", side_effect=fake_pipeline):
      events = asyncio.run(
        collect_stream(
          chapter_generate_stream(
            self.settings,
            ChapterGenerateRequest(
              project_id=self.project.id,
              chapter_id="chapter-001",
              instruction="生成一段短测试正文。",
              target_words=900,
              prompt_override="用户改写后的完整提示词",
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["headline"], "短章节测试")

  def test_style_analyze_stream_and_related_storage(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "instruction": "句子偏短，动作先行，心理判断压后，结尾留半步悬念。",
                  "analysis": "语句短促，镜头切换快，信息释放偏克制。",
                  "narrative_for_architecture": "架构阶段突出冲突链条和悬念结构。",
                  "narrative_for_blueprint": "蓝图阶段强调每章钩子和信息差。",
                  "narrative_for_chapter": "正文阶段优先动作和对白，再补心理。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_stream(
          style_analyze_stream(
            self.settings,
            StyleAnalyzeRequest(
              style_name="海港悬疑",
              sample_text="他抬头看了一眼灯塔，风从海面压过来。钥匙在掌心发凉，他没有停。",
            ),
          )
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("动作先行", result_event[1]["instruction"])

    save_style(
      self.settings,
      "海港悬疑",
      StyleSaveRequest(
        instruction=result_event[1]["instruction"],
        analysis=result_event[1]["analysis"],
        narrative_for_architecture=result_event[1]["narrative_for_architecture"],
        narrative_for_blueprint=result_event[1]["narrative_for_blueprint"],
        narrative_for_chapter=result_event[1]["narrative_for_chapter"],
      ),
    )
    saved = get_style(self.settings, "海港悬疑")
    self.assertIn("动作先行", saved.instruction)

  def test_style_dna_calibration_and_rollback_flow(self) -> None:
    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "instruction": "句子短，镜头贴人，动作先到，解释后置。",
                  "analysis": "叙述紧跟角色知觉，信息分次释放。",
                  "dna_analysis": "近距离限知视角，对白偏短，动作和心理大约七三开。",
                  "narrative_for_architecture": "架构阶段先排冲突链和揭示顺序。",
                  "narrative_for_blueprint": "蓝图阶段每章只保留一个关键信息差。",
                  "narrative_for_chapter": "正文阶段先动作对白，再补心理。",
                  "calibration_notes": "后续要继续压缩解释句，并控制结尾停顿。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      analyze_events = asyncio.run(
        collect_stream(
          style_analyze_dna_stream(
            self.settings,
            StyleDNAAnalyzeRequest(
              style_name="海港压迫感",
              sample_text="林追没有停。他听见潮声往堤岸上顶，像有人在黑里敲门。钥匙在手里一沉，他先看灯塔，再看巷口。",
              user_preference="镜头更贴人，少解释。",
            ),
          )
        )
      )

    analyze_result = next(item for item in analyze_events if item[0] == "result")[1]
    self.assertIn("近距离限知视角", analyze_result["dna_analysis"])

    save_style(
      self.settings,
      "海港压迫感",
      StyleSaveRequest(
        instruction=analyze_result["instruction"],
        analysis=analyze_result["analysis"],
        dna_analysis=analyze_result["dna_analysis"],
        narrative_for_architecture=analyze_result["narrative_for_architecture"],
        narrative_for_blueprint=analyze_result["narrative_for_blueprint"],
        narrative_for_chapter=analyze_result["narrative_for_chapter"],
        source_sample="林追没有停。他听见潮声往堤岸上顶，像有人在黑里敲门。",
        calibration_reference="镜头更贴人，少解释。",
        calibration_notes=analyze_result["calibration_notes"],
      ),
    )

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=[
        {
          "choices": [
            {
              "message": {
                "content": json.dumps(
                  {
                    "instruction": "句子再短一点，镜头贴着主角知觉走，解释句只留必要部分。",
                    "analysis": "动作和知觉先行，解释继续后置。",
                    "dna_analysis": "近距离限知视角更稳定，对白偏短，动作和心理大约八二开。",
                    "narrative_for_architecture": "架构阶段只保留必要设定，优先因果链。",
                    "narrative_for_blueprint": "蓝图阶段每章只给一个钩子和一个信息差。",
                    "narrative_for_chapter": "正文阶段动作、对白、心理按 5:3:2 排布。",
                    "calibration_notes": "还可以继续压缩总结句。",
                  },
                  ensure_ascii=False,
                )
              }
            }
          ]
        },
        {
          "choices": [
            {
              "message": {
                "content": json.dumps(
                  {
                    "instruction": "保留现有文风指令，只微调叙事说明。",
                    "analysis": "主体风格不变，叙事要求更具体。",
                    "dna_analysis": "近距离限知视角，对白偏短，动作和心理八二开。",
                    "narrative_for_architecture": "架构阶段先列冲突链，再列信息释放次序。",
                    "narrative_for_blueprint": "蓝图阶段每章限定一个核心动作和一个悬念。",
                    "narrative_for_chapter": "正文阶段用短段推进，段尾留半步悬念。",
                    "calibration_notes": "叙事约束已经收紧。",
                  },
                  ensure_ascii=False,
                )
              }
            }
          ]
        },
      ],
    ):
      calibrate_events = asyncio.run(
        collect_stream(
          style_calibrate_stream(
            self.settings,
            StyleCalibrateRequest(
              style_name="海港压迫感",
              max_iterations=1,
              user_preference="进一步压短句子。",
            ),
          )
        )
      )
      narrative_events = asyncio.run(
        collect_stream(
          style_calibrate_narrative_stream(
            self.settings,
            StyleCalibrateRequest(
              style_name="海港压迫感",
              max_iterations=1,
              user_preference="三段式要求再具体一点。",
            ),
          )
        )
      )

    calibrate_result = next(item for item in calibrate_events if item[0] == "result")[1]
    narrative_result = next(item for item in narrative_events if item[0] == "result")[1]
    self.assertIn("镜头贴着主角知觉走", calibrate_result["instruction"])
    self.assertIn("架构阶段先列冲突链", narrative_result["narrative_for_architecture"])

    saved = get_style(self.settings, "海港压迫感")
    self.assertTrue(saved.has_calibration_snapshot)
    self.assertIsNotNone(saved.last_calibrated_at)
    self.assertIn("段尾留半步悬念", saved.narrative_for_chapter)

    rolled_back = rollback_style_calibration(self.settings, "海港压迫感")
    self.assertIn("句子短，镜头贴人", rolled_back.instruction)
    self.assertIn("近距离限知视角", rolled_back.dna_analysis)
    self.assertEqual(rolled_back.calibration_notes, "后续要继续压缩解释句，并控制结尾停顿。")

  def test_prompt_preset_file_service_and_style_references(self) -> None:
    preset = create_prompt_preset(
      self.settings,
      PromptPresetCreateRequest(name="测试方案", description="只看冲突"),
    )
    updated = update_prompt_preset(
      self.settings,
      preset.name,
      PromptPresetUpdateRequest(
        description="先看冲突再看情绪",
        prompts={"chapter": "正文先推冲突"},
      ),
    )
    activate_prompt_preset(self.settings, updated.name)
    self.assertEqual(get_active_prompt_instruction(self.settings, "chapter"), "正文先推冲突")

    save_style(
      self.settings,
      "港口压迫感",
      StyleSaveRequest(
        instruction="多用风、潮位和灯光压迫场面。",
        analysis="气氛偏冷硬。",
        narrative_for_chapter="段尾留压迫感。",
      ),
    )
    detail = import_style_references(
      self.settings,
      "港口压迫感",
      StyleReferenceImportRequest(
        items=[StyleReferenceItem(title="灯塔片段", content="灯塔的白光一阵一阵压下来。")]
      ),
    )
    self.assertEqual(detail.reference_materials[0].title, "灯塔片段")

    files = list_project_files(self.settings, self.project.id)
    self.assertTrue(any(item.path == "core_seed.txt" for item in files))
    self.assertFalse(any(item.path.startswith(".novel-history/") for item in files))
    file_content = read_project_file(self.settings, self.project.id, "core_seed.txt")
    self.assertIn("铜钥匙", file_content["content"])
    updated_file = write_project_file(self.settings, self.project.id, "world_building.txt", "涨潮时航线会显影。")
    self.assertEqual(updated_file["path"], "world_building.txt")
    self.assertIn("显影", read_project_file(self.settings, self.project.id, "world_building.txt")["content"])

  def test_style_reference_search_supports_semantic_hits_and_prompt_injection(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          api_key="test-key",
          base_url="https://example.com/v1",
          model_name="demo-model",
        ),
        embedding=EmbeddingConfig(
          api_key="embed-key",
          base_url="https://example.com/v1",
          model_name="text-embedding-3-small",
          retrieval_k=6,
          batch_size=4,
        ),
      ),
    )

    save_style(
      self.settings,
      "港口压迫感",
      StyleSaveRequest(
        instruction="句子偏短，镜头贴人。",
        analysis="海风、灯塔和潮位形成压迫感。",
        narrative_for_chapter="动作和对白先走，心理后置。",
      ),
    )
    import_style_references(
      self.settings,
      "港口压迫感",
      StyleReferenceImportRequest(
        items=[
          StyleReferenceItem(title="灯塔片段", content="灯塔的白光一阵一阵压下来，像有人隔着海面审讯。"),
          StyleReferenceItem(title="潮位片段", content="潮位往上顶的时候，堤岸像一条正在醒来的旧伤。"),
        ]
      ),
    )

    def fake_embed_texts(_settings, texts, *, task_name="embedding"):
      vectors: list[list[float]] = []
      for item in texts:
        normalized = str(item)
        if "审讯" in normalized or "白光" in normalized or "灯塔" in normalized:
          vectors.append([1.0, 0.0, 0.0])
        elif "潮位" in normalized:
          vectors.append([0.0, 1.0, 0.0])
        else:
          vectors.append([0.0, 0.0, 1.0])
      return vectors

    with patch("novel_backend.services.style_service.embed_texts", side_effect=fake_embed_texts):
      hits = search_style_references(self.settings, "港口压迫感", "灯塔白光像审讯")
      detail = get_style(self.settings, "港口压迫感")
      prompt_text = build_style_reference_text(
        self.settings,
        "港口压迫感",
        "chapter",
        query="灯塔白光像审讯",
      )

    self.assertTrue(hits)
    self.assertEqual(hits[0].section, "灯塔片段")
    self.assertIn(hits[0].match_type, {"semantic", "hybrid"})
    self.assertIn("高频词场", detail.reference_distillate)
    self.assertIn("灯塔", detail.reference_distillate)
    self.assertIn("参考写法", prompt_text)
    self.assertIn("参考库蒸馏", prompt_text)
    self.assertIn("灯塔片段", prompt_text)


if __name__ == "__main__":
  unittest.main()
