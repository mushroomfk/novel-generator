from __future__ import annotations

from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  KnowledgeMaterial,
  KnowledgeSearchResult,
  StyleDetail,
  StyleReferenceImportRequest,
  StyleSaveRequest,
  StyleSummary,
)
from novel_backend.services.config_service import styles_dir
from novel_backend.services.embedding_service import cosine_similarity, embed_texts, embedding_config_signature
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")
_TOKEN_STOPWORDS = {
  "现在",
  "当前",
  "作者",
  "参考",
  "这个",
  "那个",
  "已经",
  "还是",
  "因为",
  "所以",
  "没有",
  "一种",
  "一种",
  "他们",
  "自己",
  "我们",
  "这里",
}


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: str, limit: int = 180) -> str:
  normalized = " ".join(text.split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _reference_texts(rows: list[dict[str, object]]) -> list[str]:
  texts: list[str] = []
  for row in rows:
    text = " ".join(str(row.get("content") or "").split()).strip()
    if len(text) >= 12:
      texts.append(text)
  return texts


def _top_reference_tokens(texts: list[str], limit: int = 4) -> list[str]:
  counts: dict[str, int] = {}
  for text in texts:
    for token in _TOKEN_RE.findall(text):
      if token in _TOKEN_STOPWORDS:
        continue
      counts[token] = counts.get(token, 0) + 1
  ordered = sorted(counts.items(), key=lambda item: (item[1], len(item[0]), item[0]), reverse=True)
  return [token for token, _count in ordered[:limit]]


def _build_reference_distillate(rows: list[dict[str, object]]) -> str:
  texts = _reference_texts(rows)
  if not texts:
    return ""

  sentences = [
    item.strip()
    for item in _SENTENCE_RE.findall("\n".join(texts))
    if len(item.strip(" ，。！？!?；;")) >= 4
  ]
  if not sentences:
    return ""

  sentence_lengths = [len(re.sub(r"\s+", "", sentence)) for sentence in sentences]
  avg_sentence_length = round(sum(sentence_lengths) / len(sentence_lengths), 1)
  short_sentence_ratio = round(sum(1 for value in sentence_lengths if value <= 18) / len(sentence_lengths), 2)
  question_ratio = round(sum(1 for sentence in sentences if "？" in sentence or "?" in sentence) / len(sentences), 2)
  dialogue_ratio = round(sum(text.count("“") + text.count("\"") for text in texts) / max(len(sentences), 1), 2)
  imagery = _top_reference_tokens(texts)

  rhythm_label = "短句推进" if avg_sentence_length <= 22 or short_sentence_ratio >= 0.58 else "铺陈偏长"
  dialogue_label = "对白承担推进" if dialogue_ratio >= 0.35 else "动作和景物承担推进"
  tension_label = "适合保留追问和悬念" if question_ratio >= 0.12 else "更适合冷静压住解释"

  lines = [
    f"- 节奏参考：平均句长约 {avg_sentence_length} 字，短句占比 {int(short_sentence_ratio * 100)}%，整体偏 {rhythm_label}。",
    f"- 推进方式：{dialogue_label}。",
    f"- 信息释放：{tension_label}。",
  ]
  if imagery:
    lines.append(f"- 高频词场：{' / '.join(imagery)}。")
  return "\n".join(lines)


def _style_path(settings: Settings, name: str) -> Path:
  return styles_dir(settings) / f"{name}.json"


def _style_refs_dir(settings: Settings, name: str) -> Path:
  return styles_dir(settings) / f"{name}_refs"


def _style_reference_content_hash(title: str, content: str) -> str:
  payload = f"{title.strip()}::{content.strip()}".encode("utf-8")
  return sha1(payload).hexdigest()


def _style_reference_rows(settings: Settings, name: str) -> list[dict[str, object]]:
  refs_dir = _style_refs_dir(settings, name)
  if not refs_dir.exists():
    return []

  rows: list[dict[str, object]] = []
  for path in sorted(refs_dir.glob("*.json")):
    payload = read_json(path, {})
    if not isinstance(payload, dict):
      continue
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title or not content:
      continue
    rows.append(
      {
        "path": path,
        "payload": payload,
        "filename": path.name,
        "title": title,
        "content": content,
        "updated_at": str(payload.get("updated_at") or "") or None,
        "content_hash": str(payload.get("content_hash") or "") or _style_reference_content_hash(title, content),
        "embedding_signature": str(payload.get("embedding_signature") or ""),
        "embedding_vector": payload.get("embedding_vector"),
        "vector_norm": float(payload.get("vector_norm") or 0.0),
      }
    )
  return rows


def _sync_style_reference_vectors(settings: Settings, rows: list[dict[str, object]]) -> list[dict[str, object]]:
  embedding_signature = embedding_config_signature(settings)
  if not embedding_signature.endswith("ready"):
    return rows

  stale_rows = [
    row for row in rows
    if row["embedding_signature"] != embedding_signature
    or row["content_hash"] != _style_reference_content_hash(str(row["title"]), str(row["content"]))
    or not isinstance(row["embedding_vector"], list)
  ]
  if not stale_rows:
    return rows

  try:
    vectors = embed_texts(
      settings,
      [str(row["content"]) for row in stale_rows],
      task_name="style_reference_embedding",
    )
  except Exception:
    return rows

  for row, vector in zip(stale_rows, vectors):
    norm = float(sum(item * item for item in vector) ** 0.5)
    row["content_hash"] = _style_reference_content_hash(str(row["title"]), str(row["content"]))
    row["embedding_signature"] = embedding_signature
    row["embedding_vector"] = vector
    row["vector_norm"] = norm
    payload = dict(row["payload"])
    payload.update(
      {
        "content_hash": row["content_hash"],
        "embedding_signature": embedding_signature,
        "embedding_vector": vector,
        "vector_norm": norm,
      }
    )
    atomic_write_json(Path(row["path"]), payload)
  return rows


def _keyword_search_style_references(rows: list[dict[str, object]], query: str, limit: int) -> list[dict[str, object]]:
  normalized = " ".join(query.split()).strip().lower()
  if not normalized:
    return []
  tokens = [item for item in normalized.split() if item]
  if not tokens:
    tokens = [normalized]

  matches: list[dict[str, object]] = []
  for row in rows:
    haystack = f"{row['title']} {row['content']}".lower()
    score = 0.0
    for token in tokens:
      if token in str(row["title"]).lower():
        score += 2.0
      if token in haystack:
        score += 1.0
    if score <= 0:
      continue
    matches.append(
      {
        "filename": str(row["filename"]),
        "section": str(row["title"]),
        "preview": _compact_text(str(row["content"]), 180),
        "score": score,
        "match_type": "keyword",
      }
    )
  matches.sort(key=lambda item: (float(item["score"]), item["section"]), reverse=True)
  return matches[:limit]


def _semantic_search_style_references(settings: Settings, rows: list[dict[str, object]], query: str, limit: int) -> list[dict[str, object]]:
  ready_rows = [
    row for row in rows
    if isinstance(row.get("embedding_vector"), list) and float(row.get("vector_norm") or 0.0) > 0
  ]
  if not ready_rows:
    return []

  try:
    query_vectors = embed_texts(settings, [query], task_name="style_reference_query")
  except Exception:
    return []
  if not query_vectors:
    return []

  query_vector = query_vectors[0]
  query_norm = float(sum(value * value for value in query_vector) ** 0.5)
  if query_norm <= 0:
    return []

  matches: list[dict[str, object]] = []
  for row in ready_rows:
    vector = [float(item) for item in row["embedding_vector"]]
    score = cosine_similarity(query_vector, vector, query_norm, float(row["vector_norm"]))
    if score <= 0:
      continue
    matches.append(
      {
        "filename": str(row["filename"]),
        "section": str(row["title"]),
        "preview": _compact_text(str(row["content"]), 180),
        "score": score,
        "match_type": "semantic",
      }
    )
  matches.sort(key=lambda item: float(item["score"]), reverse=True)
  return matches[:limit]


def _style_or_404(settings: Settings, name: str) -> StyleDetail:
  path = _style_path(settings, name)
  if not path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "style_not_found", "message": "文风不存在"},
    )
  payload = read_json(path, {})
  if not isinstance(payload, dict):
    raise HTTPException(
      status_code=500,
      detail={"code": "style_invalid", "message": "文风文件损坏"},
    )
  reference_rows = _style_reference_rows(settings, name)
  detail = StyleDetail(
    name=str(payload.get("name") or name),
    instruction=str(payload.get("instruction") or ""),
    analysis=str(payload.get("analysis") or ""),
    dna_analysis=str(payload.get("dna_analysis") or ""),
    narrative_for_architecture=str(payload.get("narrative_for_architecture") or ""),
    narrative_for_blueprint=str(payload.get("narrative_for_blueprint") or ""),
    narrative_for_chapter=str(payload.get("narrative_for_chapter") or ""),
    reference_distillate=_build_reference_distillate(reference_rows),
    source_sample=str(payload.get("source_sample") or ""),
    calibration_reference=str(payload.get("calibration_reference") or ""),
    calibration_notes=str(payload.get("calibration_notes") or ""),
    last_calibrated_at=str(payload.get("last_calibrated_at") or "") or None,
    updated_at=str(payload.get("updated_at") or "") or None,
    has_calibration_snapshot=isinstance(payload.get("pre_calibration_snapshot"), dict),
    snapshot_timestamp=str((payload.get("pre_calibration_snapshot") or {}).get("timestamp") or "") or None,
    reference_materials=_list_style_reference_materials(settings, name),
    has_reference_library=len(reference_rows) > 0,
  )
  return detail


