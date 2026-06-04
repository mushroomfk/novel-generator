from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.services.obsidian_service import (
  collect_obsidian_note_records,
  obsidian_note_available_for_chapter,
  scoped_obsidian_note_records_for_chapter,
)
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_SCHEMA_VERSION = 1
_LEARNING_DIRNAME = "learning"
_STYLE_XP_EVOLUTION_FILENAME = "style_xp_evolution.json"
_ACTIVE_EVIDENCE_THRESHOLD = 2
_MAX_RULES = 120
_MAX_OBSERVATIONS = 80
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;]+")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_DIALOGUE_RE = re.compile(r"[“”]|^[^。！？!?]{1,16}[：:]")
_TENSION_TERMS = (
  "秘密",
  "真相",
  "线索",
  "疑问",
  "答案",
  "钥匙",
  "门",
  "脚步",
  "黑暗",
  "沉默",
  "没有回头",
  "不知道",
)
_OBSIDIAN_STYLE_LABELS = {
  "style",
  "stylerule",
  "stylerules",
  "styleguide",
  "styleguides",
  "voice",
  "tone",
  "authorstyle",
  "writingrule",
  "writingrules",
  "writingguide",
  "writingguides",
  "writingpreference",
  "writingpreferences",
  "preference",
  "preferences",
  "文风",
  "文风规则",
  "风格",
  "风格规则",
  "语气",
  "写作规则",
  "写作偏好",
  "作者偏好",
}
_OBSIDIAN_XP_LABELS = {
  "xp",
  "xprule",
  "xprules",
  "experience",
  "experiences",
  "writingxp",
  "xp规则",
  "经验",
  "经验规则",
  "写作经验",
}
_OBSIDIAN_STYLE_GUIDANCE_LABELS = (
  "文风规则",
  "句式节奏",
  "意象与感官",
  "对白规则",
  "禁用写法",
  "示例",
  "适用场景",
)
_OBSIDIAN_XP_GUIDANCE_LABELS = (
  "XP 规则",
  "生成前检查",
  "生成后检查",
  "推进方法",
  "禁用做法",
  "示例",
)
_OBSIDIAN_GUIDANCE_KEY_RE = re.compile(r"^\s*([^：:]{1,24})\s*[：:]\s*(.*)$")
_OBSIDIAN_GUIDANCE_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)]|[（(]?\d+[）)])\s*(.+?)\s*$")


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: object, limit: int = 160) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}..."


def _normalized_label(value: object) -> str:
  return re.sub(r"[\s_\-/#.]+", "", str(value or "").strip().lower())


def _int_note_attr(item: object, name: str) -> int:
  try:
    return int(getattr(item, name, 0) or 0)
  except (TypeError, ValueError):
    return 0


def _note_has_chapter_scope(item: object) -> bool:
  return any(
    _int_note_attr(item, name) > 0
    for name in ("chapter_start", "chapter_end", "reveal_after_chapter")
  )


def _obsidian_style_xp_chapter_score(item: object, chapter_index: int) -> int:
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0
  if target <= 0:
    return 0

  chapter_start = _int_note_attr(item, "chapter_start")
  chapter_end = _int_note_attr(item, "chapter_end")
  reveal_after = _int_note_attr(item, "reveal_after_chapter")
  source_chapters = sorted({
    int(value)
    for value in list(getattr(item, "source_chapters", []) or [])
    if str(value).strip().isdigit() and int(value) > 0
  })
  score = 0

  if chapter_start > 0 and chapter_end > 0 and chapter_start <= target <= chapter_end:
    span = max(1, chapter_end - chapter_start + 1)
    score = max(score, 520 if span == 1 else max(360, 500 - min(span, 120)))
  elif chapter_start > 0 and chapter_end <= 0 and target >= chapter_start:
    distance = target - chapter_start
    score = max(score, max(260, 420 - min(distance * 8, 120)))
  elif chapter_end > 0 and target <= chapter_end:
    distance = chapter_end - target
    score = max(score, max(140, 260 - min(distance * 8, 100)))

  if reveal_after > 0 and target > reveal_after:
    distance = target - reveal_after - 1
    score = max(score, max(220, 360 - min(distance * 8, 120)))

  if source_chapters:
    nearest = min(abs(target - value) for value in source_chapters)
    if target in source_chapters:
      score = max(score, 300)
    elif target > min(source_chapters):
      score = max(score, max(120, 240 - min(nearest * 10, 120)))

  return score


