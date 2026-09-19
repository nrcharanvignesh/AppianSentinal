'use strict';

const { app, BrowserWindow, dialog, Menu } = require('electron');
const { randomUUID } = require('node:crypto');
const { appendFileSync, existsSync, mkdirSync, rmSync, writeFileSync } = require('node:fs');
const { createServer, createConnection } = require('node:net');
const { spawn, spawnSync } = require('node:child_process');
const path = require('node:path');
const { applyExternalLinkPolicy } = require('./external-links');
const { resolveWorkspacePaths } = require('./workspace-paths');
const { startWindowsJobOwner } = require('./windows-job');

// Defaults match the Testing Toolkit process shape. Override with
// SENTINEL_AGENT_PORT / SENTINEL_UI_PORT if another local app already binds them.
// ensurePortAvailable refuses to kill a listener this install does not own.
const AGENT_PORT = Number(process.env.SENTINEL_AGENT_PORT || 7842);
const UI_PORT = Number(process.env.SENTINEL_UI_PORT || 8888);
const HEALTH_TIMEOUT_MS = 120000;
const POLL_MS = 250;
const SPLASH_TIMEOUT_MS = 60000;
const IS_DEV = process.env.SENTINEL_DEV === '1' || !app.isPackaged;
const DESKTOP_ROOT = path.join(__dirname, '..');
const REPO_ROOT = path.join(DESKTOP_ROOT, '..');
const OWNERSHIP_ID = randomUUID();
const API_TOKEN = randomUUID();

let workspacePaths;
let runtimeEnv = { ...process.env };
let mainWindow = null;
let splashWindow = null;
let splashTimer = null;
let agentProc = null;
let uiProc = null;
let shuttingDown = false;

function configureRuntimePaths() {
  const paths = resolveWorkspacePaths();
  for (const directory of Object.values(paths)) mkdirSync(directory, { recursive: true });

  const electronPaths = {
    userData: path.join(paths.electron, 'user-data'),
    sessionData: path.join(paths.electron, 'session'),
    logs: paths.logs,
    temp: paths.tmp,
    crashDumps: path.join(paths.logs, 'crash-dumps'),
    cache: path.join(paths.cache, 'chromium'),
  };
  for (const directory of Object.values(electronPaths)) {
    mkdirSync(directory, { recursive: true });
  }
  app.setPath('userData', electronPaths.userData);
  app.setPath('sessionData', electronPaths.sessionData);
  app.setPath('logs', electronPaths.logs);
  app.setPath('temp', electronPaths.temp);
  app.setPath('crashDumps', electronPaths.crashDumps);
  app.commandLine.appendSwitch('disk-cache-dir', electronPaths.cache);
  app.commandLine.appendSwitch('media-cache-dir', path.join(paths.cache, 'media'));

  const overrides = {
    SENTINEL_WORKSPACE_DIR: paths.workspace,
    SENTINEL_INSTALL_DIR: paths.install,
    SENTINEL_LOG_DIR: paths.logs,
    SENTINEL_CONFIG_DIR: paths.config,
    PIP_CACHE_DIR: path.join(paths.cache, 'pip'),
    NPM_CONFIG_CACHE: path.join(paths.cache, 'npm'),
    XDG_CACHE_HOME: paths.cache,
    XDG_CONFIG_HOME: paths.config,
    XDG_DATA_HOME: path.join(paths.workspace, 'data'),
    TEMP: paths.tmp,
    TMP: paths.tmp,
    TMPDIR: paths.tmp,
  };
  Object.assign(process.env, overrides);
  workspacePaths = paths;
  runtimeEnv = { ...process.env, ...overrides };
}

function probeWorkspace() {
  const probe = path.join(workspacePaths.workspace, `.write-test-${process.pid}`);
  try {
    writeFileSync(probe, 'ok', { encoding: 'ascii', flag: 'wx' });
  } catch (error) {
    throw new Error(
      `Appian Sentinel cannot write to ${workspacePaths.workspace}. ` +
        `Check folder permissions and free space. ${String(error)}`
    );
  } finally {
    rmSync(probe, { force: true });
  }
}

