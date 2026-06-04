from __future__ import annotations

import asyncio
import json
import math
import os
import time
from uuid import uuid4

from novel_backend.config import Settings
from novel_backend.models import (
  ArchitectureRequest,
  ArchitectureResult,
  ArchitectureStepRequest,
  ArchitectureStepResult,
  ArchitectureWorkspace,
  ChapterWorkflowRequest,
  ChapterWorkflowResult,
  ChapterWorkflowScene,
  ModelConfig,
)
from novel_backend.services.config_service import load_config
from novel_backend.services.continuity_guard_service import ContinuityGuardContext, build_continuity_guard_context
from novel_backend.services.context_builder import (
  ProjectContextBundle,
  build_chapter_length_guidance,
  build_project_context_bundle,
  build_prompt_support,
  chapter_average_word_target,
  chapter_text_length,
  compact_text,
  explicit_length_target,
  full_chapter_generation_target,
  instruction_requests_explicit_length,
  instruction_requests_full_chapter,
  project_documents_map,
  recommended_chapter_generation_target,
)
from novel_backend.services.log_service import append_app_log, append_prompt_history
from novel_backend.services.model_error_service import classify_model_error
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.model_transport_service import request_json
from novel_backend.services.project_dream_service import build_project_dream_prompt_block
from novel_backend.services.project_service import get_project_detail, search_project_knowledge_evidence
from novel_backend.utils.sse import encode_sse

_ARCHITECTURE_SYSTEM_PROMPT = """
你是资深中文小说策划编辑。请根据用户提供的作品信息，输出一份适合长篇小说立项和续写讨论的架构建议。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 必须包含四个字段：core_seed、character_design、world_building、plot_structure。
3. 每个字段都用中文自然表达，长度控制在 80 到 220 字之间。
4. 重点是给作者明确可继续推进的方向，不要空话。
""".strip()

_CHAPTER_WORKFLOW_SYSTEM_PROMPT = """
你是中文长篇小说编辑和章节写作教练。你要根据作品既有设定、当前章节状态和用户要求，给出可以直接执行的章节建议。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：
   headline: 一句判断
   summary: 对当前章节最重要的分析或写作建议
   checklist: 3 到 6 条可执行要点数组
   scenes: 场景数组，每项包含 title、goal、conflict、turn 四个字段
   draft: 续写正文；如果当前模式不是 draft，就返回空字符串
   next_action: 下一步最建议作者立刻做什么
3. diagnose 模式下，scenes 可为空数组，draft 必须为空。
4. scenes 模式下，给 4 到 6 个场景，draft 必须为空。
5. draft 模式下，draft 必须是可直接保存的正文，第一行使用 Markdown 标题。
6. 内容必须具体，避免空泛评价。
7. 如果上下文里出现参考资料、原作承接、参考人物、参考事件等信息，必须优先服从这些事实，不要改动已经出现的人名、关系、事件结果和时间顺序。
8. draft 模式必须从当前章节正文或上一章末尾自然接下去，不能另起一套剧情。
""".strip()

_WORKFLOW_MODE_LABELS = {
  "diagnose": "章节诊断",
  "scenes": "拆场景",
  "draft": "续写正文",
}

_ARCHITECTURE_STEP_LABELS = {
  "core_seed": "核心种子",
  "character_design": "人物设定",
  "world_building": "世界设定",
  "plot_structure": "情节骨架",
  "character_state": "人物状态",
  "blueprint": "章节蓝图",
  "global_summary": "滚动摘要",
}

_ARCHITECTURE_STEP_REQUIREMENTS = {
  "core_seed": "只输出故事切口、核心矛盾和推进引擎，不要写成长简介。",
  "character_design": "只输出主要人物关系、动机和角色分工，不要重复世界设定。",
  "world_building": "只输出世界规则、环境压力和叙事氛围，不要把情节概述写进来。",
  "plot_structure": "只输出整本推进结构、阶段目标和关键转折，不要写人物小传。必须沿用人物设定里已经确定的核心人物名单；如需新增配角，只能作为单次情节功能角色，不要替换核心人物或改名。",
  "character_state": "只输出当前阶段人物状态、关系变化和后续隐患。必须沿用人物设定里的姓名、身份和关系，不要另造一套联盟成员；如发现人物设定互相冲突，在 summary 或 checklist 指出冲突。",
  "blueprint": "输出可直接写入项目文件的章节蓝图，按章节列出标题、目标和钩子。必须沿用人物设定和人物状态里的核心人物名单，不要在蓝图里把未设定人物改成核心成员。",
  "global_summary": "输出滚动摘要，浓缩已定设定和目前推进状态，长度控制在 120 到 220 字。",
}

_ARCHITECTURE_STEP_DEPENDENCIES = {
  "core_seed": ("character_design", "world_building", "plot_structure"),
  "character_design": ("core_seed", "world_building", "plot_structure"),
  "world_building": ("core_seed", "character_design", "plot_structure"),
  "plot_structure": ("core_seed", "character_design", "world_building", "blueprint"),
  "character_state": ("core_seed", "character_design", "world_building", "plot_structure", "blueprint"),
  "blueprint": ("core_seed", "character_design", "world_building", "plot_structure", "character_state"),
  "global_summary": ("core_seed", "character_design", "world_building", "plot_structure", "character_state", "blueprint"),
}

_ARCHITECTURE_STEP_CONTEXT_LIMITS = {
  "core_seed": 9000,
  "character_design": 9800,
  "world_building": 9800,
  "plot_structure": 10_500,
  "character_state": 9800,
  "blueprint": 12_000,
  "global_summary": 8200,
}

_ARCHITECTURE_STEP_MAX_TOKENS = {
  "core_seed": 1400,
  "character_design": 2200,
  "world_building": 2200,
  "plot_structure": 2400,
  "character_state": 1800,
  "blueprint": 6000,
  "global_summary": 1000,
}

_ARCHITECTURE_STEP_SYSTEM_PROMPT = """
你是中文长篇小说总编辑，负责分步骤生成整本架构。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题或代码块。
2. JSON 字段固定为：headline、summary、content、checklist。
3. headline 用一句话说明这一步的判断。
4. summary 用 2 到 4 句话说明这一版的取舍。
5. content 只输出当前步骤对应的正文，不要混入其他模块内容。
6. checklist 给 2 到 5 条后续检查点。
7. 内容必须和已有项目文档互相兼容，不能推翻已经成立的章节和设定。
8. 如果项目有参考资料或原作信息，这一版架构必须写成承接版，沿用既有人物、关系和事件，不要另造一套故事。
""".strip()

_CONTINUATION_CANON_SYSTEM_PROMPT = """
你是中文小说续写总编，负责先整理这一章承接原作和前文时绝对不能写偏的事实。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：summary、must_keep、current_state、voice_rules、blocked_changes、next_action。
3. must_keep 写 4 到 8 条，这一章必须承接的硬事实。
4. current_state 写 3 到 6 条，说明当前人物关系、时间点和现场状态。
5. voice_rules 写 2 到 5 条，只保留对叙述距离、对白习惯、信息释放最关键的要求。
6. blocked_changes 写 2 到 5 条，明确哪些东西绝对不能改。
7. 如果证据互相冲突，优先服从当前章节和最近正文，再指出冲突点。
8. 所有结论都要贴着输入里的证据块，不要凭空补设定。
9. 如果输入里包含“章节连续性合同”，必须把其中的章节合同、剧情债务、人物弧线、Obsidian 必写 / 禁写和写作判定规则转成 must_keep / blocked_changes。
""".strip()

_CONTINUATION_BRIEF_SYSTEM_PROMPT = """
你是中文小说续写编辑，负责在写正文前整理一份承接简报。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：summary、last_state、active_characters、open_threads、next_beat、hard_constraints、avoid_conflicts、next_action。
3. last_state 写当前章节末尾的人物、地点、时间、行动状态。
4. active_characters 只写眼前会影响下一小段的人物，不要扩成全书人物表。
5. open_threads 只写还没有收住、会影响下一段的线索。
6. next_beat 只写下一小段怎么自然推进，不要重排整章大纲。
7. hard_constraints 写必须服从的硬事实，优先级为：章节连续性合同、手动记忆、当前章节和上一章末尾、导入资料和自动记忆。
8. avoid_conflicts 写续写时必须避开的冲突点。
9. 只依据输入里的项目记忆、章节、导入资料和检索证据；名著常识只能辅助表达，不能当硬证据。
""".strip()

_CONTINUATION_SCENE_SYSTEM_PROMPT = """
你是中文小说场景规划编辑，负责在既有证据和承接要求下，排出当前章节接下来最稳的推进顺序。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：headline、summary、checklist、scenes、next_action。
3. scenes 必须给 3 到 6 个场景，每项包含 title、goal、conflict、turn 四个字段。
4. 每个场景都要能直接拿去写，不能只写抽象主题。
5. 场景顺序必须承接当前章节末尾或上一章末尾，不能倒退重来。
6. 如果输入里已经给出原著证据和人物口气要求，场景设计必须让这些信息自然延续。
""".strip()

_CONTINUITY_CHECK_SYSTEM_PROMPT = """
你是中文小说连续性审校编辑，负责判断续写正文是否推翻项目证据。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：summary、passed、conflicts、rewrite_focus、next_action。
3. conflicts 是数组，每项包含 title、detail、severity、evidence。
4. severity 只能是 info、warning、critical。
5. 只检查可被证据验证的断言：人物关系、事件结果、时间地点、道具状态、历史事实、当前行动是否推翻前文。
6. 文风不够像、节奏弱、句子不好读，不算连续性冲突。
7. 只有存在 critical 硬冲突时，passed 才能为 false，并给出 rewrite_focus。
8. 没有硬冲突时 passed 为 true，rewrite_focus 可以为空数组。
9. 判断依据只来自输入里的项目记忆、章节、导入资料和检索证据。
10. 如果正文缺少章节连续性合同里的明确合同项、剧情债务、人物检查或 Obsidian 必写词，给 warning；如果正文推翻合同里的保护项或禁写项，给 critical。
""".strip()

_CONTINUATION_CANON_JUDGE_SYSTEM_PROMPT = """
你是中文小说续写审校编辑，负责检查这版正文有没有写偏承接事实。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：summary、score、passed、issues、rewrite_focus、next_action。
3. score 是 0 到 100 的整数，分数越高代表越适合直接继续写。
4. passed 只能是 true 或 false。
5. issues 是数组，每项包含 title、detail、severity，severity 只能是 info、warning、critical。
6. rewrite_focus 给 2 到 5 条，只写真正需要返工的位置。
7. 重点检查人名、关系、事件结果、时间地点连续性、信息揭示顺序。
8. 如果没有严重问题，passed 设为 true，rewrite_focus 可以为空数组。
9. 如果输入里有章节连续性合同，必须检查正文是否满足合同项；缺失明确合同项要进入 issues 和 rewrite_focus。
""".strip()

_CONTINUATION_VOICE_JUDGE_SYSTEM_PROMPT = """
你是中文小说续写审校编辑，负责检查这版正文的人物口气和叙述方式有没有跑偏。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：summary、score、passed、issues、rewrite_focus、next_action。
3. score 是 0 到 100 的整数，分数越高代表人物口气越准。
4. passed 只能是 true 或 false。
5. issues 是数组，每项包含 title、detail、severity，severity 只能是 info、warning、critical。
6. rewrite_focus 给 2 到 5 条，只写真正需要返工的位置。
7. 重点检查人物对白、叙述距离、句法节奏、原作气口有没有失真。
8. 如果没有严重问题，passed 设为 true，rewrite_focus 可以为空数组。
""".strip()