def _obsidian_note_labels(item: object) -> list[str]:
  relative_path = str(getattr(item, "relative_path", "") or "").strip().replace("\\", "/")
  path_parts = [part for part in relative_path.split("/") if part]
  stem = Path(relative_path).stem if relative_path else ""
  return [
    str(getattr(item, "note_type", "") or ""),
    str(getattr(item, "title", "") or ""),
    stem,
    *path_parts,
    *[str(value) for value in list(getattr(item, "tags", []) or [])],
  ]


def _obsidian_style_xp_kind(item: object) -> str:
  labels = [_normalized_label(label) for label in _obsidian_note_labels(item)]
  if any(label in _OBSIDIAN_XP_LABELS for label in labels):
    return "xp"
  if any(label in _OBSIDIAN_STYLE_LABELS for label in labels):
    return "style"
  return ""


def obsidian_style_xp_note_kind(item: object) -> str:
  return _obsidian_style_xp_kind(item)


def _obsidian_notes_for_style_xp(
  project_dir: Path,
  project_detail: object | None,
  chapter_index: int,
) -> list[tuple[object, str]]:
  if project_detail is None:
    return []
  obsidian = getattr(getattr(project_detail, "story_overview", None), "obsidian", None)
  overview_notes = list(getattr(obsidian, "notes", []) or [])
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0

  if target > 0:
    try:
      return [(record.summary, record.content or record.body or "") for record in scoped_obsidian_note_records_for_chapter(project_dir, target)]
    except Exception:
      return [(item, "") for item in overview_notes if obsidian_note_available_for_chapter(item, target)]

  try:
    return [
      (record.summary, record.content or record.body or "")
      for record in collect_obsidian_note_records(project_dir)[0]
      if not _note_has_chapter_scope(record.summary)
    ]
  except Exception:
    return [(item, "") for item in overview_notes if not _note_has_chapter_scope(item)]


def _structured_guidance_lines(text: str, labels: tuple[str, ...], limit: int = 7) -> list[str]:
  label_by_key = {_normalized_label(label): label for label in labels}
  lines: list[str] = []
  active_label = ""
  for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
    cleaned = raw_line.strip()
    if not cleaned:
      active_label = ""
      continue
    if cleaned.startswith("#"):
      active_label = ""
      continue
    match = _OBSIDIAN_GUIDANCE_KEY_RE.match(cleaned)
    if match:
      label_key = _normalized_label(match.group(1))
      label = label_by_key.get(label_key)
      if label:
        value = _compact_text(match.group(2), 180)
        if value:
          lines.append(f"{label}：{value}")
          active_label = ""
        else:
          active_label = label
      else:
        active_label = ""
      if len(lines) >= limit:
        break
      continue
    if active_label:
      bullet = _OBSIDIAN_GUIDANCE_BULLET_RE.match(cleaned)
      value = _compact_text((bullet.group(1) if bullet else cleaned), 180)
      if value:
        lines.append(f"{active_label}：{value}")
      if len(lines) >= limit:
        break
  return lines[:limit]


