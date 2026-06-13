<script setup>
const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
});

function compactText(value, limit = 78) {
  const normalized = String(value ?? '').trim().replace(/\s+/g, ' ');
  if (!normalized) {
    return '';
  }

  return normalized.length > limit ? `${normalized.slice(0, limit)}…` : normalized;
}

function statusLabel(status) {
  const normalized = String(status ?? '').trim();
  if (normalized === 'running') {
    return '处理中';
  }
  if (normalized === 'failed') {
    return '失败';
  }
  if (normalized === 'pending') {
    return '待处理';
  }
  return '完成';
}

function statusClass(status) {
  const normalized = String(status ?? '').trim();
  if (normalized === 'running') {
    return 'timeline-status-running';
  }
  if (normalized === 'failed') {
    return 'timeline-status-failed';
  }
  if (normalized === 'pending') {
    return 'timeline-status-pending';
  }
  return 'timeline-status-completed';
}

function stepLabel(item, index) {
  return item?.step ? `第 ${item.step} 步` : `步骤 ${index + 1}`;
}

function itemTitle(item) {
  return String(item?.label ?? item?.title ?? '').trim() || '执行步骤';
}

function itemSummary(item) {
  return compactText(item?.summary, 90);
}

function detailSummary(item) {
  const text = String(item?.summary ?? '').trim();
  return text && text !== itemSummary(item) ? text : '';
}

function taskPackLabel(value) {
  const normalized = String(value ?? '').trim();
  const labels = {
    architecture: '整书架构',
    discussion: '项目讨论',
    chapter: '章节处理',
    rewrite: '正文改写',
  };

  return labels[normalized] ?? '';
}

function actionLabel(value) {
  const normalized = String(value ?? '').trim();
  const labels = {
    session_prepare: '读取上下文',
    session_plan: '生成计划',
    review_knowledge: '资料分析',
    brainstorm: '讨论',
    generate_architecture: '写回架构',
    continue_project: '扩写后续规划',
    chapter_generate: '生成正文',
    chapter_workflow: '章节工作流',
    chapter_review: '章节检查',
    rewrite_chapter: '改写正文',
    skill_optimize: '技能整理',
  };

  return labels[normalized] ?? '';
}

function previewChanges(item) {
  return Array.isArray(item?.changes) ? item.changes.slice(0, 3) : [];
}

function hiddenChangeCount(item) {
  const total = Array.isArray(item?.changes) ? item.changes.length : 0;
  return total > 3 ? total - 3 : 0;
}

function subtasks(item) {
  return Array.isArray(item?.subTasks) ? item.subTasks : [];
}

function hasDetails(item) {
  return Boolean(detailSummary(item) || hiddenChangeCount(item) > 0 || subtasks(item).some((subtask) => subtask.summary));
}
</script>

