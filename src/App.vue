<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import CreateProjectForm from './components/CreateProjectForm.vue';
import ExistingNovelImportModal from './components/ExistingNovelImportModal.vue';
import LicensePanel from './components/LicensePanel.vue';
import LocalHistoryPanel from './components/LocalHistoryPanel.vue';
import ModelConfigForm from './components/ModelConfigForm.vue';
import gaoxiaMark from './assets/gaoxia-mark.svg';
import NovelWorkflowPanel from './components/NovelWorkflowPanel.vue';
import ProjectList from './components/ProjectList.vue';
import ProjectWorkspaceSidebar from './components/ProjectWorkspaceSidebar.vue';
import StoryOverviewPanel from './components/StoryOverviewPanel.vue';
import SkillLibraryPanel from './components/SkillLibraryPanel.vue';
import {
  deleteProject,
  exportProjectBook,
  exportProjectMigrationPackage,
  getApiBaseUrl,
  getConfig,
  getHealth,
  getModelRuntime,
  getProjectDetail,
  importExistingNovel,
  importProjectMigrationPackage,
  listProjects,
  openProjectDirectory,
  renameProject,
} from './lib/api.js';

const health = ref(null);
const projects = ref([]);
const config = ref(null);
const bootErrors = ref([]);
const isRefreshing = ref(false);
const selectedProjectId = ref('');
const selectedChapterId = ref('');
const activeSurface = ref('workspace');
const selectedProjectDetail = ref(null);
const isProjectLoading = ref(false);
const isProjectLiveSyncing = ref(false);
const isSettingsOpen = ref(false);
const isCreateOpen = ref(false);
const isExistingNovelImportOpen = ref(false);
const isHistoryOpen = ref(false);
const isStoryOverviewOpen = ref(false);
const isStoryOverviewRefreshing = ref(false);
const chapterBrowserProjectId = ref('');
const exportFormat = ref('markdown');
const isExporting = ref(false);
const isMigrationImporting = ref(false);
const isExistingNovelImporting = ref(false);
const existingNovelImportResult = ref(null);
const migrationImportInput = ref(null);
const noticeMessage = ref('');
const noticeMessageTone = ref('success');
const modelRuntime = ref(null);
const renameProjectTarget = ref(null);
const renameProjectDraft = ref('');
const deleteProjectTarget = ref(null);
const projectActionPendingId = ref('');
const conversationSessionKey = ref(0);
const requestedDiscussionThreadId = ref('');
const discussionThreadStates = ref({});
const skillLaunchRequest = ref(null);
let skillLaunchToken = 0;
let projectEventStream = null;
let dashboardRetryTimer = null;
let modelRuntimeTimer = null;
const dashboardRetryCount = ref(0);
const maxDashboardRetryCount = 4;
const architectureReadyKeys = ['core_seed', 'character_design', 'world_building', 'plot_structure', 'blueprint'];
const storyOverviewStructuredKeys = [
  'characters',
  'events',
  'locations',
  'props',
  'skills',
  'scenes',
  'organizations',
];

