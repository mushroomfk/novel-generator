<script setup>
import { computed, nextTick, onMounted, reactive, ref, toRefs, watch } from 'vue';
import {
  applyProjectArchitectureWorkspace,
  activatePromptPreset,
  clearPromptHistory,
  clearStudioLogs,
  clearStyleReferences,
  createPromptPreset,
  createXpPreset,
  deleteCharacterReplicaProfile,
  deletePromptPreset,
  deleteStyle,
  deleteXpPreset,
  getCharacterReplicaProfile,
  getProjectDetail,
  getProjectFileContent,
  getSelfEvolutionReport,
  getPromptHistory,
  getPromptPresetDetail,
  getStudioLogs,
  getStyleDetail,
  importProjectKnowledge,
  importProjectKnowledgeFiles,
  importStyleReferenceFiles,
  importStyleReferences,
  listCharacterReplicaProfiles,
  listProjectFiles,
  listPromptPresets,
  listStyles,
  listStudioSkills,
  listXpPresets,
  rollbackStyleCalibration,
  saveStyle,
  searchStyleReferences,
  searchProjectKnowledge,
  researchHistoricalReferences,
  streamArchitectureStep,
  streamBatchGenerate,
  streamBlueprint,
  streamBrainstorm,
  streamCharacterReplica,
  streamChapterFinalize,
  streamChapterGenerate,
  streamChapterHumanize,
  streamChapterPolish,
  streamChapterWorkflow,
  streamConsistency,
  streamContinueProject,
  streamStyleAnalyze,
  streamStyleAnalyzeDna,
  streamStyleCalibrate,
  streamStyleCalibrateNarrative,
    streamStyleMerge,
    updateProjectChapter,
    updateProjectFileContent,
    updateProjectMemory,
    updatePromptPreset,
    saveCharacterReplicaProfile,
    updateStoryDocument,
  updateXpPreset,
} from '../lib/api.js';
import { buildImportedFilePayloads, importAcceptValue } from '../lib/importFiles.js';
import { filterOptions as fallbackFilterOptions, skillSections as fallbackSkillSections } from '../lib/skillCatalog.js';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  launchRequest: {
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
});

const emit = defineEmits(['project-detail-updated', 'return-workspace']);
const { project, selectedChapter, modelName } = toRefs(props);
const workbenchRef = ref(null);

const activeFilter = ref('全部');
const keyword = ref('');
const activeToolId = ref('');
const skillFilters = ref([...fallbackFilterOptions]);
const skillCatalogSections = ref([...fallbackSkillSections]);

const isToolRunning = ref(false);
const toolTaskId = ref('');
const toolProgress = ref([]);
const toolResult = ref(null);
const toolError = ref('');
const toolMessage = ref('');
const toolMessageTone = ref('success');
const lastStyleAction = ref('analyze');

const brainstormState = reactive({
  input: '',
  history: [],
});

const characterReplicaForm = reactive({
  personaName: '',
  question: '',
  focus: '',
  sourceNotes: '',
  useProjectContext: true,
  useChapterContext: true,
});

const characterReplicaLibraryState = reactive({
  list: [],
  selectedName: '',
  detail: null,
});

const chapterScenesForm = reactive({
  instruction: '',
  targetWords: 1600,
});

const chapterDiagnoseForm = reactive({
  instruction: '',
  targetWords: 1200,
});

const chapterDraftForm = reactive({
  instruction: '',
  targetWords: 1800,
});

const consistencyForm = reactive({
  focus: '',
});

const blueprintForm = reactive({
  instruction: '',
  chapterCount: '',
  styleName: '',
  xpPreset: '',
});

const chapterGenerateForm = reactive({
  instruction: '',
  styleName: '',
  xpPreset: '',
  charactersInvolved: '',
  keyItems: '',
  sceneLocation: '',
  timeConstraint: '',
});

const rewriteForm = reactive({
  instruction: '',
  styleName: '',
  xpPreset: '',
});

const batchForm = reactive({
  startChapter: 1,
  endChapter: 1,
  instruction: '',
  styleName: '',
  xpPreset: '',
  taskId: '',
  retryFailed: false,
  comment: '',
});

const continueForm = reactive({
  newChapters: 3,
  instruction: '',
  styleName: '',
  xpPreset: '',
});

const architectureStepForm = reactive({
  step: 'core_seed',
  mode: 'initial',
  guidance: '',
  newChapters: 3,
});

const architectureWorkspace = reactive({
  core_seed: '',
  character_design: '',
  world_building: '',
  plot_structure: '',
  character_state: '',
  blueprint: '',
  global_summary: '',
});

const styleAnalyzeForm = reactive({
  styleName: '',
  sampleText: '',
  userPreference: '',
});

const styleDnaForm = reactive({
  styleName: '',
  sampleText: '',
  userPreference: '',
});

const styleMergeForm = reactive({
  styleName: '',
  userPreference: '',
  selectedStyles: [],
});

const styleCalibrateForm = reactive({
  maxIterations: 3,
  userPreference: '',
});

const knowledgeForm = reactive({
  query: '',
  importTitle: '',
  importContent: '',
  limit: 8,
});

const knowledgeHits = ref([]);

const webResearchForm = reactive({
  query: '',
  limit: 8,
});
const webResearchResult = ref(null);
const isWebResearching = ref(false);
const canImportWebResearchResult = computed(() => Boolean(
  webResearchResult.value?.answer
  && webResearchResult.value?.provider !== 'none'
));

function webResearchProviderLabel(provider) {
  if (!provider || provider === 'none') {
    return '未完成';
  }
  if (provider === 'aliyun-bailian') {
    return '阿里百炼联网搜索';
  }
  if (provider === 'bocha') {
    return '博查联网搜索';
  }
  return '国内联网搜索';
}

const readerChapterId = ref('');

const filesState = reactive({
  list: [],
  selectedPath: '',
  content: '',
  isSaving: false,
});

const logsState = reactive({
  content: '',
});

const promptHistoryState = reactive({
  search: '',
  records: [],
  total: 0,
});

const selfEvolutionState = reactive({
  report: null,
});

const promptPresetState = reactive({
  list: [],
  activeName: '',
  selectedName: '',
});

const promptPresetDraft = reactive({
  name: '',
  description: '',
  prompts: {
    architecture: '',
    brainstorm: '',
    blueprint: '',
    chapter: '',
    finalize: '',
    polish: '',
    humanize: '',
  },
});

const xpPresetState = reactive({
  list: [],
  selectedName: '',
  draftName: '',
  draftContent: '',
});

const styleState = reactive({
  list: [],
  selectedName: '',
  detail: null,
  referenceTitle: '',
  referenceContent: '',
  referenceQuery: '',
  referenceHits: [],
});

const totalSkillCount = computed(() => (
  skillCatalogSections.value.reduce((sum, section) => sum + section.items.length, 0)
));

const filteredSections = computed(() => {
  const normalizedKeyword = keyword.value.trim();

  return skillCatalogSections.value
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => {
        const matchesFilter = activeFilter.value === '全部' || item.category === activeFilter.value;
        const matchesKeyword = normalizedKeyword.length === 0
          || item.name.includes(normalizedKeyword)
          || item.description.includes(normalizedKeyword)
          || item.category.includes(normalizedKeyword)
          || item.scenes.some((scene) => scene.includes(normalizedKeyword));
        return matchesFilter && matchesKeyword;
      }),
    }))
    .filter((section) => section.items.length > 0);
});

const currentProjectLine = computed(() => {
  if (!props.project) {
    return '还没有选中作品';
  }
  const parts = [
    props.project.name,
    props.project.genre,
    `${props.project.target_chapters} 章`,
  ];
  if (props.selectedChapter) {
    parts.push(`第 ${props.selectedChapter.index} 章`);
  }
  return parts.join(' · ');
});

const defaultSkillBehaviorById = {
  'chapter-scenes': {
    panel: 'chapter-workflow',
    mode: 'scenes',
    input_label: '拆场要求',
    submit_label: '开始拆场',
  },
  'chapter-diagnose': {
    panel: 'chapter-workflow',
    mode: 'diagnose',
    input_label: '诊断要求',
    submit_label: '开始诊断',
  },
  'chapter-draft': {
    panel: 'chapter-workflow',
    mode: 'draft',
    input_label: '续写要求',
    submit_label: '开始续写',
  },
  'chapter-finalize': {
    panel: 'chapter-rewrite',
    mode: 'finalize',
    input_label: '改稿要求',
    submit_label: '开始定稿',
  },
  'chapter-polish': {
    panel: 'chapter-rewrite',
    mode: 'polish',
    input_label: '改稿要求',
    submit_label: '开始润色',
  },
  'chapter-humanize': {
    panel: 'chapter-rewrite',
    mode: 'humanize',
    input_label: '改稿要求',
    submit_label: '开始去 AI',
  },
};

function normalizeSkillBehavior(skill) {
  if (!skill) {
    return {
      panel: '',
      mode: '',
      input_label: '',
      submit_label: '',
    };
  }

  const fallback = defaultSkillBehaviorById[skill.id] ?? {};
  const behavior = skill.behavior ?? {};
  return {
    panel: behavior.panel || fallback.panel || skill.id,
    mode: behavior.mode || fallback.mode || '',
    input_label: behavior.input_label || fallback.input_label || '',
    submit_label: behavior.submit_label || fallback.submit_label || '',
  };
}

const chapterWorkflowModeConfig = {
  scenes: {
    mode: 'scenes',
    form: chapterScenesForm,
    instructionLabel: '拆场要求',
    targetWordsLabel: '目标字数',
    submitLabel: '开始拆场',
    runningLabel: '处理中…',
    min: 400,
    max: 8000,
    step: 100,
  },
  diagnose: {
    mode: 'diagnose',
    form: chapterDiagnoseForm,
    instructionLabel: '诊断要求',
    targetWordsLabel: '参考字数',
    submitLabel: '开始诊断',
    runningLabel: '诊断中…',
    min: 400,
    max: 4000,
    step: 100,
  },
  draft: {
    mode: 'draft',
    form: chapterDraftForm,
    instructionLabel: '续写要求',
    targetWordsLabel: '目标字数',
    submitLabel: '开始续写',
    runningLabel: '续写中…',
    min: 500,
    max: 8000,
    step: 100,
  },
};

const rewriteModeConfig = {
  finalize: {
    mode: 'finalize',
    instructionLabel: '改稿要求',
    submitLabel: '开始定稿',
  },
  polish: {
    mode: 'polish',
    instructionLabel: '改稿要求',
    submitLabel: '开始润色',
  },
  humanize: {
    mode: 'humanize',
    instructionLabel: '改稿要求',
    submitLabel: '开始去 AI',
  },
};

const activeToolMeta = computed(() => {
  if (!activeToolId.value) {
    return null;
  }
  return skillCatalogSections.value.flatMap((section) => section.items).find((item) => item.id === activeToolId.value) ?? null;
});

const activeToolBehavior = computed(() => normalizeSkillBehavior(activeToolMeta.value));
const activeToolPanelKey = computed(() => activeToolBehavior.value.panel || activeToolId.value);
const activeToolMode = computed(() => activeToolBehavior.value.mode || '');
const activeToolLabel = computed(() => activeToolMeta.value?.name ?? '技能工作区');
const activeToolDescription = computed(() => activeToolMeta.value?.description ?? '在这里直接调用技能。');
const activeToolUsage = computed(() => activeToolMeta.value?.usage ?? []);
const activeToolLimitations = computed(() => activeToolMeta.value?.limitations ?? []);
const activeToolInstructionPreview = computed(() => activeToolMeta.value?.instruction_preview ?? '');
const activeToolNeedsProject = computed(() => (
  activeToolMeta.value?.requires_project ?? !['prompt-presets', 'xp-presets', 'style-dna', 'logs', 'prompt-history'].includes(activeToolPanelKey.value)
));
const activeToolNeedsChapter = computed(() => (
  activeToolMeta.value?.requires_chapter ?? [
    'chapter-workflow',
    'consistency',
    'chapter-generate',
    'chapter-rewrite',
    'reader',
  ].includes(activeToolPanelKey.value)
));

const activeChapterWorkflowConfig = computed(() => {
  if (activeToolPanelKey.value !== 'chapter-workflow') {
    return null;
  }

  const base = chapterWorkflowModeConfig[activeToolMode.value] ?? {
    mode: activeToolMode.value || 'diagnose',
    form: chapterDiagnoseForm,
    instructionLabel: '补充要求',
    targetWordsLabel: '参考字数',
    submitLabel: activeToolLabel.value ? `开始${activeToolLabel.value}` : '开始处理',
    runningLabel: '处理中…',
    min: 400,
    max: 8000,
    step: 100,
  };

  return {
    ...base,
    instructionLabel: activeToolBehavior.value.input_label || base.instructionLabel,
    submitLabel: activeToolBehavior.value.submit_label || base.submitLabel,
  };
});

const activeRewriteConfig = computed(() => {
  if (activeToolPanelKey.value !== 'chapter-rewrite') {
    return null;
  }

  const base = rewriteModeConfig[activeToolMode.value] ?? {
    mode: activeToolMode.value || 'finalize',
    instructionLabel: '改稿要求',
    submitLabel: activeToolLabel.value ? `开始${activeToolLabel.value}` : '开始处理',
  };

  return {
    ...base,
    instructionLabel: activeToolBehavior.value.input_label || base.instructionLabel,
    submitLabel: activeToolBehavior.value.submit_label || base.submitLabel,
  };
});

function findSkillMetaById(skillId) {
  return skillCatalogSections.value.flatMap((section) => section.items).find((item) => item.id === skillId) ?? null;
}

function prefillToolFromLaunch(tool, prompt) {
  const text = String(prompt ?? '').trim();
  const behavior = normalizeSkillBehavior(tool);
  const panel = behavior.panel || tool.id;

  if (panel === 'brainstorm' && text) {
    brainstormState.input = text;
    return;
  }
  if (panel === 'character-replica' && text) {
    characterReplicaForm.question = text;
    return;
  }
  if (panel === 'consistency' && text) {
    consistencyForm.focus = text;
    return;
  }
  if (panel === 'blueprint' && text) {
    blueprintForm.instruction = text;
    return;
  }
  if (panel === 'chapter-workflow' && text) {
    const mode = behavior.mode || 'diagnose';
    const workflowForm = chapterWorkflowModeConfig[mode]?.form;
    if (workflowForm) {
      workflowForm.instruction = text;
    }
    return;
  }
  if (panel === 'chapter-generate' && text) {
    chapterGenerateForm.instruction = text;
    return;
  }
  if (panel === 'chapter-rewrite' && text) {
    rewriteForm.instruction = text;
    return;
  }
  if (panel === 'batch-generate' && text) {
    batchForm.instruction = text;
    return;
  }
  if (panel === 'continue-project' && text) {
    continueForm.instruction = text;
    return;
  }
  if (panel === 'architecture-stepper' && text) {
    architectureStepForm.guidance = text;
    return;
  }
  if (panel === 'style-dna' && text) {
    styleAnalyzeForm.userPreference = text;
    return;
  }
  if (panel === 'knowledge-search' && text) {
    knowledgeForm.query = text;
    return;
  }
  if (panel === 'web-research' && text) {
    webResearchForm.query = text;
  }
}

