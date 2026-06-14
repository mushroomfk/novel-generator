<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import AgentActionTimeline from './AgentActionTimeline.vue';
import AgentArtifactSummary from './AgentArtifactSummary.vue';
import AgentEventBlockSummary from './AgentEventBlockSummary.vue';
import AgentPlanCard from './AgentPlanCard.vue';
import ProjectWorkspaceSidebar from './ProjectWorkspaceSidebar.vue';
import {
  acceptChapterSegment,
  applyProjectArchitectureWorkspace,
  getProjectDetail,
  getProjectAgentThreads,
  importProjectKnowledgeFiles,
  listStyles,
  listXpPresets,
  previewChapterGeneratePrompt,
  previewChapterWorkflowPrompt,
  saveProjectAgentThreads,
  startChapterSegmentSession,
  streamChapterSegmentGenerate,
  updateProjectMemory,
} from '../lib/api.js';
import { useAgentSession } from '../composables/useAgentSession.js';
import { buildImportedFilePayloads, importAcceptValue } from '../lib/importFiles.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  selectedChapter: {
    type: Object,
    default: null,
  },
  selectedChapterId: {
    type: String,
    default: '',
  },
  modelName: {
    type: String,
    default: '未配置模型',
  },
  conversationSessionKey: {
    type: Number,
    default: 0,
  },
  requestedDiscussionThreadId: {
    type: String,
    default: '',
  },
  embedded: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['project-detail-updated', 'discussion-thread-state-updated', 'open-model-settings', 'focus-chapter', 'open-skill']);

const DISCUSSION_THREAD_STORE_KEY = 'novel-agent-threads-v2';
const MAX_DISCUSSION_THREADS = 20;
const AGENT_REQUEST_MESSAGE_LIMIT = 50;
const AGENT_REQUEST_MESSAGE_CONTENT_LIMIT = 6000;
const AGENT_REQUEST_CURRENT_USER_CONTENT_LIMIT = 1000000;
const AGENT_REQUEST_OMITTED_MARKER = '\n\n[中间较长历史已省略]\n\n';
const AGENT_THREAD_SUMMARY_LIMIT = 500;

const composerText = ref('');
const composerActiveSkillId = ref('');
const composerActiveSkillPrompt = ref('');
const composerFileInput = ref(null);
const operationStreamRef = ref(null);
const operationStreamNeedsLatestButton = ref(false);
const composerReferences = ref([]);
const composerReferenceSyncing = ref(false);
const composerToolMessage = ref('');
const composerToolTone = ref('success');
const discussionSaveMessage = ref('');
const discussionSavePending = ref(false);
const previewCollapsed = ref(true);
const agentPanelHidden = ref(false);

const discussionThreads = ref([]);
const activeDiscussionThreadId = ref('');
const discussionHistory = ref([]);
const pendingPlan = ref(null);
const threadSuggestions = ref([]);
const runningProjectId = ref('');
const runningThreadId = ref('');
const styleOptions = ref([]);
const xpPresetOptions = ref([]);

const executionOptions = reactive({
  styleName: '',
  xpPreset: '',
  charactersInvolved: '',
  keyItems: '',
  sceneLocation: '',
  timeConstraint: '',
});

const architectureForm = reactive({
  genre: '',
  targetChapters: 20,
  targetWords: 200000,
});

const architectureConfirmOpen = ref(false);
const architectureSessionActive = ref(false);
const planConfirmOpen = ref(false);
const planPromptPreviews = ref([]);
const planPromptPreviewLoading = ref(false);
const planPromptPreviewError = ref('');
const planPromptPreviewMessage = ref('');
const agentSegmentState = reactive({
  open: false,
  starting: false,
  running: false,
  accepting: false,
  planId: '',
  promptActions: [],
  actionCursor: 0,
  session: null,
  prompt: '',
  draftText: '',
  message: '',
  error: '',
  taskId: '',
  focusChapterId: '',
  streamResult: null,
});
const forceDiscussionMode = ref(false);
let discussionLoadSequence = 0;
let remotePersistInFlight = false;
let queuedRemotePersist = null;
let operationStreamScrollFrame = 0;
let operationStreamStateFrame = 0;

const {
  running,
  runtimeError,
  sessionStatus,
  timelineItems: sessionTimeline,
  clearTimeline: clearSessionTimeline,
  resetSession: resetAgentSession,
  stopSession,
  runAgentSession,
} = useAgentSession({
  onProjectUpdated: (detail) => {
    if (detail?.id === props.project?.id) {
      emit('project-detail-updated', detail);
    }
  },
});

const sessionElapsedSeconds = ref(0);
let sessionElapsedTimer = null;

const quickActionSeed = computed(() => ([
  {
    id: 'discuss',
    label: '看现状',
    skillId: 'brainstorm',
    prompt: '先看当前项目状态，告诉我这本书现在最该推进什么。',
  },
  {
    id: 'architecture',
    label: '完善架构',
    skillId: 'blueprint',
    prompt: '先看当前状态，帮我完善整书架构。',
  },
  {
    id: 'diagnose',
    label: props.selectedChapter ? '判断本章' : '判断章节',
    skillId: 'chapter-diagnose',
    prompt: props.selectedChapter
      ? `先看当前状态，判断第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》现在最该处理什么。`
      : '先看当前状态，判断当前章节现在最该处理什么。',
  },
  {
    id: 'draft',
    label: props.selectedChapter ? '续写本章' : '续写正文',
    skillId: 'chapter-draft',
    prompt: props.selectedChapter
      ? `先看当前状态，续写第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》。`
      : '先看当前状态，直接续写当前章节。',
  },
]));

const previewMode = computed(() => {
  const planActions = pendingPlan.value?.actions ?? [];
  const currentPlanIsProjectLevel = planActions.length > 0
    && planActions.every((item) => !item.chapter_id);
  if (currentPlanIsProjectLevel) {
    return 'project';
  }
  return props.selectedChapter ? 'chapter' : 'project';
});

const planPromptActions = computed(() => {
  const actions = Array.isArray(pendingPlan.value?.actions) ? pendingPlan.value.actions : [];
  return actions
    .map((action, index) => ({ action, index }))
    .filter(({ action }) => (
      action?.kind === 'chapter_generate'
      || (action?.kind === 'chapter_workflow' && (action.mode || '') === 'draft')
    ));
});

const pendingPlanHasWritingActions = computed(() => planPromptActions.value.length > 0);

const activeAgentSegment = computed(() => {
  const session = agentSegmentState.session;
  if (!session?.segments?.length) {
    return null;
  }
  return session.segments.find((item) => item.index === session.current_segment_index) ?? null;
});

const isAgentSegmentCompleted = computed(() => agentSegmentState.session?.status === 'completed');

const agentSegmentProgressLabel = computed(() => {
  const session = agentSegmentState.session;
  if (!session) {
    return '';
  }
  return `第 ${session.current_segment_index ?? 1}/${session.segments?.length ?? 1} 段`;
});

const agentSegmentWordLabel = computed(() => {
  const session = agentSegmentState.session;
  if (!session) {
    return '';
  }
  const current = Number(session.current_word_count ?? 0);
  const target = Number(session.target_word_count ?? 0);
  return target > 0 ? `${current} / ${target} 字` : `${current} 字`;
});

const agentSegmentCurrentTitle = computed(() => {
  const session = agentSegmentState.session;
  if (!session) {
    return '当前章节';
  }
  return `第 ${session.chapter_index} 章《${session.chapter_title}》`;
});

const agentSegmentBusy = computed(() => (
  agentSegmentState.starting || agentSegmentState.running || agentSegmentState.accepting
));

const planConfirmDisabled = computed(() => (
  running.value
  || planPromptPreviewLoading.value
  || (
    planPromptActions.value.length > 0
    && (Boolean(planPromptPreviewError.value) || planPromptPreviews.value.length !== planPromptActions.value.length)
  )
));

const hasPreviewChapter = computed(() => Boolean(props.selectedChapter));

const canTogglePreview = computed(() => (
  !props.embedded && hasPreviewChapter.value
));

const showPreviewPanel = computed(() => (
  canTogglePreview.value && (!previewCollapsed.value || agentPanelHidden.value)
));

const canHideAgentPanel = computed(() => (
  !props.embedded && hasPreviewChapter.value
));

const discussionSummary = computed(() => {
  const manualEntries = (props.project?.story_overview?.memory_entries ?? [])
    .filter((item) => (item.source ?? 'manual') !== 'auto')
    .filter((item) => item.id === 'project-discussion-summary' || item.title === '项目讨论结论');
  const latestEntry = manualEntries[manualEntries.length - 1];
  return latestEntry?.content?.trim() ?? '';
});

const hasPendingPlanActions = computed(() => Boolean(pendingPlan.value?.actions?.length));

function openObsidianMaintenanceFromArtifact(artifact) {
  const metadata = artifact?.metadata && typeof artifact.metadata === 'object' ? artifact.metadata : {};
  const chapterIndex = Number(metadata.chapter_index ?? 0);
  const suggestionIds = Array.isArray(metadata.suggestion_ids)
    ? metadata.suggestion_ids.map((item) => String(item ?? '').trim()).filter(Boolean)
    : [];
  emit('open-skill', {
    skillId: 'self-evolution',
    source: 'obsidian-maintenance-artifact',
    obsidianMaintenanceSourceChapter: chapterIndex > 0 ? chapterIndex : 0,
    obsidianMaintenanceSuggestionIds: suggestionIds,
    obsidianMaintenanceQuery: '',
    obsidianMaintenanceStatusFilter: '全部',
  });
}

const discussionHasArchitectureExecution = computed(() => (
  discussionHistory.value.some((message) => (
    message.mode === 'execution'
    && (
      message.taskPackKind === 'architecture'
      || Boolean(message.executionTrace?.some((item) => (
        item.taskPackKind === 'architecture' || item.actionKind === 'generate_architecture'
      )))
    )
  ))
));

const canShowArchitectureStage = computed(() => (
  previewMode.value === 'project'
  && !props.selectedChapter
  && Boolean(
    discussionSummary.value
    || discussionHasArchitectureExecution.value
    || architectureSessionActive.value
  )
));

const showArchitectureStage = computed(() => (
  canShowArchitectureStage.value && !forceDiscussionMode.value && !hasPendingPlanActions.value
));

const currentOperationHint = computed(() => {
  if (showArchitectureStage.value) {
    return '这里就是用户和 Agent 的聊天窗口。继续聊需求，准备好后再执行整书架构。';
  }

  if (pendingPlan.value?.actions?.length) {
    return '系统已经列出执行计划。点“执行当前计划”，或者直接发新要求覆盖它。';
  }

  if (props.selectedChapter) {
    return '你可以直接说“续写这一章”“判断这一章问题”“把这章拆成场景”“润色这一章”。明确是执行命令时，会直接开始。';
  }

  return '你可以直接说“看当前状态”“完善整书架构”“继续讨论故事方向”。明确是执行命令时，会直接开始。';
});

const sendButtonLabel = computed(() => {
  if (activeDiscussionIsRunning.value) {
    return sessionStatus.value === 'cancelling' ? '停止中…' : '停止';
  }

  if (otherDiscussionRunning.value) {
    return '其他线程执行中';
  }

  if (composerReferenceSyncing.value) {
    return '资料导入中…';
  }

  return '发送';
});

const composerDisabled = computed(() => (
  composerReferenceSyncing.value || !props.project?.id
));

const hasExecutionOptions = computed(() => (
  styleOptions.value.length > 0
  || xpPresetOptions.value.length > 0
  || Boolean(props.selectedChapter)
));

const activeSessionTimelineItem = computed(() => {
  const runningItems = sessionTimeline.value.filter((item) => item.status === 'running');
  if (runningItems.length > 0) {
    return runningItems[runningItems.length - 1];
  }

  return sessionTimeline.value[sessionTimeline.value.length - 1] ?? null;
});

const runtimeStripLead = computed(() => {
  if (sessionStatus.value === 'cancelling') {
    return '正在停止';
  }

  const actionKind = String(activeSessionTimelineItem.value?.actionKind ?? '').trim();
  switch (actionKind) {
    case 'session_prepare':
      return '正在读取';
    case 'session_plan':
      return '正在规划';
    case 'review_knowledge':
      return '正在分析资料';
    case 'generate_architecture':
      return '正在生成架构';
    case 'brainstorm':
      return '正在讨论';
    case 'chapter_generate':
      return '正在续写';
    case 'rewrite_chapter':
      return '正在改写';
    case 'skill_optimize':
      return '正在整理技能';
    default:
      return running.value ? '正在处理' : '';
  }
});

const runtimeStripTitle = computed(() => {
  if (sessionStatus.value === 'cancelling') {
    return '本轮任务正在停止';
  }

  const label = String(activeSessionTimelineItem.value?.label ?? '').trim();
  return label || '正在处理当前请求';
});

const runtimeProgressText = computed(() => {
  const step = Number(activeSessionTimelineItem.value?.step ?? 0);
  const total = Number(activeSessionTimelineItem.value?.total ?? 0);
  if (step && total) {
    return `第 ${step} / ${total} 步`;
  }
  if (step) {
    return `第 ${step} 步`;
  }
  return sessionStatus.value === 'cancelling' ? '正在停止' : '执行中';
});

const runtimeProgressPercent = computed(() => {
  const step = Number(activeSessionTimelineItem.value?.step ?? 0);
  const total = Number(activeSessionTimelineItem.value?.total ?? 0);
  if (step && total) {
    return Math.max(14, Math.min(100, Math.round((step / total) * 100)));
  }
  return sessionStatus.value === 'cancelling' ? 100 : 28;
});

const runtimeStripContext = computed(() => {
  const materialCount = Number(activeSessionTimelineItem.value?.materialCount ?? 0);
  if (materialCount > 0) {
    return `已处理 ${materialCount} 份资料`;
  }

  return hasPreviewChapter.value
    ? `当前预览第 ${props.selectedChapter.index} 章`
    : '当前结果会写回项目';
});

function runtimeStatusLabel(status) {
  const normalized = String(status ?? '').trim();
  if (normalized === 'running') {
    return sessionStatus.value === 'cancelling' ? '正在停止' : '正在运行';
  }
  if (normalized === 'failed') {
    return '运行失败';
  }
  if (normalized === 'cancelled') {
    return '已停止';
  }
  if (normalized === 'pending') {
    return '等待运行';
  }
  return '已完成';
}

function runtimeStatusDetail(item) {
  if (item.status === 'running') {
    return `已持续 ${sessionElapsedLabel.value}`;
  }

  const materialCount = Number(item.materialCount ?? 0);
  if (materialCount > 0) {
    return `${materialCount} 份资料`;
  }

  const changes = Array.isArray(item.changes) ? item.changes : [];
  if (changes.length > 0) {
    return changes.slice(0, 2).join('、');
  }

  return '';
}

