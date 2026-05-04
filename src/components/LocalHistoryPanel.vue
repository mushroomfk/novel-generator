<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  createProjectSnapshot,
  getProjectDetail,
  getProjectSnapshotDetail,
  restoreProjectSnapshot,
} from '../lib/api.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  open: {
    type: Boolean,
    default: false,
  },
  selectedChapterId: {
    type: String,
    default: '',
  },
});

const emit = defineEmits(['project-detail-updated', 'close']);

const versionMessage = ref('');
const actionError = ref('');
const isSavingVersion = ref(false);
const restoringSnapshotId = ref('');
const selectedSnapshotId = ref('');
const selectedPreviewChapterId = ref('');
const selectedFilter = ref('all');
const previewMode = ref('snapshot');
const compareFilter = ref('all');
const snapshotDetail = ref(null);
const isLoadingDetail = ref(false);
const isRefreshingProject = ref(false);
const detailError = ref('');

const selectedChapterSummary = computed(() => (
  props.project?.chapters?.find((chapter) => chapter.id === props.selectedChapterId) ?? null
));

const workingTree = computed(() => (
  props.project?.local_history?.working_tree
  ?? {
    clean: true,
    changed_count: 0,
    changed_files: [],
    base_snapshot_version: null,
    base_snapshot_id: null,
    base_snapshot_message: null,
    base_snapshot_created_at: null,
  }
));

const snapshots = computed(() => props.project?.local_history?.snapshots ?? []);
const latestSnapshot = computed(() => snapshots.value[0] ?? null);
const currentBaseSnapshot = computed(() => (
  snapshots.value.find((item) => item.id === workingTree.value.base_snapshot_id) ?? null
));

const workingTreeSummary = computed(() => (
  workingTree.value.clean
    ? '当前没有未保存改动'
    : `当前有 ${workingTree.value.changed_count} 个未保存改动`
));

const filterOptions = computed(() => ([
  { id: 'all', label: '全部' },
  { id: 'manual', label: '关键版本' },
  { id: 'auto', label: '自动保存' },
  ...(props.selectedChapterId ? [{
    id: 'chapter',
    label: selectedChapterSummary.value?.title ?? '当前章节',
  }] : []),
]));

const filteredSnapshots = computed(() => (
  snapshots.value.filter((snapshot) => {
    if (selectedFilter.value === 'auto') {
      return snapshot.kind === 'auto';
    }

    if (selectedFilter.value === 'manual') {
      return snapshot.kind !== 'auto';
    }

    if (selectedFilter.value === 'chapter') {
      return snapshot.affected_chapters?.some((chapter) => chapter.id === props.selectedChapterId);
    }

    return true;
  })
));

const selectedSnapshot = computed(() => (
  filteredSnapshots.value.find((snapshot) => snapshot.id === selectedSnapshotId.value)
  ?? filteredSnapshots.value[0]
  ?? null
));

const previewChapters = computed(() => snapshotDetail.value?.preview_chapters ?? []);
const activePreviewChapter = computed(() => (
  previewChapters.value.find((chapter) => chapter.id === selectedPreviewChapterId.value)
  ?? previewChapters.value[0]
  ?? null
));

const currentWorkingChapter = computed(() => (
  props.project?.chapters?.find((chapter) => chapter.id === activePreviewChapter.value?.id) ?? null
));

const currentWorkingContent = computed(() => (
  currentWorkingChapter.value?.content?.trim()
  || currentWorkingChapter.value?.preview?.trim()
  || ''
));

const snapshotPreviewContent = computed(() => (
  activePreviewChapter.value?.content?.trim()
  || activePreviewChapter.value?.preview?.trim()
  || ''
));

const selectedSnapshotChangedFiles = computed(() => snapshotDetail.value?.changed_files ?? []);
const canComparePreview = computed(() => Boolean(activePreviewChapter.value && (snapshotPreviewContent.value || currentWorkingContent.value)));

function buildLcsTable(leftList, rightList) {
  const table = Array.from(
    { length: leftList.length + 1 },
    () => Array.from({ length: rightList.length + 1 }, () => 0),
  );

  for (let leftIndex = leftList.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = rightList.length - 1; rightIndex >= 0; rightIndex -= 1) {
      if (leftList[leftIndex] === rightList[rightIndex]) {
        table[leftIndex][rightIndex] = table[leftIndex + 1][rightIndex + 1] + 1;
      } else {
        table[leftIndex][rightIndex] = Math.max(
          table[leftIndex + 1][rightIndex],
          table[leftIndex][rightIndex + 1],
        );
      }
    }
  }

  return table;
}

