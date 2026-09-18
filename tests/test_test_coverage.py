"""Deterministic acceptance-criteria coverage validation."""

from __future__ import annotations

from appian_sentinel.agent.orchestrator import Orchestrator
from appian_sentinel.agent.state import AgentState
from appian_sentinel.models import test_case as tc
from appian_sentinel.models.test_case import COVERAGE_NEGATIVE, COVERAGE_POSITIVE

# Aliased to keep pytest from trying to collect the ``Test*`` model classes.
Case = tc.TestCase
CaseType = tc.TestCaseType
Scope = tc.TestExecutionScope
Suite = tc.TestSuite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _case(test_id: str, ac_id: str, test_type: tc.TestCaseType) -> tc.TestCase:
    return Case(id=test_id, name=f"{test_id} {test_type.value}", type=test_type, linked_ac=ac_id)


def _suite(*cases: tc.TestCase, coverage_map: dict[str, list[str]] | None = None) -> tc.TestSuite:
    return Suite(name="suite", test_cases=list(cases), coverage_map=coverage_map or {})


def _agent(state: AgentState) -> Orchestrator:
    return Orchestrator(state)


# ---------------------------------------------------------------------------
# Execution scope of test types
# ---------------------------------------------------------------------------

def test_functional_tests_are_statically_decidable() -> None:
    case = Case(id="TC-1", name="happy path", type=CaseType.FUNCTIONAL)
    assert case.execution_scope is Scope.STATIC


def test_performance_and_accessibility_tests_require_live_appian() -> None:
    for test_type in (CaseType.PERFORMANCE, CaseType.ACCESSIBILITY):
        case = Case(id="TC-1", name="non functional", type=test_type)
        assert case.execution_scope is Scope.LIVE_APPIAN


def test_declared_static_scope_cannot_override_a_live_only_type() -> None:
    case = Case(
        id="TC-1",
        name="screen reader",
        type=CaseType.ACCESSIBILITY,
        execution_scope=Scope.STATIC,
    )
    assert case.execution_scope is Scope.LIVE_APPIAN


def test_accessibility_type_is_accepted_from_serialised_data() -> None:
    case = Case(**{"id": "TC-1", "name": "contrast", "type": "accessibility"})
    assert case.type is CaseType.ACCESSIBILITY


# ---------------------------------------------------------------------------
# Coverage validation
# ---------------------------------------------------------------------------

def test_positive_and_negative_cover_completes_a_criterion() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.NEGATIVE),
    )
    report = suite.validate_coverage(["AC-1"])

    assert report.is_complete is True
    assert report.covered == ["AC-1"]
    assert report.gaps == []
    assert report.summary == "1/1 acceptance criteria covered"


def test_edge_tests_satisfy_the_negative_dimension() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.EDGE),
    )
    assert suite.validate_coverage(["AC-1"]).is_complete is True


def test_regression_tests_satisfy_the_positive_dimension() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.REGRESSION),
        _case("TC-2", "AC-1", CaseType.EDGE),
    )
    assert suite.validate_coverage(["AC-1"]).is_complete is True


def test_positive_only_cover_is_a_gap() -> None:
    suite = _suite(_case("TC-1", "AC-1", CaseType.FUNCTIONAL))
    report = suite.validate_coverage(["AC-1"])

    assert report.is_complete is False
    assert report.covered == []
    assert [gap.ac_id for gap in report.gaps] == ["AC-1"]
    assert report.gaps[0].missing == [COVERAGE_NEGATIVE]
    assert report.gaps[0].linked_test_ids == ["TC-1"]


def test_negative_only_cover_is_a_gap() -> None:
    suite = _suite(_case("TC-1", "AC-1", CaseType.NEGATIVE))
    report = suite.validate_coverage(["AC-1"])

    assert report.gaps[0].missing == [COVERAGE_POSITIVE]


def test_uncovered_criterion_misses_both_dimensions() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.EDGE),
    )
    report = suite.validate_coverage(["AC-1", "AC-2"])

    assert report.is_complete is False
    assert [gap.ac_id for gap in report.gaps] == ["AC-2"]
    assert report.gaps[0].missing == [COVERAGE_POSITIVE, COVERAGE_NEGATIVE]
    assert report.gaps[0].linked_test_ids == []
    assert "AC-2 missing positive, negative_or_edge" in report.summary


def test_non_functional_tests_do_not_cover_a_criterion() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.PERFORMANCE),
        _case("TC-2", "AC-1", CaseType.ACCESSIBILITY),
    )
    report = suite.validate_coverage(["AC-1"])

    assert report.is_complete is False
    assert report.gaps[0].missing == [COVERAGE_POSITIVE, COVERAGE_NEGATIVE]


