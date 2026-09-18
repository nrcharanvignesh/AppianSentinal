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
from appian_sentinel.mcp_server.models import (
    ApplySailEditResponse,
    BulkAddTestsResponse,
    CoverageResponse,
    DependencyGraphRequest,
    DependencyGraphResponse,
    GenerateFullZipRequest,
    GenerateFullZipResponse,
    GenerateSailRequest,
    GenerateSailResponse,
    GenerateSolutionDesignRequest,
    GenerateSolutionDesignResponse,
    GenerateTestSuiteRequest,
    GenerateTestSuiteResponse,
    HistoryCommitResponse,
    HistoryDiffResponse,
    HistoryLogResponse,
    HistoryRestoreResponse,
    InspectSailRequest,
    InspectSailResponse,
    ListObjectsRequest,
    ListObjectsResponse,
    NormalizeRequirementRequest,
    NormalizeRequirementResponse,
    ResolveObjectRequest,
    ResolveObjectResponse,
    RunStaticTestsRequest,
    StaticTestResult,
    ValidateObjectRequest,
    ValidateObjectResponse,
    ValidateSailRequest,
    ValidateTestCoverageRequest,
    ValidateWorkspaceRequest,
    ValidateWorkspaceResponse,
    ValidationResponse,
    WorkspaceStatusResponse,
)

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


@mcp.tool(structured_output=True)
def list_objects(request: ListObjectsRequest) -> ListObjectsResponse:
    """List parsed objects by type with bounded cursor pagination."""
    return tools.list_objects(request)


@mcp.tool(structured_output=True)
def resolve_object(request: ResolveObjectRequest) -> ResolveObjectResponse:
    """Resolve an object UUID or exact name and report ambiguity."""
    return tools.resolve_object(request)


@mcp.tool(structured_output=True)
def get_dependency_graph(request: DependencyGraphRequest) -> DependencyGraphResponse:
    """Return a bounded object dependency graph."""
    return tools.get_dependency_graph(request)


@mcp.tool(structured_output=True)
def inspect_sail(request: InspectSailRequest) -> InspectSailResponse:
    """Inspect SAIL syntax, symbols, references, AST, and formatting."""
    return tools.inspect_sail(request)


@mcp.tool(structured_output=True)
def validate_sail(request: ValidateSailRequest) -> ValidationResponse:
    """Run parser and structural validation against SAIL source."""
    return tools.validate_sail(request)


@mcp.tool(structured_output=True)
def validate_object(request: ValidateObjectRequest) -> ValidateObjectResponse:
    """Validate one parsed object without writing files."""
    return tools.validate_object(request)


@mcp.tool(structured_output=True)
def validate_workspace(request: ValidateWorkspaceRequest) -> ValidateWorkspaceResponse:
    """Validate a bounded page of parsed workspace objects."""
    return tools.validate_workspace(request)


@mcp.tool(structured_output=True)
def normalize_requirement(
    request: NormalizeRequirementRequest,
) -> NormalizeRequirementResponse:
    """Normalize plain requirement text into a typed user story."""
    return tools.normalize_requirement(request)


@mcp.tool(structured_output=True)
async def generate_sail(request: GenerateSailRequest) -> GenerateSailResponse:
    """Generate SAIL for one existing interface or expression rule.

    The target is resolved by its real workspace UUID. The generated source is
    returned only after the shared SAIL validator accepts its syntax, functions,
    inputs, version compatibility, and UUID references.
    """
    return await tools.generate_sail(request)


@mcp.tool(structured_output=True)
async def generate_test_suite(
    request: GenerateTestSuiteRequest,
) -> GenerateTestSuiteResponse:
    """Generate a typed test suite for one existing Appian object.

    The supplied requirement and solution design are combined with the target
    object's real UUID and bounded workspace context. Empty or malformed LLM
    output is rejected instead of returning a placeholder suite.
    """
    return await tools.generate_test_suite(request)


@mcp.tool(structured_output=True)
async def generate_solution_design(
    request: GenerateSolutionDesignRequest,
) -> GenerateSolutionDesignResponse:
    """Generate a minimal Appian solution design for one requirement.

    The existing story analyzer first derives a requirement analysis and then
    designs object changes using a bounded summary of the parsed workspace.
    """
    return await tools.generate_solution_design(request)


@mcp.tool(structured_output=True)
def validate_test_coverage(
    request: ValidateTestCoverageRequest,
) -> CoverageResponse:
    """Validate deterministic acceptance-criterion test coverage."""
    return tools.validate_test_coverage(request)


@mcp.tool(structured_output=True)
async def run_static_tests(request: RunStaticTestsRequest) -> StaticTestResult:
    """Run static SAIL tests without claiming live Appian execution."""
    return await tools.run_static_tests(request)


@mcp.tool(structured_output=True)
def workspace_status(export_dir: str) -> WorkspaceStatusResponse:
    """Return baseline, HEAD, staged, and working-tree status."""
    return tools.workspace_status(export_dir)


@mcp.tool(structured_output=True)
def history_log(export_dir: str, limit: int = 50) -> HistoryLogResponse:
    """Return bounded newest-first workspace revision history."""
    return tools.history_log(export_dir, limit)


@mcp.tool(structured_output=True)
def history_diff(
    export_dir: str,
    from_revision: str,
    to_revision: str | None = None,
) -> HistoryDiffResponse:
    """Return a redacted diff between workspace revisions."""
    return tools.history_diff(export_dir, from_revision, to_revision)


@mcp.tool(structured_output=True)
def history_commit(
    export_dir: str,
    actor: str,
    requirement: str,
    message: str,
    paths: list[str] | None = None,
    expected_revision: str | None = None,
) -> HistoryCommitResponse:
    """Create a baseline or commit selected workspace changes."""
    return tools.history_commit(
        export_dir,
        actor,
        requirement,
        message,
        paths,
        expected_revision,
    )


@mcp.tool(structured_output=True)
def history_restore(
    export_dir: str,
    revision_hash: str,
    actor: str,
    requirement: str,
    message: str = "restore",
    expected_revision: str | None = None,
) -> HistoryRestoreResponse:
    """Restore a clean workspace to a prior revision."""
    return tools.history_restore(
        export_dir,
        revision_hash,
        actor,
        requirement,
        message,
        expected_revision,
    )


@mcp.tool(structured_output=True)
def apply_sail_edit(
    export_dir: str,
    uuid: str,
    definition: str,
) -> ApplySailEditResponse:
    """Validate first, then update one SAIL object definition."""
    return tools.apply_sail_edit(export_dir, uuid, definition)


@mcp.tool(structured_output=True)
def bulk_add_tests(
    export_dir: str,
    object_uuids: list[str],
    tests: list[str],
    preview: bool,
) -> BulkAddTestsResponse:
    """Preview or replace embedded test nodes on multiple objects."""
    return tools.bulk_add_tests(export_dir, object_uuids, tests, preview)


@mcp.tool(structured_output=True)
def generate_full_zip(request: GenerateFullZipRequest) -> GenerateFullZipResponse:
    """Build a source-pure full ZIP at a new isolated output path."""
    return tools.generate_full_zip(request)


def main() -> None:
    """Console-script entry point that runs the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