function splitParagraphs(content) {
  const trimmed = content.trim();
  if (!trimmed) {
    return [];
  }

  return trimmed
    .split(/\n\s*\n/g)
    .map((block) => block.trim())
    .filter(Boolean);
}

function splitSentences(text) {
  const normalized = text.trim();
  if (!normalized) {
    return [];
  }

  const matches = normalized.match(/[^。！？!?；;\n]+[。！？!?；;]?|\n+/g);
  return (matches ?? [normalized])
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildInlineSegments(leftText, rightText) {
  const leftTokens = splitSentences(leftText);
  const rightTokens = splitSentences(rightText);
  const table = buildLcsTable(leftTokens, rightTokens);
  const leftSegments = [];
  const rightSegments = [];

  let leftIndex = 0;
  let rightIndex = 0;

  while (leftIndex < leftTokens.length && rightIndex < rightTokens.length) {
    if (leftTokens[leftIndex] === rightTokens[rightIndex]) {
      leftSegments.push({ kind: 'same', text: leftTokens[leftIndex] });
      rightSegments.push({ kind: 'same', text: rightTokens[rightIndex] });
      leftIndex += 1;
      rightIndex += 1;
      continue;
    }

    if (table[leftIndex + 1][rightIndex] >= table[leftIndex][rightIndex + 1]) {
      leftSegments.push({ kind: 'removed', text: leftTokens[leftIndex] });
      leftIndex += 1;
    } else {
      rightSegments.push({ kind: 'added', text: rightTokens[rightIndex] });
      rightIndex += 1;
    }
  }

  while (leftIndex < leftTokens.length) {
    leftSegments.push({ kind: 'removed', text: leftTokens[leftIndex] });
    leftIndex += 1;
  }

  while (rightIndex < rightTokens.length) {
    rightSegments.push({ kind: 'added', text: rightTokens[rightIndex] });
    rightIndex += 1;
  }

  if (leftSegments.length === 0 && leftText) {
    leftSegments.push({ kind: 'removed', text: leftText });
  }

  if (rightSegments.length === 0 && rightText) {
    rightSegments.push({ kind: 'added', text: rightText });
  }

  return { leftSegments, rightSegments };
}

function buildCompareRows(leftContent, rightContent) {
  const leftBlocks = splitParagraphs(leftContent);
  const rightBlocks = splitParagraphs(rightContent);
  const table = buildLcsTable(leftBlocks, rightBlocks);
  const rows = [];

  let leftIndex = 0;
  let rightIndex = 0;
  let rowId = 0;

  while (leftIndex < leftBlocks.length && rightIndex < rightBlocks.length) {
    if (leftBlocks[leftIndex] === rightBlocks[rightIndex]) {
      rows.push({
        id: `same-${rowId += 1}`,
        status: 'same',
        snapshotSegments: [{ kind: 'same', text: leftBlocks[leftIndex] }],
        currentSegments: [{ kind: 'same', text: rightBlocks[rightIndex] }],
      });
      leftIndex += 1;
      rightIndex += 1;
      continue;
    }

    if (table[leftIndex + 1][rightIndex] === table[leftIndex][rightIndex + 1]) {
      const inline = buildInlineSegments(leftBlocks[leftIndex], rightBlocks[rightIndex]);
      rows.push({
        id: `changed-${rowId += 1}`,
        status: 'changed',
        snapshotSegments: inline.leftSegments,
        currentSegments: inline.rightSegments,
      });
      leftIndex += 1;
      rightIndex += 1;
      continue;
    }

    if (table[leftIndex + 1][rightIndex] > table[leftIndex][rightIndex + 1]) {
      rows.push({
        id: `removed-${rowId += 1}`,
        status: 'removed',
        snapshotSegments: [{ kind: 'removed', text: leftBlocks[leftIndex] }],
        currentSegments: [],
      });
      leftIndex += 1;
      continue;
    }

    rows.push({
      id: `added-${rowId += 1}`,
      status: 'added',
      snapshotSegments: [],
      currentSegments: [{ kind: 'added', text: rightBlocks[rightIndex] }],
    });
    rightIndex += 1;
  }

  while (leftIndex < leftBlocks.length) {
    rows.push({
      id: `removed-${rowId += 1}`,
      status: 'removed',
      snapshotSegments: [{ kind: 'removed', text: leftBlocks[leftIndex] }],
      currentSegments: [],
    });
    leftIndex += 1;
  }

  while (rightIndex < rightBlocks.length) {
    rows.push({
      id: `added-${rowId += 1}`,
      status: 'added',
      snapshotSegments: [],
      currentSegments: [{ kind: 'added', text: rightBlocks[rightIndex] }],
    });
    rightIndex += 1;
  }

  return rows;
}

const compareRows = computed(() => (
  buildCompareRows(snapshotPreviewContent.value, currentWorkingContent.value)
));

const compareSummary = computed(() => ({
  snapshotLength: snapshotPreviewContent.value.length,
  currentLength: currentWorkingContent.value.length,
  identical: snapshotPreviewContent.value === currentWorkingContent.value,
  addedRows: compareRows.value.filter((row) => row.status === 'added').length,
  removedRows: compareRows.value.filter((row) => row.status === 'removed').length,
  changedRows: compareRows.value.filter((row) => row.status === 'changed').length,
}));

const compareFilterOptions = computed(() => ([
  { id: 'diff', label: '只看变化', count: compareRows.value.filter((row) => row.status !== 'same').length },
  { id: 'all', label: '查看全部', count: compareRows.value.length },
]));

const visibleCompareRows = computed(() => {
  if (compareFilter.value === 'diff') {
    return compareRows.value.filter((row) => row.status !== 'same');
  }

  return compareRows.value;
});

watch(
  () => [props.project?.id, props.open],
  () => {
    versionMessage.value = '';
    actionError.value = '';
    detailError.value = '';
    selectedFilter.value = 'all';
    previewMode.value = 'snapshot';
    compareFilter.value = 'all';
    selectedSnapshotId.value = '';
    selectedPreviewChapterId.value = '';
    snapshotDetail.value = null;
    isSavingVersion.value = false;
    restoringSnapshotId.value = '';
  },
  { immediate: true },
);

async function refreshProjectState(preferredSnapshotId = '') {
  if (!props.project?.id) {
    return;
  }

  isRefreshingProject.value = true;
  try {
    const detail = await getProjectDetail(props.project.id);
    emit('project-detail-updated', detail);
    const nextSnapshots = detail.local_history?.snapshots ?? [];
    const canKeepCurrent = nextSnapshots.some((snapshot) => snapshot.id === preferredSnapshotId);
    selectedSnapshotId.value = canKeepCurrent ? preferredSnapshotId : nextSnapshots[0]?.id ?? '';
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '版本状态刷新失败';
  } finally {
    isRefreshingProject.value = false;
  }
}

watch(
  () => props.open,
  async (open) => {
    if (typeof document !== 'undefined') {
      document.body.style.overflow = open ? 'hidden' : '';
    }

    if (open) {
      await refreshProjectState(selectedSnapshotId.value);
    }
  },
  { immediate: true },
);

watch(
  filteredSnapshots,
  (nextSnapshots) => {
    if (nextSnapshots.length === 0) {
      selectedSnapshotId.value = '';
      snapshotDetail.value = null;
      return;
    }

    const stillVisible = nextSnapshots.some((snapshot) => snapshot.id === selectedSnapshotId.value);
    if (!stillVisible) {
      selectedSnapshotId.value = nextSnapshots[0].id;
    }
  },
  { immediate: true },
);

watch(
  [() => props.open, selectedSnapshotId],
  async ([open, snapshotId]) => {
    if (!open || !props.project?.id || !snapshotId) {
      snapshotDetail.value = null;
      return;
    }

    isLoadingDetail.value = true;
    detailError.value = '';
    try {
      snapshotDetail.value = await getProjectSnapshotDetail(props.project.id, snapshotId);
    } catch (error) {
      snapshotDetail.value = null;
      detailError.value = error instanceof Error ? error.message : '版本详情读取失败';
    } finally {
      isLoadingDetail.value = false;
    }
  },
  { immediate: true },
);

watch(
  [previewChapters, () => props.selectedChapterId],
  ([chapters, selectedChapterId]) => {
    if (chapters.length === 0) {
      selectedPreviewChapterId.value = '';
      return;
    }

    const preferred = chapters.find((chapter) => chapter.id === selectedChapterId);
    selectedPreviewChapterId.value = preferred?.id ?? chapters[0].id;
  },
  { immediate: true },
);

watch(
  activePreviewChapter,
  () => {
    if (typeof window !== 'undefined') {
      const searchParams = new URLSearchParams(window.location.search);
      previewMode.value = searchParams.get('compare') === 'open' ? 'compare' : 'snapshot';
    } else {
      previewMode.value = 'snapshot';
    }
  },
);

watch(
  [previewMode, compareRows],
  ([mode, rows]) => {
    if (mode === 'compare') {
      compareFilter.value = rows.some((row) => row.status !== 'same') ? 'diff' : 'all';
      return;
    }

    compareFilter.value = 'all';
  },
  { immediate: true },
);

function closeDialog() {
  emit('close');
}

function handleKeydown(event) {
  if (event.key === 'Escape' && props.open) {
    closeDialog();
  }
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('keydown', handleKeydown);
  }
});

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleKeydown);
  }
  if (typeof document !== 'undefined') {
    document.body.style.overflow = '';
  }
});