def test_coverage_map_links_tests_without_linked_ac() -> None:
    suite = _suite(
        Case(id="TC-1", name="happy path", type=CaseType.FUNCTIONAL),
        Case(id="TC-2", name="bad input", type=CaseType.NEGATIVE),
        coverage_map={"AC-1": ["TC-1", "TC-2"]},
    )
    report = suite.validate_coverage(["AC-1"])

    assert report.is_complete is True
    assert report.unlinked_test_ids == []
    assert suite.linked_test_ids("AC-1") == ["TC-1", "TC-2"]


def test_criterion_ids_match_case_insensitively_and_ignore_padding() -> None:
    suite = _suite(
        _case("TC-1", " ac-1 ", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.NEGATIVE),
    )
    assert suite.validate_coverage(["AC-1"]).is_complete is True


def test_tests_linked_to_nothing_are_reported() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.NEGATIVE),
        Case(id="TC-3", name="orphan", type=CaseType.FUNCTIONAL),
    )
    report = suite.validate_coverage(["AC-1"])

    assert report.is_complete is True
    assert report.unlinked_test_ids == ["TC-3"]
    assert "1 test(s) linked to no criterion" in report.summary


def test_unknown_criterion_ids_are_reported() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.NEGATIVE),
        _case("TC-3", "AC-9", CaseType.FUNCTIONAL),
    )
    report = suite.validate_coverage(["AC-1"])

    assert report.unknown_ac_ids == ["AC-9"]
    assert "1 unknown criterion ID(s) referenced" in report.summary


def test_missing_criteria_make_coverage_unverifiable() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.NEGATIVE),
    )
    report = suite.validate_coverage([])

    assert report.is_complete is False
    assert report.summary == "no acceptance criteria available, coverage cannot be verified"


def test_empty_suite_cannot_cover_anything() -> None:
    report = Suite(name="empty").validate_coverage(["AC-1"])

    assert report.is_complete is False
    assert report.gaps[0].missing == [COVERAGE_POSITIVE, COVERAGE_NEGATIVE]


def test_self_referenced_criteria_are_used_when_none_are_supplied() -> None:
    suite = _suite(
        _case("TC-1", "AC-1", CaseType.FUNCTIONAL),
        _case("TC-2", "AC-1", CaseType.NEGATIVE),
    )
    report = suite.validate_coverage()

    assert report.acceptance_criteria == ["AC-1"]
    assert report.is_complete is True


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------

def test_criteria_ids_come_from_the_structured_user_story() -> None:
    state = AgentState()
    state.user_story = {
        "acceptance_criteria": [{"id": "AC-2"}, {"id": "AC-1"}, {"description": "no id"}],
    }

    assert _agent(state).acceptance_criteria_ids() == ["AC-2", "AC-1", "AC-3"]


def test_criteria_ids_fall_back_to_scanning_the_requirement_analysis() -> None:
    state = AgentState()
    state.requirement_analysis = {"raw": "Covers AC-1 and ac 2, plus AC_3 and AC-1 again."}

    assert _agent(state).acceptance_criteria_ids() == ["AC-1", "AC-2", "AC-3"]


def test_criteria_ids_are_empty_without_a_story() -> None:
    assert _agent(AgentState()).acceptance_criteria_ids() == []


def test_evaluate_coverage_reports_gaps_from_session_state() -> None:
    state = AgentState()
    state.user_story = {"acceptance_criteria": [{"id": "AC-1"}, {"id": "AC-2"}]}
    state.test_suite = {"structured": {
        "name": "generated",
        "test_cases": [
            {"id": "TC-1", "name": "happy path", "type": "functional", "linked_ac": "AC-1"},
            {"id": "TC-2", "name": "bad input", "type": "negative", "linked_ac": "AC-1"},
            {"id": "TC-3", "name": "load speed", "type": "performance", "linked_ac": "AC-2"},
        ],
    }}

    report = _agent(state).evaluate_coverage()

    assert report.is_complete is False
    assert report.covered == ["AC-1"]
    assert [gap.ac_id for gap in report.gaps] == ["AC-2"]


def test_evaluate_coverage_without_a_suite_reports_every_criterion_as_a_gap() -> None:
    state = AgentState()
    state.user_story = {"acceptance_criteria": [{"id": "AC-1"}]}

    report = _agent(state).evaluate_coverage()

    assert report.is_complete is False
    assert [gap.ac_id for gap in report.gaps] == ["AC-1"]
