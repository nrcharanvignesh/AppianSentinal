'use strict';

const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const net = require('net');
const path = require('path');
const fs = require('fs');

const IS_DEV = process.env.SENTINEL_DEV === '1';
const REPO_ROOT = path.join(__dirname, '..', '..'); // desktop/electron -> repo root

let sidecarProc = null;
let staticServer = null;
let mainWindow = null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function waitForHealth(port, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(
        { host: '127.0.0.1', port, path: '/api/health', timeout: 2000 },
        (res) => {
          res.resume();
          if (res.statusCode === 200) return resolve();
          retry();
        }
      );
      req.on('error', retry);
      req.on('timeout', () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error('Sidecar health check timed out'));
      setTimeout(attempt, 400);
    };
    attempt();
  });
}

function startSidecar(port) {
  const env = { ...process.env, SENTINEL_HOST: '127.0.0.1', SENTINEL_PORT: String(port) };
  let cmd, args, cwd;

  if (IS_DEV) {
    cmd = process.platform === 'win32' ? 'python' : 'python3';
    args = ['-m', 'uvicorn', 'appian_sentinel.main:app', '--host', '127.0.0.1', '--port', String(port)];
    cwd = REPO_ROOT;
  } else {
    // Packaged: PyInstaller sidecar exe under resources/sidecar/
    const exeName = process.platform === 'win32' ? 'appian-sentinel-sidecar.exe' : 'appian-sentinel-sidecar';
    cmd = path.join(process.resourcesPath, 'sidecar', exeName);
    args = [];
    cwd = path.dirname(cmd);
  }

  console.log('[sentinel] starting sidecar:', cmd, args.join(' '));
  sidecarProc = spawn(cmd, args, { cwd, env });
  sidecarProc.stdout.on('data', (d) => process.stdout.write(`[sidecar] ${d}`));
  sidecarProc.stderr.on('data', (d) => process.stderr.write(`[sidecar] ${d}`));
  sidecarProc.on('exit', (code) => console.log('[sentinel] sidecar exited', code));
}

// Minimal static server for the exported Next.js `out/` folder (prod only).
function startStaticServer(rootDir) {
  const mime = {
    '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
    '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
    '.woff': 'font/woff', '.txt': 'text/plain', '.map': 'application/json',
  };
  return new Promise(async (resolve) => {
    const port = await findFreePort();
    staticServer = http.createServer((req, res) => {
      let urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
      if (urlPath === '/') urlPath = '/index.html';
      let filePath = path.join(rootDir, urlPath);
      if (!filePath.startsWith(rootDir)) { res.writeHead(403); return res.end(); }
      // Next static export uses folder/index.html and .html fallbacks.
      if (!fs.existsSync(filePath)) {
        if (fs.existsSync(filePath + '.html')) filePath += '.html';
        else if (fs.existsSync(path.join(filePath, 'index.html'))) filePath = path.join(filePath, 'index.html');
        else filePath = path.join(rootDir, 'index.html'); // SPA fallback
      }
      fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); return res.end('Not found'); }
        res.writeHead(200, { 'Content-Type': mime[path.extname(filePath)] || 'application/octet-stream' });
        res.end(data);
      });
    });
    staticServer.listen(port, '127.0.0.1', () => resolve(port));
  });
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

async function createWindow() {
  const sidecarPort = await findFreePort();
  startSidecar(sidecarPort);

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    backgroundColor: '#0f1115',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--sentinel-port=${sidecarPort}`],
    },
  });

  // Show a lightweight loading page until the sidecar is healthy.
  mainWindow.loadURL(
    'data:text/html,' +
    encodeURIComponent(
      '<body style="margin:0;background:#0f1115;color:#c7ccd6;font-family:system-ui;' +
      'display:flex;align-items:center;justify-content:center;height:100vh">' +
      '<div style="text-align:center"><h2>Appian Sentinel</h2>' +
      '<p>Starting engine…</p></div></body>'
    )
  );
  mainWindow.show();

  try {
    await waitForHealth(sidecarPort);
  } catch (e) {
    console.error('[sentinel]', e.message);
  }

  let uiUrl;
  if (IS_DEV) {
    uiUrl = 'http://localhost:3000';
  } else {
    const outDir = path.join(app.getAppPath(), 'out');
    const uiPort = await startStaticServer(outDir);
    uiUrl = `http://127.0.0.1:${uiPort}`;
  }
  await mainWindow.loadURL(uiUrl);
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

function cleanup() {
  if (sidecarProc && !sidecarProc.killed) { try { sidecarProc.kill(); } catch (_) {} }
  if (staticServer) { try { staticServer.close(); } catch (_) {} }
}
app.on('before-quit', cleanup);
process.on('exit', cleanup);
