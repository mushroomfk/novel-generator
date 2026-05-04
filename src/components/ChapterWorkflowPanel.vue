<script setup>
import { computed, ref, watch } from 'vue';
import { streamChapterWorkflow, updateProjectChapter, updateStoryDocument } from '../lib/api.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  selectedChapter: {
    type: Object,
    default: null,
  },
  architectureReady: {
    type: Boolean,
    default: true,
  },
});

const emit = defineEmits(['project-detail-updated']);

const mode = ref('diagnose');
const instruction = ref('');
const targetWords = ref(1500);
const isRunning = ref(false);
const progressEntries = ref([]);
const result = ref(null);
const errorMessage = ref('');
const taskId = ref('');
const actionMessage = ref('');
const isSavingDraft = ref(false);
const isSavingScenes = ref(false);

const modeOptions = [
  { id: 'diagnose', label: '章节诊断', hint: '判断这一章现在最该先改什么' },
  { id: 'scenes', label: '拆场景', hint: '把本章拆成可直接执行的场景列表' },
  { id: 'draft', label: '续写正文', hint: '围绕当前上下文直接写出正文' },
];

const chapterContextLine = computed(() => {
  if (!props.selectedChapter) {
    return '先从左侧选中一章，再在这里推进本章。';
  }

  return [
    `第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》`,
    props.project?.genre ?? '长篇小说',
    props.selectedChapter.exists ? '已有正文' : '待写章节',
  ].join(' · ');
});

const currentProgress = computed(() => (
  progressEntries.value.length > 0 ? progressEntries.value[progressEntries.value.length - 1] : null
));

const progressRatio = computed(() => {
  if (result.value) {
    return 1;
  }

  if (!currentProgress.value?.total) {
    return isRunning.value ? 0.08 : 0;
  }

  return currentProgress.value.step / currentProgress.value.total;
});

const runButtonLabel = computed(() => {
  if (mode.value === 'scenes') {
    return '开始拆场景';
  }
  if (mode.value === 'draft') {
    return '开始续写';
  }
  return '开始判断';
});

watch(
  [() => props.project, () => props.selectedChapter, mode],
  ([project, chapter, nextMode]) => {
    resetRunState();
    if (!project || !chapter) {
      instruction.value = '';
      return;
    }

    if (nextMode === 'scenes') {
      instruction.value = `请把《${chapter.title}》拆成 4 到 6 个场景，并明确每场的目标、冲突和转折。`;
      return;
    }

    if (nextMode === 'draft') {
      instruction.value = chapter.exists
        ? `请沿着这一章现有内容继续写，保持当前语气和冲突方向。`
        : `请从这一章的第一个有效场景写起，不要提前揭露真相。`;
      return;
    }

    instruction.value = chapter.exists
      ? `请判断《${chapter.title}》现在最该优先处理的是节奏、冲突升级还是结尾钩子。`
      : `请判断《${chapter.title}》在正式落笔前最该先明确的目标和冲突。`;
  },
  { immediate: true },
);

function isRecord(value) {
  return value !== null && typeof value === 'object';
}

function resetRunState() {
  progressEntries.value = [];
  result.value = null;
  errorMessage.value = '';
  taskId.value = '';
  actionMessage.value = '';
}

async function runWorkflow() {
  if (!props.architectureReady) {
    errorMessage.value = '先把整书架构补齐，再开始逐章推进。';
    return;
  }

  if (!props.project?.id || !props.selectedChapter?.id) {
    errorMessage.value = '先选择当前章节';
    return;
  }

  isRunning.value = true;
  resetRunState();

  try {
    await streamChapterWorkflow(
      {
        project_id: props.project.id,
        chapter_id: props.selectedChapter.id,
        mode: mode.value,
        instruction: instruction.value.trim(),
        target_words: targetWords.value,
      },
      (event) => {
        if (event.event === 'started' && isRecord(event.data)) {
          taskId.value = event.data.task_id ?? '';
          return;
        }

        if (event.event === 'progress' && isRecord(event.data)) {
          progressEntries.value = [
            ...progressEntries.value,
            {
              step: event.data.step ?? progressEntries.value.length + 1,
              total: event.data.total ?? 0,
              message: event.data.message ?? '正在继续处理',
            },
          ];
          return;
        }

        if (event.event === 'result' && isRecord(event.data)) {
          result.value = event.data;
          return;
        }

        if (event.event === 'error' && isRecord(event.data)) {
          errorMessage.value = event.data.message ?? '章节工作流执行失败';
        }
      },
    );
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '章节工作流执行失败';
  } finally {
    isRunning.value = false;
  }
}