_CONTINUATION_READER_JUDGE_SYSTEM_PROMPT = """
你是中文小说续写审校编辑，负责检查这版正文作为一章正文本身是不是成立。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：summary、score、passed、issues、rewrite_focus、next_action。
3. score 是 0 到 100 的整数，分数越高代表这一段越适合直接入稿。
4. passed 只能是 true 或 false。
5. issues 是数组，每项包含 title、detail、severity，severity 只能是 info、warning、critical。
6. rewrite_focus 给 2 到 5 条，只写真正需要返工的位置。
7. 重点检查节奏、场景推进、张力、结尾压力和可读性。
8. 如果没有严重问题，passed 设为 true，rewrite_focus 可以为空数组。
""".strip()

_CONTINUATION_REWRITE_SYSTEM_PROMPT = """
你是中文小说续写修订编辑，负责在不推翻既有事实的前提下，按返工要求重写当前正文。

输出要求：
1. 只输出一个 JSON 对象，不要输出解释、标题、代码块。
2. JSON 字段固定为：headline、summary、content、next_action。
3. content 必须是可直接保存的完整正文，第一行使用 Markdown 标题。
4. 只修复返工指出的问题，不要擅自改掉已经成立的好段落。
5. 必须沿用输入里给出的章节连续性合同、连续性证据、人物关系和承接简报。
""".strip()

_CONTINUATION_WRITE_SYSTEM_PROMPT = """
你是中文小说续写写手。

写作要求：
1. 你会收到当前章节已经确认的前缀，请直接顺着这个前缀往后写，不要重写前文。
2. 只输出接在前缀后面的正文，不要解释，不要分析，不要输出 JSON。
3. 必须承接已经给出的证据、人物关系、承接简报和文风约束。
4. 不要擅自改人名、关系、事件结果和时间顺序。
5. 结尾要留下能继续推进的压力，不要用总结句收尾。
6. 如果输入里包含“章节连续性合同”，正文必须优先满足合同里的明确义务项，并避开保护项和禁写项。
""".strip()

_CONTINUATION_CANDIDATE_VARIANTS = [
  {
    "id": "dialogue-pressure",
    "label": "对白承压",
    "hint": "优先让人物对白先顶上来，把关系压力尽快摆到桌面上。",
    "temperature": 0.75,
  },
  {
    "id": "action-pressure",
    "label": "动作压迫",
    "hint": "优先让动作和环境信号先往前推，把现场危险感压近。",
    "temperature": 0.85,
  },
  {
    "id": "hook-pressure",
    "label": "尾压推进",
    "hint": "优先保证段尾留出更强的后续压力，但不要突然跳戏。",
    "temperature": 0.95,
  },
]

_CONTINUATION_JUDGE_WEIGHTS = {
  "承接事实": 0.45,
  "人物口气": 0.30,
  "可读性": 0.25,
}
_CONTINUATION_SINGLE_CALL_TARGET = 5_500
_CONTINUATION_REPAIR_CONTENT_LIMIT = 24_000
_CONTINUATION_COMPLETION_RATIO = 0.9
_CONTINUATION_MIN_SECTION_TARGET = 1_200
_CONTINUATION_MAX_SECTION_COUNT = 24


class GenerationConfigError(RuntimeError):
  pass


def _resolve_api_key(model_config: ModelConfig) -> str:
  candidates = [
    model_config.api_key,
    os.getenv("NOVEL_MODEL_API_KEY", ""),
    os.getenv("DASHSCOPE_API_KEY", ""),
    os.getenv("ARK_API_KEY", ""),
    os.getenv("NOVEL_API_KEY", ""),
    os.getenv("OPENAI_API_KEY", ""),
  ]

  for item in candidates:
    value = item.strip()
    if value:
      return value

  raise GenerationConfigError(
    "还没配置 API Key。请在设置里填写，或设置 NOVEL_MODEL_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY / OPENAI_API_KEY。"
  )


def _chat_completions_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  if not normalized:
    raise GenerationConfigError("模型接口地址不能为空")
  if normalized.endswith("/chat/completions"):
    return normalized
  return f"{normalized}/chat/completions"


def _extract_message_content(payload: dict[str, object]) -> str:
  choices = payload.get("choices")
  if not isinstance(choices, list) or not choices:
    raise RuntimeError("模型返回格式不正确：缺少 choices")

  first_choice = choices[0]
  if not isinstance(first_choice, dict):
    raise RuntimeError("模型返回格式不正确：choices[0] 不是对象")

  message = first_choice.get("message")
  if not isinstance(message, dict):
    raise RuntimeError("模型返回格式不正确：缺少 message")

  content = message.get("content")
  if isinstance(content, str):
    return content.strip()

  if isinstance(content, list):
    text_parts: list[str] = []
    for item in content:
      if isinstance(item, dict):
        text_value = item.get("text")
        if isinstance(text_value, str) and text_value.strip():
          text_parts.append(text_value.strip())
    merged = "\n".join(text_parts).strip()
    if merged:
      return merged

  raise RuntimeError("模型返回格式不正确：message.content 为空")


def _strip_code_fence(text: str) -> str:
  stripped = text.strip()
  if not stripped.startswith("```"):
    return stripped

  lines = stripped.splitlines()
  if len(lines) >= 3 and lines[-1].strip() == "```":
    return "\n".join(lines[1:-1]).strip()

  return stripped


def _extract_json_object(text: str) -> dict[str, object] | None:
  stripped = _strip_code_fence(text)

  try:
    parsed = json.loads(stripped)
  except json.JSONDecodeError:
    parsed = None

  if isinstance(parsed, dict):
    return parsed

  start = stripped.find("{")
  end = stripped.rfind("}")
  if start == -1 or end == -1 or end <= start:
    return None

  try:
    embedded = json.loads(stripped[start : end + 1])
  except json.JSONDecodeError:
    return None

  if isinstance(embedded, dict):
    return embedded

  return None


def _string_from_keys(payload: dict[str, object], *keys: str) -> str:
  for key in keys:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  return ""


_STRUCTURED_NAME_KEYS = ("name", "姓名", "人物", "角色", "角色名", "title", "标题")


def _structured_value_to_text(value: object) -> str:
  if value is None:
    return ""
  if isinstance(value, str):
    return value.strip()
  if isinstance(value, (int, float, bool)):
    return str(value)
  if isinstance(value, list):
    return "\n".join(
      item
      for item in (_structured_value_to_text(entry) for entry in value)
      if item
    ).strip()
  if isinstance(value, dict):
    heading = ""
    for key in _STRUCTURED_NAME_KEYS:
      raw_heading = value.get(key)
      if isinstance(raw_heading, str) and raw_heading.strip():
        heading = raw_heading.strip()
        break

    lines = [f"{heading}："] if heading else []
    for key, item in value.items():
      if heading and key in _STRUCTURED_NAME_KEYS:
        continue
      text = _structured_value_to_text(item)
      if not text:
        continue
      if "\n" in text:
        lines.append(f"{key}：\n{text}")
      else:
        lines.append(f"{key}：{text}")
    return "\n".join(lines).strip()
  return str(value).strip()


def _structured_text_from_keys(payload: dict[str, object], *keys: str) -> str:
  for key in keys:
    if key not in payload:
      continue
    text = _structured_value_to_text(payload.get(key))
    if text:
      return text
  return ""


def _string_list_from_keys(payload: dict[str, object], *keys: str) -> list[str]:
  for key in keys:
    value = payload.get(key)
    if isinstance(value, list):
      items = [str(item).strip() for item in value if str(item).strip()]
      if items:
        return items
    if isinstance(value, str) and value.strip():
      lines = [
        item.strip(" -0123456789.、）)")
        for item in value.splitlines()
        if item.strip()
      ]
      cleaned = [item for item in lines if item]
      if cleaned:
        return cleaned
  return []


_compact_text = compact_text


def _query_tail(text: str, limit: int = 900) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return normalized[-limit:].lstrip()


