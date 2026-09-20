"""Build native XML for Appian process-related design objects.

Every element name, attribute and sibling order below is copied from real
Appian export files (``processModel/*.xml``, ``processModelFolder/*.xml``).
Object types with no proven export shape are rejected instead of guessed.
"""

from __future__ import annotations

from uuid import uuid4

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType

APPIAN_NS = "http://www.appian.com/ae/types/2009"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# process_model_port carries this exact schemaVersion in every corpus file.
PM_SCHEMA_VERSION = "007.000.004"

# roleMap role order is identical in processModel and processModelFolder exports.
ROLE_NAMES: tuple[str, ...] = (
    "ADMIN_OWNER",
    "EDITOR",
    "EXPLICIT_NONMEMBER",
    "VIEWER",
    "MANAGER",
    "INITIATOR",
)

# Types with no proven export XML in any local Appian package we have seen.
_UNPROVEN_TYPES: frozenset[ObjectType] = frozenset(
    {
        ObjectType.BUSINESS_PROCESS,
        ObjectType.PROCESS_REPORT,
        ObjectType.ROBOTIC_TASK,
        ObjectType.ROBOT_POOL,
    }
)


def _plain(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    """Append a child in no namespace (processModelHaul body style)."""
    element = etree.SubElement(parent, tag)
    if text is not None:
        element.text = text
    return element


def _ns(
    parent: etree._Element,
    tag: str,
    text: str | None = None,
    **attributes: str,
) -> etree._Element:
    """Append a child in the Appian namespace (process_model_port body style)."""
    element = etree.SubElement(parent, f"{{{APPIAN_NS}}}{tag}", **attributes)
    if text is not None:
        element.text = text
    return element


def _cdata(parent: etree._Element, tag: str, value: str) -> etree._Element:
    """Append an Appian-namespaced child whose text is a CDATA section.

    Real exports wrap uuid, name values, timeZoneId and activity names in
    CDATA, and use a self-closing element when the value is empty.
    """
    element = _ns(parent, tag)
    if value:
        element.text = etree.CDATA(value)
    return element


def _locale_string_map(
    parent: etree._Element,
    tag: str,
    value: str,
    *,
    localized: bool,
) -> None:
    """Append ``<tag><string-map><pair><locale/><value/></pair>...``.

    ``localized`` selects the real en-US locale attributes
    (``country="US" lang="en" variant=""``) used by meta name/process-name.
    Node labels and empty descriptions instead carry a bare ``<locale/>``.
    """
    pair = _ns(_ns(_ns(parent, tag), "string-map"), "pair")
    if localized:
        _ns(pair, "locale", country="US", lang="en", variant="")
    else:
        _ns(pair, "locale")
    _cdata(pair, "value", value)


def _label(parent: etree._Element, *, bold: bool) -> None:
    """Append the shared font <label> block used by nodes, lanes and edges."""
    label = _ns(parent, "label")
    _ns(label, "fontColor", "#000000")
    _ns(label, "fontFamily", "Appian Open Sans, Sans-Serif")
    _ns(label, "fontSize", "12")
    _ns(label, "bold", "true" if bold else "false")
    _ns(label, "italics", "false")
    _ns(label, "underline", "false")


def _deadline(parent: etree._Element) -> None:
    """Append the disabled <deadline> block used by meta and every node."""
    deadline = _ns(parent, "deadline")
    _ns(deadline, "enabled", "false")
    _ns(deadline, "type", "0")
    _ns(deadline, "units", "0")
    _ns(deadline, "rex")
    _ns(deadline, "aex")


def _role_map(parent: etree._Element) -> None:
    """Append the six-role <roleMap> in real corpus order (no namespace).

    Members stay empty: group membership belongs to the target environment, not
    to generated XML.
    """
    role_map = _plain(parent, "roleMap")
    for role_name in ROLE_NAMES:
        role = etree.SubElement(role_map, "role", name=role_name)
        _plain(role, "users")
        _plain(role, "groups")


def _serialize(root: etree._Element, standalone: bool | None) -> bytes:
    """Serialize with the XML declaration the matching corpus files use.

    processModel exports omit standalone; processModelFolder exports set it.
    """
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=standalone,
        pretty_print=True,
    )


def _field_text(fields: dict[str, object], key: str) -> str:
    value = fields.get(key, "")
    return "" if value is None else str(value)


