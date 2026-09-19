"""Unified diagnostics for SAIL parsing and static analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from enum import Enum

from appian_sentinel.knowledge.icon_catalog import load_icon_catalog
from appian_sentinel.parser.sail_ast import (
    ComponentCall,
    DomainVar,
    FunctionCall,
    Node,
    NodeVisitor,
    SailTokenizer,
    SourcePosition,
    SourceRange,
    StringLiteral,
    UuidCall,
    parse_sail_with_context,
)
from appian_sentinel.parser.sail_catalog import (
    DEFAULT_SAIL_CATALOG,
    SailCallableCatalog,
)


class DiagnosticSeverity(str, Enum):
    """Appian's design guidance levels, plus the syntax error.

    Appian has exactly two guidance levels, Warning and Recommendation, and
    reserves red for a syntax error, which suppresses guidance until it is
    fixed. Anything semantic, such as an unknown function or an unresolved
    reference, is a warning rather than an error: the expression still
    parses, so reporting it as a syntax error both misstates the problem and
    hides every other finding on the object.
    """

    ERROR = "error"
    WARNING = "warning"
    RECOMMENDATION = "recommendation"


@dataclass(frozen=True)
class SailDiagnostic:
    """A coded SAIL finding with an exact half-open source range."""

    code: str
    message: str
    severity: DiagnosticSeverity
    range: SourceRange

    @property
    def line(self) -> int:
        return self.range.start.line

    @property
    def column(self) -> int:
        return self.range.start.column

    @property
    def end_line(self) -> int:
        return self.range.end.line

    @property
    def end_column(self) -> int:
        return self.range.end.column


@dataclass
class SailAnalysis:
    """AST plus all diagnostics from one analysis pass."""

    ast: Node
    diagnostics: list[SailDiagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[SailDiagnostic]:
        return [
            item
            for item in self.diagnostics
            if item.severity == DiagnosticSeverity.ERROR
        ]

    @property
    def warnings(self) -> list[SailDiagnostic]:
        return [
            item
            for item in self.diagnostics
            if item.severity == DiagnosticSeverity.WARNING
        ]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _position(source: str, offset: int) -> SourcePosition:
    line = source.count("\n", 0, offset) + 1
    previous_newline = source.rfind("\n", 0, offset)
    return SourcePosition(line, offset - previous_newline, offset)


def _range(source: str, start: int, end: int) -> SourceRange:
    if not source:
        return SourceRange(
            SourcePosition(1, 1, 0),
            SourcePosition(1, 2, 1),
        )
    bounded_start = min(max(start, 0), len(source) - 1)
    bounded_end = min(max(end, bounded_start + 1), len(source))
    return SourceRange(
        _position(source, bounded_start),
        _position(source, bounded_end),
    )


def _node_range(source: str, node: Node) -> SourceRange:
    start = node.pos.offset if node.pos is not None else 0
    end = node.end.offset if node.end is not None else start + 1
    return _range(source, start, end)


def _masked_source(source: str) -> str:
    """Mask strings and comments while preserving all offsets."""
    tokenizer = SailTokenizer(source)
    tokens = tokenizer.tokenize()
    chars = list(source)
    for token in tokens:
        if (
            token.type.value
            not in {"STRING", "COMMENT", "QUOTED_REFERENCE"}
            or token.end is None
        ):
            continue
        for index in range(token.pos.offset, token.end.offset):
            chars[index] = " "
    return "".join(chars)


class _FindingVisitor(NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[tuple[str, Node]] = []
        self.component_calls: list[ComponentCall] = []
        self.uuids: list[UuidCall] = []
        self.rule_inputs: list[DomainVar] = []

    def visit_FunctionCall(self, node: FunctionCall) -> None:  # noqa: N802
        self.calls.append((node.name, node))
        self.generic_visit(node)

    def visit_ComponentCall(self, node: ComponentCall) -> None:  # noqa: N802
        self.calls.append((f"a!{node.name}", node))
        self.component_calls.append(node)
        self.generic_visit(node)

    def visit_UuidCall(self, node: UuidCall) -> None:  # noqa: N802
        self.uuids.append(node)
        self.generic_visit(node)

    def visit_DomainVar(self, node: DomainVar) -> None:  # noqa: N802
        if node.domain.casefold() == "ri":
            self.rule_inputs.append(node)


_FORBIDDEN = (
    (re.compile(r"=="), "SAIL010", "Forbidden operator '==': use '='"),
    (re.compile(r"!="), "SAIL011", "Forbidden operator '!=': use '<>'"),
    (re.compile(r"&&"), "SAIL012", "Forbidden operator '&&': use and()"),
    (re.compile(r"\|\|"), "SAIL013", "Forbidden operator '||': use or()"),
    (re.compile(r";"), "SAIL014", "Forbidden operator ';': remove it"),
    (re.compile(r"//[^\n]*"), "SAIL015", "Use block comments, not '//'"),
)

_APPIAN_URN_RE = re.compile(
    r"^urn:appian:[a-z0-9-]+:v\d+:([^/]+)(?:/.*)?$",
    re.IGNORECASE,
)
_STANDARD_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


_ICON_NEAR_MISS_CUTOFF = 0.8
_UNVERIFIABLE_ICON = (
    "is not in the bundled Appian 26.5 reference, which is truncated and "
    "covers only part of the icon set; verify in the Expression Editor"
)


def _literal_icon_argument(node: ComponentCall) -> StringLiteral | None:
    named = next(
        (
            arg.value
            for arg in node.args
            if arg.name is not None and arg.name.casefold() == "icon"
        ),
        None,
    )
    if isinstance(named, StringLiteral):
        return named
    positional = next((arg.value for arg in node.args if arg.name is None), None)
    return positional if isinstance(positional, StringLiteral) else None


def appian_reference_owner_uuid(reference: str) -> str | None:
    """Return the owning object UUID for a direct reference or Appian URN.

    Appian function URNs have no owning design-object UUID and return ``None``.
    """
    if not reference.casefold().startswith("urn:appian:"):
        return reference
    match = _APPIAN_URN_RE.fullmatch(reference)
    if match is None:
        return reference
    owner = match.group(1)
    return owner if _STANDARD_UUID_RE.fullmatch(owner) else None


def analyze_sail(
    source: str,
    *,
    target_version: str | None = None,
    known_uuids: set[str] | None = None,
    declared_inputs: list[str] | None = None,
    catalog: SailCallableCatalog = DEFAULT_SAIL_CATALOG,
) -> SailAnalysis:
    """Parse and analyze SAIL source through one diagnostic pipeline."""
    ast, parse_errors, _ = parse_sail_with_context(source)
    diagnostics: list[SailDiagnostic] = []
    masked = _masked_source(source)
    forbidden_ranges: list[tuple[int, int]] = []

    for pattern, code, message in _FORBIDDEN:
        for match in pattern.finditer(masked):
            forbidden_ranges.append(match.span())
            diagnostics.append(SailDiagnostic(
                code,
                message,
                DiagnosticSeverity.ERROR,
                _range(source, *match.span()),
            ))

    for error in parse_errors:
        start = error.pos.offset if error.pos is not None else 0
        if any(
            left <= start <= right
            or (start > right and source[right:start].isspace())
            for left, right in forbidden_ranges
        ):
            continue
        end = error.end_pos.offset if error.end_pos is not None else start + 1
        diagnostics.append(SailDiagnostic(
            error.code,
            error.message,
            DiagnosticSeverity(error.severity),
            _range(source, start, end),
        ))

    visitor = _FindingVisitor()
    visitor.visit(ast)
    for name, node in visitor.calls:
        if name.casefold().startswith(
            ("rule!", "recordtype!", "'type!", "'recordtype!"),
        ):
            continue
        decision = catalog.classify(name, target_version)
        if decision.status == "valid":
            continue
        diagnostics.append(SailDiagnostic(
            "SAIL020" if decision.status == "invalid" else "SAIL021",
            decision.reason,
            DiagnosticSeverity.WARNING,
            _node_range(source, node),
        ))

    icon_catalog = load_icon_catalog()
    rich_icons = icon_catalog.rich_text_aliases
    system_icons = icon_catalog.system_icon_keys
    for node in visitor.component_calls:
        literal = _literal_icon_argument(node)
        if literal is None:
            continue
        name = node.name.casefold()
        if name == "richtexticon" and rich_icons and literal.value not in rich_icons:
            matches = get_close_matches(
                literal.value,
                rich_icons,
                n=1,
                cutoff=_ICON_NEAR_MISS_CUTOFF,
            )
            if matches:
                diagnostics.append(SailDiagnostic(
                    "SAIL041",
                    (
                        f"Unknown rich-text icon alias '{literal.value}'; "
                        f"did you mean '{matches[0]}'?"
                    ),
                    DiagnosticSeverity.ERROR,
                    _node_range(source, literal),
                ))
            else:
                diagnostics.append(SailDiagnostic(
                    "SAIL041",
                    f"icon '{literal.value}' {_UNVERIFIABLE_ICON}",
                    DiagnosticSeverity.WARNING,
                    _node_range(source, literal),
                ))
        elif (
            name in {"iconindicator", "iconnewsevent"}
            and system_icons
            and literal.value not in system_icons
        ):
            matches = get_close_matches(
                literal.value,
                system_icons,
                n=1,
                cutoff=_ICON_NEAR_MISS_CUTOFF,
            )
            if matches:
                diagnostics.append(SailDiagnostic(
                    "SAIL042",
                    (
                        f"Unknown system icon key '{literal.value}'; "
                        f"did you mean '{matches[0]}'?"
                    ),
                    DiagnosticSeverity.ERROR,
                    _node_range(source, literal),
                ))
            else:
                diagnostics.append(SailDiagnostic(
                    "SAIL042",
                    f"icon '{literal.value}' {_UNVERIFIABLE_ICON}",
                    DiagnosticSeverity.WARNING,
                    _node_range(source, literal),
                ))

    if known_uuids is not None:
        normalized_uuids = frozenset(uuid.casefold() for uuid in known_uuids)
        for node in visitor.uuids:
            owner_uuid = appian_reference_owner_uuid(node.uuid)
            if (
                owner_uuid is not None
                and owner_uuid.casefold() not in normalized_uuids
            ):
                diagnostics.append(SailDiagnostic(
                    "SAIL030",
                    (
                        f'Unresolved UUID reference: #"{node.uuid}" '
                        f"(owning object: {owner_uuid})"
                    ),
                    DiagnosticSeverity.WARNING,
                    _node_range(source, node),
                ))

    if declared_inputs is not None:
        declared = frozenset(declared_inputs)
        used = {node.name for node in visitor.rule_inputs}
        for node in visitor.rule_inputs:
            if node.name not in declared:
                diagnostics.append(SailDiagnostic(
                    "SAIL031",
                    f"Rule input 'ri!{node.name}' is not declared",
                    DiagnosticSeverity.WARNING,
                    _node_range(source, node),
                ))
        for name in sorted(declared - used):
            diagnostics.append(SailDiagnostic(
                "SAIL032",
                f"Declared input '{name}' is never used",
                DiagnosticSeverity.RECOMMENDATION,
                _range(source, 0, len(source)),
            ))

    for match in re.finditer(r"\bwith\s*\(", masked, re.IGNORECASE):
        diagnostics.append(SailDiagnostic(
            "SAIL040",
            "Legacy with() detected; use a!localVariables()",
            DiagnosticSeverity.WARNING,
            _range(source, *match.span()),
        ))

    diagnostics.sort(
        key=lambda item: (
            item.range.start.offset,
            item.range.end.offset,
            item.code,
        ),
    )
    return SailAnalysis(ast=ast, diagnostics=diagnostics)
