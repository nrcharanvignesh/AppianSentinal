const NAVIGABLE_REFERENCE = /\b(rule|cons|recordType)!([A-Za-z_][A-Za-z0-9_]*)/gi;
const UUID_REFERENCE = /#"\s*(_a-[A-Za-z0-9_-]+)"/gi;

function lineAt(source, offset) {
  return source.slice(0, offset).split('\n').length;
}

function uniqueMatches(source, expression, kind, nameGroup = 1) {
  const seen = new Set();
  const result = [];
  for (const match of source.matchAll(expression)) {
    const name = match[nameGroup];
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push({ kind, name, line: lineAt(source, match.index), offset: match.index });
  }
  return result;
}

export function extractSymbols(source) {
  const inputs = uniqueMatches(source, /\bri!([A-Za-z_][A-Za-z0-9_]*)/gi, 'Rule input');
  const locals = [];
  const localStart = /\ba!localVariables\s*\(/i.exec(source);
  if (localStart) {
    let depth = 1;
    let end = source.length;
    for (let index = localStart.index + localStart[0].length; index < source.length; index += 1) {
      if (source[index] === '(') depth += 1;
      if (source[index] === ')') depth -= 1;
      if (depth === 0) {
        end = index;
        break;
      }
    }
    const section = source.slice(localStart.index, end);
    locals.push(...uniqueMatches(
      section,
      /\blocal!([A-Za-z_][A-Za-z0-9_]*)\s*:/gi,
      'Local',
    ).map((item) => ({
      ...item,
      line: lineAt(source, localStart.index + item.offset),
      offset: localStart.index + item.offset,
    })));
  }

  const calls = [];
  let depth = 0;
  let minimum = Number.POSITIVE_INFINITY;
  for (const match of source.matchAll(/\ba!([A-Za-z_][A-Za-z0-9_]*)\s*\(/gi)) {
    depth = 0;
    for (let index = 0; index < match.index; index += 1) {
      if (source[index] === '(') depth += 1;
      if (source[index] === ')') depth = Math.max(0, depth - 1);
    }
    if (match[1].toLowerCase() === 'localvariables') continue;
    if (depth < minimum) {
      minimum = depth;
      calls.length = 0;
    }
    if (depth === minimum) {
      calls.push({
        kind: 'Component',
        name: `a!${match[1]}`,
        line: lineAt(source, match.index),
        offset: match.index,
      });
    }
  }
  return [...inputs, ...locals, ...calls].sort((left, right) => left.offset - right.offset);
}

export function extractObjectReferences(source) {
  const references = [];
  for (const match of source.matchAll(NAVIGABLE_REFERENCE)) {
    references.push({
      prefix: match[1].toLowerCase(),
      name: match[2],
      offset: match.index,
      line: lineAt(source, match.index),
    });
  }
  for (const match of source.matchAll(UUID_REFERENCE)) {
    references.push({
      prefix: 'uuid',
      name: match[1],
      offset: match.index,
      line: lineAt(source, match.index),
    });
  }
  return references;
}

export function buildNavigation(codebase, objects) {
  const entries = Object.entries(codebase?.uuid_to_name || {}).map(([uuid, name]) => ({
    uuid,
    name,
    type: Object.entries(codebase?.by_type || {})
      .find(([, ids]) => ids.includes(uuid))?.[0] || 'object',
  }));
  const byName = new Map();
  for (const item of entries) {
    const key = item.name.toLowerCase();
    byName.set(key, [...(byName.get(key) || []), item]);
  }

  function resolve(reference) {
    if (reference.prefix === 'uuid') {
      return entries.filter((item) => item.uuid.toLowerCase() === reference.name.toLowerCase());
    }
    return byName.get(reference.name.toLowerCase()) || [];
  }

  const dependencies = {};
  const reverseDependencies = {};
  for (const item of entries) {
    const source = objects?.[item.uuid]?.definition || '';
    const targets = new Set();
    for (const reference of extractObjectReferences(source)) {
      for (const target of resolve(reference)) targets.add(target.uuid);
    }
    dependencies[item.uuid] = [...targets];
    for (const target of targets) {
      reverseDependencies[target] = [...(reverseDependencies[target] || []), item.uuid];
    }
  }
  return { entries, resolve, dependencies, reverseDependencies };
}