def _build_meta(pm: etree._Element, uuid: str, name: str, description: str) -> None:
    """Append <meta> with every field the real corpus always carries, in order."""
    meta = _ns(pm, "meta")
    _cdata(meta, "uuid", uuid)
    _locale_string_map(meta, "name", name, localized=True)
    _locale_string_map(meta, "desc", description, localized=bool(description))
    _ns(meta, "versionStatus", "2")
    _locale_string_map(meta, "process-name", name, localized=True)
    _deadline(meta)
    notifications = _ns(meta, "pm-notification-settings")
    _ns(notifications, "custom-settings", "false")
    _ns(notifications, "notify-initiator", "false")
    _ns(notifications, "notify-owner", "false")
    _ns(notifications, "usersandgroups")
    _ns(notifications, "recipients-exp")
    _ns(meta, "cleanup-action", "3")
    _ns(meta, "auto-archive-delay", "7")
    _ns(meta, "auto-delete-delay", "0")
    _cdata(meta, "timeZoneId", "GMT")
    _ns(meta, "useProcessInitiatorTimeZone", "true")


def _build_connection(node: etree._Element, target_gui_id: str) -> None:
    """Append <connections><connection> in real child order."""
    connection = _ns(_ns(node, "connections"), "connection")
    _ns(connection, "guiId", "2")
    _ns(connection, "to", target_gui_id)
    _ns(connection, "toObjectType", "ap.gui.Node")
    _ns(connection, "fromAnchor")
    _ns(connection, "toAnchor")
    _ns(connection, "showArrowhead", "true")
    _ns(connection, "flowLabel")
    _label(connection, bold=False)
    _ns(connection, "associations")
    _ns(connection, "chained", "false")
    _ns(connection, "overridesAssignment", "true")
    _ns(connection, "synchronizeData", "false")


def _build_node(
    nodes: etree._Element,
    *,
    node_uuid: str,
    gui_id: str,
    icon_id: str,
    activity_local_id: str,
    activity_name: str,
    x: str,
    target_gui_id: str | None,
) -> None:
    """Append one <node> with the full child order taken from the corpus."""
    node = _ns(nodes, "node", uuid=node_uuid)
    _ns(node, "guiId", gui_id)
    _ns(node, "owner")
    _ns(node, "icon", id=icon_id)
    _ns(node, "picon", id="0")
    _locale_string_map(node, "fname", activity_name, localized=False)
    _ns(node, "x", x)
    _ns(node, "y", "98")
    _locale_string_map(node, "display", activity_name, localized=False)
    _locale_string_map(node, "desc", "", localized=False)
    _ns(node, "notify", "false")
    _ns(node, "confirmation-url")
    _ns(node, "lane", "0")
    _ns(node, "overrideLaneAssignment", "false")

    activity = _ns(node, "ac")
    _ns(activity, "local-id", activity_local_id)
    _cdata(activity, "name", activity_name)
    # ponytail: <acps/> left empty; copy the real End Node acp block if a
    # published model ever needs its pmID/inMap/pmUUID parameters.
    _ns(activity, "acps")
    _ns(activity, "custom-params")
    _ns(activity, "output-exprs")
    _ns(activity, "requires-user-interaction", "true")
    _ns(_ns(activity, "run-as"), "performer", id="0")
    _ns(activity, "form-map")
    _ns(activity, "helper-class")

    _ns(node, "multiple-instance")
    _ns(node, "escalations")
    if target_gui_id is None:
        _ns(node, "connections")
    else:
        _build_connection(node, target_gui_id)
    _ns(node, "associations")
    _ns(node, "target-completion", "5.0")
    _ns(node, "target-lag", "1.0")
    _ns(node, "attachments")
    _ns(node, "notes")
    _ns(node, "lingering", "false")
    _ns(node, "on-create-ignore-if-active", "false")
    _ns(node, "on-create-delete-previous-active", "false")
    _ns(node, "on-complete-delete-previous-completed", "false")
    _ns(node, "pre-triggers")
    _ns(node, "post-triggers")
    _ns(node, "event-producers")
    _ns(node, "exception-flow")
    _label(node, bold=False)
    _deadline(node)
    _ns(node, "allowsBack", "false")
    _ns(node, "refreshDefaultValues", "false")
    _ns(node, "on-complete-keep-form-data", "false")
    _ns(node, "skipNotification", "false")


