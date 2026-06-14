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
  applyProjectSelfEvolutionDraft,
  deleteCharacterReplicaProfile,
  deletePromptPreset,
  deleteStyle,
  deleteXpPreset,
  getCharacterReplicaProfile,
  getProjectObsidian,
  getProjectDetail,
  getProjectFileContent,
  getProjectSelfEvolution,
  getPromptHistory,
  getPromptPresetDetail,
  exportSkillPackage,
  getSkillVersions,
  getStudioLogs,
  getStyleDetail,
  importProjectKnowledge,
  importProjectKnowledgeFiles,
  importSkillPackage,
  importStyleReferenceFiles,
  importStyleReferences,
  listCharacterReplicaProfiles,
  listProjectFiles,
  listPromptPresets,
  listStyles,
  listStudioSkills,
  listXpPresets,
  previewChapterGeneratePrompt,
  previewChapterWorkflowPrompt,
  rollbackStyleCalibration,
  rollbackSkillVersion,
  saveStyle,
  searchStyleReferences,
  searchProjectKnowledge,
  confirmProjectObsidianMaintenanceMerge,
  confirmProjectObsidianMaintenanceMergeBatch,
  ignoreProjectObsidianMaintenance,
  ignoreProjectObsidianMaintenanceBatch,
  publishProjectObsidianMaintenance,
  publishProjectObsidianMaintenanceBatch,
  reopenProjectObsidianMaintenance,
  reopenProjectObsidianMaintenanceBatch,
  stageProjectObsidianMaintenance,
  stageProjectObsidianMaintenanceBatch,
  syncProjectObsidian,
  curateProjectSelfEvolution,
  runProjectSelfEvolutionModelReview,
  runProjectSelfEvolutionRegression,
  runProjectSelfEvolutionSchedule,
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
  updateProjectObsidian,
  updateProjectSelfEvolutionSchedule,
  updateProjectSelfEvolutionDraft,
  updateProjectSelfEvolutionCandidate,
  updatePromptPreset,
  saveCharacterReplicaProfile,
  updateStoryDocument,
  promoteSkillToGlobal,
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

const selfEvolutionSkill = Object.freeze({
  id: 'self-evolution',
  name: 'Agent 自学习',
  description: '查看 Agent 任务后的经验候选、调用规则、系统学习版文风 / XP、写作评价和技能统计。',
  category: '系统',
  scenes: ['复盘', '技能', '调用规则'],
  badge: '学',
  accent: 'olive',
  requires_project: true,
  requires_chapter: false,
  behavior: {
    panel: 'self-evolution',
  },
});

const selfEvolutionStatusOptions = ['全部', 'pending', 'accepted', 'rejected', 'archived'];
const selfEvolutionStatusLabels = {
  pending: '待确认',
  accepted: '已采纳',
  rejected: '已拒绝',
  archived: '已归档',
};
const obsidianMaintenanceStatusOptions = [
  '全部',
  '待处理',
  '自动草稿',
  '已保存草稿',
  '人工改动草稿',
  '保留人工草稿',
  '草稿缺失',
  'Vault 笔记缺失',
  'Vault 笔记已移动',
  'Vault 笔记待更新',
  '已发布',
  '已忽略',
];
const selfEvolutionKindLabels = {
  memory: '记忆',
  skill: '技能',
  capability: '调用能力',
};
const styleXpRuleKindLabels = {
  style: '文风',
  xp: 'XP',
};
const styleXpRuleStatusLabels = {
  observed: '观察中',
  active: '已生效',
};
const narrativeDebtKindLabels = {
  foreshadow: '伏笔',
  promise: '承诺',
  relationship: '关系',
  world_rule: '规则',
};
const narrativeDebtStatusLabels = {
  open: '待处理',
  touched: '已推进',
  paid: '已兑现',
  conflict: '有冲突',
  deferred: '延后',
};
const narrativeRiskLabels = {
  critical: '严重',
  high: '高',
  medium: '中',
  low: '低',
};
const selfEvolutionDraftKindLabels = {
  memory: '项目记忆',
  skill: '用户技能',
  capability: '调用规则',
};

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

const chapterPromptPreviewState = reactive({
  open: false,
  loading: false,
  error: '',
  message: '',
  title: '确认章节提示词',
  confirmLabel: '确认生成',
  kind: '',
  payload: null,
  items: [],
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

const obsidianForm = reactive({
  enabled: false,
  vaultPath: '',
  includePatterns: '**/*.md\n**/*.canvas',
  excludePatterns: '.obsidian/**\n.trash/**\ntemplates/**',
  allowedStatuses: 'canonical\n正式\n已确认\nactive\npublished\nusable',
  excludedStatuses: 'draft\n草稿\nprivate\n私密\ndeprecated\n废案\n弃用',
  includeWithoutStatus: true,
  requireUsableByAi: false,
  maxNotes: 2000,
});
const obsidianState = ref(null);
const isObsidianSaving = ref(false);
const isObsidianFormDirty = ref(false);
const obsidianStateRequestId = ref(0);

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

const selfEvolutionState = reactive({
  data: null,
  statusFilter: '全部',
  isLoading: false,
  isCurating: false,
  isRegressing: false,
  isReviewing: false,
  updatingCandidateId: '',
  updatingDraftId: '',
  obsidianMaintenanceStatusFilter: '全部',
  obsidianMaintenanceSourceChapter: '',
  obsidianMaintenanceSuggestionIds: [],
  obsidianMaintenanceQuery: '',
  stagingObsidianMaintenanceId: '',
  stagingAllObsidianMaintenance: false,
  publishingObsidianMaintenanceId: '',
  publishingAllObsidianMaintenance: false,
  confirmingObsidianMaintenanceMergeId: '',
  confirmingAllObsidianMaintenanceMerges: false,
  ignoringObsidianMaintenanceId: '',
  ignoringAllObsidianMaintenance: false,
  reopeningObsidianMaintenanceId: '',
  reopeningAllObsidianMaintenance: false,
});

const selfEvolutionScheduleForm = reactive({
  enabled: false,
  intervalHours: 168,
  tasks: {
    curate: true,
    regression: true,
    model_review: true,
  },
  isSaving: false,
  isRunning: false,
});

const skillVersionState = reactive({
  selectedSkillId: '',
  data: null,
  isLoading: false,
  actionId: '',
});

const skillPackageState = reactive({
  text: '',
  strategy: 'create_copy',
  isExporting: false,
  isImporting: false,
});

const selfEvolutionCandidates = computed(() => {
  const items = selfEvolutionState.data?.candidates?.items;
  return Array.isArray(items) ? items : [];
});

const filteredSelfEvolutionCandidates = computed(() => {
  if (selfEvolutionState.statusFilter === '全部') {
    return selfEvolutionCandidates.value;
  }
  return selfEvolutionCandidates.value.filter((item) => item.status === selfEvolutionState.statusFilter);
});

const selfEvolutionRules = computed(() => {
  const rules = selfEvolutionState.data?.capability_rules?.rules;
  return Array.isArray(rules) ? rules : [];
});

const selfEvolutionStyleXpState = computed(() => selfEvolutionState.data?.style_xp_evolution ?? {});
const selfEvolutionStyleXpRules = computed(() => {
  const rules = selfEvolutionStyleXpState.value?.rules;
  return Array.isArray(rules) ? rules : [];
});
const activeSelfEvolutionStyleXpRules = computed(() => (
  selfEvolutionStyleXpRules.value.filter((item) => item.status === 'active')
));

const selfEvolutionNarrativeState = computed(() => selfEvolutionState.data?.narrative_state ?? {});
const selfEvolutionNarrativeDebts = computed(() => {
  const debts = selfEvolutionNarrativeState.value?.debts;
  return Array.isArray(debts) ? debts : [];
});
const selfEvolutionObsidianMaintenance = computed(() => {
  const suggestions = selfEvolutionNarrativeState.value?.obsidian_maintenance_suggestions;
  return Array.isArray(suggestions) ? suggestions : [];
});
const filteredSelfEvolutionObsidianMaintenance = computed(() => {
  const statusFilter = selfEvolutionState.obsidianMaintenanceStatusFilter;
  const sourceChapter = Number(selfEvolutionState.obsidianMaintenanceSourceChapter || 0);
  const suggestionIds = new Set(
    Array.isArray(selfEvolutionState.obsidianMaintenanceSuggestionIds)
      ? selfEvolutionState.obsidianMaintenanceSuggestionIds.map((item) => String(item ?? '').trim()).filter(Boolean)
      : [],
  );
  const query = selfEvolutionState.obsidianMaintenanceQuery.trim().toLowerCase();
  return selfEvolutionObsidianMaintenance.value.filter((item) => {
    if (statusFilter !== '全部' && obsidianMaintenanceStatusLabel(item) !== statusFilter) {
      return false;
    }
    if (sourceChapter > 0 && !obsidianMaintenanceSourceChapters(item).includes(sourceChapter)) {
      return false;
    }
    if (suggestionIds.size > 0 && !suggestionIds.has(String(item.id ?? '').trim())) {
      return false;
    }
    if (!query) {
      return true;
    }
    const haystack = [
      item.title,
      item.reason,
      item.action,
      item.kind,
      item.priority,
      item.id,
      item.suggested_path,
      item.draft_path,
      item.vault_relative_path,
      Array.isArray(item.source_chapters) ? item.source_chapters.join(' ') : '',
    ].join(' ').toLowerCase();
    return haystack.includes(query);
  });
});
const filteredSelfEvolutionObsidianStageable = computed(() => (
  filteredSelfEvolutionObsidianMaintenance.value.filter((item) => canStageObsidianMaintenanceInBatch(item))
));
const filteredSelfEvolutionObsidianPublishable = computed(() => (
  filteredSelfEvolutionObsidianMaintenance.value.filter((item) => canPublishObsidianMaintenanceInBatch(item))
));
const filteredSelfEvolutionObsidianMergeConfirmable = computed(() => (
  filteredSelfEvolutionObsidianMaintenance.value.filter((item) => canConfirmObsidianMaintenanceMergeInBatch(item))
));
const filteredSelfEvolutionObsidianIgnorable = computed(() => (
  filteredSelfEvolutionObsidianMaintenance.value.filter((item) => canIgnoreObsidianMaintenanceInBatch(item))
));
const filteredSelfEvolutionObsidianReopenable = computed(() => (
  filteredSelfEvolutionObsidianMaintenance.value.filter((item) => canReopenObsidianMaintenanceInBatch(item))
));
const hasSelfEvolutionObsidianMaintenanceFilters = computed(() => {
  const statusFilter = selfEvolutionState.obsidianMaintenanceStatusFilter;
  const sourceChapter = Number(selfEvolutionState.obsidianMaintenanceSourceChapter || 0);
  const suggestionIds = Array.isArray(selfEvolutionState.obsidianMaintenanceSuggestionIds)
    ? selfEvolutionState.obsidianMaintenanceSuggestionIds.filter((item) => String(item ?? '').trim())
    : [];
  const query = selfEvolutionState.obsidianMaintenanceQuery.trim();
  return statusFilter !== '全部' || sourceChapter > 0 || suggestionIds.length > 0 || Boolean(query);
});
const obsidianMaintenanceArtifactFilterCount = computed(() => (
  Array.isArray(selfEvolutionState.obsidianMaintenanceSuggestionIds)
    ? selfEvolutionState.obsidianMaintenanceSuggestionIds.filter((item) => String(item ?? '').trim()).length
    : 0
));
const selfEvolutionObsidianMaintenanceSummary = computed(() => {
  if (!hasSelfEvolutionObsidianMaintenanceFilters.value) {
    const summary = selfEvolutionNarrativeState.value?.obsidian_maintenance_summary;
    if (summary && typeof summary === 'object') {
      return summary;
    }
  }
  return buildSelfEvolutionObsidianMaintenanceSummary(filteredSelfEvolutionObsidianMaintenance.value);
});

function obsidianMaintenanceStatusKey(item) {
  return item?.draft_missing
    ? 'draft_missing'
    : item?.published_missing
      ? 'published_missing'
      : item?.published_outdated
        ? 'published_outdated'
        : item?.status || 'open';
}

function buildSelfEvolutionObsidianMaintenanceSummary(items) {
  const byStatus = {
    open: 0,
    staged: 0,
    published: 0,
    draft_missing: 0,
    published_missing: 0,
    published_outdated: 0,
    vault_moved: 0,
    ignored: 0,
  };
  let highPriority = 0;
  let autoStaged = 0;
  items.forEach((item) => {
    const status = obsidianMaintenanceStatusKey(item);
    if (Object.prototype.hasOwnProperty.call(byStatus, status)) {
      byStatus[status] += 1;
    }
    if (item.vault_moved) {
      byStatus.vault_moved += 1;
    }
    if (item.priority === 'high') {
      highPriority += 1;
    }
    if (item.auto_staged) {
      autoStaged += 1;
    }
  });
  return {
    total: items.length,
    needs_action: byStatus.open + byStatus.staged + byStatus.draft_missing + byStatus.published_missing + byStatus.published_outdated,
    high_priority: highPriority,
    auto_staged: autoStaged,
    by_status: byStatus,
  };
}
const highRiskNarrativeDebts = computed(() => (
  selfEvolutionNarrativeDebts.value.filter((item) => ['critical', 'high'].includes(item.risk_level))
));
const selfEvolutionCharacterArcs = computed(() => {
  const arcs = selfEvolutionNarrativeState.value?.character_arcs;
  return Array.isArray(arcs) ? arcs : [];
});
const selfEvolutionChapterCards = computed(() => {
  const cards = selfEvolutionNarrativeState.value?.chapter_cards;
  return Array.isArray(cards) ? cards : [];
});
const latestChapterCard = computed(() => (
  selfEvolutionChapterCards.value[selfEvolutionChapterCards.value.length - 1] ?? null
));
const latestChapterCardObsidianSources = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_sources)
));
const latestChapterCardObsidianExternalReferences = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_external_references)
));
const latestChapterCardObsidianRequired = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_required)
));
const latestChapterCardObsidianForbidden = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_forbidden)
));
const latestChapterCardObsidianRisks = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_risks)
));
const latestChapterCardObsidianSatisfied = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_required_satisfied)
));
const latestChapterCardObsidianMissing = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_required_missing)
));
const latestChapterCardObsidianViolations = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_forbidden_violations)
));
const latestChapterCardObsidianNarrativeDebts = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_narrative_debts)
    .map(formatObsidianNarrativeDebt)
    .filter(Boolean)
));
const latestChapterCardObsidianCharacterArcs = computed(() => (
  previewListItems(latestChapterCard.value?.obsidian_character_arcs)
    .map(formatObsidianCharacterArc)
    .filter(Boolean)
));
const latestChapterCardHasObsidian = computed(() => (
  latestChapterCardObsidianSources.value.length > 0
    || latestChapterCardObsidianExternalReferences.value.length > 0
    || latestChapterCardObsidianRequired.value.length > 0
    || latestChapterCardObsidianForbidden.value.length > 0
    || latestChapterCardObsidianRisks.value.length > 0
    || latestChapterCardObsidianSatisfied.value.length > 0
    || latestChapterCardObsidianMissing.value.length > 0
    || latestChapterCardObsidianViolations.value.length > 0
    || latestChapterCardObsidianNarrativeDebts.value.length > 0
    || latestChapterCardObsidianCharacterArcs.value.length > 0
));
const selfEvolutionNarrativeModelReviews = computed(() => {
  const reviews = selfEvolutionNarrativeState.value?.model_reviews;
  return Array.isArray(reviews) ? reviews : [];
});
const selfEvolutionChapterContracts = computed(() => {
  const contracts = selfEvolutionNarrativeState.value?.chapter_contracts;
  return Array.isArray(contracts) ? contracts : [];
});
const selfEvolutionContractReviews = computed(() => {
  const reviews = selfEvolutionNarrativeState.value?.contract_reviews;
  return Array.isArray(reviews) ? reviews : [];
});
const latestNarrativeModelReview = computed(() => (
  selfEvolutionNarrativeModelReviews.value[selfEvolutionNarrativeModelReviews.value.length - 1] ?? null
));
const latestChapterContract = computed(() => (
  selfEvolutionChapterContracts.value[selfEvolutionChapterContracts.value.length - 1] ?? null
));
const latestContractReview = computed(() => (
  selfEvolutionContractReviews.value[selfEvolutionContractReviews.value.length - 1] ?? null
));

