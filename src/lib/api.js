import { getKnownBackendUrl, markBackendUnavailable, waitForBackendReady } from './runtime.js';

let activeBackendUrl = getKnownBackendUrl();

function unwrapEnvelope(payload) {
  if (!payload.ok || payload.data === undefined) {
    throw new Error(payload.error?.message ?? '请求失败');
  }

  return payload.data;
}

function unwrapChapterMutationEnvelope(payload) {
  return {
    detail: unwrapEnvelope(payload),
    reviewError: String(payload?.meta?.review_error ?? ''),
    selfEvolution: payload?.meta?.self_evolution ?? null,
    selfEvolutionError: String(payload?.meta?.self_evolution_error ?? ''),
  };
}

function unwrapSelfEvolutionEnvelope(payload) {
  return {
    data: unwrapEnvelope(payload),
    selfEvolution: payload?.meta?.self_evolution ?? null,
    selfEvolutionError: String(payload?.meta?.self_evolution_error ?? ''),
  };
}

async function readPayload(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return {
      ok: false,
      error: {
        message: text,
      },
    };
  }
}

function backendNetworkError(error, backendUrl) {
  if (error?.name === 'AbortError') {
    return error;
  }

  markBackendUnavailable(backendUrl);
  const message = error instanceof Error ? error.message : '';
  if (message && !/Failed to fetch|NetworkError|Load failed|fetch/i.test(message)) {
    return error;
  }

  return new Error(`本地 backend 连接失败：${backendUrl}。请确认桌面端后端已启动，或重启应用后再试。`);
}

export async function getApiBaseUrl() {
  const backendUrl = await waitForBackendReady();
  activeBackendUrl = backendUrl;
  return backendUrl;
}

