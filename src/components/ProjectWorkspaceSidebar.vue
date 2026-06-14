<script setup>
import { computed, ref, watch } from 'vue';
import { updateProjectChapter } from '../lib/api.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  selectedChapterId: {
    type: String,
    default: '',
  },
  agentHidden: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['project-detail-updated', 'show-agent']);

const isEditing = ref(false);
const draftContent = ref('');
const savePending = ref(false);
const saveMessage = ref('');
const saveTone = ref('success');
const backendContentChangedWhileEditing = ref(false);

const selectedChapter = computed(() => (
  props.project?.chapters?.find((chapter) => chapter.id === props.selectedChapterId)
  ?? null
));

const writtenChapterCount = computed(() => (
  props.project?.chapters?.filter((chapter) => chapter.exists).length ?? 0
));

const previewWordCount = computed(() => (
  activePreviewContent.value.replace(/\s+/g, '').length
));

const rawChapterContent = computed(() => (
  String(selectedChapter.value?.content ?? '').replace(/\r\n/g, '\n')
));

function splitChapterContent(rawValue) {
  const raw = String(rawValue ?? '').replace(/\r\n/g, '\n');
  if (!raw) {
    return { heading: '', body: '' };
  }

  const headingMatch = raw.match(/^#\s+[^\n]*(?:\n+|$)/);
  if (!headingMatch) {
    return { heading: '', body: raw.trim() };
  }

  return {
    heading: headingMatch[0],
    body: raw.slice(headingMatch[0].length).trim(),
  };
}

const chapterContentParts = computed(() => splitChapterContent(rawChapterContent.value));

const normalizedPreviewContent = computed(() => chapterContentParts.value.body);

const activePreviewContent = computed(() => (
  isEditing.value ? draftContent.value : normalizedPreviewContent.value
));

const chapterStatusLabel = computed(() => (
  selectedChapter.value?.exists ? '已有正文' : '待写章节'
));

const saveDisabled = computed(() => (
  savePending.value
  || !props.project?.id
  || !selectedChapter.value?.id
  || !isEditing.value
));

function resetEditorState() {
  isEditing.value = false;
  draftContent.value = normalizedPreviewContent.value;
  savePending.value = false;
  saveMessage.value = '';
  saveTone.value = 'success';
  backendContentChangedWhileEditing.value = false;
}

function startEditing() {
  if (!selectedChapter.value) {
    return;
  }

  draftContent.value = normalizedPreviewContent.value;
  isEditing.value = true;
  saveMessage.value = '';
  saveTone.value = 'success';
  backendContentChangedWhileEditing.value = false;
}

function cancelEditing() {
  draftContent.value = normalizedPreviewContent.value;
  isEditing.value = false;
  backendContentChangedWhileEditing.value = false;
  saveMessage.value = '';
}

function normalizeEditorContent(value) {
  return String(value ?? '').replace(/\r\n/g, '\n').trim();
}

function buildChapterContentForSave(value) {
  const body = normalizeEditorContent(value);
  if (!body) {
    return '';
  }

  const heading = chapterContentParts.value.heading.trim();
  if (!heading) {
    return body;
  }

  return `${heading}\n\n${body}`;
}

async function saveChapterEdits() {
  const chapter = selectedChapter.value;
  if (!props.project?.id || !chapter?.id || savePending.value) {
    return;
  }

  const content = buildChapterContentForSave(draftContent.value);
  if (!content.trim()) {
    saveTone.value = 'error';
    saveMessage.value = '正文为空，未同步。';
    return;
  }

  savePending.value = true;
  saveMessage.value = '';
  try {
    const { detail, reviewError, selfEvolutionError } = await updateProjectChapter(
      props.project.id,
      chapter.id,
      { content },
    );
    isEditing.value = false;
    backendContentChangedWhileEditing.value = false;
    emit('project-detail-updated', detail);
    saveTone.value = reviewError ? 'error' : 'success';
    const messages = [reviewError || '正文已同步，后端已刷新资料索引和章节核验。'];
    if (selfEvolutionError) {
      messages.push(`自学习状态刷新失败：${selfEvolutionError}`);
    }
    saveMessage.value = messages.join('；');
  } catch (error) {
    saveTone.value = 'error';
    saveMessage.value = error instanceof Error ? error.message : '正文同步失败';
  } finally {
    savePending.value = false;
  }
}

watch(
  () => selectedChapter.value?.id ?? '',
  () => {
    resetEditorState();
  },
  { immediate: true },
);

watch(
  rawChapterContent,
  (nextContent, previousContent) => {
    if (nextContent === previousContent) {
      return;
    }

    if (isEditing.value) {
      backendContentChangedWhileEditing.value = true;
      return;
    }

    draftContent.value = normalizedPreviewContent.value;
  },
);
</script>

<template>
  <aside class="workspace-sidebar">
    <section
      v-if="selectedChapter"
      class="panel chapter-preview-panel"
      data-testid="chapter-preview-panel"
    >
      <div class="panel-header">
        <div class="panel-header-copy">
          <p class="eyebrow">正文预览</p>
          <h2>{{ selectedChapter.title }}</h2>
        </div>
        <div class="panel-header-actions">
          <button
            v-if="agentHidden"
            class="preview-action-button"
            type="button"
            @click="emit('show-agent')"
          >
            显示 Agent
          </button>
          <span class="chapter-summary">已写 {{ writtenChapterCount }} / {{ project?.target_chapters }} 章</span>
        </div>
      </div>

      <div class="preview-toolbar">
        <div class="preview-meta">
          <span>第 {{ selectedChapter.index }} 章</span>
          <span>{{ chapterStatusLabel }}</span>
          <span>{{ previewWordCount }} 字</span>
        </div>

        <div class="preview-actions">
          <button
            v-if="!isEditing"
            class="preview-action-button"
            type="button"
            @click="startEditing"
          >
            编辑正文
          </button>
          <template v-else>
            <button
              :disabled="savePending"
              class="preview-action-button"
              type="button"
              @click="cancelEditing"
            >
              取消
            </button>
            <button
              :disabled="saveDisabled"
              class="preview-action-button preview-primary-button"
              type="button"
              @click="saveChapterEdits"
            >
              {{ savePending ? '同步中…' : '保存并同步' }}
            </button>
          </template>
        </div>
      </div>

      <article :class="['article-preview', { 'article-preview-editing': isEditing }]">
        <textarea
          v-if="isEditing"
          v-model="draftContent"
          class="article-editor"
          data-testid="chapter-preview-editor"
          spellcheck="false"
        ></textarea>
        <p
          v-else-if="normalizedPreviewContent"
          class="article-preview-content"
        >
          {{ normalizedPreviewContent }}
        </p>
        <p
          v-else
          class="empty-copy"
        >
          这一章还没有正文。生成完成后，这里会自动显示；也可以从左侧章节列表点进来看。
        </p>
      </article>

      <p
        v-if="backendContentChangedWhileEditing"
        class="preview-status preview-status-warning"
      >
        后端正文已更新，保存会用当前编辑内容覆盖这一章。
      </p>
      <p
        v-if="saveMessage"
        :class="[
          'preview-status',
          saveTone === 'error' ? 'preview-status-error' : 'preview-status-success',
        ]"
      >
        {{ saveMessage }}
      </p>
    </section>
  </aside>