function currentDocumentContent(documentKey) {
  return props.project?.story_overview?.documents?.find((item) => item.key === documentKey)?.content ?? '';
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildBlueprintSection() {
  if (!props.selectedChapter || !result.value) {
    return '';
  }

  const chapterHeading = `## 第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》`;
  const sceneLines = (result.value.scenes ?? []).map((item, index) => (
    [
      `### 场景 ${index + 1} · ${item.title}`,
      `目标：${item.goal}`,
      `冲突：${item.conflict}`,
      `转折：${item.turn}`,
    ].join('\n')
  ));

  return [
    chapterHeading,
    result.value.summary ?? '',
    ...sceneLines,
  ].filter(Boolean).join('\n\n');
}

function mergeBlueprintContent(existingContent, nextSection) {
  if (!props.selectedChapter) {
    return existingContent;
  }

  const heading = `## 第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》`;
  const escaped = escapeRegex(heading);
  const pattern = new RegExp(`${escaped}[\\s\\S]*?(?=\\n## 第 \\d+ 章《|$)`, 'm');

  if (pattern.test(existingContent)) {
    return existingContent.replace(pattern, nextSection).trim();
  }

  return [existingContent.trim(), nextSection].filter(Boolean).join('\n\n').trim();
}

async function saveScenesToBlueprint() {
  if (!props.project?.id || !props.selectedChapter || !result.value?.scenes?.length) {
    return;
  }

  isSavingScenes.value = true;
  actionMessage.value = '';

  try {
    const mergedContent = mergeBlueprintContent(
      currentDocumentContent('blueprint'),
      buildBlueprintSection(),
    );
    const detail = await updateStoryDocument(props.project.id, 'blueprint', {
      content: mergedContent,
    });
    emit('project-detail-updated', detail);
    actionMessage.value = '场景计划已写入章节蓝图';
  } catch (error) {
    actionMessage.value =
      error instanceof Error ? error.message : '章节蓝图写入失败';
  } finally {
    isSavingScenes.value = false;
  }
}

async function saveDraftToChapter() {
  if (!props.project?.id || !props.selectedChapter?.id || !result.value?.draft) {
    return;
  }

  isSavingDraft.value = true;
  actionMessage.value = '';

  try {
    const { detail, reviewError } = await updateProjectChapter(props.project.id, props.selectedChapter.id, {
      content: result.value.draft,
    });
    emit('project-detail-updated', detail);
    actionMessage.value = reviewError || '续写正文已保存到当前章节';
  } catch (error) {
    actionMessage.value =
      error instanceof Error ? error.message : '正文保存失败';
  } finally {
    isSavingDraft.value = false;
  }
}
</script>

<template>
  <section class="chapter-agent-shell">
    <header class="chapter-agent-header">
      <div>
        <h3>{{ selectedChapter ? `围绕 ${selectedChapter.title} 推进本章` : '围绕当前章节推进' }}</h3>
        <p class="chapter-context">{{ chapterContextLine }}</p>
      </div>
    </header>

    <section class="chat-surface">
      <div class="workflow-controls">
        <section
          v-if="!architectureReady"
          class="empty-note empty-note-warning"
        >
          这一步依赖整书架构。先把核心种子、人物设定、世界设定、情节骨架和章节蓝图写好，再回来推进本章。
        </section>

        <div class="mode-row">
          <button
            v-for="item in modeOptions"
            :key="item.id"
            :class="['mode-chip', { 'mode-chip-active': mode === item.id }]"
            :disabled="!architectureReady"
            type="button"
            @click="mode = item.id"
          >
            <strong>{{ item.label }}</strong>
            <span>{{ item.hint }}</span>
          </button>
        </div>

        <div class="control-grid">
          <label class="control-field control-field-grow">
            <span>工作指令</span>
            <textarea
              v-model="instruction"
              :disabled="!architectureReady"
              rows="4"
              placeholder="补充这一章当前最想解决的问题。"
            />
          </label>

          <label class="control-field control-field-small">
            <span>目标字数</span>
            <input
              v-model.number="targetWords"
              :disabled="!architectureReady"
              min="300"
              max="8000"
              step="100"
              type="number"
            >
          </label>
        </div>

        <div class="workflow-actions">
          <button
            :disabled="isRunning || !selectedChapter || !architectureReady"
            class="primary-button"
            type="button"
            @click="runWorkflow"
          >
            {{ isRunning ? '处理中…' : runButtonLabel }}
          </button>
          <span
            v-if="taskId"
            class="task-chip"
          >
            任务 {{ taskId }}
          </span>
        </div>
      </div>

      <div class="chat-scroll">
        <article
          v-if="isRunning || progressEntries.length > 0"
          class="message message-assistant"
        >
          <div class="message-role">执行进度</div>
          <div class="thinking-progress">
            <div
              class="thinking-progress-bar"
              :style="{ width: `${Math.max(progressRatio * 100, isRunning ? 8 : 0)}%` }"
            />
          </div>
          <ul
            v-if="progressEntries.length > 0"
            class="message-list"
          >
            <li
              v-for="item in progressEntries"
              :key="`${item.step}-${item.message}`"
            >
              第 {{ item.step }} / {{ item.total }} 步：{{ item.message }}
            </li>
          </ul>
        </article>

        <article
          v-if="result"
          class="message message-assistant message-stage"
        >
          <div class="result-head">
            <div>
              <div class="message-role">工作流结果</div>
              <strong class="result-headline">{{ result.headline }}</strong>
            </div>

            <div class="result-actions">
              <button
                v-if="mode === 'scenes' && result.scenes?.length > 0"
                :disabled="isSavingScenes"
                class="secondary-button"
                type="button"
                @click="saveScenesToBlueprint"
              >
                {{ isSavingScenes ? '写入中…' : '写入章节蓝图' }}
              </button>

              <button
                v-if="mode === 'draft' && result.draft"
                :disabled="isSavingDraft"
                class="primary-button"
                type="button"
                @click="saveDraftToChapter"
              >
                {{ isSavingDraft ? '保存中…' : '保存到当前章节' }}
              </button>
            </div>
          </div>

          <p class="result-summary">{{ result.summary }}</p>

          <section
            v-if="result.checklist?.length > 0"
            class="result-section"
          >
            <span class="result-label">执行要点</span>
            <ul class="message-list">
              <li
                v-for="item in result.checklist"
                :key="item"
              >
                {{ item }}
              </li>
            </ul>
          </section>

          <section
            v-if="result.scenes?.length > 0"
            class="result-section"
          >
            <span class="result-label">场景拆分</span>
            <div class="scene-grid">
              <article
                v-for="(item, index) in result.scenes"
                :key="`${item.title}-${index}`"
                class="scene-card"
              >
                <strong>{{ index + 1 }}. {{ item.title }}</strong>
                <p>目标：{{ item.goal }}</p>
                <p>冲突：{{ item.conflict }}</p>
                <p>转折：{{ item.turn }}</p>
              </article>
            </div>
          </section>

          <section
            v-if="result.draft"
            class="result-section"
          >
            <span class="result-label">续写正文</span>
            <pre class="draft-block">{{ result.draft }}</pre>
          </section>

          <p
            v-if="result.next_action"
            class="next-action"
          >
            下一步：{{ result.next_action }}
          </p>
          <p
            v-if="actionMessage"
            class="action-message"
          >
            {{ actionMessage }}
          </p>
        </article>

        <p
          v-if="errorMessage"
          class="error"
        >
          {{ errorMessage }}
        </p>

        <section
          v-if="!selectedChapter"
          class="empty-note"
        >
          先从左侧或右侧打开一章，再在这里推进这一章的目标、冲突和续写。
        </section>
      </div>
    </section>
  </section>
</template>

<style scoped>
.chapter-agent-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  flex: 1;
  min-height: 0;
}

