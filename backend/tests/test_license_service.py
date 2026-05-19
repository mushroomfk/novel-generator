from __future__ import annotations

import json
import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from novel_backend.api.license_guard import require_valid_license
from novel_backend.config import Settings
from novel_backend.services.config_service import initialize_app_storage
from novel_backend.services.license_service import base64url_encode, canonical_license_payload, import_license, validate_license


class LicenseServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    self.private_key = Ed25519PrivateKey.generate()
    public_key = self.private_key.public_key()
    public_raw = public_key.public_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw,
    )
    self._public_key_patch = mock.patch.dict(os.environ, {"NOVEL_LICENSE_PUBLIC_KEY": base64url_encode(public_raw)})
    self._public_key_patch.start()

  def tearDown(self) -> None:
    self._public_key_patch.stop()
    self._temp_dir.cleanup()

  def _fake_request(self):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=self.settings)))

  def _signed_license(self, payload: dict[str, object]) -> str:
    signature = self.private_key.sign(canonical_license_payload(payload))
    return json.dumps(
      {
        "algorithm": "ed25519",
        "payload": payload,
        "signature": base64url_encode(signature),
      },
      ensure_ascii=False,
    )

  def test_validate_license_requires_import(self) -> None:
    result = validate_license(self.settings)
    self.assertFalse(result.valid)
    self.assertEqual(result.reason, "尚未导入许可证")

  def test_import_license_accepts_unexpired_payload(self) -> None:
    result = import_license(
      self.settings,
      self._signed_license(
        {
          "licensee": "测试用户",
          "expires_at": "2099-01-01T00:00:00+00:00",
        }
      ),
    )

    self.assertTrue(result.valid)
    self.assertEqual(result.reason, "测试用户 的许可证有效")

  def test_import_license_accepts_permanent_payload(self) -> None:
    result = import_license(
      self.settings,
      self._signed_license(
        {
          "licensee": "永久测试用户",
          "permanent": True,
        }
      ),
    )

    self.assertTrue(result.valid)
    self.assertEqual(result.reason, "永久测试用户 的永久许可证有效")
    self.assertIsNone(result.expires_at)

  def test_import_license_rejects_plain_text_payload(self) -> None:
    result = import_license(self.settings, "not-a-json-license")

    self.assertFalse(result.valid)
    self.assertEqual(result.reason, "许可证内容必须是 JSON 对象")
    self.assertEqual(validate_license(self.settings).reason, "尚未导入许可证")

  def test_import_license_rejects_unsigned_payload(self) -> None:
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

    self.assertFalse(result.valid)
    self.assertEqual(result.reason, "许可证签名算法无效")
    self.assertEqual(validate_license(self.settings).reason, "尚未导入许可证")

  def test_import_license_rejects_tampered_payload(self) -> None:
    document = json.loads(
      self._signed_license(
        {
          "licensee": "测试用户",
          "expires_at": "2099-01-01T00:00:00+00:00",
        }
      )
    )
    document["payload"]["expires_at"] = "2999-01-01T00:00:00+00:00"

    result = import_license(self.settings, json.dumps(document, ensure_ascii=False))

    self.assertFalse(result.valid)
    self.assertEqual(result.reason, "许可证签名无效")

  def test_import_license_requires_subject_and_expiry(self) -> None:
    missing_subject = import_license(
      self.settings,
      self._signed_license({"expires_at": "2099-01-01T00:00:00+00:00"}),
    )
    self.assertFalse(missing_subject.valid)
    self.assertEqual(missing_subject.reason, "许可证缺少授权对象")

    missing_expiry = import_license(
      self.settings,
      self._signed_license({"licensee": "测试用户"}),
    )
    self.assertFalse(missing_expiry.valid)
    self.assertEqual(missing_expiry.reason, "许可证缺少过期时间")

    invalid_permanent = import_license(
      self.settings,
      self._signed_license({"licensee": "测试用户", "permanent": "true"}),
    )
    self.assertFalse(invalid_permanent.valid)
    self.assertEqual(invalid_permanent.reason, "许可证永久字段格式无效")

  def test_validate_license_rejects_expired_payload(self) -> None:
    import_license(
      self.settings,
      self._signed_license(
        {
          "licensee": "测试用户",
          "expires_at": "2000-01-01T00:00:00+00:00",
        }
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
    import_license(self.settings, self._signed_license(payload))

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

  def test_license_guard_rejects_unlicensed_request(self) -> None:
    with self.assertRaises(HTTPException) as caught:
      require_valid_license(self._fake_request())

    self.assertEqual(caught.exception.status_code, 403)
    self.assertEqual(caught.exception.detail["code"], "license_required")

  def test_license_guard_accepts_valid_license(self) -> None:
    import_license(
      self.settings,
      self._signed_license(
        {
          "licensee": "测试用户",
          "expires_at": "2099-01-01T00:00:00+00:00",
        }
      ),
    )

    self.assertIsNone(require_valid_license(self._fake_request()))


if __name__ == "__main__":
  unittest.main()
