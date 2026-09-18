from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from appian_sentinel.config import settings
from appian_sentinel.integrations import ado_client
from appian_sentinel.mcp_server import cache, server
from appian_sentinel.parser.codebase_map import build_codebase_map

SLIM_FIXTURE = Path(__file__).parent / "fixtures" / "reference_export"


def _write_fixture_zip(output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source_path in sorted(SLIM_FIXTURE.rglob("*")):
            if source_path.is_file():
                archive.write(
                    source_path,
                    source_path.relative_to(SLIM_FIXTURE).as_posix(),
                )


def test_analyze_and_generate_patch_blueprint_tools_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    cache._MEM_CACHE.clear()
    input_zip = tmp_path / "slim.zip"
    _write_fixture_zip(input_zip)
    direct = build_codebase_map(SLIM_FIXTURE)

    analysis = server.analyze_appian_zip(str(input_zip))
    analyzed_dir = tmp_path / analysis["export_dir"]
    analyzed = build_codebase_map(analyzed_dir)
    direct_counts = {
        object_type: len(uuids)
        for object_type, uuids in direct.by_type.items()
    }

    assert analyzed_dir.is_dir()
    assert analysis["total_objects"] == len(direct.objects)
    assert analysis["by_type"] == direct_counts
    assert {
        object_type: len(uuids)
        for object_type, uuids in analyzed.by_type.items()
    } == direct_counts

    selected = [
        next(uuid for uuid, obj in analyzed.objects.items() if obj.object_type.value == object_type)
        for object_type in ("process_model", "record_type")
    ]
    result = server.generate_patch_zip(
        analysis["export_dir"],
        selected,
        "slim-patch.zip",
    )
    output_zip = tmp_path / result["zip_path"]
    expected_members = {
        analyzed.objects[uuid].file_path
        for uuid in selected
    } | {"META-INF/export.log"}

    assert result["missing"] == []
    assert output_zip.is_file()
    assert zipfile.is_zipfile(output_zip)
    with zipfile.ZipFile(output_zip) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == expected_members


@pytest.mark.asyncio
async def test_read_ado_work_item_blueprint_tool_normalizes_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "id": 731,
        "url": "https://dev.azure.com/example/project/_apis/wit/workItems/731",
        "fields": {
            "System.Title": "Approve expense request",
            "System.Description": (
                "<p>As an approver, review R&amp;D expenses.</p>"
                "<div>Reject incomplete requests.<br>Keep an audit trail.</div>"
            ),
            "Microsoft.VSTS.Common.AcceptanceCriteria": (
                "<p>Given a complete request</p>"
                "<p>When it is approved</p>"
                "<p>Then the state is Approved</p>"
            ),
            "System.WorkItemType": "User Story",
            "System.State": "Active",
        },
    }
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload, request=request)

    original_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(_handler)

    def _mock_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(ado_client.httpx, "AsyncClient", _mock_client)
    result = await server.read_ado_work_item(
        "example",
        "Sentinel Project",
        731,
        "test-pat",
    )

    assert len(requests) == 1
    assert requests[0].url.params["api-version"] == "7.1"
    assert requests[0].url.params["$expand"] == "fields"
    assert requests[0].headers["Authorization"].startswith("Basic ")
    assert result == {
        "id": 731,
        "title": "Approve expense request",
        "description": (
            "As an approver, review R&D expenses.\n"
            "Reject incomplete requests.\nKeep an audit trail."
        ),
        "acceptance_criteria": (
            "Given a complete request\nWhen it is approved\n"
            "Then the state is Approved"
        ),
        "work_item_type": "User Story",
        "state": "Active",
        "url": "https://dev.azure.com/example/project/_apis/wit/workItems/731",
        "combined_text": (
            "# Approve expense request\n\n## Description\n"
            "As an approver, review R&D expenses.\n"
            "Reject incomplete requests.\nKeep an audit trail.\n"
            "\n## Acceptance Criteria\nGiven a complete request\n"
            "When it is approved\nThen the state is Approved"
        ),
    }
