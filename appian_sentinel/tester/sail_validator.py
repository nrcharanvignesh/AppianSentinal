"""Compatibility facade over unified SAIL analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from appian_sentinel.parser.sail_catalog import (
    DEFAULT_SAIL_CATALOG,
    SailCallableCatalog,
)
from appian_sentinel.parser.sail_diagnostics import (
    SailAnalysis,
    SailDiagnostic,
    analyze_sail,
)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationError:
    """Backward-compatible validation finding with an exact range."""

    line: int
    column: int
    message: str
    severity: Severity = Severity.ERROR
    code: str = "SAIL001"
    end_line: int = 1
    end_column: int = 2

    @classmethod
    def from_diagnostic(cls, diagnostic: SailDiagnostic) -> ValidationError:
        return cls(
            line=diagnostic.line,
            column=diagnostic.column,
            message=diagnostic.message,
            severity=Severity(diagnostic.severity.value),
            code=diagnostic.code,
            end_line=diagnostic.end_line,
            end_column=diagnostic.end_column,
        )


@dataclass
class ValidationResult:
    """Aggregated compatibility result."""

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    diagnostics: list[SailDiagnostic] = field(default_factory=list)

    @classmethod
    def from_analysis(cls, analysis: SailAnalysis) -> ValidationResult:
        errors = [ValidationError.from_diagnostic(item) for item in analysis.errors]
        warnings = [
            ValidationError.from_diagnostic(item)
            for item in analysis.warnings
        ]
        return cls(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
            diagnostics=analysis.diagnostics,
        )

    def add(self, error: ValidationError) -> None:
        """Preserve the former result mutation API."""
        if error.severity == Severity.ERROR:
            self.errors.append(error)
            self.is_valid = False
        else:
            self.warnings.append(error)


class SailValidator:
    """Validate SAIL through the parser, catalog, and reference analysis."""

    def __init__(
        self,
        *,
        target_version: str | None = None,
        catalog: SailCallableCatalog = DEFAULT_SAIL_CATALOG,
        extra_hallucinated: frozenset[str] | None = None,
    ) -> None:
        self._target_version = target_version
        if extra_hallucinated:
            rejected = catalog.rejected | frozenset(
                name.casefold() for name in extra_hallucinated
            )
            catalog = SailCallableCatalog(catalog.valid, rejected)
        self._catalog = catalog

    def analyze(
        self,
        sail_code: str,
        *,
        known_uuids: set[str] | None = None,
        declared_inputs: list[str] | None = None,
    ) -> SailAnalysis:
        """Return the unified analysis result."""
        return analyze_sail(
            sail_code,
            target_version=self._target_version,
            known_uuids=known_uuids,
            declared_inputs=declared_inputs,
            catalog=self._catalog,
        )

    def validate(self, sail_code: str) -> ValidationResult:
        """Run syntax and callable checks."""
        return ValidationResult.from_analysis(self.analyze(sail_code))

    def validate_references(
        self,
        sail_code: str,
        known_uuids: set[str],
    ) -> list[ValidationError]:
        """Return unresolved UUID findings with exact locations."""
        return [
            ValidationError.from_diagnostic(item)
            for item in self.analyze(
                sail_code,
                known_uuids=known_uuids,
            ).diagnostics
            if item.code == "SAIL030"
        ]

    def validate_rule_inputs(
        self,
        sail_code: str,
        declared_inputs: list[str],
    ) -> list[ValidationError]:
        """Return rule-input findings with exact locations."""
        return [
            ValidationError.from_diagnostic(item)
            for item in self.analyze(
                sail_code,
                declared_inputs=declared_inputs,
            ).diagnostics
            if item.code in {"SAIL031", "SAIL032"}
        ]
