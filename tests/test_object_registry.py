from __future__ import annotations

from appian_sentinel.models.object_registry import (
    CRUD_TOOL_NAMES,
    OBJECT_CAPABILITIES,
    OFFICIAL_DESIGNER_TYPES,
)

EXPECTED_SLUG_TO_DIRECTORY = {
    "business_process": "businessProcess",
    "data_store": "dataStore",
    "data_type": "datatype",
    "record_type": "recordType",
    "process_model": "processModel",
    "process_model_folder": "processModelFolder",
    "process_report": "processReport",
    "robotic_task": "roboticTask",
    "robot_pool": "robotPool",
    "control_panel": "controlPanel",
    "control_panel_hierarchy_item": "controlPanelHierarchyItem",
    "dashboard": "dashboard",
    "interface": "content",
    "portal": "portal",
    "report": "content",
    "site": "site",
    "tempo_report": "tempoReport",
    "ai_agent": "aiAgent",
    "ai_skill": "aiSkill",
    "constant": "content",
    "decision": "content",
    "expression_rule": "content",
    "translation_set": "translationSet",
    "rule_folder": "content",
    "connected_system": "connectedSystem",
    "integration": "content",
    "web_api": "webApi",
    "event_consumer": "eventConsumer",
    "group": "group",
    "group_type": "groupType",
    "document": "content",
    "document_folder": "content",
    "knowledge_center": "content",
    "feed": "feed",
}

NATIVE_WRITER_SLUGS = {
    "data_store",
    "data_type",
    "record_type",
    "process_model",
    "process_model_folder",
    "interface",
    "portal",
    "report",
    "site",
    "tempo_report",
    "constant",
    "decision",
    "expression_rule",
    "translation_set",
    "rule_folder",
    "connected_system",
    "integration",
    "web_api",
    "event_consumer",
    "group",
    "document",
    "document_folder",
    "knowledge_center",
}


def test_official_catalog_has_thirty_four_types() -> None:
    assert len(OFFICIAL_DESIGNER_TYPES) == 34
    assert len(OBJECT_CAPABILITIES) == 34
    assert len({item.mcp_slug for item in OBJECT_CAPABILITIES}) == 34
    assert len(CRUD_TOOL_NAMES) == len(OBJECT_CAPABILITIES) * 4
    assert "create_integration" in CRUD_TOOL_NAMES
    assert "delete_rule_folder" in CRUD_TOOL_NAMES


def test_registry_slugs_directories_and_capabilities_match_appian_exports() -> None:
    by_slug = {item.mcp_slug: item for item in OBJECT_CAPABILITIES}
    assert {slug: item.export_dir for slug, item in by_slug.items()} == (
        EXPECTED_SLUG_TO_DIRECTORY
    )
    assert {item.mcp_slug for item in OBJECT_CAPABILITIES if item.native_write} == (
        NATIVE_WRITER_SLUGS
    )
    assert {
        item.mcp_slug for item in OBJECT_CAPABILITIES if item.requires_template
    } == set(EXPECTED_SLUG_TO_DIRECTORY)
    assert {
        item.mcp_slug for item in OBJECT_CAPABILITIES if item.sensitive
    } == {"connected_system", "data_store", "group"}
    assert (
        sum(
            item.native_write and item.requires_template
            for item in OBJECT_CAPABILITIES
        )
        == 23
    )
    assert sum(not item.native_write for item in OBJECT_CAPABILITIES) == 11
