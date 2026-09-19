from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.config import settings
from appian_sentinel.models.user_story import (
    ClarifyingQuestion,
    QuestionPriority,
    UserStory,
)
from appian_sentinel.services.workspace import WorkspaceHistoryService
from appian_sentinel.web.routes import _sessions

UUID = "_a-11111111-1111-8000-1111-111111111111_100001"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("SENTINEL_API_TOKEN", raising=False)
    monkeypatch.delenv("SENTINEL_DESKTOP_OWNERSHIP_ID", raising=False)
    _sessions.clear()
    from appian_sentinel.main import app

    return TestClient(app)


def _load_session(tmp_path: Path, session_id: str = "desktop") -> tuple[Path, str]:
    path = tmp_path / "content" / f"{UUID}.xml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"""<contentHaul>
<versionUuid>version</versionUuid>
<rule>
<name>APP_Test</name><uuid>{UUID}</uuid><definition>1</definition>
<testCase>
<name>Old</name><description>Old description</description>
<inputs><input><name>value</name><value>1</value></input></inputs>
<expected>1</expected>
</testCase>
</rule>
</contentHaul>
""",
        encoding="utf-8",
    )
    state = AgentState()
    state.export_dir = str(tmp_path)
    state.codebase_map = {
        "appian_version": "26.1",
        "objects": {
            UUID: {
                "uuid": UUID,
                "name": "APP_Test",
                "object_type": "expression_rule",
                "definition": "1",
                "rule_inputs": [],
                "file_path": str(path),
            },
        },
    }
    _sessions[session_id] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }
    WorkspaceHistoryService(tmp_path).create_baseline(
        actor="system",
        requirement="",
    )
    return path, session_id


def test_health_echoes_ownership_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.get("/api/health").json() == {
        "status": "ok",
        "ownership_id": None,
    }
    monkeypatch.setenv("SENTINEL_DESKTOP_OWNERSHIP_ID", "desktop-uuid")
    assert client.get("/api/health").json()["ownership_id"] == "desktop-uuid"


def test_optional_token_middleware(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.get("/api/status").status_code == 200
    monkeypatch.setenv("SENTINEL_API_TOKEN", "secret")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    response = client.get(
        "/api/status",
        headers={"X-Sentinel-Token": "secret"},
    )
    assert response.status_code == 200


def test_history_endpoints_use_loaded_export(
    client: TestClient,
    tmp_path: Path,
) -> None:
    path, session_id = _load_session(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace(">1<", ">2<", 1), encoding="utf-8")
    response = client.post(
        f"/api/history/commit?session_id={session_id}",
        json={"message": "Edit rule", "actor": "tester", "requirement_id": "REQ-1"},
    )
    assert response.status_code == 200
    revision = response.json()
    history = client.get(f"/api/history?session_id={session_id}").json()
    assert history[0]["requirement_id"] == "REQ-1"
    baseline = history[-1]["hash"]
    diff = client.get(
        f"/api/history/diff?session_id={session_id}&from={baseline}&to={revision['hash']}"
    )
    assert diff.status_code == 200
    assert diff.json()[0]["object_id"] == UUID


def test_bulk_tests_preview_then_atomic_apply(
    client: TestClient,
    tmp_path: Path,
) -> None:
    path, session_id = _load_session(tmp_path)
    original = path.read_bytes()
    payload = {
        "object_uuids": [UUID],
        "tests": [{
            "name": "New",
            "description": "New description",
            "inputs": {"value": 2},
            "expected": 2,
        }],
        "preview": True,
    }
    preview = client.post(f"/api/tests/bulk?session_id={session_id}", json=payload)
    assert preview.status_code == 200
    assert preview.json()["diff"][UUID]
    assert path.read_bytes() == original

    payload["preview"] = False
    applied = client.post(f"/api/tests/bulk?session_id={session_id}", json=payload)
    assert applied.status_code == 200
    assert path.read_bytes() != original
    tests = client.get(f"/api/objects/{UUID}/tests?session_id={session_id}").json()
    assert tests["tests"][0]["name"] == "New"
    assert tests["tests"][0]["inputs"] == {"value": "2"}


async def test_high_priority_questions_pause_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = Orchestrator(AgentState())
    questions = [
        ClarifyingQuestion(id="Q-1", question="Blocking?", priority=QuestionPriority.HIGH),
        ClarifyingQuestion(id="Q-2", question="Optional?", priority=QuestionPriority.LOW),
    ]
    monkeypatch.setattr(
        "appian_sentinel.agent.orchestrator.StoryAnalyzer.generate_clarifying_questions",
        AsyncMock(return_value=questions),
    )
    ask_user = AsyncMock()
    monkeypatch.setattr(orchestrator, "ask_user", ask_user)

    await orchestrator._pause_for_high_priority_questions(UserStory(title="Story"))

    ask_user.assert_awaited_once_with(["Blocking?"])


def test_package_rebuilds_zip_from_loaded_export(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path / "ws")
    (tmp_path / "ws").mkdir()
    _load_session(tmp_path)
    packed = client.post("/api/package?session_id=desktop")
    assert packed.status_code == 200, packed.text
    assert packed.json()["has_output_zip"] is True
    downloaded = client.get("/api/download?session_id=desktop")
    assert downloaded.status_code == 200
    assert downloaded.content[:2] == b"PK"
