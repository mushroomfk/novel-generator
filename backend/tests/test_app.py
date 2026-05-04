from __future__ import annotations

import re
import unittest

from novel_backend.app import LOCAL_ORIGIN_PATTERN


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


if __name__ == "__main__":
  unittest.main()