function runtimeActionSummary(item) {
  const explicitSummary = String(item?.summary ?? '').trim();
  if (explicitSummary) {
    return explicitSummary;
  }

  const normalizedStatus = String(item?.status ?? '').trim();
  const isRunning = normalizedStatus === 'running';
  const actionKind = String(item?.actionKind ?? '').trim();
  const labels = {
    session_prepare: isRunning
      ? '正在读取项目设定、章节和资料库。'
      : '项目设定、章节和资料库已经读取。',
    session_plan: isRunning
      ? '正在整理本轮任务步骤。'
      : '本轮任务步骤已经整理完成。',
    review_knowledge: isRunning
      ? '正在筛选本轮需要引用的资料。'
      : '本轮引用资料已经整理完成。',
    brainstorm: isRunning
      ? '正在分析当前问题和可选方向。'
      : '讨论结果已经整理完成。',
    generate_architecture: isRunning
      ? '正在写入整书架构和章节目标。'
      : '整书架构和章节目标已经写回项目。',
    continue_project: isRunning
      ? '正在生成后续章节规划。'
      : '后续章节规划已经生成。',
    chapter_generate: isRunning
      ? '正在生成正文并执行章节检查。'
      : '正文已经生成并完成章节检查。',
    chapter_workflow: isRunning
      ? '正在推进章节工作流。'
      : '章节工作流已经完成。',
    chapter_review: isRunning
      ? '正在检查人物、情节和资料约束。'
      : '人物、情节和资料约束已经检查。',
    rewrite_chapter: isRunning
      ? '正在改写正文，并保留剧情事实和信息顺序。'
      : '正文改写已经完成。',
    skill_optimize: isRunning
      ? '正在整理可复用技能。'
      : '可复用技能已经整理完成。',
  };

  if (labels[actionKind]) {
    return labels[actionKind];
  }

  if (normalizedStatus === 'failed') {
    return '该步骤没有完成，请查看错误说明。';
  }
  if (normalizedStatus === 'cancelled') {
    return '该步骤已经停止。';
  }
  if (normalizedStatus === 'pending') {
    return '等待前面的步骤完成。';
  }
  return isRunning ? '正在处理当前任务。' : '';
}

const runtimeStatusItems = computed(() => {
  if (!sessionTimeline.value.length) {
    return [
      {
        id: 'runtime-status-thinking',
        status: 'running',
        label: sessionStatus.value === 'cancelling' ? '正在停止' : '正在思考',
        detail: `已持续 ${sessionElapsedLabel.value}`,
        summary: sessionStatus.value === 'cancelling'
          ? '正在通知后端停止后续动作。'
          : '正在建立任务状态。',
      },
    ];
  }

  return sessionTimeline.value.map((item, index) => ({
    id: `${item.step || index + 1}-${item.actionKind || 'action'}-${item.label || index}`,
    status: String(item.status ?? 'completed').trim() || 'completed',
    label: `${runtimeStatusLabel(item.status)} ${String(item.label ?? '').trim() || '执行步骤'}`,
    detail: runtimeStatusDetail(item),
    summary: runtimeActionSummary(item),
  }));
});

const sessionElapsedLabel = computed(() => {
  const totalSeconds = Math.max(0, Number(sessionElapsedSeconds.value) || 0);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
});

const activeDiscussionIsRunning = computed(() => (
  Boolean(
    props.project?.id
    && runningProjectId.value === props.project.id
    && runningThreadId.value
    && activeDiscussionThreadId.value === runningThreadId.value
    && (running.value || sessionStatus.value === 'cancelling')
  )
));

const otherDiscussionRunning = computed(() => (
  Boolean(
    runningProjectId.value
    && props.project?.id
    && runningThreadId.value
    && running.value
    && (
      runningProjectId.value !== props.project.id
      || activeDiscussionThreadId.value !== runningThreadId.value
    )
  )
));

function compactText(value, limit = 30) {
  const normalized = String(value ?? '').trim().replace(/\s+/g, ' ');
  if (!normalized) {
    return '';
  }

  return normalized.length > limit ? `${normalized.slice(0, limit)}…` : normalized;
}

function clearSessionElapsedTimer() {
  if (sessionElapsedTimer && typeof window !== 'undefined') {
    window.clearInterval(sessionElapsedTimer);
  }
  sessionElapsedTimer = null;
}

function startSessionElapsedTimer() {
  if (typeof window === 'undefined') {
    return;
  }

  clearSessionElapsedTimer();
  sessionElapsedSeconds.value = 0;
  const startedAt = Date.now();
  sessionElapsedTimer = window.setInterval(() => {
    sessionElapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000);
  }, 1000);
}

function currentStoryDocumentContent(documentKey) {
  return props.project?.story_overview?.documents?.find((item) => item.key === documentKey)?.content ?? '';
}

function currentArchitectureWorkspace() {
  return {
    core_seed: currentStoryDocumentContent('core_seed'),
    character_design: currentStoryDocumentContent('character_design'),
    world_building: currentStoryDocumentContent('world_building'),
    plot_structure: currentStoryDocumentContent('plot_structure'),
    character_state: currentStoryDocumentContent('character_state'),
    blueprint: currentStoryDocumentContent('blueprint'),
    global_summary: currentStoryDocumentContent('global_summary'),
  };
}

function normalizeArchitectureGenre() {
  return architectureForm.genre.trim() || props.project?.genre?.trim() || '未定题材';
}

function buildArchitectureGuidance() {
  const parts = [];

  if (discussionSummary.value) {
    parts.push(`讨论结论：\n${discussionSummary.value}`);
  }

  if (composerText.value.trim()) {
    parts.push(`补充要求：\n${composerText.value.trim()}`);
  }

  return parts.join('\n\n').trim();
}

function buildArchitectureExecutionPlan(guidance) {
  const instruction = guidance.trim() || '结合当前项目文档，完善整书架构。';
  const materials = Array.isArray(props.project?.story_overview?.materials)
    ? props.project.story_overview.materials
    : [];
  const obsidianCount = props.project?.story_overview?.obsidian?.included_count ?? 0;
  const knowledgeSourceCount = materials.length + obsidianCount;
  const actions = [];
  const steps = [];

  if (knowledgeSourceCount > 0) {
    actions.push({
      kind: 'review_knowledge',
      label: obsidianCount > 0 ? '分析资料库和 Obsidian' : '分析资料库',
      task_pack_kind: 'architecture',
      instruction,
    });
    const sourceLabels = [];
    if (materials.length > 0) {
      sourceLabels.push(`资料库 ${materials.length} 份`);
    }
    if (obsidianCount > 0) {
      sourceLabels.push(`Obsidian ${obsidianCount} 份`);
    }
    steps.push(`先整理${sourceLabels.join('、')}`);
  }

  actions.push({
    kind: 'generate_architecture',
    label: '生成整书架构',
    task_pack_kind: 'architecture',
    instruction,
  });
  steps.push('生成并写回整书架构');

  return {
    id: `plan-architecture-${Date.now()}`,
    title: '执行整书架构',
    summary: knowledgeSourceCount > 0 ? '先分析资料库和 Obsidian，再生成整书架构。' : '按当前讨论结论生成整书架构。',
    requires_confirmation: true,
    steps,
    actions,
  };
}

async function persistArchitectureProfile() {
  if (!props.project?.id) {
    return null;
  }

  const detail = await applyProjectArchitectureWorkspace(props.project.id, {
    workspace: currentArchitectureWorkspace(),
    genre: normalizeArchitectureGenre(),
    target_chapters: Math.min(1000, Math.max(1, Number(architectureForm.targetChapters) || 20)),
    target_words: Math.min(2000000, Math.max(1000, Number(architectureForm.targetWords) || 200000)),
  });
  emit('project-detail-updated', detail);
  return detail;
}

async function loadExecutionOptions(projectId) {
  if (!projectId) {
    styleOptions.value = [];
    xpPresetOptions.value = [];
    return;
  }

  try {
    const [styles, xpPresets] = await Promise.all([
      listStyles(),
      listXpPresets(),
    ]);
    if (props.project?.id !== projectId) {
      return;
    }
    styleOptions.value = Array.isArray(styles) ? styles : [];
    xpPresetOptions.value = Array.isArray(xpPresets) ? xpPresets : [];
  } catch {
    if (props.project?.id !== projectId) {
      return;
    }
    styleOptions.value = [];
    xpPresetOptions.value = [];
  }
}

watch(
  () => props.project,
  (project) => {
    architectureForm.genre = project?.genre?.trim() || '长篇小说';
    architectureForm.targetChapters = project?.target_chapters ?? 20;
    architectureForm.targetWords = project?.target_words ?? 200000;
  },
  { immediate: true },
);

watch(
  () => props.project?.id,
  () => {
    architectureConfirmOpen.value = false;
    planConfirmOpen.value = false;
    planPromptPreviews.value = [];
    planPromptPreviewLoading.value = false;
    planPromptPreviewError.value = '';
    planPromptPreviewMessage.value = '';
    forceDiscussionMode.value = false;
    architectureSessionActive.value = false;
  },
  { immediate: true },
);

watch(
  () => discussionSummary.value,
  (summary) => {
    if (summary) {
      forceDiscussionMode.value = false;
    }
  },
);

function scrollOperationStreamToLatest({ smooth = true } = {}) {
  const stream = operationStreamRef.value;
  if (!stream) {
    return;
  }

  const top = stream.scrollHeight;
  operationStreamNeedsLatestButton.value = false;
  if (typeof stream.scrollTo === 'function') {
    stream.scrollTo({
      top,
      behavior: smooth ? 'smooth' : 'auto',
    });
    return;
  }

  stream.scrollTop = top;
}

function operationStreamIsAtLatest(stream = operationStreamRef.value) {
  if (!stream) {
    return true;
  }

  return stream.scrollHeight - stream.clientHeight - stream.scrollTop <= 12;
}

function updateOperationStreamLatestButton() {
  const stream = operationStreamRef.value;
  operationStreamNeedsLatestButton.value = stream
    ? !operationStreamIsAtLatest(stream)
    : false;
}

function scheduleOperationStreamLatestButtonUpdate() {
  if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
    updateOperationStreamLatestButton();
    return;
  }

  if (operationStreamStateFrame && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(operationStreamStateFrame);
  }
  operationStreamStateFrame = window.requestAnimationFrame(() => {
    operationStreamStateFrame = 0;
    updateOperationStreamLatestButton();
  });
}

function scheduleOperationStreamScrollToLatest(options = {}) {
  void nextTick(() => {
    const run = () => {
      operationStreamScrollFrame = 0;
      scrollOperationStreamToLatest(options);
    };

    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
      run();
      return;
    }

    if (operationStreamScrollFrame && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(operationStreamScrollFrame);
    }
    operationStreamScrollFrame = window.requestAnimationFrame(run);
  });
}

function handleOperationStreamScroll() {
  scheduleOperationStreamLatestButtonUpdate();
}

function handleScrollToLatestClick() {
  scheduleOperationStreamScrollToLatest({ smooth: true });
}

function currentManualMemoryEntries() {
  return (props.project?.story_overview?.memory_entries ?? [])
    .filter((item) => (item.source ?? 'manual') !== 'auto')
    .map((item) => ({
      id: item.id,
      title: item.title ?? '',
      category: item.category ?? '目标',
      content: item.content ?? '',
    }));
}

function discussionSummarySaved(message) {
  return Boolean(
    discussionSummary.value
    && discussionSummary.value.trim() === String(message?.content ?? '').trim(),
  );
}

async function saveDiscussionSummary(message) {
  if (!props.project?.id || !message?.content?.trim() || discussionSavePending.value) {
    return;
  }

  discussionSavePending.value = true;
  discussionSaveMessage.value = '';

  const manualEntries = currentManualMemoryEntries();
  const nextEntry = {
    id: 'project-discussion-summary',
    title: '项目讨论结论',
    category: '目标',
    content: message.content.trim(),
  };
  const entries = discussionSummarySaved(message)
    ? manualEntries
    : [
      ...manualEntries
        .filter((item) => item.id !== nextEntry.id && item.title !== nextEntry.title)
        .slice(-29),
      nextEntry,
    ];

  try {
    const detail = await updateProjectMemory(props.project.id, { entries });
    emit('project-detail-updated', detail);
    discussionSaveMessage.value = '讨论结论已写入项目记忆';
    forceDiscussionMode.value = false;
  } catch (error) {
    runtimeError.value = error instanceof Error ? error.message : '讨论结论写入失败';
  } finally {
    discussionSavePending.value = false;
  }
}

async function runArchitectureExecution() {
  if (!props.project?.id || running.value) {
    return;
  }

  const guidance = buildArchitectureGuidance();
  if (!guidance) {
    runtimeError.value = '先把讨论结论讲清楚，或者在下面添加一条整书架构要求。';
    return;
  }
  architectureConfirmOpen.value = false;
  architectureSessionActive.value = true;

  try {
    await persistArchitectureProfile();
    await sendConversation({
      approvedPlan: buildArchitectureExecutionPlan(guidance),
      userContent: composerText.value.trim() || '确认执行整书架构。',
    });
  } catch (error) {
    runtimeError.value = error instanceof Error ? error.message : '整书架构生成失败';
  }
}

function openArchitectureConfirmModal() {
  if (!buildArchitectureGuidance()) {
    runtimeError.value = '先把讨论结论讲清楚，或者在输入框里添加一条整书架构要求。';
    return;
  }

  architectureSessionActive.value = true;
  runtimeError.value = '';
  architectureConfirmOpen.value = true;
}

function extractWritingPlanActions(plan) {
  return (Array.isArray(plan?.actions) ? plan.actions : [])
    .map((action, index) => ({ action, index }))
    .filter(({ action }) => (
      action?.kind === 'chapter_generate'
      || (action?.kind === 'chapter_workflow' && (action.mode || '') === 'draft')
    ));
}

function resetAgentSegmentState() {
  agentSegmentState.open = false;
  agentSegmentState.starting = false;
  agentSegmentState.running = false;
  agentSegmentState.accepting = false;
  agentSegmentState.planId = '';
  agentSegmentState.promptActions = [];
  agentSegmentState.actionCursor = 0;
  agentSegmentState.session = null;
  agentSegmentState.prompt = '';
  agentSegmentState.draftText = '';
  agentSegmentState.message = '';
  agentSegmentState.error = '';
  agentSegmentState.taskId = '';
  agentSegmentState.focusChapterId = '';
  agentSegmentState.streamResult = null;
}

function applyAgentSegmentSession(session, message = '') {
  agentSegmentState.session = session;
  agentSegmentState.prompt = session?.current_prompt?.editable_prompt || '';
  const segment = session?.segments?.find((item) => item.index === session.current_segment_index);
  agentSegmentState.draftText = segment?.draft_text || '';
  agentSegmentState.message = message || session?.message || '';
  agentSegmentState.error = '';
}

function agentSegmentPayloadFromAction(action) {
  return {
    project_id: props.project.id,
    chapter_id: action.chapter_id || props.selectedChapterId,
    instruction: String(action.instruction ?? '').trim(),
    target_words: Number(action.target_words || (action.kind === 'chapter_workflow' ? 1800 : 0)),
    style_name: String(action.style_name || executionOptions.styleName || '').trim(),
    xp_preset: String(action.xp_preset || executionOptions.xpPreset || '').trim(),
    characters_involved: String(action.characters_involved || executionOptions.charactersInvolved || '').trim(),
    key_items: String(action.key_items || executionOptions.keyItems || '').trim(),
    scene_location: String(action.scene_location || executionOptions.sceneLocation || '').trim(),
    time_constraint: String(action.time_constraint || executionOptions.timeConstraint || '').trim(),
    replace_existing: Boolean(action.replace_existing),
  };
}

async function startAgentSegmentAction(actionRef, message = '') {
  if (!actionRef?.action || !props.project?.id) {
    agentSegmentState.error = '缺少可执行的写正文动作。';
    return;
  }
  agentSegmentState.starting = true;
  agentSegmentState.error = '';
  agentSegmentState.message = message || '正在准备当前段提示词。';
  try {
    const session = await startChapterSegmentSession(agentSegmentPayloadFromAction(actionRef.action));
    applyAgentSegmentSession(session, session.message || '已准备当前段提示词。');
    agentSegmentState.focusChapterId = String(session.chapter_id || '');
    emit('focus-chapter', session.chapter_id);
  } catch (error) {
    agentSegmentState.error = error instanceof Error ? error.message : '创建逐段写作会话失败';
  } finally {
    agentSegmentState.starting = false;
    scheduleOperationStreamScrollToLatest({ smooth: true });
  }
}

