'use client';

import { useMemo, useState } from 'react';

const PANELS = ['Problems', 'Dependencies', 'Tests', 'Changes', 'History', 'Output'];

export default function BottomPanel({
  diagnostics,
  tests,
  changes,
  history,
  output,
  activeId,
  navigation,
  testableObjects,
  codebaseLoaded,
  onBulkPreview,
  onBulkApply,
  onRestore,
  onPackage,
  onDownload,
  onJumpToProblem,
  onOpenObject,
}) {
  const [active, setActive] = useState('Problems');
  const [selected, setSelected] = useState([]);
  const [bulkState, setBulkState] = useState('');
  const [testJson, setTestJson] = useState(`[
  {
    "name": "Generated test",
    "description": "",
    "inputs": {},
    "expected": null
  }
]`);
  const [preview, setPreview] = useState(null);
  const [restoreState, setRestoreState] = useState('');
  const problems = diagnostics?.diagnostics || diagnostics?.items || [];
  const inbound = (navigation?.reverseDependencies?.[activeId] || [])
    .map((uuid) => navigation.entries.find((item) => item.uuid === uuid))
    .filter(Boolean);
  const outbound = (navigation?.dependencies?.[activeId] || [])
    .map((uuid) => navigation.entries.find((item) => item.uuid === uuid))
    .filter(Boolean);
  const failures = tests?.failures || [];
  const changedFiles = useMemo(() => [
    ...(changes?.created || []).map((name) => ({ name, kind: 'Added' })),
    ...(changes?.modified || []).map((name) => ({ name, kind: 'Modified' })),
  ], [changes]);

  function toggle(uuid) {
    setPreview(null);
    setSelected((value) => value.includes(uuid)
      ? value.filter((item) => item !== uuid)
      : [...value, uuid]);
  }

  function parsedTests() {
    const value = JSON.parse(testJson);
    if (!Array.isArray(value) || value.length === 0) {
      throw new Error('tests_must_be_a_non_empty_array');
    }
    return value.map((item) => {
      if (!item || typeof item.name !== 'string' || !item.name.trim()) {
        throw new Error('test_name_required');
      }
      if (!Object.prototype.hasOwnProperty.call(item, 'expected')) {
        throw new Error('test_expected_required');
      }
      return {
        name: item.name,
        description: item.description || '',
        inputs: item.inputs || {},
        expected: item.expected,
      };
    });
  }

  async function previewBulk() {
    setBulkState(`Previewing ${selected.length} objects...`);
    try {
      const result = await onBulkPreview(selected, parsedTests());
      setPreview(result);
      setBulkState('Preview complete. Review the diff before apply.');
    } catch (error) {
      setBulkState(`Bulk test error: ${error.message}`);
    }
  }

  async function applyBulk() {
    if (!preview) return;
    setBulkState(`Applying ${selected.length} objects...`);
    try {
      const result = await onBulkApply(selected, parsedTests());
      setPreview(null);
      setBulkState(`Apply complete. Revision ${result.revision || 'created'}.`);
    } catch (error) {
      setBulkState(`Bulk test error: ${error.message}`);
    }
  }

  async function restore(revision) {
    setRestoreState(`Restoring ${revision}...`);
    try {
      await onRestore(revision);
      setRestoreState(`Restored ${revision}.`);
    } catch (error) {
      setRestoreState(`Restore error: ${error.message}`);
    }
  }

  return (
    <section className="bottom-panel" aria-label="Workbench results">
      <div className="bottom-tabs" role="tablist">
        {PANELS.map((panel) => (
          <button type="button" role="tab" aria-selected={active === panel} onClick={() => setActive(panel)} key={panel}>
            {panel}
            {panel === 'Problems' && problems.length > 0 && <span>{problems.length}</span>}
            {panel === 'Changes' && changedFiles.length > 0 && <span>{changedFiles.length}</span>}
          </button>
        ))}
      </div>
      <div className="bottom-content" role="tabpanel">
        {active === 'Problems' && (!codebaseLoaded
          ? <p className="empty-result">Diagnostics disabled: load an export first.</p>
          : diagnostics?.error
            ? <p className="empty-result">Diagnostics error: {diagnostics.error}</p>
            : diagnostics === null
              ? <p className="empty-result">Open an object to load its diagnostics.</p>
              : problems.length
            ? problems.map((problem, index) => (
              <button
                type="button"
                className="problem-row"
                key={`${problem.code || 'problem'}-${index}`}
                onClick={() => onJumpToProblem(problem)}
              >
                <b>{String(problem.severity || 'error').toUpperCase()}</b>
                {problem.code ? `${problem.code}: ` : ''}{problem.message}
                {problem.line ? ` (line ${problem.line})` : ''}
              </button>
            ))
            : <p className="empty-result">No diagnostics reported.</p>)}
        {active === 'Dependencies' && (!activeId
          ? <p className="empty-result">Open an object to inspect dependencies.</p>
          : (
            <div className="dependency-view">
              <section>
                <h3>Outbound references</h3>
                {outbound.length ? outbound.map((item) => (
                  <button type="button" key={item.uuid} onClick={() => onOpenObject(item)}>
                    {item.name}<small>{item.type.replaceAll('_', ' ')}</small>
                  </button>
                )) : <p className="empty-result">No outbound references.</p>}
              </section>
              <section>
                <h3>Inbound references</h3>
                {inbound.length ? inbound.map((item) => (
                  <button type="button" key={item.uuid} onClick={() => onOpenObject(item)}>
                    {item.name}<small>{item.type.replaceAll('_', ' ')}</small>
                  </button>
                )) : <p className="empty-result">No loaded objects reference this object.</p>}
              </section>
            </div>
          ))}
        {active === 'Tests' && (
          <div className="tests-panel">
            <div className="test-summary">
              {!tests || tests.status === 'no_results' ? 'No test run is available.' : tests.passed ? 'All tests passed.' : `${failures.length} tests failed.`}
            </div>
            <div className="bulk-picker">
              {testableObjects.length ? testableObjects.map((item) => (
                <label key={item.uuid}>
                  <input type="checkbox" checked={selected.includes(item.uuid)} onChange={() => toggle(item.uuid)} />
                  <span>{item.name}</span><small>{item.type}</small>
                </label>
              )) : <p>No interfaces or rules are loaded.</p>}
            </div>
            <label>
              Test cases JSON
              <textarea
                aria-label="Bulk test cases JSON"
                rows="4"
                value={testJson}
                onChange={(event) => {
                  setTestJson(event.target.value);
                  setPreview(null);
                }}
              />
            </label>
            <div className="bulk-actions">
              <button
                type="button"
                disabled={!codebaseLoaded || selected.length === 0}
                title={codebaseLoaded ? '' : 'Load an export to manage tests.'}
                onClick={previewBulk}
              >Preview selected</button>
              <button
                type="button"
                disabled={!codebaseLoaded || !preview}
                title={codebaseLoaded ? 'Apply the reviewed preview' : 'Load an export to manage tests.'}
                onClick={applyBulk}
              >Confirm apply</button>
              {!codebaseLoaded && <span>Bulk tests disabled: load an export first.</span>}
              {bulkState && <span aria-live="polite">{bulkState}</span>}
            </div>
            {preview?.diff && (
              <pre aria-label="Bulk test preview">
                {Object.entries(preview.diff)
                  .map(([uuid, diff]) => `${uuid}\n${diff}`)
                  .join('\n')}
              </pre>
            )}
          </div>
        )}
        {active === 'Changes' && (changedFiles.length
          ? changedFiles.map((file) => <p className="change-row" key={`${file.kind}-${file.name}`}><b>{file.kind}</b>{file.name}</p>)
          : <p className="empty-result">No generated changes.</p>)}
        {active === 'History' && (!codebaseLoaded
          ? <p className="empty-result">History disabled: load an export first.</p>
          : history.length
            ? history.slice(0, 20).map((item, index) => (
              <p className="history-row" key={item.id || item.hash || index}>
                <b>{item.message || item.role || 'revision'}</b>{item.timestamp || item.created_at || item.content || item.hash}
                <button
                  type="button"
                  disabled={!codebaseLoaded}
                  title="Restore this revision"
                  onClick={() => restore(item.id || item.hash)}
                >Restore</button>
              </p>
            ))
            : <p className="empty-result">No workspace revisions.</p>)}
        {active === 'History' && restoreState && <p className="form-state" aria-live="polite">{restoreState}</p>}
        {active === 'Output' && (
          <div className="output-actions">
            <p>{output?.has_output_zip || output?.has_patch_zip ? 'Build artifacts are ready.' : 'No build artifacts are available.'}</p>
            <button type="button" disabled={!codebaseLoaded} onClick={() => onPackage()}>Rebuild ZIP</button>
            <button type="button" disabled={!output?.has_patch_zip} onClick={() => onDownload('patch')}>Download patch</button>
            <button type="button" disabled={!output?.has_output_zip} onClick={() => onDownload('download')}>Download rebuilt ZIP</button>
          </div>
        )}
      </div>
    </section>
  );
}
