from __future__ import annotations

import random

from appian_sentinel.parser.sail_ast import (
    BoolLiteral,
    DictionaryLiteral,
    FunctionCall,
    NullLiteral,
    SailTokenizer,
    parse_sail,
    validate_syntax,
)

CURATED_26_6_DEFINITIONS = (
    'a!map(name: "Ada", active: true())',
    '{name: "Ada", "display key": "Customer"}',
    "a!forEach(items: ri!items, expression: fv!item)",
    "a!queryRecordType(recordType: recordType!Case, pagingInfo: a!pagingInfo(1, 20))",
    "recordType!RE Customer.fields.customerStatus",
    'recordType!Case(recordType!Case.fields.name: "Ada")',
    "if(a!isNullOrEmpty(ri!value), null(), ri!value)",
    "a!localVariables(local!ready: false(), local!ready)",
)


def test_call_form_literals_have_exact_end_positions() -> None:
    for source, expected_type in (
        ("true()", BoolLiteral),
        ("false()", BoolLiteral),
        ("null()", NullLiteral),
    ):
        node = parse_sail(source)
        assert isinstance(node, expected_type)
        assert node.pos is not None
        assert node.end is not None
        assert (node.pos.offset, node.end.offset) == (0, len(source))


def test_tokens_have_exact_half_open_ranges() -> None:
    source = 'if(\n  "x", true())'
    tokens = SailTokenizer(source).tokenize()

    assert all(token.end is not None for token in tokens)
    assert source[tokens[2].pos.offset : tokens[2].end.offset] == '"x"'
    assert tokens[-1].pos == tokens[-1].end


def test_dictionary_supports_identifier_and_quoted_keys() -> None:
    source = '{name: "Ada", "quoted key": a!map(active: true())}'

    node = parse_sail(source)

    assert isinstance(node, DictionaryLiteral)
    assert len(node.entries) == 2
    assert validate_syntax(source) == []


def test_record_type_domain_and_trailing_argument_parse_cleanly() -> None:
    source = "if(recordType!Case.fields.status = ri!status, true(), false(),)"

    node = parse_sail(source)

    assert isinstance(node, FunctionCall)
    assert node.end is not None
    assert len(node.args) == 3
    assert validate_syntax(source) == []


def test_record_type_with_spaces_and_constructor_field_keys() -> None:
    source = (
        "recordType!RE Customer("
        'recordType!RE Customer.fields.name: "Ada"'
        ")"
    )

    node = parse_sail(source)

    assert isinstance(node, FunctionCall)
    assert node.name == "recordType!RE Customer"
    assert node.args[0].key is not None
    assert validate_syntax(source) == []


def test_empty_argument_recovers_once_and_keeps_later_arguments() -> None:
    source = "if(, true(), false())"

    node = parse_sail(source)
    errors = validate_syntax(source)

    assert isinstance(node, FunctionCall)
    assert len(node.args) == 2
    assert [error.code for error in errors] == ["SAIL003"]


def test_small_deterministic_26_6_corpus_sample_parses_cleanly() -> None:
    sample = random.Random(266).sample(CURATED_26_6_DEFINITIONS, k=4)

    assert sample == random.Random(266).sample(
        CURATED_26_6_DEFINITIONS,
        k=4,
    )
    assert all(validate_syntax(source) == [] for source in sample)


def test_appian_quoted_type_reference_and_root_trailing_comma() -> None:
    source = (
        "cast("
        "'type!{http://www.appian.com/ae/types/2009}Map', "
        "{}"
        "),"
    )

    node = parse_sail(source)

    assert isinstance(node, FunctionCall)
    assert validate_syntax(source) == []


def test_numeric_leading_local_name_from_export_parses() -> None:
    source = (
        "a!localVariables("
        "local!5MB: {true(), false()}, "
        "contains(local!5MB, true())"
        ")"
    )

    assert validate_syntax(source) == []
