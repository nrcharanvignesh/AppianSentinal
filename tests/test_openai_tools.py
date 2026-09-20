from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from appian_sentinel.config import settings
from appian_sentinel.mcp_server import cache, openai_tools, server
from appian_sentinel.services.workspace import WorkspaceHistoryService

FLAT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "properties": {
        "export_dir": {"title": "Export Dir", "type": "string"},
        "query": {"title": "Query", "type": "string"},
        "limit": {"default": 50, "type": "integer"},
    },
    "required": ["export_dir", "query"],
    "title": "search_objectsArguments",
    "type": "object",
}

WRAPPED_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {
        "ListObjectsRequest": {
            "additionalProperties": False,
            "properties": {
                "export_dir": {"type": "string"},
                "type": {"$ref": "#/$defs/ObjectType"},
                "page_size": {"default": 50, "type": "integer"},
            },
            "required": ["export_dir"],
            "type": "object",
        },
        "ObjectType": {"enum": ["interface", "constant"], "type": "string"},
    },
    "properties": {"request": {"$ref": "#/$defs/ListObjectsRequest"}},
    "required": ["request"],
    "type": "object",
}

OPTIONAL_PATH_SCHEMA: dict[str, Any] = {
    "$defs": {
        "InspectSailRequest": {
            "properties": {
                "source": {"type": "string"},
                "export_dir": {"type": "string"},
                "object_uuid": {"type": "string"},
            },
            "required": [],
            "type": "object",
        }
    },
    "properties": {"request": {"$ref": "#/$defs/InspectSailRequest"}},
    "required": ["request"],
    "type": "object",
}

EXCLUDED_TOOLS = (
    "analyze_appian_zip",
    "generate_full_zip",
    "generate_patch_zip",
    "generate_sail",
    "generate_solution_design",
    "generate_test_suite",
    "history_commit",
    "history_restore",
    "normalize_requirement",
    "read_ado_work_item",
)


@dataclass(frozen=True)
class StubTool:
    name: str
    description: str
    inputSchema: dict[str, Any]  # noqa: N815 - mirrors the MCP Tool attribute


@dataclass
class StubMcp:
    tools: list[StubTool]
    result: object = None
    error: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def list_tools(self) -> list[StubTool]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.result


def install(
    monkeypatch: pytest.MonkeyPatch,
    tools: list[StubTool],
    *,
    result: object = None,
    error: Exception | None = None,
) -> StubMcp:
    stub = StubMcp(tools=tools, result=result, error=error)
    monkeypatch.setattr(server, "mcp", stub)
    return stub


def flat_tool(name: str = "search_objects") -> StubTool:
    return StubTool(name=name, description="Search objects.", inputSchema=FLAT_SCHEMA)


def wrapped_tool(name: str = "list_objects") -> StubTool:
    return StubTool(name=name, description="List objects.", inputSchema=WRAPPED_SCHEMA)


async def test_allowlist_covers_typed_crud_and_excludes_unrelated_tools() -> None:
    registered = {tool.name for tool in await server.mcp.list_tools()}
    assert openai_tools.ALLOWED_CHAT_TOOLS <= registered
    assert len(openai_tools.ALLOWED_CHAT_TOOLS) == 157
    assert all(
        len(tool_set) == 34
        for tool_set in (
            openai_tools.TYPED_CREATE_TOOLS,
            openai_tools.TYPED_GET_TOOLS,
            openai_tools.TYPED_UPDATE_TOOLS,
            openai_tools.TYPED_DELETE_TOOLS,
        )
    )
    for name in EXCLUDED_TOOLS:
        assert name in registered
        assert not openai_tools.is_allowed_chat_tool(name)
    assert openai_tools.GENERAL_WRITE_TOOLS <= openai_tools.ALLOWED_CHAT_TOOLS
    assert "create_interface" in openai_tools.ALLOWED_CHAT_TOOLS
    assert "update_constant" in openai_tools.ALLOWED_CHAT_TOOLS
    assert "delete_record_type" in openai_tools.ALLOWED_CHAT_TOOLS


