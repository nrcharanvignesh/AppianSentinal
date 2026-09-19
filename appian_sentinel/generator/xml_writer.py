"""Write and update Appian export XML files.

All XML handling uses ``lxml.etree``.  The canonical namespace is
``http://www.appian.com/ae/types/2009`` (prefix ``a``).
"""

from __future__ import annotations

import logging
import os
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


def _serialize_tree(tree: etree._ElementTree) -> bytes:
    """Serialize and validate an Appian XML tree."""
    data = etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )
    etree.fromstring(data)
    return data


def _atomic_write_xml(output_path: Path, data: bytes) -> None:
    """Validate XML and replace *output_path* atomically."""
    etree.fromstring(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        etree.parse(str(temporary))
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)


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
    _atomic_write_xml(output_path, xml_str.encode("utf-8"))
    logger.info("Wrote content XML to %s", output_path)


def write_record_type_xml(obj_data: dict[str, Any], output_path: Path) -> None:
    """Write a record type XML file.

    Record-type exports have a different top-level element
    (``<recordTypeHaul>``) and internal structure.  *obj_data* should
    mirror the Appian export schema for record types.
    """
    if obj_data.get("action") == "modify" and output_path.exists():
        tree = etree.parse(
            str(output_path),
            etree.XMLParser(remove_blank_text=False, resolve_entities=False),
        )
        root = tree.getroot()
        record_types = root.xpath("//*[local-name()='recordType'][1]")
        if not record_types:
            raise ValueError(f"No record type element found in {output_path}")
        record_type = record_types[0]
        if "name" in obj_data:
            name_attributes = record_type.xpath("@*[local-name()='name']")
            if name_attributes:
                name_key = next(
                    key
                    for key in record_type.attrib
                    if etree.QName(key).localname == "name"
                )
                record_type.set(name_key, str(obj_data["name"]))
            else:
                name_nodes = record_type.xpath("./*[local-name()='name'][1]")
                if not name_nodes:
                    raise ValueError(f"No record type name found in {output_path}")
                name_nodes[0].text = str(obj_data["name"])
        version_nodes = root.xpath("./*[local-name()='versionUuid'][1]")
        if "versionUuid" in obj_data and version_nodes:
            version_nodes[0].text = str(obj_data["versionUuid"])
        _atomic_write_xml(output_path, _serialize_tree(tree))
        logger.info("Updated record-type XML at %s", output_path)
        return

    root = etree.Element("recordTypeHaul", nsmap=NSMAP)
    _se(root, "versionUuid", obj_data.get("versionUuid", ""))

    # Real exports carry identity as attributes on <recordType>, and
    # parse_record_type_xml reads them there, not as child elements.
    rt = _se(root, "recordType")
    rt.set(f"{{{APPIAN_NS}}}uuid", obj_data["uuid"])
    rt.set("name", obj_data["name"])
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

    tree = etree.ElementTree(root)
    _atomic_write_xml(output_path, _serialize_tree(tree))
    logger.info("Wrote record-type XML to %s", output_path)


