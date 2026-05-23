from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib import error as urllib_error
from unittest.mock import patch

from novel_backend.config import Settings
from novel_backend.models import ModelConfig
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.generation_service import _invoke_model
from novel_backend.services.log_service import get_prompt_history_records
from novel_backend.services.model_error_service import classify_model_error
from novel_backend.services.model_http_service import request_json_with_retries


class _FakeHTTPResponse:
  def __init__(self, raw_text: str) -> None:
    self.raw_text = raw_text

  def __enter__(self):
    return self

  def __exit__(self, _exc_type, _exc, _traceback) -> None:
    return None

  def read(self) -> bytes:
    return self.raw_text.encode("utf-8")


class ModelErrorServiceTestCase(unittest.TestCase):
  def test_classifies_common_model_errors(self) -> None:
    self.assertEqual(classify_model_error("模型请求失败: 429 rate limit").kind, "rate_limit")
    self.assertEqual(classify_model_error("模型请求失败: 413 context length exceeded").kind, "context_overflow")
    self.assertEqual(classify_model_error("模型请求失败: 401 invalid api key").kind, "auth")
    self.assertEqual(classify_model_error("模型请求失败: 404 model not found").kind, "model_not_found")
    self.assertEqual(classify_model_error("invalid model name").kind, "model_not_found")

  def test_classifies_ssl_eof_as_network_connection(self) -> None:
    error = "模型请求失败: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)"

    classified = classify_model_error(error)

    self.assertEqual(classified.kind, "network_connection")
    self.assertEqual(classified.title, "模型网络连接中断")
    self.assertTrue(classified.retryable)

  def test_request_json_retries_transient_ssl_eof(self) -> None:
    ssl_eof = urllib_error.URLError(
      "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1000)"
    )
    with patch(
      "novel_backend.services.model_http_service.urllib_request.urlopen",
      side_effect=[ssl_eof, _FakeHTTPResponse('{"ok": true}')],
    ) as urlopen, patch("novel_backend.services.model_http_service.time.sleep") as sleep:
      payload = request_json_with_retries(
        "https://example.com/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        payload={"model": "demo", "messages": []},
        error_prefix="模型请求失败",
        invalid_json_message="模型返回的不是合法 JSON",
        invalid_payload_message="模型返回格式不正确",
      )

    self.assertEqual(payload, {"ok": True})
    self.assertEqual(urlopen.call_count, 2)
    sleep.assert_called_once()

  def test_invoke_model_records_structured_error_history(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      settings = Settings(data_dir=Path(temp_dir))
      initialize_app_storage(settings)
      save_config(
        settings,
        ModelConfig(
          api_key="test-key",
          base_url="https://example.com/v1",
          model_name="demo-model",
        ),
      )

      with patch(
        "novel_backend.services.generation_service._request_chat_completion",
        side_effect=RuntimeError("模型请求失败: 429 rate limit"),
      ):
        with self.assertRaisesRegex(RuntimeError, "模型请求被限流"):
          _invoke_model(
            settings,
            [{"role": "user", "content": "测试"}],
            task_name="error_classification",
          )

      records = get_prompt_history_records(settings, tail=10)["records"]
      self.assertEqual(records[0]["task"], "error_classification")
      self.assertEqual(records[0]["status"], "failed")
      self.assertEqual(records[0]["error_kind"], "rate_limit")
      self.assertEqual(records[0]["error_title"], "模型请求被限流")


if __name__ == "__main__":
  unittest.main()
