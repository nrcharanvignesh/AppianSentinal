'use client';

import { useMemo, useState } from 'react';
import '../app/expression-toolbar.css';
import {
  changeIndent,
  findMatches,
  formatExpression,
  replaceAll,
  replaceMatch,
  toggleComment,
} from '../lib/sail-format';

const LIVE_ACTIONS = [
  ['View Domains', 'onViewDomains'],
  ['View Icons', 'onViewIcons'],
  ['Create Constant', 'onCreateConstant'],
  ['Save Selected Expression As...', 'onSaveSelectedExpression'],
  ['Launch the Query Editor', 'onLaunchQueryEditor'],
];

function ActionButton({ label, title = label, disabled = false, onClick }) {
  return (
    <button
      type="button"
      className="expression-action"
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

export default function ExpressionToolbar({
  value,
  selectionStart,
  selectionEnd,
  onChange,
  indentGuide,
  onToggleIndentGuide,
  onViewFunctions,
  onViewDomains,
  onViewIcons,
  onCreateConstant,
  onSaveSelectedExpression,
  onLaunchQueryEditor,
}) {
  const [searchMode, setSearchMode] = useState('');
  const [query, setQuery] = useState('');
  const [replacement, setReplacement] = useState('');
  const callbacks = {
    onViewDomains,
    onViewIcons,
    onCreateConstant,
    onSaveSelectedExpression,
    onLaunchQueryEditor,
  };
  const matches = useMemo(() => findMatches(value, query), [query, value]);
  const activeIndex = matches.findIndex(
    (match) => match.start === selectionStart && match.end === selectionEnd,
  );

  function apply(result) {
    onChange(result.value, result.selection);
  }

  function moveMatch(direction) {
    if (!matches.length) return;
    const current = activeIndex >= 0 ? activeIndex : (direction > 0 ? -1 : 0);
    const index = (current + direction + matches.length) % matches.length;
    onChange(value, matches[index]);
  }

  function replaceCurrent() {
    if (!matches.length) return;
    const match = matches[activeIndex >= 0 ? activeIndex : 0];
    apply(replaceMatch(value, match.start, match.end, replacement));
  }

  function replaceEveryMatch() {
    const result = replaceAll(value, query, replacement);
    onChange(result.value, { start: 0, end: 0 });
  }

  function openSearch(mode) {
    setSearchMode(mode);
  }

  return (
    <div className="expression-toolbar-shell">
      <div className="expression-toolbar" role="toolbar" aria-label="Expression editor actions">
        <ActionButton
          label="Format expression"
          onClick={() => {
            const nextValue = formatExpression(value);
            onChange(nextValue, {
              start: Math.min(selectionStart, nextValue.length),
              end: Math.min(selectionEnd, nextValue.length),
            });
          }}
        />
        <ActionButton
          label="Decrease Indent"
          onClick={() => apply(changeIndent(value, selectionStart, selectionEnd, -1))}
        />
        <ActionButton
          label="Increase Indent"
          onClick={() => apply(changeIndent(value, selectionStart, selectionEnd, 1))}
        />
        <ActionButton
          label="Show/Hide Indent Guide"
          title={indentGuide ? 'Hide Indent Guide' : 'Show Indent Guide'}
          onClick={onToggleIndentGuide}
        />
        <ActionButton
          label="Comment"
          title="Toggle /* */ comments on selected lines"
          onClick={() => apply(toggleComment(value, selectionStart, selectionEnd))}
        />
        <ActionButton label="Find" onClick={() => openSearch('find')} />
        <ActionButton label="Replace" onClick={() => openSearch('replace')} />
        {LIVE_ACTIONS.slice(0, 1).map(([label, callbackName]) => (
          <ActionButton
            key={label}
            label={label}
            disabled={!callbacks[callbackName]}
            title={callbacks[callbackName] ? label : `${label} requires a live Appian environment.`}
            onClick={callbacks[callbackName]}
          />
        ))}
        <ActionButton
          label="View Functions"
          disabled={!onViewFunctions}
          title={onViewFunctions ? 'Browse SAIL functions' : 'Connect a documentation pane to browse functions.'}
          onClick={onViewFunctions}
        />
        {LIVE_ACTIONS.slice(1).map(([label, callbackName]) => (
          <ActionButton
            key={label}
            label={label}
            disabled={!callbacks[callbackName]}
            title={callbacks[callbackName] ? label : `${label} requires a live Appian environment.`}
            onClick={callbacks[callbackName]}
          />
        ))}
      </div>
      {searchMode && (
        <div className="expression-search" role="search" aria-label="Find and replace">
          <label>
            <span>Find</span>
            <input
              aria-label="Find text"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          {searchMode === 'replace' && (
            <label>
              <span>Replace</span>
              <input
                aria-label="Replacement text"
                value={replacement}
                onChange={(event) => setReplacement(event.target.value)}
              />
            </label>
          )}
          <output aria-label="Match count">
            {`${matches.length} matches${activeIndex >= 0 ? `, ${activeIndex + 1} selected` : ''}`}
          </output>
          <button type="button" disabled={!matches.length} onClick={() => moveMatch(-1)}>Previous</button>
          <button type="button" disabled={!matches.length} onClick={() => moveMatch(1)}>Next</button>
          {searchMode === 'replace' && (
            <>
              <button type="button" disabled={!matches.length} onClick={replaceCurrent}>Replace</button>
              <button type="button" disabled={!matches.length} onClick={replaceEveryMatch}>Replace all</button>
            </>
          )}
          <button type="button" aria-label="Close find and replace" onClick={() => setSearchMode('')}>Close</button>
        </div>
      )}
    </div>
  );
}
