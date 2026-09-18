"""Build a *patch* Appian import ZIP containing **only** the objects a
requirement touched, not the whole application.

This is the deliverable the Sentinel workflow hands back for a single user
story: a minimal, import-ready package with just the created / modified design
objects plus a faithful ``META-INF/`` (original manifest + plugins, and an
``export.log`` filtered down to the included objects).

Layout produced (mirrors a real Appian export; object dirs at the archive
root, no wrapping folder)::

    META-INF/MANIFEST.MF          (copied verbatim from the source export)
    META-INF/design-guidance.json (copied verbatim, if present)
    META-INF/plugins.txt          (copied verbatim, if present)
    META-INF/export.log           (filtered to the included objects)
    application/<app>.xml         (copied so the patch registers under the app)
    content/<uuid>.xml            (only the touched content objects)
    recordType/<uuid>.xml         (only the touched record types)
    processModel/<uuid>.xml       (only the touched process models)
    ...
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Literal

from appian_sentinel.parser.codebase_map import _EXPORT_LOG_LINE_RE
from appian_sentinel.parser.xml_parser import parse_appian_xml

logger = logging.getLogger(__name__)

# Object directories to search when we have to re-walk to resolve a UUID.
# (Same set the codebase-map builder scans.)
_SCAN_DIRS: dict[str, str] = {
    "content": "*.xml",
    "processModel": "*.xml",
    "recordType": "*.xml",
    "datatype": "*.xsd",
    "webApi": "*.xml",
    "connectedSystem": "*.xml",
    "site": "*.xml",
    "group": "*.xml",
    "dataStore": "*.xml",
}

# Content sub-types map to a filename; used only for convention-based fallback
# resolution of freshly-created objects (written as ``<dir>/<name>.xml``).
_TYPE_TO_DIR: dict[str, str] = {
    "rule": "content",
    "expression_rule": "content",
    "interface": "content",
    "constant": "content",
    "decision": "content",
    "record_type": "recordType",
    "recordtype": "recordType",
    "process_model": "processModel",
    "processmodel": "processModel",
    "data_type": "datatype",
    "datatype": "datatype",
    "web_api": "webApi",
    "webapi": "webApi",
    "connected_system": "connectedSystem",
    "connectedsystem": "connectedSystem",
    "site": "site",
    "group": "group",
    "data_store": "dataStore",
    "datastore": "dataStore",
    "document": "content",
    "folder": "content",
    "rules_folder": "content",
    "outbound_integration": "content",
    "translation_string": "content",
}

# System references that are never part of an application patch.
_SYSTEM_PREFIXES = ("SYSTEM_SYSRULES_", "SYSTEM_")


# ---------------------------------------------------------------------------
# Codebase accessors (work on both a CodebaseMap model and its model_dump dict)
# ---------------------------------------------------------------------------

def _cb_objects(codebase: Any) -> dict[str, Any]:
    if codebase is None:
        return {}
    if isinstance(codebase, dict):
        return codebase.get("objects", {}) or {}
    return getattr(codebase, "objects", {}) or {}


def _cb_dependencies(codebase: Any) -> dict[str, set[str]]:
    if codebase is None:
        return {}
    raw = codebase.get("dependencies", {}) if isinstance(codebase, dict) else getattr(codebase, "dependencies", {})
    return {k: set(v) for k, v in (raw or {}).items()}


def _cb_uuid_to_name(codebase: Any) -> dict[str, str]:
    if codebase is None:
        return {}
    if isinstance(codebase, dict):
        return codebase.get("uuid_to_name", {}) or {}
    return getattr(codebase, "uuid_to_name", {}) or {}


def _obj_file_path(obj: Any) -> str:
    """Read ``file_path`` from a codebase object (dict or AppianObject)."""
    if obj is None:
        return ""
    if isinstance(obj, dict):
        return obj.get("file_path", "") or ""
    return getattr(obj, "file_path", "") or ""


# ---------------------------------------------------------------------------
# UUID to source-file resolution
# ---------------------------------------------------------------------------

def _normalize_refs(objects: Iterable[Any]) -> list[dict[str, Any]]:
    """Accept a list of UUID strings or object dicts; return object dicts."""
    normalized: list[dict[str, Any]] = []
    for item in objects:
        if isinstance(item, str):
            normalized.append({"uuid": item})
        elif isinstance(item, dict):
            normalized.append(item)
        else:  # pydantic model or similar
            normalized.append({
                "uuid": getattr(item, "uuid", ""),
                "name": getattr(item, "name", ""),
                "type": getattr(item, "object_type", ""),
                "file_path": getattr(item, "file_path", ""),
            })
    return [o for o in normalized if o.get("uuid")]


def _build_uuid_index(export_dir: Path) -> dict[str, Path]:
    """Re-walk the export and map every parseable object UUID to its file.

    Fallback used only when no codebase map is supplied.  Mirrors the scan the
    codebase-map builder performs.
    """
    index: dict[str, Path] = {}
    for dir_name, pattern in _SCAN_DIRS.items():
        target = export_dir / dir_name
        if not target.exists():
            continue
        for file_path in target.glob(pattern):
            obj = parse_appian_xml(file_path)
            if obj is not None and obj.uuid:
                index[obj.uuid] = file_path
    logger.info("Built UUID to file index by re-walk: %d objects", len(index))
    return index


def _resolve_file(
    ref: dict[str, Any],
    export_dir: Path,
    cb_objects: dict[str, Any],
    walk_index: dict[str, Path] | None,
) -> Path | None:
    """Resolve a single object ref to an on-disk file, best-effort.

    Order: explicit ``file_path``, codebase map, re-walk index, then naming
    UUID-backed naming convention for freshly-created objects.
    """
    uuid = ref.get("uuid", "")

    # 1. Explicit path carried on the ref (set by the writer for new objects).
    fp = ref.get("file_path")
    if fp:
        p = Path(fp)
        if p.exists():
            return p

    # 2. Codebase map.
    cb_obj = cb_objects.get(uuid)
    fp = _obj_file_path(cb_obj)
    if fp and Path(fp).exists():
        return Path(fp)

    # 3. Re-walk index.
    if walk_index and uuid in walk_index:
        return walk_index[uuid]

    # 4. Convention fallback for created objects: <dir>/<uuid>.xml
    obj_type = str(ref.get("type", "")).lower()
    subdir = _TYPE_TO_DIR.get(obj_type)
    if uuid and subdir:
        for suffix in (".xml", ".xsd"):
            candidate = export_dir / subdir / f"{uuid}{suffix}"
            if candidate.exists():
                return candidate

    return None


# ---------------------------------------------------------------------------
# META-INF handling
# ---------------------------------------------------------------------------

def _filter_export_log(source_log: Path, included_refs: list[dict[str, Any]]) -> str:
    """Return an ``export.log`` body containing only the included objects.

    Header (``Success (N):``) is rewritten with the new count; the timestamped
    DEBUG section is dropped (not needed for import).
    """
    included_uuids = {str(ref["uuid"]) for ref in included_refs}
    kept_by_uuid: dict[str, str] = {}
    if source_log.exists():
        with open(source_log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n\r")
                if line.startswith("Success") or not line.strip():
                    continue
                if re.match(r"^\d{4}-\d{2}-\d{2}", line):
                    break  # reached the DEBUG section
                m = _EXPORT_LOG_LINE_RE.match(line)
                if m and m.group(3) in included_uuids:
                    kept_by_uuid[m.group(3)] = line
    for ref in included_refs:
        uuid = str(ref["uuid"])
        if uuid not in kept_by_uuid:
            name = str(ref.get("name") or uuid).replace('"', "'")
            object_type = str(ref.get("export_type") or ref.get("type") or "unknown")
            numeric_id = int(ref.get("numeric_id", ref.get("id", 0)) or 0)
            kept_by_uuid[uuid] = f'{object_type} {numeric_id} {uuid} "{name}"'
    kept = [kept_by_uuid[str(ref["uuid"])] for ref in included_refs]
    return "\n".join([f"Success ({len(kept)}):", *kept]) + "\n"


def _stage_meta_inf(export_dir: Path, staging: Path, included_refs: list[dict[str, Any]]) -> None:
    """Copy META-INF verbatim except export.log, which is filtered."""
    src_meta = export_dir / "META-INF"
    dst_meta = staging / "META-INF"
    dst_meta.mkdir(parents=True, exist_ok=True)

    if src_meta.exists():
        for item in src_meta.iterdir():
            if item.name == "export.log" or not item.is_file():
                continue
            shutil.copy2(item, dst_meta / item.name)

    (dst_meta / "export.log").write_bytes(
        _filter_export_log(src_meta / "export.log", included_refs).encode("utf-8")
    )


def _stage_application(export_dir: Path, staging: Path) -> None:
    """Copy the application/*.xml so the patch registers under the app."""
    src_app = export_dir / "application"
    if not src_app.exists():
        return
    dst_app = staging / "application"
    dst_app.mkdir(parents=True, exist_ok=True)
    for xml in src_app.glob("*.xml"):
        shutil.copy2(xml, dst_app / xml.name)


def _stage_object_file(src_file: Path, export_dir: Path, staging: Path) -> list[Path]:
    """Copy an object's XML (and any sibling document payload dir) into staging.

    Returns the list of destination paths written.
    """
    written: list[Path] = []
    rel = src_file.relative_to(export_dir)
    dst = staging / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_file, dst)
    written.append(dst)

    # Documents store their payload in a sibling directory named after the
    # file stem (e.g. content/<stem>.xml + content/<stem>/file.txt).
    payload_dir = src_file.with_suffix("")
    if payload_dir.is_dir():
        dst_payload = staging / payload_dir.relative_to(export_dir)
        shutil.copytree(payload_dir, dst_payload, dirs_exist_ok=True)
        written.extend(p for p in dst_payload.rglob("*") if p.is_file())

    return written


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_patch_zip(
    export_dir: Path,
    objects: Iterable[Any],
    output_path: Path,
    *,
    codebase: Any | None = None,
    warn_missing_deps: bool = True,
    reindex_if_needed: bool = True,
    dependency_mode: Literal["strict", "warn", "dependency-closure"] | None = None,
) -> dict[str, Any]:
    """Build a minimal import ZIP with only the given objects.

    Parameters
    ----------
    export_dir:
        Root of the extracted source export (contains ``META-INF/`` and the
        object-type dirs).
    objects:
        Iterable of UUID strings **or** object dicts (``uuid`` required;
        ``name``/``type``/``file_path`` used for resolution when present).
    output_path:
        Destination ``.zip`` path.
    codebase:
        Optional ``CodebaseMap`` (model or ``model_dump`` dict), used for fast
        UUID to file resolution and dependency warnings.
    warn_missing_deps:
        When True and a codebase is available, report referenced objects that
        are *not* included in the patch (import may fail without them).
    reindex_if_needed:
        When True, re-walk the export to resolve UUIDs not found via the
        codebase map.

    Returns
    -------
    dict with keys: ``zip_path``, ``included`` (list of {uuid,name,file}),
    ``missing`` (uuids that could not be resolved to a file),
    ``dependency_warnings`` (list of {source, missing_ref, missing_ref_name}),
    ``file_count``.
    """
    export_dir = Path(export_dir)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mode = dependency_mode or "warn"
    if mode not in {"strict", "warn", "dependency-closure"}:
        raise ValueError(f"Unsupported dependency mode: {mode}")
    refs = _normalize_refs(objects)
    cb_objects = _cb_objects(codebase)
    uuid_to_name = _cb_uuid_to_name(codebase)
    dependencies = _cb_dependencies(codebase)
    if mode == "dependency-closure":
        if codebase is None:
            raise ValueError("dependency-closure mode requires a codebase")
        queued = [str(ref["uuid"]) for ref in refs]
        known = set(queued)
        while queued:
            source_uuid = queued.pop()
            for dependency_uuid in dependencies.get(source_uuid, set()):
                if dependency_uuid.startswith(_SYSTEM_PREFIXES) or dependency_uuid in known:
                    continue
                known.add(dependency_uuid)
                queued.append(dependency_uuid)
                refs.append({
                    "uuid": dependency_uuid,
                    "name": uuid_to_name.get(dependency_uuid, ""),
                })

    # Decide whether we need a re-walk index (only if some ref is unresolved
    # via ref.file_path / codebase and the caller allows it).
    walk_index: dict[str, Path] | None = None

    def _ensure_index() -> dict[str, Path]:
        nonlocal walk_index
        if walk_index is None:
            walk_index = _build_uuid_index(export_dir) if reindex_if_needed else {}
        return walk_index

    included: list[dict[str, str]] = []
    included_uuids: set[str] = set()
    missing: list[str] = []

    # Resolve every ref to a file, staging into a temp dir under output parent.
    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.stem}.staging.", dir=output_path.parent))
    temporary: Path | None = None

    try:
        for ref in refs:
            uuid = ref["uuid"]
            src = _resolve_file(ref, export_dir, cb_objects, None)
            if src is None and reindex_if_needed:
                src = _resolve_file(ref, export_dir, cb_objects, _ensure_index())
            if src is None:
                missing.append(uuid)
                logger.warning("Patch: could not resolve file for object %s", uuid)
                continue

            _stage_object_file(src, export_dir, staging)
            included_uuids.add(uuid)
            included.append({
                "uuid": uuid,
                "name": ref.get("name") or uuid_to_name.get(uuid, ""),
                "file": str(src.relative_to(export_dir)),
            })

        # Dependency warnings.
        dependency_warnings: list[dict[str, str]] = []
        check_dependencies = dependency_mode is not None or warn_missing_deps
        if mode in {"strict", "warn"} and check_dependencies and codebase is not None:
            for uuid in included_uuids:
                for ref_uuid in dependencies.get(uuid, set()):
                    if ref_uuid in included_uuids:
                        continue
                    if ref_uuid.startswith(_SYSTEM_PREFIXES):
                        continue
                    dependency_warnings.append({
                        "source": uuid_to_name.get(uuid, uuid),
                        "missing_ref": ref_uuid,
                        "missing_ref_name": uuid_to_name.get(ref_uuid, ref_uuid),
                    })

        if mode == "strict" and (missing or dependency_warnings):
            raise ValueError(
                f"Patch is incomplete: {len(missing)} unresolved object(s), "
                f"{len(dependency_warnings)} missing dependency reference(s)"
            )

        included_refs = [
            next(ref for ref in refs if str(ref["uuid"]) == item["uuid"])
            for item in included
        ]
        _stage_meta_inf(export_dir, staging, included_refs)
        _stage_application(export_dir, staging)

        # Zip the staging tree (object dirs at the archive root).
        file_count = 0
        descriptor, temporary_name = tempfile.mkstemp(
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(staging.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(staging).as_posix())
                    file_count += 1
        with zipfile.ZipFile(temporary, "r") as zf:
            if zf.testzip() is not None:
                raise ValueError("Generated patch ZIP failed CRC validation")
        os.replace(temporary, output_path)

        logger.info(
            "Built patch ZIP %s: %d objects, %d files, %d unresolved, %d dep warnings",
            output_path.name, len(included), file_count, len(missing), len(dependency_warnings),
        )

        return {
            "zip_path": str(output_path),
            "included": included,
            "missing": missing,
            "dependency_warnings": dependency_warnings,
            "file_count": file_count,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
