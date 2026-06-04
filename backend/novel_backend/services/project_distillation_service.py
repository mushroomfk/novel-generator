from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.models import (
  DistilledSourceProfile,
  ProjectDistillationReport,
  TaskDistillationPack,
)
from novel_backend.services.obsidian_service import scoped_obsidian_note_records_for_chapter, select_obsidian_notes_for_query
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_ARCHITECTURE_PATTERN = re.compile(r"(架构|蓝图|大纲|整书规划|整本规划|世界观|人物设定|情节骨架)")
_IMITATION_PATTERN = re.compile(r"(仿写|模仿|照着.*写|像.+一样写|复现文风|复刻文风)")
_PERSONA_PATTERN = re.compile(r"(人物复刻|角色复刻|人物视角|角色视角|像.+会怎么说|像.+会怎么做)")


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: str, limit: int = 160) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _unique_lines(items: list[str], limit: int = 8) -> list[str]:
  result: list[str] = []
  seen: set[str] = set()
  for raw_item in items:
    item = _compact_text(raw_item, 180).strip()
    if not item or item in seen:
      continue
    result.append(item)
    seen.add(item)
    if len(result) >= limit:
      break
  return result


def project_distillation_path(project_dir: Path) -> Path:
  return project_dir / "project_distillation.json"


def build_project_distillation_signature(project_detail) -> str:
  raw_parts: list[str] = ["distillation_scope::chapter_safe_v2"]
  for item in getattr(project_detail.story_overview, "documents", []) or []:
    raw_parts.append(f"doc::{item.key}::{(item.content or '').strip()}")
  for item in getattr(project_detail.story_overview, "materials", []) or []:
    raw_parts.append(f"material::{item.title}::{(item.preview or '').strip()}::{item.updated_at or ''}")
  obsidian = getattr(project_detail.story_overview, "obsidian", None)
  for item in getattr(obsidian, "notes", []) or []:
    raw_parts.append(
      "obsidian::"
      f"{item.title}::{item.relative_path}::{(item.preview or '').strip()}::{item.updated_at or ''}::"
      f"relations={','.join(getattr(item, 'graph_relations', []) or [])}::"
      f"links={','.join(getattr(item, 'resolved_links', []) or [])}::"
      f"backlinks={','.join(getattr(item, 'backlinks', []) or [])}::"
      f"unresolved={','.join(getattr(item, 'unresolved_links', []) or [])}::"
      f"ambiguous={','.join(getattr(item, 'ambiguous_links', []) or [])}::"
      f"external_refs={','.join(getattr(item, 'external_references', []) or [])}::"
      f"external_links={','.join(getattr(item, 'external_links', []) or [])}"
    )
  for item in getattr(project_detail.story_overview, "memory_entries", []) or []:
    raw_parts.append(
      f"memory::{item.id}::{item.category}::{item.title}::{(item.content or '').strip()}::{item.source}"
    )
  for item in getattr(project_detail, "chapters", []) or []:
    if not item.exists and not (item.content or "").strip():
      continue
    raw_parts.append(f"chapter::{item.id}::{item.title}::{(item.content or item.preview or '').strip()}")
  return hashlib.sha1("\n".join(raw_parts).encode("utf-8")).hexdigest()


def load_project_distillation(
  project_dir: Path,
  *,
  source_signature: str = "",
) -> ProjectDistillationReport | None:
  payload = read_json(project_distillation_path(project_dir), None)
  if not isinstance(payload, dict):
    return None
  try:
    report = ProjectDistillationReport.model_validate(payload)
  except Exception:
    return None
  if source_signature and report.source_signature and report.source_signature != source_signature:
    return report.model_copy(update={"is_stale": True})
  return report.model_copy(update={"is_stale": False})


def save_project_distillation(project_dir: Path, report: ProjectDistillationReport) -> ProjectDistillationReport:
  payload = report.model_dump(mode="json")
  payload["is_stale"] = False
  atomic_write_json(project_distillation_path(project_dir), payload)
  return report.model_copy(update={"is_stale": False})


