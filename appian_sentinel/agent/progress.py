from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from appian_sentinel.agent.state import AgentState, ChatMessage, MessageType

logger = logging.getLogger(__name__)

ProgressResult = Literal["ok", "failed", "deferred", "blocked"]
ProgressCallback = Callable[[ChatMessage], Awaitable[None]]


async def emit_progress(
    state: AgentState,
    callback: ProgressCallback | None,
    *,
    phase: str,
    current: int,
    total: int,
    detail: str,
    result: ProgressResult | None = None,
) -> ChatMessage:
    """Create, store, and optionally publish one structured progress event."""
    if not phase or not phase.isascii():
        raise ValueError("Progress phase must be non-empty ASCII.")
    if total < 1 or current < 0 or current > total:
        raise ValueError("Progress counters must satisfy 0 <= current <= total.")

    metadata: dict[str, bool | str | int] = {
        "progress": True,
        "phase": phase,
        "current": current,
        "total": total,
    }
    if result is not None:
        metadata["result"] = result

    message = state.add_message(
        "system",
        detail,
        message_type=MessageType.STATUS,
        metadata=metadata,
    )
    if callback is not None:
        try:
            await callback(message)
        except Exception:
            # ponytail: progress delivery is best effort; persist and replay if guaranteed delivery matters.
            logger.debug("Progress callback failed for phase %s.", phase, exc_info=True)
    return message
