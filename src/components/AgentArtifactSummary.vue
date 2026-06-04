<script setup>
const props = defineProps({
  artifacts: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(['open-obsidian-maintenance']);

function compactText(value, limit = 88) {
  const normalized = String(value ?? '').trim().replace(/\s+/g, ' ');
  if (!normalized) {
    return '';
  }

  return normalized.length > limit ? `${normalized.slice(0, limit)}…` : normalized;
}

function artifactKindLabel(kind) {
  const normalized = String(kind ?? '').trim();
  const labels = {
    architecture_workspace: '整书架构',
    chapter_content: '正文',
    workflow_report: '流程报告',
    rewrite_report: '改写结果',
    consistency_report: '一致性检查',
    discussion_summary: '讨论结果',
    knowledge_summary: '资料分析',
    continuation_plan: '后续规划',
    user_skill: '用户技能',
    learning_review: '经验候选',
    self_evolution_review: '自学习复盘',
    obsidian_maintenance: 'Obsidian 维护',
  };

  return labels[normalized] ?? (normalized || '产物');
}

function artifactMeta(item) {
  const metadata = item?.metadata && typeof item.metadata === 'object' ? item.metadata : {};
  if (item?.kind === 'obsidian_maintenance') {
    const chapterIndex = Number(metadata.chapter_index ?? 0);
    const itemCount = Number(metadata.item_count ?? 0);
    const parts = [];
    if (chapterIndex > 0) {
      parts.push(`第 ${chapterIndex} 章`);
    }
    if (itemCount > 0) {
      parts.push(`${itemCount} 条`);
    }
    return parts.join(' / ');
  }
  if (typeof metadata.chapter_index === 'number') {
    return `第 ${metadata.chapter_index} 章`;
  }
  if (typeof metadata.material_count === 'number' && metadata.material_count > 0) {
    return `资料 ${metadata.material_count} 份`;
  }
  if (typeof metadata.architecture_progress === 'number') {
    return `架构 ${metadata.architecture_progress}/5`;
  }
  if (typeof metadata.issue_count === 'number') {
    return `${metadata.issue_count} 条问题`;
  }
  if (typeof metadata.target_chapters === 'number') {
    return `${metadata.target_chapters} 章规划`;
  }
  if (item?.kind === 'user_skill') {
    return metadata.action === 'iterate' ? '已更新' : '已创建';
  }
  if (item?.kind === 'learning_review') {
    const memoryCount = Number(metadata.memory_candidate_count ?? 0);
    const skillCount = Number(metadata.skill_candidate_count ?? 0);
    const total = memoryCount + skillCount;
    return total > 0 ? `${total} 条候选` : '已记录';
  }
  if (item?.kind === 'self_evolution_review') {
    const candidateCount = Number(metadata.candidate_count ?? 0);
    const ruleCount = Number(metadata.capability_rule_count ?? 0);
    if (candidateCount > 0 || ruleCount > 0) {
      return `${candidateCount} 候选 / ${ruleCount} 规则`;
    }
    return metadata.status === 'failed' ? '失败' : '已记录';
  }
  return '';
}

function artifactCopy(item) {
  if (item?.kind === 'obsidian_maintenance' && item?.contentPreview?.trim()) {
    return compactText(item.contentPreview, 128);
  }

  if (item?.summary?.trim()) {
    return compactText(item.summary, 88);
  }

  if (item?.kind === 'chapter_content') {
    return '正文已经写回项目，左侧正文预览会同步显示。';
  }

  return compactText(item?.contentPreview, 88);
}

function isObsidianMaintenanceArtifact(item) {
  return item?.kind === 'obsidian_maintenance';
}

function openObsidianMaintenance(item) {
  emit('open-obsidian-maintenance', item);
}
</script>

<template>
  <section
    v-if="artifacts.length"
    class="artifact-list"
    data-testid="agent-artifact-list"
  >
    <article
      v-for="(item, index) in artifacts"
      :key="`${item.kind}-${item.title}-${index}`"
      class="artifact-card"
      data-testid="agent-artifact-card"
    >
      <div class="artifact-head">
        <div class="artifact-title-block">
          <strong>{{ item.title }}</strong>
          <p
            v-if="artifactCopy(item)"
            class="artifact-summary"
          >
            {{ artifactCopy(item) }}
          </p>
        </div>

        <div class="artifact-badges">
          <span class="artifact-kind">{{ artifactKindLabel(item.kind) }}</span>
          <span
            v-if="artifactMeta(item)"
            class="artifact-meta"
          >
            {{ artifactMeta(item) }}
          </span>
        </div>
      </div>

      <div
        v-if="isObsidianMaintenanceArtifact(item)"
        class="artifact-actions"
      >
        <button
          class="artifact-action-button"
          data-testid="agent-obsidian-maintenance-open-button"
          type="button"
          @click="openObsidianMaintenance(item)"
        >
          查看维护队列
        </button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.artifact-list {
  display: grid;
  gap: 8px;
}

.artifact-card {
  border: 1px solid #e8ebef;
  border-radius: 14px;
  padding: 12px 14px;
  background: #f8fbff;
}

.artifact-head,
.artifact-badges {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
}

.artifact-title-block {
  display: grid;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.artifact-title-block strong {
  color: #1f2328;
  font-size: 14px;
}

.artifact-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

.artifact-action-button {
  border: 1px solid #b8c4d5;
  border-radius: 8px;
  padding: 5px 10px;
  background: #ffffff;
  color: #1f3f63;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.35;
}

.artifact-action-button:hover {
  background: #eef5ff;
  border-color: #8aa7cc;
}

.artifact-kind,
.artifact-meta {
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  line-height: 1.3;
}

.artifact-kind {
  background: #eef2ff;
  color: #3b4ba3;
}

.artifact-meta {
  background: #f4f6f8;
  color: #66707c;
}

.artifact-summary {
  margin: 0;
  color: #5a6471;
  font-size: 13px;
  line-height: 1.7;
}
</style>
