from __future__ import annotations

import json
import os
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

from novel_backend.config import Settings
from novel_backend.services.config_service import load_config
from novel_backend.services.log_service import append_app_log


class RerankConfigError(RuntimeError):
  pass


def _resolve_api_key(settings: Settings) -> str:
  config = load_config(settings).model
  candidates = [
    config.api_key,
    os.getenv("NOVEL_MODEL_API_KEY", ""),
    os.getenv("DASHSCOPE_API_KEY", ""),
    os.getenv("NOVEL_API_KEY", ""),
    os.getenv("OPENAI_API_KEY", ""),
  ]
  for item in candidates:
    value = item.strip()
    if value:
      return value
  raise RerankConfigError("还没配置 API Key，暂时不能使用重排序。")


def _rerank_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  if not normalized:
    raise RerankConfigError("模型接口地址不能为空")
  if "dashscope.aliyuncs.com" not in normalized:
    raise RerankConfigError("当前模型接口不是阿里百炼，暂时不启用 qwen3-rerank。")
  if normalized.endswith("/reranks"):
    return normalized
  if normalized.endswith("/compatible-mode/v1") or normalized.endswith("/compatible-api/v1"):
    return f"{normalized.rsplit('/', 2)[0]}/compatible-api/v1/reranks"
  return "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"


def _request_rerank(endpoint: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
  body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
  request = urllib_request.Request(endpoint, data=body, method="POST")
  request.add_header("Content-Type", "application/json")
  request.add_header("Authorization", f"Bearer {api_key}")

  try:
    with urllib_request.urlopen(request, timeout=120) as response:
      raw_text = response.read().decode("utf-8")
  except urllib_error.HTTPError as error:
    error_text = error.read().decode("utf-8", errors="ignore")
    message = error_text or str(error)
    raise RuntimeError(f"重排序请求失败: {error.code} {message}") from error
  except urllib_error.URLError as error:
    raise RuntimeError(f"重排序请求失败: {error.reason}") from error

  try:
    parsed = json.loads(raw_text)
  except json.JSONDecodeError as error:
    raise RuntimeError("重排序返回的不是合法 JSON") from error

  if not isinstance(parsed, dict):
    raise RuntimeError("重排序返回格式不正确")
  return parsed


def rerank_documents(
  settings: Settings,
  *,
  query: str,
  documents: list[str],
  top_n: int | None = None,
  task_name: str = "rerank",
) -> list[dict[str, object]]:
  cleaned_documents = [item.strip() for item in documents if item.strip()]
  if not query.strip() or not cleaned_documents:
    return []

  config = load_config(settings).model
  started = time.perf_counter()
  try:
    api_key = _resolve_api_key(settings)
    endpoint = _rerank_endpoint(config.base_url)
    payload: dict[str, object] = {
      "model": "qwen3-rerank",
      "query": query.strip(),
      "documents": cleaned_documents,
    }
    if top_n is not None:
      payload["top_n"] = max(1, min(top_n, len(cleaned_documents)))
    response_payload = _request_rerank(endpoint, api_key, payload)
    items = response_payload.get("results")
    if not isinstance(items, list):
      output = response_payload.get("output")
      items = output.get("results") if isinstance(output, dict) else None
    if not isinstance(items, list):
      raise RuntimeError("重排序返回格式不正确：缺少 results")

    ranked: list[dict[str, object]] = []
    for item in items:
      if not isinstance(item, dict):
        continue
      index = item.get("index")
      if not isinstance(index, int) or index < 0 or index >= len(cleaned_documents):
        continue
      score_value = item.get("relevance_score")
      score = float(score_value) if isinstance(score_value, (int, float)) else 0.0
      ranked.append(
        {
          "index": index,
          "document": cleaned_documents[index],
          "score": score,
        }
      )
    elapsed = round(time.perf_counter() - started, 3)
    append_app_log(settings, f"{task_name} completed in {elapsed:.3f}s for {len(cleaned_documents)} docs")
    return ranked
  except Exception as error:
    elapsed = round(time.perf_counter() - started, 3)
    append_app_log(settings, f"{task_name} skipped in {elapsed:.3f}s: {error}", level="WARNING")
    return []