function handleLaunchRequest(request) {
  if (!request?.skillId) {
    return;
  }
  const tool = findSkillMetaById(request.skillId);
  if (!tool) {
    return;
  }
  activeFilter.value = '全部';
  keyword.value = '';
  prefillToolFromLaunch(tool, request.prompt);
  activateTool(tool);
  setToolMessage(request.prompt?.trim() ? '已从主对话带入本轮要求' : '已切到技能工作区');
}

const currentProgress = computed(() => (
  toolProgress.value.length > 0 ? toolProgress.value[toolProgress.value.length - 1] : null
));

const currentReaderChapter = computed(() => (
  props.project?.chapters?.find((item) => item.id === readerChapterId.value)
  ?? props.selectedChapter
  ?? props.project?.chapters?.[0]
  ?? null
));

const availableStyles = computed(() => styleState.list);
const availableXpPresets = computed(() => xpPresetState.list);

function resetToolRunState() {
  isToolRunning.value = false;
  toolTaskId.value = '';
  toolProgress.value = [];
  toolResult.value = null;
  toolError.value = '';
  toolMessage.value = '';
  toolMessageTone.value = 'success';
}

function setToolMessage(message, tone = 'success') {
  toolMessage.value = message;
  toolMessageTone.value = tone;
}

function applyChapterDefaults() {
  chapterScenesForm.instruction = props.selectedChapter
    ? `请把《${props.selectedChapter.title}》拆成 4 到 6 个场景。`
    : '';
  chapterDiagnoseForm.instruction = props.selectedChapter
    ? `请判断《${props.selectedChapter.title}》现在最该先解决的问题。`
    : '';
  chapterDraftForm.instruction = props.selectedChapter?.exists
    ? `请沿着《${props.selectedChapter.title}》当前内容继续往下写。`
    : '请从这一章的第一个有效场景写起。';
  consistencyForm.focus = props.selectedChapter
    ? `重点看《${props.selectedChapter.title}》的人物动机和信息顺序。`
    : '';
  chapterGenerateForm.instruction = props.selectedChapter?.exists
    ? `延续《${props.selectedChapter.title}》当前冲突继续往下写。`
    : '请从这一章的第一个有效场景写起。';
  rewriteForm.instruction = props.selectedChapter?.exists
    ? `保留主事件，把《${props.selectedChapter.title}》整理得更完整。`
    : '';
  if (props.selectedChapter) {
    batchForm.startChapter = props.selectedChapter.index;
    batchForm.endChapter = Math.min(
      props.project?.target_chapters ?? props.selectedChapter.index,
      props.selectedChapter.index + 1,
    );
    readerChapterId.value = props.selectedChapter.id;
  } else if (props.project?.chapters?.length) {
    batchForm.startChapter = 1;
    batchForm.endChapter = Math.min(2, props.project.target_chapters);
    readerChapterId.value = props.project.chapters[0].id;
  }
}

watch(
  () => [props.project?.id, props.selectedChapter?.id],
  () => {
    applyChapterDefaults();
    brainstormState.history = [];
    if (activeToolId.value) {
      void loadToolData(activeToolMeta.value);
    }
  },
  { immediate: true },
);

watch(
  () => props.launchRequest?.token,
  () => {
    if (props.launchRequest?.token) {
      handleLaunchRequest(props.launchRequest);
    }
  },
  { immediate: true },
);

function activateTool(itemOrId) {
  const nextId = typeof itemOrId === 'string' ? itemOrId : itemOrId.id;
  activeToolId.value = nextId;
  resetToolRunState();
  void loadToolData(typeof itemOrId === 'string'
    ? skillCatalogSections.value.flatMap((section) => section.items).find((item) => item.id === nextId) ?? null
    : itemOrId);
  void nextTick(() => {
    workbenchRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

async function refreshSkillCatalog() {
  try {
    const catalog = await listStudioSkills();
    const nextFilters = Array.isArray(catalog.filters) && catalog.filters.length > 0
      ? catalog.filters
      : [...fallbackFilterOptions];
    const nextSections = Array.isArray(catalog.sections) && catalog.sections.length > 0
      ? catalog.sections
      : [...fallbackSkillSections];
    skillFilters.value = nextFilters;
    skillCatalogSections.value = nextSections;
    if (!nextFilters.includes(activeFilter.value)) {
      activeFilter.value = '全部';
    }
  } catch {
    skillFilters.value = [...fallbackFilterOptions];
    skillCatalogSections.value = [...fallbackSkillSections];
  }
}

async function loadToolData(tool) {
  if (!tool) {
    return;
  }

  const behavior = normalizeSkillBehavior(tool);
  const panel = behavior.panel || tool.id;

  if (
    [
      'blueprint',
      'chapter-generate',
      'chapter-rewrite',
      'batch-generate',
      'continue-project',
    ].includes(panel)
  ) {
    xpPresetState.list = await listXpPresets();
    styleState.list = await listStyles();
    return;
  }

  if (panel === 'architecture-stepper') {
    syncArchitectureWorkspaceFromProject();
    return;
  }
  if (panel === 'character-replica') {
    await refreshCharacterReplicaProfiles();
    return;
  }
  if (panel === 'prompt-presets') {
    await refreshPromptPresets();
    return;
  }
  if (panel === 'xp-presets') {
    await refreshXpPresets();
    return;
  }
  if (panel === 'style-dna') {
    await refreshStyles();
    return;
  }
  if (panel === 'logs') {
    await refreshLogs();
    return;
  }
  if (panel === 'prompt-history') {
    await refreshPromptHistory();
    return;
  }
  if (panel === 'self-evolution') {
    await refreshSelfEvolution();
    return;
  }
  if (panel === 'file-browser' && props.project?.id) {
    await refreshFiles();
    return;
  }
  if (panel === 'knowledge-search') {
    knowledgeHits.value = [];
    return;
  }
  if (panel === 'web-research') {
    webResearchResult.value = null;
  }
}

onMounted(() => {
  void refreshSkillCatalog();
});

function handleStreamEvent(event) {
  if (event.event === 'started' && event.data && typeof event.data === 'object') {
    toolTaskId.value = event.data.task_id ?? '';
    if (activeToolPanelKey.value === 'batch-generate' && event.data.task_id) {
      batchForm.taskId = String(event.data.task_id);
    }
    return;
  }
  if (event.event === 'progress' && event.data && typeof event.data === 'object') {
    toolProgress.value = [
      ...toolProgress.value,
      {
        step: event.data.step ?? toolProgress.value.length + 1,
        total: event.data.total ?? 0,
        message: event.data.message ?? '处理中',
      },
    ];
    return;
  }
  if (event.event === 'result') {
    toolResult.value = event.data;
    return;
  }
  if (event.event === 'error' && event.data && typeof event.data === 'object') {
    toolError.value = event.data.message ?? '执行失败';
  }
}

async function runStream(streamer, payload, afterSuccess) {
  resetToolRunState();
  isToolRunning.value = true;

  try {
    await streamer(payload, handleStreamEvent);
    if (!toolError.value && typeof afterSuccess === 'function') {
      await afterSuccess();
    }
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '执行失败';
  } finally {
    isToolRunning.value = false;
  }
}

function ensureProjectAndChapter({ chapter = false } = {}) {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return false;
  }
  if (chapter && !props.selectedChapter?.id) {
    toolError.value = '先从左侧选中一章';
    return false;
  }
  return true;
}

async function refreshProjectDetail() {
  if (!props.project?.id) {
    return null;
  }
  const detail = await getProjectDetail(props.project.id);
  emit('project-detail-updated', detail);
  return detail;
}

function currentDocumentContent(documentKey) {
  return props.project?.story_overview?.documents?.find((item) => item.key === documentKey)?.content ?? '';
}

const architectureDocumentLabels = {
  core_seed: '核心种子',
  character_design: '人物设定',
  world_building: '世界设定',
  plot_structure: '情节骨架',
  character_state: '人物状态',
  blueprint: '章节蓝图',
  global_summary: '滚动摘要',
};

function syncArchitectureWorkspaceFromProject() {
  Object.keys(architectureDocumentLabels).forEach((key) => {
    architectureWorkspace[key] = currentDocumentContent(key);
  });
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildBlueprintSectionFromScenes() {
  if (!props.selectedChapter || !toolResult.value?.scenes?.length) {
    return '';
  }

  const chapterHeading = `## 第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》`;
  const sceneLines = toolResult.value.scenes.map((item, index) => (
    [
      `### 场景 ${index + 1} · ${item.title}`,
      `目标：${item.goal}`,
      `冲突：${item.conflict}`,
      `转折：${item.turn}`,
    ].join('\n')
  ));

  return [
    chapterHeading,
    toolResult.value.summary ?? '',
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

async function handleBrainstormRun() {
  if (!ensureProjectAndChapter({ chapter: false })) {
    return;
  }
  const userInput = brainstormState.input.trim();
  if (!userInput) {
    toolError.value = '先写下这一轮要讨论的问题';
    return;
  }

  const nextMessages = [
    ...brainstormState.history,
    { role: 'user', content: userInput },
  ];

  await runStream(
    streamBrainstorm,
    {
      project_id: props.project.id,
      messages: nextMessages,
      include_core_seed: true,
      include_characters: true,
      include_world_building: true,
      include_plot: true,
      include_blueprint: true,
      include_character_state: true,
      extra_context: props.selectedChapter
        ? `当前章节：第 ${props.selectedChapter.index} 章《${props.selectedChapter.title}》`
        : '',
    },
    async () => {
      if (toolResult.value?.reply) {
        brainstormState.history = [
          ...nextMessages,
          { role: 'assistant', content: toolResult.value.reply },
        ];
        brainstormState.input = '';
      }
    },
  );
}

async function handleCharacterReplicaRun() {
  const personaName = characterReplicaForm.personaName.trim();
  const question = characterReplicaForm.question.trim();
  if (!personaName || !question) {
    toolError.value = '先填人物名称和你要问的问题';
    return;
  }

  await runStream(streamCharacterReplica, {
    persona_name: personaName,
    question,
    focus: characterReplicaForm.focus.trim(),
    source_notes: characterReplicaForm.sourceNotes.trim(),
    project_id: props.project?.id ?? '',
    chapter_id: props.selectedChapter?.id ?? '',
    include_project_context: Boolean(props.project?.id) && characterReplicaForm.useProjectContext,
    include_chapter_context: Boolean(props.selectedChapter?.id) && characterReplicaForm.useChapterContext,
  });
}

async function refreshCharacterReplicaProfiles(selectedName = characterReplicaLibraryState.selectedName) {
  characterReplicaLibraryState.list = await listCharacterReplicaProfiles();
  const candidateNames = new Set(characterReplicaLibraryState.list.map((item) => item.name));
  const nextName = [
    selectedName,
    characterReplicaForm.personaName.trim(),
    characterReplicaLibraryState.list[0]?.name,
  ].find((name) => name && candidateNames.has(name)) || '';
  if (nextName) {
    await loadCharacterReplicaProfile(nextName);
  } else {
    characterReplicaLibraryState.selectedName = '';
    characterReplicaLibraryState.detail = null;
  }
}

async function loadCharacterReplicaProfile(name) {
  characterReplicaLibraryState.selectedName = name;
  characterReplicaLibraryState.detail = await getCharacterReplicaProfile(name);
  characterReplicaForm.personaName = characterReplicaLibraryState.detail.name ?? name;
  characterReplicaForm.focus = characterReplicaLibraryState.detail.focus ?? '';
  characterReplicaForm.sourceNotes = characterReplicaLibraryState.detail.source_notes ?? '';
}

async function handleSaveCharacterReplicaProfile() {
  const personaName = characterReplicaForm.personaName.trim();
  if (!personaName) {
    setToolMessage('先填人物名称，再保存人物卡', 'error');
    return;
  }
  await saveCharacterReplicaProfile(personaName, {
    focus: characterReplicaForm.focus.trim(),
    source_notes: characterReplicaForm.sourceNotes.trim(),
    summary: toolResult.value?.summary ?? characterReplicaLibraryState.detail?.summary ?? '',
    voice_profile: toolResult.value?.voice_profile ?? characterReplicaLibraryState.detail?.voice_profile ?? '',
    mental_models: toolResult.value?.mental_models ?? characterReplicaLibraryState.detail?.mental_models ?? [],
    heuristics: toolResult.value?.heuristics ?? characterReplicaLibraryState.detail?.heuristics ?? [],
    boundaries: toolResult.value?.boundaries ?? characterReplicaLibraryState.detail?.boundaries ?? [],
    disclaimer: toolResult.value?.disclaimer ?? characterReplicaLibraryState.detail?.disclaimer ?? '',
  });
  await refreshCharacterReplicaProfiles(personaName);
  setToolMessage('人物卡已保存');
}

async function handleDeleteCharacterReplicaProfile() {
  if (!characterReplicaLibraryState.selectedName) {
    setToolMessage('先选中一张人物卡', 'error');
    return;
  }
  const removedName = characterReplicaLibraryState.selectedName;
  await deleteCharacterReplicaProfile(removedName);
  await refreshCharacterReplicaProfiles();
  if (characterReplicaForm.personaName.trim() === removedName) {
    characterReplicaForm.personaName = '';
    characterReplicaForm.focus = '';
    characterReplicaForm.sourceNotes = '';
  }
  setToolMessage('人物卡已删除');
}

async function handleActiveChapterWorkflowRun() {
  if (!ensureProjectAndChapter({ chapter: true })) {
    return;
  }
  const config = activeChapterWorkflowConfig.value;
  if (!config) {
    toolError.value = '当前技能没有可执行的章节工作流';
    return;
  }
  await runStream(streamChapterWorkflow, {
    project_id: props.project.id,
    chapter_id: props.selectedChapter.id,
    mode: config.mode,
    instruction: config.form.instruction.trim(),
    target_words: config.form.targetWords,
  });
}

async function handleConsistencyRun() {
  if (!ensureProjectAndChapter({ chapter: true })) {
    return;
  }
  await runStream(streamConsistency, {
    project_id: props.project.id,
    chapter_id: props.selectedChapter.id,
    focus: consistencyForm.focus.trim(),
  });
}

async function handleBlueprintRun() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  await runStream(streamBlueprint, {
    project_id: props.project.id,
    instruction: blueprintForm.instruction.trim(),
    chapter_count: blueprintForm.chapterCount ? Number(blueprintForm.chapterCount) : null,
    style_name: blueprintForm.styleName.trim(),
    xp_preset: blueprintForm.xpPreset.trim(),
  });
}

async function handleChapterGenerateRun() {
  if (!ensureProjectAndChapter({ chapter: true })) {
    return;
  }
  await runStream(streamChapterGenerate, {
    project_id: props.project.id,
    chapter_id: props.selectedChapter.id,
    instruction: chapterGenerateForm.instruction.trim(),
    style_name: chapterGenerateForm.styleName.trim(),
    xp_preset: chapterGenerateForm.xpPreset.trim(),
    characters_involved: chapterGenerateForm.charactersInvolved.trim(),
    key_items: chapterGenerateForm.keyItems.trim(),
    scene_location: chapterGenerateForm.sceneLocation.trim(),
    time_constraint: chapterGenerateForm.timeConstraint.trim(),
  });
}

async function handleRewriteRun(mode = activeRewriteConfig.value?.mode) {
  if (!ensureProjectAndChapter({ chapter: true })) {
    return;
  }
  if (!mode) {
    toolError.value = '当前技能没有可执行的改稿模式';
    return;
  }
  const streamer = mode === 'finalize'
    ? streamChapterFinalize
    : mode === 'polish'
      ? streamChapterPolish
      : streamChapterHumanize;

  await runStream(streamer, {
    project_id: props.project.id,
    chapter_id: props.selectedChapter.id,
    instruction: rewriteForm.instruction.trim(),
    style_name: rewriteForm.styleName.trim(),
    xp_preset: rewriteForm.xpPreset.trim(),
  });
}

async function handleBatchRun() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  await runStream(
    streamBatchGenerate,
    {
      project_id: props.project.id,
      start_chapter: Number(batchForm.startChapter),
      end_chapter: Number(batchForm.endChapter),
      instruction: batchForm.instruction.trim(),
      style_name: batchForm.styleName.trim(),
      xp_preset: batchForm.xpPreset.trim(),
      task_id: batchForm.taskId.trim(),
      retry_failed: batchForm.retryFailed,
      comment: batchForm.comment.trim(),
    },
    refreshProjectDetail,
  );
}

async function handleContinueRun() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  await runStream(
    streamContinueProject,
    {
      project_id: props.project.id,
      new_chapters: Number(continueForm.newChapters),
      instruction: continueForm.instruction.trim(),
      style_name: continueForm.styleName.trim(),
      xp_preset: continueForm.xpPreset.trim(),
    },
    refreshProjectDetail,
  );
}

async function handleArchitectureStepRun() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  await runStream(
    streamArchitectureStep,
    {
      project_id: props.project.id,
      step: architectureStepForm.step,
      mode: architectureStepForm.mode,
      guidance: architectureStepForm.guidance.trim(),
      new_chapters: architectureStepForm.mode === 'continue' ? Number(architectureStepForm.newChapters) : 0,
      workspace: { ...architectureWorkspace },
    },
    async () => {
      if (toolResult.value?.content && architectureStepForm.step in architectureWorkspace) {
        architectureWorkspace[architectureStepForm.step] = toolResult.value.content;
      }
    },
  );
}

async function handleApplyArchitectureWorkspace() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  try {
    const targetChapters = architectureStepForm.mode === 'continue'
      ? (toolResult.value?.target_chapters ?? (props.project.target_chapters + Number(architectureStepForm.newChapters)))
      : null;
    const detail = await applyProjectArchitectureWorkspace(props.project.id, {
      workspace: { ...architectureWorkspace },
      target_chapters: targetChapters,
    });
    emit('project-detail-updated', detail);
    syncArchitectureWorkspaceFromProject();
    setToolMessage('分步架构已经写回项目');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '分步架构写回失败', 'error');
  }
}

