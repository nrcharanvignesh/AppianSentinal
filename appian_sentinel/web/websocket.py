from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import ChatMessage

logger = logging.getLogger(__name__)


class ChatWebSocket:
    """Manages a single WebSocket connection tied to an agent session.

    Responsibilities
    ----------------
    * Receive user messages and forward them to the ``Orchestrator``.
    * Stream orchestrator responses (``ChatMessage`` objects) back to the
      client as JSON frames.
    * Push status updates (step changes, progress) in real time.
    * Handle disconnect / reconnect gracefully.
    """

    def __init__(self, websocket: WebSocket, orchestrator: Orchestrator) -> None:
        self.ws = websocket
        self.orchestrator = orchestrator
        self._closed = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def accept(self) -> None:
        """Accept the WebSocket handshake."""
        await self.ws.accept()
        logger.info("WebSocket connected (session %s)", self.orchestrator.state.session_id)

        # Register ourselves as the callback so every message the orchestrator
        # emits gets pushed to the client.
        self.orchestrator._on_message = self._push_message

        # Send the current state snapshot so the client can catch up after a
        # reconnect.
        await self._send_state_snapshot()

    async def listen(self) -> None:
        """Main receive loop -- runs until the client disconnects."""
        try:
            while True:
                raw = await self.ws.receive_text()
                await self._handle_incoming(raw)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected (session %s)", self.orchestrator.state.session_id)
            self._closed = True

    async def close(self) -> None:
        if not self._closed:
            try:
                await self.ws.close()
            except Exception:
                pass
            self._closed = True

    # ------------------------------------------------------------------
    # Incoming message handling
    # ------------------------------------------------------------------

    async def _handle_incoming(self, raw: str) -> None:
        """Parse and route a message received from the client."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Treat plain text as a chat message.
            data = {"type": "chat", "content": raw}

        msg_type = data.get("type", "chat")

        if msg_type == "chat":
            content = data.get("content", "").strip()
            if not content:
                return
            async for msg in self.orchestrator.process_user_message(content):
                await self._push_message(msg)

        elif msg_type == "answer":
            # Client is responding to a clarifying question.
            question_id = data.get("question_id", "")
            answer = data.get("answer", "")
            self.orchestrator.state.answer_question(question_id, answer)
            self.orchestrator._user_reply_event.set()
            await self._push_json({"type": "ack", "question_id": question_id})

        elif msg_type == "status":
            await self._send_state_snapshot()

        elif msg_type == "ping":
            await self._push_json({"type": "pong"})

        else:
            logger.warning("Unknown WS message type: %s", msg_type)

    # ------------------------------------------------------------------
    # Outgoing helpers
    # ------------------------------------------------------------------

    async def _push_message(self, msg: ChatMessage) -> None:
        """Serialize a ChatMessage and send it to the client."""
        if self._closed:
            return
        payload = {
            "type": "message",
            "data": msg.model_dump(),
        }
        await self._push_json(payload)

    async def _push_json(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            await self.ws.send_text(json.dumps(payload, default=str))
        except Exception:
            logger.debug("Failed to send WS frame; connection may be closed.")
            self._closed = True

    async def _send_state_snapshot(self) -> None:
        """Push a full state summary to the client (used on connect / reconnect)."""
        payload = {
            "type": "state",
            "data": self.orchestrator.state.to_summary(),
            "messages": [m.model_dump() for m in self.orchestrator.state.messages[-100:]],
            "pending_questions": [
                q.model_dump() for q in self.orchestrator.state.unanswered_questions()
            ],
        }
        await self._push_json(payload)
