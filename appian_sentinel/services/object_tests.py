"""Read and safely clone embedded Appian test-case XML."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from appian_sentinel.models.test_case import AppianAssertionType
from appian_sentinel.parser.sail_ast import validate_syntax


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
            "assertion_type": _assertion_type(node).value,
            "expected": _field_text(
                node,
                ("expected", "expectedOutput"),
            ),
            "assertion_expression": _field_text(node, ("assertionExpression",)),
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
    result: list[str] = []
    for test in tests:
        assertion_type = AppianAssertionType(
            test.get("assertion_type", AppianAssertionType.OUTPUT_EQUALS),
        )
        template = next(
            (node for node in existing if _assertion_type(node) is assertion_type),
            None,
        )
        if template is None:
            raise UnsupportedTestCaseError(
                f"no_{assertion_type.value}_test_case_template"
            )
        node = deepcopy(template)
        _set_field(node, ("name",), str(test["name"]), attribute="name")
        _set_field(node, ("description",), str(test["description"]))
        if assertion_type is AppianAssertionType.OUTPUT_EQUALS:
            _set_field(
                node,
                ("expected", "expectedOutput"),
                _value_text(test.get("expected")),
            )
        elif assertion_type is AppianAssertionType.EXPRESSION:
            expression = str(test.get("assertion_expression", "")).strip()
            if not expression or "test!output" not in expression.casefold():
                raise UnsupportedTestCaseError(
                    "assertion_expression_must_reference_test_output"
                )
            if validate_syntax(expression):
                raise UnsupportedTestCaseError("assertion_expression_has_invalid_sail")
            _set_field(node, ("assertionExpression",), expression)
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


def _assertion_type(node: etree._Element) -> AppianAssertionType:
    marker = _field_text(node, ("assertionType",)).strip().casefold()
    if "expression" in marker:
        return AppianAssertionType.EXPRESSION
    if "output" in marker or "match" in marker or "equal" in marker:
        return AppianAssertionType.OUTPUT_EQUALS
    if "error" in marker or "complete" in marker:
        return AppianAssertionType.COMPLETES_WITHOUT_ERROR
    if node.xpath("./*[local-name()='assertionExpression']"):
        return AppianAssertionType.EXPRESSION
    if node.xpath("./*[local-name()='expected' or local-name()='expectedOutput']"):
        return AppianAssertionType.OUTPUT_EQUALS
    return AppianAssertionType.COMPLETES_WITHOUT_ERROR


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
