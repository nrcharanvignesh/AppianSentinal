"""Proof that free-form chat reports only tool calls the model actually made."""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest

from appian_sentinel.agent.orchestrator import MAX_CHAT_TOOL_ROUNDS, Orchestrator
from appian_sentinel.agent.state import AgentState, AgentStatus, ChatMessage, MessageType

_ADAPTER_MODULE = "appian_sentinel.mcp_server.openai_tools"
_TOOL_SCHEMA: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "get_expression_rule", "parameters": {}}},
]


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeToolCall:
    """One model-selected call, shaped like the real client's tool call."""

    id: str
    name: str
    arguments: Any


@dataclass
class FakeToolResponse:
    """One assistant turn, shaped like ``LLMToolResponse``."""

    content: str | None = None
    tool_calls: list[FakeToolCall] = field(default_factory=list)
    finish_reason: str | None = "stop"


class ScriptedLLM:
    """Replay a fixed list of tool responses and record what was sent."""

    def __init__(self, responses: list[FakeToolResponse], *, repeat_last: bool = False) -> None:
        self._responses = list(responses)
        self._repeat_last = repeat_last
        self.conversations: list[list[dict[str, Any]]] = []
        self.tool_payloads: list[list[dict[str, Any]]] = []

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        model: str | None = None,
    ) -> FakeToolResponse:
        assert tool_choice == "auto"
        self.conversations.append(copy.deepcopy(messages))
        self.tool_payloads.append(copy.deepcopy(tools))
        if len(self._responses) == 1 and self._repeat_last:
            return self._responses[0]
        return self._responses.pop(0)


class FailingLLM:
    """Raise on every call, to prove the turn ends with a reported error."""

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        model: str | None = None,
    ) -> FakeToolResponse:
        raise RuntimeError("gateway refused the request")


class RecordingAdapter:
    """Stand-in for the OpenAI tool adapter module."""

    def __init__(self, handler: Callable[[str, dict[str, Any], str], Any]) -> None:
        self.handler = handler
        self.invocations: list[tuple[str, dict[str, Any], str]] = []

    async def list_chat_tools(self) -> list[dict[str, Any]]:
        return copy.deepcopy(_TOOL_SCHEMA)

    def invoke_chat_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        export_dir: str,
    ) -> Any:
        self.invocations.append((name, dict(arguments), export_dir))
        return self.handler(name, arguments, export_dir)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _install_adapter(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[str, dict[str, Any], str], Any],
) -> RecordingAdapter:
    adapter = RecordingAdapter(handler)
    module = ModuleType(_ADAPTER_MODULE)
    module.list_chat_tools = adapter.list_chat_tools  # type: ignore[attr-defined]
    module.invoke_chat_tool = adapter.invoke_chat_tool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _ADAPTER_MODULE, module)
    return adapter