def _obsidian_note_guidance(item: object, content: str = "") -> str:
  kind = _obsidian_style_xp_kind(item)
  summary = _compact_text(str(getattr(item, "summary", "") or "").strip(), 180)
  preview = _compact_text(str(getattr(item, "preview", "") or "").strip(), 260)
  guidance_labels = _OBSIDIAN_XP_GUIDANCE_LABELS if kind == "xp" else _OBSIDIAN_STYLE_GUIDANCE_LABELS
  structured = _structured_guidance_lines(content, guidance_labels)
  required = [
    str(value).strip()
    for value in list(getattr(item, "required_phrases", []) or [])
    if str(value).strip()
  ][:4]
  forbidden = [
    str(value).strip()
    for value in list(getattr(item, "forbidden_phrases", []) or [])
    if str(value).strip()
  ][:4]
  parts: list[str] = []
  if summary:
    parts.append(summary)
  for line in structured:
    if not any(line == part or line in part for part in parts):
      parts.append(line)
  if not structured and preview and preview != summary:
    extra = preview
    if summary and preview.startswith(summary):
      extra = preview[len(summary):].strip(" ：:；;，,。.-")
    if extra and not any(extra == part or extra in part for part in parts):
      parts.append(extra)
  if not parts and preview:
    parts.append(preview)
  if required:
    parts.append(f"必须保留：{' / '.join(required)}")
  if forbidden:
    parts.append(f"避免出现：{' / '.join(forbidden)}")
  return "；".join(part for part in parts if part).strip()


def _obsidian_style_xp_prompt_lines(
  project_dir: Path,
  project_detail: object | None,
  chapter_index: int,
  *,
  max_notes: int = 6,
) -> list[str]:
  candidates: list[tuple[str, object, str, int, int]] = []
  seen: set[str] = set()
  for order, (item, content) in enumerate(_obsidian_notes_for_style_xp(project_dir, project_detail, chapter_index)):
    kind = _obsidian_style_xp_kind(item)
    if not kind:
      continue
    guidance = _obsidian_note_guidance(item, content)
    if not guidance:
      continue
    key = str(getattr(item, "source_key", "") or "").strip()
    if not key:
      key = str(getattr(item, "relative_path", "") or "").strip()
    if not key:
      key = str(getattr(item, "title", "") or "").strip()
    if key and key in seen:
      continue
    if key:
      seen.add(key)
    score = _obsidian_style_xp_chapter_score(item, chapter_index)
    candidates.append((kind, item, guidance, score, order))

  ranked = sorted(candidates, key=lambda item: (-item[3], item[4]))
  selected: list[tuple[str, object, str, int, int]] = []
  selected_keys: set[str] = set()

  def candidate_key(candidate: tuple[str, object, str, int, int]) -> str:
    _kind, item, _guidance, _score, order = candidate
    return (
      str(getattr(item, "source_key", "") or "").strip()
      or str(getattr(item, "relative_path", "") or "").strip()
      or str(getattr(item, "title", "") or "").strip()
      or str(order)
    )

  def add_candidate(candidate: tuple[str, object, str, int, int]) -> None:
    if len(selected) >= max_notes:
      return
    key = candidate_key(candidate)
    if key in selected_keys:
      return
    selected.append(candidate)
    selected_keys.add(key)

  if max_notes >= 2:
    for kind in ("style", "xp"):
      best = next((candidate for candidate in ranked if candidate[0] == kind), None)
      if best is not None:
        add_candidate(best)
  for candidate in ranked:
    add_candidate(candidate)
    if len(selected) >= max_notes:
      break

  selected.sort(key=lambda item: (-item[3], item[4]))

  if not selected:
    return []

  lines = [
    "Obsidian 文风 / XP 参考：",
    "以下内容来自目标章节可见的 Vault 笔记，优先级低于作者明确要求、手工文风和手工 XP。",
  ]
  for kind, item, guidance, _score, _order in selected:
    label = "文风" if kind == "style" else "XP"
    title = str(getattr(item, "title", "") or "").strip()
    relative_path = str(getattr(item, "relative_path", "") or "").strip()
    source = title or Path(relative_path).stem or relative_path or "未命名笔记"
    if relative_path and relative_path != source:
      source = f"{source}（{relative_path}）"
    lines.append(f"- [{label}] {source}：{guidance}")
  return lines


def build_obsidian_style_xp_reference_prompt(
  project_dir: Path,
  *,
  project_detail: object | None = None,
  chapter_index: int = 0,
  max_obsidian_notes: int = 6,
) -> str:
  lines = _obsidian_style_xp_prompt_lines(
    project_dir,
    project_detail,
    chapter_index,
    max_notes=max_obsidian_notes,
  )
  return "\n".join(lines).strip()


