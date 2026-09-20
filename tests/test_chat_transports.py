from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.analyzer import pdf_extractor
from appian_sentinel.config import settings
from appian_sentinel.mcp_server import cache
from appian_sentinel.models.user_story import AcceptanceCriterion, UserStory
from appian_sentinel.web.routes import _sessions
from appian_sentinel.web.websocket import ChatWebSocket


class FakeStructuredLLM:
    async def chat_structured(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: type[UserStory],
        model: str,
    ) -> UserStory:
        del response_schema, model
        assert "Submit a request" in messages[-1]["content"]
        return UserStory(
            title="Submit request",
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="AC-1",
                    description="Request is saved.",
                    then="the request is saved",
                )
            ],
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("SENTINEL_API_TOKEN", raising=False)
    _sessions.clear()
    fake = FakeStructuredLLM()
    monkeypatch.setattr(pdf_extractor.llm, "chat_structured", fake.chat_structured)
    from appian_sentinel.main import app

    return TestClient(app)


def test_websocket_chat_parses_message_and_streams_completion(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws?session_id=socket-proof") as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "state"

        websocket.send_text("Submit a request")
        frames = [websocket.receive_json() for _ in range(5)]

    messages = [
        frame["data"]
        for frame in frames
        if frame["type"] == "message"
    ]
    assert any(
        message["role"] == "user" and message["content"] == "Submit a request"
        for message in messages
    )
    assert any(
        message["role"] == "assistant"
        and message["content"] == "User story received and parsed. Starting the workflow ..."
        for message in messages
    )
    story = _sessions["socket-proof"]["state"].user_story
    assert story is not None
    assert story["source_kind"] == "chat"
    assert story["acceptance_criteria"][0]["then"] == "the request is saved"


@pytest.fixture
def token_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SENTINEL_API_TOKEN", "desktop-token")
    _sessions.clear()
    fake = FakeStructuredLLM()
    monkeypatch.setattr(pdf_extractor.llm, "chat_structured", fake.chat_structured)
    from appian_sentinel.main import app

    return TestClient(app)


def test_websocket_accepts_browser_token_subprotocol(token_client: TestClient) -> None:
    """A browser cannot send X-Sentinel-Token, so the token rides a subprotocol."""
    with token_client.websocket_connect(
        "/ws?session_id=browser-proof",
        subprotocols=["sentinel-token", "desktop-token"],
    ) as websocket:
        assert websocket.receive_json()["type"] == "state"


def test_websocket_still_accepts_header_token(token_client: TestClient) -> None:
    with token_client.websocket_connect(
        "/ws?session_id=header-proof",
        headers={"X-Sentinel-Token": "desktop-token"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "state"


@pytest.mark.parametrize(
    "subprotocols",
    [["sentinel-token", "wrong-token"], ["sentinel-token"], []],
)
def test_websocket_rejects_missing_or_wrong_token(
    token_client: TestClient,
    subprotocols: list[str],
) -> None:
    with pytest.raises(WebSocketDisconnect) as rejected:
        with token_client.websocket_connect(
            "/ws?session_id=reject-proof",
            subprotocols=subprotocols or None,
        ) as websocket:
            websocket.receive_json()
    assert rejected.value.code == 1008


def test_http_chat_fallback_returns_messages_and_parses_same_story(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat?session_id=http-proof",
        json={"message": "Submit a request"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Submit a request"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "User story received and parsed. Starting the workflow ..."
    story = _sessions["http-proof"]["state"].user_story
    assert story is not None
    assert story["source_kind"] == "chat"
    assert story["acceptance_criteria"][0]["then"] == "the request is saved"


def test_http_chat_reports_blocked_read_without_a_workspace(client: TestClient) -> None:
    response = client.post(
        "/api/chat?session_id=http-trace",
        json={"message": "Submit a request", "object_uuids": ["missing-uuid"]},
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert messages[0]["metadata"]["object_uuids"] == ["missing-uuid"]
    tool = next(item for item in messages if item["message_type"] == "tool")
    call = tool["metadata"]["tool_calls"][0]
    assert call["tool"] == "get_object"
    assert call["status"] == "blocked"
    # Nothing was read, so nothing may be presented as loaded.
    assert tool["metadata"]["objects"] == []
    assert "Could not read: missing-uuid." in tool["content"]


def test_http_chat_runs_the_real_read_tool_when_workspace_is_loaded(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    cache._MEM_CACHE.clear()
    uuid = "_a-11111111-1111-8000-1111-111111111111_100001"
    export_dir = tmp_path / "export"
    content = export_dir / "content"
    content.mkdir(parents=True)
    (content / f"{uuid}.xml").write_text(
        (
            "<contentHaul><rule>"
            f"<name>APP_Rule</name><uuid>{uuid}</uuid>"
            "<definition>1</definition></rule></contentHaul>"
        ),
        encoding="utf-8",
    )
    state = AgentState()
    state.export_dir = str(export_dir)
    _sessions["http-typed-trace"] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }
    response = client.post(
        "/api/chat?session_id=http-typed-trace",
        json={"message": "Submit a request", "object_uuids": [uuid]},
    )
    assert response.status_code == 200
    tool = next(item for item in response.json()["messages"] if item["message_type"] == "tool")
    call = tool["metadata"]["tool_calls"][0]
    assert call["tool"] == "get_object"
    assert call["status"] == "ok"
    assert call["object_name"] == "APP_Rule"
    # The identity comes back from the MCP read, not from a local guess.
    assert tool["metadata"]["objects"][0] == {
        "uuid": uuid,
        "name": "APP_Rule",
        "type": "expression_rule",
    }


def test_http_chat_reports_a_real_miss_for_an_unknown_uuid(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A UUID the export does not contain is reported as a failed read."""
    monkeypatch.setattr(settings, "sentinel_workspace", tmp_path)
    cache._MEM_CACHE.clear()
    export_dir = tmp_path / "export"
    (export_dir / "content").mkdir(parents=True)
    state = AgentState()
    state.export_dir = str(export_dir)
    _sessions["http-miss"] = {
        "state": state,
        "orchestrator": Orchestrator(state),
        "run_task": None,
    }

    response = client.post(
        "/api/chat?session_id=http-miss",
        json={"message": "Submit a request", "object_uuids": ["nope"]},
    )

    assert response.status_code == 200
    tool = next(item for item in response.json()["messages"] if item["message_type"] == "tool")
    call = tool["metadata"]["tool_calls"][0]
    assert call["status"] == "failed"
    assert "object_name" not in call
    assert tool["metadata"]["objects"] == []


class FakeSocket:
    """A socket that accepts a fixed number of frames, then breaks."""

    def __init__(self, frame_budget: int = 99) -> None:
        self.frames: list[dict[str, Any]] = []
        self._budget = frame_budget

    async def accept(self, subprotocol: str | None = None) -> None:
        del subprotocol

    async def send_text(self, text: str) -> None:
        if len(self.frames) >= self._budget:
            raise RuntimeError("socket is gone")
        self.frames.append(json.loads(text))


async def test_dropped_frames_are_flagged_and_replayed_after_reconnect() -> None:
    """A dead socket must not silently swallow the answer being streamed."""
    orchestrator = Orchestrator(AgentState())
    # Budget of two: the snapshot and one message land, the next cannot.
    dying = FakeSocket(frame_budget=2)
    handler = ChatWebSocket(dying, orchestrator)  # type: ignore[arg-type]
    await handler.accept()

    delivered = orchestrator.state.add_assistant_message("Frame that arrives.")
    await handler._push_message(delivered)
    lost = orchestrator.state.add_assistant_message("Frame that never arrives.")
    await handler._push_message(lost)

    assert [frame["type"] for frame in dying.frames] == ["state", "message"]
    assert orchestrator.stream_interrupted is True
    # Nothing is lost from the session itself, only from the wire.
    assert orchestrator.state.messages[-1].content == "Frame that never arrives."

    healthy = FakeSocket()
    reconnected = ChatWebSocket(healthy, orchestrator)  # type: ignore[arg-type]
    await reconnected.accept()

    snapshot = healthy.frames[0]
    assert snapshot["type"] == "state"
    assert snapshot["stream_interrupted"] is True
    assert snapshot["missed_messages"] == 1
    replayed = [message["content"] for message in snapshot["messages"]]
    assert "Frame that never arrives." in replayed
    # The flag is consumed by the client that was told about it.
    assert orchestrator.stream_interrupted is False


async def test_replay_covers_every_missed_frame_beyond_the_history_window() -> None:
    """A long outage replays all missed frames, not just the last 100."""
    orchestrator = Orchestrator(AgentState())
    dying = FakeSocket(frame_budget=2)
    handler = ChatWebSocket(dying, orchestrator)  # type: ignore[arg-type]
    await handler.accept()
    await handler._push_message(orchestrator.state.add_assistant_message("anchor"))

    for index in range(130):
        await handler._push_message(
            orchestrator.state.add_assistant_message(f"missed-{index}")
        )

    healthy = FakeSocket()
    await ChatWebSocket(healthy, orchestrator).accept()  # type: ignore[arg-type]

    snapshot = healthy.frames[0]
    assert snapshot["missed_messages"] == 130
    replayed = [message["content"] for message in snapshot["messages"]]
    assert replayed[0] == "missed-0"
    assert replayed[-1] == "missed-129"


async def test_a_clean_reconnect_reports_no_interruption() -> None:
    orchestrator = Orchestrator(AgentState())
    socket = FakeSocket()
    handler = ChatWebSocket(socket, orchestrator)  # type: ignore[arg-type]
    await handler.accept()
    await handler._push_message(orchestrator.state.add_assistant_message("delivered"))

    reconnected = FakeSocket()
    await ChatWebSocket(reconnected, orchestrator).accept()  # type: ignore[arg-type]

    snapshot = reconnected.frames[0]
    assert snapshot["stream_interrupted"] is False
    assert snapshot["missed_messages"] == 0