def _install_llm(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    from appian_sentinel.analyzer import llm_client

    monkeypatch.setattr(
        llm_client.llm,
        "chat_with_tools",
        client.chat_with_tools,
        raising=False,
    )


def _chatting_state(export_dir: Path | None) -> AgentState:
    """A session that is past requirement intake, so chat is free-form."""
    state = AgentState()
    state.status = AgentStatus.IDLE
    state.user_story = {"title": "Existing story"}
    if export_dir is not None:
        state.export_dir = str(export_dir)
    return state


async def _run_turn(
    orchestrator: Orchestrator,
    message: str,
    object_uuids: list[str] | None = None,
) -> list[ChatMessage]:
    return [item async for item in orchestrator.process_user_message(message, object_uuids)]


def _tool_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [item for item in messages if item.message_type is MessageType.TOOL]


def _ok_result(name: str, arguments: dict[str, Any], export_dir: str) -> dict[str, Any]:
    return {"status": "ok", "uuid": arguments.get("uuid", ""), "name": "APP_Rule"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_selected_objects_enter_context_without_fake_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _install_adapter(monkeypatch, _ok_result)
    llm = ScriptedLLM([FakeToolResponse(content="The rule validates the request.")])
    _install_llm(monkeypatch, llm)
    orchestrator = Orchestrator(_chatting_state(tmp_path))

    messages = await _run_turn(orchestrator, "What does this rule do?", ["uuid-1", "uuid-2"])

    assert _tool_messages(messages) == []
    assert adapter.invocations == []
    assert messages[-1].content == "The rule validates the request."
    context = llm.conversations[0][-1]
    assert context["role"] == "system"
    assert "uuid-1" in context["content"] and "uuid-2" in context["content"]


async def test_model_selected_call_emits_ordered_start_and_end(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _install_adapter(monkeypatch, _ok_result)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="call-1", name="get_expression_rule", arguments={"uuid": "uuid-1"}),
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(content="The rule adds two inputs."),
        ]
    )
    _install_llm(monkeypatch, llm)
    orchestrator = Orchestrator(_chatting_state(tmp_path))

    messages = await _run_turn(orchestrator, "Explain uuid-1.", ["uuid-1"])

    start, end = _tool_messages(messages)
    assert messages.index(start) < messages.index(end) < messages.index(messages[-1])
    assert start.metadata["status"] == "started"
    assert start.metadata["call_id"] == "call-1"
    assert start.metadata["tool"] == "get_expression_rule"
    assert start.metadata["args"] == {"uuid": "uuid-1"}
    assert start.metadata["object_uuids"] == ["uuid-1"]
    assert start.metadata["ended_at"] is None
    assert end.metadata["status"] == "ok"
    assert end.metadata["started_at"] == start.metadata["started_at"]
    assert end.metadata["ended_at"] >= end.metadata["started_at"]
    assert 0 < len(end.metadata["result_summary"]) <= 240
    assert end.metadata["result_summary"].isascii()
    assert end.metadata["result"]["name"] == "APP_Rule"
    assert adapter.invocations == [
        ("get_expression_rule", {"uuid": "uuid-1"}, str(tmp_path))
    ]

    fed_back = [item for item in llm.conversations[1] if item["role"] == "tool"]
    assert fed_back[0]["tool_call_id"] == "call-1"
    assert json.loads(fed_back[0]["content"])["name"] == "APP_Rule"
    assert messages[-1].content == "The rule adds two inputs."


async def test_multi_round_loop_runs_every_call_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _install_adapter(monkeypatch, _ok_result)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="c1", name="get_expression_rule", arguments={"uuid": "u1"}),
                    FakeToolCall(id="c2", name="get_expression_rule", arguments='{"uuid": "u2"}'),
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="c3", name="get_expression_rule", arguments={"uuid": "u3"}),
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(content="All three rules share one constant."),
        ]
    )
    _install_llm(monkeypatch, llm)
    orchestrator = Orchestrator(_chatting_state(tmp_path))

    messages = await _run_turn(orchestrator, "Compare the rules.")

    tools = _tool_messages(messages)
    assert [item.metadata["call_id"] for item in tools] == ["c1", "c1", "c2", "c2", "c3", "c3"]
    assert [item.metadata["status"] for item in tools] == [
        "started", "ok", "started", "ok", "started", "ok",
    ]
    assert [name for name, _, _ in adapter.invocations] == ["get_expression_rule"] * 3
    assert [args["uuid"] for _, args, _ in adapter.invocations] == ["u1", "u2", "u3"]
    assert len(llm.conversations) == 3
    assert len([item for item in llm.conversations[2] if item["role"] == "tool"]) == 3
    assert messages[-1].content == "All three rules share one constant."


async def test_unknown_tool_fails_and_the_loop_continues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def handler(name: str, arguments: dict[str, Any], export_dir: str) -> dict[str, Any]:
        if name == "no_such_tool":
            raise KeyError(name)
        return _ok_result(name, arguments, export_dir)

    _install_adapter(monkeypatch, handler)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="bad", name="no_such_tool", arguments={"uuid": "u1"}),
                    FakeToolCall(id="broken", name="get_expression_rule", arguments="not json"),
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(content="That tool does not exist; here is what I can do."),
        ]
    )
    _install_llm(monkeypatch, llm)
    orchestrator = Orchestrator(_chatting_state(tmp_path))

    messages = await _run_turn(orchestrator, "Use a tool that is not real.")

    ends = [item for item in _tool_messages(messages) if item.metadata["status"] != "started"]
    assert [item.metadata["status"] for item in ends] == ["failed", "failed"]
    assert "KeyError" in ends[0].metadata["result_summary"]
    assert "JSON" in ends[1].metadata["result_summary"]
    results = [
        json.loads(item["content"])
        for item in llm.conversations[1]
        if item["role"] == "tool"
    ]
    assert [result["status"] for result in results] == ["failed", "failed"]
    assert messages[-1].content == "That tool does not exist; here is what I can do."
    assert messages[-1].message_type is MessageType.TEXT


