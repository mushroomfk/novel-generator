from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import (
  AppConfigUpdateRequest,
  ChapterAutoRepairConfig,
  EmbeddingConfig,
  ModelConfig,
  ModelConfigTestRequest,
  ModelRuntimeConfig,
  ReviewModelConfig,
)
from novel_backend.services.config_service import initialize_app_storage, load_config, run_model_config_test, save_config


class ConfigServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_initialize_storage_uses_qwen36_and_local_embedding_by_default(self) -> None:
    config = load_config(self.settings)

    self.assertEqual(config.model.model_name, "qwen3.6-plus")
    self.assertIsNone(config.model.temperature)
    self.assertEqual(config.embedding.provider, "local-fastembed")
    self.assertEqual(config.embedding.base_url, "builtin://bge-small-zh-v1.5")
    self.assertEqual(config.embedding.model_name, "BAAI/bge-small-zh-v1.5")
    self.assertEqual(config.embedding.dimensions, 512)
    self.assertFalse(config.review_model.enabled)
    self.assertIsNone(config.review_model.temperature)
    self.assertTrue(config.chapter_auto_repair.enabled)
    self.assertEqual(config.chapter_auto_repair.score_threshold, 65)
    self.assertEqual(config.chapter_auto_repair.max_rounds, 2)
    self.assertEqual(config.model_runtime.max_chat_concurrency, 1)
    self.assertEqual(config.model_runtime.max_retrieval_concurrency, 1)
    self.assertEqual(config.model_runtime.chapter_candidate_mode, "standard")

  def test_save_config_persists_chapter_auto_repair_settings(self) -> None:
    config = save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(model_name="demo-model"),
        chapter_auto_repair=ChapterAutoRepairConfig(
          enabled=False,
          score_threshold=72,
          max_rounds=2,
        ),
      ),
    )

    self.assertFalse(config.chapter_auto_repair.enabled)
    self.assertEqual(config.chapter_auto_repair.score_threshold, 72)
    self.assertEqual(config.chapter_auto_repair.max_rounds, 2)

    loaded = load_config(self.settings)
    self.assertFalse(loaded.chapter_auto_repair.enabled)
    self.assertEqual(loaded.chapter_auto_repair.score_threshold, 72)
    self.assertEqual(loaded.chapter_auto_repair.max_rounds, 2)

  def test_save_model_config_preserves_chapter_auto_repair_settings(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(model_name="demo-model"),
        chapter_auto_repair=ChapterAutoRepairConfig(score_threshold=70, max_rounds=2),
        model_runtime=ModelRuntimeConfig(background_requires_idle_seconds=15, chapter_candidate_mode="deep"),
      ),
    )

    config = save_config(self.settings, ModelConfig(model_name="qwen3.6-plus"))

    self.assertEqual(config.chapter_auto_repair.score_threshold, 70)
    self.assertEqual(config.chapter_auto_repair.max_rounds, 2)
    self.assertEqual(config.model_runtime.background_requires_idle_seconds, 15)
    self.assertEqual(config.model_runtime.chapter_candidate_mode, "deep")

  def test_load_config_migrates_legacy_single_round_auto_repair(self) -> None:
    saved = save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(model_name="demo-model"),
        chapter_auto_repair=ChapterAutoRepairConfig(enabled=True, score_threshold=65, max_rounds=1),
      ),
    )
    self.assertEqual(saved.chapter_auto_repair.max_rounds, 1)

    config = load_config(self.settings)

    self.assertEqual(config.chapter_auto_repair.max_rounds, 2)
    reloaded = load_config(self.settings)
    self.assertEqual(reloaded.chapter_auto_repair.max_rounds, 2)

  def test_save_model_config_keeps_local_embedding_for_aliyun_model(self) -> None:
    config = save_config(
      self.settings,
      ModelConfig(
        provider="aliyun-bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
        model_name="qwen-max",
      ),
    )

    self.assertEqual(config.embedding.provider, "local-fastembed")
    self.assertEqual(config.embedding.base_url, "builtin://bge-small-zh-v1.5")
    self.assertEqual(config.embedding.model_name, "BAAI/bge-small-zh-v1.5")
    self.assertEqual(config.embedding.dimensions, 512)
    self.assertEqual(config.embedding.api_key, "")
    self.assertEqual(config.embedding.retrieval_k, 6)
    self.assertEqual(config.embedding.batch_size, 8)

  def test_save_config_preserves_separate_embedding_for_known_model_family(self) -> None:
    config = save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          provider="aliyun-bailian",
          base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
          api_key="dashscope-key",
          model_name="qwen-max",
        ),
        embedding=EmbeddingConfig(
          provider="openai-compatible",
          base_url="https://api.openai.com/v1",
          api_key="embedding-key",
          model_name="text-embedding-3-small",
          dimensions=None,
          retrieval_k=9,
          batch_size=4,
        ),
        review_model=ReviewModelConfig(
          enabled=True,
          base_url="https://review.example.com/v1",
          api_key="review-key",
          model_name="review-model",
          max_tokens=2048,
          temperature=0.1,
        ),
      ),
    )

    self.assertEqual(config.embedding.provider, "openai-compatible")
    self.assertEqual(config.embedding.base_url, "https://api.openai.com/v1")
    self.assertEqual(config.embedding.model_name, "text-embedding-3-small")
    self.assertIsNone(config.embedding.dimensions)
    self.assertEqual(config.embedding.api_key, "embedding-key")
    self.assertEqual(config.embedding.retrieval_k, 9)
    self.assertEqual(config.embedding.batch_size, 4)
    self.assertTrue(config.review_model.enabled)
    self.assertEqual(config.review_model.model_name, "review-model")

  def test_save_legacy_model_config_keeps_existing_embedding_for_aliyun_model(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        embedding=EmbeddingConfig(
          provider="custom-embedding",
          base_url="https://embedding.example.com/v1",
          api_key="embedding-key",
          model_name="custom-embedding-model",
          retrieval_k=9,
          batch_size=5,
        ),
      ),
    )

    config = save_config(
      self.settings,
      ModelConfig(
        provider="aliyun-bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
        model_name="qwen-max",
      ),
    )

    self.assertEqual(config.embedding.provider, "custom-embedding")
    self.assertEqual(config.embedding.base_url, "https://embedding.example.com/v1")
    self.assertEqual(config.embedding.model_name, "custom-embedding-model")
    self.assertEqual(config.embedding.api_key, "embedding-key")
    self.assertEqual(config.embedding.retrieval_k, 9)
    self.assertEqual(config.embedding.batch_size, 5)

  def test_save_legacy_model_config_keeps_local_embedding_for_volcengine_model(self) -> None:
    config = save_config(
      self.settings,
      ModelConfig(
        provider="volcengine-ark",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ark-key",
        model_name="doubao-seed-2-0-pro-260215",
      ),
    )

    self.assertEqual(config.embedding.provider, "local-fastembed")
    self.assertEqual(config.embedding.base_url, "builtin://bge-small-zh-v1.5")
    self.assertEqual(config.embedding.model_name, "BAAI/bge-small-zh-v1.5")
    self.assertEqual(config.embedding.dimensions, 512)
    self.assertEqual(config.embedding.api_key, "")

  def test_save_legacy_model_config_preserves_review_model(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          provider="aliyun-bailian",
          base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
          api_key="dashscope-key",
          model_name="qwen-max",
        ),
        review_model=ReviewModelConfig(
          enabled=True,
          base_url="https://review.example.com/v1",
          api_key="review-key",
          model_name="review-model",
        ),
      ),
    )

    config = save_config(
      self.settings,
      ModelConfig(
        provider="custom-provider",
        base_url="https://example.com/v1",
        api_key="main-key",
        model_name="main-model",
      ),
    )

    self.assertTrue(config.review_model.enabled)
    self.assertEqual(config.review_model.base_url, "https://review.example.com/v1")
    self.assertEqual(config.review_model.model_name, "review-model")

  def test_load_config_preserves_separate_embedding_for_known_model_family(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          provider="volcengine-ark",
          base_url="https://ark.cn-beijing.volces.com/api/v3",
          api_key="ark-key",
          model_name="doubao-seed-2-0-pro-260215",
        ),
        embedding=EmbeddingConfig(
          provider="openai-compatible",
          base_url="https://api.openai.com/v1",
          api_key="embedding-key",
          model_name="text-embedding-3-small",
          dimensions=None,
        ),
      ),
    )

    loaded = load_config(self.settings)

    self.assertEqual(loaded.embedding.provider, "openai-compatible")
    self.assertEqual(loaded.embedding.base_url, "https://api.openai.com/v1")
    self.assertEqual(loaded.embedding.model_name, "text-embedding-3-small")
    self.assertIsNone(loaded.embedding.dimensions)

  def test_save_config_keeps_existing_embedding_for_unknown_model_family(self) -> None:
    config = save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          provider="custom-provider",
          base_url="https://example.com/v1",
          api_key="custom-key",
          model_name="demo-model",
        ),
        embedding=EmbeddingConfig(
          provider="custom-embedding",
          base_url="https://embedding.example.com/v1",
          api_key="embedding-key",
          model_name="custom-embedding-model",
          retrieval_k=7,
          batch_size=3,
        ),
      ),
    )

    self.assertEqual(config.embedding.provider, "custom-embedding")
    self.assertEqual(config.embedding.base_url, "https://embedding.example.com/v1")
    self.assertEqual(config.embedding.model_name, "custom-embedding-model")
    self.assertEqual(config.embedding.api_key, "embedding-key")

  def test_model_config_test_uses_current_payload_without_saving(self) -> None:
    request = ModelConfigTestRequest(
      model=ModelConfig(
        provider="custom",
        base_url="https://writer.local/v1",
        api_key="writer-key",
        model_name="writer-model",
      ),
      embedding=EmbeddingConfig(
        provider="custom",
        base_url="https://embedding.local/v1",
        api_key="embedding-key",
        model_name="embedding-model",
        dimensions=None,
      ),
      review_model=ReviewModelConfig(
        enabled=True,
        base_url="https://review.local/v1",
        api_key="review-key",
        model_name="review-model",
      ),
    )

    def fake_request(endpoint: str, **kwargs):
      payload = kwargs["payload"]
      if endpoint.endswith("/embeddings"):
        return {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}
      return {"choices": [{"message": {"content": f"OK {payload['model']}"}}]}

    with patch("novel_backend.services.config_service.request_json_with_retries", side_effect=fake_request) as mocked_request:
      result = run_model_config_test(self.settings, request)

    self.assertEqual(result.status, "passed")
    self.assertEqual([item.status for item in result.items], ["passed", "passed", "passed"])
    called_models = [call.kwargs["payload"]["model"] for call in mocked_request.call_args_list]
    self.assertEqual(called_models, ["writer-model", "embedding-model", "review-model"])
    self.assertTrue(all("retry_delays" not in call.kwargs for call in mocked_request.call_args_list))
    self.assertEqual(load_config(self.settings).model.model_name, "qwen3.6-plus")

  def test_model_config_test_reports_model_error(self) -> None:
    request = ModelConfigTestRequest(
      target="model",
      model=ModelConfig(
        base_url="https://writer.local/v1",
        api_key="bad-key",
        model_name="writer-model",
      ),
    )

    with patch(
      "novel_backend.services.config_service.request_json_with_retries",
      side_effect=RuntimeError("模型测试失败: 401 invalid_api_key"),
    ):
      result = run_model_config_test(self.settings, request)

    self.assertEqual(result.status, "failed")
    self.assertEqual(result.items[0].status, "failed")
    self.assertIn("模型认证失败", result.items[0].message)
    self.assertIn("invalid_api_key", result.items[0].message)

  def test_model_config_test_uses_local_embedding_without_api_key(self) -> None:
    request = ModelConfigTestRequest(
      target="embedding",
      embedding=EmbeddingConfig(
        provider="local-fastembed",
        base_url="builtin://bge-small-zh-v1.5",
        api_key="",
        model_name="BAAI/bge-small-zh-v1.5",
        dimensions=512,
      ),
    )

    with patch("novel_backend.services.config_service.assert_local_embedding_model_available") as available, patch(
      "novel_backend.services.config_service.embed_texts_locally",
      return_value=[[0.1, 0.2, 0.3]],
    ) as embed, patch("novel_backend.services.config_service.request_json_with_retries") as request_json:
      result = run_model_config_test(self.settings, request)

    self.assertEqual(result.status, "passed")
    self.assertEqual(result.items[0].status, "passed")
    self.assertIn("BAAI/bge-small-zh-v1.5 可用", result.items[0].message)
    available.assert_called_once()
    embed.assert_called_once()
    request_json.assert_not_called()
