"""Pydantic models for every Appian design-object type found in an application export."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ObjectType(str, Enum):
    """Discriminator for Appian design-object types."""

    EXPRESSION_RULE = "expression_rule"
    INTERFACE = "interface"
    CONSTANT = "constant"
    DECISION = "decision"
    RECORD_TYPE = "record_type"
    PROCESS_MODEL = "process_model"
    DATA_TYPE = "data_type"
    WEB_API = "web_api"
    CONNECTED_SYSTEM = "connected_system"
    SITE = "site"
    GROUP = "group"
    DATA_STORE = "data_store"
    DOCUMENT = "document"
    FOLDER = "folder"
    RULES_FOLDER = "rules_folder"
    OUTBOUND_INTEGRATION = "outbound_integration"
    TRANSLATION_STRING = "translation_string"
    TRANSLATION_SET = "translation_set"
    PORTAL = "portal"
    PROCESS_MODEL_FOLDER = "process_model_folder"
    TEMPO_REPORT = "tempo_report"
    BUSINESS_PROCESS = "business_process"
    PROCESS_REPORT = "process_report"
    ROBOTIC_TASK = "robotic_task"
    ROBOT_POOL = "robot_pool"
    CONTROL_PANEL = "control_panel"
    CONTROL_PANEL_HIERARCHY_ITEM = "control_panel_hierarchy_item"
    DASHBOARD = "dashboard"
    REPORT = "report"
    AI_AGENT = "ai_agent"
    AI_SKILL = "ai_skill"
    EVENT_CONSUMER = "event_consumer"
    GROUP_TYPE = "group_type"
    DOCUMENT_FOLDER = "document_folder"
    KNOWLEDGE_CENTER = "knowledge_center"
    FEED = "feed"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Small sub-models
# ---------------------------------------------------------------------------

class RuleInput(BaseModel):
    """A single input parameter for an expression rule or interface."""

    name: str
    type_name: str = ""
    type_namespace: str = ""
    is_list: bool = False


class RecordField(BaseModel):
    """A field within a record type's source configuration."""

    uuid: str = ""
    name: str = ""
    display_name: str = ""
    type: str = ""
    source_field_name: str = ""
    source_field_type: str = ""
    is_primary_key: bool = False
    is_unique: bool = False
    is_hidden: bool = False
    is_custom_field: bool = False


class RecordRelationship(BaseModel):
    """A relationship between record types."""

    uuid: str = ""
    name: str = ""
    related_record_type_uuid: str = ""
    relationship_type: str = ""  # ONE_TO_MANY, MANY_TO_ONE, etc.
    source_field_uuid: str = ""
    target_field_uuid: str = ""
    update_behavior: str = ""
    relationship_data: str = ""


class RecordAction(BaseModel):
    """A record action definition."""

    uuid: str = ""
    name: str = ""
    process_model_uuid: str = ""
    description: str = ""
    reference_key: str = ""
    context_expr: str = ""
    visibility_expr: str = ""
    title_expr: str = ""
    description_expr: str = ""


class ProcessVariable(BaseModel):
    """A process variable in a process model."""

    name: str
    type: str = ""
    is_parameter: bool = False
    is_required: bool = False
    is_hidden: bool = False


class ProcessNode(BaseModel):
    """A node in a process model flow."""

    uuid: str = ""
    name: str = ""
    node_type: str = ""  # start, end, user_input_task, sub_process, etc.
    gui_id: str = ""
    lane_index: int | None = None
    expressions: list[str] = Field(default_factory=list)


class ProcessEdge(BaseModel):
    """A directed connection between two process nodes."""

    source_uuid: str = ""
    target_uuid: str = ""
    source_gui_id: str = ""
    target_gui_id: str = ""
    label: str = ""


class Swimlane(BaseModel):
    """A swimlane in a process model."""

    name: str = ""
    assignment_expression: str = ""
    index: int = 0
    is_vertical: bool = False
    is_assignment: bool = False
    unattended: bool = False


class SecurityRole(BaseModel):
    """A security role assignment on a design object."""

    role_name: str
    users: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    inherit: bool = False
    allow_for_all: bool = False


class DataStoreEntity(BaseModel):
    """An entity (table mapping) in a data store."""

    uuid: str = ""
    name: str = ""
    type: str = ""


class SitePage(BaseModel):
    """A page within an Appian site."""

    uuid: str = ""
    name_expr: str = ""
    description: str = ""
    url_stub: str = ""
    ui_object_uuid: str = ""
    icon_id: str = ""
    visibility_expr: str = ""
    page_width: str = ""


