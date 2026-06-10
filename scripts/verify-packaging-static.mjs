import { readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function read(relativePath) {
  return readFileSync(path.join(repoRoot, relativePath), 'utf8');
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function includesAll(content, relativePath, snippets) {
  for (const snippet of snippets) {
    assert(
      content.includes(snippet),
      `${relativePath} is missing required packaging text: ${snippet}`,
    );
  }
}

function assertFile(relativePath, options = {}) {
  const absolutePath = path.join(repoRoot, relativePath);
  const stat = statSync(absolutePath);
  assert(stat.isFile(), `${relativePath} must be a file`);
  if (options.minBytes) {
    assert(
      stat.size >= options.minBytes,
      `${relativePath} is unexpectedly small: ${stat.size} bytes`,
    );
  }
}

const modelDir = 'backend/novel_backend/assets/embedding_models/fast-bge-small-zh-v1.5';
for (const filename of [
  'config.json',
  'model_optimized.onnx',
  'ort_config.json',
  'special_tokens_map.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'vocab.txt',
]) {
  assertFile(`${modelDir}/${filename}`, filename === 'model_optimized.onnx' ? { minBytes: 50 * 1024 * 1024 } : {});
}

const packageJson = JSON.parse(read('package.json'));
assert(
  packageJson.scripts['verify:packaging-static'] === 'node scripts/verify-packaging-static.mjs',
  'package.json must expose verify:packaging-static',
);
assert(
  packageJson.scripts.verify.includes('verify:packaging-static'),
  'npm run verify must include verify:packaging-static',
);
assert(
  packageJson.scripts.verify.includes('verify:frontend-static'),
  'npm run verify must include verify:frontend-static',
);
assert(
  packageJson.scripts.verify.includes('verify:api-smoke'),
  'npm run verify must include verify:api-smoke',
);
assert(
  packageJson.scripts['verify:frontend-static'] === 'node scripts/verify-frontend-static.mjs',
  'package.json must expose verify:frontend-static',
);
assert(
  packageJson.scripts['verify:api-smoke'] === '.venv/bin/python scripts/verify-api-release-smoke.py',
  'package.json must expose verify:api-smoke',
);
assert(
  packageJson.scripts['verify:local-smoke'] === '.venv/bin/python scripts/verify-local-release-smoke.py',
  'package.json must expose verify:local-smoke',
);
assert(
  packageJson.scripts['verify:model-preflight'] === '.venv/bin/python scripts/verify-model-preflight.py',
  'package.json must expose verify:model-preflight',
);
assert(
  packageJson.scripts['verify:release-audit'] === 'node scripts/verify-release-audit.mjs',
  'package.json must expose verify:release-audit',
);
assert(
  packageJson.scripts['verify:desktop:windows']?.includes('scripts/verify-windows-release.ps1'),
  'package.json must expose the Windows desktop verifier',
);
assert(
  packageJson.scripts['backend:bundle:windows']?.includes('scripts/build-backend-sidecar.ps1'),
  'package.json must expose the Windows sidecar bundler',
);

const macBundle = read('scripts/build-backend-sidecar.sh');
includesAll(macBundle, 'scripts/build-backend-sidecar.sh', [
  'backend/novel_backend/assets/embedding_models',
  'PYINSTALLER_CONFIG_DIR',
  '--add-data',
  'novel_backend/assets/embedding_models',
  '--collect-submodules fastembed',
  '--collect-binaries onnxruntime',
  '--collect-submodules onnxruntime',
  '--collect-binaries tokenizers',
]);

assertFile('scripts/verify-local-release-smoke.py', { minBytes: 4 * 1024 });
const localSmoke = read('scripts/verify-local-release-smoke.py');
includesAll(localSmoke, 'scripts/verify-local-release-smoke.py', [
  'run_model_config_test',
  'import_existing_novel',
  'build_project_context_bundle',
  'import_project_knowledge',
  'search_project_knowledge',
  'update_chapter_content',
  'summarize_chapter_review_status',
  'local smoke skips remote chapter review model',
]);

assertFile('scripts/verify-api-release-smoke.py', { minBytes: 4 * 1024 });
const apiSmoke = read('scripts/verify-api-release-smoke.py');
includesAll(apiSmoke, 'scripts/verify-api-release-smoke.py', [
  'TestClient',
  '/api/projects/takeover/import',
  '/api/config/test',
  '/knowledge/import',
  '/migration/export',
  'api smoke skips remote chapter review model',
]);

assertFile('scripts/verify-model-preflight.py', { minBytes: 4 * 1024 });
const modelPreflight = read('scripts/verify-model-preflight.py');
includesAll(modelPreflight, 'scripts/verify-model-preflight.py', [
  'api_key_present',
  'socket.getaddrinfo',
  'chat_completions_endpoint',
  'app_config.json',
]);

assertFile('scripts/verify-release-audit.mjs', { minBytes: 2 * 1024 });
const releaseAudit = read('scripts/verify-release-audit.mjs');
includesAll(releaseAudit, 'scripts/verify-release-audit.mjs', [
  'verify:local-smoke',
  'verify-weicheng-original-continuation.py',
  'verify:model-preflight',
  'blockedBy',
  '不要把当前状态判定为可上线',
]);

assertFile('scripts/verify-frontend-static.mjs', { minBytes: 2 * 1024 });
const frontendStatic = read('scripts/verify-frontend-static.mjs');
includesAll(frontendStatic, 'scripts/verify-frontend-static.mjs', [
  'ExistingNovelImportModal.vue',
  'NovelWorkflowPanel.vue',
  'agent-runtime-status-row',
  'isCompletedExecutionMessage',
  '已导入章节',
]);

const windowsBundle = read('scripts/build-backend-sidecar.ps1');
includesAll(windowsBundle, 'scripts/build-backend-sidecar.ps1', [
  'backend\\novel_backend\\assets\\embedding_models',
  'PYINSTALLER_CONFIG_DIR',
  '--add-data',
  'novel_backend\\assets\\embedding_models',
  '--collect-submodules", "fastembed"',
  '--collect-binaries", "onnxruntime"',
  '--collect-submodules", "onnxruntime"',
  '--collect-binaries", "tokenizers"',
  'novel-backend-$TargetTriple.exe',
]);

const macVerify = read('scripts/verify-desktop-release.sh');
includesAll(macVerify, 'scripts/verify-desktop-release.sh', [
  'npm run verify:packaging-static',
  'npm run backend:test',
  'npm run build',
  'npm run backend:bundle',
  'seq 1 240',
  'sleep 0.5',
  '/api/config/test',
  'BAAI/bge-small-zh-v1.5',
  '"512" not in message',
  'TAURI_BUILD_PROFILE="${TAURI_BUILD_PROFILE:-release}"',
  '--remap-path-prefix=${ROOT_DIR}=/workspace',
  'assert_no_build_paths "$(app_executable_path)" ".app 主程序"',
  'smoke_backend_binary "$SIDE_CAR_BIN" "sidecar"',
  'smoke_backend_binary "$APP_SIDECAR" "app-sidecar"',
  'npm run tauri -- build',
  'target/${TAURI_BUILD_PROFILE}/bundle/dmg',
]);

const tauriRuntime = read('src-tauri/src/lib.rs');
includesAll(tauriRuntime, 'src-tauri/src/lib.rs', [
  'request_backend_shutdown',
  'POST /api/app/shutdown HTTP/1.1',
  'cleanup_orphaned_sidecars',
  'pid=,ppid=,command=',
  'novel-backend',
]);

const windowsVerify = read('scripts/verify-windows-release.ps1');
includesAll(windowsVerify, 'scripts/verify-windows-release.ps1', [
  'npm run verify:packaging-static',
  'npm run backend:test:windows',
  'npm run build',
  'npm run backend:bundle:windows',
  'Invoke-BackendSmoke $SidecarPath "sidecar"',
  'for ($Attempt = 0; $Attempt -lt 240; $Attempt++)',
  'Start-Sleep -Milliseconds 500',
  '/api/config/test',
  'BAAI/bge-small-zh-v1.5',
  '-match "512"',
  'npm run tauri -- build --bundles nsis',
  'src-tauri\\binaries\\novel-backend-x86_64-pc-windows-msvc.exe',
  'src-tauri\\target\\release\\bundle\\nsis',
]);

const windowsWorkflow = read('.github/workflows/windows-release.yml');
includesAll(windowsWorkflow, '.github/workflows/windows-release.yml', [
  'runs-on: windows-latest',
  'python-version: "3.12"',
  'npm ci --ignore-scripts --no-audit --no-fund',
  '.\\.venv\\Scripts\\python.exe -m pip install -e backend pyinstaller',
  'npm run verify:desktop:windows',
  'src-tauri/target/release/bundle/nsis/*.exe',
  'src-tauri/binaries/novel-backend-x86_64-pc-windows-msvc.exe',
]);

console.log('[verify-packaging-static] packaging scripts include local embedding model, API/local smoke, model preflight, release audit, and desktop release checks');