def write_process_model_xml(obj_data: dict[str, Any], output_path: Path) -> None:
    """Write a process model XML file.

    Process-model exports use ``<processModelHaul>`` as the root element.
    """
    if obj_data.get("action") == "modify" and output_path.exists():
        tree = etree.parse(
            str(output_path),
            etree.XMLParser(remove_blank_text=False, resolve_entities=False),
        )
        root = tree.getroot()
        if "name" in obj_data:
            name_values = root.xpath(
                "//*[local-name()='pm']/*[local-name()='meta']"
                "/*[local-name()='name']//*[local-name()='value'][1]"
            )
            if not name_values:
                raise ValueError(f"No process model name found in {output_path}")
            name_values[0].text = str(obj_data["name"])
        version_nodes = root.xpath("./*[local-name()='versionUuid'][1]")
        if "versionUuid" in obj_data and version_nodes:
            version_nodes[0].text = str(obj_data["versionUuid"])
        _atomic_write_xml(output_path, _serialize_tree(tree))
        logger.info("Updated process-model XML at %s", output_path)
        return

    root = etree.Element("processModelHaul", nsmap=NSMAP)
    _se(root, "versionUuid", obj_data.get("versionUuid", ""))
    if obj_data.get("folderUuid"):
        _se(root, "folderUuid", obj_data["folderUuid"])

    # Real exports nest the model under <process_model_port><pm>, and the name
    # is a locale string-map. parse_process_model_xml requires both.
    pm = _se(_se(root, "process_model_port"), "pm")
    meta = _se(pm, "meta")
    _se(meta, "uuid", obj_data["uuid"])
    pair = _se(_se(_se(meta, "name"), "string-map"), "pair")
    locale = _se(pair, "locale")
    locale.set("country", "US")
    locale.set("lang", "en")
    _se(pair, "value", obj_data["name"])
    if obj_data.get("description"):
        _se(meta, "description", obj_data["description"])
    if obj_data.get("parentUuid"):
        _se(meta, "parentUuid", obj_data["parentUuid"])

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

    tree = etree.ElementTree(root)
    _atomic_write_xml(output_path, _serialize_tree(tree))
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

    _atomic_write_xml(xml_path, _serialize_tree(tree))
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

    _atomic_write_xml(xml_path, _serialize_tree(tree))
    logger.info("Updated rule inputs in %s (%d inputs)", xml_path, len(inputs))


def update_content_nodes(
    xml_path: Path,
    *,
    definition: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    test_nodes: list[str] | None = None,
) -> None:
    """Atomically update only supplied definition, input, and test nodes."""
    data = render_content_nodes(
        xml_path,
        definition=definition,
        inputs=inputs,
        test_nodes=test_nodes,
    )
    _atomic_write_xml(xml_path, data)
    logger.info("Updated content nodes in %s", xml_path)


def render_content_nodes(
    xml_path: Path,
    *,
    definition: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    test_nodes: list[str] | None = None,
) -> bytes:
    """Render supplied content-node changes without writing the file."""
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    tree = etree.parse(str(xml_path), parser)
    root = tree.getroot()
    container = next(
        (
            candidate
            for tag in ("rule", "interface", "constant", "decision")
            if (candidate := root.find(f".//{tag}")) is not None
        ),
        None,
    )
    if container is None:
        raise ValueError(f"No content object element found in {xml_path}")

    if definition is not None:
        definition_el = container.find("definition")
        if definition_el is None:
            raise ValueError(f"No <definition> element found in {xml_path}")
        definition_el.text = definition
        for child in list(definition_el):
            definition_el.remove(child)

    if inputs is not None:
        old_inputs = container.findall("namedTypedValue")
        if old_inputs:
            insert_at = list(container).index(old_inputs[0])
        else:
            preferred_editor = container.find("preferredEditor")
            insert_at = (
                list(container).index(preferred_editor)
                if preferred_editor is not None
                else len(container)
            )
        for old_input in old_inputs:
            container.remove(old_input)
        for offset, new_input in enumerate(_build_named_typed_values(inputs)):
            container.insert(insert_at + offset, new_input)

    if test_nodes is not None:
        old_tests = [child for child in container if etree.QName(child).localname in {"test", "testCase"}]
        insert_at = list(container).index(old_tests[0]) if old_tests else len(container)
        for old_test in old_tests:
            container.remove(old_test)
        for offset, test_xml in enumerate(test_nodes):
            try:
                test_element = etree.fromstring(test_xml.encode("utf-8"))
            except etree.XMLSyntaxError as exc:
                raise ValueError("Invalid test node XML") from exc
            if etree.QName(test_element).localname not in {"test", "testCase"}:
                raise ValueError("Test node root must be <test> or <testCase>")
            container.insert(insert_at + offset, test_element)

    return _serialize_tree(tree)


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
