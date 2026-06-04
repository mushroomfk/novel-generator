#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
VENV_PYINSTALLER="$ROOT_DIR/.venv/bin/pyinstaller"

if [[ ! -x "$VENV_PYINSTALLER" ]]; then
  echo "缺少 .venv/bin/pyinstaller，先执行 .venv/bin/pip install pyinstaller" >&2
  exit 1
fi

detect_target_triple() {
  if [[ -x "${HOME}/.cargo/bin/cargo" ]]; then
    local cargo_host
    cargo_host="$("${HOME}/.cargo/bin/cargo" -Vv | awk '/^host:/ {print $2}')"
    if [[ -n "$cargo_host" ]]; then
      printf '%s\n' "$cargo_host"
      return 0
    fi
  fi

  local system
  local machine
  system="$(uname -s)"
  machine="$(uname -m)"

  if [[ "$system" == "Darwin" && "$machine" == "arm64" ]]; then
    printf '%s\n' "aarch64-apple-darwin"
    return 0
  fi
  if [[ "$system" == "Darwin" && "$machine" == "x86_64" ]]; then
    printf '%s\n' "x86_64-apple-darwin"
    return 0
  fi
  if [[ "$system" == "Linux" && "$machine" == "x86_64" ]]; then
    printf '%s\n' "x86_64-unknown-linux-gnu"
    return 0
  fi
  if [[ "$system" == "Linux" && "$machine" == "aarch64" ]]; then
    printf '%s\n' "aarch64-unknown-linux-gnu"
    return 0
  fi

  echo "无法自动识别目标三元组，请传入第一个参数，例如 aarch64-apple-darwin" >&2
  exit 1
}

TARGET_TRIPLE="${1:-$(detect_target_triple)}"
OUTPUT_PATH="$ROOT_DIR/src-tauri/binaries/novel-backend-${TARGET_TRIPLE}"
BUILD_ROOT="$(mktemp -d /tmp/novel-sidecar-build.XXXXXX)"
DIST_DIR="$BUILD_ROOT/dist"
WORK_DIR="$BUILD_ROOT/work"
SPEC_DIR="$BUILD_ROOT/spec"

cleanup() {
  rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT

PYINSTALLER_ARGS=(
  --noconfirm
  --clean
  --onefile
  --name novel-backend
  --distpath "$DIST_DIR"
  --workpath "$WORK_DIR"
  --specpath "$SPEC_DIR"
)

if [[ -x "$VENV_PYTHON" ]] && "$VENV_PYTHON" -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('liteparse') else 1)" >/dev/null 2>&1; then
  PYINSTALLER_ARGS+=(--collect-binaries liteparse --collect-datas liteparse)
fi

"$VENV_PYINSTALLER" "${PYINSTALLER_ARGS[@]}" "$ROOT_DIR/backend/novel_backend/main.py"

mkdir -p "$(dirname "$OUTPUT_PATH")"
mv "$DIST_DIR/novel-backend" "$OUTPUT_PATH"
chmod +x "$OUTPUT_PATH"

if command -v codesign >/dev/null 2>&1; then
  codesign --force --sign - "$OUTPUT_PATH" >/dev/null
fi

echo "已生成 $OUTPUT_PATH"
