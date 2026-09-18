from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from appian_sentinel.agent import orchestrator as orchestrator_module
from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.models import test_case as tc

UUID = "_a-11111111-1111-8000-1111-111111111111_100001"
VERSION_UUID = "_a-11111111-1111-8000-1111-111111111111_100002"


class _CodeAwareRunner:
    calls = 0

    def __init__(self, *, sail_code_map: dict[str, str], **_kwargs: Any) -> None:
        self._fixed = sail_code_map.get("APP_RequestView") == "a!textField()"

    async def run_suite(self, suite: Any) -> tc.TestRunResult:
        type(self).calls += 1
        status = tc.TestCaseStatus.PASS if self._fixed else tc.TestCaseStatus.FAIL
        results = [
            tc.TestCaseResult(
                test_id=case.id,
                name=case.name,
                status=status,
                message="fixed" if self._fixed else "invalid SAIL",
            )
            for case in suite.test_cases
        ]
        result = tc.TestRunResult(results=results)
        result.recount()
        return result


class _AlwaysFailRunner:
    calls = 0

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def run_suite(self, suite: Any) -> tc.TestRunResult:
        type(self).calls += 1
        results = [
            tc.TestCaseResult(
                test_id=case.id,
                name=case.name,
                status=tc.TestCaseStatus.FAIL,
                message="still red",
            )
            for case in suite.test_cases
        ]
        result = tc.TestRunResult(results=results)
        result.recount()
        return result


def _state(max_iterations: int) -> AgentState:
    state = AgentState(max_iterations=max_iterations)
    state.user_story = {
        "title": "Request view",
        "acceptance_criteria": [
            {"id": "AC-1", "description": "The view renders."},
            {"id": "AC-2", "description": "Invalid input is rejected."},
        ],
    }
    state.test_suite = {
        "structured": {
            "name": "acceptance",
            "test_cases": [
                {"id": "TC-1", "name": "render", "linked_ac": "AC-1"},
                {
                    "id": "TC-2",
                    "name": "reject invalid",
                    "type": "negative",
                    "linked_ac": "AC-2",
                },
            ],
            "coverage_map": {"AC-1": ["TC-1"], "AC-2": ["TC-2"]},
        }
    }
    state.generated_objects = [
        {
            "type": "interface",
            "name": "APP_RequestView",
            "uuid": UUID,
            "versionUuid": VERSION_UUID,
            "action": "create",
            "sail_code": "broken",
        }
    ]
    return state


async def _fake_llm_transport(
    messages: list[dict[str, str]],
    **_kwargs: Any,
) -> str:
    assert "invalid SAIL" in messages[0]["content"] or "still red" in messages[0]["content"]
    return json.dumps(
        [
            {
                "type": "interface",
                "name": "APP_RequestView",
                "uuid": UUID,
                "versionUuid": VERSION_UUID,
                "action": "create",
                "sail_code": "a!textField()",
            }
        ]
    )


async def test_fix_loop_starts_red_applies_fix_and_ends_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(max_iterations=3)
    agent = Orchestrator(state)
    agent._workspace = tmp_path
    agent._export_dir = tmp_path
    _CodeAwareRunner.calls = 0
    monkeypatch.setattr(
        orchestrator_module.test_runner,
        "StaticTestRunner",
        _CodeAwareRunner,
    )
    monkeypatch.setattr(
        "appian_sentinel.agent.orchestrator.llm_client.llm.chat",
        _fake_llm_transport,
    )

    assert await agent.run_fix_loop() is True
    assert state.iteration == 2
    assert _CodeAwareRunner.calls == 2
    assert state.test_results is not None
    assert state.test_results["passed"] is True
    assert state.test_results["passed_count"] == 2
    assert state.test_results["failures"] == []
    assert (tmp_path / "content" / f"{UUID}.xml").is_file()
    assert {item["linked_ac"] for item in state.test_suite["structured"]["test_cases"]} == {
        "AC-1",
        "AC-2",
    }


async def test_fix_loop_stops_at_budget_when_tests_never_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(max_iterations=2)
    agent = Orchestrator(state)
    agent._workspace = tmp_path
    agent._export_dir = tmp_path
    _AlwaysFailRunner.calls = 0
    monkeypatch.setattr(
        orchestrator_module.test_runner,
        "StaticTestRunner",
        _AlwaysFailRunner,
    )
    monkeypatch.setattr(
        "appian_sentinel.agent.orchestrator.llm_client.llm.chat",
        _fake_llm_transport,
    )

    assert await agent.run_fix_loop() is False
    assert state.iteration == 2
    assert _AlwaysFailRunner.calls == 2
    assert state.test_results is not None
    assert state.test_results["passed"] is False
    assert len(state.test_results["failures"]) == 2
