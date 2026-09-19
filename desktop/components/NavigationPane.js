'use client';

import { useMemo, useRef } from 'react';
import '../app/designer-shell.css';

const ENTRIES = [
  { id: 'plan', label: 'Plan' },
  { id: 'explore', label: 'Explore' },
  { id: 'build', label: 'Build' },
  { id: 'packages', label: 'Packages' },
  { id: 'deploy', label: 'Deploy' },
  { id: 'monitor', label: 'Monitor' },
];

const UNAVAILABLE_REASON = 'This view is not available in Appian Sentinel yet.';

export default function NavigationPane({ active, onNavigate, available = [] }) {
  const buttonsRef = useRef([]);
  const enabled = useMemo(
    () => new Set(Array.from(available, (id) => String(id).toLowerCase())),
    [available],
  );

  function moveFocus(event, index) {
    const enabledIndexes = ENTRIES
      .map((entry, entryIndex) => (enabled.has(entry.id) ? entryIndex : -1))
      .filter((entryIndex) => entryIndex >= 0);
    if (!enabledIndexes.length) return;

    let targetIndex;
    if (event.key === 'Home') targetIndex = enabledIndexes[0];
    if (event.key === 'End') targetIndex = enabledIndexes.at(-1);
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
      const position = enabledIndexes.indexOf(index);
      targetIndex = enabledIndexes[(position + 1) % enabledIndexes.length];
    }
    if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
      const position = enabledIndexes.indexOf(index);
      targetIndex = enabledIndexes[
        (position - 1 + enabledIndexes.length) % enabledIndexes.length
      ];
    }
    if (targetIndex === undefined) return;
    event.preventDefault();
    buttonsRef.current[targetIndex]?.focus();
  }

  return (
    <nav className="designer-navigation" aria-label="Application">
      <ul className="designer-navigation-list">
        {ENTRIES.map((entry, index) => {
          const isAvailable = enabled.has(entry.id);
          const reasonId = `navigation-${entry.id}-reason`;
          return (
            <li
              key={entry.id}
              className={isAvailable ? '' : 'is-disabled'}
              title={isAvailable ? undefined : UNAVAILABLE_REASON}
            >
              <button
                ref={(element) => { buttonsRef.current[index] = element; }}
                type="button"
                disabled={!isAvailable}
                aria-current={active === entry.id ? 'page' : undefined}
                aria-describedby={isAvailable ? undefined : reasonId}
                onClick={() => onNavigate(entry.id)}
                onKeyDown={(event) => moveFocus(event, index)}
              >
                <span className="designer-navigation-icon" aria-hidden="true" />
                <span>{entry.label}</span>
              </button>
              {!isAvailable && (
                <span id={reasonId} className="designer-sr-only">
                  {UNAVAILABLE_REASON}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
