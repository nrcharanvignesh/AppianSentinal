"""Parse individual Appian XML export files into typed model objects.

Uses ``lxml.etree`` for robust XML parsing with namespace and XPath support.
Each top-level directory in the export maps to a dedicated parse function.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lxml import etree

from appian_sentinel.models.appian_objects import (
    AppianObject,
    ConnectedSystem,
    Constant,
    DataStore,
    DataStoreEntity,
    DataType,
    Decision,
    Document,
    ExpressionRule,
    Folder,
    Group,
    Interface,
    ObjectType,
    OutboundIntegration,
    OutputMetadata,
    ProcessModel,
    ProcessNode,
    ProcessVariable,
    RecordAction,
    RecordField,
    RecordRelationship,
    RecordType,
    RuleInput,
    RulesFolder,
    SecurityRole,
    Site,
    SitePage,
    WebApi,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XML namespace constants
# ---------------------------------------------------------------------------

APPIAN_NS = "http://www.appian.com/ae/types/2009"
XSD_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

NS_MAP = {
    "a": APPIAN_NS,
    "xsd": XSD_NS,
    "xsi": XSI_NS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(element: etree._Element | None) -> str:
    """Return the text content of an element, or empty string if None."""
    if element is None:
        return ""
    return (element.text or "").strip()


def _text_or_cdata(element: etree._Element | None) -> str:
    """Return text content including CDATA sections."""
    if element is None:
        return ""
    # lxml transparently handles CDATA — just return .text
    return element.text or ""


def _bool_text(element: etree._Element | None, default: bool = False) -> bool:
    """Parse a boolean text element like ``<offlineEnabled>false</offlineEnabled>``."""
    t = _text(element).lower()
    if t in ("true", "1", "yes"):
        return True
    if t in ("false", "0", "no"):
        return False
    return default


def _find(parent: etree._Element, tag: str) -> etree._Element | None:
    """Find a direct child element, trying both with and without namespace."""
    # Try without namespace first (most content/group/site XML)
    el = parent.find(tag)
    if el is not None:
        return el
    # Try with Appian namespace
    el = parent.find(f"{{{APPIAN_NS}}}{tag}")
    if el is not None:
        return el
    # Try with a: prefix via XPath
    el_list = parent.xpath(f"a:{tag}", namespaces=NS_MAP)
    if el_list:
        return el_list[0]
    return None


def _findall(parent: etree._Element, tag: str) -> list[etree._Element]:
    """Find all direct children matching tag, with or without namespace."""
    result = parent.findall(tag)
    if result:
        return result
    result = parent.findall(f"{{{APPIAN_NS}}}{tag}")
    if result:
        return result
    result = parent.xpath(f"a:{tag}", namespaces=NS_MAP)
    return result


def _parse_xml_file(xml_path: Path) -> etree._Element | None:
    """Parse an XML file and return the root element, or None on failure."""
    try:
        parser = etree.XMLParser(
            recover=True,
            remove_comments=True,
            huge_tree=True,
        )
        tree = etree.parse(str(xml_path), parser)
        return tree.getroot()
    except Exception:
        logger.warning("Failed to parse XML file: %s", xml_path, exc_info=True)
        return None


def _get_en_us_value(string_map_el: etree._Element | None) -> str:
    """Extract the en_US value from a ``<string-map>`` element used in process models.

    Process model names/descriptions are stored as locale-keyed maps:
    ``<string-map><pair><locale country="US" lang="en" .../><value>...</value></pair>...</string-map>``
    """
    if string_map_el is None:
        return ""
    for pair in string_map_el.findall("pair"):
        locale_el = pair.find("locale")
        if locale_el is not None:
            lang = locale_el.get("lang", "")
            country = locale_el.get("country", "")
            if lang == "en" and country == "US":
                return _text_or_cdata(pair.find("value"))
    # Fallback: return first non-empty value
    for pair in string_map_el.findall("pair"):
        val = _text_or_cdata(pair.find("value"))
        if val:
            return val
    return ""


# ---------------------------------------------------------------------------
# Security / role map parsing (shared across all types)
# ---------------------------------------------------------------------------

def _parse_role_map(role_map_el: etree._Element | None) -> list[SecurityRole]:
    """Parse a ``<roleMap>`` element into a list of SecurityRole objects.

    Handles both content-style (``<role inherit="true" ...>``) and
    process-model-style (``<role name="ADMIN_OWNER">``).
    """
    if role_map_el is None:
        return []
    roles: list[SecurityRole] = []
    for role_el in role_map_el.findall("role"):
        role_name = role_el.get("name", "")
        inherit = role_el.get("inherit", "false").lower() == "true"
        allow_for_all = role_el.get("allowForAll", "false").lower() == "true"

        users: list[str] = []
        groups: list[str] = []

        users_el = role_el.find("users")
        if users_el is not None:
            for user_el in users_el:
                u = _text(user_el)
                if u:
                    users.append(u)

        groups_el = role_el.find("groups")
        if groups_el is not None:
            for group_el in groups_el:
                g = _text(group_el)
                if g:
                    groups.append(g)

        roles.append(SecurityRole(
            role_name=role_name,
            users=users,
            groups=groups,
            inherit=inherit,
            allow_for_all=allow_for_all,
        ))
    return roles


# ---------------------------------------------------------------------------
# Rule input parsing (shared by rule, interface, decision)
# ---------------------------------------------------------------------------

def _parse_named_typed_values(parent_el: etree._Element) -> list[RuleInput]:
    """Parse ``<namedTypedValue>`` elements into RuleInput objects."""
    inputs: list[RuleInput] = []
    for ntv in _findall(parent_el, "namedTypedValue"):
        name = _text(_find(ntv, "name"))
        type_el = _find(ntv, "type")
        type_name = ""
        type_namespace = ""
        is_list = False
        if type_el is not None:
            raw_type_name = _text(_find(type_el, "name"))
            type_namespace = _text(_find(type_el, "namespace"))
            if raw_type_name.endswith("?list"):
                is_list = True
                raw_type_name = raw_type_name[:-5]
            type_name = raw_type_name
        if name:
            inputs.append(RuleInput(
                name=name,
                type_name=type_name,
                type_namespace=type_namespace,
                is_list=is_list,
            ))
    return inputs


# ---------------------------------------------------------------------------
# Content parsers  (content/ directory)
# ---------------------------------------------------------------------------

def parse_content_xml(xml_path: Path) -> AppianObject | None:
    """Parse a content XML file and dispatch to the correct sub-type parser.

    The discriminator element directly inside ``<contentHaul>`` determines
    the sub-type: ``<rule>``, ``<interface>``, ``<constant>``, ``<decision>``,
    ``<document>``, ``<folder>``, ``<rulesFolder>``, ``<outboundIntegration>``.
    """
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    file_str = str(xml_path)

    # Detect discriminator element
    discriminator_map = {
        "rule": _parse_expression_rule,
        "interface": _parse_interface,
        "constant": _parse_constant,
        "decision": _parse_decision,
        "document": _parse_document,
        "folder": _parse_folder,
        "rulesFolder": _parse_rules_folder,
        "outboundIntegration": _parse_outbound_integration,
        "communityKnowledgeCenter": _parse_folder_generic,
        "report": _parse_generic_content,
    }

    for tag, parser_fn in discriminator_map.items():
        el = root.find(tag)
        if el is not None:
            role_map = _parse_role_map(root.find("roleMap"))
            obj = parser_fn(el, root)
            obj.version_uuid = version_uuid
            obj.file_path = file_str
            obj.security_roles = role_map
            return obj

    # Fallback: try to extract basic info from any first-child element
    for child in root:
        if child.tag == "versionUuid" or child.tag == "roleMap" or child.tag == "history":
            continue
        if child.tag == "file":
            continue
        # Treat any unrecognised discriminator as a generic folder-like object
        logger.debug("Treating unknown content subtype <%s> as folder in %s", child.tag, xml_path)
        role_map = _parse_role_map(root.find("roleMap"))
        obj = _parse_folder_generic(child, root)
        obj.version_uuid = version_uuid
        obj.file_path = file_str
        obj.security_roles = role_map
        return obj

    logger.warning("Could not parse any content subtype from %s", xml_path)
    return None


def _parse_expression_rule(rule_el: etree._Element, root: etree._Element) -> ExpressionRule:
    """Parse a ``<rule>`` element into an ExpressionRule."""
    return ExpressionRule(
        uuid=_text(_find(rule_el, "uuid")),
        name=_text(_find(rule_el, "name")),
        description=_text(_find(rule_el, "description")),
        parent_uuid=_text(_find(rule_el, "parentUuid")),
        definition=_text_or_cdata(_find(rule_el, "definition")),
        rule_inputs=_parse_named_typed_values(rule_el),
        preferred_editor=_text(_find(rule_el, "preferredEditor")),
        offline_enabled=_bool_text(_find(rule_el, "offlineEnabled")),
    )


def _parse_interface(iface_el: etree._Element, root: etree._Element) -> Interface:
    """Parse an ``<interface>`` element into an Interface."""
    return Interface(
        uuid=_text(_find(iface_el, "uuid")),
        name=_text(_find(iface_el, "name")),
        description=_text(_find(iface_el, "description")),
        parent_uuid=_text(_find(iface_el, "parentUuid")),
        definition=_text_or_cdata(_find(iface_el, "definition")),
        rule_inputs=_parse_named_typed_values(iface_el),
        preferred_editor=_text(_find(iface_el, "preferredEditor")),
        offline_enabled=_bool_text(_find(iface_el, "offlineEnabled")),
        is_custom=_bool_text(_find(iface_el, "isCustom")),
    )


def _parse_constant(const_el: etree._Element, root: etree._Element) -> Constant:
    """Parse a ``<constant>`` element into a Constant."""
    value = ""
    value_type = ""
    value_type_ns = ""
    typed_val_el = _find(const_el, "typedValue")
    if typed_val_el is not None:
        type_el = _find(typed_val_el, "type")
        if type_el is not None:
            value_type = _text(_find(type_el, "name"))
            value_type_ns = _text(_find(type_el, "namespace"))
        value = _text(_find(typed_val_el, "value"))

    return Constant(
        uuid=_text(_find(const_el, "uuid")),
        name=_text(_find(const_el, "name")),
        description=_text(_find(const_el, "description")),
        parent_uuid=_text(_find(const_el, "parentUuid")),
        value=value,
        value_type=value_type,
        value_type_namespace=value_type_ns,
        is_environment_specific=_bool_text(_find(const_el, "isEnvironmentSpecific")),
    )


def _parse_decision(dec_el: etree._Element, root: etree._Element) -> Decision:
    """Parse a ``<decision>`` element into a Decision."""
    outputs: list[OutputMetadata] = []
    output_list_el = _find(dec_el, "outputMetadataList")
    if output_list_el is not None:
        for om_el in _findall(output_list_el, "outputMetadata"):
            outputs.append(OutputMetadata(
                output_id=_text(_find(om_el, "outputId")),
                name_ref=_text(_find(om_el, "nameRef")),
                type_name=_text(_find(om_el, "typeName")),
            ))

    return Decision(
        uuid=_text(_find(dec_el, "uuid")),
        name=_text(_find(dec_el, "name")),
        description=_text(_find(dec_el, "description")),
        parent_uuid=_text(_find(dec_el, "parentUuid")),
        definition=_text_or_cdata(_find(dec_el, "definition")),
        rule_inputs=_parse_named_typed_values(dec_el),
        preferred_editor=_text(_find(dec_el, "preferredEditor")),
        offline_enabled=_bool_text(_find(dec_el, "offlineEnabled")),
        output_metadata=outputs,
        hit_policy=_text(_find(dec_el, "hitPolicy")),
    )


def _parse_document(doc_el: etree._Element, root: etree._Element) -> Document:
    """Parse a ``<document>`` element into a Document."""
    name = _text(_find(doc_el, "name"))
    # The <file> element is a sibling of <document> under <contentHaul>
    file_el = root.find("file")
    file_name = _text(file_el) if file_el is not None else ""
    ext = ""
    if file_name and "." in file_name:
        ext = file_name.rsplit(".", 1)[-1]

    return Document(
        uuid=_text(_find(doc_el, "uuid")),
        name=name,
        description=_text(_find(doc_el, "description")),
        parent_uuid=_text(_find(doc_el, "parentUuid")),
        file_name=file_name,
        file_extension=ext,
    )


def _parse_folder(folder_el: etree._Element, root: etree._Element) -> Folder:
    """Parse a ``<folder>`` element into a Folder."""
    return Folder(
        uuid=_text(_find(folder_el, "uuid")),
        name=_text(_find(folder_el, "name")),
        description=_text(_find(folder_el, "description")),
        parent_uuid=_text(_find(folder_el, "parentUuid")),
    )


def _parse_folder_generic(el: etree._Element, root: etree._Element) -> Folder:
    """Parse any folder-like element (communityKnowledgeCenter, etc.) into a Folder."""
    return Folder(
        uuid=_text(_find(el, "uuid")),
        name=_text(_find(el, "name")),
        description=_text(_find(el, "description")),
        parent_uuid=_text(_find(el, "parentUuid")),
    )


def _parse_generic_content(el: etree._Element, root: etree._Element) -> AppianObject:
    """Parse any unrecognised content subtype (report, etc.) as a generic AppianObject."""
    return AppianObject(
        uuid=_text(_find(el, "uuid")),
        name=_text(_find(el, "name")),
        description=_text(_find(el, "description")),
        parent_uuid=_text(_find(el, "parentUuid")),
        object_type=ObjectType.UNKNOWN,
    )


def _parse_rules_folder(rf_el: etree._Element, root: etree._Element) -> RulesFolder:
    """Parse a ``<rulesFolder>`` element into a RulesFolder."""
    return RulesFolder(
        uuid=_text(_find(rf_el, "uuid")),
        name=_text(_find(rf_el, "name")),
        description=_text(_find(rf_el, "description")),
        parent_uuid=_text(_find(rf_el, "parentUuid")),
    )


def _parse_outbound_integration(oi_el: etree._Element, root: etree._Element) -> OutboundIntegration:
    """Parse an ``<outboundIntegration>`` element."""
    http_method = ""
    config_el = _find(oi_el, "configParameters")
    if config_el is not None:
        # The method is inside a Dictionary element
        for child in config_el.iter():
            local_name = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
            if local_name == "method":
                http_method = _text(child)
                break

    return OutboundIntegration(
        uuid=_text(_find(oi_el, "uuid")),
        name=_text(_find(oi_el, "name")),
        description=_text(_find(oi_el, "description")),
        parent_uuid=_text(_find(oi_el, "parentUuid")),
        definition=_text_or_cdata(_find(oi_el, "definition")),
        preferred_editor=_text(_find(oi_el, "preferredEditor")),
        offline_enabled=_bool_text(_find(oi_el, "offlineEnabled")),
        http_method=http_method,
        connected_system_uuid=_text(_find(oi_el, "connectedSystemUuid")),
        integration_type=_text(_find(oi_el, "integrationType")),
    )


# ---------------------------------------------------------------------------
# Record type parser (recordType/ directory)
# ---------------------------------------------------------------------------

def parse_record_type_xml(xml_path: Path) -> RecordType | None:
    """Parse a record type XML file into a RecordType object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    role_map = _parse_role_map(root.find("roleMap"))

    # The <recordType> element has attributes a:uuid and name
    rt_el = root.find("recordType")
    if rt_el is None:
        rt_el = root.find(f"{{{APPIAN_NS}}}recordType")
    if rt_el is None:
        logger.warning("No <recordType> element in %s", xml_path)
        return None

    uuid = rt_el.get(f"{{{APPIAN_NS}}}uuid", "") or rt_el.get("uuid", "")
    name = rt_el.get("name", "")

    # Parse fields from <sourceConfiguration><field> elements
    fields: list[RecordField] = []
    source_config_el = _find(rt_el, "sourceConfiguration")
    source_type = ""
    source_uuid = ""
    friendly_name = ""
    if source_config_el is None:
        source_config_el = rt_el.find(f"{{{APPIAN_NS}}}sourceConfiguration")

    if source_config_el is not None:
        source_type = _text(source_config_el.find("sourceType"))
        source_uuid = _text(source_config_el.find("sourceUuid"))
        friendly_name = _text(source_config_el.find("friendlyName"))

        for field_el in source_config_el.findall("field"):
            fields.append(RecordField(
                uuid=_text(field_el.find("uuid")),
                name=_text(field_el.find("fieldName")),
                display_name=_text(field_el.find("displayName")),
                type=_text(field_el.find("type")),
                source_field_name=_text(field_el.find("sourceFieldName")),
                source_field_type=_text(field_el.find("sourceFieldType")),
                is_primary_key=_bool_text(field_el.find("isRecordId")),
                is_unique=_bool_text(field_el.find("isUnique")),
                is_hidden=_bool_text(field_el.find("isHidden")),
                is_custom_field=_bool_text(field_el.find("isCustomField")),
            ))

    # Parse relationships
    relationships: list[RecordRelationship] = []
    for rel_el in rt_el.findall(f"{{{APPIAN_NS}}}relationship") + rt_el.findall("relationship"):
        rel_uuid = _text(rel_el.find("uuid")) or rel_el.get("uuid", "")
        rel_name = _text(rel_el.find("name")) or rel_el.get("name", "")
        related_rt = _text(rel_el.find("relatedRecordType")) or _text(
            rel_el.find(f"{{{APPIAN_NS}}}relatedRecordType")
        )
        rel_type = _text(rel_el.find("type")) or _text(
            rel_el.find(f"{{{APPIAN_NS}}}type")
        )
        if rel_uuid or rel_name:
            relationships.append(RecordRelationship(
                uuid=rel_uuid,
                name=rel_name,
                related_record_type_uuid=related_rt,
                relationship_type=rel_type,
            ))

    # Parse record actions
    record_actions: list[RecordAction] = []
    for ra_el in rt_el.findall(f"{{{APPIAN_NS}}}recordAction") + rt_el.findall("recordAction"):
        ra_uuid = ra_el.get(f"{{{APPIAN_NS}}}uuid", "") or ra_el.get("uuid", "")
        ra_name = _text(_find(ra_el, "nameExpr")) or _text(_find(ra_el, "name"))
        pm_uuid_el = _find(ra_el, "processModel")
        pm_uuid = ""
        if pm_uuid_el is not None:
            pm_uuid = pm_uuid_el.get(f"{{{APPIAN_NS}}}uuid", "") or pm_uuid_el.get("uuid", "") or _text(pm_uuid_el)
        record_actions.append(RecordAction(
            uuid=ra_uuid,
            name=ra_name,
            process_model_uuid=pm_uuid,
        ))

    # Extract SAIL expressions
    list_view_expr = _text_or_cdata(_find(rt_el, "listViewTemplateExpr"))
    title_expr = _text_or_cdata(_find(rt_el, "titleExpr"))
    plural_name = _text(_find(rt_el, "pluralName"))
    description = _text(_find(rt_el, "description"))
    url_stub = _text(_find(rt_el, "urlStub"))
    layout_type = _text(_find(rt_el, "layoutType"))

    return RecordType(
        uuid=uuid,
        name=name,
        description=description,
        version_uuid=version_uuid,
        file_path=str(xml_path),
        security_roles=role_map,
        plural_name=plural_name,
        url_stub=url_stub,
        source_type=source_type,
        source_uuid=source_uuid,
        friendly_name=friendly_name,
        layout_type=layout_type,
        fields=fields,
        relationships=relationships,
        record_actions=record_actions,
        list_view_expr=list_view_expr,
        title_expr=title_expr,
    )


