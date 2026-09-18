import { SAIL_CALLABLES, SAIL_REF_PREFIXES } from './sail-tokens';

const INVALID_OPERATORS = ['==', '!=', '&&', '||', '//', ';'];
const VALID_OPERATORS = ['<>', '<=', '>=', '=', '&', '+', '-', '*', '/', '<', '>'];
const PUNCTUATION = new Set(['(', ')', '{', '}', '[', ']', ',', ':', '.']);
const REFERENCE_PREFIXES = new Set([...SAIL_REF_PREFIXES, 'rule']);

function push(tokens, type, value, start, invalid = false) {
  tokens.push({ type, value, start, end: start + value.length, invalid });
}

export function tokenizeSail(source) {
  const tokens = [];
  let index = 0;
  while (index < source.length) {
    const rest = source.slice(index);
    if (rest.startsWith('/*')) {
      const close = source.indexOf('*/', index + 2);
      const end = close < 0 ? source.length : close + 2;
      push(tokens, 'comment', source.slice(index, end), index);
      index = end;
      continue;
    }
    if (source[index] === '"') {
      let end = index + 1;
      while (end < source.length) {
        if (source[end] === '"' && source[end - 1] !== '\\') {
          end += 1;
          break;
        }
        end += 1;
      }
      push(tokens, 'string', source.slice(index, end), index);
      index = end;
      continue;
    }
    if (source[index] === "'") {
      let end = index + 1;
      while (end < source.length && source[end] !== "'" && source[end] !== '\n') end += 1;
      if (source[end] === "'") end += 1;
      push(tokens, 'string', source.slice(index, end), index, true);
      index = end;
      continue;
    }
    const invalidOperator = INVALID_OPERATORS.find((value) => rest.startsWith(value));
    if (invalidOperator) {
      push(tokens, 'operator', invalidOperator, index, true);
      index += invalidOperator.length;
      continue;
    }
    const hashReference = rest.match(/^#"(?:[^"\\]|\\.)*"(?:\(\))?/);
    if (hashReference) {
      push(tokens, 'reference-prefix', hashReference[0], index);
      index += hashReference[0].length;
      continue;
    }
    const number = rest.match(/^\d+(?:\.\d+)?/);
    if (number) {
      push(tokens, 'number', number[0], index);
      index += number[0].length;
      continue;
    }
    const appianCallable = rest.match(/^a!([A-Za-z_][A-Za-z0-9_]*)/i);
    if (appianCallable) {
      const value = appianCallable[0];
      const next = source.slice(index + value.length).match(/^\s*/)[0].length + index + value.length;
      push(
        tokens,
        source[next] === '(' && SAIL_CALLABLES.has(value.toLowerCase()) ? 'callable' : 'plain',
        value,
        index,
      );
      index += value.length;
      continue;
    }
    const identifier = rest.match(/^[A-Za-z_][A-Za-z0-9_]*/);
    if (identifier) {
      const value = identifier[0];
      const next = source.slice(index + value.length).match(/^\s*/)[0].length + index + value.length;
      if (source[next] === '!' && REFERENCE_PREFIXES.has(value.toLowerCase())) {
        push(tokens, 'reference-prefix', `${value}!`, index);
        index += value.length + 1;
      } else {
        const callable = source[next] === '('
          && (SAIL_CALLABLES.has(value.toLowerCase())
            || SAIL_CALLABLES.has(`a!${value.toLowerCase()}`));
        push(tokens, callable ? 'callable' : 'plain', value, index);
        index += value.length;
      }
      continue;
    }
    const validOperator = VALID_OPERATORS.find((value) => rest.startsWith(value));
    if (validOperator) {
      push(tokens, 'operator', validOperator, index);
      index += validOperator.length;
      continue;
    }
    if (PUNCTUATION.has(source[index])) {
      push(tokens, 'punctuation', source[index], index);
      index += 1;
      continue;
    }
    const plain = rest.match(/^[\s]+/)?.[0] || source[index];
    push(tokens, 'plain', plain, index);
    index += plain.length;
  }
  return tokens;
}

export function positionToOffset(source, line = 1, column = 1) {
  const lines = source.split('\n');
  const safeLine = Math.max(1, Math.min(line, lines.length));
  return lines.slice(0, safeLine - 1).reduce((sum, value) => sum + value.length + 1, 0)
    + Math.max(0, Math.min(column - 1, lines[safeLine - 1].length));
}

export function decorateTokens(source, diagnostics = []) {
  const ranges = diagnostics.map((item) => ({
    start: positionToOffset(source, item.line, item.column),
    end: Math.max(
      positionToOffset(source, item.line, item.column) + 1,
      positionToOffset(source, item.end_line || item.line, item.end_column || item.column + 1),
    ),
    severity: item.severity || 'error',
  }));
  const result = [];
  for (const token of tokenizeSail(source)) {
    const boundaries = new Set([token.start, token.end]);
    for (const range of ranges) {
      if (range.start > token.start && range.start < token.end) boundaries.add(range.start);
      if (range.end > token.start && range.end < token.end) boundaries.add(range.end);
    }
    const points = [...boundaries].sort((a, b) => a - b);
    for (let index = 0; index < points.length - 1; index += 1) {
      const start = points[index];
      const end = points[index + 1];
      const diagnostic = ranges.find((range) => start < range.end && end > range.start);
      result.push({
        ...token,
        start,
        end,
        value: source.slice(start, end),
        diagnostic: diagnostic?.severity || '',
      });
    }
  }
  return result;
}

export function referenceAt(source, offset) {
  const expression = /(?:rule|cons|recordType)![A-Za-z_][A-Za-z0-9_]*/gi;
  for (const match of source.matchAll(expression)) {
    if (offset >= match.index && offset <= match.index + match[0].length) {
      const [prefix, name] = match[0].split('!');
      return { prefix: prefix.toLowerCase(), name, start: match.index };
    }
  }
  return null;
}
