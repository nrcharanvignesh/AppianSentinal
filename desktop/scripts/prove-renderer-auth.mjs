// Prove the renderer's two authenticated paths against a token-protected
// sidecar using a real browser from a real cross-origin page. TestClient
// enforces neither WebSocket subprotocol echo nor CORS preflight; a browser
// enforces both, and each has already shipped broken once.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from '@playwright/test';

const HOST = '127.0.0.1';
const PORT = Number(process.env.SENTINEL_PROOF_PORT || 7899);
const ORIGIN_PORT = PORT + 1;
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

// A distinct origin, exactly like the renderer on 8888 calling the sidecar.
function startOriginServer() {
  const server = createServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end('<!doctype html><title>proof</title>');
  });
  return new Promise((resolve) => {
    server.listen(ORIGIN_PORT, HOST, () => resolve(server));
  });
}

async function crossOriginFetch(page, token) {
  return page.evaluate(
    async ([url, value]) => {
      try {
        const response = await fetch(url, {
          headers: value ? { 'X-Sentinel-Token': value } : {},
        });
        return { ok: response.ok, status: response.status };
      } catch (error) {
        return { ok: false, status: `failed-to-fetch: ${error.message}` };
      }
    },
    [`http://${HOST}:${PORT}/api/status?session_id=proof`, token]
  );
}

async function main() {
  const sidecar = spawnSidecar();
  if (!sidecar) return 2;
  const originServer = await startOriginServer();
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
    await page.goto(`http://${HOST}:${ORIGIN_PORT}/`);

    const allowed = await crossOriginFetch(page, TOKEN);
    if (!allowed.ok) {
      log('ERROR', `cross-origin REST with token failed: ${JSON.stringify(allowed)}`);
      return 1;
    }
    log('SUCCESS', 'cross-origin REST with token passed preflight and returned 200');

    const denied = await crossOriginFetch(page, '');
    if (denied.ok) {
      log('ERROR', 'cross-origin REST without token was accepted');
      return 1;
    }
    log('SUCCESS', `cross-origin REST without token refused: ${JSON.stringify(denied)}`);

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
    originServer.close();
    sidecar.kill();
  }
}

process.exitCode = await main();
