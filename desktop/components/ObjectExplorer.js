'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

function displayType(value) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function ObjectExplorer({ codebase, loading, error, selectedId, onSelect }) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState({});
  const treeRef = useRef(null);

  const groups = useMemo(() => Object.entries(codebase?.by_type || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([type, ids]) => ({
      type,
      items: ids.map((uuid) => ({
        uuid,
        name: codebase.uuid_to_name?.[uuid] || uuid,
      })).filter((item) => item.name.toLowerCase().includes(query.toLowerCase())
        || item.uuid.toLowerCase().includes(query.toLowerCase())),
    })).filter((group) => !query || group.items.length), [codebase, query]);

  useEffect(() => {
    if (!codebase) return;
    setExpanded(Object.fromEntries(Object.keys(codebase.by_type || {}).map((type) => [type, true])));
  }, [codebase]);

  function moveFocus(event) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const rows = [...treeRef.current.querySelectorAll('[role="treeitem"]')];
    const current = rows.indexOf(document.activeElement);
    const target = event.key === 'Home' ? 0
      : event.key === 'End' ? rows.length - 1
        : event.key === 'ArrowDown' ? Math.min(rows.length - 1, current + 1)
          : Math.max(0, current - 1);
    if (rows[target]) {
      event.preventDefault();
      rows[target].focus();
    }
  }

  return (
    <aside className="explorer pane" aria-label="Object explorer">
      <div className="pane-heading">
        <div>
          <p className="eyebrow">DESIGN OBJECTS</p>
          <h2>Object Explorer</h2>
        </div>
        <span className="count-badge">{Object.values(codebase?.by_type || {}).reduce((sum, ids) => sum + ids.length, 0)}</span>
      </div>
      <label className="search-field">
        <span className="sr-only">Search objects</span>
        <span aria-hidden="true">/</span>
        <input id="object-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name or UUID" />
      </label>
      {loading && (
        <div className="tree-state is-loading" role="status">
          <span className="state-spinner" aria-hidden="true" />
          <span>Loading application objects...</span>
        </div>
      )}
      {!loading && error && (
        <div className="tree-state is-error" role="alert">
          <strong>Could not load objects: {error}</strong>
          <span>Check the sidecar connection or import again.</span>
        </div>
      )}
      {!loading && !error && !codebase && (
        <div className="tree-state is-empty">
          <strong>Import an Appian export to begin.</strong>
          <span>Use Import application in the top bar.</span>
        </div>
      )}
      {!loading && !error && codebase && groups.length === 0 && (
        <div className="tree-state">No objects match this search.</div>
      )}
      <div className="object-tree" role="tree" ref={treeRef} onKeyDown={moveFocus}>
        {groups.map((group) => {
          const isOpen = query ? true : expanded[group.type];
          return (
            <div className="tree-group" key={group.type}>
              <button
                type="button"
                className="tree-group-button"
                role="treeitem"
                aria-expanded={isOpen}
                onClick={() => setExpanded((value) => ({ ...value, [group.type]: !isOpen }))}
              >
                <span className="chevron" aria-hidden="true">{isOpen ? 'v' : '>'}</span>
                <span>{displayType(group.type)}</span>
                <span className="group-count">{group.items.length}</span>
              </button>
              {isOpen && (
                <div role="group">
                  {group.items.map((item) => (
                    <button
                      type="button"
                      role="treeitem"
                      aria-selected={selectedId === item.uuid}
                      className={`object-row ${selectedId === item.uuid ? 'is-selected' : ''}`}
                      key={item.uuid}
                      title={`${item.name}\n${item.uuid}`}
                      onClick={() => onSelect(item)}
                    >
                      <span className="object-icon" aria-hidden="true">{group.type.slice(0, 2).toUpperCase()}</span>
                      <span className="object-label">{item.name}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
