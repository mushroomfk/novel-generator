<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import {
  importProjectKnowledge,
  importProjectKnowledgeFiles,
  runProjectDream,
  searchProjectKnowledge,
  updateProjectMemory,
  updateStoryDocument,
} from '../lib/api.js';
import { buildImportedFilePayloads, importAcceptValue } from '../lib/importFiles.js';

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  project: {
    type: Object,
    default: null,
  },
  selectedChapterId: {
    type: String,
    default: '',
  },
});

const emit = defineEmits(['close', 'project-detail-updated']);

const activeTab = ref('characters');
const activeCharacterName = ref('');
const activeEntitySectionId = ref('');
const overviewPanel = ref(null);
const draftDocuments = ref({});
const saveMessage = ref('');
const knowledgeMessage = ref('');
const knowledgeImportMessage = ref('');
const knowledgeQuery = ref('');
const knowledgeResults = ref([]);
const knowledgeTitle = ref('');
const knowledgeContent = ref('');
const knowledgeFiles = ref([]);
const knowledgeFileInput = ref(null);
const documentSavingState = ref({});
const isKnowledgeSearching = ref(false);
const isKnowledgeImporting = ref(false);
const memoryDraftEntries = ref([]);
const memorySaveMessage = ref('');
const isMemorySaving = ref(false);
const dreamFocus = ref('');
const dreamMessage = ref('');
const isDreamRunning = ref(false);

const emptyOverview = Object.freeze({
  documents: [],
  materials: [],
  obsidian: null,
  memory_entries: [],
  dream_report: null,
  model_overview: {
    status: 'not_generated',
    message: '',
    generated_at: '',
    failed_at: '',
    error: '',
  },
  chapter_reviews: [],
  characters: [],
  events: [],
  locations: [],
  props: [],
  skills: [],
  scenes: [],
  organizations: [],
});

