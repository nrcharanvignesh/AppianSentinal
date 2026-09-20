"""Atomic updates for Appian application membership and export.log."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from lxml import etree

from appian_sentinel.models.appian_objects import ObjectType
from appian_sentinel.models.object_registry import CAPABILITY_BY_TYPE
from appian_sentinel.services.mutation_transaction import MutationTransaction

_APPLICATION_GLOB: Final[str] = "application/*.xml"
_EXPORT_LOG: Final[Path] = Path("META-INF") / "export.log"
_CONTENT_TYPES: Final[frozenset[ObjectType]] = frozenset(
    {
        ObjectType.EXPRESSION_RULE,
        ObjectType.INTERFACE,
        ObjectType.CONSTANT,
        ObjectType.DECISION,
        ObjectType.REPORT,
        ObjectType.RULES_FOLDER,
        ObjectType.OUTBOUND_INTEGRATION,
        ObjectType.DOCUMENT,
        ObjectType.FOLDER,
        ObjectType.DOCUMENT_FOLDER,
        ObjectType.KNOWLEDGE_CENTER,
    }
)
_APPLICATION_TAG_OVERRIDES: Final[dict[ObjectType, str]] = {
    ObjectType.PROCESS_REPORT: "taskReport",
    ObjectType.ROBOTIC_TASK: "roboticTaskDesignObject",
    ObjectType.ROBOT_POOL: "robotPoolDesignObject",
    ObjectType.CONTROL_PANEL_HIERARCHY_ITEM: "controlPanelTierItem",
    ObjectType.FEED: "tempoFeed",
}
_APPLICATION_SLOT_ORDER: Final[tuple[str, ...]] = (
    "datatype",
    "dataStore",
    "user",
    "groupType",
    "group",
    "content",
    "forum",
    "processModelFolder",
    "processModel",
    "portlet",
    "page",
    "application",
    "tempoFeed",
    "recordType",
    "recordField",
    "recordRelationship",
    "tempoReport",
    "taskReport",
    "webApi",
    "site",
    "adminSetting",
    "thirdPartyCredentials",
    "dataSource",
    "embeddedSailTheme",
    "connectedSystem",
    "pluginInfo",
    "featureFlag",
    "designObjectReferenceImplementation",
    "aiSkill",
    "roboticTaskDesignObject",
    "robotPoolDesignObject",
    "portal",
    "translationSet",
    "translationString",
    "translationVariable",
    "controlPanel",
    "controlPanelTierItem",
    "eventConsumer",
    "aiAgent",
    "report",
    "dashboard",
    "businessProcess",
)
_SUCCESS_HEADER = re.compile(rb"^Success \(([0-9,]+)\):(?P<ending>\r\n|\n|\r)?$")
_SUCCESS_LINE = re.compile(
    rb'^(?P<tag>\S+) (?P<id>[0-9]+) (?P<uuid>\S+) "(?P<name>.*)"(?P<ending>\r\n|\n|\r)?$'
)


class ExportMetadataError(ValueError):
    """Raised when Appian export metadata is missing or malformed."""


def metadata_tags(object_type: ObjectType) -> tuple[str, str]:
    """Return the export.log and application membership tags for a type."""
    if object_type in _CONTENT_TYPES:
        return "content", "content"
    capability = CAPABILITY_BY_TYPE.get(object_type)
    if capability is None:
        raise ExportMetadataError(f"unsupported object type: {object_type.value}")
    export_tag = capability.export_dir
    application_tag = _APPLICATION_TAG_OVERRIDES.get(object_type, export_tag)
    return export_tag, application_tag


def next_export_log_id(export_log: bytes, export_tag: str) -> int:
    """Return one more than the largest positive ID used by *export_tag*."""
    tag = _ascii_token(export_tag, "export_tag").encode("ascii")
    identifiers = [
        int(match.group("id"))
        for line in export_log.splitlines()
        if (match := _SUCCESS_LINE.match(line)) is not None
        and match.group("tag") == tag
        and int(match.group("id")) > 0
    ]
    return max(identifiers, default=0) + 1


def update_export_log(
    export_log: bytes,
    export_tag: str,
    object_uuid: str,
    name: str,
    *,
    add: bool,
) -> bytes:
    """Add, update, or remove one Success entry without duplicate UUIDs."""
    tag = _ascii_token(export_tag, "export_tag").encode("ascii")
    uuid = _utf8_token(object_uuid, "object_uuid").encode("utf-8")
    safe_name = _log_name(name).encode("utf-8")
    lines = export_log.splitlines(keepends=True)
    header_index = _success_header_index(lines)
    entry_indexes = _success_entry_indexes(lines, header_index)
    matching = [
        index
        for index in entry_indexes
        if (match := _SUCCESS_LINE.match(lines[index])) is not None
        and match.group("tag") == tag
        and match.group("uuid") == uuid
    ]

    changed = False
    if add:
        if matching:
            first = matching[0]
            match = _SUCCESS_LINE.match(lines[first])
            assert match is not None
            replacement = (
                tag
                + b" "
                + match.group("id")
                + b" "
                + uuid
                + b' "'
                + safe_name
                + b'"'
                + _line_ending(lines[first], _preferred_ending(lines, header_index))
            )
            if lines[first] != replacement:
                lines[first] = replacement
                changed = True
            for index in reversed(matching[1:]):
                del lines[index]
                changed = True
        else:
            ending = _preferred_ending(lines, header_index)
            new_line = (
                tag
                + b" "
                + str(next_export_log_id(export_log, export_tag)).encode("ascii")
                + b" "
                + uuid
                + b' "'
                + safe_name
                + b'"'
                + ending
            )
            insert_at = entry_indexes[-1] + 1 if entry_indexes else header_index + 1
            lines.insert(insert_at, new_line)
            changed = True
    else:
        for index in reversed(matching):
            del lines[index]
            changed = True

    if not changed:
        return export_log
    _replace_success_count(lines, header_index)
    return b"".join(lines)


def update_application_membership(
    application_xml: bytes,
    export_tag: str,
    object_uuid: str,
    *,
    add: bool,
) -> bytes:
    """Update the real Appian globalIdMap membership structure."""
    tag = _ascii_token(export_tag, "export_tag")
    object_uuid = _utf8_token(object_uuid, "object_uuid")
    parser = etree.XMLParser(
        remove_blank_text=False,
        resolve_entities=False,
        no_network=True,
        strip_cdata=False,
    )
    try:
        tree = etree.fromstring(application_xml, parser)
    except etree.XMLSyntaxError as exc:
        raise ExportMetadataError("application XML is not valid") from exc

    maps = tree.xpath(
        ".//*[local-name()='application']"
        "/*[local-name()='associatedObjects']"
        "/*[local-name()='globalIdMap']"
    )
    if len(maps) != 1:
        raise ExportMetadataError("application XML must contain one associatedObjects/globalIdMap")
    global_id_map = maps[0]
    items = [
        item
        for item in global_id_map
        if _local_name(item) == "item"
        and (_direct_child_text(item, "type") or "") == tag
    ]
    uuid_nodes = [
        node
        for item in items
        for uuids in item
        if _local_name(uuids) == "uuids"
        for node in uuids
        if _local_name(node) == "uuid" and (node.text or "") == object_uuid
    ]

    changed = False
    if add:
        if uuid_nodes:
            for node in uuid_nodes[1:]:
                node.getparent().remove(node)
                changed = True
        else:
            if items:
                uuids = _direct_child(items[0], "uuids")
                if uuids is None:
                    uuids = etree.SubElement(items[0], _qualified_like(items[0], "uuids"))
            else:
                item = etree.SubElement(global_id_map, _qualified_like(global_id_map, "item"))
                type_node = etree.SubElement(item, _qualified_like(item, "type"))
                type_node.text = tag
                uuids = etree.SubElement(item, _qualified_like(item, "uuids"))
                _place_application_item(global_id_map, item, tag)
            node = etree.SubElement(uuids, _qualified_like(uuids, "uuid"))
            node.text = object_uuid
            changed = True
    else:
        for node in uuid_nodes:
            node.getparent().remove(node)
            changed = True

    if not changed:
        return application_xml
    docinfo = tree.getroottree().docinfo
    return etree.tostring(
        tree.getroottree(),
        encoding=docinfo.encoding or "UTF-8",
        xml_declaration=bool(docinfo.xml_version),
        standalone=docinfo.standalone,
        pretty_print=False,
    )


def update_export_metadata(
    export_dir: Path,
    export_tag: str,
    object_uuid: str,
    name: str,
    *,
    add: bool,
    application_tag: str | None = None,
) -> list[Path]:
    """Atomically update both metadata files and return changed relative paths."""
    root = export_dir.resolve()
    updates = build_export_metadata_updates(
        root,
        export_tag,
        object_uuid,
        name,
        add=add,
        application_tag=application_tag,
    )
    transaction = MutationTransaction(root)
    for path, content in updates.items():
        transaction.write(path, content)
    changed = transaction.commit()
    return [path.relative_to(root) for path in changed]


def build_export_metadata_updates(
    export_dir: Path,
    export_tag: str,
    object_uuid: str,
    name: str,
    *,
    add: bool,
    application_tag: str | None = None,
) -> dict[Path, bytes]:
    """Build metadata file replacements without changing the filesystem."""
    root = export_dir.resolve()
    application_paths = sorted(root.glob(_APPLICATION_GLOB))
    if len(application_paths) != 1:
        raise ExportMetadataError("export must contain exactly one application XML file")
    application_path = application_paths[0]
    log_path = root / _EXPORT_LOG
    if not log_path.is_file():
        raise ExportMetadataError("export must contain META-INF/export.log")
    updates = {
        application_path: update_application_membership(
            application_path.read_bytes(),
            application_tag or export_tag,
            object_uuid,
            add=add,
        ),
        log_path: update_export_log(
            log_path.read_bytes(),
            export_tag,
            object_uuid,
            name,
            add=add,
        ),
    }
    return {
        path: content
        for path, content in updates.items()
        if path.read_bytes() != content
    }


def build_object_metadata_updates(
    export_dir: Path,
    object_type: ObjectType,
    object_uuid: str,
    name: str,
    *,
    add: bool,
) -> dict[Path, bytes]:
    """Build per-type metadata replacements without writing either file."""
    export_tag, application_tag = metadata_tags(object_type)
    return build_export_metadata_updates(
        export_dir,
        export_tag,
        object_uuid,
        name,
        add=add,
        application_tag=application_tag,
    )


def update_object_metadata(
    export_dir: Path,
    object_type: ObjectType,
    object_uuid: str,
    name: str,
    *,
    add: bool,
) -> list[Path]:
    """Update metadata using the real per-type log and membership tags."""
    export_tag, application_tag = metadata_tags(object_type)
    return update_export_metadata(
        export_dir,
        export_tag,
        object_uuid,
        name,
        add=add,
        application_tag=application_tag,
    )


def _ascii_token(value: str, field: str) -> str:
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        raise ExportMetadataError(f"{field} must be one non-empty token")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExportMetadataError(f"{field} must contain ASCII characters only") from exc
    return value


def _utf8_token(value: str, field: str) -> str:
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        raise ExportMetadataError(f"{field} must be one non-empty token")
    return value


def _log_name(name: str) -> str:
    if "\n" in name or "\r" in name:
        raise ExportMetadataError("name must not contain line breaks")
    return name.replace('"', "'")


def _success_header_index(lines: list[bytes]) -> int:
    indexes = [index for index, line in enumerate(lines) if _SUCCESS_HEADER.match(line)]
    if len(indexes) != 1:
        raise ExportMetadataError("export.log must contain one Success header")
    return indexes[0]


def _success_entry_indexes(lines: list[bytes], header_index: int) -> list[int]:
    indexes: list[int] = []
    for index in range(header_index + 1, len(lines)):
        if _SUCCESS_LINE.match(lines[index]) is None:
            break
        indexes.append(index)
    return indexes


def _replace_success_count(lines: list[bytes], header_index: int) -> None:
    ending = _line_ending(lines[header_index], _preferred_ending(lines, header_index))
    count = len(_success_entry_indexes(lines, header_index))
    lines[header_index] = f"Success ({count:,}):".encode("ascii") + ending


def _preferred_ending(lines: list[bytes], header_index: int) -> bytes:
    for line in lines[header_index:]:
        ending = _line_ending(line, b"")
        if ending:
            return ending
    return b"\n"


def _line_ending(line: bytes, default: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    if line.endswith(b"\r"):
        return b"\r"
    return default


def _local_name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _direct_child(node: etree._Element, name: str) -> etree._Element | None:
    return next((child for child in node if _local_name(child) == name), None)


def _direct_child_text(node: etree._Element, name: str) -> str | None:
    child = _direct_child(node, name)
    return child.text if child is not None else None


def _qualified_like(node: etree._Element, local_name: str) -> str:
    namespace = etree.QName(node).namespace
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _place_application_item(
    global_id_map: etree._Element,
    item: etree._Element,
    tag: str,
) -> None:
    """Place a missing type slot in Appian's canonical globalIdMap order."""
    try:
        rank = _APPLICATION_SLOT_ORDER.index(tag)
    except ValueError:
        return
    for sibling in global_id_map:
        if sibling is item or _local_name(sibling) != "item":
            continue
        sibling_tag = _direct_child_text(sibling, "type") or ""
        try:
            sibling_rank = _APPLICATION_SLOT_ORDER.index(sibling_tag)
        except ValueError:
            continue
        if sibling_rank > rank:
            sibling.addprevious(item)
            return
