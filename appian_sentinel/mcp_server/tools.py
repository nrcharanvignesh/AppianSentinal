"""Tool logic for the Appian Sentinel MCP server.

Plain (async where needed) functions wrapping the existing engine, so they can
be unit-tested without the MCP transport. ``server.py`` registers thin
decorated wrappers around these.
"""

from __future__ import annotations

import base64
import dataclasses
import logging
import re
from pathlib import Path
from typing import Any

from lxml import etree

from appian_sentinel.analyzer.story_analyzer import StoryAnalyzer
from appian_sentinel.config import settings
from appian_sentinel.generator.object_writer import write_object
from appian_sentinel.generator.sail_generator import SailGenerator
from appian_sentinel.integrations import ado_client
from appian_sentinel.mcp_server import cache
from appian_sentinel.mcp_server.models import (
    ApplySailEditResponse,
    BulkAddTestsResponse,
    CoverageResponse,
    DependencyDirection,
    DependencyEdge,
    DependencyGraphRequest,
    DependencyGraphResponse,
    GenerateFullZipRequest,
    GenerateFullZipResponse,
    GenerateSailRequest,
    GenerateSailResponse,
    GenerateSolutionDesignRequest,
    GenerateSolutionDesignResponse,
    GenerateTestSuiteRequest,
    GenerateTestSuiteResponse,
    HistoryChange,
    HistoryCommitResponse,
    HistoryDiffResponse,
    HistoryLogResponse,
    HistoryRestoreResponse,
    HistoryRevision,
    InspectSailRequest,
    InspectSailResponse,
    ListObjectsRequest,
    ListObjectsResponse,
    NormalizeRequirementRequest,
    NormalizeRequirementResponse,
    ObjectSummary,
    ResolveObjectRequest,
    ResolveObjectResponse,
    RunStaticTestsRequest,
    SailDiagnostic,
    StaticTestResult,
    ValidateObjectRequest,
    ValidateObjectResponse,
    ValidateSailRequest,
    ValidateTestCoverageRequest,
    ValidateWorkspaceRequest,
    ValidateWorkspaceResponse,
    ValidationResponse,
    WorkspaceStatusResponse,
)
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.codebase import CodebaseMap
from appian_sentinel.models.test_case import TestSuite
from appian_sentinel.models.user_story import AcceptanceCriterion, UserStory
from appian_sentinel.packager import patch_builder
from appian_sentinel.packager.zip_builder import build_appian_zip, validate_zip_structure
from appian_sentinel.parser import codebase_map as codebase_map_mod
from appian_sentinel.parser.sail_ast import (
    extract_domain_vars,
    extract_uuid_refs,
    pretty_print,
)
from appian_sentinel.parser.sail_diagnostics import analyze_sail
from appian_sentinel.security import mask_secrets
from appian_sentinel.services.workspace import WorkspaceHistoryService
from appian_sentinel.tester.test_generator import TestGenerator
from appian_sentinel.tester.test_runner import StaticTestRunner

logger = logging.getLogger(__name__)

_SECRET_KEY = re.compile(
    r"(authorization|credential|password|secret|token|api[_-]?key|(?:^|_)pat(?:$|_))",
    re.IGNORECASE,
)


def _sandbox_path(value: str | Path, *, must_exist: bool = True) -> Path:
    """Resolve a path below the configured workspace root."""
    root = settings.sentinel_workspace.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Path must resolve below the configured workspace root")
    if must_exist and not candidate.exists():
        raise ValueError("Workspace path does not exist")
    return candidate