const sortedProjects = computed(() => (
  [...projects.value].sort(
    (left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
  )
));

const selectedProject = computed(() => (
  sortedProjects.value.find((project) => project.id === selectedProjectId.value) ?? null
));

const selectedChapter = computed(() => (
  selectedProjectDetail.value?.chapters?.find((chapter) => chapter.id === selectedChapterId.value)
  ?? null
));

const modelDisplayName = computed(() => (
  config.value?.model?.model_name ?? '未配置模型'
));

const historySnapshotCount = computed(() => (
  selectedProjectDetail.value?.local_history?.snapshots?.length ?? 0
));

const storyOverviewCharacterCount = computed(() => (
  selectedProjectDetail.value?.story_overview?.characters?.length ?? 0
));

const selectedDiscussionThreadState = computed(() => (
  discussionThreadStates.value[selectedProjectId.value] ?? {
    activeThreadId: '',
    threads: [],
  }
));

const modelRuntimeTask = computed(() => (
  modelRuntime.value?.active?.[0] ?? modelRuntime.value?.waiting?.[0] ?? null
));

const modelRuntimeLine = computed(() => {
  const state = modelRuntime.value;
  if (!state) {
    return '';
  }
  const task = modelRuntimeTask.value;
  const cooldownEntries = Object.entries(state.cooldowns ?? {});
  if (state.active_count > 0 && task) {
    return `模型处理中：${task.task_name} · 等待 ${Number(task.queue_wait_seconds ?? 0).toFixed(1)}s`;
  }
  if (state.waiting_count > 0 && task) {
    return `模型任务排队：${task.task_name} · 前方 ${Math.max(0, state.waiting_count - 1)} 个`;
  }
  if (cooldownEntries.length > 0) {
    const [, cooldown] = cooldownEntries[0];
    return `后台模型任务暂停：${cooldown.reason || '模型服务暂时不可用'}`;
  }
  return '';
});

const topLevelModalOpen = computed(() => (
  isCreateOpen.value
  || isExistingNovelImportOpen.value
  || isSettingsOpen.value
  || isHistoryOpen.value
  || isStoryOverviewOpen.value
  || Boolean(renameProjectTarget.value)
  || Boolean(deleteProjectTarget.value)
));

const selectedProjectMetaLine = computed(() => {
  const project = selectedProject.value;
  const projectDetail = selectedProjectDetail.value;

  if (!project) {
    return '左侧选择作品和章节，右侧直接和 Agent 继续写。';
  }

  const writtenCount = projectDetail
    ? projectDetail.chapters.filter((chapter) => chapter.exists).length
    : 0;
  const discussionSummary = projectDetail ? getProjectDiscussionSummary(projectDetail) : '';
  const architectureProgress = projectDetail ? getProjectArchitectureProgress(projectDetail) : 0;

  if (discussionSummary && architectureProgress < architectureReadyKeys.length) {
    return '讨论已完成 · 下一步生成整书架构';
  }

  if (architectureProgress >= architectureReadyKeys.length) {
    return `整书架构已就绪 · ${project.target_chapters} 章规划 · ${project.target_words.toLocaleString()} 字目标`;
  }

  return [
    project.genre,
    `${writtenCount}/${project.target_chapters} 章`,
    `${project.target_words.toLocaleString()} 字`,
    new Date(project.updated_at).toLocaleString('zh-CN'),
  ].join(' · ');
});

function getStoryDocumentContent(projectDetail, documentKey) {
  return projectDetail?.story_overview?.documents?.find((item) => item.key === documentKey)?.content?.trim() ?? '';
}

function getProjectArchitectureProgress(projectDetail) {
  return architectureReadyKeys.filter((key) => getStoryDocumentContent(projectDetail, key)).length;
}

function getProjectDiscussionSummary(projectDetail) {
  const manualEntries = (projectDetail?.story_overview?.memory_entries ?? [])
    .filter((item) => (item.source ?? 'manual') !== 'auto')
    .filter((item) => item.id === 'project-discussion-summary' || item.title === '项目讨论结论');
  return manualEntries[manualEntries.length - 1]?.content?.trim() ?? '';
}

function syncProjectSummary(projectDetail) {
  const nextSummary = {
    id: projectDetail.id,
    name: projectDetail.name,
    path: projectDetail.path,
    genre: projectDetail.genre,
    target_chapters: projectDetail.target_chapters,
    target_words: projectDetail.target_words,
    updated_at: projectDetail.updated_at,
  };

  const existingIndex = projects.value.findIndex((project) => project.id === projectDetail.id);
  if (existingIndex === -1) {
    projects.value = [nextSummary, ...projects.value];
    return;
  }

  projects.value = projects.value.map((project) => (
    project.id === projectDetail.id ? nextSummary : project
  ));
}

function storyOverviewHasStructuredEntities(overview) {
  return storyOverviewStructuredKeys.some((key) => (overview?.[key] ?? []).length > 0);
}

function preserveStoryOverviewStructuredEntities(projectDetail) {
  const currentDetail = selectedProjectDetail.value;
  if (!currentDetail || currentDetail.id !== projectDetail?.id) {
    return projectDetail;
  }

  const currentOverview = currentDetail.story_overview;
  const nextOverview = projectDetail.story_overview;
  if (!storyOverviewHasStructuredEntities(currentOverview) || storyOverviewHasStructuredEntities(nextOverview)) {
    return projectDetail;
  }

  return {
    ...projectDetail,
    story_overview: {
      ...nextOverview,
      ...Object.fromEntries(
        storyOverviewStructuredKeys.map((key) => [key, currentOverview?.[key] ?? []]),
      ),
    },
  };
}

function handleProjectDetailUpdated(projectDetail) {
  const nextProjectDetail = preserveStoryOverviewStructuredEntities(projectDetail);
  selectedProjectDetail.value = nextProjectDetail;
  syncProjectSummary(nextProjectDetail);
}

function updateSelectedProjectSummary(projectSummary) {
  if (selectedProjectDetail.value?.id !== projectSummary.id) {
    return;
  }

  selectedProjectDetail.value = {
    ...selectedProjectDetail.value,
    ...projectSummary,
  };
}

function showNotice(message, tone = 'success') {
  noticeMessageTone.value = tone;
  noticeMessage.value = message;
}

function clearNotice() {
  noticeMessage.value = '';
  noticeMessageTone.value = 'success';
}

function clearResolvedBackendNotice() {
  if (
    noticeMessageTone.value === 'error'
    && /本地 backend (连接失败|未就绪)/.test(noticeMessage.value)
  ) {
    clearNotice();
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function syncBodyScrollLock(isLocked) {
  if (typeof document === 'undefined') {
    return;
  }

  document.body.style.overflow = isLocked ? 'hidden' : '';
}

function clearDashboardRetryTimer() {
  if (dashboardRetryTimer && typeof window !== 'undefined') {
    window.clearTimeout(dashboardRetryTimer);
  }
  dashboardRetryTimer = null;
}

function clearModelRuntimeTimer() {
  if (modelRuntimeTimer && typeof window !== 'undefined') {
    window.clearInterval(modelRuntimeTimer);
  }
  modelRuntimeTimer = null;
}

async function refreshModelRuntimeState() {
  try {
    modelRuntime.value = await getModelRuntime();
  } catch {
    modelRuntime.value = null;
  }
}

function startModelRuntimePolling() {
  if (typeof window === 'undefined') {
    return;
  }
  clearModelRuntimeTimer();
  modelRuntimeTimer = window.setInterval(() => {
    void refreshModelRuntimeState();
  }, 2000);
}

function scheduleDashboardRetry() {
  if (typeof window === 'undefined') {
    return;
  }

  if (dashboardRetryCount.value >= maxDashboardRetryCount) {
    return;
  }

  clearDashboardRetryTimer();
  dashboardRetryCount.value += 1;
  dashboardRetryTimer = window.setTimeout(() => {
    dashboardRetryTimer = null;
    void refreshDashboard();
  }, 2500);
}

function stopProjectLiveSync() {
  if (projectEventStream) {
    projectEventStream.close();
    projectEventStream = null;
  }
}

async function refreshProjectDetailFromEvent(projectId) {
  if (!projectId || isProjectLoading.value || isProjectLiveSyncing.value) {
    return;
  }

  isProjectLiveSyncing.value = true;
  try {
    const detail = await getProjectDetail(projectId);
    if (selectedProjectId.value === projectId) {
      handleProjectDetailUpdated(detail);
    }
  } catch {
    // Ignore background live sync failures and keep the workspace usable.
  } finally {
    isProjectLiveSyncing.value = false;
  }
}

async function startProjectLiveSync(projectId) {
  stopProjectLiveSync();
  if (!projectId || typeof window.EventSource === 'undefined') {
    return;
  }

  try {
    const backendUrl = await getApiBaseUrl();
    if (selectedProjectId.value !== projectId) {
      return;
    }
    const stream = new window.EventSource(`${backendUrl}/api/projects/${projectId}/events`);
    stream.addEventListener('local-history-updated', () => {
      void refreshProjectDetailFromEvent(projectId);
    });
    projectEventStream = stream;
  } catch {
    projectEventStream = null;
  }
}

watch(
  selectedProjectDetail,
  (project) => {
    const chapterStillExists = project?.chapters?.some((chapter) => chapter.id === selectedChapterId.value);
    if (!chapterStillExists) {
      selectedChapterId.value = '';
    }
  },
  { immediate: true },
);

watch(
  sortedProjects,
  (nextProjects) => {
    if (nextProjects.length === 0) {
      selectedProjectId.value = '';
      chapterBrowserProjectId.value = '';
      return;
    }

    const stillExists = nextProjects.some((project) => project.id === selectedProjectId.value);
    if (!stillExists) {
      selectedProjectId.value = nextProjects[0].id;
    }

    const drawerStillExists = nextProjects.some((project) => project.id === chapterBrowserProjectId.value);
    if (!drawerStillExists) {
      chapterBrowserProjectId.value = '';
    }
  },
  { immediate: true },
);

watch(
  selectedProjectId,
  async (projectId, previousProjectId) => {
    if (projectId !== previousProjectId) {
      clearNotice();
    }

    stopProjectLiveSync();

    if (!projectId) {
      selectedProjectDetail.value = null;
      chapterBrowserProjectId.value = '';
      return;
    }

    chapterBrowserProjectId.value = projectId;
    isProjectLoading.value = true;
    try {
      selectedProjectDetail.value = await getProjectDetail(projectId);
    } catch (error) {
      bootErrors.value.push(`章节索引读取失败：${error instanceof Error ? error.message : '未知错误'}`);
      selectedProjectDetail.value = null;
    } finally {
      isProjectLoading.value = false;
      if (selectedProjectId.value === projectId) {
        void startProjectLiveSync(projectId);
      }
    }
  },
  { immediate: true },
);

watch(
  topLevelModalOpen,
  (isOpen) => {
    syncBodyScrollLock(isOpen);
  },
  { immediate: true },
);

async function handleProjectExport(formatOverride = '') {
  if (!selectedProjectDetail.value?.id || isExporting.value) {
    return;
  }

  isExporting.value = true;
  noticeMessage.value = '';
  const resolvedFormat = formatOverride || exportFormat.value;
  exportFormat.value = resolvedFormat;

  try {
    const result = await exportProjectBook(selectedProjectDetail.value.id, {
      format: resolvedFormat,
    });
    noticeMessageTone.value = 'success';
    noticeMessage.value =
      `已导出 ${result.chapter_count} 章，约 ${result.word_count.toLocaleString()} 字：${result.path}`;
  } catch (error) {
    noticeMessageTone.value = 'error';
    noticeMessage.value = error instanceof Error ? error.message : '导出失败';
  } finally {
    isExporting.value = false;
  }
}

async function handleProjectMigrationExport(project = null) {
  const target = project ?? selectedProjectDetail.value;
  if (!target?.id || projectActionPendingId.value) {
    return;
  }

  projectActionPendingId.value = target.id;
  clearNotice();
  try {
    const result = await exportProjectMigrationPackage(target.id);
    const warningText = result.warnings?.length ? `；提醒：${result.warnings.join('；')}` : '';
    showNotice(`迁移包已导出：${result.path}${warningText}`);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '迁移包导出失败', 'error');
  } finally {
    if (projectActionPendingId.value === target.id) {
      projectActionPendingId.value = '';
    }
  }
}

function handleProjectMigrationImportRequest() {
  if (isMigrationImporting.value) {
    return;
  }
  migrationImportInput.value?.click();
}

function handleExistingNovelImportRequest() {
  if (isExistingNovelImporting.value) {
    return;
  }
  existingNovelImportResult.value = null;
  isExistingNovelImportOpen.value = true;
}

async function handleExistingNovelImportSubmit(payload) {
  if (isExistingNovelImporting.value) {
    return;
  }

  isExistingNovelImporting.value = true;
  clearNotice();
  try {
    const result = await importExistingNovel(payload);
    existingNovelImportResult.value = result;
    syncProjectSummary(result.project);
    selectedProjectId.value = result.project.id;
    selectedChapterId.value = '';
    chapterBrowserProjectId.value = result.project.id;
    activeSurface.value = 'workspace';
    isHistoryOpen.value = false;
    isStoryOverviewOpen.value = false;
    conversationSessionKey.value += 1;
    await refreshDashboard();
    await nextTick();
    showNotice(`已接管《${result.project.name}》：已导入 ${result.report.applied_chapter_count} 章`);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '旧稿接管失败', 'error');
  } finally {
    isExistingNovelImporting.value = false;
  }
}

async function handleProjectMigrationFileSelected(event) {
  const input = event?.target;
  const file = input?.files?.[0];
  if (!file || isMigrationImporting.value) {
    return;
  }

  isMigrationImporting.value = true;
  clearNotice();
  try {
    const buffer = await file.arrayBuffer();
    const result = await importProjectMigrationPackage({
      filename: file.name,
      content_base64: arrayBufferToBase64(buffer),
    });
    syncProjectSummary(result.project);
    selectedProjectId.value = result.project.id;
    selectedChapterId.value = '';
    chapterBrowserProjectId.value = result.project.id;
    activeSurface.value = 'workspace';
    isHistoryOpen.value = false;
    isStoryOverviewOpen.value = false;
    conversationSessionKey.value += 1;
    const warningText = result.warnings?.length ? `；提醒：${result.warnings.join('；')}` : '';
    await refreshDashboard();
    await nextTick();
    showNotice(`已导入《${result.project.name}》：${result.path}${warningText}`);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '迁移包导入失败', 'error');
  } finally {
    isMigrationImporting.value = false;
    if (input) {
      input.value = '';
    }
  }
}

