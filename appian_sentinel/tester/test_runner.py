"""Abstract test runner and a static (validator-based) implementation.

:class:`TestRunner` defines the interface; :class:`StaticTestRunner`
executes test suites against :class:`SailValidator` without needing a
running Appian environment.
"""

from __future__ import annotations

import abc
import logging

from appian_sentinel.models.test_case import (
    TestCase,
    TestCaseResult,
    TestCaseStatus,
    TestRunResult,
    TestSuite,
)
from appian_sentinel.parser.sail_diagnostics import DiagnosticSeverity
from appian_sentinel.tester.sail_validator import SailValidator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class TestRunner(abc.ABC):
    """Protocol for running a :class:`TestSuite`."""

    @abc.abstractmethod
    async def run_suite(self, suite: TestSuite) -> TestRunResult:
        """Execute every test case in *suite* and return aggregated results."""

    @abc.abstractmethod
    async def run_case(self, case: TestCase) -> TestCaseResult:
        """Execute a single test case and return the result."""


# ---------------------------------------------------------------------------
# Static test runner (structural validation only)
# ---------------------------------------------------------------------------

class StaticTestRunner(TestRunner):
    """Run tests by structurally validating SAIL code.

    This runner does **not** execute SAIL in an Appian environment.
    Instead it:

    1. Validates the SAIL code with :class:`SailValidator`.
    2. Checks UUID references against a known set.
    3. Checks bracket balance, forbidden patterns, and hallucinated functions.
    4. Reports pass/fail based on static analysis.

    The runner requires a mapping from object names to their SAIL code,
    and optionally a set of known UUIDs for reference validation.
    """

    def __init__(
        self,
        sail_code_map: dict[str, str] | None = None,
        known_uuids: set[str] | None = None,
        declared_inputs_map: dict[str, list[str]] | None = None,
        validator: SailValidator | None = None,
    ) -> None:
        """
        Parameters
        ----------
        sail_code_map:
            ``{object_name: sail_code}`` for every object under test.
        known_uuids:
            Set of valid UUIDs for reference resolution checks.
        declared_inputs_map:
            ``{object_name: [input_name, ...]}`` for rule-input validation.
        validator:
            Optional pre-configured :class:`SailValidator` instance.
        """
        self._code_map: dict[str, str] = sail_code_map or {}
        self._known_uuids: set[str] = known_uuids or set()
        self._inputs_map: dict[str, list[str]] = declared_inputs_map or {}
        self._validator = validator or SailValidator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_suite(self, suite: TestSuite) -> TestRunResult:
        """Run all test cases in *suite* sequentially."""
        result = TestRunResult()
        for case in suite.test_cases:
            case_result = await self.run_case(case)
            result.results.append(case_result)
            if case_result.status == TestCaseStatus.PASS:
                result.passed += 1
            elif case_result.status == TestCaseStatus.FAIL:
                result.failed += 1
            elif case_result.status == TestCaseStatus.ERROR:
                result.errors += 1
            else:
                result.skipped += 1
        return result

    async def run_case(self, case: TestCase) -> TestCaseResult:
        """Run a single test case against the static validator.

        The test case's steps are inspected for ``input_data`` keys that
        reference object names; if the corresponding SAIL code is found
        in the code map, it is validated.  If no code is found, the test
        is marked as *skipped*.
        """
        try:
            return self._execute_static(case)
        except Exception as exc:
            logger.exception("Error running test case %s", case.id)
            return TestCaseResult(
                test_id=case.id,
                status=TestCaseStatus.ERROR,
                message=f"Unexpected error: {exc}",
            )

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute_static(self, case: TestCase) -> TestCaseResult:
        """Core static-analysis logic for one test case."""
        # Determine which objects this test touches
        target_objects = self._resolve_targets(case)
        if not target_objects:
            return TestCaseResult(
                test_id=case.id,
                status=TestCaseStatus.SKIPPED,
                message="No SAIL code found for the objects referenced by this test",
            )

        all_errors: list[str] = []
        all_warnings: list[str] = []

        for obj_name, code in target_objects.items():
            declared = self._inputs_map.get(obj_name)
            analysis = self._validator.analyze(
                code,
                known_uuids=self._known_uuids,
                declared_inputs=declared,
            )
            for finding in analysis.diagnostics:
                rendered = (
                    f"[{obj_name}] {finding.code} "
                    f"L{finding.line}:C{finding.column} {finding.message}"
                )
                if finding.severity == DiagnosticSeverity.ERROR:
                    all_errors.append(rendered)
                else:
                    all_warnings.append(rendered)

        if all_errors:
            return TestCaseResult(
                test_id=case.id,
                status=TestCaseStatus.FAIL,
                message=f"{len(all_errors)} validation error(s)",
                details={"errors": all_errors, "warnings": all_warnings},
            )

        return TestCaseResult(
            test_id=case.id,
            status=TestCaseStatus.PASS,
            message="Static validation passed",
            details={"warnings": all_warnings} if all_warnings else {},
        )

    def _resolve_targets(self, case: TestCase) -> dict[str, str]:
        """Identify SAIL code blobs referenced by a test case.

        Looks at:
        - ``case.steps[*].input_data["object_name"]``
        - ``case.steps[*].input_data["objects"]`` (list)
        - Falls back to scanning for any key in ``self._code_map`` that
          appears in the test name or preconditions.
        """
        targets: dict[str, str] = {}

        # Explicit references in step input_data
        for step in case.steps:
            obj = step.input_data.get("object_name")
            if isinstance(obj, str) and obj in self._code_map:
                targets[obj] = self._code_map[obj]

            objs = step.input_data.get("objects")
            if isinstance(objs, list):
                for o in objs:
                    if isinstance(o, str) and o in self._code_map:
                        targets[o] = self._code_map[o]

        # Heuristic: match code-map keys against test metadata
        if not targets:
            search_text = " ".join([
                case.name,
                case.expected_result,
                *case.preconditions,
            ]).lower()
            for name, code in self._code_map.items():
                if name.lower() in search_text:
                    targets[name] = code

        # Last resort: validate ALL code in the map
        if not targets and self._code_map:
            targets = dict(self._code_map)

        return targets