const selfEvolutionEvaluations = computed(() => {
  const evaluations = selfEvolutionState.data?.writing_evaluations;
  return Array.isArray(evaluations) ? evaluations : [];
});

const selfEvolutionSkillUsage = computed(() => {
  const records = selfEvolutionState.data?.skill_usage?.records;
  return Array.isArray(records) ? records : [];
});

const selfEvolutionDrafts = computed(() => {
  const items = selfEvolutionState.data?.drafts?.items;
  return Array.isArray(items) ? items : [];
});

const pendingSelfEvolutionDrafts = computed(() => (
  selfEvolutionDrafts.value.filter((item) => item.status === 'pending')
));

const selfEvolutionRegressionRuns = computed(() => {
  const runs = selfEvolutionState.data?.writing_regression_runs;
  return Array.isArray(runs) ? runs : [];
});

const selfEvolutionModelReviews = computed(() => {
  const reviews = selfEvolutionState.data?.model_reviews;
  return Array.isArray(reviews) ? reviews : [];
});

const selfEvolutionDashboard = computed(() => selfEvolutionState.data?.dashboard ?? {});
const selfEvolutionSchedule = computed(() => selfEvolutionState.data?.schedule ?? {});
const selfEvolutionHumanizePatrol = computed(() => selfEvolutionState.data?.humanize_review_patrol ?? {});
const selfEvolutionFailureCases = computed(() => {
  const cases = selfEvolutionState.data?.failure_cases;
  return Array.isArray(cases) ? cases : [];
});
const selfEvolutionQualityDimensions = computed(() => selfEvolutionDashboard.value.quality_dimensions ?? {});
const selfEvolutionWritingTrend = computed(() => selfEvolutionDashboard.value.trends?.writing_scores ?? []);
const selfEvolutionRegressionTrend = computed(() => selfEvolutionDashboard.value.trends?.regression_scores ?? []);
const selfEvolutionHumanizeAbTrend = computed(() => selfEvolutionDashboard.value.trends?.humanize_ab_scores ?? []);
const selfEvolutionHumanizeJudgeTrend = computed(() => selfEvolutionDashboard.value.trends?.humanize_judge_scores ?? []);
const selfEvolutionFailureGroups = computed(() => {
  const groups = selfEvolutionDashboard.value.failure_case_groups;
  return Array.isArray(groups) ? groups : [];
});

const selfEvolutionMetrics = computed(() => [
  { label: '候选', value: selfEvolutionCandidates.value.length },
  { label: '调用规则', value: selfEvolutionRules.value.length },
  { label: '文风 / XP', value: activeSelfEvolutionStyleXpRules.value.length },
  { label: '剧情债务', value: highRiskNarrativeDebts.value.length },
  { label: '章节合同', value: selfEvolutionChapterContracts.value.length },
  { label: '写作评价', value: selfEvolutionEvaluations.value.length },
  { label: '待确认草案', value: pendingSelfEvolutionDrafts.value.length },
]);

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
  brainstorm: {
    panel: 'brainstorm',
    agent_action_kind: 'brainstorm',
    agent_requires_confirmation: false,
  },
  blueprint: {
    panel: 'blueprint',
    agent_action_kind: 'generate_architecture',
    agent_requires_confirmation: true,
  },
  'continue-project': {
    panel: 'continue-project',
    agent_action_kind: 'continue_project',
    agent_requires_confirmation: true,
  },
  consistency: {
    panel: 'consistency',
    agent_action_kind: 'consistency_check',
    agent_requires_confirmation: false,
  },
  'knowledge-search': {
    panel: 'knowledge-search',
    agent_action_kind: 'review_knowledge',
    agent_requires_confirmation: false,
  },
  'chapter-scenes': {
    panel: 'chapter-workflow',
    mode: 'scenes',
    input_label: '拆场要求',
    submit_label: '开始拆场',
    agent_action_kind: 'chapter_workflow',
    agent_action_mode: 'scenes',
    agent_requires_confirmation: false,
  },
  'chapter-diagnose': {
    panel: 'chapter-workflow',
    mode: 'diagnose',
    input_label: '诊断要求',
    submit_label: '开始诊断',
    agent_action_kind: 'chapter_workflow',
    agent_action_mode: 'diagnose',
    agent_requires_confirmation: false,
  },
  'chapter-generate': {
    panel: 'chapter-generate',
    agent_action_kind: 'chapter_generate',
    agent_requires_confirmation: true,
  },
  'chapter-draft': {
    panel: 'chapter-workflow',
    mode: 'draft',
    input_label: '续写要求',
    submit_label: '开始续写',
    agent_action_kind: 'chapter_workflow',
    agent_action_mode: 'draft',
    agent_requires_confirmation: true,
  },
  'chapter-finalize': {
    panel: 'chapter-rewrite',
    mode: 'finalize',
    input_label: '改稿要求',
    submit_label: '开始定稿',
    agent_action_kind: 'rewrite_chapter',
    agent_action_mode: 'finalize',
    agent_requires_confirmation: true,
  },
  'chapter-polish': {
    panel: 'chapter-rewrite',
    mode: 'polish',
    input_label: '改稿要求',
    submit_label: '开始润色',
    agent_action_kind: 'rewrite_chapter',
    agent_action_mode: 'polish',
    agent_requires_confirmation: true,
  },
  'chapter-humanize': {
    panel: 'chapter-rewrite',
    mode: 'humanize',
    input_label: '改稿要求',
    submit_label: '开始去 AI',
    agent_action_kind: 'rewrite_chapter',
    agent_action_mode: 'humanize',
    agent_requires_confirmation: true,
  },
};

function addSelfEvolutionCatalogEntry(sections) {
  const normalizedSections = sections.map((section) => ({
    ...section,
    items: Array.isArray(section.items) ? section.items : [],
  }));
  if (normalizedSections.some((section) => section.items.some((item) => item.id === selfEvolutionSkill.id))) {
    return normalizedSections;
  }
  return [
    ...normalizedSections,
    {
      id: 'agent-system',
      title: 'Agent 能力',
      description: '查看 Agent 执行后的自学习记录、调用规则和技能维护状态。',
      order: 99,
      items: [selfEvolutionSkill],
    },
  ];
}

function addSelfEvolutionFilter(filters) {
  return filters.includes('系统') ? filters : [...filters, '系统'];
}

function normalizeSkillBehavior(skill) {
  if (!skill) {
    return {
      panel: '',
      mode: '',
      input_label: '',
      submit_label: '',
      agent_action_kind: '',
      agent_action_mode: '',
      agent_requires_confirmation: false,
    };
  }

  const fallback = defaultSkillBehaviorById[skill.id] ?? {};
  const behavior = skill.behavior ?? {};
  return {
    panel: behavior.panel || fallback.panel || skill.id,
    mode: behavior.mode || fallback.mode || '',
    input_label: behavior.input_label || fallback.input_label || '',
    submit_label: behavior.submit_label || fallback.submit_label || '',
    agent_action_kind: behavior.agent_action_kind || fallback.agent_action_kind || '',
    agent_action_mode: behavior.agent_action_mode || fallback.agent_action_mode || '',
    agent_requires_confirmation: Boolean(
      behavior.agent_requires_confirmation ?? fallback.agent_requires_confirmation ?? false,
    ),
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

function applySelfEvolutionLaunchFilters(request) {
  if (request?.skillId !== 'self-evolution') {
    return;
  }
  const statusFilter = String(request.obsidianMaintenanceStatusFilter ?? '').trim();
  if (obsidianMaintenanceStatusOptions.includes(statusFilter)) {
    selfEvolutionState.obsidianMaintenanceStatusFilter = statusFilter;
  }
  const sourceChapter = Number(request.obsidianMaintenanceSourceChapter ?? 0);
  selfEvolutionState.obsidianMaintenanceSourceChapter = sourceChapter > 0 ? String(sourceChapter) : '';
  selfEvolutionState.obsidianMaintenanceSuggestionIds = Array.isArray(request.obsidianMaintenanceSuggestionIds)
    ? request.obsidianMaintenanceSuggestionIds.map((item) => String(item ?? '').trim()).filter(Boolean)
    : [];
  selfEvolutionState.obsidianMaintenanceQuery = String(request.obsidianMaintenanceQuery ?? '').trim();
}

function clearObsidianMaintenanceArtifactFilter() {
  selfEvolutionState.obsidianMaintenanceSuggestionIds = [];
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
  applySelfEvolutionLaunchFilters(request);
  activateTool(tool);
  setToolMessage(
    request.source === 'obsidian-maintenance-artifact'
      ? '已打开 Obsidian 维护队列'
      : request.prompt?.trim() ? '已从主对话带入当前要求' : '已打开技能工作区',
  );
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
const activeObsidianState = computed(() => (
  obsidianState.value
  ?? props.project?.story_overview?.obsidian
  ?? null
));
const obsidianNotesPreview = computed(() => (
  (activeObsidianState.value?.notes ?? []).slice(0, 8)
));

function obsidianChapterScope(item) {
  const start = Number(item?.chapter_start ?? 0);
  const end = Number(item?.chapter_end ?? 0);
  const revealAfter = Number(item?.reveal_after_chapter ?? 0);
  const parts = [];
  if (start && end) {
    parts.push(start === end ? `适用章节：第 ${start} 章` : `适用章节：第 ${start}-${end} 章`);
  } else if (start) {
    parts.push(`适用章节：第 ${start} 章起`);
  } else if (end) {
    parts.push(`适用章节：第 ${end} 章前`);
  }
  if (revealAfter) {
    parts.push(`剧透边界：第 ${revealAfter} 章后可用`);
  }
  return parts.join('；');
}

function obsidianNoteSourceChapterText(item) {
  const values = Array.isArray(item?.source_chapters) ? item.source_chapters : [];
  const indexes = [];
  for (const value of values) {
    const chapterIndex = Number(value || 0);
    if (Number.isInteger(chapterIndex) && chapterIndex > 0 && !indexes.includes(chapterIndex)) {
      indexes.push(chapterIndex);
    }
  }
  if (!indexes.length) {
    return '';
  }
  return `来源章节：${indexes.map((index) => `第 ${index} 章`).join('、')}`;
}

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
    const resolvedFilters = addSelfEvolutionFilter(nextFilters);
    skillFilters.value = resolvedFilters;
    skillCatalogSections.value = addSelfEvolutionCatalogEntry(nextSections);
    if (!resolvedFilters.includes(activeFilter.value)) {
      activeFilter.value = '全部';
    }
  } catch {
    skillFilters.value = addSelfEvolutionFilter([...fallbackFilterOptions]);
    skillCatalogSections.value = addSelfEvolutionCatalogEntry([...fallbackSkillSections]);
  }
}

function selfEvolutionStatusLabel(status) {
  return selfEvolutionStatusLabels[status] ?? status ?? '未知';
}

function selfEvolutionKindLabel(kind) {
  return selfEvolutionKindLabels[kind] ?? kind ?? '候选';
}

function styleXpRuleKindLabel(kind) {
  return styleXpRuleKindLabels[kind] ?? kind ?? '规则';
}

function styleXpRuleStatusLabel(status) {
  return styleXpRuleStatusLabels[status] ?? status ?? '未知';
}

function narrativeDebtKindLabel(kind) {
  return narrativeDebtKindLabels[kind] ?? kind ?? '线索';
}

function narrativeDebtStatusLabel(status) {
  return narrativeDebtStatusLabels[status] ?? status ?? '未知';
}

function narrativeRiskLabel(risk) {
  return narrativeRiskLabels[risk] ?? risk ?? '未知';
}

function obsidianMaintenanceStatusLabel(item) {
  const status = item?.status ?? 'open';
  if (status === 'draft_missing' || item?.draft_missing) {
    return '草稿缺失';
  }
  if (status === 'published_missing' || item?.published_missing) {
    return 'Vault 笔记缺失';
  }
  if (status === 'published_outdated' || item?.published_outdated) {
    return 'Vault 笔记待更新';
  }
  if (item?.vault_moved) {
    return 'Vault 笔记已移动';
  }
  if (status === 'published') {
    return '已发布';
  }
  if (status === 'ignored') {
    return '已忽略';
  }
  if (status === 'staged' && item?.preserved_existing_draft) {
    return '保留人工草稿';
  }
  if (status === 'staged' && item?.manual_draft_edits) {
    return '人工改动草稿';
  }
  if (status === 'staged' && item?.auto_staged) {
    return '自动草稿';
  }
  if (status === 'staged') {
    return '已保存草稿';
  }
  if (status === 'open') {
    return '待处理';
  }
  return status || '待处理';
}

function obsidianMaintenanceSourceChapters(item) {
  const values = Array.isArray(item?.source_chapters) ? item.source_chapters : [];
  const indexes = [];
  for (const value of values) {
    const chapterIndex = Number(value || 0);
    if (Number.isInteger(chapterIndex) && chapterIndex > 0 && !indexes.includes(chapterIndex)) {
      indexes.push(chapterIndex);
    }
  }
  return indexes;
}

function obsidianMaintenanceSourceChapterText(item) {
  const indexes = obsidianMaintenanceSourceChapters(item);
  if (!indexes.length) {
    return '';
  }
  return `来源章节：${indexes.map((index) => `第 ${index} 章`).join('、')}`;
}

function canStageObsidianMaintenanceInBatch(item) {
  if (!item?.draft_markdown) {
    return false;
  }
  return !['已发布', '已忽略'].includes(obsidianMaintenanceStatusLabel(item));
}

function canPublishObsidianMaintenanceInBatch(item) {
  if (!item?.draft_path) {
    return false;
  }
  if (item?.merge_draft_path) {
    return false;
  }
  return [
    '自动草稿',
    '已保存草稿',
    '人工改动草稿',
    '保留人工草稿',
    'Vault 笔记缺失',
  ].includes(obsidianMaintenanceStatusLabel(item));
}

function canConfirmObsidianMaintenanceMergeInBatch(item) {
  return Boolean(item?.merge_draft_path);
}

function canIgnoreObsidianMaintenanceInBatch(item) {
  return !['已发布', '已忽略'].includes(obsidianMaintenanceStatusLabel(item));
}

function canReopenObsidianMaintenanceInBatch(item) {
  return obsidianMaintenanceStatusLabel(item) === '已忽略';
}

function selfEvolutionDraftKindLabel(kind) {
  return selfEvolutionDraftKindLabels[kind] ?? kind ?? '草案';
}

function qualityDimensionLabel(key) {
  const labels = {
    character_consistency: '人物一致性',
    conflict_progress: '冲突推进',
    information_release: '信息释放',
    dialogue_naturalness: '对白自然度',
    style_stability: '文风稳定性',
  };
  return labels[key] ?? key;
}

function previewListItems(value) {
  return Array.isArray(value) ? value.filter((item) => String(item ?? '').trim()) : [];
}

function formatObsidianNarrativeDebt(item) {
  if (!item || typeof item !== 'object') {
    return String(item ?? '').trim();
  }
  const title = String(item.title || '剧情债务').trim();
  const content = String(item.content || '').trim();
  const range = Array.isArray(item.expected_payoff_range) ? item.expected_payoff_range : [];
  const rangeText = range.length >= 2 ? `（预计第 ${range[0]}-${range[1]} 章处理）` : '';
  return `${title}${content ? `：${content}` : ''}${rangeText}`.trim();
}

function formatObsidianCharacterArc(item) {
  if (!item || typeof item !== 'object') {
    return String(item ?? '').trim();
  }
  const name = String(item.name || item.title || '人物弧线').trim();
  const state = String(item.current_state || '').trim();
  const check = String(item.required_next_check || '').trim();
  const detail = [state, check].filter(Boolean).join('；');
  return `${name}${detail ? `：${detail}` : ''}`.trim();
}

function percentLabel(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '0%';
  }
  return `${Math.round(Math.max(0, Math.min(numeric, 1)) * 100)}%`;
}

