"""Official Appian 26.8 Designer object capabilities.

Source: https://docs.appian.com/suite/help/26.8/design-objects.html
and https://docs.appian.com/suite/help/26.8/Renaming_Design_Objects.html
"""

from __future__ import annotations

from dataclasses import dataclass

from appian_sentinel.models.appian_objects import ObjectType

# Official Designer catalog. translation_string is a child of translation_set
# and is parsed, but it is not one of the 34 NEW-menu types.
OFFICIAL_DESIGNER_TYPES: tuple[ObjectType, ...] = (
    ObjectType.BUSINESS_PROCESS,
    ObjectType.DATA_STORE,
    ObjectType.DATA_TYPE,
    ObjectType.RECORD_TYPE,
    ObjectType.PROCESS_MODEL,
    ObjectType.PROCESS_MODEL_FOLDER,
    ObjectType.PROCESS_REPORT,
    ObjectType.ROBOTIC_TASK,
    ObjectType.ROBOT_POOL,
    ObjectType.CONTROL_PANEL,
    ObjectType.CONTROL_PANEL_HIERARCHY_ITEM,
    ObjectType.DASHBOARD,
    ObjectType.INTERFACE,
    ObjectType.PORTAL,
    ObjectType.REPORT,
    ObjectType.SITE,
    ObjectType.TEMPO_REPORT,
    ObjectType.AI_AGENT,
    ObjectType.AI_SKILL,
    ObjectType.CONSTANT,
    ObjectType.DECISION,
    ObjectType.EXPRESSION_RULE,
    ObjectType.TRANSLATION_SET,
    ObjectType.RULES_FOLDER,
    ObjectType.CONNECTED_SYSTEM,
    ObjectType.OUTBOUND_INTEGRATION,
    ObjectType.WEB_API,
    ObjectType.EVENT_CONSUMER,
    ObjectType.GROUP,
    ObjectType.GROUP_TYPE,
    ObjectType.DOCUMENT,
    ObjectType.DOCUMENT_FOLDER,
    ObjectType.KNOWLEDGE_CENTER,
    ObjectType.FEED,
)


@dataclass(frozen=True, slots=True)
class ObjectCapability:
    object_type: ObjectType
    official_name: str
    export_dir: str
    content_tag: str
    native_write: bool
    requires_template: bool
    sensitive: bool
    mcp_slug: str

    @property
    def create_tool(self) -> str:
        return f"create_{self.mcp_slug}"

    @property
    def get_tool(self) -> str:
        return f"get_{self.mcp_slug}"

    @property
    def update_tool(self) -> str:
        return f"update_{self.mcp_slug}"

    @property
    def delete_tool(self) -> str:
        return f"delete_{self.mcp_slug}"


def _cap(
    object_type: ObjectType,
    official_name: str,
    export_dir: str,
    *,
    content_tag: str = "",
    native_write: bool = False,
    requires_template: bool = True,
    sensitive: bool = False,
    mcp_slug: str = "",
) -> ObjectCapability:
    return ObjectCapability(
        object_type=object_type,
        official_name=official_name,
        export_dir=export_dir,
        content_tag=content_tag,
        native_write=native_write,
        requires_template=requires_template,
        sensitive=sensitive,
        mcp_slug=mcp_slug or object_type.value,
    )


