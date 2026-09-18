"""Structured progress contract and orchestration emission tests."""

from __future__ import annotations

from typing import Any, TypeVar

import pytest

from appian_sentinel.agent import orchestrator as orchestrator_module
from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState, ChatMessage
from appian_sentinel.models.test_case import (
    TestCaseResult as CaseResult,
)
from appian_sentinel.models.test_case import (
    TestCaseStatus as CaseStatus,
)
from appian_sentinel.models.test_case import (
    TestRunResult as RunResult,
)

T = TypeVar("T")


async def _value(value: T) -> T:
    return value


def _progress(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [message for message in messages if message.metadata.get("progress") is True]


async def test_every_workflow_step_emits_unique_ascii_phase_start_and_end() -> None:
    messages: list[ChatMessage] = []

    async def collect(message: ChatMessage) -> None:
        messages.append(message)

    agent = Orchestrator(AgentState(), on_message=collect)
    for step in range(1, 10):
        assert await agent._run_workflow_step(step, _value(step)) == step

    events = _progress(messages)
    phases = {str(event.metadata["phase"]) for event in events}
    assert phases == {f"workflow.step_{step}" for step in range(1, 10)}
    assert all(phase.isascii() for phase in phases)
    for step in range(1, 10):
        step_events = [
            event
            for event in events
            if event.metadata["phase"] == f"workflow.step_{step}"
        ]
        assert len(step_events) == 2
        assert "result" not in step_events[0].metadata
        assert step_events[1].metadata["result"] == "ok"
        assert step_events[1].metadata["current"] == step
        assert step_events[1].metadata["total"] == 9


async def test_failing_workflow_step_reports_failed_not_ok() -> None:
    messages: list[ChatMessage] = []

    async def collect(message: ChatMessage) -> None:
        messages.append(message)

    async def fail() -> None:
        raise RuntimeError("scripted failure")

    agent = Orchestrator(AgentState(), on_message=collect)
    with pytest.raises(RuntimeError, match="scripted failure"):
        await agent._run_workflow_step(4, fail())

    terminal = [
        event
        for event in _progress(messages)
        if event.metadata.get("result") is not None
    ]
    assert [event.metadata["result"] for event in terminal] == ["failed"]


async def test_llm_progress_includes_the_selected_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[ChatMessage] = []
    calls: list[str | None] = []

    async def collect(message: ChatMessage) -> None:
        messages.append(message)

    async def fake_chat(
        _messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        **_kwargs: Any,
    ) -> str:
        calls.append(model)
        return "done"

    monkeypatch.setattr(orchestrator_module.llm_client.llm, "chat", fake_chat)
    agent = Orchestrator(AgentState(), on_message=collect)
    agent.state.set_step(3)

    assert await agent._call_llm("prompt") == "done"
    assert calls == [orchestrator_module.settings.sentinel_primary_model]
    llm_events = [
        event
        for event in _progress(messages)
        if event.metadata["phase"] == "llm.step_3"
    ]
    assert len(llm_events) == 2
    assert all(calls[0] in event.content for event in llm_events)
    assert llm_events[-1].metadata["result"] == "ok"


async def test_deferred_live_test_reports_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[ChatMessage] = []

    async def collect(message: ChatMessage) -> None:
        messages.append(message)

    class FakeRunner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run_suite(self, _suite: Any) -> RunResult:
            result = RunResult(results=[
                CaseResult(
                    test_id="TC-1",
                    status=CaseStatus.PASS,
                    message="Static runner cannot prove the live test.",
                )
            ])
            result.recount()
            return result

    monkeypatch.setattr(
        orchestrator_module.test_runner,
        "StaticTestRunner",
        FakeRunner,
    )
    state = AgentState(max_iterations=1)
    state.test_suite = {
        "structured": {
            "name": "live",
            "test_cases": [
                {
                    "id": "TC-1",
                    "name": "screen reader",
                    "type": "accessibility",
                }
            ],
        }
    }
    agent = Orchestrator(state, on_message=collect)

    assert await agent.run_fix_loop() is False
    terminal = {
        str(event.metadata["phase"]): event.metadata["result"]
        for event in _progress(messages)
        if event.metadata.get("result") is not None
    }
    assert terminal["tests.run_1"] == "deferred"
    assert terminal["fix_loop.iteration_1"] == "deferred"
    assert "ok" not in {
        event.metadata["result"]
        for event in _progress(messages)
        if event.metadata.get("phase") in {"tests.run_1", "fix_loop.iteration_1"}
        and event.metadata.get("result") is not None
    }


async def test_legacy_upload_and_parse_start_metadata_shape_is_unchanged() -> None:
    messages: list[ChatMessage] = []

    async def collect(message: ChatMessage) -> None:
        messages.append(message)

    agent = Orchestrator(AgentState(), on_message=collect)
    await agent.emit_progress(
        phase="upload",
        current=0,
        total=1,
        detail="Saving export.zip.",
    )
    await agent.emit_progress(
        phase="parsing",
        current=4,
        total=10,
        detail="Parsing files.",
    )

    assert [message.metadata for message in messages] == [
        {"progress": True, "phase": "upload", "current": 0, "total": 1},
        {"progress": True, "phase": "parsing", "current": 4, "total": 10},
    ]
