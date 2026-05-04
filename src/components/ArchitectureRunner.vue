<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { skillSections } from '../lib/skillCatalog.js';
import { streamArchitecture, updateStoryDocuments } from '../lib/api.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  selectedChapter: {
    type: Object,
    default: null,
  },
  modelName: {
    type: String,
    default: '未配置模型',
  },
  sessionKey: {
    type: Number,
    default: 0,
  },
});
const emit = defineEmits(['project-detail-updated']);

const form = reactive({
  mode: '灵感碰撞',
  chapterFocus: '',
  styleReference: '',
  premise: '',
});

const isRunning = ref(false);
const progressEntries = ref([]);
const result = ref(null);
const errorMessage = ref('');
const currentTaskId = ref('');
const chatViewport = ref(null);
const skillPickerRef = ref(null);
const skillKeyword = ref('');
const isSkillPickerOpen = ref(false);
const selectedSkillNames = ref([]);
const isApplyingResult = ref(false);
const applyMessage = ref('');

function isRecord(value) {
  return value !== null && typeof value === 'object';
}

function scrollConversationToBottom() {
  nextTick(() => {
    if (!chatViewport.value) {
      return;
    }

    chatViewport.value.scrollTop = chatViewport.value.scrollHeight;
  });
}

function handleDocumentPointerDown(event) {
  if (!isSkillPickerOpen.value || !skillPickerRef.value) {
    return;
  }

  if (!skillPickerRef.value.contains(event.target)) {
    isSkillPickerOpen.value = false;
  }
}

function syncDraftState(project, selectedChapter) {
  if (!project) {
    return;
  }

  const chapterLabel = selectedChapter
    ? `第 ${selectedChapter.index} 章《${selectedChapter.title}》`
    : `围绕《${project.name}》的下一章或当前场景继续讨论`;

  form.chapterFocus = chapterLabel;
  form.styleReference = `${project.genre} 的整体气质、节奏和角色关系`;
  form.premise = selectedChapter
    ? `我正在推进《${project.name}》的 ${chapterLabel}。请先判断当前最值得先处理的是章节目标、冲突升级、场景拆解，还是续写入口。`
    : `我想继续推进《${project.name}》，请先判断下一步最值得讨论的是开篇冲突、章节拆解，还是人物关系。`;
  progressEntries.value = [];
  result.value = null;
  errorMessage.value = '';
  currentTaskId.value = '';
  applyMessage.value = '';
}

onMounted(() => {
  if (typeof document !== 'undefined') {
    document.addEventListener('pointerdown', handleDocumentPointerDown);
  }
});

onBeforeUnmount(() => {
  if (typeof document !== 'undefined') {
    document.removeEventListener('pointerdown', handleDocumentPointerDown);
  }
});

watch(
  [() => props.project, () => props.selectedChapter],
  ([project, selectedChapter]) => {
    syncDraftState(project, selectedChapter);
  },
  { immediate: true },
);

watch(
  () => props.sessionKey,
  () => {
    syncDraftState(props.project, props.selectedChapter);
  },
);

watch(
  [progressEntries, result, () => isRunning.value],
  () => {
    scrollConversationToBottom();
  },
  { deep: true },
);

const allSkills = computed(() => (
  skillSections.flatMap((section) => section.items)
));

const filteredSkillSections = computed(() => {
  const normalizedKeyword = skillKeyword.value.trim();

  return skillSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => (
        normalizedKeyword.length === 0
        || item.name.includes(normalizedKeyword)
        || item.description.includes(normalizedKeyword)
        || item.category.includes(normalizedKeyword)
        || item.scenes.some((scene) => scene.includes(normalizedKeyword))
      )),
    }))
    .filter((section) => section.items.length > 0);
});

const selectedSkills = computed(() => (
  selectedSkillNames.value
    .map((name) => allSkills.value.find((item) => item.name === name))
    .filter(Boolean)
));

const payload = computed(() => ({
  title: props.project?.name ?? '未命名作品',
  premise: [
    `当前任务：${form.mode}`,
    props.selectedChapter ? `当前章节：第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》` : '',
    `当前章节或场景：${form.chapterFocus.trim()}`,
    props.selectedChapter?.preview ? `章节预览：${props.selectedChapter.preview}` : '',
    form.styleReference.trim() ? `参考风格或素材：${form.styleReference.trim()}` : '',
    selectedSkills.value.length > 0
      ? `启用技能：${selectedSkills.value.map((item) => `${item.name}（${item.description}）`).join('；')}`
      : '',
    `创作讨论：${form.premise.trim()}`,
  ].filter(Boolean).join('\n'),
  genre: props.project?.genre ?? '长篇小说',
  chapter_count: props.project?.target_chapters ?? 20,
  target_words: props.project?.target_words ?? 200000,
}));

