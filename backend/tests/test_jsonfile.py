from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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


if __name__ == "__main__":
  unittest.main()
