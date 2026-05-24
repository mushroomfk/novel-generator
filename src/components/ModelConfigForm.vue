<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { updateModelConfig } from '../lib/api.js';

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
    temperature: 0.8,
  },
  embedding: {
    provider: 'aliyun-bailian',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_key: '',
    model_name: 'text-embedding-v4',
    dimensions: '',
    retrieval_k: 6,
    batch_size: 8,
  },
  review_model: {
    enabled: false,
    provider: 'openai-compatible',
    base_url: '',
    api_key: '',
    model_name: '',
    max_tokens: 1800,
    temperature: 0.2,
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
const message = ref('');
const customEmbeddingEnabled = ref(false);

function inferModelFamily(model) {
  const baseUrl = String(model?.base_url ?? '').trim().toLowerCase();
  const modelName = String(model?.model_name ?? '').trim().toLowerCase();

  if (baseUrl.includes('dashscope.aliyuncs.com')) {
    return 'aliyun';
  }
  if (baseUrl.includes('ark.cn-beijing.volces.com')) {
    return 'volcengine';
  }
  if (baseUrl.includes('api.openai.com')) {
    return 'openai-compatible';
  }

  if (modelName.startsWith('qwen')) {
    return 'aliyun';
  }
  if (modelName.startsWith('doubao-')) {
    return 'volcengine';
  }
  if (modelName.startsWith('gpt-') || modelName.startsWith('text-embedding-')) {
    return 'openai-compatible';
  }

  return '';
}

function inferEmbeddingConfig(model, fallback) {
  const family = inferModelFamily(model);
  const apiKey = String(model?.api_key ?? '').trim() || String(fallback?.api_key ?? '').trim();

  if (family === 'aliyun') {
    return {
      provider: 'aliyun-bailian',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      api_key: apiKey,
      model_name: 'text-embedding-v4',
      dimensions: 2048,
      retrieval_k: fallback?.retrieval_k ?? 6,
      batch_size: fallback?.batch_size ?? 8,
    };
  }

  if (family === 'volcengine') {
    return {
      provider: 'volcengine-ark',
      base_url: 'https://ark.cn-beijing.volces.com/api/coding/v3',
      api_key: apiKey,
      model_name: 'doubao-embedding-vision',
      dimensions: null,
      retrieval_k: fallback?.retrieval_k ?? 6,
      batch_size: fallback?.batch_size ?? 8,
    };
  }

  if (family === 'openai-compatible') {
    return {
      provider: 'openai-compatible',
      base_url: String(model?.base_url ?? '').trim() || 'https://api.openai.com/v1',
      api_key: apiKey,
      model_name: 'text-embedding-3-small',
      dimensions: null,
      retrieval_k: fallback?.retrieval_k ?? 6,
      batch_size: fallback?.batch_size ?? 8,
    };
  }

  return {
    ...fallback,
    dimensions: fallback?.dimensions ?? null,
  };
}

const autoEmbeddingFamily = computed(() => inferModelFamily(form.model));
const autoEmbeddingConfig = computed(() => inferEmbeddingConfig(form.model, form.embedding));

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

function sameEmbeddingConfig(left, right) {
  const normalizedLeft = normalizeEmbeddingPayload(left ?? {});
  const normalizedRight = normalizeEmbeddingPayload(right ?? {});
  return [
    'provider',
    'base_url',
    'api_key',
    'model_name',
    'dimensions',
    'retrieval_k',
    'batch_size',
  ].every((key) => String(normalizedLeft[key] ?? '') === String(normalizedRight[key] ?? ''));
}

watch(
  () => props.config,
  (nextConfig) => {
    if (!nextConfig) {
      return;
    }

    Object.assign(form.model, nextConfig.model ?? {});
    Object.assign(form.embedding, {
      ...form.embedding,
      ...(nextConfig.embedding ?? {}),
      dimensions: nextConfig.embedding?.dimensions ?? '',
    });
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
    customEmbeddingEnabled.value = !sameEmbeddingConfig(
      form.embedding,
      inferEmbeddingConfig(form.model, form.embedding),
    );
  },
  { immediate: true },
);

function applyModelPreset(preset) {
  Object.assign(form.model, {
    ...form.model,
    ...preset.config,
  });
  message.value = `已填入 ${preset.label} 整套预设，知识检索会自动跟随。`;
}

async function save() {
  isSaving.value = true;
  message.value = '';

  try {
    const embeddingPayload = customEmbeddingEnabled.value
      ? normalizeEmbeddingPayload(form.embedding)
      : normalizeEmbeddingPayload(autoEmbeddingConfig.value);
    await updateModelConfig({
      model: { ...form.model },
      embedding: embeddingPayload,
      review_model: { ...form.review_model },
      chapter_auto_repair: { ...form.chapter_auto_repair },
      model_runtime: { ...form.model_runtime },
    });
    message.value = '写作设置已保存';
    emit('updated');
  } catch (error) {
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
          <p class="accordion-label">高级设置</p>
          <h3>{{ form.model.model_name }}</h3>
          <p class="accordion-helper">{{ form.model.provider }} · 知识检索会自动跟随当前服务商</p>
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
          <small class="field-helper">保存在本机配置里；留空时 backend 会回退到 `NOVEL_MODEL_API_KEY`、`DASHSCOPE_API_KEY`、`ARK_API_KEY` 等环境变量。</small>
        </label>

        <div class="grid two-columns">
          <label>
            <span>单次回复长度</span>
            <input
              v-model.number="form.model.max_tokens"
              min="256"
              max="64000"
              step="256"
              type="number"
            />
          </label>

          <label>
            <span>创意发散度</span>
            <input
              v-model.number="form.model.temperature"
              min="0"
              max="2"
              step="0.1"
              type="number"
            />
          </label>
        </div>

        <div class="section-label">
          Embedding / RAG
        </div>
        <label class="checkbox-field">
          <input
            v-model="customEmbeddingEnabled"
            type="checkbox"
          />
          单独设置 Embedding
        </label>
        <div class="auto-panel">
          <p class="auto-title">
            {{ customEmbeddingEnabled ? form.embedding.model_name : autoEmbeddingConfig.model_name }}
          </p>
          <p class="auto-copy">
            {{
              customEmbeddingEnabled
                ? '知识检索会使用下面单独填写的 Embedding 配置。'
                : autoEmbeddingFamily === 'aliyun'
                  ? '当前默认使用阿里的 Embedding 配置。'
                  : autoEmbeddingFamily === 'volcengine'
                    ? '当前默认使用豆包的 Embedding 配置。'
                    : autoEmbeddingFamily === 'openai-compatible'
                      ? '当前默认使用 OpenAI-compatible 的 Embedding 配置。'
                      : '当前服务商没有命中内置整套预设，会沿用现有 Embedding 配置。'
            }}
          </p>
          <p class="auto-copy">服务商：{{ customEmbeddingEnabled ? form.embedding.provider : autoEmbeddingConfig.provider }}</p>
          <p class="auto-copy">接口地址：{{ customEmbeddingEnabled ? form.embedding.base_url : autoEmbeddingConfig.base_url }}</p>
          <p class="field-helper">默认跟随当前写作模型；勾选后可以为知识检索填写独立模型、接口地址和 API Key。</p>
        </div>
        <div
          v-if="customEmbeddingEnabled"
          class="embedding-fields"
        >
          <div class="grid two-columns">
            <label>
              <span>Embedding 服务商</span>
              <input v-model="form.embedding.provider" />
            </label>

            <label>
              <span>Embedding 模型</span>
              <input v-model="form.embedding.model_name" />
            </label>
          </div>

          <label>
            <span>Embedding 接口地址</span>
            <input v-model="form.embedding.base_url" />
          </label>

          <label>
            <span>Embedding API Key</span>
            <input
              v-model="form.embedding.api_key"
              autocomplete="off"
              placeholder="留空则走环境变量"
              type="password"
            />
          </label>

          <div class="grid three-columns">
            <label>
              <span>向量维度</span>
              <input
                v-model="form.embedding.dimensions"
                min="64"
                max="4096"
                placeholder="留空则不传"
                type="number"
              />
            </label>

            <label>
              <span>检索数量</span>
              <input
                v-model.number="form.embedding.retrieval_k"
                min="1"
                max="20"
                type="number"
              />
            </label>

            <label>
              <span>批量大小</span>
              <input
                v-model.number="form.embedding.batch_size"
                min="1"
                max="32"
                type="number"
              />
            </label>
          </div>
        </div>

        <div class="section-label">
          自学习审查模型
        </div>
        <label class="checkbox-field">
          <input
            v-model="form.review_model.enabled"
            type="checkbox"
          />
          启用第二审查模型
        </label>
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
          <small class="field-helper">环境变量 `NOVEL_REVIEW_MODEL_API_KEY`、`NOVEL_REVIEW_MODEL_BASE_URL`、`NOVEL_REVIEW_MODEL_NAME` 的优先级高于这里保存的配置。</small>
        </label>
        <div class="grid two-columns">
          <label>
            <span>审查回复长度</span>
            <input
              v-model.number="form.review_model.max_tokens"
              min="256"
              max="16000"
              step="256"
              type="number"
            />
          </label>
          <label>
            <span>审查温度</span>
            <input
              v-model.number="form.review_model.temperature"
              min="0"
              max="2"
              step="0.1"
              type="number"
            />
          </label>
        </div>

        <div class="section-label">
          章节核验自动修订
        </div>
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
        <small class="field-helper">状态为 risk 会直接触发；其他状态低于触发分数时触发。建议最多 1 到 2 轮，避免正文偏离原章节目标。</small>

        <div class="section-label">
          模型运行调度
        </div>
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
            <span>失败冷却秒数</span>
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
        <small class="field-helper">默认主模型和检索都设为 1；章节候选设为标准时会避免一次续写放大成多路模型请求。</small>

        <p
          v-if="message"
          class="message"
        >
          {{ message }}
        </p>

        <button
          :disabled="isSaving"
          type="submit"
        >
          {{ isSaving ? '保存中…' : '保存写作设置' }}
        </button>
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
  border-radius: 16px;
  background: #f8fbff;
  padding: 14px;
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

.embedding-fields {
  display: grid;
  gap: 14px;
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

@media (max-width: 720px) {
  .two-columns,
  .three-columns {
    grid-template-columns: 1fr;
  }
}
</style>