def _request_chat_completion(endpoint: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
  return request_json(
    endpoint,
    api_key,
    payload,
    failure_label="模型请求失败",
    invalid_json_message="模型返回的不是合法 JSON",
    invalid_format_message="模型返回格式不正确",
  )


def _model_is_aliyun(model_config: ModelConfig) -> bool:
  base_url = model_config.base_url.strip().lower()
  model_name = model_config.model_name.strip().lower()
  return "dashscope.aliyuncs.com" in base_url or model_name.startswith("qwen")


def _invoke_model(
  settings: Settings,
  messages: list[dict[str, object]],
  *,
  task_name: str = "model_task",
  temperature: float | None = None,
  max_tokens: int | None = None,
  enable_thinking: bool | None = None,
  extra_payload: dict[str, object] | None = None,
) -> str:
  config = load_config(settings).model
  api_key = _resolve_api_key(config)
  endpoint = _chat_completions_endpoint(config.base_url)
  started = time.perf_counter()
  chat_payload = {
    "model": config.model_name,
    "messages": messages,
    "temperature": config.temperature if temperature is None else temperature,
    "max_tokens": config.max_tokens if max_tokens is None else max_tokens,
  }
  if enable_thinking is not None and _model_is_aliyun(config):
    chat_payload["enable_thinking"] = enable_thinking
  for key, value in (extra_payload or {}).items():
    chat_payload[key] = value
  prompt_text = "\n\n".join(
    f"[{item.get('role', 'user')}] {item.get('content', '')}"
    for item in messages
  ).strip()
  runtime_task = None
  try:
    with model_runtime_slot(settings, lane="chat", task_name=task_name) as task:
      runtime_task = task
      response_payload = _request_chat_completion(endpoint, api_key, chat_payload)
    content = _extract_message_content(response_payload)
    elapsed = round(time.perf_counter() - started, 3)
    append_prompt_history(
      settings,
      {
        "task": task_name,
        "model": config.model_name,
        "prompt": prompt_text,
        "response": content,
        "status": "completed",
        "elapsed": elapsed,
        "runtime_task_id": runtime_task.task_id if runtime_task is not None else "",
        "runtime_lane": runtime_task.lane if runtime_task is not None else "chat",
        "runtime_priority": runtime_task.priority if runtime_task is not None else 0,
        "queue_wait_seconds": runtime_task.queue_wait_seconds if runtime_task is not None else 0.0,
      },
    )
    append_app_log(settings, f"{task_name} completed in {elapsed:.3f}s")
    return content
  except Exception as error:
    elapsed = round(time.perf_counter() - started, 3)
    classified_error = classify_model_error(error)
    if classified_error.retryable:
      mark_model_runtime_cooldown(settings, "chat", classified_error.title)
    append_prompt_history(
      settings,
      {
        "task": task_name,
        "model": config.model_name,
        "prompt": prompt_text,
        "response": "",
        "status": "failed",
        "elapsed": elapsed,
        "error": str(error),
        "error_kind": classified_error.kind,
        "error_title": classified_error.title,
        "error_user_action": classified_error.user_action,
        "error_retryable": classified_error.retryable,
        "runtime_task_id": runtime_task.task_id if runtime_task is not None else "",
        "runtime_lane": runtime_task.lane if runtime_task is not None else "chat",
        "runtime_priority": runtime_task.priority if runtime_task is not None else 0,
        "queue_wait_seconds": runtime_task.queue_wait_seconds if runtime_task is not None else 0.0,
      },
    )
    append_app_log(
      settings,
      f"{task_name} failed in {elapsed:.3f}s: {classified_error.title}: {error}",
      level="ERROR",
    )
    raise RuntimeError(f"{classified_error.title}：{classified_error.user_action} 原始错误：{error}") from error


def _invoke_partial_model(
  settings: Settings,
  messages: list[dict[str, object]],
  *,
  prefix: str,
  task_name: str,
  temperature: float | None = None,
  max_tokens: int | None = None,
  enable_thinking: bool | None = None,
) -> str:
  partial_messages = list(messages)
  partial_messages.append(
    {
      "role": "assistant",
      "content": prefix,
      "partial": True,
    }
  )
  return _invoke_model(
    settings,
    partial_messages,
    task_name=task_name,
    temperature=temperature,
    max_tokens=max_tokens,
    enable_thinking=enable_thinking,
  )


def _build_architecture_messages(settings: Settings, payload: ArchitectureRequest) -> list[dict[str, str]]:
  messages = [
    {
      "role": "system",
      "content": _ARCHITECTURE_SYSTEM_PROMPT,
    },
  ]
  support = build_prompt_support(settings, task_key="architecture")
  if support:
    messages.append({"role": "system", "content": f"额外要求：{support}"})
  messages.append(
    {
      "role": "user",
      "content": (
        "请围绕下面这部作品给出架构建议。\n\n"
        f"书名：{payload.title}\n"
        f"类型：{payload.genre}\n"
        f"目标章节数：{payload.chapter_count}\n"
        f"目标字数：{payload.target_words}\n"
        f"已有信息：\n{payload.premise.strip()}\n"
      ),
    }
  )
  return messages


def _fallback_sections_from_text(text: str) -> dict[str, str]:
  cleaned = _strip_code_fence(text)
  paragraphs = [item.strip(" -：:") for item in cleaned.splitlines() if item.strip()]
  normalized = [item for item in paragraphs if item]
  while len(normalized) < 4:
    normalized.append("")

  return {
    "core_seed": normalized[0],
    "character_design": normalized[1],
    "world_building": normalized[2],
    "plot_structure": normalized[3],
  }


def _parse_architecture_payload(text: str) -> dict[str, str]:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    parsed = {
      "core_seed": _structured_text_from_keys(payload, "core_seed", "故事切口", "核心种子"),
      "character_design": _structured_text_from_keys(payload, "character_design", "人物关系", "角色设计"),
      "world_building": _structured_text_from_keys(payload, "world_building", "世界氛围", "世界观"),
      "plot_structure": _structured_text_from_keys(payload, "plot_structure", "推进方向", "情节结构"),
    }
    if all(parsed.values()):
      return parsed

  fallback = _fallback_sections_from_text(text)
  if not all(fallback.values()):
    raise RuntimeError("模型返回里没有拿到完整的架构内容")
  return fallback


def _generate_architecture(settings: Settings, payload: ArchitectureRequest, task_id: str) -> ArchitectureResult:
  content = _invoke_model(settings, _build_architecture_messages(settings, payload), task_name="architecture")
  sections = _parse_architecture_payload(content)
  return ArchitectureResult(
    task_id=task_id,
    core_seed=sections["core_seed"],
    character_design=sections["character_design"],
    world_building=sections["world_building"],
    plot_structure=sections["plot_structure"],
  )


def _workspace_document_value(workspace: ArchitectureWorkspace, key: str) -> str:
  value = getattr(workspace, key, "")
  return value.strip() if isinstance(value, str) else ""


def _architecture_document_map(project_detail, workspace: ArchitectureWorkspace) -> dict[str, str]:
  overrides = {
    key: _workspace_document_value(workspace, key)
    for key in _ARCHITECTURE_STEP_LABELS
    if _workspace_document_value(workspace, key)
  }
  return project_documents_map(project_detail, overrides=overrides)


def _architecture_workspace_snapshot_text(documents: dict[str, str], focus_step: str = "") -> str:
  lines = []
  dependencies = set(_ARCHITECTURE_STEP_DEPENDENCIES.get(focus_step, ()))
  for key, label in _ARCHITECTURE_STEP_LABELS.items():
    if key == focus_step:
      limit = 260
    elif key in dependencies:
      limit = 420
    else:
      limit = 140
    lines.append(f"{label}：{compact_text(documents.get(key, ''), limit) or '无'}")
  return "\n".join(lines)


def _architecture_context_line_limit(line: str, focus_step: str) -> int:
  label = line.split("：", 1)[0].strip()
  step_labels = {
    "core_seed": "核心种子",
    "character_design": "人物设定",
    "world_building": "世界设定",
    "plot_structure": "情节骨架",
    "character_state": "人物状态",
    "blueprint": "章节蓝图",
    "global_summary": "滚动摘要",
  }
  focus_label = step_labels.get(focus_step, "")
  dependency_labels = {
    step_labels[key]
    for key in _ARCHITECTURE_STEP_DEPENDENCIES.get(focus_step, ())
    if key in step_labels
  }
  if label in {"作品", "类型", "目标章节数", "目标字数"}:
    return 180
  if label == focus_label:
    return 520
  if label in dependency_labels:
    return 420
  if label in set(step_labels.values()):
    return 240
  if label == "项目记忆":
    return 1200
  if label in {"参考人物", "参考事件"}:
    return 900
  if label == "参考资料":
    return 1300
  if label == "Obsidian 设定笔记":
    return 1500
  if label in {"本章 Obsidian 设定检查清单", "本章 Obsidian 写作约束"}:
    return 900
  if label == "任务蒸馏":
    return 1400
  if label == "检索线索":
    return 1300
  return 360


def _architecture_step_context_text(bundle: ProjectContextBundle, payload: ArchitectureStepRequest) -> str:
  limit = _ARCHITECTURE_STEP_CONTEXT_LIMITS.get(payload.step, 9500)
  if len(bundle.context_text) <= limit:
    return bundle.context_text
  compacted_lines = [
    compact_text(line, _architecture_context_line_limit(line, payload.step))
    for line in bundle.context_lines
    if str(line or "").strip()
  ]
  compacted = "\n".join(item for item in compacted_lines if item).strip()
  if len(compacted) <= limit:
    return compacted
  return compact_text(compacted, limit)


def _architecture_current_content_text(content: str, step: str) -> str:
  limits = {
    "blueprint": 5000,
    "plot_structure": 2600,
    "character_design": 2400,
    "world_building": 2200,
    "character_state": 2200,
    "core_seed": 1800,
    "global_summary": 900,
  }
  text = str(content or "").strip()
  if not text:
    return "无"
  limit = limits.get(step, 2200)
  if len(text) <= limit:
    return text
  return compact_text(text, limit)


def _architecture_step_max_tokens(settings: Settings, step: str) -> int:
  configured_limit = int(load_config(settings).model.max_tokens or 8192)
  step_limit = _ARCHITECTURE_STEP_MAX_TOKENS.get(step, configured_limit)
  return max(256, min(configured_limit, step_limit))


def _architecture_step_context(
  settings: Settings,
  payload: ArchitectureStepRequest,
  context_snapshot: ProjectContextBundle | None = None,
) -> tuple[object, dict[str, str], int, str]:
  if context_snapshot is None:
    project_detail = get_project_detail(settings, payload.project_id, allow_model_overview=False)
    documents = _architecture_document_map(project_detail, payload.workspace)
    knowledge_query = " ".join(
      item for item in [
        _ARCHITECTURE_STEP_LABELS.get(payload.step, ""),
        payload.guidance,
        documents.get(payload.step, ""),
      ]
      if item.strip()
    )
    bundle = build_project_context_bundle(
      settings,
      payload.project_id,
      include_blueprint=True,
      include_character_state=True,
      knowledge_query=knowledge_query,
      task_pack_kind="architecture",
      task_instruction=payload.guidance,
      override_documents=documents,
    )
  else:
    bundle = context_snapshot
    project_detail = bundle.project_detail
    documents = _architecture_document_map(project_detail, payload.workspace)

  target_chapters = project_detail.target_chapters + payload.new_chapters if payload.mode == "continue" else project_detail.target_chapters
  knowledge_text = "\n".join(
    f"- {item.section}（{item.match_type}）：{item.preview}"
    for item in bundle.knowledge_hits
  ) or "无"
  dream_text = build_project_dream_prompt_block(project_detail)
  dream_block = f"{dream_text}\n" if dream_text else ""
  workspace_text = _architecture_workspace_snapshot_text(documents, payload.step)
  compact_context_text = _architecture_step_context_text(bundle, payload)
  context_text = (
    f"当前模式：{'续写扩展' if payload.mode == 'continue' else '初始架构'}\n"
    f"当前章节数：{project_detail.target_chapters}\n"
    f"目标章节数：{target_chapters}\n"
    f"当前步骤：{_ARCHITECTURE_STEP_LABELS[payload.step]}\n"
    f"{compact_context_text}\n"
    f"本次任务架构工作区（优先参考这里的步骤间最新内容）：\n{workspace_text}\n"
    f"{dream_block}"
    f"相关检索：\n{knowledge_text}"
  )
  return project_detail, documents, target_chapters, context_text


def _build_architecture_step_messages(
  settings: Settings,
  payload: ArchitectureStepRequest,
  context_snapshot: ProjectContextBundle | None = None,
) -> list[dict[str, str]]:
  project_detail, documents, target_chapters, context_text = _architecture_step_context(settings, payload, context_snapshot)
  current_content = documents.get(payload.step, "")
  current_content_text = _architecture_current_content_text(current_content, payload.step)
  messages = [{"role": "system", "content": _ARCHITECTURE_STEP_SYSTEM_PROMPT}]
  support = build_prompt_support(settings, task_key="architecture")
  if support:
    messages.append({"role": "system", "content": f"额外要求：{support}"})
  messages.append(
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"这一步只处理：{_ARCHITECTURE_STEP_LABELS[payload.step]}。\n"
        f"步骤要求：{_ARCHITECTURE_STEP_REQUIREMENTS[payload.step]}\n"
        f"当前已有草稿：\n{current_content_text}\n\n"
        f"用户补充：{payload.guidance.strip() or '无'}\n"
        f"如果当前模式是续写扩展，请把内容写成能从 {project_detail.target_chapters} 章扩到 {target_chapters} 章的版本。"
      ).strip(),
    }
  )
  return messages


def _fallback_architecture_step_result(text: str, payload: ArchitectureStepRequest, task_id: str) -> ArchitectureStepResult:
  cleaned = _strip_code_fence(text)
  lines = [item.strip() for item in cleaned.splitlines() if item.strip()]
  headline = lines[0] if lines else f"{_ARCHITECTURE_STEP_LABELS[payload.step]} 已生成"
  summary = lines[1] if len(lines) > 1 else cleaned
  checklist = [item.strip(" -0123456789.、）)") for item in lines[2:6] if item.strip()]
  return ArchitectureStepResult(
    task_id=task_id,
    step=payload.step,
    mode=payload.mode,
    headline=headline,
    summary=summary,
    content=cleaned,
    checklist=[item for item in checklist if item],
    target_chapters=None if payload.mode != "continue" else payload.new_chapters or None,
  )


def _parse_architecture_step_payload(text: str, payload: ArchitectureStepRequest, task_id: str) -> ArchitectureStepResult:
  parsed = _extract_json_object(text)
  if not isinstance(parsed, dict):
    return _fallback_architecture_step_result(text, payload, task_id)
  headline = _string_from_keys(parsed, "headline", "判断", "title")
  summary = _string_from_keys(parsed, "summary", "说明", "analysis")
  content = _structured_text_from_keys(parsed, "content", "正文", "result")
  checklist = _string_list_from_keys(parsed, "checklist", "要点", "suggestions")
  if not content:
    return _fallback_architecture_step_result(text, payload, task_id)
  return ArchitectureStepResult(
    task_id=task_id,
    step=payload.step,
    mode=payload.mode,
    headline=headline or f"{_ARCHITECTURE_STEP_LABELS[payload.step]} 已生成",
    summary=summary or headline or "这一步的草稿已经整理好。",
    content=content,
    checklist=checklist,
    target_chapters=None if payload.mode != "continue" else None,
  )