def _display_path(path: str | Path) -> str:
    """Return a workspace-relative path without leaking an absolute path."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(settings.sentinel_workspace.resolve()).as_posix()
    except ValueError:
        return "[REDACTED_PATH]"


def _sanitize(value: Any, key: str = "") -> Any:
    """Recursively redact secrets and absolute filesystem paths."""
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item) for item in value)
    if isinstance(value, str) and (Path(value).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", value)):
        return _display_path(value)
    return value


def _object_summary(obj: Any) -> ObjectSummary:
    return ObjectSummary(
        uuid=obj.uuid,
        name=obj.name,
        type=obj.object_type,
        description=obj.description,
        file_path=_display_path(obj.file_path) if obj.file_path else "",
    )


def _parse_cursor(cursor: str | None, offset: int) -> int:
    if cursor is None:
        return offset
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        parsed = int(decoded)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
    if parsed < 0:
        raise ValueError("Invalid pagination cursor")
    return parsed


def _make_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _source_for_request(
    request: InspectSailRequest | ValidateSailRequest,
) -> tuple[str, set[str], str | None]:
    if request.source is not None:
        return request.source, set(), None
    export_dir = _sandbox_path(request.export_dir or "")
    cb = cache.get_codebase(export_dir)
    obj = cb.get_object(request.object_uuid or "")
    if obj is None:
        raise ValueError("Object not found")
    source = getattr(obj, "definition", "")
    if not isinstance(source, str) or not source:
        raise ValueError("Object does not contain SAIL source")
    return source, set(cb.objects), cb.appian_version or None


def _analysis_diagnostics(diagnostics: list[Any]) -> list[SailDiagnostic]:
    return [
        SailDiagnostic(
            source="analyzer",
            code=item.code,
            severity=item.severity.value,
            line=item.line,
            column=item.column,
            end_line=item.end_line,
            end_column=item.end_column,
            start_offset=item.range.start.offset,
            end_offset=item.range.end.offset,
            message=item.message,
        )
        for item in diagnostics
    ]


def _validate_sail_source(
    source: str,
    *,
    known_uuids: set[str] | None = None,
    target_version: str | None = None,
    declared_inputs: list[str] | None = None,
) -> ValidationResponse:
    """Run the shared SAIL validation pipeline for tool and generated source."""
    analysis = analyze_sail(
        source,
        target_version=target_version,
        known_uuids=known_uuids,
        declared_inputs=declared_inputs,
    )
    diagnostics = _analysis_diagnostics(analysis.diagnostics)
    return ValidationResponse(
        is_valid=analysis.is_valid,
        diagnostics=diagnostics,
    )


def _require_llm_configured() -> None:
    """Reject generation before any network call when no LLM is configured."""
    if not settings.litellm_api_key.strip():
        raise RuntimeError(
            "LLM generation is not configured. Set LITELLM_API_KEY and restart the MCP server."
        )


def _generation_codebase_context(export_dir: Path) -> tuple[CodebaseMap, str]:
    """Load one workspace and return its codebase plus a bounded summary."""
    cb = cache.get_codebase(export_dir)
    return cb, cb.summarise().model_dump_json()


def _history_change(item: Any) -> HistoryChange:
    return HistoryChange(
        path=item.path,
        kind=item.kind.value,
        unified_diff=_redact_text(item.unified_diff),
        before_hash=item.before_hash,
        after_hash=item.after_hash,
        object_id=item.object_id,
    )


def _history_revision(item: Any) -> HistoryRevision:
    return HistoryRevision(
        hash=item.hash,
        parent=item.parent,
        is_baseline=item.is_baseline,
        actor=item.actor,
        requirement=item.requirement,
        timestamp=item.timestamp,
        message=item.message,
        tree_hash=item.tree_hash,
        file_count=len(item.files),
    )


def _redact_text(value: str) -> str:
    """Redact common secret assignments in diff text."""
    patterns = (
        r'(?i)(["\']?(?:pat|api[_-]?key|password|secret|token)["\']?\s*[:=]\s*)["\']?[^"\'\s<]+',
        r"(?i)(<(?:pat|api[_-]?key|password|secret|token)>).*?(</[^>]+>)",
        r"(?i)(authorization:\s*(?:bearer|basic)\s+)\S+",
    )
    redacted = value
    for pattern in patterns:
        redacted = re.sub(pattern, r"\1[REDACTED]\2" if pattern.startswith("(?i)(<") else r"\1[REDACTED]", redacted)
    return redacted


def analyze_appian_zip(zip_path: str) -> dict[str, Any]:
    """Extract and analyze an Appian export ZIP; catalog objects by type."""
    export_dir, cb = cache.analyze_zip(_sandbox_path(zip_path))
    summary = cb.summarise()
    return {
        "export_dir": _display_path(export_dir),
        "app_name": cb.app_name,
        "appian_version": cb.appian_version,
        "total_objects": summary.total_objects,
        "counts_by_type": summary.counts_by_type,
        "plugin_count": summary.plugin_count,
        "by_type": {t: len(uuids) for t, uuids in cb.by_type.items()},
    }


def search_objects(
    export_dir: str,
    query: str,
    types: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search objects by name/description (case-insensitive substring)."""
    cb = cache.get_codebase(_sandbox_path(export_dir))
    object_types: list[ObjectType] | None = None
    if types:
        object_types = []
        for t in types:
            try:
                object_types.append(ObjectType(t))
            except ValueError as exc:
                raise ValueError(f"Unknown object type filter: {t}") from exc
    results = codebase_map_mod.search_objects(cb, query, object_types, limit)
    return {
        "count": len(results),
        "results": [
            {
                "uuid": o.uuid,
                "name": o.name,
                "type": o.object_type.value,
                "description": o.description,
                "file_path": _display_path(o.file_path) if o.file_path else "",
            }
            for o in results
        ],
    }