<template>
  <ol
    v-if="items.length"
    class="timeline-list"
    data-testid="agent-timeline"
  >
    <li
      v-for="(item, index) in items"
      :key="`${item.step ?? index + 1}-${item.actionKind ?? item.action_kind ?? item.title}-${item.label ?? item.title}`"
      class="timeline-item"
      data-testid="agent-timeline-item"
    >
      <span :class="['timeline-marker', statusClass(item.status)]"></span>

      <div class="timeline-card">
        <div class="timeline-head">
          <div class="timeline-title-block">
            <span class="timeline-step">{{ stepLabel(item, index) }}</span>
            <strong>{{ itemTitle(item) }}</strong>
          </div>
          <span :class="['timeline-status', statusClass(item.status)]">
            {{ statusLabel(item.status) }}
          </span>
        </div>

        <p
          v-if="itemSummary(item)"
          class="timeline-summary"
        >
          {{ itemSummary(item) }}
        </p>

        <div
          v-if="taskPackLabel(item.taskPackKind || item.task_pack_kind) || actionLabel(item.actionKind || item.action_kind) || item.materialCount"
          class="timeline-chip-row"
        >
          <span
            v-if="taskPackLabel(item.taskPackKind || item.task_pack_kind)"
            class="timeline-chip"
          >
            {{ taskPackLabel(item.taskPackKind || item.task_pack_kind) }}
          </span>
          <span
            v-if="actionLabel(item.actionKind || item.action_kind)"
            class="timeline-chip timeline-chip-muted"
          >
            {{ actionLabel(item.actionKind || item.action_kind) }}
          </span>
          <span
            v-if="item.materialCount"
            class="timeline-chip timeline-chip-muted"
          >
            资料 {{ item.materialCount }} 份
          </span>
        </div>

        <div
          v-if="previewChanges(item).length"
          class="timeline-change-row"
        >
          <span
            v-for="change in previewChanges(item)"
            :key="change"
            class="timeline-change-chip"
          >
            {{ change }}
          </span>
          <span
            v-if="hiddenChangeCount(item) > 0"
            class="timeline-change-chip timeline-change-chip-more"
          >
            +{{ hiddenChangeCount(item) }} 项
          </span>
        </div>

        <div
          v-if="subtasks(item).length"
          class="timeline-subtask-list"
        >
          <div
            v-for="subtask in subtasks(item)"
            :key="subtask.id"
            class="timeline-subtask"
          >
            <span :class="['timeline-subtask-dot', statusClass(subtask.status)]"></span>
            <div class="timeline-subtask-copy">
              <strong>{{ subtask.role }}</strong>
              <span v-if="subtask.capability">{{ subtask.capability }}</span>
            </div>
            <span :class="['timeline-subtask-status', statusClass(subtask.status)]">
              {{ statusLabel(subtask.status) }}
            </span>
          </div>
        </div>

        <details
          v-if="hasDetails(item)"
          :open="item.status === 'running'"
          class="timeline-detail"
        >
          <summary>查看详情</summary>

          <p
            v-if="detailSummary(item)"
            class="timeline-detail-copy"
          >
            {{ detailSummary(item) }}
          </p>

          <ul
            v-if="hiddenChangeCount(item) > 0"
            class="timeline-detail-list"
          >
            <li
              v-for="change in item.changes"
              :key="change"
            >
              {{ change }}
            </li>
          </ul>

          <ul
            v-if="subtasks(item).some((subtask) => subtask.summary)"
            class="timeline-detail-list"
          >
            <li
              v-for="subtask in subtasks(item).filter((subtask) => subtask.summary)"
              :key="`${subtask.id}-summary`"
            >
              {{ subtask.role }}：{{ subtask.summary }}
            </li>
          </ul>
        </details>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.timeline-list {
  margin: 0;
  padding: 2px 0 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.timeline-item {
  position: relative;
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.timeline-marker {
  position: relative;
  display: block;
  width: 12px;
  height: 12px;
  margin-top: 9px;
  border-radius: 999px;
  background: #d0d7de;
  border: 3px solid #ffffff;
  box-shadow: 0 0 0 1px #d8dee4;
}

.timeline-marker::after {
  content: '';
  position: absolute;
  top: 14px;
  left: 50%;
  width: 1px;
  height: calc(100% + 18px);
  transform: translateX(-50%);
  background: #e6eaef;
}

.timeline-item:last-child .timeline-marker::after {
  display: none;
}

.timeline-card {
  display: grid;
  gap: 7px;
  border: 1px solid #e7ebf0;
  border-radius: 10px;
  padding: 9px 11px;
  background: #ffffff;
}

.timeline-head,
.timeline-chip-row,
.timeline-change-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.timeline-head {
  justify-content: space-between;
}

.timeline-title-block {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
}

.timeline-step {
  color: #1d4ed8;
  font-size: 11px;
}

.timeline-title-block strong {
  color: #1f2328;
  font-size: 12px;
}

.timeline-status,
.timeline-chip,
.timeline-change-chip {
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  line-height: 1.3;
}

.timeline-status-running,
.timeline-marker.timeline-status-running {
  background: #e8f0fe;
  color: #1d4ed8;
}

.timeline-status-completed,
.timeline-marker.timeline-status-completed {
  background: #eaf6ee;
  color: #17663a;
}

.timeline-status-failed,
.timeline-marker.timeline-status-failed {
  background: #fff1f1;
  color: #b42318;
}

.timeline-status-pending,
.timeline-marker.timeline-status-pending {
  background: #f3f4f6;
  color: #5b6570;
}

.timeline-chip {
  background: #eef4ff;
  color: #315f9f;
}

.timeline-chip-muted {
  background: #f3f4f6;
  color: #68707c;
}

.timeline-summary,
.timeline-detail-copy {
  margin: 0;
  color: #586270;
  font-size: 12px;
  line-height: 1.75;
}

.timeline-change-chip {
  background: #f8fafc;
  color: #475467;
  border: 1px solid #e5e9ee;
}

.timeline-change-chip-more {
  color: #7a8088;
}

.timeline-subtask-list {
  display: grid;
  gap: 6px;
  border: 1px solid #eef1f4;
  border-radius: 8px;
  padding: 7px;
  background: #fbfcfe;
}

.timeline-subtask {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.timeline-subtask-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
}

.timeline-subtask-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.timeline-subtask-copy strong {
  color: #24292f;
  font-size: 11px;
}

.timeline-subtask-copy span {
  color: #6b7280;
  font-size: 11px;
  line-height: 1.5;
}

.timeline-subtask-status {
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  white-space: nowrap;
}

.timeline-detail {
  display: grid;
  gap: 8px;
  border-top: 1px solid #eef1f4;
  padding-top: 8px;
}

.timeline-detail summary {
  cursor: pointer;
  color: #6b7280;
  font-size: 11px;
  list-style: none;
}

.timeline-detail summary::-webkit-details-marker {
  display: none;
}

.timeline-detail-list {
  margin: 0;
  padding-left: 18px;
  color: #586270;
  font-size: 12px;
  line-height: 1.75;
}
</style>