const overview = computed(() => props.project?.story_overview ?? emptyOverview);
const modelOverviewStatus = computed(() => overview.value.model_overview ?? emptyOverview.model_overview);
const modelOverviewStatusLabel = computed(() => {
  const status = modelOverviewStatus.value.status ?? 'not_generated';
  if (status === 'ready') {
    return '模型总览已生成';
  }
  if (status === 'failed') {
    return '模型总览生成失败';
  }
  if (status === 'disabled') {
    return '模型总览未配置';
  }
  if (status === 'stale') {
    return '模型总览已过期';
  }
  return '模型总览未生成';
});
const modelOverviewMessage = computed(() => {
  const status = modelOverviewStatus.value;
  return status.message || status.error || '';
});
const modelOverviewIssueText = computed(() => {
  const status = modelOverviewStatus.value.status ?? 'not_generated';
  if (status === 'ready') {
    return '';
  }
  return modelOverviewMessage.value || modelOverviewStatusLabel.value;
});
const selectedChapter = computed(() => {
  if (!props.selectedChapterId) {
    return null;
  }
  return (props.project?.chapters ?? []).find((item) => item.id === props.selectedChapterId) ?? null;
});
const characters = computed(() => overview.value.characters ?? []);
const documents = computed(() => overview.value.documents ?? []);
const materials = computed(() => overview.value.materials ?? []);
const obsidian = computed(() => overview.value.obsidian ?? null);
const obsidianNotes = computed(() => obsidian.value?.notes ?? []);
const skills = computed(() => overview.value.skills ?? []);
const chapterReviews = computed(() => (
  [...(overview.value.chapter_reviews ?? [])].sort((left, right) => (
    Number(left.chapter_index ?? 0) - Number(right.chapter_index ?? 0)
  ))
));
const memoryEntries = computed(() => overview.value.memory_entries ?? []);
const dreamReport = computed(() => overview.value.dream_report ?? null);
const manualMemoryEntries = computed(() => (
  memoryEntries.value.filter((item) => (item.source ?? 'manual') !== 'auto')
));
const autoMemoryEntries = computed(() => (
  memoryEntries.value.filter((item) => item.source === 'auto')
));
const activeCharacter = computed(() => (
  characters.value.find((item) => item.name === activeCharacterName.value)
  ?? characters.value[0]
  ?? null
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

function obsidianSourceChapterText(item) {
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

function obsidianExternalReferences(item) {
  const references = Array.isArray(item?.external_references) ? item.external_references : [];
  if (references.length) {
    return {
      label: '考据来源',
      values: references.slice(0, 3),
    };
  }
  const links = Array.isArray(item?.external_links) ? item.external_links : [];
  return {
    label: '考据链接',
    values: links.slice(0, 3),
  };
}

const filledDocumentCount = computed(() => (
  overview.value.documents.filter((item) => item.content?.trim()).length
));

const totalTimelineEntries = computed(() => (
  characters.value.reduce((sum, item) => sum + (item.timeline?.length ?? 0), 0)
));

const coreSummaryCards = computed(() => ([
  {
    label: '人物',
    value: `${characters.value.length} 个`,
    targetTab: 'characters',
    targetKey: 'characters',
    note: characters.value.length > 0
      ? '当前项目里已经识别的人物节点'
      : '还没有提取到明确人物',
  },
  {
    label: '事件',
    value: `${overview.value.events.length} 个`,
    targetTab: 'entities',
    targetKey: 'events',
    note: overview.value.events.length > 0
      ? '按章节汇总推进动作和关键节点'
      : '还没有抽取出稳定事件',
  },
  {
    label: '地点',
    value: `${overview.value.locations.length} 个`,
    targetTab: 'entities',
    targetKey: 'locations',
    note: overview.value.locations.length > 0
      ? '人物活动范围和关键位置会挂在这里'
      : '还没有地点线索',
  },
  {
    label: '道具',
    value: `${overview.value.props.length} 个`,
    targetTab: 'entities',
    targetKey: 'props',
    note: overview.value.props.length > 0
      ? '和剧情推进有关的物件会持续累积'
      : '还没有道具线索',
  },
  {
    label: '技能',
    value: `${skills.value.length} 个`,
    targetTab: 'entities',
    targetKey: 'skills',
    note: skills.value.length > 0
      ? '人物的能力、擅长和本领会集中挂在这里'
      : '还没有稳定的人物技能',
  },
  {
    label: '组织/势力',
    value: `${overview.value.organizations.length} 个`,
    targetTab: 'entities',
    targetKey: 'organizations',
    note: overview.value.organizations.length > 0
      ? '人物归属、对立阵营和资源来源会挂在这里'
      : '还没有稳定的组织线索',
  },
  {
    label: '时间线',
    value: `${totalTimelineEntries.value} 条`,
    targetTab: 'characters',
    targetKey: 'timeline',
    note: totalTimelineEntries.value > 0
      ? '把人物推进挂到章节顺序上'
      : '还没有可读时间线',
  },
]));

const supportSummaryCards = computed(() => ([
  {
    label: '章节覆盖',
    compactLabel: '章节',
    value: `${props.project?.chapters?.filter((item) => item.exists)?.length ?? 0}/${props.project?.target_chapters ?? 0}`,
  },
  {
    label: '架构文件',
    compactLabel: '文件',
    value: `${filledDocumentCount.value}/${overview.value.documents.length}`,
  },
  {
    label: '资料库',
    compactLabel: '资料',
    value: `${materials.value.length} 份`,
  },
  {
    label: 'Obsidian',
    compactLabel: 'Obsidian',
    value: `${obsidian.value?.included_count ?? 0} 份`,
  },
  {
    label: '项目记忆',
    compactLabel: '记忆',
    value: `${memoryEntries.value.length} 条`,
  },
  {
    label: '章节核验',
    compactLabel: '核验',
    value: `${chapterReviews.value.length} 章`,
  },
]));

const entitySections = computed(() => ([
  {
    id: 'events',
    label: '事件',
    items: overview.value.events,
  },
  {
    id: 'locations',
    label: '地点',
    items: overview.value.locations,
  },
  {
    id: 'props',
    label: '道具',
    items: overview.value.props,
  },
  {
    id: 'skills',
    label: '技能',
    items: skills.value,
  },
  {
    id: 'organizations',
    label: '组织/势力',
    items: overview.value.organizations,
  },
  {
    id: 'scenes',
    label: '场景',
    items: overview.value.scenes,
  },
]));

const entityLookupByKind = computed(() => ({
  events: Object.fromEntries((overview.value.events ?? []).map((item) => [item.name, item])),
  locations: Object.fromEntries((overview.value.locations ?? []).map((item) => [item.name, item])),
  props: Object.fromEntries((overview.value.props ?? []).map((item) => [item.name, item])),
  skills: Object.fromEntries(skills.value.map((item) => [item.name, item])),
  scenes: Object.fromEntries((overview.value.scenes ?? []).map((item) => [item.name, item])),
  organizations: Object.fromEntries((overview.value.organizations ?? []).map((item) => [item.name, item])),
}));

const currentFocusTimelineEntry = computed(() => {
  const current = activeCharacter.value;
  if (!current || current.timeline.length === 0) {
    return null;
  }

  return current.timeline.find((item) => isCurrentChapter(item))
    ?? current.timeline[current.timeline.length - 1]
    ?? null;
});

const connectedCharacters = computed(() => {
  const current = activeCharacter.value;
  if (!current) {
    return [];
  }

  return characters.value
    .filter((item) => item.name !== current.name)
    .map((item) => {
      const sharedEvents = intersectNames(item.events, current.events);
      const sharedLocations = intersectNames(item.locations, current.locations);
      const sharedProps = intersectNames(item.props, current.props);
      const sharedSkills = intersectNames(item.skills ?? [], current.skills ?? []);
      const sharedOrganizations = intersectNames(item.organizations, current.organizations);
      const directRelations = orderedUniqueStrings([
        ...(current.relationships ?? []).filter((text) => text.includes(item.name)),
        ...(item.relationships ?? []).filter((text) => text.includes(current.name)),
      ]);
      const highlights = [
        ...directRelations.map((text) => `关系 · ${text}`),
        ...sharedEvents.slice(0, 2).map((name) => `共同事件 · ${name}`),
        ...sharedLocations.slice(0, 1).map((name) => `共同地点 · ${name}`),
        ...sharedProps.slice(0, 1).map((name) => `共同道具 · ${name}`),
        ...sharedSkills.slice(0, 1).map((name) => `共同技能 · ${name}`),
        ...sharedOrganizations.slice(0, 1).map((name) => `共同势力 · ${name}`),
      ].slice(0, 6);
      const score = (directRelations.length * 5)
        + (sharedEvents.length * 4)
        + (sharedLocations.length * 2)
        + sharedProps.length
        + sharedSkills.length
        + (sharedOrganizations.length * 2);

      return {
        name: item.name,
        summary: directRelations[0] || item.current_state || item.profile || '暂无更具体说明。',
        highlights,
        score,
      };
    })
    .filter((item) => item.score > 0)
    .sort((left, right) => (
      right.score - left.score
      || left.name.localeCompare(right.name, 'zh-CN')
    ));
});

const characterFocusMetrics = computed(() => {
  const current = activeCharacter.value;
  if (!current) {
    return [];
  }

  return [
    { label: '关联人物', value: `${connectedCharacters.value.length} 个` },
    { label: '事件', value: `${current.events.length} 个` },
    { label: '地点', value: `${current.locations.length} 个` },
    { label: '道具', value: `${current.props.length} 个` },
    { label: '技能', value: `${current.skills?.length ?? 0} 个` },
    { label: '组织/势力', value: `${current.organizations.length} 个` },
    { label: '时间线', value: `${current.timeline.length} 条` },
  ];
});

const characterRelationSections = computed(() => {
  const current = activeCharacter.value;
  if (!current) {
    return [];
  }

  return [
    {
      id: 'events',
      label: '事件',
      note: '人物当前卷入了哪些推进动作',
      items: buildEntityRelationCards('events', current.events, current.name),
      empty: '还没有抽到稳定事件。',
    },
    {
      id: 'locations',
      label: '地点',
      note: '人物活动范围和驻留位置',
      items: buildEntityRelationCards('locations', current.locations, current.name),
      empty: '还没有地点线索。',
    },
    {
      id: 'props',
      label: '道具',
      note: '和人物推进直接相关的物件',
      items: buildEntityRelationCards('props', current.props, current.name),
      empty: '还没有道具线索。',
    },
    {
      id: 'skills',
      label: '技能',
      note: '人物明确展露出来的能力、本领和擅长',
      items: buildEntityRelationCards('skills', current.skills ?? [], current.name),
      empty: '还没有抽出稳定技能。',
    },
    {
      id: 'organizations',
      label: '组织/势力',
      note: '人物站在哪些阵营、机构或势力网络里',
      items: buildEntityRelationCards('organizations', current.organizations ?? [], current.name),
      empty: '还没有稳定的组织线索。',
    },
  ];
});

watch(
  [() => props.open, characters],
  ([open, nextCharacters]) => {
    if (!open) {
      activeTab.value = 'characters';
      return;
    }

    const hasActiveCharacter = nextCharacters.some((item) => item.name === activeCharacterName.value);
    if (!hasActiveCharacter) {
      activeCharacterName.value = nextCharacters[0]?.name ?? '';
    }
  },
  { immediate: true, deep: true },
);

watch(
  documents,
  (nextDocuments) => {
    draftDocuments.value = Object.fromEntries(
      nextDocuments.map((item) => [item.key, item.content ?? '']),
    );
  },
  { immediate: true, deep: true },
);

watch(
  manualMemoryEntries,
  (nextEntries) => {
    memoryDraftEntries.value = nextEntries.map((item) => ({
      id: item.id,
      title: item.title ?? '',
      category: item.category ?? '硬规则',
      content: item.content ?? '',
      updated_at: item.updated_at ?? '',
    }));
  },
  { immediate: true, deep: true },
);

function formatDateTime(value) {
  if (!value) {
    return '未写入';
  }

  return new Date(value).toLocaleString('zh-CN');
}

function formatConfidence(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '0%';
  }
  return `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%`;
}

function chapterReviewStatusLabel(status) {
  return {
    good: '通过',
    watch: '需关注',
    risk: '高风险',
    na: '未评估',
  }[status] || status || '未评估';
}

function chapterReviewIssueLevelLabel(level) {
  return {
    critical: '严重',
    warning: '提醒',
    info: '提示',
  }[level] || level || '提示';
}

function chapterReviewIssueCount(review) {
  return (review.dimensions ?? []).reduce((sum, item) => sum + (item.issues?.length ?? 0), 0);
}

function formatTimelineLabel(entry) {
  if (entry.chapter_index) {
    return `第 ${entry.chapter_index} 章 · ${entry.chapter_title || '未命名章节'}`;
  }

  return entry.source_label || '设定';
}

function formatChapterIndexes(indexes) {
  if (!indexes || indexes.length === 0) {
    return '未关联章节';
  }

  return indexes.map((item) => `第 ${item} 章`).join(' · ');
}

function orderedUniqueStrings(items) {
  return [...new Set((items ?? []).filter(Boolean))];
}

function intersectNames(left, right) {
  const rightSet = new Set(right ?? []);
  return orderedUniqueStrings((left ?? []).filter((item) => rightSet.has(item)));
}

function buildEntityRelationCards(kind, names, activeName = '') {
  const lookup = entityLookupByKind.value[kind] ?? {};
  return orderedUniqueStrings(names)
    .map((name) => {
      const detail = lookup[name];
      return {
        name,
        summary: detail?.summary || '暂无补充说明。',
        chapter_indexes: detail?.chapter_indexes ?? [],
        related_characters: orderedUniqueStrings(
          (detail?.related_characters ?? []).filter((item) => item !== activeName),
        ),
      };
    })
    .sort((left, right) => (
      (right.chapter_indexes.length + right.related_characters.length)
      - (left.chapter_indexes.length + left.related_characters.length)
      || left.name.localeCompare(right.name, 'zh-CN')
    ));
}

function isCurrentChapter(entry) {
  return Boolean(props.selectedChapterId && entry.chapter_id === props.selectedChapterId);
}

function openCharacter(name) {
  activeCharacterName.value = name;
}

async function openSummaryTarget(item) {
  activeTab.value = item.targetTab;
  activeEntitySectionId.value = item.targetTab === 'entities' ? item.targetKey : '';
  await nextTick();
  const target = overviewPanel.value?.querySelector(`[data-overview-target="${item.targetKey}"]`);
  target?.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

const memoryCategoryOptions = ['硬规则', '偏好', '连续性', '警告', '目标'];

function addMemoryEntry() {
  memoryDraftEntries.value = [
    ...memoryDraftEntries.value,
    {
      id: '',
      title: '',
      category: '硬规则',
      content: '',
      updated_at: '',
    },
  ];
}

function removeMemoryEntry(index) {
  memoryDraftEntries.value = memoryDraftEntries.value.filter((_item, currentIndex) => currentIndex !== index);
}

function updateMemoryEntry(index, key, value) {
  memoryDraftEntries.value = memoryDraftEntries.value.map((item, currentIndex) => (
    currentIndex === index ? { ...item, [key]: value } : item
  ));
}

function normalizedMemoryDraftEntries() {
  return memoryDraftEntries.value
    .map((item) => ({
      id: item.id?.trim() || '',
      title: item.title?.trim() || '',
      category: memoryCategoryOptions.includes(item.category) ? item.category : '硬规则',
      content: item.content?.trim() || '',
    }))
    .filter((item) => item.content.length > 0);
}

function normalizedMemorySourceEntries() {
  return manualMemoryEntries.value.map((item) => ({
    id: item.id,
    title: item.title ?? '',
    category: item.category ?? '硬规则',
    content: item.content ?? '',
  }));
}

const memoryHasChanges = computed(() => (
  JSON.stringify(normalizedMemoryDraftEntries()) !== JSON.stringify(normalizedMemorySourceEntries())
));

async function saveMemoryEntries() {
  if (!props.project?.id) {
    return;
  }

  isMemorySaving.value = true;
  memorySaveMessage.value = '';

  try {
    const detail = await updateProjectMemory(props.project.id, {
      entries: normalizedMemoryDraftEntries(),
    });
    emit('project-detail-updated', detail);
    memorySaveMessage.value = '项目记忆已保存';
  } catch (error) {
    memorySaveMessage.value = error instanceof Error ? error.message : '项目记忆保存失败';
  } finally {
    isMemorySaving.value = false;
  }
}

async function runDreaming() {
  if (!props.project?.id) {
    return;
  }

  isDreamRunning.value = true;
  dreamMessage.value = '';

  try {
    const detail = await runProjectDream(props.project.id, {
      focus: dreamFocus.value.trim(),
    });
    emit('project-detail-updated', detail);
    dreamMessage.value = '梦境整理已更新';
  } catch (error) {
    dreamMessage.value = error instanceof Error ? error.message : '梦境整理失败';
  } finally {
    isDreamRunning.value = false;
  }
}

function emptyDocumentTip(label) {
  return `${label} 还没有内容，当前面板先用章节正文做回填。`;
}

function documentDraft(documentKey) {
  return draftDocuments.value[documentKey] ?? '';
}

function setDocumentDraft(documentKey, value) {
  draftDocuments.value = {
    ...draftDocuments.value,
    [documentKey]: value,
  };
}

function isDocumentSaving(documentKey) {
  return Boolean(documentSavingState.value[documentKey]);
}

function hasDocumentChanges(item) {
  return documentDraft(item.key) !== (item.content ?? '');
}

async function saveDocument(item) {
  if (!props.project?.id) {
    return;
  }

  documentSavingState.value = {
    ...documentSavingState.value,
    [item.key]: true,
  };
  saveMessage.value = '';

  try {
    const detail = await updateStoryDocument(props.project.id, item.key, {
      content: documentDraft(item.key),
    });
    emit('project-detail-updated', detail);
    saveMessage.value = `${item.label} 已保存`;
  } catch (error) {
    saveMessage.value =
      error instanceof Error ? error.message : `${item.label} 保存失败`;
  } finally {
    documentSavingState.value = {
      ...documentSavingState.value,
      [item.key]: false,
    };
  }
}

async function runKnowledgeSearch() {
  if (!props.project?.id) {
    return;
  }

  if (!knowledgeQuery.value.trim()) {
    knowledgeMessage.value = '先输入要检索的内容';
    knowledgeResults.value = [];
    return;
  }

  isKnowledgeSearching.value = true;
  knowledgeMessage.value = '';

  try {
    knowledgeResults.value = await searchProjectKnowledge(
      props.project.id,
      knowledgeQuery.value.trim(),
      8,
      { chapterIndex: selectedChapter.value?.index ?? 0 },
    );
    if (knowledgeResults.value.length === 0) {
      knowledgeMessage.value = '没有找到相关内容';
    }
  } catch (error) {
    knowledgeResults.value = [];
    knowledgeMessage.value =
      error instanceof Error ? error.message : '知识检索失败';
  } finally {
    isKnowledgeSearching.value = false;
  }
}

function handleKnowledgeFilesChange(event) {
  knowledgeFiles.value = Array.from(event.target.files ?? []);
}

async function buildKnowledgeImportItems() {
  const items = [];
  const manualContent = knowledgeContent.value.trim();
  if (manualContent) {
    items.push({
      title: knowledgeTitle.value.trim() || '手动资料',
      content: manualContent,
    });
  }

  return items;
}

async function buildKnowledgeImportFiles() {
  return buildImportedFilePayloads(knowledgeFiles.value);
}

async function importKnowledge() {
  if (!props.project?.id) {
    return;
  }

  knowledgeImportMessage.value = '';
  isKnowledgeImporting.value = true;

  try {
    const items = await buildKnowledgeImportItems();
    const files = await buildKnowledgeImportFiles();
    if (items.length === 0 && files.length === 0) {
      knowledgeImportMessage.value = '先填一段资料，或者选一个支持的文件';
      return;
    }

    let detail = null;
    if (items.length > 0) {
      detail = await importProjectKnowledge(props.project.id, { items });
    }
    if (files.length > 0) {
      detail = await importProjectKnowledgeFiles(props.project.id, { files });
    }
    emit('project-detail-updated', detail);
    knowledgeTitle.value = '';
    knowledgeContent.value = '';
    knowledgeFiles.value = [];
    if (knowledgeFileInput.value) {
      knowledgeFileInput.value.value = '';
    }
    knowledgeImportMessage.value = `已导入 ${items.length + files.length} 份资料`;
  } catch (error) {
    knowledgeImportMessage.value =
      error instanceof Error ? error.message : '资料导入失败';
  } finally {
    isKnowledgeImporting.value = false;
  }
}
</script>

<template>
  <section
    ref="overviewPanel"
    class="story-overview-panel"
    data-testid="story-overview-modal"
    role="dialog"
    aria-modal="true"
    aria-label="架构总览"
  >
    <header class="overview-header">
      <div class="overview-header-main">
        <div class="overview-title-line">
          <p class="overview-kicker">Story Overview</p>
          <h3>{{ project?.name ?? '当前小说' }} · 架构总览</h3>
        </div>
        <p class="overview-copy">人物中心 · 事件 · 地点 · 道具 · 技能 · 组织/势力 · 时间线</p>
        <div class="overview-support-inline">
          <span
            v-for="item in supportSummaryCards"
            :key="item.label"
            class="support-inline-item"
            :title="item.label"
          >
            {{ item.compactLabel }}
            <strong>{{ item.value }}</strong>
          </span>
        </div>
      </div>

      <div
        v-if="modelOverviewIssueText"
        :class="[
          'overview-model-status',
          modelOverviewStatus.status === 'failed' ? 'overview-model-status-error' : '',
        ]"
      >
        <strong>{{ modelOverviewStatusLabel }}</strong>
        <span>{{ modelOverviewIssueText }}</span>
      </div>

      <button
        class="overview-close"
        type="button"
        @click="emit('close')"
      >
        关闭
      </button>
    </header>

    <section class="overview-summary-shell">
      <div
        class="overview-summary overview-summary-core"
        data-testid="story-overview-core-summary"
      >
        <button
          v-for="item in coreSummaryCards"
          :key="item.label"
          class="summary-card"
          :title="item.note"
          :aria-label="`查看${item.label}`"
          type="button"
          @click="openSummaryTarget(item)"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>
      <nav class="overview-tabs">
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'characters' }]"
          type="button"
          @click="activeTab = 'characters'"
        >
          关系总览
        </button>
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'entities' }]"
          type="button"
          @click="activeTab = 'entities'"
        >
          世界要素
        </button>
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'documents' }]"
          type="button"
          @click="activeTab = 'documents'"
        >
          架构原文
        </button>
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'memory' }]"
          type="button"
          @click="activeTab = 'memory'"
        >
          项目记忆
        </button>
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'reviews' }]"
          type="button"
          @click="activeTab = 'reviews'"
        >
          章节核验
        </button>
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'dream' }]"
          type="button"
          @click="activeTab = 'dream'"
        >
          梦境整理
        </button>
        <button
          :class="['overview-tab', { 'overview-tab-active': activeTab === 'knowledge' }]"
          type="button"
          @click="activeTab = 'knowledge'"
        >
          知识检索
        </button>
      </nav>
    </section>

    <div
      v-if="activeTab === 'characters'"
      class="overview-body overview-body-characters"
      data-testid="story-overview-character-map"
    >
      <aside
        class="character-index"
        data-overview-target="characters"
      >
        <button
          v-for="item in characters"
          :key="item.name"
          :class="['character-index-item', { 'character-index-item-active': item.name === activeCharacter?.name }]"
          type="button"
          @click="openCharacter(item.name)"
        >
          <div class="character-index-top">
            <strong>{{ item.name }}</strong>
            <span>{{ item.timeline.length }}</span>
          </div>
          <p>{{ item.current_state || item.profile || '还没有更明确的状态描述。' }}</p>
        </button>

        <div
          v-if="characters.length === 0"
          class="empty-card"
        >
          {{ modelOverviewIssueText || '模型总览还没有生成，生成完成后这里会显示人物关系。' }}
        </div>
      </aside>

      <section
        v-if="activeCharacter"
        class="character-stage"
      >
        <article class="relationship-hero">
          <div class="relationship-hero-main">
            <p class="overview-kicker">关系总览</p>
            <div class="relationship-hero-head">
              <h4>{{ activeCharacter.name }}</h4>
              <span class="character-count">
                {{
                  currentFocusTimelineEntry
                    ? `当前聚焦 · ${formatTimelineLabel(currentFocusTimelineEntry)}`
                    : `时间线 ${activeCharacter.timeline.length} 条`
                }}
              </span>
            </div>
            <p class="relationship-copy">
              {{ activeCharacter.current_state || activeCharacter.profile || '还没有单独维护的人物状态，当前先按章节内容推断。' }}
            </p>
            <p
              v-if="activeCharacter.profile && activeCharacter.profile !== activeCharacter.current_state"
              class="relationship-profile"
            >
              设定：{{ activeCharacter.profile }}
            </p>
          </div>

          <div class="relationship-metrics">
            <article
              v-for="item in characterFocusMetrics"
              :key="item.label"
              class="relationship-metric"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
        </article>

        <section
          class="relationship-grid"
          data-testid="story-overview-relationship-grid"
        >
          <article class="relationship-panel relationship-panel-people">
            <div class="relationship-panel-head">
              <div>
                <span class="info-label">关联人物</span>
                <h5>{{ connectedCharacters.length }} 个直接相关角色</h5>
              </div>
              <span class="document-filename">先看人物之间的连线，再看外部节点</span>
            </div>

            <div
              v-if="connectedCharacters.length > 0"
              class="relationship-stack"
            >
              <article
                v-for="item in connectedCharacters"
                :key="item.name"
                class="relationship-node relationship-node-character"
              >
                <div class="relationship-node-head">
                  <strong>{{ item.name }}</strong>
                </div>
                <p>{{ item.summary }}</p>
                <div
                  v-if="item.highlights.length > 0"
                  class="chip-row"
                >
                  <span
                    v-for="tag in item.highlights"
                    :key="`${item.name}-${tag}`"
                    class="meta-chip meta-chip-accent"
                  >
                    {{ tag }}
                  </span>
                </div>
              </article>
            </div>

            <p
              v-else
              class="relationship-empty"
            >
              当前还看不出更明确的人物互动，先继续写章节或补人物设定。
            </p>
          </article>

          <article
            v-for="section in characterRelationSections"
            :key="section.id"
            class="relationship-panel"
            :data-testid="section.id === 'skills' ? 'story-overview-character-skills' : undefined"
          >
            <div class="relationship-panel-head">
              <div>
                <span class="info-label">{{ section.label }}</span>
                <h5>{{ section.items.length }} 个关联节点</h5>
              </div>
              <span class="document-filename">{{ section.note }}</span>
            </div>

            <div
              v-if="section.items.length > 0"
              class="relationship-stack"
            >
              <article
                v-for="item in section.items"
                :key="`${section.id}-${item.name}`"
                class="relationship-node"
              >
                <div class="relationship-node-head">
                  <strong>{{ item.name }}</strong>
                  <span>{{ formatChapterIndexes(item.chapter_indexes) }}</span>
                </div>
                <p>{{ item.summary }}</p>
                <div
                  v-if="item.related_characters.length > 0"
                  class="chip-row"
                >
                  <span
                    v-for="name in item.related_characters"
                    :key="`${section.id}-${item.name}-${name}`"
                    class="meta-chip"
                  >
                    人物 · {{ name }}
                  </span>
                </div>
              </article>
            </div>

            <p
              v-else
              class="relationship-empty"
            >
              {{ section.empty }}
            </p>
          </article>

        </section>

        <section
          class="timeline-shell"
          data-overview-target="timeline"
        >
          <div class="timeline-shell-head">
            <div>
              <p class="overview-kicker">时间线</p>
              <h5>{{ activeCharacter.timeline.length }} 条推进记录</h5>
            </div>
            <span class="document-filename">按章节顺序串联人物、事件、地点、道具、技能和组织/势力</span>
          </div>

          <ol
            class="timeline-list"
            data-testid="story-overview-timeline"
          >
            <li
              v-for="entry in activeCharacter.timeline"
              :key="entry.id"
              :class="['timeline-item', { 'timeline-item-current': isCurrentChapter(entry) }]"
            >
              <div class="timeline-line" />
              <article class="timeline-card">
                <div class="timeline-head">
                  <strong>{{ formatTimelineLabel(entry) }}</strong>
                  <span>{{ entry.source_label || '章节正文' }}</span>
                </div>
                <p>{{ entry.summary || '暂无摘要。' }}</p>
                <div class="chip-row">
                  <span
                    v-for="item in entry.relations"
                    :key="`relation-${entry.id}-${item}`"
                    class="meta-chip meta-chip-accent"
                  >
                    关系 · {{ item }}
                  </span>
                  <span
                    v-for="item in entry.events"
                    :key="`event-${entry.id}-${item}`"
                    class="meta-chip meta-chip-accent"
                  >
                    事件 · {{ item }}
                  </span>
                  <span
                    v-for="item in entry.locations"
                    :key="`location-${entry.id}-${item}`"
                    class="meta-chip"
                  >
                    地点 · {{ item }}
                  </span>
                  <span
                    v-for="item in entry.props"
                    :key="`prop-${entry.id}-${item}`"
                    class="meta-chip"
                  >
                    道具 · {{ item }}
                  </span>
                  <span
                    v-for="item in entry.skills"
                    :key="`skill-${entry.id}-${item}`"
                    class="meta-chip meta-chip-accent"
                  >
                    技能 · {{ item }}
                  </span>
                  <span
                    v-for="item in entry.organizations"
                    :key="`org-${entry.id}-${item}`"
                    class="meta-chip"
                  >
                    组织/势力 · {{ item }}
                  </span>
                </div>
              </article>
            </li>
          </ol>
        </section>
      </section>

      <section
        v-else
        class="empty-card"
      >
        暂时没有人物关系图和时间线。
      </section>
    </div>

    <div
      v-else-if="activeTab === 'entities'"
      class="overview-body overview-body-entities"
    >
      <section
        v-for="section in entitySections"
        :key="section.id"
        :class="['entity-section', { 'entity-section-active': activeEntitySectionId === section.id }]"
        :data-overview-target="section.id"
      >
        <header class="entity-section-head">
          <div>
            <p class="overview-kicker">{{ section.label }}</p>
            <h4>{{ section.items.length }} 个节点</h4>
          </div>
        </header>

        <div
          v-if="section.items.length > 0"
          class="entity-grid"
        >
          <article
            v-for="item in section.items"
            :key="item.name"
            class="entity-card"
          >
            <strong>{{ item.name }}</strong>
            <p>{{ item.summary || '暂无补充说明。' }}</p>
            <div class="chip-row">
              <span
                v-for="name in item.related_characters ?? []"
                :key="`${item.name}-${name}`"
                class="meta-chip"
              >
                人物 · {{ name }}
              </span>
              <span class="meta-chip meta-chip-muted">{{ formatChapterIndexes(item.chapter_indexes ?? []) }}</span>
            </div>
          </article>
        </div>

        <div
          v-else
          class="empty-card"
        >
          当前还没有提取出{{ section.label }}。
        </div>
      </section>
    </div>

    <div
      v-else-if="activeTab === 'documents'"
      class="overview-body overview-body-documents"
    >
      <p
        v-if="saveMessage"
        class="overview-inline-message overview-inline-message-grid"
      >
        {{ saveMessage }}
      </p>

      <article
        v-for="item in documents"
        :key="item.key"
        class="document-card"
      >
        <div class="document-head">
          <div>
            <p class="overview-kicker">{{ item.label }}</p>
            <h4>{{ item.content?.trim() ? '已写入' : '待补充' }}</h4>
          </div>
          <span>{{ formatDateTime(item.updated_at) }}</span>
        </div>
        <textarea
          class="document-editor"
          :placeholder="emptyDocumentTip(item.label)"
          :value="documentDraft(item.key)"
          @input="setDocumentDraft(item.key, $event.target.value)"
        />
        <div class="document-actions">
          <span class="document-filename">{{ item.filename }}</span>
          <button
            class="document-save"
            :disabled="isDocumentSaving(item.key) || !hasDocumentChanges(item)"
            type="button"
            @click="saveDocument(item)"
          >
            {{ isDocumentSaving(item.key) ? '保存中…' : '保存' }}
          </button>
        </div>
      </article>
    </div>

    <div
      v-else-if="activeTab === 'memory'"
      class="overview-body overview-body-memory"
    >
      <section class="memory-shell">
        <div class="memory-toolbar">
          <div>
            <p class="overview-kicker">项目记忆</p>
            <h4>把作者明确要求和系统整理后的长期约束分开看</h4>
          </div>
          <div class="memory-actions">
            <button
              class="document-save"
              type="button"
              @click="addMemoryEntry"
            >
              新增记忆
            </button>
            <button
              class="document-save"
              :disabled="isMemorySaving || !memoryHasChanges"
              type="button"
              @click="saveMemoryEntries"
            >
              {{ isMemorySaving ? '保存中…' : '保存全部' }}
            </button>
          </div>
        </div>

        <p
          v-if="memorySaveMessage"
          class="overview-inline-message"
        >
          {{ memorySaveMessage }}
        </p>

        <section class="memory-section">
          <div class="memory-section-head">
            <div>
              <p class="overview-kicker">作者明确要求</p>
              <h4>这些内容可以直接编辑</h4>
            </div>
            <span class="document-filename">{{ memoryDraftEntries.length }} 条</span>
          </div>

          <article
            v-for="(item, index) in memoryDraftEntries"
            :key="item.id || `memory-${index}`"
            class="document-card memory-card"
          >
            <div class="document-head">
              <div class="memory-meta">
                <select
                  class="memory-select"
                  :value="item.category"
                  @change="updateMemoryEntry(index, 'category', $event.target.value)"
                >
                  <option
                    v-for="option in memoryCategoryOptions"
                    :key="option"
                    :value="option"
                  >
                    {{ option }}
                  </option>
                </select>
                <input
                  class="knowledge-search-input"
                  :value="item.title"
                  placeholder="标题可选，比如：世界规则 / 主角底线"
                  type="text"
                  @input="updateMemoryEntry(index, 'title', $event.target.value)"
                >
              </div>
              <span>{{ formatDateTime(item.updated_at) }}</span>
            </div>

            <textarea
              class="document-editor"
              :value="item.content"
              placeholder="这里写必须长期记住的限制、偏好、连续性提醒或阶段目标。"
              @input="updateMemoryEntry(index, 'content', $event.target.value)"
            />

            <div class="document-actions">
              <span class="document-filename">进入后续生成上下文</span>
              <button
                class="overview-close memory-remove"
                type="button"
                @click="removeMemoryEntry(index)"
              >
                删除
              </button>
            </div>
          </article>

          <div
            v-if="memoryDraftEntries.length === 0"
            class="empty-card"
          >
            还没有手工记忆。适合写这里的内容包括：不能改动的世界规则、人物底线、必须保留的悬念、作者个人偏好。
          </div>
        </section>

        <section class="memory-section">
          <div class="memory-section-head">
            <div>
              <p class="overview-kicker">系统整理</p>
              <h4>跟随章节和设定自动刷新</h4>
            </div>
            <span class="document-filename">{{ autoMemoryEntries.length }} 条</span>
          </div>

          <p class="memory-note">
            这里会自动整理最近推进、人物现状、悬念和阶段目标，不在这个面板里手工保存。
          </p>

          <article
            v-for="item in autoMemoryEntries"
            :key="item.id"
            class="document-card memory-card memory-card-readonly"
          >
            <div class="document-head">
              <div class="memory-meta">
                <span class="memory-tag">{{ item.category || '连续性' }}</span>
                <strong>{{ item.title || '系统整理' }}</strong>
              </div>
              <span>{{ formatDateTime(item.updated_at) }}</span>
            </div>

            <textarea
              class="document-editor"
              :value="item.content"
              readonly
            />

            <div class="document-actions">
              <span class="document-filename">由系统自动写入项目上下文</span>
            </div>
          </article>

          <div
            v-if="autoMemoryEntries.length === 0"
            class="empty-card"
          >
            系统整理还没生成出来。补充章节或项目设定后会自动刷新。
          </div>
        </section>
      </section>
    </div>

    <div
      v-else-if="activeTab === 'reviews'"
      class="overview-body overview-body-reviews"
      data-testid="story-overview-chapter-reviews"
    >
      <section class="review-shell">
        <div class="memory-toolbar">
          <div>
            <p class="overview-kicker">章节核验</p>
            <h4>查看每章的连续性、项目记忆和设定约束问题</h4>
          </div>
          <span class="document-filename">{{ chapterReviews.length }} 章有核验报告</span>
        </div>

        <article
          v-for="review in chapterReviews"
          :key="review.chapter_id"
          class="document-card review-card"
          :data-testid="`chapter-review-${review.chapter_id}`"
        >
          <div class="document-head">
            <div>
              <p class="overview-kicker">第 {{ review.chapter_index }} 章</p>
              <h4>{{ review.chapter_title || '未命名章节' }}</h4>
            </div>
            <span>{{ formatDateTime(review.updated_at) }}</span>
          </div>

          <div class="review-score-row">
            <span :class="['memory-tag', `review-status-${review.status || 'na'}`]">
              {{ chapterReviewStatusLabel(review.status) }}
            </span>
            <strong>{{ review.overall_score }}/100</strong>
            <span>{{ chapterReviewIssueCount(review) }} 个问题</span>
            <span v-if="review.is_stale">报告已过期</span>
          </div>

          <p class="dream-summary">{{ review.summary || '暂无摘要。' }}</p>

          <div
            v-if="review.highlights?.length"
            class="chip-row"
          >
            <span
              v-for="item in review.highlights"
              :key="`${review.chapter_id}-highlight-${item}`"
              class="meta-chip meta-chip-accent"
            >
              {{ item }}
            </span>
          </div>

          <ul
            v-if="review.suggestions?.length"
            class="plain-list review-suggestions"
          >
            <li
              v-for="item in review.suggestions"
              :key="`${review.chapter_id}-suggestion-${item}`"
            >
              {{ item }}
            </li>
          </ul>

          <div class="review-dimension-grid">
            <article
              v-for="dimension in review.dimensions ?? []"
              :key="`${review.chapter_id}-${dimension.id}`"
              class="entity-card review-dimension-card"
              :data-testid="dimension.id === 'project_memory' ? 'chapter-review-project-memory-dimension' : undefined"
            >
              <div class="knowledge-result-head">
                <strong>{{ dimension.label }}</strong>
                <span>{{ chapterReviewStatusLabel(dimension.status) }} · {{ dimension.score }}/100</span>
              </div>
              <p>{{ dimension.summary || '暂无摘要。' }}</p>

              <div
                v-if="dimension.highlights?.length"
                class="chip-row"
              >
                <span
                  v-for="item in dimension.highlights"
                  :key="`${review.chapter_id}-${dimension.id}-highlight-${item}`"
                  class="meta-chip"
                >
                  {{ item }}
                </span>
              </div>

              <ul
                v-if="dimension.issues?.length"
                class="plain-list review-issue-list"
              >
                <li
                  v-for="issue in dimension.issues"
                  :key="`${review.chapter_id}-${dimension.id}-${issue.title}-${issue.detail}`"
                >
                  <strong>{{ chapterReviewIssueLevelLabel(issue.level) }}：{{ issue.title }}</strong>
                  <p>{{ issue.detail }}</p>
                </li>
              </ul>
            </article>
          </div>
        </article>

        <div
          v-if="chapterReviews.length === 0"
          class="empty-card"
        >
          还没有章节核验报告。保存章节正文后会自动生成。
        </div>
      </section>
    </div>

    <div
      v-else-if="activeTab === 'dream'"
      class="overview-body overview-body-dream"
    >
      <section class="dream-shell">
        <div class="memory-toolbar">
          <div>
            <p class="overview-kicker">梦境整理</p>
            <h4>把近期章节和设定做一次离线联想，再决定哪些内容值得沉到长期记忆</h4>
          </div>
          <button
            class="document-save"
            :disabled="isDreamRunning"
            type="button"
            @click="runDreaming"
          >
            {{ isDreamRunning ? '做梦中…' : '开始做梦' }}
          </button>
        </div>

        <div class="dream-runner">
          <input
            v-model="dreamFocus"
            class="knowledge-search-input"
            placeholder="可选：比如 聚焦主线悬念 / 人物关系 / 后三章推进"
            type="text"
          >
        </div>

        <p
          v-if="dreamMessage"
          class="overview-inline-message"
        >
          {{ dreamMessage }}
        </p>

        <article
          v-if="dreamReport"
          class="document-card dream-card"
        >
          <div class="document-head">
            <div>
              <p class="overview-kicker">最近梦境</p>
              <h4>{{ dreamReport.is_stale ? '结果已过期' : '结果可用' }}</h4>
            </div>
            <span>{{ formatDateTime(dreamReport.generated_at) }}</span>
          </div>

          <p class="dream-summary">{{ dreamReport.summary || '这轮还没有整理出足够稳定的慢线索。' }}</p>

          <div class="chip-row">
            <span class="meta-chip meta-chip-accent">{{ dreamReport.engine === 'model' ? '模型做梦' : '规则做梦' }}</span>
            <span
              v-for="item in dreamReport.themes ?? []"
              :key="`dream-theme-${item}`"
              class="meta-chip"
            >
              {{ item }}
            </span>
          </div>

          <p
            v-if="dreamReport.is_stale"
            class="memory-note"
          >
            项目内容已经变了，这份梦境结果不会再进规划提示词。先重新做梦，再决定要不要采用这些候选。
          </p>
        </article>

        <div
          v-if="dreamReport"
          class="dream-grid"
        >
          <section class="document-card dream-card">
            <div class="document-head">
              <div>
                <p class="overview-kicker">慢线索判断</p>
                <h4>{{ dreamReport.insights?.length ?? 0 }} 条</h4>
              </div>
              <span>来源章节 {{ dreamReport.source_chapter_ids?.length ?? 0 }}</span>
            </div>
            <ul
              v-if="dreamReport.insights?.length"
              class="plain-list"
            >
              <li
                v-for="item in dreamReport.insights"
                :key="item"
              >
                {{ item }}
              </li>
            </ul>
            <p v-else>这轮没有整理出更明确的判断。</p>
          </section>

          <section class="document-card dream-card">
            <div class="document-head">
              <div>
                <p class="overview-kicker">待验证问题</p>
                <h4>{{ dreamReport.open_questions?.length ?? 0 }} 条</h4>
              </div>
              <span>来源文件 {{ dreamReport.source_document_keys?.length ?? 0 }}</span>
            </div>
            <ul
              v-if="dreamReport.open_questions?.length"
              class="plain-list"
            >
              <li
                v-for="item in dreamReport.open_questions"
                :key="item"
              >
                {{ item }}
              </li>
            </ul>
            <p v-else>目前还没有需要单独盯住的问题。</p>
          </section>
        </div>

        <section
          v-if="dreamReport"
          class="memory-section"
        >
          <div class="memory-section-head">
            <div>
              <p class="overview-kicker">自动回流</p>
              <h4>梦境线索会自动进入系统记忆</h4>
            </div>
            <span class="document-filename">{{ dreamReport.memory_candidates?.length ?? 0 }} 条</span>
          </div>

          <article
            v-for="item in dreamReport.memory_candidates ?? []"
            :key="item.id"
            class="document-card memory-card"
          >
            <div class="document-head">
              <div class="dream-candidate-meta">
                <span class="memory-tag">{{ item.category || '连续性' }}</span>
                <strong>{{ item.title || '梦境候选' }}</strong>
              </div>
              <span>置信度 {{ formatConfidence(item.confidence) }}</span>
            </div>

            <p class="dream-summary">{{ item.content }}</p>
            <p
              v-if="item.rationale"
              class="dream-rationale"
            >
              {{ item.rationale }}
            </p>

            <div class="document-actions">
              <span class="document-filename">
                {{ item.promoted_at ? `已自动写入 ${formatDateTime(item.promoted_at)}` : '等待自动写入' }}
              </span>
            </div>
          </article>

          <div
            v-if="(dreamReport.memory_candidates?.length ?? 0) === 0"
            class="empty-card"
          >
            这轮做梦还没有整理出适合沉到长期记忆的候选。
          </div>
        </section>

        <div
          v-if="!dreamReport"
          class="empty-card"
        >
          还没有做梦结果。它适合在写过几章、或者整本规划变复杂之后跑一轮，用来看主线、悬念和阶段目标是不是还在同一个方向上。
        </div>
      </section>
    </div>

    <div
      v-else
      class="overview-body overview-body-knowledge"
    >
      <section class="knowledge-shell">
        <article class="knowledge-import-card">
          <div class="knowledge-import-head">
            <div>
              <p class="overview-kicker">资料导入</p>
              <h4>把外部文本收进项目资料库</h4>
            </div>
            <button
              class="knowledge-search-button"
              :disabled="isKnowledgeImporting"
              type="button"
              @click="importKnowledge"
            >
              {{ isKnowledgeImporting ? '导入中…' : '导入资料' }}
            </button>
          </div>

          <div class="knowledge-import-grid">
            <label class="knowledge-field">
              <span>资料标题</span>
              <input
                v-model="knowledgeTitle"
                class="knowledge-search-input"
                placeholder="手动粘贴时可写一个标题"
                type="text"
              >
            </label>

            <label class="knowledge-field">
              <span>本地文件</span>
              <input
                :accept="importAcceptValue()"
                class="knowledge-file-input"
                multiple
                ref="knowledgeFileInput"
                type="file"
                @change="handleKnowledgeFilesChange"
              >
            </label>
          </div>

          <label class="knowledge-field">
            <span>资料正文</span>
            <textarea
              v-model="knowledgeContent"
              class="knowledge-import-editor"
              placeholder="这里可以直接粘贴设定资料、采访记录、参考文案或世界观草稿。"
            />
          </label>

          <p
            v-if="knowledgeImportMessage"
            class="overview-inline-message"
          >
            {{ knowledgeImportMessage }}
          </p>
        </article>

        <section
          v-if="materials.length > 0"
          class="knowledge-library"
        >
          <div class="knowledge-result-head knowledge-library-head">
            <strong>资料库</strong>
            <span>{{ materials.length }} 份</span>
          </div>

          <div class="knowledge-grid">
            <article
              v-for="item in materials"
              :key="item.filename"
              class="entity-card"
            >
              <div class="knowledge-result-head">
                <strong>{{ item.title }}</strong>
                <span>{{ formatDateTime(item.updated_at) }}</span>
              </div>
              <p>{{ item.preview || '暂无摘要。' }}</p>
            </article>
          </div>
        </section>

        <section
          v-if="obsidian?.enabled"
          class="knowledge-library"
          data-testid="story-overview-obsidian"
        >
          <div class="knowledge-result-head knowledge-library-head">
            <strong>Obsidian</strong>
            <span>{{ obsidian.included_count ?? 0 }} 份 · 解析 {{ obsidian.resolved_link_count ?? 0 }} 条 · 歧义 {{ obsidian.ambiguous_link_count ?? 0 }} 条</span>
          </div>

          <div
            v-if="obsidian.warnings?.length"
            class="empty-card"
          >
            {{ obsidian.warnings.join('；') }}
          </div>

          <div
            v-if="obsidian.issues?.length"
            class="knowledge-grid"
          >
            <article
              v-for="item in obsidian.issues.slice(0, 6)"
              :key="`${item.kind}-${item.title}`"
              class="entity-card"
            >
              <div class="knowledge-result-head">
                <strong>{{ item.title }}</strong>
                <span>{{ item.severity || 'info' }}</span>
              </div>
              <p>{{ item.message }}</p>
              <p
                v-if="item.notes?.length"
                class="entity-meta-line"
              >
                {{ item.notes.slice(0, 4).join(' / ') }}
              </p>
            </article>
          </div>

          <div
            v-if="obsidianNotes.length > 0"
            class="knowledge-grid"
          >
            <article
              v-for="item in obsidianNotes.slice(0, 12)"
              :key="item.relative_path"
              class="entity-card"
            >
              <div class="knowledge-result-head">
                <strong>{{ item.title }}</strong>
                <span>{{ item.note_type || item.status || '笔记' }}</span>
              </div>
              <p>{{ item.preview || '暂无摘要。' }}</p>
              <p
                v-if="obsidianChapterScope(item)"
                class="entity-meta-line"
              >
                {{ obsidianChapterScope(item) }}
              </p>
              <p
                v-if="obsidianSourceChapterText(item)"
                class="entity-meta-line"
              >
                {{ obsidianSourceChapterText(item) }}
              </p>
              <p
                v-if="item.required_phrases?.length"
                class="entity-meta-line"
              >
                必须包含：{{ item.required_phrases.slice(0, 5).join(' / ') }}
              </p>
              <p
                v-if="item.forbidden_phrases?.length"
                class="entity-meta-line"
              >
                禁止出现：{{ item.forbidden_phrases.slice(0, 5).join(' / ') }}
              </p>
              <p
                v-if="obsidianExternalReferences(item).values.length"
                class="entity-meta-line"
              >
                {{ obsidianExternalReferences(item).label }}：{{ obsidianExternalReferences(item).values.join(' / ') }}
              </p>
              <p
                v-if="item.links?.length"
                class="entity-meta-line"
              >
                {{ item.links.slice(0, 5).join(' / ') }}
              </p>
              <p
                v-if="item.graph_relations?.length"
                class="entity-meta-line"
              >
                关系：{{ item.graph_relations.slice(0, 5).join(' / ') }}
              </p>
              <p
                v-if="item.backlinks?.length"
                class="entity-meta-line"
              >
                被引用：{{ item.backlinks.slice(0, 5).join(' / ') }}
              </p>
              <p
                v-if="item.unresolved_links?.length"
                class="entity-meta-line"
              >
                未解析：{{ item.unresolved_links.slice(0, 5).join(' / ') }}
              </p>
              <p
                v-if="item.ambiguous_links?.length"
                class="entity-meta-line"
              >
                歧义：{{ item.ambiguous_links.slice(0, 5).join(' / ') }}
              </p>
            </article>
          </div>
        </section>

        <div class="knowledge-search-row">
          <input
            v-model="knowledgeQuery"
            class="knowledge-search-input"
            placeholder="输入人物、地点、道具、伏笔或设定关键词"
            type="text"
            @keydown.enter.prevent="runKnowledgeSearch"
          >
          <button
            class="knowledge-search-button"
            :disabled="isKnowledgeSearching"
            type="button"
            @click="runKnowledgeSearch"
          >
            {{ isKnowledgeSearching ? '检索中…' : '开始检索' }}
          </button>
        </div>

        <p
          v-if="saveMessage"
          class="overview-inline-message"
        >
          {{ saveMessage }}
        </p>
        <p
          v-if="knowledgeMessage"
          class="overview-inline-message"
        >
          {{ knowledgeMessage }}
        </p>

        <div
          v-if="knowledgeResults.length > 0"
          class="knowledge-grid"
        >
          <article
            v-for="item in knowledgeResults"
            :key="`${item.source}-${item.section}-${item.preview}`"
            class="entity-card"
          >
            <div class="knowledge-result-head">
              <strong>{{ item.section }}</strong>
              <span>{{ item.source }}</span>
            </div>
            <p>{{ item.preview }}</p>
          </article>
        </div>

        <div
          v-else
          class="empty-card"
        >
          这里会同时检索架构文件和章节正文。先输入关键词再搜索。
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.story-overview-panel {
  width: min(1140px, 100%);
  height: calc(100vh - 40px);
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 10px;
  padding: 16px;
  border-radius: 28px;
  border: 1px solid rgba(214, 221, 231, 0.96);
  background: #ffffff;
  box-shadow: 0 22px 70px rgba(15, 23, 42, 0.16);
  overflow: hidden;
}

