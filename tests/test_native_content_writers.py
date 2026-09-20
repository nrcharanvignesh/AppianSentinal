from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.generator.native_content_writers import (
    build_native_content_xml,
)
from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE
from appian_sentinel.parser.xml_parser import parse_appian_xml

UUID = "11111111-2222-4333-8444-555555555555"
VERSION_UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
NAME = "APP_Native_Object"
DEFINITION = "a!localVariables(local!text: \"A & B\", local!text)"


@pytest.mark.parametrize(
    ("object_type", "fields", "recovered_attribute", "recovered_value"),
    [
        (
            ObjectType.EXPRESSION_RULE,
            {
                "definition": DEFINITION,
                "rule_inputs": [{"name": "value", "type_name": "string"}],
            },
            "definition",
            DEFINITION,
        ),
        (
            ObjectType.INTERFACE,
            {
                "definition": DEFINITION,
                "rule_inputs": [{"name": "label", "type_name": "string"}],
            },
            "definition",
            DEFINITION,
        ),
        (
            ObjectType.CONSTANT,
            {
                "value": "A & B",
                "value_type": "string",
                "value_type_namespace": "http://www.w3.org/2001/XMLSchema",
            },
            "value",
            "A & B",
        ),
        (
            ObjectType.DECISION,
            {
                "definition": DEFINITION,
                "rule_inputs": [{"name": "amount", "type_name": "decimal"}],
                "output_metadata": [
                    {
                        "output_id": "1",
                        "name_ref": "approved",
                        "type_name": "{http://www.w3.org/2001/XMLSchema}boolean",
                    }
                ],
                "hit_policy": "UNIQUE",
            },
            "definition",
            DEFINITION,
        ),
        (
            ObjectType.OUTBOUND_INTEGRATION,
            {
                "definition": DEFINITION,
                "connected_system_uuid": "connected-system-uuid",
                "http_method": "POST",
                "integration_type": "system.http",
            },
            "definition",
            DEFINITION,
        ),
        (
            ObjectType.WEB_API,
            {
                "definition": DEFINITION,
                "url_alias": "native-object",
                "http_method": "POST",
                "request_body_type": "JSON",
            },
            "definition",
            DEFINITION,
        ),
        (
            ObjectType.CONNECTED_SYSTEM,
            {
                "base_url": "https://example.invalid",
                "auth_type": "None",
                "system_type": "system.http",
            },
            "base_url",
            "https://example.invalid",
        ),
    ],
)
def test_native_xml_parses_from_official_export_directory(
    tmp_path: Path,
    object_type: ObjectType,
    fields: dict[str, object],
    recovered_attribute: str,
    recovered_value: str,
) -> None:
    fields["version_uuid"] = VERSION_UUID
    xml_bytes = build_native_content_xml(object_type, UUID, NAME, fields)

    etree.fromstring(xml_bytes)
    export_directory = CAPABILITY_BY_TYPE[object_type].export_dir
    xml_path = tmp_path / export_directory / f"{UUID}.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_bytes(xml_bytes)

    parsed = parse_appian_xml(xml_path)

    assert parsed is not None
    assert parsed.object_type == object_type
    assert parsed.uuid == UUID
    assert parsed.name == NAME
    if object_type != ObjectType.EVENT_CONSUMER:
        assert parsed.version_uuid == VERSION_UUID
    assert getattr(parsed, recovered_attribute) == recovered_value


def test_rule_input_round_trips_through_existing_parser(tmp_path: Path) -> None:
    xml_path = tmp_path / "content" / f"{UUID}.xml"
    xml_path.parent.mkdir()
    xml_path.write_bytes(
        build_native_content_xml(
            ObjectType.EXPRESSION_RULE,
            UUID,
            NAME,
            {
                "rule_inputs": [
                    {
                        "name": "items",
                        "type_name": "string",
                        "type_namespace": "http://www.w3.org/2001/XMLSchema",
                        "is_list": True,
                    }
                ]
            },
        )
    )

    parsed = parse_appian_xml(xml_path)

    assert parsed is not None
    assert parsed.rule_inputs[0].name == "items"  # type: ignore[attr-defined]
    assert parsed.rule_inputs[0].type_name == "string"  # type: ignore[attr-defined]
    assert parsed.rule_inputs[0].is_list is True  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "object_type",
    [
        ObjectType.RECORD_TYPE,
        ObjectType.PROCESS_MODEL,
        ObjectType.SITE,
    ],
)
def test_unsupported_types_raise_value_error(object_type: ObjectType) -> None:
    with pytest.raises(ValueError, match="Unsupported native object type"):
        build_native_content_xml(object_type, UUID, NAME, {})


