<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { applyProjectArchitectureWorkspace, streamArchitectureStep } from '../lib/api.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  discussionSummary: {
    type: String,
    default: '',
  },
  modelName: {
    type: String,
    default: '未配置模型',
  },
  autoRunToken: {
    type: Number,
    default: 0,
  },
});

const emit = defineEmits(['project-detail-updated', 'run-started']);

const architectureSteps = [
  { key: 'core_seed', label: '核心种子', hint: '定主线冲突和整本卖点' },
  { key: 'character_design', label: '人物设定', hint: '把人物关系和驱动力拉清楚' },
  { key: 'world_building', label: '世界设定', hint: '补齐规则、空间和氛围' },
  { key: 'plot_structure', label: '情节骨架', hint: '把大推进和转折铺开' },
  { key: 'character_state', label: '人物状态', hint: '记录当前人物处境和暗线' },
  { key: 'blueprint', label: '章节蓝图', hint: '给整本书排出章节走向' },
  { key: 'global_summary', label: '滚动摘要', hint: '压缩成后续可复用的总说明' },
];

const readinessKeys = ['core_seed', 'character_design', 'world_building', 'plot_structure', 'blueprint'];

function emptyWorkspace() {
  return {
    core_seed: '',
    character_design: '',
    world_building: '',
    plot_structure: '',
    character_state: '',
    blueprint: '',
    global_summary: '',
  };
}

const workspace = reactive(emptyWorkspace());
const planForm = reactive({
  genre: '未定题材',
  targetChapters: 20,
  targetWords: 200000,
  guidance: '',
});

const isGenerating = ref(false);
const currentStepKey = ref('');
const currentTaskId = ref('');
const streamMessage = ref('');
const actionMessage = ref('');
const errorMessage = ref('');
const resultByStep = ref({});
const lastAutoRunToken = ref(0);

function currentDocumentContent(documentKey) {
  return props.project?.story_overview?.documents?.find((item) => item.key === documentKey)?.content ?? '';
}

function syncWorkspaceFromProject() {
  Object.assign(workspace, emptyWorkspace());

  architectureSteps.forEach((step) => {
    workspace[step.key] = currentDocumentContent(step.key);
  });

  planForm.genre = props.project?.genre?.trim() || '未定题材';
  planForm.targetChapters = props.project?.target_chapters ?? 20;
  planForm.targetWords = props.project?.target_words ?? 200000;
}

watch(
  () => props.project,
  () => {
    syncWorkspaceFromProject();
  },
  { immediate: true },
);

watch(
  () => props.project?.id,
  () => {
    actionMessage.value = '';
    errorMessage.value = '';
    streamMessage.value = '';
    currentTaskId.value = '';
  },
  { immediate: true },
);

const discussionText = computed(() => props.discussionSummary.trim());

const canGenerate = computed(() => (
  Boolean(props.project?.id)
  && Boolean(discussionText.value || planForm.guidance.trim())
));

const completedStepCount = computed(() => (
  architectureSteps.filter((step) => workspace[step.key]?.trim()).length
));

const isArchitectureReady = computed(() => (
  readinessKeys.every((key) => workspace[key]?.trim())
));

const progressRatio = computed(() => {
  if (architectureSteps.length === 0) {
    return 0;
  }

  return completedStepCount.value / architectureSteps.length;
});

const stepStatusList = computed(() => (
  architectureSteps.map((step) => ({
    ...step,
    status: currentStepKey.value === step.key
      ? 'running'
      : workspace[step.key]?.trim()
        ? 'done'
        : 'pending',
  }))
));

function normalizeGenre() {
  return planForm.genre.trim() || '未定题材';
}

async function persistWorkspace() {
  if (!props.project?.id) {
    return null;
  }

  const detail = await applyProjectArchitectureWorkspace(props.project.id, {
    workspace: { ...workspace },
    genre: normalizeGenre(),
    target_chapters: Math.min(1000, Math.max(1, Number(planForm.targetChapters) || 20)),
    target_words: Math.min(2000000, Math.max(1000, Number(planForm.targetWords) || 200000)),
  });
  emit('project-detail-updated', detail);
  return detail;
}

