from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from novel_backend.models import ProjectMemoryEntry, ProjectMemoryEntryInput
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


_MEMORY_DIRNAME = "project_memory"
_AUDIT_LOG_NAME = "audit.jsonl"
_SOURCE_DIRS = {
  "manual": "author",
  "auto": "system",
}
_DIR_SOURCES = {value: key for key, value in _SOURCE_DIRS.items()}
_CATEGORY_DIRS = {
  "硬规则": "canon",
  "偏好": "style",
  "连续性": "continuity",
  "警告": "warnings",
  "目标": "planning",
}
_DIR_CATEGORIES = {value: key for key, value in _CATEGORY_DIRS.items()}
_VALID_CATEGORIES = set(_CATEGORY_DIRS)


def project_memory_path(project_dir: Path) -> Path:
  return project_dir / "project_memory.json"


def project_memory_dir(project_dir: Path) -> Path:
  return project_dir / _MEMORY_DIRNAME


def project_memory_audit_path(project_dir: Path) -> Path:
  return project_memory_dir(project_dir) / _AUDIT_LOG_NAME


def _entry_files(root: Path, *, source: str | None = None) -> list[Path]:
  if not root.exists():
    return []

  base_dirs: list[Path]
  if source is None:
    base_dirs = [root / dirname for dirname in _SOURCE_DIRS.values()]
  else:
    base_dirs = [root / _SOURCE_DIRS[source]]

  files: list[Path] = []
  for base_dir in base_dirs:
    if base_dir.exists():
      files.extend(path for path in base_dir.rglob("*.md") if path.is_file())
  return sorted(files)


def _has_entry_files(project_dir: Path) -> bool:
  return bool(_entry_files(project_memory_dir(project_dir)))


def _source_dir_exists(project_dir: Path, *, source: str) -> bool:
  return (project_memory_dir(project_dir) / _SOURCE_DIRS[source]).exists()


def _safe_stem(value: str, fallback: str) -> str:
  cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
  cleaned = cleaned.strip(".-_")
  return cleaned[:64] or fallback


def _entry_path(root: Path, entry: ProjectMemoryEntry) -> Path:
  source_dir = _SOURCE_DIRS.get(entry.source, _SOURCE_DIRS["manual"])
  category_dir = _CATEGORY_DIRS.get(entry.category, _CATEGORY_DIRS["硬规则"])
  return root / source_dir / category_dir / f"{_safe_stem(entry.id, 'memory')}.md"


def _relative(path: Path, root: Path) -> str:
  return path.relative_to(root).as_posix()


def _metadata_value(value: object) -> str:
  return json.dumps(str(value or ""), ensure_ascii=False)


def _entry_file_text(entry: ProjectMemoryEntry) -> str:
  metadata = [
    "---",
    f"id: {_metadata_value(entry.id)}",
    f"title: {_metadata_value(entry.title)}",
    f"category: {_metadata_value(entry.category)}",
    f"source: {_metadata_value(entry.source)}",
    f"updated_at: {_metadata_value(entry.updated_at or '')}",
    "---",
    "",
    entry.content.strip(),
    "",
  ]
  return "\n".join(metadata)


def _parse_metadata_value(raw: str) -> str:
  value = raw.strip()
  if not value:
    return ""
  try:
    decoded = json.loads(value)
    return str(decoded)
  except Exception:
    return value.strip("'\"")


def _parse_entry_file(path: Path, root: Path) -> ProjectMemoryEntry | None:
  try:
    text = path.read_text(encoding="utf-8")
  except OSError:
    return None

  metadata: dict[str, str] = {}
  body = text
  if text.startswith("---\n"):
    marker_index = text.find("\n---\n", 4)
    if marker_index >= 0:
      raw_metadata = text[4:marker_index]
      body = text[marker_index + 5:]
      for raw_line in raw_metadata.splitlines():
        if ":" not in raw_line:
          continue
        key, raw_value = raw_line.split(":", 1)
        metadata[key.strip()] = _parse_metadata_value(raw_value)

  content = body.strip()
  if not content:
    return None

  parts = path.relative_to(root).parts
  source = metadata.get("source", "")
  if source not in _SOURCE_DIRS and parts:
    source = _DIR_SOURCES.get(parts[0], "manual")
  if source not in _SOURCE_DIRS:
    source = "manual"

  category = metadata.get("category", "")
  if category not in _VALID_CATEGORIES and len(parts) >= 2:
    category = _DIR_CATEGORIES.get(parts[1], "硬规则")
  if category not in _VALID_CATEGORIES:
    category = "硬规则"

  entry_id = metadata.get("id", "").strip() or path.stem[:40]
  title = metadata.get("title", "").strip() or path.stem.replace("-", " ")[:80]
  updated_at = metadata.get("updated_at", "").strip() or datetime.fromtimestamp(
    path.stat().st_mtime,
    timezone.utc,
  ).isoformat()

  try:
    return ProjectMemoryEntry(
      id=entry_id[:40],
      title=title[:80],
      category=category,
      content=content,
      source=source,
      updated_at=updated_at,
    )
  except Exception:
    return None