def style_xp_evolution_path(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / _LEARNING_DIRNAME / _STYLE_XP_EVOLUTION_FILENAME


def _default_state() -> dict[str, object]:
  return {
    "schema_version": _SCHEMA_VERSION,
    "updated_at": "",
    "active_version": 0,
    "rules": [],
    "observations": [],
  }


def _normalize_state(payload: object) -> dict[str, object]:
  if not isinstance(payload, dict):
    return _default_state()
  state = _default_state()
  state.update(payload)
  if not isinstance(state.get("rules"), list):
    state["rules"] = []
  if not isinstance(state.get("observations"), list):
    state["observations"] = []
  try:
    state["active_version"] = int(state.get("active_version") or 0)
  except (TypeError, ValueError):
    state["active_version"] = 0
  state["schema_version"] = _SCHEMA_VERSION
  return state


def load_project_style_xp_state(project_dir: Path) -> dict[str, object]:
  path = style_xp_evolution_path(project_dir)
  try:
    return _normalize_state(read_json(path, _default_state()))
  except Exception:
    return _default_state()


def _body_text(text: str) -> str:
  return _MARKDOWN_HEADING_RE.sub("", text or "").strip()


def _word_count(text: str) -> int:
  return len(_WORD_RE.findall(text or ""))


def _text_stats(text: str) -> dict[str, object]:
  body = _body_text(text)
  paragraphs = [item.strip() for item in body.splitlines() if item.strip()]
  sentences = [item.strip() for item in _SENTENCE_SPLIT_RE.split(body) if item.strip()]
  sentence_lengths = [_word_count(item) for item in sentences if _word_count(item) > 0]
  paragraph_lengths = [_word_count(item) for item in paragraphs if _word_count(item) > 0]
  dialogue_lines = [item for item in paragraphs if _DIALOGUE_RE.search(item)]
  avg_sentence_length = round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 1)
  avg_paragraph_length = round(sum(paragraph_lengths) / max(len(paragraph_lengths), 1), 1)
  short_sentence_ratio = round(
    len([item for item in sentence_lengths if item <= 24]) / max(len(sentence_lengths), 1),
    3,
  )
  dialogue_ratio = round(len(dialogue_lines) / max(len(paragraphs), 1), 3)
  question_ratio = round(
    len([item for item in re.findall(r"[？?]", body)]) / max(len(sentences), 1),
    3,
  )
  ending = _compact_text(body[-180:], 180)
  return {
    "char_count": len(body),
    "sentence_count": len(sentence_lengths),
    "paragraph_count": len(paragraph_lengths),
    "avg_sentence_length": avg_sentence_length,
    "short_sentence_ratio": short_sentence_ratio,
    "dialogue_ratio": dialogue_ratio,
    "avg_paragraph_length": avg_paragraph_length,
    "question_ratio": question_ratio,
    "ending_has_tension": any(term in ending for term in _TENSION_TERMS) or ending.endswith(("？", "?")),
  }


def _rule_id(kind: str, signal: str, content: str) -> str:
  digest = hashlib.sha1(f"{kind}\n{signal}\n{content}".encode("utf-8")).hexdigest()[:10]
  return f"{kind}-{signal}-{digest}"


def _candidate_rule(
  *,
  kind: str,
  signal: str,
  content: str,
  rationale: str,
  confidence: float,
  metadata: dict[str, object] | None = None,
) -> dict[str, object]:
  return {
    "id": _rule_id(kind, signal, content),
    "kind": kind,
    "signal": signal,
    "content": content,
    "rationale": rationale,
    "confidence": max(0.0, min(1.0, float(confidence))),
    "metadata": metadata or {},
  }


