"""Build native Appian artifacts for data design objects."""

from __future__ import annotations

import re
import uuid as uuidlib
from collections.abc import Mapping
from urllib.parse import quote

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType

APPIAN_NS = "http://www.appian.com/ae/types/2009"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_QUALIFIED_NAME = re.compile(r"^\{([^}]+)\}(.+)$")
_XSD_TYPES = {
    "boolean": "boolean",
    "date": "date",
    "datetime": "dateTime",
    "decimal": "decimal",
    "float": "float",
    "integer": "int",
    "int": "int",
    "long": "long",
    "string": "string",
    "text": "string",
}

# dataStoreHaul roleMap role order, taken from the real dataStore corpus file.
DATA_STORE_ROLE_NAMES: tuple[str, ...] = (
    "administrators",
    "authors",
    "denyAdministrators",
    "denyAuthors",
    "denyReaders",
    "readers",
)
# recordTypeHaul roleMap carries only these two roles, name attribute only.
RECORD_TYPE_ROLE_NAMES: tuple[str, ...] = (
    "record_type_administrator",
    "record_type_viewer",
)
# Real sourceConfiguration refreshSchedule value in the corpus record types.
DEFAULT_REFRESH_SCHEDULE = '{"hour":3,"minute":"00","amPM":"AM","timeZone":"GMT"}'


def _value(data: Mapping[str, object], *keys: str, default: object = "") -> object:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _text(data: Mapping[str, object], *keys: str, default: str = "") -> str:
    value = _value(data, *keys, default=default)
    return str(value) if value is not None else default


def _bool(data: Mapping[str, object], *keys: str, default: bool = False) -> bool:
    value = _value(data, *keys, default=default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _items(data: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"Each {key} item must be a mapping")
        result.append(item)
    return result


def _subelement(
    parent: etree._Element,
    tag: str,
    text: str | None = None,
    *,
    namespace: str = "",
) -> etree._Element:
    qualified_tag = f"{{{namespace}}}{tag}" if namespace else tag
    element = etree.SubElement(parent, qualified_tag)
    if text is not None:
        element.text = text
    return element


def _flag(
    parent: etree._Element,
    tag: str,
    value: bool,
    *,
    namespace: str = "",
) -> etree._Element:
    return _subelement(parent, tag, str(value).lower(), namespace=namespace)


def _serialize(root: etree._Element, standalone: bool | None) -> bytes:
    """Serialize with the XML declaration the matching corpus files use.

    datatype XSD and recordTypeHaul exports omit standalone; dataStoreHaul
    exports set it.
    """
    etree.indent(root, space="  ")
    artifact = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=standalone,
        pretty_print=True,
    )
    etree.fromstring(artifact)
    return artifact


def _nested_uuid(parent_uuid: str, kind: str, name: str, index: int) -> str:
    seed = f"{parent_uuid}:{kind}:{index}:{name}"
    return str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, seed))


def _history(parent: etree._Element, version_uuid: str, *, namespace: str = "") -> None:
    """Append <history> with the single historyInfo the exports always carry.

    Real exports list every published version; a generated object has exactly
    one, so historyInfo always matches versionUuid.
    """
    history = _subelement(parent, "history", namespace=namespace)
    history_info = _subelement(history, "historyInfo", namespace=namespace)
    history_info.set("versionUuid", version_uuid)


def _group_uuids(role_map: Mapping[str, object], role_name: str) -> list[str]:
    value = role_map.get(role_name, [])
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    raise ValueError(f"role_map['{role_name}'] must be a string or a list")


def _role_map(
    parent: etree._Element,
    role_names: tuple[str, ...],
    groups_by_role: Mapping[str, object],
    *,
    content_style: bool,
) -> None:
    """Append <roleMap> in real corpus role order.

    dataStoreHaul roles carry inherit/allowForAll attributes; recordTypeHaul
    roles carry the name attribute only.
    """
    role_map = _subelement(parent, "roleMap")
    for role_name in role_names:
        role = _subelement(role_map, "role")
        if content_style:
            role.set("inherit", "false")
            role.set("allowForAll", "false")
        role.set("name", role_name)
        _subelement(role, "users")
        groups = _subelement(role, "groups")
        for group_uuid in _group_uuids(groups_by_role, role_name):
            _subelement(groups, "groupUuid", group_uuid)


def _role_groups(fields: Mapping[str, object]) -> Mapping[str, object]:
    value = _value(fields, "role_map", "roleMap", default={})
    if not isinstance(value, Mapping):
        raise ValueError("role_map must be a mapping of role name to group uuids")
    return value


