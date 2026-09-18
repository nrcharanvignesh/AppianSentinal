from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel

from appian_sentinel.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Resolve the system prompt from the project-root text file
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[2] / "Appian Sentinel.txt"


def _load_system_prompt() -> str:
    """Load the Appian Sentinel system prompt from disk.

    Falls back to a short default if the file is missing so the application
    can still start (useful during testing).
    """
    try:
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("System prompt file not found at %s; using fallback.", _SYSTEM_PROMPT_PATH)
        return (
            "You are Appian Sentinel, an expert Appian developer and QA engineer. "
            "Produce production-quality SAIL code, dependency checks, performance analysis, "
            "and test suites for every request."
        )


SYSTEM_PROMPT: str = _load_system_prompt()

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3

LLMProtocol = Literal["openai", "anthropic"]
Message = dict[str, Any]


class UnsupportedProtocolFeatureError(ValueError):
    """Raised when a selected protocol cannot represent a requested feature."""


class LLMRequestError(RuntimeError):
    """Raised for an LLM HTTP or response-shape failure."""


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Route LLM calls to the OpenAI or Anthropic HTTP protocol."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._default_model = settings.sentinel_primary_model
        self._fast_model = settings.sentinel_fast_model

    def reconfigure(self) -> None:
        """Re-read model settings used by subsequent requests."""
        self._default_model = settings.sentinel_primary_model
        self._fast_model = settings.sentinel_fast_model
        logger.info("LLMClient reconfigured for %s", settings.litellm_base_url)

    # -- helpers -------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def fast_model(self) -> str:
        return self._fast_model

    def _resolve_model(self, model: str | None) -> str:
        return model if model is not None else self._default_model

    @staticmethod
    def resolve_protocol(model: str, configured: str | None = None) -> LLMProtocol:
        """Resolve an explicit or automatic protocol for a model."""
        selected = (configured or settings.llm_protocol).strip().lower()
        if selected == "openai":
            return "openai"
        if selected == "anthropic":
            return "anthropic"
        if selected != "auto":
            raise ValueError("llm_protocol must be one of: auto, openai, anthropic")

        normalized = model.strip().lower().replace("/", ".")
        if (
            normalized.startswith("bedrock.anthropic.")
            or normalized.startswith("anthropic.")
            or normalized.startswith("claude")
            or ".anthropic.claude" in normalized
        ):
            return "anthropic"
        return "openai"

    @staticmethod
    def _log_usage(model: str, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        total = int(usage.get("total_tokens", 0) or (prompt_tokens + completion_tokens))
        logger.info(
            "LLM usage | model=%s prompt=%d completion=%d total=%d",
            model,
            prompt_tokens,
            completion_tokens,
            total,
        )

    @staticmethod
    def _headers() -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.litellm_api_key:
            headers["Authorization"] = f"Bearer {settings.litellm_api_key}"
        return headers

    @staticmethod
    def _url(protocol: LLMProtocol) -> str:
        path = "/chat/completions" if protocol == "openai" else "/v1/messages"
        base_url = settings.litellm_base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        return f"{base_url}{path}"

    @staticmethod
    def _anthropic_messages(messages: list[Message]) -> tuple[str | None, list[Message]]:
        systems: list[str] = []
        conversation: list[Message] = []
        for message in messages:
            role = str(message.get("role", ""))
            content = message.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    systems.append(content)
                else:
                    raise UnsupportedProtocolFeatureError(
                        "Anthropic protocol supports only text system messages."
                    )
            elif role in {"user", "assistant"}:
                conversation.append({"role": role, "content": content})
            else:
                raise UnsupportedProtocolFeatureError(
                    f"Anthropic protocol does not support message role '{role}'."
                )
        if not conversation:
            raise ValueError("Anthropic protocol requires at least one user or assistant message.")
        return ("\n\n".join(systems) if systems else None), conversation

    def _payload(
        self,
        protocol: LLMProtocol,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        if protocol == "openai":
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format is not None:
                payload["response_format"] = response_format
        else:
            if response_format is not None:
                raise UnsupportedProtocolFeatureError(
                    "Anthropic protocol does not support response_format; "
                    "use chat_structured for schema validation."
                )
            system, conversation = self._anthropic_messages(messages)
            payload = {
                "model": model,
                "messages": conversation,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if system is not None:
                payload["system"] = system
        if stream:
            payload["stream"] = True
        return payload

    async def _post_json(
        self,
        protocol: LLMProtocol,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout,
                ) as client:
                    response = await client.post(
                        self._url(protocol),
                        headers=self._headers(),
                        json=payload,
                    )
                if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    continue
                if response.is_error:
                    raise LLMRequestError(
                        f"{protocol} request failed with HTTP {response.status_code}."
                    )
                try:
                    data = response.json()
                except ValueError as exc:
                    raise LLMRequestError(
                        f"{protocol} response is not valid JSON."
                    ) from exc
                if not isinstance(data, dict):
                    raise LLMRequestError(f"{protocol} response must be a JSON object.")
                return data
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == _MAX_RETRIES - 1:
                    raise LLMRequestError(
                        f"{protocol} request failed after {_MAX_RETRIES} attempts: "
                        f"{type(exc).__name__}."
                    ) from exc
        raise LLMRequestError(f"{protocol} request failed.")

    @staticmethod
    def _parse_content(protocol: LLMProtocol, data: dict[str, Any]) -> str:
        try:
            if protocol == "openai":
                content = data["choices"][0]["message"]["content"]
                return content if isinstance(content, str) else ""
            blocks = data["content"]
            if not isinstance(blocks, list):
                raise TypeError
            return "".join(
                str(block.get("text", ""))
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError(f"Invalid {protocol} response shape.") from exc

    # -- public API ----------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> str:
        """Send a chat completion request and return the assistant content string."""
        resolved_model = self._resolve_model(model)
        protocol = self.resolve_protocol(resolved_model)
        logger.debug("LLM chat request | model=%s messages=%d", resolved_model, len(messages))
        payload = self._payload(
            protocol,
            resolved_model,
            messages,
            temperature,
            max_tokens or settings.sentinel_max_tokens,
            response_format,
            False,
        )
        data = await self._post_json(protocol, payload, timeout)
        usage = data.get("usage")
        self._log_usage(resolved_model, usage if isinstance(usage, dict) else None)
        return self._parse_content(protocol, data)

    async def chat_structured(
        self,
        messages: list[Message],
        response_schema: type[T],
        *,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> T:
        """Chat completion with JSON structured output parsed into a Pydantic model.

        Uses ``response_format`` with a JSON Schema derived from the provided
        Pydantic model so the LLM returns well-formed JSON that can be parsed
        directly.
        """
        schema = response_schema.model_json_schema()

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "strict": True,
                "schema": schema,
            },
        }

        json_instruction = (
            f"\n\nYou MUST respond with a JSON object that conforms to this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```\n"
            "Return ONLY valid JSON. No markdown fences, no commentary outside the JSON."
        )
        augmented_messages = list(messages)
        if augmented_messages and augmented_messages[-1].get("role") == "user":
            augmented_messages[-1] = {
                **augmented_messages[-1],
                "content": augmented_messages[-1]["content"] + json_instruction,
            }
        else:
            augmented_messages.append({"role": "user", "content": json_instruction})

        resolved_model = self._resolve_model(model)
        protocol = self.resolve_protocol(resolved_model)
        raw = await self.chat(
            augmented_messages,
            model=resolved_model,
            temperature=temperature,
            response_format=response_format if protocol == "openai" else None,
        )

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        return response_schema.model_validate_json(cleaned)

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming chat completion that yields content delta strings."""
        resolved_model = self._resolve_model(model)
        protocol = self.resolve_protocol(resolved_model)
        logger.debug("LLM stream request | model=%s messages=%d", resolved_model, len(messages))
        payload = self._payload(
            protocol,
            resolved_model,
            messages,
            temperature,
            max_tokens or settings.sentinel_max_tokens,
            None,
            True,
        )
        async with httpx.AsyncClient(transport=self._transport, timeout=120.0) as client:
            async with client.stream(
                "POST",
                self._url(protocol),
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.is_error:
                    raise LLMRequestError(
                        f"{protocol} stream request failed with HTTP {response.status_code}."
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                        if protocol == "openai":
                            text = event["choices"][0]["delta"].get("content", "")
                        elif event.get("type") == "content_block_delta":
                            text = event.get("delta", {}).get("text", "")
                        else:
                            text = ""
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                        raise LLMRequestError(
                            f"Invalid {protocol} streaming event."
                        ) from exc
                    if text:
                        yield str(text)

    async def count_tokens_approx(self, text: str) -> int:
        """Return an approximate token count using the chars/4 heuristic."""
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

llm = LLMClient()