async function startAgentSegmentWritingFlow() {
  if (!pendingPlan.value || running.value || agentSegmentBusy.value) {
    return;
  }
  const writingActions = extractWritingPlanActions(pendingPlan.value);
  if (writingActions.length === 0) {
    openPlanConfirmModal();
    return;
  }
  resetAgentSegmentState();
  agentSegmentState.open = true;
  agentSegmentState.planId = String(pendingPlan.value.id ?? '');
  agentSegmentState.promptActions = writingActions;
  agentSegmentState.actionCursor = 0;
  planConfirmOpen.value = false;
  await nextTick();
  await startAgentSegmentAction(writingActions[0]);
}

function openPlanConfirmModal() {
  if (!pendingPlan.value || running.value) {
    return;
  }
  if (pendingPlanHasWritingActions.value) {
    void startAgentSegmentWritingFlow();
    return;
  }

  planConfirmOpen.value = true;
  void loadPlanPromptPreviews();
}

function chapterTitleFromAction(action) {
  const chapter = (props.project?.chapters ?? []).find((item) => item.id === action?.chapter_id);
  if (!chapter) {
    return '章节提示词';
  }
  return `第 ${chapter.index} 章《${chapter.title}》`;
}

function chapterGeneratePreviewPayload(action) {
  return {
    project_id: props.project.id,
    chapter_id: action.chapter_id || props.selectedChapterId,
    instruction: String(action.instruction ?? '').trim(),
    target_words: Number(action.target_words || 0),
    style_name: String(action.style_name || executionOptions.styleName || '').trim(),
    xp_preset: String(action.xp_preset || executionOptions.xpPreset || '').trim(),
    characters_involved: String(action.characters_involved || executionOptions.charactersInvolved || '').trim(),
    key_items: String(action.key_items || executionOptions.keyItems || '').trim(),
    scene_location: String(action.scene_location || executionOptions.sceneLocation || '').trim(),
    time_constraint: String(action.time_constraint || executionOptions.timeConstraint || '').trim(),
    replace_existing: Boolean(action.replace_existing),
  };
}

function chapterWorkflowPreviewPayload(action) {
  return {
    project_id: props.project.id,
    chapter_id: action.chapter_id || props.selectedChapterId,
    mode: action.mode || 'draft',
    instruction: String(action.instruction ?? '').trim(),
    target_words: Number(action.target_words || 1800),
  };
}

async function loadPlanPromptPreviews() {
  planPromptPreviewMessage.value = '';
  planPromptPreviewError.value = '';
  planPromptPreviews.value = [];
  const promptActions = planPromptActions.value;
  if (!props.project?.id || promptActions.length === 0) {
    return;
  }

  planPromptPreviewLoading.value = true;
  try {
    const previews = await Promise.all(promptActions.map(async ({ action, index }) => {
      const payload = action.kind === 'chapter_generate'
        ? chapterGeneratePreviewPayload(action)
        : chapterWorkflowPreviewPayload(action);
      const preview = action.kind === 'chapter_generate'
        ? await previewChapterGeneratePrompt(payload)
        : await previewChapterWorkflowPrompt(payload);
      return {
        actionIndex: index,
        actionKind: action.kind,
        title: preview.title || chapterTitleFromAction(action),
        editablePrompt: preview.editable_prompt || '',
        promptText: preview.prompt_text || '',
      };
    }));
    planPromptPreviews.value = previews;
  } catch (error) {
    planPromptPreviewError.value = error instanceof Error ? error.message : '章节提示词预览生成失败';
  } finally {
    planPromptPreviewLoading.value = false;
  }
}

async function copyPlanPromptPreview(item) {
  const text = String(item?.editablePrompt ?? '').trim();
  if (!text) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    planPromptPreviewMessage.value = '提示词已复制';
  } catch {
    planPromptPreviewMessage.value = '复制失败，可以手动选择文本复制';
  }
}

async function copyAgentSegmentPrompt() {
  const text = String(agentSegmentState.prompt ?? '').trim();
  if (!text) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    agentSegmentState.message = '当前段提示词已复制';
  } catch {
    agentSegmentState.error = '复制失败，可以手动选择文本复制';
  }
}

function handleAgentSegmentStreamEvent(event) {
  if (event.event === 'started' && event.data && typeof event.data === 'object') {
    agentSegmentState.taskId = String(event.data.task_id ?? '');
    return;
  }
  if (event.event === 'progress' && event.data && typeof event.data === 'object') {
    agentSegmentState.message = String(event.data.message ?? '正在处理当前段');
    return;
  }
  if (event.event === 'result') {
    agentSegmentState.streamResult = event.data;
    return;
  }
  if (event.event === 'error' && event.data && typeof event.data === 'object') {
    agentSegmentState.error = String(event.data.message ?? '当前段生成失败');
  }
}

async function handleAgentSegmentGenerate(mode = 'draft') {
  const session = agentSegmentState.session;
  if (!session?.session_id || !props.project?.id) {
    agentSegmentState.error = '先准备当前段提示词。';
    return;
  }
  if (mode === 'polish' && !agentSegmentState.draftText.trim()) {
    agentSegmentState.error = '当前段还没有正文，先生成本段。';
    return;
  }
  agentSegmentState.running = true;
  agentSegmentState.error = '';
  agentSegmentState.streamResult = null;
  try {
    await streamChapterSegmentGenerate(
      {
        project_id: props.project.id,
        session_id: session.session_id,
        mode,
        prompt_override: mode === 'draft' ? agentSegmentState.prompt.trim() : '',
      },
      handleAgentSegmentStreamEvent,
    );
    if (agentSegmentState.error) {
      return;
    }
    if (agentSegmentState.streamResult?.session_id) {
      applyAgentSegmentSession(agentSegmentState.streamResult, agentSegmentState.streamResult.message || '当前段已生成。');
    }
  } catch (error) {
    agentSegmentState.error = error instanceof Error ? error.message : '当前段生成失败';
  } finally {
    agentSegmentState.running = false;
    scheduleOperationStreamScrollToLatest({ smooth: true });
  }
}

async function refreshProjectDetailAfterSegment(projectId) {
  if (!projectId) {
    return;
  }
  try {
    const detail = await getProjectDetail(projectId);
    if (props.project?.id === projectId) {
      emit('project-detail-updated', detail);
    }
  } catch (error) {
    agentSegmentState.message = `当前段已合并，但刷新项目详情失败：${error instanceof Error ? error.message : '未知错误'}`;
  }
}

function finishAgentSegmentWritingFlow(message) {
  const session = agentSegmentState.session;
  const title = session ? `第 ${session.chapter_index} 章《${session.chapter_title}》` : '当前章节';
  const assistantMessage = createMessage({
    role: 'assistant',
    mode: 'execution',
    task_pack_kind: 'continuation',
    content: message || `${title}逐段写作已完成，正文已合并到章节。`,
    changes: [`已更新${title}正文`],
  });
  const nextMessages = [...discussionHistory.value, assistantMessage];
  discussionHistory.value = nextMessages;
  pendingPlan.value = null;
  threadSuggestions.value = [];
  syncActiveDiscussionThread({
    messages: nextMessages,
    suggestions: [],
    pendingPlan: null,
    activate: true,
  });
  resetAgentSegmentState();
  scheduleOperationStreamScrollToLatest({ smooth: true });
}

async function handleAcceptAgentSegment() {
  const session = agentSegmentState.session;
  if (!session?.session_id || !props.project?.id) {
    agentSegmentState.error = '先准备当前段提示词。';
    return;
  }
  const acceptedText = agentSegmentState.draftText.trim();
  if (!acceptedText) {
    agentSegmentState.error = '当前段没有可合并正文。';
    return;
  }
  agentSegmentState.accepting = true;
  agentSegmentState.error = '';
  try {
    const nextSession = await acceptChapterSegment({
      project_id: props.project.id,
      session_id: session.session_id,
      accepted_text: acceptedText,
    });
    applyAgentSegmentSession(nextSession, nextSession.message || '当前段已合并到章节。');
    emit('focus-chapter', nextSession.chapter_id);
    await refreshProjectDetailAfterSegment(props.project.id);
    if (nextSession.status !== 'completed') {
      return;
    }

    const nextCursor = agentSegmentState.actionCursor + 1;
    if (nextCursor < agentSegmentState.promptActions.length) {
      agentSegmentState.actionCursor = nextCursor;
      await startAgentSegmentAction(agentSegmentState.promptActions[nextCursor], '上一章已完成，已准备下一章提示词。');
      return;
    }

    finishAgentSegmentWritingFlow(
      `${agentSegmentCurrentTitle.value}逐段写作已完成，正文已合并到章节。`,
    );
  } catch (error) {
    agentSegmentState.error = error instanceof Error ? error.message : '合并当前段失败';
  } finally {
    agentSegmentState.accepting = false;
  }
}

function planWithEditedPrompts(plan) {
  const previewByIndex = new Map(planPromptPreviews.value.map((item) => [item.actionIndex, item]));
  return {
    ...plan,
    actions: (plan.actions ?? []).map((action, index) => {
      const preview = previewByIndex.get(index);
      if (!preview) {
        return action;
      }
      return {
        ...action,
        prompt_override: String(preview.editablePrompt ?? '').trim(),
      };
    }),
  };
}

