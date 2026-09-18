"""AI-powered test-case generation for Appian SAIL objects.

Given a user story, solution design, and codebase context the generator
produces a :class:`TestSuite` with functional, negative, edge-case, and
regression tests -- each linked back to acceptance criteria.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from appian_sentinel.analyzer.llm_client import LLMClient, llm
from appian_sentinel.models.test_case import (
    TestCase,
    TestCasePriority,
    TestCaseType,
    TestStep,
    TestSuite,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_TEST_GENERATION_SYSTEM = """\
You are an Appian test architect. Generate comprehensive test cases for
Appian SAIL applications.

For each test case, produce a JSON object with:
- "id": unique string (e.g. "TC-001")
- "name": short descriptive name
- "type": one of "functional", "negative", "edge", "regression", "performance", "accessibility"
- "linked_ac": the acceptance-criteria ID this test validates (e.g. "AC-1")
- "preconditions": list of strings
- "steps": list of {"action": str, "input_data": dict, "expected_output": str}
- "expected_result": overall expected outcome
- "priority": one of "critical", "high", "medium", "low"

Return a JSON object:
{
  "name": "<suite name>",
  "test_cases": [ ... ],
  "coverage_map": { "<AC-id>": ["TC-001", ...], ... }
}

Requirements:
1. Include at least one FUNCTIONAL test per acceptance criterion.
2. Include NEGATIVE tests for invalid inputs and boundary violations.
3. Include EDGE cases (empty lists, null values, very long strings, etc.).
4. Include REGRESSION tests when modifying existing objects.
5. Include PERFORMANCE and ACCESSIBILITY tests for applicable scenarios.
6. Map every test case to at least one acceptance criterion.
"""

_REGRESSION_SYSTEM = """\
You are an Appian regression-test architect. Given a list of modified
objects and the surrounding codebase map, generate regression test cases
that verify:
1. The modified object still works as intended.
2. Dependent objects are not broken by the change.
3. Data flows through the modified path correctly.

Return a JSON array of test-case objects (same schema as above).
"""


# ---------------------------------------------------------------------------
# TestGenerator
# ---------------------------------------------------------------------------

class TestGenerator:
    """Generate test suites and regression tests via LLM."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or llm

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _chat(self, system: str, user: str) -> str:
        """Run a chat completion and return the raw content."""
        return await self._client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )

    @staticmethod
    def _clean_json(raw: str) -> str:
        """Strip markdown fences and whitespace from an LLM response."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.index("\n")
            cleaned = cleaned[first_nl + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        return cleaned

    @staticmethod
    def _parse_test_case(data: dict[str, Any]) -> TestCase:
        """Parse a single test-case dict into a :class:`TestCase`."""
        steps = []
        for s in data.get("steps", []):
            steps.append(TestStep(
                action=s.get("action", ""),
                input_data=s.get("input_data", {}),
                expected_output=s.get("expected_output", ""),
            ))

        tc_type = data.get("type", "functional")
        try:
            tc_type_enum = TestCaseType(tc_type)
        except ValueError:
            tc_type_enum = TestCaseType.FUNCTIONAL

        priority = data.get("priority", "medium")
        try:
            priority_enum = TestCasePriority(priority)
        except ValueError:
            priority_enum = TestCasePriority.MEDIUM

        return TestCase(
            id=data.get("id", "TC-???"),
            name=data.get("name", "Unnamed test"),
            type=tc_type_enum,
            linked_ac=data.get("linked_ac", ""),
            preconditions=data.get("preconditions", []),
            steps=steps,
            expected_result=data.get("expected_result", ""),
            priority=priority_enum,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_test_suite(
        self,
        story: str,
        solution_design: str,
        codebase_context: str = "",
    ) -> TestSuite:
        """Generate a full test suite for a user story + solution design.

        Parameters
        ----------
        story:
            The user story or feature description with acceptance criteria.
        solution_design:
            Technical solution design describing the SAIL objects involved.
        codebase_context:
            Summary of existing objects, CDTs, record types, etc.

        Returns
        -------
        TestSuite
            A populated suite with coverage mapping.
        """
        user_prompt = f"""\
## User Story
{story}

## Solution Design
{solution_design}

## Codebase Context
{codebase_context or "No additional context."}

Generate a comprehensive test suite covering functional, negative,
edge-case, and regression scenarios.  Ensure every acceptance criterion
has at least one test.
"""
        raw = await self._chat(_TEST_GENERATION_SYSTEM, user_prompt)
        cleaned = self._clean_json(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse test-suite JSON from LLM response")
            return TestSuite(name="ParseError", test_cases=[], coverage_map={})

        test_cases = [self._parse_test_case(tc) for tc in data.get("test_cases", [])]
        coverage_map: dict[str, list[str]] = data.get("coverage_map", {})

        # Auto-build coverage map if the LLM didn't supply one
        if not coverage_map:
            for tc in test_cases:
                if tc.linked_ac:
                    coverage_map.setdefault(tc.linked_ac, []).append(tc.id)

        return TestSuite(
            name=data.get("name", "Generated Suite"),
            test_cases=test_cases,
            coverage_map=coverage_map,
        )

    async def generate_regression_tests(
        self,
        modified_objects: list[dict[str, Any]],
        codebase_map: dict[str, Any],
    ) -> list[TestCase]:
        """Generate regression tests for a set of modified objects.

        Parameters
        ----------
        modified_objects:
            List of dicts describing each changed object
            (name, uuid, change_summary).
        codebase_map:
            Map of object names/UUIDs to their dependents so the LLM
            can reason about downstream impact.

        Returns
        -------
        list[TestCase]
        """
        user_prompt = f"""\
## Modified Objects
{json.dumps(modified_objects, indent=2)}

## Codebase Dependency Map
{json.dumps(codebase_map, indent=2)}

Generate regression test cases that verify the modified objects and
their dependents still function correctly after the change.
"""
        raw = await self._chat(_REGRESSION_SYSTEM, user_prompt)
        cleaned = self._clean_json(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse regression-test JSON from LLM response")
            return []

        if isinstance(data, dict) and "test_cases" in data:
            items = data["test_cases"]
        elif isinstance(data, list):
            items = data
        else:
            logger.error("Unexpected regression-test JSON shape: %s", type(data))
            return []

        return [self._parse_test_case(tc) for tc in items]
