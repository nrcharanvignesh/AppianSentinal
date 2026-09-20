"""Build native Appian collaboration objects: groups, folders and documents.

Every shape here is copied from a real export sample in the validation corpus
(``group/*.xml`` and ``content/*.xml``). Object types with no sample are
refused instead of guessed, so nothing this module writes is invented.

Proven samples behind each builder:

* ``group``  -> ``group/_e-0000d398-70cf-8000-9aee-01075c01075c_6.xml``
* ``rulesFolder`` -> ``content/64869106-d692-4685-a3bb-765035376ca2.xml``
* ``folder`` -> ``content/_a-0000ef9a-a4f8-8000-9bbc-011c48011c48_760597.xml``
* ``communityKnowledgeCenter`` -> ``content/dd6f99af-845e-4628-88f0-7f35b025f822.xml``
* ``document`` -> ``content/_a-0000f03c-e8bd-8000-9bc0-011c48011c48_993889.xml``

Documents are written as a metadata XML artifact plus a payload file: the
caller supplies the bytes, this module never invents binary content.
"""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import Callable

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType

APPIAN_NS = "http://www.appian.com/ae/types/2009"

# Role order and inherit defaults read off the folder/document samples.
_ROLE_NAMES: tuple[str, ...] = (
    "readers",
    "authors",
    "administrators",
    "denyReaders",
    "denyAuthors",
    "denyAdministrators",
)
_ROLE_NAME_SET: frozenset[str] = frozenset(_ROLE_NAMES)
_DEFAULT_ROLE_INHERIT: dict[str, bool] = {
    "readers": True,
    "authors": True,
    "administrators": True,
    "denyReaders": False,
    "denyAuthors": False,
    "denyAdministrators": False,
}

# Visibility flag order inside every proven content sample.
_VISIBILITY_FLAGS: tuple[str, ...] = (
    "hierarchy",
    "indexable",
    "quota",
    "searchable",
    "system",
    "unlogged",
)
_VISIBILITY_DEFAULTS: dict[str, bool] = {
    "hierarchy": True,
    "indexable": True,
    "quota": False,
    "searchable": True,
    "system": False,
    "unlogged": False,
}


def _field(
    fields: dict[str, object],
    *names: str,
    default: object = "",
) -> object:
    for name in names:
        if name in fields:
            return fields[name]
    return default


def _text_value(
    fields: dict[str, object],
    *names: str,
    default: str = "",
) -> str:
    value = _field(fields, *names, default=default)
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"{names[0]} must be a scalar value")
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _bool_value(
    fields: dict[str, object],
    *names: str,
    default: bool = False,
) -> str:
    value = _field(fields, *names, default=default)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower()
    raise ValueError(f"{names[0]} must be a boolean")


def _string_list(fields: dict[str, object], *names: str) -> list[str]:
    value = _field(fields, *names, default=[])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{names[0]} must be a list of strings")
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{names[0]} must contain non-empty strings")
    return list(value)


def _add_text(parent: etree._Element, tag: str, value: str) -> etree._Element:
    element = etree.SubElement(parent, tag)
    element.text = value
    return element


def _version_uuid(fields: dict[str, object], object_uuid: str) -> str:
    """Return the haul version UUID, which is never the object UUID.

    Real exports always carry a version UUID distinct from the object UUID, so
    an absent value is minted fresh rather than aliased onto the object UUID.
    """
    value = _text_value(fields, "version_uuid", "versionUuid").strip()
    if not value:
        # ponytail: random mint makes output non-deterministic when the caller
        # omits version_uuid; pass version_uuid explicitly for stable bytes.
        return str(uuid_module.uuid4())
    if value == object_uuid:
        raise ValueError(
            "version_uuid must differ from the object uuid; real exports "
            "always carry a distinct version uuid"
        )
    return value


def _add_history(
    root: etree._Element,
    version_uuid: str,
    fields: dict[str, object],
) -> None:
    """Append ``<history>`` whose last entry matches the haul version UUID."""
    history = etree.SubElement(root, "history")
    for entry in _string_list(fields, "history", "history_version_uuids"):
        if entry == version_uuid:
            continue
        etree.SubElement(history, "historyInfo", versionUuid=entry)
    etree.SubElement(history, "historyInfo", versionUuid=version_uuid)


def _add_visibility(
    parent: etree._Element,
    fields: dict[str, object],
    advertise_default: bool,
) -> None:
    visibility = etree.SubElement(parent, "visibility")
    _add_text(
        visibility,
        "advertise",
        _bool_value(fields, "advertise", default=advertise_default),
    )
    for flag in _VISIBILITY_FLAGS:
        _add_text(
            visibility,
            flag,
            _bool_value(fields, flag, default=_VISIBILITY_DEFAULTS[flag]),
        )


