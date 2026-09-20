from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.generator.native_ai_writers import (
    APPIAN_NS,
    build_native_ai_xml,
)
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.parser.xml_parser import parse_translation_set_xml

OBJECT_UUID = "22a188da-6272-4ae6-a1f3-cf6aa16f8cfd"
VERSION_UUID = "0c9e4df0-f24e-4f29-910c-13d7bacac344"


def _translation_fields() -> dict[str, object]:
    return {
        "version_uuid": VERSION_UUID,
        "description": "Labels & messages",
        "enabled_locales": ["es", "en-US"],
        "default_locale": "en-US",
        "security_roles": [
            {
                "role_name": "translation_set_administrator",
                "users": [],
                "groups": ["46b0a738-ea79-4c67-af95-e9cd57443c44"],
            }
        ],
    }


def test_build_translation_set_matches_proven_native_shape(tmp_path: Path) -> None:
    data = build_native_ai_xml(
        ObjectType.TRANSLATION_SET,
        OBJECT_UUID,
        "IHUB Translations",
        _translation_fields(),
    )

    root = etree.fromstring(data)
    namespace = {"a": APPIAN_NS}
    translation_set = root.find("translationSet")
    assert root.tag == "translationSetHaul"
    assert root.findtext("versionUuid") == VERSION_UUID
    assert translation_set is not None
    assert translation_set.get(f"{{{APPIAN_NS}}}uuid") == OBJECT_UUID
    assert translation_set.get("name") == "IHUB Translations"
    assert translation_set.findtext("a:description", namespaces=namespace) == "Labels & messages"
    assert translation_set.xpath(
        "a:enabledLocales/a:localeLanguageTag/text()",
        namespaces=namespace,
    ) == ["es", "en-US"]
    assert translation_set.findtext(
        "a:defaultLocale/a:localeLanguageTag",
        namespaces=namespace,
    ) == "en-US"
    assert root.xpath("string(roleMap/role/@name)") == "translation_set_administrator"
    assert root.xpath("string(roleMap/role/groups/groupUuid)") == (
        "46b0a738-ea79-4c67-af95-e9cd57443c44"
    )

    path = tmp_path / "translationSet" / f"{OBJECT_UUID}.xml"
    path.parent.mkdir()
    path.write_bytes(data)
    parsed = parse_translation_set_xml(path)
    assert parsed is not None
    assert parsed.uuid == OBJECT_UUID
    assert parsed.name == "IHUB Translations"
    assert parsed.description == "Labels & messages"
    assert parsed.version_uuid == VERSION_UUID
    assert parsed.enabled_locales == ["es", "en-US"]
    assert parsed.default_locale == "en-US"
    assert parsed.security_roles[0].groups == ["46b0a738-ea79-4c67-af95-e9cd57443c44"]


@pytest.mark.parametrize("object_type", [ObjectType.AI_AGENT, ObjectType.AI_SKILL])
def test_unproven_ai_shapes_fail_explicitly(object_type: ObjectType) -> None:
    with pytest.raises(
        ValueError,
        match=rf"No Appian export sample available for {object_type.value}",
    ):
        build_native_ai_xml(object_type, OBJECT_UUID, "Unsupported", {})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version_uuid", "", "version_uuid must be a non-empty string"),
        ("enabled_locales", [], "enabled_locales must not be empty"),
        ("default_locale", "fr-FR", "default_locale must be present"),
    ],
)
def test_translation_set_rejects_invalid_required_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    fields = _translation_fields()
    fields[field] = value

    with pytest.raises(ValueError, match=message):
        build_native_ai_xml(
            ObjectType.TRANSLATION_SET,
            OBJECT_UUID,
            "IHUB Translations",
            fields,
        )


def test_translation_set_rejects_unproven_fields() -> None:
    fields = _translation_fields()
    fields["agent_prompt"] = "Unsupported"

    with pytest.raises(ValueError, match="unsupported translation_set fields"):
        build_native_ai_xml(
            ObjectType.TRANSLATION_SET,
            OBJECT_UUID,
            "IHUB Translations",
            fields,
        )


