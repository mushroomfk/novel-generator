import { ref } from 'vue';
import { streamAgentConversation } from '../lib/api.js';

function normalizeString(value) {
  return String(value ?? '').trim();
}

function normalizeChanges(changes) {
  return Array.isArray(changes)
    ? changes.map((item) => normalizeString(item)).filter(Boolean)
    : [];
}

function normalizeArtifacts(artifacts) {
  if (!Array.isArray(artifacts)) {
    return [];
  }

  return artifacts.map((item, index) => ({
    id: normalizeString(item?.id) || `artifact-${index + 1}`,
    kind: normalizeString(item?.kind),
    title: normalizeString(item?.title) || '执行产物',
    summary: normalizeString(item?.summary),
    contentPreview: normalizeString(item?.content_preview ?? item?.contentPreview),
    metadata: item?.metadata && typeof item.metadata === 'object' ? item.metadata : {},
  }));
}

function normalizeTrace(trace, fallback = {}) {
  if (!trace || typeof trace !== 'object') {
    return {
      step: Number(fallback.step ?? 0),
      total: Number(fallback.total ?? 0),
      actionKind: normalizeString(fallback.action_kind ?? fallback.actionKind),
      label: normalizeString(fallback.label) || '执行步骤',
      taskPackKind: normalizeString(fallback.task_pack_kind ?? fallback.taskPackKind),
      status: normalizeString(fallback.status) || 'completed',
      summary: normalizeString(fallback.summary),
      changes: normalizeChanges(fallback.changes),
      artifacts: normalizeArtifacts(fallback.artifacts),
      subTasks: Array.isArray(fallback.subTasks) ? fallback.subTasks : [],
    };
  }

  return {
    step: Number(trace.step ?? fallback.step ?? 0),
    total: Number(fallback.total ?? 0),
    actionKind: normalizeString(trace.action_kind ?? fallback.action_kind ?? fallback.actionKind),
    label: normalizeString(trace.label ?? fallback.label) || '执行步骤',
    taskPackKind: normalizeString(trace.task_pack_kind ?? fallback.task_pack_kind ?? fallback.taskPackKind),
    status: normalizeString(trace.status ?? fallback.status) || 'completed',
    summary: normalizeString(trace.summary ?? fallback.summary),
    changes: normalizeChanges(trace.changes ?? fallback.changes),
    artifacts: normalizeArtifacts(fallback.artifacts),
    materialCount: typeof trace.material_count === 'number' ? trace.material_count : null,
    subTasks: Array.isArray(fallback.subTasks) ? fallback.subTasks : [],
  };
}

function normalizeResultPayload(data) {
  if (data && typeof data === 'object' && data.result && typeof data.result === 'object') {
    return data.result;
  }

  return data && typeof data === 'object' ? data : null;
}

function actionKey(step, actionKind, label) {
  return `${Number(step || 0)}:${normalizeString(actionKind)}:${normalizeString(label)}`;
}

function normalizeSubtask(data, status) {
  return {
    id: normalizeString(data?.subtask_id) || `${normalizeString(data?.role)}:${normalizeString(data?.capability)}`,
    role: normalizeString(data?.role) || '子任务',
    capability: normalizeString(data?.capability),
    parallelGroup: normalizeString(data?.parallel_group),
    status: normalizeString(data?.status) || status,
    summary: normalizeString(data?.summary ?? data?.message),
  };
}