def _field_type(field: Mapping[str, object]) -> str:
    value = _text(field, "type", "type_name", default="xsd:string").strip()
    qualified = _QUALIFIED_NAME.match(value)
    if qualified and qualified.group(1) == XSD_NS:
        return f"xsd:{qualified.group(2)}"
    if ":" in value:
        return value
    return f"xsd:{_XSD_TYPES.get(value.lower(), value)}"


def _data_type_identity(
    uuid: str,
    name: str,
    fields: Mapping[str, object],
) -> tuple[str, str, str]:
    identity_match = _QUALIFIED_NAME.match(uuid)
    namespace = _text(fields, "namespace", "target_namespace")
    type_name = _text(fields, "type_name", default=name)
    if identity_match:
        identity_namespace, identity_name = identity_match.groups()
        if namespace and namespace != identity_namespace:
            raise ValueError("data_type namespace conflicts with uuid identity")
        if type_name and type_name != identity_name:
            raise ValueError("data_type name conflicts with uuid identity")
        namespace = identity_namespace
        type_name = identity_name
    if not namespace:
        raise ValueError("data_type requires fields['namespace'] or a qualified uuid")
    if not type_name:
        raise ValueError("data_type requires a type name")
    return namespace, type_name, f"{{{namespace}}}{type_name}"


def _jpa_column_annotation(
    field: Mapping[str, object],
    source_name: str,
    source_type: str,
) -> str:
    """Return the appian.jpa annotation text for one JPA-backed element.

    Primary keys use the real corpus form: @Id @GeneratedValue then a @Column
    with nullable=false and unique=true.
    """
    parts: list[str] = []
    column_args = [f'name="{source_name}"']
    if _bool(field, "is_primary_key", "isPrimaryKey"):
        parts.append("@Id")
        parts.append("@GeneratedValue")
        column_args.append("nullable=false")
        column_args.append("unique=true")
    elif _bool(field, "is_unique", "isUnique"):
        column_args.append("unique=true")
    if source_type:
        column_args.append(f'columnDefinition="{source_type}"')
    parts.append(f"@Column({', '.join(column_args)})")
    return " ".join(parts)


def _data_type_field(
    sequence: etree._Element,
    field: Mapping[str, object],
    index: int,
    *,
    jpa: bool,
) -> None:
    field_name = _text(field, "name", "field_name", "fieldName")
    if not field_name:
        raise ValueError(f"data_type field {index} requires a name")
    element = _subelement(sequence, "element", namespace=XSD_NS)
    if not jpa:
        # Non-JPA CDTs are plain XSD: minOccurs="0", no nillable, no appinfo.
        element.set("minOccurs", "0")
        element.set("name", field_name)
        element.set("type", _field_type(field))
        return
    element.set("name", field_name)
    element.set("nillable", str(_bool(field, "nillable", default=True)).lower())
    element.set("type", _field_type(field))
    if _bool(field, "omit_annotation", "omitAnnotation"):
        # Real JPA CDTs carry unmapped elements with no annotation at all.
        return
    source_name = _text(
        field,
        "source_field_name",
        "sourceFieldName",
        "column_name",
        default=field_name,
    )
    source_type = _text(
        field,
        "source_field_type",
        "sourceFieldType",
        "column_definition",
    )
    field_annotation = _subelement(element, "annotation", namespace=XSD_NS)
    field_info = _subelement(field_annotation, "appinfo", namespace=XSD_NS)
    field_info.set("source", "appian.jpa")
    field_info.text = _jpa_column_annotation(field, source_name, source_type)


def _build_data_type(
    uuid: str,
    name: str,
    fields: Mapping[str, object],
) -> tuple[str, bytes]:
    namespace, type_name, identity = _data_type_identity(uuid, name, fields)
    table_name = _text(fields, "table_name", "tableName")
    jpa = _bool(fields, "jpa", "use_jpa", "is_jpa", default=bool(table_name))
    version_uuid = _text(fields, "version_uuid", "versionUuid", default=uuid)
    root = etree.Element(
        f"{{{XSD_NS}}}schema",
        nsmap={"tns": namespace, "xsd": XSD_NS},
        targetNamespace=namespace,
    )
    complex_type = _subelement(root, "complexType", namespace=XSD_NS)
    complex_type.set("name", type_name)
    annotation = _subelement(complex_type, "annotation", namespace=XSD_NS)
    if jpa and table_name:
        appinfo = _subelement(annotation, "appinfo", namespace=XSD_NS)
        appinfo.set("source", "appian.jpa")
        appinfo.text = f'@Table(name="{table_name}")'
    metadata_info = _subelement(annotation, "appinfo", namespace=XSD_NS)
    metadata_info.set("source", APPIAN_NS)
    metadata = etree.SubElement(
        metadata_info,
        f"{{{APPIAN_NS}}}Metadata",
        nsmap={"ns2": APPIAN_NS},
    )
    _subelement(metadata, "versionUuid", version_uuid, namespace=APPIAN_NS)
    _history(metadata, version_uuid, namespace=APPIAN_NS)
    sequence = _subelement(complex_type, "sequence", namespace=XSD_NS)
    for index, field in enumerate(_items(fields, "fields")):
        _data_type_field(sequence, field, index, jpa=jpa)
    return f"{quote(identity, safe='')}.xsd", _serialize(root, standalone=None)


