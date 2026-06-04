<script setup>
import { computed } from 'vue';

const props = defineProps({
  blocks: {
    type: Array,
    default: () => [],
  },
});

const STAGE_ORDER = ['plan', 'execution', 'result'];

function compactText(value, limit = 120) {
  const normalized = String(value ?? '').trim().replace(/\s+/g, ' ');
  if (!normalized) {
    return '';
  }

  return normalized.length > limit ? `${normalized.slice(0, limit)}…` : normalized;
}

function normalizedStatus(value) {
  const status = String(value ?? '').trim();
  return ['pending', 'running', 'completed', 'failed'].includes(status) ? status : 'completed';
}

function statusLabel(value) {
  const labels = {
    pending: '待处理',
    running: '处理中',
    completed: '完成',
    failed: '失败',
  };
  return labels[normalizedStatus(value)] ?? '完成';
}

function stageKey(block) {
  const eventType = String(block?.eventType ?? block?.event_type ?? '').trim();
  if (eventType.includes('plan')) {
    return 'plan';
  }
  if (eventType.includes('session') || eventType.includes('summary') || eventType.includes('final')) {
    return 'result';
  }
  return 'execution';
}

function stageLabel(stage) {
  const labels = {
    plan: '计划阶段',
    execution: '执行阶段',
    result: '结果阶段',
  };
  return labels[stage] ?? '执行阶段';
}

const groupedStages = computed(() => {
  const groups = new Map(STAGE_ORDER.map((stage) => [stage, []]));
  props.blocks.forEach((block, index) => {
    if (!block || typeof block !== 'object') {
      return;
    }
    const stage = stageKey(block);
    const title = compactText(block.title, 100);
    const summary = compactText(block.summary, 180);
    const eventType = String(block.eventType ?? block.event_type ?? '').trim();
    groups.get(stage).push({
      id: `${stage}-${eventType}-${block.step ?? index}-${title || index}`,
      title: title || stageLabel(stage),
      summary,
      status: normalizedStatus(block.status),
      step: Number(block.step ?? 0),
      actionKind: String(block.actionKind ?? block.action_kind ?? '').trim(),
    });
  });

  return STAGE_ORDER
    .map((stage) => ({
      key: stage,
      label: stageLabel(stage),
      items: groups.get(stage),
    }))
    .filter((stage) => stage.items.length > 0);
});
</script>

<template>
  <section
    v-if="groupedStages.length"
    class="event-summary"
    data-testid="agent-event-block-summary"
  >
    <div
      v-for="stage in groupedStages"
      :key="stage.key"
      class="event-stage"
      data-testid="agent-event-stage"
    >
      <div class="event-stage-label">{{ stage.label }}</div>
      <div class="event-stage-items">
        <div
          v-for="item in stage.items"
          :key="item.id"
          class="event-block"
          data-testid="agent-event-block"
        >
          <div class="event-block-head">
            <strong>{{ item.title }}</strong>
            <span :class="['event-status', `event-status-${item.status}`]">
              {{ statusLabel(item.status) }}
            </span>
          </div>
          <p v-if="item.summary">{{ item.summary }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.event-summary {
  display: grid;
  gap: 10px;
  padding: 10px 0 2px;
}

.event-stage {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.event-stage-label {
  color: #42526b;
  font-size: 12px;
  line-height: 1.6;
  padding-top: 2px;
}

.event-stage-items {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.event-block {
  display: grid;
  gap: 4px;
  border-left: 2px solid #d8e2ee;
  padding-left: 10px;
}

.event-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.event-block-head strong {
  min-width: 0;
  color: #24292f;
  font-size: 13px;
  line-height: 1.55;
}

.event-block p {
  margin: 0;
  color: #667085;
  font-size: 12px;
  line-height: 1.65;
}

.event-status {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11px;
  line-height: 1.4;
}

.event-status-running {
  background: #e8f0fe;
  color: #1d4ed8;
}

.event-status-completed {
  background: #eaf6ee;
  color: #17663a;
}

.event-status-failed {
  background: #fff1f1;
  color: #b42318;
}

.event-status-pending {
  background: #f3f4f6;
  color: #5b6570;
}

@media (max-width: 720px) {
  .event-stage {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .event-stage-label {
    padding-top: 0;
  }
}
</style>
