'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { objectMeta } from '../lib/appian-objects';
import '../app/build-grid.css';

// Appian Designer's Build view grid. The column set is fixed by the product:
// selection checkbox, type icon, Name, Description, Last Modified. There is no
// Type, Security, or Warnings column. See docs/APPIAN-DESIGNER-REFERENCE.md.
const ROW_LIMIT = 500;

function hierarchyRows(rows, parentByUuid, expanded) {
  const byUuid = new Map(rows.map((row) => [row.uuid, row]));
  const children = new Map();
  const roots = [];

  for (const row of rows) {
    const parentUuid = parentByUuid?.[row.uuid];
    if (parentUuid && parentUuid !== row.uuid && byUuid.has(parentUuid)) {
      const siblings = children.get(parentUuid) || [];
      siblings.push(row);
      children.set(parentUuid, siblings);
    } else {
      roots.push(row);
    }
  }

  const result = [];
  const visited = new Set();
  const append = (row, depth) => {
    if (visited.has(row.uuid)) return;
    visited.add(row.uuid);
    const descendants = children.get(row.uuid) || [];
    result.push({ ...row, depth, hasChildren: descendants.length > 0 });
    if (expanded[row.uuid] !== false) {
      descendants.forEach((child) => append(child, depth + 1));
    }
  };

  roots.forEach((row) => append(row, 0));
  rows.forEach((row) => {
    const parentUuid = parentByUuid?.[row.uuid];
    if (!visited.has(row.uuid) && (!parentUuid || !visited.has(parentUuid))) {
      append(row, 0);
    }
  });
  return result;
}

function actionReason(label, selectedCount, handler) {
  if (selectedCount === 0) return `Select at least one object to use ${label}.`;
  if (!handler) return `${label} is unavailable in this context.`;
  return '';
}

export function BuildGridHarness({ codebase, parentByUuid, reverseDependencies }) {
  const [mounted, setMounted] = useState(false);
  const [event, setEvent] = useState('No action yet');
  const [hasDependencyData, setHasDependencyData] = useState(true);
  const record = (label) => (uuids) => setEvent(`${label}: ${uuids.join(', ')}`);

  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  return (
    <main className="build-grid-harness">
      <div className="build-grid-harness-status">
        <p role="status">{event}</p>
        <button type="button" onClick={() => setHasDependencyData((value) => !value)}>
          {hasDependencyData ? 'Remove dependency data' : 'Restore dependency data'}
        </button>
      </div>
      <BuildGrid
        codebase={codebase}
        parentByUuid={parentByUuid}
        reverseDependencies={hasDependencyData ? reverseDependencies : undefined}
        onOpenObject={({ uuid }) => setEvent(`OPEN: ${uuid}`)}
        onShowDependents={record('DEPENDENTS')}
        onShowPrecedents={record('PRECEDENTS')}
        onAddToPackage={record('ADD TO PACKAGE')}
      />
    </main>
  );
}

