"""Structural SAIL code validator.

Validates SAIL source text against the rules from the Sentinel Output
Contract without executing it.  This catches syntax-level mistakes that
LLMs commonly make (wrong operators, hallucinated functions, unbalanced
brackets, etc.).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationError:
    """A single validation finding."""

    line: int
    column: int
    message: str
    severity: Severity = Severity.ERROR


@dataclass
class ValidationResult:
    """Aggregated outcome of ``SailValidator.validate``."""

    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    def add(self, error: ValidationError) -> None:
        if error.severity == Severity.ERROR:
            self.errors.append(error)
            self.is_valid = False
        else:
            self.warnings.append(error)


# ---------------------------------------------------------------------------
# Known-bad / hallucinated function list
# ---------------------------------------------------------------------------

# Functions that LLMs commonly invent.  The validator flags any use of these.
HALLUCINATED_FUNCTIONS: frozenset[str] = frozenset({
    "a!filter",
    "a!forEachItem",
    "a!reduce",
    "a!if",
    "a!concat",
    "a!split",
    "a!length",
    "a!append",
    "a!remove",
    "a!contains",
    "a!index",
    "a!toText",
    "a!toNumber",
    "a!toDate",
    "a!toDateTime",
    "a!toBoolean",
    "a!isNull",
    "a!isNotNull",
    "a!isEmpty",
    "a!isNotEmpty",
    "a!sum",
    "a!average",
    "a!min",
    "a!max",
    "a!count",
    "a!distinct",
    "a!sort",
    "a!reverse",
    "a!flatten",
    "a!join",
    "a!trim",
    "a!lower",
    "a!upper",
    "a!replace",
    "a!startsWith",
    "a!endsWith",
    "a!substring",
    "a!mapGet",
    "a!mapPut",
    "a!mapKeys",
    "a!mapValues",
})

# Patterns for forbidden operators
_FORBIDDEN_OPERATORS: list[tuple[str, re.Pattern[str], str]] = [
    ("==", re.compile(r"(?<![=<>!])={2}(?!=)"), "Use '=' for equality, not '=='"),
    ("!=", re.compile(r"!="), "Use '<>' for not-equal, not '!='"),
    ("&&", re.compile(r"&&"), "Use 'and()' for logical AND, not '&&'"),
    ("||", re.compile(r"\|\|"), "Use 'or()' for logical OR, not '||'"),
    (";", re.compile(r";"), "Semicolons are not valid in SAIL"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_col(code: str, pos: int) -> tuple[int, int]:
    """Convert a character offset to 1-based (line, column)."""
    line = code.count("\n", 0, pos) + 1
    last_nl = code.rfind("\n", 0, pos)
    col = pos - last_nl  # 1-based
    return line, col


def _strip_comments(code: str) -> str:
    """Remove ``/* ... */`` comments so they don't trigger false positives."""
    return re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group()), code, flags=re.DOTALL)


def _strip_strings(code: str) -> str:
    """Replace string literal contents with spaces to avoid false positives."""
    return re.sub(r'"[^"]*"', lambda m: '"' + " " * (len(m.group()) - 2) + '"', code)


# ---------------------------------------------------------------------------
# SailValidator
# ---------------------------------------------------------------------------

