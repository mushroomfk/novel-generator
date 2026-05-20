from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def atomic_write_text(path: Path, content: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
  try:
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, path)
  finally:
    temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
  atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_json(path: Path, default: Any) -> Any:
  if not path.exists():
    return default

  return json.loads(path.read_text(encoding="utf-8"))
