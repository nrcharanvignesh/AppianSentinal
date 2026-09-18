'use client';

import { useEffect, useRef, useState } from 'react';

const STEPS = [
  'Requirement Analysis', 'Codebase Analysis', 'Design', 'Implementation',
  'Dependency Check', 'Performance Check', 'Code Quality', 'Test Generation',
  'Final Packaging',
];

const MODES = ['Chat', 'ADO', 'Settings', 'Progress'];

export default function AssistantPanel({
  messages,
  currentStep,
  connected,
  progress,
  settings,
  settingsState,
  onSend,
  onFetchAdo,
  onUploadStory,
  onSaveSettings,
  onTestSettings,
}) {
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState('Chat');
  const [adoId, setAdoId] = useState('');
  const [adoState, setAdoState] = useState('');
  const [form, setForm] = useState(settings);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' });
  }, [messages]);

  useEffect(() => setForm(settings), [settings]);

  function submit() {
    const value = draft.trim();
    if (!value || !connected) return;
    onSend(value);
    setDraft('');
  }

  async function fetchAdo() {
    if (!adoId.trim()) return;
    setAdoState('Loading work item...');
    try {
      await onFetchAdo(adoId.trim());
      setAdoState(`Work item ${adoId.trim()} loaded.`);
    } catch (error) {
      setAdoState(`ADO error: ${error.message}`);
    }
  }

  async function uploadStory(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setAdoState(`Loading ${file.name}...`);
    try {
      await onUploadStory(file);
      setAdoState(`PDF ${file.name} loaded.`);
    } catch (error) {
      setAdoState(`PDF error: ${error.message}`);
    } finally {
      event.target.value = '';
    }
  }

  const setField = (name) => (event) => setForm((value) => ({ ...value, [name]: event.target.value }));

  return (
    <aside className="assistant-panel pane" aria-label="Assistant and workflow">
      <div className="assistant-tabs" role="tablist">
        {MODES.map((item) => (
          <button type="button" role="tab" aria-selected={mode === item} onClick={() => setMode(item)} key={item}>{item}</button>
        ))}
      </div>
      {mode === 'Chat' && (
        <>
          <div className="assistant-heading">
            <div className="assistant-avatar" aria-hidden="true">S</div>
            <div>
              <strong>Sentinel Assistant</strong>
              <span className={connected ? 'is-online' : 'is-offline'}>
                {connected ? 'Ready' : 'Offline'}
              </span>
            </div>
          </div>
          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="assistant-empty">
                <strong>Build with application context</strong>
                <p>Ask about the open object, requirements, tests, or dependency impact.</p>
              </div>
            )}
            {messages.map((message, index) => (
              <div className={`chat-message is-${message.role || 'assistant'}`} key={message.id || index}>
                <span>{message.role === 'user' ? 'You' : 'Sentinel'}</span>
                <p>{message.content}</p>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <div className="composer">
            <textarea
              rows="3"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              placeholder={connected ? 'Ask Sentinel...' : 'Sidecar connection required'}
              disabled={!connected}
            />
            <div><span>Enter to send</span><button type="button" onClick={submit} disabled={!connected || !draft.trim()}>Send</button></div>
          </div>
        </>
      )}
      {mode === 'ADO' && (
        <div className="assistant-form">
          <h3>Azure DevOps work item</h3>
          <label>Work item ID<input value={adoId} onChange={(event) => setAdoId(event.target.value)} placeholder="1536949" /></label>
          <button className="primary-button" type="button" disabled={!adoId.trim()} onClick={fetchAdo}>Load work item</button>
          <label>
            User story PDF
            <input type="file" accept="application/pdf,.pdf" onChange={uploadStory} />
          </label>
          {adoState && <p className="form-state" aria-live="polite">{adoState}</p>}
        </div>
      )}
      {mode === 'Settings' && (
        <div className="assistant-form settings-form">
          <h3>Connections</h3>
          <label>LiteLLM base URL<input value={form.base_url || ''} onChange={setField('base_url')} /></label>
          <label>API key<input type="password" value={form.api_key || ''} onChange={setField('api_key')} /></label>
          <label>Protocol
            <select value={form.protocol || 'auto'} onChange={setField('protocol')}>
              <option value="auto">Auto</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label>Primary model<input value={form.primary_model || ''} onChange={setField('primary_model')} /></label>
          <label>Fast model<input value={form.fast_model || ''} onChange={setField('fast_model')} /></label>
          <label>ADO organization<input value={form.ado_org || ''} onChange={setField('ado_org')} /></label>
          <label>ADO project<input value={form.ado_project || ''} onChange={setField('ado_project')} /></label>
          <label>ADO PAT<input type="password" value={form.ado_pat || ''} onChange={setField('ado_pat')} /></label>
          <div className="form-actions">
            <button type="button" className="secondary-button" onClick={() => onTestSettings(form)}>Test</button>
            <button type="button" className="primary-button" onClick={() => onSaveSettings(form)}>Save</button>
          </div>
          {settingsState && <p className="form-state" aria-live="polite">{settingsState}</p>}
        </div>
      )}
      {mode === 'Progress' && (
        <div className="progress-pane">
          {progress && (
            <div className="live-progress">
              <div><strong>{String(progress.phase || 'Working').replaceAll('_', ' ')}</strong><span>{progress.percent}%</span></div>
              <progress max="100" value={progress.percent} />
              <p>{progress.detail}</p>
            </div>
          )}
          <ol className="workflow-list">
            {STEPS.map((label, index) => {
              const step = index + 1;
              return (
                <li className={step === currentStep ? 'is-current' : step < currentStep ? 'is-complete' : ''} key={label}>
                  <span>{step < currentStep ? 'OK' : step}</span>
                  <div><strong>{label}</strong><small>{step === currentStep ? 'In progress' : step < currentStep ? 'Complete' : 'Waiting'}</small></div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </aside>
  );
}
