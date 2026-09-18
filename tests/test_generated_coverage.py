from __future__ import annotations

import json
from typing import Any

from appian_sentinel.models.test_case import (
    COVERAGE_NEGATIVE,
    COVERAGE_POSITIVE,
)
from appian_sentinel.models.test_case import (
    TestCaseType as CaseType,
)
from appian_sentinel.tester.test_generator import TestGenerator as Generator


class FakeLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[list[dict[str, str]]] = []

    async def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        del kwargs
        self.calls.append(messages)
        return json.dumps(self._payload)


def _case(test_id: str, test_type: str, linked_ac: str) -> dict[str, Any]:
    return {
        "id": test_id,
        "name": f"{test_type} for {linked_ac}",
        "type": test_type,
        "linked_ac": linked_ac,
        "preconditions": ["A user is signed in"],
        "steps": [
            {
                "action": "Submit the request",
                "input_data": {"value": "sample"},
                "expected_output": "The expected result is shown",
            }
        ],
        "expected_result": "The scenario has the expected outcome",
        "priority": "high",
    }


async def test_llm_generated_suite_produces_complete_coverage_matrix() -> None:
    payload = {
        "name": "Generated request suite",
        "test_cases": [
            _case("TC-001", "functional", "AC-1"),
            _case("TC-002", "negative", "AC-1"),
            _case("TC-003", "functional", "AC-2"),
            _case("TC-004", "edge", "AC-2"),
            _case("TC-005", "regression", "AC-1"),
            _case("TC-006", "performance", "AC-1"),
            _case("TC-007", "accessibility", "AC-2"),
        ],
        "coverage_map": {
            "AC-1": ["TC-001", "TC-002", "TC-005", "TC-006"],
            "AC-2": ["TC-003", "TC-004", "TC-007"],
        },
    }
    fake = FakeLLM(payload)
    suite = await Generator(fake).generate_test_suite(
        "AC-1 saves a request. AC-2 makes the form accessible.",
        "Update the request interface.",
    )

    report = suite.validate_coverage(["AC-1", "AC-2"])

    assert fake.calls
    assert report.is_complete is True
    assert report.covered == ["AC-1", "AC-2"]
    assert report.gaps == []
    assert {case.type for case in suite.test_cases} == set(CaseType)
    assert "accessibility" in fake.calls[0][0]["content"].lower()


async def test_incomplete_llm_generated_suite_is_reported_incomplete() -> None:
    payload = {
        "name": "Incomplete generated suite",
        "test_cases": [
            _case("TC-001", "functional", "AC-1"),
            _case("TC-002", "negative", "AC-1"),
            _case("TC-003", "performance", "AC-2"),
        ],
        "coverage_map": {
            "AC-1": ["TC-001", "TC-002"],
            "AC-2": ["TC-003"],
        },
    }
    suite = await Generator(FakeLLM(payload)).generate_test_suite(
        "AC-1 saves a request. AC-2 rejects invalid access.",
        "Update the request interface.",
    )

    report = suite.validate_coverage(["AC-1", "AC-2"])

    assert report.is_complete is False
    assert report.covered == ["AC-1"]
    assert [gap.ac_id for gap in report.gaps] == ["AC-2"]
    assert report.gaps[0].missing == [COVERAGE_POSITIVE, COVERAGE_NEGATIVE]
    assert report.gaps[0].linked_test_ids == ["TC-003"]