def test_event_consumer_refuses_unproven_shape() -> None:
    with pytest.raises(ValueError, match="No Appian export sample available for event_consumer"):
        build_native_content_xml(ObjectType.EVENT_CONSUMER, UUID, NAME, {})


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


CONTENT_REFERENCES = {
    ObjectType.EXPRESSION_RULE: "0021b392-9971-4af2-887f-755435c2b72f.xml",
    ObjectType.INTERFACE: "98bdd206-224e-44ff-b875-73dbcf736f2e.xml",
    ObjectType.CONSTANT: "_a-0000e467-a139-8000-9ba4-011c48011c48_17548.xml",
    ObjectType.DECISION: "204de581-2818-4cfd-8d4d-dec12001fe6b.xml",
    ObjectType.OUTBOUND_INTEGRATION: "2ab45f98-34c5-4ca7-b585-9b00c7adcd72.xml",
}


def _generated_for_shape(object_type: ObjectType) -> etree._Element:
    fields: dict[str, object] = {
        "version_uuid": VERSION_UUID,
        "parent_uuid": "39e1a467-3f61-4a9c-a6a7-633d868e45d9",
    }
    if object_type == ObjectType.DECISION:
        fields.update(
            {
                "rule_inputs": [{"name": "input1", "type_name": "string"}],
                "output_metadata": [
                    {
                        "output_id": "1",
                        "name_ref": "output",
                        "type_name": "{http://www.appian.com/ae/types/2009}Text",
                    }
                ],
            }
        )
    return etree.fromstring(build_native_content_xml(object_type, UUID, NAME, fields))


@pytest.mark.parametrize("object_type", tuple(CONTENT_REFERENCES))
def test_content_type_matches_real_corpus_skeleton(
    corpus_dir: Path,
    object_type: ObjectType,
) -> None:
    reference_path = corpus_dir / "content" / CONTENT_REFERENCES[object_type]
    if not reference_path.is_file():
        pytest.skip(f"[WARN] real corpus sample not available at {reference_path}")
    reference = etree.parse(str(reference_path)).getroot()
    generated = _generated_for_shape(object_type)
    element_name = {
        ObjectType.EXPRESSION_RULE: "rule",
        ObjectType.INTERFACE: "interface",
        ObjectType.CONSTANT: "constant",
        ObjectType.DECISION: "decision",
        ObjectType.OUTBOUND_INTEGRATION: "outboundIntegration",
    }[object_type]

    assert generated.tag == reference.tag == "contentHaul"
    assert generated.nsmap == reference.nsmap
    assert _child_names(generated) == _child_names(reference)
    assert _child_names(_require_local(generated, element_name)) == _child_names(
        _require_local(reference, element_name)
    )
    assert _child_names(_require_local(generated, "roleMap")) == _child_names(
        _require_local(reference, "roleMap")
    )
    assert _require_local(
        _require_local(generated, "history"), "historyInfo"
    ).get("versionUuid") == VERSION_UUID


def test_outbound_integration_dictionaries_match_real_corpus(
    corpus_dir: Path,
) -> None:
    reference_path = corpus_dir / "content" / CONTENT_REFERENCES[
        ObjectType.OUTBOUND_INTEGRATION
    ]
    if not reference_path.is_file():
        pytest.skip(f"[WARN] real corpus sample not available at {reference_path}")
    reference = _require_local(
        etree.parse(str(reference_path)).getroot(), "outboundIntegration"
    )
    generated = _require_local(
        _generated_for_shape(ObjectType.OUTBOUND_INTEGRATION),
        "outboundIntegration",
    )

    for container_name in (
        "sharedConfigParameters",
        "configParameters",
        "integrationOutputs",
    ):
        generated_dictionary = _require_local(
            _require_local(generated, container_name), "Dictionary"
        )
        reference_dictionary = _require_local(
            _require_local(reference, container_name), "Dictionary"
        )
        assert generated_dictionary.tag == reference_dictionary.tag
        assert generated_dictionary.nsmap == reference_dictionary.nsmap
        assert _child_names(generated_dictionary) == _child_names(reference_dictionary)
        assert [dict(child.attrib) for child in generated_dictionary] == [
            dict(child.attrib) for child in reference_dictionary
        ]


