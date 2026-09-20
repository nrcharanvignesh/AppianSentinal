"""Render the force-close PowerShell embedded in installer.nsh and parse-check it.

The NSIS macro writes this script line by line, so a syntax error there is
invisible until install time, when the script silently fails and locked files
survive the upgrade.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

NSH_PATH = Path(__file__).resolve().parents[1] / "desktop" / "scripts" / "installer.nsh"
FILE_WRITE = re.compile(r"^\s*FileWrite \$9 `(.*)`\s*$")


def render_script(nsh_text: str) -> str:
    lines: list[str] = []
    for line in nsh_text.splitlines():
        match = FILE_WRITE.match(line)
        if not match:
            continue
        payload = match.group(1)
        payload = payload.replace("$\\r$\\n", "")
        payload = payload.replace("$$", "$")
        lines.append(payload)
    return "\n".join(lines)


def main(nsh_path: Path = NSH_PATH) -> int:
    script = render_script(nsh_path.read_text(encoding="utf-8"))
    if not script.strip():
        print("[ERROR] no FileWrite payload found in installer.nsh")
        return 1
    with tempfile.TemporaryDirectory() as workdir:
        target = Path(workdir) / "force-close.ps1"
        target.write_text(script, encoding="utf-8")
        command = (
            "$errors = $null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{target}', [ref]$null, [ref]$errors); "
            "if ($errors) { $errors | ForEach-Object { $_.Message }; exit 1 }; "
            "Write-Output 'parse ok'"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        print("[ERROR] force-close script has PowerShell syntax errors")
        return 1
    print("[SUCCESS] force-close script parses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else NSH_PATH))