def _generate_architecture_step(
  settings: Settings,
  payload: ArchitectureStepRequest,
  task_id: str,
  context_snapshot: ProjectContextBundle | None = None,
) -> ArchitectureStepResult:
  content = _invoke_model(
    settings,
    _build_architecture_step_messages(settings, payload, context_snapshot),
    task_name=f"architecture_step:{payload.step}:{payload.mode}",
    max_tokens=_architecture_step_max_tokens(settings, payload.step),
  )
  result = _parse_architecture_step_payload(content, payload, task_id)
  if payload.mode == "continue":
    project_detail = context_snapshot.project_detail if context_snapshot is not None else get_project_detail(settings, payload.project_id)
    return result.model_copy(update={"target_chapters": project_detail.target_chapters + payload.new_chapters})
  return result


def _continuation_query(
  chapter,
  instruction: str,
  *,
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
) -> str:
  pieces = [
    chapter.title if chapter is not None else "",
    instruction,
    characters_involved,
    key_items,
    scene_location,
    time_constraint,
    _query_tail(str(getattr(chapter, "content", "") or ""), 900) if chapter is not None else "",
  ]
  return " ".join(item.strip() for item in pieces if item and item.strip())


def _continuation_context_query(
  settings: Settings,
  project_id: str,
  chapter_id: str,
  instruction: str,
  *,
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
) -> str:
  try:
    project_detail = get_project_detail(
      settings,
      project_id,
      allow_model_overview=False,
      use_model_overview_cache=False,
    )
  except Exception:
    return _continuation_query(
      None,
      instruction,
      characters_involved=characters_involved,
      key_items=key_items,
      scene_location=scene_location,
      time_constraint=time_constraint,
    )
  chapter = next((item for item in getattr(project_detail, "chapters", []) if item.id == chapter_id), None)
  return _continuation_query(
    chapter,
    instruction,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )


def _format_evidence_blocks(evidence_hits: list[dict[str, object]], limit: int = 6) -> str:
  lines: list[str] = []
  for index, item in enumerate(evidence_hits[:limit], start=1):
    source = str(item.get("source") or "").strip() or "未知来源"
    section = str(item.get("section") or "").strip() or "未命名片段"
    content = str(item.get("content") or "").strip()
    if not content:
      continue
    lines.append(
      f"[证据 {index}] {source}｜{section}\n{content[:420].rstrip()}"
    )
  return "\n\n".join(lines).strip() or "无"


def _compact_rules(items: list[str], limit: int = 5) -> str:
  cleaned = [str(item).strip() for item in items if str(item).strip()]
  return "\n".join(f"- {item}" for item in cleaned[:limit]) or "无"


def _parse_canon_payload(text: str) -> dict[str, object]:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    cleaned = _strip_code_fence(text)
    return {
      "summary": _compact_text(cleaned, 180),
      "must_keep": [],
      "current_state": [],
      "voice_rules": [],
      "blocked_changes": [],
      "next_action": "",
    }
  return {
    "summary": _string_from_keys(payload, "summary", "headline", "结论") or "这一章的承接要求已经整理好。",
    "must_keep": _string_list_from_keys(payload, "must_keep", "facts", "checklist"),
    "current_state": _string_list_from_keys(payload, "current_state", "state", "status"),
    "voice_rules": _string_list_from_keys(payload, "voice_rules", "style_rules"),
    "blocked_changes": _string_list_from_keys(payload, "blocked_changes", "dont_change"),
    "next_action": _string_from_keys(payload, "next_action", "action"),
  }


def _parse_continuation_brief_payload(text: str) -> dict[str, object]:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    cleaned = _strip_code_fence(text)
    return {
      "summary": _compact_text(cleaned, 180),
      "last_state": [],
      "active_characters": [],
      "open_threads": [],
      "next_beat": _compact_text(cleaned, 220),
      "hard_constraints": [],
      "avoid_conflicts": [],
      "next_action": "",
    }
  return {
    "summary": _string_from_keys(payload, "summary", "headline", "结论") or "承接简报已经整理好。",
    "last_state": _string_list_from_keys(payload, "last_state", "current_state", "state"),
    "active_characters": _string_list_from_keys(payload, "active_characters", "characters", "人物"),
    "open_threads": _string_list_from_keys(payload, "open_threads", "threads", "线索"),
    "next_beat": _string_from_keys(payload, "next_beat", "next_step", "推进") or "顺着当前章节末尾继续推进。",
    "hard_constraints": _string_list_from_keys(payload, "hard_constraints", "must_keep", "facts"),
    "avoid_conflicts": _string_list_from_keys(payload, "avoid_conflicts", "blocked_changes", "dont_change"),
    "next_action": _string_from_keys(payload, "next_action", "action"),
  }


def _parse_conflict_report_payload(text: str) -> dict[str, object]:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    cleaned = _strip_code_fence(text)
    return {
      "summary": _compact_text(cleaned, 180),
      "passed": True,
      "conflicts": [],
      "rewrite_focus": [],
      "next_action": "",
    }

  raw_conflicts = payload.get("conflicts")
  if not isinstance(raw_conflicts, list):
    raw_conflicts = payload.get("issues")
  conflicts: list[dict[str, str]] = []
  if isinstance(raw_conflicts, list):
    for item in raw_conflicts:
      if not isinstance(item, dict):
        continue
      title = _string_from_keys(item, "title", "问题")
      detail = _string_from_keys(item, "detail", "说明")
      severity = (_string_from_keys(item, "severity", "level") or "warning").strip().lower()
      if severity not in {"info", "warning", "critical"}:
        severity = "warning"
      evidence = _string_from_keys(item, "evidence", "依据")
      if not title and not detail:
        continue
      conflicts.append(
        {
          "title": title or "连续性风险",
          "detail": detail or title,
          "severity": severity,
          "evidence": evidence,
        }
      )

  has_hard_conflict = any(item["severity"] == "critical" for item in conflicts)
  passed_value = payload.get("passed")
  if isinstance(passed_value, bool):
    passed = passed_value and not has_hard_conflict
  else:
    passed = not has_hard_conflict
  rewrite_focus = _string_list_from_keys(payload, "rewrite_focus", "suggestions", "checklist")
  if has_hard_conflict and not rewrite_focus:
    rewrite_focus = [item["detail"] for item in conflicts if item["severity"] == "critical"]
  return {
    "summary": _string_from_keys(payload, "summary", "headline") or "连续性检查完成。",
    "passed": passed,
    "conflicts": conflicts,
    "rewrite_focus": rewrite_focus,
    "next_action": _string_from_keys(payload, "next_action", "action"),
  }


def _conflict_report_has_hard_conflict(report: dict[str, object]) -> bool:
  conflicts = report.get("conflicts")
  if not isinstance(conflicts, list):
    return False
  return any(isinstance(item, dict) and str(item.get("severity") or "") == "critical" for item in conflicts)


def _parse_judge_payload(text: str) -> dict[str, object]:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    cleaned = _strip_code_fence(text)
    return {
      "summary": _compact_text(cleaned, 180),
      "passed": True,
      "issues": [],
      "rewrite_focus": [],
      "next_action": "",
    }
  raw_issues = payload.get("issues")
  issues: list[dict[str, str]] = []
  if isinstance(raw_issues, list):
    for item in raw_issues:
      if not isinstance(item, dict):
        continue
      title = _string_from_keys(item, "title", "问题")
      detail = _string_from_keys(item, "detail", "说明")
      severity = _string_from_keys(item, "severity", "level") or "warning"
      if not title and not detail:
        continue
      issues.append(
        {
          "title": title or "潜在问题",
          "detail": detail or title,
          "severity": severity,
        }
      )
  passed_value = payload.get("passed")
  passed = bool(passed_value) if isinstance(passed_value, bool) else len([item for item in issues if item["severity"] == "critical"]) == 0
  score_value = payload.get("score")
  if isinstance(score_value, (int, float)):
    score = max(0, min(100, int(round(float(score_value)))))
  else:
    score = _estimate_judge_score(issues, passed)
  return {
    "summary": _string_from_keys(payload, "summary", "headline") or "已完成当前正文审校。",
    "score": score,
    "passed": passed,
    "issues": issues,
    "rewrite_focus": _string_list_from_keys(payload, "rewrite_focus", "suggestions", "checklist"),
    "next_action": _string_from_keys(payload, "next_action", "action"),
  }


def _parse_content_payload(text: str) -> dict[str, str]:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    cleaned = _strip_code_fence(text)
    return {
      "headline": "修订完成",
      "summary": _compact_text(cleaned, 160),
      "content": cleaned,
      "next_action": "",
    }
  content = _string_from_keys(payload, "content", "draft", "正文")
  if not content:
    cleaned = _strip_code_fence(text)
    content = cleaned
  return {
    "headline": _string_from_keys(payload, "headline", "title") or "修订完成",
    "summary": _string_from_keys(payload, "summary", "说明") or "当前正文已经按返工要求修好。",
    "content": content,
    "next_action": _string_from_keys(payload, "next_action", "action"),
  }


def _estimate_judge_score(issues: list[dict[str, str]], passed: bool) -> int:
  base = 92 if passed else 72
  penalties = {
    "critical": 24,
    "warning": 8,
    "info": 2,
  }
  score = base
  for item in issues:
    severity = str(item.get("severity") or "warning").strip() or "warning"
    score -= penalties.get(severity, 8)
  return max(0, min(100, score))


def _continuation_prefix(chapter) -> str:
  current = str(getattr(chapter, "content", "") or "").strip()
  if current:
    return current if current.endswith("\n") else f"{current}\n"
  title = str(getattr(chapter, "title", "") or "").strip() or "未命名章节"
  return f"# {title}\n"


def _strip_repeated_partial_prefix(prefix: str, suffix: str) -> str:
  clean_prefix = str(prefix or "").strip()
  clean_suffix = str(suffix or "")
  if not clean_prefix:
    return clean_suffix
  suffix_without_left_space = clean_suffix.lstrip()
  if suffix_without_left_space.startswith(clean_prefix):
    return suffix_without_left_space[len(clean_prefix) :].lstrip("\n")
  return clean_suffix


def _object_text_list(value: object) -> list[str]:
  if isinstance(value, list):
    return [str(item).strip() for item in value if str(item).strip()]
  if isinstance(value, str) and value.strip():
    return [value.strip()]
  return []


def _continuation_brief_block(brief: dict[str, object]) -> str:
  return (
    f"摘要：{brief.get('summary') or ''}\n"
    f"末尾状态：\n{_compact_rules(_object_text_list(brief.get('last_state')), 8)}\n"
    f"当前出场人物：\n{_compact_rules(_object_text_list(brief.get('active_characters')), 8)}\n"
    f"未收线索：\n{_compact_rules(_object_text_list(brief.get('open_threads')), 8)}\n"
    f"下一小段推进：{brief.get('next_beat') or ''}\n"
    f"硬约束：\n{_compact_rules(_object_text_list(brief.get('hard_constraints')), 8)}\n"
    f"必须避开的冲突：\n{_compact_rules(_object_text_list(brief.get('avoid_conflicts')), 8)}"
  ).strip()


