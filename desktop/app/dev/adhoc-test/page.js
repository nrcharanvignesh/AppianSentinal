'use client';

import { useState } from 'react';
import AdHocTestPanel from '../../../components/AdHocTestPanel';
import { useAppTheme } from '../../../components/AppThemeProvider';

const RULE_INPUTS = [
  { name: 'amount', type_name: 'Decimal', current_value: '125.50' },
  { name: 'requester', type_name: 'Text', current_value: 'Ada' },
];

const SAVED_TEST_CASES = [
  { name: 'Approved request', status: 'Test passed' },
  {
    name: 'Unexpected total',
    status: 'Test failed: test output did not match asserted output',
  },
  {
    name: 'Rejected assertion',
    status: 'Test failed: assertion expression returned false',
  },
  { name: 'Unavailable dependency', status: 'Test failed to run' },
  { name: 'Rule error', status: 'Test returned an error' },
];

function pause(milliseconds) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

export default function AdHocTestHarness() {
  const { mode, toggleMode } = useAppTheme();
  const [runNumber, setRunNumber] = useState(0);

  async function runStaticAnalysis(inputs) {
    await pause(750);
    const amount = inputs.amount;
    const rawValue = amount?.mode === 'expression' ? amount.expression : amount?.value;
    if (String(rawValue).toLowerCase().includes('error')) {
      throw new Error('Referenced rule APP_MissingRule was not found in the export.');
    }

    setRunNumber((current) => current + 1);
    const failed = typeof rawValue === 'number' && rawValue < 0;
    return {
      summary: failed
        ? 'Static validation found an invalid negative fixture value.'
        : 'Static validation completed with no structural errors.',
      localVariables: [
        { name: 'local!approvalLimit', value: 'Value unavailable from static analysis' },
      ],
      output: {
        analysis: failed ? 'fixture-failure' : 'fixture-success',
        run: runNumber + 1,
        inputsReceived: Object.keys(inputs).length,
      },
      views: {
        'formatted-map': `{
  "analysis": "${failed ? 'fixture-failure' : 'fixture-success'}",
  "inputsReceived": ${Object.keys(inputs).length}
}`,
        'raw-list': `["analysis","${failed ? 'fixture-failure' : 'fixture-success'}","inputsReceived",${Object.keys(inputs).length}]`,
        expression: `a!map(analysis: "${failed ? 'fixture-failure' : 'fixture-success'}", inputsReceived: ${Object.keys(inputs).length})`,
      },
    };
  }

  return (
    <main className="adhoc-harness">
      <div className="adhoc-harness-toolbar">
        <button type="button" onClick={toggleMode}>
          Use {mode === 'dark' ? 'light' : 'dark'} theme
        </button>
      </div>
      <AdHocTestPanel
        ruleInputs={RULE_INPUTS}
        savedTestCases={SAVED_TEST_CASES}
        onRunTest={runStaticAnalysis}
      />
    </main>
  );
}
