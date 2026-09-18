"""Build the full codebase map from an extracted Appian application export.

This module orchestrates parsing of **every** XML/XSD file in the export,
constructs the UUID <-> name mapping from ``META-INF/export.log``, builds
forward and reverse dependency graphs, and returns a fully populated
:class:`~appian_sentinel.models.codebase.CodebaseMap`.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import etree

from appian_sentinel.models.appian_objects import (
    AppianObject,
    ObjectType,
)
from appian_sentinel.models.codebase import CodebaseMap, PluginInfo
from appian_sentinel.parser.xml_parser import parse_appian_xml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# export.log parser — the UUID <-> name rosetta stone
# ---------------------------------------------------------------------------

# Matches success lines: ``type numericId uuid "displayName"``
# The UUID may be a standard UUID, an Appian internal uuid, or a namespace-
# qualified name like ``{urn:com:appian:types:IHUB}IHUB_TASK``.
_EXPORT_LOG_LINE_RE = re.compile(
    r'^(\S+)\s+(\d+)\s+(\S+)\s+"(.+)"$'
)


def parse_export_log(export_log_path: Path) -> dict[str, str]:
    """Parse ``META-INF/export.log`` and return a *uuid -> display_name* dict.

    The log has two sections:
    1. Success header lines (``type numericId uuid "name"``) at the top.
    2. Timestamped DEBUG lines below.

    We only parse section 1 — we stop as soon as we hit a line that looks
    like a timestamp (starts with a digit followed by a dash) or the ``DEBUG``
    keyword.
    """
    uuid_to_name: dict[str, str] = {}
    if not export_log_path.exists():
        logger.warning("export.log not found at %s", export_log_path)
        return uuid_to_name

    with open(export_log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n\r")
            # Skip the header line "Success (N):"
            if line.startswith("Success") or not line.strip():
                continue
            # Stop when we reach the DEBUG section (timestamp lines)
            if re.match(r'^\d{4}-\d{2}-\d{2}', line):
                break

            m = _EXPORT_LOG_LINE_RE.match(line)
            if m:
                uuid = m.group(3)
                display_name = m.group(4)
                uuid_to_name[uuid] = display_name
            else:
                # Some edge cases — skip silently
                pass

    logger.info("Parsed %d UUID mappings from export.log", len(uuid_to_name))
    return uuid_to_name


# ---------------------------------------------------------------------------
# MANIFEST.MF parser
# ---------------------------------------------------------------------------

def parse_manifest(manifest_path: Path) -> dict[str, str]:
    """Parse ``META-INF/MANIFEST.MF`` and return key-value pairs."""
    result: dict[str, str] = {}
    if not manifest_path.exists():
        return result
    with open(manifest_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip()
    return result


# ---------------------------------------------------------------------------
# plugins.txt parser
# ---------------------------------------------------------------------------

def parse_plugins(plugins_path: Path) -> list[PluginInfo]:
    """Parse ``META-INF/plugins.txt`` into a list of PluginInfo objects.

    The file is structured as triplets separated by blank lines::

        plugin.id
        Plugin Display Name
        1.2.3

        next.plugin.id
        ...
    """
    plugins: list[PluginInfo] = []
    if not plugins_path.exists():
        return plugins

    with open(plugins_path, encoding="utf-8", errors="replace") as fh:
        lines = [line.rstrip("\n\r") for line in fh.readlines()]

    # Group lines into triplets separated by blank lines
    current_block: list[str] = []
    for line in lines:
        if line.strip() == "":
            if current_block:
                pid = current_block[0] if len(current_block) > 0 else ""
                pname = current_block[1] if len(current_block) > 1 else ""
                pver = current_block[2] if len(current_block) > 2 else ""
                plugins.append(PluginInfo(id=pid, name=pname, version=pver))
                current_block = []
        else:
            current_block.append(line)

    # Don't forget the last block if file doesn't end with blank line
    if current_block:
        pid = current_block[0] if len(current_block) > 0 else ""
        pname = current_block[1] if len(current_block) > 1 else ""
        pver = current_block[2] if len(current_block) > 2 else ""
        plugins.append(PluginInfo(id=pid, name=pname, version=pver))

    logger.info("Parsed %d plugins from plugins.txt", len(plugins))
    return plugins


# ---------------------------------------------------------------------------
# application/*.xml parser (app metadata)
# ---------------------------------------------------------------------------

def parse_application_xml(app_xml_path: Path) -> dict[str, str]:
    """Parse the application manifest XML and return key metadata fields."""
    result: dict[str, str] = {}
    try:
        parser = etree.XMLParser(recover=True, remove_comments=True)
        tree = etree.parse(str(app_xml_path), parser)
        root = tree.getroot()

        app_el = root.find("application")
        if app_el is None:
            ns = "http://www.appian.com/ae/types/2009"
            app_el = root.find(f"{{{ns}}}application")
        if app_el is None:
            return result

        def _t(tag: str) -> str:
            el = app_el.find(tag)
            if el is None:
                el = app_el.find(f"{{http://www.appian.com/ae/types/2009}}{tag}")
            return (el.text or "").strip() if el is not None else ""

        result["name"] = _t("name")
        result["uuid"] = _t("uuid")
        result["prefix"] = _t("prefix")
        result["description"] = _t("description")
    except Exception:
        logger.warning("Failed to parse application XML: %s", app_xml_path, exc_info=True)

    return result


# ---------------------------------------------------------------------------
# Codebase map builder — main entry point
# ---------------------------------------------------------------------------

ProgressCallback = Any  # Callable[[str, int, int, str], None] | None


def _count_files(export_dir: Path, scan_dirs: dict[str, str]) -> int:
    """Pre-count files to parse so we can report accurate progress."""
    total = 0
    for dir_name, pattern in scan_dirs.items():
        target_dir = export_dir / dir_name
        if target_dir.exists():
            total += sum(1 for _ in target_dir.glob(pattern))
    return total


def build_codebase_map(
    export_dir: Path,
    on_progress: ProgressCallback = None,
) -> CodebaseMap:
    """Build a complete :class:`CodebaseMap` from an extracted Appian export.

    Parameters
    ----------
    export_dir : Path
        Root of the extracted Appian export.
    on_progress : callable, optional
        ``(phase, current, total, detail)`` callback fired at each
        meaningful progress point so callers can report to a UI.

    Steps:
    1. Read ``META-INF/MANIFEST.MF`` for Appian version / timestamp.
    2. Parse ``META-INF/export.log`` to build UUID <-> name mapping.
    3. Parse ``META-INF/plugins.txt`` for installed plugins.
    4. Parse ``application/*.xml`` for app name / prefix.
    5. Walk every supported directory, parse each XML/XSD file.
    6. Build forward dependency graph (object -> set of objects it references).
    7. Build reverse dependency graph.
    8. Return the populated CodebaseMap.
    """
    export_dir = Path(export_dir)
    meta_dir = export_dir / "META-INF"

    def _emit(phase: str, current: int, total: int, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(phase, current, total, detail)

    # Directories to scan (maps directory name -> file glob pattern)
    scan_dirs = {
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

    # Pre-count so progress is accurate
    file_count = _count_files(export_dir, scan_dirs)
    total_steps = file_count + 3  # +3 for metadata, deps-fwd, deps-rev

    _emit("metadata", 0, total_steps, "Reading manifest and export log…")

    # 1. Manifest
    manifest = parse_manifest(meta_dir / "MANIFEST.MF")
    appian_version = manifest.get("Appian-Version", "")
    export_timestamp = manifest.get("Created-On", "")

    # 2. export.log  (UUID <-> name)
    uuid_to_name = parse_export_log(meta_dir / "export.log")

    # 3. Plugins
    plugins = parse_plugins(meta_dir / "plugins.txt")

    # 4. Application metadata
    app_name = ""
    app_uuid = ""
    app_prefix = ""
    app_dir = export_dir / "application"
    if app_dir.exists():
        for app_file in app_dir.glob("*.xml"):
            app_meta = parse_application_xml(app_file)
            app_name = app_meta.get("name", "")
            app_uuid = app_meta.get("uuid", "")
            app_prefix = app_meta.get("prefix", "")
            break  # typically one application XML

    _emit("metadata", 1, total_steps, f"App: {app_name or '(unknown)'}, {len(uuid_to_name)} UUIDs mapped")

    # 5. Parse all XML/XSD files in supported directories
    objects: dict[str, AppianObject] = {}
    by_type: dict[str, list[str]] = defaultdict(list)

    parsed_count = 0
    parse_errors = 0

    for dir_name, pattern in scan_dirs.items():
        target_dir = export_dir / dir_name
        if not target_dir.exists():
            continue
        for file_path in target_dir.glob(pattern):
            parsed_count += 1
            obj = parse_appian_xml(file_path)
            if obj is None:
                parse_errors += 1
            elif obj.uuid:
                objects[obj.uuid] = obj
                by_type[obj.object_type.value].append(obj.uuid)
                if obj.uuid not in uuid_to_name and obj.name:
                    uuid_to_name[obj.uuid] = obj.name

            if parsed_count % 50 == 0 or parsed_count == file_count:
                _emit(
                    "parsing",
                    1 + parsed_count,
                    total_steps,
                    f"Parsing {dir_name}/ — {parsed_count}/{file_count} files ({len(objects)} objects)",
                )

    logger.info(
        "Parsed %d objects from %d files (%d errors) across %d directories",
        len(objects), parsed_count, parse_errors, len(scan_dirs),
    )

    # Build name_to_uuid (reverse of uuid_to_name)
    name_to_uuid: dict[str, str] = {}
    for uid, uname in uuid_to_name.items():
        name_to_uuid[uname] = uid

    # 6. Build forward dependency graph
    _emit("dependencies", 1 + file_count, total_steps, f"Building dependency graph for {len(objects)} objects…")

    dependencies: dict[str, set[str]] = {}
    for uid, obj in objects.items():
        refs = obj.get_uuid_references()
        valid_refs = {r for r in refs if r in objects or r in uuid_to_name}
        if valid_refs:
            dependencies[uid] = valid_refs

    # 7. Build reverse dependency graph
    _emit("dependencies", 2 + file_count, total_steps, "Building reverse dependency graph…")

    reverse_dependencies: dict[str, set[str]] = defaultdict(set)
    for uid, refs in dependencies.items():
        for ref in refs:
            reverse_dependencies[ref].add(uid)

    codebase = CodebaseMap(
        app_name=app_name,
        app_uuid=app_uuid,
        app_prefix=app_prefix,
        appian_version=appian_version,
        export_timestamp=export_timestamp,
        plugins=plugins,
        objects=objects,
        uuid_to_name=uuid_to_name,
        name_to_uuid=name_to_uuid,
        dependencies=dependencies,
        reverse_dependencies=dict(reverse_dependencies),
        by_type=dict(by_type),
    )

    dep_edges = sum(len(v) for v in dependencies.values())
    _emit("complete", total_steps, total_steps, f"Done — {len(objects)} objects, {dep_edges} dependency edges")

    logger.info(
        "CodebaseMap built: app=%s, version=%s, objects=%d, deps=%d edges",
        app_name, appian_version, len(objects), dep_edges,
    )

    return codebase


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def get_impact_analysis(
    codebase: CodebaseMap,
    changed_uuids: set[str],
    max_depth: int = 10,
) -> dict[str, Any]:
    """Compute the impact of changes to the given objects.

    Walks the *reverse* dependency graph to find every object that
    transitively depends on the changed set.

    Returns a dict with:
    - ``directly_affected``: UUIDs one hop away
    - ``transitively_affected``: all UUIDs reachable (BFS up to *max_depth*)
    - ``affected_by_type``: count of affected objects grouped by type
    - ``affected_objects``: list of dicts with uuid/name/type for each affected
    """
    directly_affected: set[str] = set()
    for uid in changed_uuids:
        directly_affected |= codebase.get_direct_dependents(uid)
    directly_affected -= changed_uuids

    # BFS for transitive impact
    visited: set[str] = set(changed_uuids)
    frontier = set(changed_uuids)
    depth = 0
    while frontier and depth < max_depth:
        next_frontier: set[str] = set()
        for uid in frontier:
            for dep in codebase.get_direct_dependents(uid):
                if dep not in visited:
                    visited.add(dep)
                    next_frontier.add(dep)
        frontier = next_frontier
        depth += 1

    transitively_affected = visited - changed_uuids

    # Group by type
    affected_by_type: dict[str, int] = defaultdict(int)
    affected_objects: list[dict[str, str]] = []
    for uid in transitively_affected:
        obj = codebase.get_object(uid)
        if obj:
            affected_by_type[obj.object_type.value] += 1
            affected_objects.append({
                "uuid": uid,
                "name": obj.name or codebase.resolve_name(uid),
                "type": obj.object_type.value,
            })
        else:
            affected_by_type["unknown"] += 1
            affected_objects.append({
                "uuid": uid,
                "name": codebase.resolve_name(uid),
                "type": "unknown",
            })

    return {
        "changed": list(changed_uuids),
        "directly_affected": list(directly_affected),
        "transitively_affected": list(transitively_affected),
        "affected_count": len(transitively_affected),
        "affected_by_type": dict(affected_by_type),
        "affected_objects": affected_objects,
    }


def get_dependency_tree(
    codebase: CodebaseMap,
    uuid: str,
    depth: int = 3,
    direction: str = "forward",
) -> dict[str, Any]:
    """Build a dependency tree for a single object.

    Parameters
    ----------
    codebase : CodebaseMap
        The codebase to query.
    uuid : str
        Root object UUID.
    depth : int
        Maximum depth to traverse.
    direction : str
        ``"forward"`` follows what this object depends on;
        ``"reverse"`` follows what depends on this object.

    Returns
    -------
    dict
        Nested tree structure with ``uuid``, ``name``, ``type``, ``children``.
    """

    def _build(uid: str, current_depth: int, visited: set[str]) -> dict[str, Any]:
        obj = codebase.get_object(uid)
        node: dict[str, Any] = {
            "uuid": uid,
            "name": obj.name if obj else codebase.resolve_name(uid),
            "type": obj.object_type.value if obj else "unknown",
            "children": [],
        }
        if current_depth >= depth or uid in visited:
            return node

        visited = visited | {uid}  # copy to allow sibling traversal

        if direction == "forward":
            neighbours = codebase.get_direct_dependencies(uid)
        else:
            neighbours = codebase.get_direct_dependents(uid)

        for neighbour in sorted(neighbours):
            child = _build(neighbour, current_depth + 1, visited)
            node["children"].append(child)

        return node

    return _build(uuid, 0, set())


def search_objects(
    codebase: CodebaseMap,
    query: str,
    object_types: list[ObjectType] | None = None,
    max_results: int = 50,
) -> list[AppianObject]:
    """Search for objects by name or description (case-insensitive substring).

    Parameters
    ----------
    codebase : CodebaseMap
        The codebase to search.
    query : str
        Search string (case-insensitive substring match).
    object_types : list[ObjectType] | None
        If provided, restrict to these types only.
    max_results : int
        Maximum number of results to return.
    """
    query_lower = query.lower()
    results: list[AppianObject] = []

    for obj in codebase.objects.values():
        if object_types and obj.object_type not in object_types:
            continue
        if query_lower in obj.name.lower() or query_lower in obj.description.lower():
            results.append(obj)
            if len(results) >= max_results:
                break

    return results
