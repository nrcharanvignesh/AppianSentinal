'use client';

import { useEffect, useMemo, useState } from 'react';
import '../app/design-guidance.css';
import {
  applyDismissals,
  computeSuppression,
  DISMISSALS_STORAGE_KEY,
  dismissalKey,
  groupFindings,
  normalizeDiagnostics,
} from '../lib/design-guidance';

const SECTIONS = [
  { severity: 'error', label: 'Syntax errors', singular: 'syntax error' },
  { severity: 'warning', label: 'Warnings', singular: 'warning' },
  { severity: 'recommendation', label: 'Recommendations', singular: 'recommendation' },
];

function GuidanceFinding({ finding, onDismiss, onOpenFinding }) {
  const location = finding.line ? `Line ${finding.line}` : '';
  const rule = finding.ruleName || finding.code || '';

  return (
    <li className={`guidance-finding is-${finding.severity}`}>
      <button
        type="button"
        className="guidance-finding-open"
        onClick={() => onOpenFinding?.(finding)}
        aria-label={`Open ${finding.severity}: ${finding.message}${location ? `, ${location}` : ''}`}
      >
        <span className={`guidance-icon is-${finding.severity}`} aria-hidden="true" />
        <span className="guidance-finding-content">
          <span className="guidance-message">{finding.message}</span>
          <span className="guidance-meta">
            {finding.objectName}
            <span aria-hidden="true"> | </span>
            {String(finding.objectType).replaceAll('_', ' ')}
            {rule && <><span aria-hidden="true"> | </span>{rule}</>}
            {location && <><span aria-hidden="true"> | </span>{location}</>}
          </span>
        </span>
      </button>
      {finding.severity === 'recommendation' && (
        <button
          type="button"
          className="guidance-dismiss"
          onClick={() => onDismiss(finding)}
          aria-label={`Dismiss recommendation: ${finding.message}`}
        >
          Dismiss
        </button>
      )}
    </li>
  );
}

export default function DesignGuidancePanel({ findings = [], onOpenFinding }) {
  const [dismissed, setDismissed] = useState(new Set());
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(DISMISSALS_STORAGE_KEY) || '[]');
      setDismissed(new Set(Array.isArray(saved) ? saved : []));
    } catch {
      setDismissed(new Set());
    }
    setReady(true);
  }, []);

  const model = useMemo(() => {
    const normalized = normalizeDiagnostics(findings);
    const active = applyDismissals(normalized, dismissed);
    const suppression = computeSuppression(active);
    return {
      groups: groupFindings(suppression.visible),
      notices: suppression.notices,
    };
  }, [dismissed, findings]);

  function dismiss(finding) {
    setDismissed((current) => {
      const next = new Set(current);
      next.add(dismissalKey(finding));
      try {
        window.localStorage.setItem(DISMISSALS_STORAGE_KEY, JSON.stringify([...next]));
      } catch {
        return next;
      }
      return next;
    });
  }

  const hasContent = SECTIONS.some(({ severity }) => model.groups[severity].length)
    || model.notices.length;

  return (
    <section
      className="design-guidance-panel"
      aria-labelledby="design-guidance-title"
      data-ready={ready}
    >
      <header className="guidance-header">
        <div>
          <h2 id="design-guidance-title">Appian Design Guidance</h2>
          <p>Warnings and Recommendations</p>
        </div>
      </header>

      {model.notices.map((notice) => (
        <p
          className="guidance-suppression"
          role="status"
          key={notice.objectUuid}
        >
          Guidance for {notice.objectName} is suppressed because syntax errors must be fixed first.
          {' '}{notice.count} {notice.count === 1 ? 'finding is' : 'findings are'} hidden.
        </p>
      ))}

      {SECTIONS.map(({ severity, label, singular }) => {
        const items = model.groups[severity];
        return (
          <section
            className={`guidance-group is-${severity}`}
            aria-labelledby={`guidance-${severity}-heading`}
            key={severity}
          >
            <h3 id={`guidance-${severity}-heading`}>
              <span className={`guidance-icon is-${severity}`} aria-hidden="true" />
              {label}
              <span
                className="guidance-count"
                aria-label={`${items.length} ${items.length === 1 ? singular : label.toLowerCase()}`}
              >
                {items.length}
              </span>
            </h3>
            {items.length > 0 && (
              <ul aria-label={label}>
                {items.map((finding) => (
                  <GuidanceFinding
                    finding={finding}
                    key={finding.id}
                    onDismiss={dismiss}
                    onOpenFinding={onOpenFinding}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}

      {!hasContent && <p className="guidance-empty">No design guidance reported.</p>}
    </section>
  );
}