const runStatus = computed(() => {
  if (isRunning.value) {
    return 'AI 正在思考';
  }

  if (result.value) {
    return '本轮已完成';
  }

  return '等待你的指令';
});

const requestPreview = computed(() => (
  form.premise.trim() || '先把当前最想解决的写作问题说清楚。'
));

const currentProgress = computed(() => {
  if (progressEntries.value.length === 0) {
    return null;
  }

  return progressEntries.value[progressEntries.value.length - 1];
});

const progressRatio = computed(() => {
  if (result.value) {
    return 1;
  }

  if (!currentProgress.value?.total) {
    return isRunning.value ? 0.08 : 0;
  }

  return currentProgress.value.step / currentProgress.value.total;
});

const thinkingHeadline = computed(() => {
  if (isRunning.value) {
    return currentProgress.value?.message ?? '正在整理这一轮问题的优先级';
  }

  if (result.value) {
    return '这一轮思考已经完成，你可以继续追问。';
  }

  return '';
});

const resultSections = computed(() => {
  if (!result.value) {
    return [];
  }

  return [
    { label: '故事入口', value: result.value.core_seed },
    { label: '人物关系', value: result.value.character_design },
    { label: '世界氛围', value: result.value.world_building },
    { label: '推进方向', value: result.value.plot_structure },
  ];
});

function toggleSkillPicker() {
  isSkillPickerOpen.value = !isSkillPickerOpen.value;
  if (!isSkillPickerOpen.value) {
    skillKeyword.value = '';
  }
}

function toggleSkill(skillName) {
  const exists = selectedSkillNames.value.includes(skillName);
  selectedSkillNames.value = exists
    ? selectedSkillNames.value.filter((item) => item !== skillName)
    : [...selectedSkillNames.value, skillName];
}

async function run() {
  isRunning.value = true;
  progressEntries.value = [];
  result.value = null;
  errorMessage.value = '';
  currentTaskId.value = '';
  applyMessage.value = '';
  scrollConversationToBottom();

  try {
    await streamArchitecture(payload.value, (event) => {
      if (event.event === 'started' && isRecord(event.data)) {
        currentTaskId.value = event.data.task_id ?? '';
        return;
      }

      if (event.event === 'progress' && isRecord(event.data)) {
        progressEntries.value = [
          ...progressEntries.value,
          {
            step: event.data.step ?? progressEntries.value.length + 1,
            total: event.data.total ?? 0,
            message: event.data.message ?? '正在继续分析',
          },
        ];
        return;
      }

      if (event.event === 'result' && isRecord(event.data)) {
        result.value = event.data;
        currentTaskId.value = event.data.task_id ?? currentTaskId.value;
        return;
      }

      if (event.event === 'error' && isRecord(event.data)) {
        errorMessage.value = event.data.message ?? '创作讨论失败';
      }
    });
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '创作讨论失败';
  } finally {
    isRunning.value = false;
  }
}

async function applyResultToProject() {
  if (!props.project?.id || !result.value) {
    return;
  }

  isApplyingResult.value = true;
  applyMessage.value = '';

  try {
    const detail = await updateStoryDocuments(props.project.id, {
      documents: [
        { key: 'core_seed', content: result.value.core_seed ?? '' },
        { key: 'character_design', content: result.value.character_design ?? '' },
        { key: 'world_building', content: result.value.world_building ?? '' },
        { key: 'plot_structure', content: result.value.plot_structure ?? '' },
      ],
    });
    emit('project-detail-updated', detail);
    applyMessage.value = '已写入项目设定文件';
  } catch (error) {
    applyMessage.value =
      error instanceof Error ? error.message : '写入项目设定失败';
  } finally {
    isApplyingResult.value = false;
  }
}
</script>

