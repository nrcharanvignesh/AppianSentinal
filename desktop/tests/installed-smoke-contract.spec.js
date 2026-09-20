const { test, expect } = require('@playwright/test');
const { spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const SCRIPT = path.join(__dirname, '..', 'scripts', 'installed-app-smoke.ps1');
const POWERSHELL = path.join(
  process.env.SystemRoot || 'C:\\Windows',
  'System32',
  'WindowsPowerShell',
  'v1.0',
  'powershell.exe'
);

function readScript() {
  return fs.readFileSync(SCRIPT, 'ascii');
}

function runSmoke(args, extraEnv) {
  return spawnSync(
    POWERSHELL,
    ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', SCRIPT, ...args],
    {
      encoding: 'utf8',
      env: { ...process.env, ...(extraEnv || {}) },
      windowsHide: true,
    }
  );
}

test.describe('installed-app smoke contract', () => {
  test('script is ASCII PowerShell with valid syntax', () => {
    const text = fs.readFileSync(SCRIPT);
    expect(text.includes(0)).toBeFalsy();
    const source = text.toString('utf8');
    expect(source).toMatch(/^[\t\n\r\x20-\x7e]*$/);
    const escaped = SCRIPT.replace(/'/g, "''");
    const command = [
      '$tokens=$null;$errors=$null;',
      '[void][Management.Automation.Language.Parser]::ParseFile(',
      `'${escaped}',[ref]$tokens,[ref]$errors);`,
      'if($errors.Count){$errors|ForEach-Object{Write-Error $_.Message};exit 1}',
    ].join('');
    const parsed = spawnSync(
      POWERSHELL,
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
      { encoding: 'utf8', windowsHide: true }
    );
    expect(parsed.status, parsed.stdout + parsed.stderr).toBe(0);
  });

  test('locates installed exe, ports, asar hash, maximize, logs, and owned cleanup', () => {
    const text = readScript();
    expect(text).toContain('[Parameter(Mandatory = $true)]');
    expect(text).toContain('$ExpectedAsarSha256');
    expect(text).toContain("Join-Path $env:USERPROFILE 'Documents\\AppianSentinel'");
    expect(text).toContain("Join-Path (Get-WorkspaceRoot) 'install\\desktop-app'");
    expect(text).toContain("Join-Path $install 'AppianSentinel.exe'");
    expect(text).toContain("Join-Path $install 'resources\\app.asar'");
    expect(text).toContain('SENTINEL_WORKSPACE_DIR');
    expect(text).toContain('Get-FileHash -LiteralPath $asar -Algorithm SHA256');
    expect(text).toContain('stale app.asar');
    expect(text).toContain('skipping launch because identity gates failed');
    expect(text).toMatch(/Get-PortListeners 7842/);
    expect(text).toMatch(/Get-PortListeners 8888/);
    expect(text).toContain('appian-sentinel-sidecar');
    expect(text).toContain('server\\.js');
    expect(text).toContain('ShowWindow');
    expect(text).toContain('launching installed exe maximized');
    expect(text).toContain('RedirectStandardOutput');
    expect(text).toContain('desktop.log');
    expect(text).toContain('BaselineProcessIds');
    expect(text).toContain('if ($p.CreationDate -lt $owned[$parentPid].CreationDate) { continue }');
    expect(text).toContain('Stop-OwnedProcesses');
    expect(text).toContain('} finally {');
    expect(text).not.toMatch(/Get-Process\s+-Name\s+['"]AppianSentinel/i);
    expect(text).not.toContain('TestingToolkit');
    expect(text).not.toContain('Invoke-SilentInstall');
    expect(text).not.toContain('taskkill.exe" /F /T /PID');
  });

  test('fails closed on missing exe without launching', () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'sentinel-smoke-missing-'));
    const hash = 'a'.repeat(64);
    const result = runSmoke([
      '-ExpectedAsarSha256', hash,
      '-InstallDir', scratch,
      '-WorkspaceDir', scratch,
    ]);
    const output = `${result.stdout || ''}\n${result.stderr || ''}`;
    expect(result.status).not.toBe(0);
    expect(output).toMatch(/installed exe missing/i);
    expect(output).toMatch(/skipping launch because identity gates failed/);
    expect(output).not.toMatch(/launching installed exe maximized/);
  });

  test('fails on stale app.asar before launch', () => {
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'sentinel-smoke-stale-'));
    const resources = path.join(scratch, 'resources');
    fs.mkdirSync(resources);
    fs.writeFileSync(path.join(scratch, 'AppianSentinel.exe'), 'not-an-exe', 'ascii');
    const asarPath = path.join(resources, 'app.asar');
    fs.writeFileSync(asarPath, 'stale-asar-bytes', 'ascii');
    const actual = createHash('sha256').update('stale-asar-bytes').digest('hex');
    const expected = 'b'.repeat(64);
    expect(actual).not.toBe(expected);
    const result = runSmoke([
      '-ExpectedAsarSha256', expected,
      '-InstallDir', scratch,
      '-WorkspaceDir', scratch,
    ]);
    const output = `${result.stdout || ''}\n${result.stderr || ''}`;
    expect(result.status).not.toBe(0);
    expect(output).toMatch(/stale app\.asar/i);
    expect(output).toContain(actual);
    expect(output).toContain(expected);
    expect(output).toMatch(/skipping launch because identity gates failed/);
    expect(output).not.toMatch(/launching installed exe maximized/);
  });
});