def _role_config(fields: dict[str, object]) -> dict[str, dict[str, object]]:
    config = _field(fields, "role_map", "roleMap", default={})
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("role_map must be a dictionary keyed by role name")
    unknown = sorted(str(key) for key in config if key not in _ROLE_NAME_SET)
    if unknown:
        raise ValueError(f"role_map has unknown role names: {', '.join(unknown)}")
    parsed: dict[str, dict[str, object]] = {}
    for role_name, entry in config.items():
        if not isinstance(entry, dict):
            raise ValueError(f"role_map[{role_name}] must be a dictionary")
        parsed[str(role_name)] = entry
    return parsed


def _add_role_map(root: etree._Element, fields: dict[str, object]) -> None:
    """Append the six-role ``<roleMap>`` block in the proven order."""
    config = _role_config(fields)
    role_map = etree.SubElement(
        root,
        "roleMap",
        public=_bool_value(fields, "public", "role_map_public", default=True),
    )
    for role_name in _ROLE_NAMES:
        entry = config.get(role_name, {})
        role = etree.SubElement(
            role_map,
            "role",
            inherit=_bool_value(
                entry,
                "inherit",
                default=_DEFAULT_ROLE_INHERIT[role_name],
            ),
            allowForAll=_bool_value(
                entry,
                "allow_for_all",
                "allowForAll",
                default=False,
            ),
            name=role_name,
        )
        users = etree.SubElement(role, "users")
        for user_uuid in _string_list(entry, "users", "user_uuids"):
            _add_text(users, "userUuid", user_uuid)
        groups = etree.SubElement(role, "groups")
        for group_uuid in _string_list(entry, "groups", "group_uuids"):
            _add_text(groups, "groupUuid", group_uuid)


def _content_haul(
    tag: str,
    object_uuid: str,
    name: str,
    fields: dict[str, object],
    advertise_default: bool,
) -> tuple[etree._Element, etree._Element, str]:
    """Open a ``<contentHaul>`` with the proven field order for ``tag``."""
    version_uuid = _version_uuid(fields, object_uuid)
    root = etree.Element("contentHaul", nsmap={"a": APPIAN_NS})
    _add_text(root, "versionUuid", version_uuid)
    content = etree.SubElement(root, tag)
    _add_text(content, "name", name)
    _add_text(content, "uuid", object_uuid)
    _add_text(content, "description", _text_value(fields, "description"))
    parent_uuid = _text_value(fields, "parent_uuid", "parentUuid")
    if parent_uuid:
        _add_text(content, "parentUuid", parent_uuid)
    _add_visibility(content, fields, advertise_default)
    return root, content, version_uuid


def _add_principals(
    parent: etree._Element,
    tag: str,
    user_uuids: list[str],
    group_uuids: list[str],
) -> None:
    container = etree.SubElement(parent, tag)
    users = etree.SubElement(container, "users")
    for user_uuid in user_uuids:
        _add_text(users, "userUuid", user_uuid)
    groups = etree.SubElement(container, "groups")
    for group_uuid in group_uuids:
        _add_text(groups, "groupUuid", group_uuid)