def list_styles(settings: Settings) -> list[StyleSummary]:
  items: list[StyleSummary] = []
  for path in sorted(styles_dir(settings).glob("*.json")):
    payload = read_json(path, {})
    if not isinstance(payload, dict):
      continue
    name = str(payload.get("name") or path.stem)
    items.append(
      StyleSummary(
        name=name,
        updated_at=str(payload.get("updated_at") or "") or None,
        has_reference_library=len(_list_style_reference_materials(settings, name)) > 0,
      )
    )
  return items


def get_style(settings: Settings, name: str) -> StyleDetail:
  return _style_or_404(settings, name)


def save_style(settings: Settings, name: str, request: StyleSaveRequest) -> StyleDetail:
  existing_payload = read_json(_style_path(settings, name), {})
  preserved_snapshot = existing_payload.get("pre_calibration_snapshot") if isinstance(existing_payload, dict) else None
  last_calibrated_at = (
    str(existing_payload.get("last_calibrated_at") or "") or None
    if isinstance(existing_payload, dict)
    else None
  )
  payload = StyleDetail(
    name=name,
    instruction=request.instruction.strip(),
    analysis=request.analysis.strip(),
    dna_analysis=request.dna_analysis.strip(),
    narrative_for_architecture=request.narrative_for_architecture.strip(),
    narrative_for_blueprint=request.narrative_for_blueprint.strip(),
    narrative_for_chapter=request.narrative_for_chapter.strip(),
    source_sample=request.source_sample,
    calibration_reference=request.calibration_reference,
    calibration_notes=request.calibration_notes.strip(),
    last_calibrated_at=last_calibrated_at,
    updated_at=_now_iso(),
    reference_materials=_list_style_reference_materials(settings, name),
    has_reference_library=len(_list_style_reference_materials(settings, name)) > 0,
    has_calibration_snapshot=isinstance(preserved_snapshot, dict),
    snapshot_timestamp=str((preserved_snapshot or {}).get("timestamp") or "") or None,
  )
  atomic_write_json(
    _style_path(settings, name),
    {
      "name": payload.name,
      "instruction": payload.instruction,
      "analysis": payload.analysis,
      "dna_analysis": payload.dna_analysis,
      "narrative_for_architecture": payload.narrative_for_architecture,
      "narrative_for_blueprint": payload.narrative_for_blueprint,
      "narrative_for_chapter": payload.narrative_for_chapter,
      "source_sample": payload.source_sample,
      "calibration_reference": payload.calibration_reference,
      "calibration_notes": payload.calibration_notes,
      "last_calibrated_at": payload.last_calibrated_at,
      "pre_calibration_snapshot": preserved_snapshot,
      "updated_at": payload.updated_at,
    },
  )
  return payload


