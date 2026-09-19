"""Launch packed AppianSentinel.exe and require loopback 7842 + 8888.

Does not prove a clean-machine GUI install. Use after win-unpacked exists.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
AGENT_PORT = int(os.environ.get("SENTINEL_AGENT_PORT", "7842"))
UI_PORT = int(os.environ.get("SENTINEL_UI_PORT", "8888"))
TIMEOUT_S = float(os.environ.get("SENTINEL_BOOT_TIMEOUT_S", "90"))
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = (
    REPO_ROOT
    / "desktop"
    / "release"
    / "desktop"
    / "win-unpacked"
    / "AppianSentinel.exe"
)


def log_info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def log_error(message: str) -> None:
    print(f"[ERROR] {message}", flush=True)


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}", flush=True)


def port_open(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.4)
    try:
        return probe.connect_ex((HOST, port)) == 0
    finally:
        probe.close()


def health_ok() -> bool:
    url = f"http://{HOST}:{AGENT_PORT}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            return int(response.status) == 200
    except Exception:
        return False


def kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        capture_output=True,
        check=False,
    )


def dump_desktop_log(workspace: Path) -> None:
    log_path = workspace / "logs" / "desktop.log"
    if not log_path.is_file():
        log_error("desktop.log missing")
        return
    tail = log_path.read_text(encoding="ascii", errors="replace")[-3000:]
    log_error(tail)


def main() -> int:
    exe = Path(os.environ.get("SENTINEL_DESKTOP_EXE", str(DEFAULT_EXE)))
    if not exe.is_file():
        log_error(f"exe missing: {exe}")
        return 2
    workspace = Path(os.environ.get("SENTINEL_WORKSPACE_DIR", str(REPO_ROOT / ".sentinel-boot-proof")))
    workspace.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["SENTINEL_WORKSPACE_DIR"] = str(workspace)
    env["SENTINEL_AGENT_PORT"] = str(AGENT_PORT)
    env["SENTINEL_UI_PORT"] = str(UI_PORT)
    log_info(f"starting {exe} workspace={workspace}")
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + TIMEOUT_S
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                dump_desktop_log(workspace)
                log_error(f"exe exited early code={proc.returncode}")
                return 1
            if health_ok() and port_open(UI_PORT):
                log_success(f"health 200 on {AGENT_PORT} and UI bound on {UI_PORT}")
                return 0
            time.sleep(0.5)
        dump_desktop_log(workspace)
        log_error(
            f"timeout {TIMEOUT_S}s health={health_ok()} ui={port_open(UI_PORT)}"
        )
        return 1
    finally:
        if proc.poll() is None:
            kill_tree(proc.pid)
        else:
            kill_tree(proc.pid)


if __name__ == "__main__":
    raise SystemExit(main())