def _find_document(project_detail, key: str) -> str:
  for item in getattr(project_detail.story_overview, "documents", []) or []:
    if item.key == key:
      return str(item.content or "").strip()
  return ""


def _latest_manual_entries(project_detail) -> list[object]:
  entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  return [item for item in entries if str(getattr(item, "source", "manual") or "manual") == "manual"]


def _first_matching_memory(project_detail, entry_ids: tuple[str, ...]) -> str:
  entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  for item in reversed(entries):
    if getattr(item, "id", "") in entry_ids and str(getattr(item, "content", "")).strip():
      return str(item.content).strip()
  return ""


def _style_traits(project_detail) -> list[str]:
  latest_text = "\n".join(
    (item.content or item.preview or "").strip()
    for item in list(getattr(project_detail, "chapters", []) or [])[-3:]
    if (item.content or item.preview or "").strip()
  )
  traits: list[str] = []
  if latest_text:
    first_person_count = latest_text.count("我")
    third_person_count = latest_text.count("他") + latest_text.count("她")
    if first_person_count >= max(3, third_person_count):
      traits.append("正文更接近第一人称近距离推进，续写时不要突然切成全知视角。")
    elif third_person_count > 0:
      traits.append("正文以第三人称推进为主，续写时保持视角稳定，不要乱跳人物内心。")

    dialogue_count = latest_text.count("“") + latest_text.count("\"")
    if dialogue_count >= 4:
      traits.append("已有正文对白占比不低，推进情节时可以继续用对白带冲突。")

    sentence_count = max(1, latest_text.count("。") + latest_text.count("！") + latest_text.count("？"))
    avg_length = len(latest_text) / sentence_count
    if avg_length <= 24:
      traits.append("句子偏短，节奏推进直接，续写时少用大段解释。")
    elif avg_length >= 42:
      traits.append("句子偏长，铺陈较多，续写时保持同样的叙述密度。")

  if getattr(project_detail.story_overview, "materials", []):
    traits.append("上传资料里已有命名和写法时，优先沿用原表达，不要自行改名。")
    traits.append("这类任务更像承接原作，不是自由起稿；拿不准时先贴着资料里的最后状态写。")

  return _unique_lines(traits, limit=5)


def _character_notes(project_detail) -> list[str]:
  notes: list[str] = []
  for item in getattr(project_detail.story_overview, "characters", [])[:10]:
    parts = [item.name]
    if item.profile:
      parts.append(_compact_text(item.profile, 80))
    if item.current_state:
      parts.append(f"当前状态：{_compact_text(item.current_state, 72)}")
    if item.relationships:
      parts.append(f"关系：{' / '.join(item.relationships[:3])}")
    notes.append("｜".join(parts))
  return _unique_lines(notes, limit=8)


def _entity_notes(entities, prefix: str, *, limit: int = 8) -> list[str]:
  lines: list[str] = []
  for item in list(entities or [])[:limit]:
    summary = _compact_text(getattr(item, "summary", "") or "", 72)
    related = list(getattr(item, "related_characters", []) or [])[:3]
    suffix = []
    if summary:
      suffix.append(summary)
    if related:
      suffix.append(f"相关人物：{' / '.join(related)}")
    lines.append(f"{prefix}{item.name}" + (f"｜{'｜'.join(suffix)}" if suffix else ""))
  return _unique_lines(lines, limit=limit)


