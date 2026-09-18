from __future__ import annotations

import logging
import os
import re
import tempfile
import zipfile
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

    export_dir = export_dir.resolve()
    manifest_path = export_dir / _MANIFEST_PATH
    manifest = manifest_path.read_bytes() if manifest_path.exists() else b"Manifest-Version: 1.0\n"
    source_log = export_dir / _EXPORT_LOG_PATH
    if source_log.exists() and not modifications:
        export_log = source_log.read_bytes()
    else:
        export_log = _updated_export_log(
            source_log.read_text(encoding="utf-8", errors="replace") if source_log.exists() else "",
            modifications,
        ).encode("utf-8")
    files = [
        path
        for path in sorted(export_dir.rglob("*"))
        if path.is_file() and path.resolve() != output_path
    ]
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zf:
            written = {_MANIFEST_PATH, _EXPORT_LOG_PATH}
            zf.writestr(_MANIFEST_PATH, manifest)
            zf.writestr(_EXPORT_LOG_PATH, export_log)
            for file_path in files:
                arcname = file_path.relative_to(export_dir).as_posix()
                if arcname not in written:
                    zf.write(file_path, arcname)
        with zipfile.ZipFile(temporary, "r") as zf:
            if zf.testzip() is not None:
                raise ValueError("Generated ZIP failed CRC validation")
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)

    logger.info("Built Appian ZIP at %s (%d files)", output_path, len(files))
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


_SUCCESS_LINE = re.compile(r'^(\S+)\s+(\d+)\s+(\S+)\s+"(.+)"$')


def _updated_export_log(existing: str, modifications: list[dict[str, Any]]) -> str:
    """Return a valid Appian Success section without changing the source file."""
    success_lines: list[str] = []
    suffix: list[str] = []
    in_suffix = False
    for line in existing.splitlines():
        if re.match(r"^\d{4}-\d{2}-\d{2}", line) or in_suffix:
            in_suffix = True
            suffix.append(line)
        elif _SUCCESS_LINE.match(line):
            success_lines.append(line)

    indexed = {
        match.group(3): index
        for index, line in enumerate(success_lines)
        if (match := _SUCCESS_LINE.match(line)) is not None
    }
    for modification in modifications:
        object_uuid = str(modification.get("uuid", "")).strip()
        name = str(modification.get("name", "unknown")).replace('"', "'")
        if not object_uuid:
            continue
        if object_uuid in indexed:
            continue
        object_type = str(modification.get("export_type") or modification.get("type", "unknown"))
        numeric_id = int(modification.get("numeric_id", modification.get("id", 0)) or 0)
        entry = f'{object_type} {numeric_id} {object_uuid} "{name}"'
        indexed[object_uuid] = len(success_lines)
        success_lines.append(entry)

    body = [f"Success ({len(success_lines)}):", *success_lines]
    if suffix:
        body.extend(["", *suffix])
    return "\n".join(body) + "\n"

# End of module.
