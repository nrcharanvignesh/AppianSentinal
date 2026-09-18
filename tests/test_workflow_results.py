"""Guards against false-green test runs in the agentic fix loop."""

from __future__ import annotations

from typing import Any

import pytest

from appian_sentinel.agent import orchestrator as orchestrator_module
from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.models import test_case as tc

# Aliased to keep pytest from trying to collect the ``Test*`` model classes.
Case = tc.TestCase
CaseResult = tc.TestCaseResult
CaseType = tc.TestCaseType
RunResult = tc.TestRunResult
Scope = tc.TestExecutionScope
Status = tc.TestCaseStatus
Suite = tc.TestSuite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(test_id: str, status: tc.TestCaseStatus) -> tc.TestCaseResult:
    return CaseResult(test_id=test_id, status=status, message=f"{test_id} {status.value}")


def _run(*statuses: tc.TestCaseStatus) -> tc.TestRunResult:
    run = RunResult(results=[_result(f"TC-{i}", s) for i, s in enumerate(statuses, 1)])
    run.recount()
    return run


def _suite(*cases: tc.TestCase) -> tc.TestSuite:
    return Suite(name="suite", test_cases=list(cases))


def _orchestrator(state: AgentState | None = None) -> Orchestrator:
    return Orchestrator(state or AgentState())


class _FakeRunner:
    """Stand-in for StaticTestRunner returning a scripted result."""

    scripted: tc.TestRunResult = RunResult()
    calls: int = 0

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def run_suite(self, suite: tc.TestSuite) -> tc.TestRunResult:
        type(self).calls += 1
        return type(self).scripted.model_copy(deep=True)


# ---------------------------------------------------------------------------
# TestRunResult verdict semantics
# ---------------------------------------------------------------------------

def test_passed_is_a_count_not_a_verdict() -> None:
    run = _run(Status.PASS, Status.FAIL)
    assert run.passed == 1
    assert bool(run.passed) is True  # the old false-green trigger
    assert run.success is False
    assert "1 failed" in run.verdict_reason


def test_failures_cover_fail_and_error_results() -> None:
    run = _run(Status.PASS, Status.FAIL, Status.ERROR)
    assert [r.test_id for r in run.failures] == ["TC-2", "TC-3"]
    assert run.failed == 1
    assert run.errors == 1
    assert run.success is False


def test_empty_run_cannot_pass() -> None:
    run = RunResult()
    assert run.total == 0
    assert run.success is False
    assert run.verdict_reason == "no test case was executed"


def test_skipped_only_run_cannot_pass() -> None:
    run = _run(Status.SKIPPED, Status.SKIPPED)
    assert run.success is False
    assert [r.test_id for r in run.unverified] == ["TC-1", "TC-2"]
    assert "no test passed" in run.verdict_reason


def test_partially_skipped_run_cannot_pass() -> None:
    run = _run(Status.PASS, Status.SKIPPED)
    assert run.success is False
    assert "1 skipped (unverified)" in run.verdict_reason


def test_deferred_only_run_cannot_pass() -> None:
    run = _run(Status.DEFERRED)
    assert run.success is False
    assert run.deferred == 1
    assert [r.test_id for r in run.deferred_results] == ["TC-1"]


def test_all_passing_run_with_deferred_tests_is_green() -> None:
    run = _run(Status.PASS, Status.DEFERRED)
    assert run.success is True
    assert run.verdict_reason == "1 passed, 1 deferred (live Appian required)"


def test_all_passing_run_is_green() -> None:
    run = _run(Status.PASS, Status.PASS)
    assert run.success is True
    assert run.verdict_reason == "2 passed"


def test_counter_and_result_mismatch_cannot_pass() -> None:
    run = RunResult(passed=3, results=[_result("TC-1", Status.PASS)])
    assert run.success is False
    assert "counter mismatch" in run.verdict_reason
    run.recount()
    assert run.passed == 1
    assert run.success is True


def test_model_dump_exposes_the_verdict_and_failures() -> None:
    dumped = _run(Status.PASS, Status.FAIL).model_dump(mode="json")
    assert dumped["passed"] == 1
    assert dumped["success"] is False
    assert [f["test_id"] for f in dumped["failures"]] == ["TC-2"]


# ---------------------------------------------------------------------------
# Static vs live-Appian distinction
# ---------------------------------------------------------------------------

def test_static_pass_on_a_live_appian_test_is_deferred() -> None:
    suite = _suite(
        Case(id="TC-1", name="load speed", type=CaseType.PERFORMANCE),
        Case(id="TC-2", name="screen reader", type=CaseType.ACCESSIBILITY),
        Case(id="TC-3", name="happy path", type=CaseType.FUNCTIONAL),
    )
    run = RunResult(results=[
        _result("TC-1", Status.PASS),
        _result("TC-2", Status.SKIPPED),
        _result("TC-3", Status.PASS),
    ])

    annotated = Orchestrator._annotate_static_run(suite, run)

    statuses = {r.test_id: r.status for r in annotated.results}
    assert statuses["TC-1"] is Status.DEFERRED
    assert statuses["TC-2"] is Status.DEFERRED
    assert statuses["TC-3"] is Status.PASS
    assert annotated.deferred == 2
    assert annotated.passed == 1
    assert annotated.success is True
    assert annotated.results[0].execution_scope is Scope.LIVE_APPIAN
    assert annotated.results[2].execution_scope is Scope.STATIC


def test_static_failure_on_a_live_appian_test_stays_a_failure() -> None:
    suite = _suite(Case(id="TC-1", name="load speed", type=CaseType.PERFORMANCE))
    run = RunResult(results=[_result("TC-1", Status.FAIL)])

    annotated = Orchestrator._annotate_static_run(suite, run)

    assert annotated.failed == 1
    assert annotated.success is False