def _stats_rules(stats: dict[str, object]) -> list[dict[str, object]]:
  avg_sentence = float(stats.get("avg_sentence_length") or 0)
  short_ratio = float(stats.get("short_sentence_ratio") or 0)
  dialogue_ratio = float(stats.get("dialogue_ratio") or 0)
  paragraph_avg = float(stats.get("avg_paragraph_length") or 0)
  rules: list[dict[str, object]] = []

  if avg_sentence and avg_sentence <= 24 and short_ratio >= 0.45:
    rules.append(
      _candidate_rule(
        kind="style",
        signal="sentence_rhythm_short",
        content="正文适合用短句推进动作和感知，解释放在场景之后。",
        rationale=f"平均句长约 {avg_sentence} 字，短句占比 {int(short_ratio * 100)}%。",
        confidence=0.58 + min(short_ratio, 0.35),
      )
    )
  elif avg_sentence >= 42:
    rules.append(
      _candidate_rule(
        kind="style",
        signal="sentence_rhythm_long",
        content="正文可以保留较长叙述句，用环境观察和心理变化连住场面。",
        rationale=f"平均句长约 {avg_sentence} 字。",
        confidence=0.62,
      )
    )

  if dialogue_ratio >= 0.28:
    rules.append(
      _candidate_rule(
        kind="style",
        signal="dialogue_forward",
        content="对白可以承担推进功能，每段对白旁边保留动作或心理反应。",
        rationale=f"对白段落占比约 {int(dialogue_ratio * 100)}%。",
        confidence=0.64,
      )
    )
  elif stats.get("paragraph_count", 0) and dialogue_ratio <= 0.08:
    rules.append(
      _candidate_rule(
        kind="xp",
        signal="dialogue_review",
        content="生成后检查对白是否过少；信息量高的段落需要动作、场景变化或人物反应承接。",
        rationale=f"对白段落占比约 {int(dialogue_ratio * 100)}%。",
        confidence=0.56,
      )
    )

  if paragraph_avg and paragraph_avg <= 80:
    rules.append(
      _candidate_rule(
        kind="style",
        signal="paragraph_short",
        content="段落宜短，单段只承载一个动作、发现或情绪变化。",
        rationale=f"平均段落长度约 {paragraph_avg} 字。",
        confidence=0.6,
      )
    )
  elif paragraph_avg >= 180:
    rules.append(
      _candidate_rule(
        kind="style",
        signal="paragraph_long",
        content="段落可以承载较长观察和心理铺陈，但需要避免重复解释。",
        rationale=f"平均段落长度约 {paragraph_avg} 字。",
        confidence=0.6,
      )
    )

  if stats.get("ending_has_tension") or float(stats.get("question_ratio") or 0) >= 0.08:
    rules.append(
      _candidate_rule(
        kind="style",
        signal="ending_pressure",
        content="章节末尾适合保留未解问题或线索压力，不急于说明真相。",
        rationale="章节结尾或问句中出现悬疑压力信号。",
        confidence=0.66,
      )
    )

  return rules


def _review_for_chapter(project_detail: object, chapter_id: str) -> object | None:
  overview = getattr(project_detail, "story_overview", None)
  for item in getattr(overview, "chapter_reviews", []) or []:
    if str(getattr(item, "chapter_id", "") or "") == chapter_id:
      return item
  return None


def _dimension(review: object | None, dimension_id: str) -> object | None:
  if review is None:
    return None
  for item in getattr(review, "dimensions", []) or []:
    if str(getattr(item, "id", "") or "") == dimension_id:
      return item
  return None


