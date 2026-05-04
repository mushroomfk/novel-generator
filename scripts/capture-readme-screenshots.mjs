import { spawn } from 'node:child_process';
import { access, mkdtemp, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright-core';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '..');
const OUT_DIR = path.join(ROOT_DIR, 'docs', 'assets');
const CHROME_CANDIDATES = [
  process.env.CHROME_BIN,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
].filter(Boolean);

function log(message) {
  console.log(`[readme-capture] ${message}`);
}

function spawnProcess(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: ROOT_DIR,
    env: { ...process.env, ...(options.env ?? {}) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const chunks = [];
  child.stdout.on('data', (buffer) => chunks.push(buffer.toString()));
  child.stderr.on('data', (buffer) => chunks.push(`[stderr] ${buffer.toString()}`));
  return {
    child,
    logs: () => chunks.slice(-80).join(''),
    async stop() {
      if (child.exitCode !== null) {
        return;
      }
      child.kill('SIGTERM');
      await new Promise((resolve) => child.once('exit', resolve));
    },
  };
}

async function runCommand(command, args, options = {}) {
  log(options.label ?? `${command} ${args.join(' ')}`);
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: ROOT_DIR,
      env: { ...process.env, ...(options.env ?? {}) },
      stdio: 'inherit',
    });
    child.once('exit', (code) => (code === 0 ? resolve() : reject(new Error(`${command} failed with ${code}`))));
  });
}

async function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForHttpOk(url, timeoutMs = 20000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // wait until timeout
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`等待服务超时：${url}`);
}

function unwrap(payload) {
  if (!payload?.ok || payload.data === undefined) {
    throw new Error(payload?.error?.message ?? '接口返回失败');
  }
  return payload.data;
}

async function apiRequest(backendUrl, route, init = {}) {
  const response = await fetch(`${backendUrl}${route}`, {
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    ...init,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.error?.message ?? `请求失败：${response.status}`);
  }
  return unwrap(payload);
}

async function resolveChromePath() {
  for (const candidate of CHROME_CANDIDATES) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // keep searching
    }
  }
  throw new Error('没有找到 Chrome，可通过 CHROME_BIN 指定');
}

function jsonResponse(response, payload, status = 200) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(payload));
}

function embeddingVectorFromText(text, dimensions = 64) {
  const vector = Array.from({ length: dimensions }, () => 0);
  const normalized = String(text ?? '');
  for (let index = 0; index < normalized.length; index += 1) {
    vector[index % dimensions] += normalized.charCodeAt(index) / 255;
  }
  return vector.map((value, index) => Number((value + (index + 1) * 0.01).toFixed(6)));
}

function mockPlan(userText) {
  const normalized = String(userText ?? '');
  if (/架构|蓝图|大纲/u.test(normalized)) {
    return {
      mode: 'plan',
      title: '整理整书架构',
      summary: '先分析项目资料，再补齐整书架构。',
      requires_confirmation: true,
      actions: [{ kind: 'generate_architecture', label: '生成整书架构', instruction: normalized }],
    };
  }
  if (/续写|写这一章|生成/u.test(normalized)) {
    return {
      mode: 'plan',
      title: '生成第 1 章正文',
      summary: '先看当前章节状态，再生成正文。',
      requires_confirmation: true,
      actions: [{
        kind: 'chapter_generate',
        label: '生成第 1 章正文',
        chapter_target: 'selected',
        instruction: normalized,
        target_words: 1800,
      }],
    };
  }
  return {
    mode: 'plan',
    title: '继续讨论项目方向',
    summary: '先看当前项目上下文，再给这一轮建议。',
    requires_confirmation: false,
    actions: [{ kind: 'brainstorm', label: '继续讨论项目方向', instruction: normalized }],
  };
}

