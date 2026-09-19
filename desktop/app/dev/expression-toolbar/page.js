'use client';

import { useEffect, useRef, useState } from 'react';
import ExpressionDocs from '../../../components/ExpressionDocs';
import ExpressionToolbar from '../../../components/ExpressionToolbar';

const INITIAL_VALUE = [
  'a!localVariables(',
  'local!message: "Keep (all) [brackets] {inside} this string",',
  'a!textField(',
  'label: "Demo",',
  'value: local!message',
  ')',
  ')',
].join('\n');

function functionAt(value, offset) {
  const expression = /\b(?:a![A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\s*(?=\()/g;
  let match = expression.exec(value);
  let previous = '';
  while (match) {
    if (offset >= match.index && offset <= match.index + match[0].length) return match[0].trim();
    if (match.index <= offset) previous = match[0].trim();
    match = expression.exec(value);
  }
  return previous;
}

export default function ExpressionToolbarHarness() {
  const [value, setValue] = useState(INITIAL_VALUE);
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [indentGuide, setIndentGuide] = useState(false);
  const [showFunctions, setShowFunctions] = useState(false);
  const [functionName, setFunctionName] = useState('a!textField');
  const [mode, setMode] = useState('dark');
  const [ready, setReady] = useState(false);
  const textareaRef = useRef(null);

  useEffect(() => setReady(true), []);

  function updateSelection(event) {
    const next = {
      start: event.currentTarget.selectionStart,
      end: event.currentTarget.selectionEnd,
    };
    setSelection(next);
    const highlighted = functionAt(value, next.start);
    if (highlighted) setFunctionName(highlighted);
  }

  function changeValue(event) {
    const nextValue = event.currentTarget.value;
    const nextSelection = {
      start: event.currentTarget.selectionStart,
      end: event.currentTarget.selectionEnd,
    };
    setValue(nextValue);
    setSelection(nextSelection);
    const highlighted = functionAt(nextValue, nextSelection.start);
    if (highlighted) setFunctionName(highlighted);
  }

  function updateValue(nextValue, nextSelection) {
    setValue(nextValue);
    setSelection(nextSelection);
    window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextSelection.start, nextSelection.end);
    });
  }

  function toggleMode() {
    const nextMode = mode === 'dark' ? 'light' : 'dark';
    setMode(nextMode);
    document.documentElement.dataset.theme = nextMode;
  }

  return (
    <main className="expression-harness" data-ready={ready}>
      <ExpressionToolbar
        value={value}
        selectionStart={selection.start}
        selectionEnd={selection.end}
        onChange={updateValue}
        indentGuide={indentGuide}
        onToggleIndentGuide={() => setIndentGuide((current) => !current)}
        onViewFunctions={() => setShowFunctions(true)}
      />
      <div className="expression-harness-main">
        <section className="expression-harness-editor" aria-label="Expression editing pane">
          <div className="expression-harness-controls">
            <button type="button" onClick={toggleMode}>
              Use {mode === 'dark' ? 'light' : 'dark'} theme
            </button>
          </div>
          <textarea
            ref={textareaRef}
            aria-label="SAIL expression"
            className={indentGuide ? 'has-indent-guide' : ''}
            value={value}
            onChange={changeValue}
            onClick={updateSelection}
            onKeyUp={updateSelection}
            onSelect={updateSelection}
            spellCheck="false"
          />
        </section>
        <ExpressionDocs
          functionName={functionName}
          showFunctions={showFunctions}
          onSelectFunction={setFunctionName}
        />
      </div>
    </main>
  );
}
