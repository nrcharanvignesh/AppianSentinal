"""The NSIS force-close script must parse; a syntax error there silently
leaves the previous build installed."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_installer_script  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("powershell") is None, reason="PowerShell is Windows only"
)


def test_force_close_script_parses() -> None:
    assert check_installer_script.main() == 0


def test_checker_rejects_unbalanced_parenthesis(tmp_path: Path) -> None:
    broken = tmp_path / "installer.nsh"
    broken.write_text(
        check_installer_script.NSH_PATH.read_text(encoding="utf-8").replace(
            "CommandLine))){Nuke", "CommandLine)){Nuke"
        ),
        encoding="utf-8",
    )
    assert check_installer_script.main(broken) == 1
