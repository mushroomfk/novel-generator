from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import KnowledgeSearchResult
from novel_backend.services.web_research_service import research_historical_reference


class WebResearchServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_missing_bocha_key_returns_clear_domestic_provider_message(self) -> None:
    with (
      patch.dict("os.environ", {"BOCHA_API_KEY": ""}, clear=False),
      patch("novel_backend.services.web_research_service.search_project_knowledge", return_value=[]),
    ):
      result = research_historical_reference(self.settings, "demo", "鸿门宴典故", limit=6)

    self.assertEqual(result.provider, "none")
    self.assertIn("BOCHA_API_KEY", result.answer)
    self.assertIn("bocha: 未配置 BOCHA_API_KEY", result.warning)

  def test_bocha_search_uses_domestic_provider_and_falls_back_without_model(self) -> None:
    captured_payloads: list[dict[str, object]] = []

    def fake_request(_endpoint, *, headers, payload, timeout):
      captured_payloads.append(payload)
      self.assertIn("Authorization", headers)
      return {
        "webPages": {
          "value": [
            {
              "name": "鸿门宴 - 中国历史典故",
              "url": "https://example.cn/hongmenyan",
              "snippet": "鸿门宴常被用来指代暗藏杀机的宴会场面。",
              "siteName": "示例中文站",
              "datePublished": "2026-01-01",
            }
          ]
        }
      }

    local_hits = [
      KnowledgeSearchResult(
        source="项目资料",
        section="人物设定",
        preview="主角被邀请赴宴。",
        match_type="keyword",
      )
    ]

    with (
      patch.dict("os.environ", {"BOCHA_API_KEY": "bocha-key"}, clear=False),
      patch("novel_backend.services.web_research_service._request_json", side_effect=fake_request),
      patch("novel_backend.services.web_research_service.search_project_knowledge", return_value=local_hits),
      patch("novel_backend.services.web_research_service._invoke_model", side_effect=RuntimeError("no model")),
    ):
      result = research_historical_reference(self.settings, "demo", "鸿门宴", limit=6)

    self.assertEqual(result.provider, "bocha")
    self.assertEqual(result.sources[0].site, "示例中文站")
    self.assertIn("鸿门宴常被用来指代", result.answer)
    self.assertEqual(result.local_hits, local_hits)
    self.assertEqual(captured_payloads[0]["summary"], True)
    self.assertEqual(captured_payloads[0]["freshness"], "noLimit")


if __name__ == "__main__":
  unittest.main()
