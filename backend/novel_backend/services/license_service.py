from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import uuid
from datetime import datetime, timezone
from hashlib import sha256

from novel_backend.config import Settings
from novel_backend.models import LicenseValidationResult
from novel_backend.services.config_service import license_path
from novel_backend.utils.jsonfile import atomic_write_json, read_json


def _normalize_fingerprints(values: object) -> list[str]:
  if not isinstance(values, list):
    return []

  normalized: list[str] = []
  for item in values:
    if not isinstance(item, str):
      continue
    cleaned = item.strip().lower()
    if cleaned and cleaned not in normalized:
      normalized.append(cleaned)

  return normalized


def _hash_device_value(raw: str) -> str:
  return sha256(raw.encode("utf-8")).hexdigest()


def _collect_machine_id_candidates() -> list[str]:
  candidates: list[str] = []
  system = platform.system().lower()

  if system == "darwin":
    try:
      output = subprocess.check_output(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        text=True,
        stderr=subprocess.DEVNULL,
      )
      match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
      if match:
        candidates.append(match.group(1))
    except Exception:
      pass
  elif system == "windows":
    try:
      output = subprocess.check_output(
        ["reg", "query", r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
        text=True,
        stderr=subprocess.DEVNULL,
      )
      match = re.search(r"MachineGuid\s+REG_SZ\s+([^\r\n]+)", output)
      if match:
        candidates.append(match.group(1).strip())
    except Exception:
      pass
  else:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
      try:
        value = open(path, "r", encoding="utf-8").read().strip()
      except OSError:
        continue
      if value:
        candidates.append(value)

  return candidates


def collect_device_fingerprints() -> list[str]:
  raw_values: list[str] = []
  raw_values.extend(
    item.strip()
    for item in os.getenv("NOVEL_LICENSE_DEVICE_HINTS", "").split(",")
    if item.strip()
  )
  raw_values.extend(_collect_machine_id_candidates())

  node = uuid.getnode()
  if node:
    raw_values.append(f"mac:{node:012x}")

  hostname = platform.node().strip()
  if hostname:
    raw_values.append(f"host:{hostname}")

  system_summary = "|".join(
    item for item in (platform.system(), platform.machine(), platform.processor()) if item
  )
  if system_summary:
    raw_values.append(f"sys:{system_summary}")

  fingerprints: list[str] = []
  for raw in raw_values:
    hashed = _hash_device_value(raw)
    if hashed not in fingerprints:
      fingerprints.append(hashed)

  return fingerprints[:5]


def _parse_expiry(value: object) -> tuple[datetime | None, str | None]:
  if value in (None, ""):
    return None, None
  if not isinstance(value, str):
    return None, "许可证过期时间格式无效"

  normalized = value.strip()
  if not normalized:
    return None, None

  try:
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
  except ValueError:
    return None, "许可证过期时间格式无效"

  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=timezone.utc)

  return parsed.astimezone(timezone.utc), None


def _extract_license_fingerprints(payload: dict[str, object]) -> list[str]:
  for key in ("device_fingerprints", "devices", "fingerprints"):
    values = _normalize_fingerprints(payload.get(key))
    if values:
      return values

  return []


def import_license(settings: Settings, content: str) -> LicenseValidationResult:
  try:
    payload = json.loads(content)
  except json.JSONDecodeError:
    payload = {"raw": content}

  atomic_write_json(license_path(settings), payload)
  return validate_license(settings)


def validate_license(settings: Settings) -> LicenseValidationResult:
  payload = read_json(license_path(settings), None)
  if payload is None:
    return LicenseValidationResult(valid=False, reason="尚未导入许可证")
  if not isinstance(payload, dict):
    return LicenseValidationResult(valid=False, reason="许可证格式无效")

  expires_at, expiry_error = _parse_expiry(payload.get("expires_at"))
  if expiry_error:
    return LicenseValidationResult(valid=False, reason=expiry_error)
  if expires_at is not None and expires_at < datetime.now(timezone.utc):
    return LicenseValidationResult(
      valid=False,
      reason="许可证已过期",
      expires_at=expires_at.isoformat(),
    )

  expected_fingerprints = _extract_license_fingerprints(payload)
  if expected_fingerprints:
    current_fingerprints = set(collect_device_fingerprints())
    match_count = len(current_fingerprints & set(expected_fingerprints))
    required_matches = 2 if len(expected_fingerprints) >= 2 and len(current_fingerprints) >= 2 else 1
    if match_count < required_matches:
      return LicenseValidationResult(
        valid=False,
        reason="许可证与当前设备不匹配",
        expires_at=expires_at.isoformat() if expires_at is not None else None,
      )

  subject = str(payload.get("licensee") or payload.get("subject") or "").strip()
  reason = "许可证有效"
  if subject:
    reason = f"{subject} 的许可证有效"
  return LicenseValidationResult(
    valid=True,
    reason=reason,
    expires_at=expires_at.isoformat() if expires_at is not None else None,
  )
