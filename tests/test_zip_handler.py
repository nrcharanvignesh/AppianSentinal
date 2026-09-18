from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from appian_sentinel.parser.zip_handler import extract_appian_zip


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_extract_appian_zip_accepts_valid_root_layout(tmp_path: Path) -> None:
    zip_path = tmp_path / "valid.zip"
    target = tmp_path / "out"
    _write_zip(
        zip_path,
        {
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\n",
            "META-INF/export.log": "Success (0):\n",
            "application/app.xml": "<application />",
        },
    )

    export_root = extract_appian_zip(zip_path, target)

    assert export_root == target
    assert (target / "META-INF" / "MANIFEST.MF").is_file()


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../outside.txt",
        "content/../../outside.txt",
        "..\\outside.txt",
        "/absolute.txt",
        "C:/absolute.txt",
    ],
)
def test_extract_appian_zip_rejects_unsafe_paths(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    zip_path = tmp_path / "unsafe.zip"
    target = tmp_path / "out"
    _write_zip(zip_path, {unsafe_name: "blocked"})

    with pytest.raises(ValueError, match="Unsafe ZIP entry path"):
        extract_appian_zip(zip_path, target)

    assert not (tmp_path / "outside.txt").exists()
