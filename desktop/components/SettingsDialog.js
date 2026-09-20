'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function ModelField({ label, value, models, onChange }) {
  if (!models.length) {
    return (
      <label>
        {label}
        <input value={value} onChange={onChange} placeholder="bedrock.anthropic.claude-sonnet-5" />
      </label>
    );
  }
  const options = models.includes(value) || !value ? models : [value, ...models];
  return (
    <label>
      {label}
      <select value={value} onChange={onChange}>
        {!value && <option value="">Select a model</option>}
        {options.map((model) => (
          <option key={model} value={model}>
            {models.includes(model) ? model : `${model} (not listed by gateway)`}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function SettingsDialog({
  open,
  settings,
  settingsState,
  onClose,
  onSaveSettings,
  onTestSettings,
  onListModels,
}) {
  const [form, setForm] = useState(settings);
  const [models, setModels] = useState([]);
  const [modelsState, setModelsState] = useState('');
  const dialogRef = useRef(null);
  const initialFocusRef = useRef(null);
  const returnFocusRef = useRef(null);

  useEffect(() => setForm(settings), [settings]);

  const loadModels = useCallback(async () => {
    if (!onListModels) return;
    setModelsState('Loading models...');
    try {
      const result = await onListModels();
      setModels(result.models || []);
      setModelsState(result.models?.length ? '' : 'The gateway returned no models.');
    } catch (error) {
      setModels([]);
      setModelsState(`Model list unavailable: ${error.message}`);
    }
  }, [onListModels]);

  useEffect(() => {
    if (open) loadModels();
  }, [open, loadModels]);

  useEffect(() => {
    if (!open) return undefined;
    returnFocusRef.current = document.activeElement;
    window.requestAnimationFrame(() => initialFocusRef.current?.focus());

    function onKey(event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...(dialogRef.current?.querySelectorAll(FOCUSABLE_SELECTOR) || [])];
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      returnFocusRef.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const setField = (name) => (event) => setForm((value) => ({ ...value, [name]: event.target.value }));

  return (
    <div className="settings-overlay" role="presentation" onClick={onClose}>
      <div
        ref={dialogRef}
        className="settings-dialog assistant-form settings-form"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="settings-dialog-heading">
          <h2 id="settings-title">Settings</h2>
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
        </div>
        <p className="settings-section-label">Connections</p>
        <label>Model service URL<input ref={initialFocusRef} value={form.base_url || ''} onChange={setField('base_url')} /></label>
        <label>API key<input type="password" value={form.api_key || ''} onChange={setField('api_key')} /></label>
        <label>Connection type
          <select value={form.protocol || 'auto'} onChange={setField('protocol')}>
            <option value="auto">Automatic</option><option value="openai">Compatible API</option><option value="anthropic">Direct API</option>
          </select>
        </label>
        <ModelField
          label="Primary model"
          value={form.primary_model || ''}
          models={models}
          onChange={setField('primary_model')}
        />
        <ModelField
          label="Fast model"
          value={form.fast_model || ''}
          models={models}
          onChange={setField('fast_model')}
        />
        {modelsState && (
          <p className="form-state" aria-live="polite">
            {modelsState}{' '}
            <button type="button" className="link-button" onClick={loadModels}>Retry</button>
          </p>
        )}
        <label>Azure DevOps organization<input value={form.ado_org || ''} onChange={setField('ado_org')} /></label>
        <label>Azure DevOps project<input value={form.ado_project || ''} onChange={setField('ado_project')} /></label>
        <label>Azure DevOps access token<input type="password" value={form.ado_pat || ''} onChange={setField('ado_pat')} /></label>
        <div className="form-actions">
          <button
            type="button"
            className="secondary-button"
            title="Save these settings and test the connection"
            onClick={() => onTestSettings(form)}
          >
            Test
          </button>
          <button
            type="button"
            className="primary-button"
            title="Save connection settings"
            onClick={() => onSaveSettings(form)}
          >
            Save
          </button>
        </div>
        {settingsState && <p className="form-state" aria-live="polite">{settingsState}</p>}
      </div>
    </div>
  );
}