<template>
  <section class="agent-shell">
    <header class="agent-header">
      <h3>{{ selectedChapter ? `围绕 ${selectedChapter.title} 继续写` : `围绕《${project?.name ?? '当前小说'}》继续写` }}</h3>
    </header>

    <section class="chat-surface">
      <div
        ref="chatViewport"
        class="chat-scroll"
      >
        <article class="message message-user">
          <div class="message-role-row">
            <span class="message-role">你</span>
            <span
              v-if="selectedSkills.length > 0"
              class="message-status"
            >
              已添加 {{ selectedSkills.length }} 个技能
            </span>
          </div>
          <p>{{ requestPreview }}</p>
          <div
            v-if="selectedSkills.length > 0"
            class="message-chip-row"
          >
            <span
              v-for="item in selectedSkills"
              :key="item.name"
              class="inline-skill-chip"
            >
              {{ item.name }}
            </span>
          </div>
        </article>

        <article
          v-if="isRunning || progressEntries.length > 0 || result"
          class="message message-assistant message-thinking"
        >
          <div class="message-role-row">
            <span class="message-role">AI 思考</span>
            <span class="message-status">{{ currentTaskId ? `任务 ${currentTaskId}` : runStatus }}</span>
          </div>
          <p>{{ thinkingHeadline }}</p>

          <div class="thinking-progress">
            <div
              class="thinking-progress-bar"
              :style="{ width: `${Math.max(progressRatio * 100, isRunning ? 8 : 0)}%` }"
            />
          </div>

          <ul
            v-if="progressEntries.length > 0"
            class="thinking-list"
          >
            <li
              v-for="item in progressEntries"
              :key="`${item.step}-${item.message}`"
            >
              <span>{{ item.step }}</span>
              <div>
                <strong>{{ item.message }}</strong>
                <p>第 {{ item.step }} / {{ item.total }} 步</p>
              </div>
            </li>
          </ul>
        </article>

        <article
          v-if="resultSections.length > 0"
          class="message message-assistant"
        >
          <div class="message-role-row">
            <span class="message-role">AI 回复</span>
            <button
              class="apply-button"
              :disabled="isApplyingResult"
              type="button"
              @click="applyResultToProject"
            >
              {{ isApplyingResult ? '写入中…' : '写入设定文件' }}
            </button>
          </div>
          <div class="result-stack">
            <section
              v-for="item in resultSections"
              :key="item.label"
              class="result-line"
            >
              <span>{{ item.label }}</span>
              <p>{{ item.value }}</p>
            </section>
          </div>
          <p
            v-if="applyMessage"
            class="result-message"
          >
            {{ applyMessage }}
          </p>
        </article>

        <p
          v-if="errorMessage"
          class="error"
        >
          {{ errorMessage }}
        </p>
      </div>

      <form
        class="composer-shell"
        @submit.prevent="run"
      >
        <textarea
          v-model="form.premise"
          class="composer-input"
          data-testid="architecture-composer-input"
          rows="5"
          placeholder="例如：我想让这一章结尾更有钩子，但不想硬反转。请先判断问题出在冲突升级、信息揭示还是人物选择。"
        />

        <div class="composer-bottom">
          <div
            ref="skillPickerRef"
            class="composer-toolbar"
          >
            <span class="toolbar-chip">{{ modelName }}</span>

            <button
              :class="['skill-trigger', { 'skill-trigger-active': isSkillPickerOpen }]"
              type="button"
              @click.stop="toggleSkillPicker"
            >
              <span class="skill-trigger-icon">＋</span>
              <span>技能</span>
              <strong v-if="selectedSkills.length > 0">{{ selectedSkills.length }}</strong>
            </button>

            <button
              v-for="item in selectedSkills"
              :key="item.name"
              class="selected-skill-chip"
              type="button"
              @click="toggleSkill(item.name)"
            >
              {{ item.name }}
              <span>×</span>
            </button>

            <div
              v-if="isSkillPickerOpen"
              class="skill-picker-panel"
            >
              <div class="skill-picker-header">
                <div>
                  <p>可添加技能</p>
                  <strong>给这一轮对话挂上能力</strong>
                </div>
                <button
                  class="skill-picker-close"
                  type="button"
                  @click="isSkillPickerOpen = false"
                >
                  关闭
                </button>
              </div>

              <label class="skill-search">
                <input
                  v-model="skillKeyword"
                  type="text"
                  placeholder="搜索技能名称、用途或适用场景"
                >
              </label>

              <div class="skill-picker-sections">
                <section
                  v-for="section in filteredSkillSections"
                  :key="section.title"
                  class="skill-section"
                >
                  <div class="skill-section-head">
                    <div>
                      <strong>{{ section.title }}</strong>
                      <p>{{ section.description }}</p>
                    </div>
                    <span>{{ section.items.length }}</span>
                  </div>

                  <div class="skill-option-list">
                    <button
                      v-for="item in section.items"
                      :key="item.name"
                      :class="['skill-option', { 'skill-option-selected': selectedSkillNames.includes(item.name) }]"
                      type="button"
                      @click="toggleSkill(item.name)"
                    >
                      <div :class="['skill-badge', `skill-badge-${item.accent}`]">
                        {{ item.badge }}
                      </div>

                      <div class="skill-option-copy">
                        <div class="skill-option-title">
                          <strong>{{ item.name }}</strong>
                          <span>{{ item.category }}</span>
                        </div>
                        <p>{{ item.description }}</p>
                        <div class="skill-scene-row">
                          <span
                            v-for="scene in item.scenes"
                            :key="scene"
                          >
                            {{ scene }}
                          </span>
                        </div>
                      </div>

                      <em>{{ selectedSkillNames.includes(item.name) ? '已添加' : '添加' }}</em>
                    </button>
                  </div>
                </section>

                <p
                  v-if="filteredSkillSections.length === 0"
                  class="skill-empty"
                >
                  没找到匹配技能。
                </p>
              </div>
            </div>
          </div>

          <button
            :disabled="isRunning"
            class="submit-button"
            data-testid="architecture-submit-button"
            type="submit"
          >
            {{ isRunning ? '讨论中…' : '发送' }}
          </button>
        </div>
      </form>
    </section>
  </section>
