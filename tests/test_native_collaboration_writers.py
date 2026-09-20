from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.generator.native_collaboration_writers import (
    build_native_collaboration_artifact,
)
from appian_sentinel.models.appian_objects import (
    Document,
    Folder,
    Group,
    KnowledgeCenter,
    ObjectType,
    RulesFolder,
)
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE
from appian_sentinel.parser.codebase_map import build_codebase_map

PARENT_UUID = "11111111-1111-4111-8111-111111111111"
VERSION_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

# Real export corpus used by the independent validation run. Structure tests
# that read it are skipped when the corpus is not present on this machine.
CORPUS_ROOT = Path(
    os.environ.get(
        "APPIAN_NATIVE_SPEC_DIR",
        str(Path(os.environ.get("TEMP", "/tmp")) / "AppianSentinel-native-spec"),
    )
)

# Sample file per proven shape, relative to the corpus root.
CORPUS_SAMPLES: dict[str, str] = {
    "group": "group/_e-0000f03c-e8bd-8000-9b0d-01075c01075c_348.xml",
    "rulesFolder": "content/64869106-d692-4685-a3bb-765035376ca2.xml",
    "folder": "content/_a-0000ef9a-a4f8-8000-9bbc-011c48011c48_760597.xml",
    "communityKnowledgeCenter": "content/dd6f99af-845e-4628-88f0-7f35b025f822.xml",
    "document": "content/_a-0000f03c-e8bd-8000-9bc0-011c48011c48_993889.xml",
}

UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _child_tags(element: etree._Element) -> list[str]:
    return [child.tag for child in element if isinstance(child.tag, str)]


def _corpus_root(sample_key: str) -> etree._Element:
    path = CORPUS_ROOT / CORPUS_SAMPLES[sample_key]
    if not path.is_file():
        pytest.skip(f"real corpus sample missing: {path}")
    return etree.fromstring(path.read_bytes())


