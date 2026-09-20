'use client';

import { useEffect, useRef, useState } from 'react';

import { objectMeta } from '../lib/appian-objects';
import { typedCrudApi } from '../lib/typed-crud-api';

const CREATE_UNAVAILABLE_TYPES = new Set([
  'ai_agent',
  'ai_skill',
  'business_process',
  'control_panel',
  'control_panel_hierarchy_item',
  'dashboard',
  'event_consumer',
  'feed',
  'group_type',
  'process_report',
  'robot_pool',
  'robotic_task',
]);

function parseFields(value) {
  const fields = JSON.parse(value || '{}');
  if (!fields || Array.isArray(fields) || typeof fields !== 'object') {
    throw new Error('Fields must be a JSON object.');
  }
  return fields;
}

export default function TypedCrudDialog({
  open,
  objectTypes,
  selectedObject,
  onClose,
  onChanged,
}) {
  const [slug, setSlug] = useState('');
  const [uuid, setUuid] = useState('');
  const [name, setName] = useState('');
  const [fieldsText, setFieldsText] = useState('{}');
  const [force, setForce] = useState(false);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const initialFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setSlug(selectedObject?.type || objectTypes[0] || '');
    setUuid(selectedObject?.uuid || '');
    setName(selectedObject?.name || '');
    setFieldsText('{}');
    setForce(false);
    setStatus('');
    setConfirmDelete(false);
    window.requestAnimationFrame(() => initialFocusRef.current?.focus());
  }, [objectTypes, open, selectedObject]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [busy, onClose, open]);

  if (!open) return null;

  async function run(operation, preview) {
    if (operation === 'delete' && !preview) setConfirmDelete(false);
    setBusy(true);
    setStatus(`${preview ? 'Previewing' : 'Applying'} ${operation}...`);
    try {
      const fields = operation === 'delete' ? {} : parseFields(fieldsText);
      let result;
      if (operation === 'create') {
        result = await typedCrudApi.create(slug, { name, fields, preview });
      } else if (operation === 'update') {
        result = await typedCrudApi.update(slug, uuid, { fields, preview });
      } else {
        result = await typedCrudApi.remove(slug, uuid, { force, preview });
      }
      setStatus(`${operation[0].toUpperCase()}${operation.slice(1)} ${result.status}.`);
      if (!preview) await onChanged(operation, result);
    } catch (error) {
      setStatus(`${operation[0].toUpperCase()}${operation.slice(1)} failed: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  const hasTarget = Boolean(slug.trim() && uuid.trim());
  const createUnavailable = CREATE_UNAVAILABLE_TYPES.has(slug);
  const canCreate = Boolean(slug.trim() && name.trim() && !createUnavailable);

  return (
    <div className="settings-overlay" role="presentation" onClick={() => !busy && onClose()}>
      <section
        className="settings-dialog typed-crud-dialog assistant-form"
        role="dialog"
        aria-modal="true"
        aria-labelledby="typed-crud-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="settings-dialog-heading">
          <h2 id="typed-crud-title">Object operations</h2>
          <button type="button" className="secondary-button" onClick={onClose} disabled={busy}>Close</button>
        </div>
        <p className="settings-section-label">Object operation</p>
        <label>
          Object type
          <select
            ref={initialFocusRef}
            aria-label="Object type"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
          >
            <option value="">Select a type</option>
            {objectTypes.map((type) => (
              <option key={type} value={type}>
                {objectMeta(type).label}
                {CREATE_UNAVAILABLE_TYPES.has(type) ? ' (create unavailable)' : ''}
              </option>
            ))}
          </select>
        </label>
        {createUnavailable && (
          <p className="typed-operation-note" role="status">
            Create unavailable: no example of this type exists in the imported application.
            You can still read, update, or delete an existing object.
          </p>
        )}
        <label>Object ID<input value={uuid} onChange={(event) => setUuid(event.target.value)} /></label>
        <label>Object name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label>
          Properties to change
          <textarea rows="4" value={fieldsText} onChange={(event) => setFieldsText(event.target.value)} spellCheck="false" />
          <span className="field-help">Enter property names and values in JSON format.</span>
        </label>
        <label className="typed-force-option">
          <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
          Allow delete when dependencies exist
        </label>
        <div className="typed-crud-actions">
          <span>
            <button type="button" className="secondary-button" disabled={busy || !canCreate} onClick={() => run('create', true)}>Preview create</button>
            <button type="button" className="primary-button compact" disabled={busy || !canCreate} onClick={() => run('create', false)}>Create</button>
          </span>
          <span>
            <button type="button" className="secondary-button" disabled={busy || !hasTarget} onClick={() => run('update', true)}>Preview update</button>
            <button type="button" className="primary-button compact" disabled={busy || !hasTarget} onClick={() => run('update', false)}>Update</button>
          </span>
          <span>
            <button type="button" className="secondary-button" disabled={busy || !hasTarget} onClick={() => run('delete', true)}>Preview delete</button>
            <button type="button" className="danger-button" disabled={busy || !hasTarget} onClick={() => setConfirmDelete(true)}>Delete</button>
          </span>
        </div>
        {confirmDelete && (
          <div className="delete-confirmation" role="alert">
            <strong>Delete {name.trim() || uuid.trim()}?</strong>
            <p>This object will be permanently deleted. This cannot be undone.</p>
            <div>
              <button type="button" className="secondary-button" disabled={busy} onClick={() => setConfirmDelete(false)}>Cancel</button>
              <button type="button" className="danger-button" disabled={busy} onClick={() => run('delete', false)}>Confirm delete</button>
            </div>
          </div>
        )}
        {status && <p className="form-state" role={status.includes('failed:') ? 'alert' : 'status'}>{status}</p>}
      </section>
    </div>
  );
}