# ---------------------------------------------------------------------------
# Process model parser (processModel/ directory)
# ---------------------------------------------------------------------------

def parse_process_model_xml(xml_path: Path) -> ProcessModel | None:
    """Parse a process model XML file into a ProcessModel object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    folder_uuid = _text(root.find("folderUuid"))
    role_map = _parse_role_map(root.find("roleMap"))

    # The actual PM data is inside <process_model_port><pm>
    pm_port = root.find("process_model_port")
    if pm_port is None:
        pm_port = root.find(f"{{{APPIAN_NS}}}process_model_port")
    if pm_port is None:
        logger.warning("No <process_model_port> in %s", xml_path)
        return None

    # pm_port may have a default namespace
    # Find <pm> inside, handling namespace
    pm_el = pm_port.find("pm")
    if pm_el is None:
        pm_el = pm_port.find(f"{{{APPIAN_NS}}}pm")
    if pm_el is None:
        # Try with wildcard namespace
        for child in pm_port:
            local = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
            if local == "pm":
                pm_el = child
                break
    if pm_el is None:
        logger.warning("No <pm> element in %s", xml_path)
        return None

    # Extract meta info
    meta_el = pm_el.find("meta")
    if meta_el is None:
        meta_el = pm_el.find(f"{{{APPIAN_NS}}}meta")

    uuid = ""
    name = ""
    description = ""
    notification_expr = ""
    process_name_expr = ""

    if meta_el is not None:
        uuid_el = meta_el.find("uuid")
        if uuid_el is None:
            uuid_el = meta_el.find(f"{{{APPIAN_NS}}}uuid")
        uuid = _text_or_cdata(uuid_el)

        # Name is in <name><string-map>...
        name_el = meta_el.find("name")
        if name_el is not None:
            sm = name_el.find("string-map")
            name = _get_en_us_value(sm)

        desc_el = meta_el.find("desc")
        if desc_el is not None:
            sm = desc_el.find("string-map")
            description = _get_en_us_value(sm)

        # Process display name expression
        pn_el = meta_el.find("process-name")
        if pn_el is not None:
            sm = pn_el.find("string-map")
            process_name_expr = _get_en_us_value(sm)

        # Notification recipients expression
        notif_el = meta_el.find("pm-notification-settings")
        if notif_el is not None:
            recip_el = notif_el.find("recipients-exp")
            notification_expr = _text_or_cdata(recip_el)

    # Parse process variables
    pvs: list[ProcessVariable] = []
    pvs_el = pm_el.find("pvs")
    if pvs_el is None:
        pvs_el = pm_el.find(f"{{{APPIAN_NS}}}pvs")
    if pvs_el is not None:
        for pv_el in pvs_el:
            local_name = etree.QName(pv_el.tag).localname if isinstance(pv_el.tag, str) else ""
            if local_name != "pv":
                continue
            pv_name = pv_el.get("name", "")
            # Type is in the xsi:type attribute of the <a:value> child
            pv_type = ""
            val_el = pv_el.find(f"{{{APPIAN_NS}}}value")
            if val_el is not None:
                pv_type = val_el.get(f"{{{XSI_NS}}}type", "")
            is_param = _bool_text(pv_el.find("parameter"))
            is_required = _bool_text(pv_el.find("required"))
            is_hidden = _bool_text(pv_el.find("hidden"))
            if pv_name:
                pvs.append(ProcessVariable(
                    name=pv_name,
                    type=pv_type,
                    is_parameter=is_param,
                    is_required=is_required,
                    is_hidden=is_hidden,
                ))

    # Parse nodes
    nodes: list[ProcessNode] = []
    nodes_el = pm_el.find("nodes")
    if nodes_el is None:
        nodes_el = pm_el.find(f"{{{APPIAN_NS}}}nodes")
    if nodes_el is not None:
        for node_el in nodes_el:
            local_tag = etree.QName(node_el.tag).localname if isinstance(node_el.tag, str) else ""
            if local_tag != "node":
                continue
            node_uuid = node_el.get("uuid", "")
            # Node name in string-map
            node_name = ""
            fname_el = node_el.find("fname")
            if fname_el is not None:
                sm = fname_el.find("string-map")
                node_name = _get_en_us_value(sm)

            # Collect all text that might contain UUID refs as expressions
            expressions: list[str] = []
            for descendant in node_el.iter():
                if descendant.text:
                    text = descendant.text.strip()
                    if '#"' in text:
                        expressions.append(text)

            nodes.append(ProcessNode(
                uuid=node_uuid,
                name=node_name,
                expressions=expressions,
            ))

    return ProcessModel(
        uuid=uuid,
        name=name,
        description=description,
        version_uuid=version_uuid,
        file_path=str(xml_path),
        folder_uuid=folder_uuid,
        security_roles=role_map,
        nodes=nodes,
        process_variables=pvs,
        notification_recipients_expr=notification_expr,
        process_name_expr=process_name_expr,
    )


# ---------------------------------------------------------------------------
# Data type parser (datatype/ directory — XSD files)
# ---------------------------------------------------------------------------

def parse_datatype_xml(xsd_path: Path) -> DataType | None:
    """Parse an XSD file (CDT definition) into a DataType object.

    Datatype files are XSD schemas, not the ``*Haul`` XML format. The UUID
    is encoded in the filename (URL-encoded namespace + type name), and the
    schema itself contains type/field information.
    """
    root = _parse_xml_file(xsd_path)
    if root is None:
        return None

    # Extract namespace from targetNamespace
    namespace = root.get("targetNamespace", "")

    # The complex type element holds the CDT definition
    complex_types = root.findall(f"{{{XSD_NS}}}complexType")
    if not complex_types:
        logger.warning("No complexType found in %s", xsd_path)
        return None

    ct = complex_types[0]
    type_name = ct.get("name", "")

    # Extract table name from annotation
    table_name = ""
    annotation_el = ct.find(f"{{{XSD_NS}}}annotation")
    if annotation_el is not None:
        for appinfo in annotation_el.findall(f"{{{XSD_NS}}}appinfo"):
            source = appinfo.get("source", "")
            if source == "appian.jpa" and appinfo.text:
                # Parse @Table(name="IHUB_TASK")
                import re
                table_match = re.search(r'@Table\(name="([^"]+)"\)', appinfo.text)
                if table_match:
                    table_name = table_match.group(1)

    # Extract version UUID from Appian metadata annotation
    version_uuid = ""
    if annotation_el is not None:
        for appinfo in annotation_el.findall(f"{{{XSD_NS}}}appinfo"):
            if appinfo.get("source", "") == APPIAN_NS:
                vu_el = appinfo.find(f".//{{{APPIAN_NS}}}versionUuid")
                if vu_el is not None:
                    version_uuid = _text(vu_el)

    # Parse fields from sequence elements
    fields: list[RecordField] = []
    seq_el = ct.find(f"{{{XSD_NS}}}sequence")
    if seq_el is not None:
        for elem in seq_el.findall(f"{{{XSD_NS}}}element"):
            field_name = elem.get("name", "")
            field_type = elem.get("type", "")
            # Extract column info from annotation
            source_name = ""
            source_type_str = ""
            is_pk = False
            is_unique = False
            field_annotation = elem.find(f"{{{XSD_NS}}}annotation")
            if field_annotation is not None:
                for appinfo in field_annotation.findall(f"{{{XSD_NS}}}appinfo"):
                    if appinfo.get("source", "") == "appian.jpa" and appinfo.text:
                        jpa_text = appinfo.text
                        # Parse @Column(name="COL_NAME", ...)
                        import re
                        col_match = re.search(r'@Column\(name="([^"]+)"', jpa_text)
                        if col_match:
                            source_name = col_match.group(1)
                        coldef_match = re.search(r'columnDefinition="([^"]+)"', jpa_text)
                        if coldef_match:
                            source_type_str = coldef_match.group(1)
                        is_pk = "@Id" in jpa_text
                        is_unique = 'unique=true' in jpa_text

            fields.append(RecordField(
                name=field_name,
                display_name=field_name,
                type=field_type,
                source_field_name=source_name,
                source_field_type=source_type_str,
                is_primary_key=is_pk,
                is_unique=is_unique,
            ))

    # The "uuid" for a datatype is its qualified name: {namespace}TypeName
    qualified_name = f"{{{namespace}}}{type_name}" if namespace else type_name

    return DataType(
        uuid=qualified_name,
        name=type_name,
        description=f"CDT for table {table_name}" if table_name else f"CDT {type_name}",
        version_uuid=version_uuid,
        file_path=str(xsd_path),
        namespace=namespace,
        fields=fields,
        table_name=table_name,
        xsd_content=etree.tostring(root, encoding="unicode", pretty_print=True),
    )


# ---------------------------------------------------------------------------
# Web API parser (webApi/ directory)
# ---------------------------------------------------------------------------

def parse_web_api_xml(xml_path: Path) -> WebApi | None:
    """Parse a Web API XML file into a WebApi object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    role_map = _parse_role_map(root.find("roleMap"))

    wa_el = root.find("webApi")
    if wa_el is None:
        logger.warning("No <webApi> element in %s", xml_path)
        return None

    uuid = wa_el.get(f"{{{APPIAN_NS}}}uuid", "") or wa_el.get("uuid", "")
    name = wa_el.get("name", "")

    return WebApi(
        uuid=uuid,
        name=name,
        description=_text(_find(wa_el, "description")),
        version_uuid=version_uuid,
        file_path=str(xml_path),
        security_roles=role_map,
        http_method=_text(_find(wa_el, "httpMethod")),
        url_alias=_text(_find(wa_el, "urlAlias")),
        definition=_text_or_cdata(_find(wa_el, "expression")),
        request_body_type=_text(_find(wa_el, "requestBodyType")),
    )


