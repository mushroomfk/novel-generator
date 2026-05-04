from __future__ import annotations

import asyncio
import json
import os
import time
from urllib import error as urllib_error
from urllib import request as urllib_request
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
from novel_backend.services.context_builder import build_project_context_bundle, build_prompt_support, compact_text, project_documents_map
from novel_backend.services.log_service import append_app_log, append_prompt_history
from novel_backend.services.model_error_service import classify_model_error
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
  "plot_structure": "只输出整本推进结构、阶段目标和关键转折，不要写人物小传。",
  "character_state": "只输出当前阶段人物状态、关系变化和后续隐患。",
  "blueprint": "输出可直接写入项目文件的章节蓝图，按章节列出标题、目标和钩子。",
  "global_summary": "输出滚动摘要，浓缩已定设定和目前推进状态，长度控制在 120 到 220 字。",
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
7. hard_constraints 写必须服从的硬事实，优先级为：手动记忆、当前章节和上一章末尾、导入资料和自动记忆。
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
5. 必须沿用输入里给出的连续性证据、人物关系和承接简报。
""".strip()

_CONTINUATION_WRITE_SYSTEM_PROMPT = """
你是中文小说续写写手。

写作要求：
1. 你会收到当前章节已经确认的前缀，请直接顺着这个前缀往后写，不要重写前文。
2. 只输出接在前缀后面的正文，不要解释，不要分析，不要输出 JSON。
3. 必须承接已经给出的证据、人物关系、承接简报和文风约束。
4. 不要擅自改人名、关系、事件结果和时间顺序。
5. 结尾要留下能继续推进的压力，不要用总结句收尾。
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


def _request_chat_completion(endpoint: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
  body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  request = urllib_request.Request(endpoint, data=body, method="POST")
  request.add_header("Content-Type", "application/json")
  request.add_header("Authorization", f"Bearer {api_key}")

  try:
    with urllib_request.urlopen(request, timeout=120) as response:
      raw_text = response.read().decode("utf-8")
  except urllib_error.HTTPError as error:
    error_text = error.read().decode("utf-8", errors="ignore")
    message = error_text or str(error)
    raise RuntimeError(f"模型请求失败: {error.code} {message}") from error
  except urllib_error.URLError as error:
    raise RuntimeError(f"模型请求失败: {error.reason}") from error

  try:
    parsed = json.loads(raw_text)
  except json.JSONDecodeError as error:
    raise RuntimeError("模型返回的不是合法 JSON") from error

  if not isinstance(parsed, dict):
    raise RuntimeError("模型返回格式不正确")

  return parsed


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
  try:
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
      },
    )
    append_app_log(settings, f"{task_name} completed in {elapsed:.3f}s")
    return content
  except Exception as error:
    elapsed = round(time.perf_counter() - started, 3)
    classified_error = classify_model_error(error)
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
      "core_seed": _string_from_keys(payload, "core_seed", "故事切口", "核心种子"),
      "character_design": _string_from_keys(payload, "character_design", "人物关系", "角色设计"),
      "world_building": _string_from_keys(payload, "world_building", "世界氛围", "世界观"),
      "plot_structure": _string_from_keys(payload, "plot_structure", "推进方向", "情节结构"),
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


def _architecture_step_context(settings: Settings, payload: ArchitectureStepRequest) -> tuple[object, dict[str, str], int, str]:
  project_detail = build_project_context_bundle(settings, payload.project_id).project_detail
  documents = _architecture_document_map(project_detail, payload.workspace)
  target_chapters = project_detail.target_chapters + payload.new_chapters if payload.mode == "continue" else project_detail.target_chapters
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
  knowledge_text = "\n".join(
    f"- {item.section}（{item.match_type}）：{item.preview}"
    for item in bundle.knowledge_hits
  ) or "无"
  dream_text = build_project_dream_prompt_block(project_detail)
  dream_block = f"{dream_text}\n" if dream_text else ""
  context_text = (
    f"当前模式：{'续写扩展' if payload.mode == 'continue' else '初始架构'}\n"
    f"当前章节数：{project_detail.target_chapters}\n"
    f"目标章节数：{target_chapters}\n"
    f"当前步骤：{_ARCHITECTURE_STEP_LABELS[payload.step]}\n"
    f"{bundle.context_text}\n"
    f"{dream_block}"
    f"相关检索：\n{knowledge_text}"
  )
  return project_detail, documents, target_chapters, context_text


