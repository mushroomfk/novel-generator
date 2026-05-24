from __future__ import annotations

import os
import time

from novel_backend.config import Settings
from novel_backend.services.config_service import load_config
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.model_transport_service import request_json


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
  return request_json(
    endpoint,
    api_key,
    payload,
    failure_label="重排序请求失败",
    invalid_json_message="重排序返回的不是合法 JSON",
    invalid_format_message="重排序返回格式不正确",
  )


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
  runtime_task = None
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
    with model_runtime_slot(settings, lane="retrieval", task_name=task_name) as task:
      runtime_task = task
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
    append_app_log(
      settings,
      (
        f"{task_name} completed in {elapsed:.3f}s for {len(cleaned_documents)} docs "
        f"(queue_wait={runtime_task.queue_wait_seconds if runtime_task is not None else 0.0:.3f}s)"
      ),
    )
    return ranked
  except Exception as error:
    elapsed = round(time.perf_counter() - started, 3)
    if runtime_task is not None:
      mark_model_runtime_cooldown(settings, "retrieval", str(error))
    append_app_log(settings, f"{task_name} skipped in {elapsed:.3f}s: {error}", level="WARNING")
    return []
