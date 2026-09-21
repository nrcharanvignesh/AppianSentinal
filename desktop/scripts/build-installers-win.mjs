import { createHash } from 'node:crypto';
import {
  appendFileSync,
  copyFileSync,
  createReadStream,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const DESKTOP_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = join(DESKTOP_ROOT, '..');
const USE_SHORT_ROOT = REPO_ROOT.length >= 100;
// ponytail: one process-local mirror; add a path hash if parallel reuse is required.
const SHORT_ROOT = join(tmpdir(), 'AppianSentinel-build', `build-${process.pid}`);

function run(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
  if (result.status !== 0) {
    throw new Error(`${command} exited with ${result.status ?? 1}`);
  }
}

function mirrorToShortPath() {
  mkdirSync(dirname(SHORT_ROOT), { recursive: true });
  const args = [
    REPO_ROOT,
    SHORT_ROOT,
    '/MIR',
    '/XD',
    '.git',
    '.next',
    'node_modules',
    'release',
    'dist',
    'build',
    '/NFL',
    '/NDL',
    '/NJH',
    '/NJS',
    '/NC',
    '/NS',
  ].map((value) => (value.includes(' ') ? `"${value}"` : value));
  const result = spawnSync('robocopy', args, {
    cwd: REPO_ROOT,
    stdio: 'inherit',
    shell: true,
  });
  if ((result.status ?? 16) >= 8) {
    throw new Error(`robocopy exited with ${result.status ?? 16}`);
  }
  run('npm', ['ci'], join(SHORT_ROOT, 'desktop'));
  return SHORT_ROOT;
}

async function fileSha256(filePath) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filePath)) hash.update(chunk);
  return hash.digest('hex');
}

function wrapperHeader(bytes, sha256, asarSha256, engineSha256) {
  return `@echo off
setlocal
title Appian Sentinel Install
if not defined SENTINEL_WORKSPACE_DIR set "SENTINEL_WORKSPACE_DIR=%USERPROFILE%\\Documents\\AppianSentinel"
set "SENTINEL_LOG_DIR=%SENTINEL_WORKSPACE_DIR%\\logs"
mkdir "%SENTINEL_LOG_DIR%" >nul 2>&1
set "SENTINEL_INSTALL_DIR=%SENTINEL_WORKSPACE_DIR%\\install\\desktop-app"
set "SENTINEL_SCRATCH=%TEMP%\\AppianSentinel-installer-%RANDOM%-%RANDOM%"
mkdir "%SENTINEL_SCRATCH%" >nul 2>&1
set "_SENTINEL_SELF=%~f0"
set "_SENTINEL_PS1=%SENTINEL_SCRATCH%\\worker.ps1"
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "try { $b=':'+'BUNDLE'; $p='#PS'+'BEGIN'; $on=$false; $w=[IO.StreamWriter]::new($env:_SENTINEL_PS1,$false,[Text.UTF8Encoding]::new($false)); try { foreach($l in [IO.File]::ReadLines($env:_SENTINEL_SELF)){ if($l -eq $b){break}; if($on){$w.WriteLine($l)} elseif($l -eq $p){$on=$true} } } finally { $w.Close() }; if(-not $on){throw 'worker marker not found'} } catch { exit 1 }"
if errorlevel 1 goto :fail
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%_SENTINEL_PS1%"
set "SENTINEL_EXIT=%ERRORLEVEL%"
rmdir /s /q "%SENTINEL_SCRATCH%" >nul 2>&1
exit /b %SENTINEL_EXIT%
:fail
echo Installation failed. See "%SENTINEL_LOG_DIR%".
rmdir /s /q "%SENTINEL_SCRATCH%" >nul 2>&1
exit /b 1
#PSBEGIN
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ExpectedBytes = ${bytes}
$ExpectedSha256 = '${sha256}'
$ExpectedAsarSha256 = '${asarSha256}'
$ExpectedEngineSha256 = '${engineSha256}'
$Self = $env:_SENTINEL_SELF
$Setup = Join-Path $env:SENTINEL_SCRATCH 'AppianSentinel-Setup.exe'
$Bundle = ':' + 'BUNDLE'
$stream = [IO.File]::Open($Setup, [IO.FileMode]::Create, [IO.FileAccess]::Write)
try {
  $inside = $false
  foreach ($line in [IO.File]::ReadLines($Self)) {
    if (-not $inside) {
      if ($line -eq $Bundle) { $inside = $true }
      continue
    }
    if ($line.Length -gt 0) {
      $chunk = [Convert]::FromBase64String($line)
      $stream.Write($chunk, 0, $chunk.Length)
    }
  }
  if (-not $inside) { throw 'bundle marker not found' }
} finally {
  $stream.Dispose()
}
$actual = Get-Item -LiteralPath $Setup
if ($actual.Length -ne $ExpectedBytes) { throw 'setup size mismatch' }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Setup).Hash.ToLowerInvariant()
if ($hash -ne $ExpectedSha256) { throw 'setup hash mismatch' }
New-Item -ItemType Directory -Force -Path $env:SENTINEL_INSTALL_DIR | Out-Null
$env:SENTINEL_NSIS_INSTDIR = $env:SENTINEL_INSTALL_DIR
$process = Start-Process -FilePath $Setup -ArgumentList @('/S', "/D=$env:SENTINEL_INSTALL_DIR") -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "NSIS exited $($process.ExitCode)" }
# NSIS reports success even when a running app locks app.asar and the copy is
# skipped, which silently leaves the previous build installed.
$installedAsar = Join-Path $env:SENTINEL_INSTALL_DIR 'resources\app.asar'
$installedEngine = Join-Path $env:SENTINEL_INSTALL_DIR 'resources\sidecar\appian-sentinel-sidecar.exe'
# NSIS can return before the last copy is visible to Test-Path.
$deadline = [datetime]::UtcNow.AddSeconds(900)
while (
  (-not (Test-Path -LiteralPath $installedAsar) -or
   -not (Test-Path -LiteralPath $installedEngine)) -and
  [datetime]::UtcNow -lt $deadline
) {
  Start-Sleep -Milliseconds 500
}
if (-not (Test-Path -LiteralPath $installedAsar)) { throw 'installed app.asar is missing' }
if (-not (Test-Path -LiteralPath $installedEngine)) { throw 'installed engine is missing' }
$installedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installedAsar).Hash.ToLowerInvariant()
if ($installedHash -ne $ExpectedAsarSha256) { throw 'installed app.asar does not match this build; close Appian Sentinel and install again' }
$installedEngineHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installedEngine).Hash.ToLowerInvariant()
if ($installedEngineHash -ne $ExpectedEngineSha256) { throw 'installed engine does not match this build; close Appian Sentinel and install again' }
Write-Host '[SUCCESS] Appian Sentinel installed'
:BUNDLE
`;
}