export default function BuildGrid({
  codebase,
  onOpenObject,
  reverseDependencies,
  parentByUuid,
  onShowDependents,
  onShowPrecedents,
  onAddToPackage,
}) {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [activeTab, setActiveTab] = useState('all');
  const [view, setView] = useState('flat');
  const [selected, setSelected] = useState(() => new Set());
  const [expanded, setExpanded] = useState({});
  const selectAllRef = useRef(null);

  const types = useMemo(
    () => Object.keys(codebase?.by_type || {}).sort(),
    [codebase],
  );

  const allRows = useMemo(() => {
    const byType = codebase?.by_type || {};
    const names = codebase?.uuid_to_name || {};
    const descriptions = codebase?.descriptions || {};
    const found = [];
    for (const [type, uuids] of Object.entries(byType)) {
      for (const uuid of uuids) {
        found.push({
          uuid,
          type,
          name: names[uuid] || uuid,
          description: descriptions[uuid] || '',
        });
      }
    }
    return found.sort((a, b) => a.name.localeCompare(b.name));
  }, [codebase]);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return allRows.filter((row) => {
      if (typeFilter && row.type !== typeFilter) return false;
      if (activeTab === 'unreferenced' && (reverseDependencies?.[row.uuid]?.length || 0) > 0) {
        return false;
      }
      return !needle || [row.name, row.description, row.uuid].some(
        (field) => String(field).toLowerCase().includes(needle),
      );
    });
  }, [activeTab, allRows, query, reverseDependencies, typeFilter]);

  const visibleRows = useMemo(
    () => view === 'hierarchical'
      ? hierarchyRows(rows, parentByUuid, expanded)
      : rows.map((row) => ({ ...row, depth: 0, hasChildren: false })),
    [expanded, parentByUuid, rows, view],
  );
  const renderedRows = visibleRows.slice(0, ROW_LIMIT);
  const visibleUuids = useMemo(
    () => renderedRows.map((row) => row.uuid),
    [renderedRows],
  );
  const selectedVisibleCount = visibleUuids.filter((uuid) => selected.has(uuid)).length;
  const allVisibleSelected = visibleUuids.length > 0
    && selectedVisibleCount === visibleUuids.length;
  const selectedUuids = useMemo(
    () => allRows.filter((row) => selected.has(row.uuid)).map((row) => row.uuid),
    [allRows, selected],
  );

  useEffect(() => {
    setSelected((current) => {
      const valid = new Set(allRows.map((row) => row.uuid));
      const next = new Set([...current].filter((uuid) => valid.has(uuid)));
      return next.size === current.size ? current : next;
    });
  }, [allRows]);

  useEffect(() => {
    if (reverseDependencies === undefined) setActiveTab('all');
  }, [reverseDependencies]);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectedVisibleCount > 0 && !allVisibleSelected;
    }
  }, [allVisibleSelected, selectedVisibleCount]);

  const setRowSelected = (uuid, checked) => {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(uuid);
      else next.delete(uuid);
      return next;
    });
  };

  const setVisibleSelected = (checked) => {
    setSelected((current) => {
      const next = new Set(current);
      visibleUuids.forEach((uuid) => {
        if (checked) next.add(uuid);
        else next.delete(uuid);
      });
      return next;
    });
  };

  const actions = [
    { label: 'DEPENDENTS', handler: onShowDependents },
    { label: 'PRECEDENTS', handler: onShowPrecedents },
    { label: 'ADD TO PACKAGE', handler: onAddToPackage },
  ];
  const unreferencedUnavailable = reverseDependencies === undefined;

  return (
    <div className="build-grid" aria-label="Build view">
      <div className="build-tabs" role="tablist" aria-label="Build object lists">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'all'}
          onClick={() => setActiveTab('all')}
        >
          ALL OBJECTS
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'unreferenced'}
          aria-disabled={unreferencedUnavailable}
          title={unreferencedUnavailable
            ? 'Dependency data is unavailable for this codebase.'
            : undefined}
          onClick={() => {
            if (!unreferencedUnavailable) setActiveTab('unreferenced');
          }}
        >
          UNREFERENCED OBJECTS
        </button>
      </div>
      <div className="build-toolbar">
        <label className="search-field">
          <span className="sr-only">Search objects</span>
          <span aria-hidden="true">/</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search name, description, or UUID"
          />
        </label>
        <label className="build-filter">
          <span className="sr-only">Filter by object type</span>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="">All object types</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {objectMeta(type).label}
              </option>
            ))}
          </select>
        </label>
        <div className="build-view-toggle" role="group" aria-label="Object view">
          <button
            type="button"
            aria-pressed={view === 'flat'}
            onClick={() => setView('flat')}
          >
            Flat view
          </button>
          <button
            type="button"
            aria-pressed={view === 'hierarchical'}
            onClick={() => setView('hierarchical')}
          >
            Hierarchical view
          </button>
        </div>
        <span className="build-count">
          {rows.length} objects, {selectedUuids.length} selected
        </span>
      </div>
      <div className="build-selection-toolbar" aria-label="Selection actions">
        {actions.map(({ label, handler }) => {
          const reason = actionReason(label, selectedUuids.length, handler);
          const reasonId = `build-action-${label.toLowerCase().replaceAll(' ', '-')}`;
          return (
            <span className="build-action-wrap" key={label} title={reason || undefined}>
              <button
                type="button"
                disabled={Boolean(reason)}
                aria-describedby={reason ? reasonId : undefined}
                onClick={() => handler(selectedUuids)}
              >
                {label}
              </button>
              {reason && <span className="sr-only" id={reasonId}>{reason}</span>}
            </span>
          );
        })}
      </div>
      {rows.length === 0 ? (
        <div className="center-state">No objects match this search.</div>
      ) : (
        <table className="build-table">
          <thead>
            <tr>
              <th scope="col" className="build-checkbox-column">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  aria-label="Select all visible objects"
                  checked={allVisibleSelected}
                  disabled={visibleUuids.length === 0}
                  onChange={(event) => setVisibleSelected(event.target.checked)}
                />
              </th>
              <th scope="col" className="build-icon-column">
                <span className="sr-only">Type</span>
              </th>
              <th scope="col">Name</th>
              <th scope="col">Description</th>
              {/* Appian's grid also has Last Modified. An export carries no
                  modification timestamp, so the column is omitted rather than
                  filled with placeholder dates. */}
            </tr>
          </thead>
          <tbody>
            {renderedRows.map((row) => {
              const meta = objectMeta(row.type);
              return (
                <tr key={row.uuid}>
                  <td className="build-checkbox-column">
                    <input
                      type="checkbox"
                      aria-label={`Select ${row.name}`}
                      checked={selected.has(row.uuid)}
                      onChange={(event) => setRowSelected(row.uuid, event.target.checked)}
                    />
                  </td>
                  <td className="build-icon-column">
                    <span
                      className="object-icon"
                      style={{ background: meta.color }}
                      title={meta.label}
                    >
                      {meta.abbreviation}
                    </span>
                  </td>
                  <td className="build-name-column" style={{ '--build-depth': row.depth }}>
                    {view === 'hierarchical' && row.hasChildren && (
                      <button
                        type="button"
                        className="build-expand"
                        aria-label={`${expanded[row.uuid] === false ? 'Expand' : 'Collapse'} ${row.name}`}
                        aria-expanded={expanded[row.uuid] !== false}
                        onClick={() => setExpanded((current) => ({
                          ...current,
                          [row.uuid]: current[row.uuid] === false,
                        }))}
                      >
                        {expanded[row.uuid] === false ? '+' : '-'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpenObject({ uuid: row.uuid, name: row.name })}
                    >
                      {row.name}
                    </button>
                  </td>
                  <td className="build-muted">{row.description}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {visibleRows.length > ROW_LIMIT && (
        <p className="build-truncated">
          Showing the first {ROW_LIMIT} of {visibleRows.length}. Narrow the search to see more.
        </p>
      )}
    </div>
  );
}
