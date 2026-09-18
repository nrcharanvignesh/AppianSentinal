from __future__ import annotations

import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Files that Appian expects at the root of a valid import ZIP.
_REQUIRED_ROOTS = {"META-INF"}
_MANIFEST_PATH = "META-INF/MANIFEST.MF"
_EXPORT_LOG_PATH = "META-INF/export.log"


def build_appian_zip(
    export_dir: Path,
    output_path: Path,
    modifications: list[dict[str, Any]],
) -> Path:
    """Re-package an extracted Appian export directory into an import-ready ZIP.

    Parameters
    ----------
    export_dir:
        Root of the extracted export (the directory that contains ``META-INF/``
        and the object-type folders).
    output_path:
        Desired path for the output ``.zip`` file.  Parent directories are
        created automatically.
    modifications:
        List of object dicts produced by the orchestrator.  Each dict is
        expected to carry at least ``name``, ``uuid``, ``type``, and
        ``action`` (``"create"`` | ``"modify"``).  The builder uses this
        list only to update ``export.log`` -- the actual XML files should
        already have been written into *export_dir* by the generator.

    Returns
    -------
    Path
        The absolute path to the created ZIP file.
    """
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Update META-INF files before zipping.
    _update_manifest(export_dir)
    _update_export_log(export_dir, modifications)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(export_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(export_dir).as_posix()
                zf.write(file_path, arcname)

    logger.info("Built Appian ZIP at %s (%d files)", output_path, _count_files(export_dir))
    return output_path


def validate_zip_structure(zip_path: Path) -> tuple[bool, list[str]]:
    """Validate that *zip_path* has a plausible Appian import structure.

    Returns ``(is_valid, issues)`` where *issues* is a list of human-readable
    warning strings.  ``is_valid`` is ``False`` only when the ZIP is
    fundamentally broken (missing ``META-INF``, etc.).
    """
    issues: list[str] = []
    if not zip_path.exists():
        return False, ["ZIP file does not exist."]

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return False, ["File is not a valid ZIP archive."]

    if not names:
        return False, ["ZIP archive is empty."]

    # Check for META-INF
    has_meta = any(n.startswith("META-INF/") for n in names)
    if not has_meta:
        issues.append("Missing META-INF/ directory.")

    has_manifest = _MANIFEST_PATH in names
    if not has_manifest:
        issues.append(f"Missing {_MANIFEST_PATH}.")

    # Warn about unexpectedly large files (> 50 MB)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.file_size > 50 * 1024 * 1024:
                issues.append(f"Large file: {info.filename} ({info.file_size // (1024*1024)} MB)")

    is_valid = has_meta and has_manifest
    return is_valid, issues


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _update_manifest(export_dir: Path) -> None:
    """Write / update the ``MANIFEST.MF`` with a current timestamp."""
    meta_dir = export_dir / "META-INF"
    meta_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = meta_dir / "MANIFEST.MF"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        "Manifest-Version: 1.0",
        f"Export-Date: {now}",
        "Created-By: AppianSentinel",
        "",
    ]

    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def _update_export_log(export_dir: Path, modifications: list[dict[str, Any]]) -> None:
    """Append entries for newly created objects to ``export.log``."""
    meta_dir = export_dir / "META-INF"
    meta_dir.mkdir(parents=True, exist_ok=True)
    log_path = meta_dir / "export.log"

    existing_content = ""
    if log_path.exists():
        existing_content = log_path.read_text(encoding="utf-8")

    new_entries: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for mod in modifications:
        name = mod.get("name", "unknown")
        obj_uuid = mod.get("uuid", "")
        obj_type = mod.get("type", "unknown")
        action = mod.get("action", "modify")
        entry = f"[{now}] {action.upper()} {obj_type} \"{name}\" (uuid={obj_uuid})"
        new_entries.append(entry)

    if new_entries:
        updated = existing_content.rstrip("\n") + "\n" + "\n".join(new_entries) + "\n"
        log_path.write_text(updated, encoding="utf-8")


def _count_files(directory: Path) -> int:
    return sum(1 for _ in directory.rglob("*") if _.is_file())
