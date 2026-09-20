"""Native XML builders for proven AI-adjacent Appian export types."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType

APPIAN_NS = "http://www.appian.com/ae/types/2009"
_A = f"{{{APPIAN_NS}}}"
_TRANSLATION_SET_FIELDS = frozenset(
    {
        "default_locale",
        "description",
        "enabled_locales",
        "security_roles",
        "version_uuid",
    }
)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    result: list[str] = []
    for item in value:
        text = _required_text(item, field_name)
        if text in result:
            raise ValueError(f"{field_name} contains duplicate value {text!r}")
        result.append(text)
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _append_security_roles(
    root: etree._Element,
    value: object,
) -> None:
    if value is None:
        return
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("security_roles must be a list of mappings")

    role_map = etree.SubElement(root, "roleMap")
    for role in value:
        if not isinstance(role, Mapping):
            raise ValueError("each security role must be a mapping")
        unknown = set(role) - {"role_name", "users", "groups"}
        if unknown:
            raise ValueError(f"unsupported security role fields: {sorted(unknown)!r}")

        role_name = _required_text(role.get("role_name"), "security role role_name")
        role_element = etree.SubElement(role_map, "role", name=role_name)
        usernames = _string_list_or_empty(role.get("users", []), "security role users")
        if usernames:
            raise ValueError(
                "non-empty security role users are unsupported: "
                "the real export contains no user element example"
            )
        etree.SubElement(role_element, "users")
        groups = etree.SubElement(role_element, "groups")
        for group_uuid in _string_list_or_empty(role.get("groups", []), "security role groups"):
            etree.SubElement(groups, "groupUuid").text = group_uuid


def _string_list_or_empty(value: object, field_name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    result: list[str] = []
    for item in value:
        text = _required_text(item, field_name)
        if text in result:
            raise ValueError(f"{field_name} contains duplicate value {text!r}")
        result.append(text)
    return result


def _build_translation_set_xml(
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> bytes:
    unknown = set(fields) - _TRANSLATION_SET_FIELDS
    if unknown:
        raise ValueError(f"unsupported translation_set fields: {sorted(unknown)!r}")

    object_uuid = _required_text(uuid, "uuid")
    object_name = _required_text(name, "name")
    version_uuid = _required_text(fields.get("version_uuid"), "version_uuid")
    enabled_locales = _string_list(fields.get("enabled_locales"), "enabled_locales")
    default_locale = _required_text(fields.get("default_locale"), "default_locale")
    if default_locale not in enabled_locales:
        raise ValueError("default_locale must be present in enabled_locales")

    root = etree.Element("translationSetHaul", nsmap={"a": APPIAN_NS})
    etree.SubElement(root, "versionUuid").text = version_uuid
    translation_set = etree.SubElement(
        root,
        "translationSet",
        attrib={f"{_A}uuid": object_uuid, "name": object_name},
    )
    description = _optional_text(fields.get("description"), "description")
    if description:
        etree.SubElement(translation_set, f"{_A}description").text = description
    for locale in enabled_locales:
        enabled = etree.SubElement(translation_set, f"{_A}enabledLocales")
        etree.SubElement(enabled, f"{_A}localeLanguageTag").text = locale
    default = etree.SubElement(translation_set, f"{_A}defaultLocale")
    etree.SubElement(default, f"{_A}localeLanguageTag").text = default_locale
    _append_security_roles(root, fields.get("security_roles"))
    history = etree.SubElement(root, "history")
    etree.SubElement(history, "historyInfo", versionUuid=version_uuid)

    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def build_native_ai_xml(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> bytes:
    """Build native XML only where repository export evidence proves the shape."""
    if not isinstance(object_type, ObjectType):
        raise ValueError("object_type must be an ObjectType")
    if not isinstance(fields, dict):
        raise ValueError("fields must be a dict")
    if object_type == ObjectType.TRANSLATION_SET:
        return _build_translation_set_xml(uuid, name, fields)
    if object_type in {ObjectType.AI_AGENT, ObjectType.AI_SKILL}:
        raise ValueError(
            f"No Appian export sample available for {object_type.value}; "
            "create it in Appian and import the export to enable this operation."
        )
    raise ValueError(f"Unsupported native AI object type: {object_type.value}")
