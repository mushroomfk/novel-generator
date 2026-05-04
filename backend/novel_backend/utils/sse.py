from __future__ import annotations

import json


def encode_sse(event: str, data: object) -> str:
  return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
