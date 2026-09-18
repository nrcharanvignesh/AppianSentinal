from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.generator import xml_writer
from appian_sentinel.services.workspace import WorkspaceHistoryService
from appian_sentinel.web.routes import _sessions

UUIDS = (
    "_a-11111111-1111-8000-1111-111111111111_100001",
    "_a-22222222-2222-8000-2222-222222222222_100002",
)


def _write_rule(path: Path, uuid: str, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "<contentHaul><versionUuid>version</versionUuid><rule>"
            f"<name>{name}</name><uuid>{uuid}</uuid><definition>1</definition>"
            "<testCase><name>Original</name><description>Keep this</description>"
            "<inputs><input><name>value</name><value>1</value></input></inputs>"
            "<expected>1</expected></testCase></rule></contentHaul>"
        ),
        encoding="utf-8",
    )


@pytest.fixture
def loaded_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[Path], str]:
    monkeypatch.delenv("SENTINEL_API_TOKEN", raising=False)
    _sessions.clear()
    paths = [tmp_path / "content" / f"{uuid}.xml" for uuid in UUIDS]
    for index, (path, uuid) in enumerate(zip(paths, UUIDS, strict=True), start=1):
        _write_rule(path, uuid, f"APP_Rule_{index}")

    state = AgentState()
    state.export_dir = str(tmp_path)
    state.codebase_map = {
        "objects": {
            uuid: {
                "uuid": uuid,
                "name": f"APP_Rule_{index}",
                "object_type": "expression_rule",
                "definition": "1",
                "rule_inputs": [],
                "file_path": str(path),
            }
            for index, (uuid, path) in enumerate(
                zip(UUIDS, paths, strict=True),
                start=1,
            )
        }
    }
    session_id = "rollback-proof"
    _sessions[session_id] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }
    WorkspaceHistoryService(tmp_path).create_baseline(
        actor="system",
        requirement="",
    )
    from appian_sentinel.main import app

    return TestClient(app, raise_server_exceptions=True), paths, session_id


def test_bulk_apply_failure_restores_all_objects_and_history_index(
    loaded_client: tuple[TestClient, list[Path], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, paths, session_id = loaded_client
    original_files = {path: path.read_bytes() for path in paths}
    index_path = paths[0].parents[1] / ".history" / "index.json"
    original_index = index_path.read_bytes()
    real_write: Callable[[Path, bytes], None] = xml_writer._atomic_write_xml
    call_count = 0

    def fail_second_apply(path: Path, data: bytes) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("forced second-object write failure")
        real_write(path, data)

    monkeypatch.setattr(xml_writer, "_atomic_write_xml", fail_second_apply)
    payload = {
        "object_uuids": list(UUIDS),
        "tests": [
            {
                "name": "Replacement",
                "description": "Must be atomic",
                "inputs": {"value": 2},
                "expected": 2,
            }
        ],
        "preview": False,
    }

    with pytest.raises(OSError, match="forced second-object write failure"):
        client.post(
            f"/api/tests/bulk?session_id={session_id}",
            json=payload,
        )

    assert call_count == 4
    assert {path: path.read_bytes() for path in paths} == original_files
    assert index_path.read_bytes() == original_index
    assert WorkspaceHistoryService(paths[0].parents[1]).staged_changes() == []
