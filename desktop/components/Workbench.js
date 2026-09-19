'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import { buildNavigation } from '../lib/sail-symbols';
import AssistantPanel from './AssistantPanel';
import BottomPanel from './BottomPanel';
import EditorWorkspace from './EditorWorkspace';
import ObjectExplorer from './ObjectExplorer';
import TopAppBar from './TopAppBar';

const TESTABLE_TYPES = new Set(['interface', 'expression_rule']);
const EMPTY_SETTINGS = {
  base_url: '', api_key: '', protocol: 'auto', primary_model: '', fast_model: '',
  ado_org: '', ado_project: '', ado_pat: '',
};
const PANEL_STORAGE_KEY = 'appian-sentinel-panel-sizes';
const PANEL_DEFAULTS = { explorer: 250, assistant: 310, results: 174 };
const PANEL_LIMITS = {
  explorer: [180, 420],
  assistant: [220, 480],
  results: [110, 360],
};

function clampPanel(name, value) {
  const [minimum, maximum] = PANEL_LIMITS[name];
  return Math.max(minimum, Math.min(maximum, Math.round(value)));
}

function ResizeHandle({ orientation, label, value, minimum, maximum, onDelta }) {
  function startResize(event) {
    const axis = orientation === 'vertical' ? 'clientX' : 'clientY';
    let previous = event[axis];
    const move = (moveEvent) => {
      const current = moveEvent[axis];
      onDelta(current - previous);
      previous = current;
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      document.body.classList.remove('is-resizing');
    };
    document.body.classList.add('is-resizing');
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
    event.preventDefault();
  }

  function resizeWithKeyboard(event) {
    const changes = orientation === 'vertical'
      ? { ArrowLeft: -16, ArrowRight: 16 }
      : { ArrowUp: -16, ArrowDown: 16 };
    if (!(event.key in changes)) return;
    event.preventDefault();
    onDelta(changes[event.key]);
  }

  return (
    <div
      className={`resize-handle is-${orientation}`}
      role="separator"
      aria-label={label}
      aria-orientation={orientation}
      aria-valuemin={minimum}
      aria-valuemax={maximum}
      aria-valuenow={value}
      tabIndex={0}
      onPointerDown={startResize}
      onKeyDown={resizeWithKeyboard}
    />
  );
}

function percentOf(current, total) {
  if (!total) return 0;
  return Math.min(100, Math.round((current / total) * 100));
}

