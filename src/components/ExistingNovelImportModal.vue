<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { arrayBufferToBase64 } from '../lib/importFiles.js';

const MAX_FILE_BYTES = 30 * 1024 * 1024;
const ALLOWED_FILE_SUFFIX = '.txt';

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  isSubmitting: {
    type: Boolean,
    default: false,
  },
  result: {
    type: Object,
    default: null,
  },
});

const emit = defineEmits(['close', 'submit']);

const fileInput = ref(null);
const fileError = ref('');
const form = reactive({
  name: '',
  genre: '',
  target_chapters: '',
  target_words: '',
  content: '',
  source_filename: '',
  content_base64: '',
});

const hasSource = computed(() => form.content.trim().length > 0 || form.content_base64.length > 0);
const canSubmit = computed(() => !props.isSubmitting && form.name.trim().length > 0 && hasSource.value);
const report = computed(() => props.result?.report ?? null);

function resetForm() {
  form.name = '';
  form.genre = '';
  form.target_chapters = '';
  form.target_words = '';
  form.content = '';
  form.source_filename = '';
  form.content_base64 = '';
  fileError.value = '';
  if (fileInput.value) {
    fileInput.value.value = '';
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen && !props.result) {
      resetForm();
    }
  },
);

function numericValue(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : undefined;
}

async function handleFileSelected(event) {
  const input = event?.target;
  const file = input?.files?.[0];
  fileError.value = '';
  form.content_base64 = '';
  form.source_filename = '';
  if (!file) {
    return;
  }
  if (!file.name.toLowerCase().endsWith(ALLOWED_FILE_SUFFIX)) {
    fileError.value = '旧稿文件只支持 .txt，请转换后再导入或直接粘贴正文';
    if (fileInput.value) {
      fileInput.value.value = '';
    }
    return;
  }
  if (file.size > MAX_FILE_BYTES) {
    fileError.value = '文件超过 30MB，请先分成单卷或复制正文导入';
    if (fileInput.value) {
      fileInput.value.value = '';
    }
    return;
  }

  try {
    const buffer = await file.arrayBuffer();
    if (!buffer || buffer.byteLength === 0) {
      fileError.value = '文件为空';
      return;
    }
    form.source_filename = file.name;
    form.content_base64 = arrayBufferToBase64(buffer);
    if (!form.name.trim()) {
      form.name = file.name.replace(/\.[^.]+$/, '').trim().slice(0, 80);
    }
  } catch (error) {
    fileError.value = error instanceof Error ? error.message : '文件读取失败';
  }
}

function clearFile() {
  form.source_filename = '';
  form.content_base64 = '';
  fileError.value = '';
  if (fileInput.value) {
    fileInput.value.value = '';
  }
}

function submit() {
  if (!canSubmit.value) {
    return;
  }

  emit('submit', {
    name: form.name.trim(),
    genre: form.genre.trim() || '未定题材',
    target_chapters: numericValue(form.target_chapters),
    target_words: numericValue(form.target_words),
    source_filename: form.source_filename || '粘贴文本.txt',
    content: form.content.trim(),
    content_base64: form.content.trim() ? '' : form.content_base64,
  });
}
</script>

