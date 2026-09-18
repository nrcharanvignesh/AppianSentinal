"""Known-invalid and false-positive guards for icon diagnostics."""

from __future__ import annotations

from appian_sentinel.knowledge.icon_catalog import (
    CORPUS_OBSERVED_RICH_TEXT_ALIASES,
    CORPUS_OBSERVED_SYSTEM_ICON_KEYS,
    IS_TRUNCATED,
    load_icon_catalog,
    rich_text_icon_aliases,
    system_icon_keys,
)
from appian_sentinel.parser.sail_diagnostics import (
    DiagnosticSeverity,
    analyze_sail,
)

_EXPECTED_RICH_SCRAPE_COUNT = 47
_EXPECTED_INDICATOR_KEY_COUNT = 19
_EXPECTED_NEWS_KEY_COUNT = 13


def _codes(source: str) -> list[tuple[str, DiagnosticSeverity]]:
    return [(item.code, item.severity) for item in analyze_sail(source).diagnostics]


def _icon_findings(source: str) -> list[tuple[str, DiagnosticSeverity, str]]:
    return [
        (item.code, item.severity, item.message)
        for item in analyze_sail(source).diagnostics
        if item.code in {"SAIL041", "SAIL042"}
    ]


def test_catalog_is_truncated_partial_scrape() -> None:
    catalog = load_icon_catalog()
    aliases = rich_text_icon_aliases()
    keys = system_icon_keys()
    assert catalog.archive_available is True
    assert catalog.is_complete is False
    assert catalog.is_truncated is True
    assert IS_TRUNCATED is True
    assert catalog.rich_text_covered_prefix == "a"
    assert catalog.rich_text_scrape_count == _EXPECTED_RICH_SCRAPE_COUNT
    assert catalog.indicator_key_count == _EXPECTED_INDICATOR_KEY_COUNT
    assert catalog.news_event_key_count == _EXPECTED_NEWS_KEY_COUNT
    assert "address-book" in aliases
    assert "ADD" in keys
    assert "zoom-in" not in aliases
    assert "address-book" not in keys
    assert "ADD" not in aliases


def test_corpus_observed_icons_are_recognized_but_catalog_remains_partial() -> None:
    catalog = load_icon_catalog()
    assert CORPUS_OBSERVED_RICH_TEXT_ALIASES <= catalog.rich_text_aliases
    assert CORPUS_OBSERVED_SYSTEM_ICON_KEYS <= catalog.system_icon_keys
    assert catalog.is_complete is False
    for alias in CORPUS_OBSERVED_RICH_TEXT_ALIASES:
        assert _icon_findings(f'a!richTextIcon(icon: "{alias}")') == []
    for key in CORPUS_OBSERVED_SYSTEM_ICON_KEYS:
        assert _icon_findings(f'a!iconIndicator(icon: "{key}")') == []


def test_valid_rich_text_alias_has_no_icon_diagnostic() -> None:
    findings = _icon_findings('a!richTextIcon(icon: "address-book")')
    assert findings == []


def test_near_miss_rich_text_alias_is_error_with_suggestion() -> None:
    findings = _icon_findings('a!richTextIcon(icon: "adress-book")')
    assert len(findings) == 1
    code, severity, message = findings[0]
    assert code == "SAIL041"
    assert severity == DiagnosticSeverity.ERROR
    assert "address-book" in message


def test_underscore_near_miss_is_error_with_suggestion() -> None:
    findings = _icon_findings('a!richTextIcon(icon: "address_book")')
    assert len(findings) == 1
    assert findings[0][1] == DiagnosticSeverity.ERROR
    assert "address-book" in findings[0][2]


def test_unknown_plausible_icon_is_warning_not_error() -> None:
    findings = _icon_findings('a!richTextIcon(icon: "zoom-in")')
    assert len(findings) == 1
    code, severity, message = findings[0]
    assert code == "SAIL041"
    assert severity == DiagnosticSeverity.WARNING
    assert severity != DiagnosticSeverity.ERROR
    assert "truncated" in message
    assert analyze_sail('a!richTextIcon(icon: "zoom-in")').errors == []


def test_valid_system_key_has_no_icon_diagnostic() -> None:
    assert _icon_findings('a!iconIndicator(icon: "ADD")') == []
    assert _icon_findings('a!iconNewsEvent(icon: "ADD")') == []


def test_unknown_system_key_is_warning_not_error() -> None:
    findings = _icon_findings('a!iconIndicator(icon: "BOGUS_KEY")')
    assert len(findings) == 1
    assert findings[0][0] == "SAIL042"
    assert findings[0][1] == DiagnosticSeverity.WARNING
    assert analyze_sail('a!iconIndicator(icon: "BOGUS_KEY")').errors == []


def test_dynamic_icon_argument_is_not_flagged() -> None:
    assert _icon_findings("a!richTextIcon(icon: local!icon)") == []
    assert _icon_findings("a!iconIndicator(icon: ri!key)") == []
    assert _icon_findings('a!richTextIcon(icon: concat("ad", "dress-book"))') == []


def test_namespaces_do_not_cross_validate() -> None:
    rich_as_system = _icon_findings('a!iconIndicator(icon: "address-book")')
    system_as_rich = _icon_findings('a!richTextIcon(icon: "ADD")')
    assert rich_as_system[0][0] == "SAIL042"
    assert system_as_rich[0][0] == "SAIL041"
    assert all(item[1] == DiagnosticSeverity.WARNING for item in rich_as_system)
    assert all(item[1] == DiagnosticSeverity.WARNING for item in system_as_rich)
    extra = [code for code, _severity in _codes('a!iconIndicator(icon: "address-book")') if code == "SAIL041"]
    assert extra == []


def test_icon_lane_does_not_change_callable_diagnostics() -> None:
    apply_result = analyze_sail("a!apply(concat, {1})", target_version="26.6")
    assert [
        item.code for item in apply_result.diagnostics if item.code in {"SAIL020", "SAIL021"}
    ] == []
    unknown = analyze_sail("a!futureWidget(value: 1)", target_version="26.6")
    assert [(item.code, item.severity) for item in unknown.diagnostics] == [
        ("SAIL021", DiagnosticSeverity.WARNING),
    ]
    invalid = analyze_sail("a!filter(items: {})", target_version="26.6")
    assert any(
        item.code == "SAIL020" and item.severity == DiagnosticSeverity.ERROR
        for item in invalid.diagnostics
    )
