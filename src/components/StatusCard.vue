<script setup>
import { computed } from 'vue';

const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  value: {
    type: String,
    required: true,
  },
  helper: {
    type: String,
    default: '',
  },
  tone: {
    type: String,
    default: 'neutral',
  },
});

const toneClass = computed(() => `tone-${props.tone}`);
</script>

<template>
  <article :class="['status-card', toneClass]">
    <p class="status-title">{{ title }}</p>
    <h3 class="status-value">{{ value }}</h3>
    <p
      v-if="helper"
      class="status-helper"
    >
      {{ helper }}
    </p>
  </article>
</template>

<style scoped>
.status-card {
  border: 1px solid #dce6f4;
  border-radius: 16px;
  padding: 18px;
  background: #ffffff;
  box-shadow: none;
}

.status-title {
  margin: 0 0 10px;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #667085;
}

.status-value {
  margin: 0;
  font-size: 24px;
  color: #1f2328;
}

.status-helper {
  margin: 8px 0 0;
  line-height: 1.6;
  color: #57606a;
}

.tone-success {
  border-color: rgba(66, 129, 94, 0.28);
}

.tone-warning {
  border-color: rgba(183, 132, 58, 0.28);
}

.tone-danger {
  border-color: rgba(166, 69, 69, 0.28);
}
</style>