function humanizeSampleIssueText(sample) {
  const issues = Array.isArray(sample?.top_issues) ? sample.top_issues : [];
  const labels = issues
    .map((item) => String(item?.label || '').trim())
    .filter(Boolean)
    .slice(0, 2);
  return labels.length ? labels.join('、') : '未标注';
}

function humanizeJudgeIssueText(issue) {
  if (!issue || typeof issue !== 'object') {
    return String(issue ?? '').trim();
  }
  const title = String(issue.title || issue.label || '去 AI 问题').trim();
  const detail = String(issue.detail || issue.evidence || '').trim();
  return `${title}${detail ? `：${detail}` : ''}`.trim();
}

function syncSelfEvolutionScheduleForm(schedule) {
  selfEvolutionScheduleForm.enabled = Boolean(schedule?.enabled);
  selfEvolutionScheduleForm.intervalHours = Number(schedule?.interval_hours ?? 168) || 168;
  const tasks = Array.isArray(schedule?.tasks) ? schedule.tasks : ['curate', 'regression', 'model_review'];
  selfEvolutionScheduleForm.tasks.curate = tasks.includes('curate');
  selfEvolutionScheduleForm.tasks.regression = tasks.includes('regression');
  selfEvolutionScheduleForm.tasks.model_review = tasks.includes('model_review');
}

function applySelfEvolutionState(payload) {
  if (!payload || typeof payload !== 'object') {
    return false;
  }
  selfEvolutionState.data = payload;
  syncSelfEvolutionScheduleForm(payload?.schedule);
  return true;
}

async function refreshSelfEvolutionState({ silent = false, exposeError = true } = {}) {
  if (!props.project?.id) {
    selfEvolutionState.data = null;
    const message = '先在左侧打开一部作品';
    if (exposeError) {
      toolError.value = message;
    }
    return message;
  }

  selfEvolutionState.isLoading = true;
  try {
    applySelfEvolutionState(await getProjectSelfEvolution(props.project.id));
    if (!silent) {
      setToolMessage('自学习状态已刷新');
    }
    return '';
  } catch (error) {
    const message = error instanceof Error ? error.message : '读取自学习状态失败';
    if (exposeError) {
      toolError.value = message;
    }
    return message;
  } finally {
    selfEvolutionState.isLoading = false;
  }
}

async function refreshAfterObsidianMaintenance({
  obsidian = false,
  projectDetail = true,
  selfEvolution = null,
  selfEvolutionError = '',
} = {}) {
  const refreshErrors = [];
  if (selfEvolution) {
    applySelfEvolutionState(selfEvolution);
  } else {
    const stateError = await refreshSelfEvolutionState({ silent: true, exposeError: false });
    if (stateError) {
      refreshErrors.push(`自学习状态刷新失败：${stateError}`);
    }
  }
  if (selfEvolutionError) {
    refreshErrors.push(`自学习状态刷新失败：${selfEvolutionError}`);
  }
  if (obsidian) {
    await refreshObsidianState();
  }
  if (projectDetail) {
    try {
      await refreshProjectDetail();
    } catch (error) {
      refreshErrors.push(`作品详情刷新失败：${error instanceof Error ? error.message : '作品详情刷新失败'}`);
    }
  }
  return refreshErrors.join('；');
}

function obsidianMaintenanceRefreshPayload(response, options = {}) {
  return stateChangingActionRefreshPayload(response, options);
}

function stateChangingActionRefreshPayload(response, options = {}) {
  return {
    ...options,
    selfEvolution: response?.selfEvolution ?? null,
    selfEvolutionError: response?.selfEvolutionError ?? '',
  };
}

async function refreshAfterSelfEvolutionAction(response) {
  return refreshAfterObsidianMaintenance(stateChangingActionRefreshPayload(response, { projectDetail: false }));
}

function refreshFailureText(refreshError) {
  return refreshError ? `；${refreshError}` : '';
}

async function stageObsidianMaintenanceSuggestion(item) {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionId = String(item?.id ?? '').trim();
  if (!suggestionId) {
    toolError.value = '维护建议缺少 ID';
    return;
  }

  selfEvolutionState.stagingObsidianMaintenanceId = suggestionId;
  try {
    const response = await stageProjectObsidianMaintenance(props.project.id, suggestionId);
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response));
    const draftPath = result?.relative_path || '项目草稿目录';
    const refreshText = refreshFailureText(refreshError);
    if (result?.preserved_existing_draft) {
      setToolMessage(`Obsidian 已保留原有草稿：${draftPath}${refreshText}`);
    } else if (result?.merge_draft_relative_path) {
      setToolMessage(`Obsidian 草稿已保存：${draftPath}；Vault 合并草稿：${result.merge_draft_relative_path}${refreshText}`);
    } else {
      setToolMessage(`Obsidian 草稿已保存：${draftPath}${refreshText}`);
    }
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 草稿保存失败';
  } finally {
    selfEvolutionState.stagingObsidianMaintenanceId = '';
  }
}

async function stageVisibleObsidianMaintenanceSuggestions() {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionIds = filteredSelfEvolutionObsidianStageable.value
    .map((item) => String(item?.id ?? '').trim())
    .filter(Boolean);
  if (!suggestionIds.length) {
    toolError.value = '当前筛选结果没有可保存的 Obsidian 草稿';
    return;
  }

  selfEvolutionState.stagingAllObsidianMaintenance = true;
  try {
    const response = await stageProjectObsidianMaintenanceBatch(props.project.id, {
      suggestion_ids: suggestionIds,
      limit: suggestionIds.length,
    });
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response));
    const mergeCount = Number(result?.merge_draft_count ?? 0);
    const mergeText = mergeCount > 0 ? `，生成 Vault 合并草稿 ${mergeCount} 份` : '';
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 草稿已批量保存 ${result?.staged_count ?? 0} 条，跳过 ${result?.skipped_count ?? 0} 条${mergeText}${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 草稿批量保存失败';
  } finally {
    selfEvolutionState.stagingAllObsidianMaintenance = false;
  }
}

async function publishObsidianMaintenanceSuggestion(item) {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionId = String(item?.id ?? '').trim();
  if (!suggestionId) {
    toolError.value = '维护建议缺少 ID';
    return;
  }

  selfEvolutionState.publishingObsidianMaintenanceId = suggestionId;
  try {
    const response = await publishProjectObsidianMaintenance(props.project.id, suggestionId);
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response, { obsidian: true }));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 笔记已发布：${result?.vault_relative_path || result?.relative_path || 'Vault'}${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 笔记发布失败';
  } finally {
    selfEvolutionState.publishingObsidianMaintenanceId = '';
  }
}

async function confirmObsidianMaintenanceMerge(item) {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionId = String(item?.id ?? '').trim();
  if (!suggestionId) {
    toolError.value = '维护建议缺少 ID';
    return;
  }

  selfEvolutionState.confirmingObsidianMaintenanceMergeId = suggestionId;
  try {
    const response = await confirmProjectObsidianMaintenanceMerge(props.project.id, suggestionId);
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response, { obsidian: true }));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 合并状态已确认：${result?.vault_relative_path || 'Vault'}${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 合并确认失败';
  } finally {
    selfEvolutionState.confirmingObsidianMaintenanceMergeId = '';
  }
}

async function confirmVisibleObsidianMaintenanceMerges() {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionIds = filteredSelfEvolutionObsidianMergeConfirmable.value
    .map((item) => String(item?.id ?? '').trim())
    .filter(Boolean);
  if (!suggestionIds.length) {
    toolError.value = '当前筛选结果没有可确认的 Vault 合并项';
    return;
  }

  selfEvolutionState.confirmingAllObsidianMaintenanceMerges = true;
  try {
    const response = await confirmProjectObsidianMaintenanceMergeBatch(props.project.id, {
      suggestion_ids: suggestionIds,
      limit: suggestionIds.length,
    });
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response, { obsidian: true }));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 合并状态已批量确认 ${result?.confirmed_count ?? 0} 条，跳过 ${result?.skipped_count ?? 0} 条${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 合并批量确认失败';
  } finally {
    selfEvolutionState.confirmingAllObsidianMaintenanceMerges = false;
  }
}

async function publishVisibleObsidianMaintenanceSuggestions() {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionIds = filteredSelfEvolutionObsidianPublishable.value
    .map((item) => String(item?.id ?? '').trim())
    .filter(Boolean);
  if (!suggestionIds.length) {
    toolError.value = '当前筛选结果没有可发布的已保存 Obsidian 草稿';
    return;
  }

  selfEvolutionState.publishingAllObsidianMaintenance = true;
  try {
    const response = await publishProjectObsidianMaintenanceBatch(props.project.id, {
      suggestion_ids: suggestionIds,
      limit: suggestionIds.length,
    });
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response, { obsidian: true }));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 笔记已批量发布 ${result?.published_count ?? 0} 条，跳过 ${result?.skipped_count ?? 0} 条${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 笔记批量发布失败';
  } finally {
    selfEvolutionState.publishingAllObsidianMaintenance = false;
  }
}