def test_unreported_test_case_becomes_an_error() -> None:
    suite = _suite(
        Case(id="TC-1", name="happy path"),
        Case(id="TC-2", name="missing from results"),
    )
    run = RunResult(results=[_result("TC-1", Status.PASS)])

    annotated = Orchestrator._annotate_static_run(suite, run)

    assert annotated.errors == 1
    assert annotated.success is False
    assert annotated.results[1].test_id == "TC-2"


def test_annotation_fills_result_names() -> None:
    suite = _suite(Case(id="TC-1", name="happy path"))
    run = RunResult(results=[_result("TC-1", Status.PASS)])

    annotated = Orchestrator._annotate_static_run(suite, run)

    assert annotated.results[0].name == "happy path"


# ---------------------------------------------------------------------------
# Orchestrator plumbing
# ---------------------------------------------------------------------------

def test_build_test_suite_returns_none_without_structured_suite() -> None:
    agent = _orchestrator()
    assert agent.build_test_suite() is None

    agent.state.test_suite = {"raw": "some prose"}
    assert agent.build_test_suite() is None

    agent.state.test_suite = {"structured": {"name": "s", "test_cases": "not-a-list"}}
    assert agent.build_test_suite() is None


def test_build_test_suite_parses_structured_suite() -> None:
    agent = _orchestrator()
    agent.state.test_suite = {"structured": {
        "name": "generated",
        "test_cases": [{"id": "TC-1", "name": "happy path"}],
    }}
    suite = agent.build_test_suite()
    assert suite is not None
    assert [c.id for c in suite.test_cases] == ["TC-1"]


async def test_run_tests_without_a_suite_is_not_green() -> None:
    run = await _orchestrator().run_tests()
    assert run.success is False
    assert run.total == 0


async def test_run_tests_reports_runner_crash_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenRunner:
        def __init__(self, **_kwargs: Any) -> None:
            raise RuntimeError("boom")

    agent = _orchestrator()
    agent.state.test_suite = {"structured": {
        "name": "generated",
        "test_cases": [{"id": "TC-1", "name": "happy path"}],
    }}
    monkeypatch.setattr(orchestrator_module.test_runner, "StaticTestRunner", _BrokenRunner)

    run = await agent.run_tests()

    assert run.success is False
    assert run.errors == 1
    assert "boom" in run.results[0].message


async def test_fix_loop_without_a_suite_returns_false_without_calling_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _orchestrator()
    calls: list[str] = []

    async def _fail(prompt: str) -> str:
        calls.append(prompt)
        return "[]"

    monkeypatch.setattr(agent, "_call_llm", _fail)

    assert await agent.run_fix_loop() is False
    assert calls == []
    assert agent.state.test_results is not None
    assert agent.state.test_results["passed"] is False


async def test_fix_loop_does_not_go_green_on_a_partially_failing_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = AgentState(max_iterations=2)
    agent = _orchestrator(state)
    state.test_suite = {"structured": {
        "name": "generated",
        "test_cases": [
            {"id": "TC-1", "name": "happy path"},
            {"id": "TC-2", "name": "invalid input", "type": "negative"},
        ],
    }}

    _FakeRunner.calls = 0
    _FakeRunner.scripted = _run(Status.PASS, Status.FAIL)
    monkeypatch.setattr(orchestrator_module.test_runner, "StaticTestRunner", _FakeRunner)

    async def _no_fix(prompt: str) -> str:
        return "[]"

    monkeypatch.setattr(agent, "_call_llm", _no_fix)

    assert await agent.run_fix_loop() is False
    assert _FakeRunner.calls == 2
    assert state.test_results is not None
    assert state.test_results["passed"] is False
    assert state.test_results["passed_count"] == 1
    assert [f["name"] for f in state.test_results["failures"]] == ["invalid input"]


async def test_fix_loop_goes_green_when_every_test_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _orchestrator()
    agent.state.test_suite = {"structured": {
        "name": "generated",
        "test_cases": [
            {"id": "TC-1", "name": "happy path"},
            {"id": "TC-2", "name": "load speed", "type": "performance"},
        ],
    }}

    _FakeRunner.calls = 0
    _FakeRunner.scripted = RunResult(results=[
        _result("TC-1", Status.PASS),
        _result("TC-2", Status.PASS),
    ])
    monkeypatch.setattr(orchestrator_module.test_runner, "StaticTestRunner", _FakeRunner)

    assert await agent.run_fix_loop() is True
    assert _FakeRunner.calls == 1
    assert agent.state.test_results is not None
    assert agent.state.test_results["passed"] is True
    assert agent.state.test_results["deferred"] == 1


async def test_fix_loop_stops_when_all_tests_need_live_appian(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _orchestrator()
    agent.state.test_suite = {"structured": {
        "name": "generated",
        "test_cases": [{"id": "TC-1", "name": "screen reader", "type": "accessibility"}],
    }}

    _FakeRunner.calls = 0
    _FakeRunner.scripted = RunResult(results=[_result("TC-1", Status.PASS)])
    monkeypatch.setattr(orchestrator_module.test_runner, "StaticTestRunner", _FakeRunner)

    llm_calls: list[str] = []

    async def _track(prompt: str) -> str:
        llm_calls.append(prompt)
        return "[]"

    monkeypatch.setattr(agent, "_call_llm", _track)

    assert await agent.run_fix_loop() is False
    assert _FakeRunner.calls == 1
    assert llm_calls == []