def _build(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> etree._Element:
    artifact, _ = build_native_collaboration_artifact(object_type, uuid, name, fields)
    return etree.fromstring(artifact)


def _write_artifact(
    export_dir: Path,
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[bytes, dict[str, bytes]]:
    artifact, payloads = build_native_collaboration_artifact(
        object_type,
        uuid,
        name,
        fields,
    )
    directory = export_dir / CAPABILITY_BY_TYPE[object_type].export_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{uuid}.xml").write_bytes(artifact)
    for relative_path, payload in payloads.items():
        target = directory / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return artifact, payloads


# ---------------------------------------------------------------------------
# Round trip through the parser
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("object_type", "uuid", "name", "fields", "model"),
    [
        (
            ObjectType.GROUP,
            "22222222-2222-4222-8222-222222222222",
            "TEST Administrators",
            {"description": "Native group", "version_uuid": VERSION_UUID},
            Group,
        ),
        (
            ObjectType.RULES_FOLDER,
            "44444444-4444-4444-8444-444444444444",
            "TEST Rule Folder",
            {
                "description": "Native rule folder",
                "parent_uuid": PARENT_UUID,
                "version_uuid": VERSION_UUID,
            },
            RulesFolder,
        ),
        (
            ObjectType.DOCUMENT_FOLDER,
            "55555555-5555-4555-8555-555555555555",
            "TEST Document Folder",
            {
                "description": "Native document folder",
                "parent_uuid": PARENT_UUID,
                "version_uuid": VERSION_UUID,
            },
            Folder,
        ),
        (
            ObjectType.KNOWLEDGE_CENTER,
            "66666666-6666-4666-8666-666666666666",
            "TEST Knowledge Center",
            {
                "description": "Native knowledge center",
                "parent_uuid": "SYSTEM_COMMUNITY_ROOT",
                "version_uuid": VERSION_UUID,
            },
            KnowledgeCenter,
        ),
        (
            ObjectType.DOCUMENT,
            "_a-00000000-0000-8000-0000-000000000000_1001",
            "TEST Terms Of Use",
            {
                "description": "Native document",
                "parent_uuid": PARENT_UUID,
                "file_extension": "pdf",
                "payload": b"%PDF-1.4 caller supplied",
                "version_uuid": VERSION_UUID,
            },
            Document,
        ),
    ],
)
def test_artifact_round_trips_through_the_parser(
    tmp_path: Path,
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
    model: type,
) -> None:
    _write_artifact(tmp_path, object_type, uuid, name, fields)

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(uuid)

    assert isinstance(parsed, model)
    assert parsed.uuid == uuid
    assert parsed.name == name
    assert parsed.version_uuid == VERSION_UUID
    assert parsed.file_path == (
        f"{CAPABILITY_BY_TYPE[object_type].export_dir}/{uuid}.xml"
    )


# ---------------------------------------------------------------------------
# Structure and field order against the real corpus
# ---------------------------------------------------------------------------

def test_group_haul_matches_the_real_corpus_structure() -> None:
    expected = _corpus_root("group")
    root = _build(
        ObjectType.GROUP,
        "_e-0000f03c-e8bd-8000-9b0d-01075c01075c_348",
        "IHUB MCP Co Pilot ",
        {
            "version_uuid": "_e-0000f03c-e8bd-8000-9b0d-01075c01075c_349",
            "security_map": "SECURITYMAP_TEAM",
            "parent_uuid": "_e-0000d398-70cf-8000-9aee-01075c01075c_6",
            "viewing_policy": "VIEWINGPOLICY_HIGH",
            "admin_users": ["mcpCopilot"],
        },
    )

    assert root.tag == expected.tag == "groupHaul"
    assert root.nsmap["a"] == expected.nsmap["a"] == "http://www.appian.com/ae/types/2009"
    assert _child_tags(root) == _child_tags(expected)
    assert _child_tags(root.find("group")) == _child_tags(expected.find("group"))
    assert _child_tags(root.find("members")) == _child_tags(expected.find("members"))
    assert _child_tags(root.find("admins")) == _child_tags(expected.find("admins"))
    assert (
        [el.tag for el in root.find("admins").find("users")]
        == [el.tag for el in expected.find("admins").find("users")]
        == ["userUuid"]
    )
    assert root.findtext("group/securityMap") == expected.findtext("group/securityMap")
    assert root.findtext("group/parentUuid") == expected.findtext("group/parentUuid")


@pytest.mark.parametrize(
    ("object_type", "sample_key", "fields"),
    [
        (
            ObjectType.RULES_FOLDER,
            "rulesFolder",
            {"parent_uuid": "SYSTEM_RULES_ROOT"},
        ),
        (
            ObjectType.DOCUMENT_FOLDER,
            "folder",
            {"parent_uuid": PARENT_UUID},
        ),
        (
            ObjectType.KNOWLEDGE_CENTER,
            "communityKnowledgeCenter",
            {"parent_uuid": "SYSTEM_COMMUNITY_ROOT"},
        ),
        (
            ObjectType.DOCUMENT,
            "document",
            {"parent_uuid": PARENT_UUID, "file_extension": "docx", "payload": b"bytes"},
        ),
    ],
)
def test_content_haul_matches_the_real_corpus_structure(
    object_type: ObjectType,
    sample_key: str,
    fields: dict[str, object],
) -> None:
    expected = _corpus_root(sample_key)
    merged: dict[str, object] = dict(fields)
    merged["version_uuid"] = VERSION_UUID
    root = _build(object_type, "88888888-8888-4888-8888-888888888888", "TEST", merged)

    assert root.tag == expected.tag == "contentHaul"
    assert _child_tags(root) == _child_tags(expected)
    assert _child_tags(root.find(sample_key)) == _child_tags(expected.find(sample_key))
    assert (
        _child_tags(root.find(f"{sample_key}/visibility"))
        == _child_tags(expected.find(f"{sample_key}/visibility"))
    )
    assert root.find("roleMap").get("public") == expected.find("roleMap").get("public")
    assert (
        [role.get("name") for role in root.findall("roleMap/role")]
        == [role.get("name") for role in expected.findall("roleMap/role")]
    )
    assert (
        [_child_tags(role) for role in root.findall("roleMap/role")]
        == [_child_tags(role) for role in expected.findall("roleMap/role")]
    )


def test_content_visibility_and_role_defaults_match_the_corpus_values() -> None:
    for sample_key, object_type, fields in (
        ("folder", ObjectType.DOCUMENT_FOLDER, {}),
        (
            "document",
            ObjectType.DOCUMENT,
            {"file_extension": "docx", "payload": b"bytes"},
        ),
    ):
        expected = _corpus_root(sample_key)
        merged: dict[str, object] = dict(fields)
        merged["version_uuid"] = VERSION_UUID
        root = _build(object_type, "uuid-under-test", "TEST", merged)

        for flag in ("advertise", "hierarchy", "indexable", "quota", "searchable"):
            assert root.findtext(f"{sample_key}/visibility/{flag}") == expected.findtext(
                f"{sample_key}/visibility/{flag}"
            )
        assert (
            [role.get("inherit") for role in root.findall("roleMap/role")]
            == [role.get("inherit") for role in expected.findall("roleMap/role")]
        )


def test_knowledge_center_advertises_and_expires_like_the_real_corpus() -> None:
    expected = _corpus_root("communityKnowledgeCenter")
    root = _build(
        ObjectType.KNOWLEDGE_CENTER,
        "99999999-9999-4999-8999-999999999999",
        "TEST Knowledge Center",
        {"parent_uuid": "SYSTEM_COMMUNITY_ROOT", "version_uuid": VERSION_UUID},
    )

    center = root.find("communityKnowledgeCenter")
    assert _child_tags(center)[-2:] == ["visibility", "expirationDays"]
    assert center.findtext("visibility/advertise") == "true"
    assert (
        center.findtext("visibility/advertise")
        == expected.findtext("communityKnowledgeCenter/visibility/advertise")
    )
    assert center.findtext("expirationDays") == "0"
    assert (
        center.findtext("expirationDays")
        == expected.findtext("communityKnowledgeCenter/expirationDays")
    )
    assert _child_tags(root) == ["versionUuid", "communityKnowledgeCenter", "roleMap", "history"]


def test_document_places_file_between_the_document_element_and_the_role_map() -> None:
    expected = _corpus_root("document")
    root = _build(
        ObjectType.DOCUMENT,
        "_a-00000000-0000-8000-0000-000000000000_2002",
        "TEST Logo",
        {"file_name": "file.png", "payload": b"bytes", "version_uuid": VERSION_UUID},
    )

    assert _child_tags(root) == _child_tags(expected)
    assert _child_tags(root) == ["versionUuid", "document", "file", "roleMap", "history"]
    assert root.findtext("file") == "file.png"


# ---------------------------------------------------------------------------
# Version UUID and history
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("object_type", "fields"),
    [
        (ObjectType.GROUP, {}),
        (ObjectType.RULES_FOLDER, {}),
        (ObjectType.DOCUMENT_FOLDER, {}),
        (ObjectType.KNOWLEDGE_CENTER, {}),
        (ObjectType.DOCUMENT, {"file_extension": "pdf", "payload": b"bytes"}),
    ],
)
def test_history_ends_with_the_haul_version_uuid(
    object_type: ObjectType,
    fields: dict[str, object],
) -> None:
    merged: dict[str, object] = dict(fields)
    merged["version_uuid"] = VERSION_UUID
    merged["history"] = ["first-version", "second-version"]
    root = _build(object_type, "object-uuid-under-test", "TEST", merged)

    history = root.find("history")
    assert history is not None
    assert [entry.get("versionUuid") for entry in history.findall("historyInfo")] == [
        "first-version",
        "second-version",
        VERSION_UUID,
    ]
    assert root.findtext("versionUuid") == VERSION_UUID
    assert _child_tags(root)[-1] == "history"


