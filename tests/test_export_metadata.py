from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.services import export_metadata
from appian_sentinel.services.export_metadata import (
    metadata_tags,
    next_export_log_id,
    update_application_membership,
    update_export_log,
    update_export_metadata,
    update_object_metadata,
)
from appian_sentinel.services.mutation_transaction import MutationTransaction

APP_UUID = "1a34a900-d6e0-45ec-970e-72d015719d7e"
EXISTING_UUID = "_a-0000ed6a-1f0e-8000-9bac-011c48011c48_555832"
NEW_UUID = "11111111-2222-3333-4444-555555555555"

APPLICATION_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<applicationHaul xmlns:a="http://www.appian.com/ae/types/2009">
    <versionUuid>_a-0000f03c-e8bd-8000-9bc0-011c48011c48_1001282</versionUuid>
    <application>
        <name>Interactions Hub</name>
        <uuid>1a34a900-d6e0-45ec-970e-72d015719d7e</uuid>
        <description></description>
        <associatedObjects>
            <globalIdMap>
                <item>
                    <type>datatype</type>
                    <uuids>
                        <uuid>{urn:appian:ps:dynamicdocgen}XslParameter</uuid>
                    </uuids>
                </item>
                <item>
                    <type>dataStore</type>
                    <uuids>
                        <uuid>_a-0000ed6a-1f0e-8000-9bac-011c48011c48_555832</uuid>
                    </uuids>
                </item>
                <item>
                    <type>user</type>
                    <uuids/>
                </item>
            </globalIdMap>
        </associatedObjects>
        <applicationNavigation/>
    </application>