export default function Workbench() {
  const [codebase, setCodebase] = useState(null);
  const [codebaseState, setCodebaseState] = useState({ loading: true, error: '' });
  const [tabs, setTabs] = useState([]);
  const [activeId, setActiveId] = useState('');
  const [object, setObject] = useState(null);
  const [objectState, setObjectState] = useState({ loading: false, error: '' });
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState({ status: 'idle', current_step: 0 });
  const [tests, setTests] = useState(null);
  const [diagnostics, setDiagnostics] = useState(null);
  const [objectCatalog, setObjectCatalog] = useState({});
  const [jumpRequest, setJumpRequest] = useState(null);
  const [changes, setChanges] = useState(null);
  const [history, setHistory] = useState([]);
  const [messages, setMessages] = useState([]);
  const [progress, setProgress] = useState(null);
  const [settings, setSettings] = useState(EMPTY_SETTINGS);
  const [settingsState, setSettingsState] = useState('');
  const [panelSizes, setPanelSizes] = useState(PANEL_DEFAULTS);
  const [panelSizesLoaded, setPanelSizesLoaded] = useState(false);
  const socketRef = useRef(null);
  const progressTimerRef = useRef(0);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(PANEL_STORAGE_KEY) || '{}');
      setPanelSizes({
        explorer: clampPanel('explorer', saved.explorer ?? PANEL_DEFAULTS.explorer),
        assistant: clampPanel('assistant', saved.assistant ?? PANEL_DEFAULTS.assistant),
        results: clampPanel('results', saved.results ?? PANEL_DEFAULTS.results),
      });
    } catch {
      setPanelSizes(PANEL_DEFAULTS);
    }
    setPanelSizesLoaded(true);
  }, []);

  useEffect(() => {
    if (panelSizesLoaded) {
      window.localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(panelSizes));
    }
  }, [panelSizes, panelSizesLoaded]);

  const resizePanel = useCallback((name, delta) => {
    setPanelSizes((current) => {
      const [minimum, configuredMaximum] = PANEL_LIMITS[name];
      let maximum = configuredMaximum;
      if (name === 'explorer') {
        maximum = Math.min(maximum, window.innerWidth - current.assistant - 328);
      } else if (name === 'assistant') {
        maximum = Math.min(maximum, window.innerWidth - current.explorer - 328);
      } else {
        maximum = Math.min(maximum, window.innerHeight - 256);
      }
      return {
        ...current,
        [name]: Math.max(minimum, Math.min(Math.max(minimum, maximum), current[name] + delta)),
      };
    });
  }, []);

  const loadCodebase = useCallback(async () => {
    setCodebaseState({ loading: true, error: '' });
    try {
      setCodebase(await api.codebase());
      setCodebaseState({ loading: false, error: '' });
    } catch (error) {
      setCodebase(null);
      setCodebaseState({ loading: false, error: error.message });
    }
  }, []);

  useEffect(() => {
    let active = true;
    let retryTimer = 0;

    async function refresh() {
      const reads = [api.status(), api.tests(), api.changes()];
      const results = await Promise.allSettled(reads);
      if (!active) return;
      const [statusResult, testsResult, changesResult] = results;
      if (statusResult.status === 'fulfilled') setStatus(statusResult.value);
      if (testsResult.status === 'fulfilled') setTests(testsResult.value);
      if (changesResult.status === 'fulfilled') setChanges(changesResult.value);
    }

    function connect() {
      if (!active) return;
      const socket = new WebSocket(api.wsUrl(), api.wsProtocols());
      socketRef.current = socket;
      socket.onopen = () => setConnected(true);
      socket.onerror = () => setConnected(false);
      socket.onclose = () => {
        setConnected(false);
        if (active) retryTimer = window.setTimeout(connect, 2000);
      };
      socket.onmessage = (event) => {
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (payload.type === 'message' && payload.data) {
          const meta = payload.data.metadata || {};
          if (meta.progress) {
            window.clearTimeout(progressTimerRef.current);
            setProgress({
              phase: meta.phase || 'working',
              percent: percentOf(meta.current, meta.total),
              detail: payload.data.content || '',
            });
            if (meta.phase === 'complete') {
              progressTimerRef.current = window.setTimeout(() => setProgress(null), 1500);
            }
            return;
          }
          setMessages((items) => [...items, payload.data]);
          return;
        }
        if (payload.type === 'state' && payload.data) {
          setStatus((value) => ({ ...value, ...payload.data }));
          if (payload.messages) {
            setMessages(payload.messages.filter((item) => !item.metadata?.progress));
          }
        }
      };
    }

    let interval = 0;
    loadCodebase();
    api.settings()
      .then((value) => { if (active) setSettings({ ...EMPTY_SETTINGS, ...value }); })
      .catch(() => setSettingsState('Could not read settings from the sidecar.'));
    refresh();
    connect();
    interval = window.setInterval(refresh, 3000);

    return () => {
      active = false;
      window.clearInterval(interval);
      window.clearTimeout(retryTimer);
      window.clearTimeout(progressTimerRef.current);
      socketRef.current?.close();
    };
  }, [loadCodebase]);

  useEffect(() => {
    if (!codebase) {
      setHistory([]);
      setObjectCatalog({});
      return;
    }
    api.history()
      .then((value) => setHistory(Array.isArray(value) ? value : value?.revisions || value?.items || []))
      .catch(() => setHistory([]));
  }, [codebase]);

  useEffect(() => {
    let active = true;
    const ids = [...new Set(Object.values(codebase?.by_type || {}).flat())];
    if (!ids.length) {
      setObjectCatalog({});
      return () => { active = false; };
    }
    async function loadCatalog() {
      const loaded = { ...(codebase?.objects || {}) };
      const missing = ids.filter((uuid) => !loaded[uuid]);
      // ponytail: requests run in batches of 12; add cancellation if exports become very large.
      for (let index = 0; index < missing.length && active; index += 12) {
        const batch = await Promise.allSettled(
          missing.slice(index, index + 12).map((uuid) => api.object(uuid)),
        );
        batch.forEach((result, offset) => {
          if (result.status === 'fulfilled') loaded[missing[index + offset]] = result.value;
        });
      }
      if (active) setObjectCatalog(loaded);
    }
    loadCatalog();
    return () => { active = false; };
  }, [codebase]);

  useEffect(() => {
    function focusSearch(event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        document.getElementById('object-search')?.focus();
      }
    }
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, []);

  const loadObject = useCallback(async (uuid) => {
    setObject(null);
    setDiagnostics(null);
    setObjectState({ loading: true, error: '' });
    try {
      const [objectResult, diagnosticsResult] = await Promise.allSettled([
        api.object(uuid),
        api.diagnostics(uuid),
      ]);
      if (objectResult.status === 'rejected') throw objectResult.reason;
      setObject(objectResult.value);
      setObjectCatalog((items) => ({ ...items, [uuid]: objectResult.value }));
      setDiagnostics(diagnosticsResult.status === 'fulfilled'
        ? diagnosticsResult.value
        : { diagnostics: [], error: diagnosticsResult.reason.message });
      setObjectState({ loading: false, error: '' });
    } catch (error) {
      setObjectState({ loading: false, error: error.message });
    }
  }, []);

  function openObject(item) {
    setTabs((items) => (items.some((tab) => tab.uuid === item.uuid) ? items : [...items, item]));
    setActiveId(item.uuid);
    loadObject(item.uuid);
  }

  function activateTab(uuid) {
    if (uuid === activeId) return;
    setActiveId(uuid);
    loadObject(uuid);
  }

  function closeTab(uuid) {
    setTabs((items) => {
      const remaining = items.filter((tab) => tab.uuid !== uuid);
      if (uuid === activeId) {
        const next = remaining[remaining.length - 1];
        setActiveId(next?.uuid || '');
        if (next) loadObject(next.uuid);
        else {
          setObject(null);
          setDiagnostics(null);
          setObjectState({ loading: false, error: '' });
        }
      }
      return remaining;
    });
  }

  async function upload(file) {
    setCodebaseState({ loading: true, error: '' });
    try {
      await api.uploadApplication(file);
      await loadCodebase();
    } catch (error) {
      setCodebaseState({ loading: false, error: error.message });
    }
  }

  function sendMessage(content) {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'chat', content }));
    setMessages((items) => [...items, { id: `local-${Date.now()}`, role: 'user', content }]);
  }

  async function saveSettings(form) {
    setSettingsState('Saving settings...');
    try {
      const saved = await api.saveSettings(form);
      setSettings({ ...EMPTY_SETTINGS, ...saved });
      setSettingsState('Settings saved.');
    } catch (error) {
      setSettingsState(`Save failed: ${error.message}`);
    }
  }

  async function testSettings(form) {
    setSettingsState('Saving and testing connection...');
    try {
      await api.saveSettings(form);
      const result = await api.testSettings();
      setSettingsState(result.message || 'Connection successful.');
    } catch (error) {
      setSettingsState(`Connection failed: ${error.message}`);
    }
  }

  async function saveObject(uuid, source) {
    if (!codebase) throw new Error('Codebase not loaded yet.');
    await api.saveObject(uuid, source);
    await loadObject(uuid);
  }

  function jumpToProblem(problem) {
    setJumpRequest({ ...problem, uuid: activeId, requestId: Date.now() });
  }

  async function restoreRevision(revision) {
    if (!codebase) throw new Error('Codebase not loaded yet.');
    await api.restore(revision);
    setHistory(await api.history().then((value) => (
      Array.isArray(value) ? value : value?.revisions || value?.items || []
    )));
    await loadCodebase();
  }

  const testableObjects = useMemo(() => Object.entries(codebase?.by_type || {})
    .filter(([type]) => TESTABLE_TYPES.has(type))
    .flatMap(([type, ids]) => ids.map((uuid) => ({
      uuid,
      type: type.replaceAll('_', ' '),
      name: codebase.uuid_to_name?.[uuid] || uuid,
    })))
    .sort((left, right) => left.name.localeCompare(right.name)), [codebase]);
  const navigation = useMemo(
    () => buildNavigation(codebase, objectCatalog),
    [codebase, objectCatalog],
  );

  return (
    <div className="workbench">
      <TopAppBar
        appName={codebase?.app_name}
        connected={connected}
        status={status.status}
        onUpload={upload}
      />
      <div
        className="workbench-main"
        style={{
          '--explorer-width': `${panelSizes.explorer}px`,
          '--assistant-width': `${panelSizes.assistant}px`,
        }}
      >
        <ObjectExplorer
          codebase={codebase}
          loading={codebaseState.loading}
          error={codebaseState.error}
          selectedId={activeId}
          onSelect={openObject}
        />
        <ResizeHandle
          orientation="vertical"
          label="Resize object explorer"
          value={panelSizes.explorer}
          minimum={PANEL_LIMITS.explorer[0]}
          maximum={PANEL_LIMITS.explorer[1]}
          onDelta={(delta) => resizePanel('explorer', delta)}
        />
        <div
          className="center-column"
          style={{ '--results-height': `${panelSizes.results}px` }}
        >
          <EditorWorkspace
            tabs={tabs}
            activeId={activeId}
            object={object}
            diagnostics={diagnostics}
            jumpRequest={jumpRequest}
            navigation={navigation}
            loading={objectState.loading}
            error={objectState.error}
            codebaseLoading={codebaseState.loading}
            codebaseLoaded={Boolean(codebase)}
            onActivate={activateTab}
            onClose={closeTab}
            onSave={saveObject}
            onOpenObject={openObject}
          />
          <ResizeHandle
            orientation="horizontal"
            label="Resize results panel"
            value={panelSizes.results}
            minimum={PANEL_LIMITS.results[0]}
            maximum={PANEL_LIMITS.results[1]}
            onDelta={(delta) => resizePanel('results', -delta)}
          />
          <BottomPanel
            diagnostics={diagnostics}
            tests={tests}
            changes={changes}
            history={history}
            output={status}
            activeId={activeId}
            navigation={navigation}
            testableObjects={testableObjects}
            codebaseLoaded={Boolean(codebase)}
            onBulkPreview={api.bulkTestPreview}
            onBulkApply={api.bulkTestApply}
            onRestore={restoreRevision}
            onPackage={async () => {
              await api.packageFull();
              setStatus(await api.status());
            }}
            onDownload={api.download}
            onJumpToProblem={jumpToProblem}
            onOpenObject={openObject}
          />
        </div>
        <ResizeHandle
          orientation="vertical"
          label="Resize assistant"
          value={panelSizes.assistant}
          minimum={PANEL_LIMITS.assistant[0]}
          maximum={PANEL_LIMITS.assistant[1]}
          onDelta={(delta) => resizePanel('assistant', -delta)}
        />
        <AssistantPanel
          messages={messages}
          currentStep={status.current_step || 0}
          connected={connected}
          progress={progress}
          settings={settings}
          settingsState={settingsState}
          onSend={sendMessage}
          onFetchAdo={api.ado}
          onUploadStory={api.uploadStory}
          onSaveSettings={saveSettings}
          onTestSettings={testSettings}
        />
      </div>
      <footer className="statusbar">
        <span>Appian {codebase?.appian_version || '--'}</span>
        <span>{activeId || 'No object selected'}</span>
        <span>{connected ? 'Connected' : 'Disconnected'}</span>
      </footer>
    </div>
  );
}
