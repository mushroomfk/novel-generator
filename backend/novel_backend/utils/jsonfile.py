from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

_ATOMIC_REPLACE_RETRY_DELAYS = (0.01, 0.03, 0.06, 0.1, 0.2)


def _replace_with_retry(source: Path, target: Path) -> None:
  for attempt in range(len(_ATOMIC_REPLACE_RETRY_DELAYS) + 1):
    try:
      os.replace(source, target)
      return
    except PermissionError:
      if attempt >= len(_ATOMIC_REPLACE_RETRY_DELAYS):
        raise
      time.sleep(_ATOMIC_REPLACE_RETRY_DELAYS[attempt])


def atomic_write_text(path: Path, content: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
  try:
    temp_path.write_text(content, encoding="utf-8")
    _replace_with_retry(temp_path, path)
  finally:
    temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
  atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_json(path: Path, default: Any) -> Any:
  if not path.exists():
    return default

  return json.loads(path.read_text(encoding="utf-8"))