function log(level, message) {
  const line = `[${level}] ${message}`;
  console.log(line);
  if (!workspacePaths) return;
  try {
    appendFileSync(path.join(workspacePaths.logs, 'desktop.log'), `${line}\n`, 'ascii');
  } catch {
    // Logging must not terminate the supervisor.
  }
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function assertPortAvailable(port) {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once('error', (error) => reject(error));
    probe.once('listening', () => {
      probe.close((error) => (error ? reject(error) : resolve()));
    });
    probe.listen(port, '127.0.0.1');
  });
}

function windowsPortOwner(port) {
  if (process.platform !== 'win32') return null;
  const powershell = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );
  const script = [
    "$ErrorActionPreference='Stop'",
    `$c=Get-NetTCPConnection -State Listen -LocalPort ${port}|Select-Object -First 1`,
    'if(-not $c){exit 3}',
    "$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess)",
    'if(-not $p){exit 4}',
    "$e=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$p.ExecutablePath))",
    "$a=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$p.CommandLine))",
    "$d=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$p.CreationDate))",
    "Write-Output ($p.ProcessId.ToString()+'|'+$e+'|'+$a+'|'+$d)",
  ].join(';');
  const result = spawnSync(
    powershell,
    ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
    { encoding: 'utf8', windowsHide: true }
  );
  if (result.status !== 0 || !result.stdout) return null;
  const [rawPid, rawExecutable, rawCommandLine, rawCreation] = result.stdout.trim().split('|');
  const pid = Number(rawPid);
  if (!Number.isSafeInteger(pid) || pid <= 0) return null;
  return {
    pid,
    executable: Buffer.from(rawExecutable || '', 'base64').toString('utf8'),
    commandLine: Buffer.from(rawCommandLine || '', 'base64').toString('utf8'),
    creationDate: Buffer.from(rawCreation || '', 'base64').toString('utf8'),
  };
}

function isOwnedListener(owner, port) {
  const installRoot = path.resolve(workspacePaths.install).toLowerCase();
  const executable = path.resolve(owner.executable || '.').toLowerCase();
  if (!executable.startsWith(`${installRoot}${path.sep}`)) return false;
  if (port === AGENT_PORT) {
    return /appian-sentinel-sidecar(?:\.exe)?/i.test(
      `${owner.executable} ${owner.commandLine}`
    );
  }
  return /(?:^|\s)(?:"[^"]*"|[^\s"])*server\.js(?:"|\s|$)/i.test(owner.commandLine);
}

function killOwnedListener(owner) {
  const powershell = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );
  const expected = Buffer.from(owner.creationDate, 'utf8').toString('base64');
  const script = [
    "$ErrorActionPreference='Stop'",
    `$p=Get-CimInstance Win32_Process -Filter 'ProcessId=${owner.pid}'`,
    'if(-not $p){exit 0}',
    `$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${expected}'))`,
    'if([string]$p.CreationDate -ne $d){exit 5}',
    `& "$env:SystemRoot\\System32\\taskkill.exe" /PID ${owner.pid} /T /F|Out-Null`,
  ].join(';');
  const result = spawnSync(
    powershell,
    ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
    { encoding: 'utf8', windowsHide: true }
  );
  if (result.status !== 0) {
    throw new Error(`Windows could not stop stale Appian Sentinel process ${owner.pid}`);
  }
}

async function ensurePortAvailable(port, label) {
  try {
    await assertPortAvailable(port);
    return;
  } catch {
    // Inspect the listener identity before any termination.
  }
  const owner = windowsPortOwner(port);
  if (!owner || !isOwnedListener(owner, port)) {
    const detail = owner ? `process ${owner.pid} (${path.basename(owner.executable)})` : 'an unknown process';
    throw new Error(`Port ${port} is used by ${detail}. It was left unchanged.`);
  }
  log('WARN', `Stopping stale ${label} process ${owner.pid} on port ${port}`);
  killOwnedListener(owner);
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      await assertPortAvailable(port);
      return;
    } catch {
      await delay(POLL_MS);
    }
  }
  throw new Error(`Stale ${label} process ${owner.pid} stopped, but port ${port} is still busy`);
}

