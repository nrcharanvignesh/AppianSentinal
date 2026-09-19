"""The codebase map must serialise subclass fields, not just the base class.

Pydantic v2 serialises a field by its declared type. ``CodebaseMap.objects``
is declared ``dict[str, AppianObject]``, so without ``SerializeAsAny`` every
subclass field is dropped on ``model_dump``. The web API returns that dump
directly, so the regression is invisible in Python and total in the UI: every
object arrives with no source and the editor reports "no editable source
definition" for the entire application.
"""

from __future__ import annotations

from appian_sentinel.models.appian_objects import Constant, ExpressionRule, Interface
from appian_sentinel.models.codebase import CodebaseMap


def _map_with(*objects: object) -> CodebaseMap:
    return CodebaseMap(objects={obj.uuid: obj for obj in objects})  # type: ignore[misc]


def test_expression_rule_definition_survives_model_dump() -> None:
    rule = ExpressionRule(
        uuid="uuid-rule",
        name="APP_CalculateTotal",
        definition="a!localVariables(local!x: 1, local!x)",
    )
    dumped = _map_with(rule).model_dump(mode="json")["objects"]["uuid-rule"]

    assert dumped["definition"] == rule.definition


def test_every_source_bearing_subclass_survives_model_dump() -> None:
    rule = ExpressionRule(uuid="u-rule", name="R", definition="1 + 1")
    interface = Interface(uuid="u-iface", name="I", definition="a!textField()")
    constant = Constant(uuid="u-const", name="C", value="42")

    dumped = _map_with(rule, interface, constant).model_dump(mode="json")["objects"]

    assert dumped["u-rule"]["definition"] == "1 + 1"
    assert dumped["u-iface"]["definition"] == "a!textField()"
    assert dumped["u-const"]["value"] == "42"


def test_uuid_collisions_also_keep_subclass_fields() -> None:
    # Collisions are shown to the user with their source, so they need the
    # same treatment as the main object map.
    duplicate = ExpressionRule(uuid="u-dup", name="D", definition="fn!sum(1, 2)")
    codebase = CodebaseMap(uuid_collisions={"u-dup": [duplicate]})

    dumped = codebase.model_dump(mode="json")["uuid_collisions"]["u-dup"][0]

    assert dumped["definition"] == "fn!sum(1, 2)"