# ---------------------------------------------------------------------------
# Connected system parser (connectedSystem/ directory)
# ---------------------------------------------------------------------------

def parse_connected_system_xml(xml_path: Path) -> ConnectedSystem | None:
    """Parse a connected system XML file into a ConnectedSystem object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    role_map = _parse_role_map(root.find("roleMap"))

    cs_el = root.find("connectedSystem")
    if cs_el is None:
        logger.warning("No <connectedSystem> element in %s", xml_path)
        return None

    # Extract properties from sharedConfigParameters Dictionary
    props: dict[str, str] = {}
    base_url = ""
    auth_type = ""
    shared_config = _find(cs_el, "sharedConfigParameters")
    if shared_config is not None:
        for child in shared_config.iter():
            local_name = etree.QName(child.tag).localname if isinstance(child.tag, str) else ""
            if local_name == "baseUrl":
                base_url = _text(child)
            elif local_name == "authType":
                auth_type = _text(child)
            elif local_name not in ("Dictionary", "sharedConfigParameters") and child.text:
                props[local_name] = child.text.strip()

    return ConnectedSystem(
        uuid=_text(_find(cs_el, "uuid")),
        name=_text(_find(cs_el, "name")),
        description=_text(_find(cs_el, "description")),
        version_uuid=version_uuid,
        file_path=str(xml_path),
        security_roles=role_map,
        system_type=_text(_find(cs_el, "integrationType")),
        properties=props,
        base_url=base_url,
        auth_type=auth_type,
    )


# ---------------------------------------------------------------------------
# Site parser (site/ directory)
# ---------------------------------------------------------------------------

def parse_site_xml(xml_path: Path) -> Site | None:
    """Parse a site XML file into a Site object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    role_map = _parse_role_map(root.find("roleMap"))

    site_el = root.find("site")
    if site_el is None:
        site_el = root.find(f"{{{APPIAN_NS}}}site")
    if site_el is None:
        logger.warning("No <site> element in %s", xml_path)
        return None

    uuid = site_el.get(f"{{{APPIAN_NS}}}uuid", "") or site_el.get("uuid", "")
    name = site_el.get("name", "")
    description = _text(site_el.find("description"))
    url_stub = _text(site_el.find("urlStub"))

    # Parse pages
    pages: list[SitePage] = []
    for page_el in site_el.findall("page"):
        page_uuid = page_el.get(f"{{{APPIAN_NS}}}uuid", "") or page_el.get("uuid", "")
        ui_obj_el = page_el.find("uiObject")
        ui_uuid = ""
        if ui_obj_el is not None:
            ui_uuid = ui_obj_el.get(f"{{{APPIAN_NS}}}uuid", "") or ui_obj_el.get("uuid", "")

        pages.append(SitePage(
            uuid=page_uuid,
            name_expr=_text_or_cdata(page_el.find("nameExpr")),
            description=_text(page_el.find("description")),
            url_stub=_text(page_el.find("urlStub")),
            ui_object_uuid=ui_uuid,
            icon_id=_text(page_el.find("iconId")),
            visibility_expr=_text_or_cdata(page_el.find("visibilityExpr")),
            page_width=_text(page_el.find("pageWidth")),
        ))

    return Site(
        uuid=uuid,
        name=name,
        description=description,
        version_uuid=version_uuid,
        file_path=str(xml_path),
        security_roles=role_map,
        url_stub=url_stub,
        pages=pages,
    )


