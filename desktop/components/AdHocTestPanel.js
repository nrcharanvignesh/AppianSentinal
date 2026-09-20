'use client';

import { useEffect, useMemo, useState } from 'react';
import '../app/adhoc-test.css';
import {
  formatOutputView,
  normalizeRuleInputs,
  OUTPUT_VIEWS,
  serializeInputValues,
} from '../lib/adhoc-test';

function errorReason(value) {
  if (typeof value === 'string' && value.trim()) return value;
  if (value?.reason) return String(value.reason);
  if (value?.message) return String(value.message);
  if (value?.error) return errorReason(value.error);
  return 'The static analysis failed without a reason.';
}

export default function AdHocTestPanel({
  ruleInputs = [],
  savedTestCases = [],
  onRunTest,
  showSavedTests = true,
}) {
  const normalized = useMemo(() => normalizeRuleInputs(ruleInputs), [ruleInputs]);
  const [inputs, setInputs] = useState(normalized);
  const [runState, setRunState] = useState('idle');
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState('');
  const [outputView, setOutputView] = useState('formatted-map');

  useEffect(() => {
    setInputs(normalized);
    setRunState('idle');
    setResult(null);
    setFailure('');
  }, [normalized]);

  function updateInput(index, patch) {
    setInputs((current) => current.map((input, inputIndex) => (
      inputIndex === index ? { ...input, ...patch } : input
    )));
  }

  async function runTest() {
    setRunState('pending');
    setResult(null);
    setFailure('');
    try {
      const nextResult = await onRunTest(serializeInputValues(inputs));
      if (nextResult?.error) {
        setFailure(errorReason(nextResult.error));
        setRunState('error');
        return;
      }
      setResult(nextResult ?? {});
      setRunState('complete');
    } catch (error) {
      setFailure(errorReason(error));
      setRunState('error');
    }
  }

  const localVariables = Array.isArray(result?.localVariables)
    ? result.localVariables
    : [];
  const resultSummary = result?.summary || result?.message;

  return (
    <section className="adhoc-panel" aria-labelledby="adhoc-test-title">
      <header className="adhoc-header">
        <div>
          <h1 id="adhoc-test-title">Ad Hoc Test</h1>
          <p>
            Static analysis only. Appian Sentinel does not execute SAIL or calculate
            runtime values.
          </p>
        </div>
        <button
          type="button"
          className="adhoc-run"
          disabled={runState === 'pending' || typeof onRunTest !== 'function'}
          onClick={runTest}
        >
          {runState === 'pending' ? 'TESTING...' : 'TEST RULE'}
        </button>
      </header>

      <section className="adhoc-section" aria-labelledby="test-inputs-title">
        <h2 id="test-inputs-title">Test Inputs</h2>
        {inputs.length ? (
          <div className="adhoc-input-list">
            {inputs.map((input, index) => {
              const id = `adhoc-input-${index}`;
              return (
                <fieldset className="adhoc-input" key={input.name}>
                  <legend>
                    <span>{input.name}</span>
                    <small>{input.type}</small>
                  </legend>
                  <div className="adhoc-mode" role="radiogroup" aria-label={`${input.name} input mode`}>
                    <label>
                      <input
                        type="radio"
                        name={`${id}-mode`}
                        value="static"
                        checked={input.mode === 'static'}
                        onChange={() => updateInput(index, { mode: 'static' })}
                      />
                      Static value
                    </label>
                    <label>
                      <input
                        type="radio"
                        name={`${id}-mode`}
                        value="expression"
                        checked={input.mode === 'expression'}
                        onChange={() => updateInput(index, { mode: 'expression' })}
                      />
                      Expression
                    </label>
                  </div>
                  <label className="adhoc-value" htmlFor={id}>
                    {input.mode === 'expression' ? 'Expression' : 'Value'}
                    <textarea
                      id={id}
                      rows="2"
                      value={input.value}
                      onChange={(event) => updateInput(index, { value: event.target.value })}
                      spellCheck="false"
                    />
                  </label>
                </fieldset>
              );
            })}
          </div>
        ) : <p className="adhoc-empty">This rule has no inputs.</p>}
      </section>

      <section className="adhoc-section" aria-labelledby="local-variables-title">
        <h2 id="local-variables-title">Local Variable Values</h2>
        {runState === 'complete' && localVariables.length ? (
          <dl className="adhoc-variables">
            {localVariables.map((variable, index) => (
              <div key={`${variable.name || 'local'}-${index}`}>
                <dt>{variable.name || `local variable ${index + 1}`}</dt>
                <dd>{String(variable.value ?? 'Value unavailable')}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="adhoc-empty">
            {runState === 'complete'
              ? 'Static analysis did not provide local variable values.'
              : 'Run static analysis to inspect any reported local variables.'}
          </p>
        )}
      </section>

      <section className="adhoc-section" aria-labelledby="test-output-title">
        <div className="adhoc-output-heading">
          <h2 id="test-output-title">Test Output</h2>
          <div className="adhoc-output-modes" role="tablist" aria-label="Test output view">
            {OUTPUT_VIEWS.map((view) => (
              <button
                type="button"
                role="tab"
                aria-selected={outputView === view.id}
                key={view.id}
                onClick={() => setOutputView(view.id)}
              >
                {view.label}
              </button>
            ))}
          </div>
        </div>

        <div className="adhoc-run-status" role="status" aria-live="polite">
          {runState === 'idle' && 'Not run.'}
          {runState === 'pending' && 'Static analysis is running.'}
          {runState === 'complete' && (
            resultSummary
              ? `Static analysis completed: ${resultSummary}`
              : 'Static analysis completed. No execution status was provided.'
          )}
          {runState === 'error' && `Static analysis error: ${failure}`}
        </div>

        {runState === 'complete' && (
          <pre className="adhoc-output" aria-label={`${OUTPUT_VIEWS.find((view) => view.id === outputView)?.label} output`}>
            {formatOutputView(result, outputView)}
          </pre>
        )}
      </section>

      {showSavedTests && (
        <section className="adhoc-section adhoc-saved" aria-labelledby="saved-tests-title">
          <h2 id="saved-tests-title">Saved Test Cases</h2>
          {savedTestCases.length ? (
            <ul>
              {savedTestCases.map((testCase, index) => (
                <li key={`${testCase.name || 'test'}-${index}`}>
                  <span>{testCase.name || `Test case ${index + 1}`}</span>
                  <strong>{testCase.status || 'Status unavailable'}</strong>
                </li>
              ))}
            </ul>
          ) : <p className="adhoc-empty">No saved test cases were supplied.</p>}
        </section>
      )}
    </section>
  );
}
