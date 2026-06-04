from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import KnowledgeSearchResult, ModelConfig
from novel_backend.services.config_service import save_config
from novel_backend.services.web_research_service import research_historical_reference


class WebResearchServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_missing_domestic_keys_returns_clear_provider_message(self) -> None:
    with (
      patch.dict(
        "os.environ",
        {"DASHSCOPE_API_KEY": "", "NOVEL_MODEL_API_KEY": "", "BOCHA_API_KEY": ""},
        clear=False,
      ),
      patch("novel_backend.services.web_research_service.search_project_knowledge", return_value=[]),
    ):
      result = research_historical_reference(self.settings, "demo", "鸿门宴典故", limit=6)

    self.assertEqual(result.provider, "none")
    self.assertIn("阿里百炼 API Key", result.answer)
    self.assertIn("BOCHA_API_KEY", result.answer)
    self.assertIn("aliyun-bailian: 未配置阿里百炼 API Key", result.warning)
    self.assertIn("bocha: 未配置 BOCHA_API_KEY", result.warning)

  def test_aliyun_responses_search_uses_existing_bailian_model_key(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        provider="aliyun-bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
        model_name="qwen3.6-plus",
        max_tokens=4096,
      ),
    )
    captured_requests: list[dict[str, object]] = []

    def fake_request(endpoint, *, headers, payload, timeout):
      captured_requests.append(
        {
          "endpoint": endpoint,
          "headers": headers,
          "payload": payload,
          "timeout": timeout,
        }
      )
      return {
        "output_text": "### 可用素材\n鸿门宴可用于宴席暗杀和政治试探场景。",
        "output": [
          {
            "type": "message",
            "content": [
              {
                "type": "output_text",
                "text": "鸿门宴可用于宴席暗杀和政治试探场景。",
                "annotations": [
                  {
                    "type": "url_citation",
                    "title": "鸿门宴资料",
                    "url": "https://example.cn/hongmenyan",
                  }
                ],
              }
            ],
          }
        ],
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
      patch.dict("os.environ", {"DASHSCOPE_API_KEY": "", "NOVEL_MODEL_API_KEY": ""}, clear=False),
      patch("novel_backend.services.web_research_service._request_json", side_effect=fake_request),
      patch("novel_backend.services.web_research_service.search_project_knowledge", return_value=local_hits) as mocked_search,
    ):
      result = research_historical_reference(self.settings, "demo", "鸿门宴", limit=6, chapter_index=58)

    self.assertEqual(result.provider, "aliyun-bailian")
    self.assertIn("宴席暗杀", result.answer)
    self.assertEqual(result.local_hits, local_hits)
    mocked_search.assert_called_once_with(self.settings, "demo", "鸿门宴", limit=4, chapter_index=58)
    self.assertEqual(result.sources[0].title, "鸿门宴资料")
    self.assertEqual(result.sources[0].provider, "aliyun-bailian")
    self.assertEqual(
      captured_requests[0]["endpoint"],
      "https://dashscope.aliyuncs.com/compatible-mode/v1/responses",
    )
    self.assertEqual(captured_requests[0]["headers"]["Authorization"], "Bearer dashscope-key")
    payload = captured_requests[0]["payload"]
    self.assertEqual(payload["model"], "qwen3.6-plus")
    self.assertIn("目标章节：第 58 章", payload["input"])
    self.assertIn({"type": "web_search"}, payload["tools"])
    self.assertIn({"type": "web_extractor"}, payload["tools"])

  def test_aliyun_search_extracts_sources_from_answer_links(self) -> None:
    save_config(
      self.settings,
      ModelConfig(
        provider="aliyun-bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="dashscope-key",
        model_name="qwen3.6-plus",
      ),
    )

    def fake_request(_endpoint, *, headers, payload, timeout):
      return {
        "output_text": "### 联网来源\n- [史记资料](https://example.cn/shiji)\n",
        "output": [],
      }

    with (
      patch.dict("os.environ", {"DASHSCOPE_API_KEY": "", "NOVEL_MODEL_API_KEY": ""}, clear=False),
      patch("novel_backend.services.web_research_service._request_json", side_effect=fake_request),
      patch("novel_backend.services.web_research_service.search_project_knowledge", return_value=[]),
    ):
      result = research_historical_reference(self.settings, "demo", "鸿门宴", limit=6)

    self.assertEqual(result.provider, "aliyun-bailian")
    self.assertEqual(result.sources[0].title, "史记资料")
    self.assertEqual(result.sources[0].url, "https://example.cn/shiji")

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
      patch.dict(
        "os.environ",
        {"DASHSCOPE_API_KEY": "", "NOVEL_MODEL_API_KEY": "", "BOCHA_API_KEY": "bocha-key"},
        clear=False,
      ),
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
