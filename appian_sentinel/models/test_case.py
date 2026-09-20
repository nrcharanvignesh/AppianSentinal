"""Test-case and test-suite domain models used by the tester subsystem."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TestCaseType(str, Enum):
    """Classification of a test case."""

    FUNCTIONAL = "functional"
    NEGATIVE = "negative"
    EDGE = "edge"
    REGRESSION = "regression"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"


class TestCasePriority(str, Enum):
    """Execution priority."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestCaseStatus(str, Enum):
    """Outcome of a single test-case execution."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"
    DEFERRED = "deferred"


class TestExecutionScope(str, Enum):
    """Where a test case can actually be proven.

    ``STATIC`` tests are decidable by structural analysis of SAIL code.
    ``LIVE_APPIAN`` tests need a running Appian environment, so a static
    runner can never turn them green.
    """

    STATIC = "static"
    LIVE_APPIAN = "live_appian"


class AppianAssertionType(str, Enum):
    """Assertion modes supported by Appian expression-rule test cases."""

    COMPLETES_WITHOUT_ERROR = "completes_without_error"
    OUTPUT_EQUALS = "output_equals"
    EXPRESSION = "expression"


# Test types that cannot be proven without a running Appian environment.
LIVE_APPIAN_TEST_TYPES: frozenset[TestCaseType] = frozenset({
    TestCaseType.PERFORMANCE,
    TestCaseType.ACCESSIBILITY,
})

# Coverage classification of test types.
POSITIVE_TEST_TYPES: frozenset[TestCaseType] = frozenset({
    TestCaseType.FUNCTIONAL,
    TestCaseType.REGRESSION,
})
NEGATIVE_TEST_TYPES: frozenset[TestCaseType] = frozenset({
    TestCaseType.NEGATIVE,
    TestCaseType.EDGE,
})

# Coverage dimensions reported as missing in a CoverageGap.
COVERAGE_POSITIVE = "positive"
COVERAGE_NEGATIVE = "negative_or_edge"


def normalize_ac_id(ac_id: str) -> str:
    """Return a comparable form of an acceptance-criteria ID."""
    return ac_id.strip().upper()


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class TestStep(BaseModel):
    """A single action inside a test case."""

    action: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""


class TestCase(BaseModel):
    """One test case with its steps, linkage, and metadata."""

    id: str
    name: str
    type: TestCaseType = TestCaseType.FUNCTIONAL
    linked_ac: str = ""  # acceptance-criteria ID
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    expected_result: str = ""
    assertion_type: AppianAssertionType = AppianAssertionType.COMPLETES_WITHOUT_ERROR
    asserted_output: Any = None
    assertion_expression: str = ""
    priority: TestCasePriority = TestCasePriority.MEDIUM
    execution_scope: TestExecutionScope = TestExecutionScope.STATIC

    @model_validator(mode="after")
    def _force_live_scope_for_live_only_types(self) -> TestCase:
        """Pin performance and accessibility tests to the live-Appian scope."""
        if self.type in LIVE_APPIAN_TEST_TYPES:
            self.execution_scope = TestExecutionScope.LIVE_APPIAN
        if self.assertion_type is AppianAssertionType.EXPRESSION:
            if not self.assertion_expression.strip():
                raise ValueError("Expression assertions require assertion_expression.")
            if "test!output" not in self.assertion_expression.casefold():
                raise ValueError("Expression assertions must reference test!output.")
        elif self.assertion_expression.strip():
            raise ValueError("assertion_expression requires assertion_type='expression'.")
        if (
            self.assertion_type is AppianAssertionType.COMPLETES_WITHOUT_ERROR
            and self.asserted_output is not None
        ):
            raise ValueError("No-error assertions cannot define asserted_output.")
        return self


class TestSuite(BaseModel):
    """A collection of test cases with coverage mapping."""

    name: str
    test_cases: list[TestCase] = Field(default_factory=list)
    coverage_map: dict[str, list[str]] = Field(default_factory=dict)
    """Maps acceptance-criteria ID -> list of test-case IDs."""

    def linked_types_by_ac(self) -> dict[str, set[TestCaseType]]:
        """Map normalized AC ID -> the test types linked to it.

        Both ``TestCase.linked_ac`` and ``coverage_map`` are honoured.
        """
        by_id = {case.id: case for case in self.test_cases}
        linked: dict[str, set[TestCaseType]] = {}

        for case in self.test_cases:
            if case.linked_ac.strip():
                linked.setdefault(normalize_ac_id(case.linked_ac), set()).add(case.type)

        for ac_id, test_ids in self.coverage_map.items():
            if not ac_id.strip():
                continue
            bucket = linked.setdefault(normalize_ac_id(ac_id), set())
            for test_id in test_ids:
                case = by_id.get(test_id)
                if case is not None:
                    bucket.add(case.type)

        return linked

    def linked_test_ids(self, ac_id: str) -> list[str]:
        """Return the sorted test-case IDs linked to *ac_id*."""
        wanted = normalize_ac_id(ac_id)
        ids = {
            case.id
            for case in self.test_cases
            if normalize_ac_id(case.linked_ac) == wanted
        }
        by_id = {case.id for case in self.test_cases}
        for mapped_ac, test_ids in self.coverage_map.items():
            if normalize_ac_id(mapped_ac) == wanted:
                ids.update(test_id for test_id in test_ids if test_id in by_id)
        return sorted(ids)

    def validate_coverage(
        self,
        acceptance_criteria: Sequence[str] | None = None,
    ) -> CoverageReport:
        """Check that every acceptance criterion has positive and negative cover.

        Deterministic: no LLM involved. A criterion is covered when it is
        linked to at least one positive test (functional or regression) and at
        least one negative or edge test. Performance and accessibility tests
        are non-functional and satisfy neither dimension.

        Parameters
        ----------
        acceptance_criteria:
            The criteria that must be covered. When ``None`` the criteria
            referenced by the suite itself are used, which only verifies the
            suite's internal consistency.
        """
        linked = self.linked_types_by_ac()

        if acceptance_criteria is None:
            required = sorted(linked)
        else:
            required = [ac_id for ac_id in acceptance_criteria if ac_id.strip()]

        required_normalized = {normalize_ac_id(ac_id) for ac_id in required}

        covered: list[str] = []
        gaps: list[CoverageGap] = []
        for ac_id in required:
            types = linked.get(normalize_ac_id(ac_id), set())
            missing: list[str] = []
            if not types & POSITIVE_TEST_TYPES:
                missing.append(COVERAGE_POSITIVE)
            if not types & NEGATIVE_TEST_TYPES:
                missing.append(COVERAGE_NEGATIVE)
            if missing:
                gaps.append(CoverageGap(
                    ac_id=ac_id,
                    missing=missing,
                    linked_test_ids=self.linked_test_ids(ac_id),
                ))
            else:
                covered.append(ac_id)

        mapped_test_ids = {
            test_id for test_ids in self.coverage_map.values() for test_id in test_ids
        }
        unlinked = sorted(
            case.id
            for case in self.test_cases
            if not case.linked_ac.strip() and case.id not in mapped_test_ids
        )
        unknown = sorted(
            ac_id for ac_id in linked if ac_id not in required_normalized
        )

        return CoverageReport(
            acceptance_criteria=required,
            covered=covered,
            gaps=gaps,
            unlinked_test_ids=unlinked,
            unknown_ac_ids=unknown,
        )


# ---------------------------------------------------------------------------
# Coverage models
# ---------------------------------------------------------------------------

class CoverageGap(BaseModel):
    """A criterion that lacks positive and/or negative coverage."""

    ac_id: str
    missing: list[str] = Field(default_factory=list)
    linked_test_ids: list[str] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """Deterministic acceptance-criteria coverage verdict for a suite."""

    acceptance_criteria: list[str] = Field(default_factory=list)
    covered: list[str] = Field(default_factory=list)
    gaps: list[CoverageGap] = Field(default_factory=list)
    unlinked_test_ids: list[str] = Field(default_factory=list)
    unknown_ac_ids: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def is_complete(self) -> bool:
        """True only when criteria exist and every one of them is covered."""
        return bool(self.acceptance_criteria) and not self.gaps

    @computed_field
    @property
    def summary(self) -> str:
        """One-line ASCII summary of the coverage verdict."""
        if not self.acceptance_criteria:
            return "no acceptance criteria available, coverage cannot be verified"
        text = (
            f"{len(self.covered)}/{len(self.acceptance_criteria)} "
            "acceptance criteria covered"
        )
        if self.gaps:
            details = "; ".join(
                f"{gap.ac_id} missing {', '.join(gap.missing)}" for gap in self.gaps
            )
            text += f"; gaps: {details}"
        if self.unlinked_test_ids:
            text += f"; {len(self.unlinked_test_ids)} test(s) linked to no criterion"
        if self.unknown_ac_ids:
            text += f"; {len(self.unknown_ac_ids)} unknown criterion ID(s) referenced"
        return text


# ---------------------------------------------------------------------------
# Execution-result models
# ---------------------------------------------------------------------------

class TestCaseResult(BaseModel):
    """Outcome of running a single *TestCase*."""

    test_id: str
    status: TestCaseStatus
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    name: str = ""
    execution_scope: TestExecutionScope = TestExecutionScope.STATIC


class TestRunResult(BaseModel):
    """Aggregated outcome of running a *TestSuite*.

    ``passed``, ``failed``, ``errors``, ``skipped``, and ``deferred`` are
    counts, never verdicts. Use :attr:`success` for the verdict.
    """

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    deferred: int = 0
    results: list[TestCaseResult] = Field(default_factory=list)

    @computed_field
    @property
    def total(self) -> int:
        """Number of counted test cases."""
        return self.passed + self.failed + self.errors + self.skipped + self.deferred

    @computed_field
    @property
    def failures(self) -> list[TestCaseResult]:
        """Results that failed or errored."""
        return [
            r for r in self.results
            if r.status in (TestCaseStatus.FAIL, TestCaseStatus.ERROR)
        ]

    @computed_field
    @property
    def unverified(self) -> list[TestCaseResult]:
        """Results the runner could not decide, excluding deferred ones."""
        return [r for r in self.results if r.status is TestCaseStatus.SKIPPED]

    @computed_field
    @property
    def deferred_results(self) -> list[TestCaseResult]:
        """Results that need a live Appian environment."""
        return [r for r in self.results if r.status is TestCaseStatus.DEFERRED]

    @computed_field
    @property
    def success(self) -> bool:
        """True only when the run proves every counted test case passed.

        An empty run, a skipped-only run, a deferred-only run, and a run whose
        counters disagree with :attr:`results` all report ``False``.
        """
        if self.passed <= 0 or self.failed or self.errors or self.skipped:
            return False
        return self.total == len(self.results)

    @computed_field
    @property
    def verdict_reason(self) -> str:
        """ASCII explanation of the :attr:`success` verdict."""
        if self.total == 0 and not self.results:
            return "no test case was executed"
        if self.total != len(self.results):
            return (
                f"counter mismatch: {self.total} counted, "
                f"{len(self.results)} recorded result(s)"
            )
        problems: list[str] = []
        if self.failed:
            problems.append(f"{self.failed} failed")
        if self.errors:
            problems.append(f"{self.errors} errored")
        if self.skipped:
            problems.append(f"{self.skipped} skipped (unverified)")
        if self.passed <= 0:
            problems.append("no test passed")
        deferred_note = (
            f", {self.deferred} deferred (live Appian required)" if self.deferred else ""
        )
        if problems:
            return ", ".join(problems) + deferred_note
        return f"{self.passed} passed" + deferred_note

    def recount(self) -> None:
        """Recompute the status counters from :attr:`results`."""
        counts = Counter(r.status for r in self.results)
        self.passed = counts[TestCaseStatus.PASS]
        self.failed = counts[TestCaseStatus.FAIL]
        self.errors = counts[TestCaseStatus.ERROR]
        self.skipped = counts[TestCaseStatus.SKIPPED]
        self.deferred = counts[TestCaseStatus.DEFERRED]
