from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import BaseModel

from appian_sentinel.analyzer.llm_client import (
    LLMClient,
    LLMRequestError,
    UnsupportedProtocolFeatureError,
)
from appian_sentinel.config import settings
from appian_sentinel.tester.test_generator import TestGenerator as LLMTestGenerator
from appian_sentinel.web import routes


@pytest.fixture(autouse=True)
def restore_llm_settings() -> Iterator[None]:
    original = (
        settings.litellm_base_url,
        settings.litellm_api_key,
        settings.llm_protocol,
        settings.sentinel_primary_model,
    )
    settings.litellm_base_url = "http://llm.test"
    settings.litellm_api_key = "top-secret"
    yield
    (
        settings.litellm_base_url,
        settings.litellm_api_key,
        settings.llm_protocol,
        settings.sentinel_primary_model,
    ) = original


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("bedrock.anthropic.claude-opus-4-8", "anthropic"),
        ("bedrock/anthropic/claude-sonnet-5", "anthropic"),
        ("claude-opus-4-8", "anthropic"),
        ("openai.gpt-5", "openai"),
        ("bedrock.openai.gpt-oss-120b", "openai"),
    ],
)
def test_auto_protocol_routing(model: str, expected: str) -> None:
    assert LLMClient.resolve_protocol(model, "auto") == expected


def test_explicit_protocol_overrides_model() -> None:
    assert LLMClient.resolve_protocol("claude-opus-4-8", "openai") == "openai"
    assert LLMClient.resolve_protocol("openai.gpt-5", "anthropic") == "anthropic"


@pytest.mark.asyncio
async def test_openai_chat_uses_chat_completions_shape() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    settings.llm_protocol = "openai"
    client = LLMClient(httpx.MockTransport(handler))
    result = await client.chat(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}],
        model="openai.gpt-5",
        max_tokens=12,
    )

    request = captured["request"]
    payload = captured["payload"]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer top-secret"
    assert payload["messages"][0]["role"] == "system"
    # The gateway contract forbids these on /v1/chat/completions.
    assert "max_tokens" not in payload
    assert "temperature" not in payload
    assert "response_format" not in payload
    assert result == "hello"


@pytest.mark.asyncio
async def test_anthropic_chat_moves_system_and_parses_content_blocks() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "hello "},
                    {"type": "tool_use", "id": "tool-1"},
                    {"type": "text", "text": "world"},
                ],
                "usage": {"input_tokens": 2, "output_tokens": 2},
            },
        )

    settings.llm_protocol = "auto"
    client = LLMClient(httpx.MockTransport(handler))
    result = await client.chat(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}],
        model="bedrock.anthropic.claude-opus-4-8",
    )

    request = captured["request"]
    payload = captured["payload"]
    assert request.url.path == "/v1/messages"
    assert payload["system"] == "Be brief."
    assert payload["messages"] == [{"role": "user", "content": "Hi"}]
    assert "response_format" not in payload
    assert result == "hello world"


@pytest.mark.parametrize(
    ("protocol", "model", "event", "expected_path"),
    [
        (
            "openai",
            "openai.gpt-5",
            '{"choices":[{"delta":{"content":"hello"}}]}',
            "/v1/chat/completions",
        ),
        (
            "anthropic",
            "claude-opus-4-8",
            '{"type":"content_block_delta","delta":{"type":"text_delta","text":"hello"}}',
            "/v1/messages",
        ),
    ],
)
@pytest.mark.asyncio
async def test_streaming_protocols(
    protocol: str,
    model: str,
    event: str,
    expected_path: str,
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=f"data: {event}\n\ndata: [DONE]\n\n".encode(),
        )

    settings.llm_protocol = protocol
    client = LLMClient(httpx.MockTransport(handler))
    chunks = [
        chunk
        async for chunk in client.chat_stream(
            [{"role": "user", "content": "Hi"}],
            model=model,
        )
    ]

    assert captured["path"] == expected_path
    assert captured["payload"]["stream"] is True
    assert chunks == ["hello"]


class StructuredAnswer(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_anthropic_structured_output_uses_prompt_validation() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"answer":"ok"}'}]},
        )

    settings.llm_protocol = "anthropic"
    client = LLMClient(httpx.MockTransport(handler))
    result = await client.chat_structured(
        [{"role": "user", "content": "Answer."}],
        StructuredAnswer,
        model="claude-opus-4-8",
    )

    assert result == StructuredAnswer(answer="ok")
    assert "response_format" not in captured["payload"]
    assert "Return ONLY valid JSON" in captured["payload"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_anthropic_rejects_raw_response_format_precisely() -> None:
    settings.llm_protocol = "anthropic"
    client = LLMClient(httpx.MockTransport(lambda request: httpx.Response(500)))

    with pytest.raises(
        UnsupportedProtocolFeatureError,
        match="gateway contract forbids response_format",
    ):
        await client.chat(
            [{"role": "user", "content": "Hi"}],
            response_format={"type": "json_object"},
        )


@pytest.mark.asyncio
async def test_failed_call_reports_the_upstream_reason_not_only_a_status() -> None:
    """A bare status code cannot distinguish a bad path from a rejected field."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "model bedrock.anthropic.claude-opus-4-8 not found"}},
        )

    settings.llm_protocol = "openai"
    client = LLMClient(httpx.MockTransport(handler))

    with pytest.raises(LLMRequestError) as caught:
        await client.chat([{"role": "user", "content": "Hi"}], model="openai.gpt-5")

    message = str(caught.value)
    assert "claude-opus-4-8 not found" in message
    assert "HTTP 400" in message
    # The URL matters: a wrong path is the most common cause of a 4xx here.
    assert "/v1/chat/completions" in message


@pytest.mark.asyncio
async def test_failed_call_without_json_body_still_reports_something_usable() -> None:
    settings.llm_protocol = "openai"
    client = LLMClient(
        httpx.MockTransport(lambda _request: httpx.Response(502, text="Bad Gateway"))
    )

    with pytest.raises(LLMRequestError, match="Bad Gateway"):
        await client.chat([{"role": "user", "content": "Hi"}], model="openai.gpt-5")


@pytest.mark.asyncio
async def test_generator_uses_shared_protocol_router() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": '{"name":"Suite","test_cases":[],"coverage_map":{}}',
                    }
                ]
            },
        )

    settings.llm_protocol = "anthropic"
    settings.sentinel_primary_model = "claude-opus-4-8"
    client = LLMClient(httpx.MockTransport(handler))
    generator = LLMTestGenerator(client)
    suite = await generator.generate_test_suite("Story", "Design")

    assert captured["path"] == "/v1/messages"
    assert suite.name == "Suite"


@pytest.mark.asyncio
async def test_connection_endpoint_uses_shared_router(monkeypatch: pytest.MonkeyPatch) -> None:
    from appian_sentinel.analyzer.llm_client import llm

    chat = AsyncMock(return_value="hello")
    monkeypatch.setattr(llm, "chat", chat)

    response = await routes.test_settings()

    assert response.status_code == 200
    chat.assert_awaited_once_with(
        [{"role": "user", "content": "Say hello in one word."}],
        model=settings.sentinel_fast_model,
        max_tokens=16,
        timeout=15,
    )


def test_short_secrets_are_fully_masked() -> None:
    assert routes._mask_key("abc") == "***"