def _load_entries_from_files(project_dir: Path, *, source: str) -> list[ProjectMemoryEntry]:
  root = project_memory_dir(project_dir)
  entries: list[ProjectMemoryEntry] = []
  for path in _entry_files(root, source=source):
    entry = _parse_entry_file(path, root)
    if entry is not None:
      entries.append(entry)
  return sorted(entries, key=lambda item: (item.category, item.title, item.id))


def _hash_text(text: str) -> str:
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _memory_hashes(root: Path) -> dict[str, str]:
  hashes: dict[str, str] = {}
  for path in _entry_files(root):
    try:
      hashes[_relative(path, root)] = _hash_text(path.read_text(encoding="utf-8"))
    except OSError:
      continue
  return hashes


def _audit_changes(before: dict[str, str], after: dict[str, str]) -> list[dict[str, str]]:
  changes: list[dict[str, str]] = []
  for path in sorted(set(before) | set(after)):
    if path not in before:
      changes.append({"path": path, "status": "added", "sha256": after[path]})
    elif path not in after:
      changes.append({"path": path, "status": "deleted", "sha256": before[path]})
    elif before[path] != after[path]:
      changes.append({"path": path, "status": "modified", "sha256": after[path]})
  return changes


def _append_audit(project_dir: Path, *, reason: str, changes: list[dict[str, str]]) -> None:
  if not changes:
    return
  audit_path = project_memory_audit_path(project_dir)
  audit_path.parent.mkdir(parents=True, exist_ok=True)
  with audit_path.open("a", encoding="utf-8") as handle:
    handle.write(
      json.dumps(
        {
          "created_at": _now_iso(),
          "reason": reason,
          "changes": changes,
        },
        ensure_ascii=False,
      )
      + "\n"
    )


def _prune_empty_dirs(path: Path, stop_at: Path) -> None:
  current = path
  while current != stop_at and current.exists():
    try:
      current.rmdir()
    except OSError:
      return
    current = current.parent


def _write_source_entries(
  project_dir: Path,
  entries: list[ProjectMemoryEntry],
  *,
  source: str,
  reason: str,
) -> None:
  root = project_memory_dir(project_dir)
  root.mkdir(parents=True, exist_ok=True)
  before = _memory_hashes(root)

  target_paths: set[Path] = set()
  for entry in entries:
    path = _entry_path(root, entry)
    target_paths.add(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, _entry_file_text(entry))

  source_root = root / _SOURCE_DIRS[source]
  for path in _entry_files(root, source=source):
    if path in target_paths:
      continue
    path.unlink()
    _prune_empty_dirs(path.parent, source_root)

  after = _memory_hashes(root)
  _append_audit(project_dir, reason=reason, changes=_audit_changes(before, after))


def ensure_project_memory_file(project_dir: Path) -> None:
  path = project_memory_path(project_dir)
  if not path.exists():
    atomic_write_json(
      path,
      {
        "manual_entries": [],
        "derived_entries": [],
        "derived_signature": "",
      },
    )
    project_memory_dir(project_dir).mkdir(parents=True, exist_ok=True)
    return

  payload = read_json(path, {})
  if isinstance(payload, dict) and (
    "manual_entries" in payload or "derived_entries" in payload or "derived_signature" in payload
  ):
    project_memory_dir(project_dir).mkdir(parents=True, exist_ok=True)
    if not _has_entry_files(project_dir):
      manual_entries = _entry_list(payload.get("manual_entries", []), source="manual")
      derived_entries = _entry_list(payload.get("derived_entries", []), source="auto")
      if manual_entries:
        _write_source_entries(project_dir, manual_entries, source="manual", reason="migrate_json")
      if derived_entries:
        _write_source_entries(project_dir, derived_entries, source="auto", reason="migrate_json")
    return

  raw_entries = payload.get("entries", []) if isinstance(payload, dict) else []
  manual_entries = _entry_list(raw_entries if isinstance(raw_entries, list) else [], source="manual")
  _dump_payload(
    project_dir,
    manual_entries=manual_entries,
    derived_entries=[],
    derived_signature="",
  )
  if manual_entries:
    _write_source_entries(project_dir, manual_entries, source="manual", reason="migrate_legacy_json")


