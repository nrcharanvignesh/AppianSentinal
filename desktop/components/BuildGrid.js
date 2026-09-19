'use client';

import { useMemo, useState } from 'react';

import { objectMeta } from '../lib/appian-objects';

// Appian Designer's Build view grid. The column set is fixed by the product:
// selection checkbox, type icon, Name, Description, Last Modified. There is no
// Type, Security, or Warnings column. See docs/APPIAN-DESIGNER-REFERENCE.md.
export default function BuildGrid({ codebase, onOpenObject }) {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const types = useMemo(
    () => Object.keys(codebase?.by_type || {}).sort(),
    [codebase],
  );

  const rows = useMemo(() => {
    const byType = codebase?.by_type || {};
    const names = codebase?.uuid_to_name || {};
    const descriptions = codebase?.descriptions || {};
    const needle = query.trim().toLowerCase();
    const found = [];
    for (const [type, uuids] of Object.entries(byType)) {
      if (typeFilter && type !== typeFilter) continue;
      for (const uuid of uuids) {
        const name = names[uuid] || uuid;
        const description = descriptions[uuid] || '';
        // Designer's search matches name, description, UUID, and ID.
        if (needle && ![name, description, uuid].some(
          (field) => String(field).toLowerCase().includes(needle),
        )) continue;
        found.push({ uuid, type, name, description });
      }
    }
    return found.sort((a, b) => a.name.localeCompare(b.name));
  }, [codebase, query, typeFilter]);

  return (
    <div className="build-grid" aria-label="Build view">
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
        <span className="build-count">{rows.length} objects</span>
      </div>
      {rows.length === 0 ? (
        <div className="center-state">No objects match this search.</div>
      ) : (
        <table className="build-table">
          <thead>
            <tr>
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
            {rows.slice(0, 500).map((row) => {
              const meta = objectMeta(row.type);
              return (
                <tr key={row.uuid}>
                  <td className="build-icon-column">
                    <span
                      className="object-icon"
                      style={{ background: meta.color }}
                      title={meta.label}
                    >
                      {meta.abbreviation}
                    </span>
                  </td>
                  <td>
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
      {rows.length > 500 && (
        <p className="build-truncated">
          Showing the first 500 of {rows.length}. Narrow the search to see more.
        </p>
      )}
    </div>
  );
}