def _material_notes(project_detail, query: str = "", chapter_index: int = 0) -> list[str]:
  notes = [
    f"{item.title}｜{_compact_text(item.preview, 100)}"
    for item in getattr(project_detail.story_overview, "materials", [])[:8]
    if item.title or item.preview
  ]
  obsidian = getattr(project_detail.story_overview, "obsidian", None)
  obsidian_notes = list(getattr(obsidian, "notes", []) or [])
  if chapter_index > 0:
    project_path = str(getattr(project_detail, "path", "") or "").strip()
    if project_path:
      try:
        obsidian_notes = [
          record.summary
          for record in scoped_obsidian_note_records_for_chapter(Path(project_path), chapter_index)
        ]
      except Exception:
        pass
  if query.strip():
    obsidian_notes = list(select_obsidian_notes_for_query(
      obsidian_notes,
      query,
      limit=8,
      chapter_index=chapter_index,
    ))
  elif chapter_index > 0:
    obsidian_notes = list(select_obsidian_notes_for_query(obsidian_notes, "", limit=8, chapter_index=chapter_index))
  obsidian_material_notes: list[str] = []
  for item in obsidian_notes[:8]:
    if not (getattr(item, "title", "") or getattr(item, "preview", "")):
      continue
    parts = [f"Obsidian:{item.title}｜{_compact_text(item.preview, 100)}"]
    external_references = [
      _compact_text(str(reference), 80)
      for reference in list(getattr(item, "external_references", []) or [])[:2]
      if str(reference or "").strip()
    ]
    if external_references:
      parts.append(f"考据来源：{' / '.join(external_references)}")
    if getattr(item, "resolved_links", []) or getattr(item, "backlinks", []):
      parts.append(
        f"关联 {len(getattr(item, 'resolved_links', []) or [])} / 被引用 {len(getattr(item, 'backlinks', []) or [])}"
      )
    obsidian_material_notes.append("｜".join(parts))
  notes.extend(obsidian_material_notes)
  return _unique_lines(notes, limit=8)


def _non_obsidian_material_notes(notes: list[str]) -> list[str]:
  return [item for item in notes if not str(item or "").strip().startswith("Obsidian:")]


def _material_notes_for_pack(profile: DistilledSourceProfile, kind: str) -> list[str]:
  if kind == "architecture":
    return profile.material_notes
  return _non_obsidian_material_notes(profile.material_notes)


def _narrative_rules(project_detail) -> list[str]:
  rules: list[str] = []
  for item in _latest_manual_entries(project_detail)[:8]:
    category = str(getattr(item, "category", "") or "").strip()
    title = str(getattr(item, "title", "") or "").strip()
    content = str(getattr(item, "content", "") or "").strip()
    if not content:
      continue
    prefix = " / ".join(part for part in [category, title] if part)
    rules.append(f"{prefix}：{_compact_text(content, 120)}" if prefix else _compact_text(content, 120))

  if getattr(project_detail.story_overview, "materials", []):
    rules.append("涉及资料库已确认事实时，以资料原文为准，不要为了续写方便改写基础设定。")
    rules.append("如果资料本身就是原著或前文，续写时必须承接已经出现的人物关系、事件结果和结尾状态。")

  return _unique_lines(rules, limit=6)


def _core_conflicts(project_detail) -> list[str]:
  candidates = [
    _first_matching_memory(project_detail, ("project-discussion-summary",)),
    _first_matching_memory(project_detail, ("auto-open-threads", "auto-stage-goal")),
    _find_document(project_detail, "plot_structure"),
    _find_document(project_detail, "global_summary"),
  ]
  lines: list[str] = []
  for item in candidates:
    for raw_line in str(item or "").splitlines():
      cleaned = raw_line.strip().lstrip("-#*0123456789.、）)")
      if cleaned:
        lines.append(cleaned)
  for entity in getattr(project_detail.story_overview, "events", [])[:5]:
    if getattr(entity, "summary", ""):
      lines.append(f"{entity.name}：{entity.summary}")
  return _unique_lines(lines, limit=6)


def _build_source_profile(project_detail) -> DistilledSourceProfile:
  narrative_rules = _narrative_rules(project_detail)
  style_traits = _style_traits(project_detail)
  core_conflicts = _core_conflicts(project_detail)
  character_notes = _character_notes(project_detail)
  event_notes = _entity_notes(getattr(project_detail.story_overview, "events", []), "", limit=6)
  location_notes = _entity_notes(getattr(project_detail.story_overview, "locations", []), "", limit=6)
  prop_notes = _entity_notes(getattr(project_detail.story_overview, "props", []), "", limit=6)
  skill_notes = _entity_notes(getattr(project_detail.story_overview, "skills", []), "", limit=6)
  material_notes = _material_notes(project_detail)
  summary = (
    _first_matching_memory(project_detail, ("project-discussion-summary",))
    or _find_document(project_detail, "global_summary")
    or _find_document(project_detail, "core_seed")
    or _find_document(project_detail, "plot_structure")
  )
  if not summary:
    summary = "；".join(
      item for item in [
        character_notes[0] if character_notes else "",
        event_notes[0] if event_notes else "",
        material_notes[0] if material_notes else "",
      ]
      if item
    )
  return DistilledSourceProfile(
    summary=_compact_text(summary, 260),
    narrative_rules=narrative_rules,
    style_traits=style_traits,
    core_conflicts=core_conflicts,
    character_notes=character_notes,
    event_notes=event_notes,
    location_notes=location_notes,
    prop_notes=prop_notes,
    skill_notes=skill_notes,
    material_notes=material_notes,
  )


