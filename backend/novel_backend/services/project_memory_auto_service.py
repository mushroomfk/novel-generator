from __future__ import annotations

import hashlib
import re

from novel_backend.models import ChapterSummary, ProjectMemoryEntry, StoryCharacter, StoryDocument, StoryEntityReference

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_SUSPENSE_TOKENS = (
  "真相",
  "身世",
  "秘密",
  "隐秘",
  "疑点",
  "线索",
  "钥匙",
  "账本",
  "航线",
  "失踪",
  "背叛",
  "怀疑",
  "证词",
  "传言",
  "信号",
  "窗口",
  "伏笔",
)
_THREAD_BLACKLIST = (
  "第一章",
  "第二章",
  "第三章",
  "第四章",
  "第五章",
  "当前章节",
  "章节蓝图",
)
_STYLE_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")
_TOKEN_STOPWORDS = {
  "现在",
  "当前",
  "已经",
  "不能",
  "不要",
  "需要",
  "还是",
  "继续",
  "保持",
  "因为",
  "所以",
  "然后",
  "这部",
  "作品",
  "主角",
  "人物",
  "章节",
  "内容",
  "时候",
}


def _compact_text(text: str, limit: int = 120) -> str:
  normalized = " ".join((text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _split_sentences(text: str) -> list[str]:
  return [
    item.strip()
    for item in _SENTENCE_RE.findall(text or "")
    if item.strip()
  ]


def _key_lines(text: str, *, limit: int = 2, line_limit: int = 80) -> list[str]:
  candidates: list[str] = []
  for raw_line in (text or "").splitlines():
    line = raw_line.strip().lstrip("#*-0123456789.、）)")
    if not line:
      continue
    candidates.append(_compact_text(line, line_limit))

  if not candidates:
    for sentence in _split_sentences(text):
      compacted = _compact_text(sentence, line_limit)
      if compacted:
        candidates.append(compacted)
      if len(candidates) >= limit:
        break

  unique: list[str] = []
  for item in candidates:
    if item and item not in unique:
      unique.append(item)
    if len(unique) >= limit:
      break
  return unique


def _written_chapters(chapters: list[ChapterSummary]) -> list[ChapterSummary]:
  return [item for item in chapters if item.exists and (item.content or "").strip()]


def _chapter_anchor(chapter: ChapterSummary) -> str:
  preview = (chapter.preview or "").strip()
  if preview:
    return _compact_text(preview, 80)
  content = (chapter.content or "").strip()
  if not content:
    return ""
  lines = content.splitlines()
  body = "\n".join(lines[1:]).strip() if lines and lines[0].strip().startswith("#") else content
  sentences = _split_sentences(body)
  if sentences:
    return _compact_text(sentences[0], 80)
  return _compact_text(body, 80)


def _top_characters(characters: list[StoryCharacter], limit: int = 3) -> list[StoryCharacter]:
  return sorted(
    characters,
    key=lambda item: (
      len(item.timeline),
      len(item.events) + len(item.relationships) + len(item.locations),
      item.name,
    ),
    reverse=True,
  )[:limit]


def _entity_focus(entities: list[StoryEntityReference], *, prefix: str, limit: int = 4) -> list[str]:
  lines: list[str] = []
  for item in entities:
    summary = _compact_text(item.summary, 52) if item.summary else ""
    chapter_label = "、".join(f"第{index}章" for index in item.chapter_indexes[:3])
    details = " / ".join(part for part in [summary, chapter_label] if part)
    if details:
      lines.append(f"{prefix}{item.name}：{details}")
    else:
      lines.append(f"{prefix}{item.name}")
    if len(lines) >= limit:
      break
  return lines


def _thread_candidates(texts: list[str], limit: int = 4) -> list[str]:
  seen: set[str] = set()
  threads: list[str] = []
  for text in texts:
    for sentence in _split_sentences(text):
      compacted = _compact_text(sentence, 88)
      if not compacted:
        continue
      if not any(token in compacted for token in _SUSPENSE_TOKENS):
        continue
      if any(flag in compacted for flag in _THREAD_BLACKLIST):
        continue
      if compacted in seen:
        continue
      seen.add(compacted)
      threads.append(compacted)
      if len(threads) >= limit:
        return threads
  return threads


def _blueprint_goal(blueprint_text: str, summary_text: str) -> str:
  blueprint_lines = _key_lines(blueprint_text, limit=3, line_limit=70)
  if blueprint_lines:
    return "\n".join(f"- {item}" for item in blueprint_lines)

  summary_lines = _key_lines(summary_text, limit=2, line_limit=90)
  if summary_lines:
    return "\n".join(f"- {item}" for item in summary_lines)
  return ""


def _image_keywords(texts: list[str], limit: int = 4) -> list[str]:
  counts: dict[str, int] = {}
  for text in texts:
    for token in _STYLE_TOKEN_RE.findall(text or ""):
      if token in _TOKEN_STOPWORDS:
        continue
      counts[token] = counts.get(token, 0) + 1

  ordered = sorted(
    counts.items(),
    key=lambda item: (item[1], len(item[0]), item[0]),
    reverse=True,
  )
  return [token for token, _count in ordered[:limit]]


def _memory_signature(
  *,
  documents: list[StoryDocument],
  characters: list[StoryCharacter],
  chapters: list[ChapterSummary],
) -> str:
  raw_parts: list[str] = []
  for item in documents:
    raw_parts.append(f"doc::{item.key}::{item.content.strip()}")
  for item in characters:
    raw_parts.append(
      "::".join(
        [
          "character",
          item.name,
          item.profile.strip(),
          item.current_state.strip(),
          "|".join(item.events[:5]),
          "|".join(item.relationships[:5]),
        ]
      )
    )
  for item in _written_chapters(chapters):
    raw_parts.append(f"chapter::{item.id}::{item.title}::{item.preview.strip()}")
  return hashlib.sha1("\n".join(raw_parts).encode("utf-8")).hexdigest()


def build_auto_project_memory(
  *,
  documents: list[StoryDocument],
  characters: list[StoryCharacter],
  events: list[StoryEntityReference],
  locations: list[StoryEntityReference],
  props: list[StoryEntityReference],
  scenes: list[StoryEntityReference],
  organizations: list[StoryEntityReference],
  chapters: list[ChapterSummary],
) -> tuple[list[ProjectMemoryEntry], str]:
  document_map = {
    item.key: item.content.strip()
    for item in documents
  }
  entries: list[ProjectMemoryEntry] = []

  world_lines = _key_lines(
    document_map.get("world_building", "") or document_map.get("core_seed", ""),
    limit=2,
    line_limit=88,
  )
  if world_lines:
    entries.append(
      ProjectMemoryEntry(
        id="auto-world-rules",
        title="世界规则",
        category="硬规则",
        content="\n".join(f"- {item}" for item in world_lines),
        source="auto",
      )
    )

  character_lines = []
  for item in _top_characters(characters):
    anchor = item.current_state.strip() or item.profile.strip()
    if not anchor:
      continue
    character_lines.append(f"- {item.name}：{_compact_text(anchor, 90)}")
  if character_lines:
    entries.append(
      ProjectMemoryEntry(
        id="auto-character-states",
        title="主要人物现状",
        category="连续性",
        content="\n".join(character_lines),
        source="auto",
      )
    )

  recent_lines = []
  for item in _written_chapters(chapters)[-3:]:
    anchor = _chapter_anchor(item)
    if not anchor:
      continue
    recent_lines.append(f"- 第 {item.index} 章《{item.title}》：{anchor}")
  if recent_lines:
    entries.append(
      ProjectMemoryEntry(
        id="auto-recent-progress",
        title="最近推进",
        category="连续性",
        content="\n".join(recent_lines),
        source="auto",
      )
    )

  key_element_lines = (
    _entity_focus(props, prefix="道具 · ", limit=2)
    + _entity_focus(organizations, prefix="组织 · ", limit=1)
    + _entity_focus(locations, prefix="地点 · ", limit=1)
  )
  if key_element_lines:
    entries.append(
      ProjectMemoryEntry(
        id="auto-key-elements",
        title="关键要素",
        category="连续性",
        content="\n".join(f"- {item}" for item in key_element_lines[:4]),
        source="auto",
      )
    )

  thread_lines = _thread_candidates(
    [
      document_map.get("global_summary", ""),
      document_map.get("plot_structure", ""),
      document_map.get("blueprint", ""),
      *[(item.preview or item.content or "") for item in _written_chapters(chapters)[-3:]],
    ],
    limit=4,
  )
  if thread_lines:
    entries.append(
      ProjectMemoryEntry(
        id="auto-open-threads",
        title="别丢的悬念",
        category="警告",
        content="\n".join(f"- {item}" for item in thread_lines),
        source="auto",
      )
    )

  stage_goal = _blueprint_goal(
    document_map.get("blueprint", ""),
    document_map.get("global_summary", ""),
  )
  if stage_goal:
    entries.append(
      ProjectMemoryEntry(
        id="auto-stage-goal",
        title="当前阶段目标",
        category="目标",
        content=stage_goal,
        source="auto",
      )
    )

  imagery = _image_keywords(
    [
      document_map.get("world_building", ""),
      document_map.get("global_summary", ""),
      *[item.name for item in props[:4]],
      *[item.name for item in scenes[:4]],
      *[item.name for item in events[:4]],
    ],
    limit=4,
  )
  if imagery:
    entries.append(
      ProjectMemoryEntry(
        id="auto-image-field",
        title="当前意象词场",
        category="偏好",
        content=" / ".join(imagery),
        source="auto",
      )
    )

  signature = _memory_signature(
    documents=documents,
    characters=characters,
    chapters=chapters,
  )
  return entries[:6], signature
