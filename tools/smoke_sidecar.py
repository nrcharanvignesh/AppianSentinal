"""Headless sidecar smoke: loopback health, ownership, and token gate."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, TextIO

HOST = "127.0.0.1"
PORT = int(os.environ.get("SENTINEL_AGENT_PORT", "7842"))
BASE_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"
STATUS_URL = f"{BASE_URL}/api/status"
POLL_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.25
PORT_WAIT_S = 60.0
SHUTDOWN_WAIT_S = 8.0


def log_info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def log_error(message: str) -> None:
    print(f"[ERROR] {message}", flush=True)


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}", flush=True)


def port_is_free(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        return probe.connect_ex((host, port)) != 0
    finally:
        probe.close()


def wait_for_free_port(host: str, port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if port_is_free(host, port):
            log_info(f"{host}:{port} is free")
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"{host}:{port} still in use after {timeout_s}s; cannot start owned uvicorn"
    )


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout_s: float = 3.0,
) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("ascii", errors="replace")
            return int(response.status), _parse_body(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("ascii", errors="replace")
        return int(exc.code), _parse_body(raw)


def _parse_body(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def wait_for_health(ownership_id: str, proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    last_error = "no attempt"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"uvicorn exited before health became ready code={proc.returncode}"
            )
        try:
            status, body = http_get(HEALTH_URL)
            if (
                status == 200
                and isinstance(body, dict)
                and body.get("ownership_id") == ownership_id
            ):
                log_info(f"GET /api/health -> 200 ownership_id={ownership_id}")
                return
            last_error = f"status={status} body={body!r}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"health poll failed after {POLL_TIMEOUT_S}s: {last_error}")


def shutdown_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        log_info(f"uvicorn already exited code={proc.returncode}")
        return
    log_info("stopping uvicorn")
    proc.terminate()
    try:
        proc.wait(timeout=SHUTDOWN_WAIT_S)
    except subprocess.TimeoutExpired:
        log_info("terminate timed out; killing uvicorn")
        proc.kill()
        proc.wait(timeout=5.0)
    log_info(f"uvicorn stopped code={proc.returncode}")


def dump_log(log_path: Path) -> None:
    if not log_path.is_file():
        return
    tail = log_path.read_text(encoding="ascii", errors="replace")[-2000:]
    if tail.strip():
        log_error(tail)


def sidecar_command(repo_root: Path) -> list[str]:
    """Frozen exe when SENTINEL_SMOKE_SIDECAR_EXE is set, else source uvicorn."""
    frozen = os.environ.get("SENTINEL_SMOKE_SIDECAR_EXE", "").strip()
    if frozen:
        exe = Path(frozen)
        if not exe.is_file():
            raise RuntimeError(f"frozen sidecar not found: {exe}")
        return [str(exe), "--host", HOST, "--port", str(PORT)]
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "appian_sentinel.main:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]


def start_uvicorn(
    repo_root: Path,
    env: dict[str, str],
    log_handle: TextIO,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        sidecar_command(repo_root),
        cwd=str(repo_root),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )


def main() -> int:
    ownership_id = str(uuid.uuid4())
    token = str(uuid.uuid4())
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["SENTINEL_DESKTOP_OWNERSHIP_ID"] = ownership_id
    env["SENTINEL_API_TOKEN"] = token
    env["SENTINEL_HOST"] = HOST
    env["SENTINEL_PORT"] = str(PORT)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        os.pathsep.join([str(repo_root), existing_pythonpath])
        if existing_pythonpath
        else str(repo_root)
    )

    log_path = repo_root / "tools" / "smoke_sidecar.uvicorn.log"
    log_handle = log_path.open("w", encoding="ascii", errors="replace")
    proc: subprocess.Popen[str] | None = None
    try:
        if not port_is_free(HOST, PORT):
            log_info(f"{HOST}:{PORT} busy; waiting for exclusive bind")
            wait_for_free_port(HOST, PORT, PORT_WAIT_S)
        log_info(f"starting {sidecar_command(repo_root)[0]} on {HOST}:{PORT}")
        proc = start_uvicorn(repo_root, env, log_handle)
        wait_for_health(ownership_id, proc)
        unauth_status, unauth_body = http_get(STATUS_URL)
        if unauth_status not in (401, 403):
            raise RuntimeError(
                "GET /api/status without X-Sentinel-Token expected 401/403, "
                f"got {unauth_status} body={unauth_body!r}"
            )
        log_info(f"GET /api/status without token -> {unauth_status}")
        auth_status, auth_body = http_get(
            STATUS_URL,
            headers={"X-Sentinel-Token": token},
        )
        if auth_status != 200:
            raise RuntimeError(
                "GET /api/status with X-Sentinel-Token expected 200, "
                f"got {auth_status} body={auth_body!r}"
            )
        log_info("GET /api/status with token -> 200")
        log_success("sidecar smoke passed")
        return 0
    except Exception as exc:
        log_error(str(exc))
        if proc is not None and proc.poll() is not None:
            log_error(f"uvicorn exited early code={proc.returncode}")
        log_handle.flush()
        dump_log(log_path)
        return 1
    finally:
        if proc is not None:
            shutdown_process(proc)
        log_handle.close()
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