.overview-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.overview-header-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
}

.overview-model-status {
  display: grid;
  gap: 4px;
  max-width: 520px;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  background: #f6f8fa;
  padding: 10px 12px;
  color: #4f5b66;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.overview-model-status strong {
  color: #1f2328;
  font-size: 13px;
}

.overview-model-status-error {
  border-color: #f4b4ad;
  background: #fff4f2;
  color: #9f2d20;
}

.overview-model-status-error strong {
  color: #8c1d18;
}

.overview-title-line {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.overview-kicker {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #6c7688;
  white-space: nowrap;
}

.overview-header h3,
.entity-section-head h4,
.document-head h4,
.character-header h4 {
  margin: 0;
  color: #1f2430;
  line-height: 1.2;
}

.overview-copy {
  margin: 0;
  color: #606977;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
}

.overview-support-inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  min-width: 0;
  color: #6a7383;
  font-size: 11px;
  line-height: 1.4;
}

.support-inline-item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  white-space: nowrap;
}

.support-inline-item strong {
  color: #18202d;
  font-size: 12px;
}

.overview-close {
  border: 1px solid rgba(200, 208, 220, 0.96);
  border-radius: 999px;
  padding: 6px 11px;
  background: rgba(255, 255, 255, 0.94);
  color: #24292f;
  cursor: pointer;
}

