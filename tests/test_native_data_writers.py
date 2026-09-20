from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.generator.native_data_writers import (
    APPIAN_NS,
    DATA_STORE_ROLE_NAMES,
    RECORD_TYPE_ROLE_NAMES,
    XSD_NS,
    build_native_data_artifact,
)
from appian_sentinel.models.appian_objects import DataStore, DataType, ObjectType, RecordType
from appian_sentinel.parser.codebase_map import build_codebase_map

DATA_STORE_UUID = "_a-11111111-1111-8000-1111-111111111111_100001"
RECORD_TYPE_UUID = "11111111-1111-4111-8111-111111111111"


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

def _child_names(element: etree._Element) -> tuple[str, ...]:
    """Return the ordered local names of the element children, skipping comments."""
    return tuple(
        etree.QName(child).localname
        for child in element
        if isinstance(child.tag, str)
    )


def _find_local(parent: etree._Element, name: str) -> etree._Element | None:
    found = parent.xpath(f"*[local-name()='{name}']")
    return found[0] if found else None


def _require_local(parent: etree._Element, name: str) -> etree._Element:
    element = _find_local(parent, name)
    assert element is not None, f"missing <{name}>"
    return element


def _findall_local(parent: etree._Element, name: str) -> list[etree._Element]:
    return list(parent.xpath(f"*[local-name()='{name}']"))


def _element_by_name(sequence: etree._Element, name: str) -> etree._Element:
    for element in _findall_local(sequence, "element"):
        if element.get("name") == name:
            return element
    raise AssertionError(f"no <element name={name}>")


def _jpa_text(element: etree._Element) -> str:
    return element.xpath(
        "string(*[local-name()='annotation']"
        "/*[local-name()='appinfo'][@source='appian.jpa'])"
    )


def _source_config_shape(source_config: etree._Element) -> tuple[str, ...]:
    """Return child order with the repeated <field> block collapsed to one entry."""
    shape: list[str] = []
    for child_name in _child_names(source_config):
        if child_name == "field" and shape and shape[-1] == "field":
            continue
        shape.append(child_name)
    return tuple(shape)


def _texts(parent: etree._Element, names: tuple[str, ...]) -> dict[str, str]:
    return {name: parent.xpath(f"string(*[local-name()='{name}'])") for name in names}


# ---------------------------------------------------------------------------
# Real corpus access
# ---------------------------------------------------------------------------

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


def _datatype_roots(corpus_dir: Path) -> list[etree._Element]:
    return [
        etree.parse(str(path)).getroot()
        for path in sorted((corpus_dir / "datatype").glob("*.xsd"))
    ]


def _complex_type(root: etree._Element) -> etree._Element:
    return _require_local(root, "complexType")


def _is_jpa(root: etree._Element) -> bool:
    return bool(root.xpath(".//*[local-name()='appinfo'][@source='appian.jpa']"))


@pytest.fixture(scope="session")
def reference_jpa_type(corpus_dir: Path) -> etree._Element:
    """Return the real JPA-mapped CDT the generated fixture data mirrors.

    The generated type reuses the taskId/taskStatus columns of that file so the
    annotation text can be compared literally, and the file also carries an
    element with no annotation at all.
    """
    for root in _datatype_roots(corpus_dir):
        if not _is_jpa(root):
            continue
        sequence = _require_local(_complex_type(root), "sequence")
        names = {element.get("name") for element in _findall_local(sequence, "element")}
        bare = [
            element
            for element in _findall_local(sequence, "element")
            if len(element) == 0
        ]
        if bare and {"taskId", "taskStatus"} <= names:
            return root
    pytest.skip("[WARN] no JPA CDT with taskId/taskStatus and a bare element in corpus")


@pytest.fixture(scope="session")
def reference_plain_type(corpus_dir: Path) -> etree._Element:
    for root in _datatype_roots(corpus_dir):
        if not _is_jpa(root):
            return root
    pytest.skip("[WARN] no non-JPA CDT in corpus")


