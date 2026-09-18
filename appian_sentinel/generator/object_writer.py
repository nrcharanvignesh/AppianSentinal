"""Shared object-writing dispatch.

A single ``write_object`` used by both the agent orchestrator and the MCP
server so the mapping from a generated-object dict to the correct
``xml_writer`` call lives in exactly one place.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from lxml import etree

from appian_sentinel.generator import xml_writer
from appian_sentinel.parser.sail_diagnostics import analyze_sail

logger = logging.getLogger(__name__)

# Object-type aliases to target export subdirectory.
_CONTENT_TYPES = {"rule", "expression_rule", "interface", "constant", "decision"}
_RECORD_TYPES = {"record_type", "recordtype"}
_PROCESS_TYPES = {"process_model", "processmodel"}
_OBJECT_DIRS = (
    "content",
    "processModel",
    "recordType",
    "datatype",
    "webApi",
    "connectedSystem",
    "site",
    "group",
    "dataStore",
)
_LOG_LINE = re.compile(r'^\S+\s+\d+\s+(\S+)\s+"(.+)"$')


class ObjectWriteError(RuntimeError):
    """A generated object could not be validated or written."""

    def __init__(
        self,
        *,
        object_name: str,
        object_type: str,
        action: str,
        target_path: Path,
        reason: str,
    ) -> None:
        self.object_name = object_name
        self.object_type = object_type
        self.action = action
        self.target_path = target_path
        self.reason = reason
        super().__init__(
            f"Failed to {action} {object_type} {object_name!r} at "
            f"{target_path}: {reason}"
        )


def _xml_uuid(path: Path) -> str:
    try:
        root = etree.parse(str(path)).getroot()
    except (OSError, etree.XMLSyntaxError):
        return ""
    attributes = root.xpath(
        "//*[local-name()='recordType'][1]/@*[local-name()='uuid']"
    )
    if attributes:
        return str(attributes[0]).strip()
    values = root.xpath("//*[local-name()='uuid'][1]/text()")
    if values:
        return str(values[0]).strip()
    return ""


def _uuid_index(export_dir: Path) -> tuple[dict[str, Path], dict[str, str]]:
    by_uuid: dict[str, Path] = {}
    by_name: dict[str, str] = {}
    log_path = export_dir / "META-INF" / "export.log"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _LOG_LINE.match(line)
            if match:
                by_name[match.group(2)] = match.group(1)
    for directory in _OBJECT_DIRS:
        for path in (export_dir / directory).glob("*"):
            if path.is_file() and path.suffix.lower() in {".xml", ".xsd"}:
                object_uuid = _xml_uuid(path)
                if object_uuid:
                    by_uuid[object_uuid] = path
    return by_uuid, by_name


def _resolve_existing(export_dir: Path, obj: dict[str, Any]) -> Path:
    by_uuid, by_name = _uuid_index(export_dir)
    object_uuid = str(obj.get("uuid", ""))
    if not object_uuid:
        object_uuid = by_name.get(str(obj.get("name", "")), "")
        if object_uuid:
            obj["uuid"] = object_uuid
    path = by_uuid.get(object_uuid)
    if path is None:
        raise FileNotFoundError(f"No indexed file found for UUID {object_uuid!r}")
    return path


def _new_path(export_dir: Path, directory: str, obj: dict[str, Any]) -> Path:
    object_uuid = str(obj.get("uuid", "")).strip()
    if not object_uuid or object_uuid in {".", ".."} or any(char in object_uuid for char in "/\\"):
        raise ValueError("A safe UUID is required for a new object")
    return export_dir / directory / f"{object_uuid}.xml"


def write_object(export_dir: Path, obj: dict[str, Any]) -> Path | None:
    """Write a generated / modified object into *export_dir*.

    *obj* keys used: ``type`` (rule|interface|constant|decision|record_type|
    process_model), ``name``, ``action`` (create|modify), ``sail_code`` /
    ``definition``, plus type-specific fields consumed by ``xml_writer``.

    On success the written path is stamped onto ``obj["file_path"]`` so the
    patch builder can locate freshly-created objects, and returned.
    """
    export_dir = Path(export_dir)
    obj_type = str(obj.get("type", "rule")).lower()
    name = str(obj.get("name", "unknown"))
    action = str(obj.get("action", "modify"))
    out = export_dir

    try:
        if obj_type in _CONTENT_TYPES:
            out = _resolve_existing(export_dir, obj) if action == "modify" else _new_path(export_dir, "content", obj)
            out.parent.mkdir(parents=True, exist_ok=True)
            definition = obj.get("sail_code", obj.get("definition"))
            if isinstance(definition, str):
                declared_inputs = [
                    str(item["name"])
                    for item in obj.get("rule_inputs", [])
                    if isinstance(item, dict) and "name" in item
                ]
                analysis = analyze_sail(
                    definition,
                    declared_inputs=declared_inputs or None,
                )
                if not analysis.is_valid:
                    codes = ", ".join(item.code for item in analysis.errors)
                    raise ObjectWriteError(
                        object_name=name,
                        object_type=obj_type,
                        action=action,
                        target_path=out,
                        reason=f"SAIL validation failed: {codes}",
                    )
            if action == "modify":
                inputs = obj.get("rule_inputs") if "rule_inputs" in obj else None
                test_nodes = obj.get("test_nodes") if "test_nodes" in obj else None
                xml_writer.update_content_nodes(
                    out,
                    definition=definition,
                    inputs=inputs,
                    test_nodes=test_nodes,
                )
            else:
                subtype = "rule" if obj_type in ("rule", "expression_rule") else obj_type
                xml_str = xml_writer.create_new_content_xml(
                    name=name,
                    uuid=obj.get("uuid", ""),
                    parent_uuid=obj.get("parentUuid", obj.get("parent_uuid", "")),
                    subtype=subtype,
                    definition=obj.get("sail_code", obj.get("definition", "")),
                    rule_inputs=obj.get("rule_inputs", []),
                    version_uuid=obj.get("versionUuid", obj.get("version_uuid", "")),
                    description=obj.get("description", ""),
                )
                xml_writer._atomic_write_xml(out, xml_str.encode("utf-8"))
        elif obj_type in _RECORD_TYPES:
            out = (
                _resolve_existing(export_dir, obj)
                if action == "modify"
                else _new_path(export_dir, "recordType", obj)
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            xml_writer.write_record_type_xml(obj, out)
        elif obj_type in _PROCESS_TYPES:
            out = (
                _resolve_existing(export_dir, obj)
                if action == "modify"
                else _new_path(export_dir, "processModel", obj)
            )
            out.parent.mkdir(parents=True, exist_ok=True)
            xml_writer.write_process_model_xml(obj, out)
        else:
            logger.warning("Unknown object type for write: %s", obj_type)
            return None
    except ObjectWriteError:
        raise
    except Exception as exc:
        raise ObjectWriteError(
            object_name=name,
            object_type=obj_type,
            action=action,
            target_path=out,
            reason=str(exc),
        ) from exc

    obj["file_path"] = str(out)
    return out