def _entry_list(raw_entries: object, *, source: str) -> list[ProjectMemoryEntry]:
  entries: list[ProjectMemoryEntry] = []
  if not isinstance(raw_entries, list):
    return entries

  for item in raw_entries:
    if not isinstance(item, dict):
      continue
    payload = dict(item)
    payload.setdefault("source", source)
    try:
      entries.append(ProjectMemoryEntry.model_validate(payload))
    except Exception:
      continue
  return entries


def _memory_payload(project_dir: Path) -> dict[str, object]:
  ensure_project_memory_file(project_dir)
  payload = read_json(project_memory_path(project_dir), {})
  return payload if isinstance(payload, dict) else {}


def _memory_groups(project_dir: Path) -> tuple[list[ProjectMemoryEntry], list[ProjectMemoryEntry], str]:
  payload = _memory_payload(project_dir)
  _record_external_file_changes(project_dir, payload)
  manual_entries = _load_entries_from_files(project_dir, source="manual")
  derived_entries = _load_entries_from_files(project_dir, source="auto")
  if not manual_entries and not _source_dir_exists(project_dir, source="manual"):
    manual_entries = _entry_list(payload.get("manual_entries", []), source="manual")
  if not derived_entries and not _source_dir_exists(project_dir, source="auto"):
    derived_entries = _entry_list(payload.get("derived_entries", []), source="auto")
  derived_signature = str(payload.get("derived_signature") or "")
  return manual_entries, derived_entries, derived_signature


def _record_external_file_changes(project_dir: Path, payload: dict[str, object]) -> None:
  raw_hashes = payload.get("file_hashes")
  if not isinstance(raw_hashes, dict):
    return
  before = {str(key): str(value) for key, value in raw_hashes.items()}
  after = _memory_hashes(project_memory_dir(project_dir))
  changes = _audit_changes(before, after)
  if not changes:
    return
  _append_audit(project_dir, reason="external_edit", changes=changes)
  next_payload = dict(payload)
  next_payload["file_hashes"] = after
  atomic_write_json(project_memory_path(project_dir), next_payload)


def _dump_payload(
  project_dir: Path,
  *,
  manual_entries: list[ProjectMemoryEntry],
  derived_entries: list[ProjectMemoryEntry],
  derived_signature: str,
) -> None:
  atomic_write_json(
    project_memory_path(project_dir),
    {
      "manual_entries": [item.model_dump(mode="json") for item in manual_entries],
      "derived_entries": [item.model_dump(mode="json") for item in derived_entries],
      "derived_signature": derived_signature,
      "file_hashes": _memory_hashes(project_memory_dir(project_dir)),
    },
  )


def _stable_updated_at(
  existing_entries: dict[str, ProjectMemoryEntry],
  *,
  entry_id: str,
  title: str,
  category: str,
  content: str,
  source: str,
  fallback_time: str,
) -> str:
  existing = existing_entries.get(entry_id)
  if (
    existing is not None
    and existing.title == title
    and existing.category == category
    and existing.content == content
    and existing.source == source
  ):
    return existing.updated_at or fallback_time
  return fallback_time


def load_project_memory(project_dir: Path) -> list[ProjectMemoryEntry]:
  manual_entries, derived_entries, _derived_signature = _memory_groups(project_dir)
  return [*manual_entries, *derived_entries]


def load_manual_project_memory(project_dir: Path) -> list[ProjectMemoryEntry]:
  manual_entries, _derived_entries, _derived_signature = _memory_groups(project_dir)
  return manual_entries


def save_project_memory(project_dir: Path, inputs: list[ProjectMemoryEntryInput]) -> list[ProjectMemoryEntry]:
  manual_entries, derived_entries, derived_signature = _memory_groups(project_dir)
  existing_entries = {item.id: item for item in manual_entries}
  normalized: list[ProjectMemoryEntry] = []
  current_time = _now_iso()

  for item in inputs:
    content = item.content.strip()
    if not content:
      continue
    entry_id = (item.id or "").strip() or uuid4().hex[:12]
    title = item.title.strip()
    updated_at = _stable_updated_at(
      existing_entries,
      entry_id=entry_id,
      title=title,
      category=item.category,
      content=content,
      source="manual",
      fallback_time=current_time,
    )
    normalized.append(
      ProjectMemoryEntry(
        id=entry_id,
        title=title,
        category=item.category,
        content=content,
        source="manual",
        updated_at=updated_at,
      )
    )

  _write_source_entries(project_dir, normalized, source="manual", reason="manual_update")
  _dump_payload(
    project_dir,
    manual_entries=normalized,
    derived_entries=derived_entries,
    derived_signature=derived_signature,
  )
  return [*normalized, *derived_entries]


