const INDENT = '  ';

function lineRange(value, selectionStart, selectionEnd) {
  const start = selectionStart === 0
    ? 0
    : value.lastIndexOf('\n', selectionStart - 1) + 1;
  const adjustedEnd = selectionEnd > selectionStart && value[selectionEnd - 1] === '\n'
    ? selectionEnd - 1
    : selectionEnd;
  const nextBreak = value.indexOf('\n', adjustedEnd);
  return {
    start,
    end: nextBreak < 0 ? value.length : nextBreak,
  };
}

function replaceRange(value, start, end, replacement) {
  return `${value.slice(0, start)}${replacement}${value.slice(end)}`;
}

export function formatExpression(value) {
  const newline = value.includes('\r\n') ? '\r\n' : '\n';
  const lines = value.replaceAll('\r\n', '\n').split('\n');
  let depth = 0;
  let inString = false;
  let inComment = false;

  const formatted = lines.map((rawLine) => {
    const content = rawLine.trimStart().trimEnd();
    if (!content) return '';

    let leadingClosers = 0;
    if (!inString && !inComment) {
      while (leadingClosers < content.length && ')}]'.includes(content[leadingClosers])) {
        leadingClosers += 1;
      }
    }
    const lineDepth = Math.max(0, depth - leadingClosers);
    let escaped = false;

    for (let index = 0; index < content.length; index += 1) {
      const character = content[index];
      const next = content[index + 1];
      if (inComment) {
        if (character === '*' && next === '/') {
          inComment = false;
          index += 1;
        }
        continue;
      }
      if (inString) {
        if (character === '"' && !escaped) inString = false;
        escaped = character === '\\' && !escaped;
        if (character !== '\\') escaped = false;
        continue;
      }
      if (character === '/' && next === '*') {
        inComment = true;
        index += 1;
      } else if (character === '"') {
        inString = true;
        escaped = false;
      } else if ('({['.includes(character)) {
        depth += 1;
      } else if (')}]'.includes(character)) {
        depth = Math.max(0, depth - 1);
      }
    }
    return `${INDENT.repeat(lineDepth)}${content}`;
  });

  return formatted.join(newline);
}

export function changeIndent(value, selectionStart, selectionEnd, direction) {
  const range = lineRange(value, selectionStart, selectionEnd);
  const selected = value.slice(range.start, range.end);
  const lines = selected.split('\n');
  const nextLines = lines.map((line) => {
    if (!line) return line;
    if (direction > 0) return `${INDENT}${line}`;
    if (line.startsWith(INDENT)) return line.slice(INDENT.length);
    if (line.startsWith(' ')) return line.slice(1);
    return line;
  });
  const replacement = nextLines.join('\n');
  return {
    value: replaceRange(value, range.start, range.end, replacement),
    selection: { start: range.start, end: range.start + replacement.length },
  };
}

export function toggleComment(value, selectionStart, selectionEnd) {
  const range = lineRange(value, selectionStart, selectionEnd);
  const selected = value.slice(range.start, range.end);
  const lines = selected.split('\n');
  const nonEmpty = lines.filter((line) => line.trim());
  const uncomment = nonEmpty.length > 0 && nonEmpty.every(
    (line) => line.trimStart().startsWith('/* ') && line.trimEnd().endsWith(' */'),
  );
  const nextLines = lines.map((line) => {
    if (!line.trim()) return line;
    const indent = line.match(/^\s*/)[0];
    const content = line.slice(indent.length);
    if (uncomment) return `${indent}${content.slice(3, -3)}`;
    return `${indent}/* ${content} */`;
  });
  const replacement = nextLines.join('\n');
  return {
    value: replaceRange(value, range.start, range.end, replacement),
    selection: { start: range.start, end: range.start + replacement.length },
  };
}

export function findMatches(value, query) {
  if (!query) return [];
  const matches = [];
  let offset = 0;
  while (offset <= value.length - query.length) {
    const index = value.indexOf(query, offset);
    if (index < 0) break;
    matches.push({ start: index, end: index + query.length });
    offset = index + Math.max(1, query.length);
  }
  return matches;
}

export function replaceMatch(value, start, end, replacement) {
  const nextValue = replaceRange(value, start, end, replacement);
  return {
    value: nextValue,
    selection: { start, end: start + replacement.length },
  };
}

export function replaceAll(value, query, replacement) {
  if (!query) return { value, count: 0 };
  const matches = findMatches(value, query);
  return {
    value: value.split(query).join(replacement),
    count: matches.length,
  };
}
