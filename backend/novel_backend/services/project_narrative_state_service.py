from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from novel_backend.config import Settings
from novel_backend.services.config_service import load_config
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.obsidian_service import (
  _CHAPTER_END_LABELS,
  _CHAPTER_RANGE_LABELS,
  _CHAPTER_START_LABELS,
  _REVEAL_AFTER_CHAPTER_LABELS,
  _chapter_numbers_from_value,
  _chapter_range_from_value,
  _frontmatter_list_item_content,
  _frontmatter_context_values,
  _frontmatter_tag_list,
  _frontmatter_tag_list_from_value,
  _frontmatter_value,
  _parse_chapter_number,
  _parse_frontmatter_key_value,
  _parse_frontmatter,
  _tags_chapter_scope,
  collect_obsidian_note_records,
  load_obsidian_config,
  obsidian_note_available_for_chapter,
  resolve_obsidian_vault_dir,
  scoped_obsidian_note_records_for_chapter,
  select_obsidian_notes_for_query,
)
from novel_backend.services.project_style_xp_evolution_service import (
  load_project_style_xp_state,
  obsidian_style_xp_note_kind,
)
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json

_SCHEMA_VERSION = 1
_LEARNING_DIRNAME = "learning"
_NARRATIVE_STATE_FILENAME = "narrative_state.json"
_OBSIDIAN_DRAFT_DIRNAME = "obsidian_drafts"
_MAX_DEBTS = 160
_MAX_ARCS = 80
_MAX_OBSERVATIONS = 100
_MAX_OBSIDIAN_MAINTENANCE_ACTIONS = 320
_MAX_MODEL_REVIEWS = 60
_MAX_CONTRACTS = 120
_MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS = 160
_MAX_OBSIDIAN_GRAPH_MAINTENANCE_SUGGESTIONS = 4
_MAX_OBSIDIAN_CHAPTER_NOTE_SUGGESTIONS = 80
_MAX_OBSIDIAN_AUTO_STAGED_DRAFTS = 12
_OBSIDIAN_AUTO_STAGE_PRIORITIES = {"high", "medium"}
_DRAFT_TAG_LABELS = ("tags", "tag", "标签")
_DRAFT_SOURCE_CHAPTER_LABELS = ("source_chapters", "source_chapter", "source chapters", "source chapter", "来源章节")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;]\s*")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_NAME_LINE_RE = re.compile(r"^\s*[-*]?\s*([一-龥A-Za-z][一-龥A-Za-z0-9·]{1,12})\s*[：:：\-]")
_CONTRACT_ID_RE = re.compile(r"^chapter-\d{3}$")
_DEBT_TOKENS = (
  "伏笔",
  "悬念",
  "秘密",
  "真相",
  "线索",
  "承诺",
  "约定",
  "预言",
  "谜",
  "答案",
  "钥匙",
  "身份",
  "失踪",
  "背叛",
  "禁忌",
  "规则",
  "代价",
  "仇",
  "证据",
  "遗言",
  "血脉",
  "封印",
)
_PAYOFF_TOKENS = (
  "揭开",
  "揭露",
  "确认",
  "证明",
  "兑现",
  "回收",
  "暴露",
  "解开",
  "说出",
  "承认",
  "知道了",
  "终于明白",
)
_CONFLICT_TOKENS = ("矛盾", "冲突", "不该", "无法解释", "前后不一")
_RELATION_TOKENS = ("背叛", "信任", "决裂", "和解", "师徒", "父子", "母女", "盟友", "仇人", "婚约")
_WORLD_RULE_TOKENS = ("规则", "禁忌", "封印", "法则", "国法", "神谕", "代价", "誓约")
_OBSIDIAN_CHAPTER_PLAN_LABELS = {
  "chapterplan",
  "chapterplans",
  "chapteroutline",
  "chapteroutlines",
  "chaptercontract",
  "chaptercontracts",
  "sceneplan",
  "sceneplans",
  "scenecard",
  "scenecards",
  "beatsheet",
  "beatsheets",
  "outline",
  "outlines",
  "plan",
  "plans",
  "scenes",
  "章节计划",
  "章节大纲",
  "章节合同",
  "章节规划",
  "本章计划",
  "场景计划",
  "场景卡",
  "分场",
  "节拍表",
  "计划",
}
_OBSIDIAN_DEBT_NOTE_LABELS = {
  "debt",
  "debts",
  "plotdebt",
  "plotdebts",
  "storydebt",
  "storydebts",
  "narrativedebt",
  "narrativedebts",
  "foreshadow",
  "foreshadows",
  "promise",
  "promises",
  "payoff",
  "payoffs",
  "伏笔",
  "剧情债务",
  "叙事债务",
  "线索债务",
  "承诺",
  "兑现",
}
_OBSIDIAN_ARC_NOTE_LABELS = {
  "arc",
  "arcs",
  "characterarc",
  "characterarcs",
  "characterstate",
  "characterstates",
  "characterprogress",
  "characterprogression",
  "人物弧线",
  "人物状态",
  "人物进展",
  "角色弧线",
  "角色状态",
}
_OBSIDIAN_CHAPTER_NOTE_LABELS = {
  "chapter",
  "chapters",
  "chapternote",
  "chapternotes",
  "chaptersummary",
  "chapterarchive",
  "authorarchive",
  "chapterrecap",
  "章节",
  "章节笔记",
  "章节档案",
  "章节摘要",
  "章节回顾",
  "作者档案",
}
_OBSIDIAN_DEBT_PAID_LABELS = {
  "paid",
  "closed",
  "resolved",
  "done",
  "finished",
  "已兑现",
  "已完成",
  "已关闭",
  "已解决",
}
_OBSIDIAN_DEBT_DEFERRED_LABELS = {"deferred", "later", "postponed", "延后", "延期", "暂缓"}
_OBSIDIAN_DEBT_CONTENT_KEYS = (
  "debt_content",
  "debt_summary",
  "debt_detail",
  "content",
  "promise",
  "foreshadow",
  "plot_debt",
  "narrative_debt",
  "剧情债务",
  "债务内容",
  "线索内容",
  "伏笔内容",
  "承诺内容",
)
_OBSIDIAN_DEBT_KIND_KEYS = ("debt_kind", "debt_type", "kind", "债务类型", "类型")
_OBSIDIAN_DEBT_STATUS_KEYS = ("debt_status", "narrative_status", "payoff_status", "处理状态", "债务状态", "兑现状态")
_OBSIDIAN_DEBT_RISK_KEYS = ("risk_level", "risk_priority", "priority", "风险等级", "风险", "优先级")
_OBSIDIAN_DEBT_PAYOFF_KEYS = ("expected_payoff_range", "payoff_range", "planned_payoff", "payoff_chapters", "预计处理区间", "兑现区间", "处理区间")
_OBSIDIAN_DEBT_ACTION_KEYS = ("next_required_action", "next_action", "required_next_action", "下一步动作", "下一步要求", "后续动作", "后续要求")
_OBSIDIAN_DEBT_CHARACTER_KEYS = ("related_characters", "related_character", "characters", "character", "相关人物", "人物", "角色")
_OBSIDIAN_ARC_NAME_KEYS = ("character", "character_name", "name", "related_character", "related_characters", "人物", "角色", "角色名", "相关人物")
_OBSIDIAN_ARC_PHASE_KEYS = ("arc_phase", "phase", "stage", "人物阶段", "弧线阶段", "阶段")
_OBSIDIAN_ARC_STATE_KEYS = ("current_state", "character_state", "state", "当前状态", "人物状态", "角色状态")
_OBSIDIAN_ARC_PRESSURE_KEYS = ("unresolved_pressure", "pressure", "tension", "人物压力", "未解压力", "关系压力")
_OBSIDIAN_ARC_CHECK_KEYS = ("required_next_check", "next_check", "next_required_check", "下一次检查", "后续检查", "下一步检查")
_OBSIDIAN_CHAPTER_NOTE_TITLE_KEYS = ("chapter_title", "chapter_name", "章节标题", "章节名", "标题")
_OBSIDIAN_CHAPTER_NOTE_SUMMARY_KEYS = ("chapter_summary", "chapter_recap", "chapter_brief", "recap", "正文摘要", "章节摘要", "章节回顾")
_OBSIDIAN_CHAPTER_NOTE_EVENTS_KEYS = ("chapter_events", "chapter_event", "key_events", "key_event", "events", "event", "plot_events", "剧情事件", "关键事件", "本章事件")
_OBSIDIAN_CHAPTER_NOTE_STATE_KEYS = ("state_changes", "state_change", "continuity_changes", "character_changes", "world_changes", "状态变化", "连续性变化", "人物变化", "世界变化")
_OBSIDIAN_CHAPTER_NOTE_HANDOFF_KEYS = ("handoff_to_next", "next_handoff", "next_chapter_handoff", "handoff", "next_chapter", "章节交接", "下一章交接", "后续交接")
_OBSIDIAN_CHAPTER_NOTE_EXCERPT_KEYS = ("chapter_excerpt", "chapter_excerpts", "excerpt", "excerpts", "body_excerpt", "正文摘录", "章节正文摘录")
_OBSIDIAN_CHAPTER_CONTRACT_OBJECTIVE_KEYS = ("objective", "chapter_objective", "chapter_goal", "goal", "合同目标", "章节目标", "目标")
_OBSIDIAN_CHAPTER_CONTRACT_REQUIRED_BEATS_KEYS = ("required_beats", "required_beat", "beats", "must_beats", "必须完成的节拍", "必须节拍", "节拍")
_OBSIDIAN_CHAPTER_CONTRACT_FORBIDDEN_MOVES_KEYS = ("forbidden_moves", "forbidden_move", "avoid", "avoid_moves", "禁止动作", "禁写动作", "不能写")
_OBSIDIAN_CHAPTER_CONTRACT_ACCEPTANCE_KEYS = ("acceptance_checks", "acceptance_check", "checks", "验收项", "验收检查", "检查项")
_OBSIDIAN_STYLE_RULE_PREVIEW_KEYS = (
  "style_rule",
  "voice_rule",
  "tone_rule",
  "sentence_rhythm",
  "imagery",
  "dialogue_rule",
  "文风规则",
  "文风",
  "语气规则",
  "句式节奏",
  "意象",
  "对白规则",
)
_OBSIDIAN_STYLE_APPLIES_KEYS = ("applies_to", "applies", "scope", "适用场景", "适用范围", "使用建议")
_OBSIDIAN_STYLE_AVOID_KEYS = ("avoid_style", "avoid", "禁用写法", "避免写法")
_OBSIDIAN_XP_RULE_PREVIEW_KEYS = ("xp_rule", "workflow", "technique", "XP规则", "XP", "流程", "技法")
_OBSIDIAN_XP_CHECK_KEYS = (
  "precheck",
  "postcheck",
  "workflow",
  "checks",
  "前置检查",
  "后置检查",
  "检查项",
  "使用建议",
)
_OBSIDIAN_XP_AVOID_KEYS = ("avoid_xp", "avoid", "禁用XP", "避免XP")
_OBSIDIAN_STYLE_XP_EVIDENCE_KEYS = ("evidence_count", "evidence", "证据数量", "证据")
_OBSIDIAN_STYLE_XP_CONFIDENCE_KEYS = ("confidence", "confidence_score", "置信度")


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: object, limit: int = 160) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}..."


def narrative_state_path(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / _LEARNING_DIRNAME / _NARRATIVE_STATE_FILENAME


def obsidian_draft_dir(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / _OBSIDIAN_DRAFT_DIRNAME


def _default_state() -> dict[str, object]:
  return {
    "schema_version": _SCHEMA_VERSION,
    "updated_at": "",
    "revision": 0,
    "debts": [],
    "character_arcs": [],
    "chapter_cards": [],
    "model_reviews": [],
    "chapter_contracts": [],
    "contract_reviews": [],
    "obsidian_maintenance_suggestions": [],
    "obsidian_maintenance_summary": {},
    "obsidian_maintenance_actions": [],
    "observations": [],
  }


def _normalize_state(payload: object) -> dict[str, object]:
  if not isinstance(payload, dict):
    return _default_state()
  state = _default_state()
  state.update(payload)
  for key in (
    "debts",
    "character_arcs",
    "chapter_cards",
    "model_reviews",
    "chapter_contracts",
    "contract_reviews",
    "obsidian_maintenance_suggestions",
    "obsidian_maintenance_actions",
    "observations",
  ):
    if not isinstance(state.get(key), list):
      state[key] = []
  if not isinstance(state.get("obsidian_maintenance_summary"), dict):
    state["obsidian_maintenance_summary"] = {}
  try:
    state["revision"] = int(state.get("revision") or 0)
  except (TypeError, ValueError):
    state["revision"] = 0
  state["schema_version"] = _SCHEMA_VERSION
  return state


def load_project_narrative_state(project_dir: Path) -> dict[str, object]:
  try:
    return _normalize_state(read_json(narrative_state_path(project_dir), _default_state()))
  except Exception:
    return _default_state()


def _body_text(text: str) -> str:
  return _MARKDOWN_HEADING_RE.sub("", text or "").strip()


def _split_sentences(text: str, *, limit: int = 80) -> list[str]:
  body = _body_text(text)
  sentences = [_compact_text(item, 180) for item in _SENTENCE_SPLIT_RE.split(body) if item.strip()]
  return [item for item in sentences if item][:limit]


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


def _string_list(value: object, *, limit: int = 8) -> list[str]:
  if isinstance(value, list):
    return [str(item).strip() for item in value if str(item).strip()][:limit]
  if isinstance(value, str) and value.strip():
    lines = [
      item.strip(" -0123456789.、）)")
      for item in value.splitlines()
      if item.strip()
    ]
    return [item for item in lines if item][:limit]
  return []


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for item in items:
    value = str(item or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    ordered.append(value)
  return ordered


def _normalized_label(value: object) -> str:
  return re.sub(r"[\s_\-/#.]+", "", str(value or "").strip().lower())


def _number(value: object, default: float = 0.0) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _word_count(text: str) -> int:
  return len(_WORD_RE.findall(str(text or "")))


def _documents_map(project_detail: object) -> dict[str, str]:
  overview = getattr(project_detail, "story_overview", None)
  return {
    str(getattr(item, "key", "") or ""): str(getattr(item, "content", "") or "")
    for item in getattr(overview, "documents", []) or []
  }


def _chapter_for_id(project_detail: object, chapter_id: str) -> object | None:
  for item in getattr(project_detail, "chapters", []) or []:
    if str(getattr(item, "id", "") or "") == chapter_id:
      return item
  return None


def _chapter_index_from_id(chapter_id: str) -> int:
  match = re.search(r"(\d+)$", str(chapter_id or ""))
  return int(match.group(1)) if match else 0


def _chapter_id_from_index(chapter_index: int) -> str:
  return f"chapter-{max(0, int(chapter_index or 0)):03d}"


def _known_names(project_detail: object) -> list[str]:
  names: list[str] = []
  overview = getattr(project_detail, "story_overview", None)
  for item in getattr(overview, "characters", []) or []:
    name = str(getattr(item, "name", "") or "").strip()
    if name and name not in names:
      names.append(name)
  docs = _documents_map(project_detail)
  for key in ("character_design", "character_state"):
    for line in docs.get(key, "").splitlines():
      match = _NAME_LINE_RE.search(line)
      if match:
        name = match.group(1).strip()
        if name and name not in names:
          names.append(name)
  return names[:30]


def _entity_names(project_detail: object) -> list[str]:
  overview = getattr(project_detail, "story_overview", None)
  names = _known_names(project_detail)
  for collection_name in ("props", "organizations", "locations", "skills", "scenes"):
    for item in getattr(overview, collection_name, []) or []:
      name = str(getattr(item, "name", "") or "").strip()
      if name and name not in names:
        names.append(name)
  return names[:80]


def _matched_overview_entity_names(
  project_detail: object,
  collection_name: str,
  content: str,
  *,
  limit: int = 8,
) -> list[str]:
  overview = getattr(project_detail, "story_overview", None)
  haystack = str(content or "")
  names: list[str] = []
  for item in getattr(overview, collection_name, []) or []:
    name = str(getattr(item, "name", "") or "").strip()
    if not name or name in names or name not in haystack:
      continue
    names.append(name)
    if len(names) >= limit:
      break
  return names


def _chapter_position(chapter_index: int, total_chapters: int) -> float:
  if total_chapters <= 0 or chapter_index <= 0:
    return 0.0
  return min(1.0, max(0.0, chapter_index / total_chapters))


def _stage_label(chapter_index: int, total_chapters: int) -> str:
  position = _chapter_position(chapter_index, total_chapters)
  if position <= 0.15:
    return "开局立约"
  if position <= 0.35:
    return "前段升级"
  if position <= 0.55:
    return "中段转向"
  if position <= 0.75:
    return "终局前加压"
  if position <= 0.9:
    return "高潮准备"
  return "结局兑现"


def _payoff_range(first_seen: int, total_chapters: int, kind: str) -> list[int]:
  total = max(1, int(total_chapters or 1))
  start = max(1, int(first_seen or 1))
  position = _chapter_position(start, total)
  if kind == "world_rule":
    target_start = max(start + 1, round(total * 0.55))
    target_end = max(target_start, round(total * 0.78))
  elif kind == "relationship":
    target_start = max(start + 1, round(total * 0.5))
    target_end = max(target_start, round(total * 0.86))
  elif position >= 0.7:
    target_start = min(total, start + 1)
    target_end = min(total, start + 4)
  elif position >= 0.45:
    target_start = max(start + 2, round(total * 0.68))
    target_end = max(target_start, round(total * 0.9))
  else:
    target_start = max(start + 3, round(total * 0.62))
    target_end = max(target_start, round(total * 0.9))
  return [min(total, target_start), min(total, max(target_start, target_end))]


def _debt_kind(text: str) -> str:
  if any(token in text for token in _RELATION_TOKENS):
    return "relationship"
  if any(token in text for token in _WORLD_RULE_TOKENS):
    return "world_rule"
  if "承诺" in text or "约定" in text or "预言" in text:
    return "promise"
  return "foreshadow"


def _debt_status(text: str) -> str:
  if any(token in text for token in _CONFLICT_TOKENS):
    return "conflict"
  if any(token in text for token in _PAYOFF_TOKENS):
    return "paid"
  if any(token in text for token in _DEBT_TOKENS):
    return "open"
  return "touched"


def _anchor_keywords(text: str, known_entities: list[str]) -> list[str]:
  hits = [name for name in known_entities if name and name in text]
  debt_hits = [token for token in _DEBT_TOKENS if token in text]
  if hits or debt_hits:
    return [*hits[:3], *debt_hits[:3]]
  chars = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))
  return [chars[:18]] if chars else []


def _debt_id(kind: str, keywords: list[str], content: str) -> str:
  key = "|".join(item for item in keywords if item) or _compact_text(content, 80)
  digest = hashlib.sha1(f"{kind}\n{key}".encode("utf-8")).hexdigest()[:12]
  return f"debt-{kind}-{digest}"


def _candidate_debts(
  project_detail: object,
  chapter: object | None,
  *,
  source_name: str,
  texts: list[str],
) -> list[dict[str, object]]:
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  chapter_id = str(getattr(chapter, "id", "") or "") if chapter is not None else ""
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  chapter_title = str(getattr(chapter, "title", "") or "") if chapter is not None else ""
  known_entities = _entity_names(project_detail)
  candidates: list[dict[str, object]] = []
  for text in texts:
    for sentence in _split_sentences(text):
      if not any(token in sentence for token in _DEBT_TOKENS):
        continue
      kind = _debt_kind(sentence)
      keywords = _anchor_keywords(sentence, known_entities)
      related_characters = [name for name in _known_names(project_detail) if name in sentence][:6]
      expected_range = _payoff_range(chapter_index or 1, total_chapters, kind)
      candidates.append(
        {
          "id": _debt_id(kind, keywords, sentence),
          "kind": kind,
          "title": " / ".join(keywords[:3]) or _compact_text(sentence, 24),
          "content": sentence,
          "status": _debt_status(sentence),
          "first_seen_chapter_id": chapter_id,
          "first_seen_chapter_index": chapter_index,
          "last_seen_chapter_id": chapter_id,
          "last_seen_chapter_index": chapter_index,
          "last_seen_chapter_title": chapter_title,
          "source_chapter_ids": [chapter_id] if chapter_id else [],
          "source_names": [source_name],
          "evidence": [_compact_text(sentence, 180)],
          "expected_payoff_range": expected_range,
          "next_required_action": _next_required_action(_debt_status(sentence), expected_range, chapter_index, total_chapters),
          "related_characters": related_characters,
          "risk_level": _risk_level(_debt_status(sentence), expected_range, chapter_index, total_chapters),
          "confidence": 0.66 if chapter_id else 0.54,
        }
      )
  return candidates


def _risk_level(status: str, expected_range: list[int], chapter_index: int, total_chapters: int) -> str:
  if status == "conflict":
    return "critical"
  if status == "paid":
    return "low"
  start, end = expected_range if len(expected_range) == 2 else [0, 0]
  if chapter_index > 0 and end > 0 and chapter_index > end:
    return "high"
  if chapter_index > 0 and start <= chapter_index <= max(start, end):
    return "high"
  if _chapter_position(chapter_index, total_chapters) >= 0.72:
    return "medium"
  return "low"


def _next_required_action(status: str, expected_range: list[int], chapter_index: int, total_chapters: int) -> str:
  start, end = expected_range if len(expected_range) == 2 else [0, 0]
  if status == "paid":
    return "后续只保留结果影响，避免重复解释。"
  if status == "conflict":
    return "生成前检查前文证据，修正冲突或明确冲突来自人物误判。"
  if chapter_index > 0 and start <= chapter_index <= max(start, end):
    return "本章需要推进或兑现，写出可验证的事件变化。"
  if chapter_index > 0 and end > 0 and chapter_index > end:
    return "已经超过预计兑现区间，需要尽快处理或说明延期原因。"
  if _chapter_position(chapter_index, total_chapters) >= 0.72:
    return "终局前不宜新增孤立问题；需要说明这条线和主线的关系。"
  return "可以轻触一次，保留后续章节继续处理的空间。"


def _merge_debt(existing: dict[str, object] | None, candidate: dict[str, object], now: str) -> dict[str, object]:
  if existing is None:
    return {
      **candidate,
      "created_at": now,
      "last_seen_at": now,
    }
  previous_status = str(existing.get("status") or "open")
  next_status = str(candidate.get("status") or "open")
  status_rank = {"conflict": 4, "paid": 3, "touched": 2, "open": 1, "deferred": 0}
  candidate_sources = [str(item) for item in candidate.get("source_names", []) if str(item).strip()]
  if "obsidian_constraint" in candidate_sources:
    existing["status"] = next_status
  elif status_rank.get(next_status, 0) >= status_rank.get(previous_status, 0):
    existing["status"] = next_status
  existing["content"] = candidate.get("content") or existing.get("content") or ""
  existing["last_seen_chapter_id"] = candidate.get("last_seen_chapter_id") or existing.get("last_seen_chapter_id") or ""
  existing["last_seen_chapter_index"] = candidate.get("last_seen_chapter_index") or existing.get("last_seen_chapter_index") or 0
  existing["last_seen_chapter_title"] = candidate.get("last_seen_chapter_title") or existing.get("last_seen_chapter_title") or ""
  existing["last_seen_at"] = now
  existing["risk_level"] = candidate.get("risk_level") or existing.get("risk_level") or "low"
  existing["next_required_action"] = candidate.get("next_required_action") or existing.get("next_required_action") or ""
  existing["confidence"] = round(max(float(existing.get("confidence") or 0), float(candidate.get("confidence") or 0)), 3)
  for key in ("source_chapter_ids", "source_names", "evidence", "related_characters"):
    merged = [str(item) for item in existing.get(key, []) if str(item).strip()]
    for item in candidate.get(key, []) or []:
      value = str(item).strip()
      if value and value not in merged:
        merged.append(value)
    existing[key] = merged[:10] if key != "evidence" else merged[-8:]
  if not existing.get("expected_payoff_range"):
    existing["expected_payoff_range"] = candidate.get("expected_payoff_range") or []
  return existing


def _obsidian_constraint_phrase(value: str) -> str:
  return str(value or "").split("（", 1)[0].strip()


def _obsidian_constraint_debt_id(kind: str, value: str) -> str:
  phrase = _obsidian_constraint_phrase(value)
  digest = hashlib.sha1(f"{kind}\n{phrase}".encode("utf-8")).hexdigest()[:12]
  return f"debt-obsidian-{kind}-{digest}"


def _obsidian_constraint_payoff_range(chapter_index: int, total_chapters: int) -> list[int]:
  total = max(1, int(total_chapters or 1))
  start = min(total, max(1, int(chapter_index or 1)))
  return [start, min(total, start + 1)]


def _obsidian_constraint_debt_candidates(
  project_detail: object,
  chapter: object,
  chapter_card: dict[str, object],
) -> list[dict[str, object]]:
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  chapter_id = str(getattr(chapter, "id", "") or "")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  chapter_title = str(getattr(chapter, "title", "") or "")
  payoff_range = _obsidian_constraint_payoff_range(chapter_index, total_chapters)
  candidates: list[dict[str, object]] = []
  for item in _string_list(chapter_card.get("obsidian_required_missing"), limit=12):
    phrase = _obsidian_constraint_phrase(item)
    if not phrase:
      continue
    candidates.append(
      {
        "id": _obsidian_constraint_debt_id("required", phrase),
        "kind": "world_rule",
        "title": f"Obsidian 必写项未完成：{phrase}",
        "content": f"第 {chapter_index} 章没有完成 Obsidian 正式笔记要求的必写项：{item}",
        "status": "open",
        "first_seen_chapter_id": chapter_id,
        "first_seen_chapter_index": chapter_index,
        "last_seen_chapter_id": chapter_id,
        "last_seen_chapter_index": chapter_index,
        "last_seen_chapter_title": chapter_title,
        "source_chapter_ids": [chapter_id] if chapter_id else [],
        "source_names": ["obsidian_constraint"],
        "evidence": [f"Obsidian 必写项缺失：{item}"],
        "expected_payoff_range": payoff_range,
        "next_required_action": "优先回到对应章节修订；如果作者决定延后，下一章必须明确承接这个缺口。",
        "related_characters": [name for name in _known_names(project_detail) if name in phrase][:6],
        "risk_level": "high",
        "confidence": 0.9,
      }
    )
  for item in _string_list(chapter_card.get("obsidian_forbidden_violations"), limit=12):
    phrase = _obsidian_constraint_phrase(item)
    if not phrase:
      continue
    candidates.append(
      {
        "id": _obsidian_constraint_debt_id("forbidden", phrase),
        "kind": "world_rule",
        "title": f"Obsidian 禁写项已触犯：{phrase}",
        "content": f"第 {chapter_index} 章触犯了 Obsidian 正式笔记标记的禁写项：{item}",
        "status": "open",
        "first_seen_chapter_id": chapter_id,
        "first_seen_chapter_index": chapter_index,
        "last_seen_chapter_id": chapter_id,
        "last_seen_chapter_index": chapter_index,
        "last_seen_chapter_title": chapter_title,
        "source_chapter_ids": [chapter_id] if chapter_id else [],
        "source_names": ["obsidian_constraint"],
        "evidence": [f"Obsidian 禁写项触犯：{item}"],
        "expected_payoff_range": [max(1, chapter_index), max(1, chapter_index)],
        "next_required_action": "优先修订触犯禁写项的章节，避免后续章节沿用错误事实。",
        "related_characters": [name for name in _known_names(project_detail) if name in phrase][:6],
        "risk_level": "critical",
        "confidence": 0.96,
      }
    )
  return candidates


def _resolve_obsidian_constraint_debts(
  debts_by_id: dict[str, dict[str, object]],
  chapter_card: dict[str, object],
  now: str,
) -> None:
  for item in _string_list(chapter_card.get("obsidian_required_satisfied"), limit=16):
    phrase = _obsidian_constraint_phrase(item)
    debt_id = _obsidian_constraint_debt_id("required", phrase)
    existing = debts_by_id.get(debt_id)
    if existing is None:
      continue
    debts_by_id[debt_id] = _merge_debt(
      existing,
      {
        **existing,
        "id": debt_id,
        "content": f"Obsidian 必写项已满足：{item}",
        "status": "paid",
        "source_names": ["obsidian_constraint"],
        "evidence": [f"Obsidian 必写项已满足：{item}"],
        "risk_level": "low",
        "next_required_action": "后续只保留结果影响，不要重复解释。",
        "confidence": 0.92,
      },
      now,
    )

  violation_ids = {
    _obsidian_constraint_debt_id("forbidden", item)
    for item in _string_list(chapter_card.get("obsidian_forbidden_violations"), limit=16)
    if _obsidian_constraint_phrase(item)
  }
  for phrase in _string_list(chapter_card.get("obsidian_forbidden"), limit=16):
    debt_id = _obsidian_constraint_debt_id("forbidden", phrase)
    if debt_id in violation_ids:
      continue
    existing = debts_by_id.get(debt_id)
    if existing is None:
      continue
    debts_by_id[debt_id] = _merge_debt(
      existing,
      {
        **existing,
        "id": debt_id,
        "content": f"Obsidian 禁写项已避开：{phrase}",
        "status": "paid",
        "source_names": ["obsidian_constraint"],
        "evidence": [f"Obsidian 禁写项已避开：{phrase}"],
        "risk_level": "low",
        "next_required_action": "后续保持该限制，不要把被禁设定重新写成事实。",
        "confidence": 0.9,
      },
      now,
    )


def _obsidian_state_enabled(project_detail: object) -> bool:
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  return bool(obsidian is not None and getattr(obsidian, "enabled", False))


def _project_obsidian_notes(project_detail: object) -> list[object]:
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  if obsidian is None:
    return []
  return list(getattr(obsidian, "notes", []) or [])


def _project_obsidian_issues(project_detail: object) -> list[object]:
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  if obsidian is None:
    return []
  return list(getattr(obsidian, "issues", []) or [])


def _safe_obsidian_filename(value: object, fallback: str) -> str:
  cleaned = _compact_text(value, 48)
  cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "-", cleaned)
  cleaned = re.sub(r"\s+", "", cleaned)
  cleaned = cleaned.strip(" .-_")
  return cleaned[:48] or fallback


def _safe_obsidian_draft_relative_path(value: object, fallback: str) -> Path:
  raw = str(value or "").strip().replace("\\", "/")
  raw_path = Path(raw)
  if not raw or raw_path.is_absolute() or ".." in raw_path.parts:
    raw = f"{fallback}.md"
    raw_path = Path(raw)
  parts = [
    _safe_obsidian_filename(part, "未命名")
    for part in raw_path.parts
    if part not in {"", ".", ".."}
  ]
  if not parts:
    parts = [f"{fallback}.md"]
  if not parts[-1].lower().endswith(".md"):
    parts[-1] = f"{parts[-1]}.md"
  return Path(*parts)


def _obsidian_note_title_labels(note: object) -> list[str]:
  relative_path = str(getattr(note, "relative_path", "") or "").strip().replace("\\", "/")
  labels = [
    str(getattr(note, "title", "") or "").strip(),
    relative_path[:-3] if relative_path.lower().endswith(".md") else relative_path,
    Path(relative_path).stem,
  ]
  labels.extend(str(item or "").strip() for item in getattr(note, "aliases", []) or [])
  return _ordered_unique([item for item in labels if item])


def _debt_has_obsidian_note_match(
  debt: dict[str, object],
  notes: list[object],
  *,
  vault_source_ids: set[str] | None = None,
) -> bool:
  source_names = [str(item or "").strip() for item in debt.get("source_names", []) or []]
  if any(item.startswith("obsidian") for item in source_names):
    return True
  debt_id = str(debt.get("id") or "").strip()
  if debt_id and vault_source_ids is not None and debt_id in vault_source_ids:
    return True
  title = str(debt.get("title") or "").strip()
  debt_text = " ".join(
    str(item or "")
    for item in [
      title,
      debt.get("content"),
      " ".join(_string_list(debt.get("evidence"), limit=6)),
    ]
  )
  if not debt_text.strip():
    return False
  for note in notes:
    for label in _obsidian_note_title_labels(note):
      if len(label) >= 4 and (label in debt_text or (title and len(title) >= 4 and title in label)):
        return True
    for phrase in [
      *_string_list(getattr(note, "required_phrases", []), limit=12),
      *_string_list(getattr(note, "forbidden_phrases", []), limit=12),
    ]:
      if len(phrase) >= 3 and phrase in debt_text:
        return True
  return False