</applicationHaul>
"""

EXPORT_LOG = (
    b"Success (4):\r\n"
    b'datatype 4296 {urn:appian:ps:dynamicdocgen}XslParameter "XslParameter"\r\n'
    + f'dataStore 40311 {EXISTING_UUID} "IHUB Materialized Views"\r\n'.encode()
    + b'group 40 46b0a738-ea79-4c67-af95-e9cd57443c44 "GPAS Administrators"\r\n'
    + b'group 81 _e-0000ec96-ea49-8000-9af5-01075c01075c_226 "Reviewer"\r\n'
    + b"\r\n2026-06-20 12:00:00 INFO export completed\r\n"
)


def _membership(xml: bytes, export_tag: str) -> list[str]:
    root = etree.fromstring(xml)
    return [
        str(value)
        for value in root.xpath(
            ".//*[local-name()='associatedObjects']"
            "/*[local-name()='globalIdMap']"
            "/*[local-name()='item'][*[local-name()='type' and text()=$tag]]"
            "/*[local-name()='uuids']/*[local-name()='uuid']/text()",
            tag=export_tag,
        )
    ]


def _write_fixture(root: Path) -> tuple[Path, Path]:
    application = root / "application" / f"{APP_UUID}.xml"
    log = root / "META-INF" / "export.log"
    application.parent.mkdir(parents=True)
    log.parent.mkdir(parents=True)
    application.write_bytes(APPLICATION_XML)
    log.write_bytes(EXPORT_LOG)
    return application, log


def test_next_export_log_id_is_positive_and_scoped_to_tag() -> None:
    log = (
        b"Success (5):\n"
        b'rule 0 old-zero "Zero"\n'
        b'rule 7 old-seven "Seven"\n'
        b'rule 3 old-three "Three"\n'
        b'group 900 other "Other"\n'
        b'rule 7 duplicate-id "Duplicate numeric ID"\n'
    )

    assert next_export_log_id(log, "rule") == 8
    assert next_export_log_id(log, "site") == 1


def test_export_log_add_allocates_id_preserves_crlf_and_is_idempotent() -> None:
    changed = update_export_log(EXPORT_LOG, "dataStore", NEW_UUID, 'New "Store"', add=True)

    assert changed.startswith(b"Success (5):\r\n")
    assert (
        f'dataStore 40312 {NEW_UUID} "New \'Store\'"\r\n'.encode()
        in changed
    )
    assert b"\r\n2026-06-20 12:00:00 INFO export completed\r\n" in changed
    assert update_export_log(changed, "dataStore", NEW_UUID, 'New "Store"', add=True) == changed


def test_export_log_add_collapses_duplicates_and_remove_deletes_all() -> None:
    duplicate = update_export_log(EXPORT_LOG, "group", NEW_UUID, "First", add=True)
    duplicate = duplicate.replace(
        b"\r\n\r\n2026-06-20",
        f'\r\ngroup 83 {NEW_UUID} "Duplicate"\r\n\r\n2026-06-20'.encode(),
    ).replace(b"Success (5):", b"Success (6):")

    added = update_export_log(duplicate, "group", NEW_UUID, "Final", add=True)
    assert added.count(NEW_UUID.encode()) == 1
    assert f'group 82 {NEW_UUID} "Final"'.encode() in added
    assert added.startswith(b"Success (5):\r\n")

    removed = update_export_log(added, "group", NEW_UUID, "ignored", add=False)
    assert NEW_UUID.encode() not in removed
    assert removed.startswith(b"Success (4):\r\n")


def test_application_membership_uses_real_global_id_map_shape() -> None:
    changed = update_application_membership(
        APPLICATION_XML, "dataStore", NEW_UUID, add=True
    )

    assert _membership(changed, "dataStore") == [EXISTING_UUID, NEW_UUID]
    assert _membership(changed, "datatype") == [
        "{urn:appian:ps:dynamicdocgen}XslParameter"
    ]
    assert update_application_membership(changed, "dataStore", NEW_UUID, add=True) == changed

    removed = update_application_membership(changed, "dataStore", NEW_UUID, add=False)
    assert _membership(removed, "dataStore") == [EXISTING_UUID]


def test_application_membership_creates_missing_real_item_shape() -> None:
    changed = update_application_membership(APPLICATION_XML, "site", NEW_UUID, add=True)

    assert _membership(changed, "site") == [NEW_UUID]
    root = etree.fromstring(changed)
    item = root.xpath(
        ".//*[local-name()='globalIdMap']"
        "/*[local-name()='item'][*[local-name()='type' and text()='site']]"
    )[0]
    assert [etree.QName(child).localname for child in item] == ["type", "uuids"]
    tags = root.xpath(
        ".//*[local-name()='associatedObjects']"
        "/*[local-name()='globalIdMap']"
        "/*[local-name()='item']/*[local-name()='type']/text()"
    )
    assert tags == ["datatype", "dataStore", "user", "site"]


@pytest.mark.parametrize(
    ("object_type", "expected"),
    [
        (ObjectType.EXPRESSION_RULE, ("content", "content")),
        (ObjectType.REPORT, ("content", "content")),
        (ObjectType.DOCUMENT_FOLDER, ("content", "content")),
        (ObjectType.PROCESS_REPORT, ("processReport", "taskReport")),
        (ObjectType.ROBOTIC_TASK, ("roboticTask", "roboticTaskDesignObject")),
        (ObjectType.ROBOT_POOL, ("robotPool", "robotPoolDesignObject")),
        (
            ObjectType.CONTROL_PANEL_HIERARCHY_ITEM,
            ("controlPanelHierarchyItem", "controlPanelTierItem"),
        ),
        (ObjectType.FEED, ("feed", "tempoFeed")),
        (ObjectType.RECORD_TYPE, ("recordType", "recordType")),
    ],
)
def test_metadata_tags_match_real_application_contract(
    object_type: ObjectType,
    expected: tuple[str, str],
) -> None:
    assert metadata_tags(object_type) == expected


def test_transaction_returns_changed_paths_and_handles_noop(tmp_path: Path) -> None:
    application, log = _write_fixture(tmp_path)

    changed = update_export_metadata(
        tmp_path, "dataStore", NEW_UUID, "New Store", add=True
    )

    assert changed == [
        application.relative_to(tmp_path),
        log.relative_to(tmp_path),
    ]
    assert _membership(application.read_bytes(), "dataStore")[-1] == NEW_UUID
    assert NEW_UUID.encode() in log.read_bytes()
    assert (
        update_export_metadata(
            tmp_path, "dataStore", NEW_UUID, "New Store", add=True
        )
        == []
    )


def test_object_metadata_uses_content_bucket_for_expression_rule(tmp_path: Path) -> None:
    application, log = _write_fixture(tmp_path)

    changed = update_object_metadata(
        tmp_path,
        ObjectType.EXPRESSION_RULE,
        NEW_UUID,
        "New Rule",
        add=True,
    )

    assert changed == [application.relative_to(tmp_path), log.relative_to(tmp_path)]
    assert _membership(application.read_bytes(), "content") == [NEW_UUID]
    assert f'content 1 {NEW_UUID} "New Rule"'.encode() in log.read_bytes()


def test_transaction_rolls_back_first_file_if_second_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, log = _write_fixture(tmp_path)
    before_application = application.read_bytes()
    before_log = log.read_bytes()
    calls = 0

    def transaction(root: Path) -> MutationTransaction:
        def fail_second_write(path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second-write failure")

        return MutationTransaction(root, on_applied=fail_second_write)

    monkeypatch.setattr(export_metadata, "MutationTransaction", transaction)

    with pytest.raises(OSError, match="injected second-write failure"):
        update_export_metadata(
            tmp_path, "dataStore", NEW_UUID, "New Store", add=True
        )

    assert application.read_bytes() == before_application
    assert log.read_bytes() == before_log
