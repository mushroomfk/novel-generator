from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os

from novel_backend.utils.jsonfile import atomic_write_text


class JsonFileTestCase(unittest.TestCase):
  def test_atomic_write_text_allows_concurrent_writes_to_same_path(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "thread.json"
      values = [f"value-{index}" for index in range(80)]

      with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(lambda value: atomic_write_text(path, value), values))

      self.assertIn(path.read_text(encoding="utf-8"), values)
      self.assertEqual(list(path.parent.glob("*.tmp")), [])

  def test_atomic_write_text_retries_transient_replace_permission_error(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "thread.json"
      original_replace = os.replace
      calls = 0

      def flaky_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 1:
          raise PermissionError("temporary lock")
        return original_replace(source, target)

      with (
        patch("novel_backend.utils.jsonfile.os.replace", side_effect=flaky_replace),
        patch("novel_backend.utils.jsonfile.time.sleep") as sleep,
      ):
        atomic_write_text(path, "ok")

      self.assertEqual(path.read_text(encoding="utf-8"), "ok")
      self.assertEqual(calls, 2)
      sleep.assert_called_once()


if __name__ == "__main__":
  unittest.main()