def _character_has_obsidian_note(
  name: str,
  notes: list[object],
  *,
  source_id: str = "",
  vault_source_ids: set[str] | None = None,
) -> bool:
  normalized = str(name or "").strip()
  normalized_source_id = str(source_id or "").strip()
  if normalized_source_id and vault_source_ids is not None and normalized_source_id in vault_source_ids:
    return True
  if not normalized:
    return False
  for note in notes:
    if normalized in _obsidian_note_title_labels(note):
      return True
  return False


def _maintenance_actions_by_suggestion(state: dict[str, object]) -> dict[str, dict[str, object]]:
  actions: dict[str, dict[str, object]] = {}
  for item in state.get("obsidian_maintenance_actions", []) or []:
    if not isinstance(item, dict):
      continue
    suggestion_id = str(item.get("suggestion_id") or "").strip()
    if not suggestion_id:
      continue
    created_at = str(item.get("created_at") or "")
    previous = actions.get(suggestion_id)
    if previous is None or created_at >= str(previous.get("created_at") or ""):
      actions[suggestion_id] = item
  return actions


def _obsidian_maintenance_suggestion_relative_path(suggestion: dict[str, object]) -> str:
  if not str(suggestion.get("suggested_path") or "").strip() and not str(suggestion.get("draft_markdown") or "").strip():
    return ""
  return _safe_obsidian_draft_relative_path(
    suggestion.get("suggested_path"),
    _safe_obsidian_filename(suggestion.get("title"), "obsidian-draft"),
  ).as_posix()


def _attach_maintenance_action_status(
  suggestions: list[dict[str, object]],
  state: dict[str, object],
  project_dir: Path | None = None,
) -> list[dict[str, object]]:
  actions = _maintenance_actions_by_suggestion(state)
  hydrated: list[dict[str, object]] = []
  for item in suggestions:
    suggestion = dict(item)
    action = actions.get(str(suggestion.get("id") or ""))
    inherited_from_path = False
    if action is None:
      relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
      if relative_path:
        action = _latest_obsidian_maintenance_action_for_relative_path(state, relative_path)
        inherited_from_path = action is not None
    if action:
      action_status = str(action.get("status") or "staged")
      draft_missing = (
        action_status == "staged"
        and project_dir is not None
        and _safe_staged_obsidian_draft_path(project_dir, action) is None
      )
      published_missing = _published_obsidian_note_missing(project_dir, action)
      published_outdated = (
        not published_missing
        and _published_obsidian_note_outdated(project_dir, action, suggestion.get("draft_markdown"))
      )
      if draft_missing:
        suggestion["status"] = "draft_missing"
      elif published_missing:
        suggestion["status"] = "published_missing"
      elif published_outdated:
        suggestion["status"] = "published_outdated"
      else:
        suggestion["status"] = action_status
      suggestion["draft_path"] = str(action.get("draft_path") or "")
      suggestion["merge_draft_path"] = str(action.get("merge_draft_path") or "")
      suggestion["merge_draft_relative_path"] = str(action.get("merge_draft_relative_path") or "")
      suggestion["vault_path"] = str(action.get("vault_path") or "")
      suggestion["vault_relative_path"] = str(action.get("vault_relative_path") or "")
      suggestion["vault_moved"] = bool(action.get("moved_from_vault_relative_path"))
      suggestion["moved_from_vault_relative_path"] = str(action.get("moved_from_vault_relative_path") or "")
      suggestion["staged_at"] = str(action.get("created_at") or "")
      suggestion["published_at"] = str(action.get("published_at") or "")
      suggestion["auto_staged"] = bool(action.get("auto_staged"))
      suggestion["relative_path"] = str(action.get("relative_path") or "")
      suggestion["status_inherited_from_path"] = inherited_from_path
      suggestion["draft_missing"] = draft_missing
      suggestion["published_missing"] = published_missing
      suggestion["published_outdated"] = published_outdated
      suggestion["merge_draft_manual_edits"] = bool(action.get("merge_draft_manual_edits"))
      suggestion["preserved_existing_draft"] = bool(action.get("preserved_existing_draft"))
      suggestion["manual_draft_edits"] = (
        False
        if draft_missing
        else bool(action.get("preserved_existing_draft")) or _action_draft_has_manual_edits(project_dir, action)
      )
    else:
      suggestion["status"] = "open"
      suggestion["draft_path"] = ""
      suggestion["merge_draft_path"] = ""
      suggestion["merge_draft_relative_path"] = ""
      suggestion["vault_path"] = ""
      suggestion["vault_relative_path"] = ""
      suggestion["vault_moved"] = False
      suggestion["moved_from_vault_relative_path"] = ""
      suggestion["staged_at"] = ""
      suggestion["published_at"] = ""
      suggestion["auto_staged"] = False
      suggestion["relative_path"] = ""
      suggestion["status_inherited_from_path"] = False
      suggestion["draft_missing"] = False
      suggestion["published_missing"] = False
      suggestion["published_outdated"] = False
      suggestion["merge_draft_manual_edits"] = False
      suggestion["preserved_existing_draft"] = False
      suggestion["manual_draft_edits"] = False
    hydrated.append(suggestion)
  return hydrated


def _obsidian_maintenance_item_status(item: dict[str, object]) -> str:
  if item.get("draft_missing"):
    return "draft_missing"
  if item.get("published_missing"):
    return "published_missing"
  if item.get("published_outdated"):
    return "published_outdated"
  return str(item.get("status") or "open")


def _obsidian_maintenance_priority_rank(item: dict[str, object]) -> int:
  return {"high": 3, "medium": 2, "low": 1}.get(str(item.get("priority") or "low"), 0)


def _obsidian_maintenance_source_chapter_indexes(item: dict[str, object]) -> list[int]:
  indexes: list[int] = []
  for raw in item.get("source_chapters", []) if isinstance(item.get("source_chapters"), list) else []:
    try:
      chapter_index = int(raw or 0)
    except (TypeError, ValueError):
      continue
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  return indexes


def _obsidian_maintenance_source_chapter_text(item: dict[str, object]) -> str:
  indexes = _obsidian_maintenance_source_chapter_indexes(item)
  if not indexes:
    return ""
  if len(indexes) == 1:
    return f"来源第 {indexes[0]} 章"
  return f"来源第 {'、'.join(str(index) for index in indexes[:4])} 章"


def _obsidian_maintenance_chapter_relevance_rank(item: dict[str, object], chapter_index: int) -> int:
  if chapter_index <= 0:
    return 0
  kind = str(item.get("kind") or "")
  source_chapters = _obsidian_maintenance_source_chapter_indexes(item)
  if kind in {"create_style_rule_note", "create_xp_rule_note"}:
    if not source_chapters:
      return 8
    if min(source_chapters) <= chapter_index:
      return 18
    return 1
  if not source_chapters:
    if kind in {"create_graph_note", "repair_graph_link"}:
      return 91
    return 10
  if chapter_index in source_chapters:
    return 100
  previous = [index for index in source_chapters if index < chapter_index]
  if previous:
    distance = chapter_index - max(previous)
    return max(20, 90 - min(distance, 70))
  future = [index for index in source_chapters if index > chapter_index]
  if future:
    distance = min(future) - chapter_index
    return max(1, 30 - min(distance, 29))
  return 10


def obsidian_maintenance_suggestion_sort_key(item: dict[str, object], chapter_index: int = 0) -> tuple[int, int, int, str]:
  status_rank, priority_rank, title = _obsidian_maintenance_attention_rank(item)
  return (
    _obsidian_maintenance_chapter_relevance_rank(item, chapter_index),
    status_rank,
    priority_rank,
    title,
  )


def _obsidian_maintenance_attention_rank(item: dict[str, object]) -> tuple[int, int, str]:
  status = _obsidian_maintenance_item_status(item)
  status_rank = {
    "draft_missing": 60,
    "published_missing": 55,
    "published_outdated": 53,
    "open": 50,
    "staged": 40,
  }.get(status, 10)
  if status == "staged" and item.get("manual_draft_edits"):
    status_rank = 45
  if status in {"published", "ignored"}:
    status_rank = 0
  return (
    status_rank,
    _obsidian_maintenance_priority_rank(item),
    str(item.get("title") or ""),
  )


def _obsidian_maintenance_summary(suggestions: list[dict[str, object]]) -> dict[str, object]:
  counts = {
    "open": 0,
    "staged": 0,
    "published": 0,
    "draft_missing": 0,
    "published_missing": 0,
    "published_outdated": 0,
    "vault_moved": 0,
    "ignored": 0,
  }
  auto_staged = 0
  manual_draft_edits = 0
  preserved_existing_draft = 0
  high_priority = 0
  for item in suggestions:
    status = _obsidian_maintenance_item_status(item)
    if status in counts:
      counts[status] += 1
    if item.get("vault_moved"):
      counts["vault_moved"] += 1
    if item.get("auto_staged"):
      auto_staged += 1
    if item.get("manual_draft_edits"):
      manual_draft_edits += 1
    if item.get("preserved_existing_draft"):
      preserved_existing_draft += 1
    if str(item.get("priority") or "") == "high":
      high_priority += 1

  top_items: list[dict[str, object]] = []
  actionable = [item for item in suggestions if _obsidian_maintenance_item_status(item) not in {"published", "ignored"}]
  for item in sorted(actionable, key=_obsidian_maintenance_attention_rank, reverse=True)[:4]:
    top_items.append(
      {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "priority": str(item.get("priority") or "medium"),
        "status": _obsidian_maintenance_item_status(item),
        "suggested_path": str(item.get("suggested_path") or ""),
        "action": str(item.get("action") or item.get("reason") or ""),
      }
    )

  needs_action = (
    counts["open"]
    + counts["staged"]
    + counts["draft_missing"]
    + counts["published_missing"]
    + counts["published_outdated"]
  )
  return {
    "total": len(suggestions),
    "needs_action": needs_action,
    "high_priority": high_priority,
    "auto_staged": auto_staged,
    "manual_draft_edits": manual_draft_edits,
    "preserved_existing_draft": preserved_existing_draft,
    "by_status": counts,
    "top_items": top_items,
  }


def _set_obsidian_maintenance_suggestions(
  state: dict[str, object],
  suggestions: list[dict[str, object]],
) -> dict[str, object]:
  state["obsidian_maintenance_suggestions"] = suggestions
  state["obsidian_maintenance_summary"] = _obsidian_maintenance_summary(suggestions)
  return state


def _frontmatter_range_text(value: object) -> str:
  if isinstance(value, list) and len(value) >= 2:
    try:
      start = int(value[0])
      end = int(value[1])
      if start > 0 and end >= start:
        if start == end:
          return f"第 {start} 章"
        return f"第 {start}-{end} 章"
    except (TypeError, ValueError):
      return ""
  return ""


def _frontmatter_list_lines(key: str, values: object, *, limit: int = 8) -> list[str]:
  items = _string_list(values, limit=limit)
  if not items:
    return []
  return [f"{key}:", *[f"  - {_compact_text(item, 80)}" for item in items]]


def _frontmatter_quoted_list_lines(key: str, values: object, *, limit: int = 8, item_limit: int = 140) -> list[str]:
  items = _string_list(values, limit=limit)
  lines: list[str] = []
  for item in items:
    cleaned = _compact_text(item, item_limit).replace("\\", "\\\\").replace('"', '\\"')
    if cleaned:
      lines.append(f'  - "{cleaned}"')
  if not lines:
    return []
  return [f"{key}:", *lines]


def _frontmatter_quoted_line(key: str, value: object, *, limit: int = 240) -> list[str]:
  cleaned = _compact_text(value, limit).replace("\\", "\\\\").replace('"', '\\"')
  if not cleaned:
    return []
  return [f'{key}: "{cleaned}"']


def _frontmatter_int_list_lines(key: str, values: object, *, limit: int = 8) -> list[str]:
  numbers: list[str] = []
  for value in values if isinstance(values, list) else [values]:
    try:
      number = int(value or 0)
    except (TypeError, ValueError):
      number = 0
    if number > 0 and str(number) not in numbers:
      numbers.append(str(number))
    if len(numbers) >= limit:
      break
  if not numbers:
    return []
  return [f"{key}:", *[f"  - {item}" for item in numbers]]


def _chapter_archive_source_hash(chapter: object) -> str:
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  chapter_title = str(getattr(chapter, "title", "") or "").strip()
  content = str(getattr(chapter, "content", "") or "").rstrip()
  return _text_content_hash(f"{chapter_index}\n{chapter_title}\n{content}\n")


def _positive_int_strings(values: list[object], *, limit: int = 8) -> list[str]:
  numbers: list[str] = []
  for value in values:
    try:
      number = int(value or 0)
    except (TypeError, ValueError):
      number = 0
    if number > 0 and str(number) not in numbers:
      numbers.append(str(number))
    if len(numbers) >= limit:
      break
  return numbers


def _source_chapter_reveal_line(source_chapter_indexes: list[object]) -> list[str]:
  chapters: list[int] = []
  for item in _positive_int_strings(source_chapter_indexes, limit=12):
    try:
      chapter_index = int(item)
    except (TypeError, ValueError):
      continue
    if chapter_index > 1:
      chapters.append(chapter_index)
  if not chapters:
    return []
  return [f"reveal_after_chapter: {max(chapters) - 1}"]


def _expected_payoff_frontmatter_lines(range_text: str) -> list[str]:
  cleaned = str(range_text or "").strip()
  if not cleaned:
    return []
  return [f"expected_payoff_range: {cleaned}"]


def _obsidian_source_scope_frontmatter_lines(notes: list[object]) -> list[str]:
  starts: list[int] = []
  ends: list[int] = []
  reveals: list[int] = []
  complete_ranges: list[tuple[int, int]] = []
  effective_starts: list[int] = []
  for note in notes:
    try:
      start = int(getattr(note, "chapter_start", 0) or 0)
    except (TypeError, ValueError):
      start = 0
    try:
      end = int(getattr(note, "chapter_end", 0) or 0)
    except (TypeError, ValueError):
      end = 0
    try:
      reveal_after = int(getattr(note, "reveal_after_chapter", 0) or 0)
    except (TypeError, ValueError):
      reveal_after = 0
    if start > 0:
      starts.append(start)
    if end > 0:
      ends.append(end)
    if start > 0 and end > 0:
      range_start, range_end = (start, end) if start <= end else (end, start)
      complete_ranges.append((range_start, range_end))
    if reveal_after > 0:
      reveals.append(reveal_after)
    effective_start_candidates: list[int] = []
    if start > 0:
      effective_start_candidates.append(start)
    if reveal_after > 0:
      effective_start_candidates.append(reveal_after + 1)
    if not effective_start_candidates and end > 0:
      effective_start_candidates.append(end)
    if effective_start_candidates:
      effective_starts.append(max(effective_start_candidates))

  lines: list[str] = []
  if len(complete_ranges) >= 2:
    merged_start, merged_end = sorted(complete_ranges)[0]
    has_gap = False
    for start, end in sorted(complete_ranges)[1:]:
      if start > merged_end + 1:
        has_gap = True
        break
      merged_end = max(merged_end, end)
    if has_gap:
      reveal_candidates = list(reveals)
      reveal_candidates.extend(max(0, start - 1) for start, _end in complete_ranges)
      reveal_after = max(reveal_candidates) if reveal_candidates else 0
      if reveal_after > 0:
        lines.append(f"reveal_after_chapter: {reveal_after}")
      return lines

  unique_effective_starts = sorted({item for item in effective_starts if item > 0})
  if len(unique_effective_starts) >= 2:
    reveal_candidates = list(reveals)
    reveal_candidates.extend(max(0, start - 1) for start in unique_effective_starts)
    reveal_after = max(reveal_candidates) if reveal_candidates else 0
    if reveal_after > 0:
      lines.append(f"reveal_after_chapter: {reveal_after}")
    return lines

  if starts and ends:
    start = min(starts)
    end = max(ends)
    if end < start:
      start, end = end, start
    lines.append(f"chapter_range: 第 {start} 章" if start == end else f"chapter_range: 第 {start}-{end} 章")
  elif starts:
    lines.append(f"chapter_start: {min(starts)}")
  elif ends:
    lines.append(f"chapter_end: {max(ends)}")
  if reveals:
    lines.append(f"reveal_after_chapter: {max(reveals)}")
  return lines


def _obsidian_note_scope_chapter_indexes(note: object) -> list[int]:
  indexes: list[int] = []
  try:
    start = int(getattr(note, "chapter_start", 0) or 0)
  except (TypeError, ValueError):
    start = 0
  try:
    end = int(getattr(note, "chapter_end", 0) or 0)
  except (TypeError, ValueError):
    end = 0
  try:
    reveal_after = int(getattr(note, "reveal_after_chapter", 0) or 0)
  except (TypeError, ValueError):
    reveal_after = 0
  if start > 0:
    indexes.append(start)
  if end > 0:
    indexes.append(end)
  if reveal_after > 0:
    indexes.append(reveal_after + 1)
  return indexes


def _obsidian_source_chapter_indexes(notes: list[object], *, limit: int = 8) -> list[int]:
  indexes: list[int] = []
  for note in notes:
    for chapter_index in _obsidian_note_scope_chapter_indexes(note):
      if chapter_index <= 0 or chapter_index in indexes:
        continue
      indexes.append(chapter_index)
      if len(indexes) >= limit:
        return indexes
  return indexes


def _safe_obsidian_link_label(value: object) -> str:
  label = _compact_text(value, 48)
  label = label.replace("[", "").replace("]", "").replace("|", "").replace("#", "")
  return label.strip()


def _obsidian_link_list(values: object, *, limit: int = 8) -> list[str]:
  return [f"[[{item}]]" for item in (_safe_obsidian_link_label(value) for value in _string_list(values, limit=limit)) if item]


def _obsidian_link_target_without_suffix(value: object) -> str:
  raw = str(value or "").replace("\\", "/").strip()
  if not raw:
    return ""
  return PurePosixPath(raw).with_suffix("").as_posix()


def _obsidian_note_paths_from_card(chapter_card: dict[str, object], *, limit: int = 8) -> list[str]:
  paths: list[str] = []
  for item in chapter_card.get("obsidian_notes", []) if isinstance(chapter_card.get("obsidian_notes"), list) else []:
    if not isinstance(item, dict):
      continue
    path = str(item.get("relative_path") or "").replace("\\", "/").strip()
    if not path or path in paths:
      continue
    paths.append(path)
    if len(paths) >= limit:
      break
  return paths


def _obsidian_structured_paths_from_card(chapter_card: dict[str, object], *, limit: int = 8) -> list[str]:
  paths: list[str] = []
  for key in ("obsidian_chapter_plans", "obsidian_narrative_debts", "obsidian_character_arcs"):
    for item in chapter_card.get(key, []) if isinstance(chapter_card.get(key), list) else []:
      if not isinstance(item, dict):
        continue
      path = str(item.get("relative_path") or "").replace("\\", "/").strip()
      if not path or path in paths:
        continue
      paths.append(path)
      if len(paths) >= limit:
        return paths
  return paths


def _issue_value(issue: object, key: str, default: object = "") -> object:
  if isinstance(issue, dict):
    return issue.get(key, default)
  return getattr(issue, key, default)


def _graph_issue_link(issue: object) -> str:
  links = _string_list(_issue_value(issue, "links", []), limit=1)
  if links:
    return links[0]
  title = str(_issue_value(issue, "title", "") or "")
  for prefix in ("未解析双链：", "歧义双链：", "重复命名："):
    if title.startswith(prefix):
      return title[len(prefix):].strip()
  return _compact_text(title, 48)


def _graph_issue_priority(issue: object) -> str:
  kind = str(_issue_value(issue, "kind", "") or "")
  notes = _string_list(_issue_value(issue, "notes", []), limit=12)
  severity = str(_issue_value(issue, "severity", "") or "")
  if kind in {"duplicate_label", "ambiguous_link"}:
    return "high"
  if kind == "scope_mismatch":
    return "high"
  if kind == "unresolved_link" and len(notes) >= 2:
    return "medium"
  if kind == "orphan_note" and len(notes) >= 2:
    return "medium"
  if severity == "error":
    return "high"
  if severity == "warning":
    return "medium"
  return "low"


def _graph_issue_action(issue: object) -> str:
  kind = str(_issue_value(issue, "kind", "") or "")
  if kind == "unresolved_link":
    return "建议确认这是缺失笔记还是链接写错；如果是正式设定，可先审校草稿再发布到 Vault。"
  if kind == "ambiguous_link":
    return "建议把来源笔记里的双链改成更完整路径，或调整重复笔记的标题和别名。"
  if kind == "duplicate_label":
    return "建议合并重复命名，或修改其中一篇笔记的标题 / aliases，避免双链指向不明。"
  if kind == "scope_mismatch":
    return "建议调整目标笔记章节范围，或把后段关系拆成新的 Graph 笔记，避免目标章节读不到已解析双链。"
  if kind == "orphan_note":
    return "建议审校图谱索引草稿，或为这些正式设定建立更具体的人物、事件、地点或章节关系。"
  return "建议检查 Obsidian 图谱关系，减少后续章节检索误读。"


def _graph_issue_source_notes(issue: object, notes: list[object]) -> list[object]:
  note_by_path = {
    str(getattr(note, "relative_path", "") or "").replace("\\", "/").strip(): note
    for note in notes
    if str(getattr(note, "relative_path", "") or "").strip()
  }
  source_notes: list[object] = []
  seen_paths: set[str] = set()
  for raw_path in _string_list(_issue_value(issue, "notes", []), limit=20):
    path = raw_path.replace("\\", "/").strip()
    if not path or path in seen_paths:
      continue
    note = note_by_path.get(path)
    if note is None:
      continue
    seen_paths.add(path)
    source_notes.append(note)
  return source_notes


def _graph_issue_source_chapters(issue: object, source_notes: list[object]) -> list[int]:
  message = str(_issue_value(issue, "message", "") or "")
  indexes: list[int] = []
  for raw in re.findall(r"第\s*(\d+)\s*章", message):
    try:
      chapter_index = int(raw)
    except (TypeError, ValueError):
      continue
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  if indexes:
    return indexes[:8]
  return _obsidian_source_chapter_indexes(source_notes, limit=8)


def _graph_orphan_maintenance_draft(source_notes: list[object]) -> str:
  orphan_notes: list[object] = []
  seen_paths: set[str] = set()
  for note in source_notes:
    path = str(getattr(note, "relative_path", "") or "").replace("\\", "/").strip()
    if not path or path in seen_paths:
      continue
    has_graph_relation = any(
      list(getattr(note, field, []) or [])
      for field in ("links", "resolved_links", "backlinks", "unresolved_links", "ambiguous_links")
    )
    if has_graph_relation:
      continue
    seen_paths.add(path)
    orphan_notes.append(note)
    if len(orphan_notes) >= 12:
      break
  if len(orphan_notes) < 2:
    return ""

  note_paths = [str(getattr(note, "relative_path", "") or "").replace("\\", "/").strip() for note in orphan_notes]
  note_links = _obsidian_link_list([_obsidian_link_target_without_suffix(path) for path in note_paths], limit=12)
  scope_lines = _obsidian_source_scope_frontmatter_lines(orphan_notes)
  frontmatter = [
    "---",
    "type: graph_index",
    "status: canonical",
    "usable_by_ai: true",
    "tags:",
    "  - Obsidian图谱",
    "  - 自动维护",
    *scope_lines,
    *_frontmatter_list_lines("source_notes", note_paths, limit=12),
    "---",
    "# 孤立笔记整理",
    "",
    "来源：Obsidian 图谱自动发现以下正式笔记没有可解析外链或反向链接。",
  ]
  if note_links:
    frontmatter.extend(["", "关联笔记："])
    for index, link in enumerate(note_links):
      title = _compact_text(getattr(orphan_notes[index], "title", "") or Path(note_paths[index]).stem, 60)
      frontmatter.append(f"- {link}：{title}")
  frontmatter.extend(
    [
      "",
      "处理建议：发布前确认这些笔记适合同属一个索引；如果某些笔记只适用于局部章节，请拆成更具体的关系笔记。",
    ]
  )
  return "\n".join(frontmatter).strip()


def _graph_issue_maintenance_draft(issue: object, source_notes: list[object] | None = None) -> str:
  kind = str(_issue_value(issue, "kind", "") or "")
  if kind == "orphan_note":
    return _graph_orphan_maintenance_draft(source_notes or [])
  if kind != "unresolved_link":
    return ""
  link = _safe_obsidian_link_label(_graph_issue_link(issue))
  if not link:
    return ""
  notes = _string_list(_issue_value(issue, "notes", []), limit=8)
  note_links = _obsidian_link_list([_obsidian_link_target_without_suffix(item) for item in notes], limit=8)
  scope_lines = _obsidian_source_scope_frontmatter_lines(source_notes or [])
  frontmatter = [
    "---",
    "type: graph_note",
    "status: canonical",
    "usable_by_ai: true",
    "tags:",
    "  - Obsidian图谱",
    "  - 自动维护",
    *scope_lines,
    *_frontmatter_list_lines("aliases", [link], limit=1),
    *_frontmatter_list_lines("source_notes", notes, limit=8),
    "---",
    f"# {link}",
    "",
    "来源：Obsidian 未解析双链自动生成的待审笔记。",
  ]
  if note_links:
    frontmatter.extend(["", "被以下笔记引用：", *[f"- {item}" for item in note_links]])
  message = _compact_text(_issue_value(issue, "message", ""), 180)
  if message:
    frontmatter.extend(["", f"图谱问题：{message}"])
  frontmatter.extend(
    [
      "",
      "处理建议：发布前确认它是正式设定；如果只是链接写错，请修改来源笔记里的双链。",
    ]
  )
  return "\n".join(frontmatter).strip()


def _graph_issue_maintenance_suggestions(project_detail: object) -> list[dict[str, object]]:
  suggestions: list[dict[str, object]] = []
  notes = _project_obsidian_notes(project_detail)
  for issue in _project_obsidian_issues(project_detail):
    kind = str(_issue_value(issue, "kind", "") or "")
    if kind not in {"unresolved_link", "ambiguous_link", "duplicate_label", "orphan_note", "scope_mismatch"}:
      continue
    link = _graph_issue_link(issue)
    title = _compact_text(_issue_value(issue, "title", "") or link or "Obsidian 图谱问题", 60)
    if not title:
      continue
    issue_key = hashlib.sha1(
      f"{kind}:{title}:{','.join(_string_list(_issue_value(issue, 'notes', []), limit=8))}".encode("utf-8")
    ).hexdigest()[:12]
    source_notes = _graph_issue_source_notes(issue, notes)
    draft_markdown = _graph_issue_maintenance_draft(issue, source_notes)
    source_chapters = _graph_issue_source_chapters(issue, source_notes)
    suggested_path = ""
    if draft_markdown:
      if kind == "orphan_note":
        suggested_path = f"Graph/孤立笔记整理-{issue_key}.md"
      else:
        suggested_path = f"Graph/{_safe_obsidian_filename(link or title, '图谱笔记')}.md"
    suggestions.append(
      {
        "id": f"obsidian-maintenance-graph-{issue_key}",
        "kind": "create_graph_note" if draft_markdown else "repair_graph_link",
        "priority": _graph_issue_priority(issue),
        "title": f"整理 Obsidian 图谱：{title}",
        "reason": _compact_text(_issue_value(issue, "message", ""), 180),
        "action": _graph_issue_action(issue),
        "source_ids": _string_list(_issue_value(issue, "notes", []), limit=8),
        "source_chapters": source_chapters,
        "suggested_path": suggested_path,
        "draft_markdown": draft_markdown,
      }
    )
    if len(suggestions) >= _MAX_OBSIDIAN_GRAPH_MAINTENANCE_SUGGESTIONS:
      break
  return suggestions


def _debt_maintenance_draft(debt: dict[str, object]) -> str:
  title = _compact_text(debt.get("title") or "剧情债务", 48)
  chapter_index = int(debt.get("last_seen_chapter_index") or debt.get("first_seen_chapter_index") or 0)
  range_text = _frontmatter_range_text(debt.get("expected_payoff_range"))
  content = _compact_text(debt.get("content"), 220)
  next_action = _compact_text(debt.get("next_required_action"), 180)
  source_chapter_indexes = _positive_int_strings([
    debt.get("first_seen_chapter_index"),
    debt.get("last_seen_chapter_index"),
  ], limit=4)
  related_characters = _string_list(debt.get("related_characters"), limit=8)
  frontmatter = [
    "---",
    "type: plot_debt",
    "status: canonical",
    "usable_by_ai: true",
    *_frontmatter_quoted_line("summary", content or title, limit=220),
    *_frontmatter_quoted_line("debt_content", content, limit=220),
    *_frontmatter_quoted_line("debt_kind", debt.get("kind") or "open_loop", limit=80),
    *_frontmatter_quoted_line("debt_status", debt.get("status") or "open", limit=80),
    *_frontmatter_quoted_line("risk_level", debt.get("risk_level") or "medium", limit=80),
    *_frontmatter_quoted_line("next_required_action", next_action, limit=180),
    "tags:",
    "  - 剧情债务",
    "  - 自动维护",
    *_frontmatter_list_lines("source_ids", [debt.get("id")], limit=2),
    *_frontmatter_int_list_lines("source_chapters", source_chapter_indexes, limit=4),
    *_source_chapter_reveal_line(source_chapter_indexes),
    *_expected_payoff_frontmatter_lines(range_text),
    *_frontmatter_list_lines("related_characters", related_characters, limit=8),
  ]
  frontmatter.append("---")
  lines = [
    *frontmatter,
    f"# {title}",
    "",
  ]
  if chapter_index:
    lines.append(f"来源章节：第 {chapter_index} 章")
  if range_text:
    lines.append(f"预计处理区间：{range_text}")
  character_links = _obsidian_link_list(related_characters, limit=8)
  if character_links:
    lines.append(f"相关人物：{'、'.join(character_links)}")
  if content:
    lines.append(f"当前状态：{content}")
  if next_action:
    lines.append(f"后续处理：{next_action}")
  evidence = _string_list(debt.get("evidence"), limit=4)
  if evidence:
    lines.extend(["", "证据：", *[f"- {item}" for item in evidence]])
  return "\n".join(lines).strip()


def _character_maintenance_draft(arc: dict[str, object]) -> str:
  name = _compact_text(arc.get("name") or "人物", 40)
  phase = _compact_text(arc.get("phase"), 80)
  current_state = _compact_text(arc.get("current_state"), 220)
  unresolved_pressure = _compact_text(arc.get("unresolved_pressure"), 180)
  required_next_check = _compact_text(arc.get("required_next_check"), 180)
  source_chapter_indexes = _positive_int_strings([
    arc.get("first_seen_chapter_index"),
    arc.get("last_seen_chapter_index"),
  ], limit=4)
  lines = [
    "---",
    "type: character",
    "status: canonical",
    "usable_by_ai: true",
    *_frontmatter_quoted_line("summary", current_state or name, limit=220),
    *_frontmatter_quoted_line("character", name, limit=80),
    *_frontmatter_quoted_line("phase", phase, limit=80),
    *_frontmatter_quoted_line("current_state", current_state, limit=220),
    *_frontmatter_quoted_line("unresolved_pressure", unresolved_pressure, limit=180),
    *_frontmatter_quoted_line("required_next_check", required_next_check, limit=180),
    "tags:",
    "  - 人物",
    "  - 人物状态",
    "  - 自动维护",
    *_frontmatter_list_lines("source_ids", [arc.get("id")], limit=2),
    *_frontmatter_int_list_lines("source_chapters", source_chapter_indexes, limit=4),
    *_source_chapter_reveal_line(source_chapter_indexes),
    "---",
    f"# {name}",
    "",
  ]
  if source_chapter_indexes:
    lines.append(f"来源章节：第 {'、'.join(source_chapter_indexes)} 章")
  if phase:
    lines.append(f"当前阶段：{phase}")
  if current_state:
    lines.append(f"当前状态：{current_state}")
  if unresolved_pressure:
    lines.append(f"未处理压力：{unresolved_pressure}")
  if required_next_check:
    lines.append(f"后续检查：{required_next_check}")
  evidence = _string_list(arc.get("evidence"), limit=4)
  if evidence:
    lines.extend(["", "证据：", *[f"- {item}" for item in evidence]])
  return "\n".join(lines).strip()


def _chapter_note_type(value: object) -> bool:
  normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
  return normalized in {
    "chapter",
    "chapter_note",
    "chapter_summary",
    "chapter_archive",
    "author_archive",
    "章节",
    "章节笔记",
    "章节档案",
    "章节摘要",
    "作者档案",
    "章节回顾",
  }