.overview-close:hover {
  background: #f5f7fb;
}

.overview-summary-shell {
  display: grid;
  gap: 6px;
}

.overview-summary {
  display: grid;
  gap: 6px;
}

.overview-summary-core {
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.summary-card,
.info-card,
.entity-card,
.document-card,
.character-index-item,
.empty-card {
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: none;
}

.summary-card {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 15px;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.summary-card:hover {
  border-color: #cfe0fa;
  background: #f8fbff;
}

.summary-card:focus-visible {
  outline: 2px solid #456ce9;
  outline-offset: 2px;
}

.summary-card span,
.info-label {
  color: #6a7383;
  font-size: 12px;
  white-space: nowrap;
}

.summary-card strong {
  color: #18202d;
  font-size: 16px;
  line-height: 1;
  white-space: nowrap;
}

.summary-card p,
.info-card p,
.entity-card p,
.document-body,
.character-index-item p,
.relationship-node p,
.timeline-card p,
.meta-section p,
.relationship-copy,
.relationship-profile,
.relationship-empty {
  margin: 8px 0 0;
  color: #5c6675;
  line-height: 1.7;
}

.overview-tabs {
  display: flex;
  flex-wrap: nowrap;
  gap: 5px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
}

.overview-tabs::-webkit-scrollbar {
  display: none;
}

.overview-tab {
  border: 1px solid rgba(208, 215, 222, 0.98);
  border-radius: 999px;
  padding: 5px 10px;
  background: rgba(255, 255, 255, 0.88);
  color: #5d6675;
  cursor: pointer;
  font-size: 12px;
  flex: 0 0 auto;
}

.overview-tab-active {
  border-color: #cfe0fa;
  background: #e8f0fe;
  color: #1d4ed8;
}

.overview-body {
  min-height: 0;
  overflow: auto;
}

.overview-body-characters {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 14px;
}

.character-index {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  padding-right: 6px;
}

.character-index-item {
  padding: 14px;
  text-align: left;
  cursor: pointer;
}

.character-index-item-active {
  border-color: #cfe0fa;
  background: #f8fbff;
  box-shadow: none;
}

.character-index-top,
.timeline-head,
.document-head,
.character-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.character-index-top strong,
.entity-card strong,
.timeline-head strong {
  color: #18202d;
}

.character-index-top span,
.character-count,
.timeline-head span,
.document-head span,
.relationship-node-head span {
  color: #6b7483;
  font-size: 11px;
  white-space: nowrap;
}

.character-stage {
  display: grid;
  gap: 14px;
  min-height: 0;
  align-content: start;
}

.relationship-hero {
  display: grid;
  gap: 16px;
  padding: 18px 20px;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 18px;
  background: #f8fbff;
  box-shadow: none;
}

.relationship-hero-head,
.relationship-panel-head,
.timeline-shell-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.relationship-hero-head h4,
.relationship-panel-head h5,
.timeline-shell-head h5 {
  margin: 0;
  color: #18202d;
}

.relationship-copy {
  margin-top: 10px;
  font-size: 14px;
}

.relationship-profile {
  margin-top: 6px;
  font-size: 12px;
}

.relationship-metrics {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 12px;
}

.relationship-metric {
  padding: 12px 14px;
  border: 1px solid rgba(218, 224, 235, 0.98);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.84);
}

.relationship-metric span {
  display: block;
  color: #6a7383;
  font-size: 11px;
}

.relationship-metric strong {
  display: block;
  margin-top: 8px;
  color: #18202d;
  font-size: 20px;
  line-height: 1;
}

.relationship-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.relationship-panel,
.timeline-shell {
  padding: 16px 18px;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: none;
}

.relationship-panel {
  display: grid;
  gap: 12px;
  align-content: start;
}

.relationship-panel-people {
  background: #f8fbff;
}

.relationship-stack {
  display: grid;
  gap: 10px;
}

.relationship-node {
  padding: 12px 14px;
  border: 1px solid rgba(222, 227, 236, 0.98);
  border-radius: 16px;
  background: #f9fbfd;
}

.relationship-node-character {
  background: #f8fbff;
}

.relationship-node-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.relationship-empty {
  margin: 0;
  font-size: 13px;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 5px 10px;
  background: #f4f7fb;
  color: #465062;
  font-size: 11px;
}

.meta-chip-accent {
  background: #edf3ff;
  color: #3356a6;
}

.meta-chip-muted {
  background: #f8f9fb;
  color: #6a7383;
}

.timeline-list {
  list-style: none;
  margin: 0;
  padding: 4px 0 0;
  display: grid;
  gap: 12px;
}

.timeline-item {
  position: relative;
  padding-left: 22px;
}

.timeline-line {
  position: absolute;
  top: 14px;
  left: 7px;
  bottom: -18px;
  width: 2px;
  border-radius: 999px;
  background: rgba(212, 219, 229, 0.96);
}

.timeline-item:last-child .timeline-line {
  display: none;
}

.timeline-card {
  position: relative;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 18px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.96);
}

