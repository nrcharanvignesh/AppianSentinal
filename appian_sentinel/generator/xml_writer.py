"""Write and update Appian export XML files.

All XML handling uses ``lxml.etree``.  The canonical namespace is
``http://www.appian.com/ae/types/2009`` (prefix ``a``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPIAN_NS = "http://www.appian.com/ae/types/2009"
NSMAP = {"a": APPIAN_NS}
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# XSD type namespace used for <type> elements inside <namedTypedValue>
XSD_NS = "http://www.w3.org/2001/XMLSchema"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _indent(tree: etree._Element, level: int = 0, indent: str = "    ") -> None:
    """Pretty-print an lxml tree in-place (Python 3.8-style indent helper)."""
    i = "\n" + level * indent
    if len(tree):
        if not tree.text or not tree.text.strip():
            tree.text = i + indent
        if not tree.tail or not tree.tail.strip():
            tree.tail = i
        for child in tree:
            _indent(child, level + 1, indent)
        if not child.tail or not child.tail.strip():  # type: ignore[possibly-undefined]
            child.tail = i  # type: ignore[possibly-undefined]
    else:
        if level and (not tree.tail or not tree.tail.strip()):
            tree.tail = i
    if not level:
        tree.tail = "\n"


def _se(parent: etree._Element, tag: str, text: str | None = None, **attribs: str) -> etree._Element:
    """Create a SubElement, optionally setting its text and attributes."""
    elem = etree.SubElement(parent, tag, **attribs)
    if text is not None:
        elem.text = text
    return elem


def _build_role_map(public: bool = True) -> etree._Element:
    """Build the standard ``<roleMap>`` block found in every content haul."""
    role_map = etree.Element("roleMap", public=str(public).lower())
    default_roles = [
        ("readers", True, False),
        ("authors", True, False),
        ("administrators", True, False),
        ("denyReaders", False, False),
        ("denyAuthors", False, False),
        ("denyAdministrators", False, False),
    ]
    for name, inherit, allow_all in default_roles:
        role = _se(role_map, "role", inherit=str(inherit).lower(), allowForAll=str(allow_all).lower(), name=name)
        _se(role, "users")
        _se(role, "groups")
    return role_map


def _build_named_typed_values(inputs: list[dict[str, Any]]) -> list[etree._Element]:
    """Convert a list of ``{name, type_name, type_namespace?}`` dicts to XML elements."""
    elements: list[etree._Element] = []
    for inp in inputs:
        ntv = etree.Element("namedTypedValue")
        _se(ntv, "name", inp["name"])
        type_el = _se(ntv, "type")
        _se(type_el, "name", inp.get("type_name", "Text"))
        _se(type_el, "namespace", inp.get("type_namespace", XSD_NS))
        elements.append(ntv)
    return elements


# ---------------------------------------------------------------------------
# Public API -- full-object writers
# ---------------------------------------------------------------------------

def write_content_xml(
    obj_data: dict[str, Any],
    output_path: Path,
    obj_subtype: str,
) -> None:
    """Write a content object (rule, interface, constant, decision) to *output_path*.

    *obj_data* must contain at minimum ``name``, ``uuid``, ``versionUuid``,
    ``definition``; and optionally ``description``, ``parentUuid``,
    ``rule_inputs`` (list of dicts), ``preferredEditor``, ``offlineEnabled``.
    """
    xml_str = create_new_content_xml(
        name=obj_data["name"],
        uuid=obj_data["uuid"],
        parent_uuid=obj_data.get("parentUuid", ""),
        subtype=obj_subtype,
        definition=obj_data.get("definition", ""),
        rule_inputs=obj_data.get("rule_inputs", []),
        version_uuid=obj_data["versionUuid"],
        description=obj_data.get("description", ""),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logger.info("Wrote content XML to %s", output_path)


def write_record_type_xml(obj_data: dict[str, Any], output_path: Path) -> None:
    """Write a record type XML file.

    Record-type exports have a different top-level element
    (``<recordTypeHaul>``) and internal structure.  *obj_data* should
    mirror the Appian export schema for record types.
    """
    root = etree.Element("recordTypeHaul", nsmap=NSMAP)
    _se(root, "versionUuid", obj_data.get("versionUuid", ""))

    rt = _se(root, "recordType")
    _se(rt, "name", obj_data["name"])
    _se(rt, "uuid", obj_data["uuid"])
    if obj_data.get("description"):
        _se(rt, "description", obj_data["description"])
    if obj_data.get("parentUuid"):
        _se(rt, "parentUuid", obj_data["parentUuid"])

    # Record-type-specific fields
    if obj_data.get("dataSource"):
        ds = _se(rt, "dataSource")
        for key, val in obj_data["dataSource"].items():
            _se(ds, key, str(val))

    if obj_data.get("fields"):
        for field in obj_data["fields"]:
            f_el = _se(rt, "field")
            for key, val in field.items():
                _se(f_el, key, str(val))

    root.append(_build_role_map())
    _se(root, "mcpEnabled", "false")
    _indent(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(
        str(output_path),
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )
    logger.info("Wrote record-type XML to %s", output_path)


def write_process_model_xml(obj_data: dict[str, Any], output_path: Path) -> None:
    """Write a process model XML file.

    Process-model exports use ``<processModelHaul>`` as the root element.
    """
    root = etree.Element("processModelHaul", nsmap=NSMAP)
    _se(root, "versionUuid", obj_data.get("versionUuid", ""))

    pm = _se(root, "processModel")
    _se(pm, "name", obj_data["name"])
    _se(pm, "uuid", obj_data["uuid"])
    if obj_data.get("description"):
        _se(pm, "description", obj_data["description"])
    if obj_data.get("parentUuid"):
        _se(pm, "parentUuid", obj_data["parentUuid"])

    # Process variables
    for pv in obj_data.get("processVariables", []):
        pv_el = _se(pm, "processVariable")
        for key, val in pv.items():
            _se(pv_el, key, str(val))

    # Nodes / flow structure (stored as raw XML string)
    if obj_data.get("nodesXml"):
        try:
            nodes_frag = etree.fromstring(obj_data["nodesXml"])
            pm.append(nodes_frag)
        except etree.XMLSyntaxError:
            logger.warning("Could not parse nodesXml; skipping node injection")

    root.append(_build_role_map())
    _se(root, "mcpEnabled", "false")
    _indent(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(
        str(output_path),
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )
    logger.info("Wrote process-model XML to %s", output_path)


# ---------------------------------------------------------------------------
# Surgical update helpers
# ---------------------------------------------------------------------------

def update_content_definition(xml_path: Path, new_definition: str) -> None:
    """Replace **only** the ``<definition>`` element in an existing XML file.

    All other elements, attributes, comments, and whitespace are preserved
    as closely as possible.
    """
    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    # <definition> lives directly under the first child element (e.g. <rule>)
    definition_el = root.find(".//definition")
    if definition_el is None:
        raise ValueError(f"No <definition> element found in {xml_path}")

    definition_el.text = new_definition
    # Remove any child elements that may exist under <definition>
    for child in list(definition_el):
        definition_el.remove(child)

    tree.write(
        str(xml_path),
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )
    logger.info("Updated <definition> in %s", xml_path)


def update_rule_inputs(xml_path: Path, inputs: list[dict[str, Any]]) -> None:
    """Replace the ``<namedTypedValue>`` elements in an existing XML file.

    Existing ``<namedTypedValue>`` elements are removed and the new ones
    are inserted in the same position relative to the parent element.
    """
    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    # Find the container element (e.g. <rule>, <interface>)
    # namedTypedValue sits directly under the rule/interface element
    container: etree._Element | None = None
    for candidate_tag in ("rule", "interface", "constant", "decision"):
        container = root.find(f".//{candidate_tag}")
        if container is not None:
            break

    if container is None:
        raise ValueError(f"No rule/interface/constant/decision element in {xml_path}")

    # Remove existing namedTypedValue elements and remember the position
    existing_ntvs = container.findall("namedTypedValue")
    insert_index: int | None = None
    for ntv in existing_ntvs:
        if insert_index is None:
            insert_index = list(container).index(ntv)
        container.remove(ntv)

    if insert_index is None:
        # No existing inputs -- insert before <preferredEditor> if present,
        # otherwise at the end of the container.
        pref = container.find("preferredEditor")
        if pref is not None:
            insert_index = list(container).index(pref)
        else:
            insert_index = len(container)

    # Insert new elements
    new_ntvs = _build_named_typed_values(inputs)
    for offset, ntv in enumerate(new_ntvs):
        container.insert(insert_index + offset, ntv)

    tree.write(
        str(xml_path),
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )
    logger.info("Updated rule inputs in %s (%d inputs)", xml_path, len(inputs))


# ---------------------------------------------------------------------------
# Full XML string builder
# ---------------------------------------------------------------------------

def create_new_content_xml(
    name: str,
    uuid: str,
    parent_uuid: str,
    subtype: str,
    definition: str,
    rule_inputs: list[dict[str, Any]],
    version_uuid: str,
    description: str = "",
) -> str:
    """Generate a complete Appian content-haul XML string.

    *subtype* is one of ``"rule"``, ``"interface"``, ``"constant"``,
    ``"decision"``.

    Returns the XML as a UTF-8 string with declaration.
    """
    root = etree.Element("contentHaul", nsmap=NSMAP)
    _se(root, "versionUuid", version_uuid)

    obj = _se(root, subtype)
    _se(obj, "name", name)
    _se(obj, "uuid", uuid)
    if description:
        _se(obj, "description", description)
    if parent_uuid:
        _se(obj, "parentUuid", parent_uuid)
    _se(obj, "definition", definition)

    for ntv in _build_named_typed_values(rule_inputs):
        obj.append(ntv)

    _se(obj, "preferredEditor", "legacy")
    _se(obj, "offlineEnabled", "false")

    root.append(_build_role_map())
    _se(root, "mcpEnabled", "false")

    history = _se(root, "history")
    _se(history, "historyInfo", versionUuid=version_uuid)

    _indent(root)

    xml_bytes: bytes = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )
    return xml_bytes.decode("utf-8")
