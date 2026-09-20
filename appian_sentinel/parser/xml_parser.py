"""Parse individual Appian XML export files into typed model objects.

Uses ``lxml.etree`` for robust XML parsing with namespace and XPath support.
Each top-level directory in the export maps to a dedicated parse function.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lxml import etree

from appian_sentinel.models.appian_objects import (
    AIAgent,
    AISkill,
    AppianObject,
    BusinessProcess,
    ConnectedSystem,
    Constant,
    ControlPanel,
    ControlPanelHierarchyItem,
    Dashboard,
    DataStore,
    DataStoreEntity,
    DataType,
    Decision,
    Document,
    EventConsumer,
    ExpressionRule,
    Feed,
    Folder,
    Group,
    GroupType,
    Interface,
    KnowledgeCenter,
    ObjectType,
    OutboundIntegration,
    OutputMetadata,
    Portal,
    ProcessEdge,
    ProcessModel,
    ProcessModelFolder,
    ProcessNode,
    ProcessReport,
    ProcessVariable,
    RecordAction,
    RecordField,
    RecordRelationship,
    RecordType,
    Report,
    RoboticTask,
    RobotPool,
    RuleInput,
    RulesFolder,
    SecurityRole,
    Site,
    SitePage,
    Swimlane,
    TempoReport,
    TranslationSet,
    TranslationString,
    WebApi,
    extract_uuid_references,
)
from appian_sentinel.models.object_registry import EXPORT_DIR_TO_TYPE

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


def _constant_value_source(element: etree._Element | None) -> str:
    """Return scalar text or the XML representation of a structured constant value."""
    if element is None:
        return ""
    if len(element) == 0 and not element.attrib:
        return _text(element)
    return etree.tostring(element, encoding="unicode", with_tail=False).strip()


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


def _attribute(element: etree._Element, name: str) -> str:
    """Return an attribute with or without the Appian namespace."""
    return element.get(name, "") or element.get(f"{{{APPIAN_NS}}}{name}", "")


def _descendants(parent: etree._Element, tag: str) -> list[etree._Element]:
    """Return descendants selected by namespace-independent local name."""
    return list(parent.xpath(f'.//*[local-name()="{tag}"]'))


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
    for pair in _findall(string_map_el, "pair"):
        locale_el = _find(pair, "locale")
        if locale_el is not None:
            lang = locale_el.get("lang", "")
            country = locale_el.get("country", "")
            if lang == "en" and country == "US":
                return _text_or_cdata(_find(pair, "value"))
    # Fallback: return first non-empty value
    for pair in _findall(string_map_el, "pair"):
        val = _text_or_cdata(_find(pair, "value"))
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
        "communityKnowledgeCenter": _parse_knowledge_center,
        "report": _parse_report,
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
        logger.debug("Preserving unknown content subtype <%s> in %s", child.tag, xml_path)
        role_map = _parse_role_map(root.find("roleMap"))
        obj = _parse_generic_content(child, root)
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
        value = _constant_value_source(_find(typed_val_el, "value"))

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
    """Parse any folder-like element into a Folder."""
    return Folder(
        uuid=_text(_find(el, "uuid")),
        name=_text(_find(el, "name")),
        description=_text(_find(el, "description")),
        parent_uuid=_text(_find(el, "parentUuid")),
    )


def _parse_knowledge_center(el: etree._Element, root: etree._Element) -> KnowledgeCenter:
    return KnowledgeCenter(
        uuid=_text(_find(el, "uuid")),
        name=_text(_find(el, "name")),
        description=_text(_find(el, "description")),
        parent_uuid=_text(_find(el, "parentUuid")),
    )


def _parse_report(el: etree._Element, root: etree._Element) -> Report:
    return Report(
        uuid=_text(_find(el, "uuid")),
        name=_text(_find(el, "name")),
        description=_text(_find(el, "description")),
        parent_uuid=_text(_find(el, "parentUuid")),
        raw_xml=etree.tostring(el, encoding="unicode", with_tail=False),
    )


def _parse_generic_content(el: etree._Element, root: etree._Element) -> AppianObject:
    """Parse any unrecognised content subtype (report, etc.) as a generic AppianObject."""
    return AppianObject(
        uuid=_text(_find(el, "uuid")),
        name=_text(_find(el, "name")),
        description=_text(_find(el, "description")),
        parent_uuid=_text(_find(el, "parentUuid")),
        object_type=ObjectType.UNKNOWN,
        unknown_xml={
            etree.QName(el).localname: [
                etree.tostring(el, encoding="unicode", with_tail=False)
            ]
        },
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
    relationship_elements = _findall(rt_el, "recordRelationshipCfg") + _findall(rt_el, "relationship")
    for rel_el in relationship_elements:
        rel_uuid = _text(_find(rel_el, "uuid")) or _attribute(rel_el, "uuid")
        rel_name = (
            _text(_find(rel_el, "relationshipName"))
            or _text(_find(rel_el, "name"))
            or _attribute(rel_el, "name")
        )
        related_rt = (
            _text(_find(rel_el, "targetRecordTypeUuid"))
            or _text(_find(rel_el, "relatedRecordType"))
        )
        rel_type = _text(_find(rel_el, "relationshipType")) or _text(_find(rel_el, "type"))
        relationship_data = _text_or_cdata(_find(rel_el, "relationshipData"))
        source_field_uuid = ""
        target_field_uuid = ""
        if relationship_data:
            try:
                import json

                relationship_values = json.loads(relationship_data)
                source_field_uuid = str(relationship_values.get("sourceRecordTypeFieldUuid", ""))
                target_field_uuid = str(relationship_values.get("targetRecordTypeFieldUuid", ""))
            except (TypeError, ValueError):
                pass
        if rel_uuid or rel_name:
            relationships.append(RecordRelationship(
                uuid=rel_uuid,
                name=rel_name,
                related_record_type_uuid=related_rt,
                relationship_type=rel_type,
                source_field_uuid=source_field_uuid,
                target_field_uuid=target_field_uuid,
                update_behavior=_text(_find(rel_el, "updateBehavior")),
                relationship_data=relationship_data,
            ))

    # Parse record actions
    record_actions: list[RecordAction] = []
    action_elements = _findall(rt_el, "relatedActionCfg") + _findall(rt_el, "recordAction")
    for ra_el in action_elements:
        ra_uuid = _attribute(ra_el, "uuid")
        title_expr = _text_or_cdata(_find(ra_el, "titleExpr"))
        static_title = _text(_find(ra_el, "staticTitleString"))
        ra_name = static_title or title_expr or _text(_find(ra_el, "nameExpr")) or _text(_find(ra_el, "name"))
        target_el = _find(ra_el, "target")
        if target_el is None:
            target_el = _find(ra_el, "processModel")
        pm_uuid = _attribute(target_el, "uuid") if target_el is not None else ""
        if target_el is not None and not pm_uuid:
            pm_uuid = _text(target_el)
        record_actions.append(RecordAction(
            uuid=ra_uuid,
            name=ra_name,
            process_model_uuid=pm_uuid,
            description=_text(_find(ra_el, "staticDescriptionString")),
            reference_key=_text(_find(ra_el, "referenceKey")),
            context_expr=_text_or_cdata(_find(ra_el, "contextExpr")),
            visibility_expr=_text_or_cdata(_find(ra_el, "visibilityExpr")),
            title_expr=title_expr,
            description_expr=_text_or_cdata(_find(ra_el, "descriptionExpr")),
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
        name_el = _find(meta_el, "name")
        if name_el is not None:
            sm = _find(name_el, "string-map")
            name = _get_en_us_value(sm)

        desc_el = _find(meta_el, "desc")
        if desc_el is not None:
            sm = _find(desc_el, "string-map")
            description = _get_en_us_value(sm)

        # Process display name expression
        pn_el = _find(meta_el, "process-name")
        if pn_el is not None:
            sm = _find(pn_el, "string-map")
            process_name_expr = _get_en_us_value(sm)

        # Notification recipients expression
        notif_el = _find(meta_el, "pm-notification-settings")
        if notif_el is not None:
            recip_el = _find(notif_el, "recipients-exp")
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
            is_param = _bool_text(_find(pv_el, "parameter"))
            is_required = _bool_text(_find(pv_el, "required"))
            is_hidden = _bool_text(_find(pv_el, "hidden"))
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
    pending_edges: list[tuple[str, str, str]] = []
    gui_to_uuid: dict[str, str] = {}
    nodes_el = pm_el.find("nodes")
    if nodes_el is None:
        nodes_el = pm_el.find(f"{{{APPIAN_NS}}}nodes")
    if nodes_el is not None:
        for node_el in nodes_el:
            local_tag = etree.QName(node_el.tag).localname if isinstance(node_el.tag, str) else ""
            if local_tag != "node":
                continue
            node_uuid = node_el.get("uuid", "")
            gui_id = _text(_find(node_el, "guiId"))
            if gui_id:
                gui_to_uuid[gui_id] = node_uuid
            # Node name in string-map
            node_name = ""
            fname_el = _find(node_el, "fname")
            if fname_el is not None:
                sm = _find(fname_el, "string-map")
                node_name = _get_en_us_value(sm)

            ac_el = _find(node_el, "ac")
            node_type = ""
            if ac_el is not None:
                node_type = _text(_find(ac_el, "local-id")) or _text(_find(ac_el, "name"))

            lane_text = _text(_find(node_el, "lane"))
            lane_index = int(lane_text) if lane_text.isdigit() else None

            # Retain expression-bearing text, including Appian URNs and internal IDs.
            expressions: list[str] = []
            for descendant in node_el.iter():
                if descendant.text:
                    text = descendant.text.strip()
                    if extract_uuid_references(text):
                        expressions.append(text)

            nodes.append(ProcessNode(
                uuid=node_uuid,
                name=node_name,
                node_type=node_type,
                gui_id=gui_id,
                lane_index=lane_index,
                expressions=expressions,
            ))
            connections_el = _find(node_el, "connections")
            if connections_el is not None:
                for connection_el in _findall(connections_el, "connection"):
                    target_gui_id = _text(_find(connection_el, "to"))
                    flow_label = _text(_find(connection_el, "flowLabel"))
                    pending_edges.append((gui_id, target_gui_id, flow_label))

    edges = [
        ProcessEdge(
            source_uuid=gui_to_uuid.get(source_gui_id, ""),
            target_uuid=gui_to_uuid.get(target_gui_id, ""),
            source_gui_id=source_gui_id,
            target_gui_id=target_gui_id,
            label=label,
        )
        for source_gui_id, target_gui_id, label in pending_edges
    ]

    swimlanes: list[Swimlane] = []
    lanes_el = _find(pm_el, "lanes")
    if lanes_el is not None:
        for index, lane_el in enumerate(_findall(lanes_el, "lane")):
            assignment = _text_or_cdata(_find(lane_el, "assignment"))
            swimlanes.append(Swimlane(
                name=_text(_find(lane_el, "laneLabel")),
                assignment_expression=assignment,
                index=index,
                is_vertical=_bool_text(_find(lane_el, "isVertical")),
                is_assignment=_bool_text(_find(lane_el, "isLaneAssignment")),
                unattended=_text(_find(lane_el, "unattended")) == "1",
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
        edges=edges,
        process_variables=pvs,
        swimlanes=swimlanes,
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
# Translation, portal, folder, and Tempo report parsers
# ---------------------------------------------------------------------------

def parse_translation_string_xml(xml_path: Path) -> TranslationString | None:
    """Parse a translation string and all localized values."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None
    string_el = _find(root, "translationString")
    if string_el is None:
        return None

    translations: dict[str, str] = {}
    for translated_el in _descendants(string_el, "translatedText"):
        locale_el = next(iter(_descendants(translated_el, "localeLanguageTag")), None)
        value_candidates = [
            child for child in translated_el
            if etree.QName(child).localname == "translatedText"
        ]
        locale = _text(locale_el)
        if locale and value_candidates:
            translations[locale] = _text_or_cdata(value_candidates[-1])

    variables = [
        _text(variable_el)
        for variable_el in _descendants(string_el, "translationStringVariable")
        if _text(variable_el)
    ]
    return TranslationString(
        uuid=_attribute(string_el, "uuid"),
        name=_attribute(string_el, "name"),
        description=_text(_find(string_el, "description")),
        version_uuid=_text(_find(root, "versionUuid")),
        file_path=str(xml_path),
        translation_set_uuid=_text(_find(string_el, "translationSetUuid")),
        translator_notes=_text(_find(string_el, "translatorNotes")),
        translations=translations,
        variables=variables,
    )


