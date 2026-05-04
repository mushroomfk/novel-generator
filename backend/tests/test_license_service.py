from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from novel_backend.config import Settings
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.license_service import import_license, validate_license


class LicenseServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_validate_license_requires_import(self) -> None:
    result = validate_license(self.settings)
    self.assertFalse(result.valid)
    self.assertEqual(result.reason, "尚未导入许可证")

  def test_import_license_accepts_unexpired_payload(self) -> None:
    result = import_license(
      self.settings,
      json.dumps(
        {
          "licensee": "测试用户",
          "expires_at": "2099-01-01T00:00:00+00:00",
        },
        ensure_ascii=False,
      ),
    )

    self.assertTrue(result.valid)
    self.assertEqual(result.reason, "测试用户 的许可证有效")

  def test_validate_license_rejects_expired_payload(self) -> None:
    import_license(
      self.settings,
      json.dumps(
        {
          "licensee": "测试用户",
          "expires_at": "2000-01-01T00:00:00+00:00",
        },
        ensure_ascii=False,
      ),
    )

    result = validate_license(self.settings)
    self.assertFalse(result.valid)
    self.assertEqual(result.reason, "许可证已过期")

  def test_validate_license_checks_device_fingerprints(self) -> None:
    payload = {
      "licensee": "设备绑定用户",
      "expires_at": "2099-01-01T00:00:00+00:00",
      "device_fingerprints": ["fingerprint-a", "fingerprint-b", "fingerprint-c"],
    }
    import_license(self.settings, json.dumps(payload, ensure_ascii=False))

    with mock.patch(
      "novel_backend.services.license_service.collect_device_fingerprints",
      return_value=["fingerprint-a", "fingerprint-b", "fingerprint-z"],
    ):
      matched = validate_license(self.settings)

    self.assertTrue(matched.valid)

    with mock.patch(
      "novel_backend.services.license_service.collect_device_fingerprints",
      return_value=["fingerprint-a", "fingerprint-z"],
    ):
      mismatched = validate_license(self.settings)

    self.assertFalse(mismatched.valid)
    self.assertEqual(mismatched.reason, "许可证与当前设备不匹配")


if __name__ == "__main__":
  unittest.main()