async function handleStyleAnalyzeRun() {
  if (!styleAnalyzeForm.styleName.trim() || !styleAnalyzeForm.sampleText.trim()) {
    toolError.value = '先填文风名称和样文';
    return;
  }
  lastStyleAction.value = 'analyze';
  await runStream(streamStyleAnalyze, {
    style_name: styleAnalyzeForm.styleName.trim(),
    sample_text: styleAnalyzeForm.sampleText.trim(),
    user_preference: styleAnalyzeForm.userPreference.trim(),
  });
}

async function handleStyleAnalyzeDnaRun() {
  const styleName = styleDnaForm.styleName.trim() || styleState.selectedName;
  if (!styleName || !styleDnaForm.sampleText.trim()) {
    toolError.value = '先选中文风，再准备 DNA 分析样文';
    return;
  }
  lastStyleAction.value = 'dna';
  await runStream(streamStyleAnalyzeDna, {
    style_name: styleName,
    sample_text: styleDnaForm.sampleText.trim(),
    user_preference: styleDnaForm.userPreference.trim(),
  });
}

async function handleStyleCalibrateRun(mode) {
  const styleName = styleState.selectedName || styleAnalyzeForm.styleName.trim() || styleDnaForm.styleName.trim();
  if (!styleName) {
    toolError.value = '先选中一个已保存文风';
    return;
  }
  lastStyleAction.value = mode === 'narrative' ? 'narrative-calibrate' : 'calibrate';
  const streamer = mode === 'narrative' ? streamStyleCalibrateNarrative : streamStyleCalibrate;
  await runStream(
    streamer,
    {
      style_name: styleName,
      max_iterations: Number(styleCalibrateForm.maxIterations),
      user_preference: styleCalibrateForm.userPreference.trim(),
    },
    async () => {
      await refreshStyles(styleName);
    },
  );
}

async function handleRollbackStyleCalibration() {
  if (!styleState.selectedName) {
    toolError.value = '先选中一个已保存文风';
    return;
  }
  try {
    await rollbackStyleCalibration(styleState.selectedName);
    await refreshStyles(styleState.selectedName);
    setToolMessage('文风已回滚到校准前版本');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '文风回滚失败', 'error');
  }
}

async function handleStyleMergeRun() {
  if (!styleMergeForm.styleName.trim() || styleMergeForm.selectedStyles.length === 0) {
    toolError.value = '先选目标名称和要融合的文风';
    return;
  }
  lastStyleAction.value = 'merge';
  await runStream(streamStyleMerge, {
    style_name: styleMergeForm.styleName.trim(),
    selected_styles: styleMergeForm.selectedStyles,
    user_preference: styleMergeForm.userPreference.trim(),
  });
}

async function saveBlueprintResult() {
  if (!props.project?.id || !toolResult.value?.blueprint) {
    return;
  }
  try {
    const detail = await updateStoryDocument(props.project.id, 'blueprint', {
      content: toolResult.value.blueprint,
    });
    emit('project-detail-updated', detail);
    setToolMessage('章节蓝图已写回项目');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '写回章节蓝图失败', 'error');
  }
}

async function saveScenesToBlueprint() {
  if (!props.project?.id || !props.selectedChapter || !toolResult.value?.scenes?.length) {
    return;
  }
  try {
    const mergedContent = mergeBlueprintContent(
      currentDocumentContent('blueprint'),
      buildBlueprintSectionFromScenes(),
    );
    const detail = await updateStoryDocument(props.project.id, 'blueprint', {
      content: mergedContent,
    });
    emit('project-detail-updated', detail);
    setToolMessage('拆场结果已写入章节蓝图');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '写入章节蓝图失败', 'error');
  }
}

async function saveGeneratedChapter(content = toolResult.value?.content ?? toolResult.value?.revised ?? '') {
  if (!props.project?.id || !props.selectedChapter?.id || !content) {
    return;
  }
  const styleName = toolResult.value?.revised
    ? rewriteForm.styleName.trim()
    : chapterGenerateForm.styleName.trim();
  try {
    const { detail, reviewError } = await updateProjectChapter(props.project.id, props.selectedChapter.id, {
      content,
      style_name: styleName,
    });
    emit('project-detail-updated', detail);
    setToolMessage(reviewError || '正文已保存到当前章节');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '正文保存失败', 'error');
  }
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

async function saveNoteToProjectMemory(title, content, category = '目标') {
  if (!props.project?.id || !content.trim()) {
    return;
  }
  const manualEntries = currentManualMemoryEntries();
  const nextEntry = {
    title: title.trim(),
    category,
    content: content.trim(),
  };
  const alreadyExists = manualEntries.some((item) => (
    item.title === nextEntry.title && item.content === nextEntry.content
  ));
  const entries = alreadyExists
    ? manualEntries
    : [...manualEntries.slice(-29), nextEntry];

  try {
    const detail = await updateProjectMemory(props.project.id, { entries });
    emit('project-detail-updated', detail);
    setToolMessage('结果已记入项目记忆');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '项目记忆保存失败', 'error');
  }
}

async function saveRewriteDocument(documentKey, content) {
  if (!props.project?.id || !content) {
    return;
  }
  try {
    const detail = await updateStoryDocument(props.project.id, documentKey, { content });
    emit('project-detail-updated', detail);
    setToolMessage('关联设定文件已更新');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '设定文件更新失败', 'error');
  }
}

async function saveStreamStyleResult() {
  const result = toolResult.value;
  const styleName = (
    lastStyleAction.value === 'merge'
      ? styleMergeForm.styleName.trim()
      : lastStyleAction.value === 'dna'
        ? (styleDnaForm.styleName.trim() || styleState.selectedName)
        : lastStyleAction.value === 'calibrate' || lastStyleAction.value === 'narrative-calibrate'
          ? styleState.selectedName
          : styleAnalyzeForm.styleName.trim()
  ) || '';
  if (!styleName || !result) {
    return;
  }
  const sourceSample = (
    lastStyleAction.value === 'dna'
      ? styleDnaForm.sampleText.trim()
      : styleAnalyzeForm.sampleText.trim() || styleDnaForm.sampleText.trim()
  );
  const calibrationReference = [
    styleCalibrateForm.userPreference.trim(),
    styleAnalyzeForm.userPreference.trim(),
    styleDnaForm.userPreference.trim(),
    styleMergeForm.userPreference.trim(),
  ].find((item) => item) || '';
  try {
    await saveStyle(styleName, {
      instruction: result.instruction ?? '',
      analysis: result.analysis ?? '',
      dna_analysis: result.dna_analysis ?? '',
      narrative_for_architecture: result.narrative_for_architecture ?? '',
      narrative_for_blueprint: result.narrative_for_blueprint ?? '',
      narrative_for_chapter: result.narrative_for_chapter ?? '',
      source_sample: sourceSample,
      calibration_reference: calibrationReference,
      calibration_notes: result.calibration_notes ?? '',
    });
    styleState.selectedName = styleName;
    await refreshStyles(styleName);
    setToolMessage('文风方案已保存');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '文风保存失败', 'error');
  }
}

async function runKnowledgeSearch() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  try {
    knowledgeHits.value = await searchProjectKnowledge(
      props.project.id,
      knowledgeForm.query.trim(),
      Number(knowledgeForm.limit),
    );
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '知识检索失败', 'error');
  }
}

async function importKnowledgeItem() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  if (!knowledgeForm.importTitle.trim() || !knowledgeForm.importContent.trim()) {
    setToolMessage('先填写资料标题和内容', 'error');
    return;
  }
  try {
    const detail = await importProjectKnowledge(props.project.id, {
      items: [
        {
          title: knowledgeForm.importTitle.trim(),
          content: knowledgeForm.importContent.trim(),
        },
      ],
    });
    emit('project-detail-updated', detail);
    knowledgeForm.importTitle = '';
    knowledgeForm.importContent = '';
    setToolMessage('资料已经导入当前项目');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '资料导入失败', 'error');
  }
}

async function runWebResearch() {
  if (!ensureProjectAndChapter({ chapter: false })) {
    return;
  }
  if (!webResearchForm.query.trim()) {
    setToolMessage('先填写要考据的问题', 'error');
    return;
  }
  isWebResearching.value = true;
  webResearchResult.value = null;
  try {
    webResearchResult.value = await researchHistoricalReferences(
      props.project.id,
      webResearchForm.query.trim(),
      Number(webResearchForm.limit),
    );
    if (webResearchResult.value?.warning) {
      setToolMessage(webResearchResult.value.warning, 'error');
    } else {
      setToolMessage(`已完成${webResearchProviderLabel(webResearchResult.value?.provider)}考据`);
    }
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '联网考据失败', 'error');
  } finally {
    isWebResearching.value = false;
  }
}

function buildWebResearchMaterial(result = webResearchResult.value) {
  if (!result) {
    return '';
  }
  const sourceLines = (result.sources ?? []).map((item, index) => [
    `${index + 1}. ${item.title || item.site || item.url}`,
    item.url ? `链接：${item.url}` : '',
    item.snippet ? `摘要：${item.snippet}` : '',
  ].filter(Boolean).join('\n'));
  const localLines = (result.local_hits ?? []).map((item, index) => (
    `${index + 1}. ${item.section}（${item.source}）：${item.preview}`
  ));
  return [
    `# 联网考据：${result.query}`,
    '',
    `搜索源：${webResearchProviderLabel(result.provider)}`,
    result.warning ? `提示：${result.warning}` : '',
    '',
    '## 研究简报',
    result.answer || '',
    '',
    '## 联网来源',
    sourceLines.length ? sourceLines.join('\n\n') : '无',
    '',
    '## 项目资料命中',
    localLines.length ? localLines.join('\n') : '无',
  ].filter((item) => item !== '').join('\n');
}

async function importWebResearchResult() {
  if (!ensureProjectAndChapter({ chapter: false })) {
    return;
  }
  const content = buildWebResearchMaterial();
  if (!content.trim()) {
    setToolMessage('还没有可保存的考据结果', 'error');
    return;
  }
  if (!canImportWebResearchResult.value) {
    setToolMessage('联网考据成功后才能保存到资料库', 'error');
    return;
  }
  try {
    const detail = await importProjectKnowledge(props.project.id, {
      items: [
        {
          title: `联网考据-${webResearchResult.value?.query || webResearchForm.query.trim()}`,
          content,
        },
      ],
    });
    emit('project-detail-updated', detail);
    setToolMessage('考据结果已保存到项目资料库');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '考据结果保存失败', 'error');
  }
}

async function refreshFiles(selectedPath = filesState.selectedPath) {
  if (!props.project?.id) {
    return;
  }
  filesState.list = await listProjectFiles(props.project.id);
  const nextPath = selectedPath || filesState.list[0]?.path || '';
  if (nextPath) {
    await openFile(nextPath);
  }
}

async function openFile(path) {
  if (!props.project?.id || !path) {
    return;
  }
  const payload = await getProjectFileContent(props.project.id, path);
  filesState.selectedPath = payload.path;
  filesState.content = payload.content;
}

async function handleSaveProjectFile() {
  if (!props.project?.id || !filesState.selectedPath) {
    return;
  }
  filesState.isSaving = true;
  try {
    await updateProjectFileContent(props.project.id, filesState.selectedPath, {
      content: filesState.content,
    });
    await refreshProjectDetail();
    await refreshFiles(filesState.selectedPath);
    setToolMessage('文件内容已保存');
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '文件保存失败', 'error');
  } finally {
    filesState.isSaving = false;
  }
}

async function refreshLogs() {
  const payload = await getStudioLogs(300);
  logsState.content = payload.content ?? '';
}

async function handleClearLogs() {
  await clearStudioLogs();
  await refreshLogs();
  setToolMessage('运行日志已清空');
}

async function refreshPromptHistory() {
  const payload = await getPromptHistory(80, promptHistoryState.search.trim());
  promptHistoryState.records = payload.records ?? [];
  promptHistoryState.total = payload.total ?? 0;
}

