import { spawn, spawnSync } from 'node:child_process';
import { access, mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright-core';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '..');
const CHROME_CANDIDATES = [
  process.env.CHROME_BIN,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
].filter(Boolean);

function log(message) {
  console.log(`\n[ui-smoke] ${message}`);
}

function createLogCollector(label, child) {
  const chunks = [];
  const pushChunk = (prefix) => (buffer) => {
    const text = buffer.toString();
    chunks.push(`${prefix}${text}`);
    if (chunks.length > 200) {
      chunks.shift();
    }
  };

  child.stdout?.on('data', pushChunk(''));
  child.stderr?.on('data', pushChunk('[stderr] '));

  return () => `----- ${label} -----\n${chunks.join('')}`;
}

function spawnProcess(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: ROOT_DIR,
    env: {
      ...process.env,
      ...(options.env ?? {}),
    },
    stdio: options.stdio ?? ['ignore', 'pipe', 'pipe'],
  });

  const readLogs = createLogCollector(options.label ?? command, child);

  return {
    child,
    readLogs,
    async stop(signal = 'SIGTERM') {
      if (child.exitCode !== null) {
        return child.exitCode;
      }

      child.kill(signal);
      return new Promise((resolve) => {
        child.once('exit', (code, exitSignal) => {
          if (code !== null) {
            resolve(code);
            return;
          }
          resolve(exitSignal === 'SIGTERM' ? 0 : 1);
        });
      });
    },
  };
}