.timeline-card::before {
  content: "";
  position: absolute;
  top: 16px;
  left: 0;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #ffffff;
  border: 3px solid #cad4e4;
}

.timeline-item-current .timeline-card {
  border-color: #cfe0fa;
  background: #f8fbff;
}

.timeline-item-current .timeline-card::before {
  border-color: #456ce9;
}

.overview-body-entities {
  display: grid;
  gap: 18px;
  align-content: start;
}

.entity-section {
  display: grid;
  gap: 10px;
  scroll-margin-top: 8px;
}

.entity-section-active .entity-section-head {
  border-color: #cfe0fa;
  background: #f8fbff;
}

.entity-section-head {
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 14px;
}

.entity-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.entity-card,
.document-card,
.empty-card {
  padding: 16px 18px;
}

.overview-body-documents {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-content: start;
}

.overview-body-memory {
  display: block;
}

.overview-body-reviews {
  display: block;
  overflow: auto;
}

.overview-body-dream {
  display: block;
}

.overview-inline-message {
  margin: 0;
  color: #5c6675;
  font-size: 12px;
}

.overview-inline-message-grid {
  grid-column: 1 / -1;
}

.document-head {
  margin-bottom: 12px;
}

.memory-shell {
  display: grid;
  gap: 12px;
  align-content: start;
}

