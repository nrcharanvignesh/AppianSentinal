from __future__ import annotations

import logging
from pathlib import Path

import pytest

from appian_sentinel.knowledge import genai_catalog, skill_loader
from appian_sentinel.parser import sail_catalog


def test_skill_archive_provides_authoritative_callables() -> None:
    skill_loader.clear_skill_cache()
    callables = skill_loader.get_valid_callables()

    assert callables is not None
    assert len(callables) >= 580
    assert {
        "a!apply",
        "a!calllanguagemodel",
        "a!cmicreatefolder",
        "a!localvariables",
    }.issubset(callables)
    assert {"a!filter", "a!foreachitem", "a!reduce"}.isdisjoint(callables)


def test_skill_archive_exposes_prefixes_and_linter() -> None:
    prefixes = skill_loader.get_ref_prefixes()
    lint = skill_loader.get_sail_lint()

    assert prefixes is not None
    assert {"local", "ri", "recordtype"}.issubset(prefixes)
    assert lint is not None
    result = lint("if(local!value == 1, 'yes', \"no\")")
    assert result.findings


def test_genai_catalog_provides_models_protocols_and_limits() -> None:
    genai_catalog.clear_genai_cache()
    models = genai_catalog.get_models()

    assert models is not None
    assert len(models) > 1
    model = genai_catalog.get_model("bedrock.anthropic.claude-opus-4-8")
    assert model is not None
    assert model.protocol == "anthropic"
    assert model.max_input_tokens
    assert model.max_output_tokens
    assert genai_catalog.get_proxy_base_urls()


def test_missing_skill_uses_logged_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.skill"
    monkeypatch.setattr(
        skill_loader,
        "resolve_ground_truth_path",
        lambda filename: missing,
    )
    skill_loader.clear_skill_cache()

    with caplog.at_level(logging.WARNING):
        catalog = sail_catalog.build_default_sail_catalog()

    assert "a!localvariables" in catalog.valid
    assert "built-in SAIL catalog fallback" in caplog.text


def test_missing_workbook_uses_logged_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.xlsx"
    monkeypatch.setattr(
        genai_catalog,
        "resolve_ground_truth_path",
        lambda filename: missing,
    )
    genai_catalog.clear_genai_cache()

    with caplog.at_level(logging.WARNING):
        defaults = genai_catalog.get_config_defaults(
            "http://localhost:4000",
            "primary-fallback",
            "fast-fallback",
        )

    assert defaults is None
    assert "built-in GenAI configuration defaults" in caplog.text
