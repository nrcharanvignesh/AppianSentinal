"""Test-case and test-suite domain models used by the tester subsystem."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

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
    priority: TestCasePriority = TestCasePriority.MEDIUM


class TestSuite(BaseModel):
    """A collection of test cases with coverage mapping."""

    name: str
    test_cases: list[TestCase] = Field(default_factory=list)
    coverage_map: dict[str, list[str]] = Field(default_factory=dict)
    """Maps acceptance-criteria ID -> list of test-case IDs."""


# ---------------------------------------------------------------------------
# Execution-result models
# ---------------------------------------------------------------------------

class TestCaseResult(BaseModel):
    """Outcome of running a single *TestCase*."""

    test_id: str
    status: TestCaseStatus
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class TestRunResult(BaseModel):
    """Aggregated outcome of running a *TestSuite*."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    results: list[TestCaseResult] = Field(default_factory=list)
