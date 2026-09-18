import { spawnSync } from 'node:child_process';
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  rmSync,
} from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DESKTOP_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const nextBin = join(DESKTOP_ROOT, 'node_modules', 'next', 'dist', 'bin', 'next');

const build = spawnSync(process.execPath, [nextBin, 'build', '--webpack'], {
  cwd: DESKTOP_ROOT,
  stdio: 'inherit',
  env: { ...process.env, SENTINEL_DESKTOP_BUILD: '1' },
});
if (build.status !== 0) process.exit(build.status ?? 1);

const standalone = join(DESKTOP_ROOT, '.next', 'standalone');
const serverJs = join(standalone, 'server.js');
if (!existsSync(serverJs)) {
  console.error('[ERROR] .next/standalone/server.js is missing after the Next build');
  process.exit(1);
}

const staticSource = join(DESKTOP_ROOT, '.next', 'static');
if (existsSync(staticSource)) {
  mkdirSync(join(standalone, '.next'), { recursive: true });
  cpSync(staticSource, join(standalone, '.next', 'static'), { recursive: true });
}
const publicSource = join(DESKTOP_ROOT, 'public');
if (existsSync(publicSource)) {
  cpSync(publicSource, join(standalone, 'public'), { recursive: true });
}

function isLink(target) {
  try {
    return lstatSync(target).isSymbolicLink();
  } catch {
    return false;
  }
}

function flattenPnpmModules(nodeModules) {
  const store = join(nodeModules, '.pnpm');
  if (!existsSync(store)) return 0;
  let copied = 0;
  const materialize = (name, source) => {
    const target = join(nodeModules, name);
    if (existsSync(target) && !isLink(target)) return;
    rmSync(target, { recursive: true, force: true });
    mkdirSync(dirname(target), { recursive: true });
    cpSync(source, target, { recursive: true, dereference: true });
    copied += 1;
  };
  // ponytail: first package version wins; preserve .pnpm if version conflicts appear.
  for (const packageDir of readdirSync(store)) {
    const inner = join(store, packageDir, 'node_modules');
    if (!existsSync(inner)) continue;
    for (const entry of readdirSync(inner)) {
      if (entry === '.bin') continue;
      const entryPath = join(inner, entry);
      if (entry.startsWith('@')) {
        for (const scoped of readdirSync(entryPath)) {
          materialize(`${entry}/${scoped}`, join(entryPath, scoped));
        }
      } else {
        materialize(entry, entryPath);
      }
    }
  }
  return copied;
}

const copied = flattenPnpmModules(join(standalone, 'node_modules'));
console.log(`[INFO] materialized ${copied} pnpm package(s)`);
console.log('[SUCCESS] desktop standalone prepared at .next/standalone');
