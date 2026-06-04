import { ref } from 'vue';
import {
  getAgentWorkflowRun,
  interruptAgentWorkflowRun,
  streamAgentConversation,
} from '../lib/api.js';

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

function normalizeWorkflowTimelineStatus(status) {
  const normalized = normalizeString(status).toUpperCase();
  if (normalized === 'SUCCEEDED') {
    return 'completed';
  }
  if (normalized === 'FAILED' || normalized === 'BLOCKED' || normalized === 'TIMED_OUT' || normalized === 'STALLED') {
    return 'failed';
  }
  if (normalized === 'CANCELLED') {
    return 'cancelled';
  }
  return 'running';
}

function normalizeWorkflowSessionStatus(status) {
  const normalized = normalizeString(status).toUpperCase();
  if (normalized === 'SUCCEEDED') {
    return 'completed';
  }
  if (normalized === 'CANCELLED') {
    return 'cancelled';
  }
  if (normalized === 'CANCELLING') {
    return 'cancelling';
  }
  if (normalized === 'FAILED' || normalized === 'BLOCKED' || normalized === 'TIMED_OUT' || normalized === 'STALLED' || normalized === 'MISSING') {
    return 'failed';
  }
  if (normalized === 'RUNNING') {
    return 'disconnected';
  }
  return normalized.toLowerCase() || 'idle';
}

function workflowRunToTimelineItems(run) {
  const actions = Array.isArray(run?.actions) ? run.actions : [];
  const total = actions.length;
  return actions
    .map((action) => normalizeTrace(null, {
      step: action?.step,
      total,
      action_kind: action?.kind,
      label: action?.label,
      task_pack_kind: action?.task_pack_kind,
      status: normalizeWorkflowTimelineStatus(action?.status),
      summary: normalizeString(action?.message),
      subTasks: Array.isArray(action?.subtasks)
        ? action.subtasks.map((item) => ({
          id: normalizeString(item?.subtask_id) || `${normalizeString(item?.role)}:${normalizeString(item?.capability)}`,
          role: normalizeString(item?.role) || '子任务',
          capability: normalizeString(item?.capability),
          parallelGroup: normalizeString(item?.parallel_group),
          status: normalizeWorkflowTimelineStatus(item?.status),
          summary: normalizeString(item?.summary),
        }))
        : [],
    }))
    .sort((left, right) => left.step - right.step);
}

export function useAgentSession(options = {}) {
  const running = ref(false);
  const runtimeError = ref('');
  const runtimeState = ref(null);
  const taskId = ref('');
  const sessionStatus = ref('idle');
  const recoveryStatus = ref('idle');
  const timelineItems = ref([]);
  const latestResult = ref(null);
  let activeAbortController = null;
  let activeProjectId = '';

  function clearTimeline() {
    timelineItems.value = [];
  }

  function resetSession() {
    activeAbortController = null;
    activeProjectId = '';
    runtimeError.value = '';
    runtimeState.value = null;
    taskId.value = '';
    sessionStatus.value = 'idle';
    recoveryStatus.value = 'idle';
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

  function applyWorkflowRun(run) {
    if (!run || typeof run !== 'object') {
      return null;
    }
    const nextTaskId = normalizeString(run.task_id);
    if (nextTaskId) {
      taskId.value = nextTaskId;
    }
    timelineItems.value = workflowRunToTimelineItems(run);
    sessionStatus.value = normalizeWorkflowSessionStatus(run.status);
    if (sessionStatus.value === 'failed') {
      runtimeError.value = normalizeString(run.message) || runtimeError.value || '执行状态异常。';
    }
    return run;
  }

  async function recoverSession(projectId, recoveryTaskId = taskId.value) {
    const normalizedProjectId = normalizeString(projectId);
    const normalizedTaskId = normalizeString(recoveryTaskId);
    if (!normalizedProjectId || !normalizedTaskId) {
      return null;
    }
    recoveryStatus.value = 'loading';
    try {
      const run = await getAgentWorkflowRun(normalizedProjectId, normalizedTaskId);
      recoveryStatus.value = 'loaded';
      return applyWorkflowRun(run);
    } catch (error) {
      recoveryStatus.value = 'failed';
      runtimeError.value = error instanceof Error ? error.message : '执行状态读取失败。';
      return null;
    }
  }

  function stopSession() {
    if (!running.value && !activeAbortController) {
      return false;
    }

    sessionStatus.value = 'cancelling';
    runtimeError.value = '';
    const projectId = activeProjectId;
    const currentTaskId = taskId.value;
    if (projectId && currentTaskId) {
      void interruptAgentWorkflowRun(projectId, currentTaskId)
        .then((run) => {
          applyWorkflowRun(run);
        })
        .catch((error) => {
          runtimeError.value = error instanceof Error ? error.message : '停止请求发送失败。';
        });
    }
    if (activeAbortController) {
      activeAbortController.abort();
    }
    return true;
  }

  async function runAgentSession(payload) {
    resetSession();
    running.value = true;
    sessionStatus.value = 'running';
    activeProjectId = normalizeString(payload?.project_id);
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
      if (activeProjectId && taskId.value) {
        const recovered = await recoverSession(activeProjectId, taskId.value);
        if (recovered) {
          if (sessionStatus.value === 'disconnected') {
            runtimeError.value = '连接已断开，已读取当前 workflow 状态。';
          } else if (sessionStatus.value === 'completed' || sessionStatus.value === 'cancelled') {
            runtimeError.value = '';
          }
          return null;
        }
      }
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
    recoveryStatus,
    timelineItems,
    latestResult,
    resetSession,
    clearTimeline,
    recoverSession,
    stopSession,
    runAgentSession,
  };
}