def _review_rules(review: object | None, *, style_name: str, review_error: str) -> list[dict[str, object]]:
  rules: list[dict[str, object]] = []
  clean_style_name = style_name.strip()
  style_dimension = _dimension(review, "style")
  if clean_style_name and style_dimension is not None:
    score = int(getattr(style_dimension, "score", 0) or 0)
    status = str(getattr(style_dimension, "status", "") or "")
    if status == "good" or score >= 78:
      rules.append(
        _candidate_rule(
          kind="style",
          signal=f"style_review_pass:{clean_style_name}",
          content=f"文风方案“{clean_style_name}”可作为生成参照，后续正文保持已通过核验的句长、对白密度和意象分布。",
          rationale=str(getattr(style_dimension, "summary", "") or "文风核验结果较好。"),
          confidence=0.78,
          metadata={"style_name": clean_style_name, "review_score": score, "review_status": status},
        )
      )
    elif status in {"watch", "risk"} and score and score < 70:
      issues = getattr(style_dimension, "issues", []) or []
      issue_text = _compact_text("；".join(str(getattr(item, "title", "") or "") for item in issues if getattr(item, "title", "")), 120)
      if issue_text:
        rules.append(
          _candidate_rule(
            kind="xp",
            signal=f"style_review_risk:{clean_style_name}",
            content=f"生成后检查文风方案“{clean_style_name}”的偏离项：{issue_text}。",
            rationale=str(getattr(style_dimension, "summary", "") or "文风核验提示需要关注。"),
            confidence=0.72,
            metadata={"style_name": clean_style_name, "review_score": score, "review_status": status},
          )
        )

  if review is not None:
    status = str(getattr(review, "status", "") or "")
    suggestions = [str(item).strip() for item in getattr(review, "suggestions", []) or [] if str(item).strip()]
    if status == "risk" and suggestions:
      rules.append(
        _candidate_rule(
          kind="xp",
          signal="chapter_review_risk",
          content=f"生成后优先检查章节核验建议：{_compact_text('；'.join(suggestions[:2]), 140)}。",
          rationale=str(getattr(review, "summary", "") or "章节核验存在风险项。"),
          confidence=0.74,
          metadata={"review_status": status, "review_score": int(getattr(review, "overall_score", 0) or 0)},
        )
      )

  if review_error.strip():
    rules.append(
      _candidate_rule(
        kind="xp",
        signal="review_failed",
        content="章节保存后如果核验不可用，需要在下次生成前检查正文长度、连续性和文风约束。",
        rationale=_compact_text(review_error, 140),
        confidence=0.55,
      )
    )
  return rules


def _xp_rules(xp_preset: str) -> list[dict[str, object]]:
  clean_name = xp_preset.strip()
  if not clean_name:
    return []
  return [
    _candidate_rule(
      kind="xp",
      signal=f"xp_used:{clean_name}",
      content=f"使用 XP“{clean_name}”的章节，生成后检查该 XP 的目标是否体现在场景推进、信息揭示和章尾压力里。",
      rationale=f"章节保存时绑定 XP“{clean_name}”。",
      confidence=0.6,
      metadata={"xp_preset": clean_name},
    )
  ]


def _chapter_for_id(project_detail: object, chapter_id: str) -> object | None:
  for item in getattr(project_detail, "chapters", []) or []:
    if str(getattr(item, "id", "") or "") == chapter_id:
      return item
  return None


def _merge_rule(
  existing: dict[str, object] | None,
  candidate: dict[str, object],
  *,
  chapter_id: str,
  now: str,
) -> dict[str, object]:
  if existing is None:
    source_ids = [chapter_id]
    return {
      "id": candidate["id"],
      "kind": candidate["kind"],
      "signal": candidate["signal"],
      "content": candidate["content"],
      "rationale": candidate["rationale"],
      "status": "observed",
      "confidence": candidate["confidence"],
      "evidence_count": 1,
      "source_chapter_ids": source_ids,
      "created_at": now,
      "last_seen_at": now,
      "activated_at": "",
      "metadata": candidate.get("metadata") or {},
    }

  source_ids = [str(item) for item in existing.get("source_chapter_ids", []) if str(item).strip()]
  if chapter_id not in source_ids:
    source_ids.append(chapter_id)
  previous_confidence = float(existing.get("confidence") or 0)
  next_confidence = float(candidate.get("confidence") or 0)
  existing["confidence"] = round(max(previous_confidence, next_confidence), 3)
  existing["rationale"] = candidate.get("rationale") or existing.get("rationale") or ""
  existing["source_chapter_ids"] = source_ids
  existing["evidence_count"] = len(source_ids)
  existing["last_seen_at"] = now
  metadata = existing.get("metadata")
  if not isinstance(metadata, dict):
    metadata = {}
  metadata.update(candidate.get("metadata") or {})
  existing["metadata"] = metadata
  return existing


