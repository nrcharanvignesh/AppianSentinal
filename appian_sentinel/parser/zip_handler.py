"""Handle Appian application export ZIP files — extraction, validation, and metadata."""

from __future__ import annotations

import logging
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from appian_sentinel.models.object_registry import official_export_directories
from appian_sentinel.parser.codebase_map import (
    parse_export_log,
    parse_manifest,
    parse_plugins,
)

logger = logging.getLogger(__name__)

_MAX_FILES = 50_000
_MAX_FILE_SIZE = 512 * 1024 * 1024
_MAX_TOTAL_SIZE = 4 * 1024 * 1024 * 1024

# Directories expected in a valid Appian export
_REQUIRED_PATHS = [
    "META-INF/MANIFEST.MF",
    "META-INF/export.log",
]

# Directories that may appear in the export (not all are mandatory)
_KNOWN_DIRECTORIES = official_export_directories()


def extract_appian_zip(zip_path: Path, target_dir: Path) -> Path:
    """Extract an Appian export ZIP to *target_dir* and return the extraction root.

    Parameters
    ----------
    zip_path : Path
        Path to the ``.zip`` file.
    target_dir : Path
        Directory to extract into.  A subdirectory named after the ZIP file
        (minus extension) is created underneath.

    Returns
    -------
    Path
        The directory containing the extracted export (one level down from
        *target_dir* if the ZIP has a single root folder, or *target_dir*
        itself otherwise).

    Raises
    ------
    FileNotFoundError
        If *zip_path* does not exist.
    zipfile.BadZipFile
        If the file is not a valid ZIP.
    """
    zip_path = Path(zip_path)
    target_dir = Path(target_dir)

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP file not found: {zip_path}")

    target_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Extracting %s to %s", zip_path, target_dir)

    with zipfile.ZipFile(zip_path, "r") as zf:
        safe_members = _validated_members(zf)
        zf.extractall(target_dir, members=safe_members)

    # Determine the actual export root
    # If all entries share a common prefix directory, use that
    safe_names = [member.filename.replace("\\", "/") for member in safe_members]
    top_dirs = {name.split("/")[0] for name in safe_names if "/" in name}
    if len(top_dirs) == 1:
        export_root = target_dir / top_dirs.pop()
    else:
        export_root = target_dir

    # Fall back: if META-INF is directly inside target_dir, that's the root
    if not (export_root / "META-INF").exists() and (target_dir / "META-INF").exists():
        export_root = target_dir

    logger.info("Export root: %s", export_root)
    return export_root


def _validated_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Validate archive paths and expansion limits before extraction."""
    members = zf.infolist()
    if len(members) > _MAX_FILES:
        raise ValueError(f"ZIP contains too many entries: {len(members)}")

    total_size = 0
    safe_members: list[zipfile.ZipInfo] = []
    for member in members:
        normalized = member.filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        parts = path.parts

        if (
            path.is_absolute()
            or not parts
            or any(part in ("", ".", "..") for part in parts)
            or ":" in parts[0]
        ):
            raise ValueError(f"Unsafe ZIP entry path: {member.filename}")

        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"ZIP symbolic links are not allowed: {member.filename}")

        if member.file_size > _MAX_FILE_SIZE:
            raise ValueError(f"ZIP entry is too large: {member.filename}")
        total_size += member.file_size
        if total_size > _MAX_TOTAL_SIZE:
            raise ValueError("ZIP expands beyond the 4 GiB safety limit")

        safe_members.append(member)

    return safe_members


def validate_appian_export(export_dir: Path) -> tuple[bool, list[str]]:
    """Validate the structure of an extracted Appian export.

    Parameters
    ----------
    export_dir : Path
        Root of the extracted export (should contain ``META-INF/``).

    Returns
    -------
    tuple[bool, list[str]]
        ``(is_valid, issues)`` where *issues* lists human-readable problems.
    """
    export_dir = Path(export_dir)
    issues: list[str] = []

    if not export_dir.exists():
        return False, [f"Export directory does not exist: {export_dir}"]

    if not export_dir.is_dir():
        return False, [f"Path is not a directory: {export_dir}"]

    # Check required files
    for req in _REQUIRED_PATHS:
        path = export_dir / req
        if not path.exists():
            issues.append(f"Missing required file: {req}")

    # Check for META-INF directory
    meta_dir = export_dir / "META-INF"
    if not meta_dir.exists():
        issues.append("Missing META-INF directory")

    # Check for at least one object directory
    found_object_dirs: list[str] = []
    for dir_name in _KNOWN_DIRECTORIES - {"META-INF"}:
        if (export_dir / dir_name).exists():
            found_object_dirs.append(dir_name)

    if not found_object_dirs:
        issues.append(
            "No object directories found (expected at least one of: "
            + ", ".join(sorted(_KNOWN_DIRECTORIES - {"META-INF"}))
            + ")"
        )

    # Check for application XML
    app_dir = export_dir / "application"
    if app_dir.exists():
        app_files = list(app_dir.glob("*.xml"))
        if not app_files:
            issues.append("application/ directory exists but contains no XML files")
    else:
        issues.append("No application/ directory found (app metadata missing)")

    # Validate export.log is parseable
    export_log = meta_dir / "export.log"
    if export_log.exists():
        uuid_map = parse_export_log(export_log)
        if not uuid_map:
            issues.append("export.log exists but no UUID mappings could be parsed")
        else:
            logger.info("export.log contains %d UUID mappings", len(uuid_map))

    is_valid = len(issues) == 0
    return is_valid, issues


def get_export_metadata(export_dir: Path) -> dict[str, Any]:
    """Read manifest, export.log summary, and plugin list as a metadata dict.

    This is a quick-summary view without parsing every XML — useful for
    inspection before a full ``build_codebase_map`` run.

    Returns
    -------
    dict
        Keys include ``appian_version``, ``created_on``, ``object_count``,
        ``object_types``, ``plugins``, and ``directories``.
    """
    export_dir = Path(export_dir)
    meta_dir = export_dir / "META-INF"

    # Manifest
    manifest = parse_manifest(meta_dir / "MANIFEST.MF")

    # export.log counts
    uuid_map = parse_export_log(meta_dir / "export.log")
    # Count objects by type from the UUID map (group by prefix of export log
    # — the type is *not* in the map, so we count by directory)
    # Re-read the log for type counts:
    type_counts: dict[str, int] = {}
    export_log = meta_dir / "export.log"
    if export_log.exists():
        with open(export_log, encoding="utf-8", errors="replace") as fh:
            import re
            for line in fh:
                line = line.rstrip()
                if line.startswith("Success") or not line.strip():
                    continue
                if re.match(r'^\d{4}-\d{2}-\d{2}', line):
                    break
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    obj_type = parts[0]
                    type_counts[obj_type] = type_counts.get(obj_type, 0) + 1

    # Plugins
    plugins = parse_plugins(meta_dir / "plugins.txt")

    # Directories present
    directories: dict[str, int] = {}
    for dir_name in sorted(_KNOWN_DIRECTORIES):
        d = export_dir / dir_name
        if d.exists() and d.is_dir():
            file_count = sum(1 for _ in d.iterdir() if _.is_file())
            directories[dir_name] = file_count

    return {
        "appian_version": manifest.get("Appian-Version", ""),
        "created_on": manifest.get("Created-On", ""),
        "manifest_version": manifest.get("Manifest-Version", ""),
        "total_objects_in_log": len(uuid_map),
        "object_types": type_counts,
        "plugins": [{"id": p.id, "name": p.name, "version": p.version} for p in plugins],
        "plugin_count": len(plugins),
        "directories": directories,
    }