.dream-shell {
  display: grid;
  gap: 12px;
  align-content: start;
}

.review-shell {
  display: grid;
  gap: 12px;
  align-content: start;
  min-width: 0;
}

.review-card {
  display: grid;
  gap: 12px;
}

.review-score-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: #5c6675;
  font-size: 13px;
}

.review-score-row strong {
  color: #1f2328;
  font-size: 18px;
}

.review-dimension-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.review-dimension-card {
  align-content: start;
}

.review-suggestions,
.review-issue-list {
  margin: 0;
}

.review-issue-list p {
  margin: 4px 0 0;
  color: #4f5b66;
  line-height: 1.6;
}

.review-status-good {
  border-color: #bbf7d0;
  background: #ecfdf5;
  color: #166534;
}

.review-status-watch {
  border-color: #fde68a;
  background: #fffbeb;
  color: #92400e;
}

.review-status-risk {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}

.dream-runner {
  display: flex;
  gap: 12px;
  align-items: center;
}

.dream-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.dream-card {
  display: grid;
  gap: 10px;
}

.dream-summary,
.dream-rationale {
  margin: 0;
  color: #5c6675;
  line-height: 1.8;
}

.dream-rationale {
  font-size: 12px;
}

.dream-candidate-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.memory-section {
  display: grid;
  gap: 12px;
}