async def test_list_chat_tools_filters_denied_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = [
        StubTool(name=name, description="denied", inputSchema=FLAT_SCHEMA)
        for name in EXCLUDED_TOOLS
    ]
    install(monkeypatch, [flat_tool(), wrapped_tool(), *denied])

    chat_tools = await openai_tools.list_chat_tools()

    names = [tool["function"]["name"] for tool in chat_tools]
    assert names == ["search_objects", "list_objects"]
    assert all(tool["type"] == "function" for tool in chat_tools)


async def test_list_chat_tools_preserves_schema_and_strips_schema_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, [wrapped_tool()])

    parameters = (await openai_tools.list_chat_tools())[0]["function"]["parameters"]

    assert "$schema" not in parameters
    assert parameters["properties"] == {"request": {"$ref": "#/$defs/ListObjectsRequest"}}
    assert parameters["$defs"]["ObjectType"]["enum"] == ["interface", "constant"]
    assert parameters["$defs"]["ListObjectsRequest"] == WRAPPED_SCHEMA["$defs"]["ListObjectsRequest"]
    assert "$schema" in WRAPPED_SCHEMA


def test_normalize_wraps_flat_keys_only_for_request_schemas() -> None:
    wrapped = openai_tools.normalize_tool_arguments(
        WRAPPED_SCHEMA, '{"export_dir": "/tmp/x", "page_size": 10}'
    )
    assert wrapped == {"request": {"export_dir": "/tmp/x", "page_size": 10}}

    already = openai_tools.normalize_tool_arguments(
        WRAPPED_SCHEMA, {"request": {"export_dir": "/tmp/x"}}
    )
    assert already == {"request": {"export_dir": "/tmp/x"}}
    mixed = openai_tools.normalize_tool_arguments(
        WRAPPED_SCHEMA, {"request": {"export_dir": "/tmp/x"}, "unexpected": True}
    )
    assert mixed == {"request": {"export_dir": "/tmp/x"}, "unexpected": True}

    flat = openai_tools.normalize_tool_arguments(
        FLAT_SCHEMA, '{"query": "rule", "limit": 5}'
    )
    assert flat == {"query": "rule", "limit": 5}

    assert openai_tools.normalize_tool_arguments(FLAT_SCHEMA, "") == {}
    assert openai_tools.normalize_tool_arguments(FLAT_SCHEMA, None) == {}


@pytest.mark.parametrize("arguments", ["[1, 2]", '"text"', "not json", [1, 2], 7])
def test_normalize_rejects_non_object_arguments(arguments: object) -> None:
    with pytest.raises(ValueError):
        openai_tools.normalize_tool_arguments(FLAT_SCHEMA, arguments)


async def test_invoke_rejects_denied_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = install(monkeypatch, [flat_tool()])

    result = await openai_tools.invoke_chat_tool(
        "history_restore", {"revision_hash": "x"}, "/session/export"
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "not_allowed"
    assert stub.calls == []


async def test_invoke_rejects_unknown_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, [])

    result = await openai_tools.invoke_chat_tool("get_object", {}, "/session/export")

    assert result["ok"] is False
    assert result["error"]["code"] == "unknown_tool"


async def test_invoke_injects_export_dir_and_ignores_model_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = install(monkeypatch, [flat_tool()], result={"total": 0})

    result = await openai_tools.invoke_chat_tool(
        "search_objects",
        {"export_dir": "C:/attacker", "output_path": "C:/evil.zip", "query": "rule"},
        "/session/export",
    )

    assert result["ok"] is True
    assert stub.calls == [
        (
            "search_objects",
            {"query": "rule", "export_dir": "/session/export"},
        )
    ]