async function runCommand(command, args, options = {}) {
  log(options.label ?? `${command} ${args.join(' ')}`);
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: ROOT_DIR,
      env: {
        ...process.env,
        ...(options.env ?? {}),
      },
      stdio: 'inherit',
    });

    child.once('exit', (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${options.label ?? command} 失败，退出码 ${code}`));
    });
  });
}

async function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') {
        reject(new Error('无法分配空闲端口'));
        return;
      }
      const { port } = address;
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(port);
      });
    });
  });
}

async function waitForHttpOk(url, options = {}) {
  const timeoutMs = options.timeoutMs ?? 15000;
  const intervalMs = options.intervalMs ?? 250;
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // ignore until timeout
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error(`等待服务超时：${url}`);
}

async function waitForProjectChapterContent(backendUrl, projectId, chapterId, expectedText, options = {}) {
  const timeoutMs = options.timeoutMs ?? 15000;
  const intervalMs = options.intervalMs ?? 300;
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const detail = await apiRequest(backendUrl, `/api/projects/${projectId}`);
      const matchedChapter = detail?.chapters?.find((item) => item.id === chapterId);
      if (matchedChapter?.content?.includes(expectedText)) {
        return;
      }
    } catch {
      // ignore until timeout
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error(`等待章节内容超时：${projectId}/${chapterId}`);
}

async function waitForProjectChapterNonEmpty(backendUrl, projectId, chapterId, options = {}) {
  const timeoutMs = options.timeoutMs ?? 15000;
  const intervalMs = options.intervalMs ?? 300;
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const detail = await apiRequest(backendUrl, `/api/projects/${projectId}`);
      const matchedChapter = detail?.chapters?.find((item) => item.id === chapterId);
      if (String(matchedChapter?.content ?? '').trim()) {
        return;
      }
    } catch {
      // ignore until timeout
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error(`等待章节写回超时：${projectId}/${chapterId}`);
}

async function waitForProjectDocumentContent(backendUrl, projectId, documentKey, expectedText, options = {}) {
  const timeoutMs = options.timeoutMs ?? 15000;
  const intervalMs = options.intervalMs ?? 300;
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const detail = await apiRequest(backendUrl, `/api/projects/${projectId}`);
      const matchedDocument = detail?.story_overview?.documents?.find((item) => item.key === documentKey);
      if (matchedDocument?.content?.includes(expectedText)) {
        return;
      }
    } catch {
      // ignore until timeout
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error(`等待文档内容超时：${projectId}/${documentKey}`);
}

async function saveProjectChapterContent(backendUrl, projectId, chapterId, content) {
  await apiRequest(backendUrl, `/api/projects/${projectId}/chapters/${chapterId}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

async function waitForChapterPreviewContent(page, expectedText) {
  await page.waitForFunction(
    (text) => {
      const panel = document.querySelector('[data-testid="chapter-preview-panel"]');
      return panel instanceof HTMLElement && panel.textContent?.includes(text);
    },
    expectedText,
  );
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

  throw new Error('没有找到可用的 Chrome，可通过 CHROME_BIN 指定浏览器路径');
}

function unwrapApiEnvelope(payload) {
  if (!payload?.ok || payload.data === undefined) {
    throw new Error(payload?.error?.message ?? '接口返回失败');
  }

  return payload.data;
}

async function apiRequest(backendUrl, path, init = {}) {
  const response = await fetch(`${backendUrl}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
    ...init,
  });
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload?.error?.message ?? `请求失败: ${response.status}`);
  }

  return unwrapApiEnvelope(payload);
}

async function seedModelConfig(backendUrl, modelBaseUrl) {
  await apiRequest(backendUrl, '/api/config', {
    method: 'PUT',
    body: JSON.stringify({
      model: {
        provider: 'openai-compatible',
        base_url: modelBaseUrl,
        api_key: 'ui-smoke-key',
        model_name: 'ui-smoke-model',
        max_tokens: 4096,
        temperature: 0.7,
      },
      embedding: {
        provider: 'openai-compatible',
        base_url: modelBaseUrl,
        api_key: 'ui-smoke-key',
        model_name: 'text-embedding-3-small',
        dimensions: 64,
        retrieval_k: 6,
        batch_size: 8,
      },
    }),
  });
}

async function seedTestLicense(backendUrl, licenseContent) {
  await apiRequest(backendUrl, '/api/license/import', {
    method: 'POST',
    body: JSON.stringify({
      content: licenseContent,
    }),
  });
}

function runJsonTool(args) {
  const result = spawnSync(path.join(ROOT_DIR, '.venv', 'bin', 'python'), args, {
    cwd: ROOT_DIR,
    encoding: 'utf-8',
  });
  if (result.status !== 0) {
    throw new Error(`${args.join(' ')} 失败：${result.stderr || result.stdout}`);
  }
  return JSON.parse(result.stdout);
}

function runTextTool(args) {
  const result = spawnSync(path.join(ROOT_DIR, '.venv', 'bin', 'python'), args, {
    cwd: ROOT_DIR,
    encoding: 'utf-8',
  });
  if (result.status !== 0) {
    throw new Error(`${args.join(' ')} 失败：${result.stderr || result.stdout}`);
  }
  return result.stdout.trim();
}

async function readTail(filePath, maxLines = 80) {
  try {
    const text = await readFile(filePath, 'utf-8');
    return text.split(/\r?\n/u).slice(-maxLines).join('\n').trim();
  } catch {
    return '';
  }
}

function createSmokeLicense() {
  const keypair = runJsonTool(['scripts/generate-license-keypair.py', '--json']);
  const content = runTextTool([
    'scripts/create-license.py',
    `--private-key=${keypair.private_key}`,
    '--licensee',
    'UI smoke',
    '--expires-at',
    '2099-01-01T00:00:00+00:00',
  ]);
  return {
    publicKey: keypair.public_key,
    content,
  };
}

function jsonResponse(response, payload, status = 200) {
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

function embeddingVectorFromText(text, dimensions = 64) {
  const vector = Array.from({ length: dimensions }, (_, index) => 0);
  const normalized = String(text ?? '');
  for (let index = 0; index < normalized.length; index += 1) {
    vector[index % dimensions] += normalized.charCodeAt(index) / 255;
  }
  return vector.map((value, index) => Number((value + (index + 1) * 0.01).toFixed(6)));
}

function architectureStepLabelFromPrompt(text) {
  const matched = String(text ?? '').match(/这一步只处理：([^\n。]+)/u);
  return matched?.[1]?.trim() ?? '';
}

function architectureStepContent(label) {
  const entries = {
    核心种子: '旧船队失踪留下的钥匙重回港口，主角被迫在家族旧账和港务会追查之间选边。',
    人物设定: '主角擅长开锁，码头旧友提供线索，港务会追兵持续施压，旧船队后人掌握关键账册。',
    世界设定: '港口依赖潮位和灯塔暗号维持灰色航线，旧船队消失后的秩序一直被港务会和商会共同掩盖。',
    情节骨架: '前段立住钥匙与追兵，中段拆家族和旧船队关系，后段逼近真相并改写港口秩序。',
    人物状态: '主角刚被迫回港，旧友立场摇摆，港务会已经盯上钥匙，旧船队后人暂时不敢露面。',
    章节蓝图: '## 第 1 章《雨夜靠港》\n钥匙回到主角手里，追兵第一次逼近。\n\n## 第 2 章《灯塔旧账》\n主角查到旧船队账册被人改写。\n\n## 第 3 章《夜潮账册》\n旧友交出一页被撕掉的港务登记。',
    滚动摘要: '故事已经明确为港口悬疑长篇，当前先立住钥匙、旧船队和家族旧账三条主线，同时用港务会追兵持续压迫主角行动。',
  };
  return entries[label] ?? '这一步的架构内容已经整理好。';
}

function mockRouteResult(userText) {
  const normalized = String(userText ?? '');
  if (/续写|写这一章|补完本章/u.test(normalized)) {
    return {
      intent: 'write_chapter',
      objective: '续写当前章节',
      chapter_index: 1,
      chapter_title: '第一章 雨夜靠港',
      rewrite_mode: '',
      new_chapters: 0,
      use_next_chapter: false,
      reason: '用户明确要续写',
    };
  }
  if (/架构|蓝图|大纲|世界观/u.test(normalized)) {
    return {
      intent: 'generate_architecture',
      objective: '补齐整书架构',
      chapter_index: 0,
      chapter_title: '',
      rewrite_mode: '',
      new_chapters: 0,
      use_next_chapter: false,
      reason: '用户明确要补架构',
    };
  }
  return {
    intent: 'discussion',
    objective: '讨论下一步推进方向',
    chapter_index: 0,
    chapter_title: '',
    rewrite_mode: '',
    new_chapters: 0,
    use_next_chapter: false,
    reason: '用户在讨论方向',
  };
}

function mockPlanResult(userText) {
  const normalized = String(userText ?? '');

  if (/聊聊|讨论|推进什么/u.test(normalized)) {
    return {
      mode: 'plan',
      title: '继续讨论项目方向',
      summary: '先看当前项目上下文，再给这一轮建议。',
      requires_confirmation: false,
      actions: [
        {
          kind: 'brainstorm',
          label: '继续讨论项目方向',
          instruction: normalized,
        },
      ],
    };
  }

  if (/资料库|资料分析|分析资料/u.test(normalized) && /架构|蓝图|大纲|世界观/u.test(normalized)) {
    return {
      mode: 'plan',
      title: '整理整书架构',
      summary: '先分析资料库，再重新整理整书架构。',
      requires_confirmation: true,
      actions: [
        {
          kind: 'review_knowledge',
          label: '分析资料库',
          instruction: normalized,
        },
        {
          kind: 'generate_architecture',
          label: '生成整书架构',
          instruction: normalized,
        },
      ],
    };
  }

  if (/架构|蓝图|大纲|世界观/u.test(normalized)) {
    return {
      mode: 'plan',
      title: '整理整书架构',
      summary: '按当前讨论结论重新整理整书架构。',
      requires_confirmation: true,
      actions: [
        {
          kind: 'generate_architecture',
          label: '生成整书架构',
          instruction: normalized,
        },
      ],
    };
  }

  if (/续写|写这一章|补完本章|生成.*第\s*[0-9零一二三四五六七八九十百两]+\s*章|生成[一二三四五六七八九十百两0-9]+章/u.test(normalized)) {
    return {
      mode: 'plan',
      title: '生成第 1 章正文',
      summary: '先看当前章节状态，再生成正文。',
      requires_confirmation: true,
      actions: [
        {
          kind: 'chapter_generate',
          label: '生成第 1 章正文',
          chapter_target: 'selected',
          instruction: normalized,
          target_words: 1800,
        },
      ],
    };
  }

  return {
    mode: 'reply',
    reply: '当前请求还不够明确，请再写一句你想让我具体做什么。',
  };
}

function isSecondChapterRevisionPrompt(userText) {
  const normalized = String(userText ?? '');
  return /(?:当前章节|目标章节|待处理章节)[：:]\s*第\s*(?:2|二)\s*章/u.test(normalized)
    || /原正文[：:][\s\S]{0,120}#\s*(?:第二章|第\s*2\s*章)/u.test(normalized)
    || /章节正文[：:][\s\S]{0,120}#\s*(?:第二章|第\s*2\s*章)/u.test(normalized);
}

function mockChatCompletionContent(messages) {
  const systemText = messages
    .filter((item) => item?.role === 'system')
    .map((item) => String(item?.content ?? ''))
    .join('\n\n');
  const lastUserMessage = [...messages].reverse().find((item) => item?.role === 'user');
  const userText = String(lastUserMessage?.content ?? '');

  if (systemText.includes('任务路由器')) {
    return JSON.stringify(mockRouteResult(userText), null, 2);
  }

  if (systemText.includes('任务规划器')) {
    return JSON.stringify(mockPlanResult(userText), null, 2);
  }

  if (systemText.includes('陪跑编辑')) {
    return JSON.stringify({
      reply: '下一步先别急着扩支线，先把钥匙为什么重新出现、港务会为什么现在追人这两个问题立住。',
      suggestions: ['钥匙和主角家族旧账怎么连起来', '追兵当前要逼近到什么程度'],
    }, null, 2);
  }

  if (systemText.includes('分步骤生成整本架构')) {
    const stepLabel = architectureStepLabelFromPrompt(userText);
    return JSON.stringify({
      headline: `${stepLabel || '架构步骤'}已整理`,
      summary: `这一版先把${stepLabel || '当前步骤'}和现有项目文档接上，方便后面继续写。`,
      content: architectureStepContent(stepLabel),
      checklist: ['检查是否和当前章节冲突', '确认后续还能继续展开'],
    }, null, 2);
  }

  if (systemText.includes('中文长篇小说资料整理编辑')) {
    return JSON.stringify({
      characters: [
        {
          name: '主角',
          profile: '擅长开锁，被旧钥匙重新卷进港口旧案。',
          current_state: '刚离开灯塔，已被港务会追兵盯上。',
          relationships: [
            '码头旧友：提供线索但立场摇摆',
            '旧船队后人：掌握关键账册',
          ],
          events: [
            {
              name: '钥匙重回港口',
              summary: '旧船队失踪留下的钥匙重回港口。',
              related_characters: ['主角'],
              evidence: ['旧船队失踪留下的钥匙重回港口'],
            },
            {
              name: '追兵持续施压',
              summary: '港务会追兵持续施压。',
              related_characters: ['主角'],
              evidence: ['港务会追兵持续施压'],
            },
          ],
          locations: [
            {
              name: '灯塔',
              summary: '灯塔暗号牵连灰色航线。',
              related_characters: ['主角'],
              evidence: ['灯塔暗号'],
            },
            {
              name: '港口',
              summary: '港口秩序被港务会和商会掩盖。',
              related_characters: ['主角'],
              evidence: ['港口依赖潮位和灯塔暗号'],
            },
          ],
          props: [
            {
              name: '钥匙',
              summary: '旧船队失踪留下的钥匙。',
              related_characters: ['主角'],
              evidence: ['旧船队失踪留下的钥匙'],
            },
          ],
          skills: [
            {
              name: '开锁',
              summary: '主角擅长开锁。',
              related_characters: ['主角'],
              evidence: ['主角擅长开锁'],
            },
          ],
          scenes: [
            {
              name: '雨夜靠港',
              summary: '第一章让钥匙回到主角手里。',
              related_characters: ['主角'],
              evidence: ['第 1 章《雨夜靠港》'],
            },
          ],
          organizations: [
            {
              name: '港务会',
              summary: '港务会追兵持续施压。',
              related_characters: ['主角'],
              evidence: ['港务会追兵持续施压'],
            },
          ],
          evidence: ['主角擅长开锁', '刚离开灯塔'],
        },
        {
          name: '码头旧友',
          profile: '提供线索，但立场处在摇摆状态。',
          current_state: '暂时协助主角，仍未完全站队。',
          relationships: ['主角：提供线索但立场摇摆'],
          events: [
            {
              name: '旧友提供线索',
              summary: '码头旧友提供线索。',
              related_characters: ['主角', '码头旧友'],
              evidence: ['码头旧友提供线索'],
            },
          ],
          locations: [
            {
              name: '港口',
              summary: '码头旧友在港口线索里活动。',
              related_characters: ['码头旧友'],
              evidence: ['港口依赖潮位和灯塔暗号'],
            },
          ],
          props: [],
          skills: [],
          scenes: [],
          organizations: [],
          evidence: ['码头旧友提供线索', '码头旧友立场摇摆'],
        },
        {
          name: '旧船队后人',
          profile: '掌握关键账册和旧船队真相碎片。',
          current_state: '暂时不敢露面。',
          relationships: ['主角：握有后续真相碎片'],
          events: [
            {
              name: '关键账册未露面',
              summary: '旧船队后人掌握关键账册。',
              related_characters: ['主角', '旧船队后人'],
              evidence: ['旧船队后人掌握关键账册'],
            },
          ],
          locations: [],
          props: [
            {
              name: '关键账册',
              summary: '旧船队后人掌握关键账册。',
              related_characters: ['旧船队后人'],
              evidence: ['旧船队后人掌握关键账册'],
            },
          ],
          skills: [],
          scenes: [],
          organizations: [],
          evidence: ['旧船队后人掌握关键账册', '旧船队后人暂时不敢露面'],
        },
      ],
      events: [
        {
          name: '钥匙重回港口',
          summary: '旧船队失踪留下的钥匙重回港口。',
          related_characters: ['主角'],
          evidence: ['旧船队失踪留下的钥匙重回港口'],
        },
        {
          name: '追兵持续施压',
          summary: '港务会追兵持续施压。',
          related_characters: ['主角'],
          evidence: ['港务会追兵持续施压'],
        },
      ],
      locations: [
        {
          name: '港口',
          summary: '港口依赖潮位和灯塔暗号维持灰色航线。',
          related_characters: ['主角', '码头旧友'],
          evidence: ['港口依赖潮位和灯塔暗号'],
        },
        {
          name: '灯塔',
          summary: '灯塔暗号维持灰色航线。',
          related_characters: ['主角'],
          evidence: ['灯塔暗号'],
        },
      ],
      props: [
        {
          name: '钥匙',
          summary: '旧船队失踪留下的钥匙。',
          related_characters: ['主角'],
          evidence: ['旧船队失踪留下的钥匙'],
        },
        {
          name: '关键账册',
          summary: '旧船队后人掌握关键账册。',
          related_characters: ['旧船队后人'],
          evidence: ['旧船队后人掌握关键账册'],
        },
      ],
      skills: [
        {
          name: '开锁',
          summary: '主角擅长开锁。',
          related_characters: ['主角'],
          evidence: ['主角擅长开锁'],
        },
      ],
      scenes: [
        {
          name: '雨夜靠港',
          summary: '钥匙回到主角手里，追兵第一次逼近。',
          related_characters: ['主角'],
          evidence: ['第 1 章《雨夜靠港》'],
        },
      ],
      organizations: [
        {
          name: '港务会',
          summary: '港务会追兵持续施压。',
          related_characters: ['主角'],
          evidence: ['港务会追兵持续施压'],
        },
      ],
    }, null, 2);
  }

  if (systemText.includes('中文小说续写总编')) {
    return JSON.stringify({
      summary: '承接当前章节：主角在灯塔下暴露行踪，港务会追兵已经逼近。',
      must_keep: [
        '主角擅长开锁',
        '旧钥匙和旧船队线索不能提前说破',
        '港务会追兵要持续施压',
      ],
      current_state: [
        '主角刚离开灯塔',
        '追兵没有明说身份',
        '潮声和木栈道声音是现场压力来源',
      ],
      voice_rules: [
        '保持连载节奏',
        '用动作和环境推进压力',
      ],
      blocked_changes: [
        '不要改掉主角已经在灯塔下出现的事实',
        '不要提前揭露旧船队真相',
      ],
      next_action: '让追兵靠近，同时把钥匙的危险性露出半格。',
    }, null, 2);
  }

  if (systemText.includes('中文小说场景规划编辑')) {
    return JSON.stringify({
      headline: '追兵压近的场景计划',
      summary: '顺着灯塔现场继续推进，让追兵的压力逼近主角。',
      checklist: ['保留灯塔现场', '让追兵压近', '把钥匙线索留到下一步'],
      scenes: [
        {
          title: '离开灯塔',
          goal: '让主角带着钥匙撤离',
          conflict: '港务会追兵从木栈道另一头逼近',
          turn: '主角发现追兵知道钥匙在他手上',
        },
        {
          title: '潮声遮步',
          goal: '利用潮声掩护主角转移',
          conflict: '追兵熟悉码头路线',
          turn: '主角被迫钻进旧船坞',
        },
        {
          title: '旧船坞暗号',
          goal: '让钥匙和旧船队线索产生联系',
          conflict: '追兵堵住出口',
          turn: '墙上旧暗号指向下一章线索',
        },
      ],
      next_action: '继续把旧船队账册和追兵关系带出来。',
    }, null, 2);
  }

  if (systemText.includes('中文小说续写写手')) {
    return '他把钥匙按进掌心，刚离开灯塔就听见潮声后面有人跟来。港务会的人没有点灯，只靠靴底刮过木栈道的声音逼近，像在提醒他这次回港不是偶然。';
  }

  if (systemText.includes('中文小说去 AI 改稿编辑')) {
    if (isSecondChapterRevisionPrompt(userText)) {
      return JSON.stringify({
        headline: '第二章语言已处理',
        summary: '保留旧船队名单和铜钥匙暗纹线索，只收紧说明腔。',
        revised: '# 第二章 旧船队名单\n他在旧档案室里把旧船队名单翻出来，发现最后一页被人重新装订过。港务会的人追到门外时，他才看见名单边角压着和铜钥匙同样的暗纹。',
        changes: ['保留原有情节事实', '减少解释性句子', '保持追查压力'],
        updated_summary: '',
        updated_character_state: '',
      }, null, 2);
    }

    return JSON.stringify({
      headline: '第一章语言已处理',
      summary: '保留灯塔、潮声、追兵和钥匙线索，只压掉模板腔。',
      revised: '# 第一章 雨夜靠港\n他把钥匙按进掌心，刚离开灯塔就听见潮声后面有人跟来。港务会的人没有点灯，只靠靴底刮过木栈道的声音逼近，像在提醒他这次回港不是偶然。',
      changes: ['保留原有情节事实', '减少解释性句子', '保持现场压力'],
      updated_summary: '',
      updated_character_state: '',
    }, null, 2);
  }

  if (systemText.includes('中文小说一致性检查编辑')) {
    return JSON.stringify({
      summary: '当前章节与既有设定一致，灯塔、钥匙和追兵线索可以继续推进。',
      issues: [],
      suggestions: ['下一步继续追查旧船队名单。'],
    }, null, 2);
  }

  if (systemText.includes('中文小说章节写手')) {
    if (/第二章|第 2 章|旧船队名单/u.test(userText)) {
      return JSON.stringify({
        headline: '第二章正文已生成',
        summary: '这一版把旧船队名单翻出，并把港务会追查压力推进到下一层。',
        content: '# 第二章 旧船队名单\n他在旧档案室里把旧船队名单翻出来，发现最后一页被人重新装订过。港务会的人追到门外时，他才看见名单边角压着和铜钥匙同样的暗纹。',
        next_action: '继续查名单缺页和港务登记的关系。',
      }, null, 2);
    }

    return JSON.stringify({
      headline: '正文已生成',
      summary: '这一版先把追兵压近，再把钥匙的来历露出半格。',
      content: '# 第一章 雨夜靠港\n他把钥匙按进掌心，刚离开灯塔就听见潮声后面有人跟来。港务会的人没有点灯，只靠靴底刮过木栈道的声音逼近，像在提醒他这次回港不是偶然。',
      next_action: '继续把旧船队账册和追兵关系拎出来。',
    }, null, 2);
  }

  return JSON.stringify({
    reply: '当前请求已经有明确结果，可以继续往下验证。',
    suggestions: ['继续下一步验证'],
  }, null, 2);
}

async function startMockModelServer(port) {
  const server = createServer(async (request, response) => {
    if (!request.url) {
      jsonResponse(response, { error: 'missing url' }, 404);
      return;
    }

    const chunks = [];
    for await (const chunk of request) {
      chunks.push(chunk);
    }
    const bodyText = Buffer.concat(chunks).toString('utf-8') || '{}';
    let payload = {};
    try {
      payload = JSON.parse(bodyText);
    } catch {
      jsonResponse(response, { error: 'invalid json' }, 400);
      return;
    }

    if (request.url.endsWith('/chat/completions')) {
      const messages = Array.isArray(payload?.messages) ? payload.messages : [];
      jsonResponse(response, {
        id: 'chatcmpl-ui-smoke',
        object: 'chat.completion',
        created: Math.floor(Date.now() / 1000),
        model: String(payload?.model ?? 'demo-model'),
        choices: [
          {
            index: 0,
            message: {
              role: 'assistant',
              content: mockChatCompletionContent(messages),
            },
            finish_reason: 'stop',
          },
        ],
      });
      return;
    }

    if (request.url.endsWith('/embeddings')) {
      const inputs = Array.isArray(payload?.input) ? payload.input : [payload?.input].filter(Boolean);
      jsonResponse(response, {
        object: 'list',
        data: inputs.map((item, index) => ({
          object: 'embedding',
          index,
          embedding: embeddingVectorFromText(item, Number(payload?.dimensions ?? 64) || 64),
        })),
        model: String(payload?.model ?? 'text-embedding-3-small'),
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
    async stop() {
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

async function findProjectByName(backendUrl, name) {
  const projects = await apiRequest(backendUrl, '/api/projects');
  const matchedProject = projects.find((item) => item.name === name);

  if (!matchedProject) {
    throw new Error(`没有找到项目：${name}`);
  }

  return matchedProject;
}

async function seedProjectWorkflow(backendUrl, projectId) {
  await apiRequest(backendUrl, `/api/projects/${projectId}/memory`, {
    method: 'PUT',
    body: JSON.stringify({
      entries: [
        {
          id: 'project-discussion-summary',
          title: '项目讨论结论',
          category: '目标',
          content: '故事定为港口悬疑长篇。主角因为一把旧钥匙重新卷入失踪船队和家族旧账，前段先立住钥匙来源和追查压力，中段拆开家族与旧船队关系，后段让主角在真相和秩序之间做选择。',
        },
      ],
    }),
  });

  await apiRequest(backendUrl, `/api/projects/${projectId}/architecture/workspace`, {
    method: 'PUT',
    body: JSON.stringify({
      genre: '港口悬疑',
      target_chapters: 20,
      target_words: 200000,
      workspace: {
        core_seed: '旧船队遗失的钥匙重新出现，主角被迫追查自己的家族旧账。',
        character_design: '主角擅长开锁，码头旧友提供线索，港务会不断追人，旧船队后人掌握真相碎片。',
        world_building: '港口城市依赖潮位和灯塔信号开启隐秘航线，旧船队消失多年后留下大量传闻。',
        plot_structure: '前段找钥匙和旧案，中段拆家族和船队关系，后段逼近真相并改写港口秩序。',
        character_state: '主角暂时被迫独自查线索，码头旧友处在摇摆状态，港务会已经开始盯人。',
        blueprint: '## 第 1 章《雨夜靠港》\n主角捡到钥匙并暴露行踪。\n\n## 第 2 章《旧船队名单》\n主角追到第一条旧线索。',
        global_summary: '项目已经明确为港口悬疑长篇，当前先推进开篇两章，把钥匙、旧船队和家族旧账三条线立起来。',
      },
    }),
  });

  await apiRequest(backendUrl, `/api/projects/${projectId}/knowledge/import`, {
    method: 'POST',
    body: JSON.stringify({
      items: [
        {
          title: '旧船队调查记录',
          content: '旧船队在大潮夜失踪，港务会随后删改登记册。铜钥匙和旧船队最后一次靠港记录有关。',
        },
      ],
    }),
  });
}

async function seedPromptPreset(backendUrl, name, description) {
  await apiRequest(backendUrl, '/api/studio/prompt-presets', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  }).catch((error) => {
    if (!String(error.message).includes('提示词方案已存在')) {
      throw error;
    }
  });

  await apiRequest(backendUrl, `/api/studio/prompt-presets/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({
      description,
      prompts: {
        architecture: '自动化回归：保留冲突密度。',
        brainstorm: '自动化回归：先追问人物关系和冲突压力。',
      },
    }),
  });
}

async function seedXpPreset(backendUrl, name, content) {
  await apiRequest(backendUrl, '/api/studio/xp-presets', {
    method: 'POST',
    body: JSON.stringify({ name, content }),
  }).catch((error) => {
    if (!String(error.message).includes('XP 预设已存在')) {
      throw error;
    }
  });
}

async function waitForSelectedProject(page, expectedName) {
  await page.waitForFunction(
    (name) => {
      const title = document.querySelector('[data-testid="stage-project-title"]');
      return title instanceof HTMLElement && title.textContent?.trim() === name;
    },
    expectedName,
  );
}

async function openSelectedProjectFirstChapter(page) {
  await page.locator('.project-card-active').first().waitFor();
  const chapterRow = page.getByTestId('chapter-row-chapter-001');
  await chapterRow.waitFor({ state: 'visible' });
  await chapterRow.click();
}

async function runSmoke(previewUrl, backendUrl) {
  const chromePath = await resolveChromePath();
  const browser = await chromium.launch({
    executablePath: chromePath,
    headless: true,
    args: [
      '--disable-dev-shm-usage',
      '--no-first-run',
      '--no-default-browser-check',
    ],
  });

  const page = await browser.newPage({
    viewport: {
      width: 1600,
      height: 1100,
    },
  });

  const projectName = `自动化烟雾测试-${Date.now()}`;
  const projectNameSecond = `${projectName}-第二部`;
  const projectNameSecondRenamed = `${projectNameSecond}-改名`;
  const token = `自动化检索词-${Date.now()}`;
  const personaName = `测试人物-${Date.now()}`;
  const personaFocus = '只看开头怎么更快立住冲突。';
  const personaNotes = '说话直接，优先判断取舍，不接受平铺。';
  const promptPresetName = `预设-${Date.now()}`;
  const xpPresetName = `XP-${Date.now()}`;
  const fileToken = `文件回写-${Date.now()}`;
  const architectureAgentToken = `架构执行-${Date.now()}`;
  const knowledgeQuery = '旧船队';

  try {
    await page.goto(previewUrl, { waitUntil: 'load' });
    await page.getByTestId('app-shell').waitFor();

    if (await page.getByText('当前有几项能力还没准备好：').isVisible().catch(() => false)) {
      throw new Error('工作台启动后出现 boot error');
    }

    await page.getByTestId('open-create-project-button').click();
    await page.getByTestId('create-project-modal').waitFor();
    await page.getByTestId('create-project-name-input').fill(projectName);
    await page.getByTestId('create-project-submit-button').click();

    await page.getByTestId('create-project-modal').waitFor({ state: 'hidden' });
    await page.getByText(projectName, { exact: true }).first().waitFor();
    await page.getByTestId('open-create-project-button').click();
    await page.getByTestId('create-project-modal').waitFor();
    await page.getByTestId('create-project-name-input').fill(projectNameSecond);
    await page.getByTestId('create-project-submit-button').click();
    await page.getByTestId('create-project-modal').waitFor({ state: 'hidden' });
    await waitForSelectedProject(page, projectNameSecond);
    await page.locator('.project-card-active').getByTestId('project-menu-trigger').click();
    await page.getByTestId('project-rename-button').click();
    await page.getByTestId('rename-project-modal').waitFor();
    await page.getByTestId('rename-project-input').fill(projectNameSecondRenamed);
    await page.getByRole('button', { name: '保存名称' }).click();
    await page.getByTestId('rename-project-modal').waitFor({ state: 'hidden' });
    await waitForSelectedProject(page, projectNameSecondRenamed);
    const renameNotice = page.getByText(`作品已重命名为《${projectNameSecondRenamed}》`);
    await renameNotice.waitFor();
    await page.locator('.project-shell').filter({
      has: page.getByText(projectName, { exact: true }),
    }).locator('.project-main').click();
    await waitForSelectedProject(page, projectName);
    await renameNotice.waitFor({ state: 'hidden' });
    await page.locator('.project-shell').filter({
      has: page.getByText(projectNameSecondRenamed, { exact: true }),
    }).locator('.project-main').click();
    await waitForSelectedProject(page, projectNameSecondRenamed);
    await page.locator('.project-shell').filter({
      has: page.getByText(projectName, { exact: true }),
    }).getByTestId('project-menu-trigger').click();
    await page.getByTestId('project-delete-button').click();
    await page.getByTestId('delete-project-modal').waitFor();
    await page.getByRole('button', { name: '确认删除' }).click();
    await page.getByTestId('delete-project-modal').waitFor({ state: 'hidden' });
    await page.getByText(projectName, { exact: true }).waitFor({ state: 'hidden' });
    await page.getByTestId('workspace-composer-input').waitFor();

    const customPrompt = `${token}：先别给结论，先判断冲突是不是太平。`;
    await page.getByTestId('workspace-composer-input').fill(customPrompt);
    await page.getByTestId('new-conversation-button').click();
    await page.waitForFunction(
      (expectedPrompt) => {
        const textarea = document.querySelector('[data-testid="workspace-composer-input"]');
        return textarea instanceof HTMLTextAreaElement
          && textarea.value !== expectedPrompt;
      },
      customPrompt,
    );

    const seededProject = await findProjectByName(backendUrl, projectNameSecondRenamed);
    await seedProjectWorkflow(backendUrl, seededProject.id);
    await seedPromptPreset(backendUrl, promptPresetName, '自动化回归用提示词方案');
    await seedXpPreset(backendUrl, xpPresetName, '测试偏好：优先保留悬念和动作牵引。');
    await page.reload({ waitUntil: 'load' });
    await page.getByTestId('app-shell').waitFor();
    await waitForSelectedProject(page, projectNameSecondRenamed);
    await saveProjectChapterContent(
      backendUrl,
      seededProject.id,
      'chapter-001',
      `# 第一章\n主角擅长开锁，${token} 在灯塔下出现。\n`,
    );
    await waitForProjectChapterContent(backendUrl, seededProject.id, 'chapter-001', token);
    await openSelectedProjectFirstChapter(page);
    await page.getByTestId('chapter-preview-panel').waitFor();
    await waitForChapterPreviewContent(page, token);
    if (await page.getByTestId('agent-session-window').isVisible().catch(() => false)) {
      throw new Error('空对话 session 区不应显示');
    }
    await page.getByTestId('chapter-drawer-collapse-button').click();
    await page.getByTestId('chapter-row-chapter-001').waitFor({ state: 'hidden' });
    await page.locator('[data-testid^="project-chapter-toggle-"]').first().click();
    await openSelectedProjectFirstChapter(page);
    await page.getByTestId('project-tools-trigger').click();
    await page.getByTestId('open-history-button').click();
    await page.getByTestId('history-modal').waitFor();
    await page.getByRole('button', { name: /刷新状态|刷新中/ }).click();
    await page.getByTestId('history-save-input').fill('自动化烟雾版本');
    const firstSnapshotRow = page.locator('.snapshot-row').first();
    await firstSnapshotRow.waitFor();
    await firstSnapshotRow.click();
    const historySaveButton = page.getByTestId('history-save-button');
    if (await historySaveButton.isEnabled()) {
      await historySaveButton.click();
      await page.waitForFunction(() => {
        const input = document.querySelector('[data-testid="history-save-input"]');
        return input instanceof HTMLInputElement && input.value === '';
      });
    } else {
      log('版本管理已进入自动快照状态，跳过手动版本保存');
    }
    await page.keyboard.press('Escape');
    await page.getByTestId('history-modal').waitFor({ state: 'hidden' });
    await page.reload({ waitUntil: 'load' });
    await page.getByTestId('app-shell').waitFor();
    await waitForSelectedProject(page, projectNameSecondRenamed);
    await openSelectedProjectFirstChapter(page);
    await page.getByTestId('chapter-preview-panel').waitFor();
    await waitForChapterPreviewContent(page, token);

    log('检查 Agent 章节计划和执行');
    await page.getByTestId('workspace-composer-input').waitFor();
    await page.getByTestId('workspace-composer-input').fill('续写这一章，把追兵压近一点。');
    await page.locator('.composer-submit-button').click();
    await page.waitForFunction(() => {
      const textarea = document.querySelector('[data-testid="workspace-composer-input"]');
      return textarea instanceof HTMLTextAreaElement && textarea.value === '';
    });
    await page.getByTestId('agent-plan-card').waitFor();
    await page.getByTestId('agent-plan-card').getByText(/生成第 1 章正文|第 1 章《.*》正文/u).first().waitFor();
    await page.getByTestId('agent-timeline').first().waitFor();
    await page.getByTestId('agent-artifact-card').first().waitFor();
    await waitForProjectChapterContent(backendUrl, seededProject.id, 'chapter-001', '潮声后面有人跟来', { timeoutMs: 60000 });
    await waitForChapterPreviewContent(page, '潮声后面有人跟来');
    await page.locator('[data-testid^="agent-session-row-"]').first().waitFor();
    await page.getByTestId('agent-session-window').getByText(/续写这一章|追兵/u).first().waitFor();
    if (await page.locator('.session-preview, .session-time').count()) {
      throw new Error('对话 session 不应显示摘要或时间');
    }

    log('检查当前第一章时生成第二章会写回第二章');
    await page.getByTestId('workspace-composer-input').fill('参考第一章，生成第二章内容。');
    await page.locator('.composer-submit-button').click();
    await page.waitForFunction(() => {
      const textarea = document.querySelector('[data-testid="workspace-composer-input"]');
      return textarea instanceof HTMLTextAreaElement && textarea.value === '';
    });
    await page.getByTestId('agent-plan-card').getByText(/生成第 2 章正文/u).first().waitFor();
    await waitForProjectChapterNonEmpty(backendUrl, seededProject.id, 'chapter-002', { timeoutMs: 60000 });

    log('检查混合命令优先走架构');
    await page.getByTestId('workspace-composer-input').fill('把资料库的资料分析完，再重新弄续写架构');
    await page.locator('.composer-submit-button').click();
    await page.getByText('整书架构已经补齐并写回项目').first().waitFor({ timeout: 20000 });
    await waitForProjectDocumentContent(backendUrl, seededProject.id, 'blueprint', '第 3 章《夜潮账册》');

    await page.getByTestId('open-skills-button').click();
    await page.getByTestId('skills-stage').waitFor();
    await page.getByTestId('skill-use-knowledge-search').click();
    await page.getByTestId('skill-workbench').waitFor();
    await page.getByTestId('knowledge-search-input').fill(knowledgeQuery);
    await page.getByTestId('knowledge-search-button').click();
    await page.getByTestId('knowledge-search-results').getByText(knowledgeQuery).first().waitFor();

    log('检查联网考据未配置提示');
    await page.getByTestId('skill-use-web-research').click();
    await page.getByTestId('web-research-input').fill('鸿门宴典故');
    await page.getByTestId('web-research-button').click();
    await page.getByTestId('web-research-result').getByText('BOCHA_API_KEY').waitFor();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="web-research-import-button"]');
      return button instanceof HTMLButtonElement && button.disabled;
    });

    log('检查 Agent 自学习面板');
    await page.getByTestId('skill-use-self-evolution').click();
    await page.getByTestId('self-evolution-result').waitFor();
    await page.getByTestId('self-evolution-candidates').waitFor();
    await page.getByTestId('self-evolution-refresh-button').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="self-evolution-refresh-button"]');
      return button instanceof HTMLButtonElement && !button.disabled;
    });
    await page.getByTestId('self-evolution-curate-button').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="self-evolution-curate-button"]');
      return button instanceof HTMLButtonElement && !button.disabled;
    });
    await page.getByTestId('self-evolution-regression-button').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="self-evolution-regression-button"]');
      return button instanceof HTMLButtonElement && !button.disabled;
    });
    await page.getByTestId('self-evolution-regression').getByText('续写样本').waitFor();
    await page.getByTestId('self-evolution-model-review-button').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="self-evolution-model-review-button"]');
      return button instanceof HTMLButtonElement && !button.disabled;
    });
    await page.getByTestId('self-evolution-model-reviews').getByText(/模型审查|自学习审查/u).first().waitFor();
    await page.getByTestId('self-evolution-quality-dimensions').waitFor();
    await page.getByTestId('self-evolution-trends').waitFor();
    await page.getByTestId('self-evolution-failure-cases').waitFor();
    await page.getByTestId('self-evolution-skill-versions').waitFor();
    await page.getByTestId('self-evolution-schedule-save-button').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="self-evolution-schedule-save-button"]');
      return button instanceof HTMLButtonElement && !button.disabled;
    });
    await page.getByTestId('self-evolution-schedule-run-button').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('[data-testid="self-evolution-schedule-run-button"]');
      return button instanceof HTMLButtonElement && !button.disabled;
    });

    await page.getByTestId('return-workspace-button').click();
    await page.getByTestId('workspace-composer-input').waitFor();

    await page.getByTestId('open-settings-button').click();
    await page.getByTestId('settings-modal').waitFor();
    await page.getByTestId('settings-modal').locator('.accordion-summary').click();
    await page.getByTestId('settings-modal').getByText('单独设置 Embedding').waitFor();
    await page.getByTestId('settings-modal').getByLabel('单独设置 Embedding').check();
    await page.getByTestId('settings-modal').getByText('Embedding 模型').waitFor();
    await page.getByTestId('settings-modal').getByText('自学习审查模型').waitFor();
    await page.keyboard.press('Escape');
    await page.getByTestId('settings-modal').waitFor({ state: 'hidden' });
    await page.getByTestId('new-conversation-button').click();
    await page.getByTestId('architecture-composer-input').waitFor();

    log('检查 Agent 整书架构执行');
    await page.getByTestId('architecture-composer-input').fill(`前十章先立住港口秩序和钥匙来源，${architectureAgentToken}`);
    await page.getByTestId('architecture-open-confirm-button').click();
    await page.getByRole('dialog', { name: '确认执行整书架构' }).waitFor();
    await page.getByRole('button', { name: '确认执行' }).click();
    await page.getByText('整书架构已经补齐并写回项目').first().waitFor({ timeout: 20000 });
    await page.getByTestId('agent-timeline').first().waitFor();
    await page.getByTestId('agent-artifact-card').first().waitFor();
    await waitForProjectDocumentContent(backendUrl, seededProject.id, 'blueprint', '第 3 章《夜潮账册》');

    log('检查 Agent 讨论结果渲染');
    await page.waitForFunction(() => {
      const textarea = document.querySelector('[data-testid="architecture-composer-input"]');
      const button = document.querySelector('[data-testid="architecture-submit-button"]');
      return textarea instanceof HTMLTextAreaElement
        && button instanceof HTMLButtonElement
        && textarea.value === ''
        && !button.disabled;
    });
    await page.getByTestId('architecture-composer-input').fill('聊聊这本书下一步最该推进什么。');
    await page.getByTestId('architecture-submit-button').click();
    await page.getByText(/下一步先别急着扩支线/u).first().waitFor({ timeout: 20000 });
    await page.getByRole('button', { name: '钥匙和主角家族旧账怎么连起来' }).waitFor();
    await page.reload({ waitUntil: 'load' });
    await page.getByTestId('app-shell').waitFor();
    await waitForSelectedProject(page, projectNameSecondRenamed);
    await page.getByText(/下一步先别急着扩支线/u).first().waitFor();
    await page.waitForFunction(() => (
      document.querySelectorAll('[data-testid^="agent-session-row-"]').length >= 2
    ));

    log('检查架构总览');
    await page.getByTestId('open-story-overview-button').click();
    await page.getByTestId('story-overview-modal').waitFor();
    await page.getByTestId('story-overview-core-summary').waitFor();
    await page.getByTestId('story-overview-character-map').waitFor();
    await page.getByTestId('story-overview-relationship-grid').waitFor();
    await page.getByTestId('story-overview-character-skills').waitFor();
    await page.getByTestId('story-overview-timeline').waitFor();
    await page.getByRole('button', { name: '查看事件' }).click();
    await page.locator('[data-overview-target="events"]').waitFor();
    await page.getByRole('button', { name: '查看技能' }).click();
    await page.locator('[data-overview-target="skills"]').waitFor();
    await page.getByRole('button', { name: '查看时间线' }).click();
    await page.getByTestId('story-overview-timeline').waitFor();
    await page.keyboard.press('Escape');
    await page.getByTestId('story-overview-modal').waitFor({ state: 'hidden' });
    log('检查提示词方案');
    await page.getByTestId('open-skills-button').click();
    await page.getByTestId('skills-stage').waitFor();
    await page.getByTestId('open-prompt-presets-button').click();
    await page.getByTestId('skill-workbench').waitFor();
    await page.getByRole('button', { name: new RegExp(promptPresetName) }).waitFor();
    await page.getByRole('button', { name: new RegExp(promptPresetName) }).click();
    log('等待提示词方案回填');
    await page.waitForFunction(
      ({ expectedName, expectedDescription }) => {
        const nameInput = document.querySelector('[data-testid="prompt-preset-name-input"]');
        const descriptionInput = document.querySelector('[data-testid="prompt-preset-description-input"]');
        return nameInput instanceof HTMLInputElement
          && descriptionInput instanceof HTMLInputElement
          && nameInput.value === expectedName
          && descriptionInput.value === expectedDescription;
      },
      { expectedName: promptPresetName, expectedDescription: '自动化回归用提示词方案' },
    );
    await page.getByTestId('prompt-preset-activate-button').click();
    await page.getByRole('button', { name: new RegExp(promptPresetName) }).waitFor();

    log('检查 XP 预设');
    await page.getByTestId('skill-use-xp-presets').click();
    await page.getByTestId('xp-preset-name-input').waitFor();
    await page.getByRole('button', { name: new RegExp(xpPresetName) }).waitFor();
    await page.getByRole('button', { name: new RegExp(xpPresetName) }).click();
    log('等待 XP 预设回填');
    await page.waitForFunction(
      (expectedValue) => {
        const textarea = document.querySelector('[data-testid="xp-preset-content-input"]');
        return textarea instanceof HTMLTextAreaElement && textarea.value.includes(expectedValue);
      },
      '测试偏好：优先保留悬念和动作牵引。',
    );

    log('检查文件浏览器');
    await page.getByTestId('skill-use-file-browser').click();
    await page.locator('.file-list .list-item-button').first().click();
    await page.getByTestId('file-browser-editor').waitFor();
    const originalFileContent = await page.getByTestId('file-browser-editor').inputValue();
    await page.getByTestId('file-browser-editor').fill(`${originalFileContent}\n${fileToken}\n`);
    await page.getByTestId('file-browser-save-button').click();

    log('检查人物复刻');
    await page.getByTestId('skill-use-character-replica').click();
    await page.getByTestId('character-replica-persona-input').fill(personaName);
    await page.getByTestId('character-replica-question-input').fill('如果用这个人的视角看，这一章开头应该怎么改？');
    await page.getByTestId('character-replica-focus-input').fill(personaFocus);
    await page.getByTestId('character-replica-notes-input').fill(personaNotes);
    await page.getByTestId('character-replica-save-profile-button').click();
    await page.getByRole('button', { name: personaName }).waitFor();

    await page.getByTestId('character-replica-persona-input').fill('');
    await page.getByTestId('character-replica-focus-input').fill('');
    await page.getByTestId('character-replica-notes-input').fill('');
    await page.getByRole('button', { name: personaName }).click();
    log('等待人物复刻资料回填');
    await page.waitForFunction(
      ({ expectedName, expectedFocus, expectedNotes }) => {
        const persona = document.querySelector('[data-testid="character-replica-persona-input"]');
        const focus = document.querySelector('[data-testid="character-replica-focus-input"]');
        const notes = document.querySelector('[data-testid="character-replica-notes-input"]');
        return persona instanceof HTMLInputElement
          && focus instanceof HTMLTextAreaElement
          && notes instanceof HTMLTextAreaElement
          && persona.value === expectedName
          && focus.value === expectedFocus
          && notes.value === expectedNotes;
      },
      { expectedName: personaName, expectedFocus: personaFocus, expectedNotes: personaNotes },
    );
  } finally {
    await page.close();
    await browser.close();
  }
}

