from __future__ import annotations

import ssl
import unittest
from urllib import error as urllib_error
from unittest.mock import patch

from novel_backend.services.model_transport_service import is_retryable_transport_error, request_json


class FakeResponse:
  def __init__(self, body: str):
    self.body = body

  def __enter__(self) -> "FakeResponse":
    return self

  def __exit__(self, _exc_type, _exc, _traceback) -> None:
    return None

  def read(self) -> bytes:
    return self.body.encode("utf-8")


class ModelTransportServiceTestCase(unittest.TestCase):
  def test_request_json_retries_ssl_eof_then_returns_payload(self) -> None:
    ssl_error = ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")

    with (
      patch(
        "novel_backend.services.model_transport_service.urllib_request.urlopen",
        side_effect=[urllib_error.URLError(ssl_error), FakeResponse('{"ok": true}')],
      ) as urlopen,
      patch("novel_backend.services.model_transport_service.time.sleep") as sleep,
    ):
      payload = request_json(
        "https://example.com/v1/chat/completions",
        "test-key",
        {"model": "demo"},
        failure_label="模型请求失败",
        invalid_json_message="模型返回的不是合法 JSON",
        invalid_format_message="模型返回格式不正确",
      )

    self.assertEqual(payload, {"ok": True})
    self.assertEqual(urlopen.call_count, 2)
    sleep.assert_called_once_with(0.8)

  def test_retryable_transport_error_matches_remote_disconnect(self) -> None:
    self.assertTrue(is_retryable_transport_error("Remote end closed connection without response"))

