from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from novel_backend.models import EmbeddingConfig


LOCAL_FASTEMBED_PROVIDER = "local-fastembed"
LOCAL_FASTEMBED_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
LOCAL_FASTEMBED_DEFAULT_BASE_URL = "builtin://bge-small-zh-v1.5"
LOCAL_FASTEMBED_DEFAULT_DIMENSIONS = 512
LOCAL_FASTEMBED_CACHE_DIR_ENV = "NOVEL_LOCAL_EMBEDDING_CACHE_DIR"

_SUPPORTED_LOCAL_MODELS = {
  "BAAI/bge-small-zh-v1.5": {
    "aliases": {"bge-small-zh-v1.5", "fast-bge-small-zh-v1.5"},
    "cache_dir_name": "fast-bge-small-zh-v1.5",
    "dimensions": LOCAL_FASTEMBED_DEFAULT_DIMENSIONS,
  }
}


class LocalEmbeddingError(RuntimeError):
  pass


def is_local_embedding_config(config: "EmbeddingConfig") -> bool:
  provider = config.provider.strip().lower()
  base_url = config.base_url.strip().lower()
  return provider == LOCAL_FASTEMBED_PROVIDER or base_url.startswith(("builtin://", "local://"))


def normalize_local_embedding_model_name(model_name: str) -> str:
  cleaned = model_name.strip() or LOCAL_FASTEMBED_DEFAULT_MODEL
  for canonical, metadata in _SUPPORTED_LOCAL_MODELS.items():
    aliases = metadata["aliases"]
    if cleaned == canonical or cleaned in aliases:
      return canonical
  raise LocalEmbeddingError(f"不支持的本地 Embedding 模型：{cleaned}")


def local_embedding_dimensions(model_name: str) -> int:
  canonical = normalize_local_embedding_model_name(model_name)
  return int(_SUPPORTED_LOCAL_MODELS[canonical]["dimensions"])


def _package_root() -> Path:
  if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    return Path(sys._MEIPASS) / "novel_backend"
  return Path(__file__).resolve().parents[1]


def local_embedding_cache_root() -> Path:
  configured = os.getenv(LOCAL_FASTEMBED_CACHE_DIR_ENV, "").strip()
  if configured:
    return Path(configured).expanduser()
  return _package_root() / "assets" / "embedding_models"


def _local_model_dir(model_name: str, cache_root: Path) -> Path:
  canonical = normalize_local_embedding_model_name(model_name)
  return cache_root / str(_SUPPORTED_LOCAL_MODELS[canonical]["cache_dir_name"])


def assert_local_embedding_model_available(model_name: str, cache_root: Path | None = None) -> Path:
  root = cache_root or local_embedding_cache_root()
  model_dir = _local_model_dir(model_name, root)
  required_files = ("model_optimized.onnx", "tokenizer.json", "config.json")
  missing = [file_name for file_name in required_files if not (model_dir / file_name).is_file()]
  if missing:
    raise LocalEmbeddingError(
      f"本地 Embedding 模型文件不完整：{model_dir}，缺少 {', '.join(missing)}。"
    )
  return model_dir


@lru_cache(maxsize=2)
def _load_fastembed_model(model_name: str, cache_root: str):
  try:
    from fastembed import TextEmbedding
  except Exception as error:
    raise LocalEmbeddingError("缺少 fastembed 依赖，无法加载内置本地 Embedding 模型。") from error

  model_dir = assert_local_embedding_model_available(model_name, Path(cache_root))
  return TextEmbedding(
    model_name=model_name,
    cache_dir=cache_root,
    specific_model_path=str(model_dir),
    lazy_load=False,
  )


def embed_texts_locally(config: "EmbeddingConfig", texts: list[str]) -> list[list[float]]:
  cleaned = [item.strip() for item in texts if item.strip()]
  if not cleaned:
    return []

  model_name = normalize_local_embedding_model_name(config.model_name)
  cache_root = local_embedding_cache_root()
  assert_local_embedding_model_available(model_name, cache_root)
  model = _load_fastembed_model(model_name, str(cache_root))
  vectors = model.embed(cleaned, batch_size=max(1, config.batch_size))
  return [[float(value) for value in vector] for vector in vectors]