async def test_adapter_error_result_is_failed_and_keeps_nested_object_uuid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def denied(
        name: str,
        arguments: dict[str, Any],
        export_dir: str,
    ) -> dict[str, Any]:
        del arguments, export_dir
        return {
            "ok": False,
            "tool": name,
            "error": {"code": "not_allowed", "object_uuid": "blocked-uuid"},
        }

    _install_adapter(monkeypatch, denied)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="denied", name="delete_object", arguments={}),
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(content="The operation is not available."),
        ]
    )
    _install_llm(monkeypatch, llm)

    messages = await _run_turn(
        Orchestrator(_chatting_state(tmp_path)),
        "Delete the object.",
    )

    end = _tool_messages(messages)[1]
    assert end.metadata["status"] == "failed"
    assert end.metadata["object_uuids"] == ["blocked-uuid"]


async def test_pending_delete_is_structured_for_desktop_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pending = {
        "ok": True,
        "tool": "delete_constant",
        "truncated": False,
        "result": {
            "status": "pending_deletion",
            "pending_deletion": True,
            "applied": False,
            "object": {"uuid": "u1", "name": "APP_Constant", "type": "constant"},
            "reverse_dependencies": ["rule-1"],
            "confirmation": {
                "required": True,
                "action": "delete_typed_object",
                "slug": "constant",
                "object_uuid": "u1",
                "preview": False,
                "force_required": True,
            },
        },
    }

    _install_adapter(monkeypatch, lambda _name, _arguments, _export_dir: pending)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(
                        id="delete-1",
                        name="delete_constant",
                        arguments={"object_uuid": "u1"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(content="Deletion is waiting for confirmation."),
        ]
    )
    _install_llm(monkeypatch, llm)

    messages = await _run_turn(
        Orchestrator(_chatting_state(tmp_path)),
        "Delete the constant.",
    )

    end = _tool_messages(messages)[1]
    assert end.metadata["status"] == "pending_confirmation"
    assert end.metadata["result"] == pending
    assert end.metadata["result"]["result"]["applied"] is False


async def test_missing_workspace_blocks_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _install_adapter(monkeypatch, _ok_result)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="c1", name="get_expression_rule", arguments={"uuid": "u1"}),
                ],
                finish_reason="tool_calls",
            ),
            FakeToolResponse(content="Import an export ZIP and ask again."),
        ]
    )
    _install_llm(monkeypatch, llm)
    orchestrator = Orchestrator(_chatting_state(None))

    messages = await _run_turn(orchestrator, "Read uuid u1.", ["u1"])

    end = _tool_messages(messages)[1]
    assert end.metadata["status"] == "blocked"
    assert "workspace" in end.metadata["result_summary"]
    assert adapter.invocations == []
    assert messages[-1].content == "Import an export ZIP and ask again."


async def test_round_limit_stops_the_loop_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _install_adapter(monkeypatch, _ok_result)
    llm = ScriptedLLM(
        [
            FakeToolResponse(
                tool_calls=[
                    FakeToolCall(id="loop", name="get_expression_rule", arguments={"uuid": "u1"}),
                ],
                finish_reason="tool_calls",
            )
        ],
        repeat_last=True,
    )
    _install_llm(monkeypatch, llm)
    orchestrator = Orchestrator(_chatting_state(tmp_path))

    messages = await _run_turn(orchestrator, "Keep calling tools.")

    assert len(llm.conversations) == MAX_CHAT_TOOL_ROUNDS
    assert len(adapter.invocations) == MAX_CHAT_TOOL_ROUNDS
    assert len(_tool_messages(messages)) == MAX_CHAT_TOOL_ROUNDS * 2
    assert messages[-1].message_type is MessageType.ERROR
    assert str(MAX_CHAT_TOOL_ROUNDS) in messages[-1].content


