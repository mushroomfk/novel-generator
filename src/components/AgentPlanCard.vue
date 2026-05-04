<script setup>
const props = defineProps({
  plan: {
    type: Object,
    default: null,
  },
  active: {
    type: Boolean,
    default: false,
  },
  statusText: {
    type: String,
    default: '',
  },
});

function actionLabel(action) {
  return String(action?.label ?? action?.kind ?? '').trim() || '执行动作';
}
</script>

<template>
  <section
    v-if="plan"
    :class="['agent-plan-card', { 'agent-plan-card-active': active }]"
    data-testid="agent-plan-card"
  >
    <div class="agent-plan-card-head">
      <strong>{{ plan.title }}</strong>
      <span
        v-if="statusText"
        class="agent-plan-status"
      >
        {{ statusText }}
      </span>
    </div>

    <p
      v-if="plan.summary"
      class="agent-plan-summary"
    >
      {{ plan.summary }}
    </p>

    <ol
      v-if="plan.steps?.length"
      class="agent-plan-list"
      data-testid="agent-plan-steps"
    >
      <li
        v-for="step in plan.steps"
        :key="step"
      >
        {{ step }}
      </li>
    </ol>

    <div
      v-if="plan.actions?.length"
      class="agent-plan-actions"
      data-testid="agent-plan-actions"
    >
      <span
        v-for="action in plan.actions"
        :key="`${action.kind}-${action.label}-${action.chapter_id}`"
        class="agent-plan-action-chip"
      >
        {{ actionLabel(action) }}
      </span>
    </div>

    <div
      v-if="$slots.actions"
      class="agent-plan-footer"
    >
      <slot name="actions"></slot>
    </div>
  </section>
</template>

<style scoped>
.agent-plan-card {
  display: grid;
  gap: 8px;
  border-left: 2px solid #9bbcf6;
  padding-left: 12px;
}

.agent-plan-card-active {
  border-left-color: #1d4ed8;
}

.agent-plan-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}

.agent-plan-card-head strong {
  color: #1d4ed8;
  font-size: 14px;
}

.agent-plan-status,
.agent-plan-action-chip {
  border-radius: 999px;
  padding: 4px 10px;
  background: #e8f0fe;
  color: #1d4ed8;
  font-size: 12px;
}

.agent-plan-summary {
  margin: 0;
  color: #5b6570;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.agent-plan-list {
  margin: 0;
  padding-left: 18px;
  color: #4d5863;
  font-size: 13px;
  line-height: 1.8;
}

.agent-plan-actions,
.agent-plan-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