function buildGuidance(step) {
  const parts = [];

  if (discussionText.value) {
    parts.push(`讨论结论：\n${discussionText.value}`);
  }

  parts.push(
    [
      '规划参数：',
      `题材：${normalizeGenre()}`,
      `目标章节数：${Math.min(1000, Math.max(1, Number(planForm.targetChapters) || 20))}`,
      `目标字数：${Math.min(2000000, Math.max(1000, Number(planForm.targetWords) || 200000))}`,
      `当前步骤：${step.label}`,
    ].join('\n'),
  );

  if (planForm.guidance.trim()) {
    parts.push(`补充要求：\n${planForm.guidance.trim()}`);
  }

  return parts.join('\n\n');
}

async function runSingleStep(step) {
  let stepResult = null;
  let stepError = '';

  currentStepKey.value = step.key;
  streamMessage.value = `正在生成${step.label}`;

  await streamArchitectureStep(
    {
      project_id: props.project.id,
      step: step.key,
      mode: 'initial',
      guidance: buildGuidance(step),
      new_chapters: 0,
      workspace: { ...workspace },
    },
    (event) => {
      if (event.event === 'started' && event.data && typeof event.data === 'object') {
        currentTaskId.value = event.data.task_id ?? '';
        return;
      }

      if (event.event === 'progress' && event.data && typeof event.data === 'object') {
        streamMessage.value = `${step.label}：${event.data.message ?? '处理中'}`;
        return;
      }

      if (event.event === 'result' && event.data && typeof event.data === 'object') {
        stepResult = event.data;
        return;
      }

      if (event.event === 'error' && event.data && typeof event.data === 'object') {
        stepError = event.data.message ?? `${step.label} 生成失败`;
      }
    },
  );

  if (stepError) {
    throw new Error(stepError);
  }

  if (!stepResult?.content?.trim()) {
    throw new Error(`${step.label} 没有返回可保存内容`);
  }

  workspace[step.key] = stepResult.content;
  resultByStep.value = {
    ...resultByStep.value,
    [step.key]: stepResult,
  };
}

async function saveWorkspaceDraft() {
  if (!props.project?.id || isGenerating.value) {
    return;
  }

  actionMessage.value = '';
  errorMessage.value = '';

  try {
    await persistWorkspace();
    actionMessage.value = '架构草稿已写回项目';
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '架构草稿写回失败';
  }
}

async function generateArchitecture() {
  if (!props.project?.id || isGenerating.value) {
    return;
  }

  if (!canGenerate.value) {
    errorMessage.value = '先补一轮讨论结论，或者手动写下这本书的规划要求';
    return;
  }

  emit('run-started');
  isGenerating.value = true;
  actionMessage.value = '';
  errorMessage.value = '';
  streamMessage.value = '正在准备整书架构';
  currentTaskId.value = '';
  resultByStep.value = {};

  try {
    await persistWorkspace();

    for (const step of architectureSteps) {
      await runSingleStep(step);
    }

    await persistWorkspace();
    actionMessage.value = '整书架构已写回项目，下面可以开始逐章写。';
    streamMessage.value = '整书架构生成完成';
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整书架构生成失败';
  } finally {
    currentStepKey.value = '';
    isGenerating.value = false;
  }
}

watch(
  () => props.autoRunToken,
  (token) => {
    if (!token || token === lastAutoRunToken.value) {
      return;
    }

    lastAutoRunToken.value = token;
    if (!isArchitectureReady.value && canGenerate.value) {
      void generateArchitecture();
    }
  },
);
</script>