def delete_style(settings: Settings, name: str) -> None:
  path = _style_path(settings, name)
  if not path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "style_not_found", "message": "文风不存在"},
    )
  path.unlink()
  refs_dir = _style_refs_dir(settings, name)
  if refs_dir.exists():
    for item in refs_dir.glob("*.json"):
      item.unlink()
    refs_dir.rmdir()


def _list_style_reference_materials(settings: Settings, name: str) -> list[KnowledgeMaterial]:
  items: list[KnowledgeMaterial] = []
  for row in _style_reference_rows(settings, name):
    items.append(
      KnowledgeMaterial(
        title=str(row["title"]),
        filename=str(row["filename"]),
        preview=_compact_text(str(row["content"]), limit=160),
        updated_at=row["updated_at"],
      )
    )
  items.sort(key=lambda item: (item.updated_at or "", item.title), reverse=True)
  return items


def import_style_references(settings: Settings, name: str, request: StyleReferenceImportRequest) -> StyleDetail:
  _style_or_404(settings, name)
  refs_dir = _style_refs_dir(settings, name)
  refs_dir.mkdir(parents=True, exist_ok=True)
  updated_at = _now_iso()
  for item in request.items:
    filename = f"{item.title.strip().replace('/', '_').replace(' ', '_')}.json"
    atomic_write_json(
      refs_dir / filename,
      {
        "title": item.title.strip(),
        "content": item.content.strip(),
        "updated_at": updated_at,
      },
    )
  detail = _style_or_404(settings, name)
  return detail.model_copy(update={"updated_at": updated_at})


