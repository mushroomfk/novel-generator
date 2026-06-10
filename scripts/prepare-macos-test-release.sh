#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(node -e "const fs=require('fs'); const pkg=JSON.parse(fs.readFileSync('package.json','utf8')); process.stdout.write(pkg.version)")"
APP_NAME="稿匣"
TAURI_BUILD_PROFILE="${TAURI_BUILD_PROFILE:-release}"

if [[ "$TAURI_BUILD_PROFILE" != "release" && "$TAURI_BUILD_PROFILE" != "debug" ]]; then
  echo "TAURI_BUILD_PROFILE 只支持 release 或 debug: $TAURI_BUILD_PROFILE" >&2
  exit 1
fi

DMG_PATH="$ROOT_DIR/src-tauri/target/${TAURI_BUILD_PROFILE}/bundle/dmg/${APP_NAME}_${VERSION}_aarch64.dmg"
OUTPUT_DIR="$ROOT_DIR/release/test-release/macos/${APP_NAME}_${VERSION}_测试包"
INSTALL_GUIDE_SRC="$ROOT_DIR/docs/macOS测试版安装说明.md"
FEEDBACK_GUIDE_SRC="$ROOT_DIR/docs/测试反馈清单.md"

if [[ ! -f "$DMG_PATH" ]]; then
  echo "缺少 dmg 产物：$DMG_PATH" >&2
  echo "先执行 npm run verify:desktop" >&2
  exit 1
fi

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

cp "$DMG_PATH" "$OUTPUT_DIR/"
cp "$INSTALL_GUIDE_SRC" "$OUTPUT_DIR/安装说明-先看这个.md"
cp "$FEEDBACK_GUIDE_SRC" "$OUTPUT_DIR/测试反馈清单.md"

(
  cd "$OUTPUT_DIR"
  shasum -a 256 "$(basename "$DMG_PATH")" > SHA256SUMS.txt
)

cat >"$OUTPUT_DIR/包信息.txt" <<EOF
应用名称：$APP_NAME
版本：$VERSION
架构：macOS arm64
构建类型：$TAURI_BUILD_PROFILE
公证状态：未 notarize
发包方式：测试版临时分发
安装方式：请先阅读 安装说明-先看这个.md
生成时间：$(date '+%Y-%m-%d %H:%M:%S %z')
EOF

printf '已整理测试包到 %s\n' "$OUTPUT_DIR"
