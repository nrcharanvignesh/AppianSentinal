'use client';

import { useEffect, useState } from 'react';
import AdHocTestPanel from './AdHocTestPanel';

function assertionSummary(testCase) {
  if (testCase.assertion_type === 'expression') {
    return testCase.assertion_expression || 'Invalid expression assertion';
  }
  if (testCase.assertion_type === 'completes_without_error') {
    return 'Completes without errors';
  }
  return `Output equals ${testCase.expected === '' ? '""' : String(testCase.expected ?? 'null')}`;
}

export function RuleTestPanel({ ruleInputs, savedTestCases, onRunTest }) {
  const [view, setView] = useState(savedTestCases.length ? 'cases' : 'adhoc');

  useEffect(() => {
    setView(savedTestCases.length ? 'cases' : 'adhoc');
  }, [savedTestCases]);

  return (
    <section className="rule-test-pane" aria-label="Rule tests">
      <div className="rule-pane-tabs" role="tablist" aria-label="Rule test view">
        <button
          type="button"
          role="tab"
          aria-selected={view === 'adhoc'}
          onClick={() => setView('adhoc')}
        >
          Ad Hoc Test
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === 'cases'}
          onClick={() => setView('cases')}
        >
          Test Cases ({savedTestCases.length})
        </button>
      </div>
      {view === 'adhoc' ? (
        <AdHocTestPanel
          ruleInputs={ruleInputs}
          onRunTest={onRunTest}
          showSavedTests={false}
        />
      ) : (
        <div className="rule-test-cases">
          {savedTestCases.length ? (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Assertion</th>
                  <th>Inputs</th>
                </tr>
              </thead>
              <tbody>
                {savedTestCases.map((testCase, index) => (
                  <tr key={`${testCase.name || 'test'}-${index}`}>
                    <td>
                      <strong>{testCase.name || `Test case ${index + 1}`}</strong>
                      {testCase.description && <small>{testCase.description}</small>}
                    </td>
                    <td><code>{assertionSummary(testCase)}</code></td>
                    <td>{Object.keys(testCase.inputs || {}).length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="rule-pane-empty">
              No embedded test cases were found in this rule.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export function RuleInputsPanel({ ruleInputs, symbols, onJumpTo }) {
  return (
    <aside className="rule-inputs-pane" aria-label="Rule inputs">
      <header>
        <strong>Rule Inputs</strong>
        <span>{ruleInputs.length}</span>
      </header>
      {ruleInputs.length ? (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Array</th>
            </tr>
          </thead>
          <tbody>
            {ruleInputs.map((input) => (
              <tr key={input.name}>
                <td>{input.name}</td>
                <td>{input.type_name || input.type || 'Any Type'}</td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`${input.name} is array`}
                    checked={Boolean(input.is_list)}
                    readOnly
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="rule-pane-empty">This rule has no inputs.</p>}
      <section className="rule-outline" aria-labelledby="rule-outline-title">
        <h3 id="rule-outline-title">Outline</h3>
        {symbols.length ? symbols.map((symbol) => (
          <button
            type="button"
            key={`${symbol.kind}-${symbol.offset}`}
            onClick={() => onJumpTo(symbol.offset)}
          >
            <b>{symbol.kind}</b>
            <span>{symbol.name}</span>
            <small>{symbol.line}</small>
          </button>
        )) : <p>No symbols found.</p>}
      </section>
    </aside>
  );
}