@pytest.mark.parametrize(
    ("object_type", "fields"),
    [
        (ObjectType.GROUP, {}),
        (ObjectType.RULES_FOLDER, {}),
        (ObjectType.DOCUMENT_FOLDER, {}),
        (ObjectType.KNOWLEDGE_CENTER, {}),
        (ObjectType.DOCUMENT, {"file_extension": "pdf", "payload": b"bytes"}),
    ],
)
def test_absent_version_uuid_is_minted_fresh_and_never_the_object_uuid(
    object_type: ObjectType,
    fields: dict[str, object],
) -> None:
    object_uuid = "77777777-7777-4777-8777-777777777777"
    first = _build(object_type, object_uuid, "TEST", dict(fields))
    second = _build(object_type, object_uuid, "TEST", dict(fields))

    minted = first.findtext("versionUuid")
    assert minted != object_uuid
    assert UUID4_PATTERN.match(minted)
    assert minted != second.findtext("versionUuid")
    assert first.find("history/historyInfo").get("versionUuid") == minted


def test_version_uuid_equal_to_the_object_uuid_is_rejected() -> None:
    with pytest.raises(ValueError, match="must differ from the object uuid"):
        build_native_collaboration_artifact(
            ObjectType.GROUP,
            "shared-uuid",
            "TEST Group",
            {"version_uuid": "shared-uuid"},
        )


