"""Inventory the standalone .cmd payload without running the installer.

Appian Sentinel ships a frozen PyInstaller sidecar plus Electron and a Next
standalone server. It does not ship nuget CPython or offline wheels; those
Testing Toolkit pieces are not required at runtime. This script fails if the
packaged runtime pieces are missing, or if the wrapper hash does not match
the extracted NSIS exe.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CMD = REPO_ROOT / "installers" / "AppianSentinel-Standalone-Install.cmd"
BUNDLE_MARKER = ":BUNDLE"
PS_MARKER = "#PSBEGIN"
HEADER_BYTES_RE = re.compile(r"\$ExpectedBytes\s*=\s*(\d+)")
HEADER_SHA_RE = re.compile(r"\$ExpectedSha256\s*=\s*'([0-9a-f]+)'", re.IGNORECASE)

REQUIRED_ARCHIVE_SUBSTRINGS: tuple[str, ...] = (
    "AppianSentinel.exe",
    "resources/app.asar",
    "resources/next-standalone/server.js",
    "resources/next-standalone/node_modules",
    "resources/sidecar/appian-sentinel-sidecar.exe",
)


def log_info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def log_warn(message: str) -> None:
    print(f"[WARN] {message}", flush=True)


def log_error(message: str) -> None:
    print(f"[ERROR] {message}", flush=True)


def log_success(message: str) -> None:
    print(f"[SUCCESS] {message}", flush=True)


def _parse_header(cmd_path: Path) -> tuple[int, str]:
    expected_bytes: int | None = None
    expected_sha: str | None = None
    with cmd_path.open("r", encoding="ascii", errors="strict") as handle:
        for line in handle:
            stripped = line.rstrip("\r\n")
            if stripped == PS_MARKER:
                continue
            if stripped == BUNDLE_MARKER:
                break
            match_bytes = HEADER_BYTES_RE.search(stripped)
            if match_bytes:
                expected_bytes = int(match_bytes.group(1))
            match_sha = HEADER_SHA_RE.search(stripped)
            if match_sha:
                expected_sha = match_sha.group(1).lower()
    if expected_bytes is None or expected_sha is None:
        raise RuntimeError("wrapper header is missing ExpectedBytes or ExpectedSha256")
    return expected_bytes, expected_sha


def _extract_setup(cmd_path: Path, setup_path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    written = 0
    inside = False
    with cmd_path.open("r", encoding="ascii", errors="strict") as handle:
        with setup_path.open("wb") as out:
            for line in handle:
                stripped = line.rstrip("\r\n")
                if not inside:
                    if stripped == BUNDLE_MARKER:
                        inside = True
                    continue
                if not stripped:
                    continue
                chunk = base64.b64decode(stripped, validate=True)
                out.write(chunk)
                digest.update(chunk)
                written += len(chunk)
    if not inside:
        raise RuntimeError("bundle marker not found")
    return written, digest.hexdigest()


def _find_7z() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "electron-builder" / "Cache"
    candidates: list[Path] = []
    if local.is_dir():
        candidates.extend(local.rglob("7za.exe"))
        candidates.extend(local.rglob("7z.exe"))
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if not candidates:
        raise FileNotFoundError("7z is not available; cannot list the NSIS archive")
    return candidates[0]


_BA_LINE = re.compile(r"[AD.]{5}\s+\d+\s+\d+\s+(.+)$")


def _list_archive(seven_zip: Path, setup_path: Path) -> list[str]:
    result = subprocess.run(
        [str(seven_zip), "l", "-ba", str(setup_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"7z list failed ({result.returncode}): {result.stderr[-400:]}")
    names: list[str] = []
    for line in result.stdout.splitlines():
        match = _BA_LINE.search(line)
        if match:
            names.append(match.group(1).replace("\\", "/"))
    return names


def _missing(names: Iterable[str], required: tuple[str, ...]) -> list[str]:
    lowered = [item.lower() for item in names]
    missing: list[str] = []
    for needle in required:
        target = needle.lower()
        if not any(target in item or item.endswith(target) for item in lowered):
            missing.append(needle)
    return missing


def main() -> int:
    cmd_path = Path(os.environ.get("SENTINEL_INSTALLER_CMD", DEFAULT_CMD))
    if not cmd_path.is_file():
        log_error(f"installer not found: {cmd_path}")
        return 1

    log_info(f"inspecting {cmd_path} ({cmd_path.stat().st_size} bytes)")
    expected_bytes, expected_sha = _parse_header(cmd_path)
    log_info(f"header bytes={expected_bytes} sha256={expected_sha}")

    scratch = Path(tempfile.mkdtemp(prefix="sentinel-payload-"))
    setup_path = scratch / "AppianSentinel-Setup.exe"
    try:
        written, actual_sha = _extract_setup(cmd_path, setup_path)
        log_info(f"extracted setup {written} bytes sha256={actual_sha}")
        if written != expected_bytes:
            log_error(f"size mismatch: header {expected_bytes} extracted {written}")
            return 1
        if actual_sha != expected_sha:
            log_error("sha256 mismatch between header and extracted setup")
            return 1

        seven_zip = _find_7z()
        log_info(f"listing NSIS archive with {seven_zip}")
        names = _list_archive(seven_zip, setup_path)
        log_info(f"archive entries={len(names)}")

        lowered_names = [name.lower() for name in names]
        python_hits = [name for name in lowered_names if name.endswith("python.exe")]
        wheel_hits = [name for name in names if name.lower().endswith(".whl")]
        if python_hits or wheel_hits:
            log_warn(
                "nuget CPython or wheels present; this app is designed around a frozen sidecar"
            )
        else:
            log_info("no nuget CPython and no wheels (expected: sidecar is frozen)")

        missing = _missing(names, REQUIRED_ARCHIVE_SUBSTRINGS)
        if missing:
            for item in missing:
                log_error(f"missing runtime piece: {item}")
            return 1
        for item in REQUIRED_ARCHIVE_SUBSTRINGS:
            log_info(f"present: {item}")

        log_success("payload inventory passed")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        if scratch.exists():
            log_error(f"could not remove {scratch}")
            return 1
        log_info(f"removed temp dir {scratch}")


if __name__ == "__main__":
    sys.exit(main())
