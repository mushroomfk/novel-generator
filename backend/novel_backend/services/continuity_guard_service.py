from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.services.context_builder import project_documents_map
from novel_backend.services.project_narrative_state_service import build_project_narrative_state_prompt
from novel_backend.services.project_service import search_project_knowledge_evidence


@dataclass(slots=True)
class ContinuityGuardContext:
  query: str
  recent_context: str
  contract_text: str
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


def _block(value: str, limit: int) -> str:
  text = str(value or "").strip()
  if len(text) <= limit:
    return text
  head_limit = max(400, limit // 2)
  tail_limit = max(400, limit - head_limit)
  return f"{text[:head_limit].rstrip()}\n[中间内容过长，已省略]\n{text[-tail_limit:].lstrip()}"


def _chapter_index(chapter) -> int:
  try:
    return int(getattr(chapter, "index", 0) or 0)
  except (TypeError, ValueError):
    return 0


def _project_total_chapters(project_detail) -> int:
  try:
    return int(getattr(project_detail, "target_chapters", 0) or 0)
  except (TypeError, ValueError):
    return 0


def _stage_label(chapter_index: int, total_chapters: int) -> str:
  if chapter_index <= 0 or total_chapters <= 0:
    return "未判定"
  ratio = chapter_index / max(total_chapters, 1)
  if ratio < 0.25:
    return "前段"
  if ratio < 0.7:
    return "中段"
  return "后段"


def _chapter_by_index(project_detail, index: int):
  return next(
    (
      item
      for item in list(getattr(project_detail, "chapters", []) or [])
      if _chapter_index(item) == index
    ),
    None,
  )


def _chapter_title(chapter) -> str:
  return str(getattr(chapter, "title", "") or "").strip() or "未命名章节"


def _chapter_window_lines(project_detail, chapter, *, before: int = 3, tail_limit: int = 420) -> list[str]:
  chapter_index = _chapter_index(chapter)
  if chapter_index <= 0:
    return []
  lines: list[str] = []
  for index in range(max(1, chapter_index - before), chapter_index):
    item = _chapter_by_index(project_detail, index)
    if item is None:
      continue
    content = str(getattr(item, "content", "") or "").strip()
    if not content:
      continue
    lines.append(f"第 {index} 章末尾｜{_chapter_title(item)}：{_tail(content, tail_limit)}")
  return lines


def _blueprint_anchor(blueprint_text: str, chapter_index: int, chapter_title: str, *, limit: int = 720) -> str:
  text = str(blueprint_text or "").strip()
  if not text or chapter_index <= 0:
    return ""
  markers = [
    f"第 {chapter_index} 章",
    f"第{chapter_index}章",
    f"Chapter {chapter_index}",
    f"chapter {chapter_index}",
    chapter_title.strip(),
  ]
  lines = [line.strip() for line in text.splitlines() if line.strip()]
  matched = [line for line in lines if any(marker and marker in line for marker in markers)]
  if matched:
    return _compact("；".join(matched[:4]), limit)
  return _compact(text, limit)


def _memory_contract_lines(memory_evidence: list[dict[str, str]], *, limit: int = 5) -> list[str]:
  lines: list[str] = []
  for item in memory_evidence[:limit]:
    title = str(item.get("title") or "项目记忆").strip()
    category = str(item.get("category") or "连续性").strip()
    content = _compact(str(item.get("content") or ""), 180)
    if content:
      lines.append(f"- {category}｜{title}：{content}")
  return lines


def _knowledge_contract_lines(knowledge_evidence: list[dict[str, object]], *, limit: int = 5) -> list[str]:
  lines: list[str] = []
  for item in knowledge_evidence[:limit]:
    source = str(item.get("source") or "资料").strip()
    section = str(item.get("section") or "片段").strip()
    content = _compact(str(item.get("content") or ""), 180)
    if content:
      lines.append(f"- {source}｜{section}：{content}")
  return lines


def build_chapter_continuity_contract(
  project_detail,
  chapter,
  *,
  instruction: str = "",
  memory_evidence: list[dict[str, str]] | None = None,
  knowledge_evidence: list[dict[str, object]] | None = None,
) -> str:
  chapter_index = _chapter_index(chapter)
  total_chapters = _project_total_chapters(project_detail)
  documents = project_documents_map(project_detail)
  project_dir = Path(str(getattr(project_detail, "path", "") or "")) if str(getattr(project_detail, "path", "") or "") else None
  chapter_id = str(getattr(chapter, "id", "") or "")
  title = _chapter_title(chapter)
  lines = [
    "章节连续性合同：",
    f"- 目标位置：第 {chapter_index or '?'} / {total_chapters or '?'} 章，阶段：{_stage_label(chapter_index, total_chapters)}。",
    f"- 当前章节：{title}",
  ]
  if instruction.strip():
    lines.append(f"- 本次任务：{_compact(instruction, 220)}")

  blueprint = _blueprint_anchor(documents.get("blueprint", ""), chapter_index, title)
  if blueprint:
    lines.append(f"- 蓝图锚点：{blueprint}")
  character_state = _compact(documents.get("character_state", ""), 520)
  if character_state:
    lines.append(f"- 人物当前状态：{character_state}")
  global_summary = _compact(documents.get("global_summary", ""), 520)
  if global_summary:
    lines.append(f"- 全书已发生事实：{global_summary}")
  plot_structure = _compact(documents.get("plot_structure", ""), 420)
  if plot_structure:
    lines.append(f"- 主线结构：{plot_structure}")

  recent_lines = _chapter_window_lines(project_detail, chapter)
  if recent_lines:
    lines.append("近期章节承接：")
    lines.extend(f"- {item}" for item in recent_lines)

  if project_dir is not None and chapter_id:
    try:
      narrative_state = build_project_narrative_state_prompt(project_dir, project_detail, chapter_id)
    except Exception:
      narrative_state = ""
    if narrative_state:
      lines.append("账本与章节约束：")
      lines.append(_block(narrative_state, 2800))

  memory_lines = _memory_contract_lines(memory_evidence or [])
  if memory_lines:
    lines.append("高优先级项目记忆：")
    lines.extend(memory_lines)

  knowledge_lines = _knowledge_contract_lines(knowledge_evidence or [])
  if knowledge_lines:
    lines.append("资料证据摘要：")
    lines.extend(knowledge_lines)

  lines.append("写作判定规则：")
  lines.extend(
    [
      "- 人物的立场、关系、能力和已知信息必须继承人物当前状态与近期章节结果。",
      "- 当前章绑定的章节合同、剧情债务、人物弧线和 Obsidian 必写项，正文没有处理时视为需要修订。",
      "- 标记为保护或禁写的真相、债务和关系，不能在当前章提前揭开或改写。",
      "- 新增行动必须能从蓝图、上一批章节或证据摘要里找到承接理由。",
    ]
  )
  return "\n".join(item for item in lines if str(item).strip()).strip()


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


def _previous_chapter_tail(project_detail, chapter, limit: int = 900) -> str:
  chapters = list(getattr(project_detail, "chapters", []) or [])
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  previous = None
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
  return _tail(str(getattr(previous, "content", "") or ""), limit) if previous is not None else ""


def _build_query(
  project_detail,
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
    _previous_chapter_tail(project_detail, chapter, 900),
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
    project_detail,
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
    chapter_index=int(getattr(chapter, "index", 0) or 0),
  )
  contract_text = build_chapter_continuity_contract(
    project_detail,
    chapter,
    instruction=instruction,
    memory_evidence=memory_evidence,
    knowledge_evidence=knowledge_evidence,
  )
  evidence_text = (
    f"{contract_text or '章节连续性合同：无'}\n\n"
    f"最近剧情：\n{recent_context or '无'}\n\n"
    f"项目记忆（手动记忆优先）：\n{_format_memory_evidence(memory_evidence)}\n\n"
    f"原文和资料证据：\n{_format_knowledge_evidence(knowledge_evidence)}"
  )
  return ContinuityGuardContext(
    query=query,
    recent_context=recent_context,
    contract_text=contract_text,
    memory_evidence=memory_evidence,
    knowledge_evidence=knowledge_evidence,
    evidence_text=evidence_text,
  )
