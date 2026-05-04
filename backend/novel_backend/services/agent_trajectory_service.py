from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.config import Settings


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def agent_trajectory_path(settings: Settings) -> Path:
  return settings.data_dir / "logs" / "agent_trajectories.jsonl"


def append_agent_trajectory(settings: Settings, record: dict[str, object]) -> None:
  path = agent_trajectory_path(settings)
  path.parent.mkdir(parents=True, exist_ok=True)
  payload = {
    "timestamp": _now_iso(),
    **record,
  }
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def get_agent_trajectory_records(settings: Settings, tail: int = 50, search: str = "") -> dict[str, object]:
  path = agent_trajectory_path(settings)
  if not path.exists():
    return {"records": [], "total": 0}

  with path.open("r", encoding="utf-8") as handle:
    raw_lines = deque(handle, maxlen=5000)

  records: list[dict[str, object]] = []
  for raw_line in raw_lines:
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
    records = [
      item for item in records
      if keyword in json.dumps(item, ensure_ascii=False).lower()
    ]

  records.sort(key=lambda item: str(item.get("timestamp") or ""))
  total = len(records)
  selected = list(reversed(records[-max(1, min(tail, 500)) :]))
  return {"records": selected, "total": total}