async def test_llm_failure_is_reported_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adapter = _install_adapter(monkeypatch, _ok_result)
    _install_llm(monkeypatch, FailingLLM())
    orchestrator = Orchestrator(_chatting_state(tmp_path))

    messages = await _run_turn(orchestrator, "Explain the rule.")

    assert _tool_messages(messages) == []
    assert adapter.invocations == []
    assert messages[-1].message_type is MessageType.ERROR
    assert "gateway refused the request" in messages[-1].content


def _install_intake_story(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make requirement intake parse without reaching a real model."""
    from appian_sentinel.analyzer import pdf_extractor
    from appian_sentinel.models.user_story import UserStory

    async def fake_extract(text: str) -> UserStory:
        return UserStory(title="Submit a request", description=text)

    monkeypatch.setattr(pdf_extractor, "extract_user_story_from_text", fake_extract)


async def test_requirement_intake_reports_only_reads_it_really_made(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A reported load must be backed by a real adapter invocation."""
    adapter = _install_adapter(monkeypatch, _ok_result)
    llm = ScriptedLLM([FakeToolResponse(content="unused")])
    _install_llm(monkeypatch, llm)
    _install_intake_story(monkeypatch)

    state = AgentState()
    state.export_dir = str(tmp_path)

    messages = await _run_turn(Orchestrator(state), "Submit a request", ["uuid-1"])

    trace = _tool_messages(messages)[0]
    call = trace.metadata["tool_calls"][0]
    # The adapter ran once, for the object the trace claims it loaded.
    assert adapter.invocations == [("get_object", {"uuid": "uuid-1"}, str(tmp_path))]
    assert call == {
        "tool": "get_object",
        "status": "ok",
        "object_uuid": "uuid-1",
        "object_name": "APP_Rule",
        "object_type": "",
    }
    assert trace.metadata["objects"] == [
        {"uuid": "uuid-1", "name": "APP_Rule", "type": ""}
    ]
    assert trace.content == "Objects loaded for this turn: APP_Rule."
    # Intake parses the story itself, so the chat model is still never called.
    assert llm.conversations == []
    assert messages[-1].content == "User story received and parsed. Starting the workflow ..."


async def test_requirement_intake_reports_a_failed_read_as_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A read that returns no object is never dressed up as a loaded object."""

    def not_found(
        name: str,
        arguments: dict[str, Any],
        export_dir: str,
    ) -> dict[str, Any]:
        del name, export_dir
        return {
            "ok": True,
            "tool": "get_object",
            "truncated": False,
            "result": {"error": f"Object {arguments['uuid']} not found."},
        }

    adapter = _install_adapter(monkeypatch, not_found)
    _install_llm(monkeypatch, ScriptedLLM([FakeToolResponse(content="unused")]))
    _install_intake_story(monkeypatch)

    state = AgentState()
    state.export_dir = str(tmp_path)

    messages = await _run_turn(Orchestrator(state), "Submit a request", ["missing-uuid"])

    trace = _tool_messages(messages)[0]
    call = trace.metadata["tool_calls"][0]
    assert len(adapter.invocations) == 1
    assert call["tool"] == "get_object"
    assert call["status"] == "failed"
    assert "object_name" not in call
    assert "not found" in call["detail"]
    assert trace.metadata["objects"] == []
    assert trace.metadata["object_uuids"] == []
    assert trace.content == (
        "Objects loaded for this turn: none. Could not read: missing-uuid."
    )


async def test_requirement_intake_without_workspace_reports_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no export loaded there is nothing to read and nothing to claim."""
    adapter = _install_adapter(monkeypatch, _ok_result)
    _install_llm(monkeypatch, ScriptedLLM([FakeToolResponse(content="unused")]))
    _install_intake_story(monkeypatch)

    messages = await _run_turn(Orchestrator(AgentState()), "Submit a request", ["u1"])

    call = _tool_messages(messages)[0].metadata["tool_calls"][0]
    # No invocation and no claim of one: the entry reports the read as blocked.
    assert adapter.invocations == []
    assert call["status"] == "blocked"
    assert call["tool"] == "get_object"
    assert "object_name" not in call