def test_translation_set_rejects_unproven_security_user_shape() -> None:
    fields = _translation_fields()
    security_roles = fields["security_roles"]
    assert isinstance(security_roles, list)
    security_roles[0]["users"] = ["appian.user"]

    with pytest.raises(ValueError, match="no user element example"):
        build_native_ai_xml(
            ObjectType.TRANSLATION_SET,
            OBJECT_UUID,
            "IHUB Translations",
            fields,
        )


def _child_names(element: etree._Element) -> tuple[str, ...]:
    return tuple(
        etree.QName(child).localname
        for child in element
        if isinstance(child.tag, str)
    )


def _require_local(parent: etree._Element, name: str) -> etree._Element:
    matches = parent.xpath(f"*[local-name()='{name}']")
    assert matches, f"missing <{name}>"
    return matches[0]


def _element_signature(element: etree._Element) -> tuple[object, ...]:
    return (
        element.tag,
        tuple(element.attrib.items()),
        (element.text or "").strip(),
        tuple(
            _element_signature(child)
            for child in element
            if isinstance(child.tag, str)
        ),
    )


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    override = os.environ.get("APPIAN_SENTINEL_NATIVE_SPEC")
    base = (
        Path(override)
        if override
        else Path(tempfile.gettempdir()) / "AppianSentinel-native-spec"
    )
    if not base.is_dir():
        pytest.skip(f"[WARN] real corpus not available at {base}")
    return base


def test_translation_set_matches_real_corpus_element_for_element(
    corpus_dir: Path,
) -> None:
    reference_path = (
        corpus_dir
        / "translationSet"
        / "22a188da-6272-4ae6-a1f3-cf6aa16f8cfd.xml"
    )
    if not reference_path.is_file():
        pytest.skip(f"[WARN] real corpus sample not available at {reference_path}")
    reference = etree.parse(str(reference_path)).getroot()
    reference_set = _require_local(reference, "translationSet")
    enabled_locales = reference_set.xpath(
        "a:enabledLocales/a:localeLanguageTag/text()",
        namespaces={"a": APPIAN_NS},
    )
    generated = etree.fromstring(
        build_native_ai_xml(
            ObjectType.TRANSLATION_SET,
            reference_set.get(f"{{{APPIAN_NS}}}uuid"),
            reference_set.get("name"),
            {
                "version_uuid": _require_local(reference, "versionUuid").text,
                "description": reference_set.xpath(
                    "string(a:description)", namespaces={"a": APPIAN_NS}
                ),
                "enabled_locales": enabled_locales,
                "default_locale": reference_set.xpath(
                    "string(a:defaultLocale/a:localeLanguageTag)",
                    namespaces={"a": APPIAN_NS},
                ),
                "security_roles": [
                    {
                        "role_name": role.get("name"),
                        "users": [],
                        "groups": role.xpath(
                            "*[local-name()='groups']/*[local-name()='groupUuid']/text()"
                        ),
                    }
                    for role in _require_local(reference, "roleMap")
                ],
            },
        )
    )

    assert generated.tag == reference.tag == "translationSetHaul"
    assert generated.nsmap == reference.nsmap
    assert _child_names(generated) == _child_names(reference)
    generated_set = _require_local(generated, "translationSet")
    assert generated_set.tag == reference_set.tag
    assert dict(generated_set.attrib) == dict(reference_set.attrib)
    assert _child_names(generated_set) == _child_names(reference_set)
    assert _element_signature(generated_set) == _element_signature(reference_set)
    assert _child_names(_require_local(generated, "roleMap")) == _child_names(
        _require_local(reference, "roleMap")
    )
    assert _require_local(
        _require_local(generated, "history"), "historyInfo"
    ).get("versionUuid") == _require_local(reference, "versionUuid").text
