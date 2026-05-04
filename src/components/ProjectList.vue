<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

const props = defineProps({
  projects: {
    type: Array,
    default: () => [],
  },
  selectedProjectId: {
    type: String,
    default: '',
  },
  selectedChapterId: {
    type: String,
    default: '',
  },
  projectDetail: {
    type: Object,
    default: null,
  },
  chapterBrowserProjectId: {
    type: String,
    default: '',
  },
  isProjectLoading: {
    type: Boolean,
    default: false,
  },
  projectActionPendingId: {
    type: String,
    default: '',
  },
  projectDiscussionSummary: {
    type: String,
    default: '',
  },
  discussionThreadState: {
    type: Object,
    default: () => ({
      activeThreadId: '',
      threads: [],
    }),
  },
});

const emit = defineEmits([
  'create-project',
  'select',
  'select-chapter',
  'select-discussion-thread',
  'toggle-chapters',
  'open-project-folder',
  'request-rename-project',
  'request-delete-project',
]);

const activeChapters = computed(() => props.projectDetail?.chapters ?? []);
const activeDiscussionThreads = computed(() => (
  Array.isArray(props.discussionThreadState?.threads)
    ? props.discussionThreadState.threads
    : []
));
const activeDiscussionThreadId = computed(() => String(props.discussionThreadState?.activeThreadId ?? ''));
const menuProjectId = ref('');
const menuVerticalPlacement = ref('down');

function isChapterDrawerOpen(projectId) {
  return props.selectedProjectId === projectId && props.chapterBrowserProjectId === projectId;
}

function resolveMenuPlacement(triggerElement) {
  if (!(triggerElement instanceof HTMLElement)) {
    return 'down';
  }

  const scrollContainer = triggerElement.closest('.project-tree');
  if (!(scrollContainer instanceof HTMLElement)) {
    return 'down';
  }

  const triggerRect = triggerElement.getBoundingClientRect();
  const containerRect = scrollContainer.getBoundingClientRect();
  const estimatedMenuHeight = 136;
  const spaceBelow = containerRect.bottom - triggerRect.bottom;
  const spaceAbove = triggerRect.top - containerRect.top;

  if (spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow) {
    return 'up';
  }

  return 'down';
}

function toggleProjectMenu(projectId, event) {
  if (menuProjectId.value === projectId) {
    menuProjectId.value = '';
    menuVerticalPlacement.value = 'down';
    return;
  }

  menuVerticalPlacement.value = resolveMenuPlacement(event?.currentTarget);
  menuProjectId.value = projectId;
}

function closeProjectMenu() {
  menuProjectId.value = '';
  menuVerticalPlacement.value = 'down';
}

function relativeDiscussionTime() {
  const updatedAt = props.projectDetail?.updated_at;
  return relativeTime(updatedAt);
}

function relativeTime(updatedAt) {
  if (!updatedAt) {
    return '';
  }

  const deltaMs = Date.now() - new Date(updatedAt).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 60_000) {
    return '刚刚';
  }

  const deltaMinutes = Math.floor(deltaMs / 60_000);
  if (deltaMinutes < 60) {
    return `${deltaMinutes} 分钟前`;
  }

  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) {
    return `${deltaHours} 小时前`;
  }

  return `${Math.floor(deltaHours / 24)} 天前`;
}

function handleToggleChapters(projectId) {
  emit('toggle-chapters', projectId);
}

function emitProjectAction(eventName, project) {
  emit(eventName, project);
  closeProjectMenu();
}

function handleWindowPointerDown(event) {
  if (!(event.target instanceof Element)) {
    return;
  }

  if (!event.target.closest('[data-project-menu-root="true"]')) {
    closeProjectMenu();
  }
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('pointerdown', handleWindowPointerDown);
  }
});

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('pointerdown', handleWindowPointerDown);
  }
});
</script>