async def test_invoke_injects_export_dir_inside_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = install(monkeypatch, [wrapped_tool()], result={"objects": []})

    await openai_tools.invoke_chat_tool(
        "list_objects",
        '{"export_dir": "../../etc", "type": "interface"}',
        "/session/export",
    )

    assert stub.calls == [
        (
            "list_objects",
            {"request": {"type": "interface", "export_dir": "/session/export"}},
        )
    ]


async def test_invoke_leaves_optional_export_dir_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = StubTool(
        name="inspect_sail",
        description="Inspect SAIL.",
        inputSchema=OPTIONAL_PATH_SCHEMA,
    )
    stub = install(monkeypatch, [tool], result={"diagnostics": []})

    await openai_tools.invoke_chat_tool(
        "inspect_sail", {"source": "a!textField()"}, "/session/export"
    )

    assert stub.calls == [("inspect_sail", {"request": {"source": "a!textField()"}})]


async def test_invoke_rejects_non_object_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = install(monkeypatch, [flat_tool()])

    result = await openai_tools.invoke_chat_tool("search_objects", "[1]", "/session")

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
    assert stub.calls == []


async def test_invoke_returns_structured_error_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-abcdefgh12345678"
    install(
        monkeypatch,
        [flat_tool()],
        error=RuntimeError(f"upstream refused api_key: {secret}"),
    )

    result = await openai_tools.invoke_chat_tool(
        "search_objects", {"query": "rule"}, "/session/export"
    )

    assert result == {
        "ok": False,
        "tool": "search_objects",
        "error": {
            "code": "tool_error",
            "message": "RuntimeError: upstream refused api_key: ****",
        },
    }
    assert secret not in json.dumps(result)


async def test_invoke_masks_secrets_in_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-abcdefgh12345678"
    install(monkeypatch, [flat_tool()], result={"notes": [f"token {secret}"]})

    result = await openai_tools.invoke_chat_tool(
        "search_objects", {"query": "rule"}, "/session/export"
    )

    assert secret not in json.dumps(result)
    assert result["truncated"] is False


async def test_invoke_converts_content_blocks_to_json_safe_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Block:
        def model_dump(self, mode: str = "python") -> dict[str, Any]:
            return {"type": "text", "text": "ok"}

    install(monkeypatch, [flat_tool()], result=[Block()])

    result = await openai_tools.invoke_chat_tool(
        "search_objects", {"query": "rule"}, "/session/export"
    )

    assert result["result"] == [{"type": "text", "text": "ok"}]
    json.dumps(result)


async def test_invoke_truncates_large_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"rows": ["x" * 1000 for _ in range(100)]}
    install(monkeypatch, [flat_tool()], result=payload)

    result = await openai_tools.invoke_chat_tool(
        "search_objects", {"query": "rule"}, "/session/export"
    )

    assert result["truncated"] is True
    assert isinstance(result["result"], str)
    assert len(result["result"]) == openai_tools.MAX_RESULT_CHARS


RULE_UUID = "_a-11111111-1111-8000-1111-111111111111_100001"
CONSTANT_UUID = "_a-11111111-1111-8000-1111-111111111111_100002"
CREATED_UUID = "_a-22222222-2222-8000-2222-222222222222_100003"


