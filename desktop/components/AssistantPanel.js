'use client';

import { useEffect, useRef, useState } from 'react';

import { typedCrudApi } from '../lib/typed-crud-api';

function toolCalls(message) {
  const meta = message.metadata || {};
  if (Array.isArray(meta.tool_calls)) return meta.tool_calls;
  if (message.message_type === 'tool' && meta.tool) {
    return [{
      tool: meta.tool,
      status: meta.status || 'ok',
      object_uuids: Array.isArray(meta.object_uuids) ? meta.object_uuids : [],
    }];
  }
  return [];
}

function involvedObjects(message, objectCatalog) {
  const meta = message.metadata || {};
  if (Array.isArray(meta.objects) && meta.objects.length) return meta.objects;
  if (Array.isArray(meta.object_uuids)) {
    return meta.object_uuids.map((uuid) => objectCatalog[uuid] || { uuid, name: uuid });
  }
  return [];
}

function pendingDeletion(message) {
  const result = message.metadata?.result?.result;
  return result?.pending_deletion === true ? result : null;
}

function PendingDeletionCard({ payload, objectCatalog }) {
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState('');
  const object = payload.object || {};
  const dependencies = payload.reverse_dependencies || [];
  const confirmation = payload.confirmation || {};
  const forceRequired = confirmation.force_required === true && dependencies.length > 0;

  if (outcome) {
    return <div className="pending-delete-outcome" role="status">{outcome}</div>;
  }

  async function applyDelete() {
    setBusy(true);
    try {
      const result = await typedCrudApi.remove(
        confirmation.slug,
        confirmation.object_uuid,
        { preview: false, force: forceRequired ? force : false },
      );
      setOutcome(result?.status === 'deleted'
        ? `${object.name || object.uuid} was deleted.`
        : `Delete completed with status: ${result?.status || 'unknown'}.`);
    } catch (error) {
      setOutcome(`Delete failed: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="pending-delete-card" aria-label={`Confirm deletion of ${object.name || object.uuid}`}>
      <strong>Delete {object.name || object.uuid}?</strong>
      <p>
        {String(object.type || 'object').replaceAll('_', ' ')}. Nothing has been deleted yet.
        Deleting cannot be undone.
      </p>
      {dependencies.length > 0 && (
        <div className="pending-delete-dependencies">
          <strong>Objects that depend on this object:</strong>
          <ul>
            {dependencies.map((uuid) => (
              <li key={uuid}>{objectCatalog[uuid]?.name || uuid}</li>
            ))}
          </ul>
        </div>
      )}
      {forceRequired && (
        <label className="pending-delete-force">
          <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
          Force deletion. Dependent objects will break.
        </label>
      )}
      <div className="pending-delete-actions">
        <button type="button" className="secondary-button" disabled={busy} onClick={() => setOutcome('Deletion cancelled. Nothing was deleted.')}>Cancel</button>
        <button type="button" className="danger-button" disabled={busy || (forceRequired && !force)} onClick={applyDelete}>
          {busy ? 'Deleting...' : 'Delete object'}
        </button>
      </div>
    </section>
  );
}

export default function AssistantPanel({
  messages,
  connected,
  progress,
  selectedObjects,
  objectCatalog = {},
  onRemoveSelected,
  onSend,
  onFetchAdo,
  onUploadFiles,
}) {
  const [draft, setDraft] = useState('');
  const [adoId, setAdoId] = useState('');
  const [adoState, setAdoState] = useState('');
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' });
  }, [messages]);

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
      setAdoState(`Azure DevOps error: ${error.message}`);
    }
  }

  async function uploadFiles(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setAdoState(`Loading ${files.length} requirement file${files.length === 1 ? '' : 's'}...`);
    try {
      const result = await onUploadFiles(files);
      setAdoState(`${result.files?.length || files.length} requirement file${files.length === 1 ? '' : 's'} loaded.`);
    } catch (error) {
      setAdoState(`Attachment error: ${error.message}`);
    } finally {
      event.target.value = '';
    }
  }

  return (
    <section className="assistant-panel pane" aria-label="Sentinel chat">
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
        {progress && (
          <div className="live-progress" role="status">
            <div>
              <strong>{String(progress.phase || 'Working').replaceAll('_', ' ')}</strong>
              <span>{progress.percent}%</span>
            </div>
            <progress max="100" value={progress.percent} />
            <p>{progress.detail}</p>
          </div>
        )}
        {messages.length === 0 && (
          <div className="assistant-empty">
            <strong>Build with application context</strong>
            <p>Select objects on the left, then ask about requirements, tests, or impact.</p>
          </div>
        )}
        {messages.map((message, index) => {
          const objects = involvedObjects(message, objectCatalog);
          const calls = toolCalls(message);
          const deletion = pendingDeletion(message);
          const isTool = message.message_type === 'tool' || calls.length > 0 || objects.length > 0;
          return (
            <div className={`chat-message is-${message.role || 'assistant'}`} key={message.id || index}>
              <span>{message.role === 'user' ? 'You' : isTool ? 'Activity' : 'Sentinel'}</span>
              {objects.length > 0 && (
                <ul className="object-chip-list" aria-label="Objects in this turn">
                  {objects.map((item) => (
                    <li className="object-chip" key={item.uuid || item.name}>
                      <strong>{item.name || item.uuid}</strong>
                      <span>{String(item.type || '').replaceAll('_', ' ')}</span>
                    </li>
                  ))}
                </ul>
              )}
              {calls.length > 0 && (
                <ol className="tool-call-list" aria-label="Tool calls">
                  {calls.map((call, callIndex) => (
                    <li key={`${call.tool}-${call.object_uuid || callIndex}`}>
                      <code>{call.tool}</code>
                      <span>
                        {call.object_name || call.object_uuid || (call.object_uuids || [])
                          .map((uuid) => objectCatalog[uuid]?.name || uuid)
                          .join(', ')}
                      </span>
                      <span className={`tool-status is-${call.status || 'ok'}`}>{call.status || 'ok'}</span>
                    </li>
                  ))}
                </ol>
              )}
              {deletion
                ? <PendingDeletionCard payload={deletion} objectCatalog={objectCatalog} />
                : <p>{message.content}</p>}
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
      {selectedObjects.length > 0 && (
        <div className="chat-selected-objects" aria-label="Selected chat objects">
          {selectedObjects.map((item) => (
            <button
              type="button"
              className="object-chip is-removable"
              key={item.uuid}
              onClick={() => onRemoveSelected(item.uuid)}
              title="Remove from chat context"
            >
              {item.name}
            </button>
          ))}
        </div>
      )}
      <div className="chat-context-bar" aria-label="Add requirement context">
        <label className="ado-chat-field">
          <span>Azure DevOps work item</span>
          <input
            value={adoId}
            onChange={(event) => setAdoId(event.target.value)}
            placeholder="1536949"
            inputMode="numeric"
          />
        </label>
        <button
          className="secondary-button"
          type="button"
          disabled={!adoId.trim()}
          onClick={fetchAdo}
          title="Load an Azure DevOps work item"
        >
          Load work item
        </button>
        <label className="attachment-button">
          Attach files (PDF, TXT, MD; up to 10)
          <input
            type="file"
            accept="application/pdf,.pdf,text/plain,.txt,text/markdown,.md"
            multiple
            onChange={uploadFiles}
          />
        </label>
        {adoState && (
          <p
            className={`chat-context-state ${adoState.includes('error:') ? 'is-error' : ''}`}
            role={adoState.includes('error:') ? 'alert' : 'status'}
          >
            {adoState}
          </p>
        )}
      </div>
      <div className="composer">
        <textarea
          aria-label="Message Sentinel"
          rows="3"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={connected ? 'Ask Sentinel...' : 'Connection required'}
          disabled={!connected}
        />
        <div><span>Enter to send</span><button type="button" onClick={submit} disabled={!connected || !draft.trim()}>Send</button></div>
      </div>
    </section>
  );
}