def _continuation_brief_messages(
  *,
  context_text: str,
  guard_context: ContinuityGuardContext,
  instruction: str,
  support_text: str,
  chapter_title: str,
  target_words: int,
) -> list[dict[str, object]]:
  return [
    {"role": "system", "content": _CONTINUATION_BRIEF_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"连续性证据包：\n{guard_context.evidence_text}\n\n"
        f"本次章节：{chapter_title}\n"
        f"用户补充：{instruction.strip() or '无'}\n"
        f"目标长度：约 {target_words} 字\n"
        f"{support_text or ''}"
      ).strip(),
    },
  ]


def _generate_continuation_brief(
  settings: Settings,
  *,
  project_id: str,
  chapter_id: str,
  instruction: str,
  target_words: int,
  support_text: str = "",
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
) -> dict[str, object]:
  context_query = _continuation_context_query(
    settings,
    project_id,
    chapter_id,
    instruction,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  bundle = build_project_context_bundle(
    settings,
    project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=chapter_id,
    knowledge_query=context_query,
    task_pack_kind="continuation",
    task_instruction=context_query,
  )
  chapter = bundle.chapter
  if chapter is None:
    raise RuntimeError("当前章节不存在")

  guard_context = build_continuity_guard_context(
    settings,
    project_id=project_id,
    project_detail=bundle.project_detail,
    chapter=chapter,
    instruction=instruction,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  brief_text = _invoke_model(
    settings,
    _continuation_brief_messages(
      context_text=bundle.context_text,
      guard_context=guard_context,
      instruction=instruction,
      support_text=support_text,
      chapter_title=chapter.title,
      target_words=target_words,
    ),
    task_name="continuation_brief",
    max_tokens=min(4096, max(1200, target_words)),
    enable_thinking=True,
  )
  return {
    "bundle": bundle,
    "chapter": chapter,
    "guard_context": guard_context,
    "brief": _parse_continuation_brief_payload(brief_text),
    "evidence_hits": guard_context.knowledge_evidence,
    "evidence_text": guard_context.evidence_text,
  }


def _continuation_single_write_messages(
  *,
  context_text: str,
  evidence_text: str,
  brief: dict[str, object],
  instruction: str,
  target_words: int,
  support_text: str,
) -> list[dict[str, object]]:
  return [
    {"role": "system", "content": _CONTINUATION_WRITE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"连续性证据包：\n{evidence_text}\n\n"
        f"承接简报：\n{_continuation_brief_block(brief)}\n\n"
        f"用户补充：{instruction.strip() or '无'}\n"
        f"目标长度：约 {target_words} 字\n"
        f"{support_text or ''}"
      ).strip(),
    },
  ]


def _check_continuation_conflicts(
  settings: Settings,
  *,
  context_text: str,
  evidence_text: str,
  brief: dict[str, object],
  content: str,
) -> dict[str, object]:
  report_text = _invoke_model(
    settings,
    [
      {"role": "system", "content": _CONTINUITY_CHECK_SYSTEM_PROMPT},
      {
        "role": "user",
        "content": (
          f"{context_text}\n\n"
          f"连续性证据包：\n{evidence_text}\n\n"
          f"承接简报：\n{_continuation_brief_block(brief)}\n\n"
          f"待检查正文：\n{content}"
        ).strip(),
      },
    ],
    task_name="continuation_conflict_check",
    max_tokens=2200,
    enable_thinking=True,
  )
  return _parse_conflict_report_payload(report_text)


def _repair_continuation_with_guard(
  settings: Settings,
  *,
  context_text: str,
  evidence_text: str,
  brief: dict[str, object],
  conflict_report: dict[str, object],
  content: str,
  support_text: str,
) -> str:
  conflicts = conflict_report.get("conflicts") if isinstance(conflict_report.get("conflicts"), list) else []
  conflict_lines = []
  for item in conflicts:
    if not isinstance(item, dict):
      continue
    conflict_lines.append(
      f"- {item.get('severity') or 'warning'}｜{item.get('title') or '连续性风险'}：{item.get('detail') or ''} 依据：{item.get('evidence') or '无'}"
    )
  repaired = _invoke_model(
    settings,
    [
      {"role": "system", "content": _CONTINUATION_REWRITE_SYSTEM_PROMPT},
      {
        "role": "user",
        "content": (
          f"{context_text}\n\n"
          f"连续性证据包：\n{evidence_text}\n\n"
          f"承接简报：\n{_continuation_brief_block(brief)}\n\n"
          f"连续性检查报告：\n"
          f"摘要：{conflict_report.get('summary') or ''}\n"
          f"冲突：\n{chr(10).join(conflict_lines) if conflict_lines else '无'}\n"
          f"修订要求：\n{_compact_rules(_object_text_list(conflict_report.get('rewrite_focus')), 8)}\n\n"
          f"当前正文：\n{content}\n"
          f"{support_text or ''}"
        ).strip(),
      },
    ],
    task_name="continuation_rewrite",
    max_tokens=max(2400, len(content) // 2),
    enable_thinking=True,
  )
  repaired_result = _parse_content_payload(repaired)
  return repaired_result["content"]


def _continuation_plan_messages(
  settings: Settings,
  *,
  context_text: str,
  evidence_text: str,
  instruction: str,
  support_text: str,
  chapter_title: str,
  target_words: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
  canon_messages: list[dict[str, object]] = [
    {"role": "system", "content": _CONTINUATION_CANON_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"原文证据块：\n{evidence_text}\n\n"
        f"本轮任务：为《{chapter_title}》整理承接简报。\n"
        f"用户补充：{instruction.strip() or '无'}\n"
        f"目标长度：约 {target_words} 字\n"
        f"{support_text or ''}"
      ).strip(),
    },
  ]
  scene_messages: list[dict[str, object]] = [
    {"role": "system", "content": _CONTINUATION_SCENE_SYSTEM_PROMPT},
  ]
  return canon_messages, scene_messages


def _generate_continuation_plan(
  settings: Settings,
  *,
  project_id: str,
  chapter_id: str,
  instruction: str,
  target_words: int,
  support_text: str = "",
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
) -> dict[str, object]:
  context_query = _continuation_context_query(
    settings,
    project_id,
    chapter_id,
    instruction,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  bundle = build_project_context_bundle(
    settings,
    project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=chapter_id,
    knowledge_query=context_query,
    task_pack_kind="continuation",
    task_instruction=context_query,
  )
  chapter = bundle.chapter
  if chapter is None:
    raise RuntimeError("当前章节不存在")

  evidence_query = _continuation_query(
    chapter,
    instruction,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  evidence_hits = search_project_knowledge_evidence(
    settings,
    project_id,
    evidence_query,
    limit=8,
    candidate_limit=24,
    chapter_index=int(getattr(chapter, "index", 0) or 0),
  )
  evidence_text = _format_evidence_blocks(evidence_hits)
  canon_messages, scene_messages = _continuation_plan_messages(
    settings,
    context_text=bundle.context_text,
    evidence_text=evidence_text,
    instruction=instruction,
    support_text=support_text,
    chapter_title=chapter.title,
    target_words=target_words,
  )
  canon_text = _invoke_model(
    settings,
    canon_messages,
    task_name="continuation_canon",
    max_tokens=min(4096, max(1200, target_words)),
    enable_thinking=True,
  )
  canon = _parse_canon_payload(canon_text)
  scene_messages.append(
    {
      "role": "user",
      "content": (
        f"{bundle.context_text}\n\n"
        f"原文证据块：\n{evidence_text}\n\n"
        f"承接简报：\n"
        f"摘要：{canon['summary']}\n"
        f"必须保留：\n{_compact_rules(canon['must_keep'])}\n"
        f"当前状态：\n{_compact_rules(canon['current_state'])}\n"
        f"表达约束：\n{_compact_rules(canon['voice_rules'])}\n"
        f"不要改动：\n{_compact_rules(canon['blocked_changes'])}\n\n"
        f"请为《{chapter.title}》排出继续往下写的场景计划。\n"
        f"用户补充：{instruction.strip() or '无'}\n"
        f"目标长度：约 {target_words} 字\n"
        f"{support_text or ''}"
      ).strip(),
    }
  )
  scene_text = _invoke_model(
    settings,
    scene_messages,
    task_name="continuation_scene_plan",
    max_tokens=min(4096, max(1200, target_words)),
    enable_thinking=True,
  )
  scene_result = _parse_chapter_workflow_payload(scene_text, "scenes", "scene-plan")
  return {
    "bundle": bundle,
    "chapter": chapter,
    "evidence_hits": evidence_hits,
    "evidence_text": evidence_text,
    "canon": canon,
    "scene_result": scene_result,
  }


def _continuation_write_messages(
  *,
  context_text: str,
  evidence_text: str,
  canon: dict[str, object],
  scene_result: ChapterWorkflowResult,
  instruction: str,
  target_words: int,
  support_text: str,
  candidate_label: str = "",
  candidate_hint: str = "",
) -> list[dict[str, object]]:
  scene_lines = []
  for index, item in enumerate(scene_result.scenes, start=1):
    scene_lines.append(
      f"{index}. {item.title}｜目标：{item.goal}｜冲突：{item.conflict}｜转折：{item.turn}"
    )
  messages: list[dict[str, object]] = [
    {"role": "system", "content": _CONTINUATION_WRITE_SYSTEM_PROMPT},
  ]
  if candidate_hint.strip():
    label = candidate_label.strip() or "候选版本"
    messages.append(
      {
        "role": "system",
        "content": f"这次正文候选的侧重点是：{label}。{candidate_hint.strip()}",
      }
    )
  messages.append(
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"原文证据块：\n{evidence_text}\n\n"
        f"承接简报：\n"
        f"摘要：{canon['summary']}\n"
        f"必须保留：\n{_compact_rules(canon['must_keep'])}\n"
        f"当前状态：\n{_compact_rules(canon['current_state'])}\n"
        f"表达约束：\n{_compact_rules(canon['voice_rules'])}\n"
        f"不要改动：\n{_compact_rules(canon['blocked_changes'])}\n\n"
        f"场景计划：\n{chr(10).join(scene_lines) if scene_lines else '无'}\n"
        f"用户补充：{instruction.strip() or '无'}\n"
        f"目标长度：约 {target_words} 字\n"
        f"{support_text or ''}"
      ).strip(),
    },
  )
  return messages


def _scene_plan_lines(scene_result: ChapterWorkflowResult) -> str:
  lines: list[str] = []
  for index, item in enumerate(scene_result.scenes, start=1):
    lines.append(
      f"{index}. {item.title}｜目标：{item.goal}｜冲突：{item.conflict}｜转折：{item.turn}"
    )
  return chr(10).join(lines) if lines else "无"


def _judge_continuation_dimension(
  settings: Settings,
  *,
  system_prompt: str,
  dimension: str,
  task_name: str,
  context_text: str,
  evidence_text: str,
  canon: dict[str, object],
  scene_result: ChapterWorkflowResult,
  content: str,
) -> dict[str, object]:
  judge_text = _invoke_model(
    settings,
    [
      {"role": "system", "content": system_prompt},
      {
        "role": "user",
        "content": (
          f"{context_text}\n\n"
          f"原文证据块：\n{evidence_text}\n\n"
          f"承接简报：\n"
          f"摘要：{canon['summary']}\n"
          f"必须保留：\n{_compact_rules(canon['must_keep'])}\n"
          f"当前状态：\n{_compact_rules(canon['current_state'])}\n"
          f"表达约束：\n{_compact_rules(canon['voice_rules'])}\n"
          f"不要改动：\n{_compact_rules(canon['blocked_changes'])}\n\n"
          f"场景计划：\n{_scene_plan_lines(scene_result)}\n\n"
          f"本轮只检查：{dimension}\n\n"
          f"待审正文：\n{content}"
        ).strip(),
      },
    ],
    task_name=task_name,
    max_tokens=1800,
    enable_thinking=True,
  )
  parsed = _parse_judge_payload(judge_text)
  return {
    **parsed,
    "dimension": dimension,
  }


def _judge_continuation(
  settings: Settings,
  *,
  context_text: str,
  evidence_text: str,
  canon: dict[str, object],
  scene_result: ChapterWorkflowResult,
  content: str,
) -> dict[str, object]:
  dimension_specs = [
    ("承接事实", _CONTINUATION_CANON_JUDGE_SYSTEM_PROMPT, "continuation_judge:canon"),
    ("人物口气", _CONTINUATION_VOICE_JUDGE_SYSTEM_PROMPT, "continuation_judge:voice"),
    ("可读性", _CONTINUATION_READER_JUDGE_SYSTEM_PROMPT, "continuation_judge:reader"),
  ]
  if load_config(settings).model_runtime.chapter_candidate_mode == "fast":
    dimension_specs = dimension_specs[:1]
  dimension_results: list[dict[str, object]] = []
  for dimension, system_prompt, task_name in dimension_specs:
    dimension_results.append(
      _judge_continuation_dimension(
        settings,
        system_prompt=system_prompt,
        dimension=dimension,
        task_name=task_name,
        context_text=context_text,
        evidence_text=evidence_text,
        canon=canon,
        scene_result=scene_result,
        content=content,
      )
    )

  ordered_dimension_results = dimension_results

  summaries: list[str] = []
  issues: list[dict[str, str]] = []
  rewrite_focus: list[str] = []
  rewrite_seen: set[str] = set()
  next_action = ""
  passed = True
  total_score = 0.0
  for result in ordered_dimension_results:
    label = str(result.get("dimension") or "").strip() or "审校"
    summary = str(result.get("summary") or "").strip()
    weight = float(_CONTINUATION_JUDGE_WEIGHTS.get(label, 0.0))
    score_value = result.get("score")
    score = float(score_value) if isinstance(score_value, (int, float)) else 0.0
    total_score += score * weight
    if summary:
      summaries.append(f"{label}（{score:.0f} 分）：{summary}")
    if not bool(result.get("passed")):
      passed = False
    if not next_action:
      next_action = str(result.get("next_action") or "").strip()
    for item in result.get("issues") or []:
      if not isinstance(item, dict):
        continue
      title = str(item.get("title") or "").strip() or "潜在问题"
      detail = str(item.get("detail") or "").strip() or title
      severity = str(item.get("severity") or "warning").strip() or "warning"
      issues.append(
        {
          "title": f"{label}：{title}",
          "detail": detail,
          "severity": severity,
        }
      )
    for item in result.get("rewrite_focus") or []:
      focus = str(item).strip()
      if not focus or focus in rewrite_seen:
        continue
      rewrite_seen.add(focus)
      rewrite_focus.append(focus)

  return {
    "summary": "\n".join(summaries).strip() or "已完成当前正文审校。",
    "score": round(total_score, 2),
    "passed": passed,
    "issues": issues,
    "rewrite_focus": rewrite_focus[:8],
    "next_action": next_action,
    "dimensions": ordered_dimension_results,
  }


def _generate_continuation_candidates(
  settings: Settings,
  *,
  prefix: str,
  context_text: str,
  evidence_text: str,
  canon: dict[str, object],
  scene_result: ChapterWorkflowResult,
  instruction: str,
  target_words: int,
  support_text: str,
  task_name_prefix: str,
  candidate_count: int | None = None,
) -> list[dict[str, object]]:
  runtime_mode = load_config(settings).model_runtime.chapter_candidate_mode
  resolved_candidate_count = max(1, candidate_count or len(_CONTINUATION_CANDIDATE_VARIANTS))
  if runtime_mode in {"fast", "standard"}:
    resolved_candidate_count = 1
  variants = _CONTINUATION_CANDIDATE_VARIANTS[:resolved_candidate_count]
  candidates: list[dict[str, object]] = []

  def build_candidate(index: int, variant: dict[str, object]) -> dict[str, object]:
    write_messages = _continuation_write_messages(
      context_text=context_text,
      evidence_text=evidence_text,
      canon=canon,
      scene_result=scene_result,
      instruction=instruction,
      target_words=target_words,
      support_text=support_text,
      candidate_label=str(variant.get("label") or ""),
      candidate_hint=str(variant.get("hint") or ""),
    )
    suffix = _invoke_partial_model(
      settings,
      write_messages,
      prefix=prefix,
      task_name=f"{task_name_prefix}:partial:{variant['id']}",
      temperature=float(variant.get("temperature") or 0.8),
      max_tokens=max(1200, target_words * 2),
      enable_thinking=False,
    )
    suffix = _strip_repeated_partial_prefix(prefix, suffix)
    content = f"{prefix}{suffix}".strip()
    judge = _judge_continuation(
      settings,
      context_text=context_text,
      evidence_text=evidence_text,
      canon=canon,
      scene_result=scene_result,
      content=content,
    )
    return {
      "index": index,
      "id": str(variant.get("id") or f"candidate-{index}"),
      "label": str(variant.get("label") or f"候选 {index}"),
      "content": content,
      "judge": judge,
    }

  for index, variant in enumerate(variants, start=1):
    candidates.append(build_candidate(index, variant))
  return candidates


def _choose_best_continuation_candidate(candidates: list[dict[str, object]]) -> dict[str, object]:
  if not candidates:
    raise RuntimeError("没有生成可用候选")

  def sort_key(candidate: dict[str, object]) -> tuple[float, float, float, float, float]:
    judge = candidate.get("judge")
    if not isinstance(judge, dict):
      return (0.0, 0.0, 0.0, 0.0, 0.0)
    issues = judge.get("issues")
    critical = 0
    warning = 0
    if isinstance(issues, list):
      for item in issues:
        if not isinstance(item, dict):
          continue
        severity = str(item.get("severity") or "").strip()
        if severity == "critical":
          critical += 1
        elif severity == "warning":
          warning += 1
    passed_rank = 1.0 if bool(judge.get("passed")) else 0.0
    score = float(judge.get("score") or 0.0)
    return (
      passed_rank,
      score,
      -float(critical),
      -float(warning),
      -float(int(candidate.get("index") or 0)),
    )

  return max(candidates, key=sort_key)


def _repair_continuation(
  settings: Settings,
  *,
  context_text: str,
  evidence_text: str,
  canon: dict[str, object],
  scene_result: ChapterWorkflowResult,
  content: str,
  rewrite_focus: list[str],
  support_text: str,
) -> str:
  repaired = _invoke_model(
    settings,
    [
      {"role": "system", "content": _CONTINUATION_REWRITE_SYSTEM_PROMPT},
      {
        "role": "user",
        "content": (
          f"{context_text}\n\n"
          f"原文证据块：\n{evidence_text}\n\n"
          f"承接简报：\n"
          f"摘要：{canon['summary']}\n"
          f"必须保留：\n{_compact_rules(canon['must_keep'])}\n"
          f"当前状态：\n{_compact_rules(canon['current_state'])}\n"
          f"表达约束：\n{_compact_rules(canon['voice_rules'])}\n"
          f"不要改动：\n{_compact_rules(canon['blocked_changes'])}\n\n"
          f"场景计划：\n{_scene_plan_lines(scene_result)}\n"
          f"返工重点：\n{_compact_rules(rewrite_focus)}\n"
          f"当前正文：\n{content}\n"
          f"{support_text or ''}"
        ).strip(),
      },
    ],
    task_name="continuation_rewrite",
    max_tokens=max(2400, len(content) // 2),
    enable_thinking=True,
  )
  repaired_result = _parse_content_payload(repaired)
  return repaired_result["content"]


def _continuation_segment_targets(target_words: int) -> list[int]:
  target = max(0, int(target_words or 0))
  if target <= _CONTINUATION_SINGLE_CALL_TARGET:
    return [target or 1_800]

  segment_count = max(2, math.ceil(target / _CONTINUATION_SINGLE_CALL_TARGET))
  base_target = target // segment_count
  extra_words = target % segment_count
  return [
    base_target + (1 if index < extra_words else 0)
    for index in range(segment_count)
  ]


def _content_length(text: str) -> int:
  return len(str(text or "").strip())


def _completion_threshold(target_words: int) -> int:
  target = max(0, int(target_words or 0))
  if target <= 0:
    return 0
  return max(1, int(target * _CONTINUATION_COMPLETION_RATIO))


def _next_section_target(current_words: int, completion_target_words: int) -> int:
  remaining = max(0, int(completion_target_words or 0) - max(0, int(current_words or 0)))
  if remaining <= 0:
    return _CONTINUATION_MIN_SECTION_TARGET
  return min(
    _CONTINUATION_SINGLE_CALL_TARGET,
    max(_CONTINUATION_MIN_SECTION_TARGET, remaining),
  )


def _segment_instruction(base_instruction: str, index: int, total: int, target_words: int) -> str:
  base = str(base_instruction or "").strip() or "请继续写当前章节。"
  return (
    f"{base}\n\n"
    f"分小节生成要求：这是第 {index}/{total} 小节，目标约 {target_words} 字。"
    "只写当前小节，承接前文继续推进；不要提前结束全章，段尾保留下一小节可继续发展的压力。"
  )


def _merge_segment_content(current_content: str, generated_content: str) -> str:
  current = str(current_content or "").strip()
  generated = str(generated_content or "").strip()
  if not current:
    return generated
  if not generated:
    return current
  if generated.startswith(current):
    return generated
  return f"{current.rstrip()}\n\n{generated.lstrip()}"


def _run_segmented_continuation_pipeline(
  settings: Settings,
  *,
  project_id: str,
  chapter_id: str,
  instruction: str,
  target_words: int,
  segment_targets: list[int],
  length_guidance: str,
  completion_target_words: int = 0,
  support_text: str = "",
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
  task_name_prefix: str = "chapter_generate",
  candidate_count: int = 1,
) -> dict[str, object]:
  plan = _generate_continuation_plan(
    settings,
    project_id=project_id,
    chapter_id=chapter_id,
    instruction=instruction,
    target_words=target_words,
    support_text=support_text,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  current_content = _continuation_prefix(plan["chapter"]).strip()
  canon = dict(plan["canon"])
  segment_reports: list[str] = []
  segment_results: list[dict[str, object]] = []
  total_candidates = 0
  repair_applied = False
  last_judge: dict[str, object] = {}
  last_candidate: dict[str, object] = {}
  section_targets = [max(1, int(item or 0)) for item in segment_targets if int(item or 0) > 0]
  if not section_targets:
    section_targets = [target_words or 1_800]
  completion_target = max(0, int(completion_target_words or 0))
  completion_threshold = _completion_threshold(completion_target)
  planned_section_count = len(section_targets)
  max_section_count = max(
    planned_section_count,
    min(
      _CONTINUATION_MAX_SECTION_COUNT,
      max(planned_section_count + 2, math.ceil(max(completion_target, target_words) / _CONTINUATION_MIN_SECTION_TARGET) + 2),
    ),
  )
  append_app_log(
    settings,
    "INFO",
    (
      f"{task_name_prefix}:segmented planned target={completion_target or target_words} "
      f"threshold={completion_threshold} segments={section_targets[:planned_section_count]}"
    ),
  )
  index = 0

  while index < len(section_targets) and index < max_section_count:
    index += 1
    segment_target = section_targets[index - 1]
    display_total = max(len(section_targets), index)
    segment_instruction = _segment_instruction(instruction, index, display_total, segment_target)
    segment_candidate_count = candidate_count if index == 1 else 1
    candidates = _generate_continuation_candidates(
      settings,
      prefix=current_content if current_content.endswith("\n") else f"{current_content}\n",
      context_text=plan["bundle"].context_text,
      evidence_text=str(plan["evidence_text"]),
      canon=canon,
      scene_result=plan["scene_result"],
      instruction=segment_instruction,
      target_words=segment_target,
      support_text=support_text,
      task_name_prefix=f"{task_name_prefix}:segment-{index:02d}",
      candidate_count=segment_candidate_count,
    )
    total_candidates += len(candidates)
    best_candidate = _choose_best_continuation_candidate(candidates)
    content = _merge_segment_content(current_content, str(best_candidate.get("content") or ""))
    judge = dict(best_candidate.get("judge") or {})
    repair_note = ""

    if not bool(judge.get("passed")) and judge.get("rewrite_focus"):
      if len(content) <= _CONTINUATION_REPAIR_CONTENT_LIMIT:
        content = _repair_continuation(
          settings,
          context_text=plan["bundle"].context_text,
          evidence_text=str(plan["evidence_text"]),
          canon=canon,
          scene_result=plan["scene_result"],
          content=content,
          rewrite_focus=[str(item) for item in judge.get("rewrite_focus") or []],
          support_text=support_text,
        )
        repair_applied = True
        repair_note = "，审校后已修订"
        judge = _judge_continuation(
          settings,
          context_text=plan["bundle"].context_text,
          evidence_text=str(plan["evidence_text"]),
          canon=canon,
          scene_result=plan["scene_result"],
          content=content,
        )
      else:
        repair_note = "，正文较长，已保留审校意见"

    current_content = content.strip()
    last_judge = judge
    last_candidate = best_candidate
    segment_summary = str(judge.get("summary") or "").strip()
    segment_reports.append(
      f"第 {index}/{display_total} 小节目标约 {segment_target} 字，"
      f"采用“{best_candidate.get('label') or '候选'}”，审校分 {judge.get('score') or '未知'}{repair_note}。"
      f"{segment_summary}"
    )
    segment_results.append(
      {
        "index": index,
        "target_words": segment_target,
        "actual_words": _content_length(current_content),
        "candidate_count": len(candidates),
        "selected_candidate_id": str(best_candidate.get("id") or ""),
        "selected_candidate_label": str(best_candidate.get("label") or ""),
        "judge": judge,
        "repair_note": repair_note,
      }
    )
    if completion_threshold > 0 and _content_length(current_content) >= completion_threshold:
      break
    if index >= len(section_targets) and completion_threshold > 0 and index < max_section_count:
      section_targets.append(_next_section_target(_content_length(current_content), completion_target))

  actual_words = _content_length(current_content)
  completion_status = ""
  if completion_threshold > 0:
    completion_status = "complete" if actual_words >= completion_threshold else "under_target"
  append_app_log(
    settings,
    "INFO",
    (
      f"{task_name_prefix}:segmented completed segments={len(segment_results)} "
      f"actual={actual_words} status={completion_status or 'checked'}"
    ),
  )
  summary_parts = [
    str(canon.get("summary") or "").strip(),
    length_guidance,
    (
      f"目标约 {completion_target or target_words} 字，"
      f"按章节容量先规划 {planned_section_count} 个小节：{', '.join(str(item) for item in segment_targets)} 字。"
    ),
    (
      f"实际生成 {len(segment_results)} 个小节，当前正文约 {actual_words} 字。"
      if segment_results
      else ""
    ),
    (
      f"当前仍低于目标容量，建议继续追加小节。"
      if completion_status == "under_target"
      else ""
    ),
    *segment_reports,
    "有段落审校后已修订一次。" if repair_applied else "",
  ]
  checklist = [
    *_object_text_list(canon.get("must_keep")),
    *_object_text_list(canon.get("blocked_changes")),
  ][:8]
  return {
    "content": current_content,
    "summary": "\n".join(item for item in summary_parts if item),
    "next_action": str(last_judge.get("next_action") or canon.get("next_action") or "").strip(),
    "headline": "章节分段初稿已修订" if repair_applied else "章节分段初稿已生成",
    "scenes": list(getattr(plan["scene_result"], "scenes", []) or []),
    "checklist": checklist,
    "brief": canon,
    "candidate_count": total_candidates,
    "selected_candidate_id": str(last_candidate.get("id") or ""),
    "selected_candidate_label": str(last_candidate.get("label") or ""),
    "candidate_judge": last_judge,
    "repair_applied": repair_applied,
    "evidence_hits": plan["evidence_hits"],
    "segmented": True,
    "segment_count": len(segment_results),
    "planned_segment_count": planned_section_count,
    "segment_targets": section_targets[:len(segment_results)],
    "planned_segment_targets": segment_targets,
    "completion_target_words": completion_target,
    "completion_threshold_words": completion_threshold,
    "actual_words": actual_words,
    "completion_status": completion_status,
    "segments": segment_results,
  }


def _run_continuation_pipeline(
  settings: Settings,
  *,
  project_id: str,
  chapter_id: str,
  instruction: str,
  target_words: int,
  support_text: str = "",
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
  task_name_prefix: str = "chapter_generate",
  candidate_count: int = 1,
  prefer_project_budget: bool = False,
  complete_chapter: bool = False,
) -> dict[str, object]:
  project_detail = get_project_detail(settings, project_id)
  chapter_for_length = next((item for item in project_detail.chapters if item.id == chapter_id), None)
  explicit_target = explicit_length_target(instruction)
  explicit_length_requested = instruction_requests_explicit_length(instruction)
  full_chapter_requested = instruction_requests_full_chapter(instruction)
  average_target = chapter_average_word_target(project_detail)
  current_words = chapter_text_length(chapter_for_length)
  if explicit_target > 0:
    target_words = explicit_target
  elif full_chapter_requested or complete_chapter:
    full_target = full_chapter_generation_target(project_detail, chapter_for_length)
    if full_target > 0:
      target_words = full_target
  target_words = recommended_chapter_generation_target(
    project_detail,
    chapter_for_length,
    requested_target=target_words,
    prefer_project_budget=prefer_project_budget and not explicit_length_requested and not complete_chapter,
  )
  if complete_chapter and explicit_target <= 0:
    full_target = full_chapter_generation_target(project_detail, chapter_for_length)
    if full_target > 0 and target_words < full_target:
      target_words = full_target
  length_guidance = build_chapter_length_guidance(project_detail, chapter_for_length, generation_target=target_words)
  segment_targets = _continuation_segment_targets(target_words)
  completion_target_words = 0
  if full_chapter_requested or complete_chapter:
    if explicit_target > 0 and full_chapter_requested:
      completion_target_words = explicit_target
    elif average_target > 0:
      completion_target_words = average_target
    else:
      completion_target_words = current_words + target_words
  elif len(segment_targets) > 1:
    completion_target_words = current_words + target_words

  if len(segment_targets) > 1:
    return _run_segmented_continuation_pipeline(
      settings,
      project_id=project_id,
      chapter_id=chapter_id,
      instruction=instruction,
      target_words=target_words,
      segment_targets=segment_targets,
      length_guidance=length_guidance,
      completion_target_words=completion_target_words,
      support_text=support_text,
      characters_involved=characters_involved,
      key_items=key_items,
      scene_location=scene_location,
      time_constraint=time_constraint,
      task_name_prefix=task_name_prefix,
      candidate_count=candidate_count,
    )

  if candidate_count > 1:
    plan = _generate_continuation_plan(
      settings,
      project_id=project_id,
      chapter_id=chapter_id,
      instruction=instruction,
      target_words=target_words,
      support_text=support_text,
      characters_involved=characters_involved,
      key_items=key_items,
      scene_location=scene_location,
      time_constraint=time_constraint,
    )
    prefix = _continuation_prefix(plan["chapter"])
    candidates = _generate_continuation_candidates(
      settings,
      prefix=prefix,
      context_text=plan["bundle"].context_text,
      evidence_text=str(plan["evidence_text"]),
      canon=dict(plan["canon"]),
      scene_result=plan["scene_result"],
      instruction=instruction,
      target_words=target_words,
      support_text=support_text,
      task_name_prefix=task_name_prefix,
      candidate_count=candidate_count,
    )
    best_candidate = _choose_best_continuation_candidate(candidates)
    content = str(best_candidate.get("content") or "").strip()
    judge = dict(best_candidate.get("judge") or {})
    repair_applied = False
    if not bool(judge.get("passed")) and judge.get("rewrite_focus"):
      content = _repair_continuation(
        settings,
        context_text=plan["bundle"].context_text,
        evidence_text=str(plan["evidence_text"]),
        canon=dict(plan["canon"]),
        scene_result=plan["scene_result"],
        content=content,
        rewrite_focus=[str(item) for item in judge.get("rewrite_focus") or []],
        support_text=support_text,
      )
      repair_applied = True
      judge = _judge_continuation(
        settings,
        context_text=plan["bundle"].context_text,
        evidence_text=str(plan["evidence_text"]),
        canon=dict(plan["canon"]),
        scene_result=plan["scene_result"],
        content=content,
      )

    canon = dict(plan["canon"])
    summary_parts = [
      str(canon.get("summary") or "").strip(),
      length_guidance,
      f"已生成 {len(candidates)} 个候选，并由承接事实、人物口气、可读性三类审校择优。",
      str(judge.get("summary") or "").strip(),
      "候选审校后已修订一次。" if repair_applied else "",
    ]
    checklist = [
      *_object_text_list(canon.get("must_keep")),
      *_object_text_list(canon.get("blocked_changes")),
    ][:8]
    return {
      "content": content,
      "summary": "\n".join(item for item in summary_parts if item),
      "next_action": str(judge.get("next_action") or canon.get("next_action") or "").strip(),
      "headline": "章节初稿已修订" if repair_applied else "章节初稿已生成",
      "scenes": list(getattr(plan["scene_result"], "scenes", []) or []),
      "checklist": checklist,
      "brief": canon,
      "candidate_count": len(candidates),
      "selected_candidate_id": str(best_candidate.get("id") or ""),
      "selected_candidate_label": str(best_candidate.get("label") or ""),
      "candidate_judge": judge,
      "repair_applied": repair_applied,
      "evidence_hits": plan["evidence_hits"],
    }

  plan = _generate_continuation_brief(
    settings,
    project_id=project_id,
    chapter_id=chapter_id,
    instruction=instruction,
    target_words=target_words,
    support_text=support_text,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  prefix = _continuation_prefix(plan["chapter"])
  suffix = _invoke_partial_model(
    settings,
    _continuation_single_write_messages(
      context_text=plan["bundle"].context_text,
      evidence_text=str(plan["evidence_text"]),
      brief=dict(plan["brief"]),
      instruction=instruction,
      target_words=target_words,
      support_text=support_text,
    ),
    prefix=prefix,
    task_name=f"{task_name_prefix}:partial",
    temperature=0.82,
    max_tokens=max(1200, target_words * 2),
    enable_thinking=False,
  )
  suffix = _strip_repeated_partial_prefix(prefix, suffix)
  content = f"{prefix}{suffix}".strip()
  conflict_report = _check_continuation_conflicts(
    settings,
    context_text=plan["bundle"].context_text,
    evidence_text=str(plan["evidence_text"]),
    brief=dict(plan["brief"]),
    content=content,
  )
  repair_applied = False
  if _conflict_report_has_hard_conflict(conflict_report):
    content = _repair_continuation_with_guard(
      settings,
      context_text=plan["bundle"].context_text,
      evidence_text=str(plan["evidence_text"]),
      brief=dict(plan["brief"]),
      conflict_report=conflict_report,
      content=content,
      support_text=support_text,
    )
    repair_applied = True
    conflict_report = _check_continuation_conflicts(
      settings,
      context_text=plan["bundle"].context_text,
      evidence_text=str(plan["evidence_text"]),
      brief=dict(plan["brief"]),
      content=content,
    )
  summary_parts = [
    str(dict(plan["brief"]).get("summary") or "").strip(),
    length_guidance,
    str(conflict_report.get("summary") or "").strip(),
    "检测到硬冲突，已修订一次。" if repair_applied else "",
  ]
  summary = "\n".join(item for item in summary_parts if item)
  brief = dict(plan["brief"])
  checklist = [
    *_object_text_list(brief.get("hard_constraints")),
    *_object_text_list(brief.get("avoid_conflicts")),
  ][:8]
  return {
    "content": content,
    "summary": summary or "这一章已经按承接简报续写并完成连续性检查。",
    "next_action": str(conflict_report.get("next_action") or brief.get("next_action") or "").strip(),
    "headline": "章节初稿已修订" if repair_applied else "章节初稿已生成",
    "scenes": [],
    "checklist": checklist,
    "brief": brief,
    "conflict_report": conflict_report,
    "repair_applied": repair_applied,
    "evidence_hits": plan["evidence_hits"],
  }


def _normalize_workflow_mode(mode: str) -> str:
  normalized = mode.strip().lower()
  if normalized not in _WORKFLOW_MODE_LABELS:
    raise RuntimeError("章节工作流模式无效")
  return normalized


def _build_workflow_instruction(mode: str, chapter_title: str, target_words: int) -> str:
  if mode == "diagnose":
    return (
      f"请判断《{chapter_title}》当前最该优先处理的问题，明确是节奏、冲突升级、信息揭示还是结尾钩子。"
      "给出直接可执行的修改建议。"
    )
  if mode == "scenes":
    return (
      f"请把《{chapter_title}》拆成 4 到 6 个场景。每个场景都写明目标、冲突和转折。"
      "重点是能直接拿去写。"
    )
  return (
    f"请围绕《{chapter_title}》直接续写一段可保存的正文，目标长度约 {target_words} 字。"
    "必须接着当前章节或上一章已经成立的剧情往后写。"
    "第一行必须是 Markdown 标题。"
  )


def _chapter_context_text(settings: Settings, payload: ChapterWorkflowRequest) -> str:
  bundle = build_project_context_bundle(
    settings,
    payload.project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=payload.chapter_id,
    knowledge_query=" ".join(
      item for item in [payload.chapter_id, payload.instruction] if item.strip()
    ),
    task_pack_kind="continuation",
    task_instruction=payload.instruction,
    rewrite_mode=payload.mode if payload.mode == "draft" else "",
  )
  project_detail = bundle.project_detail
  chapter = bundle.chapter
  if chapter is None:
    raise RuntimeError("当前章节不存在")

  return (
    f"模式：{_WORKFLOW_MODE_LABELS[payload.mode]}\n"
    f"系统任务：{_build_workflow_instruction(payload.mode, chapter.title, payload.target_words)}\n"
    f"用户补充：{payload.instruction.strip() or '无'}\n\n"
    f"{bundle.context_text}\n"
  )


def _build_chapter_workflow_messages(settings: Settings, payload: ChapterWorkflowRequest) -> list[dict[str, str]]:
  chapter_context = _chapter_context_text(settings, payload)
  messages = [
    {
      "role": "system",
      "content": _CHAPTER_WORKFLOW_SYSTEM_PROMPT,
    },
  ]
  support = build_prompt_support(
    settings,
    task_key="chapter",
    project_id=payload.project_id,
    chapter_id=payload.chapter_id,
  )
  if support:
    messages.append({"role": "system", "content": f"额外要求：{support}"})
  messages.append(
    {
      "role": "user",
      "content": chapter_context,
    }
  )
  return messages


def _scene_list_from_payload(payload: dict[str, object]) -> list[ChapterWorkflowScene]:
  raw_scenes = payload.get("scenes")
  if not isinstance(raw_scenes, list):
    return []

  scenes: list[ChapterWorkflowScene] = []
  for item in raw_scenes:
    if not isinstance(item, dict):
      continue
    title = _string_from_keys(item, "title", "场景", "name")
    goal = _string_from_keys(item, "goal", "目标")
    conflict = _string_from_keys(item, "conflict", "冲突")
    turn = _string_from_keys(item, "turn", "转折", "推进")
    if not any([title, goal, conflict, turn]):
      continue
    scenes.append(
      ChapterWorkflowScene(
        title=title or "未命名场景",
        goal=goal or "补足本场目标",
        conflict=conflict or "补足本场冲突",
        turn=turn or "补足本场转折",
      )
    )

  return scenes


def _fallback_workflow_result(text: str, mode: str, task_id: str) -> ChapterWorkflowResult:
  cleaned = _strip_code_fence(text)
  lines = [item.strip() for item in cleaned.splitlines() if item.strip()]
  headline = lines[0] if lines else _WORKFLOW_MODE_LABELS[mode]
  summary = lines[1] if len(lines) > 1 else cleaned
  checklist = [item.strip(" -0123456789.、）)") for item in lines[2:6]]
  return ChapterWorkflowResult(
    task_id=task_id,
    mode=mode,
    headline=headline,
    summary=summary,
    checklist=[item for item in checklist if item],
    scenes=[],
    draft=cleaned if mode == "draft" else "",
    next_action=lines[6] if len(lines) > 6 else "",
  )


def _parse_chapter_workflow_payload(text: str, mode: str, task_id: str) -> ChapterWorkflowResult:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    return _fallback_workflow_result(text, mode, task_id)

  headline = _string_from_keys(payload, "headline", "判断", "标题")
  summary = _string_from_keys(payload, "summary", "分析", "建议")
  checklist = _string_list_from_keys(payload, "checklist", "要点", "清单")
  scenes = _scene_list_from_payload(payload)
  draft = _string_from_keys(payload, "draft", "正文", "续写正文")
  next_action = _string_from_keys(payload, "next_action", "下一步", "行动建议")

  if not headline and not summary:
    return _fallback_workflow_result(text, mode, task_id)

  if mode != "draft":
    draft = ""
  if mode == "draft" and not draft:
    return _fallback_workflow_result(text, mode, task_id)

  return ChapterWorkflowResult(
    task_id=task_id,
    mode=mode,
    headline=headline or _WORKFLOW_MODE_LABELS[mode],
    summary=summary or headline,
    checklist=checklist,
    scenes=scenes if mode == "scenes" else scenes[:2],
    draft=draft,
    next_action=next_action,
  )


def _generate_chapter_workflow(
  settings: Settings,
  payload: ChapterWorkflowRequest,
  task_id: str,
) -> ChapterWorkflowResult:
  mode = _normalize_workflow_mode(payload.mode)
  normalized_payload = payload.model_copy(update={"mode": mode})
  if mode == "draft":
    support = build_prompt_support(
      settings,
      task_key="chapter",
      project_id=normalized_payload.project_id,
      chapter_id=normalized_payload.chapter_id,
    )
    pipeline = _run_continuation_pipeline(
      settings,
      project_id=normalized_payload.project_id,
      chapter_id=normalized_payload.chapter_id,
      instruction=normalized_payload.instruction,
      target_words=normalized_payload.target_words,
      support_text=support,
      task_name_prefix="chapter_workflow:draft",
      prefer_project_budget=normalized_payload.target_words <= 1_800,
    )
    return ChapterWorkflowResult(
      task_id=task_id,
      mode=mode,
      headline=str(pipeline["headline"] or _WORKFLOW_MODE_LABELS[mode]),
      summary=str(pipeline["summary"]),
      checklist=[str(item) for item in pipeline["checklist"]],
      scenes=list(pipeline["scenes"]),
      draft=str(pipeline["content"]),
      next_action=str(pipeline["next_action"]),
    )
  content = _invoke_model(
    settings,
    _build_chapter_workflow_messages(settings, normalized_payload),
    task_name=f"chapter_workflow:{mode}",
  )
  return _parse_chapter_workflow_payload(content, mode, task_id)


async def architecture_stream(settings: Settings, payload: ArchitectureRequest):
  task_id = str(uuid4())
  yield encode_sse("started", {"task_id": task_id})

  steps = [
    "读取模型设置",
    "整理作品信息和写作意图",
    "向模型发送架构请求",
    "解析模型返回结果",
  ]

  for index, message in enumerate(steps[:3], start=1):
    yield encode_sse(
      "progress",
      {
        "step": index,
        "total": len(steps),
        "message": message,
      },
    )
    await asyncio.sleep(0.1)

  try:
    result = await asyncio.to_thread(_generate_architecture, settings, payload, task_id)
  except Exception as error:
    yield encode_sse(
      "error",
      {
        "task_id": task_id,
        "message": str(error),
      },
    )
    yield encode_sse("done", {"task_id": task_id, "status": "failed"})
    return

  yield encode_sse(
    "progress",
    {
      "step": len(steps),
      "total": len(steps),
      "message": steps[-1],
    },
  )
  yield encode_sse("result", result.model_dump(mode="json"))
  yield encode_sse("done", {"task_id": task_id, "status": "completed"})


async def architecture_step_stream(settings: Settings, payload: ArchitectureStepRequest):
  task_id = str(uuid4())
  yield encode_sse("started", {"task_id": task_id})

  steps = [
    "读取项目设定和当前草稿",
    "检索相关资料和章节上下文",
    "向模型发送分步架构请求",
    "整理当前步骤结果",
  ]

  for index, message in enumerate(steps[:3], start=1):
    yield encode_sse(
      "progress",
      {
        "step": index,
        "total": len(steps),
        "message": message,
      },
    )
    await asyncio.sleep(0.1)

  try:
    result = await asyncio.to_thread(_generate_architecture_step, settings, payload, task_id)
  except Exception as error:
    yield encode_sse(
      "error",
      {
        "task_id": task_id,
        "message": str(error),
      },
    )
    yield encode_sse("done", {"task_id": task_id, "status": "failed"})
    return

  yield encode_sse(
    "progress",
    {
      "step": len(steps),
      "total": len(steps),
      "message": steps[-1],
    },
  )
  yield encode_sse("result", result.model_dump(mode="json"))
  yield encode_sse("done", {"task_id": task_id, "status": "completed"})


async def chapter_workflow_stream(settings: Settings, payload: ChapterWorkflowRequest):
  task_id = str(uuid4())
  yield encode_sse("started", {"task_id": task_id})

  steps = [
    "读取项目上下文",
    "检索相关设定和章节线索",
    "向模型发送章节工作流请求",
    "整理可执行结果",
  ]

  for index, message in enumerate(steps[:3], start=1):
    yield encode_sse(
      "progress",
      {
        "step": index,
        "total": len(steps),
        "message": message,
      },
    )
    await asyncio.sleep(0.1)

  try:
    result = await asyncio.to_thread(_generate_chapter_workflow, settings, payload, task_id)
  except Exception as error:
    yield encode_sse(
      "error",
      {
        "task_id": task_id,
        "message": str(error),
      },
    )
    yield encode_sse("done", {"task_id": task_id, "status": "failed"})
    return

  yield encode_sse(
    "progress",
    {
      "step": len(steps),
      "total": len(steps),
      "message": steps[-1],
    },
  )
  yield encode_sse("result", result.model_dump(mode="json"))
  yield encode_sse("done", {"task_id": task_id, "status": "completed"})