<template>
  <div
    v-if="open"
    class="modal-overlay"
    data-testid="existing-novel-import-modal"
    @click.self="emit('close')"
  >
    <section
      class="modal-dialog takeover-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="导入已有小说"
    >
      <header class="modal-header">
        <div>
          <p class="stage-kicker">旧稿接管</p>
          <h3>导入已有小说</h3>
        </div>

        <button
          class="modal-close"
          type="button"
          @click="emit('close')"
        >
          关闭
        </button>
      </header>

      <div class="takeover-layout">
        <form
          class="takeover-form"
          @submit.prevent="submit"
        >
          <label>
            <span>作品名</span>
            <input
              v-model="form.name"
              data-testid="existing-novel-name-input"
              maxlength="80"
              placeholder="例如：雾港夜航"
              type="text"
            >
          </label>

          <div class="takeover-grid">
            <label>
              <span>题材</span>
              <input
                v-model="form.genre"
                maxlength="40"
                placeholder="未定题材"
                type="text"
              >
            </label>

            <label>
              <span>预计总章数</span>
              <input
                v-model="form.target_chapters"
                max="1000"
                min="1"
                placeholder="留空自动估算"
                type="number"
              >
            </label>

            <label>
              <span>预计总字数</span>
              <input
                v-model="form.target_words"
                max="2000000"
                min="1000"
                placeholder="留空自动估算"
                type="number"
              >
            </label>
          </div>

          <label>
            <span>粘贴正文</span>
            <textarea
              v-model="form.content"
              data-testid="existing-novel-content-input"
              placeholder="从第一章开始粘贴旧稿正文"
              rows="9"
            ></textarea>
          </label>

          <div class="takeover-file-row">
            <input
              ref="fileInput"
              accept=".txt"
              class="visually-hidden"
              data-testid="existing-novel-file-input"
              type="file"
              @change="handleFileSelected"
            >
            <button
              class="secondary-button"
              title="旧稿文件仅支持 .txt，也可以直接粘贴正文"
              type="button"
              @click="fileInput?.click()"
            >
              选择旧稿文件
            </button>
            <span
              v-if="form.source_filename"
              class="takeover-file-name"
            >
              {{ form.source_filename }}
            </span>
            <button
              v-if="form.source_filename"
              class="takeover-link-button"
              type="button"
              @click="clearFile"
            >
              移除
            </button>
          </div>

          <p
            v-if="fileError"
            class="takeover-error"
          >
            {{ fileError }}
          </p>

          <div class="takeover-actions">
            <button
              class="secondary-button"
              type="button"
              @click="emit('close')"
            >
              取消
            </button>
            <button
              :disabled="!canSubmit"
              class="secondary-button takeover-submit"
              data-testid="existing-novel-submit-button"
              type="submit"
            >
              {{ isSubmitting ? '接管中…' : '开始接管' }}
            </button>
          </div>
        </form>

        <aside class="takeover-report">
          <template v-if="report">
            <h4>接管报告</h4>
            <dl>
              <div>
                <dt>章节</dt>
                <dd>{{ report.applied_chapter_count }} / {{ report.target_chapters }}</dd>
              </div>
              <div>
                <dt>置信度</dt>
                <dd>{{ Math.round((report.confidence ?? 0) * 100) }}%</dd>
              </div>
              <div v-if="report.next_chapter_index">
                <dt>下一章</dt>
                <dd>第 {{ report.next_chapter_index }} 章</dd>
              </div>
            </dl>

            <section
              v-if="report.last_chapter_tail"
              class="report-section"
            >
              <strong>最近结尾</strong>
              <p>{{ report.last_chapter_tail }}</p>
            </section>

            <section
              v-if="report.warnings?.length"
              class="report-section"
            >
              <strong>需要确认</strong>
              <ul>
                <li
                  v-for="item in report.warnings.slice(0, 6)"
                  :key="item"
                >
                  {{ item }}
                </li>
              </ul>
            </section>

            <section
              v-if="report.chapters?.length"
              class="report-section report-chapter-list"
            >
              <strong>章节识别</strong>
              <div>
                <span
                  v-for="chapter in report.chapters.slice(0, 12)"
                  :key="chapter.index"
                >
                  第 {{ chapter.index }} 章 · {{ chapter.character_count }} 字
                </span>
              </div>
            </section>
          </template>

          <template v-else>
            <h4>处理内容</h4>
            <ul>
              <li>按章节标题拆分旧稿</li>
              <li>文件导入只支持 .txt</li>
              <li>逐章写入项目章节</li>
              <li>生成接管报告和章节清单</li>
              <li>刷新本地知识库索引</li>
            </ul>
          </template>
        </aside>
      </div>
    </section>
  </div>
</template>

<style scoped>
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
  padding: 0;
  margin: -1px;
}

.takeover-dialog {
  width: min(980px, calc(100vw - 32px));
  max-height: min(760px, calc(100vh - 40px));
}

.takeover-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
  gap: 16px;
  min-height: 0;
}

.takeover-form {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.takeover-form label {
  display: grid;
  gap: 6px;
  color: #344054;
  font-size: 13px;
}

.takeover-form input,
.takeover-form textarea {
  width: 100%;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  padding: 10px 11px;
  background: #ffffff;
  color: #1f2328;
  font: inherit;
}

.takeover-form textarea {
  min-height: 220px;
  resize: vertical;
  line-height: 1.7;
}

.takeover-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}

.takeover-file-row,
.takeover-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.takeover-file-name {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #57606a;
  font-size: 13px;
}

.takeover-link-button {
  border: 0;
  padding: 0;
  background: transparent;
  color: #1d4ed8;
  cursor: pointer;
}

.takeover-submit {
  border-color: #1d4ed8;
  background: #1d4ed8;
  color: #ffffff;
}

.takeover-error {
  margin: 0;
  color: #b42318;
  font-size: 13px;
}

.takeover-report {
  display: grid;
  align-content: start;
  gap: 12px;
  min-width: 0;
  padding: 12px;
  border: 1px solid #d8e6fb;
  border-radius: 8px;
  background: #f8fbff;
  color: #344054;
}

.takeover-report h4 {
  margin: 0;
  color: #1f2328;
}

.takeover-report dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.takeover-report dl div {
  display: grid;
  gap: 4px;
  padding: 8px;
  border-radius: 8px;
  background: #ffffff;
}

.takeover-report dt {
  color: #667085;
  font-size: 12px;
}

.takeover-report dd {
  margin: 0;
  color: #1d4ed8;
  font-weight: 700;
}

.report-section {
  display: grid;
  gap: 8px;
}

.report-section p,
.report-section ul,
.takeover-report ul {
  margin: 0;
  padding-left: 18px;
  line-height: 1.6;
  font-size: 13px;
}

.report-section p {
  padding-left: 0;
}

.report-chapter-list div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.report-chapter-list span {
  border-radius: 999px;
  padding: 4px 8px;
  background: #ffffff;
  color: #57606a;
  font-size: 12px;
}

@media (max-width: 820px) {
  .takeover-layout,
  .takeover-grid {
    grid-template-columns: 1fr;
  }

  .takeover-dialog {
    max-height: calc(100vh - 24px);
    overflow: auto;
  }
}
</style>