class OutputMetadata(BaseModel):
    """Output metadata for a decision object."""

    output_id: str = ""
    name_ref: str = ""
    type_name: str = ""


# ---------------------------------------------------------------------------
# UUID reference extraction helper
# ---------------------------------------------------------------------------

# Appian references can be quoted SAIL identifiers, bare internal identifiers,
# or URNs whose first path segment identifies the owning design object.
_QUOTED_REF_PATTERN = re.compile(r'#"([^"]+)"')
_INTERNAL_REF_PATTERN = re.compile(r"(?<![A-Za-z0-9])(_[a-z]-[A-Za-z0-9_-]+)")
_URN_REF_PATTERN = re.compile(r"urn:appian:[a-z0-9-]+:v\d+:([^\"'\s,)\]}]+)", re.IGNORECASE)


def extract_uuid_references(text: str | None) -> set[str]:
    """Extract all UUID references from a SAIL expression or definition text.

    Returns a set of unique UUID strings referenced via ``#"<uuid>"`` notation,
    as well as record-type/field URN patterns.  SYSTEM_SYSRULES_* UUIDs are
    excluded since they are built-in Appian functions, not user-defined objects.
    """
    if not text:
        return set()

    refs: set[str] = set()

    for m in _QUOTED_REF_PATTERN.finditer(text):
        ref = m.group(1)
        if ref.startswith("SYSTEM_SYSRULES_"):
            continue
        if not ref.lower().startswith("urn:appian:"):
            refs.add(ref)

    for match in _URN_REF_PATTERN.finditer(text):
        refs.add(match.group(1).split("/", 1)[0])

    refs.update(match.group(1) for match in _INTERNAL_REF_PATTERN.finditer(text))
    return refs


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------

class AppianObject(BaseModel):
    """Base model for any Appian design object."""

    uuid: str
    name: str = ""
    description: str = ""
    object_type: ObjectType = ObjectType.UNKNOWN
    parent_uuid: str = ""
    file_path: str = ""
    version_uuid: str = ""
    security_roles: list[SecurityRole] = Field(default_factory=list)
    unknown_xml: dict[str, list[str]] = Field(default_factory=dict)

    def get_uuid_references(self) -> set[str]:
        """Return all UUIDs this object references (override in subclasses)."""
        return set()


# ---------------------------------------------------------------------------
# Content sub-types
# ---------------------------------------------------------------------------

class ExpressionRule(AppianObject):
    """An Appian expression rule (SAIL code in ``<definition>``)."""

    object_type: ObjectType = ObjectType.EXPRESSION_RULE
    definition: str = ""
    rule_inputs: list[RuleInput] = Field(default_factory=list)
    preferred_editor: str = ""
    offline_enabled: bool = False

    def get_uuid_references(self) -> set[str]:
        return extract_uuid_references(self.definition)


class Interface(AppianObject):
    """An Appian interface (SAIL UI definition)."""

    object_type: ObjectType = ObjectType.INTERFACE
    definition: str = ""
    rule_inputs: list[RuleInput] = Field(default_factory=list)
    preferred_editor: str = ""
    offline_enabled: bool = False
    is_custom: bool = False

    def get_uuid_references(self) -> set[str]:
        return extract_uuid_references(self.definition)


class Constant(AppianObject):
    """An Appian constant value."""

    object_type: ObjectType = ObjectType.CONSTANT
    value: str = ""
    value_type: str = ""
    value_type_namespace: str = ""
    is_environment_specific: bool = False


class Decision(AppianObject):
    """An Appian decision object (decision table)."""

    object_type: ObjectType = ObjectType.DECISION
    definition: str = ""
    rule_inputs: list[RuleInput] = Field(default_factory=list)
    preferred_editor: str = ""
    offline_enabled: bool = False
    output_metadata: list[OutputMetadata] = Field(default_factory=list)
    hit_policy: str = ""

    def get_uuid_references(self) -> set[str]:
        return extract_uuid_references(self.definition)


class Document(AppianObject):
    """A document (file) stored in Appian."""

    object_type: ObjectType = ObjectType.DOCUMENT
    file_name: str = ""
    file_extension: str = ""
    size: int = 0


class Folder(AppianObject):
    """An organizational folder or knowledge center."""

    object_type: ObjectType = ObjectType.FOLDER