def _chapter_note_path_like(value: object) -> bool:
  lowered = str(value or "").replace("\\", "/").strip().lower()
  return any(
    prefix in lowered
    for prefix in ("chapternotes/", "chapter_notes/", "chapter-archive/", "chapterarchive/", "章节档案/")
  )


def _chapter_note_path_matches(note: object, chapter_index: int) -> bool:
  path = str(getattr(note, "relative_path", "") or "").replace("\\", "/").strip()
  if not path:
    return False
  if not _chapter_note_path_like(path):
    return False
  indexes = _obsidian_note_scope_chapter_indexes(note)
  return chapter_index in indexes


def _chapter_note_path_targets_chapter(value: object, chapter_index: int) -> bool:
  raw = str(value or "").replace("\\", "/").strip()
  if chapter_index <= 0 or not raw:
    return False
  if not _chapter_note_path_like(raw):
    return False
  return _parse_chapter_number(raw) == chapter_index


def _chapter_has_obsidian_note(
  chapter: object,
  notes: list[object],
  *,
  project_detail: object | None = None,
) -> bool:
  return bool(_matching_chapter_obsidian_notes(chapter, notes, project_detail=project_detail))


def _matching_chapter_obsidian_notes(
  chapter: object,
  notes: list[object],
  *,
  project_detail: object | None = None,
) -> list[object]:
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  if chapter_index <= 0:
    return []
  chapter_id = str(getattr(chapter, "id", "") or "").strip()
  matches: list[object] = []
  for note in notes:
    if project_detail is not None and chapter_id and chapter_id in _obsidian_note_source_ids(project_detail, note):
      matches.append(note)
      continue
    if (
      _chapter_note_type(getattr(note, "note_type", ""))
      and chapter_index in _obsidian_note_scope_chapter_indexes(note)
    ) or _chapter_note_path_matches(note, chapter_index):
      matches.append(note)
  return matches


def _chapter_archive_summary(content: str) -> list[str]:
  sentences = _split_sentences(content, limit=12)
  if len(sentences) <= 4:
    return sentences
  return [*sentences[:2], *sentences[-2:]]


def _chapter_archive_handoff_items(
  chapter_card: dict[str, object],
  summary_items: list[str],
  known_names: list[str],
  related_locations: list[str],
  related_props: list[str],
  related_organizations: list[str],
) -> list[str]:
  required_missing = _string_list(chapter_card.get("obsidian_required_missing"), limit=3)
  handoffs = [
    f"下一章需要处理未完成 Obsidian 必写项：{item}"
    for item in required_missing
    if item
  ]
  focus_terms = _ordered_unique([
    *known_names[:3],
    *related_locations[:2],
    *related_props[:2],
    *related_organizations[:2],
  ])
  if focus_terms:
    handoffs.append(f"下一章关注本章后果：{'、'.join(focus_terms[:6])}")
  elif summary_items:
    handoffs.append(f"下一章关注本章后果：{summary_items[-1]}")
  return _ordered_unique(handoffs)[:4]


def _chapter_archive_maintenance_draft(project_detail: object, chapter: object, chapter_card: dict[str, object]) -> str:
  chapter_id = str(getattr(chapter, "id", "") or "")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  chapter_title = str(getattr(chapter, "title", "") or "").strip() or f"第{chapter_index}章"
  content = str(getattr(chapter, "content", "") or "")
  known_names = [name for name in _known_names(project_detail) if name and name in content][:12]
  related_locations = _matched_overview_entity_names(project_detail, "locations", content, limit=8)
  related_props = _matched_overview_entity_names(project_detail, "props", content, limit=8)
  related_organizations = _matched_overview_entity_names(project_detail, "organizations", content, limit=8)
  character_links = _obsidian_link_list(known_names, limit=12)
  location_links = _obsidian_link_list(related_locations, limit=8)
  prop_links = _obsidian_link_list(related_props, limit=8)
  organization_links = _obsidian_link_list(related_organizations, limit=8)
  summary_items = _chapter_archive_summary(content)
  obsidian_sources = [
    item
    for item in _string_list(chapter_card.get("obsidian_sources"), limit=12)
    if not _chapter_note_path_like(item)
  ][:8]
  required_satisfied = _string_list(chapter_card.get("obsidian_required_satisfied"), limit=8)
  required_missing = _string_list(chapter_card.get("obsidian_required_missing"), limit=8)
  forbidden_violations = _string_list(chapter_card.get("obsidian_forbidden_violations"), limit=8)
  source_note_paths = [
    item
    for item in _ordered_unique([
      *_obsidian_note_paths_from_card(chapter_card, limit=12),
      *_obsidian_structured_paths_from_card(chapter_card, limit=12),
    ])
    if not _chapter_note_path_like(item)
  ][:8]
  source_note_links = _obsidian_link_list([_obsidian_link_target_without_suffix(path) for path in source_note_paths], limit=8)
  handoff_items = _chapter_archive_handoff_items(
    chapter_card,
    summary_items,
    known_names,
    related_locations,
    related_props,
    related_organizations,
  )
  obsidian_chapter_plan_lines = _obsidian_chapter_plan_prompt_lines(
    [item for item in chapter_card.get("obsidian_chapter_plans", []) if isinstance(item, dict)]
  )
  obsidian_debt_lines = _obsidian_narrative_debt_prompt_lines(
    [item for item in chapter_card.get("obsidian_narrative_debts", []) if isinstance(item, dict)]
  )
  obsidian_arc_lines = _obsidian_character_arc_prompt_lines(
    [item for item in chapter_card.get("obsidian_character_arcs", []) if isinstance(item, dict)]
  )
  blueprint_anchor = _compact_text(chapter_card.get("blueprint_anchor"), 180)
  one_line_summary = _compact_text(summary_items[0] if summary_items else content, 140)
  source_chapter_hash = _chapter_archive_source_hash(chapter)
  lines = [
    "---",
    "type: chapter_note",
    "status: canonical",
    "usable_by_ai: true",
    *_frontmatter_quoted_line("summary", one_line_summary, limit=220),
    f"chapter_index: {chapter_index}",
    *_frontmatter_quoted_line("chapter_title", chapter_title, limit=120),
    *_frontmatter_quoted_line("chapter_summary", one_line_summary, limit=220),
    *_frontmatter_quoted_line("blueprint_anchor", blueprint_anchor, limit=180),
    f"source_chapter_hash: {source_chapter_hash}",
    "tags:",
    "  - 章节档案",
    "  - 自动维护",
    *_frontmatter_list_lines("source_ids", [chapter_id], limit=1),
    *_frontmatter_int_list_lines("source_chapters", [chapter_index], limit=1),
    *_frontmatter_list_lines("source_notes", source_note_paths, limit=8),
    *_frontmatter_quoted_list_lines("handoff_to_next", handoff_items, limit=4, item_limit=180),
    *_frontmatter_quoted_list_lines("chapter_excerpt", summary_items[:6], limit=6, item_limit=180),
    *_frontmatter_quoted_list_lines("obsidian_required_satisfied", required_satisfied, limit=8, item_limit=120),
    *_frontmatter_quoted_list_lines("obsidian_required_missing", required_missing, limit=8, item_limit=120),
    *_frontmatter_quoted_list_lines("obsidian_forbidden_violations", forbidden_violations, limit=8, item_limit=120),
    *_source_chapter_reveal_line([chapter_index]),
    *_frontmatter_list_lines("related_characters", known_names, limit=12),
    *_frontmatter_list_lines("related_locations", related_locations, limit=8),
    *_frontmatter_list_lines("related_props", related_props, limit=8),
    *_frontmatter_list_lines("related_organizations", related_organizations, limit=8),
    "---",
    f"# 第 {chapter_index} 章 {chapter_title}",
    "",
    f"来源章节：第 {chapter_index} 章《{chapter_title}》",
    "状态：章节保存后自动生成的待审档案，发布前请确认摘要和关联人物。",
  ]
  if blueprint_anchor:
    lines.append(f"蓝图锚点：{blueprint_anchor}")
  if character_links:
    lines.append(f"相关人物：{'、'.join(character_links)}")
  if location_links:
    lines.append(f"相关地点：{'、'.join(location_links)}")
  if prop_links:
    lines.append(f"相关道具：{'、'.join(prop_links)}")
  if organization_links:
    lines.append(f"相关组织：{'、'.join(organization_links)}")
  if obsidian_sources:
    lines.extend(["", "本章 Obsidian 来源：", *[f"- {item}" for item in obsidian_sources]])
  if source_note_links:
    lines.extend(["", "来源笔记：", *[f"- {item}" for item in source_note_links]])
  if obsidian_chapter_plan_lines:
    lines.extend(["", "本章 Obsidian 章节计划：", *obsidian_chapter_plan_lines])
  if obsidian_debt_lines:
    lines.extend(["", "本章 Obsidian 剧情债务：", *obsidian_debt_lines])
  if obsidian_arc_lines:
    lines.extend(["", "本章 Obsidian 人物弧线：", *obsidian_arc_lines])
  if handoff_items:
    lines.extend(["", "下一章交接：", *[f"- {item}" for item in handoff_items]])
  if required_satisfied:
    lines.extend(["", "已满足的 Obsidian 必写项：", *[f"- {item}" for item in required_satisfied]])
  if required_missing:
    lines.extend(["", "未完成的 Obsidian 必写项：", *[f"- {item}" for item in required_missing]])
  if forbidden_violations:
    lines.extend(["", "已触犯的 Obsidian 禁写项：", *[f"- {item}" for item in forbidden_violations]])
  if summary_items:
    lines.extend(["", "章节正文摘录：", *[f"- {item}" for item in summary_items[:6]]])
  return "\n".join(lines).strip()


def _chapter_note_maintenance_suggestions(
  project_detail: object,
  notes: list[object],
  state: dict[str, object] | None = None,
  project_dir: Path | None = None,
) -> list[dict[str, object]]:
  chapters = [
    chapter
    for chapter in getattr(project_detail, "chapters", []) or []
    if bool(getattr(chapter, "exists", False)) and str(getattr(chapter, "content", "") or "").strip()
  ]
  chapters.sort(key=lambda item: int(getattr(item, "index", 0) or 0), reverse=True)
  suggestions: list[dict[str, object]] = []
  for chapter in chapters:
    if len(suggestions) >= _MAX_OBSIDIAN_CHAPTER_NOTE_SUGGESTIONS:
      break
    chapter_index = int(getattr(chapter, "index", 0) or 0)
    if chapter_index <= 0:
      continue
    chapter_id = str(getattr(chapter, "id", "") or "") or f"chapter-{chapter_index:03d}"
    suggestion_id = f"obsidian-maintenance-chapter-{chapter_id}"
    latest_action = _latest_obsidian_maintenance_action(state or {}, suggestion_id)
    title = str(getattr(chapter, "title", "") or "").strip() or f"第{chapter_index}章"
    safe_title = _safe_obsidian_filename(title, f"第{chapter_index:03d}章")
    chapter_card = _build_chapter_card(project_detail, chapter)
    draft_markdown = _chapter_archive_maintenance_draft(project_detail, chapter, chapter_card)
    draft_markdown = str(
      _with_obsidian_maintenance_identity({
        "id": suggestion_id,
        "kind": "create_chapter_note",
        "draft_markdown": draft_markdown,
      }).get("draft_markdown")
      or draft_markdown
    )
    matching_notes = _matching_chapter_obsidian_notes(chapter, notes, project_detail=project_detail)
    has_chapter_note = bool(matching_notes)
    current_source_hash = _chapter_archive_source_hash(chapter)
    matching_hashes = [
      str(getattr(note, "source_chapter_hash", "") or "").strip()
      for note in matching_notes
      if str(getattr(note, "source_chapter_hash", "") or "").strip()
    ]
    chapter_note_hash_outdated = bool(matching_hashes) and current_source_hash not in matching_hashes
    reason = "章节正文已经保存，但没有匹配到可用 Obsidian 章节档案。"
    action_text = "建议生成章节档案草稿，发布后给后续章节检索和叙事承接使用。"
    if has_chapter_note:
      published_action = latest_action is not None and str(latest_action.get("status") or "") == "published"
      if not chapter_note_hash_outdated and (not published_action or project_dir is None):
        continue
      if (
        not chapter_note_hash_outdated
        and not _published_obsidian_note_missing(project_dir, latest_action)
        and not _published_obsidian_note_outdated(
          project_dir,
          latest_action,
          draft_markdown,
        )
      ):
        continue
      reason = "章节档案已经发布，但章节正文或标题已经变化，Vault 笔记需要人工检查。"
      action_text = "建议保存新版章节档案草稿，再由作者合并到已发布的 Vault 笔记。"
    suggestions.append(
      {
        "id": suggestion_id,
        "kind": "create_chapter_note",
        "priority": "medium",
        "title": f"整理章节档案：第 {chapter_index} 章《{title}》",
        "reason": reason,
        "action": action_text,
        "source_ids": [chapter_id],
        "source_chapters": [chapter_index],
        "suggested_path": f"ChapterNotes/第{chapter_index:03d}章-{safe_title}.md",
        "draft_markdown": draft_markdown,
      }
    )
  return suggestions


def _style_xp_rule_source_chapters(rule: dict[str, object]) -> list[int]:
  indexes: list[int] = []
  for chapter_id in rule.get("source_chapter_ids", []) if isinstance(rule.get("source_chapter_ids"), list) else []:
    chapter_index = _chapter_index_from_id(str(chapter_id or ""))
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  return indexes[:8]


def _style_xp_rule_has_obsidian_note_match(
  rule: dict[str, object],
  notes: list[object],
  *,
  project_detail: object | None = None,
) -> bool:
  kind = str(rule.get("kind") or "").strip()
  content = _compact_text(rule.get("content"), 180)
  if kind not in {"style", "xp"} or not content:
    return True
  rule_id = str(rule.get("id") or "").strip()
  for note in notes:
    if obsidian_style_xp_note_kind(note) != kind:
      continue
    if project_detail is not None and rule_id and rule_id in _obsidian_note_source_ids(project_detail, note):
      return True
    haystack = "\n".join(
      str(value or "")
      for value in (
        getattr(note, "title", ""),
        getattr(note, "summary", ""),
        getattr(note, "preview", ""),
        " ".join(str(item or "") for item in getattr(note, "keywords", []) or []),
        " ".join(str(item or "") for item in getattr(note, "aliases", []) or []),
      )
    )
    if content in haystack:
      return True
  return False


def _style_xp_rule_maintenance_draft(rule: dict[str, object], source_chapters: list[int]) -> str:
  kind = str(rule.get("kind") or "").strip()
  is_style = kind == "style"
  label = "文风" if is_style else "XP"
  note_type = "style_rule" if is_style else "xp_rule"
  content = _compact_text(rule.get("content"), 220)
  rationale = _compact_text(rule.get("rationale"), 220)
  evidence_count = int(rule.get("evidence_count") or 0)
  confidence = round(float(rule.get("confidence") or 0), 3)
  source_text = "、".join(f"第 {index} 章" for index in source_chapters[:6])
  lines = [
    "---",
    f"type: {note_type}",
    "status: canonical",
    "usable_by_ai: true",
    *_frontmatter_quoted_line("summary", content, limit=220),
    *_frontmatter_quoted_line("style_rule" if is_style else "xp_rule", content, limit=220),
    *(
      _frontmatter_list_lines("applies_to", ["章节生成", "改稿", "去 AI"], limit=3)
      if is_style
      else _frontmatter_quoted_line("postcheck", "确认这条 XP 已体现在场景推进、信息揭示和章尾压力里。", limit=120)
    ),
    f"evidence_count: {evidence_count}" if evidence_count else "",
    f"confidence: {confidence}" if confidence else "",
    "tags:",
    f"  - {label}",
    "  - 自动维护",
    *_frontmatter_list_lines("source_ids", [str(rule.get("id") or "")], limit=1),
    *_frontmatter_int_list_lines("source_chapters", source_chapters, limit=8),
    *_source_chapter_reveal_line(source_chapters),
    "---",
    f"# {label}规则：{content}",
    "",
    "来源：系统从已保存章节和章节核验记录中识别出的稳定写作规律。",
  ]
  if source_text:
    lines.append(f"证据章节：{source_text}")
  if evidence_count:
    lines.append(f"证据数量：{evidence_count}")
  if confidence:
    lines.append(f"置信度：{confidence}")
  lines.extend(["", f"{label}规则：{content}"])
  if rationale:
    lines.append(f"识别依据：{rationale}")
  if is_style:
    lines.append("使用建议：后续章节生成和改稿时作为作者文风参考，优先级低于作者显式要求。")
  else:
    lines.append("使用建议：后续章节生成后作为检查项，确认场景推进、信息揭示和章尾压力是否满足。")
  return "\n".join(lines).strip()


def _style_xp_rule_maintenance_suggestions(
  project_detail: object,
  notes: list[object],
  project_dir: Path | None,
) -> list[dict[str, object]]:
  if project_dir is None:
    return []
  style_state = load_project_style_xp_state(project_dir)
  rules = [
    item
    for item in style_state.get("rules", [])
    if (
      isinstance(item, dict)
      and str(item.get("status") or "") == "active"
      and str(item.get("kind") or "") in {"style", "xp"}
      and str(item.get("content") or "").strip()
      and int(item.get("evidence_count") or 0) >= 2
    )
  ]
  rules.sort(
    key=lambda item: (
      int(item.get("evidence_count") or 0),
      float(item.get("confidence") or 0),
      str(item.get("content") or ""),
    ),
    reverse=True,
  )
  suggestions: list[dict[str, object]] = []
  for rule in rules[:12]:
    if _style_xp_rule_has_obsidian_note_match(rule, notes, project_detail=project_detail):
      continue
    rule_id = str(rule.get("id") or "").strip()
    if not rule_id:
      continue
    kind = str(rule.get("kind") or "").strip()
    label = "文风" if kind == "style" else "XP"
    content = _compact_text(rule.get("content"), 48)
    source_chapters = _style_xp_rule_source_chapters(rule)
    folder = "Style" if kind == "style" else "XP"
    filename = _safe_obsidian_filename(content, f"{label}规则")
    suggestions.append(
      {
        "id": f"obsidian-maintenance-style-xp-{rule_id}",
        "kind": f"create_{kind}_rule_note",
        "priority": "low",
        "title": f"整理{label}规则笔记：{content}",
        "reason": "这条系统学习规则已在多个章节重复出现，但还没有匹配到可用 Obsidian 规则笔记。",
        "action": "建议整理成 Vault 待审规则，发布后可按章节边界进入文风 / XP 提示。",
        "source_ids": [rule_id],
        "source_chapters": source_chapters,
        "suggested_path": f"{folder}/{filename}.md",
        "draft_markdown": _style_xp_rule_maintenance_draft(rule, source_chapters),
      }
    )
  return suggestions


def _contract_source_chapters(contract: dict[str, object]) -> list[int]:
  indexes: list[int] = []
  for key in ("source_chapter_index", "target_chapter_index"):
    try:
      chapter_index = int(contract.get(key) or 0)
    except (TypeError, ValueError):
      chapter_index = 0
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  return indexes[:4]


def _chapter_contract_maintenance_id(contract: dict[str, object]) -> str:
  contract_id = str(contract.get("id") or "").strip()
  return f"obsidian-maintenance-contract-{contract_id}" if contract_id else ""


def _chapter_contract_has_obsidian_plan_match(project_detail: object, contract: dict[str, object]) -> bool:
  try:
    target_index = int(contract.get("target_chapter_index") or 0)
  except (TypeError, ValueError):
    target_index = 0
  if target_index <= 0:
    return True
  records = _obsidian_chapter_plan_records(project_detail, target_index, limit=8)
  if not records:
    return False
  expected_identity = _chapter_contract_maintenance_id(contract)
  contract_id = str(contract.get("id") or "").strip()
  if expected_identity:
    for record in records:
      note = getattr(record, "summary", None)
      identity = _obsidian_note_maintenance_identity(project_detail, note)
      if identity and identity == expected_identity:
        return True
      if contract_id and contract_id in _obsidian_note_source_ids(project_detail, note):
        return True
  objective = _compact_text(contract.get("objective"), 120)
  required_beats = _string_list(contract.get("required_beats"), limit=4)
  if not objective and not required_beats:
    return True
  needle_values = [objective, *required_beats]
  haystack = "\n".join(
    "\n".join(
      [
        str(getattr(getattr(record, "summary", None), "title", "") or ""),
        str(getattr(getattr(record, "summary", None), "relative_path", "") or ""),
        " ".join(_obsidian_plan_body_lines(record, limit=12)),
      ]
    )
    for record in records
  )
  return any(value and value in haystack for value in needle_values)


def _chapter_contract_maintenance_draft(contract: dict[str, object]) -> str:
  target_index = int(contract.get("target_chapter_index") or 0)
  source_index = int(contract.get("source_chapter_index") or 0)
  objective = _compact_text(contract.get("objective"), 220)
  source_chapters = _contract_source_chapters(contract)
  lines = [
    "---",
    "type: chapter_contract",
    "status: canonical",
    "usable_by_ai: true",
    *_frontmatter_quoted_line("summary", objective or f"第 {target_index} 章章节合同", limit=220),
    f"chapter_range: 第 {target_index} 章" if target_index > 0 else "",
    "tags:",
    "  - 章节合同",
    "  - 自动维护",
    *_frontmatter_list_lines("source_ids", [str(contract.get("id") or "")], limit=1),
    *_frontmatter_int_list_lines("source_chapters", source_chapters, limit=4),
    "---",
    f"# 第 {target_index} 章章节合同" if target_index > 0 else "# 章节合同",
    "",
  ]
  lines = [line for line in lines if str(line).strip()]
  if source_index > 0:
    lines.append(f"来源章节：第 {source_index} 章")
  if objective:
    lines.extend(["", f"章节目标：{objective}"])
  section_specs = (
    ("必须完成的节拍", contract.get("required_beats")),
    ("必须推进的债务", contract.get("debts_to_advance")),
    ("不能提前揭开的债务", contract.get("debts_to_protect")),
    ("人物检查", contract.get("character_checks")),
    ("文风检查", contract.get("style_checks")),
    ("禁止动作", contract.get("forbidden_moves")),
    ("验收项", contract.get("acceptance_checks")),
    ("证据来源", contract.get("evidence_sources")),
    ("风险提示", contract.get("risk_notes")),
  )
  for title, values in section_specs:
    items = _string_list(values, limit=8)
    if items:
      lines.extend(["", f"{title}：", *[f"- {item}" for item in items]])
  return "\n".join(lines).strip()


def _chapter_contract_maintenance_suggestions(project_detail: object, state: dict[str, object]) -> list[dict[str, object]]:
  contracts = [
    item
    for item in state.get("chapter_contracts", [])
    if (
      isinstance(item, dict)
      and str(item.get("status") or "active") == "active"
      and int(item.get("target_chapter_index") or 0) > 0
      and (str(item.get("objective") or "").strip() or _string_list(item.get("required_beats"), limit=1))
    )
  ]
  contracts.sort(
    key=lambda item: (
      int(item.get("target_chapter_index") or 0),
      str(item.get("generated_at") or ""),
    ),
    reverse=True,
  )
  suggestions: list[dict[str, object]] = []
  for contract in contracts[:20]:
    if _chapter_contract_has_obsidian_plan_match(project_detail, contract):
      continue
    contract_id = str(contract.get("id") or "").strip()
    target_index = int(contract.get("target_chapter_index") or 0)
    if not contract_id or target_index <= 0:
      continue
    objective = _compact_text(contract.get("objective") or f"第 {target_index} 章章节合同", 48)
    safe_title = _safe_obsidian_filename(objective, "章节合同")
    suggestions.append(
      {
        "id": _chapter_contract_maintenance_id(contract),
        "kind": "create_chapter_contract_note",
        "priority": "medium",
        "title": f"整理章节合同：第 {target_index} 章《{objective}》",
        "reason": "模型叙事编辑已经生成下一章写作合同，但没有匹配到可用 Obsidian 章节计划或章节合同笔记。",
        "action": "建议整理成 Vault 待审章节合同，发布后给目标章节生成、改稿和叙事检查使用。",
        "source_ids": [contract_id],
        "source_chapters": _contract_source_chapters(contract),
        "suggested_path": f"Plans/第{target_index:03d}章-章节合同-{safe_title}.md",
        "draft_markdown": _chapter_contract_maintenance_draft(contract),
      }
    )
  return suggestions


def _obsidian_maintenance_suggestions(
  project_detail: object,
  state: dict[str, object],
  project_dir: Path | None = None,
) -> list[dict[str, object]]:
  if not _obsidian_state_enabled(project_detail):
    return []

  notes = _project_obsidian_notes(project_detail)
  vault_source_ids = _obsidian_vault_source_ids(project_detail, notes)
  suggestions: list[dict[str, object]] = []
  priority_rank = {"high": 3, "medium": 2, "low": 1}

  def add_suggestion(item: dict[str, object]) -> None:
    suggestion_id = str(item.get("id") or "").strip()
    if not suggestion_id:
      return
    if any(str(existing.get("id") or "") == suggestion_id for existing in suggestions):
      return
    item = _with_obsidian_maintenance_identity(item)
    suggestions.append(item)

  for suggestion in _graph_issue_maintenance_suggestions(project_detail):
    add_suggestion(suggestion)

  for suggestion in _chapter_note_maintenance_suggestions(project_detail, notes, state, project_dir):
    add_suggestion(suggestion)

  for suggestion in _chapter_contract_maintenance_suggestions(project_detail, state):
    add_suggestion(suggestion)

  for suggestion in _style_xp_rule_maintenance_suggestions(project_detail, notes, project_dir):
    add_suggestion(suggestion)

  debts = [item for item in state.get("debts", []) if isinstance(item, dict)]
  debts.sort(
    key=lambda item: (
      priority_rank.get(str(item.get("risk_level") or "low"), 0),
      int(item.get("last_seen_chapter_index") or item.get("first_seen_chapter_index") or 0),
    ),
    reverse=True,
  )
  for debt in debts:
    if len(suggestions) >= _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS:
      break
    status = str(debt.get("status") or "open")
    if status in {"paid", "deferred"}:
      continue
    debt_id = str(debt.get("id") or "")
    title = _compact_text(debt.get("title") or debt.get("content") or "剧情债务", 48)
    risk = str(debt.get("risk_level") or "low")
    priority = "high" if risk in {"critical", "high"} else "medium" if risk == "medium" else "low"
    source_names = [str(item or "").strip() for item in debt.get("source_names", []) or []]
    source_chapters = [
      int(item)
      for item in _positive_int_strings(
        [debt.get("first_seen_chapter_index"), debt.get("last_seen_chapter_index")],
        limit=4,
      )
    ]
    if "obsidian_constraint" in source_names:
      add_suggestion(
        {
          "id": f"obsidian-maintenance-repair-{debt_id}",
          "kind": "repair_chapter",
          "priority": "high" if risk == "critical" else priority,
          "title": f"处理 Obsidian 章节约束：{title}",
          "reason": _compact_text(debt.get("content") or "", 180),
          "action": _compact_text(debt.get("next_required_action") or "先修订章节正文；如果 Vault 要求已经变化，再调整该要求的适用章节或约束文字。", 180),
          "source_ids": [debt_id] if debt_id else [],
          "source_chapters": source_chapters,
          "suggested_path": "",
          "draft_markdown": "",
        }
      )
      continue
    if _debt_has_obsidian_note_match(debt, notes, vault_source_ids=vault_source_ids):
      continue
    filename = _safe_obsidian_filename(title, "剧情债务")
    suggested_path = f"Plot/{filename}.md"
    add_suggestion(
      {
        "id": f"obsidian-maintenance-debt-{debt_id}",
        "kind": "create_plot_note",
        "priority": priority,
        "title": f"整理剧情债务笔记：{title}",
        "reason": "这条债务已进入项目账本，但没有匹配到可用 Obsidian 笔记。",
        "action": "建议把它整理成 Vault 正式笔记，后续章节能按章节范围和图谱关系读取。",
        "source_ids": [debt_id] if debt_id else [],
        "source_chapters": source_chapters,
        "suggested_path": suggested_path,
        "draft_markdown": _debt_maintenance_draft(debt),
      }
    )

  arcs = [item for item in state.get("character_arcs", []) if isinstance(item, dict)]
  arcs.sort(
    key=lambda item: (
      float(item.get("confidence") or 0),
      int(item.get("last_seen_chapter_index") or 0),
    ),
    reverse=True,
  )
  for arc in arcs:
    if len(suggestions) >= _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS:
      break
    name = str(arc.get("name") or "").strip()
    if not name or _character_has_obsidian_note(
      name,
      notes,
      source_id=str(arc.get("id") or ""),
      vault_source_ids=vault_source_ids,
    ):
      continue
    if float(arc.get("confidence") or 0) < 0.64 and not int(arc.get("last_seen_chapter_index") or 0):
      continue
    suggested_path = f"Characters/{_safe_obsidian_filename(name, '人物')}.md"
    source_chapters = [
      int(item)
      for item in _positive_int_strings(
        [arc.get("first_seen_chapter_index"), arc.get("last_seen_chapter_index")],
        limit=4,
      )
    ]
    add_suggestion(
      {
        "id": f"obsidian-maintenance-arc-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}",
        "kind": "create_character_note",
        "priority": "medium",
        "title": f"整理人物状态笔记：{name}",
        "reason": "人物弧线已进入项目账本，但没有匹配到可用 Obsidian 人物笔记。",
        "action": "建议建立人物笔记，记录当前阶段、状态压力和后续检查项。",
        "source_ids": [str(arc.get("id") or "")],
        "source_chapters": source_chapters,
        "suggested_path": suggested_path,
        "draft_markdown": _character_maintenance_draft(arc),
      }
    )

  suggestions.sort(
    key=lambda item: (
      priority_rank.get(str(item.get("priority") or "low"), 0),
      str(item.get("kind") or ""),
      str(item.get("title") or ""),
    ),
    reverse=True,
  )
  return _attach_maintenance_action_status(
    suggestions[:_MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS],
    state,
    project_dir,
  )


def _find_obsidian_maintenance_suggestion(
  project_detail: object,
  state: dict[str, object],
  suggestion_id: str,
  project_dir: Path | None = None,
) -> dict[str, object] | None:
  normalized_id = str(suggestion_id or "").strip()
  if not normalized_id:
    return None
  for item in _obsidian_maintenance_suggestions(project_detail, state, project_dir):
    if str(item.get("id") or "") == normalized_id:
      return item
  return None


def _frontmatter_has_key(markdown: str, key: str) -> bool:
  payload = _draft_frontmatter_payload(markdown)
  target = _draft_frontmatter_key_id(key)
  return any(_draft_frontmatter_key_id(raw_key) == target for raw_key in payload)


def _inject_frontmatter_lines(markdown: str, lines: list[str]) -> str:
  text = str(markdown or "").strip()
  if not text or not lines:
    return text
  parts = text.splitlines()
  if not parts or parts[0].strip() != "---":
    return text
  end_index = -1
  for index in range(1, len(parts)):
    if parts[index].strip() == "---":
      end_index = index
      break
  if end_index < 0:
    return text
  return "\n".join([parts[0], *lines, *parts[1:]])


def _with_obsidian_maintenance_identity(item: dict[str, object]) -> dict[str, object]:
  draft_markdown = str(item.get("draft_markdown") or "").strip()
  suggestion_id = str(item.get("id") or "").strip()
  if not draft_markdown or not suggestion_id:
    return item
  updated_markdown = _ensure_obsidian_maintenance_identity_markdown(
    draft_markdown,
    suggestion_id,
    str(item.get("kind") or "").strip(),
  )
  if updated_markdown == draft_markdown:
    return item
  updated = dict(item)
  updated["draft_markdown"] = updated_markdown
  return updated


def _ensure_obsidian_maintenance_identity_markdown(markdown: str, suggestion_id: str, kind: str = "") -> str:
  text = str(markdown or "").strip()
  identity = str(suggestion_id or "").strip()
  if not text or not identity:
    return text
  lines: list[str] = []
  if not _frontmatter_has_key(text, "gaoxia_maintenance_id"):
    lines.append(f"gaoxia_maintenance_id: {identity}")
  if not _frontmatter_has_key(text, "gaoxia_maintenance_kind"):
    normalized_kind = str(kind or "").strip()
    if normalized_kind:
      lines.append(f"gaoxia_maintenance_kind: {normalized_kind}")
  if not lines:
    return text
  return _inject_frontmatter_lines(text, lines)


def _latest_obsidian_maintenance_action(state: dict[str, object], suggestion_id: str) -> dict[str, object] | None:
  normalized_id = str(suggestion_id or "").strip()
  if not normalized_id:
    return None
  return _maintenance_actions_by_suggestion(state).get(normalized_id)


