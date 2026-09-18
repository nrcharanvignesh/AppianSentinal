from __future__ import annotations

import inspect
import zipfile
from pathlib import Path

import pytest
from lxml import etree
from pydantic import ValidationError

from appian_sentinel.config import settings
from appian_sentinel.mcp_server import cache, server, tools
from appian_sentinel.mcp_server.models import (
    DependencyDirection,
    DependencyGraphRequest,
    GenerateFullZipRequest,
    InspectSailRequest,
    ListObjectsRequest,
    NormalizeRequirementRequest,
    ResolveObjectRequest,
    RunStaticTestsRequest,
    ValidateSailRequest,
    ValidateTestCoverageRequest,
)
from appian_sentinel.models.appian_objects import ConnectedSystem, Constant, Interface
from appian_sentinel.models.codebase import CodebaseMap
from appian_sentinel.models.test_case import (
    TestCase as AppianTestCase,
)
from appian_sentinel.models.test_case import (
    TestStep as AppianTestStep,
)
from appian_sentinel.models.test_case import (
    TestSuite as AppianTestSuite,
)


@pytest.fixture
def workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, CodebaseMap]:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    content_dir = export_dir / "content"
    content_dir.mkdir()
    for uuid, tag, definition in (
        ("interface-1", "interface", 'a!textField(label: "Name")'),
        ("interface-2", "interface", 'if(ri!enabled == true(), "yes", "no")'),
        ("constant-1", "constant", "50"),
    ):
        (content_dir / f"{uuid}.xml").write_text(
            (
                f"<contentHaul><{tag}><uuid>{uuid}</uuid>"
                f"<definition>{definition}</definition></{tag}></contentHaul>"
            ),
            encoding="utf-8",
        )
    first = Interface(
        uuid="interface-1",
        name="Shared Name",
        description="First interface",
        definition='a!textField(label: "Name")',
        file_path=str(content_dir / "interface-1.xml"),
    )
    second = Interface(
        uuid="interface-2",
        name="Shared Name",
        description="Second interface",
        definition='if(ri!enabled == true(), "yes", "no")',
        file_path=str(content_dir / "interface-2.xml"),
    )
    constant = Constant(
        uuid="constant-1",
        name="Limit",
        value="50",
        file_path=str(content_dir / "constant-1.xml"),
    )
    codebase = CodebaseMap(
        objects={obj.uuid: obj for obj in (first, second, constant)},
        dependencies={"interface-1": {"constant-1"}},
        reverse_dependencies={"constant-1": {"interface-1"}},
        by_type={
            "interface": ["interface-1", "interface-2"],
            "constant": ["constant-1"],
        },
    )
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    monkeypatch.setattr(cache, "get_codebase", lambda path, **kwargs: codebase)
    return export_dir, codebase


@pytest.mark.asyncio
async def test_server_preserves_blueprint_and_original_tool_names() -> None:
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert {
        "analyze_appian_zip",
        "search_objects",
        "get_object",
        "read_ado_work_item",
        "apply_object_change",
        "generate_patch_zip",
    } <= names
    assert {
        "list_objects",
        "resolve_object",
        "get_dependency_graph",
        "inspect_sail",
        "validate_sail",
        "validate_object",
        "validate_workspace",
        "normalize_requirement",
        "validate_test_coverage",
        "run_static_tests",
        "workspace_status",
        "history_log",
        "history_diff",
        "history_commit",
        "history_restore",
        "apply_sail_edit",
        "bulk_add_tests",
        "generate_full_zip",
    } <= names


@pytest.mark.asyncio
async def test_new_tool_contracts_are_typed() -> None:
    registered = {tool.name: tool for tool in await server.mcp.list_tools()}
    for name in (
        "list_objects",
        "resolve_object",
        "get_dependency_graph",
        "inspect_sail",
        "validate_sail",
        "validate_object",
        "validate_workspace",
        "normalize_requirement",
        "validate_test_coverage",
        "run_static_tests",
        "generate_full_zip",
    ):
        assert registered[name].inputSchema["properties"]["request"]
        assert registered[name].outputSchema is not None
    for name in (
        "workspace_status",
        "history_log",
        "history_diff",
        "history_commit",
        "history_restore",
        "apply_sail_edit",
        "bulk_add_tests",
    ):
        assert registered[name].inputSchema["properties"]["export_dir"]
        assert registered[name].outputSchema is not None


def test_original_python_signatures_remain_compatible() -> None:
    assert list(inspect.signature(server.analyze_appian_zip).parameters) == ["zip_path"]
    assert list(inspect.signature(server.search_objects).parameters) == [
        "export_dir",
        "query",
        "types",
        "limit",
    ]
    assert list(inspect.signature(server.get_object).parameters) == ["export_dir", "uuid"]
    assert list(inspect.signature(server.read_ado_work_item).parameters) == [
        "organization",
        "project",
        "work_item_id",
        "pat",
    ]
    assert list(inspect.signature(server.apply_object_change).parameters) == ["export_dir", "obj"]
    assert list(inspect.signature(server.generate_patch_zip).parameters) == [
        "export_dir",
        "object_uuids",
        "output_path",
    ]


