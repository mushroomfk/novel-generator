from __future__ import annotations

import math
import os
import time

from novel_backend.config import Settings
from novel_backend.models import EmbeddingConfig
from novel_backend.services.config_service import load_config
from novel_backend.services.local_embedding_service import embed_texts_locally, is_local_embedding_config
from novel_backend.services.log_service import append_app_log
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.model_transport_service import request_json


class EmbeddingConfigError(RuntimeError):
  pass


def _resolve_embedding_api_key(config: EmbeddingConfig) -> str:
  if is_local_embedding_config(config):
    return ""
  candidates = [
    config.api_key,
    os.getenv("NOVEL_EMBEDDING_API_KEY", ""),
    os.getenv("DASHSCOPE_API_KEY", ""),
    os.getenv("ARK_API_KEY", ""),
    os.getenv("NOVEL_API_KEY", ""),
    os.getenv("OPENAI_API_KEY", ""),
  ]
  for item in candidates:
    value = item.strip()
    if value:
      return value
  raise EmbeddingConfigError(
    "还没配置 Embedding API Key。请先在设置里填写，或设置 NOVEL_EMBEDDING_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY / OPENAI_API_KEY。"
  )


def _embedding_ready(config: EmbeddingConfig) -> bool:
  if is_local_embedding_config(config):
    return bool(config.model_name.strip())
  try:
    _resolve_embedding_api_key(config)
  except EmbeddingConfigError:
    return False
  return bool(config.base_url.strip() and config.model_name.strip())


def embedding_config_signature(settings: Settings) -> str:
  config = load_config(settings).embedding
  ready = _embedding_ready(config)
  return "|".join(
    [
      config.provider.strip(),
      config.base_url.strip().rstrip("/"),
      config.model_name.strip(),
      str(config.dimensions or 0),
      str(config.retrieval_k),
      str(config.batch_size),
      "ready" if ready else "disabled",
    ]
  )


def _embeddings_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  if not normalized:
    raise EmbeddingConfigError("Embedding 接口地址不能为空")
  if normalized.endswith("/embeddings"):
    return normalized
  return f"{normalized}/embeddings"


def _request_embeddings(endpoint: str, api_key: str, payload: dict[str, object]) -> dict[str, object]:
  return request_json(
    endpoint,
    api_key,
    payload,
    failure_label="Embedding 请求失败",
    invalid_json_message="Embedding 返回的不是合法 JSON",
    invalid_format_message="Embedding 返回格式不正确",
  )


def _extract_embedding_vectors(payload: dict[str, object], expected_count: int) -> list[list[float]]:
  items = payload.get("data")
  if not isinstance(items, list):
    raise RuntimeError("Embedding 返回格式不正确：缺少 data")

  indexed: list[tuple[int, list[float]]] = []
  for position, item in enumerate(items):
    if not isinstance(item, dict):
      continue
    vector = item.get("embedding")
    if not isinstance(vector, list):
      continue
    normalized = [float(value) for value in vector]
    index_value = item.get("index")
    index = int(index_value) if isinstance(index_value, int) else position
    indexed.append((index, normalized))

  indexed.sort(key=lambda pair: pair[0])
  vectors = [vector for _, vector in indexed]
  if len(vectors) != expected_count:
    raise RuntimeError("Embedding 返回数量和请求数量不一致")
  return vectors


def _batches(items: list[str], size: int) -> list[list[str]]:
  batch_size = max(1, size)
  return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def embed_texts(settings: Settings, texts: list[str], *, task_name: str = "embedding") -> list[list[float]]:
  cleaned = [item.strip() for item in texts if item.strip()]
  if not cleaned:
    return []

  config = load_config(settings).embedding
  started = time.perf_counter()
  vectors: list[list[float]] = []
  runtime_task = None

  try:
    with model_runtime_slot(settings, lane="retrieval", task_name=task_name) as task:
      runtime_task = task
      if is_local_embedding_config(config):
        vectors = embed_texts_locally(config, cleaned)
      else:
        api_key = _resolve_embedding_api_key(config)
        endpoint = _embeddings_endpoint(config.base_url)
        for batch in _batches(cleaned, config.batch_size):
          payload: dict[str, object] = {
            "model": config.model_name,
            "input": batch,
          }
          if config.dimensions is not None:
            payload["dimensions"] = config.dimensions
          response_payload = _request_embeddings(endpoint, api_key, payload)
          vectors.extend(_extract_embedding_vectors(response_payload, len(batch)))

    elapsed = round(time.perf_counter() - started, 3)
    append_app_log(
      settings,
      (
        f"{task_name} completed in {elapsed:.3f}s for {len(cleaned)} chunks "
        f"(queue_wait={runtime_task.queue_wait_seconds if runtime_task is not None else 0.0:.3f}s)"
      ),
    )
    return vectors
  except Exception as error:
    elapsed = round(time.perf_counter() - started, 3)
    if runtime_task is not None:
      mark_model_runtime_cooldown(settings, "retrieval", str(error))
    append_app_log(settings, f"{task_name} failed in {elapsed:.3f}s: {error}", level="ERROR")
    raise


def vector_norm(values: list[float]) -> float:
  return math.sqrt(sum(item * item for item in values))


def cosine_similarity(left: list[float], right: list[float], left_norm: float | None = None, right_norm: float | None = None) -> float:
  next_left_norm = left_norm if left_norm is not None else vector_norm(left)
  next_right_norm = right_norm if right_norm is not None else vector_norm(right)
  if next_left_norm <= 0 or next_right_norm <= 0:
    return 0.0
  dot = sum(a * b for a, b in zip(left, right))
  return dot / (next_left_norm * next_right_norm)