def record_project_style_xp_observation(
  project_dir: Path,
  project_detail: object,
  chapter_id: str,
  *,
  style_name: str = "",
  xp_preset: str = "",
  review_error: str = "",
) -> dict[str, object]:
  chapter = _chapter_for_id(project_detail, chapter_id)
  content = str(getattr(chapter, "content", "") or "") if chapter is not None else ""
  if not content.strip():
    return load_project_style_xp_state(project_dir)

  now = _now_iso()
  state = load_project_style_xp_state(project_dir)
  stats = _text_stats(content)
  review = _review_for_chapter(project_detail, chapter_id)
  candidates = [
    *_stats_rules(stats),
    *_review_rules(review, style_name=style_name, review_error=review_error),
    *_xp_rules(xp_preset),
  ]
  if not candidates:
    return state

  rules_by_id = {
    str(item.get("id") or ""): item
    for item in state.get("rules", [])
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  active_version_changed = False
  candidate_ids: list[str] = []
  for candidate in candidates:
    rule_id = str(candidate.get("id") or "")
    if not rule_id:
      continue
    previous_status = str(rules_by_id.get(rule_id, {}).get("status", "") or "")
    merged = _merge_rule(rules_by_id.get(rule_id), candidate, chapter_id=chapter_id, now=now)
    if int(merged.get("evidence_count") or 0) >= _ACTIVE_EVIDENCE_THRESHOLD and str(merged.get("status") or "") != "active":
      merged["status"] = "active"
      merged["activated_at"] = now
      active_version_changed = True
    elif previous_status == "active":
      merged["status"] = "active"
    rules_by_id[rule_id] = merged
    candidate_ids.append(rule_id)

  observations = [
    item
    for item in state.get("observations", [])
    if isinstance(item, dict) and str(item.get("chapter_id") or "") != chapter_id
  ]
  observations.append(
    {
      "chapter_id": chapter_id,
      "observed_at": now,
      "style_name": style_name.strip(),
      "xp_preset": xp_preset.strip(),
      "review_error": review_error.strip(),
      "stats": stats,
      "rule_ids": candidate_ids,
    }
  )

  rules = sorted(
    rules_by_id.values(),
    key=lambda item: (
      0 if str(item.get("status") or "") == "active" else 1,
      -int(item.get("evidence_count") or 0),
      -float(item.get("confidence") or 0),
      str(item.get("last_seen_at") or ""),
    ),
  )[:_MAX_RULES]

  state["updated_at"] = now
  state["rules"] = rules
  state["observations"] = observations[-_MAX_OBSERVATIONS:]
  if active_version_changed:
    state["active_version"] = int(state.get("active_version") or 0) + 1

  atomic_write_json(style_xp_evolution_path(project_dir), state)
  return state


def build_project_style_xp_prompt(
  project_dir: Path,
  *,
  task_key: str = "chapter",
  max_rules: int = 8,
  project_detail: object | None = None,
  chapter_index: int = 0,
  max_obsidian_notes: int = 6,
) -> str:
  if task_key not in {"chapter", "polish", "finalize", "humanize", "blueprint", "brainstorm"}:
    return ""
  state = load_project_style_xp_state(project_dir)
  rules = [
    item
    for item in state.get("rules", [])
    if isinstance(item, dict) and str(item.get("status") or "") == "active" and str(item.get("content") or "").strip()
  ]
  sections: list[str] = []
  if rules:
    ordered = sorted(
      rules,
      key=lambda item: (
        -int(item.get("evidence_count") or 0),
        -float(item.get("confidence") or 0),
        str(item.get("kind") or ""),
        str(item.get("content") or ""),
      ),
    )[:max_rules]
    lines = [
      "系统学习版文风 / XP：",
      "以下规则来自项目已保存章节和核验记录，优先级低于作者明确要求、手工文风和手工 XP。",
    ]
    for item in ordered:
      label = "文风" if str(item.get("kind") or "") == "style" else "XP"
      evidence = int(item.get("evidence_count") or 0)
      lines.append(f"- [{label}] {str(item.get('content') or '').strip()}（证据章节 {evidence} 个）")
    sections.append("\n".join(lines))

  obsidian_text = build_obsidian_style_xp_reference_prompt(
    project_dir,
    project_detail=project_detail,
    chapter_index=chapter_index,
    max_obsidian_notes=max_obsidian_notes,
  )
  if obsidian_text:
    sections.append(obsidian_text)
  return "\n\n".join(sections).strip()