def _text_content_hash(text: str) -> str:
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _latest_obsidian_maintenance_action_for_relative_path(
  state: dict[str, object],
  relative_path: str,
) -> dict[str, object] | None:
  normalized_path = str(relative_path or "").replace("\\", "/").strip()
  if not normalized_path:
    return None
  latest: dict[str, object] | None = None
  for item in state.get("obsidian_maintenance_actions", []) or []:
    if not isinstance(item, dict):
      continue
    item_path = str(item.get("relative_path") or "").replace("\\", "/").strip()
    if item_path != normalized_path:
      continue
    if latest is None or str(item.get("created_at") or "") >= str(latest.get("created_at") or ""):
      latest = item
  return latest


def _latest_obsidian_maintenance_action_for_suggestion(
  state: dict[str, object],
  suggestion: dict[str, object],
) -> dict[str, object] | None:
  action = _latest_obsidian_maintenance_action(state, str(suggestion.get("id") or ""))
  if action is not None:
    return action
  relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
  if not relative_path:
    return None
  return _latest_obsidian_maintenance_action_for_relative_path(state, relative_path)


def _latest_published_obsidian_maintenance_action_for_suggestion(
  state: dict[str, object],
  suggestion: dict[str, object],
) -> dict[str, object] | None:
  suggestion_id = str(suggestion.get("id") or "").strip()
  relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
  latest: dict[str, object] | None = None
  latest_created_at = ""
  for item in state.get("obsidian_maintenance_actions", []) or []:
    if not isinstance(item, dict) or str(item.get("status") or "") != "published":
      continue
    item_suggestion_id = str(item.get("suggestion_id") or "").strip()
    item_relative_path = str(item.get("relative_path") or item.get("vault_relative_path") or "").replace("\\", "/").strip()
    if suggestion_id and item_suggestion_id == suggestion_id:
      matches = True
    elif relative_path and item_relative_path == relative_path:
      matches = True
    else:
      matches = False
    if not matches:
      continue
    created_at = str(item.get("created_at") or item.get("published_at") or "")
    if latest is None or created_at >= latest_created_at:
      latest = item
      latest_created_at = created_at
  return latest


def _safe_staged_obsidian_draft_path(project_dir: Path, action: dict[str, object] | None) -> Path | None:
  if not action:
    return None
  raw_path = str(action.get("draft_path") or "").strip()
  if not raw_path:
    return None
  path = Path(raw_path).expanduser()
  if not path.is_absolute():
    path = project_dir / path
  try:
    path.resolve().relative_to(obsidian_draft_dir(project_dir).resolve())
  except ValueError:
    return None
  return path if path.exists() and path.is_file() else None


def _safe_vault_relative_path(value: object) -> Path | None:
  raw = str(value or "").strip().replace("\\", "/")
  if not raw:
    return None
  path = Path(raw)
  if path.is_absolute() or ".." in path.parts:
    return None
  parts = [part for part in path.parts if part not in {"", "."}]
  return Path(*parts) if parts else None


def _published_obsidian_note_path(project_dir: Path | None, action: dict[str, object] | None) -> Path | None:
  if project_dir is None or not action or str(action.get("status") or "") != "published":
    return None
  config = load_obsidian_config(project_dir)
  vault_dir = resolve_obsidian_vault_dir(project_dir, config)
  if vault_dir is None:
    return None
  raw_relative = action.get("vault_relative_path") or action.get("relative_path")
  relative_path = _safe_vault_relative_path(raw_relative)
  if relative_path is not None:
    note_path = vault_dir / relative_path
  else:
    raw_path = str(action.get("vault_path") or "").strip()
    if not raw_path:
      return None
    note_path = Path(raw_path).expanduser()
    if not note_path.is_absolute():
      note_path = vault_dir / note_path
  try:
    note_path.resolve().relative_to(vault_dir.resolve())
  except ValueError:
    return None
  return note_path


def _published_obsidian_note_relative_path(action: dict[str, object] | None) -> Path | None:
  if not action:
    return None
  return _safe_vault_relative_path(action.get("vault_relative_path") or action.get("relative_path"))


def _published_obsidian_note_missing(project_dir: Path | None, action: dict[str, object] | None) -> bool:
  note_path = _published_obsidian_note_path(project_dir, action)
  if note_path is None:
    return False
  return not note_path.is_file()


def _obsidian_maintenance_identity_from_markdown(markdown: str) -> str:
  payload = _draft_frontmatter_payload(markdown)
  return _draft_frontmatter_value(
    payload,
    ("gaoxia_maintenance_id", "gaoxia suggestion id", "gaoxia_suggestion_id", "maintenance_id"),
  )


def _obsidian_maintenance_kind_from_markdown(markdown: str) -> str:
  payload = _draft_frontmatter_payload(markdown)
  return _draft_frontmatter_value(
    payload,
    ("gaoxia_maintenance_kind", "gaoxia suggestion kind", "gaoxia_suggestion_kind", "maintenance_kind"),
  )


def _obsidian_maintenance_action_kind(action: dict[str, object]) -> str:
  return str(
    action.get("kind")
    or action.get("gaoxia_maintenance_kind")
    or action.get("maintenance_kind")
    or ""
  ).strip()


def _obsidian_note_source_ids_from_markdown(markdown: str) -> list[str]:
  payload = _draft_frontmatter_payload(markdown)
  return _draft_frontmatter_values(
    payload,
    ("source_ids", "source_id", "source ids", "source id", "来源ID", "来源编号"),
    limit=12,
  )


def _source_chapter_indexes_from_values(values: object, *, limit: int = 12) -> list[int]:
  indexes: list[int] = []
  candidates = values if isinstance(values, list) else [values]
  for raw in candidates:
    text = str(raw or "").strip().strip("[]")
    if not text:
      continue
    parts = re.split(r"[,，、]+", text) if re.search(r"[,，、]", text) else [text]
    for part in parts:
      for chapter_index in _chapter_numbers_from_value(part):
        if chapter_index > 0 and chapter_index not in indexes:
          indexes.append(chapter_index)
        if len(indexes) >= limit:
          return indexes
  return indexes


def _draft_body_without_frontmatter(markdown: str) -> str:
  lines = str(markdown or "").splitlines()
  if not lines or lines[0].strip() != "---":
    return str(markdown or "")
  for index, raw_line in enumerate(lines[1:], start=1):
    if raw_line.strip() == "---":
      return "\n".join(lines[index + 1 :])
  return ""


def _draft_body_source_chapter_indexes(markdown: str, *, limit: int = 12) -> list[int]:
  label_ids = {_draft_frontmatter_key_id(label) for label in _DRAFT_SOURCE_CHAPTER_LABELS}
  indexes: list[int] = []
  for raw_line in _draft_body_without_frontmatter(markdown).replace("\r\n", "\n").split("\n"):
    line = re.sub(r"^\s*[-*]\s*", "", raw_line.strip())
    if not line:
      continue
    match = re.match(r"^([^:：]{1,40})[:：](.*)$", line)
    if not match:
      continue
    if _draft_frontmatter_key_id(match.group(1)) not in label_ids:
      continue
    value = match.group(2).strip().lstrip(":：").strip()
    for chapter_index in _source_chapter_indexes_from_values(value, limit=limit):
      if chapter_index > 0 and chapter_index not in indexes:
        indexes.append(chapter_index)
      if len(indexes) >= limit:
        return indexes
  return indexes


def _draft_body_section_values(markdown: str, labels: tuple[str, ...], *, limit: int = 4) -> list[str]:
  label_ids = {_normalized_label(label) for label in labels}
  values: list[str] = []
  current_label = False
  for raw_line in _draft_body_without_frontmatter(markdown).replace("\r\n", "\n").split("\n"):
    stripped = raw_line.strip()
    if not stripped:
      continue
    is_heading = bool(re.match(r"^\s{0,3}#{1,6}\s+", raw_line))
    is_list_item = bool(re.match(r"^\s*[-*+]\s+", raw_line))
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", stripped).strip()
    line = re.sub(r"^\s*[-*+]\s*", "", line).strip()
    line = re.sub(r"^\s*\d+[.、）)]\s*", "", line).strip()
    if not line:
      continue

    match = re.match(r"^(.{1,40}?)[：:]\s*(.*)$", line)
    if match and _normalized_label(match.group(1)) in label_ids:
      current_label = True
      value = _compact_text(match.group(2), 180)
      if value:
        values.append(value)
      continue

    if _normalized_label(line) in label_ids and (is_heading or not is_list_item):
      current_label = True
      continue

    if is_heading:
      current_label = False
      continue

    if current_label:
      if match and not is_list_item:
        current_label = False
        continue
      value = _compact_text(line, 180)
      if value:
        values.append(value)
      if len(values) >= limit:
        break
  return _ordered_unique(values)[:limit]


def _obsidian_note_source_chapters_from_markdown(markdown: str) -> list[int]:
  payload = _draft_frontmatter_payload(markdown)
  values = _draft_frontmatter_values(
    payload,
    _DRAFT_SOURCE_CHAPTER_LABELS,
    limit=12,
  )
  indexes: list[int] = []
  for chapter_index in _source_chapter_indexes_from_values(values):
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  for chapter_index in _draft_body_source_chapter_indexes(markdown):
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  return indexes


def _obsidian_note_source_chapters_from_summary(note: object, markdown: str = "") -> list[int]:
  indexes = _source_chapter_indexes_from_values(getattr(note, "source_chapters", []))
  if indexes:
    return indexes
  if markdown:
    return _obsidian_note_source_chapters_from_markdown(markdown)
  return []


def _obsidian_maintenance_identity_from_action(action: dict[str, object]) -> str:
  return str(
    action.get("gaoxia_maintenance_id")
    or action.get("maintenance_id")
    or action.get("suggestion_id")
    or ""
  ).strip()


def _obsidian_maintenance_source_ids_from_action(action: dict[str, object]) -> list[str]:
  source_ids = _string_list(action.get("source_ids"), limit=12)
  if source_ids:
    return source_ids
  suggestion_id = str(action.get("suggestion_id") or "").strip()
  chapter_prefix = "obsidian-maintenance-chapter-"
  if suggestion_id.startswith(chapter_prefix):
    source_id = suggestion_id[len(chapter_prefix):].strip()
    return [source_id] if source_id else []
  return []


def _rebind_moved_published_obsidian_notes(project_dir: Path, state: dict[str, object], *, now: str) -> bool:
  latest_actions = _maintenance_actions_by_suggestion(state)
  candidates = [
    action
    for action in latest_actions.values()
    if isinstance(action, dict)
    and str(action.get("status") or "") == "published"
    and (
      str(action.get("published_content_hash") or action.get("draft_content_hash") or "").strip()
      or _obsidian_maintenance_identity_from_action(action)
      or _obsidian_maintenance_source_ids_from_action(action)
      or (
        _obsidian_maintenance_action_kind(action) == "create_chapter_note"
        and _obsidian_maintenance_source_chapter_indexes(action)
      )
    )
    and _published_obsidian_note_missing(project_dir, action)
  ]
  if not candidates:
    return False

  config = load_obsidian_config(project_dir)
  vault_dir = resolve_obsidian_vault_dir(project_dir, config)
  if vault_dir is None or not vault_dir.exists() or not vault_dir.is_dir():
    return False

  try:
    records, _skipped, _warnings = collect_obsidian_note_records(project_dir)
  except Exception:
    return False

  files_by_hash: dict[str, list[tuple[Path, str, str]]] = {}
  files_by_identity: dict[str, list[tuple[Path, str, str]]] = {}
  files_by_source_id: dict[str, list[tuple[Path, str, str]]] = {}
  files_by_source_chapter: dict[int, list[tuple[Path, str, str]]] = {}
  for record in records:
    relative = str(getattr(record.summary, "relative_path", "") or "").replace("\\", "/").strip()
    if not relative:
      continue
    note_path = vault_dir / relative
    if not note_path.is_file():
      continue
    try:
      text = note_path.read_text(encoding="utf-8")
    except OSError:
      continue
    text_hash = _text_content_hash(text)
    files_by_hash.setdefault(text_hash, []).append((note_path, relative, text_hash))
    identity = _obsidian_maintenance_identity_from_markdown(text)
    if identity:
      files_by_identity.setdefault(identity, []).append((note_path, relative, text_hash))
    for source_id in _string_list(getattr(record.summary, "source_ids", []), limit=30) or _obsidian_note_source_ids_from_markdown(text):
      files_by_source_id.setdefault(source_id, []).append((note_path, relative, text_hash))
    if _chapter_note_type(getattr(record.summary, "note_type", "")) or _chapter_note_path_like(relative):
      for chapter_index in _obsidian_note_source_chapters_from_summary(record.summary, text):
        files_by_source_chapter.setdefault(chapter_index, []).append((note_path, relative, text_hash))

  if not files_by_hash and not files_by_identity and not files_by_source_id and not files_by_source_chapter:
    return False

  actions = [item for item in state.get("obsidian_maintenance_actions", []) if isinstance(item, dict)]
  changed = False
  for action in candidates:
    published_hash = str(action.get("published_content_hash") or action.get("draft_content_hash") or "").strip()
    matches = (files_by_hash.get(published_hash) if published_hash else []) or []
    rebind_match = "content_hash"
    identity = _obsidian_maintenance_identity_from_action(action)
    if len(matches or []) != 1 and identity:
      matches = files_by_identity.get(identity) or []
      rebind_match = "maintenance_id"
    source_ids = _obsidian_maintenance_source_ids_from_action(action)
    if len(matches or []) != 1 and source_ids:
      source_matches: list[tuple[Path, str, str]] = []
      seen_source_matches: set[str] = set()
      for source_id in source_ids:
        for candidate in files_by_source_id.get(source_id) or []:
          if candidate[1] in seen_source_matches:
            continue
          seen_source_matches.add(candidate[1])
          source_matches.append(candidate)
      matches = source_matches
      rebind_match = "source_ids"
    source_chapters = _obsidian_maintenance_source_chapter_indexes(action)
    if (
      len(matches or []) != 1
      and _obsidian_maintenance_action_kind(action) == "create_chapter_note"
      and source_chapters
    ):
      chapter_matches: list[tuple[Path, str, str]] = []
      seen_chapter_matches: set[str] = set()
      for chapter_index in source_chapters:
        for candidate in files_by_source_chapter.get(chapter_index) or []:
          if candidate[1] in seen_chapter_matches:
            continue
          seen_chapter_matches.add(candidate[1])
          chapter_matches.append(candidate)
      matches = chapter_matches
      rebind_match = "source_chapters"
    if len(matches) != 1:
      continue
    moved_path, moved_relative, moved_hash = matches[0]
    previous_relative = str(action.get("vault_relative_path") or action.get("relative_path") or "").replace("\\", "/").strip()
    if moved_relative == previous_relative:
      continue
    action_id = str(action.get("id") or "")
    new_action = dict(action)
    new_action.update({
      "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{action_id}:moved:{moved_relative}:{now}'.encode('utf-8')).hexdigest()[:12]}",
      "created_at": now,
      "vault_path": str(moved_path),
      "vault_relative_path": moved_relative,
      "relative_path": moved_relative,
      "moved_from_vault_path": str(_published_obsidian_note_path(project_dir, action) or action.get("vault_path") or ""),
      "moved_from_vault_relative_path": previous_relative,
      "vault_move_detected_at": now,
      "rebound_from_action_id": action_id,
      "rebound_match": rebind_match,
    })
    if rebind_match != "content_hash":
      new_action["published_content_hash"] = moved_hash
      new_action["draft_content_hash"] = moved_hash
      new_action["published_from_manual_edits"] = True
    actions.append(new_action)
    changed = True

  if changed:
    state["obsidian_maintenance_actions"] = actions[-_MAX_OBSIDIAN_MAINTENANCE_ACTIONS:]
  return changed


def _published_obsidian_note_outdated(
  project_dir: Path | None,
  action: dict[str, object] | None,
  draft_markdown: object,
) -> bool:
  if bool((action or {}).get("published_from_manual_edits")):
    return False
  published_hash = str((action or {}).get("published_content_hash") or (action or {}).get("draft_content_hash") or "")
  if not published_hash:
    return False
  draft_text = str(draft_markdown or "").strip()
  if not draft_text:
    return False
  current_hash = _text_content_hash(draft_text.rstrip() + "\n")
  if current_hash == published_hash:
    return False
  note_path = _published_obsidian_note_path(project_dir, action)
  if note_path is None or not note_path.is_file():
    return False
  try:
    vault_text = note_path.read_text(encoding="utf-8")
  except OSError:
    return False
  return _text_content_hash(vault_text) == published_hash


def _action_draft_has_manual_edits(project_dir: Path | None, action: dict[str, object] | None) -> bool:
  if project_dir is None or not action:
    return False
  expected_hash = str(action.get("draft_content_hash") or "")
  if not expected_hash:
    return False
  draft_path = _safe_staged_obsidian_draft_path(project_dir, action)
  if draft_path is None:
    return False
  try:
    draft_text = draft_path.read_text(encoding="utf-8")
  except OSError:
    return False
  return _text_content_hash(draft_text) != expected_hash


def _write_obsidian_draft_preserving_manual_edits(
  state: dict[str, object],
  target_path: Path,
  relative_path: Path,
  draft_text: str,
) -> tuple[str, bool]:
  if not target_path.exists():
    atomic_write_text(target_path, draft_text)
    return draft_text, False

  try:
    existing_text = target_path.read_text(encoding="utf-8")
  except OSError:
    return "", True
  if existing_text == draft_text:
    return existing_text, False

  previous_path_action = _latest_obsidian_maintenance_action_for_relative_path(state, relative_path.as_posix())
  previous_hash = str((previous_path_action or {}).get("draft_content_hash") or "")
  previous_status = str((previous_path_action or {}).get("status") or "")
  can_update_generated_draft = (
    previous_path_action is not None
    and (
      bool(previous_path_action.get("auto_staged"))
      and previous_status == "staged"
      or previous_status == "published"
    )
    and previous_hash
    and previous_hash == _text_content_hash(existing_text)
  )
  if can_update_generated_draft:
    atomic_write_text(target_path, draft_text)
    return draft_text, False
  return existing_text, True


def _same_path(left: Path, right: Path) -> bool:
  try:
    return left.resolve() == right.resolve()
  except OSError:
    return False


def _obsidian_update_review_relative_path(relative_path: Path) -> Path:
  parts = [str(part or "").strip() for part in relative_path.parts if str(part or "").strip()]
  if not parts:
    return Path("_updates") / "obsidian-update-review.md"
  filename = parts[-1]
  stem = filename[:-3] if filename.lower().endswith(".md") else filename
  parts[-1] = f"{stem}-vault-update.md"
  return Path("_updates", *parts)


def _obsidian_update_review_markdown(
  suggestion: dict[str, object],
  vault_relative_path: Path,
  suggested_relative_path: Path,
  vault_text: str,
  draft_text: str,
  now: str,
) -> str:
  title = _compact_text(suggestion.get("title") or suggested_relative_path.stem, 90)
  lines = [
    "---",
    "type: obsidian_update_review",
    f"target_note: {vault_relative_path.as_posix()}",
    f"suggested_note: {suggested_relative_path.as_posix()}",
    "status: pending_review",
    f"generated_at: {now}",
    "---",
    "",
    f"# Vault 待更新：{title}",
    "",
    f"正式 Vault 笔记：`{vault_relative_path.as_posix()}`",
  ]
  if vault_relative_path.as_posix() != suggested_relative_path.as_posix():
    lines.append(f"系统建议路径：`{suggested_relative_path.as_posix()}`")
  lines.extend(
    [
      "处理建议：确认差异后，把需要保留的内容人工合并到 Vault 正式笔记；这份文件只作为对照草稿。",
      "",
      "## Vault 当前内容",
      "",
      "```markdown",
      vault_text.rstrip(),
      "```",
      "",
      "## 系统新版草稿",
      "",
      "```markdown",
      draft_text.rstrip(),
      "```",
      "",
    ]
  )
  return "\n".join(lines)


def _write_obsidian_update_review_draft(
  project_dir: Path,
  latest_action: dict[str, object] | None,
  suggestion: dict[str, object],
  relative_path: Path,
  draft_text: str,
  now: str,
) -> dict[str, object]:
  if not latest_action or str(latest_action.get("status") or "") != "published":
    return {}
  if not _published_obsidian_note_outdated(project_dir, latest_action, draft_text):
    return {}
  note_path = _published_obsidian_note_path(project_dir, latest_action)
  if note_path is None or not note_path.is_file():
    return {}
  try:
    vault_text = note_path.read_text(encoding="utf-8")
  except OSError:
    return {}

  vault_relative_path = _published_obsidian_note_relative_path(latest_action) or relative_path
  relative_review_path = _obsidian_update_review_relative_path(vault_relative_path)
  target_path = obsidian_draft_dir(project_dir) / relative_review_path
  target_path.parent.mkdir(parents=True, exist_ok=True)
  review_text = _obsidian_update_review_markdown(
    suggestion,
    vault_relative_path,
    relative_path,
    vault_text,
    draft_text,
    now,
  )
  review_hash = _text_content_hash(review_text)
  previous_hash = str((latest_action or {}).get("merge_draft_content_hash") or "")
  existing_text = ""
  if target_path.exists():
    try:
      existing_text = target_path.read_text(encoding="utf-8")
    except OSError:
      return {
        "merge_draft_path": str(target_path),
        "merge_draft_relative_path": relative_review_path.as_posix(),
        "merge_draft_manual_edits": True,
      }
    if existing_text != review_text and previous_hash and _text_content_hash(existing_text) != previous_hash:
      return {
        "merge_draft_path": str(target_path),
        "merge_draft_relative_path": relative_review_path.as_posix(),
        "merge_draft_content_hash": _text_content_hash(existing_text),
        "merge_draft_manual_edits": True,
      }
  if existing_text != review_text:
    atomic_write_text(target_path, review_text)
  return {
    "merge_draft_path": str(target_path),
    "merge_draft_relative_path": relative_review_path.as_posix(),
    "merge_draft_content_hash": review_hash,
    "merge_draft_manual_edits": False,
  }


def _remove_generated_obsidian_draft(
  project_dir: Path,
  action: dict[str, object] | None,
  current_path: Path,
) -> bool:
  if not action or not bool(action.get("auto_staged")) or str(action.get("status") or "") != "staged":
    return False
  previous_path = _safe_staged_obsidian_draft_path(project_dir, action)
  if previous_path is None or _same_path(previous_path, current_path):
    return False
  previous_hash = str(action.get("draft_content_hash") or "")
  if not previous_hash:
    return False
  try:
    previous_text = previous_path.read_text(encoding="utf-8")
  except OSError:
    return False
  if _text_content_hash(previous_text) != previous_hash:
    return False
  try:
    previous_path.unlink()
  except OSError:
    return False
  return True


def _auto_stage_obsidian_maintenance_drafts(
  project_dir: Path,
  project_detail: object,
  state: dict[str, object],
  *,
  now: str,
) -> dict[str, object]:
  suggestions = _obsidian_maintenance_suggestions(project_detail, state, project_dir)
  actions = [item for item in state.get("obsidian_maintenance_actions", []) if isinstance(item, dict)]
  staged_count = 0
  for suggestion in suggestions:
    if staged_count >= _MAX_OBSIDIAN_AUTO_STAGED_DRAFTS:
      break
    suggestion_id = str(suggestion.get("id") or "").strip()
    if not suggestion_id:
      continue
    status = str(suggestion.get("status") or "open")
    inherited_staged_draft = status == "staged" and bool(suggestion.get("status_inherited_from_path"))
    refresh_auto_staged_draft = (
      status == "staged"
      and bool(suggestion.get("auto_staged"))
      and not bool(suggestion.get("manual_draft_edits"))
    )
    if status != "open" and not inherited_staged_draft and not refresh_auto_staged_draft:
      continue
    if str(suggestion.get("priority") or "low") not in _OBSIDIAN_AUTO_STAGE_PRIORITIES:
      continue
    draft_markdown = str(suggestion.get("draft_markdown") or "").strip()
    if not draft_markdown:
      continue
    latest_action = _latest_obsidian_maintenance_action(state, suggestion_id)
    if latest_action and str(latest_action.get("status") or "") == "published":
      continue

    relative_path = _safe_obsidian_draft_relative_path(
      suggestion.get("suggested_path"),
      _safe_obsidian_filename(suggestion.get("title"), "obsidian-draft"),
    )
    target_path = obsidian_draft_dir(project_dir) / relative_path
    draft_text = draft_markdown.rstrip() + "\n"
    existing_staged_path = _safe_staged_obsidian_draft_path(project_dir, latest_action)
    existing_staged_is_target = (
      existing_staged_path is not None and _same_path(existing_staged_path, target_path)
    )
    if existing_staged_path is not None:
      if not bool((latest_action or {}).get("auto_staged")):
        continue
      try:
        if (
          existing_staged_is_target
          and _text_content_hash(existing_staged_path.read_text(encoding="utf-8")) == _text_content_hash(draft_text)
        ):
          continue
      except OSError:
        pass
    written_text, preserved_existing = _write_obsidian_draft_preserving_manual_edits(
      state,
      target_path,
      relative_path,
      draft_text,
    )
    if preserved_existing:
      continue

    previous_draft_path = ""
    if existing_staged_path is not None and not existing_staged_is_target:
      if _remove_generated_obsidian_draft(project_dir, latest_action, target_path):
        previous_draft_path = str(existing_staged_path)

    action_id = hashlib.sha1(f"{suggestion_id}:auto-staged:{now}".encode("utf-8")).hexdigest()[:12]
    action = {
      "id": f"obsidian-maintenance-action-{action_id}",
      "suggestion_id": suggestion_id,
      "gaoxia_maintenance_id": _obsidian_maintenance_identity_from_markdown(written_text) or suggestion_id,
      "gaoxia_maintenance_kind": _obsidian_maintenance_kind_from_markdown(written_text) or str(suggestion.get("kind") or ""),
      "status": "staged",
      "created_at": now,
      "title": str(suggestion.get("title") or ""),
      "draft_path": str(target_path),
      "relative_path": relative_path.as_posix(),
      "draft_content_hash": _text_content_hash(written_text),
      "auto_staged": True,
    }
    if previous_draft_path:
      action["previous_draft_path"] = previous_draft_path
    actions.append(action)
    staged_count += 1

  if staged_count:
    state["obsidian_maintenance_actions"] = actions[-_MAX_OBSIDIAN_MAINTENANCE_ACTIONS:]
  _set_obsidian_maintenance_suggestions(
    state,
    _obsidian_maintenance_suggestions(project_detail, state, project_dir),
  )
  return state


def _append_obsidian_maintenance_action(
  project_dir: Path,
  project_detail: object,
  state: dict[str, object],
  action: dict[str, object],
) -> dict[str, object]:
  actions = [item for item in state.get("obsidian_maintenance_actions", []) if isinstance(item, dict)]
  actions.append(action)
  state["obsidian_maintenance_actions"] = actions[-_MAX_OBSIDIAN_MAINTENANCE_ACTIONS:]
  _set_obsidian_maintenance_suggestions(
    state,
    _obsidian_maintenance_suggestions(project_detail, state, project_dir),
  )
  state["updated_at"] = str(action.get("created_at") or _now_iso())
  state["revision"] = int(state.get("revision") or 0) + 1
  atomic_write_json(narrative_state_path(project_dir), state)
  return state


def stage_project_obsidian_maintenance_suggestion(
  project_dir: Path,
  project_detail: object,
  suggestion_id: str,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir)
  if suggestion is None:
    raise FileNotFoundError("Obsidian 维护建议不存在")

  now = _now_iso()
  action, result = _stage_obsidian_maintenance_draft_action(
    project_dir,
    state,
    suggestion,
    suggestion_id,
    now,
  )
  state = load_project_narrative_state(project_dir)
  state = _append_obsidian_maintenance_action(project_dir, project_detail, state, action)

  staged_suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir) or suggestion
  result["suggestion"] = staged_suggestion
  return result


def _stage_obsidian_maintenance_draft_action(
  project_dir: Path,
  state: dict[str, object],
  suggestion: dict[str, object],
  suggestion_id: str,
  now: str,
) -> tuple[dict[str, object], dict[str, object]]:
  draft_markdown = str(suggestion.get("draft_markdown") or "").strip()
  if not draft_markdown:
    raise ValueError("这条 Obsidian 维护建议没有可保存的笔记草稿")

  relative_path = _safe_obsidian_draft_relative_path(
    suggestion.get("suggested_path"),
    _safe_obsidian_filename(suggestion.get("title"), "obsidian-draft"),
  )
  target_path = obsidian_draft_dir(project_dir) / relative_path
  draft_text = draft_markdown.rstrip() + "\n"
  latest_action = _latest_obsidian_maintenance_action_for_suggestion(state, suggestion)
  written_text, preserved_existing = _write_obsidian_draft_preserving_manual_edits(
    state,
    target_path,
    relative_path,
    draft_text,
  )
  if not written_text:
    raise ValueError("Obsidian 维护草稿保存失败")
  merge_draft = _write_obsidian_update_review_draft(
    project_dir,
    latest_action,
    suggestion,
    relative_path,
    draft_text,
    now,
  )

  action = {
    "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:{now}'.encode('utf-8')).hexdigest()[:12]}",
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "gaoxia_maintenance_id": _obsidian_maintenance_identity_from_markdown(written_text) or str(suggestion.get("id") or suggestion_id),
    "gaoxia_maintenance_kind": _obsidian_maintenance_kind_from_markdown(written_text) or str(suggestion.get("kind") or ""),
    "status": "staged",
    "created_at": now,
    "title": str(suggestion.get("title") or ""),
    "draft_path": str(target_path),
    "relative_path": relative_path.as_posix(),
    "draft_content_hash": _text_content_hash(written_text),
    "preserved_existing_draft": preserved_existing,
    "source_ids": _string_list(suggestion.get("source_ids"), limit=12),
    "source_chapters": _obsidian_maintenance_source_chapter_indexes(suggestion),
  }
  if latest_action and str(latest_action.get("status") or "") == "published":
    action["vault_path"] = str(latest_action.get("vault_path") or "")
    action["vault_relative_path"] = str(latest_action.get("vault_relative_path") or latest_action.get("relative_path") or "")
  action.update(merge_draft)
  result = {
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "staged",
    "draft_path": str(target_path),
    "relative_path": relative_path.as_posix(),
    "preserved_existing_draft": preserved_existing,
  }
  if latest_action and str(latest_action.get("status") or "") == "published":
    result["vault_path"] = str(latest_action.get("vault_path") or "")
    result["vault_relative_path"] = str(latest_action.get("vault_relative_path") or latest_action.get("relative_path") or "")
  result.update({
    key: value
    for key, value in merge_draft.items()
    if key in {"merge_draft_path", "merge_draft_relative_path", "merge_draft_manual_edits"}
  })
  return action, result


def stage_project_obsidian_maintenance_suggestions(
  project_dir: Path,
  project_detail: object,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestions = _obsidian_maintenance_suggestions(project_detail, state, project_dir)
  wanted_ids = {str(item or "").strip() for item in (suggestion_ids or []) if str(item or "").strip()}
  matched_ids: set[str] = set()
  actions = [item for item in state.get("obsidian_maintenance_actions", []) if isinstance(item, dict)]
  staged: list[dict[str, object]] = []
  skipped: list[dict[str, object]] = []
  now = _now_iso()
  max_items = max(1, min(int(limit or 80), _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS))

  for suggestion in suggestions:
    suggestion_id = str(suggestion.get("id") or "").strip()
    if not suggestion_id:
      continue
    if wanted_ids and suggestion_id not in wanted_ids:
      continue
    matched_ids.add(suggestion_id)
    if len(staged) >= max_items:
      skipped.append({"suggestion_id": suggestion_id, "reason": "已达到本次批量保存数量上限"})
      continue
    status = _obsidian_maintenance_item_status(suggestion)
    if status in {"published", "ignored"}:
      skipped.append({"suggestion_id": suggestion_id, "reason": f"当前状态为 {status}"})
      continue
    if status == "staged" and not (
      suggestion.get("draft_missing")
      or suggestion.get("published_missing")
      or suggestion.get("published_outdated")
    ):
      skipped.append({"suggestion_id": suggestion_id, "reason": "草稿已经保存"})
      continue
    if not str(suggestion.get("draft_markdown") or "").strip():
      skipped.append({"suggestion_id": suggestion_id, "reason": "没有可保存的笔记草稿"})
      continue
    try:
      action, result = _stage_obsidian_maintenance_draft_action(
        project_dir,
        state,
        suggestion,
        suggestion_id,
        now,
      )
    except ValueError as error:
      skipped.append({"suggestion_id": suggestion_id, "reason": str(error)})
      continue
    actions.append(action)
    staged.append(result)

  for suggestion_id in sorted(wanted_ids - matched_ids):
    skipped.append({"suggestion_id": suggestion_id, "reason": "维护建议不存在"})

  if staged:
    state["obsidian_maintenance_actions"] = actions[-_MAX_OBSIDIAN_MAINTENANCE_ACTIONS:]
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )
    state["updated_at"] = now
    state["revision"] = int(state.get("revision") or 0) + 1
    atomic_write_json(narrative_state_path(project_dir), state)
  else:
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )

  return {
    "status": "staged",
    "staged_count": len(staged),
    "skipped_count": len(skipped),
    "merge_draft_count": sum(1 for item in staged if str(item.get("merge_draft_path") or "").strip()),
    "staged": staged,
    "skipped": skipped,
    "summary": state.get("obsidian_maintenance_summary") or {},
  }


