from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import (
  ProjectDreamCandidate,
  ProjectDreamReport,
  ProjectMemoryEntryInput,
)
from novel_backend.services.config_service import load_config
from novel_backend.services.log_service import append_app_log, append_prompt_history
from novel_backend.services.model_error_service import classify_model_error
from novel_backend.services.model_transport_service import request_json
from novel_backend.services.project_memory_service import append_project_memory, append_system_project_memory
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")
_STOPWORDS = {
  "现在",
  "当前",
  "已经",
  "继续",
  "保持",
  "人物",
  "章节",
  "内容",
  "线索",
  "世界",
  "设定",
  "阶段",
  "目标",
  "最近",
  "当前章",
  "故事",
  "作品",
  "主角",
}


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: str, limit: int = 160) -> str:
  normalized = " ".join((text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _compact_lines(text: str, *, limit: int = 3, line_limit: int = 80) -> list[str]:
  lines: list[str] = []
  for raw_line in (text or "").splitlines():
    line = raw_line.strip().lstrip("-#*0123456789.、）)")
    if not line:
      continue
    compacted = _compact_text(line, line_limit)
    if compacted and compacted not in lines:
      lines.append(compacted)
    if len(lines) >= limit:
      break
  return lines


def build_project_dream_signature(*, documents: list[object], chapters: list[object]) -> str:
  raw_parts: list[str] = []
  for item in documents:
    raw_parts.append(f"doc::{item.key}::{(item.content or '').strip()}")
  for item in chapters:
    if not item.exists and not (item.content or "").strip():
      continue
    raw_parts.append(f"chapter::{item.id}::{item.title}::{(item.content or item.preview or '').strip()}")
  return hashlib.sha1("\n".join(raw_parts).encode("utf-8")).hexdigest()


def project_dream_path(project_dir: Path) -> Path:
  return project_dir / "project_dreams.json"


def load_project_dream_report(
  project_dir: Path,
  *,
  source_signature: str = "",
) -> ProjectDreamReport | None:
  payload = read_json(project_dream_path(project_dir), None)
  if not isinstance(payload, dict):
    return None
  try:
    report = ProjectDreamReport.model_validate(payload)
  except Exception:
    return None
  if source_signature and report.source_signature and report.source_signature != source_signature:
    return report.model_copy(update={"is_stale": True})
  return report.model_copy(update={"is_stale": False})


def save_project_dream_report(project_dir: Path, report: ProjectDreamReport) -> ProjectDreamReport:
  payload = report.model_dump(mode="json")
  payload["is_stale"] = False
  atomic_write_json(project_dream_path(project_dir), payload)
  return report.model_copy(update={"is_stale": False})


def build_project_dream_prompt_block(project_detail, *, max_chars: int = 900) -> str:
  report = getattr(project_detail.story_overview, "dream_report", None)
  if report is None or report.is_stale:
    return ""

  summary = _compact_text(report.summary, min(max_chars, 320))
  if not summary:
    return ""

  lines = [f"最近梦境线索：{summary}"]
  if report.themes:
    lines.append(f"反复主题：{' / '.join(report.themes[:4])}")
  if report.open_questions:
    questions = "\n".join(
      f"- {_compact_text(item, 100)}"
      for item in report.open_questions[:3]
      if str(item).strip()
    )
    if questions:
      lines.append(f"待验证问题：\n{questions}")
  return "\n".join(lines).strip()


def _category(value: str) -> str:
  return value if value in {"硬规则", "偏好", "连续性", "警告", "目标"} else "连续性"


def _candidate_id(title: str, category: str, content: str) -> str:
  raw = "::".join([title.strip(), category.strip(), content.strip()])
  return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _top_themes(project_detail, limit: int = 5) -> list[str]:
  counts: dict[str, int] = {}
  source_texts = [
    *(item.name for item in getattr(project_detail.story_overview, "props", [])[:4]),
    *(item.name for item in getattr(project_detail.story_overview, "scenes", [])[:4]),
    *(item.name for item in getattr(project_detail.story_overview, "events", [])[:4]),
    *(item.name for item in getattr(project_detail.story_overview, "organizations", [])[:4]),
    *(item.name for item in getattr(project_detail.story_overview, "locations", [])[:4]),
    *[(item.content or "") for item in getattr(project_detail.story_overview, "documents", [])[:4]],
    *[(item.preview or item.content or "") for item in getattr(project_detail, "chapters", []) if item.exists][-3:],
  ]
  for text in source_texts:
    for token in _TOKEN_RE.findall(text or ""):
      if token in _STOPWORDS:
        continue
      counts[token] = counts.get(token, 0) + 1
  ordered = sorted(counts.items(), key=lambda item: (item[1], len(item[0]), item[0]), reverse=True)
  return [token for token, _count in ordered[:limit]]


def _find_memory_entry(project_detail, entry_id: str):
  entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  return next((item for item in entries if item.id == entry_id), None)


def _fallback_candidates(project_detail) -> list[ProjectDreamCandidate]:
  candidates: list[ProjectDreamCandidate] = []
  world_rules = _find_memory_entry(project_detail, "auto-world-rules")
  open_threads = _find_memory_entry(project_detail, "auto-open-threads")
  stage_goal = _find_memory_entry(project_detail, "auto-stage-goal")

  if world_rules and world_rules.content.strip():
    content = _compact_text(world_rules.content, 140)
    candidates.append(
      ProjectDreamCandidate(
        id=_candidate_id("规则复核", "硬规则", content),
        title="规则复核",
        category="硬规则",
        content=content,
        rationale="世界规则在近期文本里反复出现，值得继续锁住。",
        confidence=0.68,
      )
    )

  if open_threads and open_threads.content.strip():
    first_line = _compact_lines(open_threads.content, limit=1, line_limit=120)
    if first_line:
      content = f"后续章节要回应：{first_line[0]}"
      candidates.append(
        ProjectDreamCandidate(
          id=_candidate_id("悬念追踪", "警告", content),
          title="悬念追踪",
          category="警告",
          content=content,
          rationale="近期多处文本都在围绕这条未回收线索。",
          confidence=0.72,
        )
      )

  if stage_goal and stage_goal.content.strip():
    first_line = _compact_lines(stage_goal.content, limit=1, line_limit=120)
    if first_line:
      content = f"当前阶段先完成：{first_line[0]}"
      candidates.append(
        ProjectDreamCandidate(
          id=_candidate_id("阶段推进", "目标", content),
          title="阶段推进",
          category="目标",
          content=content,
          rationale="蓝图和滚动摘要都还在指向这个阶段目标。",
          confidence=0.65,
        )
      )

  return candidates[:4]


def _fallback_dream_report(project_detail, *, focus: str, source_signature: str) -> ProjectDreamReport:
  themes = _top_themes(project_detail, limit=5)
  recent_progress = _find_memory_entry(project_detail, "auto-recent-progress")
  character_states = _find_memory_entry(project_detail, "auto-character-states")
  open_threads = _find_memory_entry(project_detail, "auto-open-threads")
  stage_goal = _find_memory_entry(project_detail, "auto-stage-goal")

  insights: list[str] = []
  if recent_progress and recent_progress.content.strip():
    lines = _compact_lines(recent_progress.content, limit=2, line_limit=100)
    if lines:
      insights.append(f"近期推进主要集中在：{'；'.join(lines)}")
  if character_states and character_states.content.strip():
    lines = _compact_lines(character_states.content, limit=2, line_limit=100)
    if lines:
      insights.append(f"主要人物当前都处在被线索和关系拉扯的状态：{'；'.join(lines)}")
  if stage_goal and stage_goal.content.strip():
    lines = _compact_lines(stage_goal.content, limit=2, line_limit=90)
    if lines:
      insights.append(f"现阶段最该守住的推进方向是：{'；'.join(lines)}")

  open_questions: list[str] = []
  if open_threads and open_threads.content.strip():
    for item in _compact_lines(open_threads.content, limit=3, line_limit=90):
      open_questions.append(f"{item} 什么时候回收，才能不削弱前面埋下的劲？")

  if not insights:
    insights.append("现有文本已经形成了稳定的主线、人物状态和悬念链，但还需要定期回看它们是不是在往同一个方向推进。")
  if not open_questions:
    open_questions.append("当前主线最晚应该在哪个阶段出现一次明确升级？")

  summary_parts = []
  if themes:
    summary_parts.append(f"这轮做梦反复浮出来的主题是 {' / '.join(themes[:4])}")
  if open_questions:
    summary_parts.append(f"最值得继续盯的，是 {_compact_text(open_questions[0], 80)}")
  summary = "。".join(summary_parts) or "这轮做梦把近期项目里的反复主题、悬念和阶段推进重新拎了一遍。"

  return ProjectDreamReport(
    engine="heuristic",
    generated_at=_now_iso(),
    source_signature=source_signature,
    focus=focus.strip(),
    summary=summary,
    themes=themes,
    insights=insights[:4],
    open_questions=open_questions[:4],
    memory_candidates=_fallback_candidates(project_detail),
    source_chapter_ids=[item.id for item in getattr(project_detail, "chapters", []) if item.exists][-5:],
    source_document_keys=[item.key for item in getattr(project_detail.story_overview, "documents", []) if (item.content or "").strip()],
  )


def _chat_completions_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  return f"{normalized}/chat/completions" if not normalized.endswith("/chat/completions") else normalized


def _resolve_api_key(settings: Settings) -> str:
  config = load_config(settings).model
  candidates = [
    config.api_key,
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
  raise RuntimeError("未设置模型 API Key，请在设置里填写，或设置 NOVEL_MODEL_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY / OPENAI_API_KEY。")


def _request_chat_completion(endpoint: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
  return request_json(
    endpoint,
    api_key,
    payload,
    failure_label="模型请求失败",
    invalid_json_message="模型返回的不是合法 JSON",
    invalid_format_message="模型返回格式不正确",
  )


def _extract_message_content(payload: dict[str, object]) -> str:
  choices = payload.get("choices")
  if not isinstance(choices, list) or not choices:
    raise RuntimeError("模型返回为空")
  choice = choices[0]
  if not isinstance(choice, dict):
    raise RuntimeError("模型返回格式不正确")
  message = choice.get("message")
  if not isinstance(message, dict):
    raise RuntimeError("模型返回格式不正确")
  content = message.get("content")
  if not isinstance(content, str):
    raise RuntimeError("模型没有返回文本内容")
  return content.strip()


def _invoke_model(
  settings: Settings,
  messages: list[dict[str, str]],
  *,
  task_name: str,
  temperature: float = 0.3,
  max_tokens: int = 1400,
) -> str:
  config = load_config(settings).model
  api_key = _resolve_api_key(settings)
  endpoint = _chat_completions_endpoint(config.base_url)
  chat_payload = {
    "model": config.model_name,
    "messages": messages,
    "temperature": temperature,
    "max_tokens": max_tokens,
  }
  prompt_text = "\n\n".join(
    f"[{item.get('role', 'user')}] {item.get('content', '')}"
    for item in messages
  ).strip()
  started = time.perf_counter()
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


def _extract_json_object(text: str) -> dict[str, object] | None:
  cleaned = (text or "").strip()
  if not cleaned:
    return None
  try:
    payload = json.loads(cleaned)
    return payload if isinstance(payload, dict) else None
  except json.JSONDecodeError:
    pass

  start = cleaned.find("{")
  end = cleaned.rfind("}")
  if start < 0 or end <= start:
    return None
  try:
    payload = json.loads(cleaned[start : end + 1])
    return payload if isinstance(payload, dict) else None
  except json.JSONDecodeError:
    return None


def _string(value: object) -> str:
  return value.strip() if isinstance(value, str) else ""


def _string_list(value: object, *, limit: int = 6) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    text = _string(item)
    if text:
      items.append(text)
    if len(items) >= limit:
      break
  return items


def _model_messages(project_detail, *, focus: str) -> list[dict[str, str]]:
  documents = {
    item.key: (item.content or "").strip()
    for item in getattr(project_detail.story_overview, "documents", []) or []
  }
  memory_entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  recent_chapters = [item for item in getattr(project_detail, "chapters", []) if item.exists][-4:]

  memory_block = "\n".join(
    f"- {item.category} / {item.title or '未命名'}：{_compact_text(item.content, 140)}"
    for item in memory_entries[:8]
    if (item.content or "").strip()
  ) or "无"
  chapter_block = "\n".join(
    f"- 第 {item.index} 章《{item.title}》：{_compact_text(item.preview or item.content or '', 180)}"
    for item in recent_chapters
  ) or "无"
  entity_block = "\n".join(
    filter(
      None,
      [
        f"事件：{' / '.join(item.name for item in getattr(project_detail.story_overview, 'events', [])[:4]) or '无'}",
        f"地点：{' / '.join(item.name for item in getattr(project_detail.story_overview, 'locations', [])[:4]) or '无'}",
        f"组织：{' / '.join(item.name for item in getattr(project_detail.story_overview, 'organizations', [])[:4]) or '无'}",
        f"道具：{' / '.join(item.name for item in getattr(project_detail.story_overview, 'props', [])[:4]) or '无'}",
      ],
    )
  )

  user_content = (
    f"作品：{project_detail.name}\n"
    f"类型：{project_detail.genre}\n"
    f"目标章节数：{project_detail.target_chapters}\n"
    f"本轮聚焦：{focus.strip() or '无'}\n\n"
    f"核心种子：{_compact_text(documents.get('core_seed', ''), 220) or '无'}\n"
    f"世界设定：{_compact_text(documents.get('world_building', ''), 280) or '无'}\n"
    f"情节骨架：{_compact_text(documents.get('plot_structure', ''), 280) or '无'}\n"
    f"章节蓝图：{_compact_text(documents.get('blueprint', ''), 280) or '无'}\n"
    f"滚动摘要：{_compact_text(documents.get('global_summary', ''), 280) or '无'}\n\n"
    f"项目记忆：\n{memory_block}\n\n"
    f"最近章节：\n{chapter_block}\n\n"
    f"世界要素：\n{entity_block or '无'}"
  )
  return [
    {
      "role": "system",
      "content": (
        "你是中文长篇小说的夜间做梦整理器。"
        "不要写正文，不要改设定，不要发散成新剧情。"
        "你要做的是从现有项目里找出反复出现的主题、未回收的悬念、潜在的关系拉扯和当前阶段最该守住的推进方向。"
        "只输出一个 JSON 对象。"
        "JSON 字段固定为：summary、themes、insights、open_questions、memory_candidates。"
        "themes 是 2 到 5 个短词。"
        "insights 是 2 到 4 条中文判断。"
        "open_questions 是 2 到 4 条后续要继续盯的问题。"
        "memory_candidates 是 0 到 4 条候选，每项包含 title、category、content、rationale、confidence。"
        "category 只能是 硬规则、偏好、连续性、警告、目标。"
        "content 必须是项目级提醒，不能是新编剧情。"
      ),
    },
    {"role": "user", "content": user_content},
  ]


def _parse_model_report(text: str, project_detail, *, focus: str, source_signature: str) -> ProjectDreamReport | None:
  payload = _extract_json_object(text)
  if not isinstance(payload, dict):
    return None

  themes = _string_list(payload.get("themes"), limit=5)
  insights = _string_list(payload.get("insights"), limit=4)
  open_questions = _string_list(payload.get("open_questions"), limit=4)
  raw_candidates = payload.get("memory_candidates")
  candidates: list[ProjectDreamCandidate] = []
  if isinstance(raw_candidates, list):
    for raw in raw_candidates[:4]:
      if not isinstance(raw, dict):
        continue
      title = _string(raw.get("title")) or "梦境候选"
      category = _category(_string(raw.get("category")))
      content = _compact_text(_string(raw.get("content")), 140)
      if not content:
        continue
      rationale = _compact_text(_string(raw.get("rationale")), 100)
      try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
      except Exception:
        confidence = 0.0
      candidates.append(
        ProjectDreamCandidate(
          id=_candidate_id(title, category, content),
          title=title,
          category=category,
          content=content,
          rationale=rationale,
          confidence=round(confidence, 2),
        )
      )

  summary = _compact_text(_string(payload.get("summary")), 240)
  if not summary and not insights:
    return None

  return ProjectDreamReport(
    engine="model",
    generated_at=_now_iso(),
    source_signature=source_signature,
    focus=focus.strip(),
    summary=summary or "这轮做梦整理出了一些值得继续盯的慢线索。",
    themes=themes,
    insights=insights,
    open_questions=open_questions,
    memory_candidates=candidates,
    source_chapter_ids=[item.id for item in getattr(project_detail, "chapters", []) if item.exists][-5:],
    source_document_keys=[item.key for item in getattr(project_detail.story_overview, "documents", []) if (item.content or "").strip()],
  )


def generate_project_dream_report(
  settings: Settings,
  project_detail,
  *,
  focus: str = "",
  use_model: bool = True,
) -> ProjectDreamReport:
  source_signature = build_project_dream_signature(
    documents=getattr(project_detail.story_overview, "documents", []) or [],
    chapters=getattr(project_detail, "chapters", []) or [],
  )
  fallback_report = _fallback_dream_report(project_detail, focus=focus, source_signature=source_signature)
  if not use_model:
    return fallback_report
  try:
    content = _invoke_model(
      settings,
      _model_messages(project_detail, focus=focus),
      task_name="project_dreaming",
      temperature=0.25,
      max_tokens=1400,
    )
  except Exception:
    return fallback_report

  parsed_report = _parse_model_report(
    content,
    project_detail,
    focus=focus,
    source_signature=source_signature,
  )
  if parsed_report is None:
    return fallback_report
  if not parsed_report.memory_candidates:
    parsed_report = parsed_report.model_copy(update={"memory_candidates": fallback_report.memory_candidates})
  if not parsed_report.themes:
    parsed_report = parsed_report.model_copy(update={"themes": fallback_report.themes})
  return parsed_report


def promote_project_dream_candidates(
  project_dir: Path,
  candidate_ids: list[str],
  *,
  target_source: str = "manual",
) -> int:
  report = load_project_dream_report(project_dir)
  if report is None:
    return 0

  selected_ids = {item.strip() for item in candidate_ids if item.strip()}
  selected_candidates = [
    item for item in report.memory_candidates
    if item.id in selected_ids and not item.promoted_at
  ]
  if not selected_candidates:
    return 0

  memory_inputs = [
    ProjectMemoryEntryInput(
      id=f"dream-{item.id}" if target_source == "system" else None,
      title=item.title,
      category=item.category,
      content=item.content,
    )
    for item in selected_candidates
  ]
  if target_source == "system":
    append_system_project_memory(project_dir, memory_inputs, reason="dream_auto_promote")
  else:
    append_project_memory(project_dir, memory_inputs)

  promoted_at = _now_iso()
  updated_candidates = [
    item.model_copy(update={"promoted_at": promoted_at}) if item.id in selected_ids and not item.promoted_at else item
    for item in report.memory_candidates
  ]
  save_project_dream_report(
    project_dir,
    report.model_copy(update={"memory_candidates": updated_candidates}),
  )
  return len(selected_candidates)
