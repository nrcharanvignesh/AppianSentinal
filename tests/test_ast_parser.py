from __future__ import annotations

from appian_sentinel.parser.sail_ast import (
    BoolLiteral,
    ComponentCall,
    NullLiteral,
    extract_domain_vars,
    parse_sail,
    validate_syntax,
)


def test_parse_local_variables_and_domain_references() -> None:
    source = (
        'a!localVariables(local!enabled: true(), '
        'if(local!enabled, ri!value, null()))'
    )

    ast = parse_sail(source)

    assert isinstance(ast, ComponentCall)
    assert ast.name == "localVariables"
    assert extract_domain_vars(ast) == {
        "local": {"enabled"},
        "ri": {"value"},
    }
    assert validate_syntax(source) == []


def test_parse_boolean_and_null_call_literals() -> None:
    assert isinstance(parse_sail("true()"), BoolLiteral)
    assert isinstance(parse_sail("false()"), BoolLiteral)
    assert isinstance(parse_sail("null()"), NullLiteral)
    assert validate_syntax("if(true(), null(), false())") == []


def test_invalid_javascript_operators_report_positions() -> None:
    errors = validate_syntax("if(ri!value == 1, true(), false())")

    assert errors
    assert errors[0].pos is not None
    assert errors[0].pos.line == 1
