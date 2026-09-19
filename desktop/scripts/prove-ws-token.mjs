// Prove a real Chromium WebSocket authenticates against a token-protected
// sidecar. TestClient does not enforce subprotocol echo; a browser does.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from '@playwright/test';

const HOST = '127.0.0.1';
const PORT = Number(process.env.SENTINEL_PROOF_PORT || 7899);
const TOKEN = 'proof-token-4f2a';
const SIDECAR = process.env.SENTINEL_PROOF_SIDECAR || join(
  process.env.USERPROFILE || '',
  'Documents',
  'AppianSentinel',
  'install',
  'desktop-app',
  'resources',
  'sidecar',
  'appian-sentinel-sidecar.exe'
);

function log(level, message) {
  console.log(`[${level}] ${message}`);
}

async function waitForHealth(deadlineMs) {
  while (Date.now() < deadlineMs) {
    try {
      const response = await fetch(`http://${HOST}:${PORT}/api/health`);
      if (response.ok) return true;
    } catch {
      // Sidecar is still binding.
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

async function connect(page, protocols) {
  return page.evaluate(
    ([url, requested]) => new Promise((resolve) => {
      const socket = requested.length
        ? new WebSocket(url, requested)
        : new WebSocket(url);
      const finish = (result) => {
        socket.close();
        resolve(result);
      };
      socket.onopen = () => finish({ open: true, protocol: socket.protocol });
      socket.onerror = () => resolve({ open: false, protocol: '' });
      socket.onclose = (event) => resolve({ open: false, code: event.code });
      setTimeout(() => resolve({ open: false, code: 'timeout' }), 8000);
    }),
    [`ws://${HOST}:${PORT}/ws?session_id=ws-proof`, protocols]
  );
}

function spawnSidecar() {
  const env = {
    ...process.env,
    SENTINEL_HOST: HOST,
    SENTINEL_PORT: String(PORT),
    SENTINEL_API_TOKEN: TOKEN,
  };
  if (process.env.SENTINEL_PROOF_DEV === '1') {
    const args = [
      '-m', 'uvicorn', 'appian_sentinel.main:app',
      '--host', HOST, '--port', String(PORT),
    ];
    return spawn(process.env.PYTHON || 'python', args, {
      cwd: join(import.meta.dirname, '..', '..'),
      env,
      stdio: 'ignore',
    });
  }
  if (!existsSync(SIDECAR)) {
    log('ERROR', `sidecar missing: ${SIDECAR}`);
    return null;
  }
  return spawn(SIDECAR, [], { env, stdio: 'ignore' });
}

async function main() {
  const sidecar = spawnSidecar();
  if (!sidecar) return 2;
  let browser;
  try {
    if (!(await waitForHealth(Date.now() + 60000))) {
      log('ERROR', `sidecar health never returned 200 on ${PORT}`);
      return 1;
    }
    log('INFO', `sidecar healthy on ${HOST}:${PORT} with a token set`);
    browser = await chromium.launch({
      channel: process.env.SENTINEL_PW_CHANNEL || 'msedge',
    });
    const page = await browser.newPage();

    const authorized = await connect(page, ['sentinel-token', TOKEN]);
    if (!authorized.open || authorized.protocol !== 'sentinel-token') {
      log('ERROR', `token subprotocol rejected: ${JSON.stringify(authorized)}`);
      return 1;
    }
    log('SUCCESS', 'browser WebSocket opened and negotiated sentinel-token');

    const anonymous = await connect(page, []);
    if (anonymous.open) {
      log('ERROR', 'untokened browser WebSocket was accepted');
      return 1;
    }
    log('SUCCESS', `untokened browser WebSocket refused: ${JSON.stringify(anonymous)}`);

    const wrong = await connect(page, ['sentinel-token', 'not-the-token']);
    if (wrong.open) {
      log('ERROR', 'wrong-token browser WebSocket was accepted');
      return 1;
    }
    log('SUCCESS', `wrong-token browser WebSocket refused: ${JSON.stringify(wrong)}`);
    return 0;
  } finally {
    await browser?.close();
    sidecar.kill();
  }
}

process.exitCode = await main();
