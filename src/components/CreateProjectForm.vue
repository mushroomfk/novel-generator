<script setup>
import { computed, reactive, ref } from 'vue';
import { createProject } from '../lib/api.js';

defineProps({
  hasProjects: {
    type: Boolean,
    default: false,
  },
  forceOpen: {
    type: Boolean,
    default: false,
  },
  showSummary: {
    type: Boolean,
    default: true,
  },
});

const emit = defineEmits(['created']);

const form = reactive({
  name: '',
  base_path: '',
});

const isSubmitting = ref(false);
const errorMessage = ref('');
const trimmedName = computed(() => form.name.trim());
const isSubmitDisabled = computed(() => isSubmitting.value || !trimmedName.value);

function normalizedPayload() {
  if (!trimmedName.value) {
    errorMessage.value = '先填作品名';
    return null;
  }

  return {
    name: trimmedName.value,
    base_path: form.base_path.trim() || undefined,
  };
}

async function submit() {
  errorMessage.value = '';
  const payload = normalizedPayload();
  if (!payload) {
    return;
  }

  isSubmitting.value = true;

  try {
    const summary = await createProject(payload);

    form.name = '';
    form.base_path = '';
    emit('created', summary);
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : '创建项目失败';
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <section class="panel">
    <details
      v-if="showSummary"
      :open="forceOpen || !hasProjects"
      class="creator-shell"
    >
      <summary class="creator-summary">
        <div>
          <p class="eyebrow">新建作品</p>
          <h2>创建一部小说</h2>
        </div>
        <span class="badge">{{ hasProjects ? '展开' : '先创建一部' }}</span>
      </summary>

      <form
        class="form"
        @submit.prevent="submit"
      >
        <label>
          <span>作品名</span>
          <input
            v-model="form.name"
            data-testid="create-project-name-input"
            maxlength="80"
            placeholder="例如：雾港夜航"
            required
          />
        </label>

        <label>
          <span>保存目录（可选）</span>
          <input
            v-model="form.base_path"
            maxlength="400"
            placeholder="留空则自动保存到本地作品库"
          />
        </label>

        <p class="helper-copy">
          这里只先建作品名。题材、章数、总字数会在下一步讨论和整书架构里一起定。
        </p>

        <p
          v-if="errorMessage"
          class="error"
        >
          {{ errorMessage }}
        </p>

        <button
          :disabled="isSubmitDisabled"
          class="submit-button"
          data-testid="create-project-submit-button"
          type="submit"
        >
          {{ isSubmitting ? '正在创建…' : '创建作品空间' }}
        </button>
      </form>
    </details>

    <form
      v-else
      class="form form-standalone"
      @submit.prevent="submit"
    >
      <label>
        <span>作品名</span>
        <input
          v-model="form.name"
          data-testid="create-project-name-input"
          maxlength="80"
          placeholder="例如：雾港夜航"
          required
        />
      </label>

      <label>
        <span>保存目录（可选）</span>
        <input
          v-model="form.base_path"
          maxlength="400"
          placeholder="留空则自动保存到本地作品库"
        />
      </label>

      <p class="helper-copy">
        这里只先建作品名。题材、章数、总字数会在下一步讨论和整书架构里一起定。
      </p>

      <p
        v-if="errorMessage"
        class="error"
      >
        {{ errorMessage }}
      </p>

      <button
        :disabled="isSubmitDisabled"
        class="submit-button"
        data-testid="create-project-submit-button"
        type="submit"
      >
        {{ isSubmitting ? '正在创建…' : '创建作品空间' }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.panel {
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid #dce6f4;
  overflow: hidden;
}

.creator-shell {
  display: grid;
}

.creator-summary {
  list-style: none;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  cursor: pointer;
}

.creator-summary::-webkit-details-marker {
  display: none;
}

.eyebrow {
  margin: 0 0 8px;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #6e7781;
}

h2 {
  margin: 0;
  font-size: 16px;
  color: #1f2328;
}

.badge {
  border-radius: 999px;
  background: #f6f8fa;
  padding: 4px 8px;
  color: #57606a;
  font-size: 11px;
  white-space: nowrap;
}

.form {
  display: grid;
  gap: 12px;
  padding: 0 12px 12px;
}

.form-standalone {
  padding-top: 16px;
}

label {
  display: grid;
  gap: 8px;
}

label > span {
  color: #57606a;
  font-size: 12px;
}

input {
  width: 100%;
  border: 1px solid #d0d7de;
  background: #ffffff;
  border-radius: 14px;
  padding: 11px 12px;
  color: #1f2328;
  font-size: 13px;
}

.helper-copy {
  margin: 0;
  border-radius: 12px;
  padding: 10px 12px;
  background: #f8fbff;
  color: #57606a;
  font-size: 12px;
  line-height: 1.7;
}

.error {
  margin: 0;
  color: #a24646;
}

.submit-button {
  border: 0;
  border-radius: 999px;
  padding: 10px 14px;
  background: #1d4ed8;
  color: #ffffff;
  font-weight: 700;
  cursor: pointer;
  font-size: 12px;
}

.submit-button:disabled {
  opacity: 0.7;
  cursor: wait;
}
</style>
