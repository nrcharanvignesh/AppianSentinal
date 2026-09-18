"""Frozen-friendly sidecar entry point for the desktop app.

Electron spawns the packaged executable built from this module. It passes the
FastAPI *app object* (not an import string) to uvicorn so a PyInstaller
one-file/one-dir build doesn't try to re-import the module in a frozen
context. Host/port come from ``SENTINEL_HOST`` / ``SENTINEL_PORT`` env vars.
"""

from __future__ import annotations

import os

import uvicorn

from appian_sentinel.main import app


def main() -> None:
    host = os.environ.get("SENTINEL_HOST", "127.0.0.1")
    port = int(os.environ.get("SENTINEL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