function mockChat(messages) {
  const systemText = messages
    .filter((item) => item.role === 'system')
    .map((item) => String(item.content ?? ''))
    .join('\n');
  const userText = String([...messages].reverse().find((item) => item.role === 'user')?.content ?? '');

  if (systemText.includes('任务路由器')) {
    return JSON.stringify({
      intent: /架构|蓝图|大纲/u.test(userText)
        ? 'generate_architecture'
        : /续写|生成/u.test(userText)
          ? 'write_chapter'
          : 'discussion',
      objective: userText,
      chapter_index: 1,
      chapter_title: '雨夜靠港',
      rewrite_mode: '',
      new_chapters: 0,
      use_next_chapter: false,
      reason: '演示路由',
    });
  }
  if (systemText.includes('任务规划器')) {
    return JSON.stringify(mockPlan(userText), null, 2);
  }
  if (systemText.includes('陪跑编辑')) {
    return JSON.stringify({
      reply: '下一步先把钥匙为什么重新出现、港务会为什么现在追人这两个问题立住。',
      suggestions: ['钥匙和家族旧账怎么连起来', '追兵当前要逼近到什么程度'],
    }, null, 2);
  }
  if (systemText.includes('中文小说续写总编')) {
    return JSON.stringify({
      summary: '承接当前章节：主角在灯塔下暴露行踪，追兵已经逼近。',
      must_keep: ['铜钥匙', '旧船队', '港务会追兵'],
      current_state: ['主角刚离开灯塔', '潮声遮住追兵脚步'],
      voice_rules: ['动作推进', '保留悬念'],
      blocked_changes: ['不提前揭露旧船队真相'],
      next_action: '让追兵压近，同时露出钥匙危险性。',
    }, null, 2);
  }
  if (systemText.includes('中文小说场景规划编辑')) {
    return JSON.stringify({
      headline: '追兵压近的场景计划',
      summary: '顺着灯塔现场继续推进。',
      checklist: ['保留灯塔现场', '让追兵压近'],
      scenes: [
        {
          title: '离开灯塔',
          goal: '带着钥匙撤离',
          conflict: '追兵从木栈道逼近',
          turn: '主角发现对方知道钥匙在他手上',
        },
        {
          title: '旧船坞暗号',
          goal: '让钥匙和旧船队产生联系',
          conflict: '追兵堵住出口',
          turn: '墙上暗号指向下一章线索',
        },
      ],
      next_action: '继续查旧船队账册。',
    }, null, 2);
  }
  if (systemText.includes('中文小说章节写手')) {
    return JSON.stringify({
      headline: '正文已生成',
      summary: '这一版先把追兵压近，再把钥匙来历露出半格。',
      content: '# 第一章 雨夜靠港\n他把钥匙按进掌心，刚离开灯塔就听见潮声后面有人跟来。港务会的人没有点灯，只靠靴底刮过木栈道的声音逼近。',
      next_action: '继续把旧船队账册和追兵关系带出来。',
    }, null, 2);
  }
  if (systemText.includes('分步骤生成整本架构')) {
    return JSON.stringify({
      headline: '架构步骤已整理',
      summary: '这一版把旧船队、家族旧账和港务会追查接上。',
      content: '港口悬疑长篇：前段立钥匙和追兵，中段拆家族与旧船队关系，后段逼近真相并改写港口秩序。',
      checklist: ['检查章节冲突', '确认后续可展开'],
    }, null, 2);
  }
  if (systemText.includes('中文小说续写写手')) {
    return '他把钥匙按进掌心，刚离开灯塔就听见潮声后面有人跟来。';
  }
  return JSON.stringify({ reply: '演示模型已返回结果。', suggestions: ['继续推进'] }, null, 2);
}