.memory-toolbar,
.memory-section-head,
.memory-actions,
.memory-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.memory-actions {
  justify-content: flex-end;
}

.memory-meta {
  flex: 1;
  justify-content: flex-start;
}

.memory-section-head {
  justify-content: space-between;
}

.memory-note {
  margin: 0;
  padding: 0 4px;
  color: #5c6675;
  font-size: 12px;
  line-height: 1.7;
}

.memory-card {
  display: grid;
  gap: 10px;
}

.memory-card-readonly .document-editor {
  background: #f6f8fb;
}

.memory-select {
  min-width: 108px;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 12px;
  padding: 11px 13px;
  background: #ffffff;
  color: #253041;
}

.memory-tag {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 5px 10px;
  background: #eef3ff;
  color: #3556a3;
  font-size: 11px;
}

.memory-remove {
  border: 1px solid rgba(214, 221, 231, 0.96);
  color: #5d6675;
}

.document-editor {
  min-height: 170px;
  max-height: 360px;
  width: 100%;
  padding: 14px;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 14px;
  background: #f9fbfd;
  color: #253041;
  line-height: 1.7;
  resize: vertical;
}

.document-actions,
.knowledge-search-row,
.knowledge-result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.document-actions {
  margin-top: 12px;
}

.document-filename,
.knowledge-result-head span,
.entity-meta-line {
  color: #6b7483;
  font-size: 11px;
}