.chapter-agent-header h3 {
  margin: 0;
  color: #1f2328;
  font-size: 18px;
  line-height: 1.18;
}

.chapter-context {
  margin: 8px 0 0;
  color: #5d6675;
  font-size: 12px;
}

.chat-surface {
  min-height: 0;
  border: 1px solid rgba(212, 218, 229, 0.92);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: none;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.workflow-controls {
  border-bottom: 1px solid #edf1f6;
  padding: 14px;
  display: grid;
  gap: 12px;
}

.mode-row,
.workflow-actions,
.result-head,
.result-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
}

.mode-chip {
  flex: 1;
  min-width: 0;
  text-align: left;
  border: 1px solid #d7dee8;
  border-radius: 14px;
  padding: 10px 12px;
  background: #ffffff;
}

.mode-chip strong,
.result-headline {
  display: block;
  color: #1f2430;
}

.mode-chip span {
  display: block;
  margin-top: 6px;
  color: #616b79;
  font-size: 12px;
  line-height: 1.5;
}

.mode-chip-active {
  border-color: #d5e2f6;
  background: #eaf2ff;
}

.control-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px;
  gap: 12px;
}

.control-field {
  display: grid;
  gap: 8px;
}

.control-field span,
.result-label,
.message-role {
  color: #7a8390;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.control-field textarea,
.control-field input {
  width: 100%;
  border: 1px solid #d0d7de;
  border-radius: 12px;
  padding: 10px 12px;
  background: #ffffff;
  color: #1f2328;
  font-size: 13px;
}

.task-chip {
  border: 1px solid #d8dde6;
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.88);
  color: #4d5762;
  font-size: 11px;
}