def _blocked_changes(profile: DistilledSourceProfile) -> list[str]:
  lines = [
    "不要推翻已经成立的事件顺序、人物关系和地点命名。",
    "没有明确证据时，不要替换资料库里已经出现过的事实。",
    *profile.narrative_rules[:3],
  ]
  return _unique_lines(lines, limit=6)


def _build_pack(kind: str, project_detail, profile: DistilledSourceProfile) -> TaskDistillationPack:
  latest_chapter = next(
    (item for item in reversed(getattr(project_detail, "chapters", []) or []) if (item.content or "").strip()),
    None,
  )
  stage_goal = _first_matching_memory(project_detail, ("auto-stage-goal",))
  open_threads = _first_matching_memory(project_detail, ("auto-open-threads",))

  if kind == "continuation":
    material_notes = _material_notes_for_pack(profile, kind)
    return TaskDistillationPack(
      kind=kind,
      summary="用于在不推翻既有事实和文风的前提下继续写正文。",
      must_keep=_unique_lines(profile.narrative_rules[:3] + profile.core_conflicts[:3] + material_notes[:2], limit=6),
      execution_focus=_unique_lines(
        [
          f"最近正文位置：第 {latest_chapter.index} 章《{latest_chapter.title}》之后继续承接。" if latest_chapter else "当前还没有稳定正文，需要先沿着蓝图立住开篇。",
          stage_goal or "",
          open_threads or "",
          *profile.character_notes[:3],
        ],
        limit=6,
      ),
      voice_rules=_unique_lines(profile.style_traits + ["沿用已写正文的叙述距离和句法节奏。"], limit=5),
      blocked_changes=_blocked_changes(profile),
      prepared_from=["source_profile", "characters", "timeline", "materials"],
    )

  if kind == "architecture":
    material_notes = _material_notes_for_pack(profile, kind)
    return TaskDistillationPack(
      kind=kind,
      summary="用于补齐或重整整书架构，同时保留资料库和已写正文的硬事实。",
      must_keep=_unique_lines(material_notes[:3] + profile.core_conflicts[:4], limit=6),
      execution_focus=_unique_lines(
        [
          f"目标规模：{project_detail.target_chapters} 章，约 {project_detail.target_words} 字。",
          stage_goal or "",
          open_threads or "",
          *profile.character_notes[:3],
        ],
        limit=6,
      ),
      voice_rules=_unique_lines(profile.style_traits[:3], limit=4),
      blocked_changes=_blocked_changes(profile),
      prepared_from=["source_profile", "story_documents", "materials", "memory"],
    )

  if kind == "imitation":
    material_notes = _material_notes_for_pack(profile, kind)
    return TaskDistillationPack(
      kind=kind,
      summary="用于模仿原作品或原资料的叙述方式，不默认继承全部剧情事实。",
      must_keep=_unique_lines(profile.style_traits + material_notes[:2], limit=6),
      execution_focus=_unique_lines(
        [
          "重点复用句法、视角、节奏和常见意象，不是照搬原剧情。",
          *profile.core_conflicts[:2],
          *profile.character_notes[:2],
        ],
        limit=5,
      ),
      voice_rules=_unique_lines(profile.style_traits + ["没有明确要求续写时，不要强行继承原作品事件顺序。"], limit=5),
      blocked_changes=_unique_lines(["不要直接复制原文长段内容。"] + _blocked_changes(profile)[:2], limit=4),
      prepared_from=["source_profile", "style_profile", "materials"],
    )

  return TaskDistillationPack(
    kind=kind,
    summary="用于复刻人物的说话方式、判断方式和关系立场。",
    must_keep=_unique_lines(profile.character_notes[:5], limit=6),
    execution_focus=_unique_lines(
      [
        "执行前需要指定目标人物，再从人物档案里取对应视角。",
        *profile.character_notes[:3],
        *profile.event_notes[:2],
      ],
      limit=6,
    ),
    voice_rules=_unique_lines(profile.style_traits[:3] + ["人物表达不能脱离现有关系和处境。"], limit=4),
    blocked_changes=_unique_lines(["不要让人物说出和既有关系、目标相反的话。"] + _blocked_changes(profile)[:2], limit=4),
    prepared_from=["source_profile", "character_profiles", "event_timeline"],
  )


