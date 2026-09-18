from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TypeVar

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
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
_RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError)


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Async OpenAI-compatible client pointed at the LiteLLM proxy."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_api_key or "not-needed",
            timeout=120.0,
            max_retries=_MAX_RETRIES,
        )
        self._default_model = settings.sentinel_primary_model
        self._fast_model = settings.sentinel_fast_model

    def reconfigure(self) -> None:
        """Re-read settings and rebuild the underlying OpenAI client."""
        self._client = AsyncOpenAI(
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_api_key or "not-needed",
            timeout=120.0,
            max_retries=_MAX_RETRIES,
        )
        self._default_model = settings.sentinel_primary_model
        self._fast_model = settings.sentinel_fast_model
        logger.info("LLMClient reconfigured → %s", settings.litellm_base_url)

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
    def _log_usage(model: str, usage: object | None) -> None:
        if usage is None:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
        logger.info(
            "LLM usage | model=%s prompt=%d completion=%d total=%d",
            model,
            prompt_tokens,
            completion_tokens,
            total,
        )

    # -- public API ----------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """Send a chat completion request and return the assistant content string."""
        resolved_model = self._resolve_model(model)
        kwargs: dict = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or settings.sentinel_max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        logger.debug("LLM chat request | model=%s messages=%d", resolved_model, len(messages))

        response = await self._client.chat.completions.create(**kwargs)
        self._log_usage(resolved_model, response.usage)

        choice = response.choices[0]
        content: str = choice.message.content or ""
        return content

    async def chat_structured(
        self,
        messages: list[dict],
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

        # Build the response_format payload for the API.  LiteLLM / OpenAI
        # compatible proxies accept the ``json_schema`` variant.
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "strict": True,
                "schema": schema,
            },
        }

        # Append an instruction so the model knows it must return JSON.
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

        raw = await self.chat(
            augmented_messages,
            model=model,
            temperature=temperature,
            response_format=response_format,
        )

        # Parse — strip markdown code fences if the model wraps the JSON.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (with optional language tag) and closing fence.
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        return response_schema.model_validate_json(cleaned)

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming chat completion that yields content delta strings."""
        resolved_model = self._resolve_model(model)
        logger.debug("LLM stream request | model=%s messages=%d", resolved_model, len(messages))

        stream = await self._client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or settings.sentinel_max_tokens,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def count_tokens_approx(self, text: str) -> int:
        """Return an approximate token count using the chars/4 heuristic."""
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

llm = LLMClient()
