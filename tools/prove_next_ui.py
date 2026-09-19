"""Bind packed Next standalone on 8888 via ELECTRON_RUN_AS_NODE.

Uses an argv list so paths with spaces stay one argument.
Does not open the Electron GUI. Does not prove a clean-machine install.
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
UI_PORT = int(os.environ.get("SENTINEL_UI_PORT", "8888"))
TIMEOUT_S = float(os.environ.get("SENTINEL_UI_TIMEOUT_S", "30"))
REPO_ROOT = Path(__file__).resolve().parents[1]
UNPACKED = REPO_ROOT / "desktop" / "release" / "desktop" / "win-unpacked"
EXE = UNPACKED / "AppianSentinel.exe"
ROOT = UNPACKED / "resources" / "next-standalone"
SERVER = ROOT / "server.js"
NODE_MODULES = ROOT / "node_modules"


def log_info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def log_error(message: str) -> None:
    print(f"[ERROR] {message}", flush=True)


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}", flush=True)


def main() -> int:
    if not EXE.is_file():
        log_error(f"exe missing: {EXE}")
        return 2
    if not SERVER.is_file():
        log_error(f"server.js missing: {SERVER}")
        return 2
    if not NODE_MODULES.is_dir():
        log_error(f"node_modules missing: {NODE_MODULES}")
        return 2
    env = os.environ.copy()
    env["ELECTRON_RUN_AS_NODE"] = "1"
    env["PORT"] = str(UI_PORT)
    env["HOSTNAME"] = HOST
    env["NODE_ENV"] = "production"
    log_file = ROOT / "prove-ui.log"
    handle = log_file.open("w", encoding="ascii", errors="replace")
    proc = subprocess.Popen(
        [str(EXE), str(SERVER)],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + TIMEOUT_S
        last = "no attempt"
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                handle.flush()
                log_error(log_file.read_text(encoding="ascii", errors="replace")[-2000:])
                log_error(f"server exited code={proc.returncode}")
                return 1
            try:
                with urllib.request.urlopen(
                    f"http://{HOST}:{UI_PORT}/", timeout=1.5
                ) as response:
                    if int(response.status) == 200:
                        log_success(f"GET http://{HOST}:{UI_PORT}/ -> 200")
                        return 0
                    last = f"status={response.status}"
            except Exception as exc:
                last = str(exc)
            time.sleep(0.4)
        handle.flush()
        log_error(log_file.read_text(encoding="ascii", errors="replace")[-2000:])
        log_error(f"timeout {TIMEOUT_S}s last={last}")
        return 1
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=8)
        handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
