from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import AppConfigUpdateRequest, ChapterAutoRepairConfig, EmbeddingConfig, ModelConfig
from novel_backend.services.config_service import initialize_app_storage, load_config, save_config


class ConfigServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_initialize_storage_uses_qwen36_and_embedding_2048_by_default(self) -> None:
    config = load_config(self.settings)

    self.assertEqual(config.model.model_name, "qwen3.6-plus")
    self.assertEqual(config.embedding.model_name, "text-embedding-v4")
    self.assertEqual(config.embedding.dimensions, 2048)
    self.assertTrue(config.chapter_auto_repair.enabled)
    self.assertEqual(config.chapter_auto_repair.score_threshold, 65)
    self.assertEqual(config.chapter_auto_repair.max_rounds, 1)

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
      ),
    )

    config = save_config(self.settings, ModelConfig(model_name="qwen3.6-plus"))

    self.assertEqual(config.chapter_auto_repair.score_threshold, 70)
    self.assertEqual(config.chapter_auto_repair.max_rounds, 2)

  def test_save_model_config_auto_uses_aliyun_embedding_for_aliyun_model(self) -> None:
    config = save_config(
      self.settings,
      ModelConfig(
        provider="aliyun-bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
        model_name="qwen-max",
      ),
    )

    self.assertEqual(config.embedding.provider, "aliyun-bailian")
    self.assertEqual(config.embedding.base_url, "https://dashscope.aliyuncs.com/compatible-mode/v1")
    self.assertEqual(config.embedding.model_name, "text-embedding-v4")
    self.assertEqual(config.embedding.dimensions, 2048)
    self.assertEqual(config.embedding.api_key, "dashscope-key")
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
      ),
    )

    self.assertEqual(config.embedding.provider, "openai-compatible")
    self.assertEqual(config.embedding.base_url, "https://api.openai.com/v1")
    self.assertEqual(config.embedding.model_name, "text-embedding-3-small")
    self.assertIsNone(config.embedding.dimensions)
    self.assertEqual(config.embedding.api_key, "embedding-key")
    self.assertEqual(config.embedding.retrieval_k, 9)
    self.assertEqual(config.embedding.batch_size, 4)

  def test_save_model_config_auto_uses_doubao_embedding_for_volcengine_model(self) -> None:
    config = save_config(
      self.settings,
      ModelConfig(
        provider="volcengine-ark",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="ark-key",
        model_name="doubao-seed-2-0-pro-260215",
      ),
    )

    self.assertEqual(config.embedding.provider, "volcengine-ark")
    self.assertEqual(config.embedding.base_url, "https://ark.cn-beijing.volces.com/api/coding/v3")
    self.assertEqual(config.embedding.model_name, "doubao-embedding-vision")
    self.assertIsNone(config.embedding.dimensions)
    self.assertEqual(config.embedding.api_key, "ark-key")

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