.primary-button,
.secondary-button {
  border-radius: 10px;
  padding: 9px 14px;
  font-size: 13px;
  cursor: pointer;
}

.primary-button {
  border: none;
  background: #1d4ed8;
  color: #ffffff;
}

.secondary-button {
  border: 1px solid #d0d7de;
  background: #ffffff;
  color: #1f2430;
}

.primary-button:disabled,
.secondary-button:disabled {
  opacity: 0.55;
  cursor: default;
}

.chat-scroll {
  display: grid;
  gap: 10px;
  min-height: 0;
  height: 100%;
  padding: 14px;
  overflow: auto;
  align-content: start;
}

.message {
  border-radius: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(215, 221, 231, 0.95);
  background: #ffffff;
  box-shadow: none;
}

.message-stage {
  background: #f8fbff;
}

.thinking-progress {
  width: 100%;
  height: 6px;
  margin-top: 12px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(223, 228, 236, 0.85);
}

.thinking-progress-bar {
  height: 100%;
  border-radius: inherit;
  background: #1d4ed8;
  transition: width 220ms ease;
}

.message-list {
  margin: 10px 0 0;
  padding-left: 18px;
  color: #4a5561;
  line-height: 1.8;
}

.result-summary,
.next-action,
.action-message {
  margin: 10px 0 0;
  color: #4a5561;
  line-height: 1.8;
}

.result-section {
  margin-top: 14px;
}

.scene-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.scene-card {
  border-radius: 14px;
  padding: 12px;
  background: rgba(248, 250, 252, 0.95);
}

.scene-card strong {
  color: #1f2430;
}

.scene-card p {
  margin: 8px 0 0;
  color: #4a5561;
  line-height: 1.7;
}

.draft-block {
  margin: 10px 0 0;
  padding: 14px;
  border-radius: 14px;
  background: #f9fbfd;
  white-space: pre-wrap;
  color: #344054;
  line-height: 1.8;
  max-height: 420px;
  overflow: auto;
}

.error {
  margin: 0;
  color: #b42318;
}

.empty-note {
  border-radius: 18px;
  padding: 14px;
  border: 1px dashed #d0d7de;
  color: #5d6675;
}

.empty-note-warning {
  border-style: solid;
  background: #f8fafc;
}

@media (max-width: 1100px) {
  .control-grid,
  .scene-grid {
    grid-template-columns: 1fr;
  }
}
</style>