def confirm_project_obsidian_maintenance_merge_suggestion(
  project_dir: Path,
  project_detail: object,
  suggestion_id: str,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir)
  latest_action = (
    _latest_obsidian_maintenance_action_for_suggestion(state, suggestion)
    if suggestion is not None
    else _latest_obsidian_maintenance_action(state, suggestion_id)
  )
  if not latest_action or not str(latest_action.get("merge_draft_path") or "").strip():
    if suggestion is None:
      raise FileNotFoundError("Obsidian 维护建议不存在")
    raise ValueError("这条维护建议没有 Vault 合并草稿")
  if suggestion is None:
    suggestion = {
      "id": suggestion_id,
      "title": str(latest_action.get("title") or ""),
      "suggested_path": str(latest_action.get("relative_path") or latest_action.get("vault_relative_path") or ""),
      "draft_markdown": "",
    }
  published_action = _latest_published_obsidian_maintenance_action_for_suggestion(state, suggestion)
  if not published_action:
    raise ValueError("没有找到对应的已发布 Vault 笔记记录")

  vault_path = _published_obsidian_note_path(project_dir, published_action)
  if vault_path is None or not vault_path.is_file():
    raise ValueError("对应的 Vault 正式笔记不存在")
  try:
    vault_text = vault_path.read_text(encoding="utf-8")
  except OSError as error:
    raise ValueError("无法读取对应的 Vault 正式笔记") from error

  published_hash = str(published_action.get("published_content_hash") or published_action.get("draft_content_hash") or "")
  vault_hash = _text_content_hash(vault_text)
  if published_hash and vault_hash == published_hash:
    raise ValueError("Vault 正文仍是旧版本，请先在 Obsidian 完成合并")

  staged_path = _safe_staged_obsidian_draft_path(project_dir, latest_action)
  if staged_path is not None:
    try:
      draft_markdown = staged_path.read_text(encoding="utf-8").strip()
    except OSError:
      draft_markdown = ""
  else:
    draft_markdown = str(suggestion.get("draft_markdown") or "").strip()
  draft_hash = _text_content_hash(draft_markdown.rstrip() + "\n") if draft_markdown else ""
  vault_relative_path = _published_obsidian_note_relative_path(published_action)
  relative_path = vault_relative_path or _safe_obsidian_draft_relative_path(
    suggestion.get("suggested_path") or latest_action.get("relative_path"),
    _safe_obsidian_filename(suggestion.get("title"), "obsidian-note"),
  )

  now = _now_iso()
  action = {
    "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:merge-confirmed:{now}'.encode('utf-8')).hexdigest()[:12]}",
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "gaoxia_maintenance_id": (
      _obsidian_maintenance_identity_from_markdown(vault_text)
      or str(published_action.get("gaoxia_maintenance_id") or "")
      or str(suggestion.get("id") or suggestion_id)
    ),
    "gaoxia_maintenance_kind": (
      _obsidian_maintenance_kind_from_markdown(vault_text)
      or str(published_action.get("gaoxia_maintenance_kind") or "")
      or str(suggestion.get("kind") or "")
    ),
    "status": "published",
    "created_at": now,
    "published_at": now,
    "title": str(suggestion.get("title") or ""),
    "draft_path": str(staged_path or latest_action.get("draft_path") or ""),
    "relative_path": relative_path.as_posix(),
    "vault_path": str(vault_path),
    "vault_relative_path": relative_path.as_posix(),
    "draft_content_hash": draft_hash or vault_hash,
    "published_content_hash": vault_hash,
    "published_from_manual_edits": bool(draft_hash and vault_hash != draft_hash),
    "merge_confirmed": True,
    "resolved_merge_draft_path": str(latest_action.get("merge_draft_path") or ""),
    "resolved_merge_draft_relative_path": str(latest_action.get("merge_draft_relative_path") or ""),
  }
  state = _append_obsidian_maintenance_action(project_dir, project_detail, state, action)
  confirmed_suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir) or suggestion
  return {
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "published",
    "vault_path": str(vault_path),
    "vault_relative_path": relative_path.as_posix(),
    "published_from_manual_edits": action["published_from_manual_edits"],
    "suggestion": confirmed_suggestion,
  }


def confirm_project_obsidian_maintenance_merge_suggestions(
  project_dir: Path,
  project_detail: object,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestions = _obsidian_maintenance_suggestions(project_detail, state, project_dir)
  wanted_ids = [str(item or "").strip() for item in (suggestion_ids or []) if str(item or "").strip()]
  wanted_set = set(wanted_ids)
  matched_ids: set[str] = set()
  candidates: list[str] = []
  confirmed: list[dict[str, object]] = []
  skipped: list[dict[str, object]] = []
  max_items = max(1, min(int(limit or 80), _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS))

  if wanted_ids:
    candidates = wanted_ids
  else:
    for suggestion in suggestions:
      suggestion_id = str(suggestion.get("id") or "").strip()
      if not suggestion_id:
        continue
      if str(suggestion.get("merge_draft_path") or "").strip():
        candidates.append(suggestion_id)

  for suggestion_id in candidates:
    if not suggestion_id:
      continue
    matched_ids.add(suggestion_id)
    if len(confirmed) >= max_items:
      skipped.append({"suggestion_id": suggestion_id, "reason": "已达到本次批量确认数量上限"})
      continue
    try:
      result = confirm_project_obsidian_maintenance_merge_suggestion(project_dir, project_detail, suggestion_id)
    except FileNotFoundError:
      skipped.append({"suggestion_id": suggestion_id, "reason": "维护建议不存在"})
      continue
    except ValueError as error:
      skipped.append({"suggestion_id": suggestion_id, "reason": str(error)})
      continue
    confirmed.append(result)

  for suggestion_id in sorted(wanted_set - matched_ids):
    skipped.append({"suggestion_id": suggestion_id, "reason": "维护建议不存在"})

  state = load_project_narrative_state(project_dir)
  return {
    "status": "published",
    "confirmed_count": len(confirmed),
    "skipped_count": len(skipped),
    "confirmed": confirmed,
    "skipped": skipped,
    "summary": state.get("obsidian_maintenance_summary") or {},
  }


def ignore_project_obsidian_maintenance_suggestion(
  project_dir: Path,
  project_detail: object,
  suggestion_id: str,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir)
  if suggestion is None:
    raise FileNotFoundError("Obsidian 维护建议不存在")

  relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
  now = _now_iso()
  action = {
    "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:ignored:{now}'.encode('utf-8')).hexdigest()[:12]}",
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "ignored",
    "created_at": now,
    "title": str(suggestion.get("title") or ""),
    "relative_path": relative_path,
    "suggested_path": str(suggestion.get("suggested_path") or ""),
  }
  state = _append_obsidian_maintenance_action(project_dir, project_detail, state, action)
  ignored_suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir) or suggestion
  return {
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "ignored",
    "relative_path": relative_path,
    "suggestion": ignored_suggestion,
  }


def ignore_project_obsidian_maintenance_suggestions(
  project_dir: Path,
  project_detail: object,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestions = _obsidian_maintenance_suggestions(project_detail, state, project_dir)
  wanted_ids = {str(item or "").strip() for item in (suggestion_ids or []) if str(item or "").strip()}
  matched_ids: set[str] = set()
  actions = [item for item in state.get("obsidian_maintenance_actions", []) if isinstance(item, dict)]
  ignored: list[dict[str, object]] = []
  skipped: list[dict[str, object]] = []
  now = _now_iso()
  max_items = max(1, min(int(limit or 80), _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS))

  for suggestion in suggestions:
    suggestion_id = str(suggestion.get("id") or "").strip()
    if not suggestion_id:
      continue
    if wanted_ids and suggestion_id not in wanted_ids:
      continue
    matched_ids.add(suggestion_id)
    if len(ignored) >= max_items:
      skipped.append({"suggestion_id": suggestion_id, "reason": "已达到本次批量忽略数量上限"})
      continue
    status = _obsidian_maintenance_item_status(suggestion)
    if status == "published":
      skipped.append({"suggestion_id": suggestion_id, "reason": "已发布笔记不能批量忽略"})
      continue
    if status == "ignored":
      skipped.append({"suggestion_id": suggestion_id, "reason": "已经忽略"})
      continue

    relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
    action = {
      "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:ignored:{now}'.encode('utf-8')).hexdigest()[:12]}",
      "suggestion_id": str(suggestion.get("id") or suggestion_id),
      "status": "ignored",
      "created_at": now,
      "title": str(suggestion.get("title") or ""),
      "relative_path": relative_path,
      "suggested_path": str(suggestion.get("suggested_path") or ""),
      "batch_ignored": True,
    }
    actions.append(action)
    ignored.append({
      "suggestion_id": str(suggestion.get("id") or suggestion_id),
      "status": "ignored",
      "relative_path": relative_path,
    })

  for suggestion_id in sorted(wanted_ids - matched_ids):
    skipped.append({"suggestion_id": suggestion_id, "reason": "维护建议不存在"})

  if ignored:
    state["obsidian_maintenance_actions"] = actions[-_MAX_OBSIDIAN_MAINTENANCE_ACTIONS:]
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )
    state["updated_at"] = now
    state["revision"] = int(state.get("revision") or 0) + 1
    atomic_write_json(narrative_state_path(project_dir), state)
  else:
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )

  return {
    "status": "ignored",
    "ignored_count": len(ignored),
    "skipped_count": len(skipped),
    "ignored": ignored,
    "skipped": skipped,
    "summary": state.get("obsidian_maintenance_summary") or {},
  }


def reopen_project_obsidian_maintenance_suggestion(
  project_dir: Path,
  project_detail: object,
  suggestion_id: str,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir)
  if suggestion is None:
    raise FileNotFoundError("Obsidian 维护建议不存在")
  if _obsidian_maintenance_item_status(suggestion) != "ignored":
    raise ValueError("只能恢复已忽略的 Obsidian 维护建议")

  relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
  now = _now_iso()
  action = {
    "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:open:{now}'.encode('utf-8')).hexdigest()[:12]}",
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "open",
    "created_at": now,
    "title": str(suggestion.get("title") or ""),
    "relative_path": relative_path,
    "suggested_path": str(suggestion.get("suggested_path") or ""),
    "reopened_from_status": "ignored",
  }
  state = _append_obsidian_maintenance_action(project_dir, project_detail, state, action)
  reopened_suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir) or suggestion
  return {
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "open",
    "relative_path": relative_path,
    "suggestion": reopened_suggestion,
  }


def reopen_project_obsidian_maintenance_suggestions(
  project_dir: Path,
  project_detail: object,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestions = _obsidian_maintenance_suggestions(project_detail, state, project_dir)
  wanted_ids = {str(item or "").strip() for item in (suggestion_ids or []) if str(item or "").strip()}
  matched_ids: set[str] = set()
  actions = [item for item in state.get("obsidian_maintenance_actions", []) if isinstance(item, dict)]
  reopened: list[dict[str, object]] = []
  skipped: list[dict[str, object]] = []
  now = _now_iso()
  max_items = max(1, min(int(limit or 80), _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS))

  for suggestion in suggestions:
    suggestion_id = str(suggestion.get("id") or "").strip()
    if not suggestion_id:
      continue
    if wanted_ids and suggestion_id not in wanted_ids:
      continue
    matched_ids.add(suggestion_id)
    if len(reopened) >= max_items:
      skipped.append({"suggestion_id": suggestion_id, "reason": "已达到本次批量恢复数量上限"})
      continue
    status = _obsidian_maintenance_item_status(suggestion)
    if status != "ignored":
      skipped.append({"suggestion_id": suggestion_id, "reason": f"当前状态为 {status}"})
      continue

    relative_path = _obsidian_maintenance_suggestion_relative_path(suggestion)
    action = {
      "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:open:{now}'.encode('utf-8')).hexdigest()[:12]}",
      "suggestion_id": str(suggestion.get("id") or suggestion_id),
      "status": "open",
      "created_at": now,
      "title": str(suggestion.get("title") or ""),
      "relative_path": relative_path,
      "suggested_path": str(suggestion.get("suggested_path") or ""),
      "reopened_from_status": "ignored",
      "batch_reopened": True,
    }
    actions.append(action)
    reopened.append({
      "suggestion_id": str(suggestion.get("id") or suggestion_id),
      "status": "open",
      "relative_path": relative_path,
    })

  for suggestion_id in sorted(wanted_ids - matched_ids):
    skipped.append({"suggestion_id": suggestion_id, "reason": "维护建议不存在"})

  if reopened:
    state["obsidian_maintenance_actions"] = actions[-_MAX_OBSIDIAN_MAINTENANCE_ACTIONS:]
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )
    state["updated_at"] = now
    state["revision"] = int(state.get("revision") or 0) + 1
    atomic_write_json(narrative_state_path(project_dir), state)
  else:
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )

  return {
    "status": "open",
    "reopened_count": len(reopened),
    "skipped_count": len(skipped),
    "reopened": reopened,
    "skipped": skipped,
    "summary": state.get("obsidian_maintenance_summary") or {},
  }


def publish_project_obsidian_maintenance_suggestion(
  project_dir: Path,
  project_detail: object,
  suggestion_id: str,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir)
  if suggestion is None:
    raise FileNotFoundError("Obsidian 维护建议不存在")

  latest_action = _latest_obsidian_maintenance_action_for_suggestion(state, suggestion)
  staged_path = _safe_staged_obsidian_draft_path(project_dir, latest_action)
  if staged_path is not None:
    draft_markdown = staged_path.read_text(encoding="utf-8").strip()
  else:
    draft_markdown = str(suggestion.get("draft_markdown") or "").strip()
  if not draft_markdown:
    raise ValueError("这条 Obsidian 维护建议没有可发布的笔记草稿")
  published_text = _ensure_obsidian_maintenance_identity_markdown(
    draft_markdown,
    str(suggestion.get("id") or suggestion_id),
    str(suggestion.get("kind") or ""),
  ).rstrip() + "\n"
  published_content_hash = _text_content_hash(published_text)
  published_from_manual_edits = bool((latest_action or {}).get("preserved_existing_draft")) or _action_draft_has_manual_edits(
    project_dir,
    latest_action,
  )

  config = load_obsidian_config(project_dir)
  if not config.enabled:
    raise ValueError("Obsidian 未启用，不能发布维护笔记")
  vault_dir = resolve_obsidian_vault_dir(project_dir, config)
  if vault_dir is None:
    raise ValueError("Obsidian Vault 路径为空")
  if not vault_dir.exists() or not vault_dir.is_dir():
    raise ValueError(f"Obsidian Vault 不存在：{vault_dir}")

  relative_path = _safe_obsidian_draft_relative_path(
    suggestion.get("suggested_path") or (latest_action or {}).get("relative_path"),
    _safe_obsidian_filename(suggestion.get("title"), "obsidian-note"),
  )
  target_path = vault_dir / relative_path
  try:
    target_path.resolve().relative_to(vault_dir.resolve())
  except ValueError:
    raise ValueError("Obsidian 维护笔记目标路径不在 Vault 内") from None
  if target_path.exists():
    raise ValueError(f"Obsidian 维护笔记已存在：{relative_path.as_posix()}")

  atomic_write_text(target_path, published_text)

  now = _now_iso()
  state = load_project_narrative_state(project_dir)
  action = {
    "id": f"obsidian-maintenance-action-{hashlib.sha1(f'{suggestion_id}:published:{now}'.encode('utf-8')).hexdigest()[:12]}",
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "gaoxia_maintenance_id": _obsidian_maintenance_identity_from_markdown(published_text) or str(suggestion.get("id") or suggestion_id),
    "gaoxia_maintenance_kind": _obsidian_maintenance_kind_from_markdown(published_text) or str(suggestion.get("kind") or ""),
    "status": "published",
    "created_at": now,
    "published_at": now,
    "title": str(suggestion.get("title") or ""),
    "draft_path": str(staged_path or ""),
    "relative_path": relative_path.as_posix(),
    "vault_path": str(target_path),
    "vault_relative_path": relative_path.as_posix(),
    "draft_content_hash": published_content_hash,
    "published_content_hash": published_content_hash,
    "published_from_manual_edits": published_from_manual_edits,
    "source_ids": _string_list(suggestion.get("source_ids"), limit=12),
    "source_chapters": _obsidian_maintenance_source_chapter_indexes(suggestion),
  }
  state = _append_obsidian_maintenance_action(project_dir, project_detail, state, action)

  published_suggestion = _find_obsidian_maintenance_suggestion(project_detail, state, suggestion_id, project_dir) or suggestion
  return {
    "suggestion_id": str(suggestion.get("id") or suggestion_id),
    "status": "published",
    "draft_path": str(staged_path or ""),
    "vault_path": str(target_path),
    "vault_relative_path": relative_path.as_posix(),
    "relative_path": relative_path.as_posix(),
    "suggestion": published_suggestion,
  }