function handleProjectSelect(projectId) {
  clearNotice();
  activeSurface.value = 'workspace';
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  selectedChapterId.value = '';
  requestedDiscussionThreadId.value = '';
  selectedProjectId.value = projectId;
  chapterBrowserProjectId.value = projectId;
}

async function openStoryOverview() {
  const projectId = selectedProjectDetail.value?.id ?? selectedProjectId.value;
  isStoryOverviewOpen.value = true;
  if (!projectId || isStoryOverviewRefreshing.value) {
    return;
  }

  isStoryOverviewRefreshing.value = true;
  try {
    const detail = await getProjectDetail(projectId, { reviewCharacters: true });
    if (selectedProjectId.value === projectId) {
      handleProjectDetailUpdated(detail);
    }
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '架构总览人物复核失败', 'error');
  } finally {
    isStoryOverviewRefreshing.value = false;
  }
}

function handleChapterBrowserToggle(projectId) {
  if (!projectId) {
    return;
  }

  clearNotice();
  activeSurface.value = 'workspace';
  if (selectedProjectId.value !== projectId) {
    selectedProjectId.value = projectId;
    selectedChapterId.value = '';
  }
  chapterBrowserProjectId.value = chapterBrowserProjectId.value === projectId ? '' : projectId;
}

function handleNewConversation() {
  clearNotice();
  activeSurface.value = 'workspace';
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  chapterBrowserProjectId.value = selectedProjectId.value || '';
  selectedChapterId.value = '';
  requestedDiscussionThreadId.value = '';
  conversationSessionKey.value += 1;
}