def append_system_project_memory(
  project_dir: Path,
  inputs: list[ProjectMemoryEntryInput],
  *,
  reason: str = "system_append",
) -> list[ProjectMemoryEntry]:
  manual_entries, derived_entries, derived_signature = _memory_groups(project_dir)
  normalized_keys = {
    (
      item.title.strip(),
      item.category,
      item.content.strip(),
    )
    for item in derived_entries
    if item.content.strip()
  }
  merged_entries = list(derived_entries)
  current_time = _now_iso()

  for item in inputs:
    content = item.content.strip()
    if not content:
      continue
    normalized_key = (
      item.title.strip(),
      item.category,
      content,
    )
    if normalized_key in normalized_keys:
      continue
    normalized_keys.add(normalized_key)
    entry_id = (item.id or "").strip() or f"learned-{uuid4().hex[:12]}"
    merged_entries.append(
      ProjectMemoryEntry(
        id=entry_id,
        title=item.title.strip(),
        category=item.category,
        content=content,
        source="auto",
        updated_at=current_time,
      )
    )

  _write_source_entries(project_dir, merged_entries, source="auto", reason=reason)
  _dump_payload(
    project_dir,
    manual_entries=manual_entries,
    derived_entries=merged_entries,
    derived_signature=derived_signature,
  )
  return [*manual_entries, *merged_entries]


def append_project_memory(project_dir: Path, inputs: list[ProjectMemoryEntryInput]) -> list[ProjectMemoryEntry]:
  manual_entries = load_manual_project_memory(project_dir)
  normalized_keys = {
    (
      item.title.strip(),
      item.category,
      item.content.strip(),
    )
    for item in manual_entries
    if item.content.strip()
  }
  merged_inputs = [
    ProjectMemoryEntryInput(
      id=item.id,
      title=item.title,
      category=item.category,
      content=item.content,
    )
    for item in manual_entries
  ]

  for item in inputs:
    content = item.content.strip()
    if not content:
      continue
    normalized_key = (
      item.title.strip(),
      item.category,
      content,
    )
    if normalized_key in normalized_keys:
      continue
    normalized_keys.add(normalized_key)
    merged_inputs.append(
      ProjectMemoryEntryInput(
        id=(item.id or "").strip() or None,
        title=item.title,
        category=item.category,
        content=content,
      )
    )

  return save_project_memory(project_dir, merged_inputs)


def sync_project_memory(
  project_dir: Path,
  derived_entries: list[ProjectMemoryEntry],
  *,
  derived_signature: str,
) -> list[ProjectMemoryEntry]:
  manual_entries, existing_derived_entries, existing_signature = _memory_groups(project_dir)
  if existing_signature == derived_signature and existing_derived_entries:
    return [*manual_entries, *existing_derived_entries]

  existing_entries = {item.id: item for item in existing_derived_entries}
  preserved_entries = [
    item for item in existing_derived_entries
    if not item.id.startswith("auto-")
  ]
  current_time = _now_iso()
  normalized: list[ProjectMemoryEntry] = []
  for item in derived_entries:
    content = item.content.strip()
    if not content:
      continue
    title = item.title.strip()
    updated_at = _stable_updated_at(
      existing_entries,
      entry_id=item.id,
      title=title,
      category=item.category,
      content=content,
      source="auto",
      fallback_time=current_time,
    )
    normalized.append(
      ProjectMemoryEntry(
        id=item.id,
        title=title,
        category=item.category,
        content=content,
        source="auto",
        updated_at=updated_at,
      )
    )

  merged_derived_entries = [*preserved_entries, *normalized]
  _write_source_entries(project_dir, merged_derived_entries, source="auto", reason="auto_sync")
  _dump_payload(
    project_dir,
    manual_entries=manual_entries,
    derived_entries=merged_derived_entries,
    derived_signature=derived_signature,
  )
  return [*manual_entries, *merged_derived_entries]