async function handleClearPromptHistory() {
  await clearPromptHistory();
  await refreshPromptHistory();
  setToolMessage('Prompt 历史已清空');
}

function selfEvolutionKindLabel(kind) {
  return {
    skill: '技能候选',
    prompt: 'Prompt 样本',
    memory: '记忆候选',
    review: '章节评测',
  }[kind] ?? kind;
}

function curationStatusLabel(status) {
  return {
    active: '保留',
    stale: '待复查',
    archive_candidate: '可归档',
  }[status] ?? status;
}

async function refreshSelfEvolution() {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  selfEvolutionState.report = await getSelfEvolutionReport(props.project.id);
}

function resetPromptPresetDraft() {
  promptPresetDraft.name = '';
  promptPresetDraft.description = '';
  Object.assign(promptPresetDraft.prompts, {
    architecture: '',
    brainstorm: '',
    blueprint: '',
    chapter: '',
    finalize: '',
    polish: '',
    humanize: '',
  });
}

async function refreshPromptPresets(preferredName = promptPresetState.selectedName) {
  const payload = await listPromptPresets();
  promptPresetState.list = payload.presets ?? [];
  promptPresetState.activeName = payload.active_preset ?? '';
  const candidateNames = new Set(promptPresetState.list.map((item) => item.name));
  const nextName = [
    preferredName,
    promptPresetState.activeName,
    promptPresetState.list[0]?.name,
  ].find((name) => name && candidateNames.has(name)) || '';
  if (nextName) {
    await loadPromptPresetDetail(nextName);
  } else {
    resetPromptPresetDraft();
  }
}

async function loadPromptPresetDetail(name) {
  promptPresetState.selectedName = name;
  const detail = await getPromptPresetDetail(name);
  promptPresetDraft.name = detail.name ?? name;
  promptPresetDraft.description = detail.description ?? '';
  Object.assign(promptPresetDraft.prompts, {
    architecture: '',
    brainstorm: '',
    blueprint: '',
    chapter: '',
    finalize: '',
    polish: '',
    humanize: '',
    ...(detail.prompts ?? {}),
  });
}

async function handleCreatePromptPreset() {
  if (!promptPresetDraft.name.trim()) {
    setToolMessage('先给方案起一个名字', 'error');
    return;
  }
  await createPromptPreset({
    name: promptPresetDraft.name.trim(),
    description: promptPresetDraft.description.trim(),
  });
  await updatePromptPreset(promptPresetDraft.name.trim(), {
    description: promptPresetDraft.description.trim(),
    prompts: { ...promptPresetDraft.prompts },
  });
  await refreshPromptPresets(promptPresetDraft.name.trim());
  setToolMessage('提示词方案已创建');
}

async function handleSavePromptPreset() {
  if (!promptPresetState.selectedName) {
    return;
  }
  await updatePromptPreset(promptPresetState.selectedName, {
    description: promptPresetDraft.description.trim(),
    prompts: { ...promptPresetDraft.prompts },
  });
  await refreshPromptPresets(promptPresetState.selectedName);
  setToolMessage('提示词方案已保存');
}

async function handleActivatePromptPreset() {
  if (!promptPresetState.selectedName) {
    return;
  }
  await activatePromptPreset(promptPresetState.selectedName);
  await refreshPromptPresets(promptPresetState.selectedName);
  setToolMessage('当前全局提示词方案已切换');
}

async function handleDeletePromptPreset() {
  if (!promptPresetState.selectedName) {
    return;
  }
  await deletePromptPreset(promptPresetState.selectedName);
  await refreshPromptPresets();
  setToolMessage('提示词方案已删除');
}

async function refreshXpPresets(selectedName = xpPresetState.selectedName) {
  xpPresetState.list = await listXpPresets();
  const next = selectedName || xpPresetState.list[0]?.name || '';
  if (next) {
    selectXpPreset(next);
  } else {
    xpPresetState.selectedName = '';
    xpPresetState.draftName = '';
    xpPresetState.draftContent = '';
  }
}

function selectXpPreset(name) {
  const item = xpPresetState.list.find((entry) => entry.name === name);
  xpPresetState.selectedName = item?.name ?? '';
  xpPresetState.draftName = item?.name ?? '';
  xpPresetState.draftContent = item?.content ?? '';
}

async function handleCreateXpPreset() {
  if (!xpPresetState.draftName.trim() || !xpPresetState.draftContent.trim()) {
    setToolMessage('先填写 XP 名称和内容', 'error');
    return;
  }
  await createXpPreset({
    name: xpPresetState.draftName.trim(),
    content: xpPresetState.draftContent.trim(),
  });
  await refreshXpPresets(xpPresetState.draftName.trim());
  setToolMessage('XP 预设已创建');
}

async function handleSaveXpPreset() {
  if (!xpPresetState.selectedName) {
    return;
  }
  await updateXpPreset(xpPresetState.selectedName, {
    name: xpPresetState.draftName.trim(),
    content: xpPresetState.draftContent.trim(),
  });
  await refreshXpPresets(xpPresetState.draftName.trim());
  setToolMessage('XP 预设已保存');
}

async function handleDeleteXpPreset() {
  if (!xpPresetState.selectedName) {
    return;
  }
  await deleteXpPreset(xpPresetState.selectedName);
  await refreshXpPresets();
  setToolMessage('XP 预设已删除');
}

function resetStyleReferenceInputs() {
  styleState.referenceTitle = '';
  styleState.referenceContent = '';
}

async function refreshStyles(selectedName = styleState.selectedName) {
  styleState.list = await listStyles();
  const candidateNames = new Set(styleState.list.map((item) => item.name));
  const nextName = [
    selectedName,
    styleState.list[0]?.name,
  ].find((name) => name && candidateNames.has(name)) || '';
  if (nextName) {
    await loadStyleDetail(nextName);
  } else {
    styleState.selectedName = '';
    styleState.detail = null;
  }
}

async function loadStyleDetail(name) {
  styleState.selectedName = name;
  styleState.detail = await getStyleDetail(name);
  styleState.referenceHits = [];
  styleAnalyzeForm.styleName = name;
  styleDnaForm.styleName = name;
  styleMergeForm.selectedStyles = styleMergeForm.selectedStyles.filter((item) => (
    styleState.list.some((style) => style.name === item)
  ));
}

async function handleSaveStyleDetail() {
  if (!styleState.selectedName || !styleState.detail) {
    return;
  }
  await saveStyle(styleState.selectedName, {
    instruction: styleState.detail.instruction ?? '',
    analysis: styleState.detail.analysis ?? '',
    dna_analysis: styleState.detail.dna_analysis ?? '',
    narrative_for_architecture: styleState.detail.narrative_for_architecture ?? '',
    narrative_for_blueprint: styleState.detail.narrative_for_blueprint ?? '',
    narrative_for_chapter: styleState.detail.narrative_for_chapter ?? '',
    source_sample: styleState.detail.source_sample ?? '',
    calibration_reference: styleState.detail.calibration_reference ?? '',
    calibration_notes: styleState.detail.calibration_notes ?? '',
  });
  await refreshStyles(styleState.selectedName);
  setToolMessage('文风详情已保存');
}

async function handleDeleteStyle() {
  if (!styleState.selectedName) {
    return;
  }
  await deleteStyle(styleState.selectedName);
  await refreshStyles();
  setToolMessage('文风方案已删除');
}

async function handleImportStyleReference() {
  if (!styleState.selectedName || !styleState.referenceTitle.trim() || !styleState.referenceContent.trim()) {
    setToolMessage('先选中文风，再填写参考资料标题和内容', 'error');
    return;
  }
  await importStyleReferences(styleState.selectedName, {
    items: [
      {
        title: styleState.referenceTitle.trim(),
        content: styleState.referenceContent.trim(),
      },
    ],
  });
  resetStyleReferenceInputs();
  await refreshStyles(styleState.selectedName);
  if (styleState.referenceQuery.trim()) {
    styleState.referenceHits = await searchStyleReferences(styleState.selectedName, styleState.referenceQuery.trim(), 6);
  }
  setToolMessage('作者参考资料已导入');
}

async function handleClearStyleReferences() {
  if (!styleState.selectedName) {
    return;
  }
  await clearStyleReferences(styleState.selectedName);
  await refreshStyles(styleState.selectedName);
  styleState.referenceHits = [];
  setToolMessage('当前文风的参考资料已清空');
}

async function handleSearchStyleReferences() {
  if (!styleState.selectedName) {
    setToolMessage('先选中文风，再搜索作者参考', 'error');
    return;
  }
  if (!styleState.referenceQuery.trim()) {
    styleState.referenceHits = [];
    setToolMessage('先输入参考检索词', 'error');
    return;
  }
  try {
    styleState.referenceHits = await searchStyleReferences(styleState.selectedName, styleState.referenceQuery.trim(), 6);
    setToolMessage(`找到 ${styleState.referenceHits.length} 条作者参考`);
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '作者参考搜索失败', 'error');
  }
}

function titleFromFilename(name) {
  return name.replace(/\.[^.]+$/, '').trim() || name;
}

async function readTextImportItems(fileList) {
  const files = Array.from(fileList ?? []);
  const items = [];
  for (const file of files) {
    const content = await file.text();
    const trimmed = content.trim();
    if (!trimmed) {
      continue;
    }
    items.push({
      title: titleFromFilename(file.name),
      content: trimmed,
    });
  }
  return items;
}

async function handleKnowledgeFilesSelected(event) {
  const files = await buildImportedFilePayloads(event.target.files);
  event.target.value = '';
  if (!ensureProjectAndChapter()) {
    return;
  }
  if (files.length === 0) {
    setToolMessage('选中的文件没有可导入内容', 'error');
    return;
  }
  try {
    const detail = await importProjectKnowledgeFiles(props.project.id, { files });
    emit('project-detail-updated', detail);
    setToolMessage(`已导入 ${files.length} 份资料`);
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '文件导入失败', 'error');
  }
}

async function handleStyleSampleFilesSelected(event) {
  const items = await readTextImportItems(event.target.files);
  event.target.value = '';
  if (items.length === 0) {
    setToolMessage('选中的文件没有可用内容', 'error');
    return;
  }
  styleAnalyzeForm.sampleText = items.map((item) => `【${item.title}】\n${item.content}`).join('\n\n');
  if (!styleDnaForm.sampleText.trim()) {
    styleDnaForm.sampleText = styleAnalyzeForm.sampleText;
  }
  if (!styleAnalyzeForm.styleName.trim()) {
    styleAnalyzeForm.styleName = items[0].title;
  }
  if (!styleDnaForm.styleName.trim()) {
    styleDnaForm.styleName = styleAnalyzeForm.styleName;
  }
  setToolMessage(`已载入 ${items.length} 份样文`);
}

async function handleStyleReferenceFilesSelected(event) {
  const files = await buildImportedFilePayloads(event.target.files);
  event.target.value = '';
  if (!styleState.selectedName) {
    setToolMessage('先选中文风，再导入参考文件', 'error');
    return;
  }
  if (files.length === 0) {
    setToolMessage('选中的文件没有可导入内容', 'error');
    return;
  }
  await importStyleReferenceFiles(styleState.selectedName, { files });
  await refreshStyles(styleState.selectedName);
  if (styleState.referenceQuery.trim()) {
    styleState.referenceHits = await searchStyleReferences(styleState.selectedName, styleState.referenceQuery.trim(), 6);
  }
  setToolMessage(`已导入 ${files.length} 份作者参考资料`);
}
</script>

