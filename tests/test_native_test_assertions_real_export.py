from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from lxml import etree

from appian_sentinel.models.test_case import AppianAssertionType
from appian_sentinel.services.native_test_assertions import (
    APPIAN_NS,
    ASSERTION_ENUMS,
    XSI_NS,
    clone_test_case_with_assertion,
    extract_native_assertion,
    find_native_test_cases,
)

REAL_EXPORT = Path(__file__).parents[1] / "appian_export"


def _real_test_xml() -> Path:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    for xml_path in (REAL_EXPORT / "content").glob("*.xml"):
        if b"RuleTestConfig?list" not in xml_path.read_bytes():
            continue
        root = etree.parse(str(xml_path), parser).getroot()
        if find_native_test_cases(root):
            return xml_path
    raise AssertionError("real export has no RuleTestConfig test case")


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="real Appian export is not available")
def test_real_export_uses_native_rule_test_config_shape(tmp_path: Path) -> None:
    copied_xml = tmp_path / "real-rule-or-interface.xml"
    shutil.copy2(_real_test_xml(), copied_xml)
    root = etree.parse(str(copied_xml)).getroot()

    cases = find_native_test_cases(root)

    assert cases
    assert etree.QName(cases[0]).localname == "el"
    assertions = cases[0].xpath("./*[local-name()='assertions']")
    assert len(assertions) == 1
    assert etree.QName(assertions[0]).namespace == APPIAN_NS
    assert assertions[0].get(etree.QName(XSI_NS, "nil")) == "true"
    assert (
        extract_native_assertion(cases[0]).assertion_type
        is AppianAssertionType.COMPLETES_WITHOUT_ERROR
    )


@pytest.mark.skipif(not REAL_EXPORT.exists(), reason="real Appian export is not available")
def test_all_assertion_modes_insert_and_recover_in_copied_real_xml(
    tmp_path: Path,
) -> None:
    copied_xml = tmp_path / "real-rule-or-interface.xml"
    shutil.copy2(_real_test_xml(), copied_xml)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    tree = etree.parse(str(copied_xml), parser)
    template = find_native_test_cases(tree.getroot())[0]
    parent = template.getparent()
    assert parent is not None

    generated = [
        clone_test_case_with_assertion(
            template,
            "Sentinel completes",
            AppianAssertionType.COMPLETES_WITHOUT_ERROR,
        ),
        clone_test_case_with_assertion(
            template,
            "Sentinel output",
            AppianAssertionType.OUTPUT_EQUALS,
            expected=42,
        ),
        clone_test_case_with_assertion(
            template,
            "Sentinel expression",
            AppianAssertionType.EXPRESSION,
            assertion_expression="not(isnull(test!output))",
        ),
    ]
    for test_case in generated:
        parent.append(test_case)
    tree.write(str(copied_xml), encoding="utf-8", xml_declaration=True)

    reparsed = etree.parse(str(copied_xml), parser).getroot()
    inserted = find_native_test_cases(reparsed)[-3:]
    recovered = [extract_native_assertion(test_case) for test_case in inserted]

    assert [item.assertion_type for item in recovered] == [
        AppianAssertionType.COMPLETES_WITHOUT_ERROR,
        AppianAssertionType.OUTPUT_EQUALS,
        AppianAssertionType.EXPRESSION,
    ]
    assert recovered[1].expected == 42
    assert recovered[1].expected_xsi_type == "xsd:int"
    assert recovered[2].assertion_expression == "not(isnull(test!output))"
    assert recovered[2].expected_xsi_type == "a:Expression"

    assertion_nodes = [
        test_case.xpath("./*[local-name()='assertions']")[0]
        for test_case in inserted
    ]
    assert all(etree.QName(node).namespace == APPIAN_NS for node in assertion_nodes)
    assert assertion_nodes[0].get(etree.QName(XSI_NS, "nil")) == "true"
    assert [
        node.xpath("string(./*[local-name()='type'])")
        for node in assertion_nodes[1:]
    ] == [
        ASSERTION_ENUMS[AppianAssertionType.OUTPUT_EQUALS],
        ASSERTION_ENUMS[AppianAssertionType.EXPRESSION],
    ]
    assert assertion_nodes[1].xpath(
        "string(./*[local-name()='value']/@*[local-name()='type'])"
    ) == "xsd:int"