def _build_lane(pm: etree._Element) -> None:
    """Append <lanes><lane> with the enriched child set from the corpus."""
    lane = _ns(_ns(pm, "lanes"), "lane")
    _cdata(lane, "laneLabel", "System")
    _ns(lane, "dimension", "333")
    _ns(lane, "color", "#07ab57")
    _ns(lane, "isVertical", "false")
    _ns(lane, "isLaneAssignment", "true")
    _ns(lane, "unattended", "1")
    _ns(lane, "runAs", "1")
    _label(lane, bold=True)


def _build_process_model(uuid: str, name: str, fields: dict[str, object]) -> bytes:
    folder_uuid = _field_text(fields, "folder_uuid")
    if not folder_uuid:
        raise ValueError(
            "process_model requires folder_uuid: every real processModel export "
            "carries a <folderUuid> naming its process model folder."
        )

    # Real root element declares no namespace at all.
    root = etree.Element("processModelHaul")
    version_uuid = str(uuid4())
    _plain(root, "versionUuid", version_uuid)
    _plain(root, "folderUuid", folder_uuid)
    _role_map(root)

    port = etree.SubElement(
        root,
        f"{{{APPIAN_NS}}}process_model_port",
        schemaVersion=PM_SCHEMA_VERSION,
        nsmap={None: APPIAN_NS, "a": APPIAN_NS, "xsd": XSD_NS, "xsi": XSI_NS},
    )
    pm = _ns(port, "pm")
    _build_meta(pm, uuid, name, _field_text(fields, "description"))
    _ns(pm, "pvs")

    nodes = _ns(pm, "nodes")
    _build_node(
        nodes,
        node_uuid=str(uuid4()),
        gui_id="0",
        icon_id="50",
        activity_local_id="core.0",
        activity_name="Start Node",
        x="100",
        target_gui_id="1",
    )
    _build_node(
        nodes,
        node_uuid=str(uuid4()),
        gui_id="1",
        icon_id="51",
        activity_local_id="core.1",
        activity_name="End Node",
        x="800",
        target_gui_id=None,
    )

    _ns(pm, "annotations")
    _build_lane(pm)
    _ns(pm, "attachments")
    _ns(pm, "notes")
    _ns(pm, "priority", id="1")
    _ns(pm, "form-map")
    _ns(pm, "isPublic", "false")
    _ns(pm, "isEPEx", "false")

    _plain(root, "isPublished", "true")
    _plain(root, "mcpEnabled", "false")
    _plain(_plain(root, "history"), "historyInfo").set("versionUuid", version_uuid)
    return _serialize(root, standalone=None)


def _build_process_model_folder(
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> bytes:
    # Real root declares only the a: prefix, never a default namespace.
    root = etree.Element("processModelFolderHaul", nsmap={"a": APPIAN_NS})
    version_uuid = str(uuid4())
    _plain(root, "versionUuid", version_uuid)

    folder = _plain(root, "processModelFolder")
    _plain(folder, "name", name)
    _plain(folder, "uuid", uuid)
    description = _field_text(fields, "description")
    if description:
        _plain(folder, "description", description)
    parent_folder_uuid = _field_text(fields, "parent_folder_uuid")
    if parent_folder_uuid:
        _plain(folder, "parentFolderUuid", parent_folder_uuid)

    _role_map(root)
    _plain(_plain(root, "history"), "historyInfo").set("versionUuid", version_uuid)
    return _serialize(root, standalone=True)


def build_native_process_xml(
    object_type: ObjectType,
    uuid: str,
    name: str,
    fields: dict[str, object],
) -> bytes:
    """Build XML for one process-related Appian object with a proven shape."""
    if object_type is ObjectType.PROCESS_MODEL:
        return _build_process_model(uuid, name, fields)
    if object_type is ObjectType.PROCESS_MODEL_FOLDER:
        return _build_process_model_folder(uuid, name, fields)
    if object_type in _UNPROVEN_TYPES:
        raise ValueError(
            f"No Appian export sample available for {object_type.value}; "
            "create it in Appian and import the export to enable this operation."
        )
    raise ValueError(f"Unsupported native process object type: {object_type.value}")