# ---------------------------------------------------------------------------
# Group membership
# ---------------------------------------------------------------------------

def test_group_members_use_user_uuid_elements_never_username(tmp_path: Path) -> None:
    uuid = "88888888-8888-4888-8888-888888888888"
    artifact, payloads = _write_artifact(
        tmp_path,
        ObjectType.GROUP,
        uuid,
        "TEST Users",
        {
            "description": "Assigns viewer permissions",
            "version_uuid": VERSION_UUID,
            "member_users": ["jane.doe"],
            "member_groups": [PARENT_UUID],
            "admin_users": ["Administrator"],
            "admin_groups": [uuid],
            "member_policy": "MEMBERPOLICY_CLOSED",
            "viewing_policy": "VIEWINGPOLICY_LOW",
        },
    )

    root = etree.fromstring(artifact)
    assert payloads == {}
    assert b"<username>" not in artifact
    assert [el.tag for el in root.find("members/users")] == ["userUuid"]
    assert [el.tag for el in root.find("admins/users")] == ["userUuid"]
    assert root.findtext("members/users/userUuid") == "jane.doe"
    assert root.findtext("admins/users/userUuid") == "Administrator"

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(uuid)
    assert isinstance(parsed, Group)
    assert parsed.group_type_uuid == "SYSTEM_GROUP_TYPE_CUSTOM"
    assert parsed.security_map == "SECURITYMAP_PUBLIC"
    assert parsed.member_policy == "MEMBERPOLICY_CLOSED"
    assert parsed.viewing_policy == "VIEWINGPOLICY_LOW"
    assert parsed.member_users == ["jane.doe"]
    assert parsed.member_groups == [PARENT_UUID]
    assert parsed.admin_users == ["Administrator"]
    assert parsed.admin_groups == [uuid]


# ---------------------------------------------------------------------------
# Optional real ACL shape
# ---------------------------------------------------------------------------

def test_role_map_accepts_the_real_acl_group_and_inherit_shape(tmp_path: Path) -> None:
    uuid = "64869106-d692-4685-a3bb-765035376ca2"
    artifact, _ = _write_artifact(
        tmp_path,
        ObjectType.RULES_FOLDER,
        uuid,
        "TEST Rules & Constants",
        {
            "version_uuid": VERSION_UUID,
            "parent_uuid": "SYSTEM_RULES_ROOT",
            "role_map": {
                "readers": {
                    "inherit": False,
                    "groups": ["d9bc815f-a6fd-4a2d-8322-b2e17592cc10"],
                },
                "authors": {"inherit": False},
                "administrators": {
                    "inherit": False,
                    "groups": ["fc5cfc20-da0e-4df4-872b-07603471cb4b"],
                    "users": ["mcpCopilot"],
                },
            },
        },
    )

    root = etree.fromstring(artifact)
    roles = root.findall("roleMap/role")
    assert [role.get("inherit") for role in roles] == [
        "false",
        "false",
        "false",
        "false",
        "false",
        "false",
    ]
    assert root.findtext("roleMap/role[@name='readers']/groups/groupUuid") == (
        "d9bc815f-a6fd-4a2d-8322-b2e17592cc10"
    )
    assert root.findtext("roleMap/role[@name='administrators']/users/userUuid") == (
        "mcpCopilot"
    )

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(uuid)
    assert isinstance(parsed, RulesFolder)
    readers = next(r for r in parsed.security_roles if r.role_name == "readers")
    assert readers.inherit is False
    assert readers.groups == ["d9bc815f-a6fd-4a2d-8322-b2e17592cc10"]


