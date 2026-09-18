'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { decorateTokens, positionToOffset, referenceAt } from '../lib/sail-highlight';
import { extractSymbols } from '../lib/sail-symbols';

const SOURCE_FIELDS = ['definition', 'expression', 'value'];

function getSource(object) {
  const field = SOURCE_FIELDS.find((name) => typeof object?.[name] === 'string' && object[name]);
  return field ? object[field] : '';
}

function LineNumbers({ value, numbersRef }) {
  const numbers = useMemo(() => Array.from(
    { length: Math.max(1, value.split('\n').length) },
    (_, index) => index + 1,
  ).join('\n'), [value]);
  return <pre className="line-numbers" ref={numbersRef} aria-hidden="true">{numbers}</pre>;
}

function HighlightedSource({ source, diagnostics }) {
  const tokens = useMemo(
    () => decorateTokens(source, diagnostics),
    [source, diagnostics],
  );
  return (
    <pre className="highlight-layer" aria-hidden="true">
      {tokens.map((token) => (
        <span
          className={[
            `sail-${token.type}`,
            token.invalid ? 'is-invalid' : '',
            token.diagnostic ? `has-diagnostic is-${token.diagnostic}` : '',
          ].filter(Boolean).join(' ')}
          key={`${token.start}-${token.end}`}
        >
          {token.value}
        </span>
      ))}
    </pre>
  );
}

