from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone

from novel_backend.config import Settings
from novel_backend.services.config_service import app_log_path, prompt_history_path


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def append_app_log(settings: Settings, message: str, level: str = "INFO") -> None:
  path = app_log_path(settings)
  line = f"{_now_iso()} [{level}] {message}\n"
  with path.open("a", encoding="utf-8") as handle:
    handle.write(line)


def append_prompt_history(settings: Settings, record: dict[str, object]) -> None:
  path = prompt_history_path(settings)
  payload = {
    "timestamp": _now_iso(),
    **record,
  }
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def get_app_log_tail(settings: Settings, tail: int = 200) -> str:
  path = app_log_path(settings)
  if not path.exists():
    return ""

  with path.open("r", encoding="utf-8") as handle:
    lines = deque(handle, maxlen=max(1, min(tail, 5000)))
  return "".join(lines)


def clear_app_log(settings: Settings) -> str:
  path = app_log_path(settings)
  path.write_text("", encoding="utf-8")
  return "运行日志已清空"


def get_prompt_history_records(settings: Settings, tail: int = 50, search: str = "") -> dict[str, object]:
  path = prompt_history_path(settings)
  if not path.exists():
    return {"records": [], "total": 0}

  records: list[dict[str, object]] = []
  with path.open("r", encoding="utf-8") as handle:
    for raw_line in handle:
      line = raw_line.strip()
      if not line:
        continue
      try:
        payload = json.loads(line)
      except json.JSONDecodeError:
        continue
      if isinstance(payload, dict):
        records.append(payload)

  keyword = search.strip().lower()
  if keyword:
    filtered: list[dict[str, object]] = []
    for record in records:
      haystack = " ".join(
        str(record.get(field) or "")
        for field in ("task", "model", "prompt", "response", "status", "error", "error_kind", "error_title")
      ).lower()
      if keyword in haystack:
        filtered.append(record)
    records = filtered

  records.sort(key=lambda item: str(item.get("timestamp") or ""))
  total = len(records)
  selected = list(reversed(records[-max(1, min(tail, 500)) :]))
  return {"records": selected, "total": total}


def clear_prompt_history(settings: Settings) -> str:
  path = prompt_history_path(settings)
  path.write_text("", encoding="utf-8")
  return "Prompt 历史已清空"
