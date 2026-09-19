from __future__ import annotations

from pathlib import Path

from appian_sentinel.models.appian_objects import Constant, ExpressionRule, TempoReport
from appian_sentinel.parser.xml_parser import parse_appian_xml


def test_expression_rule_definition_is_exposed(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    xml_path = content_dir / "query.xml"
    xml_path.write_text(
        """\
<contentHaul>
  <versionUuid>version-1</versionUuid>
  <rule>
    <name>IHUB_QRY_Activity</name>
    <uuid>rule-1</uuid>
    <definition>#"SYSTEM_SYSRULES_queryRecordType_v1"(
  recordType: #"urn:appian:record-type:v1:record-1"
)</definition>
  </rule>
</contentHaul>
""",
        encoding="utf-8",
    )

    parsed = parse_appian_xml(xml_path)

    assert isinstance(parsed, ExpressionRule)
    assert parsed.definition.startswith('#"SYSTEM_SYSRULES_queryRecordType_v1"(')
    assert "urn:appian:record-type:v1:record-1" in parsed.definition


def test_structured_constant_value_is_exposed_as_xml(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    xml_path = content_dir / "constant.xml"
    xml_path.write_text(
        """\
<contentHaul xmlns:a="http://www.appian.com/ae/types/2009">
  <constant>
    <name>LIST_CONSTANT</name>
    <uuid>constant-1</uuid>
    <typedValue>
      <type>
        <name>Integer?list</name>
        <namespace>http://www.appian.com/ae/types/2009</namespace>
      </type>
      <value>
        <el>10</el>
        <el>20</el>
      </value>
    </typedValue>
  </constant>
</contentHaul>
""",
        encoding="utf-8",
    )

    parsed = parse_appian_xml(xml_path)

    assert isinstance(parsed, Constant)
    assert "<value" in parsed.value
    assert "<el>10</el>" in parsed.value
    assert "<el>20</el>" in parsed.value


def test_reference_constant_value_attribute_is_exposed(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    xml_path = content_dir / "constant.xml"
    xml_path.write_text(
        """\
<contentHaul xmlns:a="http://www.appian.com/ae/types/2009">
  <constant>
    <name>RECORD_TYPE_CONSTANT</name>
    <uuid>constant-2</uuid>
    <typedValue>
      <type>
        <name>RecordType2</name>
        <namespace>http://www.appian.com/ae/types/2009</namespace>
      </type>
      <value a:id="record-type-1"/>
    </typedValue>
  </constant>
</contentHaul>
""",
        encoding="utf-8",
    )

    parsed = parse_appian_xml(xml_path)

    assert isinstance(parsed, Constant)
    assert 'a:id="record-type-1"' in parsed.value


def test_tempo_report_expression_uses_editor_source_field(tmp_path: Path) -> None:
    report_dir = tmp_path / "tempoReport"
    report_dir.mkdir()
    xml_path = report_dir / "report.xml"
    xml_path.write_text(
        """\
<tempoReportHaul xmlns:a="http://www.appian.com/ae/types/2009">
  <tempoReport a:uuid="report-1" name="Activity Report">
    <uiExpr>a!textField(value: "Activity")</uiExpr>
  </tempoReport>
</tempoReportHaul>
""",
        encoding="utf-8",
    )

    parsed = parse_appian_xml(xml_path)

    assert isinstance(parsed, TempoReport)
    assert parsed.expression == 'a!textField(value: "Activity")'
    assert parsed.ui_expression == parsed.expression
