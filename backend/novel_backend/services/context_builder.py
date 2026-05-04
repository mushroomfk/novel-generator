from __future__ import annotations

from dataclasses import dataclass, field

from novel_backend.config import Settings
from novel_backend.services.preset_service import get_active_prompt_instruction, list_xp_presets
from novel_backend.services.project_distillation_service import build_task_distillation_prompt_block, resolve_task_pack_kind
from novel_backend.services.project_service import get_project_detail, search_project_knowledge
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


def compact_text(text: str, limit: int = 260) -> str:
  normalized = " ".join(text.split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


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
  project_detail = get_project_detail(settings, project_id)
  documents = project_documents_map(project_detail, overrides=override_documents)
  chapter = next((item for item in project_detail.chapters if item.id == chapter_id), None) if chapter_id else None
  knowledge_hits = (
    search_project_knowledge(settings, project_id, knowledge_query, knowledge_limit)
    if knowledge_query.strip()
    else []
  )
  knowledge_text = "\n".join(
    f"- {item.section}：{item.preview}"
    for item in knowledge_hits
  ) or "无"
  memory_text = "\n".join(_memory_lines(project_detail)) or "无"
  resolved_task_pack_kind = resolve_task_pack_kind(
    kind=task_pack_kind,
    instruction=task_instruction,
    rewrite_mode=rewrite_mode,
  )
  context_limit = _context_budget_limit(resolved_task_pack_kind, rewrite_mode)
  trimmed_blocks: list[ContextBudgetTrim] = []

  context_lines = [
    f"作品：{project_detail.name}",
    f"类型：{project_detail.genre}",
    f"目标章节数：{project_detail.target_chapters}",
    f"目标字数：{project_detail.target_words}",
    f"核心种子：{compact_text(documents.get('core_seed', ''), 260) or '无'}",
    f"人物设定：{compact_text(documents.get('character_design', ''), 320) or '无'}",
    f"世界设定：{compact_text(documents.get('world_building', ''), 320) or '无'}",
    f"情节骨架：{compact_text(documents.get('plot_structure', ''), 320) or '无'}",
  ]

  if include_blueprint:
    context_lines.append(f"章节蓝图：{compact_text(documents.get('blueprint', ''), 320) or '无'}")
  if include_character_state:
    context_lines.append(f"人物状态：{compact_text(documents.get('character_state', ''), 320) or '无'}")

  context_lines.append(f"滚动摘要：{compact_text(documents.get('global_summary', ''), 320) or '无'}")
  context_lines.append(f"项目记忆：\n{memory_text}")
  reference_character_text = "\n".join(_reference_character_lines(project_detail)) or "无"
  reference_event_text = "\n".join(_reference_event_lines(project_detail)) or "无"
  reference_material_text = "\n".join(_reference_material_lines(project_detail)) or "无"
  context_lines.append(f"参考人物：\n{reference_character_text}")
  context_lines.append(f"参考事件：\n{reference_event_text}")
  context_lines.append(f"参考资料：\n{reference_material_text}")
  if getattr(project_detail.story_overview, "materials", []):
    context_lines.append("原作承接提醒：如果上传资料里已经给出人物、关系、事件或结尾状态，后续架构和正文都必须沿着这些事实往后接，不能另起一套。")

  if chapter is not None:
    previous_chapter = next(
      (
        item for item in project_detail.chapters
        if item.index == chapter.index - 1 and item.exists and item.content.strip()
      ),
      None,
    )
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

  distillation_text = build_task_distillation_prompt_block(project_detail, kind=resolved_task_pack_kind)
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
