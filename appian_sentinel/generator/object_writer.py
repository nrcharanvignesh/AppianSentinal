"""Shared object-writing dispatch.

A single ``write_object`` used by both the agent orchestrator and the MCP
server so the mapping from a generated-object dict to the correct
``xml_writer`` call lives in exactly one place.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from appian_sentinel.generator import xml_writer

logger = logging.getLogger(__name__)

# Object-type aliases → target export subdirectory.
_CONTENT_TYPES = {"rule", "expression_rule", "interface", "constant", "decision"}
_RECORD_TYPES = {"record_type", "recordtype"}
_PROCESS_TYPES = {"process_model", "processmodel"}


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
    name = obj.get("name", "unknown")
    action = obj.get("action", "modify")

    try:
        if obj_type in _CONTENT_TYPES:
            out = export_dir / "content" / f"{name}.xml"
            out.parent.mkdir(parents=True, exist_ok=True)
            if action == "modify" and out.exists():
                xml_writer.update_content_definition(out, obj.get("sail_code", obj.get("definition", "")))
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
                out.write_text(xml_str, encoding="utf-8")
        elif obj_type in _RECORD_TYPES:
            out = export_dir / "recordType" / f"{name}.xml"
            out.parent.mkdir(parents=True, exist_ok=True)
            xml_writer.write_record_type_xml(obj, out)
        elif obj_type in _PROCESS_TYPES:
            out = export_dir / "processModel" / f"{name}.xml"
            out.parent.mkdir(parents=True, exist_ok=True)
            xml_writer.write_process_model_xml(obj, out)
        else:
            logger.warning("Unknown object type for write: %s", obj_type)
            return None
    except Exception as exc:
        logger.warning("Failed to write object %s: %s", name, exc)
        return None

    obj["file_path"] = str(out)
    return out
