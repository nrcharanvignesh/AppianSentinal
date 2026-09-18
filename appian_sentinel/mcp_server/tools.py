"""Tool logic for the Appian Sentinel MCP server.

Plain (async where needed) functions wrapping the existing engine, so they can
be unit-tested without the MCP transport. ``server.py`` registers thin
decorated wrappers around these.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from appian_sentinel.generator.object_writer import write_object
from appian_sentinel.integrations import ado_client
from appian_sentinel.mcp_server import cache
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.packager import patch_builder
from appian_sentinel.parser import codebase_map as codebase_map_mod

logger = logging.getLogger(__name__)


def analyze_appian_zip(zip_path: str) -> dict[str, Any]:
    """Extract and analyze an Appian export ZIP; catalog objects by type."""
    export_dir, cb = cache.analyze_zip(Path(zip_path))
    summary = cb.summarise()
    return {
        "export_dir": str(export_dir),
        "app_name": cb.app_name,
        "appian_version": cb.appian_version,
        "total_objects": summary.total_objects,
        "counts_by_type": summary.counts_by_type,
        "plugin_count": summary.plugin_count,
        "by_type": {t: len(uuids) for t, uuids in cb.by_type.items()},
    }


def search_objects(
    export_dir: str,
    query: str,
    types: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search objects by name/description (case-insensitive substring)."""
    cb = cache.get_codebase(Path(export_dir))
    object_types: list[ObjectType] | None = None
    if types:
        object_types = []
        for t in types:
            try:
                object_types.append(ObjectType(t))
            except ValueError:
                logger.warning("Unknown object type filter: %s", t)
    results = codebase_map_mod.search_objects(cb, query, object_types, limit)
    return {
        "count": len(results),
        "results": [
            {
                "uuid": o.uuid,
                "name": o.name,
                "type": o.object_type.value,
                "description": o.description,
                "file_path": o.file_path,
            }
            for o in results
        ],
    }


def get_object(export_dir: str, uuid: str) -> dict[str, Any]:
    """Return the full parsed detail for one object by UUID."""
    cb = cache.get_codebase(Path(export_dir))
    obj = cb.get_object(uuid)
    if obj is None:
        return {"error": f"Object {uuid} not found."}
    data = obj.model_dump()
    data["direct_dependencies"] = sorted(cb.get_direct_dependencies(uuid))
    data["direct_dependents"] = sorted(cb.get_direct_dependents(uuid))
    return data


async def read_ado_work_item(
    organization: str,
    project: str,
    work_item_id: int | str,
    pat: str,
) -> dict[str, Any]:
    """Fetch an ADO work item's title, description, and acceptance criteria."""
    return await ado_client.get_work_item(organization, project, work_item_id, pat)


def apply_object_change(export_dir: str, obj: dict[str, Any]) -> dict[str, Any]:
    """Write a created/modified object into the export directory.

    *obj* keys: ``type``, ``name``, ``action`` (create|modify), ``sail_code`` /
    ``definition``, and type-specific fields (see ``object_writer``).
    """
    out = write_object(Path(export_dir), obj)
    if out is None:
        return {"status": "error", "message": f"Could not write object {obj.get('name')!r}"}
    return {"status": "ok", "file_path": str(out), "uuid": obj.get("uuid", ""), "name": obj.get("name", "")}


def generate_patch_zip(
    export_dir: str,
    object_uuids: list[str],
    output_path: str,
) -> dict[str, Any]:
    """Build a patch ZIP containing only the given objects."""
    export_dir_p = Path(export_dir)
    cb = cache.get_codebase(export_dir_p)
    return patch_builder.build_patch_zip(
        export_dir_p,
        object_uuids,
        Path(output_path),
        codebase=cb,
    )
