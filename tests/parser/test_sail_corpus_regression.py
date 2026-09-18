from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from appian_sentinel.models.appian_objects import ExpressionRule, Interface
from appian_sentinel.parser.codebase_map import build_codebase_map
from appian_sentinel.parser.sail_diagnostics import analyze_sail

CORPUS_PATH = Path(__file__).parents[2] / "appian_export"
EXPECTED_OBJECTS = 2624
EXPECTED_DEFINITIONS = 1220
MINIMUM_CLEAN = 1149
MAXIMUM_ERRORING = 71
MAXIMUM_DIAGNOSTICS = {
    "SAIL001": 13,
    "SAIL010": 1,
    "SAIL014": 1,
    "SAIL015": 0,
    "SAIL021": 326,
    "SAIL030": 581,
}


@pytest.mark.skipif(
    os.environ.get("RUN_APPIAN_CORPUS") != "1",
    reason="set RUN_APPIAN_CORPUS=1 to run the large export gate",
)
def test_real_sail_corpus_does_not_regress() -> None:
    codebase = build_codebase_map(CORPUS_PATH)
    known_uuids = set(codebase.objects) | set(codebase.uuid_to_name)
    diagnostics: Counter[str] = Counter()
    definitions = 0
    clean = 0
    erroring = 0

    for obj in codebase.objects.values():
        if not isinstance(obj, (ExpressionRule, Interface)):
            continue
        if not obj.definition.strip():
            continue
        definitions += 1
        analysis = analyze_sail(
            obj.definition,
            target_version=codebase.appian_version or None,
            known_uuids=known_uuids,
        )
        diagnostics.update(item.code for item in analysis.diagnostics)
        if analysis.errors:
            erroring += 1
        else:
            clean += 1

    metrics = {
        "objects": len(codebase.objects),
        "definitions": definitions,
        "clean": clean,
        "erroring": erroring,
        "diagnostics": dict(sorted(diagnostics.items())),
    }
    print(metrics)

    assert len(codebase.objects) == EXPECTED_OBJECTS, metrics
    assert definitions == EXPECTED_DEFINITIONS, metrics
    assert clean >= MINIMUM_CLEAN, metrics
    assert erroring <= MAXIMUM_ERRORING, metrics
    assert not (set(diagnostics) - set(MAXIMUM_DIAGNOSTICS)), metrics
    for code, maximum in MAXIMUM_DIAGNOSTICS.items():
        assert diagnostics[code] <= maximum, metrics