def _build_group(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[etree._Element, dict[str, bytes]]:
    version_uuid = _version_uuid(fields, object_uuid)
    root = etree.Element("groupHaul", nsmap={"a": APPIAN_NS})
    _add_text(root, "versionUuid", version_uuid)
    group = etree.SubElement(root, "group")
    _add_text(group, "name", name)
    _add_text(
        group,
        "securityMap",
        _text_value(fields, "security_map", "securityMap", default="SECURITYMAP_PUBLIC"),
    )
    _add_text(group, "uuid", object_uuid)
    _add_text(
        group,
        "groupTypeUuid",
        _text_value(
            fields,
            "group_type_uuid",
            "groupTypeUuid",
            default="SYSTEM_GROUP_TYPE_CUSTOM",
        ),
    )
    parent_uuid = _text_value(fields, "parent_uuid", "parentUuid")
    if parent_uuid:
        _add_text(group, "parentUuid", parent_uuid)
    _add_text(group, "description", _text_value(fields, "description"))
    _add_text(
        group,
        "delegatedCreation",
        _bool_value(fields, "delegated_creation", "delegatedCreation"),
    )
    _add_text(
        group,
        "memberPolicy",
        _text_value(fields, "member_policy", "memberPolicy", default="MEMBERPOLICY_CLOSED"),
    )
    _add_text(
        group,
        "viewingPolicy",
        _text_value(fields, "viewing_policy", "viewingPolicy", default="VIEWINGPOLICY_LOW"),
    )
    etree.SubElement(group, "attributes")
    _add_principals(
        root,
        "members",
        _string_list(fields, "member_users", "memberUsers"),
        _string_list(fields, "member_groups", "memberGroups"),
    )
    _add_principals(
        root,
        "admins",
        _string_list(fields, "admin_users", "adminUsers"),
        _string_list(fields, "admin_groups", "adminGroups"),
    )
    # ponytail: empty rule set only; membership rule expressions are not
    # generated because their operator ids cannot be derived from fields.
    etree.SubElement(root, "ruleSet")
    _add_history(root, version_uuid, fields)
    return root, {}


def _unproven_builder(
    object_type: ObjectType,
) -> Callable[[str, str, dict[str, object]], tuple[etree._Element, dict[str, bytes]]]:
    """Return a builder that refuses to invent XML for an unsampled type."""

    def builder(
        object_uuid: str,
        name: str,
        fields: dict[str, object],
    ) -> tuple[etree._Element, dict[str, bytes]]:
        raise ValueError(
            f"No Appian export sample available for {object_type.value}; "
            "create it in Appian and import the export to enable this operation."
        )

    return builder


def _build_folder_like(
    tag: str,
) -> Callable[[str, str, dict[str, object]], tuple[etree._Element, dict[str, bytes]]]:
    def builder(
        object_uuid: str,
        name: str,
        fields: dict[str, object],
    ) -> tuple[etree._Element, dict[str, bytes]]:
        root, _, version_uuid = _content_haul(
            tag,
            object_uuid,
            name,
            fields,
            advertise_default=False,
        )
        _add_role_map(root, fields)
        _add_history(root, version_uuid, fields)
        return root, {}

    return builder


def _expiration_days(fields: dict[str, object]) -> str:
    value = _field(fields, "expiration_days", "expirationDays", default=0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expiration_days must be an integer")
    if value < 0:
        raise ValueError("expiration_days must not be negative")
    return str(value)


def _build_knowledge_center(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[etree._Element, dict[str, bytes]]:
    root, content, version_uuid = _content_haul(
        "communityKnowledgeCenter",
        object_uuid,
        name,
        fields,
        advertise_default=True,
    )
    _add_text(content, "expirationDays", _expiration_days(fields))
    _add_role_map(root, fields)
    _add_history(root, version_uuid, fields)
    return root, {}


def _payload_file_name(fields: dict[str, object]) -> str:
    file_name = _text_value(fields, "file_name", "fileName")
    if not file_name:
        extension = _text_value(fields, "file_extension", "fileExtension").lstrip(".")
        if not extension:
            raise ValueError("document requires file_name or file_extension")
        # Real exports store the payload as file.<ext> inside the uuid directory.
        file_name = f"file.{extension}"
    if "/" in file_name or "\\" in file_name or file_name in {".", ".."}:
        raise ValueError("document file_name must not contain a path separator")
    return file_name


def _build_document(
    object_uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[etree._Element, dict[str, bytes]]:
    file_name = _payload_file_name(fields)
    payload = _field(fields, "payload", "content_bytes", default=None)
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError(
            "document requires payload bytes; binary content is never generated"
        )
    root, _, version_uuid = _content_haul(
        "document",
        object_uuid,
        name,
        fields,
        advertise_default=False,
    )
    _add_text(root, "file", file_name)
    _add_role_map(root, fields)
    _add_history(root, version_uuid, fields)
    return root, {f"{object_uuid}/{file_name}": bytes(payload)}


_BUILDERS: dict[
    ObjectType,
    Callable[[str, str, dict[str, object]], tuple[etree._Element, dict[str, bytes]]],
] = {
    ObjectType.GROUP: _build_group,
    ObjectType.GROUP_TYPE: _unproven_builder(ObjectType.GROUP_TYPE),
    ObjectType.RULES_FOLDER: _build_folder_like("rulesFolder"),
    ObjectType.DOCUMENT_FOLDER: _build_folder_like("folder"),
    ObjectType.KNOWLEDGE_CENTER: _build_knowledge_center,
    ObjectType.FEED: _unproven_builder(ObjectType.FEED),
    ObjectType.DOCUMENT: _build_document,
}


def build_native_collaboration_artifact(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> tuple[bytes, dict[str, bytes]]:
    """Return the export XML and payload files for one collaboration object.

    The payload mapping keys are paths relative to the directory that holds the
    XML artifact; only documents produce payload files, and their bytes must be
    supplied by the caller through ``fields["payload"]``.

    Raises ``ValueError`` for object types whose XML shape has no real export
    sample; this module never guesses an unproven layout.
    """
    if not isinstance(object_type, ObjectType) or object_type not in _BUILDERS:
        raise ValueError(f"Unsupported native collaboration object type: {object_type}")
    if not isinstance(uuid, str) or not uuid.strip():
        raise ValueError("uuid must be a non-empty string")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    if not isinstance(fields, dict):
        raise ValueError("fields must be a dictionary")
    root, payloads = _BUILDERS[object_type](uuid, name, fields)
    artifact = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
        pretty_print=True,
    )
    return artifact, payloads
