"""Read and safely clone embedded Appian test-case XML."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree


class UnsupportedTestCaseError(ValueError):
    """The object XML does not expose a reusable test-case schema."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def extract_test_cases(xml_path: Path) -> list[dict[str, Any]]:
    """Return normalized fields plus the source XML for each test case."""
    nodes = _test_nodes(xml_path)
    return [
        {
            "name": _field_text(node, ("name",)) or node.get("name", ""),
            "description": _field_text(node, ("description",)),
            "inputs": _extract_inputs(node),
            "expected": _field_text(
                node,
                ("expected", "expectedOutput", "assertionExpression"),
            ),
            "xml": etree.tostring(node, encoding="unicode", with_tail=False),
        }
        for node in nodes
    ]


def clone_test_nodes(
    xml_path: Path,
    tests: list[dict[str, Any]],
) -> list[str]:
    """Clone the export's existing test node without inventing XML tags."""
    # ponytail: existing template required; add a versioned serializer when Appian publishes the schema.
    existing = _test_nodes(xml_path)
    if not existing:
        raise UnsupportedTestCaseError("no_test_case_template")
    template = existing[0]
    result: list[str] = []
    for test in tests:
        node = deepcopy(template)
        _set_field(node, ("name",), str(test["name"]), attribute="name")
        _set_field(node, ("description",), str(test["description"]))
        _set_field(
            node,
            ("expected", "expectedOutput", "assertionExpression"),
            _value_text(test["expected"]),
        )
        _set_inputs(node, dict(test["inputs"]))
        result.append(etree.tostring(node, encoding="unicode", with_tail=False))
    return result


def _test_nodes(xml_path: Path) -> list[etree._Element]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.parse(str(xml_path), parser).getroot()
    containers = root.xpath(
        "//*[local-name()='rule' or local-name()='interface']",
    )
    if not containers:
        return []
    return [
        node
        for node in containers[0]
        if etree.QName(node).localname in {"test", "testCase"}
    ]


def _field_text(node: etree._Element, names: tuple[str, ...]) -> str:
    for name in names:
        matches = node.xpath(f"./*[local-name()='{name}']")
        if matches:
            return str(matches[0].text or "")
    return ""


def _set_field(
    node: etree._Element,
    names: tuple[str, ...],
    value: str,
    *,
    attribute: str | None = None,
) -> None:
    for name in names:
        matches = node.xpath(f"./*[local-name()='{name}']")
        if matches:
            matches[0].text = value
            return
    if attribute is not None and attribute in node.attrib:
        node.set(attribute, value)
        return
    raise UnsupportedTestCaseError(f"test_case_template_missing_{names[0]}")


def _extract_inputs(node: etree._Element) -> dict[str, str]:
    containers = node.xpath("./*[local-name()='inputs']")
    if not containers:
        return {}
    result: dict[str, str] = {}
    for item in containers[0]:
        name = item.get("name", "") or _field_text(item, ("name",))
        value = item.get("value", "") or _field_text(item, ("value", "expression"))
        if name:
            result[name] = value
    return result


def _set_inputs(node: etree._Element, inputs: dict[str, Any]) -> None:
    containers = node.xpath("./*[local-name()='inputs']")
    if not containers:
        if inputs:
            raise UnsupportedTestCaseError("test_case_template_missing_inputs")
        return
    container = containers[0]
    templates = list(container)
    if inputs and not templates:
        raise UnsupportedTestCaseError("test_case_template_missing_input")
    for child in list(container):
        container.remove(child)
    for name, value in inputs.items():
        item = deepcopy(templates[0])
        if "name" in item.attrib:
            item.set("name", str(name))
        else:
            _set_field(item, ("name",), str(name))
        if "value" in item.attrib:
            item.set("value", _value_text(value))
        else:
            _set_field(item, ("value", "expression"), _value_text(value))
        container.append(item)


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
