import { spawn, spawnSync } from 'node:child_process';
import { createConnection } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DESKTOP_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.env.SENTINEL_UI_PORT || 8871);

function waitForPort(port, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const probe = () => {
      const socket = createConnection({ host: '127.0.0.1', port });
      socket.once('connect', () => {
        socket.end();
        resolve();
      });
      socket.once('error', () => {
        socket.destroy();
        if (Date.now() >= deadline) {
          reject(new Error(`port ${port} did not become ready`));
          return;
        }
        setTimeout(probe, 250);
      });
    };
    probe();
  });
}

const next = spawn(
  process.execPath,
  [join(DESKTOP_ROOT, 'node_modules', 'next', 'dist', 'bin', 'next'), 'dev', '-p', String(PORT)],
  { cwd: DESKTOP_ROOT, stdio: 'inherit', env: process.env }
);

await waitForPort(PORT);
console.log('[INFO] Next.js is ready; launching Electron');

const { ELECTRON_RUN_AS_NODE: _ignored, ...cleanEnv } = process.env;
const electron = spawn(
  process.execPath,
  [join(DESKTOP_ROOT, 'node_modules', 'electron', 'cli.js'), '.'],
  {
    cwd: DESKTOP_ROOT,
    stdio: 'inherit',
    env: {
      ...cleanEnv,
      SENTINEL_DEV: '1',
      NEXT_DEV_SERVER_URL: `http://127.0.0.1:${PORT}`,
    },
  }
);

const children = [next, electron];
function shutdown(code = 0) {
  for (const child of children) {
    if (!child?.pid || child.killed) continue;
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      child.kill('SIGTERM');
    }
  }
  process.exit(code);
}

next.once('error', (error) => {
  console.error(`[ERROR] Next.js failed to launch: ${error.message}`);
  shutdown(1);
});
electron.once('error', (error) => {
  console.error(`[ERROR] Electron failed to launch: ${error.message}`);
  shutdown(1);
});
electron.once('exit', (code) => shutdown(code ?? 0));
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));
