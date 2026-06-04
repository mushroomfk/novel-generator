#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="${1:-稿匣}"
APP_BUNDLE="$ROOT_DIR/src-tauri/target/debug/bundle/macos/${APP_NAME}.app"
APP_SIDECAR="$APP_BUNDLE/Contents/MacOS/novel-backend"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "没有找到应用包: $APP_BUNDLE" >&2
  exit 1
fi

if ! command -v codesign >/dev/null 2>&1; then
  echo "当前环境没有 codesign，无法修复 .app 签名" >&2
  exit 1
fi

mkdir -p "$APP_BUNDLE/Contents/Resources"
codesign --force --sign - --deep "$APP_BUNDLE" >/dev/null
if [[ -x "$APP_SIDECAR" ]]; then
  codesign --force --sign - "$APP_SIDECAR" >/dev/null
fi
codesign --verify --deep --strict "$APP_BUNDLE"

printf '已修复并校验 %s\n' "$APP_BUNDLE"
