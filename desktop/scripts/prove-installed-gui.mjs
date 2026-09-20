// R31 acceptance: drive the INSTALLED app's real GUI through the full
// reference workflow -- import the reference export ZIP, browse the parsed
// objects, open one, rebuild the full ZIP, and download it. No mocks, no
// stub sidecar: this launches the packaged AppianSentinel.exe.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, openSync, readSync, closeSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { _electron as electron } from '@playwright/test';

const REPO_ROOT = join(import.meta.dirname, '..', '..');
const APP_EXE = process.env.SENTINEL_GUI_EXE || join(
  process.env.USERPROFILE || '',
  'Documents',
  'AppianSentinel',
  'install',
  'desktop-app',
  'AppianSentinel.exe'
);
const REFERENCE_ZIP = process.env.SENTINEL_GUI_ZIP
  || join(REPO_ROOT, 'Interactions Hub.zip');
const ARTIFACT_DIR = join(REPO_ROOT, 'desktop', 'test-results', 'gui-proof');
const BOOT_TIMEOUT_MS = 180000;
const IMPORT_TIMEOUT_MS = 900000;
const PACKAGE_TIMEOUT_MS = 900000;

const DOWNLOAD_DIR = join(
  process.env.SENTINEL_WORKSPACE_DIR
    || join(process.env.USERPROFILE || '', 'Documents', 'AppianSentinel'),
  'downloads'
);

function log(level, message) {
  console.log(`[${level}] ${message}`);
}

function listDownloads() {
  if (!existsSync(DOWNLOAD_DIR)) return [];
  return readdirSync(DOWNLOAD_DIR).map((name) => join(DOWNLOAD_DIR, name));
}

function isZip(path) {
  const handle = openSync(path, 'r');
  try {
    const header = Buffer.alloc(2);
    readSync(handle, header, 0, 2, 0);
    return header.toString('ascii') === 'PK';
  } finally {
    closeSync(handle);
  }
}

// A rebuilt export must contain Appian content only. Node has no zip reader.
function auditArchive(path) {
  const script = [
    'import json,sys,zipfile',
    'n=zipfile.ZipFile(sys.argv[1]).namelist()',
    'print(json.dumps({"entries":len(n),'
      + '"internal":len([x for x in n if x.startswith(".history")])}))',
  ].join('\n');
  const output = execFileSync(process.env.PYTHON || 'python', ['-c', script, path], {
    encoding: 'utf8',
  });
  return JSON.parse(output.trim());
}

async function waitForNewDownload(before, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const candidate of listDownloads()) {
      // Electron writes a .crdownload placeholder until the file is complete.
      if (!before.has(candidate) && !candidate.endsWith('.crdownload')) {
        return candidate;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return null;
}

function killRunningInstances() {
  // The app holds a single-instance lock; a second launch would just exit.
  const script =
    "Get-CimInstance Win32_Process | Where-Object { $_.Name -match " +
    "'AppianSentinel|appian-sentinel-sidecar' } | ForEach-Object { " +
    'Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }';
  try {
    execFileSync('powershell', ['-NoProfile', '-Command', script], {
      stdio: 'ignore',
    });
  } catch {
    // Nothing was running.
  }
}

async function workbenchWindow(app) {
  // The splash window opens first; wait for the one serving the UI.
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    for (const window of app.windows()) {
      const url = window.url();
      if (url.includes('127.0.0.1:8888') || url.includes('/index.html')) {
        return window;
      }
    }
    await app.waitForEvent('window', { timeout: 5000 }).catch(() => {});
  }
  throw new Error('workbench window never appeared');
}

async function main() {
  for (const [label, path] of [['app', APP_EXE], ['reference ZIP', REFERENCE_ZIP]]) {
    if (!existsSync(path)) {
      log('ERROR', `${label} missing: ${path}`);
      return 2;
    }
  }
  mkdirSync(ARTIFACT_DIR, { recursive: true });
  killRunningInstances();

  const app = await electron.launch({
    executablePath: APP_EXE,
    timeout: BOOT_TIMEOUT_MS,
  });
  try {
    const page = await workbenchWindow(app);
    await page.waitForLoadState('domcontentloaded');
    log('INFO', `workbench window at ${page.url()}`);

    await page.getByText('Connected', { exact: true }).waitFor({ timeout: BOOT_TIMEOUT_MS });
    log('SUCCESS', 'installed GUI reports the connection online');

    const zipMb = (statSync(REFERENCE_ZIP).size / (1024 * 1024)).toFixed(1);
    log('INFO', `importing reference export (${zipMb} MB); this is the slow step`);
    await page.locator('input[type="file"]').first().setInputFiles(REFERENCE_ZIP);

    const objectCount = page.locator('.count-badge').first();
    await objectCount.waitFor({ timeout: IMPORT_TIMEOUT_MS });
    await page.waitForFunction(
      () => {
        const badge = document.querySelector('.count-badge');
        return badge && Number(badge.textContent.trim()) > 0;
      },
      undefined,
      { timeout: IMPORT_TIMEOUT_MS }
    );
    const parsed = Number((await objectCount.textContent()).trim());
    log('SUCCESS', `object explorer shows ${parsed} parsed objects`);

    const firstType = page.getByRole('treeitem').first();
    await firstType.waitFor({ timeout: 60000 });
    await firstType.click();
    const leaf = page.getByRole('treeitem').nth(1);
    await leaf.click();
    await page.locator('.code-editor, textarea').first().waitFor({ timeout: 60000 });
    log('SUCCESS', 'opened an object and rendered its source');

    await page.getByRole('tab', { name: 'Output' }).click();
    await page.getByRole('button', { name: 'Rebuild ZIP' }).click();
    await page
      .getByText('Build artifacts are ready.')
      .waitFor({ timeout: PACKAGE_TIMEOUT_MS });
    log('SUCCESS', 'rebuilt the full ZIP from the installed GUI');

    const downloadButton = page.getByRole('button', { name: 'Download rebuilt ZIP' });
    await downloadButton.waitFor({ timeout: 60000 });
    const before = new Set(listDownloads());
    await downloadButton.click();
    const saved = await waitForNewDownload(before, PACKAGE_TIMEOUT_MS);
    if (!saved) {
      log('ERROR', `no new file appeared in ${DOWNLOAD_DIR}`);
      return 1;
    }
    const savedMb = (statSync(saved).size / (1024 * 1024)).toFixed(1);
    if (!isZip(saved)) {
      log('ERROR', `downloaded file is not a ZIP: ${saved}`);
      return 1;
    }
    log('SUCCESS', `GUI download saved a ${savedMb} MB ZIP to ${saved}`);

    const audit = auditArchive(saved);
    if (audit.internal > 0) {
      log('ERROR', `rebuilt ZIP carries ${audit.internal} internal .history entries`);
      return 1;
    }
    log('SUCCESS', `rebuilt ZIP is import-clean: ${audit.entries} entries, no internal state`);

    log('SUCCESS', 'R31 reference workflow completed through the installed GUI');
    return 0;
  } catch (error) {
    log('ERROR', error instanceof Error ? error.message : String(error));
    return 1;
  } finally {
    // A graceful close can hang on an app holding a loaded codebase, so give it
    // a bounded chance and fall through to the kill either way.
    await Promise.race([
      app.close().catch(() => {}),
      new Promise((resolve) => setTimeout(resolve, 15000)),
    ]);
    killRunningInstances();
  }
}

// Playwright's Electron handle keeps the loop alive after the app is closed, so
// exit on the result rather than waiting for a drain that never comes.
process.exit(await main());