<template>
  <section class="planner-shell">
    <header class="planner-header">
      <div>
        <p class="planner-kicker">整书架构</p>
        <h3>把讨论结果展开成整本书</h3>
        <p class="planner-copy">
          这里会把讨论结论接成整书规划，自动补齐核心种子、人物设定、世界设定、情节骨架、章节蓝图，再写回项目。
        </p>
      </div>

      <div class="planner-chip-row">
        <span class="planner-chip">{{ modelName }}</span>
        <span class="planner-chip">{{ completedStepCount }}/{{ architectureSteps.length }} 项已就绪</span>
      </div>
    </header>

    <div class="planner-top-grid">
      <section class="planner-card">
        <div class="planner-card-head">
          <h4>讨论结论</h4>
          <span :class="['status-badge', discussionText ? 'status-badge-ready' : 'status-badge-pending']">
            {{ discussionText ? '已接入' : '还没讨论' }}
          </span>
        </div>

        <p
          v-if="discussionText"
          class="summary-text"
        >
          {{ discussionText }}
        </p>
        <p
          v-else
          class="empty-copy"
        >
          建议先在上一步把故事方向聊清楚。你也可以直接在下方补充要求，手工写入架构草稿。
        </p>
      </section>

      <section class="planner-card">
        <div class="planner-card-head">
          <h4>规划参数</h4>
          <div class="action-row">
            <button
              class="secondary-button small-button"
              type="button"
              @click="syncWorkspaceFromProject"
            >
              同步当前项目
            </button>
            <button
              :disabled="isGenerating"
              class="secondary-button small-button"
              data-testid="architecture-save-button"
              type="button"
              @click="saveWorkspaceDraft"
            >
              保存草稿
            </button>
            <button
              :disabled="isGenerating || !canGenerate"
              class="primary-button small-button"
              data-testid="architecture-generate-button"
              type="button"
              @click="generateArchitecture"
            >
              {{ isGenerating ? '生成中…' : '一键生成整书架构' }}
            </button>
          </div>
        </div>

        <div class="planner-form-grid">
          <label class="form-field">
            <span>题材</span>
            <input
              v-model="planForm.genre"
              data-testid="architecture-genre-input"
              maxlength="40"
              placeholder="例如：悬疑奇谈"
            >
          </label>

          <label class="form-field">
            <span>目标章节数</span>
            <input
              v-model.number="planForm.targetChapters"
              data-testid="architecture-target-chapters-input"
              min="1"
              max="1000"
              type="number"
            >
          </label>

          <label class="form-field">
            <span>目标字数</span>
            <input
              v-model.number="planForm.targetWords"
              data-testid="architecture-target-words-input"
              min="1000"
              max="2000000"
              step="1000"
              type="number"
            >
          </label>
        </div>

        <label class="form-field">
          <span>补充要求</span>
          <textarea
            v-model="planForm.guidance"
            data-testid="architecture-guidance-input"
            rows="5"
            placeholder="例如：前 3 章就要把主角、旧船队和钥匙之间的关系立住。"
          />
        </label>
      </section>
    </div>

    <section class="planner-card">
      <div class="planner-card-head">
        <h4>生成进度</h4>
        <span class="status-line">{{ Math.round(progressRatio * 100) }}%</span>
      </div>

      <div class="progress-track">
        <div
          class="progress-track-bar"
          :style="{ width: `${Math.max(progressRatio * 100, isGenerating ? 6 : 0)}%` }"
        />
      </div>

      <div class="step-grid">
        <article
          v-for="item in stepStatusList"
          :key="item.key"
          :class="['step-card', `step-card-${item.status}`]"
        >
          <div class="step-card-head">
            <strong>{{ item.label }}</strong>
            <span>
              {{
                item.status === 'running'
                  ? '生成中'
                  : item.status === 'done'
                    ? '已完成'
                    : '待处理'
              }}
            </span>
          </div>
          <p>{{ item.hint }}</p>
        </article>
      </div>

      <p
        v-if="streamMessage"
        class="status-copy"
      >
        {{ streamMessage }}{{ currentTaskId ? ` · 任务 ${currentTaskId}` : '' }}
      </p>
      <p
        v-if="actionMessage"
        class="status-copy status-copy-success"
      >
        {{ actionMessage }}
      </p>
      <p
        v-if="errorMessage"
        class="status-copy status-copy-error"
      >
        {{ errorMessage }}
      </p>
    </section>

    <section class="planner-card">
      <div class="planner-card-head">
        <h4>架构工作区</h4>
        <span class="status-line">可手工调整后再保存</span>
      </div>

      <div class="workspace-grid">
        <label
          v-for="item in architectureSteps"
          :key="item.key"
          class="form-field"
        >
          <span>{{ item.label }}</span>
          <textarea
            v-model="workspace[item.key]"
            :data-testid="`architecture-doc-${item.key}`"
            :rows="item.key === 'blueprint' ? 10 : 6"
          />
        </label>
      </div>
    </section>
  </section>