async function startMockModelServer(port) {
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) {
      chunks.push(chunk);
    }
    let payload = {};
    try {
      payload = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
    } catch {
      payload = {};
    }

    if (request.url?.endsWith('/chat/completions')) {
      jsonResponse(response, {
        id: 'demo',
        object: 'chat.completion',
        created: Math.floor(Date.now() / 1000),
        model: String(payload.model ?? 'demo-model'),
        choices: [{
          index: 0,
          message: { role: 'assistant', content: mockChat(Array.isArray(payload.messages) ? payload.messages : []) },
          finish_reason: 'stop',
        }],
      });
      return;
    }

    if (request.url?.endsWith('/embeddings')) {
      const inputs = Array.isArray(payload.input) ? payload.input : [payload.input].filter(Boolean);
      jsonResponse(response, {
        object: 'list',
        data: inputs.map((item, index) => ({
          object: 'embedding',
          index,
          embedding: embeddingVectorFromText(item, Number(payload.dimensions ?? 64) || 64),
        })),
        model: String(payload.model ?? 'text-embedding-3-small'),
      });
      return;
    }

    jsonResponse(response, { error: 'not found' }, 404);
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  return {
    url: `http://127.0.0.1:${port}/v1`,
    stop: () => new Promise((resolve) => server.close(resolve)),
  };
}

async function seedModelConfig(backendUrl, modelBaseUrl) {
  await apiRequest(backendUrl, '/api/config', {
    method: 'PUT',
    body: JSON.stringify({
      model: {
        provider: 'openai-compatible',
        base_url: modelBaseUrl,
        api_key: 'demo-key',
        model_name: 'demo-model',
        max_tokens: 4096,
        temperature: 0.7,
      },
      embedding: {
        provider: 'openai-compatible',
        base_url: modelBaseUrl,
        api_key: 'demo-key',
        model_name: 'text-embedding-3-small',
        dimensions: 64,
        retrieval_k: 6,
        batch_size: 8,
      },
    }),
  });
}

async function createDemoProject(backendUrl) {
  const project = await apiRequest(backendUrl, '/api/projects', {
    method: 'POST',
    body: JSON.stringify({
      name: '港口旧账',
      genre: '港口悬疑',
      target_chapters: 20,
      target_words: 200000,
    }),
  });

  await apiRequest(backendUrl, `/api/projects/${project.id}/architecture/workspace`, {
    method: 'PUT',
    body: JSON.stringify({
      genre: '港口悬疑',
      target_chapters: 20,
      target_words: 200000,
      workspace: {
        core_seed: '旧船队遗失的铜钥匙重新出现，主角被迫追查家族旧账。',
        character_design: '主角擅长开锁，码头旧友提供线索，港务会不断追人。',
        world_building: '港口城市依赖潮位和灯塔信号开启隐秘航线。',
        plot_structure: '前段找钥匙和旧案，中段拆家族和船队关系，后段逼近真相。',
        character_state: '主角刚回港，旧友立场摇摆，港务会已经盯上钥匙。',
        blueprint: '## 第 1 章《雨夜靠港》\n主角捡到钥匙并暴露行踪。\n\n## 第 2 章《旧船队名单》\n主角追到第一条旧线索。',
        global_summary: '港口悬疑长篇，前两章立住钥匙、旧船队和家族旧账。',
      },
    }),
  });
  await apiRequest(backendUrl, `/api/projects/${project.id}/chapters/chapter-001`, {
    method: 'PUT',
    body: JSON.stringify({
      content: '# 第一章 雨夜靠港\n雨水压着码头的灯。林追把铜钥匙藏进袖口，刚越过灯塔台阶，就听见木栈道另一头有人放慢脚步。港务会的人没有点灯，只用潮声遮住逼近的距离。',
    }),
  });
  await apiRequest(backendUrl, `/api/projects/${project.id}/knowledge/import`, {
    method: 'POST',
    body: JSON.stringify({
      items: [
        {
          title: '旧船队调查记录',
          content: '旧船队在大潮夜失踪，港务会随后删改登记册。铜钥匙和旧船队最后一次靠港记录有关。',
        },
        {
          title: '港务会线索卡',
          content: '港务会掌握码头登记和灯塔巡夜记录，追查铜钥匙的人都和旧船队名单有关。',
        },
      ],
    }),
  });
  await apiRequest(backendUrl, `/api/projects/${project.id}/memory`, {
    method: 'PUT',
    body: JSON.stringify({
      entries: [{
        id: 'demo-goal',
        title: '写作目标',
        category: '目标',
        content: '保持港口悬疑感，先用追兵和钥匙推动节奏，不提前揭开旧船队真相。',
      }],
    }),
  });
  return project;
}

