const browserBackendUrl = (
  import.meta.env.VITE_NOVEL_BACKEND_URL ?? 'http://127.0.0.1:18181'
).replace(/\/$/, '');

const browserStartupTimeout = 4000;
const tauriStartupTimeout = 15000;
const healthProbeInterval = 250;
const healthProbeTimeout = 1200;

let runtimeContextPromise = null;
let backendReadyPromise = null;
let backendReadyUrl = '';
let knownBackendUrl = browserBackendUrl;
const runtimeGlobal = typeof window !== 'undefined' ? window : globalThis;

function sleep(duration) {
  return new Promise((resolve) => {
    runtimeGlobal.setTimeout(resolve, duration);
  });
}

async function invokeTauriCommand(command) {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke(command);
}

async function resolveRuntimeContext() {
  if (!runtimeContextPromise) {
    runtimeContextPromise = (async () => {
      if (!isTauriRuntime()) {
        return {
          runtime: 'browser-preview',
          version: 'dev',
          backend_url: browserBackendUrl,
        };
      }

      try {
        const response = await invokeTauriCommand('get_runtime_context');
        if (response?.ok && response.data?.backend_url) {
          knownBackendUrl = response.data.backend_url;
          return response.data;
        }
      } catch {
        // Ignore and fall through to the legacy runtime command.
      }

      try {
        const response = await invokeTauriCommand('get_app_version');
        if (response?.ok && response.data) {
          return {
            ...response.data,
            backend_url: browserBackendUrl,
          };
        }
      } catch {
        return {
          runtime: 'tauri',
          version: 'unknown',
          backend_url: browserBackendUrl,
        };
      }

      return {
        runtime: 'tauri',
        version: 'unknown',
        backend_url: browserBackendUrl,
      };
    })().then((context) => {
      knownBackendUrl = context.backend_url ?? knownBackendUrl;
      return context;
    });
  }

  return runtimeContextPromise;
}

async function probeBackendHealth(baseUrl) {
  const controller = new AbortController();
  const timeoutId = runtimeGlobal.setTimeout(() => controller.abort(), healthProbeTimeout);

  try {
    const response = await fetch(`${baseUrl}/api/app/health`, {
      signal: controller.signal,
    });

    if (!response.ok) {
      return false;
    }

    const payload = await response.json().catch(() => null);
    return payload?.ok === true && payload?.data?.status === 'ok';
  } catch {
    return false;
  } finally {
    runtimeGlobal.clearTimeout(timeoutId);
  }
}

export function isTauriRuntime() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export async function getRuntimeInfo() {
  const context = await resolveRuntimeContext();
  return {
    runtime: context.runtime,
    version: context.version,
  };
}

export async function getBackendUrl() {
  const context = await resolveRuntimeContext();
  knownBackendUrl = context.backend_url ?? knownBackendUrl;
  return knownBackendUrl;
}

export function getKnownBackendUrl() {
  return knownBackendUrl;
}

export function markBackendUnavailable(baseUrl = '') {
  if (!baseUrl || backendReadyUrl === baseUrl) {
    backendReadyPromise = null;
    backendReadyUrl = '';
  }
}

export async function waitForBackendReady() {
  const baseUrl = await getBackendUrl();

  if (backendReadyPromise && backendReadyUrl === baseUrl) {
    return backendReadyPromise;
  }

  const startupTimeout = isTauriRuntime() ? tauriStartupTimeout : browserStartupTimeout;
  backendReadyUrl = baseUrl;
  backendReadyPromise = (async () => {
    const deadline = Date.now() + startupTimeout;
    while (Date.now() < deadline) {
      if (await probeBackendHealth(baseUrl)) {
        return baseUrl;
      }

      await sleep(healthProbeInterval);
    }

    throw new Error(`本地 backend 未就绪：${baseUrl}`);
  })();

  try {
    return await backendReadyPromise;
  } catch (error) {
    if (backendReadyUrl === baseUrl) {
      backendReadyPromise = null;
    }
    throw error;
  }
}
