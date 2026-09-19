// Stands in for the Electron main process in the Job Object teardown proof.
// Claims the job, spawns a stand-in sidecar, reports both PIDs, then blocks.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';

const require = createRequire(import.meta.url);
const { startWindowsJobOwner } = require('../electron/windows-job.js');

const job = await startWindowsJobOwner(tmpdir());

// A child that ignores termination signals, so only the job can end it.
const child = spawn(
  process.execPath,
  ['-e', 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000);'],
  { stdio: 'ignore', windowsHide: true }
);

console.log(JSON.stringify({
  owner: process.pid,
  child: child.pid,
  assigned: job ? job.assigned : false,
}));

setInterval(() => {}, 1000);