@pytest.fixture(scope="session")
def reference_data_store(corpus_dir: Path) -> etree._Element:
    paths = sorted((corpus_dir / "dataStore").glob("*.xml"))
    if not paths:
        pytest.skip("[WARN] no dataStore files in corpus")
    return etree.parse(str(paths[0])).getroot()


@pytest.fixture(scope="session")
def reference_record_types(corpus_dir: Path) -> list[etree._Element]:
    roots: list[etree._Element] = []
    for path in sorted((corpus_dir / "recordType").glob("*.xml")):
        root = etree.parse(str(path)).getroot()
        if root.xpath(
            "//*[local-name()='sourceConfiguration']/*[local-name()='field']"
        ):
            roots.append(root)
    if not roots:
        pytest.skip("[WARN] no recordType files with fields in corpus")
    return roots


@pytest.fixture(scope="session")
def reference_haul_shapes(
    reference_record_types: list[etree._Element],
) -> set[tuple[str, ...]]:
    return {_child_names(root) for root in reference_record_types}


@pytest.fixture(scope="session")
def reference_source_config_shapes(
    reference_record_types: list[etree._Element],
) -> set[tuple[str, ...]]:
    return {
        _source_config_shape(source_config)
        for root in reference_record_types
        for source_config in root.xpath("//*[local-name()='sourceConfiguration']")
    }


@pytest.fixture(scope="session")
def reference_fields(
    reference_record_types: list[etree._Element],
) -> list[etree._Element]:
    return [
        field
        for root in reference_record_types
        for field in root.xpath(
            "//*[local-name()='sourceConfiguration']/*[local-name()='field']"
        )
    ]


# ---------------------------------------------------------------------------
# Generated output helpers
# ---------------------------------------------------------------------------

