'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/* ----- Constants ------------------------------------------------------ */
const STEP_NAMES = {
  1: 'Requirement Analysis', 2: 'Codebase Analysis', 3: 'Design',
  4: 'Implementation', 5: 'Dependency Check', 6: 'Performance Check',
  7: 'Code Quality', 8: 'Test Generation', 9: 'Final Packaging',
};
const PHASE_LABELS = {
  upload: 'Uploading', extract: 'Extracting ZIP', metadata: 'Reading metadata',
  parsing: 'Parsing objects', dependencies: 'Building dependencies', complete: 'Complete',
};
const SESSION_ID = 'default';

/* ----- API base resolution (Electron injects window.__SENTINEL_API__) - */
function getApi() {
  if (typeof window !== 'undefined' && window.__SENTINEL_API__) return window.__SENTINEL_API__;
  // Browser dev fallback: same-origin.
  const base = typeof window !== 'undefined' ? window.location.origin : '';
  const ws = base.replace(/^http/, 'ws');
  return { baseUrl: base, wsUrl: ws };
}

/* ----- Lightweight markdown ------------------------------------------- */
function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
    `<pre><code class="language-${lang}">${code}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/\n/g, '<br>');
  return html;
}

export default function Page() {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState('idle');
  const [currentStep, setCurrentStep] = useState(0);
  const [iteration, setIteration] = useState(0);
  const [maxIterations, setMaxIterations] = useState(20);
  const [messages, setMessages] = useState([
    { id: 'welcome', role: 'system', content: 'Welcome to Appian Sentinel. Upload an Appian export ZIP and a user story (or pull one from Azure DevOps) to get started.' },
  ]);
  const [progress, setProgress] = useState(null);
  const [codebase, setCodebase] = useState(null);
  const [testResults, setTestResults] = useState(null);
  const [hasOutputZip, setHasOutputZip] = useState(false);
  const [hasPatchZip, setHasPatchZip] = useState(false);
  const [theme, setTheme] = useState('dark');
  const [draft, setDraft] = useState('');

  // ADO
  const [adoId, setAdoId] = useState('');
  const [adoBusy, setAdoBusy] = useState(false);

  // Settings
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState({
    base_url: '', api_key: '', primary_model: '', fast_model: '',
    ado_source: 'pat', ado_org: '', ado_project: '', ado_pat: '',
  });
  const [connMsg, setConnMsg] = useState(null); // {text, type}

  const wsRef = useRef(null);
  const apiRef = useRef(getApi());
  const messagesEndRef = useRef(null);
  const mountedRef = useRef(true);
  const zipInputRef = useRef(null);
  const storyInputRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    if (messagesEndRef.current) messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, []);

  /* ----- WebSocket ---------------------------------------------------- */
  const connectWS = useCallback(() => {
    const { wsUrl } = apiRef.current;
    const url = `${wsUrl}/ws?session_id=${SESSION_ID}`;
    let ws;
    try { ws = new WebSocket(url); } catch { return; }
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      if (mountedRef.current) setTimeout(connectWS, 2000);
    };
    ws.onerror = () => setConnected(false);
    ws.onmessage = (ev) => {
      let payload;
      try { payload = JSON.parse(ev.data); } catch { return; }
      handleServerMessage(payload);
    };
  }, []);

  const handleServerMessage = useCallback((payload) => {
    if (payload.type === 'message') {
      const msg = payload.data;
      if (msg?.metadata?.progress) {
        const { phase, current, total } = msg.metadata;
        setProgress({ phase, current, total, detail: msg.content });
        if (phase === 'complete') setTimeout(() => setProgress(null), 1200);
      } else {
        setMessages((prev) => [...prev, msg]);
        scrollToBottom();
      }
    } else if (payload.type === 'state') {
      const d = payload.data || {};
      setStatus(d.status || 'idle');
      setCurrentStep(d.current_step || 0);
      setIteration(d.iteration || 0);
      setMaxIterations(d.max_iterations || 20);
      if (payload.messages && payload.messages.length) setMessages(payload.messages);
    }
  }, [scrollToBottom]);

  /* ----- REST helpers ------------------------------------------------- */
  const api = (p) => `${apiRef.current.baseUrl}${p}`;

  const fetchCodebase = useCallback(async () => {
    try {
      const r = await fetch(api(`/api/codebase?session_id=${SESSION_ID}`));
      if (r.ok) setCodebase(await r.json());
    } catch {}
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(api(`/api/status?session_id=${SESSION_ID}`));
      if (r.ok) {
        const d = await r.json();
        setStatus(d.status || 'idle');
        setCurrentStep(d.current_step || 0);
        setIteration(d.iteration || 0);
        setMaxIterations(d.max_iterations || 20);
        setHasOutputZip(!!d.has_output_zip);
        setHasPatchZip(!!d.has_patch_zip);
      }
    } catch {}
  }, []);

  const fetchTestResults = useCallback(async () => {
    try {
      const r = await fetch(api(`/api/test-results?session_id=${SESSION_ID}`));
      if (r.ok) setTestResults(await r.json());
    } catch {}
  }, []);

  /* ----- Lifecycle ---------------------------------------------------- */
  useEffect(() => {
    mountedRef.current = true;
    apiRef.current = getApi();
    document.documentElement.setAttribute('data-theme', theme);
    connectWS();
    loadSettings();
    fetchStatus();
    fetchTestResults();
    const iv = setInterval(() => { fetchStatus(); fetchTestResults(); }, 2500);
    return () => {
      mountedRef.current = false;
      clearInterval(iv);
      if (wsRef.current) wsRef.current.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  /* ----- Uploads ------------------------------------------------------ */
  const uploadFile = useCallback(async (file, endpoint, label) => {
    if (!file) return;
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: 'system', content: `Uploading ${label}: ${file.name} …`, message_type: 'status' }]);
    const form = new FormData();
    form.append('file', file);
    try {
      const r = await fetch(api(`${endpoint}?session_id=${SESSION_ID}`), { method: 'POST', body: form });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        setMessages((prev) => [...prev, { id: `e-${Date.now()}`, role: 'system', content: `Upload failed: ${err.detail || 'Unknown error'}`, message_type: 'error' }]);
        return;
      }
      setMessages((prev) => [...prev, { id: `ok-${Date.now()}`, role: 'system', content: `${label} uploaded successfully.`, message_type: 'status' }]);
      if (endpoint.includes('/upload')) fetchCodebase();
    } catch (e) {
      setMessages((prev) => [...prev, { id: `e-${Date.now()}`, role: 'system', content: `Upload error: ${e.message}`, message_type: 'error' }]);
    }
  }, [fetchCodebase]);

  /* ----- Chat --------------------------------------------------------- */
  const sendMessage = useCallback(() => {
    const text = draft.trim();
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'chat', content: text }));
    setDraft('');
  }, [draft]);

  /* ----- ADO ---------------------------------------------------------- */
  const fetchAdo = useCallback(async () => {
    if (!adoId.trim()) return;
    setAdoBusy(true);
    try {
      const r = await fetch(api('/api/ado/workitem') + `?session_id=${SESSION_ID}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: adoId.trim() }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        setMessages((prev) => [...prev, { id: `ado-${Date.now()}`, role: 'system', content: `Loaded ADO #${d.work_item?.id}: ${d.work_item?.title}`, message_type: 'status' }]);
      } else {
        setMessages((prev) => [...prev, { id: `adoe-${Date.now()}`, role: 'system', content: `ADO fetch failed: ${d.detail || r.statusText}`, message_type: 'error' }]);
      }
    } catch (e) {
      setMessages((prev) => [...prev, { id: `adoe-${Date.now()}`, role: 'system', content: `ADO error: ${e.message}`, message_type: 'error' }]);
    } finally {
      setAdoBusy(false);
    }
  }, [adoId]);

  /* ----- Downloads ---------------------------------------------------- */
  const downloadFull = () => window.open(api(`/api/download?session_id=${SESSION_ID}`), '_blank');
  const downloadPatch = () => window.open(api(`/api/patch?session_id=${SESSION_ID}`), '_blank');

  /* ----- Settings ----------------------------------------------------- */
  const loadSettings = useCallback(async () => {
    try {
      const r = await fetch(api('/api/settings'));
      if (r.ok) {
        const d = await r.json();
        setSettings((s) => ({ ...s, ...d }));
      }
    } catch {}
  }, []);

  const buildSettingsPayload = () => {
    const p = {};
    ['base_url', 'api_key', 'primary_model', 'fast_model', 'ado_source', 'ado_org', 'ado_project', 'ado_pat'].forEach((k) => {
      const v = (settings[k] || '').trim();
      if (v) p[k] = v;
    });
    return p;
  };

  const saveSettings = useCallback(async () => {
    try {
      const r = await fetch(api('/api/settings'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildSettingsPayload()),
      });
      if (r.ok) { setConnMsg({ text: 'Settings saved.', type: 'success' }); setTimeout(() => setSettingsOpen(false), 700); }
      else { const e = await r.json().catch(() => ({})); setConnMsg({ text: `Save failed: ${e.detail || 'error'}`, type: 'error' }); }
    } catch (e) { setConnMsg({ text: `Save error: ${e.message}`, type: 'error' }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  const testConnection = useCallback(async () => {
    setConnMsg({ text: 'Saving & testing…', type: 'loading' });
    try {
      const save = await fetch(api('/api/settings'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildSettingsPayload()),
      });
      if (!save.ok) { setConnMsg({ text: 'Failed to save before testing.', type: 'error' }); return; }
      setConnMsg({ text: 'Testing connection…', type: 'loading' });
      const r = await fetch(api('/api/settings/test'));
      const d = await r.json();
      setConnMsg({ text: d.message || (r.ok ? 'Connection successful.' : 'Connection failed.'), type: r.ok ? 'success' : 'error' });
    } catch (e) { setConnMsg({ text: `Test error: ${e.message}`, type: 'error' }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  /* ----- Derived ------------------------------------------------------ */
  const byType = codebase?.by_type || {};
  const uuidToName = codebase?.uuid_to_name || {};
  const totalObjects = Object.values(byType).reduce((a, v) => a + (v?.length || 0), 0);
  const setField = (k) => (e) => setSettings((s) => ({ ...s, [k]: e.target.value }));

  /* ----- Render ------------------------------------------------------- */
  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header__title">Appian <span>Sentinel</span></div>
        <div className="header__actions">
          <span className={`connection-dot connection-dot--${connected ? 'connected' : 'disconnected'}`} title="Sidecar connection" />
          <span className={`header__status header__status--${status}`}>{String(status).replace(/_/g, ' ')}</span>
          <button className="theme-toggle" onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))} title="Toggle theme">{theme === 'light' ? '☾' : '☀'}</button>
          <button className="settings-btn" onClick={() => { setConnMsg(null); setSettingsOpen(true); loadSettings(); }} title="Settings">⚙</button>
        </div>
      </header>

      {/* Settings modal */}
      {settingsOpen && (
        <div className="modal-overlay" onClick={(e) => { if (e.target.classList.contains('modal-overlay')) setSettingsOpen(false); }}>
          <div className="modal">
            <div className="modal-header">
              <h3 className="modal-header__title">Settings</h3>
              <button className="modal-header__close" onClick={() => setSettingsOpen(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-group"><label className="form-label">LiteLLM Base URL</label>
                <input className="form-input" value={settings.base_url} onChange={setField('base_url')} placeholder="https://…/" /></div>
              <div className="form-group"><label className="form-label">LiteLLM API Key</label>
                <input className="form-input" type="password" value={settings.api_key} onChange={setField('api_key')} placeholder="Enter API key" /></div>
              <div className="form-group"><label className="form-label">Primary Model</label>
                <input className="form-input" value={settings.primary_model} onChange={setField('primary_model')} placeholder="bedrock.anthropic.claude-opus-4-8" /></div>
              <div className="form-group"><label className="form-label">Fast Model</label>
                <input className="form-input" value={settings.fast_model} onChange={setField('fast_model')} placeholder="bedrock.anthropic.claude-sonnet-5" /></div>
              <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '16px 0' }} />
              <div className="form-group"><label className="form-label">Azure DevOps Source</label>
                <select className="form-input" value={settings.ado_source} onChange={setField('ado_source')}>
                  <option value="pat">PAT (REST)</option>
                  <option value="mcp">ADO MCP (desktop bridge)</option>
                </select></div>
              <div className="form-group"><label className="form-label">ADO Organization</label>
                <input className="form-input" value={settings.ado_org} onChange={setField('ado_org')} placeholder="myorg or https://dev.azure.com/myorg" /></div>
              <div className="form-group"><label className="form-label">ADO Project</label>
                <input className="form-input" value={settings.ado_project} onChange={setField('ado_project')} placeholder="MyProject" /></div>
              <div className="form-group"><label className="form-label">ADO PAT</label>
                <input className="form-input" type="password" value={settings.ado_pat} onChange={setField('ado_pat')} placeholder="Personal Access Token" /></div>
              {connMsg && <div className={`connection-status connection-status--${connMsg.type}`}>{connMsg.text}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn-test" onClick={testConnection}>Test Connection</button>
              <div className="modal-footer__right">
                <button className="btn-cancel" onClick={() => setSettingsOpen(false)}>Cancel</button>
                <button className="btn-save" onClick={saveSettings}>Save</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Left sidebar */}
      <aside className="sidebar-left">
        <section className="sidebar-section">
          <div className="sidebar-section__title">Appian Export</div>
          <div className="upload-area" onClick={() => zipInputRef.current?.click()}>
            <div className="upload-area__icon">📦</div>
            <div className="upload-area__label">Click to upload ZIP</div>
            <div className="upload-area__hint">.zip exported from Appian</div>
            <input ref={zipInputRef} type="file" accept=".zip" hidden onChange={(e) => { if (e.target.files[0]) uploadFile(e.target.files[0], '/api/upload', 'Appian ZIP'); e.target.value = ''; }} />
          </div>
        </section>

        <section className="sidebar-section">
          <div className="sidebar-section__title">User Story</div>
          <div className="upload-area" onClick={() => storyInputRef.current?.click()}>
            <div className="upload-area__icon">📄</div>
            <div className="upload-area__label">Click to upload PDF</div>
            <div className="upload-area__hint">.pdf user story</div>
            <input ref={storyInputRef} type="file" accept=".pdf" hidden onChange={(e) => { if (e.target.files[0]) uploadFile(e.target.files[0], '/api/story', 'User Story'); e.target.value = ''; }} />
          </div>
        </section>

        <section className="sidebar-section">
          <div className="sidebar-section__title">Azure DevOps</div>
          <div className="form-group">
            <input className="form-input" value={adoId} onChange={(e) => setAdoId(e.target.value)} placeholder="Work item ID (e.g. 1536949)" />
          </div>
          <button className="btn-save" style={{ width: '100%' }} disabled={adoBusy} onClick={fetchAdo}>
            {adoBusy ? 'Fetching…' : 'Fetch Work Item'}
          </button>
        </section>

        <section className="sidebar-section">
          <div className="sidebar-section__title">Codebase</div>
          <div id="codebase-summary" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {codebase
              ? <><strong>{codebase.app_name || 'Unknown'}</strong><br />{totalObjects} objects{codebase.appian_version ? ` · v${codebase.appian_version}` : ''}</>
              : 'No codebase loaded.'}
          </div>
        </section>

        <div className="object-tree">
          {Object.keys(byType).sort().map((type) => (
            <div className="object-tree__group" key={type}>
              <div className="object-tree__group-label">{type} ({byType[type].length})</div>
              {byType[type].slice(0, 50).map((uid) => (
                <div className="object-tree__item" key={uid}>
                  <span className="object-tree__icon">■</span>
                  <span className="truncate">{uuidToName[uid] || uid}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* Center chat */}
      <main className="chat-panel">
        <div className="chat-messages">
          {messages.map((m) => (
            <div key={m.id || Math.random()} className={`message message--${m.role || 'assistant'} ${m.message_type === 'error' ? 'message--error' : ''} ${m.message_type === 'question' ? 'message--question' : ''}`}>
              {m.step && m.role !== 'user' && (
                <div className="message__step-badge">Step {m.step}: {STEP_NAMES[m.step] || ''}</div>
              )}
              <div dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }} />
            </div>
          ))}
          {progress && (
            <div className={`progress-card ${progress.phase === 'complete' ? 'progress-card--done' : ''}`}>
              <div className="progress-card__header">
                <span className="progress-card__phase">{PHASE_LABELS[progress.phase] || progress.phase}</span>
                <span className="progress-card__pct">{Math.min(100, Math.round((progress.current / (progress.total || 1)) * 100))}%</span>
              </div>
              <div className="progress-card__bar-track">
                <div className="progress-card__bar-fill" style={{ width: `${Math.min(100, Math.round((progress.current / (progress.total || 1)) * 100))}%` }} />
              </div>
              <div className="progress-card__detail">{progress.detail}</div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input">
          <textarea
            className="chat-input__textarea"
            placeholder="Type a message or paste your user story …"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            rows={1}
          />
          <button className="chat-input__send" onClick={sendMessage} title="Send">➤</button>
        </div>
      </main>

      {/* Right sidebar */}
      <aside className="sidebar-right">
        <section className="sidebar-section">
          <div className="sidebar-section__title">Workflow Progress</div>
          <ol className="step-progress">
            {Object.entries(STEP_NAMES).map(([n, label]) => {
              const step = Number(n);
              const cls = step === currentStep ? 'step-progress__item--active' : step < currentStep ? 'step-progress__item--done' : '';
              return (
                <li className={`step-progress__item ${cls}`} key={n}>
                  <span className="step-progress__number">{n}</span> {label}
                </li>
              );
            })}
          </ol>
        </section>

        <section className="sidebar-section">
          <div className="sidebar-section__title">Fix Loop</div>
          <div className="iteration-badge">Fix iteration: <span className="iteration-badge__count">{iteration}</span> / {maxIterations}</div>
        </section>

        <section className="sidebar-section">
          <div className="sidebar-section__title">Test Results</div>
          <div className="test-results">
            {!testResults || testResults.status === 'no_results'
              ? 'No test results yet.'
              : (
                <>
                  <div className="test-results__summary">
                    {testResults.passed
                      ? <span className="test-results__badge test-results__badge--pass">ALL PASSED</span>
                      : <span className="test-results__badge test-results__badge--fail">{(testResults.failures || []).length} FAILED</span>}
                  </div>
                  {(testResults.failures || []).length > 0 && (
                    <ul className="test-results__list">
                      {testResults.failures.map((f, i) => (
                        <li className="test-results__item test-results__item--fail" key={i}>{(f.name || 'unknown')}: {f.message || ''}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
          </div>
        </section>

        <section className="sidebar-section">
          <div className="sidebar-section__title">Output</div>
          <button className="download-btn" disabled={!hasPatchZip} onClick={downloadPatch} style={{ marginBottom: 8 }}>
            ⬇ Download Patch (story objects)
          </button>
          <button className="download-btn" disabled={!hasOutputZip} onClick={downloadFull}>
            ⬇ Download Full Rebuilt ZIP
          </button>
        </section>
      </aside>
    </div>
  );
}
