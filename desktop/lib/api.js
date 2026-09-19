const SESSION_ID = 'default';
const WS_TOKEN_PROTOCOL = 'sentinel-token';

function runtimeApi() {
  if (typeof window !== 'undefined' && window.__SENTINEL_API__) {
    return window.__SENTINEL_API__;
  }
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : '';
  return { baseUrl, wsUrl: baseUrl.replace(/^http/, 'ws') };
}

function requestHeaders(headers) {
  const result = new Headers(headers || {});
  const token = runtimeApi().token;
  if (token) result.set('X-Sentinel-Token', token);
  return result;
}

async function rawRequest(path, options = {}) {
  return fetch(`${runtimeApi().baseUrl}${path}`, {
    ...options,
    headers: requestHeaders(options.headers),
  });
}

async function request(path, options = {}) {
  const response = await rawRequest(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string'
      ? detail
      : detail?.reason || `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function json(body) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

async function download(kind) {
  const response = await rawRequest(`/api/${kind}?session_id=${SESSION_ID}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const disposition = response.headers.get('content-disposition') || '';
  link.download = disposition.match(/filename="?([^"]+)"?/)?.[1] || `${kind}.zip`;
  link.href = url;
  link.click();
  URL.revokeObjectURL(url);
}

export const api = {
  codebase: () => request(`/api/codebase?session_id=${SESSION_ID}`),
  object: (uuid) => request(`/api/objects/${encodeURIComponent(uuid)}?session_id=${SESSION_ID}`),
  saveObject: (uuid, source) => request(
    `/api/objects/${encodeURIComponent(uuid)}?session_id=${SESSION_ID}`,
    { ...json({ definition: source }), method: 'PUT' },
  ),
  diagnostics: (uuid) => request(
    `/api/objects/${encodeURIComponent(uuid)}/diagnostics?session_id=${SESSION_ID}`,
  ),
  objectTests: (uuid) => request(
    `/api/objects/${encodeURIComponent(uuid)}/tests?session_id=${SESSION_ID}`,
  ),
  status: () => request(`/api/status?session_id=${SESSION_ID}`),
  tests: () => request(`/api/test-results?session_id=${SESSION_ID}`),
  changes: () => request(`/api/diff?session_id=${SESSION_ID}`),
  history: () => request(`/api/history?session_id=${SESSION_ID}`),
  historyDiff: (fromRevision, toRevision) => {
    const params = new URLSearchParams({ session_id: SESSION_ID, from: fromRevision });
    if (toRevision) params.set('to', toRevision);
    return request(`/api/history/diff?${params}`);
  },
  commitHistory: (message, actor = 'desktop', requirementId = '') => request(
    `/api/history/commit?session_id=${SESSION_ID}`,
    json({ message, actor, requirement_id: requirementId }),
  ),
  restore: (revision) => request(
    `/api/history/restore?session_id=${SESSION_ID}`,
    json({ revision }),
  ),
  bulkTests: (objectUuids, tests, preview) => request(
    `/api/tests/bulk?session_id=${SESSION_ID}`,
    json({ object_uuids: objectUuids, tests, preview }),
  ),
  bulkTestPreview: (objectUuids, tests) => api.bulkTests(objectUuids, tests, true),
  bulkTestApply: (objectUuids, tests) => api.bulkTests(objectUuids, tests, false),
  settings: () => request('/api/settings'),
  saveSettings: (settings) => request('/api/settings', json(settings)),
  testSettings: () => request('/api/settings/test'),
  ado: (id) => request(`/api/ado/workitem?session_id=${SESSION_ID}`, json({ id })),
  chat: (message) => request(`/api/chat?session_id=${SESSION_ID}`, json({ message })),
  upload: (endpoint, file) => {
    const body = new FormData();
    body.append('file', file);
    return request(`${endpoint}?session_id=${SESSION_ID}`, { method: 'POST', body });
  },
  uploadApplication: (file) => api.upload('/api/upload', file),
  uploadStory: (file) => api.upload('/api/story', file),
  packageFull: () => request(`/api/package?session_id=${SESSION_ID}`, { method: 'POST' }),
  wsUrl: () => `${runtimeApi().wsUrl}/ws?session_id=${SESSION_ID}`,
  // A browser cannot set headers on a WebSocket, so the token rides along as a
  // subprotocol instead of X-Sentinel-Token.
  wsProtocols: () => {
    const token = runtimeApi().token;
    return token ? [WS_TOKEN_PROTOCOL, token] : [];
  },
  downloadUrl: (kind) => `${runtimeApi().baseUrl}/api/${kind}?session_id=${SESSION_ID}`,
  download,
};
