"""Appian Sentinel MCP server (stdio).

Exposes the Python engine as MCP tools reusable by this app's agent, Claude
Desktop, Cursor, or any MCP client. Run via the ``appian-sentinel-mcp``
console script or ``python -m appian_sentinel.mcp_server.server``.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from appian_sentinel.mcp_server import tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("Appian Sentinel")


@mcp.tool()
def analyze_appian_zip(zip_path: str) -> dict[str, Any]:
    """Extract an Appian export .zip and catalog its objects by type.

    Returns the export directory (needed by the other tools), app metadata,
    total object count, and per-type counts.
    """
    return tools.analyze_appian_zip(zip_path)


@mcp.tool()
def search_objects(
    export_dir: str,
    query: str,
    types: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search objects by name/description. Optionally filter by object type
    (e.g. ["interface", "expression_rule", "record_type"])."""
    return tools.search_objects(export_dir, query, types, limit)


@mcp.tool()
def get_object(export_dir: str, uuid: str) -> dict[str, Any]:
    """Return full parsed detail for one object by UUID, plus its direct
    dependencies and dependents."""
    return tools.get_object(export_dir, uuid)


@mcp.tool()
async def read_ado_work_item(
    organization: str,
    project: str,
    work_item_id: int,
    pat: str,
) -> dict[str, Any]:
    """Fetch an Azure DevOps work item's title, description, and acceptance
    criteria (PAT over REST)."""
    return await tools.read_ado_work_item(organization, project, work_item_id, pat)


@mcp.tool()
def apply_object_change(export_dir: str, obj: dict[str, Any]) -> dict[str, Any]:
    """Write a created or modified object into the export directory.

    obj keys: type (rule|interface|constant|decision|record_type|
    process_model), name, action (create|modify), sail_code/definition, plus
    type-specific fields.
    """
    return tools.apply_object_change(export_dir, obj)


@mcp.tool()
def generate_patch_zip(
    export_dir: str,
    object_uuids: list[str],
    output_path: str,
) -> dict[str, Any]:
    """Build a minimal import ZIP containing ONLY the given objects (plus a
    faithful META-INF). Returns included objects, unresolved UUIDs, and
    dependency warnings."""
    return tools.generate_patch_zip(export_dir, object_uuids, output_path)


def main() -> None:
    """Console-script entry point — runs the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