def clear_style_references(settings: Settings, name: str) -> StyleDetail:
  _style_or_404(settings, name)
  refs_dir = _style_refs_dir(settings, name)
  if refs_dir.exists():
    for path in refs_dir.glob("*.json"):
      path.unlink()
    refs_dir.rmdir()
  return _style_or_404(settings, name)


def search_style_references(settings: Settings, name: str, query: str, limit: int = 6) -> list[KnowledgeSearchResult]:
  detail = _style_or_404(settings, name)
  normalized = " ".join(query.split()).strip()
  if not normalized or not detail.reference_materials:
    return []

  rows = _sync_style_reference_vectors(settings, _style_reference_rows(settings, detail.name))
  keyword_hits = _keyword_search_style_references(rows, normalized, max(1, min(limit, 20)))
  semantic_hits = _semantic_search_style_references(settings, rows, normalized, max(1, min(limit, 20)))

  combined: dict[str, dict[str, object]] = {}
  for hit in keyword_hits:
    combined[str(hit["filename"])] = dict(hit)
  for hit in semantic_hits:
    key = str(hit["filename"])
    if key in combined:
      combined[key]["score"] = max(float(combined[key]["score"]), float(hit["score"]))
      combined[key]["match_type"] = "hybrid"
    else:
      combined[key] = dict(hit)

  ordered = sorted(
    combined.values(),
    key=lambda item: (float(item["score"]), item["section"]),
    reverse=True,
  )[: max(1, min(limit, 20))]
  return [
    KnowledgeSearchResult(
      source="作者参考库",
      section=str(item["section"]),
      preview=str(item["preview"]),
      score=float(item["score"]),
      match_type=str(item["match_type"]),
    )
    for item in ordered
  ]


