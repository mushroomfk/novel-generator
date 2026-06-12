from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import (
  ChapterReviewDimension,
  ChapterReviewIssue,
  ChapterReviewReport,
)
from novel_backend.services.config_service import load_config
from novel_backend.services.humanize_service import analyze_humanize_text
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.obsidian_service import (
  _parse_chapter_number,
  obsidian_note_available_for_chapter,
  obsidian_source_signature_for_chapter,
  scoped_obsidian_note_records_for_chapter,
)
from novel_backend.services.style_service import get_style
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_CHAPTER_REVIEW_DIRNAME = "chapter_reviews"
_REVIEW_SYSTEM_PROMPT = """
你是中文长篇小说章节回归编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：summary、suggestions、consistency、structure、plot、suspense、style。
3. consistency / structure / plot / suspense / style 都是对象，字段固定为：summary、strengths、issues、suggestions。
4. strengths 是 0 到 3 条短句数组。
5. issues 是数组，每项包含 level、title、detail。level 只能是 info、warning、critical。
6. 如果某一项暂时无法判断，要在 summary 里明确写“无法判断”，不要编造。
7. 重点只围绕当前章节，不要复述整本剧情。
""".strip()

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")
_CHAPTER_NUMBER_IN_TEXT_RE = re.compile(r"第\s*([0-9０-９零〇一二两三四五六七八九十百千]+)\s*章")
_TOKEN_STOPWORDS = {
  "现在",
  "当前",
  "已经",
  "还是",
  "因为",
  "所以",
  "他们",
  "我们",
  "这里",
  "主角",
  "人物",
  "章节",
  "内容",
  "故事",
  "作品",
  "本章",
  "这一",
  "这个",
}
_HOOK_TOKENS = (
  "却",
  "但",
  "然而",
  "忽然",
  "突然",
  "竟然",
  "原来",
  "未",
  "还没",
  "不知",
  "疑点",
  "秘密",
  "真相",
  "钥匙",
  "线索",
  "失踪",
)
_HANDOFF_REQUIRED_MARKERS = (
  "不能忘",
  "必须",
  "务必",
  "需要",
  "应当",
  "应该",
  "要",
  "继续",
  "承接",
  "推进",
  "处理",
  "追问",
  "追查",
  "查明",
  "兑现",
  "确认",
  "交代",
  "写到",
)
_HANDOFF_NEGATIVE_MARKERS = ("不要", "不得", "禁止", "不可", "不许")
_HANDOFF_GENERIC_TERMS = (
  "下一章",
  "下章",
  "后续",
  "当前章",
  "本章",
  "不能忘",
  "必须",
  "务必",
  "需要",
  "应当",
  "应该",
  "要",
  "继续",
  "承接",
  "推进",
  "处理",
  "追问",
  "追查",
  "查明",
  "兑现",
  "确认",
  "交代",
  "写到",
  "安排",
  "保留",
  "让",
  "把",
)
_PROJECT_MEMORY_RULE_CATEGORIES = {"硬规则", "警告"}
_PROJECT_MEMORY_NEGATIVE_MARKERS = ("不要", "不得", "禁止", "不可", "不许", "不能", "不会", "避免")
_PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS = {
  "不要",
  "不得",
  "禁止",
  "不可",
  "不许",
  "不能",
  "不会",
  "避免",
  "提前",
  "直接",
  "公开",
  "揭示",
  "揭开",
  "揭露",
  "暴露",
  "写出",
  "写成",
  "改成",
  "改名",
  "变成",
  "叫成",
  "说明",
  "说出",
  "透露",
  "出现",
  "身份",
  "真相",
  "主角",
  "角色",
  "人物",
  "写",
  "让",
  "把",
}
_PROJECT_MEMORY_STATE_RULES = (
  ("死亡", ("死亡", "死去", "死掉", "死了", "丧命", "遇害", "被杀", "被害", "阵亡", "牺牲")),
  ("叛变", ("叛变", "背叛", "倒戈", "投敌")),
  ("黑化", ("黑化", "堕落")),
  ("离队", ("离队", "离开队伍", "退出队伍", "脱离队伍")),
  ("暴露身份", ("暴露身份", "身份暴露", "公开身份", "主动暴露")),
)
_PROJECT_MEMORY_REVEAL_ROLES = ("主谋", "真凶", "幕后主使", "幕后黑手", "凶手", "反派")
_PROJECT_MEMORY_REVEAL_ACTIONS = ("揭示", "揭开", "揭露", "暴露", "公开", "透露", "点破", "说明", "说出")
_PROJECT_MEMORY_TRANSFER_ACTIONS = ("交给", "交出", "交还", "移交", "转交", "交付", "送给", "递给", "献给", "交到", "卖给")
_PROJECT_MEMORY_REPLACEMENT_ACTIONS = ("改名为", "改成", "写成", "叫成", "变成", "称为")
_PROJECT_MEMORY_NEGATED_STATE_PREFIXES = (
  "没有",
  "没",
  "未",
  "并未",
  "并没有",
  "尚未",
  "不会",
  "不能",
  "不曾",
  "不是",
  "无需",
  "不要",
)
_CONFLICT_TOKENS = (
  "追",
  "拦",
  "逼",
  "查",
  "逃",
  "打",
  "争",
  "骗",
  "瞒",
  "抢",
  "杀",
  "问",
  "撞",
  "怀疑",
  "威胁",
  "拒绝",
)


