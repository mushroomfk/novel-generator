from __future__ import annotations

import argparse
import os

import uvicorn

from novel_backend.app import app
from novel_backend.config import get_settings, reset_settings_cache


def _build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="Novel Generator backend service")
  parser.add_argument("--host", default=None)
  parser.add_argument("--port", type=int, default=None)
  parser.add_argument("--data-dir", default=None)
  return parser


def main() -> None:
  args = _build_parser().parse_args()
  if args.host:
    os.environ["NOVEL_HOST"] = args.host
  if args.port:
    os.environ["NOVEL_PORT"] = str(args.port)
  if args.data_dir:
    os.environ["NOVEL_DATA_DIR"] = args.data_dir

  reset_settings_cache()
  settings = get_settings()
  uvicorn.run(
    app,
    host=settings.host,
    port=settings.port,
    reload=False,
  )


if __name__ == "__main__":
  main()
