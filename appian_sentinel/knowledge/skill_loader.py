"""Lazy access to the authoritative data shipped in ``appian.skill``."""

from __future__ import annotations

import importlib.util
import logging
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Callable
from zipfile import BadZipFile, ZipFile

from appian_sentinel.knowledge import resolve_ground_truth_path

_LOGGER = logging.getLogger(__name__)
_ARCHIVE_NAME = "appian.skill"
_LINTER_MEMBER = "appian/reference/sail_lint.py"

SailLintFunction = Callable[[str], object]


@dataclass(frozen=True)
class SkillGroundTruth:
    """Structured rule data extracted from the shipped skill archive."""

    plain_funcs: frozenset[str]
    a_funcs: frozenset[str]
    ref_prefixes: frozenset[str]
    valid_callables: frozenset[str]
    lint: SailLintFunction


def _import_linter(source: bytes) -> ModuleType:
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as temporary:
        temporary.write(source)
        temporary_path = Path(temporary.name)
    try:
        spec = importlib.util.spec_from_file_location("sail_lint", temporary_path)
        if spec is None or spec.loader is None:
            raise ImportError("Could not create the sail_lint import specification")
        module = importlib.util.module_from_spec(spec)
        # The dataclasses module requires this entry while exec_module runs.
        sys.modules["sail_lint"] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop("sail_lint", None)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)


def _string_frozenset(module: ModuleType, name: str) -> frozenset[str]:
    values = getattr(module, name, None)
    if not isinstance(values, frozenset) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError(f"sail_lint.{name} is not a frozenset of strings")
    return frozenset(value.casefold() for value in values)


@lru_cache(maxsize=None)
def _load_skill(path: Path) -> SkillGroundTruth | None:
    if not path.is_file():
        _LOGGER.warning(
            "[WARN] %s is missing; using the built-in SAIL catalog fallback",
            path,
        )
        return None
    try:
        with ZipFile(path) as archive:
            module = _import_linter(archive.read(_LINTER_MEMBER))
        plain_funcs = _string_frozenset(module, "PLAIN_FUNCS")
        a_funcs = _string_frozenset(module, "A_FUNCS")
        ref_prefixes = _string_frozenset(module, "REF_PREFIXES")
        lint = getattr(module, "lint", None)
        if not callable(lint):
            raise ValueError("sail_lint.lint is not callable")
        return SkillGroundTruth(
            plain_funcs=plain_funcs,
            a_funcs=a_funcs,
            ref_prefixes=ref_prefixes,
            valid_callables=plain_funcs | a_funcs,
            lint=lint,
        )
    except (BadZipFile, ImportError, KeyError, OSError, SyntaxError, ValueError) as exc:
        _LOGGER.warning(
            "[WARN] Could not load %s (%s); using the built-in SAIL catalog fallback",
            path,
            exc,
        )
        return None


def load_skill_ground_truth() -> SkillGroundTruth | None:
    """Load and cache the shipped skill data, or return ``None`` on fallback."""
    return _load_skill(resolve_ground_truth_path(_ARCHIVE_NAME))


def get_valid_callables() -> frozenset[str] | None:
    """Return authoritative normalized callables when the archive is available."""
    ground_truth = load_skill_ground_truth()
    return None if ground_truth is None else ground_truth.valid_callables


def get_ref_prefixes() -> frozenset[str] | None:
    """Return authoritative normalized Appian reference prefixes."""
    ground_truth = load_skill_ground_truth()
    return None if ground_truth is None else ground_truth.ref_prefixes


def get_sail_lint() -> SailLintFunction | None:
    """Return the skill's deterministic linter when available."""
    ground_truth = load_skill_ground_truth()
    return None if ground_truth is None else ground_truth.lint


def clear_skill_cache() -> None:
    """Clear cached archive data for tests or changed source files."""
    _load_skill.cache_clear()
