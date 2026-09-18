from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from appian_sentinel.analyzer import pdf_extractor
from appian_sentinel.models.user_story import AcceptanceCriterion, UserStory
from appian_sentinel.web.routes import _sessions


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