def get_object(export_dir: str, uuid: str) -> dict[str, Any]:
    """Return the full parsed detail for one object by UUID."""
    cb = cache.get_codebase(_sandbox_path(export_dir))
    obj = cb.get_object(uuid)
    if obj is None:
        return {"error": f"Object {uuid} not found."}
    data = obj.model_dump()
    data["direct_dependencies"] = sorted(cb.get_direct_dependencies(uuid))
    data["direct_dependents"] = sorted(cb.get_direct_dependents(uuid))
    return _sanitize(data)


async def read_ado_work_item(
    organization: str,
    project: str,
    work_item_id: int | str,
    pat: str,
) -> dict[str, Any]:
    """Fetch an ADO work item's title, description, and acceptance criteria."""
    return _sanitize(await ado_client.get_work_item(organization, project, work_item_id, pat))


def apply_object_change(export_dir: str, obj: dict[str, Any]) -> dict[str, Any]:
    """Write a created/modified object into the export directory.

    *obj* keys: ``type``, ``name``, ``action`` (create|modify), ``sail_code`` /
    ``definition``, and type-specific fields (see ``object_writer``).
    """
    out = write_object(_sandbox_path(export_dir), obj)
    if out is None:
        return {"status": "error", "message": f"Could not write object {obj.get('name')!r}"}
    return {
        "status": "ok",
        "file_path": _display_path(out),
        "uuid": obj.get("uuid", ""),
        "name": obj.get("name", ""),
    }


def generate_patch_zip(
    export_dir: str,
    object_uuids: list[str],
    output_path: str,
) -> dict[str, Any]:
    """Build a patch ZIP containing only the given objects."""
    export_dir_p = _sandbox_path(export_dir)
    cb = cache.get_codebase(export_dir_p)
    result = patch_builder.build_patch_zip(
        export_dir_p,
        object_uuids,
        _sandbox_path(output_path, must_exist=False),
        codebase=cb,
    )
    return _sanitize(result)


def list_objects(request: ListObjectsRequest) -> ListObjectsResponse:
    """List object summaries with deterministic pagination."""
    cb = cache.get_codebase(_sandbox_path(request.export_dir))
    objects = list(cb.objects.values())
    if request.type is not None:
        objects = [obj for obj in objects if obj.object_type == request.type]
    objects.sort(key=lambda obj: (obj.object_type.value, obj.name.casefold(), obj.uuid))
    offset = _parse_cursor(request.cursor, request.offset)
    page = objects[offset : offset + request.page_size]
    next_offset = offset + len(page)
    return ListObjectsResponse(
        items=[_object_summary(obj) for obj in page],
        total=len(objects),
        offset=offset,
        next_cursor=_make_cursor(next_offset) if next_offset < len(objects) else None,
    )


def resolve_object(request: ResolveObjectRequest) -> ResolveObjectResponse:
    """Resolve a UUID or name without silently choosing duplicate names."""
    cb = cache.get_codebase(_sandbox_path(request.export_dir))
    by_uuid = cb.get_object(request.identity)
    if by_uuid is not None:
        return ResolveObjectResponse(status="resolved", object=_object_summary(by_uuid))
    identity = request.identity.casefold()
    matches = [obj for obj in cb.objects.values() if obj.name.casefold() == identity]
    matches.sort(key=lambda obj: (obj.object_type.value, obj.uuid))
    if len(matches) == 1:
        return ResolveObjectResponse(status="resolved", object=_object_summary(matches[0]))
    if matches:
        return ResolveObjectResponse(
            status="ambiguous",
            candidates=[_object_summary(obj) for obj in matches],
        )
    return ResolveObjectResponse(status="not_found")