def _write_artifact(
    export_dir: Path,
    directory: str,
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[str, bytes]:
    filename, artifact = build_native_data_artifact(
        object_type,
        uuid,
        name,
        fields,
    )
    target = export_dir / directory / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(artifact)
    return filename, artifact


def _jpa_type_fields() -> dict[str, object]:
    """Mirror the real IHUB_TASK shape: keyed int column plus a bare element."""
    return {
        "namespace": "urn:com:appian:types:TEST",
        "table_name": "IHUB_TASK",
        "version_uuid": "0001eff8-6a6f-8000-0787-7f0000014e7a",
        "fields": [
            {
                "name": "taskId",
                "type": "Integer",
                "source_field_name": "TASK_ID",
                "source_field_type": "INT",
                "is_primary_key": True,
            },
            {
                "name": "taskStatus",
                "type": "Integer",
                "source_field_name": "TASK_STATUS",
                "source_field_type": "INT",
            },
            {
                "name": "isDelegate",
                "type": "Boolean",
                "omit_annotation": True,
            },
        ],
    }


def _build_data_type(fields: dict[str, object]) -> etree._Element:
    _, artifact = build_native_data_artifact(
        ObjectType.DATA_TYPE,
        "version-data-type-1",
        "TEST_TASK",
        fields,
    )
    return etree.fromstring(artifact)


def _record_type_fields() -> dict[str, object]:
    return {
        "plural_name": "Orders",
        "source_uuid": "Appian.TEST_ORDER@jdbc/Appian",
        "source_type": "RDBMS_TABLE",
        "friendly_name": "TEST_ORDER",
        "fields": [
            {
                "name": "orderId",
                "display_name": "Order Id",
                "type": f"{{{APPIAN_NS}}}Integer",
                "source_field_name": "ORDER_ID",
                "source_field_type": "INTEGER",
                "is_primary_key": True,
                "is_unique": True,
            },
            {
                "name": "status",
                "display_name": "Status",
                "source_field_name": "STATUS",
                "source_field_type": "VARCHAR(32)",
            },
        ],
    }


def _build_record_type(fields: dict[str, object] | None = None) -> etree._Element:
    _, artifact = build_native_data_artifact(
        ObjectType.RECORD_TYPE,
        RECORD_TYPE_UUID,
        "TEST Order",
        fields if fields is not None else _record_type_fields(),
    )
    return etree.fromstring(artifact)


def _build_data_store(fields: dict[str, object] | None = None) -> etree._Element:
    payload: dict[str, object] = {
        "description": "Native data store",
        "data_source_key": "jdbc/Appian",
        "auto_update_schema": True,
        "is_published": True,
        "entities": [
            {"name": "TEST_ORDER", "type": "{urn:com:appian:types:TEST}TEST_ORDER"}
        ],
    }
    if fields is not None:
        payload.update(fields)
    _, artifact = build_native_data_artifact(
        ObjectType.DATA_STORE,
        DATA_STORE_UUID,
        "TEST Data Store",
        payload,
    )
    return etree.fromstring(artifact)


# ---------------------------------------------------------------------------
# Round trip through the real parser
# ---------------------------------------------------------------------------

def test_data_type_uses_qualified_identity_filename_and_xsd_namespaces(
    tmp_path: Path,
) -> None:
    namespace = "urn:com:appian:types:TEST"
    identity = f"{{{namespace}}}TEST_ORDER"
    filename, artifact = _write_artifact(
        tmp_path,
        "datatype",
        ObjectType.DATA_TYPE,
        "version-data-type-1",
        "TEST_ORDER",
        {
            "namespace": namespace,
            "version_uuid": "version-data-type-1",
            "table_name": "TEST_ORDER",
            "fields": [
                {
                    "name": "orderId",
                    "type": "Integer",
                    "source_field_name": "ORDER_ID",
                    "source_field_type": "INTEGER",
                    "is_primary_key": True,
                    "is_unique": True,
                }
            ],
        },
    )

    assert filename == "%7Burn%3Acom%3Aappian%3Atypes%3ATEST%7DTEST_ORDER.xsd"
    root = etree.fromstring(artifact)
    assert root.tag == f"{{{XSD_NS}}}schema"
    assert root.nsmap["xsd"] == XSD_NS
    assert root.nsmap["tns"] == namespace
    assert root.get("targetNamespace") == namespace
    assert root.xpath(
        "string(xsd:complexType/xsd:annotation/xsd:appinfo"
        "/*[local-name()='Metadata']/*[local-name()='versionUuid'])",
        namespaces={"xsd": XSD_NS},
    ) == "version-data-type-1"

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(identity)
    assert isinstance(parsed, DataType)
    assert parsed.name == "TEST_ORDER"
    assert parsed.namespace == namespace
    assert parsed.table_name == "TEST_ORDER"
    assert parsed.fields[0].name == "orderId"
    assert parsed.fields[0].is_primary_key is True
    assert parsed.fields[0].is_unique is True
    assert parsed.file_path == f"datatype/{filename}"


def test_data_type_accepts_qualified_uuid_as_parser_identity(tmp_path: Path) -> None:
    identity = "{urn:com:appian:types:TEST}TEST_CUSTOMER"
    filename, _ = _write_artifact(
        tmp_path,
        "datatype",
        ObjectType.DATA_TYPE,
        identity,
        "TEST_CUSTOMER",
        {"fields": []},
    )

    codebase = build_codebase_map(tmp_path)
    assert filename == "%7Burn%3Acom%3Aappian%3Atypes%3ATEST%7DTEST_CUSTOMER.xsd"
    assert codebase.get_object(identity) is not None


def test_data_store_round_trips_with_stable_key(tmp_path: Path) -> None:
    filename, _ = _write_artifact(
        tmp_path,
        "dataStore",
        ObjectType.DATA_STORE,
        DATA_STORE_UUID,
        "TEST Data Store",
        {
            "description": "Native data store",
            "data_source_key": "jdbc/Appian",
            "auto_update_schema": True,
            "is_published": True,
            "entities": [
                {
                    "name": "TEST_ORDER",
                    "type": "{urn:com:appian:types:TEST}TEST_ORDER",
                }
            ],
        },
    )

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(DATA_STORE_UUID)
    assert filename == f"{DATA_STORE_UUID}.xml"
    assert isinstance(parsed, DataStore)
    assert parsed.name == "TEST Data Store"
    assert parsed.data_source_key == "jdbc/Appian"
    assert parsed.auto_update_schema is True
    assert parsed.is_published is True
    assert parsed.entities[0].uuid
    assert parsed.entities[0].type == "{urn:com:appian:types:TEST}TEST_ORDER"
    assert [role.role_name for role in parsed.security_roles] == list(
        DATA_STORE_ROLE_NAMES
    )


def test_record_type_round_trips_with_deterministic_nested_uuids(
    tmp_path: Path,
) -> None:
    object_fields = _record_type_fields()
    filename, first_artifact = _write_artifact(
        tmp_path,
        "recordType",
        ObjectType.RECORD_TYPE,
        RECORD_TYPE_UUID,
        "TEST Order",
        object_fields,
    )
    second_filename, second_artifact = build_native_data_artifact(
        ObjectType.RECORD_TYPE,
        RECORD_TYPE_UUID,
        "TEST Order",
        object_fields,
    )

    nested_xpath = (
        "//*[local-name()='sourceConfiguration']"
        "/*[local-name()='field']/*[local-name()='uuid']/text()"
        " | //*[local-name()='sourceConfiguration']/*[local-name()='uuid']/text()"
    )
    first_nested = etree.fromstring(first_artifact).xpath(nested_xpath)
    second_nested = etree.fromstring(second_artifact).xpath(nested_xpath)
    assert filename == second_filename == f"{RECORD_TYPE_UUID}.xml"
    assert first_nested == second_nested
    assert len(first_nested) == 3
    assert len(set(first_nested)) == 3

    codebase = build_codebase_map(tmp_path)
    parsed = codebase.get_object(RECORD_TYPE_UUID)
    assert isinstance(parsed, RecordType)
    assert parsed.name == "TEST Order"
    assert parsed.plural_name == "Orders"
    assert parsed.source_uuid == "Appian.TEST_ORDER@jdbc/Appian"
    assert [field.uuid for field in parsed.fields] == first_nested[:2]
    assert parsed.fields[0].is_primary_key is True
    assert parsed.fields[1].source_field_name == "STATUS"
    assert [role.role_name for role in parsed.security_roles] == list(
        RECORD_TYPE_ROLE_NAMES
    )


def test_record_type_preserves_supplied_source_configuration_uuid() -> None:
    fields = _record_type_fields()
    fields["source_configuration_uuid"] = "0a928a54-2424-49fb-a467-a3e1e55b5280"

    source_config = _require_local(
        _require_local(_build_record_type(fields), "recordType"),
        "sourceConfiguration",
    )

    assert _require_local(source_config, "uuid").text == (
        "0a928a54-2424-49fb-a467-a3e1e55b5280"
    )


def test_unsupported_object_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported native data object type"):
        build_native_data_artifact(
            ObjectType.INTERFACE,
            "interface-uuid",
            "TEST Interface",
            {},
        )


# ---------------------------------------------------------------------------
# Data type fidelity against the real corpus
# ---------------------------------------------------------------------------

def test_jpa_data_type_matches_corpus_annotation_layout(
    reference_jpa_type: etree._Element,
) -> None:
    generated_ct = _complex_type(_build_data_type(_jpa_type_fields()))
    reference_ct = _complex_type(reference_jpa_type)

    assert _child_names(generated_ct) == _child_names(reference_ct)
    generated_annotation = _require_local(generated_ct, "annotation")
    reference_annotation = _require_local(reference_ct, "annotation")
    assert [
        appinfo.get("source")
        for appinfo in _findall_local(generated_annotation, "appinfo")
    ] == [
        appinfo.get("source")
        for appinfo in _findall_local(reference_annotation, "appinfo")
    ]
    generated_metadata = generated_annotation.xpath(
        ".//*[local-name()='Metadata']"
    )[0]
    reference_metadata = reference_annotation.xpath(
        ".//*[local-name()='Metadata']"
    )[0]
    assert _child_names(generated_metadata) == _child_names(reference_metadata)
    assert _child_names(_require_local(generated_metadata, "history")) == ("historyInfo",)


def test_jpa_data_type_history_matches_version_uuid() -> None:
    root = _build_data_type(_jpa_type_fields())

    metadata = root.xpath(".//*[local-name()='Metadata']")[0]
    version_uuid = _require_local(metadata, "versionUuid").text
    history_info = _require_local(_require_local(metadata, "history"), "historyInfo")

    assert version_uuid == "0001eff8-6a6f-8000-0787-7f0000014e7a"
    assert history_info.get("versionUuid") == version_uuid


def test_jpa_data_type_key_column_matches_corpus_text(
    reference_jpa_type: etree._Element,
) -> None:
    generated_sequence = _require_local(
        _complex_type(_build_data_type(_jpa_type_fields())), "sequence"
    )
    reference_sequence = _require_local(_complex_type(reference_jpa_type), "sequence")
    generated_key = _element_by_name(generated_sequence, "taskId")
    reference_key = _element_by_name(reference_sequence, "taskId")

    # Same column inputs must produce the exact real annotation text.
    assert _jpa_text(generated_key) == _jpa_text(reference_key)
    assert _jpa_text(generated_key) == (
        '@Id @GeneratedValue @Column(name="TASK_ID", nullable=false, '
        'unique=true, columnDefinition="INT")'
    )
    assert list(generated_key.keys()) == list(reference_key.keys())
    assert list(generated_key.keys()) == ["name", "nillable", "type"]
    assert generated_key.get("type") == reference_key.get("type") == "xsd:int"


def test_jpa_data_type_plain_column_matches_corpus_text(
    reference_jpa_type: etree._Element,
) -> None:
    generated_sequence = _require_local(
        _complex_type(_build_data_type(_jpa_type_fields())), "sequence"
    )
    reference_sequence = _require_local(_complex_type(reference_jpa_type), "sequence")

    assert _jpa_text(_element_by_name(generated_sequence, "taskStatus")) == _jpa_text(
        _element_by_name(reference_sequence, "taskStatus")
    )
    assert _jpa_text(_element_by_name(generated_sequence, "taskStatus")) == (
        '@Column(name="TASK_STATUS", columnDefinition="INT")'
    )


def test_jpa_data_type_permits_element_without_annotation(
    reference_jpa_type: etree._Element,
) -> None:
    generated_sequence = _require_local(
        _complex_type(_build_data_type(_jpa_type_fields())), "sequence"
    )
    reference_sequence = _require_local(_complex_type(reference_jpa_type), "sequence")
    generated_bare = _element_by_name(generated_sequence, "isDelegate")
    reference_bare = [
        element
        for element in _findall_local(reference_sequence, "element")
        if len(element) == 0
    ][0]

    assert len(generated_bare) == 0
    assert list(generated_bare.keys()) == list(reference_bare.keys())


def test_jpa_data_type_unique_column_keeps_unique_without_key() -> None:
    fields: dict[str, object] = {
        "namespace": "urn:com:appian:types:TEST",
        "table_name": "TEST_ORDER",
        "fields": [
            {
                "name": "orderRef",
                "source_field_name": "ORDER_REF",
                "source_field_type": "VARCHAR(32)",
                "is_unique": True,
            }
        ],
    }

    sequence = _require_local(_complex_type(_build_data_type(fields)), "sequence")

    assert _jpa_text(_element_by_name(sequence, "orderRef")) == (
        '@Column(name="ORDER_REF", unique=true, columnDefinition="VARCHAR(32)")'
    )


def test_non_jpa_data_type_matches_corpus_plain_schema(
    reference_plain_type: etree._Element,
) -> None:
    fields: dict[str, object] = {
        "namespace": "urn:appian:ps:test",
        "version_uuid": "0000ebe7-0a67-8000-fcb5-7f0000014e7a",
        "fields": [
            {"name": "name", "type": "Text"},
            {"name": "value", "type": "Text"},
        ],
    }
    generated_ct = _complex_type(_build_data_type(fields))
    reference_ct = _complex_type(reference_plain_type)

    generated_annotation = _require_local(generated_ct, "annotation")
    reference_annotation = _require_local(reference_ct, "annotation")
    assert [
        appinfo.get("source")
        for appinfo in _findall_local(generated_annotation, "appinfo")
    ] == [
        appinfo.get("source")
        for appinfo in _findall_local(reference_annotation, "appinfo")
    ] == [APPIAN_NS]
    generated_sequence = _require_local(generated_ct, "sequence")
    reference_sequence = _require_local(reference_ct, "sequence")
    generated_element = _findall_local(generated_sequence, "element")[0]
    reference_element = _findall_local(reference_sequence, "element")[0]
    assert list(generated_element.keys()) == list(reference_element.keys())
    assert list(generated_element.keys()) == ["minOccurs", "name", "type"]
    assert generated_element.get("minOccurs") == "0"
    assert generated_element.get("nillable") is None
    for element in _findall_local(generated_sequence, "element"):
        assert len(element) == 0
    assert not _build_data_type(fields).xpath(
        "//*[local-name()='appinfo'][@source='appian.jpa']"
    )


def test_non_jpa_mode_can_be_requested_with_a_table_name() -> None:
    fields: dict[str, object] = {
        "namespace": "urn:appian:ps:test",
        "table_name": "TEST_ORDER",
        "jpa": False,
        "fields": [{"name": "name", "type": "Text"}],
    }
    root = _build_data_type(fields)

    assert not root.xpath("//*[local-name()='appinfo'][@source='appian.jpa']")
    element = _findall_local(
        _require_local(_complex_type(root), "sequence"), "element"
    )[0]
    assert element.get("minOccurs") == "0"


# ---------------------------------------------------------------------------
# Data store fidelity against the real corpus
# ---------------------------------------------------------------------------

def test_data_store_matches_corpus_child_order(
    reference_data_store: etree._Element,
) -> None:
    generated = _build_data_store()

    assert generated.tag == reference_data_store.tag == "dataStoreHaul"
    assert generated.nsmap == reference_data_store.nsmap == {"a": APPIAN_NS}
    assert _child_names(generated) == _child_names(reference_data_store)
    assert _child_names(_require_local(generated, "dataStore")) == _child_names(
        _require_local(reference_data_store, "dataStore")
    )
    assert _child_names(
        _require_local(_require_local(generated, "dataStore"), "entities")
    ) == ("entity",)


def test_data_store_adapting_explicit_sql_names_default_matches_corpus(
    reference_data_store: etree._Element,
) -> None:
    generated_ds = _require_local(_build_data_store(), "dataStore")
    reference_ds = _require_local(reference_data_store, "dataStore")

    assert _require_local(generated_ds, "adaptingExplicitSqlNames").text == (
        _require_local(reference_ds, "adaptingExplicitSqlNames").text
    )
    assert _require_local(generated_ds, "adaptingExplicitSqlNames").text == "false"
    assert _require_local(
        _build_data_store({"adapting_explicit_sql_names": True}), "dataStore"
    ).xpath("string(*[local-name()='adaptingExplicitSqlNames'])") == "true"


def test_data_store_role_map_matches_corpus_roles(
    reference_data_store: etree._Element,
) -> None:
    generated_roles = _findall_local(_require_local(_build_data_store(), "roleMap"), "role")
    reference_roles = _findall_local(
        _require_local(reference_data_store, "roleMap"), "role"
    )

    assert [role.get("name") for role in generated_roles] == [
        role.get("name") for role in reference_roles
    ]
    assert [role.get("name") for role in generated_roles] == list(DATA_STORE_ROLE_NAMES)
    for generated_role, reference_role in zip(generated_roles, reference_roles):
        assert list(generated_role.keys()) == list(reference_role.keys())
        assert generated_role.get("inherit") == reference_role.get("inherit") == "false"
        assert (
            generated_role.get("allowForAll")
            == reference_role.get("allowForAll")
            == "false"
        )
        assert _child_names(generated_role) == ("users", "groups")


def test_data_store_history_matches_version_uuid(
    reference_data_store: etree._Element,
) -> None:
    generated = _build_data_store({"version_uuid": "version-data-store-9"})
    reference_history = _require_local(reference_data_store, "history")

    assert _child_names(_require_local(generated, "history")) == ("historyInfo",)
    assert _child_names(reference_history)[0] == "historyInfo"
    # Real exports end the history with the current version; a generated object
    # has exactly one version, so the single entry is that version.
    assert _findall_local(reference_history, "historyInfo")[-1].get("versionUuid") == (
        _require_local(reference_data_store, "versionUuid").text
    )
    assert _require_local(
        _require_local(generated, "history"), "historyInfo"
    ).get("versionUuid") == "version-data-store-9"
    assert _require_local(generated, "versionUuid").text == "version-data-store-9"


def test_data_store_role_map_carries_supplied_groups() -> None:
    generated = _build_data_store(
        {"role_map": {"administrators": ["46b0a738-ea79-4c67-af95-e9cd57443c44"]}}
    )

    role_map = _require_local(generated, "roleMap")
    administrators = _findall_local(role_map, "role")[0]
    assert administrators.get("name") == "administrators"
    assert administrators.xpath("string(*[local-name()='groups']/*)") == (
        "46b0a738-ea79-4c67-af95-e9cd57443c44"
    )
    assert _findall_local(role_map, "role")[1].xpath(
        "count(*[local-name()='groups']/*)"
    ) == 0


# ---------------------------------------------------------------------------
# Record type fidelity against the real corpus
# ---------------------------------------------------------------------------

def test_record_type_haul_matches_corpus_child_order(
    reference_record_types: list[etree._Element],
    reference_haul_shapes: set[tuple[str, ...]],
) -> None:
    generated = _build_record_type()

    assert generated.tag == reference_record_types[0].tag == "recordTypeHaul"
    assert _child_names(generated) in reference_haul_shapes
    assert _child_names(generated) == (
        "versionUuid",
        "recordType",
        "roleMap",
        "history",
        "migrationVersion",
    )
    assert _require_local(generated, "migrationVersion").text in {
        _require_local(root, "migrationVersion").text
        for root in reference_record_types
    }


def test_record_type_children_follow_corpus_relative_order(
    reference_record_types: list[etree._Element],
) -> None:
    generated_names = _child_names(
        _require_local(_build_record_type(), "recordType")
    )
    matches = 0
    for root in reference_record_types:
        reference_names = _child_names(_require_local(root, "recordType"))
        if not set(generated_names) <= set(reference_names):
            continue
        matches += 1
        assert generated_names == tuple(
            name for name in reference_names if name in set(generated_names)
        )

    assert matches, f"no corpus record type carries {generated_names}"


def test_record_type_source_configuration_shape_occurs_in_corpus(
    reference_source_config_shapes: set[tuple[str, ...]],
) -> None:
    source_config = _require_local(
        _require_local(_build_record_type(), "recordType"), "sourceConfiguration"
    )

    assert _source_config_shape(source_config) in reference_source_config_shapes


def test_record_type_source_configuration_defaults_match_corpus() -> None:
    source_config = _require_local(
        _require_local(_build_record_type(), "recordType"), "sourceConfiguration"
    )

    assert _texts(
        source_config,
        ("sourceType", "sourceSubType", "skipFailureEnabled"),
    ) == {
        "sourceType": "RDBMS_TABLE",
        "sourceSubType": "NONE",
        "skipFailureEnabled": "true",
    }
    refresh_schedule = _require_local(source_config, "refreshSchedule")
    assert _child_names(refresh_schedule) == ("value", "activated")
    assert _require_local(refresh_schedule, "value").text == (
        '{"hour":3,"minute":"00","amPM":"AM","timeZone":"GMT"}'
    )
    assert _require_local(refresh_schedule, "activated").text == "false"


def test_record_field_child_order_occurs_in_corpus(
    reference_fields: list[etree._Element],
) -> None:
    generated_fields = _findall_local(
        _require_local(
            _require_local(_build_record_type(), "recordType"), "sourceConfiguration"
        ),
        "field",
    )
    reference_shapes = {_child_names(field) for field in reference_fields}

    assert len(generated_fields) == 2
    for field in generated_fields:
        assert _child_names(field) in reference_shapes


def test_record_field_defaults_match_a_corpus_field(
    reference_fields: list[etree._Element],
) -> None:
    constant_tags = (
        "fieldCalculationType",
        "fieldTemplateType",
        "isIndexable",
        "subType",
        "displayNameSource",
        "descriptionSource",
        "compositePkPrecedence",
        "isHidden",
    )
    generated_field = _findall_local(
        _require_local(
            _require_local(_build_record_type(), "recordType"), "sourceConfiguration"
        ),
        "field",
    )[1]
    candidates = [
        field
        for field in reference_fields
        if _child_names(field) == _child_names(generated_field)
        and field.xpath("string(*[local-name()='isRecordId'])") == "false"
    ]
    assert candidates, "no corpus field matches the generated child order"
    reference_field = candidates[0]

    assert _texts(generated_field, constant_tags) == _texts(
        reference_field, constant_tags
    )
    assert _texts(generated_field, constant_tags) == {
        "fieldCalculationType": "NA",
        "fieldTemplateType": "NA",
        "isIndexable": "false",
        "subType": "NA",
        "displayNameSource": "STATIC",
        "descriptionSource": "STATIC",
        "compositePkPrecedence": "-1",
        "isHidden": "false",
    }
    assert _texts(generated_field, ("fieldName", "sourceFieldName")) == {
        "fieldName": "status",
        "sourceFieldName": "STATUS",
    }


def test_record_type_role_map_matches_corpus_roles(
    reference_record_types: list[etree._Element],
) -> None:
    generated_roles = _findall_local(
        _require_local(_build_record_type(), "roleMap"), "role"
    )
    matching = [
        _findall_local(role_map, "role")
        for role_map in (
            _find_local(root, "roleMap") for root in reference_record_types
        )
        if role_map is not None
        and tuple(str(role.get("name")) for role in _findall_local(role_map, "role"))
        == RECORD_TYPE_ROLE_NAMES
    ]
    assert matching, f"no corpus roleMap carries {RECORD_TYPE_ROLE_NAMES}"
    reference_roles = matching[0]

    assert [role.get("name") for role in generated_roles] == list(
        RECORD_TYPE_ROLE_NAMES
    )
    for generated_role, reference_role in zip(generated_roles, reference_roles):
        # Real record type roles carry the name attribute only.
        assert list(generated_role.keys()) == list(reference_role.keys()) == ["name"]
        assert _child_names(generated_role) == _child_names(reference_role)


def test_record_type_history_matches_version_uuid() -> None:
    fields = _record_type_fields()
    fields["version_uuid"] = "07a16262-1e52-4c68-b3ba-99751e1fbc50"
    generated = _build_record_type(fields)

    assert _require_local(generated, "versionUuid").text == (
        "07a16262-1e52-4c68-b3ba-99751e1fbc50"
    )
    assert _require_local(
        _require_local(generated, "history"), "historyInfo"
    ).get("versionUuid") == "07a16262-1e52-4c68-b3ba-99751e1fbc50"