def publish_project_obsidian_maintenance_suggestions(
  project_dir: Path,
  project_detail: object,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  state = refresh_project_narrative_state_chapter_cards(project_dir, project_detail, persist=True)
  suggestions = _obsidian_maintenance_suggestions(project_detail, state, project_dir)
  wanted_ids = {str(item or "").strip() for item in (suggestion_ids or []) if str(item or "").strip()}
  matched_ids: set[str] = set()
  published: list[dict[str, object]] = []
  skipped: list[dict[str, object]] = []
  max_items = max(1, min(int(limit or 80), _MAX_OBSIDIAN_MAINTENANCE_SUGGESTIONS))

  for suggestion in suggestions:
    suggestion_id = str(suggestion.get("id") or "").strip()
    if not suggestion_id:
      continue
    if wanted_ids and suggestion_id not in wanted_ids:
      continue
    matched_ids.add(suggestion_id)
    if len(published) >= max_items:
      skipped.append({"suggestion_id": suggestion_id, "reason": "已达到本次批量发布数量上限"})
      continue
    status = _obsidian_maintenance_item_status(suggestion)
    if status in {"published", "ignored"}:
      skipped.append({"suggestion_id": suggestion_id, "reason": f"当前状态为 {status}"})
      continue
    if status == "published_outdated":
      skipped.append({"suggestion_id": suggestion_id, "reason": "Vault 笔记待更新，需要人工合并"})
      continue
    if status not in {"staged", "published_missing"}:
      skipped.append({"suggestion_id": suggestion_id, "reason": "尚未保存项目草稿"})
      continue
    latest_action = _latest_obsidian_maintenance_action_for_suggestion(state, suggestion)
    if _safe_staged_obsidian_draft_path(project_dir, latest_action) is None:
      skipped.append({"suggestion_id": suggestion_id, "reason": "项目草稿文件不存在"})
      continue
    try:
      result = publish_project_obsidian_maintenance_suggestion(project_dir, project_detail, suggestion_id)
    except (FileNotFoundError, ValueError) as error:
      skipped.append({"suggestion_id": suggestion_id, "reason": str(error)})
      state = load_project_narrative_state(project_dir)
      continue
    published.append(result)
    state = load_project_narrative_state(project_dir)

  for suggestion_id in sorted(wanted_ids - matched_ids):
    skipped.append({"suggestion_id": suggestion_id, "reason": "维护建议不存在"})

  state = load_project_narrative_state(project_dir)
  return {
    "status": "published",
    "published_count": len(published),
    "skipped_count": len(skipped),
    "published": published,
    "skipped": skipped,
    "summary": state.get("obsidian_maintenance_summary") or {},
  }


def _character_source_texts(project_detail: object, character_name: str) -> list[str]:
  docs = _documents_map(project_detail)
  texts: list[str] = []
  for key in ("character_design", "character_state", "global_summary", "blueprint"):
    for line in docs.get(key, "").splitlines():
      if character_name in line:
        texts.append(_compact_text(line, 180))
  return texts


def _arc_phase(chapter_index: int, total_chapters: int) -> str:
  position = _chapter_position(chapter_index, total_chapters)
  if position <= 0.2:
    return "立场建立"
  if position <= 0.45:
    return "压力升级"
  if position <= 0.65:
    return "选择转向"
  if position <= 0.85:
    return "后果显形"
  return "结局兑现"


def _candidate_character_arcs(project_detail: object, chapter: object | None) -> list[dict[str, object]]:
  names = _known_names(project_detail)
  if not names:
    return []
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  chapter_id = str(getattr(chapter, "id", "") or "") if chapter is not None else ""
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  chapter_text = str(getattr(chapter, "content", "") or "") if chapter is not None else ""
  arcs: list[dict[str, object]] = []
  for name in names[:12]:
    sources = _character_source_texts(project_detail, name)
    appears = name in chapter_text
    if not sources and not appears:
      continue
    evidence = []
    if appears:
      sentence = next((item for item in _split_sentences(chapter_text) if name in item), "")
      evidence.append(_compact_text(sentence or f"{name} 出现在本章。", 160))
    evidence.extend(sources[:3])
    arcs.append(
      {
        "id": f"arc-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}",
        "name": name,
        "phase": _arc_phase(chapter_index, total_chapters),
        "current_state": sources[0] if sources else _compact_text(evidence[0], 140),
        "last_seen_chapter_id": chapter_id if appears else "",
        "last_seen_chapter_index": chapter_index if appears else 0,
        "source_chapter_ids": [chapter_id] if appears and chapter_id else [],
        "evidence": evidence[:6],
        "unresolved_pressure": _character_pressure(name, evidence, chapter_index, total_chapters),
        "required_next_check": _character_next_check(name, appears, chapter_index, total_chapters),
        "confidence": 0.7 if appears else 0.55,
      }
    )
  return arcs


def _character_pressure(name: str, evidence: list[str], chapter_index: int, total_chapters: int) -> str:
  joined = " ".join(evidence)
  if any(token in joined for token in ("背叛", "决裂", "仇", "怀疑")):
    return f"{name} 的关系压力需要在后续行动中体现。"
  if any(token in joined for token in ("秘密", "身份", "真相")):
    return f"{name} 身上的信息压力不能只停留在说明。"
  if _chapter_position(chapter_index, total_chapters) >= 0.7:
    return f"{name} 到了中后段，需要呈现选择造成的后果。"
  return f"{name} 的行动要和当前立场保持一致。"


def _character_next_check(name: str, appears: bool, chapter_index: int, total_chapters: int) -> str:
  if appears:
    return f"检查 {name} 在本章的选择是否延续前文状态。"
  if _chapter_position(chapter_index, total_chapters) >= 0.65:
    return f"如果 {name} 近期缺席，需要确认缺席是否会影响终局。"
  return f"需要时再让 {name} 参与，不要只为解释信息出场。"


def _merge_arc(existing: dict[str, object] | None, candidate: dict[str, object], now: str) -> dict[str, object]:
  if existing is None:
    return {**candidate, "created_at": now, "last_seen_at": now}
  for key in ("phase", "current_state", "unresolved_pressure", "required_next_check"):
    if candidate.get(key):
      existing[key] = candidate[key]
  if candidate.get("last_seen_chapter_index"):
    existing["last_seen_chapter_id"] = candidate.get("last_seen_chapter_id") or ""
    existing["last_seen_chapter_index"] = candidate.get("last_seen_chapter_index") or 0
    existing["last_seen_at"] = now
  existing["confidence"] = round(max(float(existing.get("confidence") or 0), float(candidate.get("confidence") or 0)), 3)
  for key in ("source_chapter_ids", "source_names", "evidence"):
    merged = [str(item) for item in existing.get(key, []) if str(item).strip()]
    for item in candidate.get(key, []) or []:
      value = str(item).strip()
      if value and value not in merged:
        merged.append(value)
    existing[key] = merged[-8:]
  return existing


def _state_with_obsidian_narrative_notes(
  project_detail: object,
  state: dict[str, object],
  chapter: object | None,
) -> dict[str, object]:
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  if not _obsidian_state_enabled(project_detail) or chapter_index <= 0:
    return state
  records = _obsidian_records_for_chapter(project_detail, chapter_index)
  debt_candidates = _obsidian_debt_note_candidates(project_detail, chapter, records=records)
  arc_candidates = _obsidian_arc_note_candidates(project_detail, chapter, records=records)
  if not debt_candidates and not arc_candidates:
    return state

  next_state = dict(state)
  for key in (
    "debts",
    "character_arcs",
    "chapter_cards",
    "model_reviews",
    "chapter_contracts",
    "contract_reviews",
    "obsidian_maintenance_suggestions",
    "obsidian_maintenance_actions",
    "observations",
  ):
    copied: list[object] = []
    for item in state.get(key, []) if isinstance(state.get(key), list) else []:
      copied.append(dict(item) if isinstance(item, dict) else item)
    next_state[key] = copied

  now = _now_iso()
  debts_by_id = {
    str(item.get("id") or ""): item
    for item in next_state.get("debts", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  for candidate in debt_candidates:
    debt_id = str(candidate.get("id") or "")
    debts_by_id[debt_id] = _merge_debt(debts_by_id.get(debt_id), candidate, now)
  next_state["debts"] = _sort_debts(list(debts_by_id.values()))[:_MAX_DEBTS]

  arcs_by_id = {
    str(item.get("id") or ""): item
    for item in next_state.get("character_arcs", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  for candidate in arc_candidates:
    arc_id = str(candidate.get("id") or "")
    arcs_by_id[arc_id] = _merge_arc(arcs_by_id.get(arc_id), candidate, now)
  next_state["character_arcs"] = sorted(
    arcs_by_id.values(),
    key=lambda item: (int(item.get("last_seen_chapter_index") or 0), float(item.get("confidence") or 0)),
    reverse=True,
  )[:_MAX_ARCS]
  return next_state


def _valid_debt_kind(value: object) -> str:
  kind = str(value or "").strip()
  return kind if kind in {"foreshadow", "promise", "relationship", "world_rule"} else "foreshadow"


def _valid_debt_status(value: object) -> str:
  status = str(value or "").strip()
  return status if status in {"open", "touched", "paid", "conflict", "deferred"} else "open"


def _valid_risk(value: object) -> str:
  risk = str(value or "").strip()
  return risk if risk in {"critical", "high", "medium", "low"} else "low"


def _coerce_payoff_range(value: object, chapter_index: int, total_chapters: int, kind: str) -> list[int]:
  if isinstance(value, list) and len(value) >= 2:
    try:
      start = int(value[0])
      end = int(value[1])
      total = max(1, int(total_chapters or 1))
      start = min(total, max(1, start))
      end = min(total, max(start, end))
      return [start, end]
    except (TypeError, ValueError):
      pass
  return _payoff_range(chapter_index or 1, total_chapters, kind)


def _model_debt_candidates(project_detail: object, chapter: object, payload: dict[str, object]) -> list[dict[str, object]]:
  raw_items = payload.get("debt_updates")
  if not isinstance(raw_items, list):
    return []
  chapter_id = str(getattr(chapter, "id", "") or "")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  chapter_title = str(getattr(chapter, "title", "") or "")
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  known_entities = _entity_names(project_detail)
  candidates: list[dict[str, object]] = []
  for raw in raw_items[:16]:
    if not isinstance(raw, dict):
      continue
    evidence = _string_list(raw.get("evidence") or raw.get("evidences"), limit=6)
    content = _compact_text(raw.get("content") or raw.get("summary") or raw.get("detail"), 180)
    title = _compact_text(raw.get("title") or raw.get("name") or "", 48)
    if not evidence or not content:
      continue
    kind = _valid_debt_kind(raw.get("kind"))
    status = _valid_debt_status(raw.get("status"))
    keywords = _anchor_keywords(f"{title} {content} {' '.join(evidence)}", known_entities)
    raw_id = str(raw.get("id") or "").strip()
    debt_id = raw_id if raw_id.startswith("debt-") else _debt_id(kind, keywords, content)
    payoff_range = _coerce_payoff_range(raw.get("expected_payoff_range"), chapter_index, total_chapters, kind)
    candidates.append(
      {
        "id": debt_id,
        "kind": kind,
        "title": title or " / ".join(keywords[:3]) or _compact_text(content, 24),
        "content": content,
        "status": status,
        "first_seen_chapter_id": str(raw.get("first_seen_chapter_id") or chapter_id),
        "first_seen_chapter_index": int(raw.get("first_seen_chapter_index") or chapter_index),
        "last_seen_chapter_id": chapter_id,
        "last_seen_chapter_index": chapter_index,
        "last_seen_chapter_title": chapter_title,
        "source_chapter_ids": [chapter_id] if chapter_id else [],
        "source_names": ["model_editor"],
        "evidence": evidence,
        "expected_payoff_range": payoff_range,
        "next_required_action": _compact_text(raw.get("next_required_action") or "", 140)
        or _next_required_action(status, payoff_range, chapter_index, total_chapters),
        "related_characters": _string_list(raw.get("related_characters"), limit=6),
        "risk_level": _valid_risk(raw.get("risk_level") or raw.get("risk")),
        "confidence": max(0.0, min(1.0, _number(raw.get("confidence"), 0.72))),
      }
    )
  return candidates


def _model_arc_candidates(project_detail: object, chapter: object, payload: dict[str, object]) -> list[dict[str, object]]:
  raw_items = payload.get("character_arc_updates")
  if not isinstance(raw_items, list):
    return []
  chapter_id = str(getattr(chapter, "id", "") or "")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  candidates: list[dict[str, object]] = []
  for raw in raw_items[:12]:
    if not isinstance(raw, dict):
      continue
    name = str(raw.get("name") or raw.get("character") or "").strip()
    evidence = _string_list(raw.get("evidence") or raw.get("evidences"), limit=6)
    if not name or not evidence:
      continue
    phase = _compact_text(raw.get("phase") or _arc_phase(chapter_index, total_chapters), 40)
    candidates.append(
      {
        "id": f"arc-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}",
        "name": name,
        "phase": phase,
        "current_state": _compact_text(raw.get("current_state") or raw.get("state") or evidence[0], 160),
        "last_seen_chapter_id": chapter_id,
        "last_seen_chapter_index": chapter_index,
        "source_chapter_ids": [chapter_id] if chapter_id else [],
        "evidence": evidence,
        "unresolved_pressure": _compact_text(raw.get("unresolved_pressure") or raw.get("pressure") or "", 140)
        or _character_pressure(name, evidence, chapter_index, total_chapters),
        "required_next_check": _compact_text(raw.get("required_next_check") or raw.get("next_check") or "", 140)
        or _character_next_check(name, True, chapter_index, total_chapters),
        "confidence": max(0.0, min(1.0, _number(raw.get("confidence"), 0.72))),
      }
    )
  return candidates


def _chapter_blueprint_line(project_detail: object, chapter_index: int) -> str:
  blueprint = _documents_map(project_detail).get("blueprint", "")
  if not blueprint.strip() or chapter_index <= 0:
    return ""
  patterns = [
    rf"第\s*{chapter_index}\s*章[^\n]*",
    rf"{chapter_index}[\.、\)]\s*[^\n]*",
  ]
  for pattern in patterns:
    match = re.search(pattern, blueprint)
    if match:
      return _compact_text(match.group(0), 220)
  lines = [line.strip() for line in blueprint.splitlines() if line.strip()]
  return _compact_text(lines[min(chapter_index - 1, len(lines) - 1)], 220) if lines and chapter_index <= len(lines) else ""


def _obsidian_scope_text(note: object) -> str:
  parts: list[str] = []
  start = int(getattr(note, "chapter_start", 0) or 0)
  end = int(getattr(note, "chapter_end", 0) or 0)
  reveal_after = int(getattr(note, "reveal_after_chapter", 0) or 0)
  if start and end:
    parts.append(f"适用第 {start}-{end} 章")
  elif start:
    parts.append(f"第 {start} 章起可用")
  elif end:
    parts.append(f"第 {end} 章前可用")
  if reveal_after:
    parts.append(f"第 {reveal_after} 章后可引用")
  return "；".join(parts)


def _obsidian_notes_for_chapter(
  project_detail: object,
  chapter_index: int,
  *,
  query: str = "",
  limit: int = 6,
) -> list[object]:
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  if obsidian is None or not bool(getattr(obsidian, "enabled", False)):
    return []
  notes = list(getattr(obsidian, "notes", []) or [])
  project_path = str(getattr(project_detail, "path", "") or "").strip()
  if project_path and chapter_index > 0:
    try:
      notes = [
        record.summary
        for record in scoped_obsidian_note_records_for_chapter(Path(project_path), chapter_index)
      ]
    except Exception:
      notes = [item for item in notes if obsidian_note_available_for_chapter(item, chapter_index)]
  if not notes:
    return []
  selected = select_obsidian_notes_for_query(notes, query, limit=limit, chapter_index=chapter_index)
  if selected:
    return selected[:limit]
  return [item for item in notes if obsidian_note_available_for_chapter(item, chapter_index)][:limit]


def _obsidian_plan_note_labels(note: object) -> list[str]:
  relative_path = str(getattr(note, "relative_path", "") or "").strip().replace("\\", "/")
  path_parts = [part for part in relative_path.split("/") if part]
  stem = Path(relative_path).stem if relative_path else ""
  return [
    str(getattr(note, "note_type", "") or ""),
    str(getattr(note, "title", "") or ""),
    stem,
    *path_parts,
    *[str(value) for value in list(getattr(note, "tags", []) or [])],
  ]


def _obsidian_note_is_chapter_plan(note: object) -> bool:
  labels = {_normalized_label(label) for label in _obsidian_plan_note_labels(note)}
  return any(label in _OBSIDIAN_CHAPTER_PLAN_LABELS for label in labels)


def _obsidian_note_is_chapter_contract(note: object) -> bool:
  labels = {_normalized_label(label) for label in _obsidian_plan_note_labels(note)}
  return bool(labels.intersection({"chaptercontract", "chaptercontracts", "章节合同"}))


def _obsidian_plan_targets_chapter(note: object, chapter_index: int) -> bool:
  if chapter_index <= 0:
    return False
  try:
    chapter_start = int(getattr(note, "chapter_start", 0) or 0)
  except (TypeError, ValueError):
    chapter_start = 0
  try:
    chapter_end = int(getattr(note, "chapter_end", 0) or 0)
  except (TypeError, ValueError):
    chapter_end = 0
  if chapter_start and chapter_end:
    return chapter_start <= chapter_index <= chapter_end and chapter_end - chapter_start <= 4
  if chapter_start:
    return chapter_start == chapter_index
  if chapter_end:
    return chapter_end == chapter_index
  return False


def _chapter_contract_body_section_label(value: object) -> str:
  normalized = _normalized_label(value)
  aliases = {
    "章节目标": ("章节目标", "合同目标", "目标", "objective"),
    "必须完成的节拍": ("必须完成的节拍", "必须节拍", "requiredbeats", "beats"),
    "必须推进的债务": ("必须推进的债务", "推进债务", "debtstoadvance"),
    "不能提前揭开的债务": ("不能提前揭开的债务", "保护债务", "debtstoprotect"),
    "人物检查": ("人物检查", "人物约束", "characterchecks"),
    "文风检查": ("文风检查", "风格检查", "stylechecks"),
    "禁止动作": ("禁止动作", "禁写动作", "forbiddenmoves", "avoid"),
    "验收项": ("验收项", "验收检查", "acceptancechecks", "checks"),
    "证据来源": ("证据来源", "证据", "evidencesources"),
    "风险提示": ("风险提示", "风险", "risknotes"),
  }
  for label, candidates in aliases.items():
    if normalized in {_normalized_label(candidate) for candidate in candidates}:
      return label
  return ""


def _chapter_contract_body_lines(record: object, *, limit: int = 10) -> list[str]:
  note = getattr(record, "summary", None)
  title = str(getattr(note, "title", "") or "").strip()
  text = str(getattr(record, "body", "") or "").strip()
  if not text and note is not None:
    text = str(getattr(note, "summary", "") or getattr(note, "preview", "") or "").strip()
  sections: dict[str, list[str]] = {}
  current_label = ""
  for raw_line in text.splitlines():
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw_line).strip()
    line = re.sub(r"^\s*[-*+]\s*", "", line)
    line = re.sub(r"^\s*\d+[.、）)]\s*", "", line).strip()
    if not line or line == title or line.startswith("来源章节"):
      continue
    match = re.match(r"^(.{1,24}?)[：:]\s*(.*)$", line)
    if match:
      label = _chapter_contract_body_section_label(match.group(1))
      if label:
        current_label = label
        value = _compact_text(match.group(2), 140)
        sections.setdefault(label, [])
        if value:
          sections[label].append(value)
        continue
    if current_label:
      value = _compact_text(line, 120)
      if value:
        sections.setdefault(current_label, []).append(value)

  lines: list[str] = []
  for label in (
    "章节目标",
    "必须完成的节拍",
    "必须推进的债务",
    "不能提前揭开的债务",
    "人物检查",
    "文风检查",
    "禁止动作",
    "验收项",
    "证据来源",
    "风险提示",
  ):
    values = _ordered_unique(sections.get(label, []))
    if not values:
      continue
    if label == "章节目标":
      lines.append(f"{label}：{values[0]}")
    else:
      lines.append(f"{label}：{' / '.join(values[:4])}")
    if len(lines) >= limit:
      break
  return lines


def _obsidian_plan_body_lines(record: object, *, limit: int = 7) -> list[str]:
  note = getattr(record, "summary", None)
  if note is not None and _obsidian_note_is_chapter_contract(note):
    lines = _chapter_contract_body_lines(record, limit=max(limit, 10))
    if lines:
      return lines[:max(limit, 10)]
  title = str(getattr(note, "title", "") or "").strip()
  text = str(getattr(record, "body", "") or "").strip()
  if not text and note is not None:
    text = str(getattr(note, "summary", "") or getattr(note, "preview", "") or "").strip()
  lines: list[str] = []
  for raw_line in text.splitlines():
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw_line).strip()
    line = line.strip(" \t-*+0123456789.、）)")
    if not line or line == title:
      continue
    lines.append(_compact_text(line, 150))
    if len(lines) >= limit:
      break
  if not lines and note is not None:
    fallback = _compact_text(getattr(note, "summary", "") or getattr(note, "preview", ""), 180)
    if fallback:
      lines.append(fallback)
  if note is not None:
    required = _string_list(getattr(note, "required_phrases", []), limit=4)
    forbidden = _string_list(getattr(note, "forbidden_phrases", []), limit=4)
    if required:
      lines.append(f"必须包含：{' / '.join(required)}")
    if forbidden:
      lines.append(f"禁止出现：{' / '.join(forbidden)}")
  return lines[:limit]


def _obsidian_vault_note_markdown(project_detail: object, note: object) -> str:
  project_path = str(getattr(project_detail, "path", "") or "").strip()
  if not project_path or note is None:
    return ""
  relative_path = _safe_vault_relative_path(getattr(note, "relative_path", ""))
  if relative_path is None:
    return ""
  project_dir = Path(project_path)
  config = load_obsidian_config(project_dir)
  vault_dir = resolve_obsidian_vault_dir(project_dir, config)
  if vault_dir is None:
    return ""
  note_path = vault_dir / relative_path
  try:
    note_path.resolve().relative_to(vault_dir.resolve())
  except ValueError:
    return ""
  if not note_path.is_file():
    return ""
  try:
    return note_path.read_text(encoding="utf-8")
  except OSError:
    return ""


def _obsidian_note_maintenance_identity(project_detail: object, note: object) -> str:
  inline_identity = str(getattr(note, "gaoxia_maintenance_id", "") or "").strip()
  if inline_identity:
    return inline_identity
  markdown = _obsidian_vault_note_markdown(project_detail, note)
  if not markdown:
    return ""
  return _obsidian_maintenance_identity_from_markdown(markdown)


def _obsidian_note_source_ids(project_detail: object, note: object) -> list[str]:
  markdown = _obsidian_vault_note_markdown(project_detail, note)
  if not markdown:
    return []
  return _obsidian_note_source_ids_from_markdown(markdown)


def _obsidian_vault_source_ids(project_detail: object, notes: list[object]) -> set[str]:
  source_ids: set[str] = set()
  for note in notes:
    source_ids.update(_obsidian_note_source_ids(project_detail, note))
  return source_ids


def _obsidian_note_frontmatter_payload(project_detail: object, note: object) -> dict[str, object]:
  markdown = _obsidian_vault_note_markdown(project_detail, note)
  if not markdown:
    return {}
  return _draft_frontmatter_payload(markdown)


def _obsidian_property_text(payload: dict[str, object], keys: tuple[str, ...], *, limit: int = 220) -> str:
  return _compact_text(_draft_frontmatter_value(payload, keys), limit)


def _obsidian_property_values(payload: dict[str, object], keys: tuple[str, ...], *, limit: int = 8) -> list[str]:
  return _draft_frontmatter_values(payload, keys, limit=limit)


def _obsidian_property_debt_kind(payload: dict[str, object]) -> str:
  kind = _draft_frontmatter_value(payload, _OBSIDIAN_DEBT_KIND_KEYS)
  return kind if kind in {"foreshadow", "promise", "relationship", "world_rule"} else ""


def _obsidian_property_debt_status(payload: dict[str, object]) -> str:
  status = _draft_frontmatter_value(payload, _OBSIDIAN_DEBT_STATUS_KEYS)
  return status if status in {"open", "touched", "paid", "conflict", "deferred"} else ""


def _obsidian_property_risk(payload: dict[str, object]) -> str:
  risk = _draft_frontmatter_value(payload, _OBSIDIAN_DEBT_RISK_KEYS)
  return risk if risk in {"critical", "high", "medium", "low"} else ""


def _obsidian_property_payoff_range(
  payload: dict[str, object],
  fallback: list[int],
  *,
  total_chapters: int,
) -> list[int]:
  raw = _draft_frontmatter_raw_value(payload, _OBSIDIAN_DEBT_PAYOFF_KEYS)
  if raw is None or raw == "":
    return fallback
  range_values: list[int] = []
  if isinstance(raw, list):
    for item in raw:
      start, end = _chapter_range_from_value(item)
      if start and end:
        range_values.extend([start, end])
        continue
      try:
        chapter_index = int(str(item).strip())
      except (TypeError, ValueError):
        chapter_index = _parse_chapter_number(item)
      if chapter_index > 0:
        range_values.append(chapter_index)
  else:
    start, end = _chapter_range_from_value(raw)
    if start and end:
      range_values = [start, end]
    else:
      range_values = _chapter_numbers_from_value(raw)
  if len(range_values) < 2:
    return fallback
  total = max(1, int(total_chapters or 1), range_values[0], range_values[1])
  start = min(total, max(1, int(range_values[0])))
  end = min(total, max(start, int(range_values[1])))
  return [start, end]


def _obsidian_narrative_text_with_properties(
  record: object,
  payload: dict[str, object],
  keys: tuple[str, ...],
  *,
  limit: int = 760,
) -> tuple[str, str]:
  property_text = _obsidian_property_text(payload, keys, limit=260)
  text = _obsidian_record_narrative_text(record, limit=limit)
  if property_text and property_text not in text:
    text = _compact_text(f"{property_text} {text}", limit)
  return text, property_text


def _obsidian_chapter_plan_records(project_detail: object, chapter_index: int, *, limit: int = 4) -> list[object]:
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  if obsidian is None or not bool(getattr(obsidian, "enabled", False)) or chapter_index <= 0:
    return []
  project_path = str(getattr(project_detail, "path", "") or "").strip()
  if not project_path:
    return []
  try:
    records = scoped_obsidian_note_records_for_chapter(Path(project_path), chapter_index)
  except Exception:
    return []
  selected: list[object] = []
  seen: set[str] = set()
  for record in records:
    note = record.summary
    if not _obsidian_note_is_chapter_plan(note):
      continue
    if not _obsidian_plan_targets_chapter(note, chapter_index):
      continue
    source_key = str(getattr(note, "source_key", "") or "").strip()
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    key = source_key or relative_path or str(getattr(note, "title", "") or "")
    if key and key in seen:
      continue
    if key:
      seen.add(key)
    selected.append(record)
    if len(selected) >= limit:
      break
  return selected


def _obsidian_chapter_plan_entries(project_detail: object, chapter_index: int, *, limit: int = 4) -> list[dict[str, object]]:
  records = _obsidian_chapter_plan_records(project_detail, chapter_index, limit=max(limit * 3, limit))
  entries: list[dict[str, object]] = []
  for record in records:
    note = record.summary
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    plan_lines = _obsidian_plan_body_lines(record)
    if not plan_lines:
      continue
    entries.append(
      {
        "title": str(getattr(note, "title", "") or "").strip() or Path(relative_path).stem or "未命名计划",
        "relative_path": relative_path,
        "note_type": str(getattr(note, "note_type", "") or "").strip(),
        "chapter_scope": _obsidian_scope_text(note),
        "plan_lines": plan_lines,
      }
    )
    if len(entries) >= limit:
      break
  return entries


def _obsidian_chapter_plan_prompt_lines(entries: list[dict[str, object]], *, limit: int = 4) -> list[str]:
  lines: list[str] = []
  for item in entries[:limit]:
    title = _compact_text(item.get("title"), 64)
    path = _compact_text(item.get("relative_path"), 90)
    scope = _compact_text(item.get("chapter_scope"), 80)
    label_parts = [title]
    if path and path != title:
      label_parts.append(path)
    if scope:
      label_parts.append(scope)
    label = " / ".join(part for part in label_parts if part)
    plan_line_limit = 8 if _normalized_label(item.get("note_type")) == "chaptercontract" else 5
    plan_lines = _string_list(item.get("plan_lines"), limit=plan_line_limit)
    if not label or not plan_lines:
      continue
    lines.append(f"- {label}：{'；'.join(plan_lines)}")
  return lines


def _obsidian_narrative_debt_prompt_lines(entries: list[dict[str, object]], *, limit: int = 4) -> list[str]:
  lines: list[str] = []
  for item in entries[:limit]:
    title = _compact_text(item.get("title"), 64)
    content = _compact_text(item.get("content"), 140)
    payoff = item.get("expected_payoff_range")
    payoff_text = ""
    if isinstance(payoff, list) and len(payoff) >= 2:
      payoff_text = f"；预计第 {payoff[0]}-{payoff[1]} 章处理"
    risk = str(item.get("risk_level") or "").strip()
    status = str(item.get("status") or "").strip()
    meta = "/".join(part for part in [status, risk] if part)
    meta_text = f"（{meta}{payoff_text}）" if meta or payoff_text else ""
    if title and content:
      lines.append(f"- {title}：{content}{meta_text}")
  return lines


def _obsidian_character_arc_prompt_lines(entries: list[dict[str, object]], *, limit: int = 4) -> list[str]:
  lines: list[str] = []
  for item in entries[:limit]:
    name = _compact_text(item.get("name"), 32) or "人物"
    state = _compact_text(item.get("current_state"), 140)
    check = _compact_text(item.get("required_next_check"), 100)
    if not state and not check:
      continue
    detail = "；".join(part for part in [state, check] if part)
    lines.append(f"- {name}：{detail}")
  return lines


def _obsidian_chapter_note_source_chapters(note: object) -> list[int]:
  indexes: list[int] = []
  for value in list(getattr(note, "source_chapters", []) or []):
    try:
      index = int(value or 0)
    except (TypeError, ValueError):
      index = _parse_chapter_number(value)
    if index > 0 and index not in indexes:
      indexes.append(index)
  if indexes:
    return indexes[:12]
  for index in _obsidian_note_scope_chapter_indexes(note):
    if index > 0 and index not in indexes:
      indexes.append(index)
  return indexes[:12]


def _obsidian_note_is_chapter_note(note: object) -> bool:
  relative_path = str(getattr(note, "relative_path", "") or "").strip().replace("\\", "/")
  if _chapter_note_type(getattr(note, "note_type", "")) or _chapter_note_path_like(relative_path):
    return True
  return _obsidian_note_matches_labels(note, _OBSIDIAN_CHAPTER_NOTE_LABELS)


def _obsidian_chapter_note_entry_sort_key(item: dict[str, object], chapter_index: int) -> tuple[int, int, str]:
  source_chapters = [
    int(value)
    for value in item.get("source_chapters", [])
    if isinstance(value, int) and int(value) > 0
  ]
  closest = max((value for value in source_chapters if value <= chapter_index), default=0)
  if closest <= 0:
    closest = max(source_chapters, default=0)
  has_handoff = 1 if item.get("handoff") else 0
  return (closest, has_handoff, str(item.get("title") or ""))


def _obsidian_chapter_note_entries(project_detail: object, chapter_index: int, *, limit: int = 4) -> list[dict[str, object]]:
  records = _obsidian_records_for_chapter(project_detail, chapter_index)
  entries: list[dict[str, object]] = []
  seen: set[str] = set()
  for record in records:
    note = getattr(record, "summary", None)
    if note is None or not _obsidian_note_is_chapter_note(note):
      continue
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    source_key = _obsidian_note_source_key(note)
    key = source_key or relative_path or str(getattr(note, "title", "") or "")
    if key and key in seen:
      continue
    if key:
      seen.add(key)
    payload = _obsidian_note_frontmatter_payload(project_detail, note)
    title = (
      _obsidian_property_text(payload, _OBSIDIAN_CHAPTER_NOTE_TITLE_KEYS, limit=80)
      or str(getattr(note, "title", "") or "").strip()
      or Path(relative_path).stem
      or "章节档案"
    )
    summary = (
      _obsidian_property_text(payload, _OBSIDIAN_CHAPTER_NOTE_SUMMARY_KEYS, limit=220)
      or _compact_text(getattr(note, "summary", "") or getattr(note, "preview", ""), 220)
    )
    events = _obsidian_property_values(payload, _OBSIDIAN_CHAPTER_NOTE_EVENTS_KEYS, limit=4)
    state_changes = _obsidian_property_values(payload, _OBSIDIAN_CHAPTER_NOTE_STATE_KEYS, limit=4)
    handoff = _obsidian_property_values(payload, _OBSIDIAN_CHAPTER_NOTE_HANDOFF_KEYS, limit=4)
    excerpts = _obsidian_property_values(payload, _OBSIDIAN_CHAPTER_NOTE_EXCERPT_KEYS, limit=3)
    if not any([summary, events, state_changes, handoff, excerpts]):
      body_lines = _obsidian_record_body_lines(record, limit=3)
      summary = _compact_text("；".join(body_lines), 220)
    if not any([summary, events, state_changes, handoff, excerpts]):
      continue
    entries.append(
      {
        "title": title,
        "relative_path": relative_path,
        "chapter_scope": _obsidian_scope_text(note),
        "source_chapters": _obsidian_chapter_note_source_chapters(note),
        "summary": summary,
        "events": events,
        "state_changes": state_changes,
        "handoff": handoff,
        "excerpts": excerpts,
        "source_key": key,
      }
    )
  entries.sort(key=lambda item: _obsidian_chapter_note_entry_sort_key(item, chapter_index), reverse=True)
  return entries[:limit]


def _obsidian_chapter_note_prompt_lines(entries: list[dict[str, object]], *, limit: int = 4) -> list[str]:
  lines: list[str] = []
  for item in entries[:limit]:
    title = _compact_text(item.get("title"), 64) or "章节档案"
    path = _compact_text(item.get("relative_path"), 90)
    scope = _compact_text(item.get("chapter_scope"), 80)
    source_chapters = [
      int(value)
      for value in item.get("source_chapters", [])
      if isinstance(value, int) and int(value) > 0
    ]
    source_text = "、".join(f"第 {index} 章" for index in source_chapters[:4])
    label_parts = [title]
    if path and path != title:
      label_parts.append(path)
    if source_text:
      label_parts.append(f"来源{source_text}")
    if scope:
      label_parts.append(scope)
    detail_parts: list[str] = []
    summary = _compact_text(item.get("summary"), 160)
    if summary:
      detail_parts.append(f"摘要：{summary}")
    events = _string_list(item.get("events"), limit=3)
    if events:
      detail_parts.append(f"关键事件：{' / '.join(events[:3])}")
    state_changes = _string_list(item.get("state_changes"), limit=3)
    if state_changes:
      detail_parts.append(f"状态变化：{' / '.join(state_changes[:3])}")
    handoff = _string_list(item.get("handoff"), limit=3)
    if handoff:
      detail_parts.append(f"章节交接：{' / '.join(handoff[:3])}")
    excerpts = _string_list(item.get("excerpts"), limit=2)
    if excerpts and not detail_parts:
      detail_parts.append(f"正文摘录：{' / '.join(excerpts[:2])}")
    label = " / ".join(part for part in label_parts if part)
    if label and detail_parts:
      lines.append(f"- {label}：{'；'.join(detail_parts)}")
  return lines


def _obsidian_note_label_values(note: object) -> list[str]:
  relative_path = str(getattr(note, "relative_path", "") or "").strip().replace("\\", "/")
  path_parts = [part for part in relative_path.split("/") if part]
  stem = Path(relative_path).stem if relative_path else ""
  labels = [
    str(getattr(note, "note_type", "") or ""),
    str(getattr(note, "title", "") or ""),
    stem,
    *path_parts,
    *[str(value) for value in list(getattr(note, "tags", []) or [])],
    *[str(value) for value in list(getattr(note, "keywords", []) or [])],
    *[str(value) for value in list(getattr(note, "aliases", []) or [])],
  ]
  return _ordered_unique([item for item in labels if item.strip()])


def _obsidian_note_matches_labels(note: object, labels: set[str]) -> bool:
  note_labels = {_normalized_label(label) for label in _obsidian_note_label_values(note)}
  return bool(note_labels & labels)


def _obsidian_note_is_debt_note(note: object) -> bool:
  return _obsidian_note_matches_labels(note, _OBSIDIAN_DEBT_NOTE_LABELS)


def _obsidian_note_is_arc_note(note: object) -> bool:
  return _obsidian_note_matches_labels(note, _OBSIDIAN_ARC_NOTE_LABELS)


def _obsidian_records_for_chapter(project_detail: object, chapter_index: int) -> list[object]:
  if not _obsidian_state_enabled(project_detail) or chapter_index <= 0:
    return []
  project_path = str(getattr(project_detail, "path", "") or "").strip()
  if not project_path:
    return []
  try:
    return list(scoped_obsidian_note_records_for_chapter(Path(project_path), chapter_index))
  except Exception:
    return []


def _obsidian_record_body_lines(record: object, *, limit: int = 8) -> list[str]:
  note = getattr(record, "summary", None)
  title = str(getattr(note, "title", "") or "").strip()
  text = str(getattr(record, "body", "") or "").strip()
  if not text and note is not None:
    text = str(getattr(note, "summary", "") or getattr(note, "preview", "") or "").strip()
  lines: list[str] = []
  for raw_line in text.splitlines():
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw_line).strip()
    line = line.strip(" \t-*+0123456789.、）)")
    if not line or line == title:
      continue
    lines.append(_compact_text(line, 180))
    if len(lines) >= limit:
      break
  if not lines and note is not None:
    fallback = _compact_text(getattr(note, "summary", "") or getattr(note, "preview", ""), 180)
    if fallback:
      lines.append(fallback)
  return lines[:limit]


def _obsidian_record_narrative_text(record: object, *, limit: int = 760) -> str:
  note = getattr(record, "summary", None)
  parts: list[str] = []
  if note is not None:
    for value in [
      getattr(note, "title", ""),
      getattr(note, "summary", ""),
      getattr(note, "preview", ""),
      " ".join(_string_list(getattr(note, "required_phrases", []), limit=8)),
      " ".join(_string_list(getattr(note, "forbidden_phrases", []), limit=8)),
      " ".join(_string_list(getattr(note, "graph_relations", []), limit=8)),
    ]:
      text = str(value or "").strip()
      if text:
        parts.append(text)
  parts.extend(_obsidian_record_body_lines(record, limit=10))
  return _compact_text(" ".join(parts), limit)


def _obsidian_note_scope_range(note: object, chapter_index: int, total_chapters: int, kind: str) -> list[int]:
  try:
    start = int(getattr(note, "chapter_start", 0) or 0)
  except (TypeError, ValueError):
    start = 0
  try:
    end = int(getattr(note, "chapter_end", 0) or 0)
  except (TypeError, ValueError):
    end = 0
  try:
    reveal_after = int(getattr(note, "reveal_after_chapter", 0) or 0)
  except (TypeError, ValueError):
    reveal_after = 0
  if start and end:
    total = max(1, int(total_chapters or 1), start, end)
    return [min(total, max(1, start)), min(total, max(start, end))]
  if start:
    return _payoff_range(start, total_chapters, kind)
  if reveal_after:
    return _payoff_range(max(1, reveal_after + 1), total_chapters, kind)
  return _payoff_range(max(1, chapter_index or 1), total_chapters, kind)


def _obsidian_debt_note_status(note: object, text: str) -> str:
  label_text = " ".join(_normalized_label(label) for label in _obsidian_note_label_values(note))
  body_text = _normalized_label(text)
  joined = f"{label_text} {body_text}"
  if any(label in joined for label in _OBSIDIAN_DEBT_PAID_LABELS):
    return "paid"
  if any(label in joined for label in _OBSIDIAN_DEBT_DEFERRED_LABELS):
    return "deferred"
  if any(token in text for token in _CONFLICT_TOKENS):
    return "conflict"
  if any(token in text for token in ("已推进", "已触发", "进行中")):
    return "touched"
  return "open"


def _obsidian_note_source_key(note: object) -> str:
  return (
    str(getattr(note, "source_key", "") or "").strip()
    or str(getattr(note, "relative_path", "") or "").strip()
    or str(getattr(note, "title", "") or "").strip()
  )


def _obsidian_debt_note_id(note: object, text: str) -> str:
  key = _obsidian_note_source_key(note) or _compact_text(text, 120)
  digest = hashlib.sha1(f"obsidian-debt\n{key}".encode("utf-8")).hexdigest()[:12]
  return f"debt-obsidian-note-{digest}"


def _obsidian_debt_note_candidates(
  project_detail: object,
  chapter: object | None,
  *,
  records: list[object] | None = None,
) -> list[dict[str, object]]:
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  chapter_id = str(getattr(chapter, "id", "") or "") if chapter is not None else ""
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  chapter_title = str(getattr(chapter, "title", "") or "") if chapter is not None else ""
  if chapter_index <= 0:
    return []
  scoped_records = records if records is not None else _obsidian_records_for_chapter(project_detail, chapter_index)
  candidates: list[dict[str, object]] = []
  for record in scoped_records:
    note = getattr(record, "summary", None)
    if note is None or not _obsidian_note_is_debt_note(note):
      continue
    payload = _obsidian_note_frontmatter_payload(project_detail, note)
    text, property_content = _obsidian_narrative_text_with_properties(record, payload, _OBSIDIAN_DEBT_CONTENT_KEYS)
    if not text:
      continue
    kind = _obsidian_property_debt_kind(payload) or _debt_kind(text)
    status = _obsidian_property_debt_status(payload) or _obsidian_debt_note_status(note, text)
    expected_range = _obsidian_property_payoff_range(
      payload,
      _obsidian_note_scope_range(note, chapter_index, total_chapters, kind),
      total_chapters=total_chapters,
    )
    title = str(getattr(note, "title", "") or "").strip() or Path(str(getattr(note, "relative_path", "") or "")).stem or "Obsidian 剧情债务"
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    source = f"{title} / {relative_path}" if relative_path and relative_path != title else title
    scope = _obsidian_scope_text(note)
    if scope:
      source = f"{source}（{scope}）"
    related_characters = _ordered_unique(
      _obsidian_property_values(payload, _OBSIDIAN_DEBT_CHARACTER_KEYS, limit=8)
      + [name for name in _known_names(project_detail) if name and name in text]
    )[:6]
    content = property_content or text
    evidence = [f"Obsidian 剧情债务：{source}", _compact_text(content, 180)]
    risk = _obsidian_property_risk(payload) or _risk_level(status, expected_range, chapter_index, total_chapters)
    next_action = _obsidian_property_text(payload, _OBSIDIAN_DEBT_ACTION_KEYS, limit=140)
    candidates.append(
      {
        "id": _obsidian_debt_note_id(note, text),
        "kind": kind,
        "title": title,
        "content": content,
        "status": status,
        "first_seen_chapter_id": _chapter_id_from_index(expected_range[0]) if expected_range else chapter_id,
        "first_seen_chapter_index": expected_range[0] if expected_range else chapter_index,
        "last_seen_chapter_id": chapter_id,
        "last_seen_chapter_index": chapter_index,
        "last_seen_chapter_title": chapter_title,
        "source_chapter_ids": [chapter_id] if chapter_id else [],
        "source_names": ["obsidian_debt"],
        "evidence": evidence,
        "expected_payoff_range": expected_range,
        "next_required_action": next_action or _next_required_action(status, expected_range, chapter_index, total_chapters),
        "related_characters": related_characters,
        "risk_level": risk,
        "confidence": 0.82,
      }
    )
  return candidates


def _obsidian_arc_name(project_detail: object, note: object, text: str) -> str:
  title = str(getattr(note, "title", "") or "").strip()
  for name in _known_names(project_detail):
    if name and (name in title or name in text):
      return name
  fallback = title or Path(str(getattr(note, "relative_path", "") or "")).stem
  fallback = re.sub(r"(人物弧线|人物状态|人物进展|角色弧线|角色状态|character\s*arc|arc|state|progress)", "", fallback, flags=re.IGNORECASE)
  return fallback.strip(" -_：:")[:24]


def _obsidian_arc_note_candidates(
  project_detail: object,
  chapter: object | None,
  *,
  records: list[object] | None = None,
) -> list[dict[str, object]]:
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  chapter_id = str(getattr(chapter, "id", "") or "") if chapter is not None else ""
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  if chapter_index <= 0:
    return []
  scoped_records = records if records is not None else _obsidian_records_for_chapter(project_detail, chapter_index)
  candidates: list[dict[str, object]] = []
  for record in scoped_records:
    note = getattr(record, "summary", None)
    if note is None or not _obsidian_note_is_arc_note(note):
      continue
    payload = _obsidian_note_frontmatter_payload(project_detail, note)
    text, property_state = _obsidian_narrative_text_with_properties(record, payload, _OBSIDIAN_ARC_STATE_KEYS)
    if not text:
      continue
    name = _obsidian_property_text(payload, _OBSIDIAN_ARC_NAME_KEYS, limit=40) or _obsidian_arc_name(project_detail, note, text)
    if not name:
      continue
    title = str(getattr(note, "title", "") or "").strip() or name
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    source = f"{title} / {relative_path}" if relative_path and relative_path != title else title
    scope = _obsidian_scope_text(note)
    if scope:
      source = f"{source}（{scope}）"
    phase = _obsidian_property_text(payload, _OBSIDIAN_ARC_PHASE_KEYS, limit=60) or _arc_phase(chapter_index, total_chapters)
    pressure = _obsidian_property_text(payload, _OBSIDIAN_ARC_PRESSURE_KEYS, limit=140)
    required_check = _obsidian_property_text(payload, _OBSIDIAN_ARC_CHECK_KEYS, limit=140)
    current_state = property_state or text
    candidates.append(
      {
        "id": f"arc-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}",
        "name": name,
        "phase": phase,
        "current_state": _compact_text(current_state, 180),
        "last_seen_chapter_id": chapter_id,
        "last_seen_chapter_index": chapter_index,
        "source_chapter_ids": [chapter_id] if chapter_id else [],
        "source_names": ["obsidian_arc"],
        "evidence": [f"Obsidian 人物弧线：{source}", _compact_text(current_state, 180)],
        "unresolved_pressure": pressure or f"Obsidian 人物弧线：{_compact_text(current_state, 120)}",
        "required_next_check": required_check or f"按 Obsidian 笔记《{title}》检查 {name} 的选择和行动。",
        "confidence": 0.82,
      }
    )
  return candidates


def _obsidian_narrative_note_entries(project_detail: object, chapter_index: int, *, limit: int = 4) -> dict[str, list[dict[str, object]]]:
  records = _obsidian_records_for_chapter(project_detail, chapter_index)
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  debts: list[dict[str, object]] = []
  arcs: list[dict[str, object]] = []
  seen_debts: set[str] = set()
  seen_arcs: set[str] = set()
  for record in records:
    note = getattr(record, "summary", None)
    if note is None:
      continue
    payload = _obsidian_note_frontmatter_payload(project_detail, note)
    text = _obsidian_record_narrative_text(record)
    if not text:
      continue
    relative_path = str(getattr(note, "relative_path", "") or "").strip()
    title = str(getattr(note, "title", "") or "").strip() or Path(relative_path).stem or "未命名笔记"
    source_key = _obsidian_note_source_key(note) or title
    scope = _obsidian_scope_text(note)
    if _obsidian_note_is_debt_note(note) and len(debts) < limit:
      debt_text, property_content = _obsidian_narrative_text_with_properties(record, payload, _OBSIDIAN_DEBT_CONTENT_KEYS)
      if not debt_text:
        continue
      debt_id = _obsidian_debt_note_id(note, debt_text)
      if debt_id not in seen_debts:
        seen_debts.add(debt_id)
        kind = _obsidian_property_debt_kind(payload) or _debt_kind(debt_text)
        status = _obsidian_property_debt_status(payload) or _obsidian_debt_note_status(note, debt_text)
        payoff_range = _obsidian_property_payoff_range(
          payload,
          _obsidian_note_scope_range(note, chapter_index, total_chapters, kind),
          total_chapters=total_chapters,
        )
        debts.append(
          {
            "id": debt_id,
            "title": title,
            "relative_path": relative_path,
            "kind": kind,
            "status": status,
            "expected_payoff_range": payoff_range,
            "risk_level": _obsidian_property_risk(payload) or _risk_level(status, payoff_range, chapter_index, total_chapters),
            "content": _compact_text(property_content or debt_text, 240),
            "chapter_scope": scope,
            "source_key": source_key,
          }
        )
    if _obsidian_note_is_arc_note(note) and len(arcs) < limit:
      arc_text, property_state = _obsidian_narrative_text_with_properties(record, payload, _OBSIDIAN_ARC_STATE_KEYS)
      if not arc_text:
        continue
      name = _obsidian_property_text(payload, _OBSIDIAN_ARC_NAME_KEYS, limit=40) or _obsidian_arc_name(project_detail, note, arc_text)
      arc_key = f"{source_key}:{name}"
      if name and arc_key not in seen_arcs:
        seen_arcs.add(arc_key)
        required_check = _obsidian_property_text(payload, _OBSIDIAN_ARC_CHECK_KEYS, limit=140)
        arcs.append(
          {
            "name": name,
            "title": title,
            "relative_path": relative_path,
            "phase": _obsidian_property_text(payload, _OBSIDIAN_ARC_PHASE_KEYS, limit=60) or _arc_phase(chapter_index, total_chapters),
            "current_state": _compact_text(property_state or arc_text, 240),
            "required_next_check": required_check or f"按 Obsidian 笔记《{title}》检查 {name} 的选择和行动。",
            "chapter_scope": scope,
            "source_key": source_key,
          }
        )
    if len(debts) >= limit and len(arcs) >= limit:
      break
  return {"narrative_debts": debts[:limit], "character_arcs": arcs[:limit]}


def _obsidian_guidance_for_chapter(
  project_detail: object,
  chapter_index: int,
  *,
  query: str = "",
  limit: int = 6,
  chapter_text: str = "",
) -> dict[str, object]:
  notes = _obsidian_notes_for_chapter(project_detail, chapter_index, query=query, limit=limit)
  sources: list[str] = []
  external_references: list[str] = []
  required: list[str] = []
  forbidden: list[str] = []
  risks: list[str] = []
  required_satisfied: list[str] = []
  required_missing: list[str] = []
  forbidden_violations: list[str] = []
  payload_notes: list[dict[str, object]] = []
  text = str(chapter_text or "")
  has_text = bool(text.strip())
  for note in notes:
    title = str(getattr(note, "title", "") or "").strip() or "未命名笔记"
    path = str(getattr(note, "relative_path", "") or "").strip()
    scope = _obsidian_scope_text(note)
    source = f"{title} / {path}" if path and path != title else title
    if scope:
      source = f"{source}（{scope}）"
    sources.append(source)
    for reference in _string_list(getattr(note, "external_references", []), limit=4):
      external_references.append(f"{title}：{reference}")
    note_required = _string_list(getattr(note, "required_phrases", []), limit=8)
    note_forbidden = _string_list(getattr(note, "forbidden_phrases", []), limit=8)
    required.extend(note_required)
    forbidden.extend(note_forbidden)
    if has_text:
      for phrase in note_required:
        marker = f"{phrase}（{title}）"
        if phrase in text:
          required_satisfied.append(marker)
        else:
          required_missing.append(marker)
      for phrase in note_forbidden:
        if phrase in text:
          forbidden_violations.append(f"{phrase}（{title}）")
    ambiguous = _string_list(getattr(note, "ambiguous_links", []), limit=4)
    unresolved = _string_list(getattr(note, "unresolved_links", []), limit=4)
    if ambiguous:
      risks.append(f"{title} 存在歧义双链：{' / '.join(ambiguous[:3])}")
    if unresolved:
      risks.append(f"{title} 存在未解析双链：{' / '.join(unresolved[:3])}")
    payload_notes.append(
      {
        "title": title,
        "relative_path": path,
        "note_type": str(getattr(note, "note_type", "") or ""),
        "preview": _compact_text(getattr(note, "preview", ""), 220),
        "required_phrases": note_required,
        "forbidden_phrases": note_forbidden,
        "chapter_scope": scope,
        "external_references": _string_list(getattr(note, "external_references", []), limit=4),
        "resolved_links": _string_list(getattr(note, "resolved_links", []), limit=6),
        "backlinks": _string_list(getattr(note, "backlinks", []), limit=6),
        "ambiguous_links": ambiguous,
        "unresolved_links": unresolved,
      }
    )
  return {
    "sources": _ordered_unique(sources)[:limit],
    "external_references": _ordered_unique(external_references)[:limit],
    "required": _ordered_unique(required)[:10],
    "forbidden": _ordered_unique(forbidden)[:10],
    "risks": _ordered_unique(risks)[:8],
    "required_satisfied": _ordered_unique(required_satisfied)[:10],
    "required_missing": _ordered_unique(required_missing)[:10],
    "forbidden_violations": _ordered_unique(forbidden_violations)[:10],
    "notes": payload_notes,
    "chapter_plans": _obsidian_chapter_plan_entries(project_detail, chapter_index, limit=4),
    "chapter_notes": _obsidian_chapter_note_entries(project_detail, chapter_index, limit=4),
    **_obsidian_narrative_note_entries(project_detail, chapter_index, limit=4),
  }


def _build_chapter_card(project_detail: object, chapter: object | None) -> dict[str, object]:
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  chapter_id = str(getattr(chapter, "id", "") or "") if chapter is not None else ""
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  stage = _stage_label(chapter_index, total_chapters)
  blueprint_line = _chapter_blueprint_line(project_detail, chapter_index)
  position = _chapter_position(chapter_index, total_chapters)
  required_outcomes = [
    "承接上一章末尾的因果，不跳过人物反应。",
    "推进本章蓝图目标或明确偏离原因。",
    "至少处理一条已挂起的线索、关系压力或规则后果。",
  ]
  if position >= 0.65:
    required_outcomes.append("减少孤立新问题，把信息压力转向终局。")
  if position >= 0.82:
    required_outcomes.append("开始兑现核心承诺，保留结局前最后阻力。")
  avoid = [
    "不要把旧线索只当气氛词重复。",
    "不要让人物退回早期状态。",
  ]
  if position < 0.82:
    avoid.append("不要提前交代最终真相，除非蓝图已经要求。")
  next_handoff = "下一章需要接住本章新变化，而不是重置到普通追查。"
  if position >= 0.65:
    next_handoff = "下一章应继续压缩未处理债务，准备终局兑现。"
  obsidian_guidance = _obsidian_guidance_for_chapter(
    project_detail,
    chapter_index,
    query=" ".join(item for item in [str(getattr(chapter, "title", "") or "") if chapter is not None else "", blueprint_line] if item),
    chapter_text=str(getattr(chapter, "content", "") or "") if chapter is not None else "",
  )
  return {
    "id": chapter_id or f"chapter-{chapter_index:03d}",
    "chapter_id": chapter_id,
    "chapter_index": chapter_index,
    "stage": stage,
    "position_ratio": round(position, 3),
    "blueprint_anchor": blueprint_line,
    "required_outcomes": required_outcomes,
    "avoid": avoid,
    "next_handoff": next_handoff,
    "obsidian_sources": obsidian_guidance["sources"],
    "obsidian_external_references": obsidian_guidance["external_references"],
    "obsidian_required": obsidian_guidance["required"],
    "obsidian_forbidden": obsidian_guidance["forbidden"],
    "obsidian_risks": obsidian_guidance["risks"],
    "obsidian_required_satisfied": obsidian_guidance["required_satisfied"],
    "obsidian_required_missing": obsidian_guidance["required_missing"],
    "obsidian_forbidden_violations": obsidian_guidance["forbidden_violations"],
    "obsidian_notes": obsidian_guidance["notes"],
    "obsidian_chapter_plans": obsidian_guidance["chapter_plans"],
    "obsidian_chapter_notes": obsidian_guidance["chapter_notes"],
    "obsidian_narrative_debts": obsidian_guidance["narrative_debts"],
    "obsidian_character_arcs": obsidian_guidance["character_arcs"],
  }


def build_project_narrative_state_chapter_card(project_detail: object, chapter_id: str) -> dict[str, object]:
  chapter = _chapter_for_id(project_detail, chapter_id)
  if chapter is None:
    return {}
  return _build_chapter_card(project_detail, chapter)


def refresh_project_narrative_state_chapter_cards(
  project_dir: Path,
  project_detail: object,
  *,
  persist: bool = True,
  auto_stage_drafts: bool = False,
) -> dict[str, object]:
  state = load_project_narrative_state(project_dir)
  cards = [item for item in state.get("chapter_cards", []) if isinstance(item, dict)]
  now = _now_iso()
  moved_published_note = _rebind_moved_published_obsidian_notes(project_dir, state, now=now)
  if not cards:
    before_suggestions = state.get("obsidian_maintenance_suggestions")
    before_actions = state.get("obsidian_maintenance_actions")
    _set_obsidian_maintenance_suggestions(
      state,
      _obsidian_maintenance_suggestions(project_detail, state, project_dir),
    )
    if auto_stage_drafts:
      state = _auto_stage_obsidian_maintenance_drafts(project_dir, project_detail, state, now=now)
    if (
      state.get("obsidian_maintenance_suggestions") != before_suggestions
      or state.get("obsidian_maintenance_actions") != before_actions
      or moved_published_note
    ):
      state["updated_at"] = now
      state["revision"] = int(state.get("revision") or 0) + 1
      if persist:
        atomic_write_json(narrative_state_path(project_dir), state)
    return state

  chapters_by_id = {
    str(getattr(item, "id", "") or ""): item
    for item in getattr(project_detail, "chapters", []) or []
    if str(getattr(item, "id", "") or "").strip()
  }
  chapters_by_index = {
    int(getattr(item, "index", 0) or 0): item
    for item in getattr(project_detail, "chapters", []) or []
    if int(getattr(item, "index", 0) or 0) > 0
  }

  refreshed_cards: list[dict[str, object]] = []
  changed = False
  for card in cards:
    chapter_id = str(card.get("chapter_id") or card.get("id") or "").strip()
    try:
      chapter_index = int(card.get("chapter_index") or 0)
    except (TypeError, ValueError):
      chapter_index = 0
    chapter = chapters_by_id.get(chapter_id) or chapters_by_index.get(chapter_index)
    if chapter is None:
      refreshed_cards.append(card)
      continue
    refreshed = _build_chapter_card(project_detail, chapter)
    if refreshed != card:
      changed = True
    refreshed_cards.append(refreshed)

  state["chapter_cards"] = sorted(
    refreshed_cards,
    key=lambda item: int(item.get("chapter_index") or 0),
  )[-_MAX_OBSERVATIONS:]
  before_suggestions = state.get("obsidian_maintenance_suggestions")
  before_actions = state.get("obsidian_maintenance_actions")
  _set_obsidian_maintenance_suggestions(
    state,
    _obsidian_maintenance_suggestions(project_detail, state, project_dir),
  )
  if auto_stage_drafts:
    state = _auto_stage_obsidian_maintenance_drafts(project_dir, project_detail, state, now=now)
  if (
    state.get("obsidian_maintenance_suggestions") != before_suggestions
    or state.get("obsidian_maintenance_actions") != before_actions
    or moved_published_note
  ):
    changed = True

  if not changed:
    return state

  state["updated_at"] = now
  state["revision"] = int(state.get("revision") or 0) + 1
  if persist:
    atomic_write_json(narrative_state_path(project_dir), state)
  return state


def _contract_for_chapter(state: dict[str, object], chapter_id: str, chapter_index: int) -> dict[str, object] | None:
  contracts = [item for item in state.get("chapter_contracts", []) if isinstance(item, dict)]
  for item in reversed(contracts):
    if str(item.get("target_chapter_id") or "") == chapter_id:
      return item
  for item in reversed(contracts):
    if int(item.get("target_chapter_index") or 0) == chapter_index:
      return item
  return None


def _contract_review_for_chapter(state: dict[str, object], chapter_id: str, chapter_index: int) -> dict[str, object] | None:
  reviews = [item for item in state.get("contract_reviews", []) if isinstance(item, dict)]
  for item in reversed(reviews):
    if str(item.get("target_chapter_id") or "") == chapter_id:
      return item
  for item in reversed(reviews):
    if int(item.get("target_chapter_index") or 0) == chapter_index:
      return item
  return None


def _contract_id(target_chapter_id: str, target_chapter_index: int) -> str:
  if target_chapter_id:
    return f"contract-{target_chapter_id}"
  return f"contract-{_chapter_id_from_index(target_chapter_index)}"


def _model_contract_from_payload(
  project_detail: object,
  chapter: object,
  payload: dict[str, object],
  *,
  now: str,
  model_source: str,
) -> dict[str, object] | None:
  raw = payload.get("next_chapter_contract") or payload.get("chapter_contract")
  if not isinstance(raw, dict):
    return None
  current_index = int(getattr(chapter, "index", 0) or 0)
  total_chapters = int(getattr(project_detail, "target_chapters", 0) or 0)
  target_index = int(raw.get("target_chapter_index") or min(max(current_index + 1, 1), max(total_chapters, current_index + 1)))
  if total_chapters and target_index > total_chapters:
    return None
  raw_target_id = str(raw.get("target_chapter_id") or "").strip()
  target_id = raw_target_id if _CONTRACT_ID_RE.match(raw_target_id) else _chapter_id_from_index(target_index)
  objective = _compact_text(raw.get("objective") or raw.get("goal") or raw.get("summary"), 180)
  required_beats = _string_list(raw.get("required_beats") or raw.get("beats"), limit=8)
  acceptance_checks = _string_list(raw.get("acceptance_checks") or raw.get("checks"), limit=8)
  if not objective and not required_beats and not acceptance_checks:
    return None
  return {
    "id": _contract_id(target_id, target_index),
    "target_chapter_id": target_id,
    "target_chapter_index": target_index,
    "source_chapter_id": str(getattr(chapter, "id", "") or ""),
    "source_chapter_index": current_index,
    "generated_at": now,
    "generated_by": model_source,
    "status": "active",
    "objective": objective,
    "required_beats": required_beats,
    "debts_to_advance": _string_list(raw.get("debts_to_advance"), limit=8),
    "debts_to_protect": _string_list(raw.get("debts_to_protect"), limit=8),
    "character_checks": _string_list(raw.get("character_checks"), limit=8),
    "style_checks": _string_list(raw.get("style_checks"), limit=6),
    "forbidden_moves": _string_list(raw.get("forbidden_moves") or raw.get("avoid"), limit=8),
    "acceptance_checks": acceptance_checks,
    "evidence_sources": _string_list(raw.get("evidence_sources") or raw.get("evidence"), limit=8),
    "risk_notes": _string_list(raw.get("risk_notes") or raw.get("risks"), limit=6),
  }


def _contract_review_from_payload(
  chapter: object,
  payload: dict[str, object],
  *,
  now: str,
  model_source: str,
) -> dict[str, object] | None:
  raw = payload.get("contract_review")
  if not isinstance(raw, dict):
    return None
  chapter_id = str(getattr(chapter, "id", "") or "")
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  passed = bool(raw.get("passed")) if "passed" in raw else str(raw.get("status") or "").strip() in {"passed", "good", "ok"}
  satisfied = _string_list(raw.get("satisfied") or raw.get("done"), limit=8)
  missed = _string_list(raw.get("missed") or raw.get("missing"), limit=8)
  revision_focus = _string_list(raw.get("revision_focus") or raw.get("fixes"), limit=8)
  evidence = _string_list(raw.get("evidence"), limit=8)
  if not satisfied and not missed and not revision_focus and not evidence:
    return None
  score = int(max(0, min(100, _number(raw.get("score"), 78 if passed else 62))))
  status = str(raw.get("status") or ("passed" if passed else "needs_revision")).strip()
  return {
    "id": f"contract-review-{chapter_id}-{hashlib.sha1(now.encode('utf-8')).hexdigest()[:8]}",
    "target_chapter_id": str(raw.get("target_chapter_id") or chapter_id),
    "target_chapter_index": int(raw.get("target_chapter_index") or chapter_index),
    "reviewed_at": now,
    "reviewed_by": model_source,
    "status": status,
    "score": score,
    "passed": passed,
    "satisfied": satisfied,
    "missed": missed,
    "revision_focus": revision_focus,
    "evidence": evidence,
  }


def _merge_contract(existing: dict[str, object] | None, candidate: dict[str, object]) -> dict[str, object]:
  if existing is None:
    return candidate
  merged = {**existing, **candidate}
  merged["created_at"] = existing.get("created_at") or candidate.get("generated_at") or ""
  return merged


def _sort_debts(debts: list[dict[str, object]]) -> list[dict[str, object]]:
  risk_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
  status_rank = {"conflict": 0, "open": 1, "touched": 2, "deferred": 3, "paid": 4}
  return sorted(
    debts,
    key=lambda item: (
      risk_rank.get(str(item.get("risk_level") or ""), 9),
      status_rank.get(str(item.get("status") or ""), 9),
      int(item.get("last_seen_chapter_index") or 0),
      -float(item.get("confidence") or 0),
    ),
    reverse=False,
  )


def _model_available(settings: Settings) -> bool:
  try:
    from novel_backend.services.chapter_review_service import _resolve_independent_review_model

    if _resolve_independent_review_model(settings) is not None:
      return True
  except Exception:
    pass
  config = load_config(settings).model
  return bool(config.api_key.strip())


def _invoke_narrative_editor_model(settings: Settings, messages: list[dict[str, object]]) -> tuple[str, str]:
  try:
    from novel_backend.services.chapter_review_service import _resolve_independent_review_model

    independent_model = _resolve_independent_review_model(settings)
  except Exception:
    independent_model = None
  if independent_model is not None:
    from novel_backend.services.generation_service import _extract_message_content, _request_chat_completion

    try:
      payload: dict[str, object] = {
        "model": str(independent_model["model_name"]),
        "messages": messages,
        "max_tokens": min(3600, int(independent_model["max_tokens"])),
      }
      if independent_model.get("temperature") is not None:
        payload["temperature"] = float(independent_model["temperature"])
      with model_runtime_slot(settings, lane="chat", task_name="narrative_state_editor:review_model"):
        response_payload = _request_chat_completion(
          str(independent_model["endpoint"]),
          str(independent_model["api_key"]),
          payload,
        )
    except Exception as error:
      mark_model_runtime_cooldown(settings, "chat", str(error))
      raise
    return _extract_message_content(response_payload), "review_model"

  from novel_backend.services.generation_service import _invoke_model

  content = _invoke_model(
    settings,
    messages,
    task_name="narrative_state_editor",
    temperature=0.2,
    max_tokens=2600,
  )
  return content, "primary_model"


def _state_excerpt_for_model(state: dict[str, object]) -> dict[str, object]:
  return {
    "debts": [
      {
        "id": item.get("id"),
        "title": item.get("title"),
        "kind": item.get("kind"),
        "status": item.get("status"),
        "risk_level": item.get("risk_level"),
        "expected_payoff_range": item.get("expected_payoff_range"),
        "next_required_action": item.get("next_required_action"),
      }
      for item in state.get("debts", [])[:12]
      if isinstance(item, dict)
    ],
    "character_arcs": [
      {
        "id": item.get("id"),
        "name": item.get("name"),
        "phase": item.get("phase"),
        "unresolved_pressure": item.get("unresolved_pressure"),
        "required_next_check": item.get("required_next_check"),
      }
      for item in state.get("character_arcs", [])[:8]
      if isinstance(item, dict)
    ],
    "chapter_contracts": [
      item
      for item in state.get("chapter_contracts", [])[-6:]
      if isinstance(item, dict)
    ],
  }


def _model_editor_messages(
  project_detail: object,
  chapter: object,
  state: dict[str, object],
  *,
  review_error: str,
) -> list[dict[str, object]]:
  docs = _documents_map(project_detail)
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  current_contract = _contract_for_chapter(state, str(getattr(chapter, "id", "") or ""), chapter_index)
  previous_chapter = next(
    (
      item for item in getattr(project_detail, "chapters", []) or []
      if int(getattr(item, "index", 0) or 0) == chapter_index - 1 and getattr(item, "exists", False)
    ),
    None,
  )
  payload = {
    "project": {
      "name": getattr(project_detail, "name", ""),
      "genre": getattr(project_detail, "genre", ""),
      "target_chapters": getattr(project_detail, "target_chapters", 0),
      "target_words": getattr(project_detail, "target_words", 0),
    },
    "documents": {
      "core_seed": _compact_text(docs.get("core_seed", ""), 700),
      "plot_structure": _compact_text(docs.get("plot_structure", ""), 1100),
      "character_design": _compact_text(docs.get("character_design", ""), 900),
      "character_state": _compact_text(docs.get("character_state", ""), 900),
      "global_summary": _compact_text(docs.get("global_summary", ""), 900),
      "blueprint": _compact_text(docs.get("blueprint", ""), 1600),
    },
    "current_chapter": {
      "id": getattr(chapter, "id", ""),
      "index": chapter_index,
      "title": getattr(chapter, "title", ""),
      "content": _compact_text(getattr(chapter, "content", ""), 4200),
    },
    "previous_chapter_tail": _compact_text(getattr(previous_chapter, "content", "") if previous_chapter else "", 700),
    "existing_state": _state_excerpt_for_model(state),
    "current_contract": current_contract or {},
    "obsidian_current_chapter": _obsidian_guidance_for_chapter(
      project_detail,
      chapter_index,
      query=f"{getattr(chapter, 'title', '')} {getattr(chapter, 'content', '')}",
      limit=8,
    ),
    "obsidian_next_chapter": _obsidian_guidance_for_chapter(
      project_detail,
      chapter_index + 1,
      query=f"{_chapter_blueprint_line(project_detail, chapter_index + 1)} {getattr(chapter, 'content', '')}",
      limit=8,
    ),
    "review_error": review_error.strip(),
  }
  system_prompt = (
    "你是长篇小说的叙事编辑。只输出一个 JSON 对象，不要输出解释、标题或代码块。"
    "JSON 字段固定为：summary、debt_updates、character_arc_updates、contract_review、next_chapter_contract、risk_notes。"
    "debt_updates 每项字段：id、title、kind、status、content、evidence、related_characters、expected_payoff_range、next_required_action、risk_level、confidence。"
    "kind 只能是 foreshadow、promise、relationship、world_rule；status 只能是 open、touched、paid、conflict、deferred。"
    "character_arc_updates 每项字段：name、phase、current_state、evidence、unresolved_pressure、required_next_check、confidence。"
    "contract_review 用来检查 current_contract 是否被当前章节满足，字段：target_chapter_id、target_chapter_index、status、score、passed、satisfied、missed、revision_focus、evidence。"
    "next_chapter_contract 是下一章写作合同，字段：target_chapter_id、target_chapter_index、objective、required_beats、debts_to_advance、debts_to_protect、character_checks、style_checks、forbidden_moves、acceptance_checks、evidence_sources、risk_notes。"
    "obsidian_current_chapter 和 obsidian_next_chapter 是作者 Vault 中按章节过滤后的正式设定；下一章合同需要吸收其中的章节计划、必写项、禁写项、剧情债务、人物弧线和图谱风险。"
    "所有 debt_updates 和 character_arc_updates 必须带当前章节、项目文档或 Obsidian 笔记里的证据；没有证据就不要写该项。"
  )
  return [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
  ]


def _apply_model_editor_payload(
  state: dict[str, object],
  project_detail: object,
  chapter: object,
  payload: dict[str, object],
  *,
  now: str,
  model_source: str,
) -> dict[str, object]:
  debts_by_id = {
    str(item.get("id") or ""): item
    for item in state.get("debts", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  for candidate in _model_debt_candidates(project_detail, chapter, payload):
    debts_by_id[str(candidate["id"])] = _merge_debt(debts_by_id.get(str(candidate["id"])), candidate, now)
  state["debts"] = _sort_debts(list(debts_by_id.values()))[:_MAX_DEBTS]

  arcs_by_id = {
    str(item.get("id") or ""): item
    for item in state.get("character_arcs", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  for candidate in _model_arc_candidates(project_detail, chapter, payload):
    arcs_by_id[str(candidate["id"])] = _merge_arc(arcs_by_id.get(str(candidate["id"])), candidate, now)
  state["character_arcs"] = sorted(
    arcs_by_id.values(),
    key=lambda item: (int(item.get("last_seen_chapter_index") or 0), float(item.get("confidence") or 0)),
    reverse=True,
  )[:_MAX_ARCS]

  contract = _model_contract_from_payload(project_detail, chapter, payload, now=now, model_source=model_source)
  contracts = [
    item
    for item in state.get("chapter_contracts", [])
    if isinstance(item, dict)
  ]
  if contract is not None:
    contracts_by_id = {
      str(item.get("id") or ""): item
      for item in contracts
      if str(item.get("id") or "").strip()
    }
    contracts_by_id[str(contract["id"])] = _merge_contract(contracts_by_id.get(str(contract["id"])), contract)
    contracts = sorted(
      contracts_by_id.values(),
      key=lambda item: int(item.get("target_chapter_index") or 0),
    )[-_MAX_CONTRACTS:]
  state["chapter_contracts"] = contracts

  contract_review = _contract_review_from_payload(chapter, payload, now=now, model_source=model_source)
  reviews = [item for item in state.get("contract_reviews", []) if isinstance(item, dict)]
  if contract_review is not None:
    reviews.append(contract_review)
  state["contract_reviews"] = reviews[-_MAX_MODEL_REVIEWS:]

  review = {
    "id": f"narrative-model-review-{hashlib.sha1(f'{now}:{model_source}'.encode('utf-8')).hexdigest()[:10]}",
    "generated_at": now,
    "status": "model",
    "model_source": model_source,
    "chapter_id": str(getattr(chapter, "id", "") or ""),
    "chapter_index": int(getattr(chapter, "index", 0) or 0),
    "summary": _compact_text(payload.get("summary") or "模型叙事审查完成。", 220),
    "debt_update_count": len(payload.get("debt_updates") or []) if isinstance(payload.get("debt_updates"), list) else 0,
    "arc_update_count": len(payload.get("character_arc_updates") or []) if isinstance(payload.get("character_arc_updates"), list) else 0,
    "contract_target_chapter_id": contract.get("target_chapter_id") if contract else "",
    "risk_notes": _string_list(payload.get("risk_notes") or payload.get("risks"), limit=8),
  }
  model_reviews = [item for item in state.get("model_reviews", []) if isinstance(item, dict)]
  model_reviews.append(review)
  state["model_reviews"] = model_reviews[-_MAX_MODEL_REVIEWS:]
  return state


def record_project_narrative_state_observation(
  project_dir: Path,
  project_detail: object,
  chapter_id: str,
  *,
  settings: Settings | None = None,
  review_error: str = "",
) -> dict[str, object]:
  chapter = _chapter_for_id(project_detail, chapter_id)
  if chapter is None:
    return load_project_narrative_state(project_dir)
  content = str(getattr(chapter, "content", "") or "")
  if not content.strip():
    return load_project_narrative_state(project_dir)

  now = _now_iso()
  state = load_project_narrative_state(project_dir)
  docs = _documents_map(project_detail)
  architecture_texts = [
    docs.get("plot_structure", ""),
    docs.get("blueprint", ""),
    docs.get("global_summary", ""),
    docs.get("character_state", ""),
  ]
  chapter_card = _build_chapter_card(project_detail, chapter)
  obsidian_records = _obsidian_records_for_chapter(project_detail, int(getattr(chapter, "index", 0) or 0))
  candidates = [
    *_candidate_debts(project_detail, None, source_name="architecture", texts=architecture_texts),
    *_candidate_debts(project_detail, chapter, source_name="chapter", texts=[content]),
    *_obsidian_constraint_debt_candidates(project_detail, chapter, chapter_card),
    *_obsidian_debt_note_candidates(project_detail, chapter, records=obsidian_records),
  ]
  debts_by_id = {
    str(item.get("id") or ""): item
    for item in state.get("debts", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  for candidate in candidates:
    debts_by_id[str(candidate["id"])] = _merge_debt(debts_by_id.get(str(candidate["id"])), candidate, now)
  _resolve_obsidian_constraint_debts(debts_by_id, chapter_card, now)

  arcs_by_id = {
    str(item.get("id") or ""): item
    for item in state.get("character_arcs", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  arc_candidates = [
    *_candidate_character_arcs(project_detail, chapter),
    *_obsidian_arc_note_candidates(project_detail, chapter, records=obsidian_records),
  ]
  for candidate in arc_candidates:
    arcs_by_id[str(candidate["id"])] = _merge_arc(arcs_by_id.get(str(candidate["id"])), candidate, now)

  chapter_cards = [
    item
    for item in state.get("chapter_cards", [])
    if isinstance(item, dict) and str(item.get("chapter_id") or item.get("id") or "") != str(chapter_card.get("chapter_id") or chapter_card.get("id") or "")
  ]
  chapter_cards.append(chapter_card)

  observation = {
    "chapter_id": chapter_id,
    "chapter_index": int(getattr(chapter, "index", 0) or 0),
    "observed_at": now,
    "debt_ids": [str(item.get("id") or "") for item in candidates if item.get("id")],
    "arc_ids": [str(item.get("id") or "") for item in arc_candidates if item.get("id")],
    "review_error": review_error.strip(),
  }
  observations = [item for item in state.get("observations", []) if isinstance(item, dict)]
  observations.append(observation)

  state["updated_at"] = now
  state["revision"] = int(state.get("revision") or 0) + 1
  state["debts"] = _sort_debts(list(debts_by_id.values()))[:_MAX_DEBTS]
  state["character_arcs"] = sorted(
    arcs_by_id.values(),
    key=lambda item: (int(item.get("last_seen_chapter_index") or 0), float(item.get("confidence") or 0)),
    reverse=True,
  )[:_MAX_ARCS]
  state["chapter_cards"] = sorted(
    chapter_cards,
    key=lambda item: int(item.get("chapter_index") or 0),
  )[-_MAX_OBSERVATIONS:]
  state["observations"] = observations[-_MAX_OBSERVATIONS:]
  if settings is not None and _model_available(settings):
    try:
      content, model_source = _invoke_narrative_editor_model(
        settings,
        _model_editor_messages(project_detail, chapter, state, review_error=review_error),
      )
      parsed = _extract_json_object(content)
      if not isinstance(parsed, dict):
        raise RuntimeError("模型叙事审查没有返回合法 JSON")
      state = _apply_model_editor_payload(
        state,
        project_detail,
        chapter,
        parsed,
        now=now,
        model_source=model_source,
      )
    except Exception as error:
      append_app_log(settings, f"narrative state model editor failed for {getattr(project_detail, 'id', '')}/{chapter_id}: {error}")
      model_reviews = [item for item in state.get("model_reviews", []) if isinstance(item, dict)]
      model_reviews.append(
        {
          "id": f"narrative-model-review-{hashlib.sha1(f'{now}:failed'.encode('utf-8')).hexdigest()[:10]}",
          "generated_at": now,
          "status": "model_failed",
          "chapter_id": chapter_id,
          "chapter_index": int(getattr(chapter, "index", 0) or 0),
          "summary": str(error),
          "risk_notes": [str(error)],
        }
      )
      state["model_reviews"] = model_reviews[-_MAX_MODEL_REVIEWS:]
  state = _auto_stage_obsidian_maintenance_drafts(project_dir, project_detail, state, now=now)
  atomic_write_json(narrative_state_path(project_dir), state)
  return state


def _line_items(items: list[str], limit: int = 6) -> list[str]:
  return [f"- {item}" for item in items[:limit] if str(item).strip()]


def _draft_frontmatter_payload(markdown: str) -> dict[str, object]:
  payload, _body = _parse_frontmatter(str(markdown or ""))
  return payload if isinstance(payload, dict) else {}


def _draft_frontmatter_key_id(value: str) -> str:
  return re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())


def _draft_frontmatter_value(payload: dict[str, object], keys: tuple[str, ...]) -> str:
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    values = _frontmatter_context_values(payload, key)
    if values:
      return values[0]
    if isinstance(value, (int, float, bool)):
      return str(value)
  return ""


def _draft_frontmatter_raw_value(payload: dict[str, object], keys: tuple[str, ...]) -> object:
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if found:
      return value
  return ""


def _draft_frontmatter_values(payload: dict[str, object], keys: tuple[str, ...], *, limit: int = 8) -> list[str]:
  values = _frontmatter_context_values(payload, *keys)
  return _ordered_unique([item for item in values if str(item).strip()])[:limit]


def _draft_frontmatter_lines(markdown: str) -> list[str]:
  lines = str(markdown or "").splitlines()
  if not lines or lines[0].strip() != "---":
    return []
  collected: list[str] = []
  for raw_line in lines[1:]:
    if raw_line.strip() == "---":
      break
    collected.append(raw_line)
  return collected


def _draft_tag_values(markdown: str, payload: dict[str, object]) -> list[str]:
  values = list(_frontmatter_tag_list(payload, *_DRAFT_TAG_LABELS))
  current_tag_key = False
  label_ids = {_draft_frontmatter_key_id(label) for label in _DRAFT_TAG_LABELS}
  for raw_line in _draft_frontmatter_lines(markdown):
    stripped = raw_line.strip()
    if not stripped or stripped.lstrip().startswith("#"):
      continue
    list_item_content = _frontmatter_list_item_content(stripped)
    if current_tag_key and list_item_content is not None:
      values.extend(_frontmatter_tag_list_from_value(list_item_content))
      continue
    pair = _parse_frontmatter_key_value(stripped)
    if not pair:
      current_tag_key = False
      continue
    key, value = pair
    if _draft_frontmatter_key_id(key) not in label_ids:
      current_tag_key = False
      continue
    values.extend(_frontmatter_tag_list_from_value(value))
    current_tag_key = not str(value).strip()
  return _ordered_unique(values)


def _draft_markdown_available_for_chapter(markdown: str, chapter_index: int) -> bool:
  if chapter_index <= 0:
    return True
  payload = _draft_frontmatter_payload(markdown)

  chapter_start = 0
  chapter_end = 0
  reveal_after = 0
  if payload:
    chapter_range = _draft_frontmatter_value(payload, _CHAPTER_RANGE_LABELS)
    if chapter_range:
      chapter_start, chapter_end = _chapter_range_from_value(chapter_range)
    start_value = _draft_frontmatter_value(payload, _CHAPTER_START_LABELS)
    if start_value:
      chapter_start = _parse_chapter_number(start_value)
    end_value = _draft_frontmatter_value(payload, _CHAPTER_END_LABELS)
    if end_value:
      chapter_end = _parse_chapter_number(end_value)
    reveal_after = _parse_chapter_number(_draft_frontmatter_value(payload, _REVEAL_AFTER_CHAPTER_LABELS))
    tag_chapter_start, tag_chapter_end, tag_reveal_after = _tags_chapter_scope(_draft_tag_values(markdown, payload))
    chapter_start = chapter_start or tag_chapter_start
    chapter_end = chapter_end or tag_chapter_end
    reveal_after = reveal_after or tag_reveal_after
  if not any([chapter_start, chapter_end, reveal_after]):
    source_chapters = _obsidian_note_source_chapters_from_markdown(markdown)
    if source_chapters:
      chapter_start = max(source_chapters)

  if reveal_after > 0 and chapter_index <= reveal_after:
    return False
  if chapter_start > 0 and chapter_index < chapter_start:
    return False
  if chapter_end > 0 and chapter_index > chapter_end:
    return False
  return True


def _pending_draft_scope_markdown(project_dir: Path | None, item: dict[str, object]) -> str:
  if project_dir is not None:
    candidate_paths: list[Path] = []
    staged_path = _safe_staged_obsidian_draft_path(project_dir, item)
    if staged_path is not None:
      candidate_paths.append(staged_path)
    fallback_name = _safe_obsidian_filename(item.get("title"), "obsidian-draft")
    for raw_path in (item.get("relative_path"), item.get("suggested_path")):
      if not str(raw_path or "").strip():
        continue
      candidate = obsidian_draft_dir(project_dir) / _safe_obsidian_draft_relative_path(raw_path, fallback_name)
      if candidate.exists() and candidate.is_file() and all(not _same_path(candidate, existing) for existing in candidate_paths):
        candidate_paths.append(candidate)
    expected_id = str(item.get("id") or "").strip()
    expected_kind = str(item.get("kind") or "").strip()
    for draft_path in candidate_paths:
      try:
        text = draft_path.read_text(encoding="utf-8")
      except OSError:
        continue
      draft_identity = _obsidian_maintenance_identity_from_markdown(text)
      if expected_id and draft_identity and draft_identity != expected_id:
        continue
      draft_kind = _obsidian_maintenance_kind_from_markdown(text)
      if expected_kind and draft_kind and draft_kind != expected_kind:
        continue
      return text
  return str(item.get("draft_markdown") or "")


def _pending_chapter_note_draft_preview(item: dict[str, object], markdown: str) -> str:
  kind = str(item.get("kind") or "")
  if kind != "create_chapter_note":
    return ""
  payload = _draft_frontmatter_payload(markdown)
  summary = _draft_frontmatter_value(payload, _OBSIDIAN_CHAPTER_NOTE_SUMMARY_KEYS)
  handoff = _draft_frontmatter_values(payload, _OBSIDIAN_CHAPTER_NOTE_HANDOFF_KEYS, limit=2)
  required_missing = _draft_frontmatter_values(
    payload,
    ("obsidian_required_missing", "required_missing", "未完成的 Obsidian 必写项", "未完成必写项"),
    limit=2,
  )
  if not summary:
    body_summary = _draft_body_section_values(markdown, _OBSIDIAN_CHAPTER_NOTE_SUMMARY_KEYS, limit=1)
    if not body_summary:
      body_summary = _draft_body_section_values(markdown, _OBSIDIAN_CHAPTER_NOTE_EXCERPT_KEYS, limit=1)
    summary = body_summary[0] if body_summary else ""
  if not handoff:
    handoff = _draft_body_section_values(markdown, _OBSIDIAN_CHAPTER_NOTE_HANDOFF_KEYS, limit=2)
  if not required_missing:
    required_missing = _draft_body_section_values(
      markdown,
      ("obsidian_required_missing", "required_missing", "未完成的 Obsidian 必写项", "未完成必写项"),
      limit=2,
    )
  detail_parts: list[str] = []
  if summary:
    detail_parts.append(f"摘要：{_compact_text(summary, 90)}")
  if handoff:
    detail_parts.append(f"交接：{' / '.join(_compact_text(item, 90) for item in handoff[:2])}")
  if required_missing:
    detail_parts.append(f"未完成：{' / '.join(_compact_text(item, 70) for item in required_missing[:2])}")
  if not detail_parts:
    return ""
  return f"；草稿预览：{'；'.join(detail_parts)}"


def _chapter_contract_draft_value(markdown: str, payload: dict[str, object], keys: tuple[str, ...]) -> str:
  value = _draft_frontmatter_value(payload, keys)
  if value:
    return value
  values = _draft_body_section_values(markdown, keys, limit=1)
  return values[0] if values else ""


def _chapter_contract_draft_values(
  markdown: str,
  payload: dict[str, object],
  keys: tuple[str, ...],
  *,
  limit: int = 2,
) -> list[str]:
  values = _draft_frontmatter_values(payload, keys, limit=limit)
  if values:
    return values
  return _draft_body_section_values(markdown, keys, limit=limit)


def _pending_draft_preview_markdowns(item: dict[str, object], markdown: str) -> list[str]:
  values: list[str] = []
  current = str(markdown or "").strip()
  if current:
    values.append(current)
  fallback = str(item.get("draft_markdown") or "").strip()
  if fallback and fallback not in values:
    values.append(fallback)
  return values


def _pending_draft_preview_value(markdowns: list[str], keys: tuple[str, ...]) -> str:
  for item in markdowns:
    payload = _draft_frontmatter_payload(item)
    value = _draft_frontmatter_value(payload, keys)
    if value:
      return value
    body_values = _draft_body_section_values(item, keys, limit=1)
    if body_values:
      return body_values[0]
  return ""


def _pending_draft_preview_values(markdowns: list[str], keys: tuple[str, ...], *, limit: int = 2) -> list[str]:
  for item in markdowns:
    payload = _draft_frontmatter_payload(item)
    values = _draft_frontmatter_values(payload, keys, limit=limit)
    if values:
      return values
    values = _draft_body_section_values(item, keys, limit=limit)
    if values:
      return values
  return []


def _pending_chapter_contract_draft_preview(item: dict[str, object], markdown: str) -> str:
  kind = str(item.get("kind") or "")
  if kind != "create_chapter_contract_note":
    return ""
  payload = _draft_frontmatter_payload(markdown)
  objective = _chapter_contract_draft_value(markdown, payload, _OBSIDIAN_CHAPTER_CONTRACT_OBJECTIVE_KEYS)
  required_beats = _chapter_contract_draft_values(markdown, payload, _OBSIDIAN_CHAPTER_CONTRACT_REQUIRED_BEATS_KEYS, limit=2)
  forbidden_moves = _chapter_contract_draft_values(markdown, payload, _OBSIDIAN_CHAPTER_CONTRACT_FORBIDDEN_MOVES_KEYS, limit=2)
  acceptance_checks = _chapter_contract_draft_values(markdown, payload, _OBSIDIAN_CHAPTER_CONTRACT_ACCEPTANCE_KEYS, limit=2)
  fallback_markdown = str(item.get("draft_markdown") or "").strip()
  if fallback_markdown and fallback_markdown != str(markdown or "").strip():
    fallback_payload = _draft_frontmatter_payload(fallback_markdown)
    if not objective:
      objective = _chapter_contract_draft_value(
        fallback_markdown,
        fallback_payload,
        _OBSIDIAN_CHAPTER_CONTRACT_OBJECTIVE_KEYS,
      )
    if not required_beats:
      required_beats = _chapter_contract_draft_values(
        fallback_markdown,
        fallback_payload,
        _OBSIDIAN_CHAPTER_CONTRACT_REQUIRED_BEATS_KEYS,
        limit=2,
      )
    if not forbidden_moves:
      forbidden_moves = _chapter_contract_draft_values(
        fallback_markdown,
        fallback_payload,
        _OBSIDIAN_CHAPTER_CONTRACT_FORBIDDEN_MOVES_KEYS,
        limit=2,
      )
    if not acceptance_checks:
      acceptance_checks = _chapter_contract_draft_values(
        fallback_markdown,
        fallback_payload,
        _OBSIDIAN_CHAPTER_CONTRACT_ACCEPTANCE_KEYS,
        limit=2,
      )
  detail_parts: list[str] = []
  if objective:
    detail_parts.append(f"目标：{_compact_text(objective, 90)}")
  if required_beats:
    detail_parts.append(f"节拍：{' / '.join(_compact_text(item, 70) for item in required_beats[:2])}")
  if forbidden_moves:
    detail_parts.append(f"禁写：{' / '.join(_compact_text(item, 70) for item in forbidden_moves[:2])}")
  if acceptance_checks:
    detail_parts.append(f"验收：{' / '.join(_compact_text(item, 70) for item in acceptance_checks[:2])}")
  if not detail_parts:
    return ""
  return f"；合同预览：{'；'.join(detail_parts)}"


def _pending_style_xp_draft_preview(item: dict[str, object], markdown: str) -> str:
  kind = str(item.get("kind") or "")
  if kind not in {"create_style_rule_note", "create_xp_rule_note"}:
    return ""
  markdowns = _pending_draft_preview_markdowns(item, markdown)
  detail_parts: list[str] = []
  if kind == "create_style_rule_note":
    rule = _pending_draft_preview_value(markdowns, _OBSIDIAN_STYLE_RULE_PREVIEW_KEYS)
    applies = _pending_draft_preview_values(markdowns, _OBSIDIAN_STYLE_APPLIES_KEYS, limit=2)
    avoid = _pending_draft_preview_values(markdowns, _OBSIDIAN_STYLE_AVOID_KEYS, limit=1)
    if rule:
      detail_parts.append(f"规则：{_compact_text(rule, 90)}")
    if applies:
      detail_parts.append(f"适用：{' / '.join(_compact_text(item, 50) for item in applies[:2])}")
    if avoid:
      detail_parts.append(f"禁用：{' / '.join(_compact_text(item, 50) for item in avoid[:1])}")
    label = "文风预览"
  else:
    rule = _pending_draft_preview_value(markdowns, _OBSIDIAN_XP_RULE_PREVIEW_KEYS)
    checks = _pending_draft_preview_values(markdowns, _OBSIDIAN_XP_CHECK_KEYS, limit=2)
    avoid = _pending_draft_preview_values(markdowns, _OBSIDIAN_XP_AVOID_KEYS, limit=1)
    if rule:
      detail_parts.append(f"规则：{_compact_text(rule, 90)}")
    if checks:
      detail_parts.append(f"检查：{' / '.join(_compact_text(item, 60) for item in checks[:2])}")
    if avoid:
      detail_parts.append(f"禁用：{' / '.join(_compact_text(item, 50) for item in avoid[:1])}")
    label = "XP预览"
  evidence = _pending_draft_preview_value(markdowns, _OBSIDIAN_STYLE_XP_EVIDENCE_KEYS)
  confidence = _pending_draft_preview_value(markdowns, _OBSIDIAN_STYLE_XP_CONFIDENCE_KEYS)
  if evidence:
    evidence_text = _compact_text(evidence, 20)
    if evidence_text and not evidence_text.endswith("条"):
      evidence_text = f"{evidence_text}条"
    detail_parts.append(f"证据：{evidence_text}")
  if confidence:
    detail_parts.append(f"置信度：{_compact_text(confidence, 20)}")
  if not detail_parts:
    return ""
  return f"；{label}：{'；'.join(detail_parts)}"


def _pending_draft_preview(item: dict[str, object], markdown: str) -> str:
  chapter_note_preview = _pending_chapter_note_draft_preview(item, markdown)
  if chapter_note_preview:
    return chapter_note_preview
  chapter_contract_preview = _pending_chapter_contract_draft_preview(item, markdown)
  if chapter_contract_preview:
    return chapter_contract_preview
  return _pending_style_xp_draft_preview(item, markdown)


def obsidian_maintenance_suggestion_preview(
  item: dict[str, object],
  project_dir: Path | None = None,
) -> str:
  scope_markdown = _pending_draft_scope_markdown(project_dir, item).strip()
  return _pending_draft_preview(item, scope_markdown) if scope_markdown else ""


def obsidian_maintenance_suggestion_available_for_chapter(
  item: dict[str, object],
  chapter_index: int = 0,
  project_dir: Path | None = None,
) -> bool:
  if chapter_index <= 0:
    return True
  scope_markdown = _pending_draft_scope_markdown(project_dir, item).strip()
  if scope_markdown:
    return _draft_markdown_available_for_chapter(scope_markdown, chapter_index)
  source_chapters: list[int] = []
  for raw in item.get("source_chapters", []) if isinstance(item.get("source_chapters"), list) else []:
    try:
      source_chapter = int(raw or 0)
    except (TypeError, ValueError):
      continue
    if source_chapter > 0 and source_chapter not in source_chapters:
      source_chapters.append(source_chapter)
  if source_chapters:
    return max(source_chapters) <= chapter_index
  return False


def _pending_draft_soft_constraint_label(kind: str) -> str:
  if kind == "create_chapter_note":
    return "章节档案"
  if kind == "create_chapter_contract_note":
    return "章节合同"
  if kind == "create_style_rule_note":
    return "文风"
  if kind == "create_xp_rule_note":
    return "XP"
  return "待审规则"


def _pending_draft_soft_constraint_detail(preview: str) -> str:
  text = str(preview or "").strip().lstrip("；").strip()
  if not text:
    return ""
  _label, separator, remainder = text.partition("：")
  return remainder.strip() if separator else text


def obsidian_pending_soft_constraint_lines(
  state: dict[str, object],
  *,
  chapter_index: int = 0,
  project_dir: Path | None = None,
  max_items: int = 4,
) -> list[str]:
  if chapter_index <= 0:
    return []
  suggestions = [item for item in state.get("obsidian_maintenance_suggestions", []) if isinstance(item, dict)]
  candidates: list[tuple[dict[str, object], str, tuple[int, int, int, str]]] = []
  for item in suggestions:
    kind = str(item.get("kind") or "")
    if kind not in {"create_chapter_note", "create_chapter_contract_note", "create_style_rule_note", "create_xp_rule_note"}:
      continue
    status = str(item.get("status") or "open")
    if status in {"published", "ignored"}:
      continue
    markdown = _pending_draft_scope_markdown(project_dir, item).strip()
    if not markdown or not _draft_markdown_available_for_chapter(markdown, chapter_index):
      continue
    preview = _pending_draft_preview(item, markdown)
    detail = _pending_draft_soft_constraint_detail(preview)
    if not detail:
      continue
    candidates.append((item, detail, obsidian_maintenance_suggestion_sort_key(item, chapter_index)))
  if not candidates:
    return []

  ranked = sorted(candidates, key=lambda entry: entry[2], reverse=True)
  selected: list[tuple[dict[str, object], str, tuple[int, int, int, str]]] = []
  selected_ids: set[str] = set()
  preferred_kinds = (
    "create_chapter_note",
    "create_chapter_contract_note",
    "create_style_rule_note",
    "create_xp_rule_note",
  )
  for kind in preferred_kinds:
    candidate = next((entry for entry in ranked if str(entry[0].get("kind") or "") == kind), None)
    if candidate is None:
      continue
    candidate_id = str(candidate[0].get("id") or "")
    if candidate_id and candidate_id in selected_ids:
      continue
    selected.append(candidate)
    if candidate_id:
      selected_ids.add(candidate_id)
    if len(selected) >= max_items:
      break
  if len(selected) < max_items:
    for candidate in ranked:
      candidate_id = str(candidate[0].get("id") or "")
      if candidate_id and candidate_id in selected_ids:
        continue
      selected.append(candidate)
      if candidate_id:
        selected_ids.add(candidate_id)
      if len(selected) >= max_items:
        break

  lines = [
    "以下内容来自待审草稿，优先级低于作者明确要求和正式 Vault 设定；只有正式资料没有覆盖时，才把它当补充提醒。",
  ]
  for item, detail, _sort_key in selected[:max_items]:
    kind = str(item.get("kind") or "")
    label = _pending_draft_soft_constraint_label(kind)
    title = _compact_text(item.get("title"), 56) or label
    source = _obsidian_maintenance_source_chapter_text(item)
    if source:
      lines.append(f"- [{label}] {title}（{source}）：{detail}")
    else:
      lines.append(f"- [{label}] {title}：{detail}")
  return lines


def _obsidian_pending_draft_lines(
  state: dict[str, object],
  max_items: int = 4,
  chapter_index: int = 0,
  project_dir: Path | None = None,
) -> list[str]:
  suggestions = [item for item in state.get("obsidian_maintenance_suggestions", []) if isinstance(item, dict)]
  selected: list[dict[str, object]] = []
  for item in suggestions:
    status = str(item.get("status") or "open")
    if status in {"published", "ignored"}:
      continue
    if not str(item.get("draft_markdown") or "").strip() and not str(item.get("draft_path") or "").strip():
      continue
    scope_markdown = _pending_draft_scope_markdown(project_dir, item).strip()
    if scope_markdown and not _draft_markdown_available_for_chapter(scope_markdown, chapter_index):
      continue
    if not scope_markdown and not obsidian_maintenance_suggestion_available_for_chapter(item, chapter_index, project_dir):
      continue
    selected.append(item)
  if not selected:
    return []
  selected.sort(key=lambda item: obsidian_maintenance_suggestion_sort_key(item, chapter_index), reverse=True)
  lines = ["待审草稿只提示资料维护状态，不能当作 Vault 正式设定引用。"]
  for item in selected[:max_items]:
    title = _compact_text(item.get("title"), 64)
    suggested_path = _compact_text(item.get("suggested_path"), 80)
    draft_path = _compact_text(item.get("draft_path"), 100)
    source_chapter_text = _obsidian_maintenance_source_chapter_text(item)
    action = _compact_text(item.get("action") or item.get("reason"), 90)
    if item.get("draft_missing"):
      status_label = "草稿文件缺失"
    elif item.get("published_missing"):
      status_label = "Vault 笔记缺失"
    elif item.get("preserved_existing_draft"):
      status_label = "保留人工草稿"
    elif item.get("manual_draft_edits"):
      status_label = "人工改动草稿"
    else:
      status_label = "自动草稿" if item.get("auto_staged") else str(item.get("status") or "待处理")
    path_text = suggested_path or draft_path
    details = "，".join(part for part in [status_label, source_chapter_text] if part)
    preview = obsidian_maintenance_suggestion_preview(item, project_dir)
    if path_text:
      suffix = f"；{action}" if action else ""
      lines.append(f"- {title}：{details}，建议笔记 {path_text}{suffix}{preview}")
    elif title:
      suffix = f"；{action}" if action else ""
      lines.append(f"- {title}：{details}{suffix}{preview}")
  return lines


def _debt_line(item: dict[str, object]) -> str:
  payoff = item.get("expected_payoff_range")
  payoff_text = ""
  if isinstance(payoff, list) and len(payoff) == 2:
    payoff_text = f"；预计第 {payoff[0]}-{payoff[1]} 章处理"
  status = str(item.get("status") or "open")
  risk = str(item.get("risk_level") or "low")
  return f"{item.get('title') or '未命名线索'}：{_compact_text(item.get('content'), 120)}（{status}/{risk}{payoff_text}）"


def _active_debts_for_chapter(state: dict[str, object], chapter_index: int) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
  debts = [item for item in state.get("debts", []) if isinstance(item, dict)]
  open_debts = [item for item in debts if str(item.get("status") or "") in {"open", "touched", "conflict", "deferred"}]
  must: list[dict[str, object]] = []
  touch: list[dict[str, object]] = []
  protect: list[dict[str, object]] = []
  for item in open_debts:
    payoff = item.get("expected_payoff_range")
    start, end = (payoff if isinstance(payoff, list) and len(payoff) == 2 else [0, 0])
    risk = str(item.get("risk_level") or "")
    if risk in {"critical", "high"} or (chapter_index and start <= chapter_index <= max(start, end)):
      must.append(item)
    elif chapter_index and start and chapter_index < start:
      protect.append(item)
    else:
      touch.append(item)
  return (_sort_debts(must)[:6], _sort_debts(touch)[:6], _sort_debts(protect)[:6])


def _arc_lines_for_prompt(state: dict[str, object], chapter_text: str, max_items: int) -> list[str]:
  arcs = [item for item in state.get("character_arcs", []) if isinstance(item, dict)]
  selected = []
  for item in arcs:
    name = str(item.get("name") or "")
    if name and name in chapter_text:
      selected.append(item)
  if not selected:
    selected = arcs[:max_items]
  lines: list[str] = []
  for item in selected[:max_items]:
    lines.append(
      f"- {item.get('name') or '人物'}：{item.get('phase') or '状态跟踪'}；"
      f"{_compact_text(item.get('unresolved_pressure'), 90)}；{_compact_text(item.get('required_next_check'), 90)}"
    )
  return lines


def _contract_prompt_lines(contract: dict[str, object]) -> list[str]:
  lines: list[str] = []
  objective = _compact_text(contract.get("objective"), 180)
  if objective:
    lines.append(f"合同目标：{objective}")
  sections = [
    ("必须完成的节拍", contract.get("required_beats")),
    ("必须推进的债务", contract.get("debts_to_advance")),
    ("不能提前揭开的债务", contract.get("debts_to_protect")),
    ("人物检查", contract.get("character_checks")),
    ("文风检查", contract.get("style_checks")),
    ("禁止动作", contract.get("forbidden_moves")),
    ("验收项", contract.get("acceptance_checks")),
  ]
  for label, value in sections:
    items = _string_list(value, limit=6)
    if not items:
      continue
    lines.append(f"{label}：")
    lines.extend(f"- {item}" for item in items)
  return lines


def _contract_review_prompt_lines(review: dict[str, object] | None) -> list[str]:
  if not review:
    return []
  lines = [
    (
      f"上一轮合同执行：{review.get('status') or '未判定'}，"
      f"评分 {int(review.get('score') or 0)}。"
    )
  ]
  missed = _string_list(review.get("missed"), limit=4)
  revision_focus = _string_list(review.get("revision_focus"), limit=4)
  if missed:
    lines.append("未满足项：")
    lines.extend(f"- {item}" for item in missed)
  if revision_focus:
    lines.append("改稿重点：")
    lines.extend(f"- {item}" for item in revision_focus)
  return lines


def build_project_narrative_state_prompt(
  project_dir: Path,
  project_detail: object,
  chapter_id: str,
  *,
  max_debts: int = 6,
  max_characters: int = 5,
) -> str:
  chapter = _chapter_for_id(project_detail, chapter_id)
  if chapter is None:
    return ""
  if _obsidian_state_enabled(project_detail):
    state = refresh_project_narrative_state_chapter_cards(
      project_dir,
      project_detail,
      persist=True,
      auto_stage_drafts=True,
    )
  else:
    state = load_project_narrative_state(project_dir)
  chapter_index = int(getattr(chapter, "index", 0) or 0) or _chapter_index_from_id(chapter_id)
  card = _build_chapter_card(project_detail, chapter)
  state = _state_with_obsidian_narrative_notes(project_detail, state, chapter)
  contract = _contract_for_chapter(state, chapter_id, chapter_index)
  contract_review = _contract_review_for_chapter(state, chapter_id, chapter_index)
  must, touch, protect = _active_debts_for_chapter(state, chapter_index)
  chapter_text = str(getattr(chapter, "content", "") or "")
  arc_lines = _arc_lines_for_prompt(state, chapter_text, max_characters)
  obsidian_pending_draft_lines = _obsidian_pending_draft_lines(
    state,
    max_items=4,
    chapter_index=chapter_index,
    project_dir=project_dir,
  )
  pending_soft_constraint_lines = obsidian_pending_soft_constraint_lines(
    state,
    chapter_index=chapter_index,
    project_dir=project_dir,
    max_items=4,
  )
  has_obsidian_guidance = any([
    card.get("obsidian_sources"),
    card.get("obsidian_external_references"),
    card.get("obsidian_required"),
    card.get("obsidian_forbidden"),
    card.get("obsidian_risks"),
    card.get("obsidian_required_satisfied"),
    card.get("obsidian_required_missing"),
    card.get("obsidian_forbidden_violations"),
    card.get("obsidian_chapter_plans"),
    card.get("obsidian_chapter_notes"),
    card.get("obsidian_narrative_debts"),
    card.get("obsidian_character_arcs"),
  ])

  if not any([
    must,
    touch,
    protect,
    arc_lines,
    obsidian_pending_draft_lines,
    pending_soft_constraint_lines,
    contract,
    contract_review,
    card.get("blueprint_anchor"),
    has_obsidian_guidance,
  ]):
    return ""

  lines = [
    "叙事状态账本：",
    (
      f"章节任务卡：第 {chapter_index}/{getattr(project_detail, 'target_chapters', 0) or '?'} 章，"
      f"阶段：{card.get('stage') or '未判定'}。"
    ),
  ]
  if card.get("blueprint_anchor"):
    lines.append(f"蓝图锚点：{card['blueprint_anchor']}")
  contract_lines = _contract_prompt_lines(contract) if contract else []
  if contract_lines:
    lines.append("章节合同：")
    lines.extend(contract_lines)
  review_lines = _contract_review_prompt_lines(contract_review)
  if review_lines:
    lines.append("合同回看：")
    lines.extend(review_lines)
  required_lines = _line_items([str(item) for item in card.get("required_outcomes", [])], 5)
  if required_lines:
    lines.append("本章任务：")
    lines.extend(required_lines)
  obsidian_chapter_plans = _obsidian_chapter_plan_prompt_lines(
    [
      item
      for item in card.get("obsidian_chapter_plans", [])
      if isinstance(item, dict)
    ]
  )
  if obsidian_chapter_plans:
    lines.append("Obsidian 章节计划：")
    lines.extend(obsidian_chapter_plans)
  obsidian_chapter_notes = _obsidian_chapter_note_prompt_lines(
    [
      item
      for item in card.get("obsidian_chapter_notes", [])
      if isinstance(item, dict)
    ]
  )
  if obsidian_chapter_notes:
    lines.append("Obsidian 章节档案：")
    lines.extend(obsidian_chapter_notes)
  obsidian_narrative_debts = _obsidian_narrative_debt_prompt_lines(
    [
      item
      for item in card.get("obsidian_narrative_debts", [])
      if isinstance(item, dict)
    ]
  )
  if obsidian_narrative_debts:
    lines.append("Obsidian 剧情债务：")
    lines.extend(obsidian_narrative_debts)
  obsidian_character_arcs = _obsidian_character_arc_prompt_lines(
    [
      item
      for item in card.get("obsidian_character_arcs", [])
      if isinstance(item, dict)
    ]
  )
  if obsidian_character_arcs:
    lines.append("Obsidian 人物弧线：")
    lines.extend(obsidian_character_arcs)
  obsidian_sources = _line_items([str(item) for item in card.get("obsidian_sources", [])], 5)
  obsidian_external_references = _line_items([str(item) for item in card.get("obsidian_external_references", [])], 5)
  obsidian_required = _line_items([str(item) for item in card.get("obsidian_required", [])], 6)
  obsidian_forbidden = _line_items([str(item) for item in card.get("obsidian_forbidden", [])], 6)
  obsidian_risks = _line_items([str(item) for item in card.get("obsidian_risks", [])], 4)
  obsidian_required_satisfied = _line_items([str(item) for item in card.get("obsidian_required_satisfied", [])], 6)
  obsidian_required_missing = _line_items([str(item) for item in card.get("obsidian_required_missing", [])], 6)
  obsidian_forbidden_violations = _line_items([str(item) for item in card.get("obsidian_forbidden_violations", [])], 6)
  if obsidian_sources:
    lines.append("Obsidian 章节来源：")
    lines.extend(obsidian_sources)
  if obsidian_external_references:
    lines.append("Obsidian 考据来源：")
    lines.extend(obsidian_external_references)
  if obsidian_required:
    lines.append("Obsidian 必写项：")
    lines.extend(obsidian_required)
  if obsidian_forbidden:
    lines.append("Obsidian 禁写项：")
    lines.extend(obsidian_forbidden)
  if obsidian_required_satisfied:
    lines.append("Obsidian 已满足必写项：")
    lines.extend(obsidian_required_satisfied)
  if obsidian_required_missing:
    lines.append("Obsidian 未完成必写项：")
    lines.extend(obsidian_required_missing)
  if obsidian_forbidden_violations:
    lines.append("Obsidian 已触犯禁写项：")
    lines.extend(obsidian_forbidden_violations)
  if obsidian_risks:
    lines.append("Obsidian 图谱风险：")
    lines.extend(obsidian_risks)
  if pending_soft_constraint_lines:
    lines.append("Obsidian 待审软约束：")
    lines.extend(pending_soft_constraint_lines)
  if obsidian_pending_draft_lines:
    lines.append("Obsidian 待审草稿：")
    lines.extend(obsidian_pending_draft_lines)
  if must:
    lines.append("本章必须处理或明确推进的剧情债务：")
    lines.extend(f"- {_debt_line(item)}" for item in must[:max_debts])
  if touch:
    lines.append("本章可轻触、但不能遗忘的剧情债务：")
    lines.extend(f"- {_debt_line(item)}" for item in touch[:max_debts])
  if protect:
    lines.append("本章不要提前揭开的剧情债务：")
    lines.extend(f"- {_debt_line(item)}" for item in protect[:max_debts])
  if arc_lines:
    lines.append("人物弧线检查：")
    lines.extend(arc_lines)
  avoid_lines = _line_items([str(item) for item in card.get("avoid", [])], 4)
  if avoid_lines:
    lines.append("避免事项：")
    lines.extend(avoid_lines)
  if card.get("next_handoff"):
    lines.append(f"下一章交接：{card['next_handoff']}")
  return "\n".join(lines).strip()