def get_dependency_graph(request: DependencyGraphRequest) -> DependencyGraphResponse:
    """Build a bounded forward, reverse, or bidirectional dependency graph."""
    cb = cache.get_codebase(_sandbox_path(request.export_dir))
    missing_roots = sorted(uuid for uuid in request.root_uuids if uuid not in cb.objects)
    frontier = [(uuid, 0) for uuid in request.root_uuids if uuid in cb.objects]
    visited: set[str] = set()
    edges: set[tuple[str, str]] = set()
    truncated = False
    while frontier:
        uuid, depth = frontier.pop(0)
        if uuid in visited:
            continue
        if len(visited) >= request.max_nodes:
            truncated = True
            break
        visited.add(uuid)
        if depth >= request.depth:
            continue
        neighbours: list[tuple[str, str]] = []
        if request.direction in (DependencyDirection.FORWARD, DependencyDirection.BOTH):
            neighbours.extend((uuid, target) for target in cb.get_direct_dependencies(uuid))
        if request.direction in (DependencyDirection.REVERSE, DependencyDirection.BOTH):
            neighbours.extend((source, uuid) for source in cb.get_direct_dependents(uuid))
        for source, target in sorted(neighbours):
            edges.add((source, target))
            next_uuid = target if source == uuid else source
            if next_uuid in cb.objects and next_uuid not in visited:
                frontier.append((next_uuid, depth + 1))
    return DependencyGraphResponse(
        nodes=[_object_summary(cb.objects[uuid]) for uuid in sorted(visited)],
        edges=[DependencyEdge(source=source, target=target) for source, target in sorted(edges)],
        missing_roots=missing_roots,
        truncated=truncated,
    )


def inspect_sail(request: InspectSailRequest) -> InspectSailResponse:
    """Inspect SAIL source with the unified diagnostic pipeline."""
    source, known_uuids, target_version = _source_for_request(request)
    analysis = analyze_sail(
        source,
        target_version=target_version,
        known_uuids=known_uuids or None,
    )
    variables = {
        domain: sorted(names)
        for domain, names in sorted(extract_domain_vars(analysis.ast).items())
    }
    return InspectSailResponse(
        ast=dataclasses.asdict(analysis.ast) if request.include_ast else None,
        diagnostics=_analysis_diagnostics(analysis.diagnostics),
        domain_variables=variables,
        uuid_references=sorted(extract_uuid_refs(analysis.ast)),
        formatted_source=pretty_print(analysis.ast) if request.include_formatted_source else None,
    )


def validate_sail(request: ValidateSailRequest) -> ValidationResponse:
    """Run the unified SAIL diagnostic pipeline."""
    source, known_uuids, target_version = _source_for_request(request)
    return _validate_sail_source(
        source,
        target_version=target_version,
        known_uuids=known_uuids if request.validate_references and known_uuids else None,
        declared_inputs=request.declared_inputs,
    )


def validate_object(request: ValidateObjectRequest) -> ValidateObjectResponse:
    """Validate one parsed object without changing it."""
    export_dir = _sandbox_path(request.export_dir)
    cb = cache.get_codebase(export_dir)
    obj = cb.get_object(request.object_uuid)
    if obj is None:
        diagnostic = SailDiagnostic(
            source="analyzer",
            code="OBJECT_NOT_FOUND",
            severity="error",
            message="Object not found",
        )
        return ValidateObjectResponse(is_valid=False, diagnostics=[diagnostic])
    diagnostics: list[SailDiagnostic] = []
    source = getattr(obj, "definition", "")
    if isinstance(source, str) and source:
        declared_inputs = [item.name for item in getattr(obj, "rule_inputs", [])]
        result = validate_sail(
            ValidateSailRequest(
                export_dir=request.export_dir,
                object_uuid=request.object_uuid,
                declared_inputs=declared_inputs,
            )
        )
        diagnostics.extend(result.diagnostics)
    return ValidateObjectResponse(
        object=_object_summary(obj),
        is_valid=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
    )


