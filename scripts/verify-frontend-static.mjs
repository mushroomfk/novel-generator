import { readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function read(relativePath) {
  const absolutePath = path.join(repoRoot, relativePath);
  const stat = statSync(absolutePath);
  if (!stat.isFile()) {
    throw new Error(`${relativePath} must be a file`);
  }
  return readFileSync(absolutePath, 'utf8');
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function includesAll(content, relativePath, snippets) {
  for (const snippet of snippets) {
    assert(content.includes(snippet), `${relativePath} is missing required UI text: ${snippet}`);
  }
}

function excludesAll(content, relativePath, snippets) {
  for (const snippet of snippets) {
    assert(!content.includes(snippet), `${relativePath} still contains removed UI text: ${snippet}`);
  }
}

const appVue = read('src/App.vue');
includesAll(appVue, 'src/App.vue', [
  '已接管《${result.project.name}》：已导入 ${result.report.applied_chapter_count} 章',
]);
excludesAll(appVue, 'src/App.vue', [
  '拆章置信度',
]);

const existingNovelModal = read('src/components/ExistingNovelImportModal.vue');
includesAll(existingNovelModal, 'src/components/ExistingNovelImportModal.vue', [
  'data-testid="existing-novel-import-modal"',
  'accept=".txt"',
  '旧稿文件只支持 .txt',
  '已导入章节',
  '导入旧稿正文',
  '写入项目章节正文',
  '刷新本地知识库索引',
]);
excludesAll(existingNovelModal, 'src/components/ExistingNovelImportModal.vue', [
  '<dt>置信度</dt>',
  '章节识别',
  '按章节标题拆分旧稿',
  '生成接管报告和章节清单',
]);

const workflowPanel = read('src/components/NovelWorkflowPanel.vue');
includesAll(workflowPanel, 'src/components/NovelWorkflowPanel.vue', [
  'data-testid="agent-runtime-message"',
  'data-testid="agent-runtime-status-list"',
  'data-testid="agent-runtime-status-row"',
  "id: 'runtime-status-thinking'",
  "'正在思考'",
  "'正在运行'",
  "'已完成'",
  'v-if="!isCompletedExecutionMessage(item) && messageTimelineItems(item).length"',
  'v-if="!isCompletedExecutionMessage(item) && messageEventBlocks(item).length"',
  'return isCompletedExecutionMessage(message) ? [] : blocks;',
]);

console.log('[verify-frontend-static] old draft import and agent runtime UI checks passed');