<template>
  <section class="panel">
    <div class="panel-header">
      <div class="panel-header-copy">
        <p class="eyebrow">作品</p>
        <span class="count">{{ projects.length }}</span>
      </div>

      <button
        class="header-action"
        data-testid="open-create-project-button"
        type="button"
        @click="emit('create-project')"
      >
        新建
      </button>
    </div>

    <div
      v-if="projects.length === 0"
      class="empty"
    >
      还没有作品。
      左下方先创建一部，再从这里进入它。
    </div>

    <div
      v-else
      class="project-tree"
    >
      <article
        v-for="project in projects"
        :key="project.id"
        :class="['project-shell', { 'project-shell-open': isChapterDrawerOpen(project.id) }]"
      >
        <div :class="['project-card', { 'project-card-active': selectedProjectId === project.id }]">
          <div
            class="project-actions"
            data-project-menu-root="true"
          >
            <button
              v-if="selectedProjectId === project.id"
              class="project-chapter-toggle"
              :data-testid="`project-chapter-toggle-${project.id}`"
              type="button"
              @click.stop="handleToggleChapters(project.id)"
            >
              {{ isChapterDrawerOpen(project.id) ? '收起' : '章节' }}
            </button>

            <button
              :disabled="projectActionPendingId === project.id"
              class="project-menu-trigger"
              data-testid="project-menu-trigger"
              type="button"
              @click.stop="toggleProjectMenu(project.id, $event)"
            >
              ⋯
            </button>

            <div
              v-if="menuProjectId === project.id"
              :class="['project-menu', { 'project-menu-up': menuVerticalPlacement === 'up' }]"
            >
              <button
                :disabled="projectActionPendingId === project.id"
                class="project-menu-item"
                data-testid="project-open-folder-button"
                type="button"
                @click.stop="emitProjectAction('open-project-folder', project)"
              >
                打开文件夹
              </button>
              <button
                :disabled="projectActionPendingId === project.id"
                class="project-menu-item"
                data-testid="project-rename-button"
                type="button"
                @click.stop="emitProjectAction('request-rename-project', project)"
              >
                重命名
              </button>
              <button
                :disabled="projectActionPendingId === project.id"
                class="project-menu-item project-menu-item-danger"
                data-testid="project-delete-button"
                type="button"
                @click.stop="emitProjectAction('request-delete-project', project)"
              >
                删除作品
              </button>
            </div>
          </div>

          <button
            class="project-main"
            type="button"
            @click="emit('select', project.id)"
          >
            <div class="project-marker"></div>
            <div class="project-copy">
              <strong :title="project.name">{{ project.name }}</strong>
            </div>
          </button>
        </div>

        <section
          v-if="selectedProjectId === project.id && projectDiscussionSummary"
          class="project-discussion-preview"
        >
          <div class="project-discussion-marker"></div>
          <div class="project-discussion-copy">
            <p>{{ projectDiscussionSummary }}</p>
            <span>{{ relativeDiscussionTime() }}</span>
          </div>
        </section>

        <section
          v-if="isChapterDrawerOpen(project.id)"
          class="chapter-drawer"
        >
          <div class="chapter-drawer-head">
            <span>章节文件</span>
            <div class="chapter-drawer-actions">
              <span>{{ activeChapters.length }} 章</span>
              <button
                class="drawer-text-button"
                data-testid="chapter-drawer-collapse-button"
                type="button"
                @click="handleToggleChapters(project.id)"
              >
                收起
              </button>
            </div>
          </div>

          <div
            v-if="isProjectLoading"
            class="chapter-empty"
          >
            正在读取章节索引…
          </div>

          <div
            v-else-if="activeChapters.length === 0"
            class="chapter-empty"
          >
            当前作品还没有章节索引。
          </div>

          <div
            v-else
            class="chapter-list"
          >
            <button
              v-for="chapter in activeChapters"
              :key="chapter.id"
              :class="['chapter-row', { 'chapter-row-active': selectedChapterId === chapter.id }]"
              :data-testid="`chapter-row-${chapter.id}`"
              type="button"
              @click="emit('select-chapter', chapter.id)"
            >
              <span class="chapter-title">{{ chapter.title }}</span>
              <span class="chapter-state">{{ chapter.exists ? '已写' : '待写' }}</span>
            </button>
          </div>
        </section>

        <section
          v-if="selectedProjectId === project.id && activeDiscussionThreads.length > 0"
          class="session-drawer"
          data-testid="agent-session-window"
        >
          <div class="session-drawer-head">
            <span>最近对话</span>
          </div>

          <div class="session-list">
            <button
              v-for="thread in activeDiscussionThreads"
              :key="thread.id"
              :class="['session-row', { 'session-row-active': thread.id === activeDiscussionThreadId }]"
              :data-testid="`agent-session-row-${thread.id}`"
              type="button"
              @click="emit('select-discussion-thread', thread.id)"
            >
              <span class="session-title">{{ thread.title || '新对话' }}</span>
            </button>
          </div>
        </section>
      </article>
    </div>
  </section>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-radius: 0;
  padding: 0;
  background: transparent;
  border: 0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.panel-header-copy {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.eyebrow {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #667085;
  white-space: nowrap;
}

.count {
  border-radius: 999px;
  padding: 3px 8px;
  background: #e7edf7;
  color: #57606a;
  font-size: 11px;
}

.header-action {
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 6px 10px;
  background: transparent;
  color: #475467;
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}

.header-action:hover {
  background: #e9eef7;
  color: #1d4ed8;
}

.empty {
  border-radius: 14px;
  padding: 12px;
  background: #e9eef7;
  color: #57606a;
  font-size: 12px;
  line-height: 1.6;
}

.project-tree {
  display: grid;
  flex: 1;
  align-content: start;
  gap: 6px;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
}

.project-shell {
  display: grid;
  gap: 6px;
}

.project-shell-open {
  grid-template-columns: minmax(0, 1fr);
}

.project-card {
  position: relative;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
}

.project-card-active {
  border-color: #d8e6fb;
  background: #dfeafb;
}

.project-actions {
  position: absolute;
  top: 50%;
  right: 6px;
  display: flex;
  align-items: center;
  gap: 5px;
  z-index: 2;
  transform: translateY(-50%);
}

.project-main {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 10px;
  width: 100%;
  align-items: center;
  border: 0;
  border-radius: 999px;
  padding: 8px 94px 8px 12px;
  min-height: 46px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.project-main:hover {
  background: #e9eef7;
}

.project-copy {
  min-width: 0;
}

.project-marker {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #9aa8bd;
}

.project-card-active .project-marker {
  background: #1d4ed8;
}

.project-copy strong {
  display: block;
  color: #1f2937;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.2;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.project-discussion-preview {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  padding: 0 8px 0 10px;
}

.project-discussion-marker {
  margin-top: 7px;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #cfc7bb;
}

.project-discussion-copy {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 14px;
  background: #e9eef7;
  border: 1px solid #dfe7f2;
}

.project-discussion-copy p,
.project-discussion-copy span {
  margin: 0;
  color: #6a6f77;
  font-size: 11px;
  line-height: 1.45;
}

.project-discussion-copy p {
  min-width: 0;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-discussion-copy span {
  flex: 0 0 auto;
  white-space: nowrap;
}

.project-menu-trigger {
  min-width: 32px;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 4px 8px;
  background: transparent;
  color: #57606a;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}

.project-chapter-toggle {
  border: 1px solid #cfe0fa;
  border-radius: 999px;
  padding: 4px 8px;
  background: #f8fbff;
  color: #1d4ed8;
  font-size: 11px;
  line-height: 1.2;
  cursor: pointer;
}

.project-chapter-toggle:hover {
  background: #e8f0fe;
}

.project-menu-trigger:hover {
  background: #ffffff;
}

.project-menu-trigger:disabled,
.project-menu-item:disabled {
  opacity: 0.6;
  cursor: wait;
}

.project-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  display: grid;
  gap: 4px;
  min-width: 148px;
  padding: 6px;
  border: 1px solid #d8dee4;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.12);
}

.project-menu-up {
  top: auto;
  bottom: calc(100% + 6px);
}

.project-menu-item {
  border: 0;
  border-radius: 8px;
  padding: 8px 10px;
  background: transparent;
  color: #1f2328;
  text-align: left;
  font-size: 12px;
  cursor: pointer;
}

.project-menu-item:hover {
  background: #f6f8fa;
}

.project-menu-item-danger {
  color: #cf222e;
}

.project-menu-item-danger:hover {
  background: #fff1f0;
}

.chapter-drawer {
  min-width: 0;
  margin-left: 20px;
  border-left: 1px solid #dce5f1;
  padding: 4px 0 4px 10px;
  background: transparent;
}

.chapter-drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: #6e7781;
  font-size: 11px;
}

.chapter-drawer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.drawer-text-button {
  border: 0;
  border-radius: 999px;
  padding: 4px 8px;
  background: transparent;
  color: #1d4ed8;
  font-size: 11px;
  line-height: 1.2;
  cursor: pointer;
}

.drawer-text-button:hover {
  background: #e8f0fe;
}

.chapter-empty {
  border-radius: 8px;
  padding: 8px;
  background: #edf3fb;
  color: #57606a;
  font-size: 11px;
}

.chapter-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
  max-height: 260px;
  overflow: auto;
}

.chapter-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 8px 9px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.chapter-row:hover {
  background: #f8fafc;
}

.chapter-row-active {
  border-color: #d6e5fb;
  background: #eaf2ff;
}

.chapter-state {
  color: #6e7781;
  font-size: 9px;
}

.chapter-title {
  min-width: 0;
  color: #1f2328;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-drawer {
  display: grid;
  gap: 6px;
  min-width: 0;
  margin-left: 20px;
  border-left: 1px solid #dce5f1;
  padding: 6px 0 4px 10px;
}

.session-drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.session-drawer-head span {
  color: #6e7781;
  font-size: 11px;
}

.session-list {
  display: grid;
  gap: 2px;
  max-height: 220px;
  overflow: auto;
}

.session-row {
  display: block;
  width: 100%;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 7px 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.session-row:hover {
  background: #f8fafc;
}

.session-row-active {
  border-color: transparent;
  background: #dfeafb;
}

.session-title {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1f2937;
  font-size: 12px;
  font-weight: 500;
}

</style>
