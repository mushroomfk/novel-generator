from __future__ import annotations

from dataclasses import dataclass

from novel_backend.config import Settings
from novel_backend.services.project_service import search_project_knowledge_evidence


@dataclass(slots=True)
class ContinuityGuardContext:
  query: str
  recent_context: str
  memory_evidence: list[dict[str, str]]
  knowledge_evidence: list[dict[str, object]]
  evidence_text: str


def _compact(value: str, limit: int) -> str:
  text = " ".join(str(value or "").split()).strip()
  if len(text) <= limit:
    return text
  return f"{text[:limit].rstrip()}..."


def _tail(value: str, limit: int) -> str:
  text = str(value or "").strip()
  if len(text) <= limit:
    return text
  return text[-limit:].lstrip()


def _memory_priority(item) -> tuple[int, int, str]:
  source = str(getattr(item, "source", "") or "")
  category = str(getattr(item, "category", "") or "")
  source_rank = 0 if source == "manual" else 1
  category_rank = {
    "硬规则": 0,
    "连续性": 1,
    "警告": 2,
    "目标": 3,
    "偏好": 4,
  }.get(category, 9)
  return source_rank, category_rank, str(getattr(item, "updated_at", "") or "")


def _collect_memory_evidence(project_detail, limit: int = 12) -> list[dict[str, str]]:
  entries = list(getattr(getattr(project_detail, "story_overview", None), "memory_entries", []) or [])
  entries.sort(key=_memory_priority)
  evidence: list[dict[str, str]] = []
  for item in entries[:limit]:
    content = _compact(str(getattr(item, "content", "") or ""), 520)
    if not content:
      continue
    source = str(getattr(item, "source", "") or "")
    evidence.append(
      {
        "id": str(getattr(item, "id", "") or ""),
        "title": str(getattr(item, "title", "") or "") or "项目记忆",
        "category": str(getattr(item, "category", "") or "连续性"),
        "source": source,
        "source_label": "手动记忆" if source == "manual" else "自动记忆",
        "content": content,
      }
    )
  return evidence


def _collect_recent_context(project_detail, chapter, limit: int = 1800) -> str:
  chapters = list(getattr(project_detail, "chapters", []) or [])
  previous = None
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  if chapter_index:
    previous = next((item for item in chapters if int(getattr(item, "index", 0) or 0) == chapter_index - 1), None)
  if previous is None:
    previous = next(
      (
        item
        for item in reversed(chapters)
        if str(getattr(item, "id", "") or "") != str(getattr(chapter, "id", "") or "")
        and str(getattr(item, "content", "") or "").strip()
      ),
      None,
    )
  previous_text = _tail(str(getattr(previous, "content", "") or ""), limit) if previous is not None else ""
  current_text = _tail(str(getattr(chapter, "content", "") or ""), limit)
  lines = [
    f"当前章节：{getattr(chapter, 'title', '') or '未命名章节'}",
    f"当前章节末尾：\n{current_text or '无'}",
  ]
  if previous_text:
    lines.append(f"上一章末尾：\n{previous_text}")
  return "\n\n".join(lines).strip()


def _build_query(
  chapter,
  instruction: str,
  *,
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
) -> str:
  pieces = [
    str(getattr(chapter, "title", "") or ""),
    instruction,
    characters_involved,
    key_items,
    scene_location,
    time_constraint,
    _tail(str(getattr(chapter, "content", "") or ""), 900),
  ]
  return " ".join(item.strip() for item in pieces if item and item.strip())


def _format_memory_evidence(memory_evidence: list[dict[str, str]]) -> str:
  if not memory_evidence:
    return "无"
  lines: list[str] = []
  for index, item in enumerate(memory_evidence, start=1):
    lines.append(
      f"[记忆 {index}] {item['source_label']}｜{item['category']}｜{item['title']}\n{item['content']}"
    )
  return "\n\n".join(lines)


def _format_knowledge_evidence(knowledge_evidence: list[dict[str, object]], limit: int = 8) -> str:
  lines: list[str] = []
  for index, item in enumerate(knowledge_evidence[:limit], start=1):
    source = str(item.get("source") or "").strip() or "未知来源"
    section = str(item.get("section") or "").strip() or "未命名片段"
    content = _compact(str(item.get("content") or ""), 900)
    if not content:
      continue
    lines.append(f"[证据 {index}] {source}｜{section}\n{content}")
  return "\n\n".join(lines).strip() or "无"


def build_continuity_guard_context(
  settings: Settings,
  *,
  project_id: str,
  project_detail,
  chapter,
  instruction: str,
  characters_involved: str = "",
  key_items: str = "",
  scene_location: str = "",
  time_constraint: str = "",
) -> ContinuityGuardContext:
  recent_context = _collect_recent_context(project_detail, chapter)
  memory_evidence = _collect_memory_evidence(project_detail)
  query = _build_query(
    chapter,
    instruction,
    characters_involved=characters_involved,
    key_items=key_items,
    scene_location=scene_location,
    time_constraint=time_constraint,
  )
  knowledge_evidence = search_project_knowledge_evidence(
    settings,
    project_id,
    query,
    limit=8,
    candidate_limit=24,
  )
  evidence_text = (
    f"最近剧情：\n{recent_context or '无'}\n\n"
    f"项目记忆（手动记忆优先）：\n{_format_memory_evidence(memory_evidence)}\n\n"
    f"原文和资料证据：\n{_format_knowledge_evidence(knowledge_evidence)}"
  )
  return ContinuityGuardContext(
    query=query,
    recent_context=recent_context,
    memory_evidence=memory_evidence,
    knowledge_evidence=knowledge_evidence,
    evidence_text=evidence_text,
  )