def generate_project_distillation(
  project_detail,
  *,
  source_signature: str = "",
) -> ProjectDistillationReport:
  profile = _build_source_profile(project_detail)
  packs = [
    _build_pack("continuation", project_detail, profile),
    _build_pack("architecture", project_detail, profile),
    _build_pack("imitation", project_detail, profile),
    _build_pack("persona", project_detail, profile),
  ]
  return ProjectDistillationReport(
    generated_at=_now_iso(),
    source_signature=source_signature,
    source_profile=profile,
    packs=packs,
  )


def select_task_pack(project_detail, kind: str) -> TaskDistillationPack | None:
  report = getattr(project_detail.story_overview, "distillation_report", None)
  if report is None or report.is_stale:
    return None
  for item in report.packs:
    if item.kind == kind:
      return item
  return None


def _pack_with_scoped_material_notes(
  pack: TaskDistillationPack | None,
  material_notes: list[str],
  *,
  chapter_index: int = 0,
) -> TaskDistillationPack | None:
  if pack is None or chapter_index <= 0:
    return pack
  kept = [
    item
    for item in list(pack.must_keep or [])
    if not str(item or "").strip().startswith("Obsidian:")
  ]
  return pack.model_copy(
    update={
      "must_keep": _unique_lines(kept + material_notes[:3], limit=6),
    }
  )


def _profile_summary_for_scope(
  report: ProjectDistillationReport,
  material_notes: list[str],
  *,
  chapter_index: int = 0,
  allow_obsidian_summary: bool = True,
) -> str:
  summary = str(report.source_profile.summary or "").strip()
  if (chapter_index > 0 or not allow_obsidian_summary) and summary.startswith("Obsidian:"):
    return material_notes[0] if material_notes else ""
  return summary


def resolve_task_pack_kind(*, kind: str = "", instruction: str = "", rewrite_mode: str = "") -> str:
  normalized_kind = kind.strip().lower()
  if normalized_kind in {"continuation", "architecture", "imitation", "persona"}:
    return normalized_kind

  normalized_rewrite_mode = rewrite_mode.strip().lower()
  if normalized_rewrite_mode == "humanize":
    return "imitation"

  text = instruction.strip()
  if _PERSONA_PATTERN.search(text):
    return "persona"
  if _IMITATION_PATTERN.search(text):
    return "imitation"
  if _ARCHITECTURE_PATTERN.search(text):
    return "architecture"
  return "continuation"


