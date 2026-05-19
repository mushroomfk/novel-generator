#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from novel_backend.services.license_service import (
  _base64url_decode,
  base64url_encode,
  canonical_license_payload,
)


def utc_now_text() -> str:
  return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_private_key(value: str) -> str:
  path = Path(value).expanduser()
  if path.exists():
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("private_key"), str):
      return payload["private_key"]
    raise ValueError(f"private key file has no private_key field: {path}")

  return value


def sign_license(payload: dict[str, object], private_key_text: str) -> dict[str, object]:
  private_key = Ed25519PrivateKey.from_private_bytes(_base64url_decode(private_key_text))
  signature = private_key.sign(canonical_license_payload(payload))
  return {
    "algorithm": "ed25519",
    "payload": payload,
    "signature": base64url_encode(signature),
  }


def main() -> int:
  parser = argparse.ArgumentParser(description="Create a signed offline license.")
  parser.add_argument("--private-key", required=True, help="Base64url private key or path to key JSON.")
  parser.add_argument("--licensee", required=True, help="Display name for the license owner.")
  expiry_group = parser.add_mutually_exclusive_group(required=True)
  expiry_group.add_argument("--expires-at", help="Expiry time, for example 2026-06-30T00:00:00Z.")
  expiry_group.add_argument("--permanent", action="store_true", help="Create a license without an expiry time.")
  parser.add_argument("--subject", help="Optional machine-readable subject.")
  parser.add_argument("--license-id", default="", help="Optional license id. Defaults to a random UUID.")
  parser.add_argument("--feature", action="append", default=[], help="Feature flag. Can be passed multiple times.")
  parser.add_argument(
    "--device-fingerprint",
    action="append",
    default=[],
    help="Device fingerprint hash. Can be passed multiple times.",
  )
  parser.add_argument("--output", help="Write signed license JSON to this path.")
  args = parser.parse_args()

  payload: dict[str, object] = {
    "license_id": args.license_id or str(uuid.uuid4()),
    "licensee": args.licensee,
    "issued_at": utc_now_text(),
  }
  if args.permanent:
    payload["permanent"] = True
  else:
    payload["expires_at"] = args.expires_at
  if args.subject:
    payload["subject"] = args.subject
  if args.feature:
    payload["features"] = args.feature
  if args.device_fingerprint:
    payload["device_fingerprints"] = args.device_fingerprint

  private_key_text = read_private_key(args.private_key)
  document = sign_license(payload, private_key_text)
  output = json.dumps(document, ensure_ascii=False, separators=(",", ":"))

  if args.output:
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output + "\n", encoding="utf-8")
  else:
    print(output)

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