.document-save,
.knowledge-search-button {
  border: none;
  border-radius: 10px;
  padding: 9px 14px;
  background: #1d4ed8;
  color: #ffffff;
  cursor: pointer;
}

.document-save:disabled,
.knowledge-search-button:disabled {
  opacity: 0.55;
  cursor: default;
}

.overview-body-knowledge {
  display: block;
}

.knowledge-shell {
  display: grid;
  gap: 14px;
  align-content: start;
}

.knowledge-import-card {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
}

.knowledge-import-head,
.knowledge-import-grid {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.knowledge-import-grid {
  align-items: stretch;
}

.knowledge-field {
  display: grid;
  gap: 8px;
  flex: 1;
}

.knowledge-field span {
  color: #6b7483;
  font-size: 11px;
}

.knowledge-search-input {
  flex: 1;
  min-width: 0;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 12px;
  padding: 11px 13px;
  background: #ffffff;
  color: #253041;
}

.knowledge-file-input,
.knowledge-import-editor {
  width: 100%;
  border: 1px solid rgba(214, 221, 231, 0.96);
  border-radius: 12px;
  padding: 11px 13px;
  background: #ffffff;
  color: #253041;
}

.knowledge-import-editor {
  min-height: 160px;
  resize: vertical;
  line-height: 1.7;
}

.knowledge-library {
  display: grid;
  gap: 12px;
}

.knowledge-library-head {
  padding: 0 4px;
}

.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 1380px) {
  .overview-summary-core {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .overview-support-strip,
  .relationship-metrics {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .story-overview-panel {
    height: calc(100vh - 32px);
    padding: 18px;
  }

  .overview-body-characters,
  .dream-grid,
  .overview-body-documents,
  .review-dimension-grid,
  .knowledge-grid,
  .entity-grid,
  .overview-summary,
  .overview-summary-core,
  .overview-support-strip,
  .relationship-grid,
  .relationship-metrics {
    grid-template-columns: 1fr;
  }

  .knowledge-import-head,
  .knowledge-import-grid {
    flex-direction: column;
    align-items: stretch;
  }

  .dream-runner,
  .memory-toolbar,
  .memory-section-head,
  .memory-actions,
  .memory-meta,
  .document-actions,
  .knowledge-search-row,
  .knowledge-result-head,
  .relationship-hero-head,
  .relationship-panel-head,
  .timeline-shell-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