async function ignoreObsidianMaintenanceSuggestion(item) {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionId = String(item?.id ?? '').trim();
  if (!suggestionId) {
    toolError.value = '维护建议缺少 ID';
    return;
  }

  selfEvolutionState.ignoringObsidianMaintenanceId = suggestionId;
  try {
    const response = await ignoreProjectObsidianMaintenance(props.project.id, suggestionId);
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 维护建议已忽略${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 维护建议忽略失败';
  } finally {
    selfEvolutionState.ignoringObsidianMaintenanceId = '';
  }
}

async function ignoreVisibleObsidianMaintenanceSuggestions() {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionIds = filteredSelfEvolutionObsidianIgnorable.value
    .map((item) => String(item?.id ?? '').trim())
    .filter(Boolean);
  if (!suggestionIds.length) {
    toolError.value = '当前筛选结果没有可忽略的 Obsidian 维护建议';
    return;
  }

  selfEvolutionState.ignoringAllObsidianMaintenance = true;
  try {
    const response = await ignoreProjectObsidianMaintenanceBatch(props.project.id, {
      suggestion_ids: suggestionIds,
      limit: suggestionIds.length,
    });
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 维护建议已批量忽略 ${result?.ignored_count ?? 0} 条，跳过 ${result?.skipped_count ?? 0} 条${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 维护建议批量忽略失败';
  } finally {
    selfEvolutionState.ignoringAllObsidianMaintenance = false;
  }
}

async function reopenObsidianMaintenanceSuggestion(item) {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionId = String(item?.id ?? '').trim();
  if (!suggestionId) {
    toolError.value = '维护建议缺少 ID';
    return;
  }

  selfEvolutionState.reopeningObsidianMaintenanceId = suggestionId;
  try {
    const response = await reopenProjectObsidianMaintenance(props.project.id, suggestionId);
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 维护建议已恢复处理${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 维护建议恢复失败';
  } finally {
    selfEvolutionState.reopeningObsidianMaintenanceId = '';
  }
}

async function reopenVisibleObsidianMaintenanceSuggestions() {
  if (!props.project?.id) {
    toolError.value = '先在左侧打开一部作品';
    return;
  }
  const suggestionIds = filteredSelfEvolutionObsidianReopenable.value
    .map((item) => String(item?.id ?? '').trim())
    .filter(Boolean);
  if (!suggestionIds.length) {
    toolError.value = '当前筛选结果没有可恢复的 Obsidian 维护建议';
    return;
  }

  selfEvolutionState.reopeningAllObsidianMaintenance = true;
  try {
    const response = await reopenProjectObsidianMaintenanceBatch(props.project.id, {
      suggestion_ids: suggestionIds,
      limit: suggestionIds.length,
    });
    const result = response?.data ?? {};
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response));
    const refreshText = refreshFailureText(refreshError);
    setToolMessage(`Obsidian 维护建议已批量恢复 ${result?.reopened_count ?? 0} 条，跳过 ${result?.skipped_count ?? 0} 条${refreshText}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : 'Obsidian 维护建议批量恢复失败';
  } finally {
    selfEvolutionState.reopeningAllObsidianMaintenance = false;
  }
}

function selectedScheduleTasks() {
  return Object.entries(selfEvolutionScheduleForm.tasks)
    .filter(([, enabled]) => enabled)
    .map(([task]) => task);
}

async function updateSelfEvolutionCandidateStatus(candidate, status) {
  if (!ensureProjectAndChapter()) {
    return;
  }
  const candidateId = String(candidate?.id ?? '').trim();
  if (!candidateId) {
    toolError.value = '候选缺少 ID';
    return;
  }

  selfEvolutionState.updatingCandidateId = candidateId;
  try {
    const response = await updateProjectSelfEvolutionCandidate(props.project.id, candidateId, { status });
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`候选状态已改为${selfEvolutionStatusLabel(status)}${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '更新候选状态失败';
  } finally {
    selfEvolutionState.updatingCandidateId = '';
  }
}

async function runSelfEvolutionCurator() {
  if (!ensureProjectAndChapter()) {
    return;
  }

  selfEvolutionState.isCurating = true;
  try {
    const response = await curateProjectSelfEvolution(props.project.id);
    const report = response?.data ?? {};
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    const checkedCount = Number(report?.checked_count ?? 0);
    const changeCount = Number(report?.change_count ?? 0);
    setToolMessage(`技能维护已完成：检查 ${checkedCount} 项，状态变化 ${changeCount} 项${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '技能维护失败';
  } finally {
    selfEvolutionState.isCurating = false;
  }
}

async function runSelfEvolutionRegression() {
  if (!ensureProjectAndChapter()) {
    return;
  }

  selfEvolutionState.isRegressing = true;
  try {
    const response = await runProjectSelfEvolutionRegression(props.project.id);
    const report = response?.data ?? {};
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`写作回归已完成：平均评分 ${percentLabel(report?.average_score)}${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '写作回归失败';
  } finally {
    selfEvolutionState.isRegressing = false;
  }
}

async function runSelfEvolutionModelReview() {
  if (!ensureProjectAndChapter()) {
    return;
  }

  selfEvolutionState.isReviewing = true;
  try {
    const response = await runProjectSelfEvolutionModelReview(props.project.id);
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`模型审查已完成${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '模型审查失败';
  } finally {
    selfEvolutionState.isReviewing = false;
  }
}

async function saveSelfEvolutionSchedule() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  selfEvolutionScheduleForm.isSaving = true;
  try {
    const response = await updateProjectSelfEvolutionSchedule(props.project.id, {
      enabled: selfEvolutionScheduleForm.enabled,
      interval_hours: selfEvolutionScheduleForm.intervalHours,
      tasks: selectedScheduleTasks(),
    });
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`自学习排程设置已保存${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '保存排程失败';
  } finally {
    selfEvolutionScheduleForm.isSaving = false;
  }
}

async function runSelfEvolutionScheduleNow() {
  if (!ensureProjectAndChapter()) {
    return;
  }
  selfEvolutionScheduleForm.isRunning = true;
  try {
    const response = await runProjectSelfEvolutionSchedule(props.project.id);
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`自学习排程任务已执行${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '执行排程任务失败';
  } finally {
    selfEvolutionScheduleForm.isRunning = false;
  }
}

async function loadSkillVersionsForUsage(skillId) {
  const resolvedSkillId = String(skillId ?? '').trim();
  if (!resolvedSkillId) {
    return;
  }
  skillVersionState.selectedSkillId = resolvedSkillId;
  skillVersionState.isLoading = true;
  try {
    skillVersionState.data = await getSkillVersions(resolvedSkillId);
    setToolMessage('技能版本记录已读取');
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '读取技能版本失败';
  } finally {
    skillVersionState.isLoading = false;
  }
}

async function rollbackSelfEvolutionSkillVersion(versionId) {
  if (!skillVersionState.selectedSkillId || !versionId) {
    return;
  }
  skillVersionState.actionId = String(versionId);
  try {
    await rollbackSkillVersion(skillVersionState.selectedSkillId, versionId);
    await loadSkillVersionsForUsage(skillVersionState.selectedSkillId);
    await refreshSelfEvolutionState({ silent: true });
    setToolMessage('技能已回滚到所选版本');
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '技能回滚失败';
  } finally {
    skillVersionState.actionId = '';
  }
}

async function promoteSelfEvolutionSkill(skillId) {
  const resolvedSkillId = String(skillId ?? '').trim();
  if (!resolvedSkillId) {
    return;
  }
  skillVersionState.actionId = `promote-${resolvedSkillId}`;
  try {
    await promoteSkillToGlobal(resolvedSkillId);
    await refreshSelfEvolutionState({ silent: true });
    await loadSkillVersionsForUsage(resolvedSkillId);
    setToolMessage('技能已提升为全局技能');
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '提升全局技能失败';
  } finally {
    skillVersionState.actionId = '';
  }
}

async function exportSelfEvolutionSkillPackage(skillId) {
  const resolvedSkillId = String(skillId ?? skillVersionState.selectedSkillId ?? '').trim();
  if (!resolvedSkillId) {
    toolError.value = '先选择一个技能';
    return;
  }
  skillPackageState.isExporting = true;
  try {
    const payload = await exportSkillPackage(resolvedSkillId);
    skillPackageState.text = JSON.stringify(payload, null, 2);
    setToolMessage('技能包已生成');
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '导出技能包失败';
  } finally {
    skillPackageState.isExporting = false;
  }
}

async function importSelfEvolutionSkillPackage() {
  const rawText = skillPackageState.text.trim();
  if (!rawText) {
    toolError.value = '请先粘贴技能包 JSON';
    return;
  }
  skillPackageState.isImporting = true;
  try {
    const parsed = JSON.parse(rawText);
    const result = await importSkillPackage({
      package: parsed,
      strategy: skillPackageState.strategy,
    });
    await refreshSkillCatalog();
    await refreshSelfEvolutionState({ silent: true });
    if (result?.skill_id) {
      await loadSkillVersionsForUsage(result.skill_id);
    }
    setToolMessage(`技能包已导入：${result?.skill_name || result?.skill_id || '用户技能'}`);
  } catch (error) {
    toolError.value = error instanceof SyntaxError
      ? '技能包 JSON 格式无效'
      : error instanceof Error
        ? error.message
        : '导入技能包失败';
  } finally {
    skillPackageState.isImporting = false;
  }
}

async function applySelfEvolutionDraft(draft) {
  if (!ensureProjectAndChapter()) {
    return;
  }
  const draftId = String(draft?.id ?? '').trim();
  if (!draftId) {
    toolError.value = '草案缺少 ID';
    return;
  }

  selfEvolutionState.updatingDraftId = draftId;
  try {
    const response = await applyProjectSelfEvolutionDraft(props.project.id, draftId);
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`草案已应用${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '应用草案失败';
  } finally {
    selfEvolutionState.updatingDraftId = '';
  }
}

async function discardSelfEvolutionDraft(draft) {
  if (!ensureProjectAndChapter()) {
    return;
  }
  const draftId = String(draft?.id ?? '').trim();
  if (!draftId) {
    toolError.value = '草案缺少 ID';
    return;
  }

  selfEvolutionState.updatingDraftId = draftId;
  try {
    const response = await updateProjectSelfEvolutionDraft(props.project.id, draftId, { status: 'discarded' });
    const refreshError = await refreshAfterSelfEvolutionAction(response);
    setToolMessage(`草案已废弃${refreshFailureText(refreshError)}`);
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '更新草案状态失败';
  } finally {
    selfEvolutionState.updatingDraftId = '';
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
    await refreshSelfEvolutionState({ silent: true });
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
  if (panel === 'obsidian-vault') {
    obsidianState.value = props.project?.story_overview?.obsidian ?? null;
    isObsidianFormDirty.value = false;
    syncObsidianFormFromState(obsidianState.value, { force: true });
    await refreshObsidianState();
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
      chapter_id: props.selectedChapter?.id ?? '',
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

function chapterIdForIndex(index) {
  const chapter = (props.project?.chapters ?? []).find((item) => Number(item.index) === Number(index));
  return chapter?.id || `chapter-${String(index).padStart(3, '0')}`;
}

function resetChapterPromptPreviewState() {
  chapterPromptPreviewState.open = false;
  chapterPromptPreviewState.loading = false;
  chapterPromptPreviewState.error = '';
  chapterPromptPreviewState.message = '';
  chapterPromptPreviewState.title = '确认章节提示词';
  chapterPromptPreviewState.confirmLabel = '确认生成';
  chapterPromptPreviewState.kind = '';
  chapterPromptPreviewState.payload = null;
  chapterPromptPreviewState.items = [];
}

async function copyChapterPromptPreview(item) {
  const text = String(item?.editablePrompt ?? '').trim();
  if (!text) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    chapterPromptPreviewState.message = '提示词已复制';
  } catch {
    chapterPromptPreviewState.message = '复制失败，可以手动选择文本复制';
  }
}

async function openChapterPromptPreviewDialog({ kind, title, confirmLabel, payload, items }) {
  chapterPromptPreviewState.open = true;
  chapterPromptPreviewState.loading = false;
  chapterPromptPreviewState.error = '';
  chapterPromptPreviewState.message = '';
  chapterPromptPreviewState.kind = kind;
  chapterPromptPreviewState.title = title;
  chapterPromptPreviewState.confirmLabel = confirmLabel;
  chapterPromptPreviewState.payload = payload;
  chapterPromptPreviewState.items = items.map((item) => ({
    key: item.key,
    title: item.title,
    chapterId: item.chapterId || '',
    chapterIndex: item.chapterIndex || 0,
    editablePrompt: item.editablePrompt || '',
    promptText: item.promptText || '',
  }));
}

async function previewSingleChapterPrompt(kind, payload) {
  const preview = kind === 'chapter-workflow'
    ? await previewChapterWorkflowPrompt(payload)
    : await previewChapterGeneratePrompt(payload);
  return {
    key: `${kind}-${preview.chapter_id || payload.chapter_id}`,
    title: preview.title || '章节提示词',
    chapterId: preview.chapter_id || payload.chapter_id,
    chapterIndex: Number(preview.chapter_index || 0),
    editablePrompt: preview.editable_prompt || '',
    promptText: preview.prompt_text || '',
  };
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
  const payload = {
    project_id: props.project.id,
    chapter_id: props.selectedChapter.id,
    mode: config.mode,
    instruction: config.form.instruction.trim(),
    target_words: config.form.targetWords,
  };
  if (config.mode !== 'draft') {
    await runStream(streamChapterWorkflow, payload);
    return;
  }
  try {
    chapterPromptPreviewState.loading = true;
    const item = await previewSingleChapterPrompt('chapter-workflow', payload);
    await openChapterPromptPreviewDialog({
      kind: 'chapter-workflow',
      title: '确认续写提示词',
      confirmLabel: '确认续写',
      payload,
      items: [item],
    });
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '章节提示词预览失败';
  } finally {
    chapterPromptPreviewState.loading = false;
  }
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
  const payload = {
    project_id: props.project.id,
    chapter_id: props.selectedChapter.id,
    instruction: chapterGenerateForm.instruction.trim(),
    style_name: chapterGenerateForm.styleName.trim(),
    xp_preset: chapterGenerateForm.xpPreset.trim(),
    characters_involved: chapterGenerateForm.charactersInvolved.trim(),
    key_items: chapterGenerateForm.keyItems.trim(),
    scene_location: chapterGenerateForm.sceneLocation.trim(),
    time_constraint: chapterGenerateForm.timeConstraint.trim(),
  };
  try {
    chapterPromptPreviewState.loading = true;
    const item = await previewSingleChapterPrompt('chapter-generate', payload);
    await openChapterPromptPreviewDialog({
      kind: 'chapter-generate',
      title: '确认生成提示词',
      confirmLabel: '确认生成',
      payload,
      items: [item],
    });
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '章节提示词预览失败';
  } finally {
    chapterPromptPreviewState.loading = false;
  }
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
  const startChapter = Number(batchForm.startChapter);
  const endChapter = Number(batchForm.endChapter);
  if (endChapter < startChapter) {
    toolError.value = '结束章节不能小于起始章节';
    return;
  }
  const chapterCount = endChapter - startChapter + 1;
  if (chapterCount > 5) {
    toolError.value = '逐章确认提示词时，单次批量生成最多处理 5 章。请缩小章节范围。';
    return;
  }
  const payload = {
    project_id: props.project.id,
    start_chapter: startChapter,
    end_chapter: endChapter,
    instruction: batchForm.instruction.trim(),
    style_name: batchForm.styleName.trim(),
    xp_preset: batchForm.xpPreset.trim(),
  };
  try {
    chapterPromptPreviewState.loading = true;
    const items = await Promise.all(
      Array.from({ length: chapterCount }, (_, offset) => startChapter + offset)
        .map(async (chapterIndex) => {
          const chapterId = chapterIdForIndex(chapterIndex);
          const preview = await previewChapterGeneratePrompt({
            project_id: props.project.id,
            chapter_id: chapterId,
            instruction: payload.instruction,
            style_name: payload.style_name,
            xp_preset: payload.xp_preset,
          });
          return {
            key: `batch-${chapterId}`,
            title: preview.title || `第 ${chapterIndex} 章`,
            chapterId,
            chapterIndex,
            editablePrompt: preview.editable_prompt || '',
            promptText: preview.prompt_text || '',
          };
        }),
    );
    await openChapterPromptPreviewDialog({
      kind: 'batch-generate',
      title: '确认批量生成提示词',
      confirmLabel: '确认批量生成',
      payload,
      items,
    });
  } catch (error) {
    toolError.value = error instanceof Error ? error.message : '批量章节提示词预览失败';
  } finally {
    chapterPromptPreviewState.loading = false;
  }
}

async function handleConfirmChapterPromptPreview() {
  const kind = chapterPromptPreviewState.kind;
  const payload = chapterPromptPreviewState.payload;
  const items = chapterPromptPreviewState.items;
  if (!kind || !payload || !items.length || isToolRunning.value) {
    return;
  }

  resetChapterPromptPreviewState();
  if (kind === 'chapter-workflow') {
    await runStream(streamChapterWorkflow, {
      ...payload,
      prompt_override: items[0].editablePrompt.trim(),
    });
    return;
  }
  if (kind === 'chapter-generate') {
    await runStream(streamChapterGenerate, {
      ...payload,
      prompt_override: items[0].editablePrompt.trim(),
    });
    return;
  }
  if (kind === 'batch-generate') {
    const promptOverrides = Object.fromEntries(
      items.map((item) => [item.chapterId, item.editablePrompt.trim()]),
    );
    await runStream(
      streamBatchGenerate,
      {
        ...payload,
        prompt_overrides: promptOverrides,
      },
      refreshProjectDetail,
    );
  }
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
  const xpPreset = toolResult.value?.revised
    ? rewriteForm.xpPreset.trim()
    : chapterGenerateForm.xpPreset.trim();
  try {
    const {
      detail,
      reviewError,
      selfEvolution,
      selfEvolutionError,
    } = await updateProjectChapter(props.project.id, props.selectedChapter.id, {
      content,
      style_name: styleName,
      xp_preset: xpPreset,
    });
    emit('project-detail-updated', detail);
    applySelfEvolutionState(selfEvolution);
    const messages = [reviewError || '正文已保存到当前章节'];
    if (selfEvolutionError) {
      messages.push(`自学习状态刷新失败：${selfEvolutionError}`);
    }
    setToolMessage(messages.join('；'));
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
      { chapterIndex: props.selectedChapter?.index ?? 0 },
    );
  } catch (error) {
    setToolMessage(error instanceof Error ? error.message : '知识检索失败', 'error');
  }
}

function linesToArray(value) {
  return String(value ?? '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function arrayToLines(value, fallback = '') {
  if (!Array.isArray(value) || value.length === 0) {
    return fallback;
  }
  return value.join('\n');
}

function markObsidianFormTouched() {
  isObsidianFormDirty.value = true;
}

function syncObsidianFormFromState(state, options = {}) {
  if (isObsidianFormDirty.value && !options.force) {
    return;
  }
  const config = state?.config ?? {};
  obsidianForm.enabled = true;
  obsidianForm.vaultPath = config.vault_path || 'Vault';
  obsidianForm.includePatterns = arrayToLines(config.include_patterns, '**/*.md\n**/*.canvas');
  obsidianForm.excludePatterns = arrayToLines(config.exclude_patterns, '.obsidian/**\n.trash/**\ntemplates/**');
  obsidianForm.allowedStatuses = arrayToLines(config.allowed_statuses, 'canonical\n正式\n已确认\nactive\npublished\nusable');
  obsidianForm.excludedStatuses = arrayToLines(config.excluded_statuses, 'draft\n草稿\nprivate\n私密\ndeprecated\n废案\n弃用');
  obsidianForm.includeWithoutStatus = config.include_without_status ?? true;
  obsidianForm.requireUsableByAi = Boolean(config.require_usable_by_ai);
  obsidianForm.maxNotes = Number(config.max_notes ?? 2000);
}

function obsidianPayloadFromForm() {
  return {
    enabled: true,
    vault_path: obsidianForm.vaultPath.trim() || 'Vault',
    include_patterns: linesToArray(obsidianForm.includePatterns),
    exclude_patterns: linesToArray(obsidianForm.excludePatterns),
    allowed_statuses: linesToArray(obsidianForm.allowedStatuses),
    excluded_statuses: linesToArray(obsidianForm.excludedStatuses),
    include_without_status: obsidianForm.includeWithoutStatus,
    require_usable_by_ai: obsidianForm.requireUsableByAi,
    max_notes: Number(obsidianForm.maxNotes || 2000),
  };
}

async function refreshObsidianState() {
  if (!props.project?.id) {
    return;
  }
  const requestId = ++obsidianStateRequestId.value;
  try {
    const state = await getProjectObsidian(props.project.id);
    if (requestId !== obsidianStateRequestId.value) {
      return;
    }
    obsidianState.value = state;
    syncObsidianFormFromState(state);
  } catch (error) {
    if (requestId !== obsidianStateRequestId.value) {
      return;
    }
    setToolMessage(error instanceof Error ? error.message : 'Obsidian 状态读取失败', 'error');
  }
}

async function saveObsidianConfig() {
  if (!ensureProjectAndChapter({ chapter: false })) {
    return;
  }
  const requestId = ++obsidianStateRequestId.value;
  isObsidianSaving.value = true;
  try {
    const response = await updateProjectObsidian(props.project.id, obsidianPayloadFromForm());
    if (requestId !== obsidianStateRequestId.value) {
      return;
    }
    const detail = response?.data ?? {};
    emit('project-detail-updated', detail);
    obsidianState.value = detail.story_overview?.obsidian ?? null;
    isObsidianFormDirty.value = false;
    syncObsidianFormFromState(obsidianState.value, { force: true });
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response, {
      obsidian: true,
      projectDetail: false,
    }));
    setToolMessage(`Obsidian 配置已保存，知识索引已更新${refreshFailureText(refreshError)}`);
  } catch (error) {
    if (requestId !== obsidianStateRequestId.value) {
      return;
    }
    setToolMessage(error instanceof Error ? error.message : 'Obsidian 配置保存失败', 'error');
  } finally {
    isObsidianSaving.value = false;
  }
}

async function runObsidianSync() {
  if (!ensureProjectAndChapter({ chapter: false })) {
    return;
  }
  const requestId = ++obsidianStateRequestId.value;
  isObsidianSaving.value = true;
  try {
    const response = await syncProjectObsidian(props.project.id);
    if (requestId !== obsidianStateRequestId.value) {
      return;
    }
    const detail = response?.data ?? {};
    emit('project-detail-updated', detail);
    obsidianState.value = detail.story_overview?.obsidian ?? null;
    isObsidianFormDirty.value = false;
    syncObsidianFormFromState(obsidianState.value, { force: true });
    const refreshError = await refreshAfterObsidianMaintenance(obsidianMaintenanceRefreshPayload(response, {
      obsidian: true,
      projectDetail: false,
    }));
    setToolMessage(`Obsidian 笔记已同步到知识索引${refreshFailureText(refreshError)}`);
  } catch (error) {
    if (requestId !== obsidianStateRequestId.value) {
      return;
    }
    setToolMessage(error instanceof Error ? error.message : 'Obsidian 同步失败', 'error');
  } finally {
    isObsidianSaving.value = false;
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
      { chapterIndex: props.selectedChapter?.index ?? 0 },
    );
    if (webResearchResult.value?.warning) {
      setToolMessage(webResearchResult.value.warning, 'error');
    } else {
      setToolMessage(`已完成 ${webResearchResult.value?.provider === 'bocha' ? '博查' : '国内'}联网考据`);
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
    `搜索源：${result.provider || '未完成'}`,
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
                :disabled="isToolRunning || chapterPromptPreviewState.loading"
                class="primary-button"
                type="button"
                @click="handleActiveChapterWorkflowRun"
              >
                {{ isToolRunning ? activeChapterWorkflowConfig.runningLabel : chapterPromptPreviewState.loading ? '读取提示词…' : activeChapterWorkflowConfig.submitLabel }}
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
                :disabled="isToolRunning || chapterPromptPreviewState.loading"
                class="primary-button"
                type="button"
                @click="handleChapterGenerateRun"
              >
                {{ isToolRunning ? '生成中…' : chapterPromptPreviewState.loading ? '读取提示词…' : '生成正文' }}
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
              <button
                :disabled="isToolRunning || chapterPromptPreviewState.loading"
                class="primary-button"
                type="button"
                @click="handleBatchRun"
              >
                {{ isToolRunning ? '批量处理中…' : chapterPromptPreviewState.loading ? '读取提示词…' : '开始批量生成' }}
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

          <template v-else-if="activeToolPanelKey === 'obsidian-vault'">
            <div
              class="field-stack"
              data-testid="obsidian-vault-form"
              @change.capture="markObsidianFormTouched"
              @input.capture="markObsidianFormTouched"
            >
              <label class="form-field">
                <span>Vault 文件夹</span>
                <input
                  v-model="obsidianForm.vaultPath"
                  data-testid="obsidian-vault-path-input"
                  placeholder="Vault"
                >
              </label>
              <div class="button-row">
                <button
                  class="primary-button"
                  data-testid="obsidian-save-button"
                  :disabled="isObsidianSaving"
                  type="button"
                  @click="saveObsidianConfig"
                >
                  保存并索引
                </button>
                <button
                  class="secondary-button"
                  data-testid="obsidian-sync-button"
                  :disabled="isObsidianSaving"
                  type="button"
                  @click="runObsidianSync"
                >
                  同步 Vault
                </button>
              </div>
              <details class="advanced-settings">
                <summary>高级同步规则</summary>
                <div class="advanced-settings-body">
                  <label class="form-field">
                    <span>纳入路径</span>
                    <textarea
                      v-model="obsidianForm.includePatterns"
                      rows="3"
                    />
                  </label>
                  <label class="form-field">
                    <span>排除路径</span>
                    <textarea
                      v-model="obsidianForm.excludePatterns"
                      rows="4"
                    />
                  </label>
                  <div class="two-column-fields">
                    <label class="form-field">
                      <span>允许状态</span>
                      <textarea
                        v-model="obsidianForm.allowedStatuses"
                        rows="5"
                      />
                    </label>
                    <label class="form-field">
                      <span>排除状态</span>
                      <textarea
                        v-model="obsidianForm.excludedStatuses"
                        rows="5"
                      />
                    </label>
                  </div>
                  <div class="inline-toggle-group">
                    <label class="toggle-row">
                      <input
                        v-model="obsidianForm.includeWithoutStatus"
                        type="checkbox"
                      >
                      <span>收录未标状态笔记</span>
                    </label>
                    <label class="toggle-row">
                      <input
                        v-model="obsidianForm.requireUsableByAi"
                        type="checkbox"
                      >
                      <span>只收录显式允许 AI 的笔记</span>
                    </label>
                  </div>
                  <label class="form-field compact-field">
                    <span>笔记上限</span>
                    <input
                      v-model.number="obsidianForm.maxNotes"
                      max="10000"
                      min="1"
                      type="number"
                    >
                  </label>
                </div>
              </details>
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

          <template v-else-if="activeToolPanelKey === 'self-evolution'">
            <div
              class="field-stack"
              data-testid="self-evolution-panel"
            >
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>学习状态</h4>
                  <button
                    :disabled="selfEvolutionState.isLoading"
                    class="secondary-button small-button"
                    data-testid="self-evolution-refresh-button"
                    type="button"
                    @click="refreshSelfEvolutionState()"
                  >
                    {{ selfEvolutionState.isLoading ? '刷新中…' : '刷新' }}
                  </button>
                </div>
                <div class="self-evolution-metrics">
                  <div
                    v-for="metric in selfEvolutionMetrics"
                    :key="metric.label"
                    class="self-evolution-metric"
                  >
                    <strong>{{ metric.value }}</strong>
                    <span>{{ metric.label }}</span>
                  </div>
                </div>
              </div>

              <label class="form-field">
                <span>候选状态</span>
                <select
                  v-model="selfEvolutionState.statusFilter"
                  data-testid="self-evolution-status-filter"
                >
                  <option
                    v-for="status in selfEvolutionStatusOptions"
                    :key="status"
                    :value="status"
                  >
                    {{ status === '全部' ? '全部' : selfEvolutionStatusLabel(status) }}
                  </option>
                </select>
              </label>

              <button
                :disabled="selfEvolutionState.isCurating"
                class="secondary-button"
                data-testid="self-evolution-curate-button"
                type="button"
                @click="runSelfEvolutionCurator"
              >
                {{ selfEvolutionState.isCurating ? '维护中…' : '检查技能库状态' }}
              </button>
              <button
                :disabled="selfEvolutionState.isRegressing"
                class="secondary-button"
                data-testid="self-evolution-regression-button"
                type="button"
                @click="runSelfEvolutionRegression"
              >
                {{ selfEvolutionState.isRegressing ? '回归中…' : '运行写作回归' }}
              </button>
              <button
                :disabled="selfEvolutionState.isReviewing"
                class="secondary-button"
                data-testid="self-evolution-model-review-button"
                type="button"
                @click="runSelfEvolutionModelReview"
              >
                {{ selfEvolutionState.isReviewing ? '审查中…' : '模型审查' }}
              </button>
              <div class="subpanel">
                <div class="subpanel-head">
                  <h4>自学习排程</h4>
                  <span>{{ selfEvolutionSchedule.last_run_at || '未执行' }}</span>
                </div>
                <label class="checkbox-field">
                  <input
                    v-model="selfEvolutionScheduleForm.enabled"
                    type="checkbox"
                  >
                  启用可选排程
                </label>
                <label class="form-field compact-field">
                  <span>间隔小时</span>
                  <input
                    v-model.number="selfEvolutionScheduleForm.intervalHours"
                    min="1"
                    type="number"
                  >
                </label>
                <div class="check-grid">
                  <label class="check-pill">
                    <input
                      v-model="selfEvolutionScheduleForm.tasks.curate"
                      type="checkbox"
                    >
                    技能检查
                  </label>
                  <label class="check-pill">
                    <input
                      v-model="selfEvolutionScheduleForm.tasks.regression"
                      type="checkbox"
                    >
                    写作回归
                  </label>
                  <label class="check-pill">
                    <input
                      v-model="selfEvolutionScheduleForm.tasks.model_review"
                      type="checkbox"
                    >
                    模型审查
                  </label>
                </div>
                <div class="action-row">
                  <button
                    :disabled="selfEvolutionScheduleForm.isSaving"
                    class="secondary-button small-button"
                    data-testid="self-evolution-schedule-save-button"
                    type="button"
                    @click="saveSelfEvolutionSchedule"
                  >
                    保存排程
                  </button>
                  <button
                    :disabled="selfEvolutionScheduleForm.isRunning"
                    class="secondary-button small-button"
                    data-testid="self-evolution-schedule-run-button"
                    type="button"
                    @click="runSelfEvolutionScheduleNow"
                  >
                    执行一次
                  </button>
                </div>
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

          <template v-else-if="activeToolPanelKey === 'obsidian-vault'">
            <div
              class="result-shell"
              data-testid="obsidian-vault-results"
            >
              <div class="metric-grid">
                <article class="metric-card">
                  <span>状态</span>
                  <strong>{{ activeObsidianState?.enabled ? '已启用' : '未启用' }}</strong>
                </article>
                <article class="metric-card">
                  <span>笔记</span>
                  <strong>{{ activeObsidianState?.included_count ?? 0 }} 份</strong>
                </article>
	                <article class="metric-card">
	                  <span>双链</span>
	                  <strong>{{ activeObsidianState?.link_count ?? 0 }} 条</strong>
	                </article>
	                <article class="metric-card">
	                  <span>考据链接</span>
	                  <strong data-testid="obsidian-external-link-count">{{ activeObsidianState?.external_link_count ?? 0 }} 条</strong>
	                </article>
	                <article class="metric-card">
	                  <span>已解析</span>
	                  <strong>{{ activeObsidianState?.resolved_link_count ?? 0 }} 条</strong>
                </article>
                <article class="metric-card">
                  <span>未解析</span>
                  <strong>{{ activeObsidianState?.unresolved_link_count ?? 0 }} 条</strong>
                </article>
                <article class="metric-card">
                  <span>歧义</span>
                  <strong>{{ activeObsidianState?.ambiguous_link_count ?? 0 }} 条</strong>
                </article>
                <article class="metric-card">
                  <span>重复命名</span>
                  <strong>{{ activeObsidianState?.duplicate_label_count ?? 0 }} 处</strong>
                </article>
                <article class="metric-card">
                  <span>孤立笔记</span>
                  <strong>{{ activeObsidianState?.orphan_count ?? 0 }} 份</strong>
                </article>
              </div>
              <div
                v-if="activeObsidianState?.warnings?.length"
                class="issue-list"
              >
                <article
                  v-for="item in activeObsidianState.warnings"
                  :key="item"
                  class="issue-card"
                >
                  <strong>提示</strong>
                  <p>{{ item }}</p>
                </article>
              </div>
              <div
                v-if="activeObsidianState?.issues?.length"
                class="issue-list"
              >
                <article
                  v-for="item in activeObsidianState.issues.slice(0, 8)"
                  :key="`${item.kind}-${item.title}`"
                  class="issue-card"
                >
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.message }}</p>
                  <p v-if="item.notes?.length">涉及：{{ item.notes.slice(0, 5).join(' / ') }}</p>
                  <p v-if="item.links?.length">链接：{{ item.links.slice(0, 5).join(' / ') }}</p>
                </article>
              </div>
              <div
                v-if="obsidianNotesPreview.length"
                class="issue-list"
              >
                <article
                  v-for="item in obsidianNotesPreview"
                  :key="item.relative_path"
                  class="issue-card"
                >
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.relative_path }}</p>
                  <p>{{ item.preview || '暂无摘要' }}</p>
                  <p v-if="obsidianChapterScope(item)">{{ obsidianChapterScope(item) }}</p>
                  <p v-if="obsidianNoteSourceChapterText(item)">{{ obsidianNoteSourceChapterText(item) }}</p>
	                  <p v-if="item.required_phrases?.length">必须包含：{{ item.required_phrases.slice(0, 4).join(' / ') }}</p>
	                  <p v-if="item.forbidden_phrases?.length">禁止出现：{{ item.forbidden_phrases.slice(0, 4).join(' / ') }}</p>
	                  <p v-if="item.external_references?.length">考据来源：{{ item.external_references.slice(0, 3).join(' / ') }}</p>
	                  <p v-else-if="item.external_links?.length">考据链接：{{ item.external_links.slice(0, 3).join(' / ') }}</p>
	                  <p v-if="item.links?.length">双链：{{ item.links.slice(0, 4).join(' / ') }}</p>
                  <p v-if="item.graph_relations?.length">关系：{{ item.graph_relations.slice(0, 4).join(' / ') }}</p>
                  <p v-if="item.resolved_links?.length">关联笔记：{{ item.resolved_links.slice(0, 4).join(' / ') }}</p>
                  <p v-if="item.backlinks?.length">被引用：{{ item.backlinks.slice(0, 4).join(' / ') }}</p>
                  <p v-if="item.unresolved_links?.length">未解析：{{ item.unresolved_links.slice(0, 4).join(' / ') }}</p>
                  <p v-if="item.ambiguous_links?.length">歧义：{{ item.ambiguous_links.slice(0, 4).join(' / ') }}</p>
                </article>
              </div>
              <p
                v-else
                class="empty-result-copy"
              >
                保存配置后，符合过滤条件的笔记会显示在这里。
              </p>
            </div>
          </template>

          <template v-else-if="activeToolPanelKey === 'web-research'">
            <div class="result-shell">
              <template v-if="webResearchResult">
                <div class="subpanel-head">
                  <div>
                    <h4>{{ webResearchResult.query }}</h4>
                    <p>{{ webResearchResult.provider === 'bocha' ? '博查联网搜索' : '国内联网搜索' }}</p>
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

          <template v-else-if="activeToolPanelKey === 'self-evolution'">
            <div
              class="result-shell"
              data-testid="self-evolution-result"
            >
              <section
                class="result-section"
                data-testid="self-evolution-dashboard"
              >
                <div class="subpanel-head">
                  <h4>能力看板</h4>
                  <p>{{ selfEvolutionDashboard.generated_at || '等待数据' }}</p>
                </div>
                <div class="self-evolution-metrics">
                  <div class="self-evolution-metric">
                    <strong>{{ percentLabel(selfEvolutionDashboard.latest_writing_score) }}</strong>
                    <span>最近写作评分</span>
                  </div>
                  <div class="self-evolution-metric">
                    <strong>{{ percentLabel(selfEvolutionDashboard.latest_regression_score) }}</strong>
                    <span>最近回归评分</span>
                  </div>
                  <div class="self-evolution-metric">
                    <strong>{{ percentLabel(selfEvolutionDashboard.latest_humanize_ab_score) }}</strong>
                    <span>去 AI A/B</span>
                  </div>
                  <div class="self-evolution-metric">
                    <strong>{{ percentLabel(selfEvolutionDashboard.latest_humanize_judge_score) }}</strong>
                    <span>去 AI 裁判</span>
                  </div>
                  <div class="self-evolution-metric">
                    <strong>{{ selfEvolutionDashboard.latest_humanize_patrol_status || selfEvolutionHumanizePatrol.last_status || '未巡检' }}</strong>
                    <span>去 AI 巡检</span>
                  </div>
                  <div class="self-evolution-metric">
                    <strong>{{ selfEvolutionDashboard.pending_draft_count || 0 }}</strong>
                    <span>待确认草案</span>
                  </div>
                  <div class="self-evolution-metric">
                    <strong>{{ selfEvolutionDashboard.recent_failure_count || 0 }}</strong>
                    <span>近期失败</span>
                  </div>
                </div>
                <div
                  v-if="Object.keys(selfEvolutionQualityDimensions).length"
                  class="issue-list"
                  data-testid="self-evolution-quality-dimensions"
                >
                  <article
                    v-for="(score, key) in selfEvolutionQualityDimensions"
                    :key="key"
                    class="issue-card"
                  >
                    <strong>{{ qualityDimensionLabel(key) }}</strong>
                    <div class="trend-bar">
                      <span :style="{ width: percentLabel(score) }" />
                    </div>
                    <p>{{ percentLabel(score) }}</p>
                  </article>
                </div>
                <div
                  v-if="selfEvolutionWritingTrend.length || selfEvolutionRegressionTrend.length || selfEvolutionHumanizeAbTrend.length || selfEvolutionHumanizeJudgeTrend.length"
                  class="issue-list"
                  data-testid="self-evolution-trends"
                >
                  <article class="issue-card">
                    <strong>写作评分趋势</strong>
                    <div class="trend-row">
                      <span
                        v-for="(item, index) in selfEvolutionWritingTrend.slice(0, 12).reverse()"
                        :key="`writing-${index}-${item.generated_at}`"
                        :style="{ height: percentLabel(item.score) }"
                      />
                    </div>
                  </article>
                  <article class="issue-card">
                    <strong>回归评分趋势</strong>
                    <div class="trend-row">
                      <span
                        v-for="(item, index) in selfEvolutionRegressionTrend.slice(0, 12).reverse()"
                        :key="`regression-${index}-${item.generated_at}`"
                        :style="{ height: percentLabel(item.score) }"
                      />
                    </div>
                  </article>
                  <article class="issue-card">
                    <strong>去 AI A/B 趋势</strong>
                    <div class="trend-row">
                      <span
                        v-for="(item, index) in selfEvolutionHumanizeAbTrend.slice(0, 12).reverse()"
                        :key="`humanize-ab-${index}-${item.generated_at}`"
                        :style="{ height: percentLabel(item.score) }"
                      />
                    </div>
                  </article>
                  <article
                    v-if="selfEvolutionHumanizeJudgeTrend.length"
                    class="issue-card"
                  >
                    <strong>去 AI 裁判趋势</strong>
                    <div class="trend-row">
                      <span
                        v-for="(item, index) in selfEvolutionHumanizeJudgeTrend.slice(0, 12).reverse()"
                        :key="`humanize-judge-${index}-${item.generated_at}`"
                        :style="{ height: percentLabel(item.score) }"
                      />
                    </div>
                  </article>
                </div>
                <div
                  v-if="selfEvolutionDashboard.failing_actions?.length"
                  class="issue-list"
                >
                  <article
                    v-for="item in selfEvolutionDashboard.failing_actions"
                    :key="item.action"
                    class="issue-card"
                  >
                    <strong>{{ item.action }}</strong>
                    <p>失败记录 {{ item.count }} 次</p>
                  </article>
                </div>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-style-xp"
              >
                <div class="subpanel-head">
                  <h4>系统学习版文风 / XP</h4>
                  <p>{{ activeSelfEvolutionStyleXpRules.length }} / {{ selfEvolutionStyleXpRules.length }} 条生效</p>
                </div>
                <div
                  v-if="selfEvolutionStyleXpRules.length"
                  class="issue-list"
                >
                  <article
                    v-for="rule in selfEvolutionStyleXpRules.slice(0, 8)"
                    :key="rule.id"
                    class="issue-card"
                  >
                    <div class="candidate-title-row">
                      <strong>{{ styleXpRuleKindLabel(rule.kind) }}</strong>
                      <span class="skill-tag">{{ styleXpRuleStatusLabel(rule.status) }} · 证据 {{ rule.evidence_count || 1 }} 章</span>
                    </div>
                    <p>{{ rule.content }}</p>
                    <p v-if="rule.rationale">{{ rule.rationale }}</p>
                    <div class="detail-pills">
                      <span class="scene-pill">可信度 {{ percentLabel(rule.confidence) }}</span>
                      <span
                        v-if="rule.signal"
                        class="scene-pill"
                      >
                        {{ rule.signal }}
                      </span>
                    </div>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  保存两章出现相同信号后，这里会显示生效规则。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-narrative-state"
              >
                <div class="subpanel-head">
                  <h4>剧情债务与人物弧线</h4>
                  <p>{{ highRiskNarrativeDebts.length }} / {{ selfEvolutionNarrativeDebts.length }} 条高风险 · {{ selfEvolutionChapterContracts.length }} 份合同</p>
                </div>
                <article
                  v-if="latestNarrativeModelReview"
                  class="issue-card"
                >
                  <div class="candidate-title-row">
                    <strong>模型叙事审查</strong>
                    <span class="skill-tag">{{ latestNarrativeModelReview.status }} · {{ latestNarrativeModelReview.model_source || '本地规则' }}</span>
                  </div>
                  <p>{{ latestNarrativeModelReview.summary }}</p>
                  <ul
                    v-if="latestNarrativeModelReview.risk_notes?.length"
                    class="plain-list"
                  >
                    <li
                      v-for="item in latestNarrativeModelReview.risk_notes.slice(0, 4)"
                      :key="item"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </article>
                <div
                  data-testid="self-evolution-narrative-contracts"
                >
                  <article
                    v-if="latestChapterContract"
                    class="issue-card"
                  >
                    <div class="candidate-title-row">
                      <strong>章节合同 · 第 {{ latestChapterContract.target_chapter_index }} 章</strong>
                      <span class="skill-tag">{{ latestChapterContract.generated_by || '规则' }}</span>
                    </div>
                    <p>{{ latestChapterContract.objective }}</p>
                    <ul
                      v-if="latestChapterContract.required_beats?.length"
                      class="plain-list"
                    >
                      <li
                        v-for="item in latestChapterContract.required_beats.slice(0, 4)"
                        :key="item"
                      >
                        {{ item }}
                      </li>
                    </ul>
                  </article>
                  <p
                    v-else
                    class="empty-result-copy"
                  >
                    章节合同会在模型叙事审查后显示。
                  </p>
                </div>
                <article
                  v-if="latestContractReview"
                  class="issue-card"
                >
                  <div class="candidate-title-row">
                    <strong>合同执行回看 · 第 {{ latestContractReview.target_chapter_index }} 章</strong>
                    <span class="skill-tag">{{ latestContractReview.status }} · {{ latestContractReview.score || 0 }} 分</span>
                  </div>
                  <p v-if="latestContractReview.missed?.length">未满足：{{ latestContractReview.missed.slice(0, 3).join('；') }}</p>
                  <p v-else>合同执行没有记录未满足项。</p>
                </article>
                <div
                  v-if="selfEvolutionNarrativeDebts.length"
                  class="issue-list"
                >
                  <article
                    v-for="debt in selfEvolutionNarrativeDebts.slice(0, 8)"
                    :key="debt.id"
                    class="issue-card"
                  >
                    <div class="candidate-title-row">
                      <strong>{{ debt.title || narrativeDebtKindLabel(debt.kind) }}</strong>
                      <span class="skill-tag">
                        {{ narrativeDebtKindLabel(debt.kind) }} · {{ narrativeDebtStatusLabel(debt.status) }} · 风险 {{ narrativeRiskLabel(debt.risk_level) }}
                      </span>
                    </div>
                    <p>{{ debt.content }}</p>
                    <p v-if="debt.next_required_action">{{ debt.next_required_action }}</p>
                    <div class="detail-pills">
                      <span
                        v-if="debt.last_seen_chapter_index"
                        class="scene-pill"
                      >
                        最近第 {{ debt.last_seen_chapter_index }} 章
                      </span>
                      <span
                        v-if="debt.expected_payoff_range?.length === 2"
                        class="scene-pill"
                      >
                        预计第 {{ debt.expected_payoff_range[0] }}-{{ debt.expected_payoff_range[1] }} 章
                      </span>
                    </div>
                  </article>
                </div>
                <div
                  v-if="selfEvolutionCharacterArcs.length"
                  class="issue-list"
                >
                  <article
                    v-for="arc in selfEvolutionCharacterArcs.slice(0, 6)"
                    :key="arc.id"
                    class="issue-card"
                  >
                    <strong>{{ arc.name }} · {{ arc.phase || '人物弧线' }}</strong>
                    <p>{{ arc.unresolved_pressure || arc.current_state }}</p>
                    <p v-if="arc.required_next_check">{{ arc.required_next_check }}</p>
                  </article>
                </div>
                <article
                  v-if="latestChapterCard"
                  class="issue-card"
                  data-testid="self-evolution-narrative-chapter-card"
                >
                  <strong>最新章节任务卡</strong>
                  <p>
                    第 {{ latestChapterCard.chapter_index }} 章 ·
                    {{ latestChapterCard.stage }}
                  </p>
                  <ul class="plain-list">
                    <li
                      v-for="item in (latestChapterCard.required_outcomes || []).slice(0, 4)"
                      :key="item"
                    >
                      {{ item }}
                    </li>
                  </ul>
                  <div
                    v-if="latestChapterCardHasObsidian"
                    class="obsidian-task-constraints"
                    data-testid="self-evolution-narrative-obsidian-card"
                  >
                    <strong>Obsidian 任务约束</strong>
                    <p v-if="latestChapterCardObsidianSources.length">
                      来源：{{ latestChapterCardObsidianSources.slice(0, 3).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianExternalReferences.length">
                      考据来源：{{ latestChapterCardObsidianExternalReferences.slice(0, 3).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianRequired.length">
                      必写：{{ latestChapterCardObsidianRequired.slice(0, 4).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianForbidden.length">
                      禁写：{{ latestChapterCardObsidianForbidden.slice(0, 4).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianNarrativeDebts.length">
                      剧情债务：{{ latestChapterCardObsidianNarrativeDebts.slice(0, 3).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianCharacterArcs.length">
                      人物弧线：{{ latestChapterCardObsidianCharacterArcs.slice(0, 3).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianSatisfied.length">
                      已满足：{{ latestChapterCardObsidianSatisfied.slice(0, 4).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianMissing.length">
                      未完成：{{ latestChapterCardObsidianMissing.slice(0, 4).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianViolations.length">
                      已触犯：{{ latestChapterCardObsidianViolations.slice(0, 4).join('；') }}
                    </p>
                    <p v-if="latestChapterCardObsidianRisks.length">
                      图谱风险：{{ latestChapterCardObsidianRisks.slice(0, 3).join('；') }}
                    </p>
                  </div>
                </article>
                <div
                  v-if="selfEvolutionObsidianMaintenance.length"
                  class="issue-list"
                  data-testid="self-evolution-obsidian-maintenance"
                >
                  <article
                    class="issue-card"
                    data-testid="self-evolution-obsidian-maintenance-summary"
                  >
                    <div class="candidate-title-row">
                      <strong>Obsidian 维护摘要</strong>
                      <span
                        v-if="hasSelfEvolutionObsidianMaintenanceFilters"
                        class="skill-tag"
                      >
                        当前筛选
                      </span>
                      <button
                        v-if="obsidianMaintenanceArtifactFilterCount > 0"
                        class="secondary-button small-button"
                        data-testid="self-evolution-obsidian-maintenance-artifact-filter"
                        type="button"
                        @click="clearObsidianMaintenanceArtifactFilter"
                      >
                        清除产物筛选（{{ obsidianMaintenanceArtifactFilterCount }}）
                      </button>
                      <span class="skill-tag">待处理 {{ selfEvolutionObsidianMaintenanceSummary.needs_action || 0 }} / {{ selfEvolutionObsidianMaintenanceSummary.total || 0 }}</span>
                    </div>
                    <p>
                      高优先级 {{ selfEvolutionObsidianMaintenanceSummary.high_priority || 0 }} 条 ·
                      自动草稿 {{ selfEvolutionObsidianMaintenanceSummary.auto_staged || 0 }} 条 ·
                      草稿缺失 {{ selfEvolutionObsidianMaintenanceSummary.by_status?.draft_missing || 0 }} 条 ·
                      Vault 笔记缺失 {{ selfEvolutionObsidianMaintenanceSummary.by_status?.published_missing || 0 }} 条
                      · Vault 已移动 {{ selfEvolutionObsidianMaintenanceSummary.by_status?.vault_moved || 0 }} 条
                      · Vault 待更新 {{ selfEvolutionObsidianMaintenanceSummary.by_status?.published_outdated || 0 }} 条
                      · 已忽略 {{ selfEvolutionObsidianMaintenanceSummary.by_status?.ignored || 0 }} 条
                    </p>
                    <div class="two-column-grid">
	                      <label class="form-field">
	                        <span>维护状态</span>
	                        <select
                          v-model="selfEvolutionState.obsidianMaintenanceStatusFilter"
                          data-testid="self-evolution-obsidian-maintenance-filter"
                        >
                          <option
                            v-for="status in obsidianMaintenanceStatusOptions"
                            :key="status"
                            :value="status"
                          >
                            {{ status }}
	                          </option>
	                        </select>
	                      </label>
	                      <label class="form-field">
	                        <span>来源章节</span>
	                        <input
	                          v-model="selfEvolutionState.obsidianMaintenanceSourceChapter"
	                          data-testid="self-evolution-obsidian-maintenance-source-chapter"
	                          min="1"
	                          type="number"
	                          placeholder="例如 58"
	                        >
	                      </label>
	                      <label class="form-field">
	                        <span>搜索维护项</span>
	                        <input
                          v-model="selfEvolutionState.obsidianMaintenanceQuery"
                          data-testid="self-evolution-obsidian-maintenance-search"
                          type="text"
                          placeholder="标题、路径、章节或动作"
                        >
                      </label>
                    </div>
                    <p data-testid="self-evolution-obsidian-maintenance-count">
                      显示 {{ filteredSelfEvolutionObsidianMaintenance.length }} / {{ selfEvolutionObsidianMaintenance.length }} 条
                    </p>
                    <div class="action-row">
                      <button
                        class="secondary-button small-button"
                        data-testid="self-evolution-obsidian-stage-visible-button"
                        type="button"
                        :disabled="selfEvolutionState.stagingAllObsidianMaintenance || filteredSelfEvolutionObsidianStageable.length === 0"
                        @click="stageVisibleObsidianMaintenanceSuggestions"
                      >
                        {{ selfEvolutionState.stagingAllObsidianMaintenance ? '保存中…' : `保存当前结果草稿 (${filteredSelfEvolutionObsidianStageable.length})` }}
                      </button>
                      <button
                        class="primary-button small-button"
                        data-testid="self-evolution-obsidian-publish-visible-button"
                        type="button"
                        :disabled="selfEvolutionState.publishingAllObsidianMaintenance || filteredSelfEvolutionObsidianPublishable.length === 0"
                        @click="publishVisibleObsidianMaintenanceSuggestions"
                      >
                        {{ selfEvolutionState.publishingAllObsidianMaintenance ? '发布中…' : `发布当前草稿到 Vault (${filteredSelfEvolutionObsidianPublishable.length})` }}
                      </button>
                      <button
                        class="primary-button small-button"
                        data-testid="self-evolution-obsidian-confirm-merge-visible-button"
                        type="button"
                        :disabled="selfEvolutionState.confirmingAllObsidianMaintenanceMerges || filteredSelfEvolutionObsidianMergeConfirmable.length === 0"
                        @click="confirmVisibleObsidianMaintenanceMerges"
                      >
                        {{ selfEvolutionState.confirmingAllObsidianMaintenanceMerges ? '确认中…' : `确认当前 Vault 合并 (${filteredSelfEvolutionObsidianMergeConfirmable.length})` }}
                      </button>
                      <button
                        class="secondary-button small-button"
                        data-testid="self-evolution-obsidian-ignore-visible-button"
                        type="button"
                        :disabled="selfEvolutionState.ignoringAllObsidianMaintenance || filteredSelfEvolutionObsidianIgnorable.length === 0"
                        @click="ignoreVisibleObsidianMaintenanceSuggestions"
                      >
                        {{ selfEvolutionState.ignoringAllObsidianMaintenance ? '忽略中…' : `忽略当前结果 (${filteredSelfEvolutionObsidianIgnorable.length})` }}
                      </button>
                      <button
                        class="secondary-button small-button"
                        data-testid="self-evolution-obsidian-reopen-visible-button"
                        type="button"
                        :disabled="selfEvolutionState.reopeningAllObsidianMaintenance || filteredSelfEvolutionObsidianReopenable.length === 0"
                        @click="reopenVisibleObsidianMaintenanceSuggestions"
                      >
                        {{ selfEvolutionState.reopeningAllObsidianMaintenance ? '恢复中…' : `恢复当前结果 (${filteredSelfEvolutionObsidianReopenable.length})` }}
                      </button>
                    </div>
                  </article>
                  <article
                    v-for="item in filteredSelfEvolutionObsidianMaintenance"
                    :key="item.id || item.title"
                    class="issue-card"
                  >
                    <div class="candidate-title-row">
                      <strong>{{ item.title }}</strong>
                      <span class="skill-tag">{{ item.priority || 'medium' }} · {{ obsidianMaintenanceStatusLabel(item) }}</span>
                    </div>
	                    <p>{{ item.reason || item.action }}</p>
	                    <p v-if="item.suggested_path">建议笔记：{{ item.suggested_path }}</p>
	                    <p v-if="obsidianMaintenanceSourceChapterText(item)">{{ obsidianMaintenanceSourceChapterText(item) }}</p>
	                    <p v-if="item.draft_path">草稿文件：{{ item.draft_path }}</p>
                    <p v-if="item.merge_draft_path">Vault 合并草稿：{{ item.merge_draft_path }}</p>
                    <p v-if="item.merge_draft_manual_edits">Vault 合并草稿已有人工改动，系统已保留原文。</p>
                    <p v-if="item.draft_missing">草稿文件不存在，可重新保存。</p>
                    <p v-if="item.published_missing">Vault 笔记不存在，可重新发布。</p>
                    <p v-if="item.published_outdated">Vault 笔记仍是旧自动草稿，可保存新版草稿后人工合并。</p>
                    <p v-if="item.preserved_existing_draft">同路径已有人工内容，系统已保留原文。</p>
                    <p v-else-if="item.manual_draft_edits">草稿已有人工改动，后续自动更新不会覆盖。</p>
                    <p v-if="item.vault_moved">Vault 笔记已移动：{{ item.moved_from_vault_relative_path }} → {{ item.vault_relative_path }}</p>
                    <p v-if="item.vault_relative_path">Vault 笔记：{{ item.vault_relative_path }}</p>
                    <p v-if="item.action">{{ item.action }}</p>
                    <div class="action-row">
                      <button
                        v-if="item.draft_markdown"
                        class="secondary-button small-button"
                        type="button"
                        :disabled="selfEvolutionState.stagingObsidianMaintenanceId === item.id || selfEvolutionState.publishingObsidianMaintenanceId === item.id || selfEvolutionState.confirmingObsidianMaintenanceMergeId === item.id || selfEvolutionState.ignoringObsidianMaintenanceId === item.id || selfEvolutionState.reopeningObsidianMaintenanceId === item.id"
                        @click="stageObsidianMaintenanceSuggestion(item)"
                      >
                        {{ selfEvolutionState.stagingObsidianMaintenanceId === item.id ? '保存中…' : '保存草稿' }}
                      </button>
                      <button
                        v-if="item.draft_markdown"
                        class="primary-button small-button"
                        data-testid="self-evolution-obsidian-publish-button"
                        type="button"
                        :disabled="selfEvolutionState.publishingObsidianMaintenanceId === item.id || selfEvolutionState.stagingObsidianMaintenanceId === item.id || selfEvolutionState.confirmingObsidianMaintenanceMergeId === item.id || selfEvolutionState.ignoringObsidianMaintenanceId === item.id || selfEvolutionState.reopeningObsidianMaintenanceId === item.id || item.status === 'published' || item.status === 'published_outdated' || Boolean(item.merge_draft_path)"
                        @click="publishObsidianMaintenanceSuggestion(item)"
                      >
                        {{ selfEvolutionState.publishingObsidianMaintenanceId === item.id ? '发布中…' : '发布到 Vault' }}
                      </button>
                      <button
                        v-if="item.merge_draft_path"
                        class="primary-button small-button"
                        data-testid="self-evolution-obsidian-confirm-merge-button"
                        type="button"
                        :disabled="selfEvolutionState.confirmingObsidianMaintenanceMergeId === item.id || selfEvolutionState.publishingObsidianMaintenanceId === item.id || selfEvolutionState.stagingObsidianMaintenanceId === item.id || selfEvolutionState.ignoringObsidianMaintenanceId === item.id || selfEvolutionState.reopeningObsidianMaintenanceId === item.id"
                        @click="confirmObsidianMaintenanceMerge(item)"
                      >
                        {{ selfEvolutionState.confirmingObsidianMaintenanceMergeId === item.id ? '确认中…' : '确认 Vault 已合并' }}
                      </button>
                      <button
                        v-if="item.status === 'ignored'"
                        class="secondary-button small-button"
                        type="button"
                        :disabled="selfEvolutionState.reopeningObsidianMaintenanceId === item.id || selfEvolutionState.stagingObsidianMaintenanceId === item.id || selfEvolutionState.publishingObsidianMaintenanceId === item.id || selfEvolutionState.confirmingObsidianMaintenanceMergeId === item.id || selfEvolutionState.ignoringObsidianMaintenanceId === item.id"
                        @click="reopenObsidianMaintenanceSuggestion(item)"
                      >
                        {{ selfEvolutionState.reopeningObsidianMaintenanceId === item.id ? '恢复中…' : '恢复处理' }}
                      </button>
                      <button
                        v-else
                        class="secondary-button small-button"
                        type="button"
                        :disabled="selfEvolutionState.ignoringObsidianMaintenanceId === item.id || selfEvolutionState.stagingObsidianMaintenanceId === item.id || selfEvolutionState.publishingObsidianMaintenanceId === item.id || selfEvolutionState.confirmingObsidianMaintenanceMergeId === item.id || selfEvolutionState.reopeningObsidianMaintenanceId === item.id || item.status === 'published'"
                        @click="ignoreObsidianMaintenanceSuggestion(item)"
                      >
                        {{ selfEvolutionState.ignoringObsidianMaintenanceId === item.id ? '忽略中…' : '忽略' }}
                      </button>
                    </div>
                  </article>
                  <p
                    v-if="filteredSelfEvolutionObsidianMaintenance.length === 0"
                    class="empty-result-copy"
                  >
                    没有匹配的 Obsidian 维护项。
                  </p>
                </div>
                <p
                  v-if="!selfEvolutionNarrativeDebts.length && !selfEvolutionCharacterArcs.length"
                  class="empty-result-copy"
                >
                  保存章节后会在这里显示伏笔、承诺、关系压力和人物弧线状态。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-failure-cases"
              >
                <div class="subpanel-head">
                  <h4>失败案例库</h4>
                  <p>{{ selfEvolutionFailureCases.length }} 条</p>
                </div>
                <div
                  v-if="selfEvolutionFailureGroups.length"
                  class="issue-list"
                >
                  <article
                    v-for="item in selfEvolutionFailureGroups"
                    :key="`${item.action_kind}-${item.latest_at}`"
                    class="issue-card"
                  >
                    <div class="candidate-title-row">
                      <strong>{{ item.action_kind || '失败类型' }}</strong>
                      <span class="skill-tag">{{ item.status === 'repeated' ? '重复出现' : '单次' }} · {{ item.count || 0 }} 次</span>
                    </div>
                    <p>{{ item.latest_summary }}</p>
                    <p>{{ item.prevention }}</p>
                  </article>
                </div>
                <div
                  v-if="selfEvolutionFailureCases.length"
                  class="issue-list"
                >
                  <article
                    v-for="item in selfEvolutionFailureCases.slice(0, 6)"
                    :key="item.id"
                    class="issue-card"
                  >
                    <strong>{{ item.action_kind || item.label || '失败案例' }}</strong>
                    <p>{{ item.summary }}</p>
                    <p>{{ item.prevention }}</p>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  失败任务会进入这里，后续同类任务会把提醒带进 Agent 上下文。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-drafts"
              >
                <div class="subpanel-head">
                  <h4>确认草案</h4>
                  <p>{{ pendingSelfEvolutionDrafts.length }} 个待确认</p>
                </div>
                <div
                  v-if="selfEvolutionDrafts.length"
                  class="issue-list"
                >
                  <article
                    v-for="draft in selfEvolutionDrafts.slice(0, 8)"
                    :key="draft.id"
                    class="issue-card"
                    data-testid="self-evolution-draft-card"
                  >
                    <div class="candidate-title-row">
                      <strong>{{ draft.title || '自学习草案' }}</strong>
                      <span class="skill-tag">{{ selfEvolutionDraftKindLabel(draft.kind) }} · {{ draft.status || 'pending' }}</span>
                    </div>
                    <p>{{ draft.summary }}</p>
                    <div
                      v-if="draft.diff_preview?.summary || previewListItems(draft.diff_preview?.additions).length || previewListItems(draft.diff_preview?.warnings).length"
                      class="diff-preview"
                    >
                      <strong v-if="draft.diff_preview?.summary">{{ draft.diff_preview.summary }}</strong>
                      <ul
                        v-if="previewListItems(draft.diff_preview?.additions).length"
                        class="plain-list"
                      >
                        <li
                          v-for="item in previewListItems(draft.diff_preview?.additions).slice(0, 3)"
                          :key="item"
                        >
                          {{ item }}
                        </li>
                      </ul>
                      <ul
                        v-if="previewListItems(draft.diff_preview?.warnings).length"
                        class="plain-list diff-warning-list"
                      >
                        <li
                          v-for="item in previewListItems(draft.diff_preview?.warnings).slice(0, 3)"
                          :key="item"
                        >
                          {{ item }}
                        </li>
                      </ul>
                    </div>
                    <pre
                      v-if="draft.payload?.body_markdown"
                      class="mini-pre"
                    >{{ draft.payload.body_markdown }}</pre>
                    <div class="action-row">
                      <button
                        :disabled="draft.status !== 'pending' || selfEvolutionState.updatingDraftId === draft.id"
                        class="secondary-button small-button"
                        type="button"
                        @click="applySelfEvolutionDraft(draft)"
                      >
                        应用草案
                      </button>
                      <button
                        :disabled="draft.status !== 'pending' || selfEvolutionState.updatingDraftId === draft.id"
                        class="secondary-button small-button"
                        type="button"
                        @click="discardSelfEvolutionDraft(draft)"
                      >
                        废弃
                      </button>
                    </div>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  把候选改为“已采纳”后，这里会生成待确认草案。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-regression"
              >
                <div class="subpanel-head">
                  <h4>写作回归</h4>
                  <p>{{ selfEvolutionRegressionRuns.length }} 次</p>
                </div>
                <template v-if="selfEvolutionRegressionRuns.length">
                  <article class="issue-card">
                    <strong>{{ selfEvolutionRegressionRuns[0].chapter_title || selfEvolutionRegressionRuns[0].chapter_id }}</strong>
                    <p>平均评分 {{ percentLabel(selfEvolutionRegressionRuns[0].average_score) }} · {{ selfEvolutionRegressionRuns[0].status }}</p>
                    <template v-if="selfEvolutionRegressionRuns[0].humanize_ab_benchmark">
                      <p>
                        去 AI A/B {{ percentLabel(selfEvolutionRegressionRuns[0].humanize_ab_benchmark.score) }}
                        · 平均提升 {{ selfEvolutionRegressionRuns[0].humanize_ab_benchmark.average_delta }}
                        · 通过率 {{ percentLabel(selfEvolutionRegressionRuns[0].humanize_ab_benchmark.pass_rate) }}
                      </p>
                      <ul
                        v-if="selfEvolutionRegressionRuns[0].humanize_ab_benchmark.distilled_rules?.length"
                        class="plain-list"
                      >
                        <li
                          v-for="rule in selfEvolutionRegressionRuns[0].humanize_ab_benchmark.distilled_rules"
                          :key="rule"
                        >
                          {{ rule }}
                        </li>
                      </ul>
                      <p v-if="selfEvolutionRegressionRuns[0].humanize_ab_benchmark.project_sample_pool?.sample_count">
                        项目样本池 {{ selfEvolutionRegressionRuns[0].humanize_ab_benchmark.project_sample_pool.sample_count }} 个
                        · 风险章节 {{ selfEvolutionRegressionRuns[0].humanize_ab_benchmark.project_sample_pool.risk_count }} 个
                        · 平均评分 {{ percentLabel(selfEvolutionRegressionRuns[0].humanize_ab_benchmark.project_sample_pool.average_score_ratio) }}
                      </p>
                      <ul
                        v-if="selfEvolutionRegressionRuns[0].humanize_ab_benchmark.project_sample_pool?.samples?.length"
                        class="plain-list"
                      >
                        <li
                          v-for="sample in (selfEvolutionRegressionRuns[0].humanize_ab_benchmark.project_sample_pool.samples || []).slice(0, 3)"
                          :key="sample.signature || sample.chapter_id"
                        >
                          第 {{ sample.chapter_index }} 章 · {{ percentLabel(sample.score_ratio) }} ·
                          {{ humanizeSampleIssueText(sample) }}
                          <span v-if="sample.snippet">：{{ sample.snippet }}</span>
                        </li>
                      </ul>
                    </template>
                    <div class="issue-list">
                      <article
                        v-for="item in selfEvolutionRegressionRuns[0].cases"
                        :key="item.id"
                        class="issue-card"
                      >
                        <strong>{{ item.label }}</strong>
                        <p>{{ percentLabel(item.score) }} · {{ item.status }}</p>
                        <ul
                          v-if="item.suggestions?.length"
                          class="plain-list"
                        >
                          <li
                            v-for="suggestion in item.suggestions"
                            :key="suggestion"
                          >
                            {{ suggestion }}
                          </li>
                        </ul>
                      </article>
                    </div>
                  </article>
                </template>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  运行写作回归后，会用同一样本章检查续写、改稿、去 AI 和资料调用。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-model-reviews"
              >
                <div class="subpanel-head">
                  <h4>模型审查</h4>
                  <p>{{ selfEvolutionModelReviews.length }} 次</p>
                </div>
                <article
                  v-if="selfEvolutionModelReviews.length"
                  class="issue-card"
                >
                  <strong>{{ selfEvolutionModelReviews[0].summary || '模型审查' }}</strong>
                  <p>{{ selfEvolutionModelReviews[0].status }}</p>
                  <div
                    v-if="selfEvolutionModelReviews[0].humanize_patrol"
                    class="detail-pills"
                  >
                    <span class="scene-pill">
                      触发 {{ selfEvolutionModelReviews[0].humanize_patrol.trigger || selfEvolutionModelReviews[0].humanize_patrol.reason }}
                    </span>
                    <span class="scene-pill">
                      来源 {{ selfEvolutionModelReviews[0].humanize_patrol.reason || '巡检' }}
                    </span>
                  </div>
                  <div
                    v-if="selfEvolutionModelReviews[0].cross_review"
                    class="detail-pills"
                  >
                    <span class="scene-pill">
                      审查模型 {{ selfEvolutionModelReviews[0].cross_review.reviewer_count || 1 }} 个
                    </span>
                    <span class="scene-pill">
                      {{ selfEvolutionModelReviews[0].cross_review.status || 'unknown' }}
                    </span>
                  </div>
                  <p v-if="selfEvolutionModelReviews[0].cross_review?.summary">
                    {{ selfEvolutionModelReviews[0].cross_review.summary }}
                  </p>
                  <template v-if="selfEvolutionModelReviews[0].humanize_model_judge">
                    <p>
                      去 AI 裁判 {{ percentLabel(selfEvolutionModelReviews[0].humanize_model_judge.score) }}
                      · 样本 {{ selfEvolutionModelReviews[0].humanize_model_judge.sample_count || 0 }}
                      · 历史 {{ selfEvolutionModelReviews[0].humanize_model_judge.history_sample_count || 0 }}
                      · {{ selfEvolutionModelReviews[0].humanize_model_judge.status }}
                    </p>
                    <p v-if="selfEvolutionModelReviews[0].humanize_model_judge.summary">
                      {{ selfEvolutionModelReviews[0].humanize_model_judge.summary }}
                    </p>
                    <ul
                      v-if="selfEvolutionModelReviews[0].humanize_model_judge.issues?.length"
                      class="plain-list"
                    >
                      <li
                        v-for="issue in selfEvolutionModelReviews[0].humanize_model_judge.issues.slice(0, 4)"
                        :key="issue.title || issue.label || issue.detail"
                      >
                        {{ humanizeJudgeIssueText(issue) }}
                      </li>
                    </ul>
                    <ul
                      v-if="selfEvolutionModelReviews[0].humanize_model_judge.distilled_rules?.length"
                      class="plain-list"
                    >
                      <li
                        v-for="rule in selfEvolutionModelReviews[0].humanize_model_judge.distilled_rules.slice(0, 4)"
                        :key="rule"
                      >
                        {{ rule }}
                      </li>
                    </ul>
                    <p v-if="selfEvolutionModelReviews[0].humanize_rule_update">
                      去 AI 项目规则：新增 {{ selfEvolutionModelReviews[0].humanize_rule_update.inserted || 0 }} 条 ·
                      刷新 {{ selfEvolutionModelReviews[0].humanize_rule_update.refreshed || 0 }} 条 ·
                      共 {{ selfEvolutionModelReviews[0].humanize_rule_update.total || 0 }} 条
                    </p>
                  </template>
                  <ul class="plain-list">
                    <li
                      v-for="item in [
                        ...(selfEvolutionModelReviews[0].failure_causes || []),
                        ...(selfEvolutionModelReviews[0].improvement_suggestions || []),
                        ...(selfEvolutionModelReviews[0].cross_review?.improvement_suggestions || []),
                      ].slice(0, 8)"
                      :key="item"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </article>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  点击“模型审查”后，会生成失败原因和改进建议。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-candidates"
              >
                <div class="subpanel-head">
                  <h4>经验候选</h4>
                  <p>{{ filteredSelfEvolutionCandidates.length }} / {{ selfEvolutionCandidates.length }}</p>
                </div>
                <div
                  v-if="filteredSelfEvolutionCandidates.length"
                  class="issue-list"
                >
                  <article
                    v-for="candidate in filteredSelfEvolutionCandidates"
                    :key="candidate.id"
                    class="issue-card"
                    data-testid="self-evolution-candidate-card"
                  >
                    <div class="candidate-title-row">
                      <strong>{{ candidate.title || '未命名候选' }}</strong>
                      <span class="skill-tag">{{ selfEvolutionKindLabel(candidate.kind) }} · {{ selfEvolutionStatusLabel(candidate.status) }}</span>
                    </div>
                    <p>{{ candidate.content }}</p>
                    <p v-if="candidate.rationale">{{ candidate.rationale }}</p>
                    <div class="detail-pills">
                      <span class="scene-pill">可信度 {{ percentLabel(candidate.confidence) }}</span>
                      <span class="scene-pill">出现 {{ candidate.seen_count || 1 }} 次</span>
                      <span
                        v-if="candidate.last_seen_at"
                        class="scene-pill"
                      >
                        {{ candidate.last_seen_at }}
                      </span>
                    </div>
                    <div class="action-row">
                      <button
                        v-for="status in selfEvolutionStatusOptions.filter((item) => item !== '全部')"
                        :key="`${candidate.id}-${status}`"
                        :disabled="candidate.status === status || selfEvolutionState.updatingCandidateId === candidate.id"
                        class="secondary-button small-button"
                        type="button"
                        @click="updateSelfEvolutionCandidateStatus(candidate, status)"
                      >
                        {{ selfEvolutionStatusLabel(status) }}
                      </button>
                    </div>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  当前没有符合筛选条件的候选。Agent 完成任务后会在这里显示可复用经验。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-rules"
              >
                <div class="subpanel-head">
                  <h4>调用规则</h4>
                  <p>{{ selfEvolutionRules.length }} 条</p>
                </div>
                <div
                  v-if="selfEvolutionRules.length"
                  class="issue-list"
                >
                  <article
                    v-for="rule in selfEvolutionRules"
                    :key="rule.id"
                    class="issue-card"
                  >
                    <strong>{{ rule.title || '调用规则' }}</strong>
                    <p>{{ rule.content }}</p>
                    <p v-if="rule.rationale">{{ rule.rationale }}</p>
                    <div class="detail-pills">
                      <span class="scene-pill">可信度 {{ percentLabel(rule.confidence) }}</span>
                      <span class="scene-pill">出现 {{ rule.seen_count || 1 }} 次</span>
                    </div>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  还没有高可信调用规则。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-evaluations"
              >
                <div class="subpanel-head">
                  <h4>写作评价</h4>
                  <p>{{ selfEvolutionEvaluations.length }} 条</p>
                </div>
                <div
                  v-if="selfEvolutionEvaluations.length"
                  class="issue-list"
                >
                  <article
                    v-for="item in selfEvolutionEvaluations.slice(0, 6)"
                    :key="item.id"
                    class="issue-card"
                  >
                    <strong>评分 {{ percentLabel(item.score) }}</strong>
                    <p>{{ item.latest_user_message || item.task_pack_kind || item.task_id }}</p>
                    <div class="detail-pills">
                      <span class="scene-pill">变更 {{ item.project_change_count || 0 }}</span>
                      <span class="scene-pill">失败 {{ item.failure_count || 0 }}</span>
                      <span
                        v-if="item.knowledge_used"
                        class="scene-pill"
                      >
                        已用资料
                      </span>
                    </div>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  Agent 产生写作任务后会记录评分和执行信号。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-skill-usage"
              >
                <div class="subpanel-head">
                  <h4>技能统计</h4>
                  <p>{{ selfEvolutionSkillUsage.length }} 项</p>
                </div>
                <div
                  v-if="selfEvolutionSkillUsage.length"
                  class="issue-list"
                >
                  <article
                    v-for="item in selfEvolutionSkillUsage.slice(0, 8)"
                    :key="item.skill_id"
                    class="issue-card"
                  >
                    <strong>{{ item.skill_id }}</strong>
                    <p>{{ item.state || 'active' }} · 使用 {{ item.use_count || 0 }} 次 · 修改 {{ item.patch_count || 0 }} 次</p>
                    <p v-if="item.last_used_at">最近使用：{{ item.last_used_at }}</p>
                    <div class="action-row">
                      <button
                        :disabled="skillVersionState.isLoading && skillVersionState.selectedSkillId === item.skill_id"
                        class="secondary-button small-button"
                        data-testid="self-evolution-skill-versions-button"
                        type="button"
                        @click="loadSkillVersionsForUsage(item.skill_id)"
                      >
                        版本记录
                      </button>
                      <button
                        :disabled="skillVersionState.actionId === `promote-${item.skill_id}`"
                        class="secondary-button small-button"
                        data-testid="self-evolution-skill-promote-button"
                        type="button"
                        @click="promoteSelfEvolutionSkill(item.skill_id)"
                      >
                        提升为全局
                      </button>
                    </div>
                  </article>
                </div>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  还没有技能使用记录。
                </p>
              </section>

              <section
                class="result-section"
                data-testid="self-evolution-skill-versions"
              >
                <div class="subpanel-head">
                  <h4>技能版本</h4>
                  <p>{{ skillVersionState.selectedSkillId || '未选择技能' }}</p>
                </div>
                <p
                  v-if="skillVersionState.isLoading"
                  class="empty-result-copy"
                >
                  正在读取版本记录。
                </p>
                <template v-else-if="skillVersionState.data">
                  <article class="issue-card">
                    <strong>{{ skillVersionState.data.skill_name || skillVersionState.data.skill_id }}</strong>
                    <p>{{ skillVersionState.data.current_path }}</p>
                    <div class="action-row">
                      <button
                        :disabled="skillPackageState.isExporting"
                        class="secondary-button small-button"
                        data-testid="self-evolution-skill-package-export-button"
                        type="button"
                        @click="exportSelfEvolutionSkillPackage(skillVersionState.data.skill_id)"
                      >
                        导出技能包
                      </button>
                    </div>
                  </article>
                  <article class="issue-card">
                    <div class="subpanel-head">
                      <div>
                        <strong>技能包迁移</strong>
                        <p>导出后可复制到其他环境；粘贴技能包 JSON 后可以导入。</p>
                      </div>
                    </div>
                    <label class="form-field">
                      <span>技能包 JSON</span>
                      <textarea
                        v-model="skillPackageState.text"
                        rows="6"
                        placeholder="这里显示导出的技能包，也可以粘贴其他环境导出的技能包。"
                      />
                    </label>
                    <label class="form-field compact-field">
                      <span>导入策略</span>
                      <select v-model="skillPackageState.strategy">
                        <option value="create_copy">创建副本</option>
                        <option value="overwrite">覆盖同 ID 用户技能</option>
                      </select>
                    </label>
                    <div class="action-row">
                      <button
                        :disabled="skillPackageState.isImporting"
                        class="secondary-button small-button"
                        data-testid="self-evolution-skill-package-import-button"
                        type="button"
                        @click="importSelfEvolutionSkillPackage"
                      >
                        导入技能包
                      </button>
                    </div>
                  </article>
                  <div
                    v-if="skillVersionState.data.items?.length"
                    class="issue-list"
                  >
                    <article
                      v-for="version in skillVersionState.data.items.slice(0, 8)"
                      :key="version.id"
                      class="issue-card"
                    >
                      <div class="candidate-title-row">
                        <strong>{{ version.created_at || version.id }}</strong>
                        <span class="skill-tag">{{ version.reason || 'snapshot' }}</span>
                      </div>
                      <p>{{ version.id }} · {{ version.size || 0 }} 字符</p>
                      <div
                        v-if="version.version_markdown || version.current_markdown"
                        class="diff-columns"
                      >
                        <div>
                          <strong>历史版本</strong>
                          <pre class="mini-pre diff-pre">{{ version.version_markdown }}</pre>
                        </div>
                        <div>
                          <strong>当前版本</strong>
                          <pre class="mini-pre diff-pre">{{ version.current_markdown }}</pre>
                        </div>
                      </div>
                      <pre
                        v-if="version.diff_from_current"
                        class="mini-pre diff-pre"
                      >{{ version.diff_from_current }}</pre>
                      <div class="action-row">
                        <button
                          :disabled="skillVersionState.actionId === version.id"
                          class="secondary-button small-button"
                          data-testid="self-evolution-skill-rollback-button"
                          type="button"
                          @click="rollbackSelfEvolutionSkillVersion(version.id)"
                        >
                          回滚到此版本
                        </button>
                      </div>
                    </article>
                  </div>
                  <p
                    v-else
                    class="empty-result-copy"
                  >
                    这个技能还没有历史版本。
                  </p>
                </template>
                <p
                  v-else
                  class="empty-result-copy"
                >
                  在技能统计里选择“版本记录”后，这里会显示差异和回滚操作。
                </p>
              </section>
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

    <div
      v-if="chapterPromptPreviewState.open"
      class="modal-overlay"
      @click.self="resetChapterPromptPreviewState"
    >
      <section
        class="modal-dialog prompt-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="确认章节提示词"
      >
        <header class="prompt-preview-dialog-head">
          <div>
            <p class="stage-kicker">章节提示词</p>
            <h3>{{ chapterPromptPreviewState.title }}</h3>
          </div>
          <button
            class="secondary-button small-button"
            type="button"
            @click="resetChapterPromptPreviewState"
          >
            关闭
          </button>
        </header>

        <p class="empty-result-copy">
          确认后会使用这里编辑后的内容生成正文。
        </p>
        <p
          v-if="chapterPromptPreviewState.error"
          class="prompt-preview-error"
        >
          {{ chapterPromptPreviewState.error }}
        </p>
        <p
          v-else-if="chapterPromptPreviewState.message"
          class="prompt-preview-message"
        >
          {{ chapterPromptPreviewState.message }}
        </p>

        <div class="prompt-preview-list">
          <article
            v-for="item in chapterPromptPreviewState.items"
            :key="item.key"
            class="prompt-preview-item"
          >
            <div class="prompt-preview-item-head">
              <strong>{{ item.title }}</strong>
              <button
                class="secondary-button small-button"
                type="button"
                @click="copyChapterPromptPreview(item)"
              >
                复制提示词
              </button>
            </div>
            <textarea
              v-model="item.editablePrompt"
              class="prompt-preview-editor"
              rows="14"
            />
          </article>
        </div>

        <div class="action-row prompt-preview-actions">
          <button
            class="secondary-button"
            type="button"
            @click="resetChapterPromptPreviewState"
          >
            取消
          </button>
          <button
            :disabled="isToolRunning || chapterPromptPreviewState.items.length === 0"
            class="primary-button"
            type="button"
            @click="handleConfirmChapterPromptPreview"
          >
            {{ isToolRunning ? '执行中…' : chapterPromptPreviewState.confirmLabel }}
          </button>
        </div>
      </section>
    </div>
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

.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(31, 35, 40, 0.38);
}

.modal-dialog {
  width: min(920px, 100%);
  max-height: min(86vh, 820px);
  overflow: auto;
  border: 1px solid #d0d7de;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 24px 60px rgba(31, 35, 40, 0.24);
}

.prompt-preview-dialog {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.prompt-preview-dialog-head,
.prompt-preview-item-head,
.prompt-preview-actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.stage-kicker {
  margin: 0 0 4px;
  color: #6e7781;
  font-size: 12px;
  font-weight: 700;
}

.prompt-preview-dialog h3 {
  margin: 0;
  font-size: 18px;
}

.prompt-preview-list {
  display: grid;
  gap: 14px;
}

.prompt-preview-item {
  display: grid;
  gap: 8px;
}

.prompt-preview-editor {
  min-height: 300px;
  max-height: 520px;
  resize: vertical;
  font-family: 'SFMono-Regular', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.7;
}

.prompt-preview-message,
.prompt-preview-error {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
}

.prompt-preview-message {
  color: #57606a;
}

.prompt-preview-error {
  color: #b42318;
}

.chapter-segment-panel {
  border: 1px solid #dfe6ec;
  border-radius: 14px;
  padding: 14px;
  background: #fbfcfe;
}

.segment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.segment-pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  border: 1px solid #d0d7de;
  border-radius: 999px;
  padding: 4px 9px;
  background: #ffffff;
  color: #57606a;
  font-size: 12px;
  line-height: 1.5;
}

.segment-pill-active {
  border-color: #9ec5fe;
  background: #e8f0fe;
  color: #1d4ed8;
}

.segment-pill-accepted {
  border-color: #b7dfc1;
  background: #f4fbf5;
  color: #2b6940;
}

.segment-pill-draft {
  border-color: #f1d18a;
  background: #fff8e6;
  color: #8a5a00;
}

.segment-prompt-editor {
  min-height: 220px;
}

.segment-draft-editor {
  min-height: 360px;
  font-family: 'SFMono-Regular', ui-monospace, monospace;
  line-height: 1.7;
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

.two-column-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.inline-toggle-group,
.button-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.advanced-settings {
  border: 1px solid #d8dee4;
  border-radius: 12px;
  padding: 0;
  background: #f6f8fa;
}

.advanced-settings summary {
  cursor: pointer;
  padding: 11px 13px;
  color: #475467;
  font-size: 13px;
  line-height: 1.5;
}

.advanced-settings-body {
  display: grid;
  gap: 12px;
  padding: 0 13px 13px;
}

.toggle-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #24292f;
  font-size: 13px;
  line-height: 1.5;
}

.toggle-row input {
  width: auto;
  min-width: 16px;
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

.detail-pills,
.overview-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.self-evolution-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  display: grid;
  gap: 4px;
  padding: 12px;
  border-radius: 12px;
  background: #f6f8fa;
  border: 1px solid #e2e8ee;
}

.metric-card span {
  color: #57606a;
  font-size: 12px;
}

.metric-card strong {
  color: #1f2328;
  font-size: 18px;
}

.self-evolution-metric {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f6f8fa;
}

.self-evolution-metric strong {
  color: #1f2328;
  font-size: 18px;
}

.self-evolution-metric span {
  color: #57606a;
  font-size: 12px;
}

.trend-bar {
  height: 8px;
  border-radius: 999px;
  background: #eef2f5;
  overflow: hidden;
}

.trend-bar span {
  display: block;
  height: 100%;
  min-width: 3px;
  border-radius: inherit;
  background: #1d4ed8;
}

.trend-row {
  min-height: 88px;
  display: flex;
  align-items: end;
  gap: 6px;
  padding: 8px 0 2px;
}

.trend-row span {
  width: 14px;
  min-height: 4px;
  border-radius: 5px 5px 2px 2px;
  background: #1d4ed8;
}

.diff-preview {
  display: grid;
  gap: 8px;
  border: 1px solid #dfe6ec;
  border-radius: 12px;
  padding: 10px 12px;
  background: #f8fafc;
}

.diff-preview strong {
  color: #1f2328;
  font-size: 13px;
}

.diff-warning-list {
  color: #8a5a00;
}

.diff-pre {
  max-height: 260px;
}

.diff-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.diff-columns > div {
  display: grid;
  gap: 8px;
}

.diff-columns strong {
  color: #1f2328;
  font-size: 13px;
}

.candidate-title-row {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 10px;
}

.obsidian-task-constraints {
  display: grid;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #dfe6ec;
}

.obsidian-task-constraints strong {
  font-size: 13px;
  color: #1f2328;
}

.obsidian-task-constraints p {
  margin: 0;
  color: #4f5b66;
  font-size: 12px;
  line-height: 1.6;
}

.result-section {
  display: grid;
  gap: 12px;
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

  .diff-columns {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 980px) {
  .workbench-grid,
  .two-column-grid,
  .two-column-fields,
  .metric-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