def validate_workspace(request: ValidateWorkspaceRequest) -> ValidateWorkspaceResponse:
    """Validate a bounded page of objects in one parsed workspace."""
    cb = cache.get_codebase(_sandbox_path(request.export_dir))
    uuids = sorted(cb.objects)
    selected = uuids[request.offset : request.offset + request.page_size]
    results = [
        validate_object(
            ValidateObjectRequest(export_dir=request.export_dir, object_uuid=uuid)
        )
        for uuid in selected
    ]
    error_count = sum(
        item.severity == "error"
        for result in results
        for item in result.diagnostics
    )
    warning_count = sum(
        item.severity == "warning"
        for result in results
        for item in result.diagnostics
    )
    return ValidateWorkspaceResponse(
        is_valid=error_count == 0,
        checked=len(results),
        total=len(uuids),
        error_count=error_count,
        warning_count=warning_count,
        results=results,
    )


def normalize_requirement(request: NormalizeRequirementRequest) -> NormalizeRequirementResponse:
    """Normalize plain text into the existing typed user-story model."""
    text = request.text.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0][:200]
    role_match = re.search(
        r"\bAs an?\s+(.+?),\s*I want\s+(.+?)(?:,\s*so that\s+(.+?))?(?:[.\n]|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    criteria: list[AcceptanceCriterion] = []
    blocks = re.split(r"(?im)^(?=AC[- ]?\d+\s*[:.-])", text)
    for block in blocks:
        match = re.match(r"(?is)AC[- ]?(\d+)\s*[:.-]\s*(.*)", block.strip())
        if not match:
            continue
        body = match.group(2).strip()
        given = re.search(r"(?im)^Given\s+(.+)$", body)
        when = re.search(r"(?im)^When\s+(.+)$", body)
        then = re.search(r"(?im)^Then\s+(.+)$", body)
        criteria.append(
            AcceptanceCriterion(
                id=f"AC-{match.group(1)}",
                description=body.splitlines()[0][:500],
                given=given.group(1).strip() if given else "",
                when=when.group(1).strip() if when else "",
                then=then.group(1).strip() if then else "",
            )
        )
    warnings = [] if role_match else ["No complete As a/I want/so that statement was found"]
    return NormalizeRequirementResponse(
        requirement=UserStory(
            title=title,
            description=text,
            as_a=role_match.group(1).strip() if role_match else "",
            i_want=role_match.group(2).strip() if role_match else "",
            so_that=role_match.group(3).strip() if role_match and role_match.group(3) else "",
            acceptance_criteria=criteria,
            raw_text=text,
        ),
        warnings=warnings,
    )


async def generate_sail(request: GenerateSailRequest) -> GenerateSailResponse:
    """Generate validated SAIL for one existing interface or expression rule."""
    _require_llm_configured()
    export_dir = _sandbox_path(request.export_dir)
    cb, codebase_context = _generation_codebase_context(export_dir)
    obj = cb.get_object(request.object_uuid)
    if obj is None:
        raise ValueError("Object not found")
    definition = getattr(obj, "definition", "")
    if not isinstance(definition, str):
        raise ValueError("Object does not contain SAIL source")

    generator = SailGenerator()
    try:
        if obj.object_type is ObjectType.INTERFACE:
            generated = await generator.modify_interface(
                definition,
                request.requirements,
                codebase_context,
            )
        elif obj.object_type is ObjectType.EXPRESSION_RULE:
            generated = await generator.modify_rule(
                definition,
                request.requirements,
                codebase_context,
            )
        else:
            raise ValueError(
                "SAIL generation supports existing interfaces and expression rules only"
            )
    except ValueError:
        raise
    except Exception:
        raise RuntimeError(
            "LLM generation failed. Verify the configured endpoint, credentials, and model."
        ) from None

    if mask_secrets(generated.code) != generated.code:
        raise RuntimeError(
            "Generated SAIL contained secret material and was not returned."
        )
    declared_inputs = [item.name for item in getattr(obj, "rule_inputs", [])]
    validation = _validate_sail_source(
        generated.code,
        known_uuids=set(cb.objects),
        target_version=cb.appian_version or None,
        declared_inputs=declared_inputs,
    )
    has_unknown_callable = any(
        diagnostic.code == "SAIL021" for diagnostic in validation.diagnostics
    )
    if not generated.code.strip() or not validation.is_valid or has_unknown_callable:
        raise RuntimeError(
            "Generated SAIL failed validation and was not returned. "
            "Review the requirement or LLM configuration and retry."
        )
    return GenerateSailResponse(
        object_uuid=obj.uuid,
        code=generated.code,
        confidence=generated.confidence,
        notes=[mask_secrets(note) for note in generated.notes],
        warnings=[mask_secrets(warning) for warning in generated.warnings],
        diagnostics=validation.diagnostics,
    )


async def generate_test_suite(
    request: GenerateTestSuiteRequest,
) -> GenerateTestSuiteResponse:
    """Generate tests for one existing object and preserve its real UUID."""
    _require_llm_configured()
    export_dir = _sandbox_path(request.export_dir)
    cb, codebase_context = _generation_codebase_context(export_dir)
    obj = cb.get_object(request.object_uuid)
    if obj is None:
        raise ValueError("Object not found")
    object_context = (
        f"{codebase_context}\nTarget object:\n"
        f"{obj.model_dump_json(exclude={'security_roles', 'unknown_xml'})}"
    )
    try:
        suite = await TestGenerator().generate_test_suite(
            request.requirement.model_dump_json(),
            request.solution_design,
            object_context,
        )
    except Exception:
        raise RuntimeError(
            "LLM generation failed. Verify the configured endpoint, credentials, and model."
        ) from None
    if not suite.test_cases:
        raise RuntimeError(
            "The LLM returned no usable test cases; no generated suite was returned."
        )
    suite_json = suite.model_dump_json()
    if mask_secrets(suite_json) != suite_json:
        raise RuntimeError(
            "The generated test suite contained secret material and was not returned."
        )
    return GenerateTestSuiteResponse(object_uuid=obj.uuid, suite=suite)


async def generate_solution_design(
    request: GenerateSolutionDesignRequest,
) -> GenerateSolutionDesignResponse:
    """Analyze one requirement and generate a minimal Appian solution design."""
    _require_llm_configured()
    export_dir = _sandbox_path(request.export_dir)
    _, codebase_context = _generation_codebase_context(export_dir)
    analyzer = StoryAnalyzer()
    try:
        analysis = await analyzer.analyze_requirements(
            request.requirement,
            codebase_context,
        )
        design = await analyzer.design_solution(
            request.requirement,
            analysis,
            codebase_context,
        )
    except Exception:
        raise RuntimeError(
            "LLM generation failed. Verify the configured endpoint, credentials, and model."
        ) from None
    design_json = design.model_dump_json()
    if mask_secrets(design_json) != design_json:
        raise RuntimeError(
            "The generated solution design contained secret material and was not returned."
        )
    return GenerateSolutionDesignResponse(design=design)


def validate_test_coverage(request: ValidateTestCoverageRequest) -> CoverageResponse:
    """Check criterion links and duplicate test IDs deterministically."""
    criterion_ids = [criterion.id for criterion in request.requirement.acceptance_criteria]
    known_criteria = set(criterion_ids)
    seen_ids: set[str] = set()
    duplicates: set[str] = set()
    covered: set[str] = set()
    invalid_links: list[str] = []
    for test in request.suite.test_cases:
        if test.id in seen_ids:
            duplicates.add(test.id)
        seen_ids.add(test.id)
        if test.linked_ac in known_criteria:
            covered.add(test.linked_ac)
        elif test.linked_ac:
            invalid_links.append(f"{test.id}:{test.linked_ac}")
    uncovered = sorted(known_criteria - covered)
    return CoverageResponse(
        is_complete=not uncovered and not invalid_links and not duplicates,
        acceptance_criteria=criterion_ids,
        uncovered_criteria=uncovered,
        invalid_test_links=sorted(invalid_links),
        duplicate_test_ids=sorted(duplicates),
    )


async def run_static_tests(request: RunStaticTestsRequest) -> StaticTestResult:
    """Execute the existing static test runner against snapshot source."""
    cb = cache.get_codebase(_sandbox_path(request.export_dir))
    code_map: dict[str, str] = {}
    inputs_map: dict[str, list[str]] = {}
    for obj in cb.objects.values():
        source = getattr(obj, "definition", "")
        if isinstance(source, str) and source:
            code_map[obj.name] = source
            inputs_map[obj.name] = [item.name for item in getattr(obj, "rule_inputs", [])]
    suite: TestSuite = request.suite
    if request.selected_test_ids is not None:
        selected = set(request.selected_test_ids)
        suite = suite.model_copy(
            update={"test_cases": [test for test in suite.test_cases if test.id in selected]}
        )
    result = await StaticTestRunner(
        sail_code_map=code_map,
        known_uuids=set(cb.objects),
        declared_inputs_map=inputs_map,
    ).run_suite(suite)
    return StaticTestResult(
        passed=result.passed,
        failed=result.failed,
        errors=result.errors,
        skipped=result.skipped,
        results=[item.model_dump(mode="json") for item in result.results],
    )


def workspace_status(export_dir: str) -> WorkspaceStatusResponse:
    """Return history and working-tree status for one export."""
    service = WorkspaceHistoryService(_sandbox_path(export_dir))
    staged = [
        HistoryChange(
            path=item.path,
            kind=item.kind.value,
            after_hash=item.blob_hash,
        )
        for item in service.staged_changes()
    ]
    working = [_history_change(item) for item in service.working_changes()]
    head = service.head()
    return WorkspaceStatusResponse(
        initialized=head is not None,
        head=head,
        baseline=service.baseline(),
        is_clean=not staged and not working,
        staged=staged,
        working_changes=working,
    )


def history_log(export_dir: str, limit: int = 50) -> HistoryLogResponse:
    """Return bounded newest-first workspace revision history."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    service = WorkspaceHistoryService(_sandbox_path(export_dir))
    return HistoryLogResponse(
        revisions=[_history_revision(item) for item in service.log(limit)],
    )


def history_diff(
    export_dir: str,
    from_revision: str,
    to_revision: str | None = None,
) -> HistoryDiffResponse:
    """Return a redacted revision-to-revision diff."""
    service = WorkspaceHistoryService(_sandbox_path(export_dir))
    resolved_to = to_revision or service.head()
    return HistoryDiffResponse(
        from_revision=from_revision,
        to_revision=resolved_to,
        changes=[
            _history_change(item)
            for item in service.diff(from_revision, to_revision)
        ],
    )


def history_commit(
    export_dir: str,
    actor: str,
    requirement: str,
    message: str,
    paths: list[str] | None = None,
    expected_revision: str | None = None,
) -> HistoryCommitResponse:
    """Create a baseline or stage and commit selected workspace changes."""
    service = WorkspaceHistoryService(_sandbox_path(export_dir))
    if service.head() is None:
        revision = service.create_baseline(
            actor=actor,
            requirement=requirement,
            message=message or "baseline",
            expected_revision=expected_revision,
        )
        return HistoryCommitResponse(revision=_history_revision(revision))
    selected_paths = paths
    if selected_paths is None:
        selected_paths = [item.path for item in service.working_changes()]
    staged_paths = sorted(set(selected_paths))
    for relative_path in staged_paths:
        service.stage(relative_path)
    revision = service.commit(
        actor=actor,
        requirement=requirement,
        message=message,
        expected_revision=expected_revision,
    )
    return HistoryCommitResponse(
        revision=_history_revision(revision),
        staged_paths=staged_paths,
    )


def history_restore(
    export_dir: str,
    revision_hash: str,
    actor: str,
    requirement: str,
    message: str = "restore",
    expected_revision: str | None = None,
) -> HistoryRestoreResponse:
    """Restore a clean workspace to a prior revision as a new revision."""
    service = WorkspaceHistoryService(_sandbox_path(export_dir))
    if service.staged_changes() or service.working_changes():
        raise ValueError("Workspace must be clean before restore")
    revision = service.restore(
        revision_hash,
        actor=actor,
        requirement=requirement,
        message=message,
        expected_revision=expected_revision,
    )
    cache.get_codebase(_sandbox_path(export_dir), rebuild=True)
    return HistoryRestoreResponse(
        revision=_history_revision(revision),
        restored_from=revision_hash,
    )


def apply_sail_edit(
    export_dir: str,
    uuid: str,
    definition: str,
) -> ApplySailEditResponse:
    """Validate and atomically update one SAIL object definition."""
    export_path = _sandbox_path(export_dir)
    cb = cache.get_codebase(export_path)
    obj = cb.get_object(uuid)
    if obj is None:
        raise ValueError("Object not found")
    analysis = analyze_sail(
        definition,
        target_version=cb.appian_version or None,
        known_uuids=set(cb.objects),
        declared_inputs=[item.name for item in getattr(obj, "rule_inputs", [])],
    )
    diagnostics = _analysis_diagnostics(analysis.diagnostics)
    if not analysis.is_valid:
        return ApplySailEditResponse(
            status="rejected",
            object_uuid=uuid,
            diagnostics=diagnostics,
        )
    output = write_object(
        export_path,
        {
            "type": obj.object_type.value,
            "name": obj.name,
            "uuid": uuid,
            "action": "modify",
            "definition": definition,
        },
    )
    if output is None:
        raise RuntimeError("SAIL edit could not be written")
    _sandbox_path(output)
    cache.get_codebase(export_path, rebuild=True)
    return ApplySailEditResponse(
        status="updated",
        object_uuid=uuid,
        file_path=_display_path(output),
        diagnostics=diagnostics,
    )


def bulk_add_tests(
    export_dir: str,
    object_uuids: list[str],
    tests: list[str],
    preview: bool,
) -> BulkAddTestsResponse:
    """Replace test nodes on multiple content objects, with preview support."""
    if not object_uuids:
        raise ValueError("object_uuids must not be empty")
    if not tests:
        raise ValueError("tests must not be empty")
    for test_xml in tests:
        try:
            node = etree.fromstring(test_xml.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            raise ValueError("Invalid test node XML") from exc
        if etree.QName(node).localname not in {"test", "testCase"}:
            raise ValueError("Test node root must be <test> or <testCase>")

    export_path = _sandbox_path(export_dir)
    cb = cache.get_codebase(export_path)
    objects: list[Any] = []
    source_bytes: dict[Path, bytes] = {}
    for uuid in dict.fromkeys(object_uuids):
        obj = cb.get_object(uuid)
        if obj is None:
            raise ValueError(f"Object not found: {uuid}")
        if obj.object_type.value not in {"interface", "expression_rule", "rule"}:
            raise ValueError(f"Object does not support embedded tests: {uuid}")
        path = _sandbox_path(obj.file_path)
        if not path.is_relative_to(export_path):
            raise ValueError("Object file must be inside export_dir")
        objects.append(obj)
        source_bytes[path] = path.read_bytes()

    file_paths = [_display_path(Path(obj.file_path)) for obj in objects]
    if preview:
        return BulkAddTestsResponse(
            status="preview",
            object_uuids=[obj.uuid for obj in objects],
            test_count=len(tests),
            file_paths=file_paths,
        )

    try:
        for obj in objects:
            output = write_object(
                export_path,
                {
                    "type": obj.object_type.value,
                    "name": obj.name,
                    "uuid": obj.uuid,
                    "action": "modify",
                    "test_nodes": tests,
                },
            )
            if output is None:
                raise RuntimeError(f"Tests could not be written: {obj.uuid}")
    except Exception:
        for path, payload in source_bytes.items():
            path.write_bytes(payload)
        raise
    cache.get_codebase(export_path, rebuild=True)
    return BulkAddTestsResponse(
        status="updated",
        object_uuids=[obj.uuid for obj in objects],
        test_count=len(tests),
        file_paths=file_paths,
    )


def generate_full_zip(request: GenerateFullZipRequest) -> GenerateFullZipResponse:
    """Package a source-pure full ZIP at a new isolated output path."""
    export_dir = _sandbox_path(request.export_dir)
    output_path = _sandbox_path(request.output_path, must_exist=False)
    if output_path.is_relative_to(export_dir):
        raise ValueError("output_path must be outside export_dir")
    if output_path.exists():
        raise ValueError("output_path must not already exist")
    if output_path.suffix.casefold() != ".zip":
        raise ValueError("output_path must end with .zip")
    built = build_appian_zip(export_dir, output_path, request.modifications)
    is_valid, issues = validate_zip_structure(built)
    return GenerateFullZipResponse(
        output_path=_display_path(built),
        is_valid=is_valid,
        issues=issues,
    )
