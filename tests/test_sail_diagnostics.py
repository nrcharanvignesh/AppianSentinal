from __future__ import annotations

import json

from appian_sentinel.generator.sail_generator import SailGenerator
from appian_sentinel.parser.sail_catalog import DEFAULT_SAIL_CATALOG, parse_version
from appian_sentinel.parser.sail_diagnostics import (
    DiagnosticSeverity,
    analyze_sail,
)
from appian_sentinel.tester.sail_validator import SailValidator


def test_catalog_valid_and_rejected_sets_are_disjoint() -> None:
    assert not (
        DEFAULT_SAIL_CATALOG.valid.keys()
        & DEFAULT_SAIL_CATALOG.rejected
    )


def test_build_qualified_appian_version_uses_major_minor() -> None:
    assert parse_version("26.6.205.0") == (26, 6)


def test_unknown_callable_warns_but_known_invalid_callable_errors() -> None:
    unknown = analyze_sail(
        "a!futureWidget(value: 1)",
        target_version="26.6",
    )
    invalid = analyze_sail(
        "a!filter(items: {})",
        target_version="26.6",
    )

    assert [(item.code, item.severity) for item in unknown.diagnostics] == [
        ("SAIL021", DiagnosticSeverity.WARNING),
    ]
    assert any(
        item.code == "SAIL020"
        and item.severity == DiagnosticSeverity.ERROR
        for item in invalid.diagnostics
    )


def test_valid_map_is_not_rejected() -> None:
    analysis = analyze_sail('a!map("quoted key": true())', target_version="26.6")

    assert analysis.diagnostics == []


def test_uuid_and_rule_input_findings_have_exact_ranges() -> None:
    source = '#"missing-id"(ri!missing)'
    analysis = analyze_sail(
        source,
        known_uuids=set(),
        declared_inputs=[],
    )

    findings = {
        item.code: item
        for item in analysis.diagnostics
        if item.code in {"SAIL030", "SAIL031"}
    }
    assert set(findings) == {"SAIL030", "SAIL031"}
    for finding in findings.values():
        assert finding.range.end.offset > finding.range.start.offset
        assert source[
            finding.range.start.offset : finding.range.end.offset
        ]
    assert source[
        findings["SAIL031"].range.start.offset :
        findings["SAIL031"].range.end.offset
    ] == "ri!missing"


def test_uuid_resolution_supports_direct_and_appian_urn_forms() -> None:
    root = "b93f42a5-a085-401f-85c2-6975da5b7d84"
    references = (
        root,
        f"urn:appian:record-type:v1:{root}",
        f"urn:appian:record-field:v1:{root}/relationship/field",
    )

    for reference in references:
        analysis = analyze_sail(f'#"{reference}"()', known_uuids={root})
        assert not [
            item
            for item in analysis.diagnostics
            if item.code == "SAIL030"
        ]


def test_uuid_resolution_reports_unresolved_urn_owner() -> None:
    missing = "00000000-0000-4000-8000-000000000099"
    source = (
        f'#"urn:appian:record-field:v1:{missing}/relationship/field"()'
    )

    analysis = analyze_sail(source, known_uuids=set())

    unresolved = [item for item in analysis.diagnostics if item.code == "SAIL030"]
    assert len(unresolved) == 1
    assert missing in unresolved[0].message


def test_function_urn_does_not_require_an_object_uuid() -> None:
    analysis = analyze_sail(
        '#"urn:appian:function:v1:a:update"()',
        known_uuids=set(),
    )

    assert not [item for item in analysis.diagnostics if item.code == "SAIL030"]


def test_urls_inside_quoted_appian_references_are_masked() -> None:
    source = "cast('type!{http://www.appian.com/ae/types/2009}Map', {})"

    analysis = analyze_sail(source)

    assert not [item for item in analysis.diagnostics if item.code == "SAIL015"]


def test_forbidden_operator_is_one_non_cascading_diagnostic() -> None:
    analysis = analyze_sail("ri!value == 1")

    assert [(item.code, item.line, item.column, item.end_column)
            for item in analysis.diagnostics] == [
        ("SAIL010", 1, 10, 12),
    ]


def test_validator_is_a_facade_over_unified_analysis() -> None:
    result = SailValidator(target_version="26.6").validate(
        "a!futureWidget()",
    )

    assert result.is_valid
    assert [item.code for item in result.warnings] == ["SAIL021"]
    assert result.diagnostics[0].code == result.warnings[0].code


def test_generator_returns_output_diagnostics() -> None:
    raw = json.dumps({
        "code": "a!filter(items: {})",
        "confidence": 0.8,
        "notes": [],
        "warnings": [],
    })

    generated = SailGenerator._parse_response(raw)

    assert [item.code for item in generated.diagnostics] == ["SAIL020"]
    assert generated.warnings[0].startswith("SAIL020 ")