</template>

<style scoped>
.planner-shell {
  display: grid;
  gap: 12px;
  min-height: 0;
}

.planner-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.planner-kicker {
  margin: 0 0 6px;
  color: #7a8390;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.planner-header h3 {
  margin: 0;
  color: #1f2328;
  font-size: 22px;
  line-height: 1.15;
}

.planner-copy {
  margin: 8px 0 0;
  color: #5d6675;
  font-size: 13px;
  line-height: 1.7;
  max-width: 720px;
}

.planner-chip-row,
.action-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.planner-chip,
.status-badge,
.status-line {
  border-radius: 999px;
  padding: 7px 11px;
  border: 1px solid #d8dde6;
  background: rgba(255, 255, 255, 0.88);
  color: #4d5762;
  font-size: 12px;
  white-space: nowrap;
}

.status-badge-ready {
  border-color: #c7e7cf;
  background: #f3fbf4;
  color: #116329;
}

.status-badge-pending {
  border-color: #e2e8ef;
  background: #f8fafc;
  color: #6b7280;
}

.planner-top-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(360px, 1.2fr);
  gap: 12px;
}

.planner-card {
  display: grid;
  gap: 12px;
  border: 1px solid rgba(212, 218, 229, 0.92);
  border-radius: 16px;
  padding: 16px;
  background: #ffffff;
  box-shadow: none;
}

.planner-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.planner-card-head h4 {
  margin: 0;
  color: #1f2328;
  font-size: 16px;
}

.summary-text,
.empty-copy,
.status-copy,
.step-card p {
  margin: 0;
  color: #4a5561;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.empty-copy {
  color: #6b7280;
}

.planner-form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.form-field {
  display: grid;
  gap: 8px;
}

.form-field span {
  color: #57606a;
  font-size: 12px;
}

.form-field input,
.form-field textarea {
  width: 100%;
  border: 1px solid #d0d7de;
  border-radius: 14px;
  padding: 11px 12px;
  background: #fbfcfd;
  color: #1f2328;
  font-size: 13px;
  line-height: 1.7;
}

.form-field textarea {
  resize: vertical;
}

.secondary-button,
.primary-button {
  border-radius: 999px;
  padding: 9px 13px;
  font-size: 12px;
  cursor: pointer;
}

.secondary-button {
  border: 1px solid #d0d7de;
  background: #ffffff;
  color: #24292f;
}

.primary-button {
  border: 0;
  background: #1d4ed8;
  color: #ffffff;
  font-weight: 700;
}

.secondary-button:disabled,
.primary-button:disabled {
  opacity: 0.68;
  cursor: wait;
}

.progress-track {
  width: 100%;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(223, 228, 236, 0.85);
}

.progress-track-bar {
  height: 100%;
  border-radius: inherit;
  background: #1d4ed8;
  transition: width 220ms ease;
}

.step-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}

.step-card {
  display: grid;
  gap: 8px;
  border-radius: 18px;
  padding: 12px;
  border: 1px solid #e3e8ef;
  background: #f9fbfd;
}

.step-card-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.step-card-head strong {
  color: #1f2328;
  font-size: 14px;
}

.step-card-head span {
  color: #6b7280;
  font-size: 11px;
}

.step-card-running {
  border-color: #cbd8ff;
  background: #eef4ff;
}

.step-card-done {
  border-color: #c7e7cf;
  background: #f3fbf4;
}

.status-copy-success {
  color: #116329;
}

.status-copy-error {
  color: #cf222e;
}

.workspace-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 1200px) {
  .planner-top-grid,
  .planner-form-grid,
  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .planner-header,
  .planner-card-head {
    flex-direction: column;
  }
}
</style>
