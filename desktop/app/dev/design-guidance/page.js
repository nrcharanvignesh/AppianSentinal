'use client';

import { useState } from 'react';
import DesignGuidancePanel from '../../../components/DesignGuidancePanel';
import { useAppTheme } from '../../../components/AppThemeProvider';

const FINDINGS = [
  {
    id: 'syntax-broken-expression',
    objectUuid: 'broken-expression-uuid',
    objectName: 'APP_BrokenExpression',
    objectType: 'expression_rule',
    severity: 'error',
    message: 'Expected a closing parenthesis.',
    line: 8,
    ruleName: 'SAIL001',
  },
  {
    id: 'warning-broken-expression',
    objectUuid: 'broken-expression-uuid',
    objectName: 'APP_BrokenExpression',
    objectType: 'expression_rule',
    severity: 'warning',
    message: 'Invalid parameter may cause unexpected behavior.',
    line: 4,
    ruleName: 'Invalid parameter',
  },
  {
    id: 'recommendation-broken-expression',
    objectUuid: 'broken-expression-uuid',
    objectName: 'APP_BrokenExpression',
    objectType: 'expression_rule',
    severity: 'recommendation',
    message: 'Remove the unused local variable.',
    line: 2,
    ruleName: 'Unused local variable',
  },
  {
    id: 'warning-active-interface',
    objectUuid: 'active-interface-uuid',
    objectName: 'APP_OrderForm',
    objectType: 'interface',
    severity: 'warning',
    message: 'Record field reference is invalid.',
    line: 14,
    ruleName: 'Invalid record field reference',
  },
  {
    id: 'recommendation-active-interface',
    objectUuid: 'active-interface-uuid',
    objectName: 'APP_OrderForm',
    objectType: 'interface',
    severity: 'recommendation',
    message: 'Scope this variable inside the component.',
    line: 21,
    ruleName: 'Improperly scoped variable',
  },
];

export default function DesignGuidanceDevPage() {
  const { mode, toggleMode } = useAppTheme();
  const [opened, setOpened] = useState('No finding opened.');

  return (
    <main className="design-guidance-dev">
      <div className="design-guidance-dev-toolbar">
        <button
          type="button"
          onClick={toggleMode}
          aria-label={mode === 'dark' ? 'Use light mode' : 'Use dark mode'}
        >
          {mode === 'dark' ? 'Light theme' : 'Dark theme'}
        </button>
        <p className="design-guidance-dev-status" aria-live="polite">{opened}</p>
      </div>
      <DesignGuidancePanel
        findings={FINDINGS}
        onOpenFinding={(finding) => setOpened(
          `Opened ${finding.objectName} at line ${finding.line || 1}.`,
        )}
      />
    </main>
  );
}