</template>

<style scoped>
.agent-shell {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  flex: 1;
  min-height: 0;
}

.agent-header h3 {
  margin: 0;
  color: #1f2328;
  font-size: 18px;
  line-height: 1.18;
}

.chat-surface {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
  border: 1px solid rgba(212, 218, 229, 0.92);
  border-radius: 18px;
  background: #ffffff;
  box-shadow: none;
  overflow: hidden;
}

.chat-scroll {
  display: grid;
  gap: 10px;
  min-height: 0;
  padding: 14px;
  overflow: auto;
  align-content: start;
}

.message {
  max-width: min(760px, 100%);
  border-radius: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(215, 221, 231, 0.95);
  background: #ffffff;
  box-shadow: none;
}

.message-assistant {
  justify-self: start;
}

.message-user {
  justify-self: end;
  background: #eef4ff;
}

.message-thinking {
  background: #f8fbff;
}

.message-role-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.message-role,
.result-line span {
  color: #7a8390;
  font-size: 12px;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.message-status {
  color: #5c6674;
  font-size: 12px;
}

.message p {
  margin: 8px 0 0;
  color: #1f2430;
  line-height: 1.72;
  white-space: pre-wrap;
}

.message-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.inline-skill-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 5px 10px;
  background: #ffffff;
  border: 1px solid rgba(196, 206, 222, 0.95);
  color: #3b4350;
  font-size: 11px;
}

.thinking-progress {
  margin-top: 10px;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(214, 222, 236, 0.8);
}

.thinking-progress-bar {
  height: 100%;
  border-radius: inherit;
  background: #1d4ed8;
  transition: width 180ms ease;
}

.thinking-list {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
}

.thinking-list li {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.thinking-list span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #eef3ff;
  color: #4055c2;
  font-size: 12px;
  font-weight: 600;
}

.thinking-list strong {
  display: block;
  color: #1f2430;
  font-size: 13px;
}

.thinking-list p {
  margin: 4px 0 0;
  color: #6a7380;
  font-size: 12px;
}