def build_distillation_review_text(project_detail, *, kind: str = "", instruction: str = "", chapter_index: int = 0) -> str:
  report = getattr(project_detail.story_overview, "distillation_report", None)
  if report is None or report.is_stale:
    return ""

  pack_kind = resolve_task_pack_kind(kind=kind, instruction=instruction)
  pack = select_task_pack(project_detail, pack_kind)
  if chapter_index > 0:
    material_notes = _material_notes(project_detail, query=instruction, chapter_index=chapter_index)
  elif pack_kind == "architecture":
    material_notes = _material_notes(project_detail, query=instruction) if instruction.strip() else report.source_profile.material_notes
  else:
    material_notes = _non_obsidian_material_notes(
      _material_notes(project_detail, query=instruction) if instruction.strip() else report.source_profile.material_notes
    )
  pack = _pack_with_scoped_material_notes(pack, material_notes, chapter_index=chapter_index)
  profile_summary = _profile_summary_for_scope(
    report,
    material_notes,
    chapter_index=chapter_index,
    allow_obsidian_summary=pack_kind == "architecture",
  )
  lines: list[str] = []
  if profile_summary:
    lines.append(f"统一摘要：{_compact_text(profile_summary, 220)}")
  if report.source_profile.narrative_rules:
    lines.append("已确认规则：\n" + "\n".join(f"- {item}" for item in report.source_profile.narrative_rules[:4]))
  if report.source_profile.character_notes:
    lines.append("参考人物：\n" + "\n".join(f"- {item}" for item in report.source_profile.character_notes[:4]))
  if report.source_profile.event_notes:
    lines.append("参考事件：\n" + "\n".join(f"- {item}" for item in report.source_profile.event_notes[:4]))
  if material_notes:
    lines.append("资料库要点：\n" + "\n".join(f"- {item}" for item in material_notes[:4]))
  if pack is not None:
    lines.append(f"任务包：{pack.kind}｜{pack.summary}")
    if pack.must_keep:
      lines.append("必须保留：\n" + "\n".join(f"- {item}" for item in pack.must_keep[:5]))
    if pack.execution_focus:
      lines.append("执行重点：\n" + "\n".join(f"- {item}" for item in pack.execution_focus[:5]))
    if pack.blocked_changes:
      lines.append("不要改动：\n" + "\n".join(f"- {item}" for item in pack.blocked_changes[:4]))
  return "\n\n".join(lines).strip()


def build_task_distillation_prompt_block(
  project_detail,
  *,
  kind: str = "",
  query: str = "",
  chapter_index: int = 0,
) -> str:
  report = getattr(project_detail.story_overview, "distillation_report", None)
  if report is None or report.is_stale:
    return ""
  pack_kind = resolve_task_pack_kind(kind=kind, instruction=query)
  if chapter_index > 0:
    material_notes = _material_notes(project_detail, query=query, chapter_index=chapter_index)
  elif pack_kind == "architecture":
    material_notes = _material_notes(project_detail, query=query) if query.strip() else report.source_profile.material_notes
  else:
    material_notes = _non_obsidian_material_notes(
      _material_notes(project_detail, query=query) if query.strip() else report.source_profile.material_notes
    )

  lines: list[str] = []
  profile_summary = _profile_summary_for_scope(
    report,
    material_notes,
    chapter_index=chapter_index,
    allow_obsidian_summary=pack_kind == "architecture",
  )
  if profile_summary:
    lines.append(f"统一蒸馏摘要：{_compact_text(profile_summary, 220)}")
  if report.source_profile.narrative_rules:
    lines.append("统一蒸馏规则：\n" + "\n".join(f"- {item}" for item in report.source_profile.narrative_rules[:4]))
  if report.source_profile.character_notes:
    lines.append("统一蒸馏人物：\n" + "\n".join(f"- {item}" for item in report.source_profile.character_notes[:4]))
  if report.source_profile.event_notes:
    lines.append("统一蒸馏事件：\n" + "\n".join(f"- {item}" for item in report.source_profile.event_notes[:4]))
  if material_notes:
    lines.append("统一蒸馏资料：\n" + "\n".join(f"- {item}" for item in material_notes[:3]))

  pack = select_task_pack(project_detail, pack_kind) if pack_kind else None
  pack = _pack_with_scoped_material_notes(pack, material_notes, chapter_index=chapter_index)
  if pack is not None:
    lines.append(f"{pack.kind} 任务包：{pack.summary}")
    if pack.must_keep:
      lines.append("必须保留：\n" + "\n".join(f"- {item}" for item in pack.must_keep[:5]))
    if pack.execution_focus:
      lines.append("执行重点：\n" + "\n".join(f"- {item}" for item in pack.execution_focus[:5]))
    if pack.voice_rules:
      lines.append("表达约束：\n" + "\n".join(f"- {item}" for item in pack.voice_rules[:4]))

  return "\n\n".join(lines).strip()
