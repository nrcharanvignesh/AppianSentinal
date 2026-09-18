from __future__ import annotations

from pathlib import Path

import pytest

from appian_sentinel.models.appian_objects import AppianObject, ObjectType, extract_uuid_references
from appian_sentinel.models.codebase import (
    AmbiguousObjectNameError,
    AmbiguousObjectUuidError,
    CodebaseMap,
)
from appian_sentinel.parser.codebase_map import OBJECT_SCAN_PATTERNS, build_codebase_map

FIXTURE_EXPORT = Path(__file__).parent / "fixtures" / "reference_export"
REFERENCE_EXPORT = Path(__file__).parents[1] / "appian_export"


def test_slim_reference_inventory_reconciles_all_files() -> None:
    codebase = build_codebase_map(FIXTURE_EXPORT)

    expected_files = sum(
        len(list((FIXTURE_EXPORT / directory).glob(pattern)))
        for directory, pattern in OBJECT_SCAN_PATTERNS.items()
    )
    assert codebase.scanned_files == expected_files == 7
    assert not codebase.parse_failures
    assert len(codebase.objects) == expected_files
    assert {obj.object_type for obj in codebase.objects.values()} == {
        ObjectType.PORTAL,
        ObjectType.PROCESS_MODEL,
        ObjectType.PROCESS_MODEL_FOLDER,
        ObjectType.RECORD_TYPE,
        ObjectType.TEMPO_REPORT,
        ObjectType.TRANSLATION_SET,
        ObjectType.TRANSLATION_STRING,
    }
    assert all(not Path(obj.file_path).is_absolute() for obj in codebase.objects.values())


def test_modern_record_actions_and_relationships_are_parsed() -> None:
    codebase = build_codebase_map(FIXTURE_EXPORT)
    record = codebase.get_object("11111111-1111-4111-8111-111111111111")

    assert record is not None
    assert record.record_actions[0].process_model_uuid == "22222222-2222-4222-8222-222222222222"
    assert record.record_actions[0].reference_key == "approve"
    assert record.relationships[0].related_record_type_uuid == "33333333-3333-4333-8333-333333333333"
    assert record.relationships[0].source_field_uuid == "source-field"
    assert record.relationships[0].target_field_uuid == "target-field"


def test_process_topology_nodes_edges_and_swimlanes_are_parsed() -> None:
    codebase = build_codebase_map(FIXTURE_EXPORT)
    process = codebase.get_object("22222222-2222-4222-8222-222222222222")

    assert process is not None
    assert [node.node_type for node in process.nodes] == ["core.0", "core.1"]
    assert process.edges[0].source_uuid == "node-start"
    assert process.edges[0].target_uuid == "node-end"
    assert process.swimlanes[0].name == "System"
    assert process.swimlanes[0].unattended


def test_translation_and_extended_reference_forms() -> None:
    codebase = build_codebase_map(FIXTURE_EXPORT)
    translation = codebase.get_object("77777777-7777-4777-8777-777777777777")

    assert translation is not None
    assert translation.translations == {"en-US": "Hello"}
    assert translation.translation_set_uuid == "66666666-6666-4666-8666-666666666666"
    assert extract_uuid_references(
        'urn:appian:record-field:v1:11111111-1111-4111-8111-111111111111/field '
        '_a-0000ec3a-acb2-8000-9ba6-011c48011c48_78136'
    ) == {
        "11111111-1111-4111-8111-111111111111",
        "_a-0000ec3a-acb2-8000-9ba6-011c48011c48_78136",
    }


def test_name_ambiguity_is_explicit_but_unique_resolution_is_compatible() -> None:
    codebase = CodebaseMap(
        objects={
            "uuid-1": AppianObject(uuid="uuid-1", name="Duplicate"),
            "uuid-2": AppianObject(uuid="uuid-2", name="Duplicate"),
        },
        name_to_uuid={"Unique": "uuid-3"},
        name_to_uuids={"Duplicate": ["uuid-1", "uuid-2"], "Unique": ["uuid-3"]},
    )

    assert codebase.resolve_uuid("Unique") == "uuid-3"
    assert codebase.resolve_uuids("Duplicate") == ["uuid-1", "uuid-2"]
    with pytest.raises(AmbiguousObjectNameError):
        codebase.resolve_uuid("Duplicate")


def test_uuid_ambiguity_preserves_all_source_objects() -> None:
    primary = AppianObject(uuid="duplicate-uuid", file_path="content/first.xml")
    duplicate = AppianObject(uuid="duplicate-uuid", file_path="content/second.xml")
    codebase = CodebaseMap(
        objects={"duplicate-uuid": primary},
        uuid_collisions={"duplicate-uuid": [duplicate]},
    )

    assert codebase.get_uuid_candidates("duplicate-uuid") == [primary, duplicate]
    assert codebase.summarise().total_objects == 2
    with pytest.raises(AmbiguousObjectUuidError):
        codebase.get_object("duplicate-uuid")


@pytest.mark.skipif(not REFERENCE_EXPORT.exists(), reason="full reference export is not available")
def test_optional_full_reference_inventory_reconciles() -> None:
    codebase = build_codebase_map(REFERENCE_EXPORT)

    assert codebase.scanned_files == 2624
    assert not codebase.parse_failures
    assert len(codebase.objects) == 2624
    assert codebase.summarise().counts_by_type == {
        "connected_system": 4,
        "constant": 652,
        "data_store": 1,
        "data_type": 7,
        "decision": 18,
        "document": 155,
        "expression_rule": 610,
        "folder": 37,
        "group": 37,
        "interface": 615,
        "outbound_integration": 9,
        "portal": 2,
        "process_model": 178,
        "process_model_folder": 3,
        "record_type": 148,
        "rules_folder": 3,
        "site": 5,
        "tempo_report": 1,
        "translation_set": 1,
        "translation_string": 130,
        "unknown": 1,
        "web_api": 7,
    }
