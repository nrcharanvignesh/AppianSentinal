"""Build native XML for Appian experience design objects.

Every element name, attribute and sibling order below is copied from real
Appian export files (``site/*.xml``, ``portal/*.xml``, ``tempoReport/*.xml``
and the ``content/*.xml`` report). Object types with no proven export shape
are rejected instead of guessed.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType

APPIAN_NS = "http://www.appian.com/ae/types/2009"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
_A_UUID = f"{{{APPIAN_NS}}}uuid"
_XSI_TYPE = f"{{{XSI_NS}}}type"

_NS_A: dict[str, str] = {"a": APPIAN_NS}
_NS_A_XSI: dict[str, str] = {"a": APPIAN_NS, "xsi": XSI_NS}

# Every site in the corpus carries this exact visibility mask.
SITE_VISIBILITY = "268435456"

# roleMap role names in the order each real export writes them.
SITE_ROLE_NAMES: tuple[str, ...] = ("site_administrator", "site_viewer")
PORTAL_ROLE_NAMES: tuple[str, ...] = ("portal_viewer", "portal_administrator")
TEMPO_REPORT_ROLE_NAMES: tuple[str, ...] = ("report_administrator", "report_viewer")
CONTENT_ROLE_NAMES: tuple[str, ...] = (
    "readers",
    "authors",
    "administrators",
    "denyReaders",
    "denyAuthors",
    "denyAdministrators",
)
_CONTENT_INHERITED_ROLES = frozenset({"readers", "authors", "administrators"})

# Types with no proven export XML in any local Appian package we have seen.
_UNPROVEN_TYPES: frozenset[ObjectType] = frozenset(
    {
        ObjectType.DASHBOARD,
        ObjectType.CONTROL_PANEL,
        ObjectType.CONTROL_PANEL_HIERARCHY_ITEM,
    }
)


def _text_field(fields: dict[str, object], key: str) -> str:
    value = fields.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _boolean_field(fields: dict[str, object], key: str) -> bool | None:
    value = fields.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _add_text(parent: etree._Element, tag: str, value: str) -> None:
    """Append a child only when it carries a value, as optional export fields do."""
    if value:
        etree.SubElement(parent, tag).text = value


def _always_text(parent: etree._Element, tag: str, value: str) -> None:
    """Append a child even when empty; real exports keep ``<description/>``."""
    element = etree.SubElement(parent, tag)
    if value:
        element.text = value


def _role_map(
    root: etree._Element,
    role_names: tuple[str, ...],
    *,
    content_style: bool,
) -> None:
    """Append the ``<roleMap>`` skeleton in real corpus order with no members.

    Group membership belongs to the target environment, not to generated XML.
    """
    # ponytail: the content roleMap sample also carries public="true"; it is
    # omitted so generated reports are not world readable by default.
    role_map = etree.SubElement(root, "roleMap")
    for role_name in role_names:
        role = etree.SubElement(role_map, "role")
        if content_style:
            role.set(
                "inherit",
                "true" if role_name in _CONTENT_INHERITED_ROLES else "false",
            )
            role.set("allowForAll", "false")
        role.set("name", role_name)
        etree.SubElement(role, "users")
        etree.SubElement(role, "groups")


def _history(root: etree._Element, version_uuid: str) -> None:
    """Append ``<history>`` holding the current version, as every export does."""
    etree.SubElement(etree.SubElement(root, "history"), "historyInfo").set(
        "versionUuid", version_uuid
    )


def _haul(
    root_tag: str,
    object_tag: str,
    fields: dict[str, object],
    nsmap: dict[str, str],
) -> tuple[etree._Element, etree._Element, str]:
    root = etree.Element(root_tag, nsmap=nsmap)
    version_uuid = _text_field(fields, "version_uuid") or str(uuid4())
    etree.SubElement(root, "versionUuid").text = version_uuid
    return root, etree.SubElement(root, object_tag), version_uuid


def _serialize(root: etree._Element, standalone: bool | None) -> bytes:
    """Serialize with the XML declaration the matching corpus files use.

    site and portal exports omit standalone; tempoReport and content set it.
    """
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=standalone,
        pretty_print=True,
    )


def _build_site(uuid: str, name: str, fields: dict[str, object]) -> bytes:
    # Real root declares both the a: and xsi: prefixes.
    root, element, version_uuid = _haul("siteHaul", "site", fields, _NS_A_XSI)
    element.set(_A_UUID, uuid)
    element.set("name", name)
    _always_text(element, "description", _text_field(fields, "description"))
    _add_text(element, "urlStub", _text_field(fields, "url_stub"))
    # ponytail: no <page> children; copy a real page block when a generated
    # site has to ship navigation instead of an empty shell.
    etree.SubElement(element, "visibility").text = SITE_VISIBILITY
    _role_map(root, SITE_ROLE_NAMES, content_style=False)
    _history(root, version_uuid)
    return _serialize(root, standalone=None)


def _build_portal(uuid: str, name: str, fields: dict[str, object]) -> bytes:
    # Real root declares only the a: prefix; xsi is declared where it is used.
    root, element, version_uuid = _haul("portalHaul", "portal", fields, _NS_A)
    element.set(_A_UUID, uuid)
    element.set("name", name)
    _always_text(element, "description", _text_field(fields, "description"))
    published = _boolean_field(fields, "published")
    if published is not None:
        etree.SubElement(element, "published").text = str(published).lower()
    _add_text(element, "displayName", _text_field(fields, "display_name"))
    _add_text(element, "urlStub", _text_field(fields, "url_stub"))
    service_account_uuid = _text_field(fields, "service_account_uuid")
    if service_account_uuid:
        account = etree.SubElement(element, "serviceAccountUser", nsmap={"xsi": XSI_NS})
        account.set(_A_UUID, service_account_uuid)
        account.set(_XSI_TYPE, "a:User")
    _add_text(element, "hostname", _text_field(fields, "hostname"))
    _role_map(root, PORTAL_ROLE_NAMES, content_style=False)
    _history(root, version_uuid)
    return _serialize(root, standalone=None)


def _build_tempo_report(uuid: str, name: str, fields: dict[str, object]) -> bytes:
    root, element, version_uuid = _haul(
        "tempoReportHaul", "tempoReport", fields, _NS_A
    )
    element.set(_A_UUID, uuid)
    element.set("name", name)
    _add_text(element, f"{{{APPIAN_NS}}}description", _text_field(fields, "description"))
    expression = _text_field(fields, "expression") or _text_field(
        fields, "ui_expression"
    )
    _add_text(element, f"{{{APPIAN_NS}}}uiExpr", expression)
    _add_text(element, f"{{{APPIAN_NS}}}urlStub", _text_field(fields, "url_stub"))
    _role_map(root, TEMPO_REPORT_ROLE_NAMES, content_style=False)
    _history(root, version_uuid)
    return _serialize(root, standalone=True)


def _build_report(uuid: str, name: str, fields: dict[str, object]) -> bytes:
    root, element, version_uuid = _haul("contentHaul", "report", fields, _NS_A)
    _add_text(element, "name", name)
    _add_text(element, "uuid", uuid)
    _add_text(element, "description", _text_field(fields, "description"))
    _add_text(element, "parentUuid", _text_field(fields, "parent_uuid"))
    # ponytail: no <visibility> or <reportData>; copy the real blocks when a
    # generated report must define its own columns instead of identity only.
    _role_map(root, CONTENT_ROLE_NAMES, content_style=True)
    _history(root, version_uuid)
    return _serialize(root, standalone=True)


_Builder = Callable[[str, str, dict[str, object]], bytes]
_BUILDERS: dict[ObjectType, _Builder] = {
    ObjectType.SITE: _build_site,
    ObjectType.PORTAL: _build_portal,
    ObjectType.REPORT: _build_report,
    ObjectType.TEMPO_REPORT: _build_tempo_report,
}


def build_native_experience_xml(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> bytes:
    """Build importable XML for one Appian experience object with a proven shape."""
    if not uuid.strip():
        raise ValueError("uuid must not be empty")
    if not name.strip():
        raise ValueError("name must not be empty")
    if object_type in _UNPROVEN_TYPES:
        raise ValueError(
            f"No Appian export sample available for {object_type.value}; "
            "create it in Appian and import the export to enable this operation."
        )
    try:
        builder = _BUILDERS[object_type]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported native experience type: {object_type.value}"
        ) from exc
    return builder(uuid, name, fields)