export function useAgentSession(options = {}) {
  const running = ref(false);
  const runtimeError = ref('');
  const runtimeState = ref(null);
  const taskId = ref('');
  const sessionStatus = ref('idle');
  const timelineItems = ref([]);
  const latestResult = ref(null);
  let activeAbortController = null;

  function clearTimeline() {
    timelineItems.value = [];
  }

  function resetSession() {
    activeAbortController = null;
    runtimeError.value = '';
    runtimeState.value = null;
    taskId.value = '';
    sessionStatus.value = 'idle';
    latestResult.value = null;
    clearTimeline();
  }

  function upsertTimelineItem(item) {
    const normalizedItem = normalizeTrace(item.trace, item);
    const key = actionKey(normalizedItem.step, normalizedItem.actionKind, normalizedItem.label);
    const nextItems = [...timelineItems.value];
    const matchedIndex = nextItems.findIndex((current) => (
      actionKey(current.step, current.actionKind, current.label) === key
    ));

    if (matchedIndex >= 0) {
      nextItems[matchedIndex] = {
        ...nextItems[matchedIndex],
        ...normalizedItem,
        changes: normalizedItem.changes.length ? normalizedItem.changes : nextItems[matchedIndex].changes,
        artifacts: normalizedItem.artifacts.length ? normalizedItem.artifacts : nextItems[matchedIndex].artifacts,
        subTasks: normalizedItem.subTasks.length ? normalizedItem.subTasks : nextItems[matchedIndex].subTasks,
      };
    } else {
      nextItems.push(normalizedItem);
    }

    timelineItems.value = nextItems.sort((left, right) => left.step - right.step);
  }

  function upsertSubtask(data, status) {
    const key = actionKey(data?.step, data?.action_kind ?? data?.actionKind, data?.label);
    const subtask = normalizeSubtask(data, status);
    const nextItems = [...timelineItems.value];
    let matchedIndex = nextItems.findIndex((current) => (
      actionKey(current.step, current.actionKind, current.label) === key
    ));

    if (matchedIndex < 0) {
      nextItems.push(normalizeTrace(null, {
        step: data?.step,
        total: data?.total,
        action_kind: data?.action_kind,
        label: data?.label,
        status: 'running',
        subTasks: [],
      }));
      matchedIndex = nextItems.length - 1;
    }

    const currentItem = nextItems[matchedIndex];
    const currentSubtasks = Array.isArray(currentItem.subTasks) ? [...currentItem.subTasks] : [];
    const subtaskIndex = currentSubtasks.findIndex((item) => item.id === subtask.id);
    if (subtaskIndex >= 0) {
      currentSubtasks[subtaskIndex] = {
        ...currentSubtasks[subtaskIndex],
        ...subtask,
        summary: subtask.summary || currentSubtasks[subtaskIndex].summary,
      };
    } else {
      currentSubtasks.push(subtask);
    }
    nextItems[matchedIndex] = {
      ...currentItem,
      subTasks: currentSubtasks,
    };
    timelineItems.value = nextItems.sort((left, right) => left.step - right.step);
  }

  function handleStructuredEvent(eventName, data) {
    if (!data || typeof data !== 'object') {
      return;
    }

    if (normalizeString(data.task_id)) {
      taskId.value = normalizeString(data.task_id);
    }

    if (eventName === 'session_started') {
      sessionStatus.value = 'running';
      return;
    }

    if (eventName === 'plan_confirm_required') {
      sessionStatus.value = 'waiting_confirmation';
      return;
    }

    if (eventName === 'action_started') {
      upsertTimelineItem({
        step: data.step,
        total: data.total,
        action_kind: data.action_kind,
        label: data.label,
        task_pack_kind: data.task_pack_kind,
        status: 'running',
      });
      return;
    }

    if (eventName === 'action_result') {
      upsertTimelineItem({
        step: data.step,
        total: data.total,
        action_kind: data.action_kind,
        label: data.label,
        task_pack_kind: data.task_pack_kind,
        status: 'completed',
        trace: data.trace,
        changes: data.changes,
        artifacts: data.artifacts,
      });
      return;
    }

    if (eventName === 'action_failed') {
      upsertTimelineItem({
        step: data.step,
        total: data.total,
        action_kind: data.action_kind,
        label: data.label,
        task_pack_kind: data.task_pack_kind,
        status: 'failed',
        summary: normalizeString(data.message) || '执行失败',
      });
      runtimeError.value = normalizeString(data.message) || runtimeError.value;
      return;
    }

    if (eventName === 'subtask_started') {
      upsertSubtask(data, 'running');
      return;
    }

    if (eventName === 'subtask_result') {
      upsertSubtask(data, 'completed');
      return;
    }

    if (eventName === 'subtask_failed') {
      upsertSubtask(data, 'failed');
      return;
    }

    if (eventName === 'state_updated' && data.state) {
      runtimeState.value = data.state;
      return;
    }

    if (eventName === 'project_updated' && data.project_detail && typeof options.onProjectUpdated === 'function') {
      options.onProjectUpdated(data.project_detail);
      return;
    }

    if (eventName === 'session_result') {
      const result = normalizeResultPayload(data);
      latestResult.value = result;
      if (result?.state) {
        runtimeState.value = result.state;
      }
      if (result?.project_detail && typeof options.onProjectUpdated === 'function') {
        options.onProjectUpdated(result.project_detail);
      }
      return;
    }

    if (eventName === 'session_error') {
      runtimeError.value = normalizeString(data.message) || '处理失败';
      sessionStatus.value = 'failed';
      return;
    }

    if (eventName === 'session_finished') {
      sessionStatus.value = normalizeString(data.status) || 'completed';
    }
  }

  function handleLegacyEvent(eventName, data) {
    if (!data || typeof data !== 'object') {
      return;
    }

    if (eventName === 'started') {
      taskId.value = normalizeString(data.task_id);
      sessionStatus.value = 'running';
      return;
    }

    if (eventName === 'progress') {
      upsertTimelineItem({
        step: data.step,
        total: data.total,
        label: data.message,
        status: 'running',
      });
      return;
    }

    if (eventName === 'result') {
      const result = normalizeResultPayload(data);
      latestResult.value = result;
      if (result?.state) {
        runtimeState.value = result.state;
      }
      if (result?.project_detail && typeof options.onProjectUpdated === 'function') {
        options.onProjectUpdated(result.project_detail);
      }
      return;
    }

    if (eventName === 'error') {
      runtimeError.value = normalizeString(data.message) || '处理失败';
      sessionStatus.value = 'failed';
      return;
    }

    if (eventName === 'done') {
      sessionStatus.value = normalizeString(data.status) || 'completed';
    }
  }

  function handleEvent(event) {
    const eventName = normalizeString(event?.event) || 'message';
    const data = event?.data;
    if (eventName.startsWith('session_') || eventName.startsWith('action_') || eventName.startsWith('subtask_') || eventName === 'plan_confirm_required' || eventName === 'state_updated' || eventName === 'project_updated') {
      handleStructuredEvent(eventName, data);
      return;
    }

    handleLegacyEvent(eventName, data);
  }

  function stopSession() {
    if (!running.value || !activeAbortController) {
      return false;
    }

    sessionStatus.value = 'cancelling';
    runtimeError.value = '';
    activeAbortController.abort();
    return true;
  }

  async function runAgentSession(payload) {
    resetSession();
    running.value = true;
    sessionStatus.value = 'running';
    activeAbortController = new AbortController();

    try {
      await streamAgentConversation(payload, handleEvent, {
        signal: activeAbortController.signal,
      });
      return latestResult.value;
    } catch (error) {
      if (error?.name === 'AbortError' || activeAbortController?.signal?.aborted) {
        sessionStatus.value = 'cancelled';
        runtimeError.value = '';
        return null;
      }

      runtimeError.value = error instanceof Error ? error.message : '处理失败';
      sessionStatus.value = 'failed';
      throw error;
    } finally {
      running.value = false;
      activeAbortController = null;
    }
  }

  return {
    running,
    runtimeError,
    runtimeState,
    taskId,
    sessionStatus,
    timelineItems,
    latestResult,
    resetSession,
    clearTimeline,
    stopSession,
    runAgentSession,
  };
}