class RulesFolder(AppianObject):
    """A rules folder (organizes expression rules/interfaces)."""

    object_type: ObjectType = ObjectType.RULES_FOLDER


class OutboundIntegration(AppianObject):
    """An outbound integration (HTTP call, etc.)."""

    object_type: ObjectType = ObjectType.OUTBOUND_INTEGRATION
    definition: str = ""
    preferred_editor: str = ""
    offline_enabled: bool = False
    http_method: str = ""
    connected_system_uuid: str = ""
    integration_type: str = ""

    def get_uuid_references(self) -> set[str]:
        refs = extract_uuid_references(self.definition)
        if self.connected_system_uuid:
            refs.add(self.connected_system_uuid)
        return refs


# ---------------------------------------------------------------------------
# Top-level object types (each has its own directory in the export)
# ---------------------------------------------------------------------------

class RecordType(AppianObject):
    """An Appian record type definition."""

    object_type: ObjectType = ObjectType.RECORD_TYPE
    plural_name: str = ""
    url_stub: str = ""
    source_type: str = ""
    source_uuid: str = ""
    friendly_name: str = ""
    layout_type: str = ""
    fields: list[RecordField] = Field(default_factory=list)
    relationships: list[RecordRelationship] = Field(default_factory=list)
    record_actions: list[RecordAction] = Field(default_factory=list)
    data_source: str = ""
    list_view_expr: str = ""
    title_expr: str = ""
    is_exportable: bool = True

    def get_uuid_references(self) -> set[str]:
        refs: set[str] = set()
        refs |= extract_uuid_references(self.list_view_expr)
        refs |= extract_uuid_references(self.title_expr)
        for ra in self.record_actions:
            if ra.process_model_uuid:
                refs.add(ra.process_model_uuid)
            refs |= extract_uuid_references(ra.context_expr)
            refs |= extract_uuid_references(ra.visibility_expr)
            refs |= extract_uuid_references(ra.title_expr)
            refs |= extract_uuid_references(ra.description_expr)
        for relationship in self.relationships:
            if relationship.related_record_type_uuid:
                refs.add(relationship.related_record_type_uuid)
        return refs


class ProcessModel(AppianObject):
    """An Appian process model."""

    object_type: ObjectType = ObjectType.PROCESS_MODEL
    folder_uuid: str = ""
    nodes: list[ProcessNode] = Field(default_factory=list)
    edges: list[ProcessEdge] = Field(default_factory=list)
    process_variables: list[ProcessVariable] = Field(default_factory=list)
    swimlanes: list[Swimlane] = Field(default_factory=list)
    notification_recipients_expr: str = ""
    process_name_expr: str = ""

    def get_uuid_references(self) -> set[str]:
        refs: set[str] = set()
        # Collect references from all node expressions
        for node in self.nodes:
            for expr in node.expressions:
                refs |= extract_uuid_references(expr)
        # Also from process-level expressions
        refs |= extract_uuid_references(self.notification_recipients_expr)
        refs |= extract_uuid_references(self.process_name_expr)
        return refs


class DataType(AppianObject):
    """A CDT (Custom Data Type) represented as XSD."""

    object_type: ObjectType = ObjectType.DATA_TYPE
    xsd_content: str = ""
    namespace: str = ""
    fields: list[RecordField] = Field(default_factory=list)
    table_name: str = ""


class WebApi(AppianObject):
    """An Appian Web API endpoint."""

    object_type: ObjectType = ObjectType.WEB_API
    http_method: str = ""
    url_alias: str = ""
    definition: str = ""
    request_body_type: str = ""
    path: str = ""

    def get_uuid_references(self) -> set[str]:
        return extract_uuid_references(self.definition)


class ConnectedSystem(AppianObject):
    """An Appian connected system (external service configuration)."""

    object_type: ObjectType = ObjectType.CONNECTED_SYSTEM
    system_type: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)
    base_url: str = ""
    auth_type: str = ""


class Site(AppianObject):
    """An Appian site (user-facing portal)."""

    object_type: ObjectType = ObjectType.SITE
    url_stub: str = ""
    pages: list[SitePage] = Field(default_factory=list)

    def get_uuid_references(self) -> set[str]:
        refs: set[str] = set()
        for page in self.pages:
            refs |= extract_uuid_references(page.name_expr)
            refs |= extract_uuid_references(page.visibility_expr)
            if page.ui_object_uuid:
                refs.add(page.ui_object_uuid)
        return refs


