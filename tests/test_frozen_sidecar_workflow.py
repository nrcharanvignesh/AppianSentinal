"""ZIP upload against the frozen sidecar when the built exe is present."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_SIDECAR = (
    Path.home()
    / "Documents"
    / "AppianSentinel"
    / "install"
    / "desktop-app"
    / "resources"
    / "sidecar"
    / "appian-sentinel-sidecar.exe"
)
_UNPACKED_SIDECAR = (
    REPO_ROOT
    / "desktop"
    / "release"
    / "desktop"
    / "win-unpacked"
    / "resources"
    / "sidecar"
    / "appian-sentinel-sidecar.exe"
)
_env_sidecar = os.environ.get("SENTINEL_SMOKE_SIDECAR_EXE", "").strip()
FROZEN_EXE = Path(_env_sidecar) if _env_sidecar else (
    _DOCS_SIDECAR if _DOCS_SIDECAR.is_file() else _UNPACKED_SIDECAR
)
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "reference_export"
HOST = "127.0.0.1"


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind((HOST, 0))
    port = int(probe.getsockname()[1])
    probe.close()
    return port


def _write_slim_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for item in FIXTURE.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(FIXTURE).as_posix())
        archive.writestr(
            "META-INF/MANIFEST.MF",
            "Manifest-Version: 1.0\r\nAppian-Version: 26.6.0\r\n\r\n",
        )
        archive.writestr("META-INF/export.log", "Success (0):\r\n")


def _multipart_zip(zip_path: Path) -> tuple[bytes, str]:
    boundary = "----sentinelFrozen"
    body = (
        b"--" + boundary.encode("ascii") + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="slim.zip"\r\n'
        b"Content-Type: application/zip\r\n\r\n"
        + zip_path.read_bytes()
        + b"\r\n--"
        + boundary.encode("ascii")
        + b"--\r\n"
    )
    return body, boundary


def _http_json(
    url: str,
    token: str,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout_s: float = 60.0,
    method: str | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"X-Sentinel-Token": token, "X-Session-Id": "frozen-workflow"}
    if content_type:
        headers["Content-Type"] = content_type
    verb = method or ("POST" if data is not None else "GET")
    request = urllib.request.Request(url, data=data, headers=headers, method=verb)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("ascii", errors="replace")
            return int(response.status), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("ascii", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return int(exc.code), body


@pytest.mark.skipif(not FROZEN_EXE.is_file(), reason="frozen sidecar exe is not built")
def test_frozen_sidecar_upload_parses_slim_export(tmp_path: Path) -> None:
    port = _free_port()
    token = str(uuid.uuid4())
    ownership = str(uuid.uuid4())
    zip_path = tmp_path / "slim.zip"
    _write_slim_zip(zip_path)
    env = os.environ.copy()
    env["SENTINEL_HOST"] = HOST
    env["SENTINEL_PORT"] = str(port)
    env["SENTINEL_API_TOKEN"] = token
    env["SENTINEL_DESKTOP_OWNERSHIP_ID"] = ownership
    env["SENTINEL_WORKSPACE_DIR"] = str(tmp_path / "ws")
    proc = subprocess.Popen(
        [str(FROZEN_EXE), "--host", HOST, "--port", str(port)],
        cwd=str(FROZEN_EXE.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                status, body = _http_json(f"http://{HOST}:{port}/api/health", token)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                time.sleep(0.25)
                continue
            if status == 200 and body.get("ownership_id") == ownership:
                break
            time.sleep(0.25)
        else:
            pytest.fail("frozen sidecar did not become healthy")

        payload, boundary = _multipart_zip(zip_path)
        status, upload = _http_json(
            f"http://{HOST}:{port}/api/upload",
            token,
            data=payload,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        assert status == 200, upload
        assert upload.get("objects") == 7

        status, codebase = _http_json(f"http://{HOST}:{port}/api/codebase", token)
        assert status == 200, codebase
        by_type = codebase.get("by_type") or {}
        assert isinstance(by_type, dict)
        assert sum(len(uuids) for uuids in by_type.values()) == 7

        status, packed = _http_json(
            f"http://{HOST}:{port}/api/package",
            token,
            data=b"",
            timeout_s=120.0,
        )
        assert status == 200, packed
        assert packed.get("has_output_zip") is True

        download = urllib.request.Request(
            f"http://{HOST}:{port}/api/download",
            headers={"X-Sentinel-Token": token, "X-Session-Id": "frozen-workflow"},
            method="GET",
        )
        with urllib.request.urlopen(download, timeout=60.0) as response:
            zip_bytes = response.read()
        assert zip_bytes[:2] == b"PK"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