def _compact_text(text: str, limit: int = 180) -> str:
  normalized = " ".join((text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _split_sentences(text: str) -> list[str]:
  return [item.strip() for item in _SENTENCE_RE.findall(text or "") if item.strip()]


def _body_text(chapter) -> str:
  content = str(getattr(chapter, "content", "") or "").strip()
  if not content:
    return ""
  lines = content.splitlines()
  if lines and lines[0].lstrip().startswith("#"):
    return "\n".join(lines[1:]).strip()
  return content


def _body_paragraphs(text: str) -> list[str]:
  return [item.strip() for item in re.split(r"\n\s*\n", text or "") if item.strip()]


def _tokens(text: str, *, limit: int = 16) -> list[str]:
  counts: dict[str, int] = {}
  for token in _TOKEN_RE.findall(text or ""):
    if token in _TOKEN_STOPWORDS:
      continue
    counts[token] = counts.get(token, 0) + 1
  ordered = sorted(counts.items(), key=lambda item: (item[1], len(item[0]), item[0]), reverse=True)
  return [token for token, _count in ordered[:limit]]


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  result: list[str] = []
  for item in items:
    value = str(item or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    result.append(value)
  return result


def _score_status(score: int) -> str:
  if score >= 85:
    return "good"
  if score >= 65:
    return "watch"
  return "risk"


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _strip_code_fence(text: str) -> str:
  stripped = str(text or "").strip()
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
  return embedded if isinstance(embedded, dict) else None


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
      lines = [item.strip(" -0123456789.、）)") for item in value.splitlines() if item.strip()]
      cleaned = [item for item in lines if item]
      if cleaned:
        return cleaned
  return []


def _chapter_review_dir(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / _CHAPTER_REVIEW_DIRNAME


def _chapter_review_path(project_dir: Path, chapter_id: str) -> Path:
  return _chapter_review_dir(project_dir) / f"{chapter_id}.json"


def save_chapter_review(project_dir: Path, review: ChapterReviewReport) -> ChapterReviewReport:
  review_dir = _chapter_review_dir(project_dir)
  review_dir.mkdir(parents=True, exist_ok=True)
  payload = review.model_dump(mode="json")
  payload["is_stale"] = False
  atomic_write_json(_chapter_review_path(project_dir, review.chapter_id), payload)
  return review.model_copy(update={"is_stale": False})


def delete_chapter_review(project_dir: Path, chapter_id: str) -> None:
  _chapter_review_path(project_dir, chapter_id).unlink(missing_ok=True)


def _documents_map(project_detail) -> dict[str, str]:
  return {
    item.key: str(item.content or "").strip()
    for item in getattr(project_detail.story_overview, "documents", []) or []
  }


def _chapter_or_none(project_detail, chapter_id: str):
  return next((item for item in getattr(project_detail, "chapters", []) if item.id == chapter_id), None)


def _memory_entry(project_detail, entry_id: str):
  entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  return next((item for item in entries if item.id == entry_id), None)


def _chapter_timeline_entities(project_detail, chapter_index: int) -> dict[str, list[str]]:
  overview = getattr(project_detail, "story_overview", None)
  characters: list[str] = []
  events: list[str] = []
  locations: list[str] = []
  props: list[str] = []
  organizations: list[str] = []
  scenes: list[str] = []
  timeline_count = 0

  for character in getattr(overview, "characters", []) or []:
    chapter_entries = [
      entry for entry in (getattr(character, "timeline", []) or [])
      if getattr(entry, "chapter_index", None) == chapter_index and getattr(entry, "source_label", "") == "章节正文"
    ]
    if chapter_entries:
      characters.append(character.name)
      timeline_count += len(chapter_entries)

  def collect(kind: str) -> list[str]:
    items = getattr(overview, kind, []) or []
    return [
      item.name
      for item in items
      if chapter_index in (getattr(item, "chapter_indexes", []) or [])
    ]

  events = collect("events")
  locations = collect("locations")
  props = collect("props")
  organizations = collect("organizations")
  scenes = collect("scenes")
  return {
    "characters": characters,
    "events": events,
    "locations": locations,
    "props": props,
    "organizations": organizations,
    "scenes": scenes,
    "timeline_count": [str(timeline_count)],
  }


def _blueprint_section(blueprint_text: str, chapter_index: int, chapter_title: str) -> str:
  if not blueprint_text.strip():
    return ""
  lines = blueprint_text.splitlines()
  current: list[str] = []
  in_section = False
  heading_patterns = [
    re.compile(rf"^\s*#+\s*第\s*{chapter_index}\s*章"),
    re.compile(rf"^\s*#+\s*第\s*{chapter_index}\s*章《{re.escape(chapter_title)}》"),
    re.compile(rf"^\s*#+\s*{re.escape(chapter_title)}\s*$"),
  ]
  other_heading = re.compile(r"^\s*#+\s*第\s*\d+\s*章")
  for line in lines:
    stripped = line.strip()
    if any(pattern.search(stripped) for pattern in heading_patterns):
      in_section = True
      current.append(stripped)
      continue
    if in_section and other_heading.search(stripped):
      break
    if in_section:
      current.append(line.rstrip())
  return "\n".join(item for item in current if item.strip()).strip()


def _style_sample_text(detail) -> str:
  parts = [
    str(getattr(detail, "source_sample", "") or "").strip(),
    str(getattr(detail, "calibration_reference", "") or "").strip(),
  ]
  return "\n".join(item for item in parts if item).strip()


def _text_stats(text: str) -> dict[str, object]:
  sentences = _split_sentences(text)
  if not sentences:
    return {
      "avg_sentence_length": 0.0,
      "short_sentence_ratio": 0.0,
      "dialogue_ratio": 0.0,
      "question_ratio": 0.0,
      "imagery": [],
      "paragraph_count": 0,
      "sentence_count": 0,
    }
  sentence_lengths = [len(re.sub(r"\s+", "", item)) for item in sentences]
  avg_sentence_length = round(sum(sentence_lengths) / len(sentence_lengths), 1)
  short_sentence_ratio = round(sum(1 for item in sentence_lengths if item <= 18) / len(sentence_lengths), 2)
  question_ratio = round(sum(1 for item in sentences if "？" in item or "?" in item) / len(sentences), 2)
  dialogue_ratio = round((text.count("“") + text.count("\"")) / max(len(sentences), 1), 2)
  return {
    "avg_sentence_length": avg_sentence_length,
    "short_sentence_ratio": short_sentence_ratio,
    "dialogue_ratio": dialogue_ratio,
    "question_ratio": question_ratio,
    "imagery": _tokens(text, limit=6),
    "paragraph_count": len(_body_paragraphs(text)),
    "sentence_count": len(sentences),
  }


def _issue_penalty(level: str) -> int:
  if level == "critical":
    return 26
  if level == "warning":
    return 12
  return 4


def _parse_issue(item) -> ChapterReviewIssue | None:
  if not isinstance(item, dict):
    return None
  title = _string_from_keys(item, "title", "问题")
  detail = _string_from_keys(item, "detail", "说明", "analysis")
  if not title and not detail:
    return None
  return ChapterReviewIssue(
    level=_string_from_keys(item, "level") or "warning",
    title=title or "待留意问题",
    detail=detail or title,
  )


def _parse_model_dimension(payload, key: str) -> dict[str, object] | None:
  if not isinstance(payload, dict):
    return None
  raw = payload.get(key)
  if not isinstance(raw, dict):
    return None
  issues = [issue for issue in (_parse_issue(item) for item in raw.get("issues", [])) if issue is not None]
  return {
    "summary": _string_from_keys(raw, "summary", "结论"),
    "strengths": _string_list_from_keys(raw, "strengths", "亮点", "highlights"),
    "issues": issues,
    "suggestions": _string_list_from_keys(raw, "suggestions", "actions", "下一步"),
  }


def _build_review_guard_context(settings: Settings, project_detail, chapter):
  try:
    from novel_backend.services.continuity_guard_service import build_continuity_guard_context

    return build_continuity_guard_context(
      settings,
      project_id=project_detail.id,
      project_detail=project_detail,
      chapter=chapter,
      instruction="章节核验：检查本章是否和项目记忆、最近剧情、导入资料存在连续性冲突。",
    )
  except Exception as error:
    append_app_log(settings, f"chapter review continuity guard fallback for {project_detail.id}/{chapter.id}: {error}")
    return None


def _resolve_independent_review_model(settings: Settings) -> dict[str, object] | None:
  from novel_backend.services.generation_service import _chat_completions_endpoint

  config = load_config(settings).review_model
  api_key = os.environ.get("NOVEL_REVIEW_MODEL_API_KEY", "").strip()
  base_url = os.environ.get("NOVEL_REVIEW_MODEL_BASE_URL", "").strip()
  model_name = os.environ.get("NOVEL_REVIEW_MODEL_NAME", "").strip()
  max_tokens = int(os.environ.get("NOVEL_REVIEW_MODEL_MAX_TOKENS", "") or config.max_tokens)
  temperature_text = os.environ.get("NOVEL_REVIEW_MODEL_TEMPERATURE", "").strip()
  temperature = float(temperature_text) if temperature_text else config.temperature
  if not api_key and config.enabled:
    api_key = config.api_key.strip()
  if not base_url and config.enabled:
    base_url = config.base_url.strip()
  if not model_name and config.enabled:
    model_name = config.model_name.strip()
  if not api_key or not base_url or not model_name:
    return None
  return {
    "endpoint": _chat_completions_endpoint(base_url),
    "api_key": api_key,
    "model_name": model_name,
    "max_tokens": max_tokens,
    "temperature": temperature,
  }


def _parse_review_model_content(content: str, *, source: str) -> dict[str, object] | None:
  payload = _extract_json_object(content)
  if isinstance(payload, dict):
    payload["__model_source"] = source
    return payload
  cleaned = _strip_code_fence(content)
  if cleaned.strip():
    return {"summary": _compact_text(cleaned, 220), "suggestions": [], "__model_source": source}
  return None


def _call_model_review(
  settings: Settings,
  project_detail,
  chapter,
  *,
  style_name: str,
  style_context: str,
  blueprint_section: str,
  stage_goal: str,
  open_threads: list[str],
  guard_context,
) -> dict[str, object] | None:
  docs = _documents_map(project_detail)
  previous_chapter = next(
    (
      item for item in getattr(project_detail, "chapters", [])
      if item.index == chapter.index - 1 and item.exists and str(item.content or "").strip()
    ),
    None,
  )
  memory_entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  memory_block = "\n".join(
    f"- {item.title or item.id}：{_compact_text(item.content, 90)}"
    for item in memory_entries[:8]
    if str(item.content or "").strip()
  ) or "无"
  guard_evidence_text = str(getattr(guard_context, "evidence_text", "") or "").strip() or "无"
  threads_block = "\n".join(f"- {item}" for item in open_threads[:4]) or "无"
  prompt = (
    f"作品：{project_detail.name}\n"
    f"类型：{project_detail.genre}\n"
    f"核心种子：{_compact_text(docs.get('core_seed', ''), 220) or '无'}\n"
    f"情节骨架：{_compact_text(docs.get('plot_structure', ''), 260) or '无'}\n"
    f"人物状态：{_compact_text(docs.get('character_state', ''), 220) or '无'}\n"
    f"滚动摘要：{_compact_text(docs.get('global_summary', ''), 220) or '无'}\n"
    f"当前章节：第 {chapter.index} 章《{chapter.title}》\n"
    f"上一章末尾：{_compact_text(str(getattr(previous_chapter, 'content', '') or ''), 260) if previous_chapter else '无'}\n"
    f"本章蓝图：{_compact_text(blueprint_section, 260) or '无'}\n"
    f"当前阶段目标：{_compact_text(stage_goal, 220) or '无'}\n"
    f"别丢的悬念：\n{threads_block}\n"
    f"项目记忆：\n{memory_block}\n"
    f"连续性证据包（与续写链路共用）：\n{guard_evidence_text}\n"
    f"文风方案：{style_name or '未设置'}\n"
    f"{style_context or '文风额外信息：无'}\n\n"
    f"当前章节正文：\n{str(getattr(chapter, 'content', '') or '').strip()}\n\n"
    "请从一致性、结构、剧情推进、悬念和文风五个维度做回归核验。"
  )
  messages = [
    {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
    {"role": "user", "content": prompt},
  ]
  independent_model = _resolve_independent_review_model(settings)
  if independent_model is not None:
    from novel_backend.services.generation_service import _extract_message_content, _request_chat_completion

    try:
      payload: dict[str, object] = {
        "model": str(independent_model["model_name"]),
        "messages": messages,
        "max_tokens": int(independent_model["max_tokens"]),
      }
      if independent_model.get("temperature") is not None:
        payload["temperature"] = float(independent_model["temperature"])
      with model_runtime_slot(settings, lane="chat", task_name="chapter_review:evaluator"):
        response_payload = _request_chat_completion(
          str(independent_model["endpoint"]),
          str(independent_model["api_key"]),
          payload,
        )
    except Exception as error:
      mark_model_runtime_cooldown(settings, "chat", str(error))
      raise
    return _parse_review_model_content(_extract_message_content(response_payload), source="review_model")

  from novel_backend.services.generation_service import _invoke_model

  content = _invoke_model(
    settings,
    messages,
    task_name="chapter_review",
  )
  return _parse_review_model_content(content, source="primary_model")


def _model_dimension_score(model_dimension: dict[str, object], *, base: int = 82) -> int:
  score = base + min(12, len(model_dimension.get("strengths", [])) * 4)
  for issue in model_dimension.get("issues", []):
    score -= _issue_penalty(issue.level)
  return max(0, min(100, score))


def _dimension(
  dimension_id: str,
  label: str,
  score: int,
  summary: str,
  *,
  highlights: list[str] | None = None,
  issues: list[ChapterReviewIssue] | None = None,
  status: str | None = None,
) -> ChapterReviewDimension:
  return ChapterReviewDimension(
    id=dimension_id,
    label=label,
    score=max(0, min(100, int(score))),
    status=status or _score_status(score),
    summary=summary.strip(),
    highlights=[item for item in (highlights or []) if str(item).strip()][:4],
    issues=(issues or [])[:4],
  )


def _fallback_consistency_dimension(project_detail, chapter, model_dimension: dict[str, object] | None) -> ChapterReviewDimension:
  issues: list[ChapterReviewIssue] = []
  highlights: list[str] = []
  previous_chapter = next(
    (
      item for item in getattr(project_detail, "chapters", [])
      if item.index == chapter.index - 1 and item.exists and str(item.content or "").strip()
    ),
    None,
  )
  current_entities = _chapter_timeline_entities(project_detail, chapter.index)
  current_characters = set(current_entities["characters"])
  if previous_chapter is not None:
    previous_entities = _chapter_timeline_entities(project_detail, previous_chapter.index)
    previous_characters = set(previous_entities["characters"])
    shared = sorted(current_characters & previous_characters)
    if shared:
      highlights.append(f"和上一章继续挂在同一批人物上：{' / '.join(shared[:3])}")
    elif previous_characters and current_characters:
      issues.append(
        ChapterReviewIssue(
          level="warning",
          title="与上一章人物线衔接偏弱",
          detail="当前章和上一章没有明显共享人物，最好再确认是不是故意切线。",
        )
      )
  if not current_characters:
    issues.append(
      ChapterReviewIssue(
        level="warning",
        title="人物识别偏弱",
        detail="这一章没有抽到稳定人物，后续查连续性会比较吃力。",
      )
    )
  if model_dimension is not None:
    issues = [*model_dimension.get("issues", []), *issues]
    highlights = [*model_dimension.get("strengths", []), *highlights]
    score = _model_dimension_score(model_dimension, base=84) - (8 if len(current_characters) == 0 else 0)
    summary = str(model_dimension.get("summary") or "本章的一致性需要继续盯。")
  else:
    score = 76 - sum(_issue_penalty(item.level) for item in issues)
    summary = "当前没有接上模型核验，先按人物和章节衔接做基础回看。"
  return _dimension("consistency", "一致性", score, summary, highlights=highlights, issues=issues)


def _structure_dimension(chapter, model_dimension: dict[str, object] | None) -> ChapterReviewDimension:
  text = _body_text(chapter)
  stats = _text_stats(text)
  score = 70
  issues: list[ChapterReviewIssue] = []
  highlights: list[str] = []
  last_sentence = _split_sentences(text)[-1] if _split_sentences(text) else ""
  has_hook = ("？" in last_sentence or "?" in last_sentence or any(token in last_sentence for token in _HOOK_TOKENS))
  has_conflict = any(token in text for token in _CONFLICT_TOKENS)
  if stats["paragraph_count"] >= 4:
    score += 8
    highlights.append(f"段落数 {stats['paragraph_count']}，节奏有层次")
  else:
    issues.append(ChapterReviewIssue(level="warning", title="段落层次偏少", detail="这章的段落切分不多，容易读成一口气平推。"))
  if stats["sentence_count"] >= 10:
    score += 8
  else:
    issues.append(ChapterReviewIssue(level="warning", title="有效句数偏少", detail="正文体量还不够，很多推进来不及展开。"))
  if has_conflict:
    score += 6
    highlights.append("章节里已经有明显的对抗或阻力")
  else:
    issues.append(ChapterReviewIssue(level="warning", title="冲突抬升不够", detail="本章能看到动作，但阻力还不够集中。"))
  if has_hook:
    score += 8
    highlights.append("结尾留下了继续往下读的钩子")
  else:
    issues.append(ChapterReviewIssue(level="info", title="结尾钩子偏弱", detail="章末最好再留半步悬念或新的不安。"))
  if model_dimension is not None:
    score = round(score * 0.45 + _model_dimension_score(model_dimension, base=82) * 0.55)
    highlights = [*model_dimension.get("strengths", []), *highlights]
    issues = [*model_dimension.get("issues", []), *issues]
    summary = str(model_dimension.get("summary") or "本章结构需要继续打磨。")
  else:
    summary = (
      f"这章大致有 {stats['paragraph_count']} 个段落、{stats['sentence_count']} 句。"
      f"{' 章末有钩子。' if has_hook else ' 章末的钩子还不够。'}"
    )
  return _dimension("structure", "结构与节奏", score, summary, highlights=highlights, issues=issues)


def _keyword_overlap(text_a: str, text_b: str) -> float:
  tokens_a = set(_tokens(text_a, limit=12))
  tokens_b = set(_tokens(text_b, limit=12))
  if not tokens_a or not tokens_b:
    return 0.0
  return round(len(tokens_a & tokens_b) / max(min(len(tokens_a), len(tokens_b)), 1), 2)


def _plot_dimension(chapter, blueprint_section: str, stage_goal: str, model_dimension: dict[str, object] | None) -> ChapterReviewDimension:
  text = _body_text(chapter)
  blueprint_overlap = _keyword_overlap(text, blueprint_section)
  goal_overlap = _keyword_overlap(text, stage_goal)
  score = 62
  highlights: list[str] = []
  issues: list[ChapterReviewIssue] = []
  if blueprint_section.strip():
    if blueprint_overlap >= 0.3:
      score += 20
      highlights.append("正文和本章蓝图的关键词重合度较高")
    elif blueprint_overlap >= 0.12:
      score += 10
    else:
      issues.append(ChapterReviewIssue(level="warning", title="蓝图落地度偏弱", detail="这一章和蓝图的目标、动作或钩子重合不多。"))
  else:
    issues.append(ChapterReviewIssue(level="info", title="缺少本章蓝图", detail="当前还没有抽到对应章节蓝图，只能按正文本身判断。"))
  if stage_goal.strip():
    if goal_overlap >= 0.18:
      score += 10
      highlights.append("当前阶段目标在这章里有被推进")
    else:
      issues.append(ChapterReviewIssue(level="info", title="阶段目标露出不多", detail="正文里还看不太到当前阶段目标被继续推进。"))
  if model_dimension is not None:
    score = round(score * 0.45 + _model_dimension_score(model_dimension, base=80) * 0.55)
    highlights = [*model_dimension.get("strengths", []), *highlights]
    issues = [*model_dimension.get("issues", []), *issues]
    summary = str(model_dimension.get("summary") or "剧情推进还要继续对齐蓝图。")
  else:
    summary = (
      f"本章和蓝图重合度约 {int(blueprint_overlap * 100)}%。"
      f"{' 阶段目标有继续往前推。' if goal_overlap >= 0.18 else ' 阶段目标露出还不够。'}"
    )
  return _dimension("plot", "剧情推进", score, summary, highlights=highlights, issues=issues)


def _suspense_dimension(chapter, open_threads: list[str], model_dimension: dict[str, object] | None) -> ChapterReviewDimension:
  text = _body_text(chapter)
  sentences = _split_sentences(text)
  last_sentence = sentences[-1] if sentences else ""
  thread_overlap = max((_keyword_overlap(text, item) for item in open_threads), default=0.0)
  score = 64
  highlights: list[str] = []
  issues: list[ChapterReviewIssue] = []
  if thread_overlap >= 0.22:
    score += 16
    highlights.append("旧悬念在这章里有被继续碰到")
  elif open_threads:
    issues.append(ChapterReviewIssue(level="info", title="旧悬念回收不明显", detail="项目里挂着的悬念这章提得不多。"))
  if last_sentence and ("？" in last_sentence or "?" in last_sentence or any(token in last_sentence for token in _HOOK_TOKENS)):
    score += 12
    highlights.append("结尾保留了继续追问的空间")
  else:
    issues.append(ChapterReviewIssue(level="warning", title="章末悬念偏弱", detail="最后一句没有明显留下新的不安、问题或反常。"))
  if model_dimension is not None:
    score = round(score * 0.4 + _model_dimension_score(model_dimension, base=80) * 0.6)
    highlights = [*model_dimension.get("strengths", []), *highlights]
    issues = [*model_dimension.get("issues", []), *issues]
    summary = str(model_dimension.get("summary") or "悬念线还可以再压紧。")
  else:
    summary = (
      f"项目悬念和本章的关键词重合度约 {int(thread_overlap * 100)}%。"
      f"{' 章末有继续往下读的牵引。' if score >= 76 else ' 章末牵引还不够。'}"
    )
  return _dimension("suspense", "悬念与钩子", score, summary, highlights=highlights, issues=issues)


def _language_dimension(chapter) -> ChapterReviewDimension:
  text = _body_text(chapter)
  profile = analyze_humanize_text(text)
  issues = [
    ChapterReviewIssue(
      level="warning" if item.penalty >= 12 else "info",
      title=item.label,
      detail=f"{item.count} 处，例子：{' / '.join(item.examples[:2])}" if item.examples else f"{item.count} 处",
    )
    for item in profile.issues[:4]
  ]
  highlights: list[str] = []
  if profile.score >= 85:
    highlights.append("模板腔和解释腔残留不多")
  if not issues:
    highlights.append("本地规则没有扫出明显的 AI 腔高频词")
  summary = f"本地语言评分 {profile.score}/100。"
  if issues:
    summary += f" 当前最显眼的是 {issues[0].title}。"
  return _dimension("language", "语言读感", profile.score, summary, highlights=highlights, issues=issues)


def _continuity_dimension(project_detail, chapter, guard_context=None) -> ChapterReviewDimension:
  entities = _chapter_timeline_entities(project_detail, chapter.index)
  characters = entities["characters"]
  events = entities["events"]
  locations = entities["locations"]
  props = entities["props"]
  organizations = entities["organizations"]
  timeline_count = int((entities["timeline_count"] or ["0"])[0])
  text = _body_text(chapter)
  score = 70
  highlights: list[str] = []
  issues: list[ChapterReviewIssue] = []
  if characters:
    score += 8
    highlights.append(f"识别到人物：{' / '.join(characters[:3])}")
  else:
    issues.append(ChapterReviewIssue(level="warning", title="人物锚点偏弱", detail="这章没有抽到稳定人物，时间线会比较虚。"))
  if events:
    score += 6
  else:
    issues.append(ChapterReviewIssue(level="warning", title="事件锚点偏少", detail="这章还没有形成清楚的事件锚点。"))
  if locations or props or organizations:
    score += 8
    if locations:
      highlights.append(f"地点线索：{' / '.join(locations[:2])}")
    elif props:
      highlights.append(f"关键道具：{' / '.join(props[:2])}")
    elif organizations:
      highlights.append(f"组织势力：{' / '.join(organizations[:2])}")
  if timeline_count > 0:
    score += 8
  if len(text) >= 800 and len(characters) == 0:
    score -= 12
  if len(text) >= 800 and len(events) == 0:
    score -= 8
  if guard_context is not None:
    memory_evidence = list(getattr(guard_context, "memory_evidence", []) or [])
    knowledge_evidence = list(getattr(guard_context, "knowledge_evidence", []) or [])
    manual_memory = [item for item in memory_evidence if str(item.get("source") or "") == "manual"]
    if manual_memory:
      score += 6
      highlights.append(f"连续性证据已读取手动记忆 {len(manual_memory)} 条")
    elif memory_evidence:
      score += 3
      highlights.append(f"连续性证据已读取自动记忆 {len(memory_evidence)} 条")
    if knowledge_evidence:
      score += 4
      highlights.append(f"检索到原文或资料证据 {len(knowledge_evidence)} 条")
    if not memory_evidence and not knowledge_evidence:
      issues.append(ChapterReviewIssue(level="info", title="连续性证据较少", detail="本章核验没有命中项目记忆或导入资料，只能更多依赖章节正文。"))
  else:
    issues.append(ChapterReviewIssue(level="info", title="连续性证据包不可用", detail="本次核验没有拿到共享连续性证据包，已使用本地实体规则回看。"))
  summary = (
    f"这章识别到 {len(characters)} 个人物、{len(events)} 个事件、{len(locations)} 个地点、"
    f"{len(props)} 个道具，时间线新增 {timeline_count} 条记录。"
  )
  if guard_context is not None:
    memory_count = len(getattr(guard_context, "memory_evidence", []) or [])
    evidence_count = len(getattr(guard_context, "knowledge_evidence", []) or [])
    summary += f" 共享连续性证据包含 {memory_count} 条项目记忆、{evidence_count} 条资料命中。"
  return _dimension("continuity", "连续性回看", score, summary, highlights=highlights, issues=issues)


_CONTRACT_OBLIGATION_HEADINGS = {
  "必须完成的节拍",
  "必须推进的债务",
  "人物检查",
  "验收项",
  "Obsidian 章节计划",
  "Obsidian 剧情债务",
  "Obsidian 人物弧线",
  "本章必须处理或明确推进的剧情债务",
}


def _contract_obligation_lines(contract_text: str, *, limit: int = 8) -> list[tuple[str, str]]:
  obligations: list[tuple[str, str]] = []
  active_heading = ""
  for raw_line in str(contract_text or "").splitlines():
    line = raw_line.strip()
    if not line:
      continue
    if line.startswith("合同目标："):
      obligations.append(("合同目标", line.split("：", 1)[1].strip()))
    if not line.startswith("-") and line.endswith("："):
      heading = line.rstrip("：").strip()
      active_heading = heading if heading in _CONTRACT_OBLIGATION_HEADINGS else ""
      continue
    if active_heading and line.startswith("-"):
      obligations.append((active_heading, line.lstrip("- ").strip()))
    if len(obligations) >= limit:
      break
  return [(heading, value) for heading, value in obligations if value][:limit]


def _contract_line_missing(chapter_text: str, obligation: str) -> bool:
  if "必写项未完成：" in obligation:
    marker = obligation.split("必写项未完成：", 1)[1].split("：", 1)[0].strip()
    if marker and marker in chapter_text:
      return False
  if "必须包含：" in obligation:
    marker = obligation.split("必须包含：", 1)[1].split("：", 1)[0].strip()
    if marker and marker in chapter_text:
      return False
  tokens = [token for token in _tokens(obligation, limit=8) if token not in _TOKEN_STOPWORDS]
  if not tokens:
    return False
  required = min(2, len(tokens))
  matched = sum(1 for token in tokens if token in chapter_text)
  return matched < required


def _continuity_contract_dimension(project_detail, chapter, guard_context=None) -> ChapterReviewDimension:
  contract_text = str(getattr(guard_context, "contract_text", "") or "").strip()
  if not contract_text:
    try:
      from novel_backend.services.continuity_guard_service import build_chapter_continuity_contract

      contract_text = build_chapter_continuity_contract(project_detail, chapter)
    except Exception:
      contract_text = ""
  if not contract_text:
    return _dimension(
      "continuity_contract",
      "章节连续性合同",
      0,
      "本章没有生成章节连续性合同，暂不计入评分。",
      status="na",
    )

  chapter_text = _body_text(chapter)
  issues: list[ChapterReviewIssue] = []
  highlights = ["已加载章节连续性合同"]
  if "账本与章节约束" in contract_text:
    highlights.append("已读取叙事状态账本")
  if "近期章节承接" in contract_text:
    highlights.append("已读取近期章节承接")
  if "资料证据摘要" in contract_text or "Obsidian" in contract_text:
    highlights.append("已合并外部资料约束")

  obligations = _contract_obligation_lines(contract_text)
  for heading, obligation in obligations:
    if _contract_line_missing(chapter_text, obligation):
      issues.append(
        ChapterReviewIssue(
          level="warning",
          title=f"缺少连续性合同项：{heading}",
          detail=f"合同要求：{_compact_text(obligation, 160)}；正文没有命中足够的可核验关键词。",
        )
      )
      if len(issues) >= 4:
        break

  chapter_index = int(getattr(chapter, "index", 0) or 0)
  previous_chapter = next(
    (
      item for item in getattr(project_detail, "chapters", [])
      if int(getattr(item, "index", 0) or 0) == chapter_index - 1 and str(getattr(item, "content", "") or "").strip()
    ),
    None,
  )
  if chapter_index > 1 and previous_chapter is None:
    issues.append(
      ChapterReviewIssue(
        level="warning",
        title="缺少连续性合同承接源",
        detail="当前章前一章没有可读取正文，长篇中段生成只能依赖摘要和资料，连续性风险会上升。",
      )
    )

  score = 92 - sum(_issue_penalty(item.level) for item in issues)
  summary = f"章节连续性合同已参与核验，当前检查 {len(obligations)} 个义务项。"
  if issues:
    summary = f"章节连续性合同发现 {len(issues)} 个需要处理的承接问题。"
  return _dimension(
    "continuity_contract",
    "章节连续性合同",
    score,
    summary,
    highlights=highlights,
    issues=issues,
  )


def _obsidian_note_labels(note) -> list[str]:
  labels = [
    str(getattr(note, "title", "") or ""),
    Path(str(getattr(note, "relative_path", "") or "")).stem,
  ]
  labels.extend(str(item or "") for item in getattr(note, "aliases", []) or [])
  return [item.strip() for item in labels if item.strip()]


def _obsidian_evidence_paths(guard_context) -> set[str]:
  paths: set[str] = set()
  if guard_context is None:
    return paths
  for item in list(getattr(guard_context, "knowledge_evidence", []) or []):
    if str(item.get("source") or "") != "Obsidian":
      continue
    source_key = str(item.get("source_key") or "").strip()
    if source_key.startswith("obsidian:"):
      relative_path = source_key.split(":", 1)[1].strip().replace("\\", "/")
      if relative_path:
        paths.add(relative_path)
        continue
    section = str(item.get("section") or "").strip()
    if "·" in section:
      relative_path = section.rsplit("·", 1)[1].strip()
      if relative_path:
        paths.add(relative_path)
  return paths


def _obsidian_forbidden_matches(note, chapter_text: str) -> list[str]:
  matches: list[str] = []
  for phrase in list(getattr(note, "forbidden_phrases", []) or [])[:8]:
    cleaned = str(phrase or "").strip()
    if cleaned and cleaned in chapter_text:
      matches.append(cleaned)
  return matches


def _obsidian_note_focused_on_chapter(note, chapter_index: int) -> bool:
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0
  if target <= 0:
    return False
  try:
    chapter_start = int(getattr(note, "chapter_start", 0) or 0)
  except (TypeError, ValueError):
    chapter_start = 0
  try:
    chapter_end = int(getattr(note, "chapter_end", 0) or 0)
  except (TypeError, ValueError):
    chapter_end = 0
  if chapter_start <= 0 or chapter_end <= 0:
    return False
  if chapter_start > chapter_end:
    chapter_start, chapter_end = chapter_end, chapter_start
  span = chapter_end - chapter_start + 1
  return span <= 3 and chapter_start <= target <= chapter_end


def _handoff_chapter_numbers(text: str) -> list[int]:
  indexes: list[int] = []
  for match in _CHAPTER_NUMBER_IN_TEXT_RE.finditer(str(text or "")):
    index = _parse_chapter_number(match.group(1))
    if index > 0 and index not in indexes:
      indexes.append(index)
  return indexes


def _handoff_source_chapters(item: dict[str, object]) -> list[int]:
  indexes: list[int] = []
  for value in item.get("source_chapters", []):
    if isinstance(value, int):
      index = int(value)
    else:
      try:
        index = int(str(value or ""))
      except (TypeError, ValueError):
        index = _parse_chapter_number(value)
    if index > 0 and index not in indexes:
      indexes.append(index)
  return indexes


def _handoff_applies_to_chapter(item: dict[str, object], handoff: str, chapter_index: int) -> bool:
  if chapter_index <= 0:
    return False
  explicit_chapters = _handoff_chapter_numbers(handoff)
  if explicit_chapters:
    return chapter_index in explicit_chapters
  source_chapters = _handoff_source_chapters(item)
  if not source_chapters:
    return False
  return max(source_chapters) + 1 == chapter_index


def _handoff_is_required(text: str) -> bool:
  value = str(text or "")
  if "不能忘" not in value and any(marker in value for marker in _HANDOFF_NEGATIVE_MARKERS):
    return False
  return any(marker in value for marker in _HANDOFF_REQUIRED_MARKERS)


def _handoff_check_tokens(text: str) -> list[str]:
  cleaned = _CHAPTER_NUMBER_IN_TEXT_RE.sub("", str(text or ""))
  for term in _HANDOFF_GENERIC_TERMS:
    cleaned = cleaned.replace(term, "")
  candidates: list[str] = []
  for part in re.split(r"[\s,，、;；。！？!?：:（）()【】\[\]《》“”\"']+", cleaned):
    token = part.strip()
    if len(token) >= 3:
      candidates.append(token)
  for token in _TOKEN_RE.findall(cleaned):
    if token in _TOKEN_STOPWORDS or len(token) < 3:
      continue
    candidates.append(token)
  return _ordered_unique(candidates)[:6]


def _obsidian_chapter_handoff_issues(project_detail, chapter, chapter_text: str) -> list[ChapterReviewIssue]:
  try:
    from novel_backend.services.project_narrative_state_service import build_project_narrative_state_chapter_card
  except Exception:
    return []

  chapter_id = str(getattr(chapter, "id", "") or "")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  if not chapter_id or chapter_index <= 0:
    return []
  try:
    card = build_project_narrative_state_chapter_card(project_detail, chapter_id)
  except Exception:
    return []
  entries = card.get("obsidian_chapter_notes", []) if isinstance(card, dict) else []
  if not isinstance(entries, list):
    return []

  issues: list[ChapterReviewIssue] = []
  for item in entries:
    if not isinstance(item, dict):
      continue
    title = str(item.get("title") or item.get("relative_path") or "章节档案").strip()
    for raw_handoff in item.get("handoff", []):
      handoff = str(raw_handoff or "").strip()
      if not handoff or not _handoff_is_required(handoff):
        continue
      if not _handoff_applies_to_chapter(item, handoff, chapter_index):
        continue
      tokens = _handoff_check_tokens(handoff)
      if not tokens or any(token in chapter_text for token in tokens):
        continue
      issues.append(
        ChapterReviewIssue(
          level="warning",
          title=f"缺少 Obsidian 必需设定：{title}",
          detail=(
            f"章节档案交接提醒要求当前章承接：{handoff}；"
            f"正文未命中可核验关键词：{' / '.join(tokens[:4])}"
          ),
        )
      )
      if len(issues) >= 4:
        return issues
  return issues


def _obsidian_dimension(project_detail, chapter, guard_context=None) -> ChapterReviewDimension:
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  if obsidian is None or not bool(getattr(obsidian, "enabled", False)):
    return _dimension("obsidian", "Obsidian 设定", 0, "当前没有可用于核验的长篇稳定档案，暂不做设定反查。", status="na")
  all_notes = list(getattr(obsidian, "notes", []) or [])
  if not all_notes:
    return _dimension("obsidian", "Obsidian 设定", 0, "Obsidian 当前没有可用于核验的正式笔记。", status="na")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  project_path = str(getattr(project_detail, "path", "") or "").strip()
  if project_path and chapter_index > 0:
    try:
      notes = [
        record.summary
        for record in scoped_obsidian_note_records_for_chapter(Path(project_path), chapter_index)
      ]
    except Exception:
      notes = [note for note in all_notes if obsidian_note_available_for_chapter(note, chapter_index)]
  else:
    notes = [note for note in all_notes if obsidian_note_available_for_chapter(note, chapter_index)]
  if not notes:
    return _dimension(
      "obsidian",
      "Obsidian 设定",
      0,
      "当前目标章节没有可用的 Obsidian 设定笔记，暂不做设定反查。",
      status="na",
    )

  chapter_text = str(getattr(chapter, "content", "") or "")
  handoff_issues = _obsidian_chapter_handoff_issues(project_detail, chapter, chapter_text)
  evidence_paths = _obsidian_evidence_paths(guard_context)
  relevant_notes: list[tuple[object, bool, bool, bool, list[str]]] = []
  for note in notes:
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    labels = _obsidian_note_labels(note)
    evidence_matched = relative_path in evidence_paths
    label_matched = any(label and label in chapter_text for label in labels)
    forbidden_matches = _obsidian_forbidden_matches(note, chapter_text)
    focused_scope_matched = (
      _obsidian_note_focused_on_chapter(note, chapter_index)
      and any(str(item or "").strip() for item in getattr(note, "required_phrases", []) or [])
    )
    if (
      evidence_matched
      or label_matched
      or forbidden_matches
      or focused_scope_matched
    ):
      relevant_notes.append(
        (note, evidence_matched, label_matched, focused_scope_matched, forbidden_matches)
      )

  if not relevant_notes and not handoff_issues:
    return _dimension(
      "obsidian",
      "Obsidian 设定",
      0,
      "本章没有命中明确的 Obsidian 设定笔记，暂不计入评分。",
      status="na",
    )

  score = 88
  highlights = []
  if relevant_notes:
    highlights.append(f"已反查 Obsidian 设定 {len(relevant_notes)} 份")
  if handoff_issues:
    highlights.append(f"已检查章节档案交接 {len(handoff_issues)} 项")
  issues: list[ChapterReviewIssue] = list(handoff_issues)
  for note, evidence_matched, label_matched, focused_scope_matched, forbidden_matches in relevant_notes[:8]:
    title = str(getattr(note, "title", "") or "").strip() or str(getattr(note, "relative_path", "") or "").strip()
    for cleaned in forbidden_matches:
      issues.append(
        ChapterReviewIssue(
          level="critical",
          title=f"触犯 Obsidian 禁用设定：{title}",
          detail=f"正文出现了正式笔记标记为禁止的短语：{cleaned}",
        )
      )
    if evidence_matched or label_matched or focused_scope_matched:
      for phrase in list(getattr(note, "required_phrases", []) or [])[:8]:
        cleaned = str(phrase or "").strip()
        if cleaned and cleaned not in chapter_text:
          if label_matched:
            reason = "正文提到了该笔记"
          elif evidence_matched:
            reason = "本章证据命中了该笔记"
          else:
            reason = "Vault 将该笔记绑定到当前章节"
          issues.append(
            ChapterReviewIssue(
              level="warning",
              title=f"缺少 Obsidian 必需设定：{title}",
              detail=f"{reason}，但没有出现正式笔记要求保留的短语：{cleaned}",
            )
          )
    ambiguous = [str(item).strip() for item in getattr(note, "ambiguous_links", []) or [] if str(item).strip()]
    if ambiguous:
      issues.append(
        ChapterReviewIssue(
          level="warning",
          title=f"相关 Obsidian 笔记存在歧义链接：{title}",
          detail=f"这些双链不会自动解析：{' / '.join(ambiguous[:4])}",
        )
      )
    unresolved = [str(item).strip() for item in getattr(note, "unresolved_links", []) or [] if str(item).strip()]
    if unresolved:
      issues.append(
        ChapterReviewIssue(
          level="info",
          title=f"相关 Obsidian 笔记存在未解析链接：{title}",
          detail=f"这些双链还没有对应正式笔记：{' / '.join(unresolved[:4])}",
        )
      )

  score -= sum(_issue_penalty(item.level) for item in issues)
  summary = "Obsidian 正式设定已参与本章核验。"
  if issues:
    summary = f"Obsidian 设定核验发现 {len(issues)} 个需要处理的风险。"
  return _dimension("obsidian", "Obsidian 设定", score, summary, highlights=highlights, issues=issues)


def _rule_sentences(text: str) -> list[str]:
  sentences: list[str] = []
  for raw_line in str(text or "").splitlines():
    line = raw_line.strip(" -\t")
    if not line:
      continue
    parts = re.split(r"[。！？!?；;]\s*", line)
    sentences.extend(part.strip() for part in parts if part.strip())
  return sentences


def _quoted_terms(text: str) -> list[str]:
  terms: list[str] = []
  for pattern in (
    r"“([^”]{2,40})”",
    r"\"([^\"]{2,40})\"",
    r"'([^']{2,40})'",
    r"《([^》]{2,40})》",
    r"【([^】]{2,40})】",
  ):
    terms.extend(match.strip() for match in re.findall(pattern, text) if match.strip())
  return _ordered_unique(terms)


def _memory_negative_fragment(sentence: str) -> str:
  earliest = -1
  for marker in _PROJECT_MEMORY_NEGATIVE_MARKERS:
    index = sentence.find(marker)
    if index >= 0 and (earliest < 0 or index < earliest):
      earliest = index
  return sentence[earliest:] if earliest >= 0 else ""


def _explicit_replacement_terms(fragment: str) -> list[str]:
  terms: list[str] = []
  action_pattern = "|".join(re.escape(item) for item in _PROJECT_MEMORY_REPLACEMENT_ACTIONS)
  for match in re.finditer(rf"(?:{action_pattern})([\u4e00-\u9fffA-Za-z0-9_·]{{2,24}})", fragment):
    term = match.group(1).strip()
    if term and term not in _PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS:
      terms.append(term)
  return _ordered_unique(terms)


def _clean_project_memory_subject(value: str) -> str:
  subject = str(value or "").strip()
  for term in sorted(_PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS, key=len, reverse=True):
    subject = subject.replace(term, "")
  return subject.strip(" ，,、：:的了被")


def _clean_project_memory_identity(value: str) -> str:
  identity = str(value or "").strip(" ，,、：:的了。！？!?；;")
  if identity in _PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS:
    return ""
  return identity if len(identity) >= 2 else ""


def _identity_terms_after_reveal_action(text: str) -> list[str]:
  action_pattern = "|".join(re.escape(action) for action in _PROJECT_MEMORY_REVEAL_ACTIONS)
  terms: list[str] = []
  for match in re.finditer(
    rf"(?:{action_pattern})[^。！？!?；;\n]{{0,18}}?(?:就是|是|成为|成了|为)([\u4e00-\u9fffA-Za-z0-9_·]{{2,16}})",
    text or "",
  ):
    term = _clean_project_memory_identity(match.group(1))
    if term:
      terms.append(term)
  return _ordered_unique(terms)


def _generic_reveal_match(chapter_text: str, text: str) -> str:
  action_pattern = "|".join(re.escape(action) for action in _PROJECT_MEMORY_REVEAL_ACTIONS)
  for match in re.finditer(
    rf"(?:{action_pattern})[^。！？!?；;\n]{{0,12}}?([\u4e00-\u9fffA-Za-z0-9_·]{{2,16}}?)(?:就是|是|成为|成了|为)([\u4e00-\u9fffA-Za-z0-9_·]{{2,16}})",
    text or "",
  ):
    name = _clean_project_memory_subject(match.group(1))
    identity = _clean_project_memory_identity(match.group(2))
    if name and identity and _chapter_reveals_role(chapter_text, name, identity):
      return f"{name} / {identity}"
  return ""


def _chapter_reveals_role(chapter_text: str, name: str, role: str) -> bool:
  if not name or not role:
    return False
  patterns = (
    rf"{re.escape(name)}[^。！？!?；;\n]{{0,16}}{re.escape(role)}",
    rf"{re.escape(role)}[^。！？!?；;\n]{{0,16}}{re.escape(name)}",
  )
  for pattern in patterns:
    for match in re.finditer(pattern, chapter_text or ""):
      segment = match.group(0)
      if any(marker in segment for marker in ("不是", "并非", "并不是", "否认", "未被", "没有")):
        continue
      return True
  return False


def _explicit_reveal_match(chapter_text: str, rule_sentence: str, fragment: str) -> str:
  for text in (fragment, rule_sentence):
    for match in re.finditer(
      r"([\u4e00-\u9fffA-Za-z0-9_·]{2,16}?)(?:就是|是|成为|成了|为)("
      + "|".join(re.escape(role) for role in _PROJECT_MEMORY_REVEAL_ROLES)
      + r")",
      text,
    ):
      name = _clean_project_memory_subject(match.group(1))
      role = match.group(2).strip()
      if _chapter_reveals_role(chapter_text, name, role):
        return f"{name} / {role}"
    generic_match = _generic_reveal_match(chapter_text, text)
    if generic_match:
      return generic_match

  for marker in _PROJECT_MEMORY_NEGATIVE_MARKERS:
    index = rule_sentence.find(marker)
    if index <= 0:
      continue
    prefix = rule_sentence[:index].strip(" ，,、：:")
    fragment_after_marker = rule_sentence[index:]
    roles = [role for role in _PROJECT_MEMORY_REVEAL_ROLES if role in fragment_after_marker]
    roles.extend(_identity_terms_after_reveal_action(fragment_after_marker))
    roles = _ordered_unique(roles)
    if not roles:
      continue
    subjects = [_clean_project_memory_subject(item) for item in [*_quoted_terms(prefix), *_tokens(prefix, limit=4)]]
    for subject in _ordered_unique(item for item in subjects if item):
      for role in roles:
        if _chapter_reveals_role(chapter_text, subject, role):
          return f"{subject} / {role}"
  return ""


def _clean_project_memory_transfer_target(value: str) -> str:
  target = str(value or "").strip(" ，,、：:的了。！？!?；;")
  if target in _PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS:
    return ""
  return target if len(target) >= 2 else ""


def _transfer_targets_after_action(text: str) -> list[tuple[str, str]]:
  action_pattern = "|".join(re.escape(action) for action in _PROJECT_MEMORY_TRANSFER_ACTIONS)
  targets: list[tuple[str, str]] = []
  for match in re.finditer(
    rf"(?:被|把)?({action_pattern})([\u4e00-\u9fffA-Za-z0-9_·]{{2,24}})",
    text or "",
  ):
    action = match.group(1)
    target = _clean_project_memory_transfer_target(match.group(2))
    if target:
      targets.append((action, target))
  return list(dict.fromkeys(targets))


def _chapter_transfers_object(chapter_text: str, subject: str, action: str, target: str) -> bool:
  if not subject or not target:
    return False
  action_pattern = "|".join(re.escape(item) for item in _PROJECT_MEMORY_TRANSFER_ACTIONS)
  pattern = rf"{re.escape(subject)}[^。！？!?；;\n]{{0,24}}(?:{action_pattern})[^。！？!?；;\n]{{0,12}}{re.escape(target)}"
  for match in re.finditer(pattern, chapter_text or ""):
    segment = match.group(0)
    action_match = re.search(action_pattern, segment)
    if action_match:
      action_start = match.start() + action_match.start()
      prefix = (chapter_text or "")[max(0, action_start - 16) : action_start]
      if any(marker in prefix for marker in _PROJECT_MEMORY_NEGATED_STATE_PREFIXES):
        continue
    return True
  return False


def _explicit_transfer_match(chapter_text: str, rule_sentence: str) -> str:
  for marker in _PROJECT_MEMORY_NEGATIVE_MARKERS:
    index = rule_sentence.find(marker)
    if index <= 0:
      continue
    prefix = rule_sentence[:index].strip(" ，,、：:")
    fragment_after_marker = rule_sentence[index:]
    targets = _transfer_targets_after_action(fragment_after_marker)
    if not targets:
      continue
    subjects = [_clean_project_memory_subject(item) for item in [*_quoted_terms(prefix), *_tokens(prefix, limit=4)]]
    for subject in _ordered_unique(item for item in subjects if item):
      for action, target in targets:
        if _chapter_transfers_object(chapter_text, subject, action, target):
          return f"{subject} / {action} / {target}"
  return ""


def _replacement_subject_target_pairs(rule_sentence: str) -> list[tuple[str, str, str]]:
  action_pattern = "|".join(re.escape(item) for item in _PROJECT_MEMORY_REPLACEMENT_ACTIONS)
  pairs: list[tuple[str, str, str]] = []
  for marker in _PROJECT_MEMORY_NEGATIVE_MARKERS:
    index = rule_sentence.find(marker)
    if index < 0:
      continue
    prefix = rule_sentence[:index].strip(" ，,、：:")
    fragment_after_marker = rule_sentence[index:]
    for match in re.finditer(
      rf"(?:把|将|让|使)?([\u4e00-\u9fffA-Za-z0-9_·]{{2,24}})(?:被)?({action_pattern})([\u4e00-\u9fffA-Za-z0-9_·]{{2,24}})",
      fragment_after_marker,
    ):
      subject = _clean_project_memory_subject(match.group(1))
      action = match.group(2)
      target = _clean_project_memory_identity(match.group(3))
      if subject and target:
        pairs.append((subject, action, target))

    prefix_subjects = [_clean_project_memory_subject(item) for item in [*_quoted_terms(prefix), *_tokens(prefix, limit=4)]]
    targets = _explicit_replacement_terms(fragment_after_marker)
    for subject in _ordered_unique(item for item in prefix_subjects if item):
      for target in targets:
        pairs.append((subject, "改名为", target))
  return list(dict.fromkeys(pairs))


def _chapter_replaces_identity(chapter_text: str, subject: str, target: str) -> tuple[str, str] | None:
  if not subject or not target:
    return None
  action_pattern = "|".join(re.escape(item) for item in _PROJECT_MEMORY_REPLACEMENT_ACTIONS)
  patterns = (
    rf"{re.escape(subject)}[^。！？!?；;\n]{{0,20}}(?:被|让人)?({action_pattern})[^。！？!?；;\n]{{0,8}}{re.escape(target)}",
    rf"(?:把|将|让|使){re.escape(subject)}[^。！？!?；;\n]{{0,8}}({action_pattern})[^。！？!?；;\n]{{0,8}}{re.escape(target)}",
  )
  for pattern in patterns:
    for match in re.finditer(pattern, chapter_text or ""):
      action_match = re.search(action_pattern, match.group(0))
      if not action_match:
        continue
      action_start = match.start() + action_match.start()
      prefix = (chapter_text or "")[max(0, action_start - 16) : action_start]
      if any(marker in prefix for marker in _PROJECT_MEMORY_NEGATED_STATE_PREFIXES):
        continue
      return action_match.group(0), match.group(0)
  return None


def _explicit_replacement_match(chapter_text: str, rule_sentence: str) -> str:
  for subject, action, target in _replacement_subject_target_pairs(rule_sentence):
    match = _chapter_replaces_identity(chapter_text, subject, target)
    if match:
      actual_action, _segment = match
      return f"{subject} / {actual_action or action} / {target}"
  return ""


def _memory_rule_subject_candidates(sentence: str, terms: tuple[str, ...]) -> list[str]:
  candidates = _quoted_terms(sentence)
  for marker in _PROJECT_MEMORY_NEGATIVE_MARKERS:
    index = sentence.find(marker)
    if index <= 0:
      continue
    prefix = sentence[:index].strip(" ，,、：:")
    if prefix:
      candidates.extend(_tokens(prefix, limit=4))
  for term in sorted(terms, key=len, reverse=True):
    for match in re.finditer(r"(?:让|把|使)?([\u4e00-\u9fffA-Za-z0-9_·]{2,16})[^。！？!?；;]{0,8}" + re.escape(term), sentence):
      candidates.append(match.group(1).strip())

  cleaned: list[str] = []
  for candidate in candidates:
    value = str(candidate or "").strip()
    for generic in sorted(_PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS, key=len, reverse=True):
      value = value.replace(generic, "")
    value = value.strip(" ，,、：:的了")
    if len(value) >= 2:
      cleaned.append(value)
  return _ordered_unique(cleaned)


def _explicit_state_rule_match(chapter_text: str, rule_sentence: str) -> str:
  for label, terms in _PROJECT_MEMORY_STATE_RULES:
    if not any(term in rule_sentence for term in terms):
      continue
    chapter_hit = next((term for term in terms if _state_term_occurs_affirmatively(chapter_text, term)), "")
    if not chapter_hit:
      continue
    subjects = _memory_rule_subject_candidates(rule_sentence, terms)
    if subjects:
      for subject in subjects:
        if subject in chapter_text:
          return f"{subject} / {chapter_hit}"
      continue
    return f"{label} / {chapter_hit}" if label != chapter_hit else chapter_hit
  return ""


def _state_term_occurs_affirmatively(text: str, term: str) -> bool:
  for match in re.finditer(re.escape(term), text or ""):
    prefix = text[max(0, match.start() - 8) : match.start()]
    if any(marker in prefix for marker in _PROJECT_MEMORY_NEGATED_STATE_PREFIXES):
      continue
    return True
  return False


def _memory_rule_violation_match(chapter_text: str, rule_sentence: str) -> str:
  fragment = _memory_negative_fragment(rule_sentence)
  if not fragment:
    return ""
  reveal_match = _explicit_reveal_match(chapter_text, rule_sentence, fragment)
  if reveal_match:
    return reveal_match
  transfer_match = _explicit_transfer_match(chapter_text, rule_sentence)
  if transfer_match:
    return transfer_match
  replacement_match = _explicit_replacement_match(chapter_text, rule_sentence)
  if replacement_match:
    return replacement_match
  state_match = _explicit_state_rule_match(chapter_text, rule_sentence)
  if state_match:
    return state_match
  for term in _quoted_terms(fragment):
    if term and term in chapter_text:
      return term
  tokens = [
    token
    for token in _tokens(fragment, limit=10)
    if token not in _TOKEN_STOPWORDS and token not in _PROJECT_MEMORY_NEGATIVE_GENERIC_TERMS
  ]
  if not tokens:
    return ""
  matched = [token for token in tokens if token in chapter_text]
  required = min(2, len(tokens))
  if len(matched) >= required:
    return " / ".join(matched[:4])
  return ""


def _project_memory_dimension(project_detail, chapter) -> ChapterReviewDimension:
  entries = [
    item for item in list(getattr(project_detail.story_overview, "memory_entries", []) or [])
    if str(getattr(item, "category", "") or "") in _PROJECT_MEMORY_RULE_CATEGORIES
  ]
  if not entries:
    return _dimension("project_memory", "项目记忆规则", 0, "当前没有项目记忆规则，暂不做记忆反查。", status="na")

  chapter_text = _body_text(chapter)
  issues: list[ChapterReviewIssue] = []
  checked_count = 0
  for entry in entries[:20]:
    category = str(getattr(entry, "category", "") or "")
    title = str(getattr(entry, "title", "") or "").strip() or "未命名记忆"
    for sentence in _rule_sentences(str(getattr(entry, "content", "") or "")):
      if not any(marker in sentence for marker in _PROJECT_MEMORY_NEGATIVE_MARKERS):
        continue
      checked_count += 1
      matched = _memory_rule_violation_match(chapter_text, sentence)
      if not matched:
        continue
      issues.append(
        ChapterReviewIssue(
          level="critical",
          title=f"触犯项目记忆{category}：{title}",
          detail=f"项目记忆要求：{_compact_text(sentence, 160)}；正文命中：{matched}",
        )
      )
      if len(issues) >= 4:
        break
    if len(issues) >= 4:
      break

  if checked_count == 0:
    return _dimension(
      "project_memory",
      "项目记忆规则",
      0,
      "项目记忆里没有可自动反查的禁写规则，暂不计入评分。",
      status="na",
    )

  score = 94 - sum(_issue_penalty(item.level) for item in issues)
  if issues:
    score = min(score, 60)
  highlights = [f"已反查项目记忆规则 {checked_count} 条"]
  summary = "项目记忆规则已参与本章核验。"
  if issues:
    summary = f"项目记忆规则发现 {len(issues)} 个硬性冲突。"
  return _dimension(
    "project_memory",
    "项目记忆规则",
    score,
    summary,
    highlights=highlights,
    issues=issues,
    status="risk" if issues else None,
  )


def _style_dimension(settings: Settings, chapter, style_name: str, model_dimension: dict[str, object] | None) -> ChapterReviewDimension:
  if not style_name.strip():
    return _dimension("style", "文风贴合", 0, "当前没有绑定文风方案，暂时不做贴合度评分。", status="na")

  try:
    detail = get_style(settings, style_name.strip())
  except Exception:
    return _dimension("style", "文风贴合", 0, f"没有找到文风方案“{style_name.strip()}”，暂时无法判断贴合度。", status="na")

  sample_text = _style_sample_text(detail)
  if not sample_text.strip():
    return _dimension("style", "文风贴合", 0, f"文风方案“{style_name.strip()}”还没有样文，暂时无法做贴合度评分。", status="na")

  chapter_stats = _text_stats(_body_text(chapter))
  style_stats = _text_stats(sample_text)
  penalty = 0
  penalty += min(28, int(abs(chapter_stats["avg_sentence_length"] - style_stats["avg_sentence_length"]) * 1.8))
  penalty += min(18, int(abs(chapter_stats["short_sentence_ratio"] - style_stats["short_sentence_ratio"]) * 45))
  penalty += min(18, int(abs(chapter_stats["dialogue_ratio"] - style_stats["dialogue_ratio"]) * 45))
  penalty += min(12, int(abs(chapter_stats["question_ratio"] - style_stats["question_ratio"]) * 50))
  imagery_overlap = 0.0
  chapter_imagery = set(chapter_stats["imagery"])
  style_imagery = set(style_stats["imagery"])
  if chapter_imagery and style_imagery:
    imagery_overlap = round(len(chapter_imagery & style_imagery) / max(min(len(chapter_imagery), len(style_imagery)), 1), 2)
    penalty += max(0, 12 - int(imagery_overlap * 12))
  score = max(0, 100 - penalty)
  highlights = [
    f"目标句长 {style_stats['avg_sentence_length']} 字，本章约 {chapter_stats['avg_sentence_length']} 字",
    f"目标短句占比 {int(style_stats['short_sentence_ratio'] * 100)}%，本章 {int(chapter_stats['short_sentence_ratio'] * 100)}%",
  ]
  if imagery_overlap > 0:
    highlights.append(f"当前意象词和样文有 {int(imagery_overlap * 100)}% 的重合")
  issues: list[ChapterReviewIssue] = []
  if score < 70:
    issues.append(
      ChapterReviewIssue(
        level="warning",
        title="文风偏离样文",
        detail="句长、对白密度或意象词场和样文差距较大。",
      )
    )
  if model_dimension is not None:
    score = round(score * 0.55 + _model_dimension_score(model_dimension, base=78) * 0.45)
    highlights = [*model_dimension.get("strengths", []), *highlights]
    issues = [*model_dimension.get("issues", []), *issues]
    summary = str(model_dimension.get("summary") or f"这章和文风方案“{style_name.strip()}”还需要继续对齐。")
  else:
    summary = f"当前按文风方案“{style_name.strip()}”做统计对比。"
  return _dimension("style", "文风贴合", score, summary, highlights=highlights, issues=issues)


def _style_context(settings: Settings, style_name: str) -> tuple[str, str]:
  if not style_name.strip():
    return "", ""
  try:
    detail = get_style(settings, style_name.strip())
  except Exception:
    return "", ""
  blocks = []
  if detail.instruction:
    blocks.append(f"文风说明：{detail.instruction}")
  if detail.narrative_for_chapter:
    blocks.append(f"章节叙事要求：{detail.narrative_for_chapter}")
  if detail.calibration_notes:
    blocks.append(f"最近校准记录：{_compact_text(detail.calibration_notes, 180)}")
  if detail.reference_distillate:
    blocks.append(detail.reference_distillate)
  return "\n".join(blocks).strip(), _style_sample_text(detail)


def _review_signature(project_detail, chapter, *, style_name: str) -> str:
  docs = _documents_map(project_detail)
  memory_entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  dream_report = getattr(project_detail.story_overview, "dream_report", None)
  parts = [
    str(project_detail.name or ""),
    str(project_detail.genre or ""),
    str(getattr(chapter, "id", "") or ""),
    str(getattr(chapter, "content", "") or ""),
    style_name.strip(),
  ]
  for key in ("core_seed", "character_design", "character_state", "world_building", "plot_structure", "blueprint", "global_summary"):
    parts.append(f"{key}::{docs.get(key, '').strip()}")
  for item in sorted(
    memory_entries,
    key=lambda item: (
      str(getattr(item, "source", "") or ""),
      str(getattr(item, "category", "") or ""),
      str(getattr(item, "id", "") or ""),
      str(getattr(item, "title", "") or ""),
    ),
  ):
    parts.append(f"memory::{item.id}::{item.title}::{item.content}")
  if dream_report is not None:
    parts.append(str(getattr(dream_report, "summary", "") or ""))
    parts.extend(getattr(dream_report, "open_questions", []) or [])
  obsidian = getattr(project_detail.story_overview, "obsidian", None)
  if obsidian is not None:
    chapter_index = int(getattr(chapter, "index", 0) or 0)
    obsidian_signature = str(getattr(obsidian, "source_signature", "") or "")
    project_path = str(getattr(project_detail, "path", "") or "").strip()
    if project_path:
      try:
        obsidian_signature = obsidian_source_signature_for_chapter(Path(project_path), chapter_index)
      except Exception:
        pass
    visible_note_count = sum(
      1
      for note in list(getattr(obsidian, "notes", []) or [])
      if obsidian_note_available_for_chapter(note, chapter_index)
    )
    parts.append(f"obsidian::{obsidian_signature}")
    parts.append(f"obsidian_notes::{visible_note_count}")
  return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def build_chapter_review(
  settings: Settings,
  project_detail,
  chapter_id: str,
  *,
  style_name: str = "",
) -> ChapterReviewReport:
  chapter = _chapter_or_none(project_detail, chapter_id)
  if chapter is None:
    raise ValueError("章节不存在")
  if not str(getattr(chapter, "content", "") or "").strip():
    raise ValueError("章节正文为空，不能生成核验报告")

  style_context, _style_sample = _style_context(settings, style_name)
  docs = _documents_map(project_detail)
  blueprint_section = _blueprint_section(docs.get("blueprint", ""), chapter.index, chapter.title)
  stage_goal_entry = _memory_entry(project_detail, "auto-stage-goal")
  stage_goal = str(getattr(stage_goal_entry, "content", "") or "").strip()
  open_threads_entry = _memory_entry(project_detail, "auto-open-threads")
  open_threads = [
    item.strip(" -0123456789.、）)")
    for item in str(getattr(open_threads_entry, "content", "") or "").splitlines()
    if item.strip()
  ]
  dream_report = getattr(project_detail.story_overview, "dream_report", None)
  if dream_report is not None:
    open_threads.extend([item for item in (getattr(dream_report, "open_questions", []) or []) if str(item).strip()])
  guard_context = _build_review_guard_context(settings, project_detail, chapter)
  model_payload: dict[str, object] | None = None
  engine = "heuristic"
  suggestions: list[str] = []
  summary = ""
  try:
    model_payload = _call_model_review(
      settings,
      project_detail,
      chapter,
      style_name=style_name,
      style_context=style_context,
      blueprint_section=blueprint_section,
      stage_goal=stage_goal,
      open_threads=open_threads,
      guard_context=guard_context,
    )
    if isinstance(model_payload, dict):
      source = str(model_payload.get("__model_source") or "")
      engine = "review_model" if source == "review_model" else "mixed"
      suggestions = _string_list_from_keys(model_payload, "suggestions", "actions", "next_steps")
      summary = _string_from_keys(model_payload, "summary", "结论")
  except Exception as error:
    append_app_log(settings, f"chapter review fallback for {project_detail.id}/{chapter_id}: {error}")

  consistency_dimension = _fallback_consistency_dimension(
    project_detail,
    chapter,
    _parse_model_dimension(model_payload, "consistency") if model_payload is not None else None,
  )
  structure_dimension = _structure_dimension(
    chapter,
    _parse_model_dimension(model_payload, "structure") if model_payload is not None else None,
  )
  plot_dimension = _plot_dimension(
    chapter,
    blueprint_section,
    stage_goal,
    _parse_model_dimension(model_payload, "plot") if model_payload is not None else None,
  )
  suspense_dimension = _suspense_dimension(
    chapter,
    open_threads,
    _parse_model_dimension(model_payload, "suspense") if model_payload is not None else None,
  )
  language_dimension = _language_dimension(chapter)
  continuity_dimension = _continuity_dimension(project_detail, chapter, guard_context)
  continuity_contract_dimension = _continuity_contract_dimension(project_detail, chapter, guard_context)
  obsidian_dimension = _obsidian_dimension(project_detail, chapter, guard_context)
  project_memory_dimension = _project_memory_dimension(project_detail, chapter)
  style_dimension = _style_dimension(
    settings,
    chapter,
    style_name,
    _parse_model_dimension(model_payload, "style") if model_payload is not None else None,
  )

  dimensions = [
    consistency_dimension,
    structure_dimension,
    plot_dimension,
    suspense_dimension,
    language_dimension,
    continuity_dimension,
    continuity_contract_dimension,
    obsidian_dimension,
    project_memory_dimension,
    style_dimension,
  ]
  scored_dimensions = [item.score for item in dimensions if item.status != "na"]
  overall_score = round(sum(scored_dimensions) / max(len(scored_dimensions), 1))
  if not summary:
    risk_dimensions = [item for item in dimensions if item.status == "risk"]
    watch_dimensions = [item for item in dimensions if item.status == "watch"]
    if risk_dimensions:
      summary = f"这一章当前最要紧的是 {risk_dimensions[0].label}。"
    elif watch_dimensions:
      summary = f"这一章整体能读，但 {watch_dimensions[0].label} 还要继续盯。"
    else:
      summary = "这一章整体比较完整，主要维度都还在线。"
  aggregated_suggestions = suggestions[:]
  if not aggregated_suggestions:
    for item in (
      consistency_dimension,
      structure_dimension,
      plot_dimension,
      suspense_dimension,
      continuity_contract_dimension,
      obsidian_dimension,
      project_memory_dimension,
      style_dimension,
    ):
      if item.issues:
        aggregated_suggestions.append(item.issues[0].title)
  highlights: list[str] = []
  for item in dimensions:
    if item.status == "good" and item.highlights:
      highlights.append(f"{item.label}：{item.highlights[0]}")
    if len(highlights) >= 4:
      break
  return ChapterReviewReport(
    chapter_id=chapter.id,
    chapter_index=chapter.index,
    chapter_title=chapter.title,
    version="complete",
    engine=engine,
    status=_score_status(overall_score),
    overall_score=overall_score,
    summary=summary,
    highlights=highlights[:4],
    suggestions=aggregated_suggestions[:6],
    dimensions=dimensions,
    style_name=style_name.strip(),
    updated_at=_now_iso(),
    source_signature=_review_signature(project_detail, chapter, style_name=style_name),
  )


def load_chapter_reviews(project_dir: Path, project_detail) -> list[ChapterReviewReport]:
  review_dir = _chapter_review_dir(project_dir)
  if not review_dir.exists():
    return []
  reports: list[ChapterReviewReport] = []
  for path in sorted(review_dir.glob("*.json")):
    payload = read_json(path, None)
    if not isinstance(payload, dict):
      continue
    try:
      report = ChapterReviewReport.model_validate(payload)
    except Exception:
      continue
    chapter = _chapter_or_none(project_detail, report.chapter_id)
    if chapter is None:
      continue
    current_signature = _review_signature(project_detail, chapter, style_name=report.style_name)
    reports.append(
      report.model_copy(
        update={
          "is_stale": bool(report.source_signature) and report.source_signature != current_signature,
        }
      )
    )
  return sorted(reports, key=lambda item: item.chapter_index)