async function waitForPort(port, timeoutMs = HEALTH_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const socket = createConnection({ host: '127.0.0.1', port });
        socket.once('connect', () => {
          socket.end();
          resolve();
        });
        socket.once('error', reject);
      });
      return;
    } catch {
      await delay(POLL_MS);
    }
  }
  throw new Error(`Port ${port} did not become ready`);
}

async function waitForHealth(ownershipId) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${AGENT_PORT}/api/health`);
      if (response.status === 200) {
        const body = await response.json();
        if (body?.ownership_id === ownershipId) return;
      }
    } catch {
      // Retry until the bounded deadline.
    }
    await delay(POLL_MS);
  }
  throw new Error(
    `Agent health on port ${AGENT_PORT} did not return ownership_id ${ownershipId}`
  );
}

function rejectOnSpawnError(child, label) {
  return new Promise((_resolve, reject) => {
    child.once('error', (error) => {
      reject(new Error(`${label} failed to launch: ${error.message}`));
    });
  });
}

function rejectOnEarlyExit(child, label) {
  return new Promise((_resolve, reject) => {
    child.once('exit', (code, signal) => {
      reject(
        new Error(
          `${label} exited before readiness (code ${code ?? 'none'}, signal ${signal ?? 'none'})`
        )
      );
    });
  });
}

function pipeChild(child, label) {
  child.stdout?.on('data', (chunk) => process.stdout.write(`[${label}] ${chunk}`));
  child.stderr?.on('data', (chunk) => process.stderr.write(`[${label}] ${chunk}`));
}

async function startUiServer() {
  if (IS_DEV) {
    const url = process.env.NEXT_DEV_SERVER_URL || `http://127.0.0.1:${UI_PORT}`;
    await waitForPort(new URL(url).port ? Number(new URL(url).port) : UI_PORT);
    return url;
  }

  await ensurePortAvailable(UI_PORT, 'UI server');
  const root = path.join(process.resourcesPath, 'next-standalone');
  const serverJs = path.join(root, 'server.js');
  if (!existsSync(serverJs)) throw new Error(`Next standalone server is missing: ${serverJs}`);

  const child = spawn(process.execPath, [serverJs], {
    cwd: root,
    env: {
      ...runtimeEnv,
      ELECTRON_RUN_AS_NODE: '1',
      PORT: String(UI_PORT),
      HOSTNAME: '127.0.0.1',
      NODE_ENV: 'production',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  uiProc = child;
  pipeChild(child, 'ui');
  child.once('exit', () => {
    if (uiProc === child) uiProc = null;
  });
  await Promise.race([
    waitForPort(UI_PORT),
    rejectOnSpawnError(child, 'UI server'),
    rejectOnEarlyExit(child, 'UI server'),
  ]);
  return `http://127.0.0.1:${UI_PORT}`;
}

async function startAgent() {
  await ensurePortAvailable(AGENT_PORT, 'agent');
  let command;
  let args;
  let cwd;
  if (IS_DEV) {
    command = process.platform === 'win32' ? 'python' : 'python3';
    args = [
      '-m',
      'uvicorn',
      'appian_sentinel.main:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(AGENT_PORT),
    ];
    cwd = REPO_ROOT;
  } else {
    command = path.join(
      process.resourcesPath,
      'sidecar',
      process.platform === 'win32'
        ? 'appian-sentinel-sidecar.exe'
        : 'appian-sentinel-sidecar'
    );
    args = [];
    cwd = path.dirname(command);
  }

  const child = spawn(command, args, {
    cwd,
    env: {
      ...runtimeEnv,
      SENTINEL_HOST: '127.0.0.1',
      SENTINEL_PORT: String(AGENT_PORT),
      SENTINEL_DESKTOP_OWNERSHIP_ID: OWNERSHIP_ID,
      SENTINEL_API_TOKEN: API_TOKEN,
      SENTINEL_WORKSPACE_DIR: workspacePaths.workspace,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  agentProc = child;
  pipeChild(child, 'agent');
  child.once('exit', () => {
    if (agentProc === child) agentProc = null;
  });
  await Promise.race([
    waitForHealth(OWNERSHIP_ID),
    rejectOnSpawnError(child, 'agent'),
    rejectOnEarlyExit(child, 'agent'),
  ]);
}

function closeSplash() {
  if (splashTimer) clearTimeout(splashTimer);
  splashTimer = null;
  const win = splashWindow;
  splashWindow = null;
  if (win && !win.isDestroyed()) win.close();
}

const SPLASH_HTML =
  '<!doctype html><html><head><meta charset="utf-8">' +
  '<meta http-equiv="Content-Security-Policy" content="default-src \'none\';style-src \'unsafe-inline\'">' +
  '</head><body style="margin:0;height:100vh;display:flex;align-items:center;' +
  'justify-content:center;background:#0f1115;color:#c7ccd6;font-family:Segoe UI,sans-serif">' +
  '<div role="status" style="text-align:center"><h2>Appian Sentinel</h2><p>Starting...</p></div>' +
  '</body></html>';

function openSplash() {
  const win = new BrowserWindow({
    width: 380,
    height: 200,
    frame: false,
    center: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    skipTaskbar: true,
    focusable: false,
    show: true,
    backgroundColor: '#0f1115',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setMenuBarVisibility(false);
  win.on('closed', () => {
    if (splashWindow === win) splashWindow = null;
  });
  splashWindow = win;
  void win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`);
  splashTimer = setTimeout(closeSplash, SPLASH_TIMEOUT_MS);
}

function createWindow(uiUrl) {
  if (process.platform !== 'darwin') Menu.setApplicationMenu(null);
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    backgroundColor: '#0f1115',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      additionalArguments: [
        `--sentinel-base-url=${encodeURIComponent(`http://127.0.0.1:${AGENT_PORT}`)}`,
        `--sentinel-ws-url=${encodeURIComponent(`ws://127.0.0.1:${AGENT_PORT}`)}`,
        `--sentinel-port=${AGENT_PORT}`,
        `--sentinel-token=${encodeURIComponent(API_TOKEN)}`,
      ],
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = win;
  applyExternalLinkPolicy(win);
  win.once('ready-to-show', () => {
    closeSplash();
    if (!win.isDestroyed()) win.show();
  });
  win.webContents.on('did-fail-load', closeSplash);
  win.on('close', shutdown);
  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null;
  });
  void win.loadURL(uiUrl);
}

function killChildTree(child) {
  if (!child?.pid) return;
  try {
    child.kill('SIGKILL');
  } catch {
    // The child already exited.
  }
}

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  closeSplash();
  const agent = agentProc;
  const ui = uiProc;
  agentProc = null;
  uiProc = null;
  killChildTree(agent);
  killChildTree(ui);
}

function showStartupError(error) {
  closeSplash();
  const detail = error instanceof Error ? error.message : String(error);
  log('ERROR', detail);
  dialog.showErrorBox(
    'Appian Sentinel failed to start',
    `${detail}\n\nTechnical details: ${path.join(workspacePaths.logs, 'desktop.log')}`
  );
}

async function bootDesktop() {
  openSplash();
  try {
    await startWindowsJobOwner(workspacePaths.electron);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    log('WARN', `Windows Job Object unavailable; continuing without it: ${detail}`);
  }
  const [uiUrl] = await Promise.all([startUiServer(), startAgent()]);
  createWindow(uiUrl);
}

let startupError = null;
try {
  configureRuntimePaths();
  probeWorkspace();
} catch (error) {
  startupError = error;
}

const gotSingleInstanceLock = startupError === null && app.requestSingleInstanceLock();
if (startupError) {
  dialog.showErrorBox('Appian Sentinel workspace unavailable', startupError.message);
  app.exit(1);
} else if (!gotSingleInstanceLock) {
  app.quit();
}

app.on('second-instance', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
});

app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;
  try {
    await bootDesktop();
  } catch (error) {
    shutdown();
    showStartupError(error);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  shutdown();
  if (process.platform !== 'darwin') app.quit();
});
app.on('before-quit', shutdown);
app.on('will-quit', shutdown);
process.on('exit', shutdown);
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    shutdown();
    app.exit(0);
  });
}
