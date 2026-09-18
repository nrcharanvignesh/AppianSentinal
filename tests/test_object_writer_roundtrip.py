from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.generator import xml_writer
from appian_sentinel.generator.object_writer import ObjectWriteError, write_object

UUID = "_a-11111111-1111-8000-1111-111111111111_100001"
VERSION_UUID = "_a-22222222-2222-8000-2222-222222222222_100002"
FIXTURE_EXPORT = Path(__file__).parent / "fixtures" / "reference_export"


def _content_xml(name: str = "APP_Rule") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<contentHaul xmlns:a="http://www.appian.com/ae/types/2009" custom="keep">
  <!--preserve-comment-->
  <versionUuid>{VERSION_UUID}</versionUuid>
  <rule>
    <name>{name}</name>
    <uuid>{UUID}</uuid>
    <description untouched="yes">Keep me</description>
    <definition>old()</definition>
    <namedTypedValue><name>oldInput</name><type><name>Text</name></type></namedTypedValue>
    <testCase id="old"><expected>true</expected></testCase>
    <preferredEditor>legacy</preferredEditor>
  </rule>
  <roleMap public="true"><role name="readers"><groups/></role></roleMap>
</contentHaul>
""".encode()


def _canonical(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n", with_comments=True)


def test_modify_resolves_uuid_file_and_preserves_unrelated_nodes(tmp_path: Path) -> None:
    opaque_path = tmp_path / "content" / "opaque-export-name.xml"
    opaque_path.parent.mkdir(parents=True)
    opaque_path.write_bytes(_content_xml())
    before = etree.parse(str(opaque_path))
    before_role = _canonical(before.xpath("//*[local-name()='roleMap']")[0])
    before_description = _canonical(before.xpath("//*[local-name()='description']")[0])

    result = write_object(
        tmp_path,
        {
            "type": "rule",
            "name": "APP_Rule",
            "uuid": UUID,
            "action": "modify",
            "definition": "a!localVariables(local!x: 1, local!x)",
            "rule_inputs": [{"name": "value", "type_name": "Integer"}],
            "test_nodes": ['<testCase id="new"><expected>1</expected></testCase>'],
        },
    )

    assert result == opaque_path
    assert not (tmp_path / "content" / "APP_Rule.xml").exists()
    assert not opaque_path.with_name(f".{opaque_path.name}.tmp").exists()
    after = etree.parse(str(opaque_path))
    assert after.xpath("string(//*[local-name()='definition'])") == "a!localVariables(local!x: 1, local!x)"
    assert after.xpath("string(//*[local-name()='namedTypedValue']/*[local-name()='name'])") == "value"
    assert after.xpath("string(//*[local-name()='testCase']/@id)") == "new"
    assert _canonical(after.xpath("//*[local-name()='roleMap']")[0]) == before_role
    assert _canonical(after.xpath("//*[local-name()='description']")[0]) == before_description


def test_modify_can_resolve_uuid_from_export_log_name(tmp_path: Path) -> None:
    path = tmp_path / "content" / f"{UUID}.xml"
    path.parent.mkdir(parents=True)
    path.write_bytes(_content_xml())
    meta = tmp_path / "META-INF"
    meta.mkdir()
    (meta / "export.log").write_text(f'Success (1):\nrule 7 {UUID} "APP_Rule"\n', encoding="utf-8")

    result = write_object(
        tmp_path,
        {"type": "rule", "name": "APP_Rule", "action": "modify", "definition": "new()"},
    )

    assert result == path
    assert etree.parse(str(path)).xpath("string(//*[local-name()='definition'])") == "new()"


def test_new_object_uses_uuid_backed_filename(tmp_path: Path) -> None:
    result = write_object(
        tmp_path,
        {
            "type": "interface",
            "name": "APP_View",
            "uuid": UUID,
            "versionUuid": VERSION_UUID,
            "action": "create",
            "definition": "a!textField()",
        },
    )

    assert result == tmp_path / "content" / f"{UUID}.xml"
    assert result.is_file()
    assert not (tmp_path / "content" / "APP_View.xml").exists()
    etree.parse(str(result))


def test_invalid_test_fragment_does_not_change_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "content" / f"{UUID}.xml"
    path.parent.mkdir(parents=True)
    original = _content_xml()
    path.write_bytes(original)

    with pytest.raises(ObjectWriteError):
        write_object(
            tmp_path,
            {
                "type": "rule",
                "name": "APP_Rule",
                "uuid": UUID,
                "action": "modify",
                "test_nodes": ["<notATest/>"],
            },
        )

    assert path.read_bytes() == original


def test_modify_missing_uuid_does_not_create_name_file(tmp_path: Path) -> None:
    with pytest.raises(ObjectWriteError):
        write_object(
            tmp_path,
            {
                "type": "rule",
                "name": "APP_Missing",
                "uuid": UUID,
                "action": "modify",
                "definition": "new()",
            },
        )

    assert not (tmp_path / "content" / "APP_Missing.xml").exists()


def test_write_failure_surfaces_without_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "content" / f"{UUID}.xml"

    def fail_atomic_write(output_path: Path, data: bytes) -> None:
        raise PermissionError("read-only target")

    monkeypatch.setattr(xml_writer, "_atomic_write_xml", fail_atomic_write)

    with pytest.raises(ObjectWriteError) as error:
        write_object(
            tmp_path,
            {
                "type": "interface",
                "name": "APP_View",
                "uuid": UUID,
                "versionUuid": VERSION_UUID,
                "action": "create",
                "sail_code": "a!textField()",
            },
        )

    assert error.value.object_name == "APP_View"
    assert error.value.object_type == "interface"
    assert error.value.action == "create"
    assert error.value.target_path == target
    assert not target.exists()
    assert not target.with_name(f".{target.name}.tmp").exists()


def test_record_type_modify_preserves_unrelated_nodes(tmp_path: Path) -> None:
    target = tmp_path / "recordType" / "opaque-record.xml"
    target.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE_EXPORT / "recordType" / "record.xml", target)
    before = etree.parse(str(target))
    before_actions = _canonical(
        before.xpath("//*[local-name()='relatedActionCfg']")[0]
    )
    before_relationship = _canonical(
        before.xpath("//*[local-name()='recordRelationshipCfg']")[0]
    )

    result = write_object(
        tmp_path,
        {
            "type": "record_type",
            "name": "Renamed Reference Record",
            "uuid": "11111111-1111-4111-8111-111111111111",
            "action": "modify",
        },
    )

    assert result == target
    after = etree.parse(str(target))
    assert after.xpath(
        "string(//*[local-name()='recordType']/@*[local-name()='name'])"
    ) == "Renamed Reference Record"
    assert _canonical(
        after.xpath("//*[local-name()='relatedActionCfg']")[0]
    ) == before_actions
    assert _canonical(
        after.xpath("//*[local-name()='recordRelationshipCfg']")[0]
    ) == before_relationship


def test_process_model_modify_preserves_unrelated_nodes(tmp_path: Path) -> None:
    target = tmp_path / "processModel" / "opaque-process.xml"
    target.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE_EXPORT / "processModel" / "process.xml", target)
    before = etree.parse(str(target))
    before_nodes = _canonical(before.xpath("//*[local-name()='nodes']")[0])
    before_lanes = _canonical(before.xpath("//*[local-name()='lanes']")[0])

    result = write_object(
        tmp_path,
        {
            "type": "process_model",
            "name": "Renamed Reference Process",
            "uuid": "22222222-2222-4222-8222-222222222222",
            "action": "modify",
        },
    )

    assert result == target
    after = etree.parse(str(target))
    assert after.xpath(
        "string(//*[local-name()='pm']/*[local-name()='meta']"
        "/*[local-name()='name']//*[local-name()='value'])"
    ) == "Renamed Reference Process"
    assert _canonical(after.xpath("//*[local-name()='nodes']")[0]) == before_nodes
    assert _canonical(after.xpath("//*[local-name()='lanes']")[0]) == before_lanes
