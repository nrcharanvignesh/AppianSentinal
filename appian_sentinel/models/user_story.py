from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# User Story models
# ---------------------------------------------------------------------------


class AcceptanceCriterion(BaseModel):
    """Single acceptance criterion in Given/When/Then format."""

    id: str = Field(..., description="Identifier, e.g. 'AC-1'")
    description: str = Field(..., description="Plain-language description of the criterion")
    given: str = Field(default="", description="Given precondition")
    when: str = Field(default="", description="When action/event")
    then: str = Field(default="", description="Then expected outcome")
    source_id: str = ""
    source_kind: Literal["chat", "pdf", "ado"] = "chat"


class UserStory(BaseModel):
    """Structured representation of a user story extracted from a PDF or text."""

    title: str = Field(..., description="Short title for the story")
    description: str = Field(default="", description="Full narrative description")
    as_a: str = Field(default="", description="The role (As a ...)")
    i_want: str = Field(default="", description="The desired action (I want ...)")
    so_that: str = Field(default="", description="The benefit (So that ...)")
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    raw_text: str = Field(default="", description="Original unprocessed text from the source document")
    source_id: str = ""
    source_kind: Literal["chat", "pdf", "ado"] = "chat"


# ---------------------------------------------------------------------------
# Requirement Analysis models
# ---------------------------------------------------------------------------


class NewObject(BaseModel):
    """An Appian object that needs to be created."""

    name: str
    object_type: str = Field(..., description="E.g. 'Expression Rule', 'Interface', 'Record Type', 'CDT'")
    purpose: str


class ModifiedObject(BaseModel):
    """An existing Appian object that needs modification."""

    uuid: str = Field(default="", description="Appian object UUID if known")
    name: str
    changes: str = Field(..., description="Description of what changes are required")


class RequirementAnalysis(BaseModel):
    """Result of analysing a user story against the existing codebase."""

    restated_story: str = Field(..., description="The story restated in Appian-specific terms")
    new_objects: list[NewObject] = Field(default_factory=list)
    modified_objects: list[ModifiedObject] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Solution Design models
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    CREATE = "create"
    MODIFY = "modify"


class ObjectChange(BaseModel):
    """A single object-level change in the proposed solution."""

    object_name: str
    object_type: str
    action: ActionType
    sail_approach: str = Field(..., description="SAIL implementation approach / pseudo-code summary")
    dependencies: list[str] = Field(default_factory=list, description="Names of objects this change depends on")


class SolutionDesign(BaseModel):
    """High-level design for implementing a user story."""

    approach_summary: str
    object_changes: list[ObjectChange] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Clarifying Question models
# ---------------------------------------------------------------------------


class QuestionPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClarifyingQuestion(BaseModel):
    """A question the agent needs answered before it can proceed confidently."""

    id: str = Field(..., description="Identifier, e.g. 'Q-1'")
    question: str
    context: str = Field(default="", description="Why this question matters")
    options: list[str] = Field(default_factory=list, description="Possible answers, if known")
    priority: QuestionPriority = QuestionPriority.MEDIUM


# ---------------------------------------------------------------------------
# Impact Analysis models
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BreakingChange(BaseModel):
    """A change that may break downstream consumers."""

    object_name: str
    description: str
    affected_callers: list[str] = Field(default_factory=list)
    severity: RiskLevel = RiskLevel.MEDIUM


class CircularReference(BaseModel):
    """A detected circular dependency chain."""

    chain: list[str] = Field(..., description="Ordered list of object names forming the cycle")


class ImpactReport(BaseModel):
    """Full impact analysis of a set of proposed changes."""

    changed_objects: list[str] = Field(default_factory=list)
    forward_deps: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of changed object -> list of objects it depends on",
    )
    reverse_deps: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of changed object -> list of objects that depend on it",
    )
    breaking_changes: list[BreakingChange] = Field(default_factory=list)
    circular_refs: list[CircularReference] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CompatibilityIssue(BaseModel):
    """A compatibility problem detected between a new/modified object and its callers."""

    object_uuid: str = Field(default="", description="UUID of the affected object")
    issue_type: str = Field(..., description="E.g. 'signature_mismatch', 'missing_input', 'type_change'")
    description: str
    severity: IssueSeverity = IssueSeverity.WARNING