def test_list_objects_filters_and_paginates(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    first = tools.list_objects(
        ListObjectsRequest(export_dir=str(export_dir), type="interface", page_size=1)
    )
    second = tools.list_objects(
        ListObjectsRequest(
            export_dir=str(export_dir),
            type="interface",
            page_size=1,
            cursor=first.next_cursor,
        )
    )
    assert first.total == 2
    assert len(first.items) == 1
    assert len(second.items) == 1
    assert first.items[0].uuid != second.items[0].uuid


def test_invalid_object_type_filter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ListObjectsRequest(export_dir="export", type="not_a_real_type")


def test_existing_search_rejects_invalid_type_filter(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    with pytest.raises(ValueError, match="Unknown object type"):
        tools.search_objects(str(export_dir), "", ["not_a_real_type"])


def test_resolve_object_reports_ambiguity(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    result = tools.resolve_object(
        ResolveObjectRequest(export_dir=str(export_dir), identity="shared name")
    )
    assert result.status == "ambiguous"
    assert [candidate.uuid for candidate in result.candidates] == [
        "interface-1",
        "interface-2",
    ]


def test_dependency_graph_supports_forward_and_reverse(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    forward = tools.get_dependency_graph(
        DependencyGraphRequest(
            export_dir=str(export_dir),
            root_uuids=["interface-1"],
            direction=DependencyDirection.FORWARD,
        )
    )
    reverse = tools.get_dependency_graph(
        DependencyGraphRequest(
            export_dir=str(export_dir),
            root_uuids=["constant-1"],
            direction=DependencyDirection.REVERSE,
        )
    )
    assert [(edge.source, edge.target) for edge in forward.edges] == [
        ("interface-1", "constant-1")
    ]
    assert [(edge.source, edge.target) for edge in reverse.edges] == [
        ("interface-1", "constant-1")
    ]


def test_inspect_and_validate_sail() -> None:
    inspection = tools.inspect_sail(
        InspectSailRequest(
            source='if(ri!enabled, "yes", "no")',
            include_ast=True,
        )
    )
    validation = tools.validate_sail(
        ValidateSailRequest(source='if(ri!enabled == true(), "yes", "no")')
    )
    assert inspection.ast is not None
    assert inspection.domain_variables == {"ri": ["enabled"]}
    assert validation.is_valid is False
    forbidden = next(
        item for item in validation.diagnostics if "Forbidden operator" in item.message
    )
    assert (forbidden.line, forbidden.column, forbidden.end_column) == (1, 15, 17)
    assert (forbidden.start_offset, forbidden.end_offset) == (14, 16)


def test_paths_are_sandboxed_and_redacted(
    workspace: tuple[Path, CodebaseMap],
    tmp_path: Path,
) -> None:
    export_dir, _ = workspace
    result = tools.get_object(str(export_dir), "interface-1")
    assert result["file_path"] == "export/content/interface-1.xml"
    with pytest.raises(ValueError, match="workspace root"):
        tools.get_object(str(tmp_path.parent), "interface-1")


def test_object_secrets_are_redacted(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, codebase = workspace
    connected_system = ConnectedSystem(
        uuid="system-1",
        name="Payments",
        properties={"password": "do-not-return", "region": "us"},
    )
    codebase.objects[connected_system.uuid] = connected_system
    result = tools.get_object(str(export_dir), connected_system.uuid)
    assert result["properties"] == {"password": "[REDACTED]", "region": "us"}


def test_normalize_requirement_and_validate_coverage() -> None:
    normalized = tools.normalize_requirement(
        NormalizeRequirementRequest(
            text=(
                "Submit request\n"
                "As a requester, I want to submit a request, so that it can be approved.\n"
                "AC-1: Request is saved\n"
                "Given valid data\n"
                "When I submit\n"
                "Then the request is saved"
            )
        )
    )
    suite = AppianTestSuite(
        name="Submit",
        test_cases=[
            AppianTestCase(
                id="TC-1",
                name="Submit valid request",
                linked_ac="AC-1",
            )
        ],
    )
    coverage = tools.validate_test_coverage(
        ValidateTestCoverageRequest(
            requirement=normalized.requirement,
            suite=suite,
        )
    )
    assert normalized.requirement.as_a == "requester"
    assert normalized.requirement.acceptance_criteria[0].then == "the request is saved"
    assert coverage.is_complete is True


@pytest.mark.asyncio
async def test_static_tests_report_explicit_static_mode(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    suite = AppianTestSuite(
        name="Static",
        test_cases=[
            AppianTestCase(
                id="TC-1",
                name="Validate interface",
                steps=[
                    AppianTestStep(
                        action="Validate",
                        input_data={"object_name": "Shared Name"},
                    )
                ],
            )
        ],
    )
    result = await tools.run_static_tests(
        RunStaticTestsRequest(export_dir=str(export_dir), suite=suite)
    )
    assert result.execution_mode == "static"
    assert result.failed == 1


def test_workspace_history_tools_cover_status_log_diff_commit_and_restore(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    baseline = tools.history_commit(
        str(export_dir),
        actor="agent",
        requirement="REQ-24",
        message="baseline",
    )
    target = export_dir / "content" / "interface-1.xml"
    target.write_text("<api_key>do-not-return</api_key>", encoding="utf-8")
    dirty = tools.workspace_status(str(export_dir))
    assert dirty.initialized is True
    assert dirty.is_clean is False
    assert dirty.working_changes[0].path == "content/interface-1.xml"

    changed = tools.history_commit(
        str(export_dir),
        actor="agent",
        requirement="REQ-25",
        message="change",
        expected_revision=baseline.revision.hash,
    )
    history = tools.history_log(str(export_dir), limit=10)
    diff = tools.history_diff(
        str(export_dir),
        baseline.revision.hash,
        changed.revision.hash,
    )
    assert [item.hash for item in history.revisions[:2]] == [
        changed.revision.hash,
        baseline.revision.hash,
    ]
    assert "do-not-return" not in diff.changes[0].unified_diff
    assert "[REDACTED]" in diff.changes[0].unified_diff

    restored = tools.history_restore(
        str(export_dir),
        baseline.revision.hash,
        actor="agent",
        requirement="REQ-25",
        expected_revision=changed.revision.hash,
    )
    assert restored.restored_from == baseline.revision.hash
    assert "contentHaul" in target.read_text(encoding="utf-8")


def test_apply_sail_edit_validates_before_write(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    target = export_dir / "content" / "interface-1.xml"
    before = target.read_bytes()
    rejected = tools.apply_sail_edit(
        str(export_dir),
        "interface-1",
        'if(1 == 1, "yes", "no")',
    )
    assert rejected.status == "rejected"
    assert target.read_bytes() == before
    assert rejected.diagnostics[0].start_offset == 5

    updated = tools.apply_sail_edit(
        str(export_dir),
        "interface-1",
        'a!textField(label: "Updated")',
    )
    assert updated.status == "updated"
    assert "Updated" in target.read_text(encoding="utf-8")


def test_bulk_add_tests_previews_then_updates(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    target = export_dir / "content" / "interface-1.xml"
    before = target.read_bytes()
    test_nodes = ['<testCase name="valid"><assert>true</assert></testCase>']
    preview = tools.bulk_add_tests(
        str(export_dir),
        ["interface-1"],
        test_nodes,
        True,
    )
    assert preview.status == "preview"
    assert target.read_bytes() == before

    updated = tools.bulk_add_tests(
        str(export_dir),
        ["interface-1"],
        test_nodes,
        False,
    )
    tree = etree.parse(str(target))
    assert updated.status == "updated"
    assert len(tree.xpath("//*[local-name()='testCase']")) == 1


def test_full_zip_packages_without_mutating_source(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    meta = export_dir / "META-INF"
    meta.mkdir()
    manifest = meta / "MANIFEST.MF"
    manifest.write_text("Manifest-Version: 1.0\n", encoding="ascii")
    (meta / "export.log").write_text("Success (0):\n", encoding="ascii")
    before = {
        path.relative_to(export_dir).as_posix(): path.read_bytes()
        for path in export_dir.rglob("*")
        if path.is_file()
    }
    output = export_dir.parent / "full.zip"
    result = tools.generate_full_zip(
        GenerateFullZipRequest(
            export_dir=str(export_dir),
            output_path=str(output),
        )
    )
    assert result.status == "ok"
    assert result.is_valid is True
    assert output.is_file()
    assert {
        path.relative_to(export_dir).as_posix(): path.read_bytes()
        for path in export_dir.rglob("*")
        if path.is_file()
    } == before
    with zipfile.ZipFile(output) as archive:
        assert "META-INF/MANIFEST.MF" in archive.namelist()


def test_full_zip_rejects_output_inside_export(
    workspace: tuple[Path, CodebaseMap],
) -> None:
    export_dir, _ = workspace
    with pytest.raises(ValueError, match="outside export_dir"):
        tools.generate_full_zip(
            GenerateFullZipRequest(
                export_dir=str(export_dir),
                output_path=str(export_dir / "unsafe.zip"),
            )
        )
