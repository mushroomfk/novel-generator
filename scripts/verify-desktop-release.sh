#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="稿匣"
APP_BUNDLE="$ROOT_DIR/src-tauri/target/debug/bundle/macos/${APP_NAME}.app"
APP_SIDECAR="$APP_BUNDLE/Contents/MacOS/novel-backend"
BUILD_LOG_DIR="$(mktemp -d /tmp/novel-desktop-release.XXXXXX)"
APP_SIGN_REPAIR_SCRIPT="$ROOT_DIR/scripts/repair-tauri-app-signature.sh"

cleanup() {
  rm -rf "$BUILD_LOG_DIR"
}
trap cleanup EXIT

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"
}

require_file() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    echo "缺少文件: $path" >&2
    exit 1
  fi
}

free_port() {
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

smoke_backend_binary() {
  local binary="$1"
  local label="$2"
  local port
  local data_dir
  local log_file
  local pid

  port="$(free_port)"
  data_dir="$(mktemp -d /tmp/novel-backend-smoke.XXXXXX)"
  log_file="$BUILD_LOG_DIR/${label}.log"

  "$binary" --host 127.0.0.1 --port "$port" --data-dir "$data_dir" >"$log_file" 2>&1 &
  pid=$!

  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${port}/api/app/health" >"$BUILD_LOG_DIR/${label}-health.json" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done

  if ! curl -fsS "http://127.0.0.1:${port}/api/app/health" >"$BUILD_LOG_DIR/${label}-health.json" 2>/dev/null; then
    echo "${label} 启动后健康检查失败" >&2
    cat "$log_file" >&2 || true
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    exit 1
  fi

  curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:${port}/api/app/shutdown" >/dev/null
  wait "$pid" 2>/dev/null || status=$?
  status="${status:-0}"
  if [[ "$status" -ne 0 && "$status" -ne 143 ]]; then
    echo "${label} 退出码异常: ${status}" >&2
    cat "$log_file" >&2 || true
    rm -rf "$data_dir"
    exit 1
  fi
  rm -rf "$data_dir"
}

app_executable_path() {
  local executable_name="$APP_NAME"
  local plist="$APP_BUNDLE/Contents/Info.plist"

  if [[ -f "$plist" ]] && [[ -x /usr/libexec/PlistBuddy ]]; then
    executable_name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$plist" 2>/dev/null || printf '%s' "$APP_NAME")"
  fi

  printf '%s\n' "$APP_BUNDLE/Contents/MacOS/$executable_name"
}

app_pids_for_executable() {
  local executable="$1"
  ps -axo pid=,command= | awk -v target="$executable" 'index($0, target) > 0 { print $1 }'
}

kill_app_bundle_sidecars() {
  local sidecar="$APP_BUNDLE/Contents/MacOS/novel-backend"
  local sidecar_pids
  sidecar_pids="$(app_pids_for_executable "$sidecar" || true)"
  if [[ -n "$sidecar_pids" ]]; then
    printf '%s\n' "$sidecar_pids" | xargs kill 2>/dev/null || true
  fi
}

smoke_app_launch() {
  local app_executable
  local log_file
  local pid
  local status
  local before_pids
  local current_pids

  app_executable="$(app_executable_path)"
  log_file="$BUILD_LOG_DIR/app-launch.log"

  require_file "$app_executable"
  if [[ ! -x "$app_executable" ]]; then
    echo ".app 主程序没有执行权限: $app_executable" >&2
    exit 1
  fi

  before_pids="$(app_pids_for_executable "$app_executable" || true)"
  open -n "$APP_BUNDLE" >"$log_file" 2>&1

  for _ in $(seq 1 20); do
    current_pids="$(app_pids_for_executable "$app_executable" || true)"
    pid="$(
      comm -13 \
        <(printf '%s\n' "$before_pids" | sed '/^$/d' | sort -n) \
        <(printf '%s\n' "$current_pids" | sed '/^$/d' | sort -n) \
        | head -n 1
    )"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done

  if [[ -z "${pid:-}" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo ".app 启动后没有保持运行" >&2
    cat "$log_file" >&2 || true
    kill_app_bundle_sidecars
    exit 1
  fi

  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo ".app 启动后提前退出" >&2
      cat "$log_file" >&2 || true
      kill_app_bundle_sidecars
      exit 1
    fi
    sleep 0.5
  done

  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  kill_app_bundle_sidecars
}

log "运行 backend 回归"
(cd "$ROOT_DIR" && npm run backend:test)

log "运行前端构建"
(cd "$ROOT_DIR" && npm run build)

log "打包 Python sidecar"
(cd "$ROOT_DIR" && npm run backend:bundle)

SIDE_CAR_BIN="$(find "$ROOT_DIR/src-tauri/binaries" -maxdepth 1 -type f -name 'novel-backend-*' | head -n 1)"
if [[ -z "$SIDE_CAR_BIN" ]]; then
  echo "没有找到 sidecar 二进制" >&2
  exit 1
fi
require_file "$SIDE_CAR_BIN"
if [[ ! -x "$SIDE_CAR_BIN" ]]; then
  echo "sidecar 没有执行权限: $SIDE_CAR_BIN" >&2
  exit 1
fi

log "验证 sidecar 健康检查"
smoke_backend_binary "$SIDE_CAR_BIN" "sidecar"

log "构建 Tauri 调试包"
(cd "$ROOT_DIR" && npm run tauri -- build --debug)

require_file "$APP_BUNDLE"
require_file "$APP_SIDECAR"
if [[ ! -x "$APP_SIDECAR" ]]; then
  echo "应用内 sidecar 没有执行权限: $APP_SIDECAR" >&2
  exit 1
fi

DMG_PATH="$(find "$ROOT_DIR/src-tauri/target/debug/bundle/dmg" -maxdepth 1 -type f -name '*.dmg' | head -n 1)"
if [[ -z "$DMG_PATH" ]]; then
  echo "没有找到 dmg 产物" >&2
  exit 1
fi
require_file "$DMG_PATH"

if command -v codesign >/dev/null 2>&1; then
  log "修复并检查 .app 签名"
  bash "$APP_SIGN_REPAIR_SCRIPT" "$APP_NAME"
fi

log "验证应用内 sidecar 健康检查"
smoke_backend_binary "$APP_SIDECAR" "app-sidecar"

log "验证 .app 启动"
smoke_app_launch

log "桌面版回归完成"
printf 'app=%s\n' "$APP_BUNDLE"
printf 'dmg=%s\n' "$DMG_PATH"
printf 'sidecar=%s\n' "$SIDE_CAR_BIN"