@pytest.mark.parametrize(
    ("object_type", "directory", "filename", "element_name"),
    [
        (
            ObjectType.WEB_API,
            "webApi",
            "0d2fcb75-80a5-4af5-a51d-4be585545e5a.xml",
            "webApi",
        ),
        (
            ObjectType.CONNECTED_SYSTEM,
            "connectedSystem",
            "_a-0000ef9a-a4f8-8000-9bbc-011c48011c48_756395.xml",
            "connectedSystem",
        ),
    ],
)
def test_standalone_content_type_matches_real_corpus(
    corpus_dir: Path,
    object_type: ObjectType,
    directory: str,
    filename: str,
    element_name: str,
) -> None:
    reference_path = corpus_dir / directory / filename
    if not reference_path.is_file():
        pytest.skip(f"[WARN] real corpus sample not available at {reference_path}")
    reference = etree.parse(str(reference_path)).getroot()
    fields: dict[str, object] = {"version_uuid": VERSION_UUID}
    if object_type == ObjectType.CONNECTED_SYSTEM:
        fields.update({"base_url": "https://example.invalid", "auth_type": "None"})
    generated = etree.fromstring(
        build_native_content_xml(object_type, UUID, NAME, fields)
    )

    assert generated.tag == reference.tag
    assert generated.nsmap == reference.nsmap
    assert _child_names(generated) == _child_names(reference)
    assert _child_names(_require_local(generated, element_name)) == _child_names(
        _require_local(reference, element_name)
    )
    assert [
        (role.get("name"), tuple(role.keys()), _child_names(role))
        for role in _require_local(generated, "roleMap")
    ] == [
        (role.get("name"), tuple(role.keys()), _child_names(role))
        for role in _require_local(reference, "roleMap")
    ]


def test_event_consumer_has_no_corpus_directory(corpus_dir: Path) -> None:
    assert not (corpus_dir / "eventConsumer").is_dir()


XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

CONNECTED_SYSTEM_AUTH_REFERENCES = (
    (
        "None",
        "_a-0000ef9a-a4f8-8000-9bbc-011c48011c48_756395.xml",
        {"auth_type": "None"},
    ),
    (
        "API Key",
        "_a-0000ec3a-acb2-8000-9ba6-011c48011c48_78136.xml",
        {"auth_type": "API Key"},
    ),
    (
        "OAuth Client Credentials Grant",
        "_a-0000ec3a-acb2-8000-9ba6-011c48011c48_98866.xml",
        {"auth_type": "OAuth Client Credentials Grant"},
    ),
)


@pytest.mark.parametrize(
    ("auth_type", "filename", "fields"),
    CONNECTED_SYSTEM_AUTH_REFERENCES,
)
def test_connected_system_auth_details_match_corpus_auth_type(
    corpus_dir: Path,
    auth_type: str,
    filename: str,
    fields: dict[str, object],
) -> None:
    reference_path = corpus_dir / "connectedSystem" / filename
    if not reference_path.is_file():
        pytest.skip(f"[WARN] real corpus sample not available at {reference_path}")
    reference = _require_local(
        etree.parse(str(reference_path)).getroot(), "connectedSystem"
    )
    generated = _require_local(
        etree.fromstring(
            build_native_content_xml(
                ObjectType.CONNECTED_SYSTEM,
                UUID,
                NAME,
                {"version_uuid": VERSION_UUID, **fields},
            )
        ),
        "connectedSystem",
    )
    generated_details = _require_local(
        _require_local(generated, "sharedConfigParameters"), "Dictionary"
    ).xpath("*[local-name()='authDetails']")[0]
    reference_details = _require_local(
        _require_local(reference, "sharedConfigParameters"), "Dictionary"
    ).xpath("*[local-name()='authDetails']")[0]

    assert generated.xpath("string(.//*[local-name()='authType'])") == auth_type
    assert generated_details.get(XSI_TYPE) == reference_details.get(XSI_TYPE)
    assert _child_names(generated_details) == _child_names(reference_details)
    assert [child.get(XSI_TYPE) for child in generated_details] == [
        child.get(XSI_TYPE) for child in reference_details
    ]


def test_web_api_receive_documents_folder_matches_corpus_order(
    corpus_dir: Path,
) -> None:
    reference_path = corpus_dir / "webApi" / "29d189de-f372-4dc0-bae2-b5757eca31ad.xml"
    if not reference_path.is_file():
        pytest.skip(f"[WARN] real corpus sample not available at {reference_path}")
    reference = _require_local(etree.parse(str(reference_path)).getroot(), "webApi")
    generated = _require_local(
        etree.fromstring(
            build_native_content_xml(
                ObjectType.WEB_API,
                UUID,
                NAME,
                {
                    "version_uuid": VERSION_UUID,
                    "receive_documents_folder_uuid": (
                        "_a-0000ed6a-1f0e-8000-9bac-011c48011c48_578539"
                    ),
                },
            )
        ),
        "webApi",
    )

    assert _child_names(generated) == _child_names(reference)
    assert generated.xpath("string(*[local-name()='receiveDocumentsFolderUuid'])") == (
        "_a-0000ed6a-1f0e-8000-9bac-011c48011c48_578539"
    )
