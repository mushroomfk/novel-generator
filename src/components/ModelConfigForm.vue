<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { testModelConfig, updateModelConfig } from '../lib/api.js';

const MODEL_PRESETS = [
  {
    id: 'aliyun-qwen36-plus',
    label: '阿里 Qwen3.6 Plus',
    config: {
      provider: 'aliyun-bailian',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      model_name: 'qwen3.6-plus',
    },
  },
  {
    id: 'doubao-seed-pro',
    label: '豆包 Doubao-Seed-2.0-pro-260215',
    config: {
      provider: 'volcengine-ark',
      base_url: 'https://ark.cn-beijing.volces.com/api/v3',
      model_name: 'doubao-seed-2-0-pro-260215',
    },
  },
];

const TOKEN_BUDGET_PRESETS = [
  { value: 4096, label: '普通章节', helper: '适合短任务、资料整理和普通章节续写。' },
  { value: 8192, label: '长章节', helper: '适合多数长篇章节生成。' },
  { value: 16000, label: '超长章节', helper: '适合长上下文、批量续写和复杂修订。' },
  { value: 24000, label: '大纲到正文', helper: '适合一次携带大量设定和章节证据。' },
];

const LOCAL_EMBEDDING_CONFIG = {
  provider: 'local-fastembed',
  base_url: 'builtin://bge-small-zh-v1.5',
  api_key: '',
  model_name: 'BAAI/bge-small-zh-v1.5',
  dimensions: 512,
  retrieval_k: 6,
  batch_size: 8,
};

const props = defineProps({
  config: {
    type: Object,
    default: null,
  },
});

const emit = defineEmits(['updated']);

const form = reactive({
  model: {
    provider: 'aliyun-bailian',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_key: '',
    model_name: 'qwen3.6-plus',
    max_tokens: 8192,
  },
  review_model: {
    enabled: false,
    provider: 'openai-compatible',
    base_url: '',
    api_key: '',
    model_name: '',
    max_tokens: 1800,
  },
  chapter_auto_repair: {
    enabled: true,
    score_threshold: 65,
    max_rounds: 1,
  },
  model_runtime: {
    max_chat_concurrency: 1,
    max_retrieval_concurrency: 1,
    background_model_enabled: true,
    background_requires_idle_seconds: 90,
    chapter_candidate_mode: 'standard',
    queue_policy: 'wait',
    max_queue_size: 24,
    provider_cooldown_seconds: 1800,
  },
});

const isSaving = ref(false);
const isTesting = ref(false);
const message = ref('');
const messageTone = ref('');

const selectedTokenPreset = computed(() => (
  TOKEN_BUDGET_PRESETS.find((item) => item.value === Number(form.model.max_tokens))
  ?? TOKEN_BUDGET_PRESETS[1]
));

