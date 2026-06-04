from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.services.log_service import append_app_log
from novel_backend.services.obsidian_service import (
  obsidian_note_available_for_chapter,
  scoped_obsidian_note_records_for_chapter,
  select_obsidian_notes_for_query,
)
from novel_backend.services.preset_service import get_active_prompt_instruction, list_xp_presets
from novel_backend.services.project_distillation_service import build_task_distillation_prompt_block, resolve_task_pack_kind
from novel_backend.services.project_narrative_state_service import build_project_narrative_state_prompt
from novel_backend.services.project_service import get_project_detail, search_project_knowledge
from novel_backend.services.project_style_xp_evolution_service import build_project_style_xp_prompt
from novel_backend.services.style_service import build_style_reference_text


@dataclass(slots=True)
class ProjectContextBundle:
  project_detail: object
  documents: dict[str, str]
  chapter: object | None
  knowledge_hits: list[object] = field(default_factory=list)
  context_lines: list[str] = field(default_factory=list)
  context_text: str = ""
  budget_report: ContextBudgetReport | None = None


@dataclass(slots=True)
class ContextBudgetTrim:
  block: str
  original_chars: int
  kept_chars: int


@dataclass(slots=True)
class ContextBudgetReport:
  limit_chars: int
  original_chars: int
  final_chars: int
  trimmed_blocks: list[ContextBudgetTrim] = field(default_factory=list)


_CONTEXT_BUDGET_BY_TASK = {
  "architecture": 18_000,
  "continuation": 18_000,
  "imitation": 20_000,
  "persona": 16_000,
}

_LONG_CHAPTER_AVERAGE_THRESHOLD = 9_000
_LONG_CHAPTER_SEGMENT_MIN = 3_500
_LONG_CHAPTER_SEGMENT_MAX = 5_500
_EXPLICIT_LENGTH_MAX = 30_000
_EXPLICIT_LENGTH_PATTERN = re.compile(r"([0-9０-９.．零〇一二三四五六七八九十百千万两\s]+?)\s*字")
_SHORT_FORM_HINTS = (
  "短稿",
  "片段",
  "一段",
  "一小段",
  "开头",
  "试写",
  "样章",
  "示范",
)
_FULL_CHAPTER_HINTS = (
  "完整章",
  "整章",
  "完整章节",
  "写完整",
  "补完整",
  "补完本章",
  "扩成完整",
  "扩到完整",
  "按目标字数",
  "达到目标字数",
  "补到目标字数",
)
_LENGTH_TARGET_HINTS = (
  "写",
  "生成",
  "续写",
  "扩写",
  "改写",
  "重写",
  "目标",
  "要求",
  "容量",
  "完整章",
  "完整章节",
  "整章",
  "扩成",
  "扩到",
  "达到",
  "达成",
  "补到",
  "补足",
  "单章均值",
)
_LENGTH_STRONG_TARGET_HINTS = (
  "目标",
  "要求",
  "容量",
  "完整章",
  "完整章节",
  "整章",
  "扩成",
  "扩到",
  "扩展为",
  "达到",
  "达成",
  "补到",
  "补足",
  "单章均值",
  "左右",
  "以上",
  "以内",
)
_LENGTH_MEASUREMENT_HINTS = (
  "当前",
  "现有",
  "已有",
  "目前",
  "现在",
  "原约",
  "原文",
  "保存校验",
  "当前正文",
  "正文约",
  "短稿",
  "已接近",
  "低于",
)
_FULL_WIDTH_DIGIT_TABLE = str.maketrans("０１２３４５６７８９．", "0123456789.")
_CHINESE_DIGITS = {
  "零": 0,
  "〇": 0,
  "一": 1,
  "二": 2,
  "两": 2,
  "三": 3,
  "四": 4,
  "五": 5,
  "六": 6,
  "七": 7,
  "八": 8,
  "九": 9,
  **{str(index): index for index in range(10)},
}
_CHINESE_UNITS = {
  "十": 10,
  "百": 100,
  "千": 1_000,
}


