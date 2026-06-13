from __future__ import annotations

import asyncio
import json
import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.exceptions import RequestValidationError

from novel_backend.api import generate, studio
from novel_backend.app import LOCAL_ORIGIN_PATTERN, create_app
from novel_backend.config import Settings, reset_settings_cache
from novel_backend.models import AGENT_MESSAGE_CONTENT_MAX_LENGTH
from novel_backend import __version__


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

  def test_cors_origins_env_accepts_comma_separated_values(self) -> None:
    with patch.dict(
      os.environ,
      {"NOVEL_CORS_ORIGINS": "http://localhost:1420,http://127.0.0.1:1420"},
    ):
      settings = Settings()

    self.assertEqual(settings.cors_origins, ["http://localhost:1420", "http://127.0.0.1:1420"])

  def test_cors_origins_env_accepts_json_array(self) -> None:
    with patch.dict(
      os.environ,
      {"NOVEL_CORS_ORIGINS": '["http://localhost:1420","http://127.0.0.1:1420"]'},
    ):
      settings = Settings()

    self.assertEqual(settings.cors_origins, ["http://localhost:1420", "http://127.0.0.1:1420"])

  def test_default_app_version_uses_backend_package_version(self) -> None:
    self.assertEqual(Settings().app_version, __version__)


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


class AppEnvelopeTestCase(unittest.TestCase):
  def test_chapter_prompt_preview_routes_use_success_envelope(self) -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=Settings())))
    preview = SimpleNamespace(model_dump=lambda mode="json": {"editable_prompt": "提示词"})

    with patch("novel_backend.api.generate.require_valid_license"), patch(
      "novel_backend.api.generate.chapter_workflow_prompt_preview",
      return_value=preview,
    ):
      workflow_payload = asyncio.run(generate.preview_chapter_workflow_prompt(request, object()))

    with patch("novel_backend.api.studio.require_valid_license"), patch(
      "novel_backend.api.studio.chapter_generate_prompt_preview",
      return_value=preview,
    ):
      generate_payload = asyncio.run(studio.preview_chapter_generate_prompt(request, object()))

    self.assertEqual(workflow_payload, {"ok": True, "data": {"editable_prompt": "提示词"}})
    self.assertEqual(generate_payload, {"ok": True, "data": {"editable_prompt": "提示词"}})


if __name__ == "__main__":
  unittest.main()
