from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  ArchitectureRequest,
  ProjectDreamRunRequest,
  ArchitectureStepRequest,
  ArchitectureWorkspace,
  ChapterWorkflowRequest,
  ChapterWorkflowResult,
  ChapterWorkflowScene,
  CreateProjectRequest,
  KnowledgeImportItem,
  KnowledgeImportRequest,
  ModelConfig,
  ProjectMemoryEntry,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
)
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.continuity_guard_service import build_continuity_guard_context
from novel_backend.services.generation_service import (
  _continuation_segment_targets,
  _generate_continuation_candidates,
  _judge_continuation,
  _run_continuation_pipeline,
  architecture_step_stream,
  architecture_stream,
  chapter_workflow_stream,
)
from novel_backend.services.project_service import create_project, get_project_detail, import_project_knowledge, run_project_dream, update_project_memory


def decode_sse_event(chunk: str) -> tuple[str, object]:
  event_name = "message"
  data = ""

  for raw_line in chunk.strip().splitlines():
    if raw_line.startswith("event:"):
      event_name = raw_line.split(":", 1)[1].strip()
    elif raw_line.startswith("data:"):
      data = raw_line.split(":", 1)[1].strip()

  return event_name, json.loads(data)


async def collect_events(settings: Settings, payload: ArchitectureRequest) -> list[tuple[str, object]]:
  events: list[tuple[str, object]] = []
  async for chunk in architecture_stream(settings, payload):
    events.append(decode_sse_event(chunk))
  return events


async def collect_workflow_events(settings: Settings, payload: ChapterWorkflowRequest) -> list[tuple[str, object]]:
  events: list[tuple[str, object]] = []
  async for chunk in chapter_workflow_stream(settings, payload):
    events.append(decode_sse_event(chunk))
  return events


async def collect_architecture_step_events(settings: Settings, payload: ArchitectureStepRequest) -> list[tuple[str, object]]:
  events: list[tuple[str, object]] = []
  async for chunk in architecture_step_stream(settings, payload):
    events.append(decode_sse_event(chunk))
  return events


class GenerationServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self._embedding_signature_patcher = patch(
      "novel_backend.services.project_service.embedding_config_signature",
      return_value="generation-tests:not-ready",
    )
    self._embedding_signature_patcher.start()
    self.addCleanup(self._embedding_signature_patcher.stop)
    self._embedding_request_patcher = patch(
      "novel_backend.services.project_service.embed_texts",
      side_effect=RuntimeError("skip embedding in generation tests"),
    )
    self._embedding_request_patcher.start()
    self.addCleanup(self._embedding_request_patcher.stop)
    self._rerank_patcher = patch(
      "novel_backend.services.project_service.rerank_documents",
      return_value=[],
    )
    self._rerank_patcher.start()
    self.addCleanup(self._rerank_patcher.stop)
    self.payload = ArchitectureRequest(
      title="测试小说",
      premise="主角在海港城市追查一段被隐藏的家族航线，同时被旧秩序和黑市交易追赶。",
      genre="悬疑幻想",
      chapter_count=24,
      target_words=280000,
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_architecture_stream_returns_model_result(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
        max_tokens=2048,
        temperature=0.7,
      ),
    )

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": """
```json
{
  "core_seed": "一把失踪航线钥匙牵出主角的身世和港口权力真相。",
  "character_design": "主角负责追查真相，对立方把守港口秩序，辅助角色分别连接黑市、海关和旧船队。",
  "world_building": "表层是现代港口贸易，底层是只在潮汐窗口开启的隐秘航线系统。",
  "plot_structure": "前段引入失踪案与钥匙，中段揭开旧船队和家族秘密，后段完成身份回收和秩序改写。"
}
```""".strip()
            }
          }
        ]
      },
    ):
      events = asyncio.run(collect_events(self.settings, self.payload))

    self.assertEqual(events[0][0], "started")
    self.assertEqual(events[-1], ("done", {"task_id": events[0][1]["task_id"], "status": "completed"}))

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["core_seed"], "一把失踪航线钥匙牵出主角的身世和港口权力真相。")
    self.assertIn("港口秩序", result_event[1]["character_design"])

  def test_architecture_stream_flattens_structured_json_sections(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
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
                  "core_seed": {"title": "铜钥匙", "summary": "一把铜钥匙牵出旧港口秩序。"},
                  "character_design": {
                    "characters": [
                      {"name": "林追", "role": "追查真相"},
                      {"name": "苏青", "role": "掌握旧账本"},
                    ]
                  },
                  "world_building": {"rules": ["潮位窗口开启隐秘航线", "港务会封锁证据"]},
                  "plot_structure": {"acts": [{"title": "追查", "goal": "找到账本"}]},
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(collect_events(self.settings, self.payload))

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("铜钥匙", result_event[1]["core_seed"])
    self.assertIn("林追", result_event[1]["character_design"])
    self.assertIn("潮位窗口", result_event[1]["world_building"])
    self.assertIn("找到账本", result_event[1]["plot_structure"])

  def test_architecture_stream_reports_missing_api_key(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )

    events = asyncio.run(collect_events(self.settings, self.payload))

    error_event = next(item for item in events if item[0] == "error")
    self.assertIn("API Key", error_event[1]["message"])
    self.assertEqual(events[-1][1]["status"], "failed")

  def test_chapter_workflow_stream_returns_structured_result(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="章节工作流",
        genre="悬疑",
        target_chapters=3,
        target_words=60000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "core_seed.txt").write_text("失踪航线钥匙引出主角身世之谜。", encoding="utf-8")
    (project_dir / "chapters" / "001.md").write_text(
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
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
                  "headline": "这一章最该先把冲突抬起来。",
                  "summary": "先让主角因为钥匙暴露行踪，再把追查者拉进场。",
                  "checklist": ["开场十行内出现异常", "中段必须有人逼近", "结尾留下更大的问题"],
                  "scenes": [
                    {
                      "title": "雨夜取钥匙",
                      "goal": "主角拿到关键线索",
                      "conflict": "现场有人提前来过",
                      "turn": "钥匙引出追兵",
                    }
                  ],
                  "draft": "",
                  "next_action": "先按这套场景重排章节。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_workflow_events(
          self.settings,
          ChapterWorkflowRequest(
            project_id=project.id,
            chapter_id="chapter-001",
            mode="scenes",
            instruction="请把这一章拆场景。",
            target_words=1500,
          ),
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["headline"], "这一章最该先把冲突抬起来。")
    self.assertEqual(result_event[1]["scenes"][0]["title"], "雨夜取钥匙")
    self.assertEqual(events[-1][1]["status"], "completed")

  def test_chapter_workflow_prompt_carries_reference_blocks_for_source_continuation(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="原著承接工作流",
        genre="文学续写",
        target_chapters=3,
        target_words=60000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "chapters" / "001.md").write_text(
      "# 第一章 失眠夜\n方鸿渐在寓所里听见楼下脚步，心里还挂着白天那场争吵。\n",
      encoding="utf-8",
    )
    import_project_knowledge(
      self.settings,
      project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="围城原文节选",
            content=(
              "方鸿渐回到寓所，孙柔嘉冷笑着问他在外面跟谁闲逛。"
              "赵辛楣后来来信，只说方鸿渐的婚姻像穿错的鞋。"
            ),
          )
        ]
      ),
    )

    captured_payload: dict[str, object] = {}

    def fake_request(_endpoint, _api_key, payload):
      captured_payload.update(payload)
      return {
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "先稳住承接点。",
                  "summary": "这一章要先接住人物关系，再推进新一轮场景。",
                  "checklist": ["先承接原文结尾"],
                  "scenes": [],
                  "draft": "",
                  "next_action": "先按承接点重排。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      }

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=fake_request,
    ):
      asyncio.run(
        collect_workflow_events(
          self.settings,
          ChapterWorkflowRequest(
            project_id=project.id,
            chapter_id="chapter-001",
            mode="diagnose",
            instruction="接着原文看这一章该怎么续。",
            target_words=1200,
          ),
        )
      )

    user_messages = captured_payload.get("messages")
    self.assertIsInstance(user_messages, list)
    prompt_text = str(user_messages[-1]["content"])
    self.assertIn("参考人物：", prompt_text)
    self.assertIn("方鸿渐", prompt_text)
    self.assertIn("孙柔嘉", prompt_text)
    self.assertIn("参考事件：", prompt_text)
    self.assertIn("围城原文节选", prompt_text)
    self.assertIn("原作承接提醒：", prompt_text)

  def test_chapter_workflow_draft_uses_single_partial_continuation(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.6-plus",
      ),
    )
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="续写流水线",
        genre="文学续写",
        target_chapters=3,
        target_words=60000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "chapters" / "001.md").write_text(
      "# 第一章 失眠夜\n方鸿渐把门掩上，楼下的脚步声还没散。\n",
      encoding="utf-8",
    )
    import_project_knowledge(
      self.settings,
      project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="围城原文节选",
            content="孙柔嘉冷笑着盯住方鸿渐，问他白天到底去了哪里。",
          )
        ]
      ),
    )

    captured_payloads: list[dict[str, object]] = []
    responses = [
      {
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "先接住孙柔嘉的怀疑，再把争吵往更难收的方向推。",
                  "must_keep": ["方鸿渐刚回寓所", "孙柔嘉对他起了疑心"],
                  "current_state": ["两人正处在争吵余波里"],
                  "voice_rules": ["对白里保留尖刻和冷嘲"],
                  "blocked_changes": ["不要改掉现有婚姻关系"],
                  "next_action": "先让孙柔嘉开口。",
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
              "content": "孙柔嘉先把声音压低了一层，问他今天白天到底跟谁在一起。方鸿渐手还按在门栓上，答得慢了一拍，屋里的气先沉了下去。\n"
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
                  "summary": "没有发现硬冲突。",
                  "passed": True,
                  "conflicts": [],
                  "rewrite_focus": [],
                  "next_action": "下一段继续把白天那件事挑明。",
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
                  "summary": "承接没有写偏。",
                  "score": 88,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段继续把眼前这场争执推深。",
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
                  "summary": "人物口气接上了，冷嘲味道还在。",
                  "score": 84,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段把孙柔嘉的话再写得更具体。",
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
                  "summary": "这一段能继续往下带，张力也够。",
                  "score": 80,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段把争吵推进到更实的人和事上。",
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
              "content": "孙柔嘉把门边那盏灯拧亮了一点，眼睛也跟着亮起来，说他今天白天若真没有见人，何必把一句话含在喉咙里不肯吐净。方鸿渐让那光照得无处躲闪，肩膀微微往后一缩。\n"
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
                  "summary": "承接仍然成立。",
                  "score": 90,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "继续把白天那件事挑明。",
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
                  "summary": "人物口气基本接住了。",
                  "score": 87,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段让孙柔嘉的话更尖一点。",
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
                  "summary": "这一版更像在逼问现场里往前走。",
                  "score": 86,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "顺着灯光把人物关系再压紧。",
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
              "content": "孙柔嘉在门里冷冷问了一句，他今天白天到底跟谁在一起。方鸿渐还按着门栓，指节白得像被门上的铁件硌出来的，答话慢了一拍。孙柔嘉便笑了，那笑意薄得像纸边，却把两个人白天没说破的人和事一下子都逼到了屋里。\n"
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
                  "summary": "承接没有写偏，现场关系也稳。",
                  "score": 94,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段把白天那个人点出来。",
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
                  "summary": "人物口气最准，冷嘲和心虚都在。",
                  "score": 92,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段让一句话把旧账扯出来。",
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
                  "summary": "这一版最适合继续往下带，结尾压力也更顺。",
                  "score": 95,
                  "passed": True,
                  "issues": [],
                  "rewrite_focus": [],
                  "next_action": "下一段继续把那个人和白天的去向挑明。",
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ]

    def fake_request(_endpoint, _api_key, payload):
      captured_payloads.append(payload)
      return responses[len(captured_payloads) - 1]

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      side_effect=fake_request,
    ):
      events = asyncio.run(
        collect_workflow_events(
          self.settings,
          ChapterWorkflowRequest(
            project_id=project.id,
            chapter_id="chapter-001",
            mode="draft",
            instruction="接着这场争吵往下写。",
            target_words=1200,
          ),
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    self.assertIn("孙柔嘉先把声音压低", result_event[1]["draft"])
    self.assertEqual(len(captured_payloads), 3)
    partial_messages = captured_payloads[1]["messages"]
    self.assertEqual(partial_messages[-1]["role"], "assistant")
    self.assertTrue(partial_messages[-1]["partial"])
    self.assertIn("# 第一章 失眠夜", partial_messages[-1]["content"])
    self.assertTrue(captured_payloads[0]["enable_thinking"])
    self.assertFalse(captured_payloads[1]["enable_thinking"])
    self.assertTrue(captured_payloads[2]["enable_thinking"])
    self.assertEqual(captured_payloads[1]["max_tokens"], 11000)
    self.assertEqual(events[-1][1]["status"], "completed")

  def test_continuation_segment_targets_are_balanced(self) -> None:
    self.assertEqual(_continuation_segment_targets(5_500), [5_500])
    self.assertEqual(_continuation_segment_targets(5_501), [2_751, 2_750])
    self.assertEqual(_continuation_segment_targets(6_000), [3_000, 3_000])
    self.assertEqual(_continuation_segment_targets(15_000), [5_000, 5_000, 5_000])
    self.assertEqual(_continuation_segment_targets(30_000), [5_000, 5_000, 5_000, 5_000, 5_000, 5_000])

  def test_run_continuation_pipeline_splits_oversized_target(self) -> None:
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="长章分段",
        genre="历史幻想",
        target_chapters=4,
        target_words=60000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "chapters" / "001.md").write_text(
      "# 第一章 葛陂以北\n石季龙在战场边缘听见黑石里的低语。\n",
      encoding="utf-8",
    )
    detail = get_project_detail(self.settings, project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    fake_scene_result = ChapterWorkflowResult(
      task_id="scene-task",
      mode="draft",
      headline="场景计划",
      summary="按战后荒原、归营、营中异动推进。",
      scenes=[
        ChapterWorkflowScene(
          title="战场余响",
          goal="承接黑石低语",
          conflict="兵魂煞气继续侵蚀",
          turn="营地传来粮道消息",
        )
      ],
    )
    fake_plan = {
      "bundle": SimpleNamespace(context_text="当前章节：石季龙刚吸收兵魂煞气。"),
      "chapter": chapter,
      "evidence_text": "证据：石勒已目睹异象。",
      "evidence_hits": [],
      "canon": {
        "summary": "必须承接葛陂战后现场和石季龙身体代价。",
        "must_keep": ["石季龙已吸收兵魂煞气"],
        "current_state": ["二人正准备归营"],
        "voice_rules": ["冷峻短句"],
        "blocked_changes": ["不要解释铜雀伏笔"],
        "next_action": "继续写营地压力。",
      },
      "scene_result": fake_scene_result,
    }
    partial_calls: list[dict[str, object]] = []
    judge_calls: list[str] = []

    def fake_partial(_settings, _messages, **kwargs):
      partial_calls.append(kwargs)
      return f"第 {len(partial_calls)} 小节正文继续推进。\n" + ("推进。" * 1700)

    def fake_judge(_settings, **kwargs):
      judge_calls.append(str(kwargs["content"]))
      return {
        "summary": "承接可用。",
        "score": 90,
        "passed": True,
        "issues": [],
        "rewrite_focus": [],
        "next_action": "继续写下一段。",
      }

    with patch(
      "novel_backend.services.generation_service._generate_continuation_plan",
      return_value=fake_plan,
    ) as plan_mock, patch(
      "novel_backend.services.generation_service._invoke_partial_model",
      side_effect=fake_partial,
    ), patch(
      "novel_backend.services.generation_service._judge_continuation",
      side_effect=fake_judge,
    ):
      result = _run_continuation_pipeline(
        self.settings,
        project_id=project.id,
        chapter_id="chapter-001",
        instruction="按目标字数写完整章一万五千字。",
        target_words=1_800,
        support_text="",
        candidate_count=1,
      )

    self.assertEqual(plan_mock.call_args.kwargs["target_words"], 15000)
    self.assertEqual(result["segment_count"], 3)
    self.assertEqual(result["segment_targets"], [5000, 5000, 5000])
    self.assertEqual(len(partial_calls), 3)
    self.assertEqual(len(judge_calls), 3)
    self.assertIn("第 1 小节正文继续推进", result["content"])
    self.assertIn("第 2 小节正文继续推进", result["content"])
    self.assertIn("第 3 小节正文继续推进", result["content"])
    self.assertIn("先规划 3 个小节", result["summary"])
    self.assertEqual(
      [item["task_name"] for item in partial_calls],
      [
        "chapter_generate:segment-01:partial:dialogue-pressure",
        "chapter_generate:segment-02:partial:dialogue-pressure",
        "chapter_generate:segment-03:partial:dialogue-pressure",
      ],
    )

  def test_segmented_continuation_adds_sections_until_length_target(self) -> None:
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="长章追加小节",
        genre="历史幻想",
        target_chapters=4,
        target_words=60000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "chapters" / "001.md").write_text(
      "# 第一章 葛陂以北\n石季龙在战场边缘听见黑石里的低语。\n",
      encoding="utf-8",
    )
    detail = get_project_detail(self.settings, project.id)
    chapter = next(item for item in detail.chapters if item.id == "chapter-001")
    fake_scene_result = ChapterWorkflowResult(
      task_id="scene-task",
      mode="draft",
      headline="场景计划",
      summary="按战后荒原、归营、营中异动推进。",
      scenes=[
        ChapterWorkflowScene(
          title="战场余响",
          goal="承接黑石低语",
          conflict="兵魂煞气继续侵蚀",
          turn="营地传来粮道消息",
        )
      ],
    )
    fake_plan = {
      "bundle": SimpleNamespace(context_text="当前章节：石季龙刚吸收兵魂煞气。"),
      "chapter": chapter,
      "evidence_text": "证据：石勒已目睹异象。",
      "evidence_hits": [],
      "canon": {
        "summary": "必须承接葛陂战后现场和石季龙身体代价。",
        "must_keep": ["石季龙已吸收兵魂煞气"],
        "current_state": ["二人正准备归营"],
        "voice_rules": ["冷峻短句"],
        "blocked_changes": ["不要解释铜雀伏笔"],
        "next_action": "继续写营地压力。",
      },
      "scene_result": fake_scene_result,
    }
    partial_calls: list[dict[str, object]] = []

    def fake_partial(_settings, _messages, **kwargs):
      partial_calls.append(kwargs)
      return f"第 {len(partial_calls)} 小节正文继续推进。\n" + ("推进。" * 1000)

    def fake_judge(_settings, **_kwargs):
      return {
        "summary": "承接可用。",
        "score": 90,
        "passed": True,
        "issues": [],
        "rewrite_focus": [],
        "next_action": "继续写下一节。",
      }

    with patch(
      "novel_backend.services.generation_service._generate_continuation_plan",
      return_value=fake_plan,
    ), patch(
      "novel_backend.services.generation_service._invoke_partial_model",
      side_effect=fake_partial,
    ), patch(
      "novel_backend.services.generation_service._judge_continuation",
      side_effect=fake_judge,
    ):
      result = _run_continuation_pipeline(
        self.settings,
        project_id=project.id,
        chapter_id="chapter-001",
        instruction="按目标字数写完整章一万五千字。",
        target_words=1_800,
        support_text="",
        candidate_count=1,
      )

    self.assertGreater(result["segment_count"], result["planned_segment_count"])
    self.assertEqual(result["planned_segment_targets"], [5000, 5000, 5000])
    self.assertEqual(result["completion_status"], "complete")
    self.assertGreaterEqual(result["actual_words"], result["completion_threshold_words"])
    self.assertEqual(len(partial_calls), result["segment_count"])
    self.assertIn("实际生成", result["summary"])

  def test_continuation_judge_runs_dimension_reviews_in_order(self) -> None:
    scene_result = ChapterWorkflowResult(
      task_id="scene-task",
      mode="draft",
      headline="场景计划",
      summary="先守住门外压力。",
      scenes=[
        ChapterWorkflowScene(
          title="仓库门外",
          goal="让林追判断是否离开",
          conflict="门外有人逼近",
          turn="铜钥匙发出异常声响",
        )
      ],
    )
    calls: list[str] = []

    def fake_dimension(_settings, **kwargs):
      dimension = str(kwargs["dimension"])
      calls.append(dimension)
      scores = {"承接事实": 100, "人物口气": 80, "可读性": 60}
      return {
        "dimension": dimension,
        "summary": f"{dimension}审校完成。",
        "score": scores[dimension],
        "passed": dimension != "可读性",
        "issues": [{"title": "段尾偏弱", "detail": "结尾压力不足", "severity": "warning"}] if dimension == "可读性" else [],
        "rewrite_focus": ["增强段尾压力"] if dimension == "可读性" else [],
        "next_action": "继续写门外逼近。",
      }

    with patch("novel_backend.services.generation_service._judge_continuation_dimension", side_effect=fake_dimension):
      report = _judge_continuation(
        self.settings,
        context_text="当前章节：林追握着铜钥匙。",
        evidence_text="原文证据：铜钥匙仍在林追手中。",
        canon={
          "summary": "林追刚拿到铜钥匙。",
          "must_keep": ["铜钥匙仍在林追手中"],
          "current_state": ["门外有人逼近"],
          "voice_rules": ["短句推进"],
          "blocked_changes": ["不要提前揭开钥匙用途"],
        },
        scene_result=scene_result,
        content="# 第一章 雨夜靠港\n林追握着铜钥匙，门外有人靠近。\n",
      )

    self.assertEqual(set(calls), {"承接事实", "人物口气", "可读性"})
    self.assertEqual([item["dimension"] for item in report["dimensions"]], ["承接事实", "人物口气", "可读性"])
    self.assertEqual(report["score"], 84)
    self.assertFalse(report["passed"])
    self.assertEqual(report["rewrite_focus"], ["增强段尾压力"])
    self.assertEqual(report["issues"][0]["title"], "可读性：段尾偏弱")

  def test_generate_continuation_candidates_keeps_parallel_results_ordered(self) -> None:
    scene_result = ChapterWorkflowResult(
      task_id="scene-task",
      mode="draft",
      headline="场景计划",
      summary="先守住门外压力。",
      scenes=[
        ChapterWorkflowScene(
          title="仓库门外",
          goal="让林追判断是否离开",
          conflict="门外有人逼近",
          turn="铜钥匙发出异常声响",
        )
      ],
    )
    task_names: list[str] = []

    def fake_partial(_settings, _messages, *, task_name, **_kwargs):
      task_names.append(str(task_name))
      return f"{task_name} 写出的续写正文。\n"

    def fake_judge(_settings, **kwargs):
      content = str(kwargs["content"])
      score = 95 if "dialogue-pressure" in content else 80
      return {
        "summary": "候选审校完成。",
        "score": score,
        "passed": True,
        "issues": [],
        "rewrite_focus": [],
        "next_action": "继续推进。",
      }

    with patch("novel_backend.services.generation_service._invoke_partial_model", side_effect=fake_partial), patch(
      "novel_backend.services.generation_service._judge_continuation",
      side_effect=fake_judge,
    ):
      candidates = _generate_continuation_candidates(
        self.settings,
        prefix="# 第一章 雨夜靠港\n",
        context_text="当前章节：林追握着铜钥匙。",
        evidence_text="原文证据：铜钥匙仍在林追手中。",
        canon={
          "summary": "林追刚拿到铜钥匙。",
          "must_keep": ["铜钥匙仍在林追手中"],
          "current_state": ["门外有人逼近"],
          "voice_rules": ["短句推进"],
          "blocked_changes": ["不要提前揭开钥匙用途"],
        },
        scene_result=scene_result,
        instruction="让门外压力靠近。",
        target_words=1200,
        support_text="",
        task_name_prefix="chapter_generate",
        candidate_count=3,
      )

    self.assertEqual([item["id"] for item in candidates], ["dialogue-pressure", "action-pressure", "hook-pressure"])
    self.assertEqual(
      set(task_names),
      {
        "chapter_generate:partial:dialogue-pressure",
        "chapter_generate:partial:action-pressure",
        "chapter_generate:partial:hook-pressure",
      },
    )
    self.assertEqual(candidates[0]["judge"]["score"], 95)

  def test_architecture_step_stream_returns_target_step_content(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="分步架构",
        genre="悬疑幻想",
        target_chapters=6,
        target_words=120000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "core_seed.txt").write_text("一把铜钥匙引出港口旧秩序。", encoding="utf-8")
    (project_dir / "plot_structure.txt").write_text("前段追线索，中段反咬，后段改写秩序。", encoding="utf-8")
    update_project_memory(
      self.settings,
      project.id,
      ProjectMemoryUpdateRequest(
        entries=[ProjectMemoryEntryInput(category="硬规则", title="主角底线", content="林追不会主动交出铜钥匙。")]
      ),
    )
    with patch(
      "novel_backend.services.project_dream_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "summary": "这轮做梦提醒要继续守住铜钥匙、身世和港务会压迫感这三条慢线。",
                  "themes": ["铜钥匙", "身世", "港务会"],
                  "insights": ["人物关系要继续围绕钥匙和旧秩序展开。"],
                  "open_questions": ["港务会什么时候从追查转成公开围剿？"],
                  "memory_candidates": [],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      run_project_dream(self.settings, project.id, ProjectDreamRunRequest())

    with patch(
      "novel_backend.services.generation_service._request_chat_completion",
      return_value={
        "choices": [
          {
            "message": {
              "content": json.dumps(
                {
                  "headline": "人物设定已经补齐。",
                  "summary": "把主角、旧船队后人和港务会的冲突关系拉清楚了。",
                  "content": "林追负责追查旧船队真相，旧船队后人提供潮位线索，港务会掌控表层秩序并追杀知情者。",
                  "checklist": ["补一个摇摆盟友", "明确主角的情感风险"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ) as mocked_request:
      events = asyncio.run(
        collect_architecture_step_events(
          self.settings,
          ArchitectureStepRequest(
            project_id=project.id,
            step="character_design",
            mode="initial",
            guidance="先把主要人物关系排清楚。",
            workspace=ArchitectureWorkspace(core_seed="一把铜钥匙引出港口旧秩序。"),
          ),
        )
      )

    sent_prompt = "\n\n".join(
      str(item.get("content") or "")
      for item in mocked_request.call_args.args[2]["messages"]
    )

    result_event = next(item for item in events if item[0] == "result")
    self.assertEqual(result_event[1]["step"], "character_design")
    self.assertIn("港务会", result_event[1]["content"])
    self.assertIn("项目记忆：", sent_prompt)
    self.assertIn("作者明确要求 / 硬规则 / 主角底线", sent_prompt)
    self.assertIn("最近梦境线索：这轮做梦提醒要继续守住铜钥匙、身世和港务会压迫感这三条慢线。", sent_prompt)
    self.assertEqual(events[-1][1]["status"], "completed")

  def test_architecture_step_stream_accepts_structured_content(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model_name="demo-model",
      ),
    )
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="结构化架构",
        genre="都市",
        target_chapters=6,
        target_words=120000,
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
                  "headline": "人物设定已经整理。",
                  "summary": "围绕林晚的职业危机展开人物关系。",
                  "content": [
                    {
                      "name": "林晚",
                      "age": 32,
                      "role": "创意总监",
                      "initial_state": "事业巅峰期被当众羞辱。",
                      "relationships": {"苏青": "需要主动接触。"},
                    },
                    {
                      "name": "陈小雨",
                      "role": "前实习生",
                      "initial_state": "掌握关键证据。",
                    },
                  ],
                  "checklist": ["确认证据链", "保留职业尊严主线"],
                },
                ensure_ascii=False,
              )
            }
          }
        ]
      },
    ):
      events = asyncio.run(
        collect_architecture_step_events(
          self.settings,
          ArchitectureStepRequest(
            project_id=project.id,
            step="character_design",
            mode="initial",
            guidance="整理人物设定。",
            workspace=ArchitectureWorkspace(),
          ),
        )
      )

    result_event = next(item for item in events if item[0] == "result")
    content = result_event[1]["content"]
    self.assertTrue(content.startswith("林晚："))
    self.assertIn("role：创意总监", content)
    self.assertIn("陈小雨：", content)
    self.assertNotIn('"headline"', content)

  def test_continuity_guard_prefers_manual_memory_and_recent_chapters(self) -> None:
    project = create_project(
      self.settings,
      CreateProjectRequest(
        name="连续性证据",
        genre="文学续写",
        target_chapters=2,
        target_words=40000,
      ),
    )
    project_dir = Path(project.path)
    (project_dir / "chapters" / "001.md").write_text(
      "# 第一章 雨夜靠港\n林追在旧码头仓库找到一把铜钥匙。\n",
      encoding="utf-8",
    )
    (project_dir / "chapters" / "002.md").write_text(
      "# 第二章 门外白光\n探照灯扫到仓库门缝，林追把铜钥匙扣进掌心。\n",
      encoding="utf-8",
    )
    detail = get_project_detail(self.settings, project.id)
    detail.story_overview.memory_entries = [
      ProjectMemoryEntry(
        id="auto-001",
        title="系统整理",
        category="连续性",
        content="自动记忆：林追可能会把铜钥匙暂时放下。",
        source="auto",
      ),
      ProjectMemoryEntry(
        id="manual-001",
        title="作者要求",
        category="硬规则",
        content="手动记忆：林追不能主动交出或放下铜钥匙。",
        source="manual",
      ),
    ]
    chapter = next(item for item in detail.chapters if item.id == "chapter-002")

    with patch(
      "novel_backend.services.continuity_guard_service.search_project_knowledge_evidence",
      return_value=[],
    ):
      guard_context = build_continuity_guard_context(
        self.settings,
        project_id=project.id,
        project_detail=detail,
        chapter=chapter,
        instruction="接着门外白光往下写。",
      )

    self.assertEqual(guard_context.memory_evidence[0]["source"], "manual")
    self.assertIn("手动记忆：林追不能主动交出或放下铜钥匙", guard_context.evidence_text)
    self.assertIn("当前章节末尾", guard_context.evidence_text)
    self.assertIn("上一章末尾", guard_context.evidence_text)


if __name__ == "__main__":
  unittest.main()