async function main() {
  const backendPort = await getFreePort();
  const previewPort = await getFreePort();
  const modelPort = await getFreePort();
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const previewUrl = `http://127.0.0.1:${previewPort}`;
  const dataDir = await mkdtemp(path.join(os.tmpdir(), 'novel-readme-demo-'));
  const processes = [];
  let modelServer = null;
  let browser = null;

  try {
    await runCommand('npm', ['run', 'build'], {
      label: '构建演示前端',
      env: { VITE_NOVEL_BACKEND_URL: backendUrl },
    });

    const corsOrigins = JSON.stringify([
      'http://localhost:1420',
      'http://127.0.0.1:1420',
      'http://tauri.localhost',
      'https://tauri.localhost',
      'tauri://localhost',
      previewUrl,
    ]);
    const backend = spawnProcess(
      path.join(ROOT_DIR, '.venv', 'bin', 'python'),
      ['-m', 'novel_backend.main', '--host', '127.0.0.1', '--port', String(backendPort), '--data-dir', dataDir],
      { env: { NOVEL_CORS_ORIGINS: corsOrigins, BOCHA_API_KEY: '', BOCHA_SEARCH_ENDPOINT: '' } },
    );
    processes.push(backend);
    await waitForHttpOk(`${backendUrl}/api/app/health`);

    modelServer = await startMockModelServer(modelPort);
    await seedModelConfig(backendUrl, modelServer.url);
    await createDemoProject(backendUrl);

    const preview = spawnProcess(
      process.execPath,
      ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', String(previewPort), '--strictPort'],
    );
    processes.push(preview);
    await waitForHttpOk(previewUrl);

    browser = await chromium.launch({
      executablePath: await resolveChromePath(),
      headless: true,
      args: ['--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check'],
    });
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
    await page.goto(previewUrl, { waitUntil: 'load' });
    await page.getByTestId('app-shell').waitFor();
    await page.getByTestId('stage-project-title').getByText('港口旧账', { exact: true }).waitFor();
    const firstChapterRow = page.getByTestId('chapter-row-chapter-001');
    if (!await firstChapterRow.isVisible().catch(() => false)) {
      await page.locator('[data-testid^="project-chapter-toggle-"]').first().click();
    }
    await firstChapterRow.click();
    await page.getByTestId('chapter-preview-panel').waitFor();
    await page.screenshot({ path: path.join(OUT_DIR, 'readme-workspace.png'), fullPage: false });

    await page.getByTestId('workspace-composer-input').fill('续写这一章，把追兵压近一点。');
    await page.locator('.composer-submit-button').click();
    await page.getByText('已经生成并写回项目').first().waitFor({ timeout: 25000 });
    await page.getByTestId('agent-timeline').first().waitFor();
    await page.screenshot({ path: path.join(OUT_DIR, 'readme-agent-flow.png'), fullPage: false });

    await page.getByTestId('open-skills-button').click();
    await page.getByTestId('skills-stage').waitFor();
    await page.getByTestId('skill-use-knowledge-search').click();
    await page.getByTestId('knowledge-search-input').fill('旧船队');
    await page.getByTestId('knowledge-search-button').click();
    await page.getByTestId('knowledge-search-results').getByText('旧船队').first().waitFor();
    await page.screenshot({ path: path.join(OUT_DIR, 'readme-skills-knowledge.png'), fullPage: false });
    await page.close();

    log('截图已写入 docs/assets/');
  } finally {
    if (browser) {
      await browser.close();
    }
    if (modelServer) {
      await modelServer.stop();
    }
    for (const item of processes.reverse()) {
      await item.stop();
    }
    await rm(dataDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