function formatChangedFileStatus(status) {
  if (status === 'added') {
    return '新增';
  }

  if (status === 'deleted') {
    return '删除';
  }

  return '修改';
}

function formatSnapshotTime(value) {
  return new Date(value).toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function versionTitle(snapshot) {
  return `v${snapshot.version}`;
}

function formatSnapshotKind(kind) {
  if (kind === 'auto') {
    return '自动保存';
  }

  if (kind === 'restore') {
    return '回退生成';
  }

  if (kind === 'system') {
    return '初始化';
  }

  return '手动保存';
}

function summarizeAffectedChapters(snapshot) {
  const chapters = snapshot.affected_chapters ?? [];
  if (chapters.length === 0) {
    return '全局资料或设定文件';
  }

  if (chapters.length === 1) {
    return chapters[0].title;
  }

  return `${chapters[0].title} 等 ${chapters.length} 章`;
}

function snapshotMatchesCurrentChapter(snapshot) {
  return snapshot.affected_chapters?.some((chapter) => chapter.id === props.selectedChapterId);
}

async function handleCreateSnapshot() {
  if (!props.project || isSavingVersion.value) {
    return;
  }

  isSavingVersion.value = true;
  actionError.value = '';

  try {
    const detail = await createProjectSnapshot(props.project.id, {
      message: versionMessage.value.trim() || undefined,
    });
    versionMessage.value = '';
    selectedSnapshotId.value = detail.local_history?.snapshots?.[0]?.id ?? '';
    emit('project-detail-updated', detail);
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '版本保存失败';
  } finally {
    isSavingVersion.value = false;
  }
}

async function handleRestoreSnapshot(snapshot, chapterId = null) {
  if (!props.project || restoringSnapshotId.value) {
    return;
  }

  const restoreTarget = chapterId
    ? `只恢复 ${activePreviewChapter.value?.title ?? '当前章节'}`
    : `整本回退到 ${versionTitle(snapshot)}`;
  const confirmed = window.confirm(
    `${restoreTarget}。\n当前未保存改动会先自动存成新版本，是否继续？`,
  );
  if (!confirmed) {
    return;
  }

  restoringSnapshotId.value = `${snapshot.id}:${chapterId ?? 'all'}`;
  actionError.value = '';

  try {
    const detail = await restoreProjectSnapshot(props.project.id, snapshot.id, chapterId ? { chapter_id: chapterId } : {});
    selectedSnapshotId.value = detail.local_history?.snapshots?.[0]?.id ?? '';
    emit('project-detail-updated', detail);
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '版本回退失败';
  } finally {
    restoringSnapshotId.value = '';
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-overlay"
      data-testid="history-modal"
      @click.self="closeDialog"
    >
      <section
        class="history-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="版本管理"
      >
        <header class="history-header">
          <div class="history-heading">
            <p class="eyebrow">版本管理</p>
            <h3>{{ project?.name ?? '当前小说' }}</h3>
            <p class="history-subtitle">左边选版本，右边直接看这一版改了什么。</p>
          </div>

          <div class="history-header-actions">
            <span class="top-chip">{{ snapshots.length }} 个版本</span>
            <button
              :disabled="isRefreshingProject"
              class="filter-chip"
              type="button"
              @click="refreshProjectState(selectedSnapshotId)"
            >
              {{ isRefreshingProject ? '刷新中…' : '刷新状态' }}
            </button>
            <button
              class="modal-close"
              type="button"
              @click="closeDialog"
            >
              关闭
            </button>
          </div>
        </header>

        <section class="history-toolbar">
          <div class="history-status-row">
            <span :class="['top-chip', { 'top-chip-dirty': !workingTree.clean }]">{{ workingTreeSummary }}</span>
            <span
              v-if="latestSnapshot"
              class="top-chip"
            >
              最新 {{ versionTitle(latestSnapshot) }}
            </span>
            <span
              v-if="selectedChapterSummary"
              class="top-chip"
            >
              当前章节 {{ selectedChapterSummary.title }}
            </span>
          </div>

          <div class="history-save-row">
            <input
              v-model="versionMessage"
              :disabled="isSavingVersion"
              class="save-input"
              data-testid="history-save-input"
              placeholder="给当前写作状态起个版本名"
            />
            <button
              :disabled="workingTree.clean || isSavingVersion"
              class="save-button"
              data-testid="history-save-button"
              type="button"
              @click="handleCreateSnapshot"
            >
              {{ isSavingVersion ? '保存中…' : '保存当前版本' }}
            </button>
          </div>
        </section>

        <p
          v-if="actionError"
          class="error-copy"
        >
          {{ actionError }}
        </p>

        <div class="history-layout">
          <aside class="history-sidebar">
            <div class="sidebar-header">
              <h4>版本列表</h4>
              <span class="top-chip">{{ filteredSnapshots.length }}</span>
            </div>

            <div class="filter-row">
              <button
                v-for="item in filterOptions"
                :key="item.id"
                :class="['filter-chip', { 'filter-chip-active': selectedFilter === item.id }]"
                type="button"
                @click="selectedFilter = item.id"
              >
                {{ item.label }}
              </button>
            </div>

            <div
              v-if="filteredSnapshots.length > 0"
              class="snapshot-list"
            >
              <button
                v-for="snapshot in filteredSnapshots"
                :key="snapshot.id"
                :class="[
                  'snapshot-row',
                  {
                    'snapshot-row-active': selectedSnapshot?.id === snapshot.id,
                  },
                ]"
                type="button"
                @click="selectedSnapshotId = snapshot.id"
              >
                <div class="snapshot-row-top">
                  <strong>{{ versionTitle(snapshot) }}</strong>
                  <span class="snapshot-time">{{ formatSnapshotTime(snapshot.created_at) }}</span>
                </div>

                <p class="snapshot-label-line">
                  <span class="kind-chip">{{ formatSnapshotKind(snapshot.kind) }}</span>
                  <span
                    v-if="snapshotMatchesCurrentChapter(snapshot)"
                    class="kind-chip kind-chip-current"
                  >
                    当前章节
                  </span>
                </p>

                <p class="snapshot-message">{{ snapshot.message }}</p>
              </button>
            </div>

            <p
              v-else
              class="empty-note"
            >
              当前筛选条件下还没有版本。
            </p>
          </aside>

          <section class="history-detail">
            <div
              v-if="isLoadingDetail"
              class="empty-state"
            >
              正在读取这个版本的详情…
            </div>

            <div
              v-else-if="detailError"
              class="error-copy"
            >
              {{ detailError }}
            </div>

            <div
              v-else-if="snapshotDetail && selectedSnapshot"
              class="detail-shell"
            >
              <header class="detail-header">
                <div class="detail-heading">
                  <div class="detail-title-row">
                    <strong>{{ versionTitle(selectedSnapshot) }}</strong>
                    <span class="kind-chip">{{ formatSnapshotKind(selectedSnapshot.kind) }}</span>
                  </div>
                  <p class="detail-message">{{ selectedSnapshot.message }}</p>
                  <p class="detail-meta">{{ formatSnapshotTime(selectedSnapshot.created_at) }} · {{ summarizeAffectedChapters(selectedSnapshot) }}</p>
                </div>

                <div class="detail-actions">
                  <button
                    :disabled="restoringSnapshotId.length > 0"
                    class="restore-button"
                    data-testid="history-restore-all-button"
                    type="button"
                    @click="handleRestoreSnapshot(selectedSnapshot)"
                  >
                    {{ restoringSnapshotId === `${selectedSnapshot.id}:all` ? '恢复中…' : '恢复整本' }}
                  </button>
                  <button
                    v-if="activePreviewChapter"
                    :disabled="restoringSnapshotId.length > 0"
                    class="restore-button"
                    type="button"
                    @click="handleRestoreSnapshot(selectedSnapshot, activePreviewChapter.id)"
                  >
                    {{ restoringSnapshotId === `${selectedSnapshot.id}:${activePreviewChapter.id}` ? '恢复中…' : '只恢复这一章' }}
                  </button>
                </div>
              </header>

              <div class="detail-summary-grid">
                <section class="summary-box">
                  <div class="summary-box-head">
                    <h4>这版影响的章节</h4>
                    <span class="top-chip">{{ selectedSnapshot.affected_chapters.length }}</span>
                  </div>

                  <div
                    v-if="selectedSnapshot.affected_chapters.length > 0"
                    class="chapter-chip-list"
                  >
                    <button
                      v-for="chapter in selectedSnapshot.affected_chapters"
                      :key="chapter.id"
                      :class="['chapter-chip', { 'chapter-chip-active': selectedPreviewChapterId === chapter.id }]"
                      type="button"
                      @click="selectedPreviewChapterId = chapter.id"
                    >
                      {{ chapter.title }}
                    </button>
                  </div>

                  <p
                    v-else
                    class="empty-note"
                  >
                    这版主要改的是全局资料或设定文件。
                  </p>
                </section>

                <section class="summary-box">
                  <div class="summary-box-head">
                    <h4>这版改动的文件</h4>
                    <span class="top-chip">{{ selectedSnapshotChangedFiles.length }}</span>
                  </div>

                  <div
                    v-if="selectedSnapshotChangedFiles.length > 0"
                    class="file-list"
                  >
                    <article
                      v-for="item in selectedSnapshotChangedFiles.slice(0, 6)"
                      :key="`${item.status}-${item.path}`"
                      class="file-row"
                    >
                      <span>{{ item.path }}</span>
                      <strong>{{ formatChangedFileStatus(item.status) }}</strong>
                    </article>
                  </div>

                  <p
                    v-else
                    class="empty-note"
                  >
                    当前版本没有记录到文件变动。
                  </p>
                </section>
              </div>

              <section class="preview-panel">
                <div class="preview-panel-head">
                  <div class="preview-panel-title">
                    <h4>{{ activePreviewChapter ? activePreviewChapter.title : '正文预览' }}</h4>
                  </div>

                  <div class="preview-mode-row">
                    <button
                      :class="['preview-mode-chip', { 'preview-mode-chip-active': previewMode === 'snapshot' }]"
                      type="button"
                      @click="previewMode = 'snapshot'"
                    >
                      版本正文
                    </button>
                    <button
                      :disabled="!canComparePreview"
                      :class="['preview-mode-chip', { 'preview-mode-chip-active': previewMode === 'compare' }]"
                      type="button"
                      @click="previewMode = 'compare'"
                    >
                      与当前对比
                    </button>
                  </div>
                </div>

                <div
                  v-if="activePreviewChapter"
                  class="preview-body"
                >
                  <template v-if="previewMode === 'snapshot'">
                    <div
                      v-if="snapshotPreviewContent"
                      class="preview-text"
                    >
                      {{ snapshotPreviewContent }}
                    </div>
                    <p v-else class="empty-note">这个版本里，这一章还没有正文内容。</p>
                  </template>

                  <template v-else>
                    <p class="compare-summary-copy">
                      版本正文 {{ compareSummary.snapshotLength }} 字 · 当前正文 {{ compareSummary.currentLength }} 字
                      <template v-if="compareSummary.identical">
                        · 两边内容一致
                      </template>
                      <template v-else>
                        · 有 {{ compareSummary.addedRows + compareSummary.removedRows + compareSummary.changedRows }} 处变化
                      </template>
                    </p>

                    <div class="compare-filter-row">
                      <button
                        v-for="item in compareFilterOptions"
                        :key="item.id"
                        :class="['compare-filter-chip', { 'compare-filter-chip-active': compareFilter === item.id }]"
                        type="button"
                        @click="compareFilter = item.id"
                      >
                        {{ item.label }}<span>{{ item.count }}</span>
                      </button>
                    </div>

                    <div
                      v-if="visibleCompareRows.length > 0"
                      class="compare-split"
                    >
                      <section class="compare-pane">
                        <header class="compare-pane-head">
                          <strong>版本正文</strong>
                        </header>

                        <div class="compare-pane-body">
                          <article
                            v-for="row in visibleCompareRows"
                            :key="`${row.id}-snapshot`"
                            :class="['compare-paragraph', `compare-paragraph-${row.status}`]"
                          >
                            <div
                              v-if="row.snapshotSegments.length > 0"
                              class="diff-rich-text"
                            >
                              <span
                                v-for="(segment, segmentIndex) in row.snapshotSegments"
                                :key="`${row.id}-snapshot-${segmentIndex}`"
                                :class="['diff-segment', `diff-segment-${segment.kind}`]"
                              >
                                {{ segment.text }}
                              </span>
                            </div>
                            <p v-else class="compare-empty-copy">这一段为空。</p>
                          </article>
                        </div>
                      </section>

                      <section class="compare-pane">
                        <header class="compare-pane-head">
                          <strong>当前正文</strong>
                        </header>

                        <div class="compare-pane-body">
                          <article
                            v-for="row in visibleCompareRows"
                            :key="`${row.id}-current`"
                            :class="['compare-paragraph', `compare-paragraph-${row.status}`]"
                          >
                            <div
                              v-if="row.currentSegments.length > 0"
                              class="diff-rich-text"
                            >
                              <span
                                v-for="(segment, segmentIndex) in row.currentSegments"
                                :key="`${row.id}-current-${segmentIndex}`"
                                :class="['diff-segment', `diff-segment-${segment.kind}`]"
                              >
                                {{ segment.text }}
                              </span>
                            </div>
                            <p v-else class="compare-empty-copy">这一段为空。</p>
                          </article>
                        </div>
                      </section>
                    </div>

                    <p v-else class="empty-note">当前筛选条件下没有匹配的差异内容。</p>
                  </template>
                </div>

                <p
                  v-else
                  class="empty-note"
                >
                  当前版本没有可直接预览的章节正文。
                </p>
              </section>
            </div>

            <div
              v-else
              class="empty-state"
            >
              先从左侧选择一个版本，再看这版改了什么。
            </div>
          </section>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: stretch;
  justify-content: flex-end;
  padding: 20px 24px;
  background: rgba(248, 250, 252, 0.62);
  backdrop-filter: blur(3px);
}

.history-dialog {
  width: min(1120px, calc(100vw - 72px));
  height: calc(100vh - 40px);
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 28px;
  padding: 18px;
  background: #ffffff;
  box-shadow: 0 22px 70px rgba(15, 23, 42, 0.16);
}

.history-header,
.history-toolbar,
.history-header-actions,
.history-status-row,
.history-save-row,
.sidebar-header,
.detail-header,
.detail-actions,
.summary-box-head,
.preview-panel-head,
.preview-mode-row,
.compare-filter-row {
  display: flex;
  gap: 12px;
}

.history-header,
.history-toolbar,
.sidebar-header,
.detail-header,
.summary-box-head,
.preview-panel-head {
  justify-content: space-between;
  align-items: flex-start;
}

.history-heading {
  min-width: 0;
}

.eyebrow {
  margin: 0 0 4px;
  color: #6e7781;
  font-size: 9px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h3,
h4 {
  margin: 0;
  color: #1f2328;
}

h3 {
  font-size: 21px;
  line-height: 1.12;
}

.history-subtitle,
.snapshot-message,
.snapshot-summary,
.detail-message,
.detail-meta,
.empty-note,
.empty-state,
.error-copy {
  margin: 6px 0 0;
  color: #57606a;
  font-size: 11px;
  line-height: 1.55;
}

.history-toolbar {
  align-items: center;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid #dde4eb;
  border-radius: 16px;
  background: #f8fbff;
}

.history-status-row,
.history-save-row,
.filter-row,
.chapter-chip-list,
.compare-summary-row,
.compare-filter-row {
  flex-wrap: wrap;
  align-items: center;
}

.history-status-row {
  gap: 8px;
}

.history-save-row {
  gap: 10px;
}

.top-chip,
.kind-chip,
.compare-filter-chip span {
  border-radius: 999px;
  padding: 3px 8px;
  background: #f6f8fa;
  color: #57606a;
  font-size: 10px;
  white-space: nowrap;
}

.top-chip-dirty {
  background: #eef4ff;
  color: #1d4ed8;
}

.save-input {
  width: 260px;
  border: 1px solid #d0d7de;
  border-radius: 999px;
  padding: 7px 12px;
  background: #ffffff;
  color: #1f2328;
  font-size: 12px;
}

.modal-close,
.save-button,
.filter-chip,
.chapter-chip,
.preview-mode-chip,
.compare-filter-chip,
.restore-button {
  border: 1px solid #d0d7de;
  border-radius: 999px;
  padding: 7px 11px;
  background: #ffffff;
  color: #24292f;
  cursor: pointer;
  font-size: 11px;
}

.modal-close:hover,
.filter-chip:hover,
.chapter-chip:hover,
.preview-mode-chip:hover:not(:disabled),
.compare-filter-chip:hover:not(:disabled),
.restore-button:hover:not(:disabled) {
  background: #f6f8fa;
}

.save-button {
  border-color: #1d4ed8;
  background: #1d4ed8;
  color: #ffffff;
}

.save-button:disabled,
.preview-mode-chip:disabled,
.compare-filter-chip:disabled,
.restore-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.filter-chip-active,
.chapter-chip-active,
.preview-mode-chip-active,
.compare-filter-chip-active {
  border-color: #cfe0fa;
  background: #e8f0fe;
  color: #1d4ed8;
}

.kind-chip-current {
  background: #eef3f8;
  color: #1f2328;
}

.history-layout {
  display: grid;
  grid-template-columns: 288px minmax(0, 1fr);
  gap: 10px;
  margin-top: 10px;
  min-height: 0;
}

.history-sidebar,
.history-detail {
  min-width: 0;
  min-height: 0;
}

.history-sidebar {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 8px;
}

.snapshot-list,
.detail-shell {
  display: grid;
  gap: 8px;
}

.snapshot-list {
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.snapshot-row,
.summary-box,
.preview-panel,
.file-row,
.empty-state {
  border: 1px solid #dde4eb;
  border-radius: 16px;
  background: #ffffff;
}

.snapshot-row,
.summary-box,
.preview-panel,
.empty-state {
  padding: 10px 11px;
}

.snapshot-row {
  text-align: left;
  display: grid;
  gap: 5px;
}

.snapshot-row-active {
  border-color: #cfe0fa;
  background: #f8fbff;
  box-shadow: none;
}

.snapshot-row-top,
.snapshot-label-line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.snapshot-row-top strong,
.detail-title-row strong {
  color: #1f2328;
  font-size: 14px;
}

.snapshot-time {
  color: #6e7781;
  font-size: 10px;
  white-space: nowrap;
}

.snapshot-label-line {
  justify-content: flex-start;
  margin-top: 0;
  gap: 6px;
}

.snapshot-message {
  margin: 0;
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
  font-size: 11px;
  line-height: 1.35;
}

.detail-heading {
  min-width: 0;
}

.detail-title-row {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.detail-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.history-detail {
  display: grid;
  min-height: 0;
}

.detail-shell {
  grid-template-rows: auto auto minmax(0, 1fr);
  min-height: 0;
}

.file-list {
  display: grid;
  gap: 6px;
}

.file-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
}

.file-row span {
  min-width: 0;
  color: #3d4852;
  font-size: 11px;
  line-height: 1.5;
  word-break: break-all;
}

.file-row strong {
  color: #57606a;
  font-size: 10px;
  white-space: nowrap;
}

.summary-box-head h4,
.preview-panel-head h4,
.sidebar-header h4 {
  font-size: 13px;
  line-height: 1.25;
}

.preview-panel-head {
  align-items: center;
}

.preview-panel-title {
  min-width: 0;
}

.preview-body {
  display: grid;
  gap: 8px;
  min-height: 0;
}

.preview-text {
  min-height: 300px;
  max-height: none;
  overflow: auto;
  border: 1px solid #e7edf2;
  border-radius: 12px;
  padding: 12px;
  background: #fcfdff;
  color: #3d4852;
  font-size: 12px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.compare-summary-copy {
  margin: 0;
  color: #57606a;
  font-size: 11px;
  line-height: 1.45;
}

.compare-split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  min-height: 0;
}

.compare-pane {
  min-width: 0;
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid #e7edf2;
  border-radius: 12px;
  background: #ffffff;
  min-height: 0;
}

.compare-pane-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.compare-pane-head strong {
  color: #6e7781;
  font-size: 9px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 600;
}

.compare-pane-body {
  display: grid;
  gap: 8px;
  min-height: 220px;
  max-height: 280px;
  overflow: auto;
  padding-right: 2px;
}

.compare-paragraph {
  border-radius: 10px;
  padding: 10px;
  background: #fbfcfd;
  border: 1px solid #eef2f6;
}

.compare-paragraph-added {
  background: #fbfffb;
  border-color: #d4e8d4;
}

.compare-paragraph-removed {
  background: #fffafb;
  border-color: #ead5d5;
}

.compare-paragraph-changed {
  background: #fbfcfd;
  border-color: #d8e2ee;
}

.diff-rich-text,
.compare-empty-copy {
  margin: 0;
  color: #3d4852;
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.compare-empty-copy {
  color: #8a94a0;
}

.diff-segment {
  display: inline;
}

.diff-segment-added {
  background: #e9f7ec;
  color: #25683b;
  border-radius: 6px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
  padding: 1px 2px;
}

.diff-segment-removed {
  background: #fdeeee;
  color: #9a3b3b;
  border-radius: 6px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
  padding: 1px 2px;
}

@media (max-width: 1180px) {
  .history-toolbar,
  .history-layout,
  .detail-summary-grid,
  .compare-split {
    grid-template-columns: 1fr;
  }

  .history-toolbar {
    display: grid;
  }

  .history-dialog {
    width: 100%;
    height: calc(100vh - 24px);
    max-height: none;
    overflow: auto;
  }

  .save-input {
    width: 100%;
  }

}
</style>
