#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"

import sys

sys.path.insert(0, str(BACKEND_DIR))

from novel_backend.services.license_service import base64url_encode


def generate_keypair() -> dict[str, str]:
  private_key = Ed25519PrivateKey.generate()
  public_key = private_key.public_key()
  private_raw = private_key.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
  )
  public_raw = public_key.public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
  )
  return {
    "algorithm": "ed25519",
    "private_key": base64url_encode(private_raw),
    "public_key": base64url_encode(public_raw),
  }


def main() -> int:
  parser = argparse.ArgumentParser(description="Generate an Ed25519 license keypair.")
  parser.add_argument("--json", action="store_true", help="Print compact JSON.")
  parser.add_argument("--private-key-file", help="Write the private key JSON to this path.")
  parser.add_argument("--public-key-file", help="Write the public key text to this path.")
  parser.add_argument("--force", action="store_true", help="Overwrite output files if they exist.")
  args = parser.parse_args()

  keypair = generate_keypair()

  for raw_path in (args.private_key_file, args.public_key_file):
    if not raw_path:
      continue
    path = Path(raw_path).expanduser()
    if path.exists() and not args.force:
      parser.error(f"refusing to overwrite existing file: {path}")

  if args.private_key_file:
    private_path = Path(args.private_key_file).expanduser()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps(keypair, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    private_path.chmod(0o600)

  if args.public_key_file:
    public_path = Path(args.public_key_file).expanduser()
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(keypair["public_key"] + "\n", encoding="utf-8")

  if args.json:
    print(json.dumps(keypair, ensure_ascii=False, separators=(",", ":")))
  else:
    print("algorithm=ed25519")
    print(f"public_key={keypair['public_key']}")
    print(f"private_key={keypair['private_key']}")

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
