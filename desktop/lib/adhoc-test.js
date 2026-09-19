export const OUTPUT_VIEWS = Object.freeze([
  { id: 'formatted-map', label: 'Formatted map' },
  { id: 'raw-list', label: 'Raw list' },
  { id: 'expression', label: 'Expression' },
]);

function inputType(input) {
  const base = input?.type ?? input?.type_name ?? 'Any Type';
  return `${base || 'Any Type'}${input?.is_list ? ' (List)' : ''}`;
}

export function normalizeRuleInputs(ruleInputs = []) {
  if (!Array.isArray(ruleInputs)) return [];
  return ruleInputs
    .filter((input) => input && typeof input.name === 'string' && input.name.trim())
    .map((input) => ({
      name: input.name.trim(),
      type: inputType(input),
      mode: input.mode === 'expression' ? 'expression' : 'static',
      value: String(input.currentValue ?? input.current_value ?? input.value ?? ''),
    }));
}

function staticValue(value, type) {
  const normalizedType = type.toLowerCase();
  const trimmed = value.trim();
  if (normalizedType.includes('boolean')) {
    if (trimmed === 'true') return true;
    if (trimmed === 'false') return false;
  }
  if (/(integer|decimal|number|float|double)/.test(normalizedType) && trimmed !== '') {
    const number = Number(trimmed);
    if (Number.isFinite(number)) return number;
  }
  return value;
}

export function serializeInputValues(inputs = []) {
  return Object.fromEntries(inputs.map((input) => [
    input.name,
    input.mode === 'expression'
      ? { mode: 'expression', expression: String(input.value ?? '') }
      : { mode: 'static', value: staticValue(String(input.value ?? ''), input.type || '') },
  ]));
}

function outputValue(result) {
  return result?.output ?? result?.details ?? result ?? null;
}

export function formatOutputView(result, view) {
  const supplied = result?.views?.[view];
  if (typeof supplied === 'string') return supplied;

  const output = outputValue(result);
  if (view === 'expression') {
    if (typeof output === 'string') return output;
    return JSON.stringify(output);
  }
  if (view === 'raw-list') {
    const list = Array.isArray(output) ? output : Object.entries(output || {});
    return JSON.stringify(list);
  }
  return JSON.stringify(output, null, 2);
}