OBJECT_CAPABILITIES: tuple[ObjectCapability, ...] = (
    _cap(ObjectType.BUSINESS_PROCESS, "Business Process", "businessProcess"),
    _cap(
        ObjectType.DATA_STORE,
        "Data Store",
        "dataStore",
        native_write=True,
        requires_template=False,
        sensitive=True,
    ),
    _cap(
        ObjectType.DATA_TYPE,
        "Data Type",
        "datatype",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.RECORD_TYPE,
        "Record Type",
        "recordType",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.PROCESS_MODEL,
        "Process Model",
        "processModel",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.PROCESS_MODEL_FOLDER,
        "Process Model Folder",
        "processModelFolder",
        native_write=True,
        requires_template=False,
    ),
    _cap(ObjectType.PROCESS_REPORT, "Process Report", "processReport"),
    _cap(ObjectType.ROBOTIC_TASK, "Robotic Task", "roboticTask"),
    _cap(ObjectType.ROBOT_POOL, "Robot Pool", "robotPool"),
    _cap(ObjectType.CONTROL_PANEL, "Control Panel", "controlPanel"),
    _cap(
        ObjectType.CONTROL_PANEL_HIERARCHY_ITEM,
        "Control Panel Hierarchy Item",
        "controlPanelHierarchyItem",
    ),
    _cap(ObjectType.DASHBOARD, "Dashboard", "dashboard"),
    _cap(
        ObjectType.INTERFACE,
        "Interface",
        "content",
        content_tag="interface",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.PORTAL,
        "Portal",
        "portal",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.REPORT,
        "Report",
        "content",
        content_tag="report",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.SITE,
        "Site",
        "site",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.TEMPO_REPORT,
        "Tempo Report",
        "tempoReport",
        native_write=True,
        requires_template=False,
    ),
    _cap(ObjectType.AI_AGENT, "AI Agent", "aiAgent"),
    _cap(ObjectType.AI_SKILL, "AI Skill", "aiSkill"),
    _cap(
        ObjectType.CONSTANT,
        "Constant",
        "content",
        content_tag="constant",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.DECISION,
        "Decision",
        "content",
        content_tag="decision",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.EXPRESSION_RULE,
        "Expression Rule",
        "content",
        content_tag="rule",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.TRANSLATION_SET,
        "Translation Set",
        "translationSet",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.RULES_FOLDER,
        "Rule Folder",
        "content",
        content_tag="rulesFolder",
        native_write=True,
        requires_template=False,
        mcp_slug="rule_folder",
    ),
    _cap(
        ObjectType.CONNECTED_SYSTEM,
        "Connected System",
        "connectedSystem",
        native_write=True,
        requires_template=False,
        sensitive=True,
    ),
    _cap(
        ObjectType.OUTBOUND_INTEGRATION,
        "Integration",
        "content",
        content_tag="outboundIntegration",
        native_write=True,
        requires_template=False,
        mcp_slug="integration",
    ),
    _cap(
        ObjectType.WEB_API,
        "Web API",
        "webApi",
        native_write=True,
        requires_template=False,
    ),
    _cap(ObjectType.EVENT_CONSUMER, "Event Consumer", "eventConsumer"),
    _cap(
        ObjectType.GROUP,
        "Group",
        "group",
        native_write=True,
        requires_template=False,
        sensitive=True,
    ),
    _cap(ObjectType.GROUP_TYPE, "Group Type", "groupType"),
    _cap(
        ObjectType.DOCUMENT,
        "Document",
        "content",
        content_tag="document",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.DOCUMENT_FOLDER,
        "Document Folder",
        "content",
        content_tag="folder",
        native_write=True,
        requires_template=False,
    ),
    _cap(
        ObjectType.KNOWLEDGE_CENTER,
        "Knowledge Center",
        "content",
        content_tag="communityKnowledgeCenter",
        native_write=True,
        requires_template=False,
    ),
    _cap(ObjectType.FEED, "Feed", "feed"),
)

CAPABILITY_BY_TYPE: dict[ObjectType, ObjectCapability] = {
    item.object_type: item for item in OBJECT_CAPABILITIES
}
CAPABILITY_BY_SLUG: dict[str, ObjectCapability] = {
    item.mcp_slug: item for item in OBJECT_CAPABILITIES
}
EXPORT_DIR_TO_TYPE: dict[str, ObjectType] = {
    item.export_dir: item.object_type
    for item in OBJECT_CAPABILITIES
    if item.export_dir != "content"
}
CONTENT_TAG_TO_TYPE: dict[str, ObjectType] = {
    item.content_tag: item.object_type
    for item in OBJECT_CAPABILITIES
    if item.content_tag
}

CRUD_TOOL_NAMES: frozenset[str] = frozenset(
    name
    for item in OBJECT_CAPABILITIES
    for name in (item.create_tool, item.get_tool, item.update_tool, item.delete_tool)
)


def official_export_directories() -> frozenset[str]:
    return frozenset(item.export_dir for item in OBJECT_CAPABILITIES) | {
        "META-INF",
        "application",
        "translationString",
    }
