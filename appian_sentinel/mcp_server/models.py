"""Typed request and response models for Appian Sentinel MCP tools."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.test_case import AppianAssertionType, TestSuite
from appian_sentinel.models.user_story import SolutionDesign, UserStory


class StrictModel(BaseModel):
    """Base model that rejects unknown MCP input fields."""

    model_config = ConfigDict(extra="forbid")


class ObjectSummary(StrictModel):
    uuid: str
    name: str
    type: ObjectType
    description: str = ""
    file_path: str = ""


class ListObjectsRequest(StrictModel):
    export_dir: str
    type: ObjectType | None = None
    page_size: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    cursor: str | None = None


class ListObjectsResponse(StrictModel):
    items: list[ObjectSummary] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    next_cursor: str | None = None


class ResolveObjectRequest(StrictModel):
    export_dir: str
    identity: str = Field(min_length=1, max_length=500)


class ResolveObjectResponse(StrictModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    object: ObjectSummary | None = None
    candidates: list[ObjectSummary] = Field(default_factory=list)


class GetCodebaseRequest(StrictModel):
    export_dir: str


class GetCodebaseResponse(StrictModel):
    app_name: str = ""
    app_uuid: str = ""
    app_prefix: str = ""
    appian_version: str = ""
    export_timestamp: str = ""
    by_type: dict[str, list[str]] = Field(default_factory=dict)
    uuid_to_name: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)
    reverse_dependencies: dict[str, list[str]] = Field(default_factory=dict)
    parent_by_uuid: dict[str, str] = Field(default_factory=dict)


class DependencyDirection(str, Enum):
    FORWARD = "forward"
    REVERSE = "reverse"
    BOTH = "both"


class DependencyGraphRequest(StrictModel):
    export_dir: str
    root_uuids: list[str] = Field(min_length=1, max_length=50)
    direction: DependencyDirection = DependencyDirection.FORWARD
    depth: int = Field(default=3, ge=0, le=10)
    max_nodes: int = Field(default=500, ge=1, le=1000)


class DependencyEdge(StrictModel):
    source: str
    target: str


class DependencyGraphResponse(StrictModel):
    nodes: list[ObjectSummary] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    missing_roots: list[str] = Field(default_factory=list)
    truncated: bool = False


class SailSourceRequest(StrictModel):
    source: str | None = Field(default=None, max_length=1_000_000)
    export_dir: str | None = None
    object_uuid: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> SailSourceRequest:
        has_source = self.source is not None
        has_object = self.export_dir is not None or self.object_uuid is not None
        if has_source == has_object:
            raise ValueError("Provide source or export_dir with object_uuid")
        if has_object and (self.export_dir is None or self.object_uuid is None):
            raise ValueError("export_dir and object_uuid must be provided together")
        return self


class InspectSailRequest(SailSourceRequest):
    include_ast: bool = False
    include_formatted_source: bool = True


class SailDiagnostic(StrictModel):
    source: Literal["analyzer"]
    code: str
    severity: Literal["error", "warning", "recommendation"]
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0
    start_offset: int = 0
    end_offset: int = 0
    message: str


class InspectSailResponse(StrictModel):
    ast: dict[str, Any] | None = None
    diagnostics: list[SailDiagnostic] = Field(default_factory=list)
    domain_variables: dict[str, list[str]] = Field(default_factory=dict)
    uuid_references: list[str] = Field(default_factory=list)
    formatted_source: str | None = None


class ValidateSailRequest(SailSourceRequest):
    declared_inputs: list[str] | None = None
    validate_references: bool = True


class ValidationResponse(StrictModel):
    is_valid: bool
    diagnostics: list[SailDiagnostic] = Field(default_factory=list)


class ValidateObjectRequest(StrictModel):
    export_dir: str
    object_uuid: str


class ValidateObjectResponse(StrictModel):
    object: ObjectSummary | None = None
    is_valid: bool
    diagnostics: list[SailDiagnostic] = Field(default_factory=list)


class ValidateWorkspaceRequest(StrictModel):
    export_dir: str
    page_size: int = Field(default=200, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class ValidateWorkspaceResponse(StrictModel):
    is_valid: bool
    checked: int
    total: int
    error_count: int
    warning_count: int
    results: list[ValidateObjectResponse] = Field(default_factory=list)


class NormalizeRequirementRequest(StrictModel):
    text: str = Field(min_length=1, max_length=1_000_000)


class NormalizeRequirementResponse(StrictModel):
    requirement: UserStory
    warnings: list[str] = Field(default_factory=list)


class ValidateTestCoverageRequest(StrictModel):
    requirement: UserStory
    suite: TestSuite


class CoverageResponse(StrictModel):
    is_complete: bool
    acceptance_criteria: list[str] = Field(default_factory=list)
    uncovered_criteria: list[str] = Field(default_factory=list)
    invalid_test_links: list[str] = Field(default_factory=list)
    duplicate_test_ids: list[str] = Field(default_factory=list)


class RunStaticTestsRequest(StrictModel):
    export_dir: str
    suite: TestSuite
    selected_test_ids: list[str] | None = None


class StaticTestResult(StrictModel):
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    execution_mode: Literal["static"] = "static"
    results: list[dict[str, Any]] = Field(default_factory=list)


class GetObjectTestsRequest(StrictModel):
    export_dir: str
    object_uuid: str = Field(min_length=1, max_length=500)


class EmbeddedTestCase(StrictModel):
    name: str = ""
    description: str = ""
    inputs: dict[str, str] = Field(default_factory=dict)
    assertion_type: AppianAssertionType = AppianAssertionType.COMPLETES_WITHOUT_ERROR
    expected: str = ""
    assertion_expression: str = ""
    xml: str = ""


class GetObjectTestsResponse(StrictModel):
    object_uuid: str
    tests: list[EmbeddedTestCase] = Field(default_factory=list)


class RunObjectStaticTestRequest(StrictModel):
    export_dir: str
    object_uuid: str = Field(min_length=1, max_length=500)
    inputs: dict[str, Any] = Field(default_factory=dict)


class RunObjectStaticTestResponse(StrictModel):
    object_uuid: str
    evaluated: Literal[False] = False
    is_valid: bool
    note: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[SailDiagnostic] = Field(default_factory=list)


class StructuredObjectTest(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    assertion_type: AppianAssertionType = AppianAssertionType.OUTPUT_EQUALS
    expected: Any = None
    assertion_expression: str = Field(default="", max_length=1_000_000)

    @model_validator(mode="after")
    def validate_assertion(self) -> StructuredObjectTest:
        if self.assertion_type is AppianAssertionType.EXPRESSION:
            if not self.assertion_expression.strip():
                raise ValueError("Expression assertions require assertion_expression.")
            if "test!output" not in self.assertion_expression.casefold():
                raise ValueError("Expression assertions must reference test!output.")
        elif self.assertion_expression.strip():
            raise ValueError("assertion_expression requires assertion_type='expression'.")
        if (
            self.assertion_type is AppianAssertionType.COMPLETES_WITHOUT_ERROR
            and self.expected is not None
        ):
            raise ValueError("No-error assertions cannot define expected.")
        return self


class BulkReplaceTestsRequest(StrictModel):
    export_dir: str
    object_uuids: list[str] = Field(min_length=1, max_length=500)
    tests: list[StructuredObjectTest] = Field(min_length=1, max_length=500)
    preview: bool = True


class GenerateFullZipRequest(StrictModel):
    export_dir: str
    output_path: str
    modifications: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class GenerateFullZipResponse(StrictModel):
    status: Literal["ok"] = "ok"
    output_path: str
    is_valid: bool
    issues: list[str] = Field(default_factory=list)


class GenerateSailRequest(StrictModel):
    export_dir: str
    object_uuid: str = Field(min_length=1, max_length=500)
    requirements: str = Field(min_length=1, max_length=1_000_000)


class GenerateSailResponse(StrictModel):
    object_uuid: str
    code: str
    confidence: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diagnostics: list[SailDiagnostic] = Field(default_factory=list)


class GenerateTestSuiteRequest(StrictModel):
    export_dir: str
    object_uuid: str = Field(min_length=1, max_length=500)
    requirement: UserStory
    solution_design: str = Field(min_length=1, max_length=1_000_000)


class GenerateTestSuiteResponse(StrictModel):
    object_uuid: str
    suite: TestSuite


class GenerateSolutionDesignRequest(StrictModel):
    export_dir: str
    requirement: UserStory


class GenerateSolutionDesignResponse(StrictModel):
    design: SolutionDesign


class HistoryChange(StrictModel):
    path: str
    kind: Literal["added", "modified", "deleted"]
    unified_diff: str = ""
    before_hash: str | None = None
    after_hash: str | None = None
    object_id: str | None = None


class HistoryRevision(StrictModel):
    hash: str
    parent: str | None = None
    is_baseline: bool
    actor: str
    requirement: str
    timestamp: datetime
    message: str
    tree_hash: str
    file_count: int


class WorkspaceStatusResponse(StrictModel):
    initialized: bool
    head: str | None = None
    baseline: str | None = None
    is_clean: bool
    staged: list[HistoryChange] = Field(default_factory=list)
    working_changes: list[HistoryChange] = Field(default_factory=list)


class HistoryLogResponse(StrictModel):
    revisions: list[HistoryRevision] = Field(default_factory=list)


class HistoryDiffResponse(StrictModel):
    from_revision: str
    to_revision: str | None = None
    changes: list[HistoryChange] = Field(default_factory=list)


class HistoryCommitResponse(StrictModel):
    revision: HistoryRevision
    staged_paths: list[str] = Field(default_factory=list)


class HistoryRestoreResponse(StrictModel):
    revision: HistoryRevision
    restored_from: str


class ApplySailEditResponse(StrictModel):
    status: Literal["updated", "rejected"]
    object_uuid: str
    file_path: str = ""
    diagnostics: list[SailDiagnostic] = Field(default_factory=list)


class BulkAddTestsResponse(StrictModel):
    status: Literal["preview", "updated"]
    object_uuids: list[str] = Field(default_factory=list)
    test_count: int
    file_paths: list[str] = Field(default_factory=list)


class TypedObjectRequest(StrictModel):
    export_dir: str = Field(description="Path to the extracted Appian export.")
    object_uuid: str = Field(
        min_length=1,
        max_length=500,
        description="UUID of the object to return.",
    )


class CreateTypedObjectRequest(StrictModel):
    export_dir: str = Field(description="Path to the extracted Appian export.")
    name: str = Field(
        min_length=1,
        max_length=500,
        description="Name for the new object.",
    )
    template_uuid: str = Field(
        default="",
        description=(
            "UUID of a same-type object to clone. Required only when the type "
            "has no native writer."
        ),
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific object fields. Omit fields that should use defaults.",
    )
    preview: bool = Field(
        default=False,
        description="When true, validate and describe the create without writing files.",
    )


class UpdateTypedObjectRequest(StrictModel):
    export_dir: str = Field(description="Path to the extracted Appian export.")
    object_uuid: str = Field(
        min_length=1,
        max_length=500,
        description="UUID of the object to update.",
    )
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Fields to replace. Use name to rename the object.",
    )
    preview: bool = Field(
        default=False,
        description="When true, validate and describe the update without writing files.",
    )


class DeleteTypedObjectRequest(StrictModel):
    export_dir: str = Field(description="Path to the extracted Appian export.")
    object_uuid: str = Field(
        min_length=1,
        max_length=500,
        description="UUID of the object to delete.",
    )
    force: bool = Field(
        default=False,
        description="When true, allow deletion despite reverse dependencies or children.",
    )
    preview: bool = Field(
        default=True,
        description="When true, report the delete without changing files.",
    )


class MutationResponse(StrictModel):
    status: str
    uuid: str = ""
    name: str = ""
    file_path: str = ""
    reason: str = ""
    template_uuid: str = ""
    dependents: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    forced: bool = False
    object: dict[str, Any] | None = None
