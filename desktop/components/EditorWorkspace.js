'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { decorateTokens, positionToOffset, referenceAt } from '../lib/sail-highlight';
import { extractSymbols } from '../lib/sail-symbols';
import { api } from '../lib/api';
import AdHocTestPanel from './AdHocTestPanel';
import BuildGrid from './BuildGrid';
import ExpressionDocs from './ExpressionDocs';
import ExpressionToolbar from './ExpressionToolbar';
import { RuleInputsPanel, RuleTestPanel } from './RuleWorkspace';

const SOURCE_FIELDS = ['definition', 'expression', 'value'];
const RULE_PANE_STORAGE_KEY = 'appian-sentinel-rule-pane-sizes';

function RuleResizeHandle({ label, onDelta }) {
  function startResize(event) {
    let previous = event.clientX;
    const move = (moveEvent) => {
      onDelta(moveEvent.clientX - previous);
      previous = moveEvent.clientX;
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

  return (
    <div
      className="rule-resize-handle"
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      tabIndex={0}
      onPointerDown={startResize}
      onKeyDown={(event) => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        onDelta(event.key === 'ArrowLeft' ? -16 : 16);
      }}
    />
  );
}

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

function InterfaceDesignView({ object, source }) {
  const components = ['Text', 'Text Field', 'Dropdown', 'Button', 'Section', 'Columns', 'Grid'];
  return (
    <div className="interface-designer" aria-label="Interface design mode">
      <aside className="interface-palette" aria-label="Component palette">
        <div className="interface-pane-heading">
          <strong>Palette</strong>
          <span>Components</span>
        </div>
        <label className="interface-search">
          <span className="sr-only">Search components</span>
          <input type="search" placeholder="Search components" />
        </label>
        <div className="interface-component-list">
          {components.map((component) => (
            <button type="button" disabled key={component} title="Requires a live Appian designer">
              <span aria-hidden="true">+</span>
              {component}
            </button>
          ))}
        </div>
      </aside>
      <section className="interface-live-view" aria-label="Interface live view">
        <div className="interface-preview-toolbar">
          <strong>Live View</strong>
          <span>Desktop</span>
          <button type="button" disabled>Preview</button>
        </div>
        <div className="interface-preview">
          <div className="interface-preview-notice">
            <strong>Preview requires an Appian runtime</strong>
            <p>The exported expression remains available in Expression mode.</p>
          </div>
          <pre>{source.slice(0, 1200)}</pre>
        </div>
      </section>
      <aside className="interface-configuration" aria-label="Component configuration">
        <div className="interface-pane-heading">
          <strong>Configuration</strong>
          <span>Rule Inputs</span>
        </div>
        {(object.rule_inputs || []).length ? (
          <ul>
            {object.rule_inputs.map((input) => (
              <li key={input.name}>
                <strong>{input.name}</strong>
                <span>{input.type_name || input.type || 'Any Type'}</span>
              </li>
            ))}
          </ul>
        ) : <p>No rule inputs.</p>}
      </aside>
    </div>
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
  codebase,
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
  const [editorSelection, setEditorSelection] = useState({ start: 0, end: 0 });
  const [indentGuide, setIndentGuide] = useState(false);
  const [showFunctionList, setShowFunctionList] = useState(false);
  const [docsFunction, setDocsFunction] = useState('');
  const [savedTestCases, setSavedTestCases] = useState([]);
  const [rulePaneSizes, setRulePaneSizes] = useState({ source: 190, inputs: 130 });
  const editorRef = useRef(null);
  const highlightRef = useRef(null);
  const lineNumbersRef = useRef(null);
  const historyRef = useRef({ items: [''], index: 0 });
  const tab = tabs.find((item) => item.uuid === activeId);
  const symbols = useMemo(() => extractSymbols(source), [source]);
  const problems = diagnostics?.diagnostics || diagnostics?.items || [];
  const isExpressionRule = object?.object_type === 'expression_rule';
  const isInterface = object?.object_type === 'interface';

  useEffect(() => {
    const initial = getSource(object);
    setSource(initial);
    setSavedSource(initial);
    historyRef.current = { items: [initial], index: 0 };
    setView(object?.object_type === 'interface' ? 'design' : 'source');
    setCopyState('Copy source');
  }, [object]);

  useEffect(() => setSaveState(''), [activeId]);

  useEffect(() => {
    try {
      const saved = JSON.parse(
        window.localStorage.getItem(RULE_PANE_STORAGE_KEY) || '{}',
      );
      setRulePaneSizes({
        source: Math.max(170, Math.min(420, Number(saved.source) || 190)),
        inputs: Math.max(120, Math.min(280, Number(saved.inputs) || 130)),
      });
    } catch {
      setRulePaneSizes({ source: 190, inputs: 130 });
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(
      RULE_PANE_STORAGE_KEY,
      JSON.stringify(rulePaneSizes),
    );
  }, [rulePaneSizes]);

  useEffect(() => {
    let active = true;
    if (!activeId || !isExpressionRule) {
      setSavedTestCases([]);
      return () => { active = false; };
    }
    api.objectTests(activeId)
      .then((value) => {
        if (active) setSavedTestCases(Array.isArray(value?.tests) ? value.tests : []);
      })
      .catch(() => {
        if (active) setSavedTestCases([]);
      });
    return () => { active = false; };
  }, [activeId, isExpressionRule]);

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

  function captureSelection(event) {
    setEditorSelection({
      start: event.currentTarget.selectionStart,
      end: event.currentTarget.selectionEnd,
    });
  }

  function applyExpressionChange(nextValue, nextSelection) {
    recordChange(nextValue);
    setEditorSelection(nextSelection);
    // The textarea is uncontrolled with respect to selection, so the caret
    // has to be restored after React commits the new value.
    window.requestAnimationFrame(() => {
      editorRef.current?.focus();
      editorRef.current?.setSelectionRange(nextSelection.start, nextSelection.end);
    });
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

      {!tab && codebaseLoaded && (
        <BuildGrid
          codebase={codebase}
          onOpenObject={onOpenObject}
          reverseDependencies={codebase?.reverse_dependencies}
          parentByUuid={codebase?.parent_by_uuid}
        />
      )}

      {!tab && !codebaseLoaded && (
        <div className="editor-welcome">
          <span className="welcome-mark" aria-hidden="true">
            <img src="/icon.png" alt="" />
          </span>
          <h1>
            {codebaseLoading ? 'Loading Appian application' : 'Import an Appian application'}
          </h1>
          <p>
            {codebaseLoading
              ? 'Reading application objects.'
              : 'Use Import application in the top bar to load an Appian export ZIP.'}
          </p>
        </div>
      )}

      {tab && (
        <>
          <div className="editor-toolbar">
            <div className="segmented" role="tablist" aria-label="Object view">
              {isInterface && (
                <button type="button" role="tab" aria-selected={view === 'design'} onClick={() => setView('design')}>Design</button>
              )}
              <button type="button" role="tab" aria-selected={view === 'source'} onClick={() => setView('source')}>
                {isInterface ? 'Expression' : 'Source'}
              </button>
              <button type="button" role="tab" aria-selected={view === 'metadata'} onClick={() => setView('metadata')}>Metadata</button>
              {!isExpressionRule && (
                <button type="button" role="tab" aria-selected={view === 'test'} onClick={() => setView('test')}>Ad Hoc Test</button>
              )}
            </div>
            <div className="editor-actions">
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
            <span className="object-type">{object?.object_type?.replaceAll('_', ' ') || 'object'}</span>
            <span>{tab.uuid}</span>
          </div>
          <div className="editor-content" aria-live="polite">
            {loading && <div className="center-state">Loading object source...</div>}
            {!loading && error && <div className="center-state error-text">Could not open object: {error}</div>}
            {!loading && !error && object && view === 'source' && source && (
              <ExpressionToolbar
                value={source}
                selectionStart={editorSelection.start}
                selectionEnd={editorSelection.end}
                onChange={applyExpressionChange}
                indentGuide={indentGuide}
                onToggleIndentGuide={() => setIndentGuide((current) => !current)}
                onViewFunctions={() => setShowFunctionList((current) => !current)}
              />
            )}
            {!loading && !error && object && view === 'source' && (
              source ? (
                isExpressionRule ? (
                  <div
                    className="appian-rule-workspace"
                    style={{
                      '--rule-source-width': `${rulePaneSizes.source}px`,
                      '--rule-input-width': `${rulePaneSizes.inputs}px`,
                    }}
                  >
                    <section className="rule-source-pane" aria-label="Rule source">
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
                            onKeyUp={captureSelection}
                            onSelect={captureSelection}
                            onClick={captureSelection}
                            onScroll={syncScroll}
                            spellCheck="false"
                          />
                        </div>
                      </div>
                    </section>
                    <RuleResizeHandle
                      label="Resize rule source"
                      onDelta={(delta) => setRulePaneSizes((current) => ({
                        ...current,
                        source: Math.max(170, Math.min(420, current.source + delta)),
                      }))}
                    />
                    <RuleTestPanel
                      ruleInputs={object.rule_inputs || []}
                      savedTestCases={savedTestCases}
                      onRunTest={(inputs) => api.runObjectStaticTest(activeId, inputs)}
                    />
                    <RuleResizeHandle
                      label="Resize rule inputs"
                      onDelta={(delta) => setRulePaneSizes((current) => ({
                        ...current,
                        inputs: Math.max(120, Math.min(280, current.inputs - delta)),
                      }))}
                    />
                    <RuleInputsPanel
                      ruleInputs={object.rule_inputs || []}
                      symbols={symbols}
                      onJumpTo={jumpTo}
                    />
                    {showFunctionList && (
                      <ExpressionDocs
                        functionName={docsFunction}
                        showFunctions
                        onSelectFunction={setDocsFunction}
                      />
                    )}
                  </div>
                ) : (
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
                          onKeyUp={captureSelection}
                          onSelect={captureSelection}
                          onClick={captureSelection}
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
                    {showFunctionList && (
                      <ExpressionDocs
                        functionName={docsFunction}
                        showFunctions
                        onSelectFunction={setDocsFunction}
                      />
                    )}
                  </div>
                )
              ) : <div className="center-state">This object has no editable source definition.</div>
            )}
            {!loading && !error && object && view === 'metadata' && (
              <pre className="metadata-view">{JSON.stringify(object, null, 2)}</pre>
            )}
            {!loading && !error && object && view === 'design' && isInterface && (
              <InterfaceDesignView object={object} source={source} />
            )}
            {!loading && !error && object && view === 'test' && (
              <AdHocTestPanel
                ruleInputs={object.rule_inputs || []}
                onRunTest={(inputs) => api.runObjectStaticTest(activeId, inputs)}
              />
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