function handleSkillLibraryOpen() {
  clearNotice();
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  chapterBrowserProjectId.value = '';
  activeSurface.value = 'skills';
}

function handleWorkspaceOpen() {
  clearNotice();
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  activeSurface.value = 'workspace';
}

function handleSkillLaunchRequest(request) {
  clearNotice();
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  chapterBrowserProjectId.value = '';
  activeSurface.value = 'skills';
  skillLaunchToken += 1;
  skillLaunchRequest.value = {
    ...(request ?? {}),
    token: skillLaunchToken,
  };
}

function handleChapterSelect(chapterId) {
  clearNotice();
  activeSurface.value = 'workspace';
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  chapterBrowserProjectId.value = selectedProjectId.value || chapterBrowserProjectId.value;
  selectedChapterId.value = chapterId;
}

async function handleProjectCreated(projectSummary) {
  syncProjectSummary(projectSummary);
  activeSurface.value = 'workspace';
  isCreateOpen.value = false;
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  noticeMessage.value = '';
  requestedDiscussionThreadId.value = '';
  chapterBrowserProjectId.value = projectSummary.id;
  selectedChapterId.value = '';
  selectedProjectId.value = projectSummary.id;
  conversationSessionKey.value += 1;

  await refreshDashboard();
}

function handleDiscussionThreadStateUpdated(payload) {
  const projectId = String(payload?.projectId ?? '').trim();
  if (!projectId) {
    return;
  }

  discussionThreadStates.value = {
    ...discussionThreadStates.value,
    [projectId]: {
      activeThreadId: String(payload.activeThreadId ?? ''),
      threads: Array.isArray(payload.threads) ? payload.threads : [],
    },
  };
}