def _build_data_store(
    uuid: str,
    name: str,
    fields: Mapping[str, object],
) -> tuple[str, bytes]:
    version_uuid = _text(fields, "version_uuid", "versionUuid", default=uuid)
    root = etree.Element("dataStoreHaul", nsmap={"a": APPIAN_NS})
    _subelement(root, "versionUuid", version_uuid)
    data_store = _subelement(root, "dataStore")
    _subelement(data_store, "uuid", uuid)
    _subelement(data_store, "name", name)
    description = _text(fields, "description")
    if description:
        _subelement(data_store, "description", description)
    _subelement(
        data_store,
        "dataSourceKey",
        _text(fields, "data_source_key", "dataSourceKey", default="jdbc/Appian"),
    )
    _flag(
        data_store,
        "adaptingExplicitSqlNames",
        _bool(fields, "adapting_explicit_sql_names", "adaptingExplicitSqlNames"),
    )
    _flag(
        data_store,
        "autoUpdateSchema",
        _bool(fields, "auto_update_schema", "autoUpdateSchema"),
    )
    entities = _subelement(data_store, "entities")
    for index, entity in enumerate(_items(fields, "entities")):
        entity_name = _text(entity, "name")
        entity_type = _text(entity, "type")
        if not entity_name or not entity_type:
            raise ValueError(f"data_store entity {index} requires name and type")
        entity_element = _subelement(entities, "entity")
        _subelement(
            entity_element,
            "uuid",
            _text(entity, "uuid", default=_nested_uuid(uuid, "entity", entity_name, index)),
        )
        _subelement(entity_element, "name", entity_name)
        _subelement(entity_element, "type", entity_type)
    _flag(root, "isPublished", _bool(fields, "is_published", "isPublished"))
    _role_map(root, DATA_STORE_ROLE_NAMES, _role_groups(fields), content_style=True)
    _history(root, version_uuid)
    return f"{uuid}.xml", _serialize(root, standalone=True)


def _record_field(
    source_configuration: etree._Element,
    parent_uuid: str,
    field: Mapping[str, object],
    index: int,
) -> None:
    """Append one <field> with the complete real child set, in corpus order."""
    field_name = _text(field, "name", "field_name", "fieldName")
    if not field_name:
        raise ValueError(f"record_type field {index} requires a name")
    field_element = _subelement(source_configuration, "field")
    _subelement(
        field_element,
        "uuid",
        _text(field, "uuid", default=_nested_uuid(parent_uuid, "field", field_name, index)),
    )
    _subelement(
        field_element,
        "type",
        _text(field, "type", default=f"{{{APPIAN_NS}}}Text"),
    )
    _subelement(
        field_element,
        "sourceFieldName",
        _text(field, "source_field_name", "sourceFieldName", default=field_name),
    )
    _subelement(
        field_element,
        "sourceFieldType",
        _text(field, "source_field_type", "sourceFieldType"),
    )
    _subelement(field_element, "fieldName", field_name)
    _subelement(
        field_element,
        "displayName",
        _text(field, "display_name", "displayName", default=field_name),
    )
    _flag(field_element, "isRecordId", _bool(field, "is_primary_key", "isRecordId"))
    _flag(field_element, "isUnique", _bool(field, "is_unique", "isUnique"))
    _flag(field_element, "isCustomField", _bool(field, "is_custom_field", "isCustomField"))
    _subelement(
        field_element,
        "customFieldExpr",
        _text(field, "custom_field_expr", "customFieldExpr"),
    )
    _subelement(field_element, "fieldCalculationType", "NA")
    _subelement(field_element, "fieldTemplateType", "NA")
    _subelement(field_element, "recordFieldSecurityMembershipFilter")
    _subelement(field_element, "fieldFormat")
    _flag(field_element, "isIndexable", _bool(field, "is_indexable", "isIndexable"))
    _subelement(field_element, "subType", "NA")
    _subelement(field_element, "displayNameSource", "STATIC")
    _subelement(field_element, "descriptionSource", "STATIC")
    _subelement(field_element, "compositePkPrecedence", "-1")
    _flag(field_element, "isHidden", _bool(field, "is_hidden", "isHidden"))