<template>
  <section class="skills-page">
    <header class="skills-topbar">
      <div class="skills-actions">
        <button
          data-testid="return-workspace-button"
          class="utility-button utility-button-primary"
          type="button"
          @click="emit('return-workspace')"
        >
          返回工作台
        </button>
        <button
          data-testid="open-prompt-presets-button"
          class="utility-button"
          type="button"
          @click="activateTool('prompt-presets')"
        >
          提示词方案
        </button>
        <button
          data-testid="open-style-dna-button"
          class="utility-button"
          type="button"
          @click="activateTool('style-dna')"
        >
          文风与 DNA
        </button>
      </div>
    </header>

    <section class="overview-shell">
      <div class="overview-copy">
        <div class="overview-title-row">
          <p class="skills-kicker">写作技能库</p>
          <p class="skills-summary">
            常用写作工具集中在这里，选择技能后在下方继续处理当前项目。
          </p>
        </div>

        <div class="overview-pills">
          <span class="overview-pill">{{ totalSkillCount }} 个技能</span>
          <span class="overview-pill">{{ currentProjectLine }}</span>
          <span class="overview-pill">{{ modelName }}</span>
        </div>
      </div>
    </section>

    <section class="controls-shell">
      <label class="search-bar">
        <span class="search-icon">⌕</span>
        <input
          v-model="keyword"
          type="text"
          placeholder="搜索技能名称、用途或适用场景"
        >
      </label>

      <div class="filter-row">
        <button
          v-for="filter in skillFilters"
          :key="filter"
          :class="['filter-pill', { 'filter-pill-active': activeFilter === filter }]"
          type="button"
          @click="activeFilter = filter"
        >
          {{ filter }}
        </button>
      </div>
    </section>

    <section
      v-for="section in filteredSections"
      :key="section.title"
      class="catalog-section"
    >
      <div class="section-header">
        <div>
          <h3>{{ section.title }}</h3>
          <p>{{ section.description }}</p>
        </div>
        <span>{{ section.items.length }} 个技能</span>
      </div>

      <div class="skills-grid">
        <article
          v-for="item in section.items"
          :key="item.id"
          class="skill-card"
          :data-testid="`skill-card-${item.id}`"
        >
          <div :class="['skill-badge', `skill-badge-${item.accent}`]">
            {{ item.badge }}
          </div>

          <div class="skill-meta">
            <div class="skill-title-row">
              <strong>{{ item.name }}</strong>
              <span class="skill-tag">{{ item.category }}</span>
            </div>

            <p>{{ item.description }}</p>

            <div class="scene-row">
              <span
                v-for="scene in item.scenes"
                :key="scene"
                class="scene-pill"
              >
                {{ scene }}
              </span>
            </div>
          </div>

          <button
            class="skill-use"
            :data-testid="`skill-use-${item.id}`"
            type="button"
            @click="activateTool(item)"
          >
            使用
          </button>
        </article>
      </div>
    </section>

    <section
      v-if="filteredSections.length === 0"
      class="skills-empty"
    >
      当前筛选条件下没有匹配技能。
    </section>

    <section
      v-if="activeToolId"
      ref="workbenchRef"
      class="workbench-shell"
      data-testid="skill-workbench"
    >
      <header class="workbench-head">
        <div>
          <p class="workbench-kicker">技能工作区</p>
          <h3>{{ activeToolLabel }}</h3>
          <p class="workbench-copy">{{ activeToolDescription }}</p>
        </div>

        <div class="overview-pills">
          <span class="overview-pill">{{ currentProjectLine }}</span>
          <span
            v-if="toolTaskId"
            class="overview-pill"
          >
            任务 {{ toolTaskId }}
          </span>
        </div>
      </header>

      <section
        v-if="toolMessage"
        :class="['notice-banner', toolMessageTone === 'error' ? 'notice-banner-error' : 'notice-banner-success']"
      >
        {{ toolMessage }}
      </section>

      <section
        v-if="toolError"
        class="error-banner"
      >
        {{ toolError }}
      </section>

      <div
        v-if="(activeToolNeedsProject && !project) || (activeToolNeedsChapter && !selectedChapter)"
        class="workbench-empty"
      >
        {{ activeToolNeedsChapter ? '先在左侧选中作品和章节，再使用这个技能。' : '先在左侧选中作品，再使用这个技能。' }}
      </div>

      <div
        v-else
        class="workbench-grid"
      >
        <section class="workbench-panel">
          <template v-if="activeToolPanelKey === 'brainstorm'">
            <div class="field-stack">
              <label class="form-field">
                <span>这一轮讨论的问题</span>
                <textarea
                  v-model="brainstormState.input"
                  rows="5"
                  placeholder="把当前最想讨论的问题直接写出来。"
                />
              </label>

              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleBrainstormRun"
              >
                {{ isToolRunning ? '讨论中…' : '开始讨论' }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'character-replica'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>人物卡</h4>
                  <div class="action-row">
                    <button
                      class="secondary-button small-button"
                      type="button"
                      @click="refreshCharacterReplicaProfiles()"
                    >
                      刷新
                    </button>
                    <button
                      class="secondary-button small-button"
                      data-testid="character-replica-save-profile-button"
                      type="button"
                      @click="handleSaveCharacterReplicaProfile"
                    >
                      保存人物卡
                    </button>
                    <button
                      :disabled="!characterReplicaLibraryState.selectedName"
                      class="secondary-button small-button"
                      type="button"
                      @click="handleDeleteCharacterReplicaProfile"
                    >
                      删除
                    </button>
                  </div>
                </div>
                <div
                  v-if="characterReplicaLibraryState.list.length"
                  class="list-column"
                >
                  <button
                    v-for="item in characterReplicaLibraryState.list"
                    :key="item.name"
                    :class="['list-item-button', { 'list-item-button-active': characterReplicaLibraryState.selectedName === item.name }]"
                    type="button"
                    @click="loadCharacterReplicaProfile(item.name)"
                  >
                    <strong>{{ item.name }}</strong>
                    <span>{{ item.summary || '已保存人物资料，可直接复用。' }}</span>
                  </button>
                </div>
                <div
                  v-else
                  class="workbench-empty"
                >
                  还没有保存的人物卡。
                </div>
              </div>
              <label class="form-field">
                <span>人物名称</span>
                <input
                  v-model="characterReplicaForm.personaName"
                  data-testid="character-replica-persona-input"
                  placeholder="比如：乔布斯、王家卫、张雪峰"
                >
              </label>
              <label class="form-field">
                <span>你要问的问题</span>
                <textarea
                  v-model="characterReplicaForm.question"
                  data-testid="character-replica-question-input"
                  rows="5"
                  placeholder="比如：如果用这个人的视角看，我这一章的开头该怎么改？"
                />
              </label>
              <label class="form-field">
                <span>希望强调</span>
                <textarea
                  v-model="characterReplicaForm.focus"
                  data-testid="character-replica-focus-input"
                  rows="3"
                  placeholder="比如：只看人物选择，不看文风模仿。"
                />
              </label>
              <label class="form-field">
                <span>补充资料</span>
                <textarea
                  v-model="characterReplicaForm.sourceNotes"
                  data-testid="character-replica-notes-input"
                  rows="7"
                  placeholder="可以贴这个人的观点、语录、访谈摘要，或者你自己整理的资料。"
                />
              </label>
              <div class="action-row">
                <label class="checkbox-field">
                  <input
                    v-model="characterReplicaForm.useProjectContext"
                    type="checkbox"
                  >
                  <span>带上当前作品上下文</span>
                </label>
                <label class="checkbox-field">
                  <input
                    v-model="characterReplicaForm.useChapterContext"
                    :disabled="!selectedChapter"
                    type="checkbox"
                  >
                  <span>带上当前章节</span>
                </label>
              </div>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleCharacterReplicaRun"
              >
                {{ isToolRunning ? '复刻中…' : '开始复刻' }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'chapter-workflow' && activeChapterWorkflowConfig">
            <div class="field-stack">
              <label class="form-field">
                <span>{{ activeChapterWorkflowConfig.instructionLabel }}</span>
                <textarea
                  v-model="activeChapterWorkflowConfig.form.instruction"
                  rows="5"
                />
              </label>
              <label class="form-field compact-field">
                <span>{{ activeChapterWorkflowConfig.targetWordsLabel }}</span>
                <input
                  v-model.number="activeChapterWorkflowConfig.form.targetWords"
                  type="number"
                  :min="activeChapterWorkflowConfig.min"
                  :max="activeChapterWorkflowConfig.max"
                  :step="activeChapterWorkflowConfig.step"
                >
              </label>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleActiveChapterWorkflowRun"
              >
                {{ isToolRunning ? activeChapterWorkflowConfig.runningLabel : activeChapterWorkflowConfig.submitLabel }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'consistency'">
            <div class="field-stack">
              <label class="form-field">
                <span>检查重点</span>
                <textarea
                  v-model="consistencyForm.focus"
                  rows="5"
                />
              </label>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleConsistencyRun"
              >
                {{ isToolRunning ? '检查中…' : '开始检查' }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'blueprint'">
            <div class="field-stack">
              <label class="form-field">
                <span>蓝图要求</span>
                <textarea
                  v-model="blueprintForm.instruction"
                  rows="5"
                  placeholder="比如：前三章钩子更明确一点。"
                />
              </label>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>目标章节数</span>
                  <input
                    v-model="blueprintForm.chapterCount"
                    type="number"
                    min="1"
                    max="1000"
                  >
                </label>
                <label class="form-field">
                  <span>XP 预设</span>
                  <select v-model="blueprintForm.xpPreset">
                    <option value="">
                      不使用
                    </option>
                    <option
                      v-for="item in availableXpPresets"
                      :key="item.name"
                      :value="item.name"
                    >
                      {{ item.name }}
                    </option>
                  </select>
                </label>
              </div>
              <label class="form-field">
                <span>文风方案</span>
                <input
                  v-model="blueprintForm.styleName"
                  placeholder="可填已保存的文风名称"
                >
              </label>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleBlueprintRun"
              >
                {{ isToolRunning ? '生成中…' : '生成蓝图' }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'chapter-generate'">
            <div class="field-stack">
              <label class="form-field">
                <span>写作要求</span>
                <textarea
                  v-model="chapterGenerateForm.instruction"
                  rows="4"
                />
              </label>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>涉及人物</span>
                  <input v-model="chapterGenerateForm.charactersInvolved">
                </label>
                <label class="form-field">
                  <span>关键道具</span>
                  <input v-model="chapterGenerateForm.keyItems">
                </label>
                <label class="form-field">
                  <span>场景地点</span>
                  <input v-model="chapterGenerateForm.sceneLocation">
                </label>
                <label class="form-field">
                  <span>时间限制</span>
                  <input v-model="chapterGenerateForm.timeConstraint">
                </label>
              </div>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>文风方案</span>
                  <input v-model="chapterGenerateForm.styleName">
                </label>
                <label class="form-field">
                  <span>XP 预设</span>
                  <select v-model="chapterGenerateForm.xpPreset">
                    <option value="">
                      不使用
                    </option>
                    <option
                      v-for="item in availableXpPresets"
                      :key="item.name"
                      :value="item.name"
                    >
                      {{ item.name }}
                    </option>
                  </select>
                </label>
              </div>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleChapterGenerateRun"
              >
                {{ isToolRunning ? '生成中…' : '生成正文' }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'chapter-rewrite' && activeRewriteConfig">
            <div class="field-stack">
              <label class="form-field">
                <span>{{ activeRewriteConfig.instructionLabel }}</span>
                <textarea
                  v-model="rewriteForm.instruction"
                  rows="5"
                />
              </label>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>文风方案</span>
                  <input v-model="rewriteForm.styleName">
                </label>
                <label class="form-field">
                  <span>XP 预设</span>
                  <select v-model="rewriteForm.xpPreset">
                    <option value="">
                      不使用
                    </option>
                    <option
                      v-for="item in availableXpPresets"
                      :key="item.name"
                      :value="item.name"
                    >
                      {{ item.name }}
                    </option>
                  </select>
                </label>
              </div>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleRewriteRun()"
              >
                {{ isToolRunning ? '处理中…' : activeRewriteConfig.submitLabel }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'batch-generate'">
            <div class="field-stack">
              <div class="two-column-grid">
                <label class="form-field">
                  <span>起始章节</span>
                  <input
                    v-model.number="batchForm.startChapter"
                    type="number"
                    min="1"
                    :max="project?.target_chapters ?? 1"
                  >
                </label>
                <label class="form-field">
                  <span>结束章节</span>
                  <input
                    v-model.number="batchForm.endChapter"
                    type="number"
                    min="1"
                    :max="project?.target_chapters ?? 1"
                  >
                </label>
              </div>
              <label class="form-field">
                <span>批量要求</span>
                <textarea
                  v-model="batchForm.instruction"
                  rows="4"
                />
              </label>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>文风方案</span>
                  <input v-model="batchForm.styleName">
                </label>
                <label class="form-field">
                  <span>XP 预设</span>
                  <select v-model="batchForm.xpPreset">
                    <option value="">
                      不使用
                    </option>
                    <option
                      v-for="item in availableXpPresets"
                      :key="item.name"
                      :value="item.name"
                    >
                      {{ item.name }}
                    </option>
                  </select>
                </label>
              </div>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>任务 ID</span>
                  <input v-model="batchForm.taskId">
                </label>
                <label class="checkbox-field form-checkbox-field">
                  <input
                    v-model="batchForm.retryFailed"
                    type="checkbox"
                  >
                  <span>失败章节重试</span>
                </label>
              </div>
              <label class="form-field">
                <span>人工评论</span>
                <textarea
                  v-model="batchForm.comment"
                  rows="2"
                />
              </label>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleBatchRun"
              >
                {{ isToolRunning ? '批量处理中…' : (batchForm.taskId.trim() ? '继续批量任务' : '开始批量生成') }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'continue-project'">
            <div class="field-stack">
              <label class="form-field compact-field">
                <span>新增章节数</span>
                <input
                  v-model.number="continueForm.newChapters"
                  type="number"
                  min="1"
                  max="200"
                >
              </label>
              <label class="form-field">
                <span>扩写要求</span>
                <textarea
                  v-model="continueForm.instruction"
                  rows="5"
                />
              </label>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>文风方案</span>
                  <input v-model="continueForm.styleName">
                </label>
                <label class="form-field">
                  <span>XP 预设</span>
                  <select v-model="continueForm.xpPreset">
                    <option value="">
                      不使用
                    </option>
                    <option
                      v-for="item in availableXpPresets"
                      :key="item.name"
                      :value="item.name"
                    >
                      {{ item.name }}
                    </option>
                  </select>
                </label>
              </div>
              <button
                :disabled="isToolRunning"
                class="primary-button"
                type="button"
                @click="handleContinueRun"
              >
                {{ isToolRunning ? '扩写中…' : '开始续写扩展' }}
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'style-dna'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>样文分析</h4>
                  <button
                    :disabled="isToolRunning"
                    class="primary-button small-button"
                    type="button"
                    @click="handleStyleAnalyzeRun"
                  >
                    {{ isToolRunning ? '分析中…' : '分析文风' }}
                  </button>
                </div>
                <label class="form-field">
                  <span>文风名称</span>
                  <input v-model="styleAnalyzeForm.styleName">
                </label>
                <label class="form-field">
                  <span>样文</span>
                  <textarea
                    v-model="styleAnalyzeForm.sampleText"
                    rows="7"
                  />
                </label>
                <label class="form-field">
                  <span>从本地文本载入样文</span>
                  <input
                    accept=".txt,.md,.json"
                    multiple
                    type="file"
                    @change="handleStyleSampleFilesSelected"
                  >
                </label>
                <label class="form-field">
                  <span>补充偏好</span>
                  <textarea
                    v-model="styleAnalyzeForm.userPreference"
                    rows="3"
                  />
                </label>
              </div>

              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>DNA 分析</h4>
                  <button
                    :disabled="isToolRunning"
                    class="secondary-button small-button"
                    type="button"
                    @click="handleStyleAnalyzeDnaRun"
                  >
                    做 DNA 分析
                  </button>
                </div>
                <label class="form-field">
                  <span>目标文风</span>
                  <input v-model="styleDnaForm.styleName">
                </label>
                <label class="form-field">
                  <span>DNA 样文</span>
                  <textarea
                    v-model="styleDnaForm.sampleText"
                    rows="5"
                  />
                </label>
                <label class="form-field">
                  <span>补充要求</span>
                  <textarea
                    v-model="styleDnaForm.userPreference"
                    rows="3"
                  />
                </label>
              </div>

              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>文风融合</h4>
                  <button
                    :disabled="isToolRunning"
                    class="secondary-button small-button"
                    type="button"
                    @click="handleStyleMergeRun"
                  >
                    融合文风
                  </button>
                </div>
                <label class="form-field">
                  <span>新文风名称</span>
                  <input v-model="styleMergeForm.styleName">
                </label>
                <label class="form-field">
                  <span>融合偏好</span>
                  <textarea
                    v-model="styleMergeForm.userPreference"
                    rows="3"
                  />
                </label>
                <div class="check-grid">
                  <label
                    v-for="item in availableStyles"
                    :key="item.name"
                    class="check-pill"
                  >
                    <input
                      v-model="styleMergeForm.selectedStyles"
                      :value="item.name"
                      type="checkbox"
                    >
                    <span>{{ item.name }}</span>
                  </label>
                </div>
              </div>

              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>DNA 校准</h4>
                  <div class="action-row">
                    <button
                      class="secondary-button small-button"
                      type="button"
                      @click="handleStyleCalibrateRun('style')"
                    >
                      校准文风
                    </button>
                    <button
                      class="secondary-button small-button"
                      type="button"
                      @click="handleStyleCalibrateRun('narrative')"
                    >
                      校准叙事
                    </button>
                  </div>
                </div>
                <div class="two-column-grid">
                  <label class="form-field">
                    <span>迭代轮数</span>
                    <input
                      v-model.number="styleCalibrateForm.maxIterations"
                      min="1"
                      max="8"
                      type="number"
                    >
                  </label>
                  <label class="form-field">
                    <span>当前文风</span>
                    <input
                      :value="styleState.selectedName || styleAnalyzeForm.styleName || styleDnaForm.styleName"
                      disabled
                    >
                  </label>
                </div>
                <label class="form-field">
                  <span>本轮校准补充</span>
                  <textarea
                    v-model="styleCalibrateForm.userPreference"
                    rows="3"
                    placeholder="比如：镜头更贴人物、对白更短一点。"
                  />
                </label>
                <button
                  :disabled="!styleState.detail?.has_calibration_snapshot"
                  class="secondary-button"
                  type="button"
                  @click="handleRollbackStyleCalibration"
                >
                  回滚上一次校准
                </button>
              </div>

              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>已保存文风</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="refreshStyles()"
                  >
                    刷新
                  </button>
                </div>
                <div class="list-column">
                  <button
                    v-for="item in availableStyles"
                    :key="item.name"
                    :class="['list-item-button', { 'list-item-button-active': styleState.selectedName === item.name }]"
                    type="button"
                    @click="loadStyleDetail(item.name)"
                  >
                    <strong>{{ item.name }}</strong>
                    <span>{{ item.has_reference_library ? '有参考库' : '无参考库' }}</span>
                  </button>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'architecture-stepper'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>分步生成</h4>
                  <div class="action-row">
                    <button
                      class="secondary-button small-button"
                      type="button"
                      @click="syncArchitectureWorkspaceFromProject"
                    >
                      载入当前项目
                    </button>
                    <button
                      :disabled="isToolRunning"
                      class="primary-button small-button"
                      type="button"
                      @click="handleArchitectureStepRun"
                    >
                      {{ isToolRunning ? '生成中…' : '生成当前步骤' }}
                    </button>
                  </div>
                </div>
                <div class="two-column-grid">
                  <label class="form-field">
                    <span>模式</span>
                    <select v-model="architectureStepForm.mode">
                      <option value="initial">
                        初始架构
                      </option>
                      <option value="continue">
                        续写扩展
                      </option>
                    </select>
                  </label>
                  <label class="form-field">
                    <span>步骤</span>
                    <select v-model="architectureStepForm.step">
                      <option
                        v-for="(label, key) in architectureDocumentLabels"
                        :key="key"
                        :value="key"
                      >
                        {{ label }}
                      </option>
                    </select>
                  </label>
                </div>
                <label
                  v-if="architectureStepForm.mode === 'continue'"
                  class="form-field"
                >
                  <span>新增章节数</span>
                  <input
                    v-model.number="architectureStepForm.newChapters"
                    min="1"
                    max="200"
                    type="number"
                  >
                </label>
                <label class="form-field">
                  <span>补充要求</span>
                  <textarea
                    v-model="architectureStepForm.guidance"
                    rows="5"
                    placeholder="比如：先把主角和旧船队后人的关系拉清楚。"
                  />
                </label>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'prompt-presets'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>方案列表</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="refreshPromptPresets()"
                  >
                    刷新
                  </button>
                </div>
                <div class="list-column">
                  <button
                    v-for="item in promptPresetState.list"
                    :key="item.name"
                    :class="['list-item-button', { 'list-item-button-active': promptPresetState.selectedName === item.name }]"
                    type="button"
                    @click="loadPromptPresetDetail(item.name)"
                  >
                    <strong>{{ item.name }}</strong>
                    <span>{{ promptPresetState.activeName === item.name ? '当前启用' : item.description }}</span>
                  </button>
                </div>
              </div>

              <div class="action-row">
                <button
                  class="secondary-button"
                  data-testid="prompt-preset-activate-button"
                  type="button"
                  @click="handleActivatePromptPreset"
                >
                  设为当前
                </button>
                <button
                  class="secondary-button"
                  data-testid="prompt-preset-save-button"
                  type="button"
                  @click="handleSavePromptPreset"
                >
                  保存修改
                </button>
                <button
                  class="secondary-button"
                  data-testid="prompt-preset-delete-button"
                  type="button"
                  @click="handleDeletePromptPreset"
                >
                  删除
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'xp-presets'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>XP 列表</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="refreshXpPresets()"
                  >
                    刷新
                  </button>
                </div>
                <div class="list-column">
                  <button
                    v-for="item in xpPresetState.list"
                    :key="item.name"
                    :class="['list-item-button', { 'list-item-button-active': xpPresetState.selectedName === item.name }]"
                    type="button"
                    @click="selectXpPreset(item.name)"
                  >
                    <strong>{{ item.name }}</strong>
                    <span>{{ item.content }}</span>
                  </button>
                </div>
              </div>
              <div class="action-row">
                <button
                  class="secondary-button"
                  data-testid="xp-preset-create-button"
                  type="button"
                  @click="handleCreateXpPreset"
                >
                  新建
                </button>
                <button
                  class="secondary-button"
                  data-testid="xp-preset-save-button"
                  type="button"
                  @click="handleSaveXpPreset"
                >
                  保存
                </button>
                <button
                  class="secondary-button"
                  data-testid="xp-preset-delete-button"
                  type="button"
                  @click="handleDeleteXpPreset"
                >
                  删除
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'knowledge-search'">
            <div class="field-stack">
              <label class="form-field">
                <span>检索问题</span>
                <textarea
                  v-model="knowledgeForm.query"
                  data-testid="knowledge-search-input"
                  rows="4"
                  placeholder="比如：钥匙、旧船队、潮位窗口。"
                />
              </label>
              <button
                class="primary-button"
                data-testid="knowledge-search-button"
                type="button"
                @click="runKnowledgeSearch"
              >
                搜索知识
              </button>
                <label class="form-field">
                <span>导入本地资料</span>
                <input
                  :accept="importAcceptValue()"
                  multiple
                  type="file"
                  @change="handleKnowledgeFilesSelected"
                >
              </label>
              <label class="form-field">
                <span>资料标题</span>
                <input v-model="knowledgeForm.importTitle">
              </label>
              <label class="form-field">
                <span>资料内容</span>
                <textarea
                  v-model="knowledgeForm.importContent"
                  rows="6"
                />
              </label>
              <button
                class="secondary-button"
                type="button"
                @click="importKnowledgeItem"
              >
                导入资料
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'web-research'">
            <div class="field-stack">
              <label class="form-field">
                <span>考据问题</span>
                <textarea
                  v-model="webResearchForm.query"
                  data-testid="web-research-input"
                  rows="4"
                  placeholder="比如：鸿门宴典故能怎么改写成权谋场景。"
                />
              </label>
              <label class="form-field compact-field">
                <span>来源数量</span>
                <input
                  v-model.number="webResearchForm.limit"
                  data-testid="web-research-limit-input"
                  max="12"
                  min="1"
                  type="number"
                >
              </label>
              <div class="action-row">
                <button
                  :disabled="isWebResearching"
                  class="primary-button"
                  data-testid="web-research-button"
                  type="button"
                  @click="runWebResearch"
                >
                  {{ isWebResearching ? '考据中…' : '联网考据' }}
                </button>
                <button
                  :disabled="!canImportWebResearchResult"
                  class="secondary-button"
                  data-testid="web-research-import-button"
                  type="button"
                  @click="importWebResearchResult"
                >
                  存入资料库
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'reader'">
            <div class="field-stack">
              <label class="form-field">
                <span>选择章节</span>
                <select v-model="readerChapterId">
                  <option
                    v-for="item in project?.chapters ?? []"
                    :key="item.id"
                    :value="item.id"
                  >
                    第 {{ item.index }} 章 · {{ item.title }}
                  </option>
                </select>
              </label>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'file-browser'">
            <div class="field-stack">
              <div class="subpanel-head">
                <h4>项目文件</h4>
                <div class="action-row">
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="refreshFiles()"
                  >
                    刷新
                  </button>
                  <button
                    :disabled="filesState.isSaving || !filesState.selectedPath"
                    class="secondary-button small-button"
                    data-testid="file-browser-save-button"
                    type="button"
                    @click="handleSaveProjectFile"
                  >
                    {{ filesState.isSaving ? '保存中…' : '保存文件' }}
                  </button>
                </div>
              </div>
              <div class="list-column file-list">
                <button
                  v-for="item in filesState.list"
                  :key="item.path"
                  :class="['list-item-button', { 'list-item-button-active': filesState.selectedPath === item.path }]"
                  type="button"
                  @click="openFile(item.path)"
                >
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.directory || '根目录' }}</span>
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'logs'">
            <div class="action-row">
              <button
                class="secondary-button"
                type="button"
                @click="refreshLogs"
              >
                刷新日志
              </button>
              <button
                class="secondary-button"
                type="button"
                @click="handleClearLogs"
              >
                清空日志
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'prompt-history'">
            <div class="field-stack">
              <label class="form-field">
                <span>检索历史</span>
                <input
                  v-model="promptHistoryState.search"
                  placeholder="按任务名、模型名或关键词搜索"
                >
              </label>
              <div class="action-row">
                <button
                  class="secondary-button"
                  type="button"
                  @click="refreshPromptHistory"
                >
                  刷新
                </button>
                <button
                  class="secondary-button"
                  type="button"
                  @click="handleClearPromptHistory"
                >
                  清空历史
                </button>
              </div>
            </div>
          </template>
          <template v-else-if="activeToolPanelKey === 'self-evolution'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>进化报告</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="refreshSelfEvolution"
                  >
                    刷新
                  </button>
                </div>
                <p>报告只生成候选建议；记忆和技能写入仍需人工确认。</p>
              </div>
            </div>
          </template>
          <template v-else-if="activeToolPanelKey === 'conversation-skill'">
            <div class="field-stack">
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>用户沉淀技能</h4>
                </div>
                <p>这类技能从主对话里沉淀下来，使用时仍然回到主对话触发。</p>
                <ul
                  v-if="activeToolUsage.length"
                  class="plain-list"
                >
                  <li
                    v-for="item in activeToolUsage"
                    :key="item"
                  >
                    {{ item }}
                  </li>
                </ul>
              </div>
            </div>
          </template>
          <template v-else>
            <div class="workbench-empty">
              这个技能已经进入目录，但当前版本还没有对应的专用面板。
            </div>
          </template>
        </section>

        <section class="workbench-panel">
          <article
            v-if="isToolRunning || toolProgress.length > 0"
            class="progress-card"
          >
            <div class="progress-head">
              <strong>{{ currentProgress?.message ?? '正在处理' }}</strong>
              <span v-if="currentProgress?.total">第 {{ currentProgress.step }} / {{ currentProgress.total }} 步</span>
            </div>
            <div class="progress-bar">
              <div
                class="progress-bar-fill"
                :style="{ width: `${toolResult ? 100 : Math.max(((currentProgress?.step ?? 0) / (currentProgress?.total || 1)) * 100, isToolRunning ? 8 : 0)}%` }"
              />
            </div>
          </article>

          <template v-if="activeToolPanelKey === 'brainstorm'">
            <div class="message-list-shell">
              <article
                v-for="(item, index) in brainstormState.history"
                :key="`${item.role}-${index}`"
                :class="['message-card', item.role === 'user' ? 'message-card-user' : 'message-card-assistant']"
              >
                <div class="message-role">{{ item.role === 'user' ? '你' : '技能' }}</div>
                <p>{{ item.content }}</p>
              </article>
              <article
                v-if="toolResult?.suggestions?.length"
                class="message-card message-card-assistant"
              >
                <div class="message-role">下一轮可追问</div>
                <ul class="plain-list">
                  <li
                    v-for="item in toolResult.suggestions"
                    :key="item"
                  >
                    {{ item }}
                  </li>
                </ul>
              </article>
              <div
                v-if="brainstormState.history[brainstormState.history.length - 1]?.role === 'assistant'"
                class="action-row"
              >
                <button
                  class="secondary-button"
                  type="button"
                  @click="saveNoteToProjectMemory(
                    props.selectedChapter ? `第 ${props.selectedChapter.index} 章讨论结论` : '创意讨论结论',
                    brainstormState.history[brainstormState.history.length - 1]?.content ?? '',
                    '目标'
                  )"
                >
                  记到项目记忆
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'character-replica' && toolResult">
            <div class="result-shell">
              <h4>{{ toolResult.headline }}</h4>
              <p>{{ toolResult.summary }}</p>
              <p v-if="toolResult.disclaimer">
                {{ toolResult.disclaimer }}
              </p>
              <div class="issue-list">
                <article
                  v-if="toolResult.voice_profile"
                  class="issue-card"
                >
                  <strong>表达特征</strong>
                  <p>{{ toolResult.voice_profile }}</p>
                </article>
              </div>
              <div class="two-column-grid">
                <div>
                  <h4>判断框架</h4>
                  <ul class="plain-list">
                    <li
                      v-for="item in toolResult.mental_models ?? []"
                      :key="`model-${item}`"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </div>
                <div>
                  <h4>判断原则</h4>
                  <ul class="plain-list">
                    <li
                      v-for="item in toolResult.heuristics ?? []"
                      :key="`heuristic-${item}`"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </div>
              </div>
              <div>
                <h4>适用边界</h4>
                <ul class="plain-list">
                  <li
                    v-for="item in toolResult.boundaries ?? []"
                    :key="`boundary-${item}`"
                  >
                    {{ item }}
                  </li>
                </ul>
              </div>
              <div>
                <h4>视角回答</h4>
                <pre class="result-pre">{{ toolResult.answer }}</pre>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'chapter-workflow' && toolResult">
            <div class="result-shell">
              <template v-if="activeToolMode === 'scenes'">
                <h4>{{ toolResult.headline }}</h4>
                <p>{{ toolResult.summary }}</p>
                <div class="scene-card-grid">
                  <article
                    v-for="(scene, index) in toolResult.scenes ?? []"
                    :key="`${scene.title}-${index}`"
                    class="scene-card"
                  >
                    <strong>{{ scene.title }}</strong>
                    <p>目标：{{ scene.goal }}</p>
                    <p>冲突：{{ scene.conflict }}</p>
                    <p>转折：{{ scene.turn }}</p>
                  </article>
                </div>
                <button
                  class="secondary-button"
                  type="button"
                  @click="saveScenesToBlueprint"
                >
                  写入章节蓝图
                </button>
              </template>

              <template v-else-if="activeToolMode === 'draft'">
                <h4>{{ toolResult.headline }}</h4>
                <p>{{ toolResult.summary }}</p>
                <ul
                  v-if="toolResult.checklist?.length"
                  class="plain-list"
                >
                  <li
                    v-for="item in toolResult.checklist"
                    :key="item"
                  >
                    {{ item }}
                  </li>
                </ul>
                <pre class="result-pre">{{ toolResult.draft }}</pre>
                <button
                  class="secondary-button"
                  type="button"
                  @click="saveGeneratedChapter(toolResult.draft)"
                >
                  保存到当前章节
                </button>
              </template>

              <template v-else>
                <h4>{{ toolResult.headline }}</h4>
                <p>{{ toolResult.summary }}</p>
                <ul
                  v-if="toolResult.checklist?.length"
                  class="plain-list"
                >
                  <li
                    v-for="item in toolResult.checklist"
                    :key="item"
                  >
                    {{ item }}
                  </li>
                </ul>
                <p v-if="toolResult.next_action">
                  下一步：{{ toolResult.next_action }}
                </p>
              </template>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'consistency' && toolResult">
            <div class="result-shell">
              <h4>{{ toolResult.summary }}</h4>
              <div class="issue-list">
                <article
                  v-for="(item, index) in toolResult.issues ?? []"
                  :key="`${item.title}-${index}`"
                  class="issue-card"
                >
                  <span class="issue-level">{{ item.level }}</span>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.detail }}</p>
                </article>
              </div>
              <ul
                v-if="toolResult.suggestions?.length"
                class="plain-list"
              >
                <li
                  v-for="item in toolResult.suggestions"
                  :key="item"
                >
                  {{ item }}
                </li>
              </ul>
              <button
                class="secondary-button"
                type="button"
                @click="saveNoteToProjectMemory(
                  props.selectedChapter ? `第 ${props.selectedChapter.index} 章一致性检查` : '一致性检查',
                  [toolResult.summary, ...(toolResult.suggestions ?? [])].filter(Boolean).join('\n'),
                  '连续性'
                )"
              >
                记到项目记忆
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'blueprint' && toolResult">
            <div class="result-shell">
              <h4>{{ toolResult.headline }}</h4>
              <p>{{ toolResult.summary }}</p>
              <pre class="result-pre">{{ toolResult.blueprint }}</pre>
              <div
                v-if="toolResult.chapters?.length"
                class="issue-list"
              >
                <article
                  v-for="item in toolResult.chapters"
                  :key="item.chapter_id"
                  class="issue-card"
                >
                  <strong>{{ item.chapter_id }} · {{ item.title }}</strong>
                  <p>目标：{{ item.goal }}</p>
                  <p>钩子：{{ item.hook }}</p>
                </article>
              </div>
              <button
                class="secondary-button"
                type="button"
                @click="saveBlueprintResult"
              >
                写回章节蓝图
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'chapter-generate' && toolResult">
            <div class="result-shell">
              <h4>{{ toolResult.headline }}</h4>
              <p>{{ toolResult.summary }}</p>
              <pre class="result-pre">{{ toolResult.content }}</pre>
              <button
                class="secondary-button"
                type="button"
                @click="saveGeneratedChapter(toolResult.content)"
              >
                保存到当前章节
              </button>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'chapter-rewrite' && toolResult">
            <div class="result-shell">
              <h4>{{ toolResult.headline }}</h4>
              <p>{{ toolResult.summary }}</p>
              <div
                v-if="toolResult.quality_report"
                class="issue-list"
              >
                <article class="issue-card">
                  <strong>本地回归评分</strong>
                  <p>
                    {{ toolResult.quality_report.before_score }}
                    →
                    {{ toolResult.quality_report.after_score }}
                    <span v-if="toolResult.quality_report.delta">
                      （{{ toolResult.quality_report.delta > 0 ? `+${toolResult.quality_report.delta}` : toolResult.quality_report.delta }}）
                    </span>
                  </p>
                  <p>{{ toolResult.quality_report.summary }}</p>
                </article>
                <article
                  v-if="toolResult.quality_report.remaining_issues?.length"
                  class="issue-card"
                >
                  <strong>残留问题</strong>
                  <ul class="plain-list">
                    <li
                      v-for="item in toolResult.quality_report.remaining_issues"
                      :key="item.code"
                    >
                      {{ item.label }} · {{ item.count }} 处
                    </li>
                  </ul>
                </article>
              </div>
              <ul
                v-if="toolResult.changes?.length"
                class="plain-list"
              >
                <li
                  v-for="item in toolResult.changes"
                  :key="item"
                >
                  {{ item }}
                </li>
              </ul>
              <pre class="result-pre">{{ toolResult.revised }}</pre>
              <div class="action-row">
                <button
                  class="secondary-button"
                  type="button"
                  @click="saveGeneratedChapter(toolResult.revised)"
                >
                  保存修订稿
                </button>
                <button
                  v-if="toolResult.updated_summary"
                  class="secondary-button"
                  type="button"
                  @click="saveRewriteDocument('global_summary', toolResult.updated_summary)"
                >
                  更新滚动摘要
                </button>
                <button
                  v-if="toolResult.updated_character_state"
                  class="secondary-button"
                  type="button"
                  @click="saveRewriteDocument('character_state', toolResult.updated_character_state)"
                >
                  更新人物状态
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'batch-generate' && toolResult">
            <div class="result-shell">
              <h4>批量生成完成</h4>
              <div class="issue-list">
                <article
                  v-for="item in toolResult.generated ?? []"
                  :key="item.chapter_id"
                  class="issue-card"
                >
                  <strong>{{ item.chapter_id }}</strong>
                  <p>{{ item.status }}</p>
                  <p>{{ item.preview }}</p>
                </article>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'continue-project' && toolResult">
            <div class="result-shell">
              <h4>{{ toolResult.headline }}</h4>
              <p>{{ toolResult.summary }}</p>
              <ul class="plain-list">
                <li>目标章节数：{{ toolResult.target_chapters }}</li>
                <li>情节骨架已更新</li>
                <li>人物状态已更新</li>
                <li>章节蓝图已更新</li>
              </ul>
              <pre class="result-pre">{{ toolResult.blueprint }}</pre>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'architecture-stepper'">
            <div class="result-shell">
              <div
                v-if="toolResult"
                class="subpanel"
              >
                <div class="subpanel-head">
                  <h4>{{ toolResult.headline }}</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="handleApplyArchitectureWorkspace"
                  >
                    写回项目
                  </button>
                </div>
                <p>{{ toolResult.summary }}</p>
                <ul class="plain-list">
                  <li
                    v-for="(item, index) in toolResult.checklist ?? []"
                    :key="`${item}-${index}`"
                  >
                    {{ item }}
                  </li>
                </ul>
                <pre class="result-pre">{{ toolResult.content }}</pre>
              </div>

              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>架构工作区</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="handleApplyArchitectureWorkspace"
                  >
                    一次性写回
                  </button>
                </div>
                <div class="two-column-grid">
                  <label
                    v-for="(label, key) in architectureDocumentLabels"
                    :key="key"
                    class="form-field"
                  >
                    <span>{{ label }}</span>
                    <textarea
                      v-model="architectureWorkspace[key]"
                      rows="5"
                    />
                  </label>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'style-dna'">
            <div class="result-shell">
              <div
                v-if="toolResult"
                class="subpanel"
              >
                <div class="subpanel-head">
                  <h4>本次分析结果</h4>
                  <button
                    class="secondary-button small-button"
                    type="button"
                    @click="saveStreamStyleResult"
                  >
                    保存方案
                  </button>
                </div>
                <label class="form-field">
                  <span>文风指令</span>
                  <textarea
                    :value="toolResult.instruction ?? ''"
                    rows="4"
                    readonly
                  />
                </label>
                <label class="form-field">
                  <span>风格分析</span>
                  <textarea
                    :value="toolResult.analysis ?? ''"
                    rows="6"
                    readonly
                  />
                </label>
                <label class="form-field">
                  <span>DNA 分析</span>
                  <textarea
                    :value="toolResult.dna_analysis ?? ''"
                    rows="6"
                    readonly
                  />
                </label>
                <div class="two-column-grid">
                  <label class="form-field">
                    <span>架构阶段要求</span>
                    <textarea
                      :value="toolResult.narrative_for_architecture ?? ''"
                      rows="4"
                      readonly
                    />
                  </label>
                  <label class="form-field">
                    <span>蓝图阶段要求</span>
                    <textarea
                      :value="toolResult.narrative_for_blueprint ?? ''"
                      rows="4"
                      readonly
                    />
                  </label>
                </div>
                <label class="form-field">
                  <span>正文阶段要求</span>
                  <textarea
                    :value="toolResult.narrative_for_chapter ?? ''"
                    rows="4"
                    readonly
                  />
                </label>
                <label class="form-field">
                  <span>校准备忘</span>
                  <textarea
                    :value="toolResult.calibration_notes ?? ''"
                    rows="4"
                    readonly
                  />
                </label>
              </div>

              <div
                v-if="styleState.detail"
                class="subpanel"
              >
                <div class="subpanel-head">
                  <h4>{{ styleState.detail.name }}</h4>
                  <div class="action-row">
                    <button
                      class="secondary-button small-button"
                      type="button"
                      @click="handleSaveStyleDetail"
                    >
                      保存详情
                    </button>
                    <button
                      class="secondary-button small-button"
                      type="button"
                      @click="handleDeleteStyle"
                    >
                      删除文风
                    </button>
                  </div>
                </div>
                <label class="form-field">
                  <span>文风指令</span>
                  <textarea
                    v-model="styleState.detail.instruction"
                    rows="4"
                  />
                </label>
                <label class="form-field">
                  <span>风格分析</span>
                  <textarea
                    v-model="styleState.detail.analysis"
                    rows="5"
                  />
                </label>
                <label class="form-field">
                  <span>DNA 分析</span>
                  <textarea
                    v-model="styleState.detail.dna_analysis"
                    rows="6"
                  />
                </label>
                <label class="form-field">
                  <span>参考库蒸馏</span>
                  <textarea
                    :value="styleState.detail.reference_distillate ?? ''"
                    rows="5"
                    readonly
                  />
                </label>
                <div class="two-column-grid">
                  <label class="form-field">
                    <span>架构阶段要求</span>
                    <textarea
                      v-model="styleState.detail.narrative_for_architecture"
                      rows="4"
                    />
                  </label>
                  <label class="form-field">
                    <span>蓝图阶段要求</span>
                    <textarea
                      v-model="styleState.detail.narrative_for_blueprint"
                      rows="4"
                    />
                  </label>
                </div>
                <label class="form-field">
                  <span>章节叙事要求</span>
                  <textarea
                    v-model="styleState.detail.narrative_for_chapter"
                    rows="4"
                  />
                </label>
                <label class="form-field">
                  <span>校准备忘</span>
                  <textarea
                    v-model="styleState.detail.calibration_notes"
                    rows="4"
                  />
                </label>
                <div class="detail-pills">
                  <span class="overview-pill">{{ styleState.detail.last_calibrated_at ? `上次校准 ${styleState.detail.last_calibrated_at}` : '还没做过校准' }}</span>
                  <span class="overview-pill">{{ styleState.detail.has_calibration_snapshot ? '支持回滚' : '当前没有回滚快照' }}</span>
                  <span
                    v-if="styleState.detail.snapshot_timestamp"
                    class="overview-pill"
                  >
                    快照时间 {{ styleState.detail.snapshot_timestamp }}
                  </span>
                </div>
                <label class="form-field">
                  <span>样文</span>
                  <textarea
                    v-model="styleState.detail.source_sample"
                    rows="6"
                  />
                </label>
                <label class="form-field">
                  <span>校准参考</span>
                  <textarea
                    v-model="styleState.detail.calibration_reference"
                    rows="5"
                  />
                </label>
                <div class="subpanel">
                  <div class="subpanel-head">
                    <h4>作者参考库</h4>
                    <div class="action-row">
                      <button
                        class="secondary-button small-button"
                        type="button"
                        @click="handleSearchStyleReferences"
                      >
                        搜索参考
                      </button>
                      <button
                        class="secondary-button small-button"
                        type="button"
                        @click="handleClearStyleReferences"
                      >
                        清空参考
                      </button>
                    </div>
                  </div>
                  <label class="form-field">
                    <span>参考检索词</span>
                    <input
                      v-model="styleState.referenceQuery"
                      placeholder="比如：灯塔白光、审讯感、近距离限知视角"
                    >
                  </label>
                  <label class="form-field">
                    <span>资料标题</span>
                    <input v-model="styleState.referenceTitle">
                  </label>
                  <label class="form-field">
                    <span>资料内容</span>
                    <textarea
                      v-model="styleState.referenceContent"
                      rows="4"
                    />
                  </label>
                  <label class="form-field">
                    <span>从本地文件导入参考资料</span>
                    <input
                      :accept="importAcceptValue()"
                      multiple
                      type="file"
                      @change="handleStyleReferenceFilesSelected"
                    >
                  </label>
                  <button
                    class="secondary-button"
                    type="button"
                    @click="handleImportStyleReference"
                  >
                    导入参考资料
                  </button>
                  <div
                    v-if="styleState.referenceHits.length"
                    class="list-column"
                  >
                    <article
                      v-for="item in styleState.referenceHits"
                      :key="`${item.section}-${item.preview}`"
                      class="message-card"
                    >
                      <div class="message-role">{{ item.match_type }}</div>
                      <strong>{{ item.section }}</strong>
                      <p>{{ item.preview }}</p>
                    </article>
                  </div>
                  <ul class="plain-list">
                    <li
                      v-for="item in styleState.detail.reference_materials ?? []"
                      :key="item.filename"
                    >
                      {{ item.title }}：{{ item.preview }}
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'prompt-presets'">
            <div class="result-shell">
              <label class="form-field">
                <span>方案名称</span>
                <input
                  v-model="promptPresetDraft.name"
                  data-testid="prompt-preset-name-input"
                >
              </label>
              <label class="form-field">
                <span>说明</span>
                <input
                  v-model="promptPresetDraft.description"
                  data-testid="prompt-preset-description-input"
                >
              </label>
              <div class="action-row">
                <button
                  class="secondary-button"
                  data-testid="prompt-preset-create-button"
                  type="button"
                  @click="handleCreatePromptPreset"
                >
                  新建方案
                </button>
              </div>
              <div class="two-column-grid">
                <label class="form-field">
                  <span>整本架构</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.architecture"
                    rows="3"
                  />
                </label>
                <label class="form-field">
                  <span>创意讨论</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.brainstorm"
                    rows="3"
                  />
                </label>
                <label class="form-field">
                  <span>蓝图生成</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.blueprint"
                    rows="3"
                  />
                </label>
                <label class="form-field">
                  <span>章节生成</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.chapter"
                    rows="3"
                  />
                </label>
                <label class="form-field">
                  <span>定稿</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.finalize"
                    rows="3"
                  />
                </label>
                <label class="form-field">
                  <span>润色</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.polish"
                    rows="3"
                  />
                </label>
                <label class="form-field">
                  <span>去 AI</span>
                  <textarea
                    v-model="promptPresetDraft.prompts.humanize"
                    rows="3"
                  />
                </label>
              </div>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'xp-presets'">
            <div class="result-shell">
              <label class="form-field">
                <span>XP 名称</span>
                <input
                  v-model="xpPresetState.draftName"
                  data-testid="xp-preset-name-input"
                >
              </label>
              <label class="form-field">
                <span>XP 内容</span>
                <textarea
                  v-model="xpPresetState.draftContent"
                  data-testid="xp-preset-content-input"
                  rows="6"
                />
              </label>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'knowledge-search'">
            <div
              class="result-shell"
              data-testid="knowledge-search-results"
            >
              <div
                v-if="knowledgeHits.length"
                class="issue-list"
              >
                <article
                  v-for="(item, index) in knowledgeHits"
                  :key="`${item.section}-${index}`"
                  class="issue-card"
                >
                  <strong>{{ item.section }}</strong>
                  <p>{{ item.source }} · {{ item.match_type === 'hybrid' ? '混合命中' : item.match_type === 'semantic' ? '语义命中' : '关键词命中' }}</p>
                  <p>{{ item.preview }}</p>
                </article>
              </div>
              <p
                v-else
                class="empty-result-copy"
              >
                输入关键词后点击“搜索知识”，结果会显示在这里。没有结果时，可以先导入资料，或换一个更具体的关键词。
              </p>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'web-research'">
            <div class="result-shell">
              <template v-if="webResearchResult">
                <div class="subpanel-head">
                  <div>
                    <h4>{{ webResearchResult.query }}</h4>
                    <p>{{ webResearchProviderLabel(webResearchResult.provider) }}</p>
                  </div>
                  <button
                    :disabled="!canImportWebResearchResult"
                    class="secondary-button small-button"
                    data-testid="web-research-result-import-button"
                    type="button"
                    @click="importWebResearchResult"
                  >
                    存入资料库
                  </button>
                </div>
                <p
                  v-if="webResearchResult.warning"
                  class="notice-banner notice-banner-error"
                >
                  {{ webResearchResult.warning }}
                </p>
                <pre
                  class="result-pre"
                  data-testid="web-research-result"
                >{{ webResearchResult.answer }}</pre>
                <section
                  v-if="webResearchResult.sources?.length"
                  class="result-section"
                >
                  <h4>联网来源</h4>
                  <div class="issue-list">
                    <article
                      v-for="(item, index) in webResearchResult.sources"
                      :key="`${item.url}-${index}`"
                      class="issue-card"
                    >
                      <strong>{{ item.title || item.site || '来源' }}</strong>
                      <p v-if="item.site || item.published_at">
                        {{ [item.site, item.published_at].filter(Boolean).join(' · ') }}
                      </p>
                      <p v-if="item.snippet">{{ item.snippet }}</p>
                      <a
                        v-if="item.url"
                        :href="item.url"
                        rel="noreferrer"
                        target="_blank"
                      >
                        打开来源
                      </a>
                    </article>
                  </div>
                </section>
                <section
                  v-if="webResearchResult.local_hits?.length"
                  class="result-section"
                >
                  <h4>项目资料命中</h4>
                  <div class="issue-list">
                    <article
                      v-for="(item, index) in webResearchResult.local_hits"
                      :key="`${item.section}-${index}`"
                      class="issue-card"
                    >
                      <strong>{{ item.section }}</strong>
                      <p>{{ item.source }}</p>
                      <p>{{ item.preview }}</p>
                    </article>
                  </div>
                </section>
              </template>
              <p
                v-else
                class="empty-result-copy"
              >
                输入历史典故、史实或写作问题后开始考据。结果可以保存进资料库，后续写章节时会参与项目检索。
              </p>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'reader'">
            <div class="result-shell">
              <h4>{{ currentReaderChapter?.title ?? '当前章节' }}</h4>
              <pre class="result-pre reader-pre">{{ currentReaderChapter?.content || '这一章还没有正文。' }}</pre>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'file-browser'">
            <div class="result-shell">
              <h4>{{ filesState.selectedPath || '项目文件' }}</h4>
              <textarea
                v-model="filesState.content"
                class="reader-editor"
                data-testid="file-browser-editor"
                rows="24"
                placeholder="当前没有可显示的文件。"
              />
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'logs'">
            <div class="result-shell">
              <pre class="result-pre reader-pre">{{ logsState.content || '当前没有日志内容。' }}</pre>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'prompt-history'">
            <div class="result-shell">
              <p>共 {{ promptHistoryState.total }} 条记录</p>
              <div class="issue-list">
                <article
                  v-for="item in promptHistoryState.records"
                  :key="`${item.timestamp}-${item.task}`"
                  class="issue-card"
                >
                  <strong>{{ item.task || '未命名任务' }}</strong>
                  <p>{{ item.model }}</p>
                  <p>{{ item.timestamp }}</p>
                  <p>{{ item.status }}</p>
                  <pre class="mini-pre">{{ item.prompt }}</pre>
                </article>
              </div>
            </div>
          </template>
          <template v-else-if="activeToolPanelKey === 'self-evolution'">
            <div class="result-shell">
              <template v-if="selfEvolutionState.report">
                <div class="detail-pills">
                  <span class="overview-pill">候选 {{ selfEvolutionState.report.candidates?.length ?? 0 }}</span>
                  <span class="overview-pill">学习记录 {{ selfEvolutionState.report.learning_review_count ?? 0 }}</span>
                  <span class="overview-pill">轨迹 {{ selfEvolutionState.report.trajectory_count ?? 0 }}</span>
                  <span class="overview-pill">Prompt 失败 {{ selfEvolutionState.report.prompt_failure_count ?? 0 }}</span>
                </div>

                <section>
                  <div class="subpanel-head">
                    <h4>候选建议</h4>
                  </div>
                  <div
                    v-if="selfEvolutionState.report.candidates?.length"
                    class="issue-list"
                  >
                    <article
                      v-for="item in selfEvolutionState.report.candidates"
                      :key="item.id"
                      class="issue-card"
                    >
                      <strong>{{ item.title }}</strong>
                      <p>{{ selfEvolutionKindLabel(item.kind) }} · 置信度 {{ Math.round((item.confidence ?? 0) * 100) }}%</p>
                      <p>{{ item.summary }}</p>
                      <ul
                        v-if="item.evidence?.length"
                        class="plain-list"
                      >
                        <li
                          v-for="evidence in item.evidence"
                          :key="`${item.id}-${evidence}`"
                        >
                          {{ evidence }}
                        </li>
                      </ul>
                      <p v-if="item.recommendation">
                        建议：{{ item.recommendation }}
                      </p>
                    </article>
                  </div>
                  <p
                    v-else
                    class="empty-result-copy"
                  >
                    当前没有新的经验候选或失败样本。
                  </p>
                </section>

                <section>
                  <div class="subpanel-head">
                    <h4>技能维护</h4>
                    <span>{{ selfEvolutionState.report.skill_curation?.total ?? 0 }} 个技能</span>
                  </div>
                  <div class="issue-list">
                    <article
                      v-for="item in (selfEvolutionState.report.skill_curation?.items ?? []).slice(0, 12)"
                      :key="item.skill_id"
                      class="issue-card"
                    >
                      <strong>{{ item.name }}</strong>
                      <p>{{ curationStatusLabel(item.status) }} · 使用 {{ item.usage_count ?? 0 }} 次 · 沉淀 {{ item.materialized_count ?? 0 }} 次</p>
                      <p>{{ item.reason }}</p>
                      <p>{{ item.suggestion }}</p>
                    </article>
                  </div>
                </section>
              </template>
              <p
                v-else
                class="empty-result-copy"
              >
                打开报告后，会显示经验候选、失败样本和技能维护建议。
              </p>
            </div>
          </template>
          <template v-else-if="activeToolPanelKey === 'conversation-skill'">
            <div class="result-shell">
              <h4>{{ activeToolLabel }}</h4>
              <p>{{ activeToolDescription }}</p>
              <div
                v-if="activeToolUsage.length"
                class="issue-list"
              >
                <article class="issue-card">
                  <strong>适用场景</strong>
                  <ul class="plain-list">
                    <li
                      v-for="item in activeToolUsage"
                      :key="`usage-${item}`"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </article>
              </div>
              <div
                v-if="activeToolLimitations.length"
                class="issue-list"
              >
                <article class="issue-card">
                  <strong>还可加强</strong>
                  <ul class="plain-list">
                    <li
                      v-for="item in activeToolLimitations"
                      :key="`limitation-${item}`"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </article>
              </div>
              <label
                v-if="activeToolInstructionPreview"
                class="form-field"
              >
                <span>技能预览</span>
                <textarea
                  :value="activeToolInstructionPreview"
                  rows="8"
                  readonly
                />
              </label>
              <p>回到主对话，在左下角技能选择器里选中它，就会按这套规则执行。</p>
            </div>
          </template>
          <template v-else>
            <div class="result-shell">
              <h4>{{ activeToolLabel }}</h4>
              <p>当前版本已经能从后端技能目录读取这项技能，但还没有它的专用交互。</p>
            </div>
          </template>
        </section>
      </div>
    </section>
  </section>
</template>

<style scoped>
.skills-page {
  width: min(1160px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 10px;
  align-content: start;
}

.skills-topbar,
.overview-copy,
.section-header,
.workbench-head,
.subpanel-head,
.progress-head,
.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.utility-button,
.secondary-button,
.primary-button,
.skill-use,
.filter-pill,
.list-item-button {
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.skills-actions,
.overview-pills,
.filter-row,
.scene-row,
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.utility-button,
.secondary-button,
.skill-use {
  border: 1px solid #d0d7de;
  border-radius: 999px;
  padding: 9px 14px;
  background: #ffffff;
  color: #24292f;
  font-size: 13px;
  cursor: pointer;
}

.utility-button:hover,
.secondary-button:hover,
.skill-use:hover,
.filter-pill:hover,
.list-item-button:hover {
  background: #f6f8fa;
}

.utility-button-primary {
  border-color: #cfe0fa;
  background: #e8f0fe;
  color: #1d4ed8;
}

.utility-button-primary:hover {
  background: #dbe8ff;
}

.primary-button {
  border: 0;
  border-radius: 999px;
  padding: 11px 15px;
  background: #1d4ed8;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.primary-button:disabled,
.secondary-button:disabled,
.utility-button:disabled,
.skill-use:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.small-button {
  padding: 7px 11px;
}

.overview-copy,
.controls-shell,
.catalog-section,
.workbench-shell {
  scroll-margin-top: 16px;
  border: 1px solid #dfe6ec;
  border-radius: 16px;
  padding: 16px;
  background: #ffffff;
  box-shadow: none;
}

.overview-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.skills-kicker,
.workbench-kicker {
  margin: 0;
  color: #1f2328;
  font-size: 17px;
  font-weight: 700;
}

.skills-summary,
.workbench-copy,
.section-header p,
.section-header span,
.notice-banner,
.error-banner,
  .workbench-empty,
  .empty-result-copy,
  .message-role,
  .issue-level {
  color: #57606a;
  font-size: 13px;
  line-height: 1.6;
}

.overview-pill,
.skill-tag,
.scene-pill,
.filter-pill,
.check-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 7px 11px;
  background: #f6f8fa;
  border: 1px solid #e2e8ee;
  font-size: 12px;
  color: #57606a;
}

.search-bar,
.form-field,
.field-stack {
  display: grid;
  gap: 8px;
}

.search-bar {
  grid-template-columns: auto 1fr;
  align-items: center;
  border: 1px solid #d0d7de;
  border-radius: 14px;
  padding: 10px 12px;
  background: #ffffff;
}

.search-icon {
  color: #6e7781;
  font-size: 13px;
}

.filter-pill {
  border: 1px solid #d0d7de;
  background: #ffffff;
  cursor: pointer;
}

.filter-pill-active {
  background: #e8f0fe;
  border-color: #cfe0fa;
  color: #1d4ed8;
}

.skills-grid,
.workbench-grid,
.scene-card-grid,
.issue-list,
.two-column-grid {
  display: grid;
  gap: 12px;
}

.skills-grid {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.skill-card,
.workbench-panel,
.subpanel,
.progress-card,
.message-card,
.scene-card,
.issue-card {
  border: 1px solid #dfe6ec;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: none;
}

.skill-card,
.workbench-panel,
.subpanel,
.progress-card,
.message-card,
.scene-card,
.issue-card {
  padding: 16px;
}

.skill-card {
  display: grid;
  gap: 12px;
  align-content: start;
}

.skill-badge {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 700;
}

.skill-badge-sand {
  background: #e8f0fe;
  color: #1d4ed8;
}

.skill-badge-slate {
  background: #eef2f7;
  color: #475467;
}

.skill-badge-olive {
  background: #e7f7ef;
  color: #067647;
}

.skill-badge-smoke {
  background: #eef0f2;
  color: #616b74;
}

.skill-meta {
  display: grid;
  gap: 8px;
}

.skill-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.skill-title-row strong,
.section-header h3,
.workbench-head h3,
.subpanel-head h4,
.result-shell h4 {
  margin: 0;
  color: #1f2328;
}

.skill-meta p,
.result-shell p,
.message-card p,
.scene-card p,
.issue-card p {
  margin: 0;
  color: #4f5b66;
  font-size: 14px;
  line-height: 1.65;
}

.skills-empty,
.workbench-empty,
.empty-result-copy {
  padding: 20px;
  text-align: center;
}

.workbench-grid {
  grid-template-columns: minmax(0, 420px) minmax(0, 1fr);
  align-items: start;
}

.workbench-panel,
.result-shell,
.field-stack,
.subpanel,
.message-list-shell,
.list-column {
  display: grid;
  gap: 12px;
}

.two-column-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.compact-field {
  max-width: 220px;
}

.form-field span {
  color: #57606a;
  font-size: 13px;
}

input,
textarea,
select {
  width: 100%;
  border: 1px solid #d0d7de;
  background: #ffffff;
  border-radius: 12px;
  padding: 11px 13px;
  color: #1f2328;
  font-size: 13px;
  line-height: 1.6;
}

textarea {
  resize: vertical;
}

.check-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.checkbox-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #4f5b66;
  font-size: 13px;
}

.checkbox-field input {
  width: auto;
  margin: 0;
}

.form-checkbox-field {
  min-height: 38px;
  align-self: end;
}

.detail-pills,
.overview-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.check-pill input {
  margin: 0;
}

.list-item-button {
  display: grid;
  gap: 4px;
  text-align: left;
  border: 1px solid #d0d7de;
  border-radius: 14px;
  padding: 10px 12px;
  background: #ffffff;
  cursor: pointer;
}

.list-item-button-active {
  border-color: #cfe0fa;
  background: #e8f0fe;
}

.list-item-button strong {
  font-size: 14px;
  color: #1f2328;
}

.list-item-button span {
  font-size: 11px;
  color: #6e7781;
}

.file-list {
  max-height: 520px;
  overflow: auto;
}

.progress-head span {
  color: #6e7781;
  font-size: 11px;
}

.progress-bar {
  height: 8px;
  border-radius: 999px;
  background: #eef2f5;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  border-radius: inherit;
  background: #1d4ed8;
}

.message-card-user {
  background: #f7f9fb;
}

.message-card-assistant {
  background: #ffffff;
}

.plain-list {
  margin: 0;
  padding-left: 18px;
  color: #4f5b66;
  font-size: 13px;
  line-height: 1.7;
}

.result-pre,
.mini-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f6f8fa;
  border-radius: 14px;
  padding: 12px;
  color: #1f2328;
  font-size: 12px;
  line-height: 1.7;
  font-family: 'SFMono-Regular', ui-monospace, monospace;
}

.mini-pre {
  max-height: 180px;
  overflow: auto;
}

.reader-pre {
  max-height: 620px;
  overflow: auto;
}

.reader-editor {
  min-height: 520px;
  font-family: 'SFMono-Regular', ui-monospace, monospace;
  line-height: 1.7;
}

.notice-banner,
.error-banner {
  border-radius: 16px;
  padding: 12px 14px;
  background: #f6f8fa;
  border: 1px solid #dfe6ec;
}

.notice-banner-error,
.error-banner {
  background: #fff7f7;
  border-color: #efc2c2;
  color: #a33a3a;
}

.notice-banner-success {
  background: #f4fbf5;
  border-color: #cfe4d2;
  color: #2b6940;
}

@media (max-width: 1240px) {
  .workbench-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 1160px) {
  .two-column-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-head,
  .subpanel-head,
  .progress-head {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 980px) {
  .workbench-grid,
  .two-column-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
