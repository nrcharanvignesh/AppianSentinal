"""Mocked-transport tests for the OpenAI tool-call chat protocol."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from appian_sentinel.analyzer.llm_client import (
    LLMClient,
    LLMRequestError,
    LLMToolCall,
    LLMToolResponse,
)
from appian_sentinel.config import settings

WEATHER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Return the weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


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
    settings.llm_protocol = "openai"
    settings.sentinel_primary_model = "openai.gpt-5"
    yield
    (
        settings.litellm_base_url,
        settings.litellm_api_key,
        settings.llm_protocol,
        settings.sentinel_primary_model,
    ) = original


def _client(payload: dict[str, Any], captured: dict[str, Any] | None = None) -> LLMClient:
    """Build a client whose transport always answers 200 with *payload*."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["request"] = request
            captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=payload)

    return LLMClient(httpx.MockTransport(handler))


def _tool_call(call_id: str, name: str, arguments: Any) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


async def test_final_text_returns_content_without_tool_calls() -> None:
    client = _client(
        {
            "choices": [
                {"message": {"role": "assistant", "content": "It is sunny."}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4},
        }
    )

    result = await client.chat_with_tools(
        [{"role": "user", "content": "Weather?"}],
        [WEATHER_TOOL],
    )

    assert result == LLMToolResponse(content="It is sunny.", tool_calls=(), finish_reason="stop")


async def test_single_tool_call_is_parsed() -> None:
    client = _client(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            _tool_call("call_1", "get_weather", '{"city": "Madrid"}')
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )

    result = await client.chat_with_tools(
        [{"role": "user", "content": "Weather in Madrid?"}],
        [WEATHER_TOOL],
    )

    assert result.content is None
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == (
        LLMToolCall(id="call_1", name="get_weather", arguments='{"city": "Madrid"}'),
    )
    assert json.loads(result.tool_calls[0].arguments) == {"city": "Madrid"}


async def test_multiple_tool_calls_keep_order_and_empty_arguments_become_an_object() -> None:
    client = _client(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            _tool_call("call_1", "get_weather", '{"city": "Madrid"}'),
                            _tool_call("call_2", "get_weather", '{"city": "Oslo"}'),
                            _tool_call("call_3", "list_cities", ""),
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )

    result = await client.chat_with_tools(
        [{"role": "user", "content": "Compare Madrid and Oslo."}],
        [WEATHER_TOOL],
    )

    assert [call.id for call in result.tool_calls] == ["call_1", "call_2", "call_3"]
    assert [call.name for call in result.tool_calls] == [
        "get_weather",
        "get_weather",
        "list_cities",
    ]
    assert result.tool_calls[2].arguments == "{}"


async def test_tool_call_records_are_immutable() -> None:
    call = LLMToolCall(id="call_1", name="get_weather", arguments="{}")

    with pytest.raises((AttributeError, TypeError)):
        call.name = "other"  # type: ignore[misc]


async def test_malformed_arguments_raise_and_mask_secrets() -> None:
    client = _client(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            _tool_call(
                                "call_1",
                                "get_weather",
                                '{"city": "Madrid", "api_key": "top-secret"',
                            )
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )

    with pytest.raises(LLMRequestError) as caught:
        await client.chat_with_tools(
            [{"role": "user", "content": "Weather?"}],
            [WEATHER_TOOL],
        )

    message = str(caught.value)
    assert "get_weather" in message
    assert "malformed JSON arguments" in message
    assert "top-secret" not in message


async def test_non_object_arguments_are_rejected() -> None:
    client = _client(
        {
            "choices": [
                {"message": {"tool_calls": [_tool_call("call_1", "get_weather", '"Madrid"')]}}
            ]
        }
    )

    with pytest.raises(LLMRequestError, match="must decode to a JSON object"):
        await client.chat_with_tools(
            [{"role": "user", "content": "Weather?"}],
            [WEATHER_TOOL],
        )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"finish_reason": "stop"}]},
        {"choices": [{"message": {"tool_calls": {"id": "call_1"}}}]},
        {"choices": [{"message": {"tool_calls": [{"id": "call_1"}]}}]},
        {"choices": [{"message": {"tool_calls": [_tool_call("", "get_weather", "{}")]}}]},
        {"choices": [{"message": {"tool_calls": [_tool_call("call_1", "", "{}")]}}]},
        {"choices": [{"message": {"tool_calls": [_tool_call("call_1", "get_weather", 7)]}}]},
    ],
)
async def test_malformed_responses_raise_llm_request_error(body: dict[str, Any]) -> None:
    client = _client(body)

    with pytest.raises(LLMRequestError):
        await client.chat_with_tools(
            [{"role": "user", "content": "Weather?"}],
            [WEATHER_TOOL],
        )


async def test_http_error_reports_status_url_and_upstream_reason() -> None:
    client = LLMClient(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                400, json={"error": {"message": "unknown tool schema"}}
            )
        )
    )

    with pytest.raises(LLMRequestError) as caught:
        await client.chat_with_tools(
            [{"role": "user", "content": "Weather?"}],
            [WEATHER_TOOL],
        )

    message = str(caught.value)
    assert "HTTP 400" in message
    assert "unknown tool schema" in message
    assert "/v1/chat/completions" in message


async def test_payload_is_exact_and_preserves_assistant_and_tool_messages() -> None:
    captured: dict[str, Any] = {}
    client = _client(
        {"choices": [{"message": {"content": "Sunny."}, "finish_reason": "stop"}]},
        captured,
    )
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Weather in Madrid?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("call_1", "get_weather", '{"city": "Madrid"}')],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_c": 21}'},
    ]

    await client.chat_with_tools(
        messages,
        [WEATHER_TOOL],
        tool_choice="required",
        model="openai.gpt-5",
    )

    request = captured["request"]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer top-secret"
    assert captured["payload"] == {
        "model": "openai.gpt-5",
        "messages": messages,
        "tools": [WEATHER_TOOL],
        "tool_choice": "required",
    }


async def test_anthropic_model_still_posts_to_chat_completions() -> None:
    captured: dict[str, Any] = {}
    client = _client({"choices": [{"message": {"content": "ok"}}]}, captured)
    settings.llm_protocol = "anthropic"

    result = await client.chat_with_tools(
        [{"role": "user", "content": "Weather?"}],
        [WEATHER_TOOL],
        model="claude-opus-4-8",
    )

    assert captured["request"].url.path == "/v1/chat/completions"
    assert captured["payload"]["model"] == "claude-opus-4-8"
    assert result.content == "ok"
    assert result.finish_reason is None


async def test_rate_limited_call_is_retried() -> None:
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    client = LLMClient(httpx.MockTransport(handler))
    result = await client.chat_with_tools(
        [{"role": "user", "content": "Weather?"}],
        [WEATHER_TOOL],
    )

    assert len(attempts) == 2
    assert result.content == "ok"