def _build_source_configuration(
    record_type: etree._Element,
    uuid: str,
    name: str,
    fields: Mapping[str, object],
) -> None:
    source_configuration = _subelement(
        record_type,
        "sourceConfiguration",
        namespace=APPIAN_NS,
    )
    _subelement(
        source_configuration,
        "sourceUuid",
        _text(fields, "source_uuid", "sourceUuid"),
    )
    _subelement(
        source_configuration,
        "sourceType",
        _text(fields, "source_type", "sourceType", default="RDBMS_TABLE"),
    )
    _subelement(
        source_configuration,
        "sourceSubType",
        _text(fields, "source_sub_type", "sourceSubType", default="NONE"),
    )
    _subelement(
        source_configuration,
        "sourceContextExpr",
        _text(fields, "source_context_expr", "sourceContextExpr"),
    )
    _subelement(
        source_configuration,
        "friendlyName",
        _text(fields, "friendly_name", "friendlyName", default=name),
    )
    _subelement(
        source_configuration,
        "sourceFilterExpr",
        _text(fields, "source_filter_expr", "sourceFilterExpr"),
    )
    for index, field in enumerate(_items(fields, "fields")):
        _record_field(source_configuration, uuid, field, index)
    _subelement(
        source_configuration,
        "uuid",
        _text(
            fields,
            "source_configuration_uuid",
            "sourceConfigurationUuid",
            default=_nested_uuid(uuid, "source-configuration", name, 0),
        ),
    )
    refresh_schedule = _subelement(source_configuration, "refreshSchedule")
    _subelement(
        refresh_schedule,
        "value",
        _text(
            fields,
            "refresh_schedule",
            "refreshSchedule",
            default=DEFAULT_REFRESH_SCHEDULE,
        ),
    )
    _flag(
        refresh_schedule,
        "activated",
        _bool(fields, "refresh_schedule_activated", "refreshScheduleActivated"),
    )
    _flag(
        source_configuration,
        "skipFailureEnabled",
        _bool(fields, "skip_failure_enabled", "skipFailureEnabled", default=True),
    )
    _subelement(
        source_configuration,
        "recordIdGeneratorUuid",
        _text(fields, "record_id_generator_uuid", "recordIdGeneratorUuid"),
    )


def _build_record_type(
    uuid: str,
    name: str,
    fields: Mapping[str, object],
) -> tuple[str, bytes]:
    version_uuid = _text(fields, "version_uuid", "versionUuid", default=uuid)
    root = etree.Element(
        "recordTypeHaul",
        nsmap={"a": APPIAN_NS, "xsi": XSI_NS},
    )
    _subelement(root, "versionUuid", version_uuid)
    record_type = _subelement(root, "recordType")
    record_type.set(f"{{{APPIAN_NS}}}uuid", uuid)
    record_type.set("name", name)
    for key, tag in (
        ("plural_name", "pluralName"),
        ("description", "description"),
        ("url_stub", "urlStub"),
        ("layout_type", "layoutType"),
    ):
        value = _text(fields, key, tag)
        if value:
            _subelement(record_type, tag, value, namespace=APPIAN_NS)
    _build_source_configuration(record_type, uuid, name, fields)
    _role_map(root, RECORD_TYPE_ROLE_NAMES, _role_groups(fields), content_style=False)
    _history(root, version_uuid)
    _subelement(
        root,
        "migrationVersion",
        _text(fields, "migration_version", "migrationVersion", default="1"),
    )
    return f"{uuid}.xml", _serialize(root, standalone=None)


def build_native_data_artifact(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[str, bytes]:
    """Return the native export filename and content for one data object."""
    if not uuid.strip():
        raise ValueError("uuid must not be empty")
    if not name.strip():
        raise ValueError("name must not be empty")
    builders = {
        ObjectType.DATA_TYPE: _build_data_type,
        ObjectType.DATA_STORE: _build_data_store,
        ObjectType.RECORD_TYPE: _build_record_type,
    }
    builder = builders.get(object_type)
    if builder is None:
        raise ValueError(f"Unsupported native data object type: {object_type.value}")
    return builder(uuid, name, fields)