async function request(path, init) {
  const backendUrl = await getApiBaseUrl();
  let response;
  try {
    response = await fetch(`${backendUrl}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (error) {
    throw backendNetworkError(error, backendUrl);
  }

  const payload = await readPayload(response);

  if (!response.ok) {
    throw new Error(payload.error?.message ?? `请求失败: ${response.status}`);
  }

  return unwrapEnvelope(payload);
}

async function requestEnvelope(path, init) {
  const backendUrl = await getApiBaseUrl();
  let response;
  try {
    response = await fetch(`${backendUrl}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (error) {
    throw backendNetworkError(error, backendUrl);
  }

  const payload = await readPayload(response);

  if (!response.ok) {
    throw new Error(payload.error?.message ?? `请求失败: ${response.status}`);
  }

  return payload;
}

function parseEventChunk(chunk) {
  let event = 'message';
  let data = '';

  for (const rawLine of chunk.split('\n')) {
    const line = rawLine.trimEnd();
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data += line.slice(5).trim();
    }
  }

  try {
    return {
      event,
      data: JSON.parse(data),
    };
  } catch {
    return {
      event,
      data,
    };
  }
}

export async function getHealth() {
  return request('/api/app/health');
}

export async function listStudioSkills() {
  return request('/api/studio/skills');
}

export async function materializeConversationSkill(payload) {
  return request('/api/studio/skills/materialize', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getSkillCurationReport() {
  return request('/api/studio/skills/curation');
}

export async function getSelfEvolutionReport(projectId) {
  const params = new URLSearchParams({
    project_id: projectId,
  });
  return request(`/api/studio/self-evolution?${params.toString()}`);
}

export async function getModelRuntime() {
  return request('/api/studio/model-runtime');
}

export async function listProjects() {
  return request('/api/projects');
}

export async function createProject(payload) {
  return request('/api/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function renameProject(projectId, payload) {
  return request(`/api/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteProject(projectId) {
  return request(`/api/projects/${projectId}`, {
    method: 'DELETE',
  });
}

export async function openProjectDirectory(projectId) {
  return request(`/api/projects/${projectId}/open-directory`, {
    method: 'POST',
  });
}

export async function getProjectDetail(projectId, options = {}) {
  const params = new URLSearchParams();
  if (options.reviewCharacters) {
    params.set('review_characters', 'true');
  }
  const query = params.toString();
  return request(`/api/projects/${projectId}${query ? `?${query}` : ''}`);
}

export async function getProjectAgentThreads(projectId) {
  return request(`/api/projects/${projectId}/agent-threads`);
}

export async function saveProjectAgentThreads(projectId, payload) {
  return request(`/api/projects/${projectId}/agent-threads`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function exportProjectBook(projectId, payload) {
  return request(`/api/projects/${projectId}/export`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function exportProjectMigrationPackage(projectId) {
  return request(`/api/projects/${projectId}/migration/export`, {
    method: 'POST',
  });
}

export async function importProjectMigrationPackage(payload) {
  return request('/api/projects/migration/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function importExistingNovel(payload) {
  return request('/api/projects/takeover/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getProjectTakeoverState(projectId) {
  return request(`/api/projects/${projectId}/takeover`);
}

export async function resumeProjectTakeover(projectId) {
  return request(`/api/projects/${projectId}/takeover/resume`, {
    method: 'POST',
  });
}

export async function updateStoryDocument(projectId, documentKey, payload) {
  return request(`/api/projects/${projectId}/documents/${documentKey}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function updateStoryDocuments(projectId, payload) {
  return request(`/api/projects/${projectId}/documents`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function updateProjectMemory(projectId, payload) {
  return request(`/api/projects/${projectId}/memory`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function runProjectDream(projectId, payload = {}) {
  return request(`/api/projects/${projectId}/dreams/run`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function promoteProjectDreamCandidates(projectId, payload) {
  return request(`/api/projects/${projectId}/dreams/promote`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getProjectSelfEvolution(projectId) {
  return request(`/api/projects/${projectId}/self-evolution`);
}

export async function updateProjectSelfEvolutionCandidate(projectId, candidateId, payload) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/candidates/${candidateId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }));
}

export async function curateProjectSelfEvolution(projectId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/curate`, {
    method: 'POST',
  }));
}

export async function runProjectSelfEvolutionRegression(projectId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/regression`, {
    method: 'POST',
  }));
}

export async function runProjectSelfEvolutionModelReview(projectId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/model-review`, {
    method: 'POST',
  }));
}

export async function updateProjectSelfEvolutionDraft(projectId, draftId, payload) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/drafts/${draftId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }));
}

export async function applyProjectSelfEvolutionDraft(projectId, draftId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/drafts/${draftId}/apply`, {
    method: 'POST',
  }));
}

export async function updateProjectSelfEvolutionSchedule(projectId, payload) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/schedule`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }));
}

export async function runProjectSelfEvolutionSchedule(projectId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/self-evolution/schedule/run`, {
    method: 'POST',
  }));
}

export async function getSkillVersions(skillId) {
  return request(`/api/studio/skills/${encodeURIComponent(skillId)}/versions`);
}

export async function exportSkillPackage(skillId) {
  return request(`/api/studio/skills/${encodeURIComponent(skillId)}/package`);
}

export async function importSkillPackage(payload) {
  return request('/api/studio/skills/import-package', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function rollbackSkillVersion(skillId, versionId) {
  return request(`/api/studio/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(versionId)}/rollback`, {
    method: 'POST',
  });
}

export async function promoteSkillToGlobal(skillId) {
  return request(`/api/studio/skills/${encodeURIComponent(skillId)}/promote-global`, {
    method: 'POST',
  });
}

export async function applyProjectArchitectureWorkspace(projectId, payload) {
  return request(`/api/projects/${projectId}/architecture/workspace`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function updateProjectChapter(projectId, chapterId, payload) {
  return unwrapChapterMutationEnvelope(await requestEnvelope(`/api/projects/${projectId}/chapters/${chapterId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }));
}

export async function refreshProjectChapterReview(projectId, chapterId, payload = {}) {
  return unwrapChapterMutationEnvelope(await requestEnvelope(`/api/projects/${projectId}/chapters/${chapterId}/review`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
}

export async function searchProjectKnowledge(projectId, query, limit = 8, options = {}) {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });
  if (Number(options.chapterIndex) > 0) {
    params.set('chapter_index', String(Number(options.chapterIndex)));
  }
  return request(`/api/projects/${projectId}/knowledge/search?${params.toString()}`);
}

export async function researchHistoricalReferences(projectId, query, limit = 8, options = {}) {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });
  if (Number(options.chapterIndex) > 0) {
    params.set('chapter_index', String(Number(options.chapterIndex)));
  }
  return request(`/api/projects/${projectId}/research/historical?${params.toString()}`);
}

export async function importProjectKnowledge(projectId, payload) {
  return request(`/api/projects/${projectId}/knowledge/import`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function importProjectKnowledgeFiles(projectId, payload) {
  return request(`/api/projects/${projectId}/knowledge/import-files`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getProjectObsidian(projectId) {
  return request(`/api/projects/${projectId}/obsidian`);
}

export async function updateProjectObsidian(projectId, payload) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }));
}

export async function syncProjectObsidian(projectId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/sync`, {
    method: 'POST',
  }));
}

export async function stageProjectObsidianMaintenance(projectId, suggestionId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/${encodeURIComponent(suggestionId)}/stage`, {
    method: 'POST',
  }));
}

export async function stageProjectObsidianMaintenanceBatch(projectId, payload = {}) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/stage-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
}

export async function publishProjectObsidianMaintenanceBatch(projectId, payload = {}) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/publish-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
}

export async function publishProjectObsidianMaintenance(projectId, suggestionId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/${encodeURIComponent(suggestionId)}/publish`, {
    method: 'POST',
  }));
}

export async function confirmProjectObsidianMaintenanceMergeBatch(projectId, payload = {}) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/confirm-merge-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
}

export async function confirmProjectObsidianMaintenanceMerge(projectId, suggestionId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/${encodeURIComponent(suggestionId)}/confirm-merge`, {
    method: 'POST',
  }));
}

export async function ignoreProjectObsidianMaintenance(projectId, suggestionId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/${encodeURIComponent(suggestionId)}/ignore`, {
    method: 'POST',
  }));
}

export async function ignoreProjectObsidianMaintenanceBatch(projectId, payload = {}) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/ignore-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
}

export async function reopenProjectObsidianMaintenance(projectId, suggestionId) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/${encodeURIComponent(suggestionId)}/reopen`, {
    method: 'POST',
  }));
}

export async function reopenProjectObsidianMaintenanceBatch(projectId, payload = {}) {
  return unwrapSelfEvolutionEnvelope(await requestEnvelope(`/api/projects/${projectId}/obsidian/maintenance/reopen-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }));
}

