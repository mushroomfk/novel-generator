import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');

if (process.platform !== 'darwin') {
  console.log('[fix-macos-native-binaries] skipped: non-macos');
  process.exit(0);
}

function run(command, args) {
  const result = spawnSync(command, args, { stdio: 'pipe', encoding: 'utf8' });
  return {
    status: result.status ?? 1,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function collectTargets(dir, matches, acc = []) {
  if (!fs.existsSync(dir)) return acc;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collectTargets(fullPath, matches, acc);
      continue;
    }
    if (matches(fullPath)) acc.push(fullPath);
  }
  return acc;
}

const nodeModules = path.join(repoRoot, 'node_modules');
const targets = collectTargets(
  nodeModules,
  (fullPath) => fullPath.endsWith('.node') || /node_modules\/@esbuild\/[^/]+\/bin\/esbuild$/.test(fullPath),
).sort();

if (targets.length === 0) {
  console.log('[fix-macos-native-binaries] skipped: no native targets found');
  process.exit(0);
}

for (const target of targets) {
  run('xattr', ['-d', 'com.apple.provenance', target]);
  run('xattr', ['-d', 'com.apple.quarantine', target]);
  const signResult = run('codesign', ['--force', '--sign', '-', target]);
  if (signResult.status !== 0) {
    console.error(`[fix-macos-native-binaries] failed: ${target}`);
    process.stderr.write(signResult.stderr);
    process.exit(signResult.status);
  }
  console.log(`[fix-macos-native-binaries] resigned ${path.relative(repoRoot, target)}`);
}