</template>

<style scoped>
.workspace-sidebar {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.panel {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  border: 1px solid #d8dee4;
  border-radius: 16px;
  padding: 16px;
  background: #f8fbff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.chapter-preview-panel {
  gap: 14px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.panel-header-actions,
.preview-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.panel-header-copy {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.eyebrow {
  margin: 0;
  color: #667085;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  color: #1f2328;
  font-size: 18px;
  line-height: 1.35;
}

.chapter-summary,
.preview-meta span {
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.84);
  color: #5c6470;
  font-size: 11px;
  white-space: nowrap;
  border: 1px solid rgba(215, 220, 226, 0.9);
}

.preview-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.preview-action-button {
  border: 1px solid #d0d7de;
  border-radius: 999px;
  padding: 6px 10px;
  background: #ffffff;
  color: #344054;
  font-size: 11px;
  line-height: 1.4;
  white-space: nowrap;
  cursor: pointer;
}

.preview-action-button:disabled {
  cursor: wait;
  opacity: 0.62;
}

.preview-primary-button {
  border-color: #1f2430;
  background: #1f2430;
  color: #ffffff;
}

.article-preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border-radius: 14px;
  padding: 18px;
  background: #ffffff;
  border: 1px solid rgba(224, 228, 233, 0.92);
}

.article-preview-editing {
  display: flex;
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}

.article-editor {
  display: block;
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 0;
  resize: none;
  overflow: auto;
  padding: 18px;
  color: #344054;
  font: inherit;
  line-height: 2;
  background: #ffffff;
  outline: none;
}

.article-preview-content,
.empty-copy {
  margin: 0;
  color: #475467;
  font-size: 14px;
  line-height: 2;
  white-space: pre-wrap;
}

.empty-copy {
  color: #7a8491;
}

.preview-status {
  margin: 0;
  border-radius: 12px;
  padding: 9px 11px;
  font-size: 12px;
  line-height: 1.6;
}

.preview-status-success {
  background: #ecfdf3;
  color: #047857;
}

.preview-status-warning {
  background: #fff7ed;
  color: #9a3412;
}

.preview-status-error {
  background: #fef2f2;
  color: #b42318;
}

@media (max-width: 720px) {
  .panel-header,
  .preview-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .panel-header-actions,
  .preview-actions {
    justify-content: flex-start;
  }
}
</style>