function handleDiscussionThreadSelect(threadId) {
  const nextThreadId = String(threadId ?? '').trim();
  if (!nextThreadId) {
    return;
  }

  clearNotice();
  activeSurface.value = 'workspace';
  isHistoryOpen.value = false;
  isStoryOverviewOpen.value = false;
  requestedDiscussionThreadId.value = nextThreadId;
}

async function handleProjectFolderOpen(project) {
  if (!project?.id || projectActionPendingId.value) {
    return;
  }

  projectActionPendingId.value = project.id;
  try {
    const result = await openProjectDirectory(project.id);
    showNotice(`已打开作品目录：${result.path}`);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '打开文件夹失败', 'error');
  } finally {
    if (projectActionPendingId.value === project.id) {
      projectActionPendingId.value = '';
    }
  }
}

function handleRenameProjectRequest(project) {
  renameProjectTarget.value = project;
  renameProjectDraft.value = project?.name ?? '';
}

function closeRenameProjectModal() {
  renameProjectTarget.value = null;
  renameProjectDraft.value = '';
}

async function handleProjectRenameSubmit() {
  const target = renameProjectTarget.value;
  if (!target?.id || projectActionPendingId.value) {
    return;
  }

  const nextName = renameProjectDraft.value.trim();
  if (!nextName) {
    showNotice('作品名不能为空', 'error');
    return;
  }

  projectActionPendingId.value = target.id;
  try {
    const summary = await renameProject(target.id, { name: nextName });
    syncProjectSummary(summary);
    updateSelectedProjectSummary(summary);
    closeRenameProjectModal();
    showNotice(`作品已重命名为《${summary.name}》`);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '重命名失败', 'error');
  } finally {
    if (projectActionPendingId.value === target.id) {
      projectActionPendingId.value = '';
    }
  }
}

function handleDeleteProjectRequest(project) {
  deleteProjectTarget.value = project;
}

function closeDeleteProjectModal() {
  deleteProjectTarget.value = null;
}

async function handleProjectDeleteConfirm() {
  const target = deleteProjectTarget.value;
  if (!target?.id || projectActionPendingId.value) {
    return;
  }

  projectActionPendingId.value = target.id;
  try {
    const result = await deleteProject(target.id);
    projects.value = projects.value.filter((project) => project.id !== target.id);

    if (selectedProjectId.value === target.id) {
      selectedProjectId.value = '';
      selectedChapterId.value = '';
      selectedProjectDetail.value = null;
      stopProjectLiveSync();
    }

    if (chapterBrowserProjectId.value === target.id) {
      chapterBrowserProjectId.value = '';
    }

    closeDeleteProjectModal();
    showNotice(`《${result.name}》已删除`);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : '删除失败', 'error');
  } finally {
    if (projectActionPendingId.value === target.id) {
      projectActionPendingId.value = '';
    }
  }
}

function closeTransientOverlay() {
  if (renameProjectTarget.value) {
    closeRenameProjectModal();
    return;
  }

  if (deleteProjectTarget.value) {
    closeDeleteProjectModal();
    return;
  }

  if (isCreateOpen.value) {
    isCreateOpen.value = false;
    return;
  }

  if (isExistingNovelImportOpen.value) {
    isExistingNovelImportOpen.value = false;
    return;
  }

  if (isSettingsOpen.value) {
    isSettingsOpen.value = false;
    return;
  }

  if (isHistoryOpen.value) {
    isHistoryOpen.value = false;
    return;
  }

  if (isStoryOverviewOpen.value) {
    isStoryOverviewOpen.value = false;
  }
}

function isEditableTarget(target) {
  return target instanceof Element
    && Boolean(target.closest('input, textarea, select, [contenteditable="true"], [contenteditable=""]'));
}

function handleWindowKeydown(event) {
  if (event.key === 'Escape') {
    if (isSettingsOpen.value && isEditableTarget(event.target)) {
      return;
    }
    closeTransientOverlay();
  }
}

async function refreshDashboard() {
  if (isRefreshing.value) {
    return;
  }

  isRefreshing.value = true;
  clearDashboardRetryTimer();
  const nextBootErrors = [];

  const [healthResult, projectsResult, configResult, modelRuntimeResult] =
    await Promise.allSettled([
      getHealth(),
      listProjects(),
      getConfig(),
      getModelRuntime(),
    ]);

  if (healthResult.status === 'fulfilled') {
    health.value = healthResult.value;
  } else {
    nextBootErrors.push(`创作空间暂时无法连接：${healthResult.reason instanceof Error ? healthResult.reason.message : '未知错误'}`);
  }

  if (projectsResult.status === 'fulfilled') {
    projects.value = projectsResult.value;
  } else {
    nextBootErrors.push(`作品列表读取失败：${projectsResult.reason instanceof Error ? projectsResult.reason.message : '未知错误'}`);
  }

  if (configResult.status === 'fulfilled') {
    config.value = configResult.value;
  } else {
    nextBootErrors.push(`AI 写作设置读取失败：${configResult.reason instanceof Error ? configResult.reason.message : '未知错误'}`);
  }

  if (modelRuntimeResult.status === 'fulfilled') {
    modelRuntime.value = modelRuntimeResult.value;
  }

  bootErrors.value = nextBootErrors;
  if (nextBootErrors.length === 0) {
    dashboardRetryCount.value = 0;
    clearResolvedBackendNotice();
  } else {
    scheduleDashboardRetry();
  }
  isRefreshing.value = false;
}

