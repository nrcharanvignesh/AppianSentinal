from __future__ import annotations

from pathlib import Path

import pytest

from appian_sentinel.generator.object_writer import ObjectWriteError, write_object
from appian_sentinel.parser.codebase_map import build_codebase_map
from appian_sentinel.parser.sail_diagnostics import analyze_sail
from appian_sentinel.parser.xml_parser import parse_appian_xml

UUID = "_a-33333333-3333-8000-3333-333333333333_100003"
VERSION_UUID = "_a-44444444-4444-8000-4444-444444444444_100004"


def test_generated_object_validates_round_trips_and_resolves(
    tmp_path: Path,
) -> None:
    generated_object: dict[str, object] = {
        "type": "interface",
        "name": "APP_GeneratedView",
        "uuid": UUID,
        "action": "create",
        "sail_code": "a!localVariables(local!label: \"Ready\", a!textField(label: local!label))",
        "rule_inputs": [],
        "versionUuid": VERSION_UUID,
    }

    output = write_object(tmp_path, generated_object)

    assert output is not None
    parsed = parse_appian_xml(output)
    assert parsed is not None
    analysis = analyze_sail(parsed.definition)
    assert analysis.errors == []

    codebase = build_codebase_map(tmp_path)
    assert codebase.resolve_name(UUID) == "APP_GeneratedView"
    assert codebase.resolve_uuid("APP_GeneratedView") == UUID
    assert codebase.get_object(UUID) is not None


def test_invalid_generated_object_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    generated_object: dict[str, object] = {
        "type": "interface",
        "name": "APP_InvalidView",
        "uuid": UUID,
        "action": "create",
        "sail_code": "a!localVariables(local!x: 1; local!x)",
        "rule_inputs": [],
        "versionUuid": VERSION_UUID,
    }
    target = tmp_path / "content" / f"{UUID}.xml"

    with pytest.raises(ObjectWriteError, match="SAIL validation failed"):
        write_object(tmp_path, generated_object)

    assert not target.exists()
    assert not target.with_name(f".{target.name}.tmp").exists()