function buildDiscussionMessageId() {
  return `message-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function messageContentHash(value) {
  const source = String(value ?? '');
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `fnv1a-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

function summarizeThreadContent(value, limit = AGENT_THREAD_SUMMARY_LIMIT) {
  const normalized = String(value ?? '').trim().replace(/\s+/g, ' ');
  if (normalized.length <= limit) {
    return normalized;
  }
  const headLength = Math.max(120, Math.floor(limit * 0.54));
  const tailLength = Math.max(120, limit - headLength - 12);
  return `${normalized.slice(0, headLength).trimEnd()} …… ${normalized.slice(-tailLength).trimStart()}`;
}

function createMessage(seed = {}) {
  const executionTrace = Array.isArray(seed.execution_trace ?? seed.executionTrace)
    ? (seed.execution_trace ?? seed.executionTrace).map((item, index) => ({
      step: Number(item?.step ?? index + 1),
      actionKind: String(item?.action_kind ?? item?.actionKind ?? ''),
      label: String(item?.label ?? ''),
      taskPackKind: String(item?.task_pack_kind ?? item?.taskPackKind ?? ''),
      status: String(item?.status ?? 'completed'),
      summary: String(item?.summary ?? ''),
      changes: Array.isArray(item?.changes)
        ? item.changes.map((change) => String(change ?? '').trim()).filter(Boolean)
        : [],
      materialCount: typeof item?.material_count === 'number' ? item.material_count : null,
    }))
    : [];
  const eventBlocks = Array.isArray(seed.event_blocks ?? seed.eventBlocks)
    ? (seed.event_blocks ?? seed.eventBlocks).map((item, index) => ({
      step: Number(item?.step ?? index + 1),
      eventType: String(item?.event_type ?? item?.eventType ?? ''),
      actionKind: String(item?.action_kind ?? item?.actionKind ?? ''),
      title: String(item?.title ?? ''),
      status: String(item?.status ?? 'completed'),
      summary: String(item?.summary ?? ''),
    }))
    : [];
  const artifacts = Array.isArray(seed.artifacts)
    ? seed.artifacts.map((item, index) => ({
      id: String(item?.id ?? `artifact-${index + 1}`),
      kind: String(item?.kind ?? ''),
      title: String(item?.title ?? ''),
      summary: String(item?.summary ?? ''),
      contentPreview: String(item?.content_preview ?? item?.contentPreview ?? ''),
      metadata: item?.metadata && typeof item.metadata === 'object' ? item.metadata : {},
    }))
    : [];

  const content = String(seed.content ?? '');
  const contentHash = String(seed.content_hash ?? seed.contentHash ?? '') || messageContentHash(content);
  return {
    id: String(seed.id ?? '') || buildDiscussionMessageId(),
    role: seed.role === 'user' ? 'user' : seed.role === 'system' ? 'system' : 'assistant',
    content,
    contentHash,
    originalLength: Number(seed.original_length ?? seed.originalLength ?? content.length) || content.length,
    summary: String(seed.summary ?? '') || summarizeThreadContent(content),
    mode: String(seed.mode ?? ''),
    taskPackKind: String(seed.task_pack_kind ?? seed.taskPackKind ?? ''),
    plan: seed.plan ?? null,
    executionTrace,
    eventBlocks,
    artifacts,
    state: seed.state ?? null,
    suggestions: Array.isArray(seed.suggestions)
      ? seed.suggestions.map((item) => String(item ?? '').trim()).filter(Boolean)
      : [],
    changes: Array.isArray(seed.changes)
      ? seed.changes.map((item) => String(item ?? '').trim()).filter(Boolean)
      : [],
    canSaveDiscussionSummary: Boolean(seed.can_save_discussion_summary ?? seed.canSaveDiscussionSummary),
  };
}

function cleanThreadTitleCandidate(value) {
  if (!value) {
    return '';
  }

  let normalized = value
    .replace(/[#>*`]/g, ' ')
    .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();

  if (!normalized) {
    return '';
  }

  normalized = normalized
    .replace(/^(例如|比如|题材|方向|需求|目标|设定|背景|人物|风格|主题|备注)[：:]\s*/u, '')
    .replace(/^(我想写|我想做|我想|我准备写|我准备|我要写|我要|请帮我|帮我|先帮我|想写|写一部|写一本|做一部|做一个)\s*/u, '')
    .replace(/[，,]?(先帮我|先聊|先讨论|先判断|先看|聊清楚|理清楚|规划一下|规划清楚|给我一个方案|怎么处理|怎么推进).{0,24}$/u, '')
    .trim();

  const sentence = normalized
    .split(/[。！？!\?\n]/u)
    .map((item) => item.trim())
    .filter(Boolean)[0] ?? normalized;

  return sentence.replace(/^[，,:：\s]+|[，,:：\s]+$/gu, '').trim();
}

function threadTitleScore(value) {
  if (!value) {
    return -1;
  }

  let score = Math.min(value.length, 24);

  if (/^(继续|这个|这里|然后|现在|先|再|看看|处理一下|聊一下)/u.test(value)) {
    score -= 8;
  }

  if (/[《》“”"'A-Za-z0-9\u4e00-\u9fa5]/u.test(value)) {
    score += 2;
  }

  if (/主角|冲突|设定|章节|架构|悬疑|人物|世界|蓝图|剧情|风格/u.test(value)) {
    score += 4;
  }

  return score;
}

function buildDiscussionThreadTitle(messages) {
  const titleSources = [
    ...messages.filter((item) => item.role === 'user'),
    ...messages.filter((item) => item.role === 'assistant'),
  ];
  let bestCandidate = '';
  let bestScore = -1;

  for (const item of titleSources) {
    const candidate = cleanThreadTitleCandidate(item.content ?? '');
    if (candidate.length < 4) {
      continue;
    }

    const score = threadTitleScore(candidate);
    if (score > bestScore) {
      bestCandidate = candidate;
      bestScore = score;
    }
  }

  if (bestCandidate) {
    return compactText(bestCandidate, 22) || '新对话';
  }

  return '新对话';
}

function buildDiscussionThreadPreview(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const currentMessage = messages[index];
    if (currentMessage?.content?.trim()) {
      return compactText(currentMessage.content, 34) || '还没有内容';
    }
  }

  return '还没有内容';
}

function buildDiscussionThreadId() {
  return `thread-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function createDiscussionThread(seed = {}) {
  const messages = Array.isArray(seed.messages)
    ? seed.messages.map((item) => createMessage(item))
    : [];
  const suggestions = Array.isArray(seed.suggestions)
    ? seed.suggestions.map((item) => String(item ?? '').trim()).filter(Boolean)
    : [];

  return {
    id: String(seed.id ?? buildDiscussionThreadId()),
    title: String(seed.title ?? '') || buildDiscussionThreadTitle(messages),
    preview: String(seed.preview ?? '') || buildDiscussionThreadPreview(messages),
    updatedAt: String(seed.updatedAt ?? new Date().toISOString()),
    messages,
    suggestions,
    pendingPlan: seed.pendingPlan ?? null,
  };
}

function sortDiscussionThreads(threads) {
  return [...threads].sort((left, right) => (
    new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
  ));
}

function readLocalDiscussionThreadStore() {
  if (typeof window === 'undefined') {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(DISCUSSION_THREAD_STORE_KEY);
    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function emitDiscussionThreadState() {
  if (!props.project?.id) {
    return;
  }

  emit('discussion-thread-state-updated', {
    projectId: props.project.id,
    activeThreadId: activeDiscussionThreadId.value,
    threads: discussionThreads.value.map((item) => ({
      id: item.id,
      title: item.title,
      preview: item.preview,
      updatedAt: item.updatedAt,
    })),
  });
}

function writeLocalDiscussionThreadStore(projectId, payload) {
  if (typeof window === 'undefined' || !projectId) {
    return;
  }

  const store = readLocalDiscussionThreadStore();
  store[projectId] = payload;
  window.localStorage.setItem(DISCUSSION_THREAD_STORE_KEY, JSON.stringify(store));
}

function readLocalProjectThreads(projectId) {
  if (!projectId) {
    return null;
  }

  const store = readLocalDiscussionThreadStore();
  const payload = store[projectId];
  return payload && typeof payload === 'object' ? payload : null;
}

function serializeThreadMessage(message) {
  return {
    id: String(message.id ?? ''),
    role: message.role,
    content: String(message.content ?? ''),
    content_hash: String(message.contentHash ?? message.content_hash ?? '') || messageContentHash(message.content),
    original_length: Number(message.originalLength ?? message.original_length ?? String(message.content ?? '').length) || 0,
    summary: String(message.summary ?? '') || summarizeThreadContent(message.content),
    mode: String(message.mode ?? ''),
    task_pack_kind: String(message.taskPackKind ?? ''),
    plan: message.plan ?? null,
    execution_trace: Array.isArray(message.executionTrace)
      ? message.executionTrace.map((item) => ({
        step: Number(item?.step ?? 0),
        action_kind: String(item?.actionKind ?? item?.action_kind ?? ''),
        label: String(item?.label ?? ''),
        task_pack_kind: String(item?.taskPackKind ?? item?.task_pack_kind ?? ''),
        status: String(item?.status ?? 'completed'),
        summary: String(item?.summary ?? ''),
        changes: Array.isArray(item?.changes) ? item.changes : [],
        material_count: typeof item?.materialCount === 'number' ? item.materialCount : null,
      }))
      : [],
    event_blocks: Array.isArray(message.eventBlocks)
      ? message.eventBlocks.map((item) => ({
        event_type: String(item?.eventType ?? item?.event_type ?? ''),
        title: String(item?.title ?? ''),
        status: String(item?.status ?? 'completed'),
        summary: String(item?.summary ?? ''),
        step: Number(item?.step ?? 0),
        action_kind: String(item?.actionKind ?? item?.action_kind ?? ''),
      }))
      : [],
    artifacts: Array.isArray(message.artifacts)
      ? message.artifacts.map((item) => ({
        kind: String(item?.kind ?? ''),
        title: String(item?.title ?? ''),
        summary: String(item?.summary ?? ''),
        content_preview: String(item?.contentPreview ?? item?.content_preview ?? ''),
        metadata: item?.metadata && typeof item.metadata === 'object' ? item.metadata : {},
      }))
      : [],
    state: message.state ?? null,
    suggestions: Array.isArray(message.suggestions) ? message.suggestions : [],
    changes: Array.isArray(message.changes) ? message.changes : [],
    can_save_discussion_summary: Boolean(message.canSaveDiscussionSummary),
  };
}

function serializeThread(thread) {
  return {
    id: thread.id,
    title: thread.title,
    preview: thread.preview,
    updated_at: thread.updatedAt,
    messages: thread.messages.map((item) => serializeThreadMessage(item)),
    suggestions: Array.isArray(thread.suggestions) ? thread.suggestions : [],
    pending_plan: thread.pendingPlan ?? null,
  };
}

function buildPersistPayload(projectId = props.project?.id) {
  if (!projectId) {
    return null;
  }

  return {
    active_thread_id: activeDiscussionThreadId.value,
    threads: discussionThreads.value.map((item) => serializeThread(item)),
  };
}

function buildLocalPersistPayload(projectId = props.project?.id) {
  if (!projectId) {
    return null;
  }

  return {
    activeThreadId: activeDiscussionThreadId.value,
    threads: discussionThreads.value.map((item) => ({
      id: item.id,
      title: item.title,
      preview: item.preview,
      updatedAt: item.updatedAt,
      messages: item.messages.map((message) => serializeThreadMessage(message)),
      suggestions: Array.isArray(item.suggestions) ? item.suggestions : [],
      pendingPlan: item.pendingPlan ?? null,
    })),
  };
}

function serializeThreadStoreSnapshot(snapshot) {
  const normalized = normalizePersistedThreadStore(snapshot);
  return {
    active_thread_id: normalized.activeThreadId,
    threads: normalized.threads.map((item) => serializeThread(item)),
  };
}

function persistThreadStoreSnapshot(projectId, snapshot, options = {}) {
  if (!projectId || !snapshot) {
    return;
  }

  const normalized = normalizePersistedThreadStore(snapshot);
  const localStore = {
    activeThreadId: normalized.activeThreadId,
    threads: normalized.threads.map((item) => ({
      id: item.id,
      title: item.title,
      preview: item.preview,
      updatedAt: item.updatedAt,
      messages: item.messages.map((message) => serializeThreadMessage(message)),
      suggestions: Array.isArray(item.suggestions) ? item.suggestions : [],
      pendingPlan: item.pendingPlan ?? null,
    })),
  };

  writeLocalDiscussionThreadStore(projectId, localStore);

  if (options.skipRemote) {
    return;
  }

  queuedRemotePersist = {
    projectId,
    store: serializeThreadStoreSnapshot(normalized),
    localStore,
  };
  void flushRemoteThreadPersistQueue();
}

function updateThreadStoreSnapshot(snapshot, threadId, options = {}) {
  const normalized = normalizePersistedThreadStore(snapshot);
  const currentThread = normalized.threads.find((item) => item.id === threadId)
    ?? createDiscussionThread({ id: threadId });
  const nextMessages = (options.messages ?? currentThread.messages).map((item) => createMessage(item));
  const nextSuggestions = (options.suggestions ?? currentThread.suggestions)
    .map((item) => String(item ?? '').trim())
    .filter(Boolean);
  const nextPendingPlan = options.pendingPlan ?? currentThread.pendingPlan ?? null;
  const nextUpdatedAt = options.updatedAt ?? new Date().toISOString();
  const shouldActivate = options.activate ?? true;
  const remainingThreads = normalized.threads.filter((item) => item.id !== threadId);

  const nextThread = createDiscussionThread({
    ...currentThread,
    id: threadId,
    messages: nextMessages,
    suggestions: nextSuggestions,
    pendingPlan: nextPendingPlan,
    updatedAt: nextUpdatedAt,
  });

  return {
    activeThreadId: shouldActivate ? threadId : normalized.activeThreadId,
    threads: sortDiscussionThreads([nextThread, ...remainingThreads]).slice(0, MAX_DISCUSSION_THREADS),
  };
}

function normalizePersistedThread(item) {
  return createDiscussionThread({
    id: item.id,
    title: item.title,
    preview: item.preview,
    updatedAt: item.updated_at ?? item.updatedAt,
    messages: Array.isArray(item.messages) ? item.messages : [],
    suggestions: Array.isArray(item.suggestions) ? item.suggestions : [],
    pendingPlan: item.pending_plan ?? item.pendingPlan ?? null,
  });
}

function normalizePersistedThreadStore(payload) {
  const nextThreads = Array.isArray(payload?.threads)
    ? sortDiscussionThreads(
      payload.threads
        .map((item) => normalizePersistedThread(item))
        .slice(0, MAX_DISCUSSION_THREADS),
    )
    : [];

  const candidateActiveId = String(payload?.active_thread_id ?? payload?.activeThreadId ?? '');
  const activeThreadId = nextThreads.some((item) => item.id === candidateActiveId)
    ? candidateActiveId
    : nextThreads[0]?.id ?? '';

  return {
    activeThreadId,
    threads: nextThreads,
  };
}

function threadStoreLatestUpdatedAt(payload) {
  const threads = Array.isArray(payload?.threads) ? payload.threads : [];
  let latest = 0;
  for (const item of threads) {
    const raw = item?.updated_at ?? item?.updatedAt ?? '';
    const value = new Date(String(raw || '')).getTime();
    if (Number.isFinite(value) && value > latest) {
      latest = value;
    }
  }
  return latest;
}

async function flushRemoteThreadPersistQueue() {
  if (remotePersistInFlight) {
    return;
  }

  remotePersistInFlight = true;
  try {
    while (queuedRemotePersist) {
      const payload = queuedRemotePersist;
      queuedRemotePersist = null;
      try {
        await saveProjectAgentThreads(payload.projectId, payload.store);
      } catch {
        writeLocalDiscussionThreadStore(payload.projectId, payload.localStore);
      }
    }
  } finally {
    remotePersistInFlight = false;
  }
}

function persistDiscussionThreads(options = {}) {
  const projectId = options.projectId ?? props.project?.id;
  if (!projectId) {
    return;
  }

  const localStore = buildLocalPersistPayload(projectId);
  if (localStore) {
    writeLocalDiscussionThreadStore(projectId, localStore);
  }

  if (options.skipRemote) {
    return;
  }

  const remoteStore = buildPersistPayload(projectId);
  if (!remoteStore) {
    return;
  }

  queuedRemotePersist = {
    projectId,
    store: remoteStore,
    localStore,
  };
  void flushRemoteThreadPersistQueue();
}

function applyLoadedThreadStore(payload) {
  const normalized = normalizePersistedThreadStore(payload);
  discussionThreads.value = normalized.threads;

  const preferredThreadId = (
    props.project?.id
    && runningProjectId.value === props.project.id
    && runningThreadId.value
    && normalized.threads.some((item) => item.id === runningThreadId.value)
  )
    ? runningThreadId.value
    : normalized.activeThreadId;

  if (preferredThreadId) {
    applyDiscussionThread(preferredThreadId);
    return;
  }

  startDraftDiscussion();
}

async function loadDiscussionThreads(projectId) {
  if (!projectId) {
    discussionThreads.value = [];
    startDraftDiscussion();
    return;
  }

  const loadSequence = ++discussionLoadSequence;
  const localProjectThreads = readLocalProjectThreads(projectId);
  let payload = null;
  let shouldMigrateLocal = false;

  try {
    const remoteStore = await getProjectAgentThreads(projectId);
    if (loadSequence !== discussionLoadSequence) {
      return;
    }

    const remoteHasThreads = Array.isArray(remoteStore?.threads) && remoteStore.threads.length > 0;
    const localHasThreads = Array.isArray(localProjectThreads?.threads) && localProjectThreads.threads.length > 0;
    const shouldPreferLocal = localHasThreads && (
      (runningProjectId.value === projectId && runningThreadId.value)
      || threadStoreLatestUpdatedAt(localProjectThreads) > threadStoreLatestUpdatedAt(remoteStore)
    );

    if (localHasThreads && shouldPreferLocal) {
      payload = localProjectThreads;
      shouldMigrateLocal = !remoteHasThreads;
    } else if (remoteHasThreads) {
      payload = remoteStore;
    } else if (localHasThreads) {
      payload = localProjectThreads;
      shouldMigrateLocal = true;
    } else {
      payload = remoteStore;
    }
  } catch {
    if (loadSequence !== discussionLoadSequence) {
      return;
    }
    payload = localProjectThreads;
  }

  if (loadSequence !== discussionLoadSequence) {
    return;
  }

  applyLoadedThreadStore(payload);
  writeLocalDiscussionThreadStore(projectId, buildLocalPersistPayload(projectId));

  if (shouldMigrateLocal) {
    persistDiscussionThreads({ projectId });
  }
}

function applyDiscussionThread(threadId) {
  const matchedThread = discussionThreads.value.find((item) => item.id === threadId);
  if (!matchedThread) {
    return;
  }

  activeDiscussionThreadId.value = matchedThread.id;
  discussionHistory.value = matchedThread.messages.map((item) => createMessage(item));
  threadSuggestions.value = [...matchedThread.suggestions];
  pendingPlan.value = matchedThread.pendingPlan ?? null;
  if (!running.value) {
    resetAgentSession();
  }
  discussionSaveMessage.value = '';
  emitDiscussionThreadState();
  scheduleOperationStreamScrollToLatest({ smooth: false });
}

function startDraftDiscussion() {
  activeDiscussionThreadId.value = '';
  discussionHistory.value = [];
  threadSuggestions.value = [];
  pendingPlan.value = null;
  if (!running.value) {
    resetAgentSession();
  }
  discussionSaveMessage.value = '';
  emitDiscussionThreadState();
}

function syncDiscussionThread(threadId, options = {}) {
  if (!threadId) {
    return;
  }

  const currentThread = discussionThreads.value.find((item) => item.id === threadId);
  if (!currentThread) {
    return;
  }

  const nextMessages = (options.messages ?? discussionHistory.value).map((item) => createMessage(item));
  const nextSuggestions = (options.suggestions ?? threadSuggestions.value)
    .map((item) => String(item ?? '').trim())
    .filter(Boolean);
  const nextPendingPlan = options.pendingPlan ?? pendingPlan.value ?? null;
  const nextUpdatedAt = options.updatedAt ?? new Date().toISOString();
  const shouldActivate = options.activate ?? (!activeDiscussionThreadId.value || activeDiscussionThreadId.value === threadId);

  discussionThreads.value = sortDiscussionThreads(
    discussionThreads.value
      .map((item) => (item.id === currentThread.id
        ? createDiscussionThread({
          ...item,
          messages: nextMessages,
          suggestions: nextSuggestions,
          pendingPlan: nextPendingPlan,
          updatedAt: nextUpdatedAt,
        })
        : item
      ))
      .slice(0, MAX_DISCUSSION_THREADS),
  );

  if (shouldActivate) {
    activeDiscussionThreadId.value = threadId;
  }

  persistDiscussionThreads();
  emitDiscussionThreadState();
}

function syncActiveDiscussionThread(options = {}) {
  syncDiscussionThread(activeDiscussionThreadId.value, options);
}

function setComposerToolMessage(message, tone = 'success') {
  composerToolMessage.value = message;
  composerToolTone.value = tone;
}

function clearComposerReferences() {
  composerReferences.value = [];
  composerToolMessage.value = '';
  composerToolTone.value = 'success';
  if (composerFileInput.value) {
    composerFileInput.value.value = '';
  }
}

function composerReferenceNames(limit = 6) {
  return composerReferences.value
    .slice(0, limit)
    .map((item) => String(item.filename ?? '').trim())
    .filter(Boolean);
}

async function ensureComposerReferencesImported() {
  if (!props.project?.id) {
    return;
  }

  const pendingFiles = composerReferences.value.filter((item) => !item.imported);
  if (pendingFiles.length === 0) {
    return;
  }

  composerReferenceSyncing.value = true;
  try {
    const detail = await importProjectKnowledgeFiles(props.project.id, {
      files: pendingFiles.map((item) => item.payload),
    });
    emit('project-detail-updated', detail);

    const pendingIds = new Set(pendingFiles.map((item) => item.id));
    composerReferences.value = composerReferences.value.map((item) => (
      pendingIds.has(item.id)
        ? { ...item, imported: true }
        : item
    ));
    setComposerToolMessage(`已导入 ${pendingFiles.length} 份资料到资料库，发送时会自动检索使用。`);
  } catch (error) {
    setComposerToolMessage(error instanceof Error ? error.message : '参考资料导入失败', 'error');
    throw error;
  } finally {
    composerReferenceSyncing.value = false;
  }
}

function removeComposerReference(referenceId) {
  composerReferences.value = composerReferences.value.filter((item) => item.id !== referenceId);
  if (composerReferences.value.length === 0 && composerToolTone.value !== 'error') {
    composerToolMessage.value = '';
  }
}

function triggerComposerReferencePicker() {
  composerFileInput.value?.click();
}

async function handleComposerFilesSelected(event) {
  const input = event?.target;
  const files = await buildImportedFilePayloads(input?.files);
  if (input) {
    input.value = '';
  }

  if (!props.project?.id) {
    setComposerToolMessage('先打开一部作品，再添加参考资料。', 'error');
    return;
  }

  if (files.length === 0) {
    setComposerToolMessage('选中的文件没有可导入内容。', 'error');
    return;
  }

  const existingNames = new Set(
    composerReferences.value.map((item) => String(item.filename ?? '').trim()),
  );
  const nextFiles = files
    .filter((item) => !existingNames.has(item.filename))
    .map((item, index) => ({
      id: `composer-ref-${Date.now()}-${index}`,
      filename: item.filename,
      payload: item,
      imported: false,
    }));

  if (nextFiles.length === 0) {
    setComposerToolMessage('这些资料已经在本轮参考里了。', 'error');
    return;
  }

  composerReferences.value = [...composerReferences.value, ...nextFiles].slice(0, 20);
  setComposerToolMessage(`已选 ${nextFiles.length} 份资料，发送后会导入资料库并自动检索。`);
}

function createThreadIfNeeded(nextMessages) {
  let targetThreadId = activeDiscussionThreadId.value;

  if (!targetThreadId) {
    const nextThread = createDiscussionThread({
      messages: nextMessages,
      suggestions: [],
      pendingPlan: null,
    });
    discussionThreads.value = sortDiscussionThreads([nextThread, ...discussionThreads.value]).slice(0, MAX_DISCUSSION_THREADS);
    activeDiscussionThreadId.value = nextThread.id;
    targetThreadId = nextThread.id;
    persistDiscussionThreads();
    emitDiscussionThreadState();
  }

  return targetThreadId;
}

function statePills(state) {
  if (!state) {
    return [];
  }

  const items = [
    `讨论结论 ${state.discussion_ready ? '已就位' : '未锁定'}`,
    `架构 ${state.architecture_progress ?? 0}/5`,
  ];

  if (state.selected_chapter_index) {
    items.push(`当前章节 第 ${state.selected_chapter_index} 章`);
  }

  if (state.next_chapter_index) {
    items.push(`下一待写 第 ${state.next_chapter_index} 章`);
  }

  return items;
}

async function refreshProjectDetailAfterExecution(projectId, result) {
  if (!projectId || props.project?.id !== projectId) {
    return;
  }

  if (result?.project_detail?.id === projectId) {
    emit('project-detail-updated', result.project_detail);
    return;
  }

  if (result?.mode !== 'execution') {
    return;
  }

  try {
    const detail = await getProjectDetail(projectId);
    if (props.project?.id === projectId) {
      emit('project-detail-updated', detail);
    }
  } catch {
    // The conversation result is still shown; the next project refresh will pick up saved files.
  }
}

function isExplicitExecutionRequest(value) {
  const text = String(value ?? '').trim();
  if (!text) {
    return false;
  }

  if (/[?？]$/.test(text) || /(怎么|为什么|是否|能不能|可不可以|要不要|行不行|聊聊|讨论|建议|想法|看看|如果)/u.test(text)) {
    return false;
  }

  return /(续写|重写|改写|润色|修订|补|生成|整理|分析|检查|判断|拆|执行|写回|扩写|完善|补齐|重做|继续写|继续补|继续整理|重新做|重新弄)/u.test(text);
}

function shouldAutoExecutePlan(userContent, plan) {
  const actions = Array.isArray(plan?.actions) ? plan.actions : [];
  const hasChapterPrompt = actions.some((action) => (
    action?.kind === 'chapter_generate'
    || (action?.kind === 'chapter_workflow' && (action.mode || '') === 'draft')
  ));
  if (hasChapterPrompt) {
    return false;
  }
  return Boolean(plan?.requires_confirmation) && isExplicitExecutionRequest(userContent);
}

function messageModeLabel(message) {
  if (message.mode === 'plan') {
    return '执行计划';
  }
  if (message.mode === 'execution') {
    return '执行结果';
  }
  if (message.role === 'system') {
    return '系统';
  }
  return '';
}

function messageTimelineItems(message) {
  if (message.mode === 'plan') {
    return [];
  }

  if (isCompletedExecutionMessage(message)) {
    return [];
  }

  if (Array.isArray(message.executionTrace) && message.executionTrace.length > 0) {
    return message.executionTrace;
  }

  return [];
}

function isCompletedExecutionMessage(message) {
  return Boolean(message?.role === 'assistant' && message.mode === 'execution');
}

function hasCompletedExecutionAfter(messageIndex) {
  return discussionHistory.value
    .slice(messageIndex + 1)
    .some((message) => isCompletedExecutionMessage(message));
}

function shouldHideProcessMessage(message, messageIndex) {
  return Boolean(message?.role === 'assistant' && message.mode === 'plan' && hasCompletedExecutionAfter(messageIndex));
}

function messageEventBlocks(message) {
  const blocks = Array.isArray(message.eventBlocks) ? message.eventBlocks : [];
  return isCompletedExecutionMessage(message) ? [] : blocks;
}

function hasMessageThinkingProcess(message) {
  return messageTimelineItems(message).length > 0 || messageEventBlocks(message).length > 0;
}

function isPendingPlanMessage(message) {
  return Boolean(
    message.plan
    && pendingPlan.value
    && message.plan.id === pendingPlan.value.id
  );
}

function isPlanMessageActive(message) {
  return isPendingPlanMessage(message) && !running.value;
}

function planStatusLabel(message) {
  if (!message?.plan?.requires_confirmation || !isPendingPlanMessage(message)) {
    return '';
  }

  return running.value ? '执行中' : '等待确认';
}

function setComposerFromSuggestion(value) {
  clearComposerActiveSkill();
  composerText.value = String(value ?? '').trim();
}

function isSkillOptimizationSuggestion(value) {
  const text = String(value ?? '').trim();
  return /(用户技能|保存成技能|沉淀成技能|更新.*技能|优化.*技能)/u.test(text);
}

async function handleSuggestionClick(value) {
  const text = String(value ?? '').trim();
  if (!text) {
    return;
  }

  clearComposerActiveSkill();
  composerText.value = text;
  if (!isSkillOptimizationSuggestion(text)) {
    return;
  }

  if (activeDiscussionIsRunning.value || otherDiscussionRunning.value) {
    setComposerToolMessage('当前有任务在处理，结束后再整理技能。', 'error');
    return;
  }

  setComposerToolMessage('正在准备技能整理计划。');
  await sendConversation({ userContent: text });
}

function clearComposerActiveSkill() {
  composerActiveSkillId.value = '';
  composerActiveSkillPrompt.value = '';
}

function applyQuickAction(item) {
  composerText.value = String(item?.prompt ?? '').trim();
  composerActiveSkillId.value = String(item?.skillId ?? '').trim();
  composerActiveSkillPrompt.value = composerText.value;
}

function activeSkillIdsForComposer(userContent) {
  const skillId = composerActiveSkillId.value.trim();
  const prompt = composerActiveSkillPrompt.value.trim();
  const text = String(userContent ?? '').trim();
  if (!skillId || !prompt || !text.startsWith(prompt)) {
    return [];
  }
  return [skillId];
}

function buildMessagePayload(messages) {
  const headLength = 1800;
  const latestUserIndex = messages.reduce((latestIndex, item, index) => (
    item?.role === 'user' && String(item.content ?? '').trim() ? index : latestIndex
  ), -1);

  return messages
    .slice(-AGENT_REQUEST_MESSAGE_LIMIT)
    .map((item, slicedIndex, slicedMessages) => {
      const originalIndex = messages.length - slicedMessages.length + slicedIndex;
      const normalizedContent = String(item.content ?? '').trim();
      const contentLimit = originalIndex === latestUserIndex
        ? AGENT_REQUEST_CURRENT_USER_CONTENT_LIMIT
        : AGENT_REQUEST_MESSAGE_CONTENT_LIMIT;
      const tailLength = contentLimit - headLength - AGENT_REQUEST_OMITTED_MARKER.length;
      const content = normalizedContent.length > contentLimit
        ? `${normalizedContent.slice(0, headLength).trimEnd()}${AGENT_REQUEST_OMITTED_MARKER}${normalizedContent.slice(-tailLength).trimStart()}`
        : normalizedContent;

      return {
        id: String(item.id ?? ''),
        role: ['user', 'assistant', 'system'].includes(item.role) ? item.role : 'assistant',
        content,
        content_hash: String(item.contentHash ?? item.content_hash ?? '') || messageContentHash(item.content),
        compacted: content.length < normalizedContent.length,
        original_length: normalizedContent.length,
        summary: String(item.summary ?? '') || summarizeThreadContent(normalizedContent),
      };
    })
    .filter((item) => item.content);
}

function threadHistoryNeedsRemoteSnapshot(messages) {
  return messages.length > AGENT_REQUEST_MESSAGE_LIMIT
    || messages.some((item) => String(item.content ?? '').trim().length > AGENT_REQUEST_MESSAGE_CONTENT_LIMIT);
}

function focusChapterIdFromArtifacts(artifacts) {
  if (!Array.isArray(artifacts)) {
    return '';
  }

  for (const item of artifacts) {
    const chapterId = String(item?.metadata?.chapter_id ?? '').trim();
    if (chapterId) {
      return chapterId;
    }
  }

  return '';
}

function handleComposerKeydown(event) {
  if (event.key !== 'Enter') {
    return;
  }

  if (
    event.isComposing
    || event.shiftKey
    || event.altKey
    || event.ctrlKey
    || event.metaKey
  ) {
    return;
  }

  event.preventDefault();
  void handleComposerSubmit();
}

function handleStopRunningSession() {
  if (!activeDiscussionIsRunning.value) {
    setComposerToolMessage('当前执行在别的线程里，回到那条线程再停止。', 'error');
    return;
  }

  const stopped = stopSession();
  if (stopped) {
    setComposerToolMessage('已停止当前执行。');
  }
}

function togglePreviewPanel() {
  if (!canTogglePreview.value) {
    return;
  }

  previewCollapsed.value = !previewCollapsed.value;
  if (previewCollapsed.value) {
    agentPanelHidden.value = false;
  }
}

function hideAgentPanelForReading() {
  if (!canHideAgentPanel.value) {
    return;
  }

  previewCollapsed.value = false;
  agentPanelHidden.value = true;
}

function showAgentPanel() {
  agentPanelHidden.value = false;
  void nextTick(() => {
    scheduleOperationStreamLatestButtonUpdate();
  });
}

async function sendConversation(options = {}) {
  const approvedPlan = options.approvedPlan ?? null;
  const appendUserMessage = options.appendUserMessage ?? true;
  const targetProjectId = props.project?.id ?? '';
  const defaultUserContent = approvedPlan ? '确认执行。' : '';
  const userContent = String(options.userContent ?? composerText.value ?? defaultUserContent).trim()
    || defaultUserContent;
  const optionSkillIds = Array.isArray(options.activeSkillIds) ? options.activeSkillIds : null;
  const activeSkillIds = optionSkillIds
    ? optionSkillIds.map((item) => String(item ?? '').trim()).filter(Boolean)
    : activeSkillIdsForComposer(userContent);
  const baseMessages = Array.isArray(options.messages)
    ? options.messages.map((item) => createMessage(item))
    : discussionHistory.value.map((item) => createMessage(item));

  if (!targetProjectId) {
    runtimeError.value = '先打开一部作品。';
    return;
  }

  if (!approvedPlan && !userContent) {
    runtimeError.value = '先写清楚这一轮想处理什么。';
    return;
  }

  resetAgentSession();

  try {
    await ensureComposerReferencesImported();
  } catch (error) {
    runtimeError.value = error instanceof Error ? error.message : '参考资料导入失败';
    return;
  }

  const submittedReferenceNames = composerReferenceNames(8);
  const nextMessages = appendUserMessage && userContent
    ? [...baseMessages, createMessage({ role: 'user', content: userContent })]
    : [...baseMessages];
  const targetThreadId = createThreadIfNeeded(nextMessages);
  runningProjectId.value = targetProjectId;
  runningThreadId.value = targetThreadId;
  let backgroundThreadStore = buildLocalPersistPayload(targetProjectId)
    ?? { activeThreadId: targetThreadId, threads: [] };

  discussionHistory.value = nextMessages;
  if (!approvedPlan) {
    pendingPlan.value = null;
    threadSuggestions.value = [];
  }
  scheduleOperationStreamScrollToLatest({ smooth: true });
  syncDiscussionThread(targetThreadId, {
    messages: nextMessages,
    suggestions: approvedPlan ? threadSuggestions.value : [],
    pendingPlan: approvedPlan ? pendingPlan.value : null,
    activate: true,
  });
  backgroundThreadStore = updateThreadStoreSnapshot(backgroundThreadStore, targetThreadId, {
    messages: nextMessages,
    suggestions: approvedPlan ? threadSuggestions.value : [],
    pendingPlan: approvedPlan ? pendingPlan.value : null,
    activate: true,
  });
  persistThreadStoreSnapshot(targetProjectId, backgroundThreadStore);
  const needsRemoteSnapshot = threadHistoryNeedsRemoteSnapshot(nextMessages);
  try {
    await saveProjectAgentThreads(targetProjectId, serializeThreadStoreSnapshot(backgroundThreadStore));
  } catch (error) {
    writeLocalDiscussionThreadStore(targetProjectId, buildLocalPersistPayload(targetProjectId));
    if (needsRemoteSnapshot) {
      runtimeError.value = error instanceof Error
        ? `长线程保存失败，已停止本轮执行，避免只用压缩历史继续生成：${error.message}`
        : '长线程保存失败，已停止本轮执行，避免只用压缩历史继续生成。';
      runningProjectId.value = '';
      runningThreadId.value = '';
      if (appendUserMessage && userContent) {
        composerText.value = '';
        clearComposerActiveSkill();
        clearComposerReferences();
      }
      return;
    }
  }
  if (appendUserMessage && userContent) {
    composerText.value = '';
    clearComposerActiveSkill();
    clearComposerReferences();
  }

  try {
    const result = await runAgentSession(
      {
        project_id: targetProjectId,
        thread_id: targetThreadId,
        selected_chapter_id: props.selectedChapterId,
        messages: buildMessagePayload(nextMessages),
        reference_filenames: submittedReferenceNames,
        style_name: executionOptions.styleName.trim(),
        xp_preset: executionOptions.xpPreset.trim(),
        characters_involved: executionOptions.charactersInvolved.trim(),
        key_items: executionOptions.keyItems.trim(),
        scene_location: executionOptions.sceneLocation.trim(),
        time_constraint: executionOptions.timeConstraint.trim(),
        active_skill_ids: activeSkillIds,
        approved_plan: approvedPlan,
      },
    );

    if (sessionStatus.value === 'cancelled') {
      return;
    }

    await refreshProjectDetailAfterExecution(targetProjectId, result);

    const stillViewingTargetThread = props.project?.id === targetProjectId
      && activeDiscussionThreadId.value === targetThreadId;

    const assistantMessage = result
      ? createMessage({
        role: 'assistant',
        content: result.reply ?? '系统已完成处理。',
        mode: result.mode ?? '',
        task_pack_kind: result.task_pack_kind ?? '',
        plan: result.plan ?? null,
        execution_trace: result.execution_trace ?? [],
        event_blocks: result.event_blocks ?? [],
        artifacts: result.artifacts ?? [],
        state: result.state ?? null,
        suggestions: result.suggestions ?? [],
        changes: result.changes ?? [],
        can_save_discussion_summary: result.can_save_discussion_summary,
      })
      : null;

    if (!runtimeError.value && assistantMessage) {
      const completedMessages = [...nextMessages, assistantMessage];
      backgroundThreadStore = updateThreadStoreSnapshot(backgroundThreadStore, targetThreadId, {
        messages: completedMessages,
        suggestions: assistantMessage.suggestions ?? [],
        pendingPlan: assistantMessage.plan ?? null,
        activate: true,
      });
      persistThreadStoreSnapshot(targetProjectId, backgroundThreadStore);
      if (stillViewingTargetThread) {
        discussionHistory.value = completedMessages;
        pendingPlan.value = assistantMessage.plan ?? null;
        threadSuggestions.value = assistantMessage.suggestions ?? [];
        scheduleOperationStreamScrollToLatest({ smooth: true });
      }
      syncDiscussionThread(targetThreadId, {
        messages: completedMessages,
        suggestions: assistantMessage.suggestions ?? [],
        pendingPlan: assistantMessage.plan ?? null,
        activate: stillViewingTargetThread,
      });
      if (stillViewingTargetThread) {
        clearSessionTimeline();
      }
      const focusChapterId = focusChapterIdFromArtifacts(assistantMessage.artifacts);
      if (focusChapterId && stillViewingTargetThread) {
        emit('focus-chapter', focusChapterId);
      }
      if (!approvedPlan && shouldAutoExecutePlan(userContent, assistantMessage.plan)) {
        await sendConversation({
          approvedPlan: assistantMessage.plan,
          appendUserMessage: false,
        });
        return;
      }
      return;
    }

    if (!runtimeError.value) {
      runtimeError.value = '处理失败，未收到结果。';
    }
  } catch (error) {
    if (props.project?.id === targetProjectId && activeDiscussionThreadId.value === targetThreadId) {
      runtimeError.value = error instanceof Error ? error.message : '处理失败';
    }
  } finally {
    if (!running.value && runningThreadId.value === targetThreadId) {
      runningThreadId.value = '';
      runningProjectId.value = '';
    }
  }
}

async function handleComposerSubmit() {
  if (activeDiscussionIsRunning.value) {
    handleStopRunningSession();
    return;
  }

  if (otherDiscussionRunning.value) {
    setComposerToolMessage('当前有另一条线程在执行，回到那条线程停止，或者等它结束。', 'error');
    return;
  }

  if (agentSegmentState.open) {
    setComposerToolMessage('当前有逐段写作未完成，先关闭面板或接受当前段后再发新要求。', 'error');
    return;
  }

  await sendConversation();
}

async function handleConfirmPlan() {
  if (!pendingPlan.value) {
    return;
  }
  if (planConfirmDisabled.value) {
    return;
  }

  planConfirmOpen.value = false;
  await sendConversation({
    approvedPlan: planWithEditedPrompts(pendingPlan.value),
    userContent: '确认执行。',
  });
}

function handleCancelPlan() {
  if (!pendingPlan.value) {
    return;
  }

  planConfirmOpen.value = false;
  planPromptPreviews.value = [];
  planPromptPreviewError.value = '';
  planPromptPreviewMessage.value = '';
  resetAgentSegmentState();
  const systemMessage = createMessage({
    role: 'system',
    content: '当前计划已取消。你可以直接发新要求，我会按新的请求重新判断。',
  });
  const nextMessages = [...discussionHistory.value, systemMessage];
  discussionHistory.value = nextMessages;
  pendingPlan.value = null;
  threadSuggestions.value = [];
  scheduleOperationStreamScrollToLatest({ smooth: true });
  syncActiveDiscussionThread({
    messages: nextMessages,
    suggestions: [],
    pendingPlan: null,
    activate: true,
  });
}

function selectDiscussionThread(threadId) {
  composerText.value = '';
  clearComposerActiveSkill();
  clearComposerReferences();
  resetAgentSegmentState();
  applyDiscussionThread(threadId);
}

watch(
  () => props.project?.id,
  (projectId) => {
    composerText.value = '';
    clearComposerActiveSkill();
    clearComposerReferences();
    runtimeError.value = '';
    resetAgentSegmentState();
    architectureSessionActive.value = false;
    forceDiscussionMode.value = false;
    discussionSaveMessage.value = '';
    agentPanelHidden.value = false;
    executionOptions.styleName = '';
    executionOptions.xpPreset = '';
    executionOptions.charactersInvolved = '';
    executionOptions.keyItems = '';
    executionOptions.sceneLocation = '';
    executionOptions.timeConstraint = '';
    if (!running.value) {
      resetAgentSession();
    }
    void loadDiscussionThreads(projectId);
    void loadExecutionOptions(projectId);
  },
  { immediate: true },
);

watch(
  () => props.selectedChapterId,
  (chapterId, previousChapterId) => {
    if (!chapterId) {
      previewCollapsed.value = true;
      agentPanelHidden.value = false;
      resetAgentSegmentState();
      return;
    }

    if (chapterId !== previousChapterId) {
      previewCollapsed.value = false;
      if (agentSegmentState.open && agentSegmentState.focusChapterId === chapterId) {
        agentSegmentState.focusChapterId = '';
        return;
      }
      resetAgentSegmentState();
    }
  },
  { immediate: true },
);

watch(
  running,
  (isRunning) => {
    if (isRunning) {
      startSessionElapsedTimer();
      return;
    }

    clearSessionElapsedTimer();
  },
  { immediate: true },
);

watch(
  () => activeDiscussionIsRunning.value,
  (isActive) => {
    if (isActive) {
      scheduleOperationStreamScrollToLatest({ smooth: true });
    } else {
      scheduleOperationStreamLatestButtonUpdate();
    }
  },
);

watch(
  sessionTimeline,
  () => {
    if (activeDiscussionIsRunning.value) {
      scheduleOperationStreamScrollToLatest({ smooth: false });
    }
  },
);

watch(
  () => discussionHistory.value.length,
  () => {
    scheduleOperationStreamLatestButtonUpdate();
  },
);

watch(
  runtimeError,
  (message) => {
    if (message) {
      scheduleOperationStreamScrollToLatest({ smooth: true });
    }
  },
);

watch(
  () => props.conversationSessionKey,
  () => {
    composerText.value = '';
    clearComposerActiveSkill();
    clearComposerReferences();
    architectureConfirmOpen.value = false;
    planConfirmOpen.value = false;
    architectureSessionActive.value = false;
    startDraftDiscussion();
    forceDiscussionMode.value = false;
    discussionSaveMessage.value = '';
  },
);

watch(
  () => props.requestedDiscussionThreadId,
  (threadId) => {
    if (!threadId || threadId === activeDiscussionThreadId.value) {
      return;
    }

    if (discussionThreads.value.some((item) => item.id === threadId)) {
      selectDiscussionThread(threadId);
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  clearSessionElapsedTimer();
  if (
    operationStreamScrollFrame
    && typeof window !== 'undefined'
    && typeof window.cancelAnimationFrame === 'function'
  ) {
    window.cancelAnimationFrame(operationStreamScrollFrame);
    operationStreamScrollFrame = 0;
  }
  if (
    operationStreamStateFrame
    && typeof window !== 'undefined'
    && typeof window.cancelAnimationFrame === 'function'
  ) {
    window.cancelAnimationFrame(operationStreamStateFrame);
    operationStreamStateFrame = 0;
  }
});
</script>

<template>
  <section class="workspace-console">
    <div
      :class="[
        'workspace-top',
        {
          'workspace-top-embedded': embedded,
          'workspace-top-preview-hidden': !embedded && !showPreviewPanel,
          'workspace-top-agent-hidden': agentPanelHidden,
        },
      ]"
    >
      <ProjectWorkspaceSidebar
        v-if="!embedded && showPreviewPanel"
        class="preview-panel"
        :project="project"
        :selected-chapter-id="selectedChapterId"
        :agent-hidden="agentPanelHidden"
        @project-detail-updated="emit('project-detail-updated', $event)"
        @show-agent="showAgentPanel"
      />

      <section
        v-if="!agentPanelHidden"
        class="operation-panel"
      >
        <header class="operation-header operation-header-compact">
          <div class="operation-header-copy operation-header-copy-compact">
            <strong class="operation-header-title">Agent 对话</strong>
            <span class="operation-header-subtitle">
              {{
                showArchitectureStage
                  ? '整书架构讨论与执行'
                  : props.selectedChapter
                    ? `第 ${props.selectedChapter.index} 章`
                    : '项目讨论'
              }}
            </span>
          </div>

          <div class="operation-header-actions">
            <button
              v-if="canTogglePreview"
              class="secondary-button small-button operation-preview-toggle"
              type="button"
              @click="togglePreviewPanel"
            >
              {{ previewCollapsed ? '显示正文' : '收起正文' }}
            </button>
            <button
              v-if="canHideAgentPanel"
              class="secondary-button small-button operation-preview-toggle"
              type="button"
              @click="hideAgentPanelForReading"
            >
              隐藏 Agent
            </button>

            <span
              v-if="showArchitectureStage && !hasPendingPlanActions"
              class="operation-chip"
            >
              整书架构
            </span>
            <span
              v-else-if="activeDiscussionIsRunning"
              class="operation-chip"
            >
              处理中
            </span>
            <button
              v-if="showArchitectureStage && !hasPendingPlanActions"
              :disabled="running || !project?.id || otherDiscussionRunning"
              class="secondary-button small-button"
              data-testid="architecture-open-confirm-button"
              type="button"
              @click="openArchitectureConfirmModal"
            >
              {{ running ? '执行中…' : '执行整书架构' }}
            </button>
          </div>
        </header>

        <div
          ref="operationStreamRef"
          class="operation-stream"
          data-testid="agent-operation-stream"
          @scroll="handleOperationStreamScroll"
        >
          <article
            v-if="discussionHistory.length === 0"
            class="stream-card stream-card-assistant stream-card-empty"
          >
            <div class="stream-head">
              <span>AI</span>
              <em>等待输入</em>
            </div>
            <p v-if="showArchitectureStage">整书架构需要哪些变化？</p>
            <p v-else>今天处理哪部小说？</p>
            <div
              v-if="!showArchitectureStage"
              class="suggestion-row"
            >
              <button
                v-for="item in quickActionSeed"
                :key="item.id"
                class="suggestion-button"
                type="button"
                @click="applyQuickAction(item)"
              >
                {{ item.label }}
              </button>
            </div>
          </article>

          <template
            v-for="(item, index) in discussionHistory"
            :key="`${item.role}-${index}-${item.content.slice(0, 24)}`"
          >
            <article
              v-if="!shouldHideProcessMessage(item, index)"
              :class="[
                'stream-card',
                item.role === 'user'
                  ? 'stream-card-user'
                  : item.role === 'system'
                    ? 'stream-card-system'
                    : 'stream-card-assistant',
              ]"
            >
              <div class="stream-head">
                <span>{{ item.role === 'user' ? '你' : item.role === 'system' ? '系统' : 'AI' }}</span>
                <em v-if="messageModeLabel(item)">{{ messageModeLabel(item) }}</em>
              </div>

              <p class="message-content">{{ item.content }}</p>

              <div
                v-if="item.state && !isCompletedExecutionMessage(item)"
                class="state-pill-row"
              >
                <span
                  v-for="pill in statePills(item.state)"
                  :key="pill"
                  class="state-pill"
                >
                  {{ pill }}
                </span>
              </div>

              <AgentPlanCard
                v-if="item.plan && !isCompletedExecutionMessage(item)"
                :active="isPendingPlanMessage(item)"
                :plan="item.plan"
                :status-text="planStatusLabel(item)"
              >
                <template
                  v-if="isPlanMessageActive(item)"
                  #actions
                >
                  <button
                    class="primary-button small-button plan-execute-button"
                    data-testid="agent-plan-confirm-button"
                    :disabled="agentSegmentState.open || agentSegmentBusy"
                    type="button"
                    @click="openPlanConfirmModal"
                  >
                    {{ pendingPlanHasWritingActions ? agentSegmentState.open ? '逐段写作中' : '开始逐段写作' : '执行当前计划' }}
                  </button>
                </template>
              </AgentPlanCard>

              <section
                v-if="isPlanMessageActive(item) && agentSegmentState.open && agentSegmentState.planId === item.plan?.id"
                class="chapter-prompt-preview agent-segment-panel"
                data-testid="agent-chapter-segment-panel"
              >
                <div class="chapter-prompt-preview-head">
                  <div>
                    <strong>当前段提示词</strong>
                    <p>
                      {{ agentSegmentCurrentTitle }}
                      <span v-if="agentSegmentProgressLabel"> · {{ agentSegmentProgressLabel }}</span>
                      <span v-if="agentSegmentWordLabel"> · {{ agentSegmentWordLabel }}</span>
                    </p>
                  </div>
                  <button
                    class="secondary-button small-button"
                    :disabled="agentSegmentBusy"
                    data-testid="agent-chapter-segment-close-button"
                    type="button"
                    @click="resetAgentSegmentState"
                  >
                    关闭
                  </button>
                </div>

                <p
                  v-if="agentSegmentState.error"
                  class="prompt-preview-error"
                  data-testid="agent-chapter-segment-error"
                >
                  {{ agentSegmentState.error }}
                </p>
                <p
                  v-else-if="agentSegmentState.message"
                  class="prompt-preview-message"
                  data-testid="agent-chapter-segment-message"
                >
                  {{ agentSegmentState.message }}
                </p>

                <div
                  v-if="agentSegmentState.session?.segments?.length"
                  class="agent-segment-list"
                >
                  <span
                    v-for="segment in agentSegmentState.session.segments"
                    :key="segment.index"
                    :class="[
                      'agent-segment-pill',
                      {
                        'agent-segment-pill-active': segment.index === agentSegmentState.session.current_segment_index,
                        'agent-segment-pill-done': segment.status === 'accepted',
                      },
                    ]"
                  >
                    {{ segment.title || `第 ${segment.index} 段` }}
                    · {{ segment.accepted_word_count || segment.draft_word_count || segment.target_words || 0 }} 字
                  </span>
                </div>

                <label
                  v-if="!isAgentSegmentCompleted"
                  class="segment-editor-field"
                >
                  <span>当前段提示词</span>
                  <textarea
                    v-model="agentSegmentState.prompt"
                    class="chapter-prompt-editor"
                    data-testid="agent-chapter-segment-prompt-editor"
                    rows="12"
                  />
                </label>

                <div
                  v-if="!isAgentSegmentCompleted"
                  class="architecture-confirm-actions agent-segment-actions"
                >
                  <button
                    class="secondary-button"
                    type="button"
                    @click="copyAgentSegmentPrompt"
                  >
                    复制提示词
                  </button>
                  <button
                    :disabled="agentSegmentBusy || !agentSegmentState.prompt.trim()"
                    class="primary-button"
                    data-testid="agent-chapter-segment-generate-button"
                    type="button"
                    @click="handleAgentSegmentGenerate('draft')"
                  >
                    {{ agentSegmentState.running ? '生成中…' : activeAgentSegment?.draft_text ? '重新生成本段' : '生成本段' }}
                  </button>
                  <button
                    :disabled="agentSegmentBusy || !agentSegmentState.draftText.trim()"
                    class="secondary-button"
                    type="button"
                    @click="handleAgentSegmentGenerate('polish')"
                  >
                    润色本段
                  </button>
                </div>

                <label
                  v-if="agentSegmentState.draftText"
                  class="segment-editor-field"
                >
                  <span>当前段正文</span>
                  <textarea
                    v-model="agentSegmentState.draftText"
                    class="chapter-prompt-editor segment-draft-editor"
                    data-testid="agent-chapter-segment-draft-editor"
                    rows="16"
                  />
                </label>

                <div
                  v-if="agentSegmentState.draftText && !isAgentSegmentCompleted"
                  class="architecture-confirm-actions agent-segment-actions"
                >
                  <button
                    :disabled="agentSegmentBusy"
                    class="primary-button"
                    data-testid="agent-chapter-segment-accept-button"
                    type="button"
                    @click="handleAcceptAgentSegment"
                  >
                    {{ agentSegmentState.accepting ? '合并中…' : '接受并合并到章节' }}
                  </button>
                </div>
              </section>

              <section
                v-if="hasMessageThinkingProcess(item)"
                class="thinking-process"
                data-testid="agent-thinking-process"
              >
                <div class="thinking-process-head">
                  <span>思考过程</span>
                </div>

                <AgentActionTimeline
                  v-if="messageTimelineItems(item).length"
                  :items="messageTimelineItems(item)"
                />

                <AgentEventBlockSummary
                  v-if="messageEventBlocks(item).length"
                  :blocks="messageEventBlocks(item)"
                />
              </section>

              <AgentArtifactSummary
                v-if="item.artifacts?.length"
                :artifacts="item.artifacts"
                @open-obsidian-maintenance="openObsidianMaintenanceFromArtifact"
              />

              <div
                v-if="item.canSaveDiscussionSummary"
                class="message-action-row"
              >
                <button
                  :disabled="discussionSavePending || discussionSummarySaved(item)"
                  class="secondary-button small-button"
                  type="button"
                  @click="saveDiscussionSummary(item)"
                >
                  {{ discussionSummarySaved(item) ? '已记为讨论结论' : discussionSavePending ? '写入中…' : '记为讨论结论' }}
                </button>
              </div>

              <div
                v-if="item.suggestions?.length"
                class="suggestion-row"
              >
                <button
                  v-for="suggestion in item.suggestions"
                  :key="suggestion"
                  class="suggestion-button"
                  type="button"
                  @click="handleSuggestionClick(suggestion)"
                >
                  {{ suggestion }}
                </button>
              </div>
            </article>
          </template>

          <article
            v-if="activeDiscussionIsRunning"
            class="stream-card stream-card-assistant stream-card-runtime"
            data-testid="agent-runtime-message"
          >
            <div class="stream-head">
              <span>AI</span>
              <em>{{ sessionStatus === 'cancelling' ? '停止中' : '正在执行' }}</em>
            </div>

            <div class="runtime-message-head">
              <strong>{{ runtimeStripTitle }}</strong>
              <span>{{ runtimeProgressText }} · 已持续 {{ sessionElapsedLabel }}</span>
            </div>

            <p class="runtime-message-copy">
              <span>{{ runtimeStripLead }}</span>
              <span>{{ runtimeStripContext }}</span>
            </p>

            <section
              class="thinking-process thinking-process-runtime"
              data-testid="agent-runtime-thinking-process"
            >
              <div class="thinking-process-head">
                <span>思考过程</span>
              </div>

              <div
                class="runtime-status-list"
                data-testid="agent-runtime-status-list"
              >
                <div
                  v-for="item in runtimeStatusItems"
                  :key="item.id"
                  :class="['runtime-status-row', `runtime-status-row-${item.status}`]"
                  data-testid="agent-runtime-status-row"
                >
                  <span
                    class="runtime-status-icon"
                    aria-hidden="true"
                  ></span>
                  <div class="runtime-status-copy">
                    <div class="runtime-status-line">
                      <strong>{{ item.label }}</strong>
                      <span v-if="item.detail">{{ item.detail }}</span>
                    </div>
                    <p v-if="item.summary">{{ item.summary }}</p>
                  </div>
                </div>
              </div>
            </section>
          </article>

          <p
            v-if="discussionSaveMessage"
            class="stream-note"
          >
            {{ discussionSaveMessage }}
          </p>

          <p
            v-if="runtimeError"
            class="stream-error"
          >
            {{ runtimeError }}
          </p>

        </div>

        <button
          v-if="!agentPanelHidden && operationStreamNeedsLatestButton"
          aria-label="滑到最新消息"
          class="latest-scroll-button"
          data-testid="agent-scroll-to-latest-button"
          type="button"
          @click="handleScrollToLatestClick"
        >
          <span aria-hidden="true">↓</span>
        </button>

      </section>
    </div>

    <section
      v-if="activeDiscussionIsRunning"
      :class="[
        'runtime-strip',
        { 'runtime-strip-cancelling': sessionStatus === 'cancelling' },
      ]"
    >
      <div class="runtime-strip-glow"></div>

      <div class="runtime-strip-content">
        <div class="runtime-strip-head">
          <div class="runtime-strip-meta">
            <span class="runtime-strip-badge">{{ runtimeProgressText }}</span>
            <span class="runtime-strip-elapsed">已持续 {{ sessionElapsedLabel }}</span>
          </div>
        <button
          class="runtime-strip-stop"
          type="button"
          @click="handleStopRunningSession"
        >
          {{ sessionStatus === 'cancelling' ? '停止中…' : '停止' }}
        </button>
        </div>

        <div class="runtime-strip-body">
          <strong class="runtime-strip-title">{{ runtimeStripTitle }}</strong>
          <div class="runtime-strip-copy">
            <span class="runtime-strip-lead">{{ runtimeStripLead }}</span>
            <span class="runtime-strip-context">{{ runtimeStripContext }}</span>
          </div>
        </div>

        <div class="runtime-strip-track">
          <span
            class="runtime-strip-fill"
            :style="{ width: `${runtimeProgressPercent}%` }"
          ></span>
        </div>
      </div>
    </section>

    <footer
      v-if="!agentPanelHidden"
      :class="['composer-shell', { 'composer-shell-architecture': showArchitectureStage }]"
    >
      <input
        ref="composerFileInput"
        :accept="importAcceptValue()"
        class="composer-file-input"
        type="file"
        multiple
        @change="handleComposerFilesSelected"
      >

      <div
        v-if="composerReferences.length > 0"
        class="reference-row"
      >
        <button
          v-for="item in composerReferences"
          :key="item.id"
          class="reference-chip"
          type="button"
          @click="removeComposerReference(item.id)"
        >
          {{ item.filename }}
        </button>
      </div>

      <textarea
        v-model="composerText"
        :class="['composer-input', { 'composer-input-architecture': showArchitectureStage }]"
        :data-testid="showArchitectureStage ? 'architecture-composer-input' : 'workspace-composer-input'"
        :disabled="composerDisabled"
        :placeholder="showArchitectureStage
          ? '可添加整书架构要求，例如前几章先立住、哪条线优先展开'
          : props.selectedChapter
            ? `例如：先看当前状态，再续写第 ${props.selectedChapter.index} 章。`
            : '例如：先看当前状态，再告诉我这本书现在最该推进什么。'"
        @keydown="handleComposerKeydown"
      />

      <div class="composer-bottom">
        <div class="composer-bottom-left">
          <button
            :disabled="composerDisabled"
            class="composer-attach-button"
            :title="composerReferences.length > 0 ? `已选 ${composerReferences.length} 份资料` : '上传资料到资料库'"
            type="button"
            @click="triggerComposerReferencePicker"
          >
            <span
              aria-hidden="true"
              class="composer-attach-icon"
            >
              +
            </span>
            <span class="composer-attach-label">
              {{ composerReferences.length > 0 ? `已选 ${composerReferences.length} 份资料` : '上传资料' }}
            </span>
          </button>

          <p
            :class="[
              composerToolMessage
                ? 'composer-tool-message'
                : 'composer-tip',
              composerToolMessage && composerToolTone === 'error'
                ? 'composer-tool-message-error'
                : composerToolMessage
                  ? 'composer-tool-message-success'
                  : '',
            ]"
          >
            {{
              composerToolMessage
                || (showArchitectureStage
                  ? '继续添加整书架构要求。'
                  : '可附加参考资料。')
            }}
          </p>
        </div>

        <div class="composer-bottom-right">
          <button
            :disabled="!project?.id"
            :class="['composer-model-button', { 'composer-model-button-architecture': showArchitectureStage }]"
            type="button"
            @click="emit('open-model-settings')"
          >
            <span
              :class="[
                'composer-model-indicator',
                { 'composer-model-indicator-busy': running || composerReferenceSyncing },
              ]"
            ></span>
            <span class="composer-model-name">{{ modelName }}</span>
            <span class="composer-model-caret">⌄</span>
          </button>

          <button
            :aria-label="sendButtonLabel"
            :disabled="composerReferenceSyncing || !project?.id || sessionStatus === 'cancelling' || otherDiscussionRunning"
            :title="sendButtonLabel"
            :class="['composer-submit-button', { 'composer-submit-button-running': activeDiscussionIsRunning }]"
            :data-testid="showArchitectureStage ? 'architecture-submit-button' : undefined"
            type="button"
            @click="handleComposerSubmit"
          >
            <svg
              v-if="activeDiscussionIsRunning"
              aria-hidden="true"
              class="composer-submit-stop-icon"
              viewBox="0 0 16 16"
            >
              <rect
                x="4.2"
                y="4.2"
                width="7.6"
                height="7.6"
                rx="1.6"
                fill="currentColor"
              />
            </svg>
            <svg
              v-else
              aria-hidden="true"
              class="composer-submit-icon"
              fill="none"
              viewBox="0 0 20 20"
            >
              <path
                d="M10 15V5"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2.2"
              />
              <path
                d="M6.25 8.75L10 5L13.75 8.75"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2.2"
              />
            </svg>
          </button>
        </div>
      </div>

    </footer>

    <Teleport to="body">
      <div
        v-if="architectureConfirmOpen"
        class="modal-overlay"
        @click.self="architectureConfirmOpen = false"
      >
        <section
          class="modal-dialog modal-dialog-narrow"
          role="dialog"
          aria-modal="true"
          aria-label="确认执行整书架构"
        >
          <header class="modal-header">
            <div>
              <p class="stage-kicker">执行确认</p>
              <h3>执行整书架构</h3>
            </div>

            <button
              class="modal-close"
              type="button"
              @click="architectureConfirmOpen = false"
            >
              关闭
            </button>
          </header>

          <div class="architecture-confirm-stack">
            <p class="architecture-confirm-copy">
              会按照当前讨论结论执行整书架构。执行中显示状态，完成后聊天窗口只保留结果和说明。
            </p>

            <label class="execution-field">
              <span>题材</span>
              <input
                v-model="architectureForm.genre"
                type="text"
                placeholder="例如：长篇小说"
              >
            </label>

            <label class="execution-field">
              <span>目标章节数</span>
              <input
                v-model.number="architectureForm.targetChapters"
                min="1"
                max="1000"
                type="number"
              >
            </label>

            <label class="execution-field">
              <span>目标字数</span>
              <input
                v-model.number="architectureForm.targetWords"
                min="1000"
                max="2000000"
                step="1000"
                type="number"
              >
            </label>

            <div class="architecture-confirm-actions">
              <button
                class="secondary-button"
                type="button"
                @click="architectureConfirmOpen = false"
              >
                取消
              </button>
              <button
                :disabled="running"
                class="primary-button"
                type="button"
                @click="runArchitectureExecution"
              >
                {{ running ? '执行中…' : '确认执行' }}
              </button>
            </div>
          </div>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="planConfirmOpen && pendingPlan"
        class="modal-overlay"
        data-testid="agent-plan-confirm-modal"
        @click.self="planConfirmOpen = false"
      >
        <section
          class="modal-dialog modal-dialog-narrow"
          role="dialog"
          aria-modal="true"
          aria-label="确认执行计划"
        >
          <header class="modal-header">
            <div>
              <p class="stage-kicker">执行确认</p>
              <h3>{{ pendingPlan.title || '确认执行当前计划' }}</h3>
            </div>

            <button
              class="modal-close"
              type="button"
              @click="planConfirmOpen = false"
            >
              关闭
            </button>
          </header>

          <div class="architecture-confirm-stack">
            <p class="architecture-confirm-copy">
              执行中显示状态，完成后聊天窗口只保留结果和说明。
            </p>

            <ol
              v-if="pendingPlan.steps?.length"
              class="plan-list plan-list-modal"
            >
              <li
                v-for="step in pendingPlan.steps"
                :key="step"
              >
                {{ step }}
              </li>
            </ol>

            <section
              v-if="planPromptActions.length"
              class="chapter-prompt-preview"
              data-testid="agent-plan-prompt-preview"
            >
              <div class="chapter-prompt-preview-head">
                <div>
                  <strong>章节提示词</strong>
                  <p>确认后将使用这里编辑后的内容生成正文。</p>
                </div>
                <span v-if="planPromptPreviewLoading">读取中…</span>
              </div>
              <p
                v-if="planPromptPreviewError"
                class="prompt-preview-error"
                data-testid="agent-plan-prompt-error"
              >
                {{ planPromptPreviewError }}
              </p>
              <p
                v-else-if="planPromptPreviewMessage"
                class="prompt-preview-message"
                data-testid="agent-plan-prompt-message"
              >
                {{ planPromptPreviewMessage }}
              </p>
              <article
                v-for="item in planPromptPreviews"
                :key="item.actionIndex"
                class="chapter-prompt-preview-item"
              >
                <div class="chapter-prompt-preview-item-head">
                  <strong>{{ item.title }}</strong>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="copyPlanPromptPreview(item)"
                  >
                    复制提示词
                  </button>
                </div>
                <textarea
                  v-model="item.editablePrompt"
                  class="chapter-prompt-editor"
                  data-testid="agent-plan-prompt-editor"
                  rows="12"
                />
              </article>
            </section>

            <div class="architecture-confirm-actions">
              <button
                class="secondary-button"
                type="button"
                @click="handleCancelPlan"
              >
                取消
              </button>
              <button
                :disabled="planConfirmDisabled"
                class="primary-button"
                data-testid="agent-plan-confirm-execute-button"
                type="button"
                @click="handleConfirmPlan"
              >
                {{ running ? '执行中…' : planPromptPreviewLoading ? '读取提示词…' : '确认执行' }}
              </button>
            </div>
          </div>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.workspace-console,
.workspace-top,
.operation-panel,
.operation-stream {
  min-height: 0;
}

.workspace-console {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  height: 100%;
}

.workspace-top {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(300px, 0.86fr) minmax(520px, 1.14fr);
  gap: 18px;
  width: 100%;
  min-height: 0;
}

.workspace-top-preview-hidden,
.workspace-top-embedded,
.workspace-top-agent-hidden {
  grid-template-columns: minmax(0, 1fr);
}

.operation-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0;
}

.operation-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  width: min(920px, 100%);
  margin: 0 auto;
  padding: 0 0 10px;
  border-bottom: 0;
}

.operation-header-compact {
  min-height: 40px;
}

.operation-header-copy {
  display: grid;
  gap: 4px;
}

.operation-header-copy-compact {
  min-width: 0;
}

.operation-kicker {
  color: #8f5a1d;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.operation-header-title {
  color: #1f2328;
  font-size: 14px;
  line-height: 1.2;
}

.operation-header-subtitle {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.5;
}

.operation-hint {
  margin: 0;
  color: #57606a;
  font-size: 13px;
  line-height: 1.7;
}

.operation-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.operation-header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.operation-chip,
.state-pill {
  border-radius: 999px;
  padding: 5px 10px;
  background: #e8f0fe;
  color: #1d4ed8;
  font-size: 12px;
}

.operation-chip-muted {
  background: #f4f6f8;
  color: #68707c;
}

.operation-preview-toggle {
  background: #f8fafc;
}

.architecture-stage-card,
.architecture-status-card {
  margin-top: 12px;
  border: 1px solid #dbe2ec;
  border-radius: 16px;
  padding: 14px 16px;
  background: #ffffff;
}

.architecture-stage-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.architecture-stage-head strong {
  color: #1f2328;
  font-size: 14px;
}

.architecture-stage-head p {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.7;
}

.architecture-back-button {
  flex: 0 0 auto;
}

.architecture-params-card {
  margin-top: 12px;
  padding: 14px;
  border-radius: 16px;
  border-color: #dbe2ec;
  background: #ffffff;
}

.architecture-status-card {
  display: grid;
  gap: 10px;
}

.architecture-task-note {
  margin: 0;
  color: #7d8790;
  font-size: 12px;
}

.operation-action-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.quick-action-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.execution-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #dce6f4;
  border-radius: 14px;
  background: #f8fbff;
}

.execution-options.architecture-params-card {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.execution-field {
  display: grid;
  gap: 6px;
}

.execution-field span {
  color: #6b7280;
  font-size: 12px;
}

.execution-field input,
.execution-field select {
  width: 100%;
  border: 1px solid #d0d7de;
  border-radius: 10px;
  padding: 9px 11px;
  background: #ffffff;
  color: #1f2328;
  font-size: 13px;
}

.quick-action-button,
.suggestion-button,
.reference-chip {
  border: 1px solid #d6e3f5;
  border-radius: 999px;
  padding: 8px 12px;
  background: #f8fbff;
  color: #315f9f;
  font-size: 12px;
  cursor: pointer;
}

.operation-stream {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 18px;
  width: min(920px, 100%);
  margin: 0 auto;
  overflow: auto;
  padding: 18px 0 16px;
}

.latest-scroll-button {
  position: absolute;
  left: 50%;
  bottom: 20px;
  z-index: 4;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border: 1px solid #d6dbe3;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
  color: #1f2328;
  cursor: pointer;
  transform: translateX(-50%);
  transition:
    background 0.16s ease,
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    transform 0.16s ease;
}

.latest-scroll-button:hover {
  border-color: #b9c1ce;
  background: #ffffff;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.18);
  transform: translateX(-50%) translateY(-1px);
}

.latest-scroll-button:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 3px;
}

.latest-scroll-button span {
  font-size: 25px;
  font-weight: 400;
  line-height: 1;
}

.stream-card {
  display: grid;
  gap: 8px;
  max-width: 860px;
  border-radius: 0;
  padding: 0;
  border: 0;
  background: transparent;
}

.stream-card-user {
  align-self: flex-end;
  max-width: min(680px, 86%);
  border-radius: 24px 24px 6px 24px;
  padding: 12px 16px;
  background: #eef4ff;
  color: #1f2937;
}

.stream-card-assistant {
  color: #1f2937;
}

.stream-card-empty {
  align-self: center;
  width: min(680px, 100%);
  margin-top: auto;
  margin-bottom: auto;
  text-align: center;
}

.stream-card-empty .stream-head {
  justify-content: center;
  color: #667085;
}

.stream-card-empty p {
  margin: 12px 0 0;
  font-size: 28px;
  font-weight: 600;
  line-height: 1.3;
  color: #1f2937;
}

.stream-card-empty .suggestion-row {
  justify-content: center;
  margin-top: 18px;
}

.stream-card-system {
  border-radius: 14px;
  padding: 12px 14px;
  background: #f8fafc;
  border: 1px solid #e5e8ec;
}

.stream-card-runtime {
  width: min(800px, 100%);
  gap: 14px;
}

.stream-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  color: inherit;
  font-size: 12px;
}

.stream-head em {
  color: #7d8790;
  font-style: normal;
}

.stream-card-user .stream-head em {
  color: #cfd6dc;
}

.message-content {
  margin: 0;
  color: inherit;
  font-size: 14px;
  line-height: 1.85;
  white-space: pre-wrap;
}

.runtime-message-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px 12px;
}

.runtime-message-head strong {
  min-width: 0;
  color: #1f2328;
  font-size: 15px;
  line-height: 1.5;
}

.runtime-message-head span {
  flex: 0 0 auto;
  color: #7d8790;
  font-size: 12px;
}

.runtime-message-copy {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  color: #566171;
  font-size: 13px;
  line-height: 1.7;
}

.thinking-process {
  display: grid;
  gap: 8px;
  padding: 2px 0 0;
  color: #667085;
  font-size: 12px;
}

.thinking-process-runtime {
  gap: 10px;
  padding-top: 0;
}

.thinking-process-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: #8a94a3;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.45;
}

.thinking-process-head::after {
  content: '';
  flex: 1 1 auto;
  min-width: 24px;
  height: 1px;
  background: #e8ecf1;
}

.state-pill-row,
.suggestion-row,
.reference-row,
.message-action-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.plan-card {
  display: grid;
  gap: 6px;
  padding: 2px 0 2px 12px;
  border: none;
  border-left: 2px solid #9bbcf6;
  background: transparent;
}

.plan-card strong {
  color: #1d4ed8;
  font-size: 14px;
}

.plan-list,
.plain-list {
  margin: 0;
  padding-left: 18px;
  color: #4d5863;
  font-size: 13px;
  line-height: 1.8;
}

.plan-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-start;
}

.result-list {
  color: #4f5a66;
}

.stream-note {
  margin: 0;
  border-radius: 12px;
  padding: 12px 14px;
  background: #eef8f0;
  color: #1f7a41;
  font-size: 13px;
}

.stream-error {
  margin: 0;
  border-radius: 12px;
  padding: 12px 14px;
  background: #fff0f0;
  color: #b42318;
  font-size: 13px;
}

.runtime-status-list {
  display: grid;
  gap: 12px;
  padding: 0;
}

.runtime-status-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 9px;
  align-items: start;
  color: #8b949e;
}

.runtime-status-icon {
  position: relative;
  width: 14px;
  height: 14px;
  margin-top: 4px;
  border: 2px solid currentColor;
  border-radius: 4px;
}

.runtime-status-icon::before {
  content: '';
  position: absolute;
  inset: 2px;
  border-radius: 2px;
  background: currentColor;
  opacity: 0.12;
}

.runtime-status-row-running .runtime-status-icon::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: currentColor;
  transform: translate(-50%, -50%);
  animation: runtime-status-pulse 1.2s ease-in-out infinite;
}

.runtime-status-row-completed {
  color: #9aa1aa;
}

.runtime-status-row-failed,
.runtime-status-row-cancelled {
  color: #b42318;
}

.runtime-status-copy {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.runtime-status-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
}

.runtime-status-line strong {
  min-width: 0;
  color: #8b949e;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.55;
}

.runtime-status-row-running .runtime-status-line strong {
  color: #7b8490;
}

.runtime-status-row-failed .runtime-status-line strong,
.runtime-status-row-cancelled .runtime-status-line strong {
  color: #b42318;
}

.runtime-status-line span {
  color: #a0a7b0;
  font-size: 11px;
  line-height: 1.5;
}

.runtime-status-copy p {
  margin: 0;
  color: #596474;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.65;
}

.runtime-status-row-failed .runtime-status-copy p,
.runtime-status-row-cancelled .runtime-status-copy p {
  color: #b42318;
}

@keyframes runtime-status-pulse {
  0%,
  100% {
    opacity: 0.35;
  }

  50% {
    opacity: 1;
  }
}

.runtime-strip {
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  width: min(920px, 100%);
  margin: 0 auto;
  border: 1px solid rgba(216, 222, 228, 0.92);
  border-radius: 18px;
  padding: 16px 18px;
  background: #f8fbff;
  box-shadow: none;
}

.runtime-strip-cancelling {
  background: #fff7ed;
}

.runtime-strip-glow {
  display: none;
}

.runtime-strip-content {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 12px;
}

.runtime-strip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.runtime-strip-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.runtime-strip-badge,
.runtime-strip-elapsed {
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 11px;
  line-height: 1.2;
}

.runtime-strip-badge {
  background: #e8f0fe;
  color: #1d4ed8;
}

.runtime-strip-elapsed {
  background: rgba(255, 255, 255, 0.86);
  color: #67707c;
  border: 1px solid rgba(220, 225, 230, 0.9);
}

.runtime-strip-stop {
  border: 1px solid rgba(207, 213, 220, 0.92);
  border-radius: 999px;
  padding: 7px 12px;
  background: rgba(255, 255, 255, 0.9);
  color: #4b5563;
  font-size: 12px;
  line-height: 1.2;
  cursor: pointer;
}

.runtime-strip-body {
  display: grid;
  gap: 6px;
}

.runtime-strip-copy {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.runtime-strip-lead {
  color: #315f9f;
  font-size: 13px;
}

.runtime-strip-context {
  color: #7a8088;
  font-size: 12px;
}

.runtime-strip-title {
  color: #253041;
  font-size: 16px;
  font-weight: 600;
}

.runtime-strip-track {
  overflow: hidden;
  height: 7px;
  border-radius: 999px;
  background: rgba(228, 232, 236, 0.88);
}

.runtime-strip-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #1d4ed8;
  transition: width 180ms ease;
}

.composer-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(920px, 100%);
  margin: 0 auto;
  border: 1px solid #cfd6df;
  border-radius: 28px;
  padding: 18px 20px 14px;
  background: #ffffff;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.composer-shell-architecture {
  gap: 8px;
  padding: 12px 14px 10px;
}

.composer-file-input {
  display: none;
}

.composer-input {
  width: 100%;
  min-height: 86px;
  border: none;
  padding: 0;
  background: transparent;
  color: #1f2328;
  font-size: 15px;
  line-height: 1.65;
  resize: none;
  outline: none;
}

.composer-input-architecture {
  min-height: 56px;
}

.composer-input::placeholder {
  color: #b3bac3;
}

.composer-bottom,
.composer-bottom-left,
.composer-bottom-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.composer-bottom {
  justify-content: space-between;
  flex-wrap: wrap;
}

.composer-bottom-left {
  min-width: 0;
  flex: 1;
}

.composer-bottom-right {
  flex: 0 0 auto;
}

.composer-attach-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 0 12px 0 8px;
  background: #ffffff;
  color: #57606a;
  cursor: pointer;
}

.composer-attach-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #f4f6f8;
  color: #697281;
  font-size: 18px;
  line-height: 1;
}

.composer-attach-label {
  font-size: 12px;
  white-space: nowrap;
}

.composer-attach-button:hover:not(:disabled),
.composer-model-button:hover:not(:disabled) {
  background: #f6f8fa;
}

.composer-model-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 0 12px;
  background: #f8fafc;
  color: #6b7280;
  cursor: pointer;
}

.composer-model-button-architecture {
  min-height: 32px;
  padding: 0 10px;
}

.composer-model-indicator {
  width: 12px;
  height: 12px;
  border: 2px solid #d0d7de;
  border-right-color: #9aa4af;
  border-radius: 999px;
}

.composer-model-indicator-busy {
  animation: composer-spin 0.9s linear infinite;
}

.composer-model-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.composer-model-caret {
  color: #7d8790;
  font-size: 12px;
}

.composer-submit-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border: 1px solid #e8f0fe;
  border-radius: 999px;
  background: #e8f0fe;
  color: #1d4ed8;
  cursor: pointer;
}

.composer-submit-button-running {
  background: #dbe8ff;
}

.composer-submit-button:hover:not(:disabled) {
  background: #dbe8ff;
}

.composer-submit-icon {
  width: 17px;
  height: 17px;
}

.composer-submit-stop-icon {
  width: 16px;
  height: 16px;
}

.composer-tip,
.composer-tool-message {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.composer-tip {
  color: #7d8790;
}

.composer-tool-message-success {
  color: #1f7a41;
}

.composer-tool-message-error {
  color: #b42318;
}

.architecture-confirm-stack {
  display: grid;
  gap: 12px;
}

.architecture-confirm-copy {
  margin: 0;
  color: #57606a;
  font-size: 13px;
  line-height: 1.7;
}

.architecture-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.plan-list-modal {
  padding-left: 20px;
}

.chapter-prompt-preview {
  display: grid;
  gap: 12px;
  border: 1px solid #d0d7de;
  border-radius: 12px;
  padding: 12px;
  background: #f6f8fa;
}

.chapter-prompt-preview-head,
.chapter-prompt-preview-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.chapter-prompt-preview-head p {
  margin: 4px 0 0;
  color: #57606a;
  font-size: 12px;
  line-height: 1.6;
}

.chapter-prompt-preview-head span,
.prompt-preview-message {
  color: #57606a;
  font-size: 12px;
}

.prompt-preview-error {
  margin: 0;
  color: #b42318;
  font-size: 12px;
  line-height: 1.6;
}

.chapter-prompt-preview-item {
  display: grid;
  gap: 8px;
}

.chapter-prompt-editor {
  min-height: 260px;
  max-height: 460px;
  resize: vertical;
  font-family: 'SFMono-Regular', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.7;
}

.agent-segment-panel {
  margin-top: 12px;
}

.agent-segment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.agent-segment-pill {
  border-radius: 999px;
  padding: 5px 10px;
  background: #eef2f7;
  color: #57606a;
  font-size: 12px;
}

.agent-segment-pill-active {
  background: #dbeafe;
  color: #1d4ed8;
}

.agent-segment-pill-done {
  background: #dcfce7;
  color: #166534;
}

.segment-editor-field {
  display: grid;
  gap: 6px;
  color: #3d4650;
  font-size: 13px;
}

.segment-draft-editor {
  min-height: 320px;
}

.agent-segment-actions {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.primary-button,
.secondary-button {
  border-radius: 10px;
  padding: 10px 16px;
  font-size: 13px;
  cursor: pointer;
}

.small-button {
  padding: 8px 12px;
  font-size: 12px;
}

.primary-button {
  border: none;
  background: #1f2430;
  color: #ffffff;
}

.plan-execute-button {
  background: #1d4ed8;
  box-shadow: 0 8px 18px rgba(29, 78, 216, 0.18);
}

.secondary-button {
  border: 1px solid #d0d7de;
  background: #ffffff;
  color: #344054;
}

.primary-button:disabled,
.secondary-button:disabled,
.quick-action-button:disabled,
.suggestion-button:disabled,
.reference-chip:disabled,
.composer-attach-button:disabled,
.composer-model-button:disabled,
.composer-submit-button:disabled {
  opacity: 0.55;
  cursor: default;
}

@keyframes composer-spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1200px) {
  .workspace-top {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .execution-options,
  .architecture-params-card {
    grid-template-columns: 1fr;
  }

  .architecture-stage-head,
  .operation-header,
  .composer-bottom,
  .composer-bottom-left,
  .composer-bottom-right {
    flex-direction: column;
    align-items: stretch;
  }

  .operation-header-actions {
    justify-content: flex-start;
  }
}
</style>