async function main() {
  const backendPort = await getFreePort();
  const previewPort = await getFreePort();
  const modelPort = await getFreePort();
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const previewUrl = `http://127.0.0.1:${previewPort}`;
  const dataDir = await mkdtemp(path.join(os.tmpdir(), 'novel-ui-smoke-data-'));
  const corsOrigins = JSON.stringify([
    'http://localhost:1420',
    'http://127.0.0.1:1420',
    'http://tauri.localhost',
    'https://tauri.localhost',
    'tauri://localhost',
    previewUrl,
  ]);
  const backgroundProcesses = [];
  let mockModelServer = null;
  let shouldRestoreDefaultBuild = false;
  let pendingError = null;
  const smokeLicense = createSmokeLicense();

  try {
    await runCommand('npm', ['run', 'build'], {
      label: '构建前端',
      env: {
        VITE_NOVEL_BACKEND_URL: backendUrl,
      },
    });
    shouldRestoreDefaultBuild = true;

    log(`启动临时 backend：${backendUrl}`);
    const backend = spawnProcess(
      path.join(ROOT_DIR, '.venv', 'bin', 'python'),
      ['-m', 'novel_backend.main', '--host', '127.0.0.1', '--port', String(backendPort), '--data-dir', dataDir],
      {
        label: 'backend',
        env: {
          NOVEL_CORS_ORIGINS: corsOrigins,
          NOVEL_LICENSE_PUBLIC_KEY: smokeLicense.publicKey,
          BOCHA_API_KEY: '',
          BOCHA_SEARCH_ENDPOINT: '',
        },
      },
    );
    backgroundProcesses.push(backend);
    await waitForHttpOk(`${backendUrl}/api/app/health`, { timeoutMs: 15000 });
    await seedTestLicense(backendUrl, smokeLicense.content);

    log(`启动本地假模型：127.0.0.1:${modelPort}`);
    mockModelServer = await startMockModelServer(modelPort);
    await seedModelConfig(backendUrl, mockModelServer.url);

    log(`启动 Vite preview：${previewUrl}`);
    const preview = spawnProcess(
      process.execPath,
      ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', String(previewPort), '--strictPort'],
      {
        label: 'preview',
      },
    );
    backgroundProcesses.push(preview);
    await waitForHttpOk(previewUrl, { timeoutMs: 15000 });

    log('运行浏览器 smoke');
    await runSmoke(previewUrl, backendUrl);
    log('界面 smoke 通过');
  } catch (error) {
    pendingError = error;
    const logs = backgroundProcesses
      .map((processInfo) => processInfo.readLogs())
      .filter(Boolean)
      .join('\n');
    const appLog = await readTail(path.join(dataDir, 'logs', 'app.log'), 120);
    const promptLog = await readTail(path.join(dataDir, 'logs', 'prompt_history.jsonl'), 40);

    if (logs) {
      console.error(`\n${logs}`);
    }
    if (appLog) {
      console.error(`\n----- app.log -----\n${appLog}`);
    }
    if (promptLog) {
      console.error(`\n----- prompt_history.jsonl -----\n${promptLog}`);
    }

    throw error;
  } finally {
    for (const processInfo of backgroundProcesses.reverse()) {
      await processInfo.stop().catch(() => {});
    }
    if (mockModelServer) {
      await mockModelServer.stop().catch(() => {});
    }
    await rm(dataDir, { recursive: true, force: true });
    if (shouldRestoreDefaultBuild) {
      try {
        await runCommand('npm', ['run', 'build'], {
          label: '恢复默认前端构建',
        });
      } catch (restoreError) {
        if (pendingError) {
          console.error(`\n[ui-smoke] 恢复默认构建失败：${restoreError instanceof Error ? restoreError.message : String(restoreError)}`);
        } else {
          throw restoreError;
        }
      }
    }
  }

  if (pendingError) {
    throw pendingError;
  }
}

main().catch((error) => {
  console.error(`\n[ui-smoke] 失败：${error instanceof Error ? error.message : String(error)}`);
  if (error instanceof Error && error.stack) {
    console.error(error.stack);
  }
  process.exit(1);
});
