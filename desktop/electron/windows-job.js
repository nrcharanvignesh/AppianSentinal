'use strict';

const { spawn } = require('node:child_process');
const { existsSync, readFileSync, rmSync } = require('node:fs');
const { randomUUID } = require('node:crypto');
const path = require('node:path');

const READY_TIMEOUT_MS = 15000;
const READY_POLL_MS = 25;

const JOB_HELPER = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class AppianSentinelJob {
  const uint PROCESS_TERMINATE = 0x0001;
  const uint PROCESS_SET_QUOTA = 0x0100;
  const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
  const uint SYNCHRONIZE = 0x00100000;
  const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
  const int JobObjectExtendedLimitInformation = 9;
  const uint INFINITE = 0xffffffff;

  [StructLayout(LayoutKind.Sequential)]
  struct IO_COUNTERS {
    public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
    public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
  }

  [StructLayout(LayoutKind.Sequential)]
  struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
    public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
    public uint LimitFlags;
    public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
    public uint ActiveProcessLimit;
    public UIntPtr Affinity;
    public uint PriorityClass, SchedulingClass;
  }

  [StructLayout(LayoutKind.Sequential)]
  struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
    public IO_COUNTERS IoInfo;
    public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed;
    public UIntPtr PeakJobMemoryUsed;
  }

  [DllImport("kernel32.dll", SetLastError = true)]
  static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern bool QueryFullProcessImageName(
    IntPtr process, uint flags, System.Text.StringBuilder path, ref uint size);
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern bool GetProcessTimes(
    IntPtr process, out long created, out long exited, out long kernel, out long user);
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern IntPtr CreateJobObject(IntPtr attributes, string name);
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern bool SetInformationJobObject(
    IntPtr job, int infoClass, IntPtr info, uint length);
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
  [DllImport("kernel32.dll")]
  static extern bool CloseHandle(IntPtr handle);

  static void Win32(string operation) {
    throw new Win32Exception(Marshal.GetLastWin32Error(), operation);
  }

  public static long Supervise(
    uint pid, string expectedImage, long expectedStartedUnixMs, string readyPath) {
    IntPtr process = OpenProcess(
      PROCESS_TERMINATE | PROCESS_SET_QUOTA |
      PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, false, pid);
    if (process == IntPtr.Zero) Win32("OpenProcess");
    IntPtr job = IntPtr.Zero;
    try {
      var image = new System.Text.StringBuilder(32768);
      uint imageLength = (uint)image.Capacity;
      if (!QueryFullProcessImageName(process, 0, image, ref imageLength)) {
        Win32("QueryFullProcessImageName");
      }
      if (!String.Equals(
        System.IO.Path.GetFullPath(image.ToString()),
        System.IO.Path.GetFullPath(expectedImage),
        StringComparison.OrdinalIgnoreCase)) {
        throw new InvalidOperationException("owner image identity mismatch");
      }
      long created, exited, kernel, user;
      if (!GetProcessTimes(process, out created, out exited, out kernel, out user)) {
        Win32("GetProcessTimes");
      }
      long startedUnixMs = (created - 116444736000000000L) / 10000L;
      // ponytail: 30s startup ceiling; use a native creation-time lookup if needed.
      if (Math.Abs(startedUnixMs - expectedStartedUnixMs) > 30000L) {
        throw new InvalidOperationException("owner creation identity mismatch");
      }
      job = CreateJobObject(IntPtr.Zero, null);
      if (job == IntPtr.Zero) Win32("CreateJobObject");
      var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
      limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
      int size = Marshal.SizeOf(limits);
      IntPtr data = Marshal.AllocHGlobal(size);
      try {
        Marshal.StructureToPtr(limits, data, false);
        if (!SetInformationJobObject(
          job, JobObjectExtendedLimitInformation, data, (uint)size)) {
          Win32("SetInformationJobObject");
        }
      } finally {
        Marshal.FreeHGlobal(data);
      }
      if (!AssignProcessToJobObject(job, process)) {
        CloseHandle(job);
        job = IntPtr.Zero;
        // Nested parent jobs cannot be reassigned; Electron still boots.
        System.IO.File.WriteAllText(
          readyPath, "READY|" + created.ToString(), System.Text.Encoding.ASCII);
        WaitForSingleObject(process, INFINITE);
        return created;
      }
      System.IO.File.WriteAllText(
        readyPath, "READY|" + created.ToString(), System.Text.Encoding.ASCII);
      WaitForSingleObject(process, INFINITE);
      return created;
    } finally {
      if (job != IntPtr.Zero) CloseHandle(job);
      CloseHandle(process);
    }
  }
}
'@
[void][AppianSentinelJob]::Supervise(
  [uint32]$env:SENTINEL_JOB_OWNER_PID,
  $env:SENTINEL_JOB_OWNER_IMAGE,
  [int64]$env:SENTINEL_JOB_OWNER_STARTED_UNIX_MS,
  $env:SENTINEL_JOB_READY_PATH)
`;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function startWindowsJobOwner(readyDir) {
  if (process.platform !== 'win32') return null;
  const readyPath = path.join(
    readyDir,
    `appian-sentinel-job-${process.pid}-${randomUUID()}.ready`
  );
  const powershell = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );
  const helper = spawn(
    powershell,
    [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-EncodedCommand',
      Buffer.from(JOB_HELPER, 'utf16le').toString('base64'),
    ],
    {
      env: {
        ...process.env,
        SENTINEL_JOB_OWNER_PID: String(process.pid),
        SENTINEL_JOB_OWNER_IMAGE: process.execPath,
        SENTINEL_JOB_OWNER_STARTED_UNIX_MS: String(
          Math.round(Date.now() - process.uptime() * 1000)
        ),
        SENTINEL_JOB_READY_PATH: readyPath,
      },
      stdio: ['ignore', 'ignore', 'pipe'],
      windowsHide: true,
    }
  );
  let helperError = '';
  helper.stderr?.on('data', (chunk) => {
    helperError = (helperError + chunk.toString('utf8')).slice(-4096);
  });
  helper.unref();

  const deadline = Date.now() + READY_TIMEOUT_MS;
  try {
    while (Date.now() < deadline) {
      if (existsSync(readyPath)) {
        const [status, creation] = readFileSync(readyPath, 'ascii').trim().split('|');
        if (status !== 'READY' || !/^\d+$/.test(creation || '')) {
          throw new Error('Windows Job Object helper returned invalid identity');
        }
        return { helper, ownerCreationFileTime: creation };
      }
      if (helper.exitCode !== null) {
        const detail = helperError.trim();
        throw new Error(
          `Windows Job Object helper exited before assignment (${helper.exitCode})` +
            (detail ? `: ${detail}` : '')
        );
      }
      await delay(READY_POLL_MS);
    }
    throw new Error('Windows Job Object assignment timed out');
  } finally {
    rmSync(readyPath, { force: true });
  }
}

module.exports = { startWindowsJobOwner };