function normalizeDimensions(value) {
  if (value === '' || value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeEmbeddingPayload(embedding) {
  return {
    ...embedding,
    dimensions: normalizeDimensions(embedding?.dimensions),
    retrieval_k: Number(embedding?.retrieval_k) || 6,
    batch_size: Number(embedding?.batch_size) || 8,
  };
}

watch(
  () => props.config,
  (nextConfig) => {
    if (!nextConfig) {
      return;
    }

    Object.assign(form.model, nextConfig.model ?? {});
    Object.assign(form.review_model, {
      ...form.review_model,
      ...(nextConfig.review_model ?? {}),
    });
    Object.assign(form.chapter_auto_repair, {
      ...form.chapter_auto_repair,
      ...(nextConfig.chapter_auto_repair ?? {}),
    });
    Object.assign(form.model_runtime, {
      ...form.model_runtime,
      ...(nextConfig.model_runtime ?? {}),
    });
  },
  { immediate: true },
);

function applyModelPreset(preset) {
  Object.assign(form.model, {
    ...form.model,
    ...preset.config,
  });
  message.value = `已填入 ${preset.label} 预设，知识检索使用内置本地模型。`;
}

function modelPayloadFromForm() {
  return {
    provider: form.model.provider,
    base_url: form.model.base_url,
    api_key: form.model.api_key,
    model_name: form.model.model_name,
    max_tokens: Number(form.model.max_tokens) || 8192,
  };
}

function reviewModelPayloadFromForm() {
  return {
    enabled: Boolean(form.review_model.enabled),
    provider: form.review_model.provider,
    base_url: form.review_model.base_url,
    api_key: form.review_model.api_key,
    model_name: form.review_model.model_name,
    max_tokens: Number(form.review_model.max_tokens) || 1800,
  };
}

function settingsPayloadFromForm() {
  return {
    model: modelPayloadFromForm(),
    embedding: normalizeEmbeddingPayload(LOCAL_EMBEDDING_CONFIG),
    review_model: reviewModelPayloadFromForm(),
    chapter_auto_repair: { ...form.chapter_auto_repair },
    model_runtime: { ...form.model_runtime },
  };
}

function testItemText(item) {
  const statusText = item.status === 'passed'
    ? '通过'
    : item.status === 'skipped'
      ? '跳过'
      : '失败';
  return `${item.label} ${statusText}${item.message ? `：${item.message}` : ''}`;
}

async function testCurrentConfig() {
  isTesting.value = true;
  message.value = '';
  messageTone.value = '';

  try {
    const result = await testModelConfig({
      ...settingsPayloadFromForm(),
      target: 'all',
    });
    messageTone.value = result.status === 'passed' ? 'success' : result.status === 'skipped' ? '' : 'error';
    message.value = (result.items ?? []).map(testItemText).join('；') || '没有可测试的模型配置';
  } catch (error) {
    messageTone.value = 'error';
    message.value = error instanceof Error ? error.message : '模型配置测试失败';
  } finally {
    isTesting.value = false;
  }
}

async function save() {
  isSaving.value = true;
  message.value = '';
  messageTone.value = '';

  try {
    await updateModelConfig(settingsPayloadFromForm());
    message.value = '写作设置已保存';
    messageTone.value = 'success';
    emit('updated');
  } catch (error) {
    messageTone.value = 'error';
    message.value =
      error instanceof Error ? error.message : '保存写作设置失败';
  } finally {
    isSaving.value = false;
  }
}
</script>

<template>
  <section class="panel">
    <details class="settings-accordion">
      <summary class="accordion-summary">
        <div class="accordion-copy">
          <p class="accordion-label">模型设置</p>
          <h3>{{ form.model.model_name }}</h3>
          <p class="accordion-helper">{{ form.model.provider }} · 知识检索可用内置本地模型</p>
        </div>
      </summary>

      <form
        class="form"
        @submit.prevent="save"
      >
        <div class="section-label">
          写作模型
        </div>
        <div class="preset-row">
          <span class="preset-label">常用预设</span>
          <div class="preset-buttons">
            <button
              v-for="preset in MODEL_PRESETS"
              :key="preset.id"
              class="preset-button"
              type="button"
              @click="applyModelPreset(preset)"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>
        <div class="grid two-columns">
          <label>
            <span>服务商标识</span>
            <input v-model="form.model.provider" />
          </label>

          <label>
            <span>模型名称</span>
            <input v-model="form.model.model_name" />
          </label>
        </div>

        <label>
          <span>接口地址</span>
          <input v-model="form.model.base_url" />
        </label>

        <label>
          <span>API Key</span>
          <input
            v-model="form.model.api_key"
            autocomplete="off"
            placeholder="留空则走环境变量"
            type="password"
          />
          <small class="field-helper">保存在本机配置里；留空时读取 `NOVEL_MODEL_API_KEY`、`DASHSCOPE_API_KEY`、`ARK_API_KEY` 等环境变量。</small>
        </label>

        <label>
          <span>篇幅能力</span>
          <select v-model.number="form.model.max_tokens">
            <option
              v-for="preset in TOKEN_BUDGET_PRESETS"
              :key="preset.value"
              :value="preset.value"
            >
              {{ preset.label }}
            </option>
          </select>
          <small class="field-helper">{{ selectedTokenPreset.helper }}</small>
        </label>

        <div class="auto-panel smart-panel">
          <p class="auto-title">智能参数</p>
          <p class="auto-copy">写作风格参数由系统处理，避免部分模型因为不支持附加项而报错。</p>
        </div>

        <details class="advanced-group">
          <summary>第二审查模型</summary>
          <div class="advanced-body">
        <label class="checkbox-field">
          <input
            v-model="form.review_model.enabled"
            type="checkbox"
          />
          启用第二审查模型
        </label>
        <div
          v-if="form.review_model.enabled"
          class="review-fields"
        >
        <div class="grid two-columns">
          <label>
            <span>服务商标识</span>
            <input v-model="form.review_model.provider" />
          </label>
          <label>
            <span>模型名称</span>
            <input
              v-model="form.review_model.model_name"
              placeholder="例如 gpt-4.1-mini"
            />
          </label>
        </div>
        <label>
          <span>接口地址</span>
          <input
            v-model="form.review_model.base_url"
            placeholder="https://api.openai.com/v1"
          />
        </label>
        <label>
          <span>API Key</span>
          <input
            v-model="form.review_model.api_key"
            autocomplete="off"
            placeholder="留空则走 NOVEL_REVIEW_MODEL_API_KEY"
            type="password"
          />
          <small class="field-helper">环境变量 `NOVEL_REVIEW_MODEL_API_KEY`、`NOVEL_REVIEW_MODEL_BASE_URL`、`NOVEL_REVIEW_MODEL_NAME` 的优先级更高。</small>
        </label>
        </div>
          </div>
        </details>

        <details class="advanced-group">
          <summary>自动修订</summary>
          <div class="advanced-body">
        <label class="switch-row">
          <input
            v-model="form.chapter_auto_repair.enabled"
            type="checkbox"
          />
          <span>核验低分后自动修订</span>
        </label>
        <div class="grid two-columns">
          <label>
            <span>触发分数</span>
            <input
              v-model.number="form.chapter_auto_repair.score_threshold"
              min="0"
              max="100"
              step="1"
              type="number"
            />
          </label>

          <label>
            <span>最多修订轮数</span>
            <input
              v-model.number="form.chapter_auto_repair.max_rounds"
              min="0"
              max="3"
              step="1"
              type="number"
            />
          </label>
        </div>
        <small class="field-helper">状态为 risk 会直接触发；其他状态低于触发分数时触发。</small>
          </div>
        </details>

        <details class="advanced-group">
          <summary>运行调度</summary>
          <div class="advanced-body">
        <div class="grid two-columns">
          <label>
            <span>主模型并发</span>
            <input
              v-model.number="form.model_runtime.max_chat_concurrency"
              min="1"
              max="4"
              type="number"
            />
          </label>

          <label>
            <span>检索并发</span>
            <input
              v-model.number="form.model_runtime.max_retrieval_concurrency"
              min="1"
              max="4"
              type="number"
            />
          </label>
        </div>
        <label class="switch-row">
          <input
            v-model="form.model_runtime.background_model_enabled"
            type="checkbox"
          />
          <span>允许后台模型任务</span>
        </label>
        <div class="grid two-columns">
          <label>
            <span>后台空闲等待秒数</span>
            <input
              v-model.number="form.model_runtime.background_requires_idle_seconds"
              min="0"
              max="3600"
              step="5"
              type="number"
            />
          </label>

          <label>
            <span>后台失败暂停秒数</span>
            <input
              v-model.number="form.model_runtime.provider_cooldown_seconds"
              min="0"
              max="86400"
              step="60"
              type="number"
            />
          </label>
        </div>
        <div class="grid two-columns">
          <label>
            <span>章节候选模式</span>
            <select v-model="form.model_runtime.chapter_candidate_mode">
              <option value="fast">快速：少评审</option>
              <option value="standard">标准：单候选</option>
              <option value="deep">深度：多候选排队</option>
            </select>
          </label>

          <label>
            <span>队列策略</span>
            <select v-model="form.model_runtime.queue_policy">
              <option value="wait">等待</option>
              <option value="reject">忙时拒绝</option>
            </select>
          </label>
        </div>
        <label>
          <span>队列容量</span>
          <input
            v-model.number="form.model_runtime.max_queue_size"
            min="1"
            max="200"
            type="number"
          />
        </label>
        <small class="field-helper">并发过高可能触发供应商限流。</small>
          </div>
        </details>

        <p
          v-if="message"
          :class="['message', messageTone ? `message-${messageTone}` : '']"
        >
          {{ message }}
        </p>

        <div class="form-actions">
          <button
            class="secondary-action"
            :disabled="isSaving || isTesting"
            type="button"
            @click="testCurrentConfig"
          >
            {{ isTesting ? '测试中…' : '测试当前配置' }}
          </button>

          <button
            :disabled="isSaving || isTesting"
            type="submit"
          >
            {{ isSaving ? '保存中…' : '保存写作设置' }}
          </button>
        </div>
      </form>
    </details>
  </section>
</template>

<style scoped>
.panel {
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid #dce6f4;
  overflow: hidden;
}

.settings-accordion {
  display: grid;
}

.accordion-summary {
  list-style: none;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  cursor: pointer;
}

.accordion-summary::-webkit-details-marker {
  display: none;
}

.accordion-summary::after {
  content: '展开';
  display: inline-flex;
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 5px 9px;
  background: #e8f0fe;
  color: #1d4ed8;
  font-size: 12px;
  white-space: nowrap;
}

.settings-accordion[open] .accordion-summary::after {
  content: '收起';
}

.accordion-copy h3 {
  margin: 0;
  font-size: 18px;
  color: #1f2328;
}

.accordion-label {
  margin: 0 0 8px;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #6e7781;
}

.accordion-helper {
  margin: 8px 0 0;
  font-size: 13px;
  color: #57606a;
  line-height: 1.6;
}

.form {
  display: grid;
  gap: 16px;
  padding: 0 14px 14px;
}

label {
  display: grid;
  gap: 8px;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.switch-row input {
  width: 18px;
  height: 18px;
  accent-color: #2563eb;
}

label > span {
  color: #57606a;
  font-size: 13px;
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

.field-helper {
  color: #6e7781;
  font-size: 12px;
  line-height: 1.6;
}

.section-label {
  margin: 4px 0 -4px;
  color: #57606a;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.preset-row {
  display: grid;
  gap: 8px;
}

.preset-label {
  color: #57606a;
  font-size: 13px;
}

.preset-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.auto-panel {
  display: grid;
  gap: 6px;
  border: 1px solid #dce6f4;
  border-radius: 8px;
  background: #f8fbff;
  padding: 14px;
}

.smart-panel {
  background: #f6f8fa;
}

.auto-title {
  margin: 0;
  color: #1f2328;
  font-size: 16px;
  font-weight: 700;
}

.auto-copy {
  margin: 0;
  color: #57606a;
  font-size: 13px;
  line-height: 1.6;
}

.review-fields {
  display: grid;
  gap: 14px;
}

.advanced-group {
  border: 1px solid #dce6f4;
  border-radius: 8px;
  background: #ffffff;
}

.advanced-group summary {
  cursor: pointer;
  padding: 12px 14px;
  color: #1f2328;
  font-size: 13px;
  font-weight: 700;
  list-style: none;
}

.advanced-group summary::-webkit-details-marker {
  display: none;
}

.advanced-group summary::after {
  content: '+';
  float: right;
  color: #57606a;
}

.advanced-group[open] summary::after {
  content: '-';
}

.advanced-body {
  display: grid;
  gap: 14px;
  border-top: 1px solid #dce6f4;
  padding: 14px;
}

input,
select {
  width: 100%;
  border: 1px solid #d0d7de;
  background: #ffffff;
  border-radius: 10px;
  padding: 10px 12px;
  color: #1f2328;
  font-size: 13px;
}

.grid {
  display: grid;
  gap: 16px;
}

.two-columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.three-columns {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.message {
  margin: 0;
  color: #57606a;
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
}

.message-success {
  color: #166534;
}

.message-error {
  color: #b42318;
}

.preset-button {
  border: 1px solid #d0d7de;
  background: #f6f8fa;
  color: #1f2328;
  font-weight: 600;
  padding: 9px 13px;
  font-size: 13px;
}

button {
  border: 0;
  border-radius: 999px;
  padding: 11px 15px;
  background: #24292f;
  color: #ffffff;
  font-weight: 700;
  cursor: pointer;
  font-size: 13px;
}

.form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.form-actions button {
  min-width: 128px;
}

.secondary-action {
  border: 1px solid #d0d7de;
  background: #f6f8fa;
  color: #1f2328;
}

button:disabled {
  cursor: progress;
  opacity: 0.65;
}

@media (max-width: 720px) {
  .two-columns,
  .three-columns {
    grid-template-columns: 1fr;
  }
}
</style>
