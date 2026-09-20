from __future__ import annotations

import inspect
from typing import get_type_hints

from appian_sentinel.mcp_server import server
from appian_sentinel.models.object_registry import CRUD_TOOL_NAMES, OBJECT_CAPABILITIES

EXPECTED_TOOLS = {
    "analyze_appian_zip",
    "apply_object_change",
    "apply_sail_edit",
    "bulk_add_tests",
    "bulk_replace_tests",
    "generate_full_zip",
    "generate_patch_zip",
    "generate_sail",
    "generate_solution_design",
    "generate_test_suite",
    "get_codebase",
    "get_dependency_graph",
    "get_object",
    "get_object_tests",
    "history_commit",
    "history_diff",
    "history_log",
    "history_restore",
    "inspect_sail",
    "list_objects",
    "normalize_requirement",
    "read_ado_work_item",
    "resolve_object",
    "run_object_static_test",
    "run_static_tests",
    "search_objects",
    "validate_object",
    "validate_sail",
    "validate_test_coverage",
    "validate_workspace",
    "workspace_status",
} | set(CRUD_TOOL_NAMES)

CATEGORY_TO_TOOLS = {
    "workspace lifecycle": {"analyze_appian_zip", "workspace_status"},
    "analysis": {"analyze_appian_zip"},
    "search": {"search_objects"},
    "objects": {"get_codebase", "get_object", "list_objects", "resolve_object"},
    "code intelligence": {"inspect_sail"},
    "dependencies": {"get_dependency_graph"},
    "requirements": {"normalize_requirement", "read_ado_work_item"},
    "validation": {"validate_object", "validate_sail", "validate_workspace"},
    "generation": {
        "generate_sail",
        "generate_solution_design",
        "generate_test_suite",
    },
    "tests": {
        "bulk_add_tests",
        "bulk_replace_tests",
        "get_object_tests",
        "run_object_static_test",
        "run_static_tests",
        "validate_test_coverage",
    },
    "changes": {
        "apply_object_change",
        "apply_sail_edit",
        "history_commit",
        "history_restore",
    },
    "packaging": {"generate_full_zip", "generate_patch_zip"},
    "typed crud": {"create_expression_rule", "get_interface", "update_constant", "delete_record_type"},
}


async def test_exact_mcp_tool_inventory_is_typed_and_documented() -> None:
    registered = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert set(registered) == EXPECTED_TOOLS
    assert len(CRUD_TOOL_NAMES) == len(OBJECT_CAPABILITIES) * 4

    for name, tool in registered.items():
        function = getattr(server, name)
        assert inspect.getdoc(function)
        assert tool.description and tool.description.strip()
        signature = inspect.signature(function)
        hints = get_type_hints(function)
        assert set(signature.parameters) <= set(hints)
        assert "return" in hints
        assert set(tool.inputSchema.get("properties", {})) == set(signature.parameters)


async def test_typed_crud_schemas_explain_required_and_optional_fields() -> None:
    registered = {tool.name: tool for tool in await server.mcp.list_tools()}
    expected_required = {
        "create": {"export_dir", "name"},
        "get": {"export_dir", "object_uuid"},
        "update": {"export_dir", "object_uuid"},
        "delete": {"export_dir", "object_uuid"},
    }
    for capability in OBJECT_CAPABILITIES:
        for operation, name in (
            ("create", capability.create_tool),
            ("get", capability.get_tool),
            ("update", capability.update_tool),
            ("delete", capability.delete_tool),
        ):
            tool = registered[name]
            request_schema = tool.inputSchema["$defs"][
                f"{operation.title()}TypedObjectRequest"
                if operation != "get"
                else "TypedObjectRequest"
            ]
            assert set(request_schema["required"]) == expected_required[operation]
            assert all(
                property_schema.get("description", "").strip()
                for property_schema in request_schema["properties"].values()
            )


def test_each_implemented_mcp_category_has_a_tool() -> None:
    for category, names in CATEGORY_TO_TOOLS.items():
        assert names & EXPECTED_TOOLS, f"No MCP tool covers {category}"


def test_generation_category_has_dedicated_tools() -> None:
    assert CATEGORY_TO_TOOLS["generation"] == {
        "generate_sail",
        "generate_solution_design",
        "generate_test_suite",
    }
