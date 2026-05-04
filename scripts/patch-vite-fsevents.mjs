import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');

const patches = [
  {
    file: path.join(repoRoot, 'node_modules', 'vite', 'dist', 'node', 'index.js'),
    replacements: [
      {
        name: 'vite-index-rollup-parseAst',
        target: "export { parseAst, parseAstAsync } from 'rollup/parseAst';",
        replacement: "export { parseAst, parseAstAsync } from '@rollup/wasm-node/parseAst';",
      },
    ],
  },
  {
    file: path.join(repoRoot, 'node_modules', 'vite', 'dist', 'node', 'chunks', 'dep-Dq2t6Dq0.js'),
    replacements: [
      {
        name: 'fsevents',
        target: "  fsevents = __require('fsevents');",
        replacement: "  fsevents = process.env.ENABLE_VITE_FSEVENTS === '1' ? __require('fsevents') : undefined;",
      },
      {
        name: 'vite-chunk-rollup-parseAst',
        target: "import { parseAstAsync, parseAst } from 'rollup/parseAst';",
        replacement: "import { parseAstAsync, parseAst } from '@rollup/wasm-node/parseAst';",
      },
    ],
  },
];

for (const patch of patches) {
  if (!fs.existsSync(patch.file)) {
    console.log(`[patch-vite-fsevents] skipped: file not found ${path.relative(repoRoot, patch.file)}`);
    continue;
  }

  let source = fs.readFileSync(patch.file, 'utf8');
  let changed = false;

  for (const { name, target, replacement } of patch.replacements) {
    if (source.includes(replacement)) {
      console.log(`[patch-vite-fsevents] already applied: ${name}`);
      continue;
    }

    if (!source.includes(target)) {
      console.error(`[patch-vite-fsevents] failed: target snippet not found for ${name}`);
      process.exit(1);
    }

    source = source.replace(target, replacement);
    changed = true;
    console.log(`[patch-vite-fsevents] applied: ${name}`);
  }

  if (changed) {
    fs.writeFileSync(patch.file, source, 'utf8');
  }
}