def _build_architecture_step_messages(settings: Settings, payload: ArchitectureStepRequest) -> list[dict[str, str]]:
  project_detail, documents, target_chapters, context_text = _architecture_step_context(settings, payload)
  current_content = documents.get(payload.step, "")
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
        f"当前已有草稿：\n{current_content or '无'}\n\n"
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
  content = _string_from_keys(parsed, "content", "正文", "result")
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


def _generate_architecture_step(settings: Settings, payload: ArchitectureStepRequest, task_id: str) -> ArchitectureStepResult:
  content = _invoke_model(
    settings,
    _build_architecture_step_messages(settings, payload),
    task_name=f"architecture_step:{payload.step}:{payload.mode}",
  )
  result = _parse_architecture_step_payload(content, payload, task_id)
  if payload.mode == "continue":
    project_detail = get_project_detail(settings, payload.project_id)
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
  ]
  return " ".join(item.strip() for item in pieces if item and item.strip())


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
  bundle = build_project_context_bundle(
    settings,
    project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=chapter_id,
    knowledge_query=instruction,
    task_pack_kind="continuation",
    task_instruction=instruction,
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
  bundle = build_project_context_bundle(
    settings,
    project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=chapter_id,
    knowledge_query=instruction,
    task_pack_kind="continuation",
    task_instruction=instruction,
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
  dimension_results = [
    _judge_continuation_dimension(
      settings,
      system_prompt=_CONTINUATION_CANON_JUDGE_SYSTEM_PROMPT,
      dimension="承接事实",
      task_name="continuation_judge:canon",
      context_text=context_text,
      evidence_text=evidence_text,
      canon=canon,
      scene_result=scene_result,
      content=content,
    ),
    _judge_continuation_dimension(
      settings,
      system_prompt=_CONTINUATION_VOICE_JUDGE_SYSTEM_PROMPT,
      dimension="人物口气",
      task_name="continuation_judge:voice",
      context_text=context_text,
      evidence_text=evidence_text,
      canon=canon,
      scene_result=scene_result,
      content=content,
    ),
    _judge_continuation_dimension(
      settings,
      system_prompt=_CONTINUATION_READER_JUDGE_SYSTEM_PROMPT,
      dimension="可读性",
      task_name="continuation_judge:reader",
      context_text=context_text,
      evidence_text=evidence_text,
      canon=canon,
      scene_result=scene_result,
      content=content,
    ),
  ]

  summaries: list[str] = []
  issues: list[dict[str, str]] = []
  rewrite_focus: list[str] = []
  rewrite_seen: set[str] = set()
  next_action = ""
  passed = True
  total_score = 0.0
  for result in dimension_results:
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
    "dimensions": dimension_results,
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
) -> list[dict[str, object]]:
  candidates: list[dict[str, object]] = []
  for index, variant in enumerate(_CONTINUATION_CANDIDATE_VARIANTS, start=1):
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
    content = f"{prefix}{suffix}".strip()
    judge = _judge_continuation(
      settings,
      context_text=context_text,
      evidence_text=evidence_text,
      canon=canon,
      scene_result=scene_result,
      content=content,
    )
    candidates.append(
      {
        "index": index,
        "id": str(variant.get("id") or f"candidate-{index}"),
        "label": str(variant.get("label") or f"候选 {index}"),
        "content": content,
        "judge": judge,
      }
    )
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
) -> dict[str, object]:
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
  support = build_prompt_support(settings, task_key="chapter")
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
    support = build_prompt_support(settings, task_key="chapter")
    pipeline = _run_continuation_pipeline(
      settings,
      project_id=normalized_payload.project_id,
      chapter_id=normalized_payload.chapter_id,
      instruction=normalized_payload.instruction,
      target_words=normalized_payload.target_words,
      support_text=support,
      task_name_prefix="chapter_workflow:draft",
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