.result-stack {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.result-line {
  border: 1px solid rgba(218, 224, 233, 0.9);
  border-radius: 14px;
  padding: 12px 13px;
  background: rgba(248, 250, 253, 0.92);
}

.result-line p {
  margin-top: 8px;
}

.apply-button {
  border: 1px solid rgba(195, 205, 221, 0.98);
  border-radius: 999px;
  padding: 8px 12px;
  background: #ffffff;
  color: #1f2430;
  cursor: pointer;
}

.apply-button:disabled {
  opacity: 0.6;
  cursor: wait;
}

.result-message {
  margin: 10px 0 0;
  color: #5d6675;
  font-size: 12px;
}

.composer-shell {
  border-top: 1px solid #edf1f6;
  padding: 14px;
  background: rgba(255, 255, 255, 0.98);
}

.composer-input {
  width: 100%;
  min-height: 124px;
  border: none;
  padding: 0;
  background: transparent;
  color: #1f2328;
  font-size: 14px;
  line-height: 1.8;
  resize: vertical;
}

.composer-input:focus {
  outline: none;
}

.composer-bottom {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-end;
  margin-top: 12px;
}

.composer-toolbar {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.toolbar-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 7px 11px;
  background: #f6f8fb;
  color: #586174;
  font-size: 12px;
}

.skill-trigger,
.selected-skill-chip {
  border: 1px solid rgba(206, 213, 224, 0.98);
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 11px;
  cursor: pointer;
}

.skill-trigger {
  background: #ffffff;
  color: #1f2328;
}

.skill-trigger-active {
  border-color: #1f2328;
}

.skill-trigger-icon {
  font-size: 15px;
  line-height: 1;
}

.skill-trigger strong,
.selected-skill-chip span {
  font-size: 11px;
  line-height: 1;
}

.selected-skill-chip {
  background: #f8fafd;
  color: #314155;
}

.skill-picker-panel {
  position: absolute;
  left: 0;
  bottom: calc(100% + 12px);
  width: min(760px, 78vw);
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid rgba(213, 220, 231, 0.98);
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 20px 56px rgba(15, 23, 42, 0.12);
  z-index: 10;
}

.skill-picker-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.skill-picker-header p {
  margin: 0;
  color: #7a8390;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.skill-picker-header strong {
  display: block;
  margin-top: 4px;
  color: #1f2328;
  font-size: 18px;
}

.skill-picker-close {
  border: 1px solid rgba(210, 217, 228, 0.98);
  border-radius: 999px;
  padding: 7px 10px;
  background: #ffffff;
  color: #1f2328;
  cursor: pointer;
}

.skill-search input {
  width: 100%;
  border: 1px solid rgba(210, 217, 228, 0.98);
  border-radius: 14px;
  padding: 10px 12px;
  background: #ffffff;
  color: #1f2328;
}

.skill-picker-sections {
  display: grid;
  gap: 12px;
  max-height: 420px;
  overflow: auto;
}

.skill-section {
  display: grid;
  gap: 10px;
}

.skill-section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.skill-section-head strong {
  color: #1f2328;
}

.skill-section-head p {
  margin: 4px 0 0;
  color: #637083;
  font-size: 12px;
}

.skill-section-head span {
  border-radius: 999px;
  padding: 4px 9px;
  background: #eef3ff;
  color: #4055c2;
  font-size: 11px;
}

.skill-option-list {
  display: grid;
  gap: 8px;
}

.skill-option {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  width: 100%;
  border: 1px solid rgba(213, 220, 231, 0.96);
  border-radius: 16px;
  padding: 12px;
  background: #ffffff;
  cursor: pointer;
  text-align: left;
}

.skill-option-selected {
  border-color: #cfe0fa;
  background: #f8fbff;
  box-shadow: none;
}

.skill-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  height: 32px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
}

.skill-badge-amber {
  background: #e8f0fe;
  color: #1d4ed8;
}

.skill-badge-blue {
  background: #eaf1ff;
  color: #3751ad;
}

.skill-badge-green {
  background: #e9f9ee;
  color: #1f7a41;
}

.skill-badge-plum {
  background: #f4ebff;
  color: #7445b5;
}

.skill-option-copy {
  min-width: 0;
}

.skill-option-title {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}

.skill-option-title strong {
  color: #1f2328;
  font-size: 14px;
}

.skill-option-title span {
  color: #6d7786;
  font-size: 12px;
}

.skill-option-copy p {
  margin: 6px 0 0;
  color: #596474;
  font-size: 12px;
  line-height: 1.65;
}

.skill-scene-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.skill-scene-row span {
  border-radius: 999px;
  padding: 4px 8px;
  background: #f6f8fb;
  color: #657184;
  font-size: 11px;
}

.skill-option em {
  color: #526075;
  font-style: normal;
  font-size: 12px;
}

.skill-empty {
  margin: 0;
  border-radius: 14px;
  padding: 16px;
  background: #f6f8fb;
  color: #667386;
  text-align: center;
}

.submit-button {
  border: 0;
  border-radius: 999px;
  padding: 11px 16px;
  background: #1d4ed8;
  color: #ffffff;
  font-weight: 700;
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
}

.submit-button:disabled {
  opacity: 0.6;
  cursor: wait;
}

.error {
  margin: 0;
  color: #cf222e;
  font-size: 12px;
}

@media (max-width: 1080px) {
  .composer-bottom {
    flex-direction: column;
    align-items: stretch;
  }

  .submit-button {
    width: 100%;
  }

  .skill-picker-panel {
    position: fixed;
    left: 12px;
    right: 12px;
    bottom: 12px;
    width: auto;
  }
}
</style>
