// Prove the "stop the sidecar safely" claim: when the owning process dies
// without a chance to clean up, the Windows Job Object must still reap its
// children. The owner is killed with taskkill /F and deliberately without /T,
// so nothing but the job can end the child.
import { execFileSync, spawn } from 'node:child_process';
import { join } from 'node:path';

const KILL_TIMEOUT_MS = 20000;
const POLL_MS = 200;
const START_TIMEOUT_MS = 30000;

function log(level, message) {
  console.log(`[${level}] ${message}`);
}

function isRunning(pid) {
  try {
    // Signal 0 tests for existence without delivering anything.
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function startFixture() {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.execPath,
      [join(import.meta.dirname, 'job-object-fixture.mjs')],
      { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true }
    );
    let out = '';
    let err = '';
    const timer = setTimeout(
      () => reject(new Error(`fixture never reported: ${err.trim()}`)),
      START_TIMEOUT_MS
    );
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8');
      const line = out.split('\n').find((candidate) => candidate.trim().startsWith('{'));
      if (line) {
        clearTimeout(timer);
        resolve(JSON.parse(line));
      }
    });
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8');
    });
    child.once('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`fixture exited early (${code}): ${err.trim()}`));
    });
  });
}

async function waitForExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isRunning(pid)) return true;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
  return false;
}

function kill(pid, tree) {
  try {
    execFileSync('taskkill', tree ? ['/PID', String(pid), '/T', '/F'] : ['/PID', String(pid), '/F'], {
      stdio: 'ignore',
    });
  } catch {
    // Already gone.
  }
}

async function main() {
  if (process.platform !== 'win32') {
    log('INFO', 'not Windows; the Job Object claim does not apply');
    return 0;
  }

  const { owner, child, assigned } = await startFixture();
  log('INFO', `owner pid ${owner}, child pid ${child}, assigned=${assigned}`);

  if (!isRunning(child)) {
    log('ERROR', 'child was not running before the kill; the proof is invalid');
    kill(owner, true);
    return 1;
  }

  if (!assigned) {
    // Do not pretend a nested-job fallback proves the kernel guarantee.
    log('WARN', 'a nested parent job blocked assignment, so this environment '
      + 'cannot prove the guarantee; rerun outside a job-owning shell');
    kill(owner, true);
    return 3;
  }

  // /F without /T: the job is the only thing that can reap the child.
  kill(owner, false);

  if (!(await waitForExit(owner, KILL_TIMEOUT_MS))) {
    log('ERROR', 'owner survived taskkill /F');
    kill(owner, true);
    return 1;
  }
  log('SUCCESS', 'owner terminated without cleanup');

  if (!(await waitForExit(child, KILL_TIMEOUT_MS))) {
    log('ERROR', `child ${child} outlived its owner: the Job Object did not reap it`);
    kill(child, true);
    return 1;
  }

  log('SUCCESS', 'child died with its owner: Job Object teardown holds');
  return 0;
}

process.exit(await main());