export async function createProjectSnapshot(projectId, payload = {}) {
  return request(`/api/projects/${projectId}/snapshots`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getProjectSnapshotDetail(projectId, snapshotId) {
  return request(`/api/projects/${projectId}/snapshots/${snapshotId}`);
}

export async function autoSaveProjectChanges(projectId) {
  return request(`/api/projects/${projectId}/autosave`, {
    method: 'POST',
  });
}

export async function restoreProjectSnapshot(projectId, snapshotId, payload = {}) {
  return request(`/api/projects/${projectId}/snapshots/${snapshotId}/restore`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getConfig() {
  return request('/api/config');
}

export async function updateModelConfig(payload) {
  return request('/api/config', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function testModelConfig(payload) {
  return request('/api/config/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getLicenseStatus() {
  return request('/api/license/validate');
}

export async function getLicenseDeviceFingerprints() {
  return request('/api/license/device-fingerprints');
}

export async function importLicense(content) {
  return request('/api/license/import', {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export async function streamArchitecture(payload, onEvent) {
  return streamRequest('/api/generate/architecture/stream', payload, onEvent);
}

export async function streamArchitectureStep(payload, onEvent) {
  return streamRequest('/api/generate/architecture/step/stream', payload, onEvent);
}

async function streamRequest(path, payload, onEvent, options = {}) {
  const backendUrl = await getApiBaseUrl();
  let response;
  try {
    response = await fetch(`${backendUrl}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: options.signal,
    });
  } catch (error) {
    throw backendNetworkError(error, backendUrl);
  }

  if (!response.ok || !response.body) {
    const payload = await readPayload(response);
    throw new Error(payload.error?.message ?? `SSE 建连失败: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');

    while (buffer.includes('\n\n')) {
      const boundary = buffer.indexOf('\n\n');
      const chunk = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);

      if (chunk.length > 0) {
        onEvent(parseEventChunk(chunk));
      }
    }
  }

  const finalChunk = buffer.trim();
  if (finalChunk.length > 0) {
    onEvent(parseEventChunk(finalChunk));
  }
}

export async function streamChapterWorkflow(payload, onEvent) {
  return streamRequest('/api/generate/chapter-workflow/stream', payload, onEvent);
}

export async function previewChapterWorkflowPrompt(payload) {
  return request('/api/generate/chapter-workflow/prompt-preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function streamBrainstorm(payload, onEvent) {
  return streamRequest('/api/studio/brainstorm/stream', payload, onEvent);
}

export async function streamAgentConversation(payload, onEvent, options = {}) {
  return streamRequest('/api/studio/agent/stream', payload, onEvent, options);
}

export async function getAgentWorkflowRun(projectId, taskId) {
  return request(`/api/studio/agent/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(taskId)}`);
}

export async function interruptAgentWorkflowRun(projectId, taskId) {
  return request(`/api/studio/agent/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(taskId)}/interrupt`, {
    method: 'POST',
  });
}

export async function streamCharacterReplica(payload, onEvent) {
  return streamRequest('/api/studio/character-replica/stream', payload, onEvent);
}

export async function listCharacterReplicaProfiles() {
  return request('/api/studio/character-replica-profiles');
}

export async function getCharacterReplicaProfile(name) {
  return request(`/api/studio/character-replica-profiles/${encodeURIComponent(name)}`);
}

export async function saveCharacterReplicaProfile(name, payload) {
  return request(`/api/studio/character-replica-profiles/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteCharacterReplicaProfile(name) {
  return request(`/api/studio/character-replica-profiles/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function streamConsistency(payload, onEvent) {
  return streamRequest('/api/studio/consistency/stream', payload, onEvent);
}

export async function streamBlueprint(payload, onEvent) {
  return streamRequest('/api/studio/blueprint/stream', payload, onEvent);
}

export async function streamChapterGenerate(payload, onEvent) {
  return streamRequest('/api/studio/chapter-generate/stream', payload, onEvent);
}

export async function previewChapterGeneratePrompt(payload) {
  return request('/api/studio/chapter-generate/prompt-preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function startChapterSegmentSession(payload) {
  return request('/api/studio/chapter-segments/start', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function streamChapterSegmentGenerate(payload, onEvent) {
  return streamRequest('/api/studio/chapter-segments/generate/stream', payload, onEvent);
}

export async function acceptChapterSegment(payload) {
  return request('/api/studio/chapter-segments/accept', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function streamChapterFinalize(payload, onEvent) {
  return streamRequest('/api/studio/chapter-finalize/stream', payload, onEvent);
}

export async function streamChapterPolish(payload, onEvent) {
  return streamRequest('/api/studio/chapter-polish/stream', payload, onEvent);
}

export async function streamChapterHumanize(payload, onEvent) {
  return streamRequest('/api/studio/chapter-humanize/stream', payload, onEvent);
}

export async function streamBatchGenerate(payload, onEvent) {
  return streamRequest('/api/studio/batch-generate/stream', payload, onEvent);
}

export async function streamContinueProject(payload, onEvent) {
  return streamRequest('/api/studio/continue-project/stream', payload, onEvent);
}

export async function streamStyleAnalyze(payload, onEvent) {
  return streamRequest('/api/studio/styles/analyze/stream', payload, onEvent);
}

export async function streamStyleAnalyzeDna(payload, onEvent) {
  return streamRequest('/api/studio/styles/analyze-dna/stream', payload, onEvent);
}

export async function streamStyleCalibrate(payload, onEvent) {
  return streamRequest('/api/studio/styles/calibrate/stream', payload, onEvent);
}

export async function streamStyleCalibrateNarrative(payload, onEvent) {
  return streamRequest('/api/studio/styles/calibrate-narrative/stream', payload, onEvent);
}

export async function streamStyleMerge(payload, onEvent) {
  return streamRequest('/api/studio/styles/merge/stream', payload, onEvent);
}

export async function getStudioLogs(tail = 200) {
  return request(`/api/studio/logs?tail=${encodeURIComponent(String(tail))}`);
}

export async function clearStudioLogs() {
  return request('/api/studio/logs', {
    method: 'DELETE',
  });
}

export async function getPromptHistory(tail = 50, search = '') {
  const params = new URLSearchParams({
    tail: String(tail),
    search,
  });
  return request(`/api/studio/prompt-history?${params.toString()}`);
}

export async function clearPromptHistory() {
  return request('/api/studio/prompt-history', {
    method: 'DELETE',
  });
}

export async function listPromptPresets() {
  return request('/api/studio/prompt-presets');
}

export async function createPromptPreset(payload) {
  return request('/api/studio/prompt-presets', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getPromptPresetDetail(name) {
  return request(`/api/studio/prompt-presets/${encodeURIComponent(name)}`);
}

export async function updatePromptPreset(name, payload) {
  return request(`/api/studio/prompt-presets/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deletePromptPreset(name) {
  return request(`/api/studio/prompt-presets/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function activatePromptPreset(name) {
  return request(`/api/studio/prompt-presets/${encodeURIComponent(name)}/activate`, {
    method: 'POST',
  });
}

export async function listXpPresets() {
  return request('/api/studio/xp-presets');
}

export async function createXpPreset(payload) {
  return request('/api/studio/xp-presets', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateXpPreset(name, payload) {
  return request(`/api/studio/xp-presets/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteXpPreset(name) {
  return request(`/api/studio/xp-presets/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function listStyles() {
  return request('/api/studio/styles');
}

export async function getStyleDetail(name) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}`);
}

export async function saveStyle(name, payload) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteStyle(name) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function rollbackStyleCalibration(name) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}/rollback-calibration`, {
    method: 'POST',
  });
}

export async function importStyleReferences(name, payload) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}/references`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function importStyleReferenceFiles(name, payload) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}/references/import-files`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function searchStyleReferences(name, query, limit = 6) {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });
  return request(`/api/studio/styles/${encodeURIComponent(name)}/references/search?${params.toString()}`);
}

export async function clearStyleReferences(name) {
  return request(`/api/studio/styles/${encodeURIComponent(name)}/references`, {
    method: 'DELETE',
  });
}

export async function listProjectFiles(projectId) {
  return request(`/api/studio/projects/${projectId}/files`);
}

export async function getProjectFileContent(projectId, relativePath) {
  const params = new URLSearchParams({ path: relativePath });
  return request(`/api/studio/projects/${projectId}/files/content?${params.toString()}`);
}

export async function updateProjectFileContent(projectId, relativePath, payload) {
  const params = new URLSearchParams({ path: relativePath });
  return request(`/api/studio/projects/${projectId}/files/content?${params.toString()}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export const apiMeta = {
  get backendUrl() {
    return activeBackendUrl;
  },
};
