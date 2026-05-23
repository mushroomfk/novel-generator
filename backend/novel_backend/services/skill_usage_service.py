from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re

from novel_backend.config import Settings
from novel_backend.services.config_service import skills_dir
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_ARCHIVE_AFTER_DAYS = 90
_STALE_AFTER_DAYS = 30
_REVIEW_FAILURE_RATE = 0.5


def _now() -> datetime:
  return datetime.now(timezone.utc)


def _now_iso() -> str:
  return _now().isoformat()


def _usage_path(settings: Settings) -> Path:
  return skills_dir(settings) / ".usage.json"


def _curator_report_path(settings: Settings) -> Path:
  return skills_dir(settings) / ".curator_reports.jsonl"


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for raw in items:
    value = str(raw or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    ordered.append(value)
  return ordered


def _parse_datetime(value: object) -> datetime | None:
  if not isinstance(value, str) or not value.strip():
    return None
  normalized = value.strip()
  if normalized.endswith("Z"):
    normalized = f"{normalized[:-1]}+00:00"
  try:
    parsed = datetime.fromisoformat(normalized)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    return parsed.replace(tzinfo=timezone.utc)
  return parsed.astimezone(timezone.utc)


def _empty_usage_store() -> dict[str, object]:
  return {
    "schema_version": 1,
    "updated_at": _now_iso(),
    "records": {},
  }


def _load_usage_store(settings: Settings) -> dict[str, object]:
  payload = read_json(_usage_path(settings), None)
  if not isinstance(payload, dict):
    return _empty_usage_store()
  records = payload.get("records")
  if not isinstance(records, dict):
    payload["records"] = {}
  payload.setdefault("schema_version", 1)
  payload.setdefault("updated_at", _now_iso())
  return payload


def _record_for(skill_id: str, now_iso: str) -> dict[str, object]:
  return {
    "skill_id": skill_id,
    "state": "active",
    "pinned": False,
    "created_at": now_iso,
    "updated_at": now_iso,
    "first_used_at": "",
    "last_used_at": "",
    "last_patched_at": "",
    "last_curated_at": "",
    "archived_at": "",
    "use_count": 0,
    "success_count": 0,
    "failure_count": 0,
    "patch_count": 0,
    "task_pack_counts": {},
    "action_counts": {},
    "project_counts": {},
  }


def _int_value(value: object) -> int:
  try:
    return int(value or 0)
  except (TypeError, ValueError):
    return 0


def _bump_counter(payload: dict[str, object], key: str, counter_key: str) -> None:
  normalized = str(key or "").strip()
  if not normalized:
    return
  counters = payload.get(counter_key)
  if not isinstance(counters, dict):
    counters = {}
    payload[counter_key] = counters
  counters[normalized] = _int_value(counters.get(normalized)) + 1


def _save_usage_store(settings: Settings, payload: dict[str, object]) -> None:
  payload["updated_at"] = _now_iso()
  atomic_write_json(_usage_path(settings), payload)


def record_skill_usage(
  settings: Settings,
  skill_ids: list[str],
  *,
  project_id: str = "",
  task_id: str = "",
  action_kinds: list[str] | None = None,
  task_pack_kind: str = "",
  status: str = "completed",
) -> dict[str, object]:
  resolved_ids = _ordered_unique(skill_ids)
  if not resolved_ids:
    return {"updated": 0, "skill_ids": []}

  store = _load_usage_store(settings)
  records = store.setdefault("records", {})
  if not isinstance(records, dict):
    records = {}
    store["records"] = records

  now_iso = _now_iso()
  for skill_id in resolved_ids:
    record = records.get(skill_id)
    if not isinstance(record, dict):
      record = _record_for(skill_id, now_iso)
      records[skill_id] = record

    if not record.get("first_used_at"):
      record["first_used_at"] = now_iso
    record["last_used_at"] = now_iso
    record["updated_at"] = now_iso
    record["last_task_id"] = str(task_id or "")
    record["use_count"] = _int_value(record.get("use_count")) + 1
    if status == "failed":
      record["failure_count"] = _int_value(record.get("failure_count")) + 1
    else:
      record["success_count"] = _int_value(record.get("success_count")) + 1
    _bump_counter(record, project_id, "project_counts")
    _bump_counter(record, task_pack_kind, "task_pack_counts")
    for action_kind in action_kinds or []:
      _bump_counter(record, action_kind, "action_counts")
    if str(record.get("state") or "") in {"stale", "archived"} and status != "failed":
      record["state"] = "active"
      record["archived_at"] = ""

  _save_usage_store(settings, store)
  return {"updated": len(resolved_ids), "skill_ids": resolved_ids}


def record_skill_patch(
  settings: Settings,
  skill_id: str,
  *,
  action: str = "iterate",
  project_id: str = "",
) -> dict[str, object]:
  normalized = str(skill_id or "").strip()
  if not normalized:
    return {"updated": 0, "skill_id": ""}

  store = _load_usage_store(settings)
  records = store.setdefault("records", {})
  if not isinstance(records, dict):
    records = {}
    store["records"] = records

  now_iso = _now_iso()
  record = records.get(normalized)
  if not isinstance(record, dict):
    record = _record_for(normalized, now_iso)
    records[normalized] = record
  record["updated_at"] = now_iso
  record["last_patched_at"] = now_iso
  record["last_patch_action"] = str(action or "").strip() or "iterate"
  record["patch_count"] = _int_value(record.get("patch_count")) + 1
  record["state"] = "active"
  record["archived_at"] = ""
  _bump_counter(record, project_id, "project_counts")
  _save_usage_store(settings, store)
  return {"updated": 1, "skill_id": normalized}


def _normalize_for_grouping(value: str) -> str:
  return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def _days_since(value: object, now: datetime) -> int | None:
  parsed = _parse_datetime(value)
  if parsed is None:
    return None
  return max(0, (now - parsed).days)


def _append_curator_report(settings: Settings, report: dict[str, object]) -> None:
  path = _curator_report_path(settings)
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(report, ensure_ascii=False) + "\n")