export default function EditorWorkspace({
  tabs,
  activeId,
  object,
  diagnostics,
  jumpRequest,
  navigation,
  loading,
  error,
  codebaseLoading,
  codebaseLoaded,
  onActivate,
  onClose,
  onSave,
  onOpenObject,
}) {
  const [view, setView] = useState('source');
  const [source, setSource] = useState('');
  const [savedSource, setSavedSource] = useState('');
  const [copyState, setCopyState] = useState('Copy source');
  const [saveState, setSaveState] = useState('');
  const [choices, setChoices] = useState([]);
  const editorRef = useRef(null);
  const highlightRef = useRef(null);
  const lineNumbersRef = useRef(null);
  const historyRef = useRef({ items: [''], index: 0 });
  const tab = tabs.find((item) => item.uuid === activeId);
  const symbols = useMemo(() => extractSymbols(source), [source]);
  const problems = diagnostics?.diagnostics || diagnostics?.items || [];

  useEffect(() => {
    const initial = getSource(object);
    setSource(initial);
    setSavedSource(initial);
    historyRef.current = { items: [initial], index: 0 };
    setView('source');
    setCopyState('Copy source');
  }, [object]);

  useEffect(() => setSaveState(''), [activeId]);

  useEffect(() => {
    if (!jumpRequest || jumpRequest.uuid !== activeId) return;
    const start = positionToOffset(source, jumpRequest.line, jumpRequest.column);
    const end = positionToOffset(
      source,
      jumpRequest.end_line || jumpRequest.line,
      jumpRequest.end_column || jumpRequest.column + 1,
    );
    editorRef.current?.focus();
    editorRef.current?.setSelectionRange(start, Math.max(start + 1, end));
    if (editorRef.current) editorRef.current.scrollTop = Math.max(0, (jumpRequest.line - 2) * 20);
    syncScroll();
  }, [activeId, jumpRequest, source]);

  function recordChange(value) {
    const history = historyRef.current;
    const items = history.items.slice(0, history.index + 1);
    if (items[items.length - 1] === value) return;
    items.push(value);
    if (items.length > 100) items.shift();
    historyRef.current = { items, index: items.length - 1 };
    setSource(value);
  }

  function moveHistory(delta) {
    const history = historyRef.current;
    const index = Math.max(0, Math.min(history.items.length - 1, history.index + delta));
    if (index === history.index) return;
    history.index = index;
    setSource(history.items[index]);
  }

  function editorShortcut(event) {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === 's') {
      event.preventDefault();
      if (codebaseLoaded && tab && source !== savedSource) saveSource();
      return;
    }
    if (key === 'z' && !event.shiftKey) {
      event.preventDefault();
      moveHistory(-1);
      return;
    }
    if (key === 'y' || (key === 'z' && event.shiftKey)) {
      event.preventDefault();
      moveHistory(1);
    }
  }

  function syncScroll() {
    if (!editorRef.current) return;
    if (highlightRef.current) {
      highlightRef.current.scrollTop = editorRef.current.scrollTop;
      highlightRef.current.scrollLeft = editorRef.current.scrollLeft;
    }
    if (lineNumbersRef.current) lineNumbersRef.current.scrollTop = editorRef.current.scrollTop;
  }

  function jumpTo(offset) {
    editorRef.current?.focus();
    editorRef.current?.setSelectionRange(offset, offset);
    const line = source.slice(0, offset).split('\n').length;
    if (editorRef.current) editorRef.current.scrollTop = Math.max(0, (line - 2) * 20);
    syncScroll();
  }

  function followReference() {
    const reference = referenceAt(source, editorRef.current?.selectionStart || 0);
    if (!reference) return;
    const matches = navigation?.resolve(reference) || [];
    if (matches.length === 1) onOpenObject(matches[0]);
    if (matches.length > 1) setChoices(matches);
  }

  async function copySource() {
    try {
      await navigator.clipboard.writeText(source);
      setCopyState('Copied');
      window.setTimeout(() => setCopyState('Copy source'), 1200);
    } catch {
      setCopyState('Copy failed');
    }
  }

  async function saveSource() {
    setSaveState('Saving...');
    try {
      await onSave(tab.uuid, source);
      setSavedSource(source);
      setSaveState('Saved');
    } catch (saveError) {
      setSaveState(`Save failed: ${saveError.message}`);
    }
  }

  return (
    <section className="editor-shell" aria-label="Editor">
      <div className="editor-tabs" role="tablist" aria-label="Open objects">
        {tabs.length ? tabs.map((item) => (
          <div className={`file-tab ${item.uuid === activeId ? 'is-active' : ''}`} key={item.uuid}>
            <button
              type="button"
              className="tab-select"
              role="tab"
              aria-selected={item.uuid === activeId}
              onClick={() => onActivate(item.uuid)}
            >
              <span className="dirty-dot">{item.uuid === activeId && source !== savedSource ? '*' : ''}</span>
              <span className="tab-name">{item.name}</span>
            </button>
            <button type="button" className="tab-close" aria-label={`Close ${item.name}`} onClick={() => onClose(item.uuid)}>x</button>
          </div>
        )) : <span className="empty-tab">No object open</span>}
      </div>

      {!tab && (
        <div className="editor-welcome">
          <span className="welcome-mark" aria-hidden="true">AS</span>
          <h1>
            {codebaseLoading
              ? 'Loading Appian application'
              : codebaseLoaded ? 'Appian workbench' : 'Import an Appian application'}
          </h1>
          <p>
            {codebaseLoading
              ? 'Reading application objects from the sidecar.'
              : codebaseLoaded
                ? 'Select an object from the explorer to inspect its source and metadata.'
                : 'Use Import application in the top bar to load an Appian export ZIP.'}
          </p>
          {codebaseLoaded && (
            <div className="shortcut-list">
              <span>Find object</span><kbd>Ctrl</kbd><kbd>K</kbd>
              <span>Copy source</span><kbd>Ctrl</kbd><kbd>C</kbd>
            </div>
          )}
        </div>
      )}

      {tab && (
        <>
          <div className="editor-toolbar">
            <div className="segmented" role="tablist" aria-label="Object view">
              <button type="button" role="tab" aria-selected={view === 'source'} onClick={() => setView('source')}>Source</button>
              <button type="button" role="tab" aria-selected={view === 'metadata'} onClick={() => setView('metadata')}>Metadata</button>
            </div>
            <div className="editor-actions">
              <span className="object-type">{object?.object_type?.replaceAll('_', ' ') || 'object'}</span>
              <button type="button" className="secondary-button" disabled={!source || loading} onClick={copySource}>{copyState}</button>
              <button
                type="button"
                className="primary-button compact"
                disabled={!codebaseLoaded || !source || source === savedSource}
                title={codebaseLoaded ? 'Save source (Ctrl+S)' : 'Load an export to save source.'}
                onClick={saveSource}
              >
                Save
              </button>
            </div>
          </div>
          <div className="object-context">
            <strong>{tab.name}</strong>
            <span>{tab.uuid}</span>
          </div>
          <div className="editor-content" aria-live="polite">
            {loading && <div className="center-state">Loading object source...</div>}
            {!loading && error && <div className="center-state error-text">Could not open object: {error}</div>}
            {!loading && !error && object && view === 'source' && (
              source ? (
                <div className="editor-with-outline">
                  <div className="code-editor">
                    <LineNumbers value={source} numbersRef={lineNumbersRef} />
                    <div className="source-layers">
                      <div className="highlight-scroll" ref={highlightRef}>
                        <HighlightedSource source={source} diagnostics={problems} />
                      </div>
                      <textarea
                        ref={editorRef}
                        aria-label={`${tab.name} source editor`}
                        value={source}
                        onChange={(event) => recordChange(event.target.value)}
                        onDoubleClick={followReference}
                        onKeyDown={editorShortcut}
                        onScroll={syncScroll}
                        spellCheck="false"
                      />
                    </div>
                  </div>
                  <aside className="symbol-outline" aria-label="Symbol outline">
                    <h3>Outline</h3>
                    {symbols.length ? symbols.map((symbol) => (
                      <button
                        type="button"
                        key={`${symbol.kind}-${symbol.offset}`}
                        onClick={() => jumpTo(symbol.offset)}
                      >
                        <b>{symbol.kind}</b>
                        <span>{symbol.name}</span>
                        <small>{symbol.line}</small>
                      </button>
                    )) : <p>No symbols found.</p>}
                  </aside>
                </div>
              ) : <div className="center-state">This object has no editable source definition.</div>
            )}
            {!loading && !error && object && view === 'metadata' && (
              <pre className="metadata-view">{JSON.stringify(object, null, 2)}</pre>
            )}
          </div>
          {(saveState || !codebaseLoaded) && (
            <div className="editor-status">
              {saveState || 'Save disabled: load an export first.'}
            </div>
          )}
          {choices.length > 0 && (
            <div className="reference-choice" role="dialog" aria-label="Choose referenced object">
              <strong>Choose object</strong>
              {choices.map((item) => (
                <button type="button" key={item.uuid} onClick={() => {
                  setChoices([]);
                  onOpenObject(item);
                }}>
                  {item.name} ({item.type.replaceAll('_', ' ')})
                </button>
              ))}
              <button type="button" onClick={() => setChoices([])}>Cancel</button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