# ---------------------------------------------------------------------------
# Group parser (group/ directory)
# ---------------------------------------------------------------------------

def parse_group_xml(xml_path: Path) -> Group | None:
    """Parse a group XML file into a Group object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))

    group_el = root.find("group")
    if group_el is None:
        logger.warning("No <group> element in %s", xml_path)
        return None

    # Members
    member_users: list[str] = []
    member_groups: list[str] = []
    members_el = root.find("members")
    if members_el is not None:
        users_el = members_el.find("users")
        if users_el is not None:
            for u in users_el:
                val = _text(u)
                if val:
                    member_users.append(val)
        groups_el = members_el.find("groups")
        if groups_el is not None:
            for g in groups_el:
                val = _text(g)
                if val:
                    member_groups.append(val)

    # Admins
    admin_users: list[str] = []
    admin_groups: list[str] = []
    admins_el = root.find("admins")
    if admins_el is not None:
        users_el = admins_el.find("users")
        if users_el is not None:
            for u in users_el:
                val = _text(u)
                if val:
                    admin_users.append(val)
        groups_el = admins_el.find("groups")
        if groups_el is not None:
            for g in groups_el:
                val = _text(g)
                if val:
                    admin_groups.append(val)

    return Group(
        uuid=_text(_find(group_el, "uuid")),
        name=_text(_find(group_el, "name")),
        description=_text(_find(group_el, "description")),
        version_uuid=version_uuid,
        file_path=str(xml_path),
        group_type_uuid=_text(_find(group_el, "groupTypeUuid")),
        member_policy=_text(_find(group_el, "memberPolicy")),
        viewing_policy=_text(_find(group_el, "viewingPolicy")),
        security_map=_text(_find(group_el, "securityMap")),
        member_users=member_users,
        member_groups=member_groups,
        admin_users=admin_users,
        admin_groups=admin_groups,
    )


# ---------------------------------------------------------------------------
# Data store parser (dataStore/ directory)
# ---------------------------------------------------------------------------

def parse_data_store_xml(xml_path: Path) -> DataStore | None:
    """Parse a data store XML file into a DataStore object."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None

    version_uuid = _text(root.find("versionUuid"))
    role_map = _parse_role_map(root.find("roleMap"))

    ds_el = root.find("dataStore")
    if ds_el is None:
        logger.warning("No <dataStore> element in %s", xml_path)
        return None

    entities: list[DataStoreEntity] = []
    entities_el = _find(ds_el, "entities")
    if entities_el is not None:
        for ent_el in _findall(entities_el, "entity"):
            entities.append(DataStoreEntity(
                uuid=_text(_find(ent_el, "uuid")),
                name=_text(_find(ent_el, "name")),
                type=_text(_find(ent_el, "type")),
            ))

    is_published = _bool_text(root.find("isPublished"))

    return DataStore(
        uuid=_text(_find(ds_el, "uuid")),
        name=_text(_find(ds_el, "name")),
        description=_text(_find(ds_el, "description")),
        version_uuid=version_uuid,
        file_path=str(xml_path),
        security_roles=role_map,
        data_source_key=_text(_find(ds_el, "dataSourceKey")),
        entities=entities,
        is_published=is_published,
        auto_update_schema=_bool_text(_find(ds_el, "autoUpdateSchema")),
    )


# ---------------------------------------------------------------------------
# Dispatcher: parse any file based on its parent directory
# ---------------------------------------------------------------------------

_DIR_PARSER_MAP: dict[str, type] = {}  # populated at module level below


def parse_appian_xml(xml_path: Path) -> AppianObject | None:
    """Auto-detect the object type from the file's parent directory and parse it.

    This is the single entry-point used by ``codebase_map.build_codebase_map``.
    """
    parent_dir = xml_path.parent.name

    parser_map: dict[str, object] = {
        "content": parse_content_xml,
        "recordType": parse_record_type_xml,
        "processModel": parse_process_model_xml,
        "datatype": parse_datatype_xml,
        "webApi": parse_web_api_xml,
        "connectedSystem": parse_connected_system_xml,
        "site": parse_site_xml,
        "group": parse_group_xml,
        "dataStore": parse_data_store_xml,
    }

    parser_fn = parser_map.get(parent_dir)
    if parser_fn is None:
        logger.debug("No parser for directory '%s' — skipping %s", parent_dir, xml_path.name)
        return None

    try:
        return parser_fn(xml_path)
    except Exception:
        logger.warning("Error parsing %s", xml_path, exc_info=True)
        return None