def parse_translation_set_xml(xml_path: Path) -> TranslationSet | None:
    """Parse a translation set and its enabled locales."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None
    set_el = _find(root, "translationSet")
    if set_el is None:
        return None
    locales = [_text(el) for el in _descendants(set_el, "localeLanguageTag") if _text(el)]
    default_el = _find(set_el, "defaultLocale")
    default_locale_el = (
        next(iter(_descendants(default_el, "localeLanguageTag")), None)
        if default_el is not None
        else None
    )
    return TranslationSet(
        uuid=_attribute(set_el, "uuid"),
        name=_attribute(set_el, "name"),
        description=_text(_find(set_el, "description")),
        version_uuid=_text(_find(root, "versionUuid")),
        file_path=str(xml_path),
        security_roles=_parse_role_map(_find(root, "roleMap")),
        enabled_locales=list(dict.fromkeys(locales)),
        default_locale=_text(default_locale_el),
    )


def parse_process_model_folder_xml(xml_path: Path) -> ProcessModelFolder | None:
    """Parse a process model folder."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None
    folder_el = _find(root, "processModelFolder")
    if folder_el is None:
        return None
    return ProcessModelFolder(
        uuid=_text(_find(folder_el, "uuid")) or _attribute(folder_el, "uuid"),
        name=_text(_find(folder_el, "name")) or _attribute(folder_el, "name"),
        description=_text(_find(folder_el, "description")),
        version_uuid=_text(_find(root, "versionUuid")),
        file_path=str(xml_path),
        security_roles=_parse_role_map(_find(root, "roleMap")),
    )