def test_role_map_rejects_unknown_role_names() -> None:
    with pytest.raises(ValueError, match="unknown role names"):
        build_native_collaboration_artifact(
            ObjectType.DOCUMENT_FOLDER,
            "folder-uuid",
            "TEST Folder",
            {"version_uuid": VERSION_UUID, "role_map": {"owners": {}}},
        )


# ---------------------------------------------------------------------------
# Unproven shapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("object_type", "export_dir"),
    [(ObjectType.GROUP_TYPE, "groupType"), (ObjectType.FEED, "feed")],
)
def test_unproven_object_types_refuse_to_emit_guessed_xml(
    object_type: ObjectType,
    export_dir: str,
) -> None:
    assert not (CORPUS_ROOT / export_dir).exists()
    with pytest.raises(ValueError, match="No Appian export sample available for"):
        build_native_collaboration_artifact(
            object_type,
            "unproven-uuid",
            "TEST Unproven",
            {"description": "no sample exists"},
        )


def test_unsupported_object_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported native collaboration object type"):
        build_native_collaboration_artifact(
            ObjectType.INTERFACE,
            "interface-uuid",
            "TEST Interface",
            {},
        )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_document_payload_uses_caller_bytes_in_a_uuid_sibling_directory(
    tmp_path: Path,
) -> None:
    uuid = "_a-00000000-0000-8000-0000-000000000000_2002"
    payload_bytes = b"caller supplied bytes"
    artifact, payloads = _write_artifact(
        tmp_path,
        ObjectType.DOCUMENT,
        uuid,
        "TEST Logo",
        {
            "file_name": "file.png",
            "payload": payload_bytes,
            "version_uuid": VERSION_UUID,
        },
    )

    assert payloads == {f"{uuid}/file.png": payload_bytes}
    assert (tmp_path / "content" / uuid / "file.png").read_bytes() == payload_bytes
    root = etree.fromstring(artifact)
    assert root.findtext("file") == "file.png"

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(uuid)
    assert isinstance(parsed, Document)
    assert parsed.file_name == "file.png"
    assert parsed.file_extension == "png"


def test_document_requires_caller_supplied_payload_bytes() -> None:
    with pytest.raises(ValueError, match="payload bytes"):
        build_native_collaboration_artifact(
            ObjectType.DOCUMENT,
            "document-uuid",
            "TEST Document",
            {"file_extension": "pdf"},
        )


def test_document_requires_a_payload_file_name_or_extension() -> None:
    with pytest.raises(ValueError, match="file_name or file_extension"):
        build_native_collaboration_artifact(
            ObjectType.DOCUMENT,
            "document-uuid",
            "TEST Document",
            {"payload": b""},
        )


def test_document_file_name_rejects_path_separators() -> None:
    with pytest.raises(ValueError, match="path separator"):
        build_native_collaboration_artifact(
            ObjectType.DOCUMENT,
            "document-uuid",
            "TEST Document",
            {"file_name": "../escape.pdf", "payload": b"bytes"},
        )


def test_artifacts_are_byte_identical_for_an_explicit_version_uuid() -> None:
    fields: dict[str, object] = {
        "description": "Native knowledge center",
        "parent_uuid": "SYSTEM_COMMUNITY_ROOT",
        "version_uuid": VERSION_UUID,
    }
    first, first_payloads = build_native_collaboration_artifact(
        ObjectType.KNOWLEDGE_CENTER,
        "99999999-9999-4999-8999-999999999999",
        "TEST Knowledge Center",
        fields,
    )
    second, second_payloads = build_native_collaboration_artifact(
        ObjectType.KNOWLEDGE_CENTER,
        "99999999-9999-4999-8999-999999999999",
        "TEST Knowledge Center",
        fields,
    )

    assert first == second
    assert first_payloads == second_payloads == {}