onMounted(async () => {
  if (typeof window !== 'undefined') {
    const searchParams = new URLSearchParams(window.location.search);
    const requestedSurface = searchParams.get('surface');
    if (requestedSurface === 'skills' || requestedSurface === 'workspace') {
      activeSurface.value = requestedSurface;
    }
    if (searchParams.get('history') === 'open') {
      isHistoryOpen.value = true;
    }
    window.addEventListener('keydown', handleWindowKeydown);
  }

  await refreshDashboard();
  startModelRuntimePolling();
});

onBeforeUnmount(() => {
  stopProjectLiveSync();
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleWindowKeydown);
  }
  clearDashboardRetryTimer();
  clearModelRuntimeTimer();
  syncBodyScrollLock(false);
});
</script>

<template>
  <div
    class="app-shell"
    data-testid="app-shell"
  >
    <div :class="['workspace-shell', { 'workspace-shell-chapters-open': chapterBrowserProjectId }]">
      <aside class="sidebar">
        <section class="sidebar-brand">
          <img
            :src="gaoxiaMark"
            alt="稿匣"
            class="sidebar-logo"
          >
          <div class="sidebar-brand-copy">
            <p class="sidebar-kicker">GAOXIA</p>
            <h1>稿匣 <span>小说工作台</span></h1>
          </div>
        </section>

        <div class="sidebar-tools">
          <button
            class="tool-button tool-button-primary"
            data-testid="new-conversation-button"
            type="button"
            @click="handleNewConversation"
          >
            ＋ 新对话
          </button>

          <button
            :class="['tool-button', { 'tool-button-active': activeSurface === 'skills' }]"
            data-testid="open-skills-button"
            type="button"
            @click="handleSkillLibraryOpen"
          >
            技能库
          </button>
        </div>

        <ProjectList
          class="sidebar-tree"
          :projects="sortedProjects"
          :selected-project-id="selectedProjectId"
          :selected-chapter-id="selectedChapterId"
          :project-detail="selectedProjectDetail"
          :chapter-browser-project-id="chapterBrowserProjectId"
          :discussion-thread-state="selectedDiscussionThreadState"
          :is-project-loading="isProjectLoading"
          :project-action-pending-id="projectActionPendingId"
          :project-discussion-summary="getProjectDiscussionSummary(selectedProjectDetail)"
          @create-project="isCreateOpen = true"
          @import-existing-novel="handleExistingNovelImportRequest"
          @select="handleProjectSelect"
          @select-chapter="handleChapterSelect"
          @select-discussion-thread="handleDiscussionThreadSelect"
          @toggle-chapters="handleChapterBrowserToggle"
          @open-project-folder="handleProjectFolderOpen"
          @export-project-migration="handleProjectMigrationExport"
          @request-rename-project="handleRenameProjectRequest"
          @request-delete-project="handleDeleteProjectRequest"
        />

        <input
          ref="migrationImportInput"
          accept=".gaoxia-project.zip,.zip"
          aria-hidden="true"
          class="visually-hidden"
          data-testid="project-migration-file-input"
          hidden
          tabindex="-1"
          type="file"
          @change="handleProjectMigrationFileSelected"
        >

        <div class="sidebar-footer">
          <button
            class="settings-trigger"
            data-testid="open-settings-button"
            type="button"
            @click="isSettingsOpen = true"
          >
            设置
          </button>
        </div>
      </aside>

      <main class="main-stage">
        <header
          v-if="activeSurface !== 'skills'"
          class="stage-header"
        >
          <div class="stage-heading stage-heading-inline">
            <div class="stage-title-stack">
              <h2 data-testid="stage-project-title">
                {{ selectedProject ? selectedProject.name : '稿匣' }}
              </h2>
              <span class="stage-meta-line">{{ selectedProjectMetaLine }}</span>
            </div>
          </div>

          <div
            v-if="selectedProjectDetail"
            class="stage-actions"
          >
            <button
              :aria-busy="isStoryOverviewRefreshing"
              class="secondary-button stage-primary-action"
              data-testid="open-story-overview-button"
              type="button"
              @click="openStoryOverview"
            >
              <span>架构总览</span>
              <strong>{{ storyOverviewCharacterCount }}</strong>
            </button>

            <details class="stage-tools-menu">
              <summary
                class="secondary-button stage-tools-trigger"
                data-testid="project-tools-trigger"
              >
                更多
              </summary>

              <div class="stage-tools-popover">
                <button
                  :disabled="isExporting"
                  class="stage-tools-item"
                  type="button"
                  @click="handleProjectExport('markdown')"
                >
                  {{ isExporting && exportFormat === 'markdown' ? '导出中…' : '导出 Markdown' }}
                </button>

                <button
                  :disabled="isExporting"
                  class="stage-tools-item"
                  type="button"
                  @click="handleProjectExport('text')"
                >
                  {{ isExporting && exportFormat === 'text' ? '导出中…' : '导出纯文本' }}
                </button>

                <button
                  :disabled="projectActionPendingId === selectedProjectDetail.id"
                  class="stage-tools-item"
                  data-testid="project-migration-export-button"
                  type="button"
                  @click="handleProjectMigrationExport(selectedProjectDetail)"
                >
                  {{ projectActionPendingId === selectedProjectDetail.id ? '导出中…' : '导出迁移包' }}
                </button>

                <button
                  :disabled="isMigrationImporting"
                  class="stage-tools-item"
                  data-testid="project-migration-import-button"
                  type="button"
                  @click="handleProjectMigrationImportRequest"
                >
                  {{ isMigrationImporting ? '导入中…' : '导入迁移包' }}
                </button>

                <button
                  class="stage-tools-item"
                  data-testid="open-history-button"
                  type="button"
                  @click="isHistoryOpen = true"
                >
                  <span>版本管理</span>
                  <strong>{{ historySnapshotCount }}</strong>
                </button>
              </div>
            </details>
          </div>
        </header>

        <section
          v-if="noticeMessage"
          :class="['notice-banner', noticeMessageTone === 'error' ? 'notice-banner-error' : 'notice-banner-success']"
        >
          {{ noticeMessage }}
        </section>

        <section
          v-if="modelRuntimeLine"
          class="model-runtime-banner"
        >
          <span>{{ modelRuntimeLine }}</span>
          <strong v-if="modelRuntime?.waiting_count">队列 {{ modelRuntime.waiting_count }}</strong>
        </section>

        <section
          v-if="bootErrors.length > 0"
          class="error-banner"
        >
          <div class="error-banner-head">
            <div>
              <p>当前有几项能力还没准备好：</p>
              <span v-if="dashboardRetryCount < maxDashboardRetryCount">系统会自动再试几次，你也可以手动重连。</span>
              <span v-else>自动重试已经结束，可以手动再试一次。</span>
            </div>
            <button
              :disabled="isRefreshing"
              class="error-banner-action"
              type="button"
              @click="refreshDashboard"
            >
              {{ isRefreshing ? '重连中…' : '立即重试' }}
            </button>
          </div>
          <ul>
            <li
              v-for="item in bootErrors"
              :key="item"
            >
              {{ item }}
            </li>
          </ul>
        </section>

        <section
          v-if="activeSurface === 'skills'"
          class="skills-stage"
          data-testid="skills-stage"
        >
          <SkillLibraryPanel
            :project="selectedProjectDetail"
            :launch-request="skillLaunchRequest"
            :selected-chapter="selectedChapter"
            :model-name="modelDisplayName"
            @project-detail-updated="handleProjectDetailUpdated"
            @return-workspace="handleWorkspaceOpen"
          />
        </section>

        <div
          v-if="selectedProject"
          v-show="activeSurface !== 'skills'"
          class="stage-workbench"
        >
          <section
            :class="[
              'stage-canvas',
              { 'stage-canvas-loading': isProjectLoading && selectedProjectDetail },
            ]"
          >
            <template v-if="selectedProjectDetail">
              <NovelWorkflowPanel
                :model-name="modelDisplayName"
                :project="selectedProjectDetail"
                :conversation-session-key="conversationSessionKey"
                :requested-discussion-thread-id="requestedDiscussionThreadId"
                :selected-chapter-id="selectedChapterId"
                :selected-chapter="selectedChapter"
                @discussion-thread-state-updated="handleDiscussionThreadStateUpdated"
                @focus-chapter="handleChapterSelect"
                @open-model-settings="isSettingsOpen = true"
                @open-skill="handleSkillLaunchRequest"
                @project-detail-updated="handleProjectDetailUpdated"
              />
            </template>

            <div
              v-else
              class="loading-panel"
            >
              {{ isProjectLoading ? '正在读取当前小说的章节索引…' : '正在准备当前小说工作区…' }}
            </div>

            <div
              v-if="isProjectLoading && selectedProjectDetail"
              class="stage-loading-overlay"
            >
              <div class="loading-panel stage-loading-overlay-panel">
                正在读取当前小说的章节索引…
              </div>
            </div>
          </section>
        </div>

        <section
          v-if="!selectedProject && activeSurface !== 'skills'"
          class="empty-stage"
        >
          <p class="empty-stage-kicker">还没有打开的小说</p>
          <h3>先在左侧创建或选择一部作品</h3>
          <p>选择作品后，章节会在左侧展开，右侧直接进入智能写作对话。</p>
        </section>
      </main>
    </div>

    <Teleport to="body">
      <div
        v-if="isCreateOpen"
        class="modal-overlay"
        data-testid="create-project-modal"
        @click.self="isCreateOpen = false"
      >
        <section
          class="modal-dialog modal-dialog-narrow"
          role="dialog"
          aria-modal="true"
          aria-label="新建作品"
        >
          <header class="modal-header">
            <div>
              <p class="stage-kicker">新建作品</p>
              <h3>创建一部小说</h3>
            </div>

            <button
              class="modal-close"
              type="button"
              @click="isCreateOpen = false"
            >
              关闭
            </button>
          </header>

          <CreateProjectForm
            :has-projects="sortedProjects.length > 0"
            :force-open="true"
            :show-summary="false"
            @created="handleProjectCreated"
          />
        </section>
      </div>

      <ExistingNovelImportModal
        :open="isExistingNovelImportOpen"
        :is-submitting="isExistingNovelImporting"
        :result="existingNovelImportResult"
        @close="isExistingNovelImportOpen = false"
        @submit="handleExistingNovelImportSubmit"
      />

      <div
        v-if="renameProjectTarget"
        class="modal-overlay"
        data-testid="rename-project-modal"
        @click.self="closeRenameProjectModal"
      >
        <section
          class="modal-dialog modal-dialog-narrow"
          role="dialog"
          aria-modal="true"
          aria-label="重命名作品"
        >
          <header class="modal-header">
            <div>
              <p class="stage-kicker">作品管理</p>
              <h3>重命名作品</h3>
            </div>

            <button
              class="modal-close"
              type="button"
              @click="closeRenameProjectModal"
            >
              关闭
            </button>
          </header>

          <div class="project-manage-form">
            <label class="project-manage-field">
              <span>作品名称</span>
              <input
                v-model="renameProjectDraft"
                :disabled="projectActionPendingId === renameProjectTarget.id"
                data-testid="rename-project-input"
                maxlength="80"
                placeholder="输入新的作品名称"
                type="text"
                @keydown.enter.prevent="handleProjectRenameSubmit"
              >
            </label>

            <p class="project-manage-hint">
              会同时更新作品名和本地项目目录名。
            </p>

            <div class="project-manage-actions">
              <button
                class="secondary-button"
                type="button"
                @click="closeRenameProjectModal"
              >
                取消
              </button>
              <button
                :disabled="projectActionPendingId === renameProjectTarget.id"
                class="secondary-button project-manage-submit"
                type="button"
                @click="handleProjectRenameSubmit"
              >
                {{ projectActionPendingId === renameProjectTarget.id ? '保存中…' : '保存名称' }}
              </button>
            </div>
          </div>
        </section>
      </div>

      <div
        v-if="deleteProjectTarget"
        class="modal-overlay"
        data-testid="delete-project-modal"
        @click.self="closeDeleteProjectModal"
      >
        <section
          class="modal-dialog modal-dialog-narrow"
          role="dialog"
          aria-modal="true"
          aria-label="删除作品"
        >
          <header class="modal-header">
            <div>
              <p class="stage-kicker">作品管理</p>
              <h3>删除作品</h3>
            </div>

            <button
              class="modal-close"
              type="button"
              @click="closeDeleteProjectModal"
            >
              关闭
            </button>
          </header>

          <div class="project-manage-form">
            <p class="project-manage-warning">
              这会删除《{{ deleteProjectTarget.name }}》的整个本地项目目录，章节、设定和版本记录都会一起删掉。
            </p>
            <p class="project-manage-hint">
              目录位置：{{ deleteProjectTarget.path }}
            </p>

            <div class="project-manage-actions">
              <button
                class="secondary-button"
                type="button"
                @click="closeDeleteProjectModal"
              >
                取消
              </button>
              <button
                :disabled="projectActionPendingId === deleteProjectTarget.id"
                class="secondary-button project-manage-danger"
                type="button"
                @click="handleProjectDeleteConfirm"
              >
                {{ projectActionPendingId === deleteProjectTarget.id ? '删除中…' : '确认删除' }}
              </button>
            </div>
          </div>
        </section>
      </div>

      <div
        v-if="isSettingsOpen"
        class="modal-overlay modal-overlay-drawer"
        data-testid="settings-modal"
      >
        <section
          class="modal-dialog modal-dialog-drawer settings-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="AI 写作设置"
        >
          <header class="modal-header">
            <div>
              <p class="stage-kicker">高级设置</p>
              <h3>AI 写作设置</h3>
            </div>

            <button
              class="modal-close"
              type="button"
              @click="isSettingsOpen = false"
            >
              关闭
            </button>
          </header>

          <div class="settings-panel-stack">
            <ModelConfigForm
              :config="config"
              @updated="refreshDashboard"
            />

            <LicensePanel />
          </div>
        </section>
      </div>

      <LocalHistoryPanel
        v-if="selectedProjectDetail"
        :open="isHistoryOpen"
        :project="selectedProjectDetail"
        :selected-chapter-id="selectedChapterId"
        @close="isHistoryOpen = false"
        @project-detail-updated="handleProjectDetailUpdated"
      />

      <div
        v-if="selectedProjectDetail && isStoryOverviewOpen"
        class="modal-overlay modal-overlay-drawer modal-overlay-wide"
        @click.self="isStoryOverviewOpen = false"
      >
        <StoryOverviewPanel
          :open="isStoryOverviewOpen"
          :project="selectedProjectDetail"
          :selected-chapter-id="selectedChapterId"
          @close="isStoryOverviewOpen = false"
          @project-detail-updated="handleProjectDetailUpdated"
        />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
  padding: 0;
  margin: -1px;
}

.stage-canvas {
  position: relative;
}

.stage-canvas-loading {
  min-height: 100%;
}

.stage-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 12;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 88px 24px 24px;
  background: rgba(247, 246, 242, 0.72);
  backdrop-filter: blur(3px);
}

.stage-loading-overlay-panel {
  pointer-events: none;
  min-width: min(360px, calc(100% - 48px));
}

.model-runtime-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 12px;
  padding: 10px 14px;
  border: 1px solid #c8d7eb;
  border-radius: 8px;
  background: #f4f8ff;
  color: #243b53;
  font-size: 13px;
  line-height: 1.5;
}

.model-runtime-banner strong {
  flex: 0 0 auto;
  font-size: 12px;
  color: #1d4ed8;
}
</style>
