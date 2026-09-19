'use client';

import { useMemo, useState } from 'react';
import { SAIL_CALLABLES } from '../lib/sail-tokens';

const FUNCTION_DETAILS = {
  'a!textfield': {
    description: 'Displays a single-line text input.',
    parameters: [
      ['label', 'Text'],
      ['instructions', 'Text'],
      ['required', 'Boolean'],
      ['readOnly', 'Boolean'],
      ['disabled', 'Boolean'],
      ['value', 'Text'],
      ['validations', 'List of Text String'],
      ['saveInto', 'Save'],
      ['placeholder', 'Text'],
      ['showWhen', 'Boolean'],
    ],
  },
  'a!localvariables': {
    description: 'Defines local variables and returns the final expression.',
    parameters: [
      ['local variables', 'Any Type'],
      ['expression', 'Any Type'],
    ],
  },
  if: {
    description: 'Returns one result when a condition is true and another when it is false.',
    parameters: [
      ['condition', 'Boolean'],
      ['valueIfTrue', 'Any Type'],
      ['valueIfFalse', 'Any Type'],
    ],
  },
};

const FUNCTIONS = [...SAIL_CALLABLES]
  .filter((name) => !/_\d/.test(name))
  .sort((left, right) => left.localeCompare(right));

function canonicalName(name) {
  return FUNCTIONS.find((item) => item.toLowerCase() === name?.toLowerCase()) || name || '';
}

export default function ExpressionDocs({
  functionName = '',
  showFunctions = false,
  onSelectFunction,
}) {
  const [filter, setFilter] = useState('');
  const name = canonicalName(functionName);
  const details = FUNCTION_DETAILS[name.toLowerCase()];
  const filteredFunctions = useMemo(
    () => FUNCTIONS.filter((item) => item.includes(filter.trim().toLowerCase())).slice(0, 200),
    [filter],
  );

  return (
    <aside className="expression-docs" aria-label="Expression documentation">
      {showFunctions && (
        <section className="function-browser">
          <h2>Functions</h2>
          <label>
            <span>Filter functions</span>
            <input
              aria-label="Filter functions"
              value={filter}
              onChange={(event) => setFilter(event.target.value.toLowerCase())}
            />
          </label>
          <p className="function-count">{filteredFunctions.length} shown</p>
          <ul className="function-list">
            {filteredFunctions.map((item) => (
              <li key={item}>
                <button
                  type="button"
                  aria-current={item === name ? 'true' : undefined}
                  onClick={() => onSelectFunction?.(item)}
                >
                  {item}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="function-detail" aria-live="polite">
        <h2>{name || 'Documentation'}</h2>
        {!name && <p>Highlight a function to view its documentation.</p>}
        {name && !details && (
          <p>No parameter metadata is available for {name} in the bundled catalog.</p>
        )}
        {details && (
          <>
            <p>{details.description}</p>
            <h3>Parameters</h3>
            <dl>
              {details.parameters.map(([parameter, type]) => (
                <div key={parameter}>
                  <dt>{parameter}</dt>
                  <dd>{type}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </section>
    </aside>
  );
}