def compact_text(text: str, limit: int = 260) -> str:
  normalized = " ".join(text.split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _tail_text(text: str, limit: int = 700) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return normalized[-limit:].lstrip()


def _int_attr(source: object, name: str, default: int = 0) -> int:
  try:
    return int(getattr(source, name, default) or default)
  except (TypeError, ValueError):
    return default


def chapter_text_length(chapter: object | None) -> int:
  if chapter is None:
    return 0
  return len(str(getattr(chapter, "content", "") or "").strip())


def chapter_average_word_target(project_detail: object) -> int:
  target_chapters = max(1, _int_attr(project_detail, "target_chapters", 1))
  target_words = max(0, _int_attr(project_detail, "target_words", 0))
  if target_words <= 0:
    return 0
  return max(1, math.ceil(target_words / target_chapters))


def instruction_requests_explicit_length(text: str) -> bool:
  normalized = str(text or "").strip()
  if not normalized:
    return False
  if explicit_length_target(normalized) > 0:
    return True
  return any(hint in normalized for hint in _SHORT_FORM_HINTS)


def instruction_requests_full_chapter(text: str) -> bool:
  normalized = str(text or "").strip()
  if not normalized:
    return False
  return any(hint in normalized for hint in _FULL_CHAPTER_HINTS)


def _parse_arabic_length_amount(text: str) -> int:
  normalized = text.translate(_FULL_WIDTH_DIGIT_TABLE).replace(" ", "")
  if not normalized:
    return 0

  pure_match = re.fullmatch(r"(\d+(?:\.\d+)?)(万|千)?", normalized)
  if pure_match:
    number = float(pure_match.group(1))
    unit = pure_match.group(2)
    if unit == "万":
      number *= 10_000
    elif unit == "千":
      number *= 1_000
    return int(round(number))

  remaining = normalized
  total = 0.0
  highest_unit = 0
  for unit, multiplier in (("万", 10_000), ("千", 1_000), ("百", 100), ("十", 10)):
    match = re.search(rf"(\d+(?:\.\d+)?){unit}", remaining)
    if match is None:
      continue
    total += float(match.group(1)) * multiplier
    highest_unit = max(highest_unit, multiplier)
    remaining = f"{remaining[:match.start()]}{remaining[match.end():]}"

  if total <= 0:
    return 0
  if not remaining:
    return int(round(total))
  if re.fullmatch(r"\d+(?:\.\d+)?", remaining):
    tail = float(remaining)
    if highest_unit >= 1_000 and tail < 10 and "." not in remaining:
      total += tail * (highest_unit // 10)
    else:
      total += tail
    return int(round(total))
  return 0


def _parse_chinese_length_amount(text: str) -> int:
  normalized = text.translate(_FULL_WIDTH_DIGIT_TABLE).replace(" ", "")
  if not normalized:
    return 0
  if re.fullmatch(r"[0-9.]+", normalized):
    return _parse_arabic_length_amount(normalized)

  total = 0
  section = 0
  number = 0
  last_small_unit = 1
  zero_after_large_unit = False
  for char in normalized:
    if char in _CHINESE_DIGITS:
      number = _CHINESE_DIGITS[char]
      if number == 0 and last_small_unit >= 1_000:
        zero_after_large_unit = True
      continue
    if char in _CHINESE_UNITS:
      unit = _CHINESE_UNITS[char]
      section += (number or 1) * unit
      number = 0
      last_small_unit = unit
      zero_after_large_unit = False
      continue
    if char == "万":
      total += (section + number or 1) * 10_000
      section = 0
      number = 0
      last_small_unit = 10_000
      zero_after_large_unit = False
      continue
    return 0

  if number and last_small_unit >= 1_000 and not zero_after_large_unit:
    return total + section + number * (last_small_unit // 10)
  return total + section + number


def _parse_length_amount(text: str) -> int:
  normalized = str(text or "").strip()
  if not normalized:
    return 0
  parsed = _parse_arabic_length_amount(normalized)
  if parsed > 0:
    return parsed
  return _parse_chinese_length_amount(normalized)


def _contains_any_hint(text: str, hints: tuple[str, ...]) -> bool:
  return any(hint in text for hint in hints)


def _length_candidate_score(text: str, match: re.Match[str]) -> int:
  before = text[max(0, match.start() - 16) : match.start()]
  after = text[match.end() : match.end() + 16]
  around = f"{before}{after}"
  target_hint = _contains_any_hint(around, _LENGTH_TARGET_HINTS)
  strong_target_hint = _contains_any_hint(around, _LENGTH_STRONG_TARGET_HINTS)
  measurement_hint = _contains_any_hint(around, _LENGTH_MEASUREMENT_HINTS)

  if measurement_hint and not strong_target_hint:
    return -100

  score = 0
  if target_hint:
    score += 100
  if re.search(r"(写|生成|续写|扩写|改写|重写|补写)\s*$", before):
    score += 50
  if _contains_any_hint(after, ("目标", "要求", "容量", "左右", "以上", "以内")):
    score += 40
  if len(text.strip()) <= 24:
    score += 20
  if measurement_hint:
    score -= 80
  return score


def explicit_length_target(text: str) -> int:
  normalized = str(text or "").strip()
  if not normalized:
    return 0
  candidates: list[tuple[int, int, int]] = []
  for match in _EXPLICIT_LENGTH_PATTERN.finditer(normalized):
    number = _parse_length_amount(match.group(1))
    if number <= 0:
      continue
    score = _length_candidate_score(normalized, match)
    if score <= 0:
      continue
    candidates.append((score, match.start(), number))
  if not candidates:
    return 0
  _score, _position, number = max(candidates, key=lambda item: (item[0], item[1]))
  return max(300, min(number, _EXPLICIT_LENGTH_MAX))


def recommended_chapter_generation_target(
  project_detail: object,
  chapter: object | None = None,
  *,
  requested_target: int = 0,
  prefer_project_budget: bool = False,
) -> int:
  requested = max(0, int(requested_target or 0))
  average = chapter_average_word_target(project_detail)
  if average <= 0:
    return requested or 1_800

  if average < _LONG_CHAPTER_AVERAGE_THRESHOLD:
    return requested or min(8_000, max(1_200, average))

  segment_target = min(
    _LONG_CHAPTER_SEGMENT_MAX,
    max(_LONG_CHAPTER_SEGMENT_MIN, math.ceil(average / 3)),
  )
  if chapter is not None:
    remaining = max(0, average - chapter_text_length(chapter))
    if remaining > 0:
      segment_target = min(segment_target, max(_LONG_CHAPTER_SEGMENT_MIN, remaining))

  if not prefer_project_budget and requested > 0:
    return requested
  if requested <= 0:
    return segment_target
  if requested < int(segment_target * 0.7):
    return segment_target
  return requested


def full_chapter_generation_target(project_detail: object, chapter: object | None = None) -> int:
  average = chapter_average_word_target(project_detail)
  if average <= 0:
    return 0
  if chapter is None:
    return min(_EXPLICIT_LENGTH_MAX, average)
  remaining = max(0, average - chapter_text_length(chapter))
  return min(_EXPLICIT_LENGTH_MAX, remaining or average)


def build_chapter_length_guidance(
  project_detail: object,
  chapter: object | None = None,
  *,
  generation_target: int = 0,
) -> str:
  target_chapters = max(1, _int_attr(project_detail, "target_chapters", 1))
  target_words = max(0, _int_attr(project_detail, "target_words", 0))
  average = chapter_average_word_target(project_detail)
  if target_words <= 0 or average <= 0:
    return ""

  lower = max(300, int(average * 0.9))
  upper = max(lower, int(average * 1.1))
  lines = [
    (
      f"章节容量校验：全书目标 {target_words} 字 / {target_chapters} 章，"
      f"单章均值约 {average} 字，完整章建议落在 {lower} 到 {upper} 字。"
    )
  ]
  if average >= _LONG_CHAPTER_AVERAGE_THRESHOLD:
    lines.append(
      "单章容量较大时，正文应按上、中、下三段推进，不能把两三千字短稿当作完整章节。"
    )

  if chapter is not None:
    current_length = chapter_text_length(chapter)
    remaining = max(0, average - current_length)
    chapter_index = _int_attr(chapter, "index", 0)
    if chapter_index:
      lines.append(f"当前第 {chapter_index} 章约 {current_length} 字，距离均值还差约 {remaining} 字。")
    else:
      lines.append(f"当前章节约 {current_length} 字，距离均值还差约 {remaining} 字。")
    if remaining > 0 and current_length < int(average * 0.75):
      lines.append("本章目前明显偏短，后续应优先扩展本章内容，再进入下一章。")

  if generation_target > 0:
    lines.append(f"本次生成建议目标约 {generation_target} 字，作为完整章节的一段或一次扩展量。")

  return "\n".join(lines)


def _context_budget_limit(kind: str, rewrite_mode: str = "") -> int:
  if rewrite_mode.strip():
    return 22_000
  return _CONTEXT_BUDGET_BY_TASK.get(kind.strip(), 18_000)


def _chapter_content_limit(kind: str, rewrite_mode: str = "") -> int:
  if rewrite_mode.strip():
    return 14_000
  if kind == "architecture":
    return 3_600
  if kind == "persona":
    return 6_000
  if kind == "imitation":
    return 10_000
  return 8_000


def _fit_text_to_budget(
  *,
  label: str,
  text: str,
  limit: int,
  trimmed_blocks: list[ContextBudgetTrim],
) -> str:
  content = str(text or "").strip()
  if len(content) <= limit:
    return content

  kept_limit = max(200, limit)
  head_chars = max(80, int(kept_limit * 0.48))
  tail_chars = max(80, kept_limit - head_chars - 90)
  shortened = (
    f"{content[:head_chars].rstrip()}\n\n"
    f"[{label}中间内容已按上下文预算缩短，原长 {len(content)} 字。]\n\n"
    f"{content[-tail_chars:].lstrip()}"
  ).strip()
  trimmed_blocks.append(
    ContextBudgetTrim(
      block=label,
      original_chars=len(content),
      kept_chars=len(shortened),
    )
  )
  return shortened


def _build_budget_report(
  *,
  original_text: str,
  final_text: str,
  limit_chars: int,
  trimmed_blocks: list[ContextBudgetTrim],
) -> ContextBudgetReport:
  return ContextBudgetReport(
    limit_chars=limit_chars,
    original_chars=len(original_text),
    final_chars=len(final_text),
    trimmed_blocks=trimmed_blocks,
  )


def project_documents_map(project_detail, overrides: dict[str, str] | None = None) -> dict[str, str]:
  documents = {
    item.key: item.content.strip()
    for item in project_detail.story_overview.documents
  }
  for key, value in (overrides or {}).items():
    cleaned = value.strip()
    if cleaned:
      documents[key] = cleaned
  return documents


def _xp_instruction(settings: Settings, xp_name: str) -> str:
  if not xp_name.strip():
    return ""
  for item in list_xp_presets(settings):
    if item.name == xp_name.strip():
      return item.content.strip()
  return ""


def build_prompt_support(
  settings: Settings,
  *,
  task_key: str,
  style_name: str = "",
  style_task_type: str = "chapter",
  style_query: str = "",
  xp_name: str = "",
  project_id: str = "",
  chapter_id: str = "",
  chapter_index: int = 0,
) -> str:
  blocks: list[str] = []
  preset_text = get_active_prompt_instruction(settings, task_key)
  if preset_text:
    blocks.append(f"提示词方案：{preset_text}")

  style_text = build_style_reference_text(settings, style_name, style_task_type, query=style_query)
  if style_text:
    blocks.append(style_text)

  xp_text = _xp_instruction(settings, xp_name)
  if xp_text:
    blocks.append(f"XP 预设：{xp_text}")

  if project_id.strip():
    try:
      project_detail = get_project_detail(
        settings,
        project_id.strip(),
        allow_model_overview=False,
        use_model_overview_cache=False,
      )
      try:
        resolved_chapter_index = int(chapter_index or 0)
      except (TypeError, ValueError):
        resolved_chapter_index = 0
      if resolved_chapter_index <= 0 and chapter_id.strip():
        chapter = next(
          (
            item
            for item in getattr(project_detail, "chapters", []) or []
            if str(getattr(item, "id", "") or "") == chapter_id.strip()
          ),
          None,
        )
        resolved_chapter_index = _int_attr(chapter, "index", 0)
      learned_text = build_project_style_xp_prompt(
        Path(project_detail.path),
        task_key=task_key,
        project_detail=project_detail,
        chapter_index=resolved_chapter_index,
      )
      if learned_text:
        blocks.append(learned_text)
    except Exception as error:
      append_app_log(settings, f"style/xp prompt support failed for {project_id.strip()}: {error}")

  return "\n\n".join(blocks).strip()


def _memory_lines(project_detail) -> list[str]:
  entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  auto_priority = {
    "auto-world-rules": 0,
    "auto-character-states": 1,
    "auto-recent-progress": 2,
    "auto-key-elements": 3,
    "auto-open-threads": 4,
    "auto-stage-goal": 5,
    "auto-image-field": 6,
  }
  ordered_entries = sorted(
    entries,
    key=lambda item: (
      0 if str(getattr(item, "source", "manual")) == "manual" else 1,
      auto_priority.get(str(getattr(item, "id", "") or ""), 20),
      str(getattr(item, "category", "") or ""),
      str(getattr(item, "title", "") or ""),
    ),
  )
  lines: list[str] = []
  for item in ordered_entries[:12]:
    category = str(getattr(item, "category", "") or "").strip()
    title = str(getattr(item, "title", "") or "").strip()
    content = str(getattr(item, "content", "") or "").strip()
    source = str(getattr(item, "source", "manual") or "manual").strip()
    if not content:
      continue
    source_label = "系统整理" if source == "auto" else "作者明确要求"
    prefix = " / ".join(part for part in [source_label, category, title] if part)
    if prefix:
      lines.append(f"- {prefix}：{compact_text(content, 160)}")
    else:
      lines.append(f"- {compact_text(content, 160)}")
  return lines


def _reference_character_lines(project_detail, limit: int = 6) -> list[str]:
  lines: list[str] = []
  for item in getattr(project_detail.story_overview, "characters", [])[:limit]:
    name = str(getattr(item, "name", "") or "").strip()
    if not name:
      continue
    anchor = str(getattr(item, "current_state", "") or "").strip() or str(getattr(item, "profile", "") or "").strip()
    extras: list[str] = []
    if anchor:
      extras.append(compact_text(anchor, 90))
    events = list(getattr(item, "events", []) or [])[:2]
    if events:
      extras.append(f"涉及：{' / '.join(events)}")
    lines.append(f"- {name}" + (f"：{'；'.join(extras)}" if extras else ""))
  return lines


def _reference_event_lines(project_detail, limit: int = 6) -> list[str]:
  lines: list[str] = []
  for item in getattr(project_detail.story_overview, "events", [])[:limit]:
    name = str(getattr(item, "name", "") or "").strip()
    if not name:
      continue
    summary = str(getattr(item, "summary", "") or "").strip()
    related = list(getattr(item, "related_characters", []) or [])[:3]
    extras: list[str] = []
    if summary:
      extras.append(compact_text(summary, 90))
    if related:
      extras.append(f"相关人物：{' / '.join(related)}")
    lines.append(f"- {name}" + (f"：{'；'.join(extras)}" if extras else ""))
  return lines


def _reference_material_lines(project_detail, limit: int = 4) -> list[str]:
  lines: list[str] = []
  for item in getattr(project_detail.story_overview, "materials", [])[:limit]:
    title = str(getattr(item, "title", "") or "").strip()
    preview = str(getattr(item, "preview", "") or "").strip()
    if not title:
      continue
    lines.append(f"- {title}：{compact_text(preview, 100) if preview else '已导入参考资料'}")
  return lines


def _obsidian_notes_for_scope(project_detail, chapter_index: int = 0) -> list[object]:
  obsidian = getattr(project_detail.story_overview, "obsidian", None)
  notes = list(getattr(obsidian, "notes", []) or [])
  if chapter_index <= 0:
    return notes
  project_path = str(getattr(project_detail, "path", "") or "").strip()
  if project_path:
    try:
      return [
        record.summary
        for record in scoped_obsidian_note_records_for_chapter(Path(project_path), chapter_index)
      ]
    except Exception:
      pass
  return [item for item in notes if obsidian_note_available_for_chapter(item, chapter_index)]


def _obsidian_note_source_map(project_detail, chapter_index: int = 0) -> dict[str, object]:
  notes = _obsidian_notes_for_scope(project_detail, chapter_index)
  return {
    str(getattr(item, "source_key", "") or "").strip(): item
    for item in notes
    if str(getattr(item, "source_key", "") or "").strip()
  }


def _filter_obsidian_knowledge_hits_for_chapter(
  project_detail,
  hits: list[object],
  chapter_index: int = 0,
) -> list[object]:
  if chapter_index <= 0:
    return hits
  note_by_source_key = _obsidian_note_source_map(project_detail, chapter_index)
  filtered: list[object] = []
  for hit in hits:
    source = str(getattr(hit, "source", "") or "").strip()
    if source != "Obsidian":
      filtered.append(hit)
      continue
    source_key = str(getattr(hit, "source_key", "") or "").strip()
    note = note_by_source_key.get(source_key)
    if note is None:
      continue
    if obsidian_note_available_for_chapter(note, chapter_index):
      safe_preview = compact_text(str(getattr(note, "preview", "") or "").strip(), 180)
      if not safe_preview:
        safe_preview = f"Obsidian 笔记：{str(getattr(note, 'title', '') or '').strip() or source_key}"
      if hasattr(hit, "model_copy"):
        filtered.append(hit.model_copy(update={"preview": safe_preview}))
      else:
        filtered.append(hit)
  return filtered


def _obsidian_chapter_scope_text(item: object) -> str:
  chapter_start = _int_attr(item, "chapter_start", 0)
  chapter_end = _int_attr(item, "chapter_end", 0)
  reveal_after = _int_attr(item, "reveal_after_chapter", 0)
  parts: list[str] = []
  if chapter_start and chapter_end:
    if chapter_start == chapter_end:
      parts.append(f"适用章节：第 {chapter_start} 章")
    else:
      parts.append(f"适用章节：第 {chapter_start}-{chapter_end} 章")
  elif chapter_start:
    parts.append(f"适用章节：第 {chapter_start} 章起")
  elif chapter_end:
    parts.append(f"适用章节：第 {chapter_end} 章前")
  if reveal_after:
    parts.append(f"剧透边界：第 {reveal_after} 章后可用")
  return "；".join(parts)


def _obsidian_lookup_key(value: str) -> str:
  normalized = str(value or "").strip().replace("\\", "/").lower()
  if normalized.endswith(".md"):
    normalized = normalized[:-3]
  return normalized


def _obsidian_visible_note_lookup(notes: list[object]) -> dict[str, object]:
  lookup: dict[str, object] = {}
  for note in notes:
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    title = str(getattr(note, "title", "") or "").strip()
    aliases = [str(value).strip() for value in list(getattr(note, "aliases", []) or []) if str(value).strip()]
    labels = [
      relative_path,
      Path(relative_path).with_suffix("").as_posix() if relative_path else "",
      Path(relative_path).stem if relative_path else "",
      title,
      *aliases,
    ]
    for label in labels:
      key = _obsidian_lookup_key(label)
      if key and key not in lookup:
        lookup[key] = note
  return lookup


def _obsidian_relation_target(value: str) -> tuple[str, str]:
  if "->" not in value:
    return "", ""
  label, target = value.split("->", 1)
  return label.strip(), target.strip()


def _obsidian_note_display_label(note: object | None, fallback: str = "") -> str:
  if note is None:
    return str(fallback or "").strip()
  title = str(getattr(note, "title", "") or "").strip()
  if title:
    return title
  relative_path = str(getattr(note, "relative_path", "") or "").strip()
  return Path(relative_path).stem if relative_path else str(fallback or "").strip()


def _obsidian_relation_label_for_context(label: str, visible_lookup: dict[str, object]) -> str:
  cleaned = str(label or "").strip()
  if not cleaned:
    return ""
  for separator in ("：", ":"):
    if separator not in cleaned:
      continue
    prefix, tail = cleaned.rsplit(separator, 1)
    tail = tail.strip()
    target_note = visible_lookup.get(_obsidian_lookup_key(tail))
    if target_note is None:
      continue
    return f"{prefix.strip()}{separator}{_obsidian_note_display_label(target_note, tail)}"

  target_note = visible_lookup.get(_obsidian_lookup_key(cleaned))
  if target_note is not None:
    return _obsidian_note_display_label(target_note, cleaned)
  return cleaned


def _obsidian_relation_line_for_context(
  relation: str,
  visible_lookup: dict[str, object],
  *,
  require_visible_target: bool,
) -> str:
  label, target = _obsidian_relation_target(relation)
  if not label or not target:
    return ""
  target_note = visible_lookup.get(_obsidian_lookup_key(target))
  if target_note is None:
    return "" if require_visible_target else relation
  display_label = _obsidian_relation_label_for_context(label, visible_lookup)
  display_target = _obsidian_note_display_label(target_note, target)
  if not display_label or not display_target:
    return ""
  return f"{display_label} -> {display_target}"


def _obsidian_embedded_preview_lines(item: object, visible_lookup: dict[str, object], limit: int = 2) -> list[str]:
  lines: list[str] = []
  seen: set[str] = set()
  for raw_link in list(getattr(item, "embedded_links", []) or []):
    target_note = visible_lookup.get(_obsidian_lookup_key(str(raw_link or "")))
    if target_note is None:
      continue
    path = str(getattr(target_note, "relative_path", "") or "").strip()
    key = path or _obsidian_lookup_key(str(raw_link or ""))
    if not key or key in seen:
      continue
    seen.add(key)
    label = _obsidian_note_display_label(target_note, str(raw_link or ""))
    preview = str(getattr(target_note, "preview", "") or "").strip() or str(getattr(target_note, "summary", "") or "").strip()
    if preview:
      lines.append(f"{label}：{compact_text(preview, 80)}")
    elif label:
      lines.append(label)
    if len(lines) >= limit:
      break
  return lines


def _obsidian_external_reference_lines(item: object, limit: int = 2) -> list[str]:
  lines: list[str] = []
  seen: set[str] = set()
  references = list(getattr(item, "external_references", []) or [])
  if not references:
    references = list(getattr(item, "external_links", []) or [])
  for raw_reference in references:
    reference = str(raw_reference or "").strip()
    if not reference or reference in seen:
      continue
    seen.add(reference)
    lines.append(compact_text(reference, 120))
    if len(lines) >= limit:
      break
  return lines


def _chapter_safe_obsidian_relation_lines(
  item: object,
  visible_lookup: dict[str, object],
  chapter_index: int,
  limit: int,
) -> list[str]:
  relations = [
    str(value).strip()
    for value in list(getattr(item, "graph_relations", []) or [])
    if str(value).strip()
  ]
  if chapter_index <= 0:
    lines = [
      _obsidian_relation_line_for_context(relation, visible_lookup, require_visible_target=False)
      for relation in relations
    ]
    return [line for line in lines if line][:limit]

  safe_relations: list[str] = []
  for relation in relations:
    line = _obsidian_relation_line_for_context(relation, visible_lookup, require_visible_target=True)
    if not line:
      continue
    safe_relations.append(line)
    if len(safe_relations) >= limit:
      break
  return safe_relations


def _select_obsidian_notes_for_context(notes: list[object], query: str, limit: int, chapter_index: int = 0) -> list[object]:
  return select_obsidian_notes_for_query(notes, query, limit=limit, chapter_index=chapter_index)


def _obsidian_notes_for_context(
  project_detail,
  query: str = "",
  limit: int = 8,
  chapter_index: int = 0,
) -> list[object]:
  notes = _obsidian_notes_for_scope(project_detail, chapter_index)
  return _select_obsidian_notes_for_context(notes, query, limit, chapter_index=chapter_index)


def _reference_obsidian_lines(project_detail, query: str = "", limit: int = 8, chapter_index: int = 0) -> list[str]:
  notes = _obsidian_notes_for_scope(project_detail, chapter_index)
  selected_notes = _obsidian_notes_for_context(project_detail, query, limit, chapter_index=chapter_index)
  available_notes = [item for item in notes if obsidian_note_available_for_chapter(item, chapter_index)]
  visible_lookup = _obsidian_visible_note_lookup(available_notes)
  note_by_path = {
    str(getattr(item, "relative_path", "") or "").strip(): item
    for item in available_notes
    if str(getattr(item, "relative_path", "") or "").strip()
  }

  def note_label(path: str) -> str:
    note = note_by_path.get(path)
    if note is None:
      return ""
    return str(getattr(note, "title", "") or "").strip() or Path(path).stem or path

  lines: list[str] = []
  for item in selected_notes:
    title = str(getattr(item, "title", "") or "").strip()
    if not title:
      continue
    preview = str(getattr(item, "preview", "") or "").strip()
    note_type = str(getattr(item, "note_type", "") or "").strip()
    status = str(getattr(item, "status", "") or "").strip()
    chapter_scope = _obsidian_chapter_scope_text(item)
    links = list(getattr(item, "links", []) or [])[:3]
    resolved = [
      label
      for label in (note_label(str(path)) for path in list(getattr(item, "resolved_links", []) or []))
      if label
    ][:3]
    relations = _chapter_safe_obsidian_relation_lines(item, visible_lookup, chapter_index, 3)
    embedded_previews = _obsidian_embedded_preview_lines(item, visible_lookup, 2)
    external_references = _obsidian_external_reference_lines(item, 2)
    backlinks = [
      label
      for label in (note_label(str(path)) for path in list(getattr(item, "backlinks", []) or []))
      if label
    ][:3]
    unresolved = list(getattr(item, "unresolved_links", []) or [])[:2]
    ambiguous = list(getattr(item, "ambiguous_links", []) or [])[:2]
    meta = " / ".join(part for part in [note_type, status, chapter_scope] if part)
    related_parts = []
    if resolved:
      related_parts.append(f"关联笔记：{' / '.join(resolved)}")
    elif links and chapter_index <= 0:
      related_parts.append(f"双链：{' / '.join(links)}")
    if relations:
      related_parts.append(f"关系：{' / '.join(relations)}")
    if embedded_previews:
      related_parts.append(f"嵌入预览：{' / '.join(embedded_previews)}")
    if external_references:
      related_parts.append(f"考据来源：{' / '.join(external_references)}")
    if backlinks:
      related_parts.append(f"被引用：{' / '.join(backlinks)}")
    if unresolved:
      related_parts.append(f"未解析：{' / '.join(unresolved)}")
    if ambiguous:
      related_parts.append(f"歧义：{' / '.join(ambiguous)}")
    related = f"；{'；'.join(related_parts)}" if related_parts else ""
    suffix = compact_text(preview, 100) if preview else "已同步笔记"
    lines.append(f"- {title}" + (f"（{meta}）" if meta else "") + f"：{suffix}{related}")
  return lines


def _obsidian_constraint_lines(project_detail, query: str = "", limit: int = 8, chapter_index: int = 0) -> list[str]:
  lines: list[str] = []
  for item in _obsidian_notes_for_context(project_detail, query, limit, chapter_index=chapter_index):
    title = str(getattr(item, "title", "") or "").strip()
    if not title:
      continue
    path = str(getattr(item, "relative_path", "") or "").strip()
    label = f"{title}（{path}）" if path else title
    required = [str(value).strip() for value in list(getattr(item, "required_phrases", []) or []) if str(value).strip()]
    forbidden = [str(value).strip() for value in list(getattr(item, "forbidden_phrases", []) or []) if str(value).strip()]
    if required:
      lines.append(f"- 必须包含｜{label}：{' / '.join(required[:8])}")
    if forbidden:
      lines.append(f"- 禁止出现｜{label}：{' / '.join(forbidden[:8])}")
    if len(lines) >= limit * 2:
      break
  return lines


def _obsidian_chapter_checklist_lines(project_detail, query: str = "", limit: int = 6, chapter_index: int = 0) -> list[str]:
  notes = _obsidian_notes_for_scope(project_detail, chapter_index)
  selected_notes = _obsidian_notes_for_context(project_detail, query, limit, chapter_index=chapter_index)
  available_notes = [item for item in notes if obsidian_note_available_for_chapter(item, chapter_index)]
  visible_lookup = _obsidian_visible_note_lookup(available_notes)
  note_by_path = {
    str(getattr(item, "relative_path", "") or "").strip(): item
    for item in available_notes
    if str(getattr(item, "relative_path", "") or "").strip()
  }

  def note_label(path: str) -> str:
    note = note_by_path.get(path)
    if note is None:
      return ""
    return str(getattr(note, "title", "") or "").strip() or Path(path).stem or path

  lines: list[str] = []
  for item in selected_notes[:limit]:
    title = str(getattr(item, "title", "") or "").strip()
    path = str(getattr(item, "relative_path", "") or "").strip()
    if not title and not path:
      continue
    label = f"{title or Path(path).stem}（{path}）" if path else title
    required = [str(value).strip() for value in list(getattr(item, "required_phrases", []) or []) if str(value).strip()]
    forbidden = [str(value).strip() for value in list(getattr(item, "forbidden_phrases", []) or []) if str(value).strip()]
    chapter_scope = _obsidian_chapter_scope_text(item)
    resolved = [
      label
      for label in (note_label(str(path_value)) for path_value in list(getattr(item, "resolved_links", []) or []))
      if label
    ][:3]
    relations = _chapter_safe_obsidian_relation_lines(item, visible_lookup, chapter_index, 4)
    embedded_previews = _obsidian_embedded_preview_lines(item, visible_lookup, 2)
    external_references = _obsidian_external_reference_lines(item, 2)
    backlinks = [
      label
      for label in (note_label(str(path_value)) for path_value in list(getattr(item, "backlinks", []) or []))
      if label
    ][:3]
    ambiguous = [str(value).strip() for value in list(getattr(item, "ambiguous_links", []) or []) if str(value).strip()]
    unresolved = [str(value).strip() for value in list(getattr(item, "unresolved_links", []) or []) if str(value).strip()]

    parts = [f"来源｜{label}"]
    if chapter_scope:
      parts.append(chapter_scope)
    if required:
      parts.append(f"必须出现：{' / '.join(required[:6])}")
    if forbidden:
      parts.append(f"禁止出现：{' / '.join(forbidden[:6])}")
    if resolved:
      parts.append(f"关联笔记：{' / '.join(resolved)}")
    if relations:
      parts.append(f"关系：{' / '.join(relations)}")
    if embedded_previews:
      parts.append(f"嵌入预览：{' / '.join(embedded_previews)}")
    if external_references:
      parts.append(f"考据来源：{' / '.join(external_references)}")
    if backlinks:
      parts.append(f"反向关联：{' / '.join(backlinks)}")
    graph_warnings: list[str] = []
    if ambiguous:
      graph_warnings.append(f"歧义双链 {' / '.join(ambiguous[:4])}")
    if unresolved:
      graph_warnings.append(f"未解析双链 {' / '.join(unresolved[:4])}")
    if graph_warnings:
      parts.append(f"图谱注意：{'；'.join(graph_warnings)}")
    lines.append("- " + "；".join(parts))
  return lines


def build_project_context_bundle(
  settings: Settings,
  project_id: str,
  *,
  include_blueprint: bool = True,
  include_character_state: bool = True,
  chapter_id: str = "",
  knowledge_query: str = "",
  knowledge_limit: int = 5,
  task_pack_kind: str = "",
  task_instruction: str = "",
  rewrite_mode: str = "",
  override_documents: dict[str, str] | None = None,
) -> ProjectContextBundle:
  resolved_task_pack_kind = resolve_task_pack_kind(
    kind=task_pack_kind,
    instruction=task_instruction,
    rewrite_mode=rewrite_mode,
  )
  project_detail = get_project_detail(
    settings,
    project_id,
    allow_model_overview=False,
    use_model_overview_cache=False,
  )
  documents = project_documents_map(project_detail, overrides=override_documents)
  chapter = next((item for item in project_detail.chapters if item.id == chapter_id), None) if chapter_id else None
  target_chapter_index = _int_attr(chapter, "index", 0) if chapter is not None else 0
  previous_chapter = None
  if chapter is not None:
    previous_chapter = next(
      (
        item for item in project_detail.chapters
        if item.index == chapter.index - 1 and item.exists and item.content.strip()
      ),
      None,
    )
  lightweight_knowledge = resolved_task_pack_kind == "architecture"
  knowledge_hits = (
    search_project_knowledge(
      settings,
      project_id,
      knowledge_query,
      knowledge_limit,
      ensure_current=not lightweight_knowledge,
      include_semantic=not lightweight_knowledge,
      chapter_index=target_chapter_index,
    )
    if knowledge_query.strip()
    else []
  )
  knowledge_hits = _filter_obsidian_knowledge_hits_for_chapter(project_detail, knowledge_hits, target_chapter_index)
  knowledge_text = "\n".join(
    f"- {item.section}：{item.preview}"
    for item in knowledge_hits
  ) or "无"
  memory_text = "\n".join(_memory_lines(project_detail)) or "无"
  context_limit = _context_budget_limit(resolved_task_pack_kind, rewrite_mode)
  trimmed_blocks: list[ContextBudgetTrim] = []

  context_lines = [
    f"作品：{project_detail.name}",
    f"类型：{project_detail.genre}",
    f"目标章节数：{project_detail.target_chapters}",
    f"目标字数：{project_detail.target_words}",
    build_chapter_length_guidance(project_detail, chapter),
    f"核心种子：{compact_text(documents.get('core_seed', ''), 260) or '无'}",
    f"人物设定：{compact_text(documents.get('character_design', ''), 320) or '无'}",
    f"世界设定：{compact_text(documents.get('world_building', ''), 320) or '无'}",
    f"情节骨架：{compact_text(documents.get('plot_structure', ''), 320) or '无'}",
  ]
  context_lines = [item for item in context_lines if item]

  if include_blueprint:
    context_lines.append(f"章节蓝图：{compact_text(documents.get('blueprint', ''), 320) or '无'}")
  if include_character_state:
    context_lines.append(f"人物状态：{compact_text(documents.get('character_state', ''), 320) or '无'}")

  context_lines.append(f"滚动摘要：{compact_text(documents.get('global_summary', ''), 320) or '无'}")
  context_lines.append(f"项目记忆：\n{memory_text}")
  if chapter is not None:
    try:
      narrative_state_text = build_project_narrative_state_prompt(Path(project_detail.path), project_detail, chapter.id)
      if narrative_state_text:
        context_lines.append(narrative_state_text)
    except Exception as error:
      append_app_log(settings, f"narrative state context failed for {project_id}/{chapter.id}: {error}")
  reference_character_text = "\n".join(_reference_character_lines(project_detail)) or "无"
  reference_event_text = "\n".join(_reference_event_lines(project_detail)) or "无"
  reference_material_text = "\n".join(_reference_material_lines(project_detail)) or "无"
  obsidian_context_query = " ".join(
    part
    for part in [
      knowledge_query,
      task_instruction,
      str(getattr(chapter, "title", "") or "") if chapter is not None else "",
      _tail_text(str(getattr(chapter, "content", "") or ""), 700) if chapter is not None else "",
      _tail_text(str(getattr(previous_chapter, "content", "") or ""), 700) if previous_chapter is not None else "",
    ]
    if part
  )
  reference_obsidian_text = "\n".join(_reference_obsidian_lines(
    project_detail,
    query=obsidian_context_query,
    chapter_index=target_chapter_index,
  )) or "无"
  obsidian_checklist_text = "\n".join(_obsidian_chapter_checklist_lines(
    project_detail,
    query=obsidian_context_query,
    chapter_index=target_chapter_index,
  )) or ""
  obsidian_constraint_text = "\n".join(_obsidian_constraint_lines(
    project_detail,
    query=obsidian_context_query,
    chapter_index=target_chapter_index,
  )) or ""
  context_lines.append(f"参考人物：\n{reference_character_text}")
  context_lines.append(f"参考事件：\n{reference_event_text}")
  context_lines.append(f"参考资料：\n{reference_material_text}")
  context_lines.append(f"Obsidian 设定笔记：\n{reference_obsidian_text}")
  if obsidian_checklist_text:
    context_lines.append(f"本章 Obsidian 设定检查清单：\n{obsidian_checklist_text}")
  if obsidian_constraint_text:
    context_lines.append(f"本章 Obsidian 写作约束：\n{obsidian_constraint_text}")
  if getattr(project_detail.story_overview, "materials", []):
    context_lines.append("原作承接提醒：如果上传资料里已经给出人物、关系、事件或结尾状态，后续架构和正文都必须沿着这些事实往后接，不能另起一套。")

  if chapter is not None:
    chapter_content = _fit_text_to_budget(
      label="当前章节正文",
      text=chapter.content.strip() or "无",
      limit=_chapter_content_limit(resolved_task_pack_kind, rewrite_mode),
      trimmed_blocks=trimmed_blocks,
    )
    context_lines.extend(
      [
        f"当前章节：第 {chapter.index} 章《{chapter.title}》",
        f"当前章节状态：{'已有正文' if chapter.exists else '待写章节'}",
        f"当前章节正文：\n{chapter_content}",
        f"上一章末尾：{compact_text(previous_chapter.content, 320) if previous_chapter else '无'}",
      ]
    )

  distillation_text = build_task_distillation_prompt_block(
    project_detail,
    kind=resolved_task_pack_kind,
    query=obsidian_context_query,
    chapter_index=target_chapter_index,
  )
  if distillation_text:
    context_lines.append(f"任务蒸馏：\n{distillation_text}")

  context_lines.append(f"检索线索：\n{knowledge_text}")
  original_context_text = "\n".join(context_lines).strip()
  if len(original_context_text) > context_limit:
    overflow = len(original_context_text) - context_limit
    compacted_knowledge = _fit_text_to_budget(
      label="检索线索",
      text=knowledge_text,
      limit=max(400, len(knowledge_text) - overflow),
      trimmed_blocks=trimmed_blocks,
    )
    context_lines[-1] = f"检索线索：\n{compacted_knowledge or '无'}"

  final_context_text = "\n".join(context_lines).strip()
  budget_report = _build_budget_report(
    original_text=original_context_text,
    final_text=final_context_text,
    limit_chars=context_limit,
    trimmed_blocks=trimmed_blocks,
  )
  return ProjectContextBundle(
    project_detail=project_detail,
    documents=documents,
    chapter=chapter,
    knowledge_hits=knowledge_hits,
    context_lines=context_lines,
    context_text=final_context_text,
    budget_report=budget_report,
  )
