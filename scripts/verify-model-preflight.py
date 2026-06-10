#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
  sys.path.insert(0, str(BACKEND_DIR))

from novel_backend.config import Settings, default_data_dir
from novel_backend.models import AppConfig
from novel_backend.services.config_service import app_config_path
from novel_backend.utils.jsonfile import read_json


def _endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  if normalized.endswith("/chat/completions"):
    return normalized
  return normalized + "/chat/completions"


def _host_port(parsed) -> tuple[str, int]:
  if parsed.port:
    return parsed.hostname or "", parsed.port
  return parsed.hostname or "", 443 if parsed.scheme == "https" else 80


def _resolve_host(host: str, port: int) -> dict[str, object]:
  try:
    entries = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
  except OSError as error:
    return {
      "ok": False,
      "error": getattr(error, "strerror", str(error)),
      "code": getattr(error, "errno", None),
    }

  families = sorted({entry[0].name for entry in entries if hasattr(entry[0], "name")})
  return {
    "ok": True,
    "address_family": families,
    "resolved_count": len(entries),
  }


def _diagnose_chat(label: str, payload: dict[str, object], required: bool) -> dict[str, object]:
  base_url = str(payload.get("base_url") or "").strip()
  model_name = str(payload.get("model_name") or "").strip()
  api_key = str(payload.get("api_key") or "")
  parsed = urlparse(base_url)
  host, port = _host_port(parsed)

  result: dict[str, object] = {
    "label": label,
    "required": required,
    "enabled": bool(payload.get("enabled", True)) if label == "review_model" else True,
    "model_name": model_name,
    "model_name_present": bool(model_name),
    "base_url_present": bool(base_url),
    "url_parse_ok": bool(parsed.scheme and host),
    "scheme": parsed.scheme or "",
    "host": host,
    "path": parsed.path or "",
    "api_key_present": bool(api_key),
  }

  checks = [
    result["model_name_present"],
    result["base_url_present"],
    result["url_parse_ok"],
    parsed.scheme in {"http", "https"},
    result["api_key_present"],
  ]

  if host and parsed.scheme in {"http", "https"}:
    result["chat_completions_endpoint"] = _endpoint(base_url)
    result["dns"] = _resolve_host(host, port)
    checks.append(bool(result["dns"]["ok"]))
  else:
    result["dns"] = {"ok": False, "error": "base_url 没有合法 host"}
    checks.append(False)

  result["ok"] = all(checks) if required else True
  if required and not result["ok"]:
    failures: list[str] = []
    if not result["model_name_present"]:
      failures.append("模型名为空")
    if not result["base_url_present"]:
      failures.append("接口地址为空")
    if not result["url_parse_ok"] or parsed.scheme not in {"http", "https"}:
      failures.append("接口地址格式不正确")
    if not result["api_key_present"]:
      failures.append("API Key 为空")
    dns = result.get("dns")
    if isinstance(dns, dict) and not dns.get("ok"):
      failures.append(f"DNS 解析失败：{dns.get('error')}")
    result["failures"] = failures
  else:
    result["failures"] = []

  return result


def run_preflight(source_data_dir: Path) -> dict[str, object]:
  settings = Settings(data_dir=source_data_dir)
  config_path = app_config_path(settings)
  payload = read_json(config_path, None)
  if not isinstance(payload, dict):
    return {
      "status": "failed",
      "data_dir": str(source_data_dir),
      "config_path": str(config_path),
      "error": "app_config.json 不存在或格式不正确",
      "items": [],
    }

  config = AppConfig.model_validate(payload)
  model_payload = config.model.model_dump(mode="json")
  review_payload = config.review_model.model_dump(mode="json")
  review_required = bool(config.review_model.enabled)
  items = [
    _diagnose_chat("model", model_payload, required=True),
    _diagnose_chat("review_model", review_payload, required=review_required),
  ]
  status = "passed" if all(item["ok"] for item in items) else "failed"
  return {
    "status": status,
    "data_dir": str(source_data_dir),
    "config_path": str(config_path),
    "items": items,
  }


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Check saved model config without exposing API keys or sending model requests.")
  parser.add_argument("--source-data-dir", default=str(default_data_dir()), help="App data dir containing app_config.json.")
  return parser


def main() -> int:
  args = build_parser().parse_args()
  result = run_preflight(Path(args.source_data_dir).expanduser().resolve())
  print(json.dumps(result, ensure_ascii=False, indent=2))
  return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
  raise SystemExit(main())