class SailValidator:
    """Structural SAIL validator enforcing the Sentinel output contract."""

    def __init__(
        self,
        *,
        extra_hallucinated: frozenset[str] | None = None,
    ) -> None:
        self._hallucinated = HALLUCINATED_FUNCTIONS
        if extra_hallucinated:
            self._hallucinated = self._hallucinated | extra_hallucinated

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def validate(self, sail_code: str) -> ValidationResult:
        """Run all structural checks against *sail_code*.

        Returns a :class:`ValidationResult` aggregating all findings.
        """
        result = ValidationResult()
        self._check_bracket_balance(sail_code, result)
        self._check_forbidden_operators(sail_code, result)
        self._check_hallucinated_functions(sail_code, result)
        self._check_string_quoting(sail_code, result)
        self._check_comment_style(sail_code, result)
        self._check_legacy_patterns(sail_code, result)
        return result

    # ------------------------------------------------------------------
    # Reference validation (requires UUID context)
    # ------------------------------------------------------------------

    def validate_references(
        self, sail_code: str, known_uuids: set[str],
    ) -> list[ValidationError]:
        """Check that every ``#"uuid"`` reference resolves to a known UUID."""
        errors: list[ValidationError] = []
        for m in re.finditer(r'#"([^"]+)"', sail_code):
            uuid_str = m.group(1)
            if uuid_str not in known_uuids:
                ln, col = _line_col(sail_code, m.start())
                errors.append(ValidationError(
                    line=ln,
                    column=col,
                    message=f'Unresolved UUID reference: #"{uuid_str}"',
                    severity=Severity.ERROR,
                ))
        return errors

    # ------------------------------------------------------------------
    # Rule-input validation
    # ------------------------------------------------------------------

    def validate_rule_inputs(
        self, sail_code: str, declared_inputs: list[str],
    ) -> list[ValidationError]:
        """Check that ``ri!<name>`` usage matches declared inputs."""
        errors: list[ValidationError] = []
        declared = set(declared_inputs)

        # Find all ri! usages in code (outside strings/comments)
        cleaned = _strip_strings(_strip_comments(sail_code))
        used: set[str] = set()
        for m in re.finditer(r"\bri!(\w+)", cleaned):
            used.add(m.group(1))

        # Used but not declared
        for name in sorted(used - declared):
            errors.append(ValidationError(
                line=0,
                column=0,
                message=f"Rule input 'ri!{name}' used in code but not declared",
                severity=Severity.ERROR,
            ))

        # Declared but not used
        for name in sorted(declared - used):
            errors.append(ValidationError(
                line=0,
                column=0,
                message=f"Declared input '{name}' is never used in the code",
                severity=Severity.WARNING,
            ))

        return errors

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_bracket_balance(self, code: str, result: ValidationResult) -> None:
        """Verify that parentheses, brackets, and braces are balanced."""
        # Strip comments and strings to avoid false hits
        cleaned = _strip_strings(_strip_comments(code))

        openers = {"(": ")", "{": "}", "[": "]"}
        closers = {v: k for k, v in openers.items()}
        stack: list[tuple[str, int]] = []

        for pos, ch in enumerate(cleaned):
            if ch in openers:
                stack.append((ch, pos))
            elif ch in closers:
                if not stack:
                    ln, col = _line_col(code, pos)
                    result.add(ValidationError(
                        line=ln, column=col,
                        message=f"Unmatched closing '{ch}'",
                    ))
                else:
                    top_ch, top_pos = stack[-1]
                    if openers[top_ch] == ch:
                        stack.pop()
                    else:
                        ln, col = _line_col(code, pos)
                        result.add(ValidationError(
                            line=ln, column=col,
                            message=(
                                f"Mismatched bracket: expected '{openers[top_ch]}' "
                                f"to close '{top_ch}' at "
                                f"line {_line_col(code, top_pos)[0]}, "
                                f"but found '{ch}'"
                            ),
                        ))
                        stack.pop()

        for ch, pos in stack:
            ln, col = _line_col(code, pos)
            result.add(ValidationError(
                line=ln, column=col,
                message=f"Unmatched opening '{ch}'",
            ))

    def _check_forbidden_operators(self, code: str, result: ValidationResult) -> None:
        """Flag forbidden operators (==, !=, &&, ||, ;)."""
        # Work on comment-free and string-free text
        cleaned = _strip_strings(_strip_comments(code))

        for label, pattern, suggestion in _FORBIDDEN_OPERATORS:
            for m in pattern.finditer(cleaned):
                ln, col = _line_col(code, m.start())
                result.add(ValidationError(
                    line=ln, column=col,
                    message=f"Forbidden operator '{label}': {suggestion}",
                ))

    def _check_hallucinated_functions(self, code: str, result: ValidationResult) -> None:
        """Flag functions that do not exist in the Appian SAIL API."""
        cleaned = _strip_strings(_strip_comments(code))

        # Match function-call patterns: name(
        for m in re.finditer(r"\b([a-zA-Z_!]+)\s*\(", cleaned):
            fn = m.group(1)
            if fn in self._hallucinated:
                ln, col = _line_col(code, m.start())
                result.add(ValidationError(
                    line=ln, column=col,
                    message=f"Hallucinated function '{fn}' does not exist in SAIL",
                ))

    def _check_string_quoting(self, code: str, result: ValidationResult) -> None:
        """Ensure strings use double quotes only (no single-quoted strings)."""
        # Strip comments first
        no_comments = _strip_comments(code)

        # Look for single-quoted strings.  SAIL does not use single quotes
        # for strings; they only appear in contractions (shouldn't, etc.)
        # which are inside double-quoted strings.  Outside of double-quoted
        # strings, a single quote followed by text and another single quote
        # is suspicious.
        in_double = False
        for pos, ch in enumerate(no_comments):
            if ch == '"':
                in_double = not in_double
            elif ch == "'" and not in_double:
                # Peek ahead to see if this looks like a string literal
                rest = no_comments[pos + 1:]
                closing = rest.find("'")
                if closing != -1 and closing < 200 and "\n" not in rest[:closing]:
                    ln, col = _line_col(code, pos)
                    result.add(ValidationError(
                        line=ln, column=col,
                        message="Possible single-quoted string; SAIL uses double quotes only",
                        severity=Severity.WARNING,
                    ))
                    break  # one warning is enough

    def _check_comment_style(self, code: str, result: ValidationResult) -> None:
        """SAIL only supports ``/* ... */`` comments, not ``//``."""
        # Strip strings so we don't flag // inside string literals
        no_strings = _strip_strings(code)

        for m in re.finditer(r"//[^\n]*", no_strings):
            ln, col = _line_col(code, m.start())
            result.add(ValidationError(
                line=ln, column=col,
                message="Line comment '//' is not valid in SAIL; use /* ... */ instead",
            ))

    def _check_legacy_patterns(self, code: str, result: ValidationResult) -> None:
        """Warn about deprecated SAIL patterns."""
        cleaned = _strip_strings(_strip_comments(code))

        # with() is legacy; should use a!localVariables()
        for m in re.finditer(r"\bwith\s*\(", cleaned):
            ln, col = _line_col(code, m.start())
            result.add(ValidationError(
                line=ln, column=col,
                message="Legacy 'with()' detected; use 'a!localVariables()' instead",
                severity=Severity.WARNING,
            ))
