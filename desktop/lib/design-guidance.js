export const DISMISSALS_STORAGE_KEY = 'appian-sentinel-design-guidance-dismissals';

const SEVERITIES = new Set(['error', 'warning', 'recommendation']);

export function classifySeverity(value) {
  const severity = String(value || '').toLowerCase();
  if (severity === 'syntax' || severity === 'syntax_error') return 'error';
  return SEVERITIES.has(severity) ? severity : 'warning';
}

export function dismissalKey(finding) {
  return `${finding.objectUuid}::${finding.id || finding.ruleName || finding.code}`;
}

export function normalizeDiagnostics(rawDiagnostics, object = {}) {
  const diagnostics = Array.isArray(rawDiagnostics)
    ? rawDiagnostics
    : rawDiagnostics?.diagnostics || rawDiagnostics?.items || [];

  return diagnostics.map((diagnostic, index) => {
    const objectUuid = diagnostic.objectUuid || diagnostic.object_uuid
      || object.uuid || object.objectUuid || '';
    const objectName = diagnostic.objectName || diagnostic.object_name
      || object.name || object.objectName || objectUuid || 'Unknown object';
    const objectType = diagnostic.objectType || diagnostic.object_type
      || object.object_type || object.type || object.objectType || 'unknown';
    const ruleName = diagnostic.ruleName || diagnostic.rule_name || diagnostic.code || '';
    const line = diagnostic.line ?? diagnostic.start_line;
    const id = diagnostic.id || [
      objectUuid,
      ruleName || 'diagnostic',
      line || 0,
      diagnostic.column || 0,
      diagnostic.message || index,
    ].join('::');

    return {
      ...diagnostic,
      id,
      objectUuid,
      objectName,
      objectType,
      severity: classifySeverity(diagnostic.severity),
      message: String(diagnostic.message || 'No diagnostic message was provided.'),
      ...(line == null ? {} : { line: Number(line) }),
      ...(ruleName ? { ruleName } : {}),
    };
  });
}

export function applyDismissals(findings, dismissedKeys) {
  const keys = dismissedKeys instanceof Set ? dismissedKeys : new Set(dismissedKeys || []);
  return findings.filter((finding) => (
    finding.severity !== 'recommendation' || !keys.has(dismissalKey(finding))
  ));
}

export function computeSuppression(findings) {
  const objectsWithSyntaxErrors = new Set(
    findings
      .filter((finding) => finding.severity === 'error')
      .map((finding) => finding.objectUuid),
  );
  const visible = [];
  const suppressed = [];

  findings.forEach((finding) => {
    if (
      finding.severity !== 'error'
      && objectsWithSyntaxErrors.has(finding.objectUuid)
    ) {
      suppressed.push(finding);
    } else {
      visible.push(finding);
    }
  });

  const notices = [...objectsWithSyntaxErrors].flatMap((objectUuid) => {
    const hidden = suppressed.filter((finding) => finding.objectUuid === objectUuid);
    if (!hidden.length) return [];
    const syntaxFinding = findings.find(
      (finding) => finding.objectUuid === objectUuid && finding.severity === 'error',
    );
    return [{
      objectUuid,
      objectName: syntaxFinding?.objectName || objectUuid,
      count: hidden.length,
    }];
  });

  return { visible, suppressed, notices };
}

export function groupFindings(findings) {
  const groups = {
    error: [],
    warning: [],
    recommendation: [],
  };
  findings.forEach((finding) => groups[classifySeverity(finding.severity)].push(finding));
  return groups;
}
