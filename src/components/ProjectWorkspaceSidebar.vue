<script setup>
import { computed } from 'vue';

const props = defineProps({
  project: {
    type: Object,
    default: null,
  },
  selectedChapterId: {
    type: String,
    default: '',
  },
});

const selectedChapter = computed(() => (
  props.project?.chapters?.find((chapter) => chapter.id === props.selectedChapterId)
  ?? null
));

const writtenChapterCount = computed(() => (
  props.project?.chapters?.filter((chapter) => chapter.exists).length ?? 0
));

const previewWordCount = computed(() => (
  normalizedPreviewContent.value.replace(/\s+/g, '').length
));

const normalizedPreviewContent = computed(() => {
  const raw = String(selectedChapter.value?.content ?? '').replace(/\r\n/g, '\n').trim();
  if (!raw) {
    return '';
  }

  const lines = raw.split('\n');
  if (/^#\s+/.test(lines[0])) {
    lines.shift();
  }

  return lines.join('\n').trim();
});

const chapterStatusLabel = computed(() => (
  selectedChapter.value?.exists ? '已有正文' : '待写章节'
));
</script>

<template>
  <aside class="workspace-sidebar">
    <section
      v-if="selectedChapter"
      class="panel chapter-preview-panel"
      data-testid="chapter-preview-panel"
    >
      <div class="panel-header">
        <div class="panel-header-copy">
          <p class="eyebrow">正文预览</p>
          <h2>{{ selectedChapter.title }}</h2>
        </div>
        <span class="chapter-summary">已写 {{ writtenChapterCount }} / {{ project?.target_chapters }} 章</span>
      </div>

      <div class="preview-meta">
        <span>第 {{ selectedChapter.index }} 章</span>
        <span>{{ chapterStatusLabel }}</span>
        <span>{{ previewWordCount }} 字</span>
      </div>

      <article class="article-preview">
        <p
          v-if="normalizedPreviewContent"
          class="article-preview-content"
        >
          {{ normalizedPreviewContent }}
        </p>
        <p
          v-else
          class="empty-copy"
        >
          这一章还没有正文。生成完成后，这里会自动显示；也可以从左侧章节列表点进来看。
        </p>
      </article>
    </section>
  </aside>
</template>

<style scoped>
.workspace-sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  border: 1px solid #d8dee4;
  border-radius: 16px;
  padding: 16px;
  background: #f8fbff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.chapter-preview-panel {
  gap: 14px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.panel-header-copy {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.eyebrow {
  margin: 0;
  color: #667085;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  color: #1f2328;
  font-size: 18px;
  line-height: 1.35;
}

.chapter-summary,
.preview-meta span {
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.84);
  color: #5c6470;
  font-size: 11px;
  white-space: nowrap;
  border: 1px solid rgba(215, 220, 226, 0.9);
}

.preview-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.article-preview {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border-radius: 14px;
  padding: 18px;
  background: #ffffff;
  border: 1px solid rgba(224, 228, 233, 0.92);
}

.article-preview-content,
.empty-copy {
  margin: 0;
  color: #475467;
  font-size: 14px;
  line-height: 2;
  white-space: pre-wrap;
}

.empty-copy {
  color: #7a8491;
}
</style>
