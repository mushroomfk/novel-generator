from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import AppConfigUpdateRequest, EmbeddingConfig, ModelConfig
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.embedding_service import embed_texts, embedding_config_signature


class EmbeddingServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_local_fastembed_embedding_does_not_require_api_key(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model=ModelConfig(api_key="writer-key"),
        embedding=EmbeddingConfig(
          provider="local-fastembed",
          base_url="builtin://bge-small-zh-v1.5",
          api_key="",
          model_name="BAAI/bge-small-zh-v1.5",
          dimensions=512,
          batch_size=2,
        ),
      ),
    )

    with patch(
      "novel_backend.services.embedding_service.embed_texts_locally",
      return_value=[[0.1, 0.2], [0.3, 0.4]],
    ) as local_embed, patch("novel_backend.services.embedding_service._request_embeddings") as remote_embed:
      vectors = embed_texts(self.settings, ["人物设定", "章节线索"], task_name="unit_local_embedding")

    self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
    local_embed.assert_called_once()
    remote_embed.assert_not_called()
    self.assertIn("local-fastembed", embedding_config_signature(self.settings))
    self.assertIn("ready", embedding_config_signature(self.settings))


if __name__ == "__main__":
  unittest.main()
