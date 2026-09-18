from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.models.workspace import Revision
from appian_sentinel.services.workspace import WorkspaceHistoryService
from appian_sentinel.web.routes import _sessions

UUID = "_a-11111111-1111-8000-1111-111111111111_100001"


def _xml(definition: str = "1") -> str:
    return (
        "<contentHaul><versionUuid>version</versionUuid><rule>"
        f"<name>APP_Test</name><uuid>{UUID}</uuid>"
        f"<definition>{definition}</definition>"
        "<testCase><name>Old</name><description>Old test</description>"
        "<inputs><input><name>value</name><value>1</value></input></inputs>"
        "<expected>1</expected></testCase>"
        "</rule></contentHaul>"
    )


def _loaded_client(tmp_path: Path) -> tuple[TestClient, Path, AgentState]:
    path = tmp_path / "content" / f"{UUID}.xml"
    path.parent.mkdir(parents=True)
    path.write_text(_xml(), encoding="utf-8")
    state = AgentState()
    state.export_dir = str(tmp_path)
    state.user_story = {"title": "Story", "source_id": "REQ-24"}
    state.codebase_map = {
        "objects": {
            UUID: {
                "uuid": UUID,
                "name": "APP_Test",
                "object_type": "expression_rule",
                "definition": "1",
                "rule_inputs": [],
                "file_path": str(path),
            }
        }
    }
    _sessions.clear()
    _sessions["history"] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }
    WorkspaceHistoryService(tmp_path).create_baseline(
        actor="system",
        requirement="REQ-24",
    )
    from appian_sentinel.main import app

    return TestClient(app), path, state


def _assert_revision(
    service: WorkspaceHistoryService,
    revision: Revision,
    *,
    actor: str,
    requirement: str,
    relative_path: str,
    before: bytes,
    after: bytes,
) -> None:
    assert revision.actor == actor
    assert revision.requirement == requirement
    assert revision.timestamp.tzinfo is not None
    assert revision.parent is not None
    changes = service.diff(revision.parent, revision.hash)
    change = next(item for item in changes if item.path == relative_path)
    assert change.before_hash == hashlib.sha256(before).hexdigest()
    assert change.after_hash == hashlib.sha256(after).hexdigest()


def test_object_save_records_complete_revision(tmp_path: Path) -> None:
    client, path, _ = _loaded_client(tmp_path)
    service = WorkspaceHistoryService(tmp_path)
    before = path.read_bytes()
    count_before = len(service.log())

    response = client.put(
        f"/api/objects/{UUID}?session_id=history",
        json={"definition": "2"},
    )

    assert response.status_code == 200, response.text
    assert len(service.log()) == count_before + 1
    _assert_revision(
        service,
        service.log()[0],
        actor="desktop",
        requirement="REQ-24",
        relative_path=f"content/{UUID}.xml",
        before=before,
        after=path.read_bytes(),
    )


def test_bulk_test_apply_records_complete_revision(tmp_path: Path) -> None:
    client, path, _ = _loaded_client(tmp_path)
    service = WorkspaceHistoryService(tmp_path)
    before = path.read_bytes()

    response = client.post(
        "/api/tests/bulk?session_id=history",
        json={
            "object_uuids": [UUID],
            "tests": [
                {
                    "name": "New",
                    "description": "New test",
                    "inputs": {"value": 2},
                    "expected": 2,
                }
            ],
            "preview": False,
        },
    )

    assert response.status_code == 200, response.text
    _assert_revision(
        service,
        service.log()[0],
        actor="desktop",
        requirement="REQ-24",
        relative_path=f"content/{UUID}.xml",
        before=before,
        after=path.read_bytes(),
    )


def test_history_restore_records_complete_revision(tmp_path: Path) -> None:
    client, path, _ = _loaded_client(tmp_path)
    service = WorkspaceHistoryService(tmp_path)
    baseline = service.log()[0]
    original = path.read_bytes()
    path.write_text(_xml("2"), encoding="utf-8")
    changed = path.read_bytes()
    service.stage(f"content/{UUID}.xml")
    dirty = service.commit(
        actor="desktop",
        requirement="REQ-24",
        message="change",
    )

    response = client.post(
        "/api/history/restore?session_id=history",
        json={"revision": baseline.hash},
    )

    assert response.status_code == 200
    restored = service.log()[0]
    assert restored.parent == dirty.hash
    _assert_revision(
        service,
        restored,
        actor="desktop",
        requirement="REQ-24",
        relative_path=f"content/{UUID}.xml",
        before=changed,
        after=original,
    )
    assert path.read_bytes() == original


def test_agent_generated_write_records_complete_revision(tmp_path: Path) -> None:
    _, path, state = _loaded_client(tmp_path)
    service = WorkspaceHistoryService(tmp_path)
    before = path.read_bytes()
    count_before = len(service.log())
    agent = Orchestrator(state)
    agent._export_dir = tmp_path

    output = agent._write_object_xml(
        {
            "type": "rule",
            "name": "APP_Test",
            "uuid": UUID,
            "action": "modify",
            "definition": "2",
        }
    )

    assert output == path
    assert len(service.log()) == count_before + 1
    _assert_revision(
        service,
        service.log()[0],
        actor="agent",
        requirement="REQ-24",
        relative_path=f"content/{UUID}.xml",
        before=before,
        after=path.read_bytes(),
    )
