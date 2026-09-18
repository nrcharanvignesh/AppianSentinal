"""Install runtime + dev extras without invoking the pyproject build backend.

`pip install -e .` currently fails: pyproject.toml names
`setuptools.backends._legacy:_Backend`, which setuptools 81 does not provide.
This script installs the declared dependencies so pytest and ruff can run from
the repository root (the `appian_sentinel` package is imported from source).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    raise SystemExit("[ERROR] Python 3.11+ is required")

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    packages: list[str] = list(project["dependencies"])
    packages.extend(project["optional-dependencies"]["dev"])
    command = [sys.executable, "-m", "pip", "install", *packages]
    print("[INFO] " + " ".join(command), flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