def run_skill_curator(settings: Settings) -> dict[str, object]:
  store = _load_usage_store(settings)
  records = store.setdefault("records", {})
  if not isinstance(records, dict):
    records = {}
    store["records"] = records

  now = _now()
  now_iso = now.isoformat()
  changes: list[dict[str, object]] = []
  recommendations: list[str] = []
  groups: dict[str, list[str]] = {}

  for skill_id, raw_record in records.items():
    if not isinstance(raw_record, dict):
      continue
    record = raw_record
    record["last_curated_at"] = now_iso
    record.setdefault("state", "active")
    record.setdefault("pinned", False)
    record.setdefault("archived_at", "")
    if bool(record.get("pinned")):
      continue

    grouping_key = _normalize_for_grouping(str(skill_id))
    if grouping_key:
      groups.setdefault(grouping_key, []).append(str(skill_id))

    last_activity = record.get("last_used_at") or record.get("last_patched_at") or record.get("created_at")
    idle_days = _days_since(last_activity, now)
    previous_state = str(record.get("state") or "active")
    next_state = previous_state
    use_count = _int_value(record.get("use_count"))
    patch_count = _int_value(record.get("patch_count"))
    if idle_days is not None and idle_days >= _ARCHIVE_AFTER_DAYS and use_count <= 1 and patch_count <= 1:
      next_state = "archived"
    elif idle_days is not None and idle_days >= _STALE_AFTER_DAYS and use_count <= 1:
      next_state = "stale"
    elif use_count >= 2 and _int_value(record.get("failure_count")) / max(1, use_count) >= _REVIEW_FAILURE_RATE:
      next_state = "needs_review"
    elif use_count >= 2 or patch_count >= 1:
      next_state = "active"

    if next_state != previous_state:
      record["state"] = next_state
      if next_state == "archived":
        record["archived_at"] = now_iso
      elif previous_state == "archived":
        record["archived_at"] = ""
      changes.append(
        {
          "skill_id": skill_id,
          "from": previous_state,
          "to": next_state,
          "idle_days": idle_days,
        }
      )

  for _group_key, skill_ids in groups.items():
    if len(skill_ids) > 1:
      sorted_ids = sorted(skill_ids)
      recommendations.append(f"技能 {', '.join(sorted_ids)} 的标识很接近，后续可以人工合并边界。")
      for skill_id in sorted_ids[1:]:
        record = records.get(skill_id)
        if isinstance(record, dict) and not bool(record.get("pinned")) and record.get("state") == "active":
          record["state"] = "needs_review"
          changes.append(
            {
              "skill_id": skill_id,
              "from": "active",
              "to": "needs_review",
              "reason": "duplicate_id",
            }
          )

  _save_usage_store(settings, store)
  active_count = sum(1 for item in records.values() if isinstance(item, dict) and item.get("state") == "active")
  stale_count = sum(1 for item in records.values() if isinstance(item, dict) and item.get("state") == "stale")
  archived_count = sum(1 for item in records.values() if isinstance(item, dict) and item.get("state") == "archived")
  needs_review_count = sum(1 for item in records.values() if isinstance(item, dict) and item.get("state") == "needs_review")
  report = {
    "id": f"curator-{now.strftime('%Y%m%d%H%M%S')}",
    "generated_at": now_iso,
    "checked_count": len(records),
    "active_count": active_count,
    "stale_count": stale_count,
    "archived_count": archived_count,
    "needs_review_count": needs_review_count,
    "change_count": len(changes),
    "changes": changes,
    "recommendations": recommendations[:8],
  }
  _append_curator_report(settings, report)
  return report


def get_skill_usage_state(settings: Settings) -> dict[str, object]:
  store = _load_usage_store(settings)
  records = store.get("records")
  if not isinstance(records, dict):
    records = {}
  return {
    "updated_at": store.get("updated_at", ""),
    "records": sorted(
      [record for record in records.values() if isinstance(record, dict)],
      key=lambda item: (
        str(item.get("state") or "active"),
        -_int_value(item.get("use_count")),
        str(item.get("skill_id") or ""),
      ),
    ),
  }