def save_style_detail(settings: Settings, detail: StyleDetail, *, snapshot: dict[str, object] | None = None) -> StyleDetail:
  updated_at = _now_iso()
  current_payload = read_json(_style_path(settings, detail.name), {})
  preserved_snapshot = snapshot if snapshot is not None else current_payload.get("pre_calibration_snapshot") if isinstance(current_payload, dict) else None
  atomic_write_json(
    _style_path(settings, detail.name),
    {
      "name": detail.name,
      "instruction": detail.instruction.strip(),
      "analysis": detail.analysis.strip(),
      "dna_analysis": detail.dna_analysis.strip(),
      "narrative_for_architecture": detail.narrative_for_architecture.strip(),
      "narrative_for_blueprint": detail.narrative_for_blueprint.strip(),
      "narrative_for_chapter": detail.narrative_for_chapter.strip(),
      "source_sample": detail.source_sample,
      "calibration_reference": detail.calibration_reference,
      "calibration_notes": detail.calibration_notes,
      "last_calibrated_at": detail.last_calibrated_at,
      "pre_calibration_snapshot": preserved_snapshot,
      "updated_at": updated_at,
    },
  )
  return _style_or_404(settings, detail.name)


def style_calibration_snapshot(detail: StyleDetail) -> dict[str, object]:
  return {
    "timestamp": _now_iso(),
    "instruction": detail.instruction,
    "analysis": detail.analysis,
    "dna_analysis": detail.dna_analysis,
    "narrative_for_architecture": detail.narrative_for_architecture,
    "narrative_for_blueprint": detail.narrative_for_blueprint,
    "narrative_for_chapter": detail.narrative_for_chapter,
    "calibration_notes": detail.calibration_notes,
    "source_sample": detail.source_sample,
    "calibration_reference": detail.calibration_reference,
  }


def rollback_style_calibration(settings: Settings, name: str) -> StyleDetail:
  path = _style_path(settings, name)
  payload = read_json(path, {})
  if not isinstance(payload, dict):
    raise HTTPException(
      status_code=404,
      detail={"code": "style_not_found", "message": "文风不存在"},
    )
  snapshot = payload.get("pre_calibration_snapshot")
  if not isinstance(snapshot, dict):
    raise HTTPException(
      status_code=409,
      detail={"code": "style_snapshot_missing", "message": "当前文风没有可回滚的校准快照"},
    )

  atomic_write_json(
    path,
    {
      "name": str(payload.get("name") or name),
      "instruction": str(snapshot.get("instruction") or ""),
      "analysis": str(snapshot.get("analysis") or ""),
      "dna_analysis": str(snapshot.get("dna_analysis") or ""),
      "narrative_for_architecture": str(snapshot.get("narrative_for_architecture") or ""),
      "narrative_for_blueprint": str(snapshot.get("narrative_for_blueprint") or ""),
      "narrative_for_chapter": str(snapshot.get("narrative_for_chapter") or ""),
      "source_sample": str(snapshot.get("source_sample") or payload.get("source_sample") or ""),
      "calibration_reference": str(snapshot.get("calibration_reference") or payload.get("calibration_reference") or ""),
      "calibration_notes": str(snapshot.get("calibration_notes") or ""),
      "last_calibrated_at": None,
      "pre_calibration_snapshot": None,
      "updated_at": _now_iso(),
    },
  )
  return _style_or_404(settings, name)


def build_style_reference_text(settings: Settings, name: str, task_type: str, query: str = "") -> str:
  if not name.strip():
    return ""
  try:
    detail = _style_or_404(settings, name.strip())
  except HTTPException:
    return ""

  lines = []
  if detail.instruction:
    lines.append(f"文风说明：{detail.instruction}")

  if task_type == "architecture" and detail.narrative_for_architecture:
    lines.append(f"叙事要求：{detail.narrative_for_architecture}")
  elif task_type == "blueprint" and detail.narrative_for_blueprint:
    lines.append(f"叙事要求：{detail.narrative_for_blueprint}")
  elif task_type == "chapter" and detail.narrative_for_chapter:
    lines.append(f"叙事要求：{detail.narrative_for_chapter}")

  if detail.reference_distillate:
    lines.append(f"参考库蒸馏：\n{detail.reference_distillate}")

  keyword = query.strip()
  if keyword and detail.reference_materials:
    hits = search_style_references(settings, detail.name, keyword, limit=3)
    if hits:
      lines.append(
        "参考写法：\n" + "\n".join(
          f"- {item.section}（{item.match_type}）：{item.preview}"
          for item in hits
        )
      )

  return "\n".join(lines).strip()