@pytest.fixture
def crud_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    cache._MEM_CACHE.clear()
    export_dir = tmp_path / "export"
    content = export_dir / "content"
    application = export_dir / "application"
    metadata = export_dir / "META-INF"
    content.mkdir(parents=True)
    application.mkdir()
    metadata.mkdir()
    (content / f"{RULE_UUID}.xml").write_text(
        (
            "<contentHaul><versionUuid>version</versionUuid><rule>"
            f"<name>APP_Rule</name><uuid>{RULE_UUID}</uuid>"
            f"<definition>{CONSTANT_UUID}</definition></rule></contentHaul>"
        ),
        encoding="utf-8",
    )
    (content / f"{CONSTANT_UUID}.xml").write_text(
        (
            "<contentHaul><versionUuid>version</versionUuid><constant>"
            f"<name>APP_Constant</name><uuid>{CONSTANT_UUID}</uuid>"
            "<typedValue><type><name>Integer</name></type><value>1</value>"
            "</typedValue></constant></contentHaul>"
        ),
        encoding="utf-8",
    )
    (application / "app.xml").write_text(
        (
            "<applicationHaul><application><associatedObjects><globalIdMap>"
            "<item><type>content</type><uuids>"
            f"<uuid>{RULE_UUID}</uuid><uuid>{CONSTANT_UUID}</uuid>"
            "</uuids></item></globalIdMap></associatedObjects>"
            "</application></applicationHaul>"
        ),
        encoding="utf-8",
    )
    (metadata / "MANIFEST.MF").write_text(
        "Manifest-Version: 1.0\n", encoding="utf-8"
    )
    (metadata / "export.log").write_text(
        (
            "Success (2):\n"
            f'rule 1 {RULE_UUID} "APP_Rule"\n'
            f'constant 2 {CONSTANT_UUID} "APP_Constant"\n'
        ),
        encoding="utf-8",
    )
    WorkspaceHistoryService(export_dir).create_baseline(
        actor="system", requirement="", message="baseline"
    )
    return export_dir


async def test_chat_create_and_update_apply_directly(crud_export: Path) -> None:
    created = await openai_tools.invoke_chat_tool(
        "create_expression_rule",
        {
            "export_dir": "C:/outside",
            "name": "APP_ChatCreated",
            "fields": {"uuid": CREATED_UUID, "definition": "2"},
            "preview": True,
        },
        str(crud_export),
    )

    assert created["ok"] is True
    assert created["result"]["status"] == "created"
    created_path = crud_export / "content" / f"{CREATED_UUID}.xml"
    assert created_path.is_file()

    updated = await openai_tools.invoke_chat_tool(
        "update_expression_rule",
        {
            "request": {
                "export_dir": "../../outside",
                "object_uuid": CREATED_UUID,
                "fields": {"name": "APP_ChatUpdated"},
                "preview": True,
            }
        },
        str(crud_export),
    )

    assert updated["ok"] is True
    assert updated["result"]["status"] == "updated"
    assert "APP_ChatUpdated" in created_path.read_text(encoding="utf-8")


async def test_chat_delete_returns_pending_payload_without_mutating(
    crud_export: Path,
) -> None:
    target = crud_export / "content" / f"{CONSTANT_UUID}.xml"
    before = target.read_bytes()

    result = await openai_tools.invoke_chat_tool(
        "delete_constant",
        {
            "object_uuid": CONSTANT_UUID,
            "preview": False,
            "force": False,
        },
        str(crud_export),
    )

    assert result["ok"] is True
    pending = result["result"]
    assert pending == {
        "status": "pending_deletion",
        "pending_deletion": True,
        "applied": False,
        "tool": "delete_constant",
        "object": {
            "uuid": CONSTANT_UUID,
            "name": "APP_Constant",
            "type": "constant",
        },
        "reverse_dependencies": [RULE_UUID],
        "children": [],
        "confirmation": {
            "required": True,
            "action": "delete_typed_object",
            "slug": "constant",
            "object_uuid": CONSTANT_UUID,
            "preview": False,
            "force_required": True,
        },
    }
    assert target.read_bytes() == before


async def test_chat_write_cannot_redirect_outside_session(
    crud_export: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"

    result = await openai_tools.invoke_chat_tool(
        "create_expression_rule",
        {
            "export_dir": str(outside),
            "path": str(outside),
            "output_path": str(outside / "escape.xml"),
            "name": "APP_Safe",
            "fields": {"uuid": CREATED_UUID, "definition": "3"},
        },
        str(crud_export),
    )

    assert result["ok"] is True
    assert (crud_export / "content" / f"{CREATED_UUID}.xml").is_file()
    assert not outside.exists()