async function appendBase64Payload(outputPath, inputPath) {
  let carry = Buffer.alloc(0);
  for await (const chunk of createReadStream(inputPath, { highWaterMark: 3 * 1024 * 1024 })) {
    const data = Buffer.concat([carry, chunk]);
    const complete = data.length - (data.length % 3072);
    for (let offset = 0; offset < complete; offset += 3072) {
      appendFileSync(outputPath, `${data.subarray(offset, offset + 3072).toString('base64')}\n`);
    }
    carry = data.subarray(complete);
  }
  if (carry.length) appendFileSync(outputPath, `${carry.toString('base64')}\n`);
}

let workRoot = REPO_ROOT;
try {
  const wrapOnly = process.argv.includes('--wrap-only');
  if (USE_SHORT_ROOT && !wrapOnly) {
    console.log(`[INFO] mirroring long path to ${SHORT_ROOT}`);
    workRoot = mirrorToShortPath();
  }

  if (!wrapOnly) {
    const python = process.env.PYTHON || 'python';
    run(python, ['-m', 'PyInstaller', 'sidecar.spec', '--noconfirm'], workRoot);
    run(python, ['desktop/scripts/make-icon.py'], workRoot);
    run('npm', ['run', 'build:desktop'], join(workRoot, 'desktop'));
  }

  const releaseDir = join(workRoot, 'desktop', 'release', 'desktop');
  const setupNames = readdirSync(releaseDir).filter((name) => {
    const lower = name.toLowerCase();
    return lower.endsWith('.exe')
      && lower !== 'appiansentinel-setup.exe'
      && !lower.includes('uninstall');
  });
  if (setupNames.length !== 1) {
    throw new Error(
      `expected one newly built NSIS setup under ${releaseDir}; found ${setupNames.length}`
    );
  }
  const setup = join(releaseDir, setupNames[0]);

  const originalRelease = join(DESKTOP_ROOT, 'release', 'desktop');
  mkdirSync(originalRelease, { recursive: true });
  const stableSetup = join(originalRelease, 'AppianSentinel-Setup.exe');
  if (setup !== stableSetup) copyFileSync(setup, stableSetup);

  const outputDir = join(REPO_ROOT, 'installers');
  const output = join(outputDir, 'AppianSentinel-Standalone-Install.cmd');
  mkdirSync(outputDir, { recursive: true });
  const bytes = statSync(stableSetup).size;
  const sha256 = await fileSha256(stableSetup);
  const builtAsar = join(releaseDir, 'win-unpacked', 'resources', 'app.asar');
  if (!existsSync(builtAsar)) throw new Error(`packed app.asar is missing under ${builtAsar}`);
  const asarSha256 = await fileSha256(builtAsar);
  const builtEngine = join(
    releaseDir,
    'win-unpacked',
    'resources',
    'sidecar',
    'appian-sentinel-sidecar.exe',
  );
  if (!existsSync(builtEngine)) throw new Error(`packed engine is missing under ${builtEngine}`);
  const engineSha256 = await fileSha256(builtEngine);
  writeFileSync(
    output,
    wrapperHeader(bytes, sha256, asarSha256, engineSha256),
    'ascii',
  );
  await appendBase64Payload(output, stableSetup);
  console.log(`[SUCCESS] delivery artifact written to ${output}`);
} finally {
  if (USE_SHORT_ROOT) rmSync(SHORT_ROOT, { recursive: true, force: true });
}
