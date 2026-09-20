'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { objectMeta } from '../lib/appian-objects';

export default function ObjectExplorer({
  codebase,
  loading,
  error,
  selectedId,
  chatSelectedIds,
  onSelect,
  onToggleChat,
}) {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [expanded, setExpanded] = useState({});
  const treeRef = useRef(null);

  const typeOptions = useMemo(
    () => Object.keys(codebase?.by_type || {}).sort((a, b) => a.localeCompare(b)),
    [codebase],
  );

  const groups = useMemo(() => Object.entries(codebase?.by_type || {})
    .filter(([type]) => !typeFilter || type === typeFilter)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([type, ids]) => ({
      type,
      items: ids.map((uuid) => ({
        uuid,
        type,
        name: codebase.uuid_to_name?.[uuid] || uuid,
      })).filter((item) => item.name.toLowerCase().includes(query.toLowerCase())
        || item.uuid.toLowerCase().includes(query.toLowerCase())),
    })).filter((group) => !query || group.items.length), [codebase, query, typeFilter]);

  useEffect(() => {
    if (!codebase) return;
    setExpanded(Object.fromEntries(Object.keys(codebase.by_type || {}).map((type) => [type, true])));
  }, [codebase]);

  function moveFocus(event) {
    const rows = [...treeRef.current.querySelectorAll('[role="treeitem"]')];
    const current = rows.indexOf(document.activeElement);

    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      const active = rows[current];
      if (!active) return;
      const groupType = active.dataset.groupType;
      if (!groupType) {
        event.preventDefault();
        active.closest('.tree-group')?.querySelector('.tree-group-button')?.focus();
        return;
      }
      // A search result set is force-expanded, so collapsing it would hide
      // matches the operator is looking at.
      const isOpen = query ? true : expanded[groupType];
      event.preventDefault();
      if (event.key === 'ArrowRight') {
        if (isOpen) rows[current + 1]?.focus();
        else setExpanded((value) => ({ ...value, [groupType]: true }));
      } else if (isOpen && !query) {
        setExpanded((value) => ({ ...value, [groupType]: false }));
      }
      return;
    }

    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
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
      <label className="type-filter-field">
        <span className="sr-only">Filter object type</span>
        <select
          aria-label="Filter object type"
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)}
        >
          <option value="">All types</option>
          {typeOptions.map((type) => (
            <option key={type} value={type}>{objectMeta(type).label}</option>
          ))}
        </select>
      </label>
      {loading && (
        <div className="tree-state is-loading" role="status">
          <span className="state-spinner" aria-hidden="true" />
          <span>Loading application objects...</span>
        </div>
      )}
      {!loading && error && (
        <div className="tree-state is-error" role="alert">
          <strong>Could not load application objects.</strong>
          <span>Check the connection or import again.</span>
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
            <div className="tree-group" role="none" key={group.type}>
              <button
                type="button"
                className="tree-group-button"
                role="treeitem"
                data-group-type={group.type}
                aria-expanded={isOpen}
                onClick={() => setExpanded((value) => ({ ...value, [group.type]: !isOpen }))}
              >
                <span className="chevron" aria-hidden="true">{isOpen ? 'v' : '>'}</span>
                <span>{objectMeta(group.type).label}</span>
                <span className="group-count">{group.items.length}</span>
              </button>
              {isOpen && (
                <div role="group">
                  {group.items.map((item) => (
                    <div
                      className={`object-row ${selectedId === item.uuid ? 'is-selected' : ''}`}
                      key={item.uuid}
                    >
                      <input
                        type="checkbox"
                        checked={chatSelectedIds.includes(item.uuid)}
                        aria-label={chatSelectedIds.includes(item.uuid)
                          ? `Remove ${item.name} from chat`
                          : `Add ${item.name} to chat`}
                        onChange={() => onToggleChat(item)}
                      />
                      <button
                        type="button"
                        role="treeitem"
                        aria-selected={selectedId === item.uuid}
                        className="object-row-button"
                        title={`${item.name}\n${item.uuid}`}
                        onClick={() => onSelect(item)}
                      >
                        <span
                          className="object-icon"
                          aria-hidden="true"
                          style={{ background: objectMeta(group.type).color }}
                        >
                          {objectMeta(group.type).abbreviation}
                        </span>
                        <span className="object-label">{item.name}</span>
                      </button>
                    </div>
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
