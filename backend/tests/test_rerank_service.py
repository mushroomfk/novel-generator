from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import AppConfigUpdateRequest, EmbeddingConfig, ModelConfig
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.rerank_service import _rerank_endpoint, rerank_documents


class RerankServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(
          provider="aliyun-bailian",
          base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
          api_key="dashscope-key",
          model_name="qwen3.6-plus",
        ),
        embedding=EmbeddingConfig(),
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_rerank_endpoint_uses_official_compatible_api_path(self) -> None:
    endpoint = _rerank_endpoint("https://dashscope.aliyuncs.com/compatible-mode/v1")

    self.assertEqual(endpoint, "https://dashscope.aliyuncs.com/compatible-api/v1/reranks")

  def test_rerank_endpoint_keeps_explicit_reranks_path(self) -> None:
    endpoint = _rerank_endpoint("https://dashscope.aliyuncs.com/compatible-api/v1/reranks")

    self.assertEqual(endpoint, "https://dashscope.aliyuncs.com/compatible-api/v1/reranks")

  def test_rerank_documents_supports_official_output_results_shape(self) -> None:
    with patch(
      "novel_backend.services.rerank_service._request_rerank",
      return_value={
        "output": {
          "results": [
            {"index": 1, "relevance_score": 0.93},
            {"index": 0, "relevance_score": 0.41},
          ]
        }
      },
    ):
      ranked = rerank_documents(
        self.settings,
        query="潮位窗口",
        documents=["灯塔记录", "涨潮前三分钟开航"],
        top_n=2,
      )

    self.assertEqual(len(ranked), 2)
    self.assertEqual(ranked[0]["document"], "涨潮前三分钟开航")
    self.assertGreater(ranked[0]["score"], ranked[1]["score"])