class Group(AppianObject):
    """An Appian security group."""

    object_type: ObjectType = ObjectType.GROUP
    group_type_uuid: str = ""
    member_policy: str = ""
    viewing_policy: str = ""
    security_map: str = ""
    member_users: list[str] = Field(default_factory=list)
    member_groups: list[str] = Field(default_factory=list)
    admin_users: list[str] = Field(default_factory=list)
    admin_groups: list[str] = Field(default_factory=list)


class DataStore(AppianObject):
    """An Appian data store (JDBC data source configuration)."""

    object_type: ObjectType = ObjectType.DATA_STORE
    data_source_key: str = ""
    entities: list[DataStoreEntity] = Field(default_factory=list)
    is_published: bool = False
    auto_update_schema: bool = False


class TranslationString(AppianObject):
    """An Appian translation string (i18n entry)."""

    object_type: ObjectType = ObjectType.TRANSLATION_STRING
    translation_set_uuid: str = ""
    translator_notes: str = ""
    translations: dict[str, str] = Field(default_factory=dict)
    variables: list[str] = Field(default_factory=list)

    def get_uuid_references(self) -> set[str]:
        return {self.translation_set_uuid} if self.translation_set_uuid else set()


class TranslationSet(AppianObject):
    """A collection of localized translation strings."""

    object_type: ObjectType = ObjectType.TRANSLATION_SET
    enabled_locales: list[str] = Field(default_factory=list)
    default_locale: str = ""


class ProcessModelFolder(AppianObject):
    """A folder that contains process models."""

    object_type: ObjectType = ObjectType.PROCESS_MODEL_FOLDER


class TempoReport(AppianObject):
    """A legacy Tempo report."""

    object_type: ObjectType = ObjectType.TEMPO_REPORT
    expression: str = ""
    ui_expression: str = ""
    url_stub: str = ""

    def get_uuid_references(self) -> set[str]:
        return extract_uuid_references(self.expression or self.ui_expression)


class PreservedObject(AppianObject):
    """Typed identity for an official Appian object whose XML is kept raw."""

    raw_xml: str = ""


class BusinessProcess(PreservedObject):
    object_type: ObjectType = ObjectType.BUSINESS_PROCESS


class ProcessReport(PreservedObject):
    object_type: ObjectType = ObjectType.PROCESS_REPORT


class RoboticTask(PreservedObject):
    object_type: ObjectType = ObjectType.ROBOTIC_TASK


class RobotPool(PreservedObject):
    object_type: ObjectType = ObjectType.ROBOT_POOL


class ControlPanel(PreservedObject):
    object_type: ObjectType = ObjectType.CONTROL_PANEL


class ControlPanelHierarchyItem(PreservedObject):
    object_type: ObjectType = ObjectType.CONTROL_PANEL_HIERARCHY_ITEM


class Dashboard(PreservedObject):
    object_type: ObjectType = ObjectType.DASHBOARD


class Report(PreservedObject):
    object_type: ObjectType = ObjectType.REPORT


class AIAgent(PreservedObject):
    object_type: ObjectType = ObjectType.AI_AGENT


class AISkill(PreservedObject):
    object_type: ObjectType = ObjectType.AI_SKILL


class EventConsumer(PreservedObject):
    object_type: ObjectType = ObjectType.EVENT_CONSUMER


class GroupType(PreservedObject):
    object_type: ObjectType = ObjectType.GROUP_TYPE


class DocumentFolder(Folder):
    object_type: ObjectType = ObjectType.DOCUMENT_FOLDER


class KnowledgeCenter(Folder):
    object_type: ObjectType = ObjectType.KNOWLEDGE_CENTER


class Feed(PreservedObject):
    object_type: ObjectType = ObjectType.FEED


class Portal(AppianObject):
    """An Appian Portal and its navigation pages."""

    object_type: ObjectType = ObjectType.PORTAL
    display_name: str = ""
    url_stub: str = ""
    hostname: str = ""
    published: bool = False
    service_account_uuid: str = ""
    pages: list[SitePage] = Field(default_factory=list)

    def get_uuid_references(self) -> set[str]:
        refs: set[str] = set()
        if self.service_account_uuid:
            refs.add(self.service_account_uuid)
        for page in self.pages:
            refs |= extract_uuid_references(page.visibility_expr)
            if page.ui_object_uuid:
                refs.add(page.ui_object_uuid)
        return refs