def parse_tempo_report_xml(xml_path: Path) -> TempoReport | None:
    """Parse a legacy Tempo report."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None
    report_el = _find(root, "tempoReport")
    if report_el is None:
        return None
    expression = _text_or_cdata(_find(report_el, "uiExpr"))
    return TempoReport(
        uuid=_attribute(report_el, "uuid"),
        name=_attribute(report_el, "name"),
        description=_text(_find(report_el, "description")),
        version_uuid=_text(_find(root, "versionUuid")),
        file_path=str(xml_path),
        security_roles=_parse_role_map(_find(root, "roleMap")),
        expression=expression,
        ui_expression=expression,
        url_stub=_text(_find(report_el, "urlStub")),
    )


def parse_portal_xml(xml_path: Path) -> Portal | None:
    """Parse an Appian Portal and its navigation pages."""
    root = _parse_xml_file(xml_path)
    if root is None:
        return None
    portal_el = _find(root, "portal")
    if portal_el is None:
        return None

    pages: list[SitePage] = []
    for page_el in _findall(portal_el, "navigationNode"):
        ui_el = _find(page_el, "uiObject")
        pages.append(SitePage(
            uuid=_attribute(page_el, "uuid"),
            name_expr=_text(_find(page_el, "staticName")),
            description=_text(_find(page_el, "description")),
            url_stub=_text(_find(page_el, "urlStub")),
            ui_object_uuid=_attribute(ui_el, "uuid") if ui_el is not None else "",
            icon_id=_text(_find(page_el, "iconId")),
            visibility_expr=_text_or_cdata(_find(page_el, "visibilityExpr")),
            page_width=_text(_find(page_el, "pageWidth")),
        ))

    service_account_el = _find(portal_el, "serviceAccountUser")
    return Portal(
        uuid=_attribute(portal_el, "uuid"),
        name=_attribute(portal_el, "name"),
        description=_text(_find(portal_el, "description")),
        version_uuid=_text(_find(root, "versionUuid")),
        file_path=str(xml_path),
        security_roles=_parse_role_map(_find(root, "roleMap")),
        display_name=_text(_find(portal_el, "displayName")),
        url_stub=_text(_find(portal_el, "urlStub")),
        hostname=_text(_find(portal_el, "hostname")),
        published=_bool_text(_find(portal_el, "published")),
        service_account_uuid=_attribute(service_account_el, "uuid") if service_account_el is not None else "",
        pages=pages,
    )


# ---------------------------------------------------------------------------
# Dispatcher: parse any file based on its parent directory
# ---------------------------------------------------------------------------

_DIR_PARSER_MAP: dict[str, type] = {}  # populated at module level below


_PRESERVED_MODELS: dict[ObjectType, type] = {
    ObjectType.BUSINESS_PROCESS: BusinessProcess,
    ObjectType.PROCESS_REPORT: ProcessReport,
    ObjectType.ROBOTIC_TASK: RoboticTask,
    ObjectType.ROBOT_POOL: RobotPool,
    ObjectType.CONTROL_PANEL: ControlPanel,
    ObjectType.CONTROL_PANEL_HIERARCHY_ITEM: ControlPanelHierarchyItem,
    ObjectType.DASHBOARD: Dashboard,
    ObjectType.REPORT: Report,
    ObjectType.AI_AGENT: AIAgent,
    ObjectType.AI_SKILL: AISkill,
    ObjectType.EVENT_CONSUMER: EventConsumer,
    ObjectType.GROUP_TYPE: GroupType,
    ObjectType.FEED: Feed,
}


def parse_preserved_directory_xml(xml_path: Path) -> AppianObject | None:
    """Parse an official type whose schema is preserved as raw XML."""
    object_type = EXPORT_DIR_TO_TYPE.get(xml_path.parent.name)
    if object_type is None:
        logger.debug("No parser for directory '%s' — skipping %s", xml_path.parent.name, xml_path.name)
        return None
    root = _parse_xml_file(xml_path)
    if root is None:
        return None
    model = _PRESERVED_MODELS.get(object_type)
    if model is None:
        return None
    uuid = _text(_find(root, "uuid")) or _attribute(root, "uuid")
    if not uuid:
        uuid_nodes = root.xpath(".//*[local-name()='uuid'][1]/text()")
        uuid = str(uuid_nodes[0]).strip() if uuid_nodes else xml_path.stem
    name_nodes = root.xpath(".//*[local-name()='name'][1]/text()")
    return model(
        uuid=uuid,
        name=str(name_nodes[0]).strip() if name_nodes else xml_path.stem,
        file_path=str(xml_path),
        raw_xml=etree.tostring(root, encoding="unicode"),
    )


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
        "translationString": parse_translation_string_xml,
        "translationSet": parse_translation_set_xml,
        "processModelFolder": parse_process_model_folder_xml,
        "tempoReport": parse_tempo_report_xml,
        "portal": parse_portal_xml,
    }

    parser_fn = parser_map.get(parent_dir)
    if parser_fn is None:
        return parse_preserved_directory_xml(xml_path)

    try:
        return parser_fn(xml_path)
    except Exception:
        logger.warning("Error parsing %s", xml_path, exc_info=True)
        return None
