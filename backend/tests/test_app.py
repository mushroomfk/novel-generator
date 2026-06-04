from __future__ import annotations

import asyncio
import json
import re
import unittest

from fastapi.exceptions import RequestValidationError

from novel_backend.app import LOCAL_ORIGIN_PATTERN, create_app
from novel_backend.config import reset_settings_cache
from novel_backend.models import AGENT_MESSAGE_CONTENT_MAX_LENGTH


class AppCorsTestCase(unittest.TestCase):
  def test_local_preview_origin_matches_cors_pattern(self) -> None:
    pattern = re.compile(LOCAL_ORIGIN_PATTERN)

    self.assertIsNotNone(pattern.match("http://127.0.0.1:53918"))
    self.assertIsNotNone(pattern.match("http://localhost:1420"))
    self.assertIsNotNone(pattern.match("https://tauri.localhost"))
    self.assertIsNotNone(pattern.match("tauri://localhost"))

  def test_remote_origin_does_not_match_cors_pattern(self) -> None:
    pattern = re.compile(LOCAL_ORIGIN_PATTERN)

    self.assertIsNone(pattern.match("https://example.com"))
    self.assertIsNone(pattern.match("http://192.168.1.10:1420"))


class AppValidationErrorTestCase(unittest.TestCase):
  def test_validation_error_uses_error_envelope(self) -> None:
    try:
      reset_settings_cache()
      app = create_app()
      handler = app.exception_handlers[RequestValidationError]
      response = asyncio.run(
        handler(
          None,
          RequestValidationError(
            [
              {
                "loc": ("body", "messages", 0, "content"),
                "msg": f"String should have at most {AGENT_MESSAGE_CONTENT_MAX_LENGTH} characters",
                "type": "string_too_long",
              }
            ]
          ),
        )
      )
    finally:
      reset_settings_cache()

    self.assertEqual(response.status_code, 422)
    payload = json.loads(response.body)
    self.assertFalse(payload["ok"])
    self.assertEqual(payload["error"]["code"], "validation_error")
    self.assertIn("messages.0.content", payload["error"]["message"])


if __name__ == "__main__":
  unittest.main()
