"""
SAIL AST Parser for Appian SAIL Expression Language.

This module provides a complete parser for the SAIL (Self-Assembling Interface Layer)
expression language used in Appian applications. It includes:

- A tokenizer/lexer that converts SAIL source code into a stream of tokens
- A recursive descent parser that builds an Abstract Syntax Tree (AST)
- AST node types representing all SAIL language constructs
- A visitor pattern for traversing the AST
- Utility functions for common operations (parsing, extraction, validation, formatting)

The parser is fault-tolerant: it collects errors but continues parsing when possible,
producing a best-effort AST even for syntactically invalid input.

Usage::

    from appian_sentinel.parser.sail_ast import parse_sail, pretty_print, extract_uuid_refs

    source = 'if(ri!isEnabled, "yes", "no")'
    ast = parse_sail(source)
    print(pretty_print(ast))
    refs = extract_uuid_refs(ast)

SAIL Syntax Overview:
    - Function calls: ``functionName(arg1, arg2, namedArg: value)``
    - Component calls: ``a!componentName(param: val)``
    - UUID references: ``#"_a-0000xxxx-..."(args)``
    - System rules: ``#"SYSTEM_SYSRULES_functionName"(args)``
    - Variable domains: ``ri!x``, ``local!y``, ``fv!item``, ``pv!z``, ``dp!w``
    - Operators: ``=``, ``<>``, ``<``, ``>``, ``<=``, ``>=``, ``+``, ``-``, ``*``, ``/``, ``&``
    - Lists: ``{1, 2, 3}``
    - Strings: ``"text"`` (doubled quotes ``""`` for escaping)
    - Comments: ``/* comment */``
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Optional, Union

# ============================================================================
# Source Position Tracking
# ============================================================================

@dataclass(frozen=True)
class SourcePosition:
    """Tracks a position in source code for error reporting.

    Attributes:
        line: 1-based line number.
        column: 1-based column number within the line.
        offset: 0-based character offset from the start of the source.
    """

    line: int
    column: int
    offset: int

    def __str__(self) -> str:
        return f"line {self.line}, col {self.column}"


@dataclass(frozen=True)
class SourceRange:
    """A non-empty half-open source range."""

    start: SourcePosition
    end: SourcePosition

    def __post_init__(self) -> None:
        if self.end.offset <= self.start.offset:
            raise ValueError("SourceRange must be non-empty")


# ============================================================================
# Token Types
# ============================================================================

class TokenType(enum.Enum):
    """All token types recognised by the SAIL tokenizer."""

    # Literals
    STRING = "STRING"
    QUOTED_REFERENCE = "QUOTED_REFERENCE"
    NUMBER = "NUMBER"
    NULL = "NULL"
    TRUE = "TRUE"
    FALSE = "FALSE"

    # Identifiers
    IDENTIFIER = "IDENTIFIER"
    PREFIXED_IDENTIFIER = "PREFIXED_IDENTIFIER"  # ri!x, local!y, a!comp, etc.

    # Hash-quoted references: #"_a-uuid-..." or #"SYSTEM_SYSRULES_..."
    HASH_REF = "HASH_REF"

    # Arithmetic operators
    PLUS = "PLUS"            # +
    MINUS = "MINUS"          # -
    STAR = "STAR"            # *
    SLASH = "SLASH"          # /
    AMPERSAND = "AMPERSAND"  # &  (string concatenation)

    # Comparison operators
    EQUAL = "EQUAL"                  # =
    NOT_EQUAL = "NOT_EQUAL"          # <>
    LESS = "LESS"                    # <
    GREATER = "GREATER"              # >
    LESS_EQUAL = "LESS_EQUAL"        # <=
    GREATER_EQUAL = "GREATER_EQUAL"  # >=

    # Delimiters
    LPAREN = "LPAREN"      # (
    RPAREN = "RPAREN"      # )
    LBRACE = "LBRACE"      # {
    RBRACE = "RBRACE"      # }
    LBRACKET = "LBRACKET"  # [
    RBRACKET = "RBRACKET"  # ]
    COMMA = "COMMA"        # ,
    COLON = "COLON"        # :
    DOT = "DOT"            # .

    # Special
    COMMENT = "COMMENT"  # /* ... */
    EOF = "EOF"
    ERROR = "ERROR"


# ============================================================================
# Token
# ============================================================================

@dataclass
class Token:
    """A single token produced by the SAIL tokenizer.

    Attributes:
        type: The kind of token.
        value: The raw text of the token (string content for STRING, the
            reference body for HASH_REF, etc.).
        pos: Where the token starts in source.
        prefix: For PREFIXED_IDENTIFIER only -- the part before ``!``.
        name: For PREFIXED_IDENTIFIER only -- the part after ``!``.
    """

    type: TokenType
    value: str
    pos: SourcePosition
    end: Optional[SourcePosition] = None
    prefix: str = ""
    name: str = ""

    def __repr__(self) -> str:
        if self.type == TokenType.PREFIXED_IDENTIFIER:
            return f"Token({self.type.value}, {self.prefix}!{self.name})"
        return f"Token({self.type.value}, {self.value!r})"


# ============================================================================
# Parse Errors
# ============================================================================

@dataclass
class SailParseError:
    """A parse error or warning collected during tokenization or parsing.

    Attributes:
        message: Human-readable description of the problem.
        pos: Source location of the error (may be ``None``).
        severity: ``"error"`` or ``"warning"``.
    """

    message: str
    pos: Optional[SourcePosition]
    severity: str = "error"
    code: str = "SAIL001"
    end_pos: Optional[SourcePosition] = None

    def __str__(self) -> str:
        loc = f" at {self.pos}" if self.pos else ""
        return f"[{self.severity}]{loc}: {self.message}"


# ============================================================================
# AST Node Types
# ============================================================================

@dataclass
class Node:
    """Base class for all AST nodes.

    Every node carries an optional ``pos`` recording where it appeared
    in source.  ``pos`` is excluded from ``repr`` and ``__eq__`` so
    that structural equality tests remain clean.
    """

    pos: Optional[SourcePosition] = dc_field(
        default=None, repr=False, compare=False,
    )
    end: Optional[SourcePosition] = dc_field(
        default=None, repr=False, compare=False,
    )


@dataclass
class FunctionCall(Node):
    """A plain function call: ``if(...)``, ``index(...)``, ``reject(...)``.

    Attributes:
        name: The function name.
        args: Ordered list of arguments (named and positional).
    """

    name: str = ""
    args: list["Arg"] = dc_field(default_factory=list)


@dataclass
class ComponentCall(Node):
    """An Appian component / utility call with the ``a!`` prefix.

    Examples: ``a!textField(...)``, ``a!localVariables(...)``.

    Attributes:
        name: Component name *without* the ``a!`` prefix.
        args: Ordered list of arguments.
    """

    name: str = ""
    args: list["Arg"] = dc_field(default_factory=list)


@dataclass
class UuidCall(Node):
    """A call via a UUID reference: ``#"_a-0000d62a-..."(args)``.

    Attributes:
        uuid: The UUID string (content between the quotes).
        args: Ordered list of arguments.
    """

    uuid: str = ""
    args: list["Arg"] = dc_field(default_factory=list)


@dataclass
class SystemCall(Node):
    """A system rule call: ``#"SYSTEM_SYSRULES_forEach"(args)``.

    Attributes:
        name: The full system-rule identifier (e.g.
            ``SYSTEM_SYSRULES_forEach``).
        args: Ordered list of arguments.
    """

    name: str = ""
    args: list["Arg"] = dc_field(default_factory=list)


@dataclass
class Arg(Node):
    """A single function argument -- named or positional.

    Attributes:
        name: The parameter name if this is a named argument
            (e.g. ``label`` in ``label: "hi"``), otherwise ``None``.
        value: The argument's value expression.
    """

    name: Optional[str] = None
    value: Optional[Node] = None
    quoted_name: bool = False
    key: Optional[Node] = None


@dataclass
class DomainVar(Node):
    """A domain-qualified variable reference.

    Examples: ``ri!documents``, ``local!x``, ``fv!item``, ``fn!isnull``.

    Attributes:
        domain: The domain prefix (``ri``, ``local``, ``fv``, etc.).
        name: The variable name after ``!``.
    """

    domain: str = ""
    name: str = ""

    @property
    def full_name(self) -> str:
        """Return the fully-qualified name, e.g. ``ri!documents``."""
        return f"{self.domain}!{self.name}"


@dataclass
class DotAccess(Node):
    """Property access via dot notation: ``local!var.field``.

    Chained access like ``x.a.b`` is represented as nested DotAccess
    nodes: ``DotAccess(DotAccess(x, 'a'), 'b')``.

    Attributes:
        target: The expression being accessed.
        field: The field / property name.
    """

    target: Optional[Node] = None
    field: str = ""


@dataclass
class BracketAccess(Node):
    """Bracket-based indexing: ``rv!record[recordType!Field.fields.name]``.

    Attributes:
        target: The expression being indexed.
        index: The index expression inside the brackets.
    """

    target: Optional[Node] = None
    index: Optional[Node] = None


@dataclass
class BinaryOp(Node):
    """A binary operation: ``a + b``, ``x = y``, ``count <> 0``.

    Attributes:
        op: The operator string (``+``, ``-``, ``*``, ``/``, ``&``,
            ``=``, ``<>``, ``<``, ``>``, ``<=``, ``>=``).
        left: Left operand.
        right: Right operand.
    """

    op: str = ""
    left: Optional[Node] = None
    right: Optional[Node] = None


@dataclass
class UnaryOp(Node):
    """A unary operation, currently only negation: ``-x``.

    Attributes:
        op: The operator string (``-``).
        operand: The operand expression.
    """

    op: str = ""
    operand: Optional[Node] = None


@dataclass
class ListLiteral(Node):
    """A list literal: ``{1, 2, 3}``.

    Attributes:
        items: The list elements in order.
    """

    items: list[Node] = dc_field(default_factory=list)


@dataclass
class DictionaryEntry(Node):
    """A key-value entry in a dictionary literal."""

    key: Optional[Node] = None
    value: Optional[Node] = None


@dataclass
class DictionaryLiteral(Node):
    """A dictionary literal such as ``{name: "Ada"}``."""

    entries: list[DictionaryEntry] = dc_field(default_factory=list)


@dataclass
class StringLiteral(Node):
    """A string literal: ``"hello"``.

    The stored value has escape sequences resolved (doubled quotes
    ``""`` become a single ``"``).

    Attributes:
        value: The string content.
    """

    value: str = ""


@dataclass
class NumberLiteral(Node):
    """A numeric literal (integer or decimal).

    Attributes:
        value: The numeric value as ``int`` or ``float``.
    """

    value: Union[int, float] = 0


@dataclass
class BoolLiteral(Node):
    """A boolean literal: ``true`` or ``false``.

    Attributes:
        value: The boolean value.
    """

    value: bool = False


@dataclass
class NullLiteral(Node):
    """The ``null`` literal."""


@dataclass
class Comment(Node):
    """A SAIL block comment ``/* ... */``.

    Attributes:
        text: The comment body (without the delimiters).
    """

    text: str = ""


@dataclass
class VariableBinding(Node):
    """A variable binding inside ``a!localVariables``.

    Example: ``local!x: someExpression``.

    Attributes:
        name: The fully-qualified variable name (e.g. ``local!x``).
        expression: The value expression bound to the variable.
    """

    name: str = ""
    expression: Optional[Node] = None

    @property
    def domain(self) -> str:
        """The domain part of the binding name (e.g. ``local``)."""
        parts = self.name.split("!", 1)
        return parts[0] if len(parts) > 1 else ""

    @property
    def var_name(self) -> str:
        """The variable part of the binding name (e.g. ``x``)."""
        parts = self.name.split("!", 1)
        return parts[1] if len(parts) > 1 else self.name


@dataclass
class TypeCast(Node):
    """A type-cast function call: ``todocument(x)``, ``tointeger(y)``.

    Only recognised for well-known cast function names; other ``to*``
    functions are kept as :class:`FunctionCall`.

    Attributes:
        type_name: The cast function name (e.g. ``todocument``).
        expression: The expression being cast.
    """

    type_name: str = ""
    expression: Optional[Node] = None


@dataclass
class RecordFieldRef(Node):
    """A record field reference: ``recordType!Case.fields.status``.

    This node is available for downstream consumers that wish to
    construct it explicitly.  The parser produces this pattern as
    a chain of :class:`DotAccess` nodes rooted in a
    :class:`DomainVar` with ``domain='recordType'``.

    Attributes:
        record_type: The record type name (e.g. ``Case``).
        field_path: The field path segments (e.g. ``['fields', 'status']``).
    """

    record_type: str = ""
    field_path: list[str] = dc_field(default_factory=list)


@dataclass
class Identifier(Node):
    """A plain identifier that is not a function call or domain variable.

    Rarely produced by the parser -- most identifiers in SAIL are
    function names (followed by ``(``) or domain-qualified names.
    This node covers edge cases and provides fault tolerance.

    Attributes:
        name: The identifier text.
    """

    name: str = ""


@dataclass
class ErrorNode(Node):
    """Placeholder for an unparseable section of source.

    Created during fault-tolerant error recovery so that the AST
    still covers the full input.

    Attributes:
        message: Description of the parsing failure.
        tokens: The raw tokens that could not be parsed.
    """

    message: str = ""
    tokens: list[Token] = dc_field(default_factory=list)


# ============================================================================
# Constants
# ============================================================================

#: Well-known Appian type-cast function names.  When the parser
#: encounters one of these as a single-argument function call it
#: produces a :class:`TypeCast` node instead of a :class:`FunctionCall`.
TYPE_CAST_FUNCTIONS: frozenset[str] = frozenset({
    "todocument",
    "tointeger",
    "tostring",
    "toboolean",
    "tonumber",
    "todatetime",
    "todate",
    "totime",
    "todecimal",
    "touniformstring",
    "torecord",
    "topeople",
    "touser",
    "togroup",
    "tointervalds",
    "toemailaddress",
    "toemailrecipient",
    "toknowledgecenter",
    "tocommunity",
})

#: Domain prefixes that introduce variable references.
VARIABLE_DOMAINS: frozenset[str] = frozenset({
    "ri",          # rule input
    "local",       # local variable
    "fv",          # forEach variable
    "pv",          # process variable
    "dp",          # data parameter
    "fn",          # function reference
    "rv",          # record variable
    "recordType",  # record type reference
    "rule",        # rule reference
    "cons",        # constant reference
    "load",        # load variable
    "save",        # save variable
})

#: Prefixes that denote component / utility function calls.
COMPONENT_PREFIXES: frozenset[str] = frozenset({"a"})

#: SAIL keyword tokens.
KEYWORDS: dict[str, TokenType] = {
    "null": TokenType.NULL,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
}


# ============================================================================
# Tokenizer
# ============================================================================

class SailTokenizer:
    """Tokenizes SAIL source code into a stream of :class:`Token` objects.

    The tokenizer handles all SAIL lexical constructs:

    * Strings (``"..."`` with ``""`` escape for embedded quotes)
    * Numbers (integers and decimals)
    * Identifiers and keywords (``null``, ``true``, ``false``)
    * Domain-qualified names (``ri!x``, ``a!textField``)
    * Hash-quoted references (``#"_a-uuid..."`` and ``#"SYSTEM_..."`` )
    * Operators, delimiters, and block comments

    The tokenizer is **fault-tolerant**: invalid characters are
    recorded as errors and emitted as :attr:`TokenType.ERROR` tokens
    so that subsequent tokens can still be produced.

    Usage::

        tz = SailTokenizer('if(ri!x, 1, 2)')
        tokens = tz.tokenize()
        errors = tz.errors          # any problems found
        comments = tz.comments      # extracted Comment nodes
    """

    def __init__(self, source: str) -> None:
        self.source: str = source
        self.pos: int = 0
        self.line: int = 1
        self.column: int = 1
        self.tokens: list[Token] = []
        self.errors: list[SailParseError] = []
        self.comments: list[Comment] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tokenize(self) -> list[Token]:
        """Run the tokenizer over the full source.

        Returns:
            The token list, always ending with an ``EOF`` token.
        """
        while self.pos < len(self.source):
            self._skip_whitespace()
            if self.pos >= len(self.source):
                break

            start = self._current_pos()
            c = self._peek()

            # Block comment  /* ... */
            if c == "/" and self._peek(1) == "*":
                self._read_comment(start)

            # String literal
            elif c == '"':
                self._read_string(start)

            # Appian design/type reference
            elif c == "'":
                self._read_quoted_reference(start)

            # Hash reference  #"..."
            elif c == "#" and self._peek(1) == '"':
                self._read_hash_ref(start)

            # Number literal
            elif c.isdigit():
                self._read_number(start)

            # Identifier, keyword, or prefixed identifier
            elif c.isalpha() or c == "_":
                self._read_identifier_or_keyword(start)

            # Two-character operators first to avoid consuming only the
            # first character.
            elif c == "<":
                if self._peek(1) == ">":
                    self._advance()
                    self._advance()
                    self.tokens.append(Token(TokenType.NOT_EQUAL, "<>", start))
                elif self._peek(1) == "=":
                    self._advance()
                    self._advance()
                    self.tokens.append(Token(TokenType.LESS_EQUAL, "<=", start))
                else:
                    self._advance()
                    self.tokens.append(Token(TokenType.LESS, "<", start))

            elif c == ">":
                if self._peek(1) == "=":
                    self._advance()
                    self._advance()
                    self.tokens.append(
                        Token(TokenType.GREATER_EQUAL, ">=", start),
                    )
                else:
                    self._advance()
                    self.tokens.append(Token(TokenType.GREATER, ">", start))

            # Single-character tokens
            elif c == "=":
                self._advance()
                self.tokens.append(Token(TokenType.EQUAL, "=", start))
            elif c == "+":
                self._advance()
                self.tokens.append(Token(TokenType.PLUS, "+", start))
            elif c == "-":
                self._advance()
                self.tokens.append(Token(TokenType.MINUS, "-", start))
            elif c == "*":
                self._advance()
                self.tokens.append(Token(TokenType.STAR, "*", start))
            elif c == "/":
                self._advance()
                self.tokens.append(Token(TokenType.SLASH, "/", start))
            elif c == "&":
                self._advance()
                self.tokens.append(Token(TokenType.AMPERSAND, "&", start))
            elif c == "(":
                self._advance()
                self.tokens.append(Token(TokenType.LPAREN, "(", start))
            elif c == ")":
                self._advance()
                self.tokens.append(Token(TokenType.RPAREN, ")", start))
            elif c == "{":
                self._advance()
                self.tokens.append(Token(TokenType.LBRACE, "{", start))
            elif c == "}":
                self._advance()
                self.tokens.append(Token(TokenType.RBRACE, "}", start))
            elif c == "[":
                self._advance()
                self.tokens.append(Token(TokenType.LBRACKET, "[", start))
            elif c == "]":
                self._advance()
                self.tokens.append(Token(TokenType.RBRACKET, "]", start))
            elif c == ",":
                self._advance()
                self.tokens.append(Token(TokenType.COMMA, ",", start))
            elif c == ":":
                self._advance()
                self.tokens.append(Token(TokenType.COLON, ":", start))
            elif c == ".":
                self._advance()
                self.tokens.append(Token(TokenType.DOT, ".", start))

            else:
                # Unrecognised character -- skip and record error
                self.errors.append(
                    SailParseError(
                        message=f"Unexpected character: {c!r}",
                        pos=start,
                    ),
                )
                self._advance()
                self.tokens.append(Token(TokenType.ERROR, c, start))

        self.tokens.append(Token(TokenType.EOF, "", self._current_pos()))
        self._set_token_ends()
        return self.tokens

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_pos(self) -> SourcePosition:
        return SourcePosition(self.line, self.column, self.pos)

    def _position_at(self, offset: int) -> SourcePosition:
        line = self.source.count("\n", 0, offset) + 1
        previous_newline = self.source.rfind("\n", 0, offset)
        return SourcePosition(line, offset - previous_newline, offset)

    def _set_token_ends(self) -> None:
        """Set exact token ends after tokenization."""
        for index, token in enumerate(self.tokens):
            if token.type == TokenType.EOF:
                token.end = token.pos
                continue
            next_offset = self.tokens[index + 1].pos.offset
            end_offset = next_offset
            while (
                end_offset > token.pos.offset
                and self.source[end_offset - 1] in " \t\r\n\ufeff"
            ):
                end_offset -= 1
            token.end = self._position_at(end_offset)

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        return self.source[idx] if idx < len(self.source) else "\0"

    def _advance(self) -> str:
        if self.pos >= len(self.source):
            return "\0"
        c = self.source[self.pos]
        self.pos += 1
        if c == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return c

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters including BOM."""
        while self.pos < len(self.source) and self.source[self.pos] in " \t\r\n﻿":
            self._advance()

    # -- Compound token readers ----------------------------------------

    def _read_comment(self, start: SourcePosition) -> None:
        """Read a ``/* ... */`` block comment."""
        self._advance()  # /
        self._advance()  # *
        text_start = self.pos
        while self.pos < len(self.source):
            if self._peek() == "*" and self._peek(1) == "/":
                text = self.source[text_start : self.pos]
                self._advance()  # *
                self._advance()  # /
                tok = Token(TokenType.COMMENT, text.strip(), start)
                self.tokens.append(tok)
                self.comments.append(Comment(text=text.strip(), pos=start))
                return
            self._advance()
        # Unterminated
        text = self.source[text_start : self.pos]
        self.errors.append(
            SailParseError(message="Unterminated block comment", pos=start),
        )
        self.tokens.append(Token(TokenType.COMMENT, text.strip(), start))
        self.comments.append(Comment(text=text.strip(), pos=start))

    def _read_string(self, start: SourcePosition) -> None:
        """Read a double-quoted string.

        Doubled quotes ``""`` inside the string are treated as an
        escaped literal quote character.
        """
        self._advance()  # opening "
        chars: list[str] = []
        while self.pos < len(self.source):
            c = self._peek()
            if c == '"':
                self._advance()
                if self._peek() == '"':
                    # Escaped quote
                    chars.append('"')
                    self._advance()
                else:
                    # End of string
                    self.tokens.append(
                        Token(TokenType.STRING, "".join(chars), start),
                    )
                    return
            else:
                chars.append(c)
                self._advance()
        # Unterminated
        self.errors.append(
            SailParseError(message="Unterminated string literal", pos=start),
        )
        self.tokens.append(Token(TokenType.STRING, "".join(chars), start))

    def _read_hash_ref(self, start: SourcePosition) -> None:
        """Read a hash-quoted reference ``#"content"``."""
        self._advance()  # #
        self._advance()  # opening "
        chars: list[str] = []
        while self.pos < len(self.source):
            c = self._peek()
            if c == '"':
                self._advance()
                content = "".join(chars)
                self.tokens.append(Token(TokenType.HASH_REF, content, start))
                return
            chars.append(c)
            self._advance()
        # Unterminated
        content = "".join(chars)
        self.errors.append(
            SailParseError(message="Unterminated hash reference", pos=start),
        )
        self.tokens.append(Token(TokenType.HASH_REF, content, start))

    def _read_quoted_reference(self, start: SourcePosition) -> None:
        """Read an Appian reference such as ``'type!{urn}Name'``."""
        self._advance()
        content_start = self.pos
        while self.pos < len(self.source) and self._peek() != "'":
            self._advance()
        content = self.source[content_start : self.pos]
        if self._peek() == "'":
            self._advance()
        else:
            self.errors.append(SailParseError(
                message="Unterminated quoted reference",
                pos=start,
                end_pos=self._current_pos(),
            ))
        self.tokens.append(Token(TokenType.QUOTED_REFERENCE, content, start))

    def _read_number(self, start: SourcePosition) -> None:
        """Read an integer or decimal number literal."""
        num_start = self.pos
        while self.pos < len(self.source) and self.source[self.pos].isdigit():
            self._advance()
        # Decimal part -- only if the dot is followed by more digits
        # (otherwise the dot is a property access).
        if (
            self.pos < len(self.source)
            and self.source[self.pos] == "."
            and self.pos + 1 < len(self.source)
            and self.source[self.pos + 1].isdigit()
        ):
            self._advance()  # .
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                self._advance()
        value = self.source[num_start : self.pos]
        self.tokens.append(Token(TokenType.NUMBER, value, start))

    def _read_identifier_or_keyword(self, start: SourcePosition) -> None:
        """Read an identifier, keyword, or prefixed identifier.

        If the identifier is immediately followed by ``!`` and then
        another identifier, the entire ``prefix!name`` sequence is
        emitted as a single :attr:`TokenType.PREFIXED_IDENTIFIER` token.
        """
        id_start = self.pos
        while self.pos < len(self.source) and (
            self.source[self.pos].isalnum() or self.source[self.pos] == "_"
        ):
            self._advance()
        word = self.source[id_start : self.pos]

        # Check for  prefix!name
        if self.pos < len(self.source) and self.source[self.pos] == "!":
            next_idx = self.pos + 1
            if next_idx < len(self.source) and (
                self.source[next_idx].isalnum() or self.source[next_idx] == "_"
            ):
                self._advance()  # consume !
                name_start = self.pos
                if word.casefold() == "recordtype":
                    while (
                        self.pos < len(self.source)
                        and self.source[self.pos] not in ".,()[]{}:+-*/&=<>\r\n"
                    ):
                        self._advance()
                    name = self.source[name_start : self.pos].rstrip()
                    trailing = self.pos - name_start - len(name)
                    if trailing:
                        self.pos -= trailing
                        self.column -= trailing
                else:
                    while self.pos < len(self.source) and (
                        self.source[self.pos].isalnum()
                        or self.source[self.pos] == "_"
                    ):
                        self._advance()
                    name = self.source[name_start : self.pos]
                self.tokens.append(
                    Token(
                        TokenType.PREFIXED_IDENTIFIER,
                        f"{word}!{name}",
                        start,
                        prefix=word,
                        name=name,
                    ),
                )
                return

        # Keyword check (case-insensitive for null, true, false)
        lower = word.lower()
        if lower in KEYWORDS:
            self.tokens.append(Token(KEYWORDS[lower], word, start))
        else:
            self.tokens.append(Token(TokenType.IDENTIFIER, word, start))


# ============================================================================
# Parser
# ============================================================================

class SailParser:
    """Recursive-descent parser for SAIL expressions.

    Builds an AST from a token stream produced by :class:`SailTokenizer`.
    The parser is **fault-tolerant**: it records errors in
    :attr:`errors` and continues, producing a best-effort AST.

    Operator precedence (lowest to highest)::

        1. Equality      =  <>
        2. Comparison     <  >  <=  >=
        3. Additive       +  -  &
        4. Multiplicative *  /
        5. Unary          -
        6. Postfix        .field  [index]
        7. Primary        literals, calls, identifiers, lists, (expr)

    Usage::

        tz = SailTokenizer(source)
        tokens = tz.tokenize()
        parser = SailParser(tokens, errors=tz.errors)
        ast = parser.parse()
    """

    def __init__(
        self,
        tokens: list[Token],
        errors: Optional[list[SailParseError]] = None,
    ) -> None:
        self.all_tokens: list[Token] = tokens
        # Filter out comments and error tokens for the parser --
        # they are preserved separately.
        self.tokens: list[Token] = [
            t
            for t in tokens
            if t.type not in (TokenType.COMMENT, TokenType.ERROR)
        ]
        self.pos: int = 0
        self.errors: list[SailParseError] = errors if errors is not None else []
        self.comments: list[Comment] = [
            Comment(text=t.value, pos=t.pos)
            for t in tokens
            if t.type == TokenType.COMMENT
        ]

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def parse(self) -> Node:
        """Parse the token stream into a single AST node.

        Returns:
            The root :class:`Node` of the AST.  For empty input a
            :class:`NullLiteral` is returned.
        """
        if not self.tokens or self._current().type == TokenType.EOF:
            return NullLiteral(pos=SourcePosition(1, 1, 0))

        node = self._parse_expression()

        if self._match(TokenType.COMMA) and self._peek().type == TokenType.EOF:
            self._advance()

        if self._current().type != TokenType.EOF:
            self._add_error(
                f"Unexpected token after expression: "
                f"'{self._current().value}'",
            )

        return node

    # ------------------------------------------------------------------
    # Token access helpers
    # ------------------------------------------------------------------

    def _current(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, "", SourcePosition(0, 0, 0))

    def _peek(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.EOF, "", SourcePosition(0, 0, 0))

    def _advance(self) -> Token:
        tok = self._current()
        if self.pos < len(self.tokens):
            self.pos += 1
        return tok

    def _expect(self, token_type: TokenType, context: str = "") -> Token:
        """Consume and return the current token if it matches *token_type*.

        On mismatch an error is recorded but the token is **not**
        consumed, allowing the caller to attempt recovery.
        """
        tok = self._current()
        if tok.type != token_type:
            ctx = f" in {context}" if context else ""
            self._add_error(
                f"Expected {token_type.value}{ctx}, "
                f"got {tok.type.value} ('{tok.value}')",
            )
            return tok
        return self._advance()

    def _match(self, *types: TokenType) -> bool:
        return self._current().type in types

    def _add_error(
        self,
        message: str,
        pos: Optional[SourcePosition] = None,
        code: str = "SAIL001",
        end_pos: Optional[SourcePosition] = None,
    ) -> None:
        token = self._current()
        start = pos or token.pos
        end = end_pos or token.end
        if end is None or end.offset <= start.offset:
            end = SourcePosition(start.line, start.column + 1, start.offset + 1)
        self.errors.append(
            SailParseError(message=message, pos=start, code=code, end_pos=end),
        )

    # ------------------------------------------------------------------
    # Expression parsing -- precedence climbing
    # ------------------------------------------------------------------

    def _parse_expression(self) -> Node:
        """Entry point: parse a full expression."""
        return self._parse_equality()

    def _parse_equality(self) -> Node:
        """Precedence 1: ``=`` and ``<>``."""
        left = self._parse_comparison()
        while self._match(TokenType.EQUAL, TokenType.NOT_EQUAL):
            op = self._advance()
            right = self._parse_comparison()
            left = BinaryOp(
                op=op.value, left=left, right=right, pos=left.pos, end=right.end,
            )
        return left

    def _parse_comparison(self) -> Node:
        """Precedence 2: ``<``, ``>``, ``<=``, ``>=``."""
        left = self._parse_additive()
        while self._match(
            TokenType.LESS,
            TokenType.GREATER,
            TokenType.LESS_EQUAL,
            TokenType.GREATER_EQUAL,
        ):
            op = self._advance()
            right = self._parse_additive()
            left = BinaryOp(
                op=op.value, left=left, right=right, pos=left.pos, end=right.end,
            )
        return left

    def _parse_additive(self) -> Node:
        """Precedence 3: ``+``, ``-``, ``&``."""
        left = self._parse_multiplicative()
        while self._match(TokenType.PLUS, TokenType.MINUS, TokenType.AMPERSAND):
            op = self._advance()
            right = self._parse_multiplicative()
            left = BinaryOp(
                op=op.value, left=left, right=right, pos=left.pos, end=right.end,
            )
        return left

    def _parse_multiplicative(self) -> Node:
        """Precedence 4: ``*``, ``/``."""
        left = self._parse_unary()
        while self._match(TokenType.STAR, TokenType.SLASH):
            op = self._advance()
            right = self._parse_unary()
            left = BinaryOp(
                op=op.value, left=left, right=right, pos=left.pos, end=right.end,
            )
        return left

    def _parse_unary(self) -> Node:
        """Precedence 5: unary ``-``."""
        if self._match(TokenType.MINUS):
            op = self._advance()
            operand = self._parse_unary()  # right-recursive
            return UnaryOp(op="-", operand=operand, pos=op.pos, end=operand.end)
        return self._parse_postfix()

    def _parse_postfix(self) -> Node:
        """Precedence 6: dot access (``.field``) and bracket access (``[expr]``)."""
        node = self._parse_primary()
        while True:
            if self._match(TokenType.DOT):
                self._advance()
                if self._match(TokenType.IDENTIFIER):
                    field = self._advance()
                    node = DotAccess(
                        target=node, field=field.value, pos=node.pos, end=field.end,
                    )
                elif self._match(TokenType.PREFIXED_IDENTIFIER):
                    # Edge case -- the tokenizer may have consumed
                    # ``fields!something`` as a prefixed id after a dot.
                    field = self._advance()
                    node = DotAccess(
                        target=node, field=field.value, pos=node.pos, end=field.end,
                    )
                else:
                    self._add_error("Expected field name after '.'")
                    break
            elif self._match(TokenType.LBRACKET):
                self._advance()
                index_expr = self._parse_expression()
                close = self._expect(TokenType.RBRACKET, "bracket access")
                node = BracketAccess(
                    target=node,
                    index=index_expr,
                    pos=node.pos,
                    end=close.end or index_expr.end,
                )
            else:
                break
        return node

    def _parse_primary(self) -> Node:
        """Precedence 7: literals, calls, identifiers, lists, ``(expr)``."""
        tok = self._current()

        # -- Literals --------------------------------------------------

        if tok.type == TokenType.NUMBER:
            self._advance()
            if "." in tok.value:
                value: Union[int, float] = float(tok.value)
            else:
                value = int(tok.value)
            return NumberLiteral(value=value, pos=tok.pos, end=tok.end)

        if tok.type == TokenType.STRING:
            self._advance()
            return StringLiteral(value=tok.value, pos=tok.pos, end=tok.end)

        if tok.type == TokenType.QUOTED_REFERENCE:
            self._advance()
            name = f"'{tok.value}'"
            if self._match(TokenType.LPAREN):
                args = self._parse_args()
                return FunctionCall(
                    name=name,
                    args=args,
                    pos=tok.pos,
                    end=self._previous_end(tok),
                )
            return Identifier(name=name, pos=tok.pos, end=tok.end)

        if tok.type == TokenType.TRUE:
            self._advance()
            if self._match(TokenType.LPAREN):
                args = self._parse_args()
                if args:
                    self._add_error("true() does not accept arguments", tok.pos)
            return BoolLiteral(value=True, pos=tok.pos, end=self._previous_end(tok))

        if tok.type == TokenType.FALSE:
            self._advance()
            if self._match(TokenType.LPAREN):
                args = self._parse_args()
                if args:
                    self._add_error("false() does not accept arguments", tok.pos)
            return BoolLiteral(value=False, pos=tok.pos, end=self._previous_end(tok))

        if tok.type == TokenType.NULL:
            self._advance()
            if self._match(TokenType.LPAREN):
                args = self._parse_args()
                if args:
                    self._add_error("null() does not accept arguments", tok.pos)
            return NullLiteral(pos=tok.pos, end=self._previous_end(tok))

        # -- Identifier (plain function call or bare identifier) -------

        if tok.type == TokenType.IDENTIFIER:
            return self._parse_identifier_or_call()

        # -- Prefixed identifier (a!comp, ri!var, ...) -----------------

        if tok.type == TokenType.PREFIXED_IDENTIFIER:
            return self._parse_prefixed()

        # -- Hash reference (#"uuid"(...) or #"SYSTEM_..."(...)) -------

        if tok.type == TokenType.HASH_REF:
            return self._parse_hash_ref()

        # -- List literal {1, 2, 3} ------------------------------------

        if tok.type == TokenType.LBRACE:
            return self._parse_list()

        # -- Parenthesised expression (expr) ---------------------------

        if tok.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expression()
            close = self._expect(TokenType.RPAREN, "parenthesised expression")
            expr.end = close.end or expr.end
            return expr

        # -- Error recovery --------------------------------------------

        self._add_error(
            f"Unexpected token: {tok.type.value} ('{tok.value}')",
        )
        self._advance()
        return ErrorNode(
            message=f"Unexpected: {tok.value}", tokens=[tok], pos=tok.pos,
            end=tok.end,
        )

    # ------------------------------------------------------------------
    # Specialised primary parsers
    # ------------------------------------------------------------------

    def _parse_identifier_or_call(self) -> Node:
        """Parse a plain identifier, optionally followed by ``(...)``."""
        tok = self._advance()  # IDENTIFIER
        name = tok.value

        if self._match(TokenType.LPAREN):
            args = self._parse_args()
            # Recognise well-known type-cast functions
            if (
                name.lower() in TYPE_CAST_FUNCTIONS
                and len(args) == 1
                and args[0].name is None
            ):
                return TypeCast(
                    type_name=name,
                    expression=args[0].value,
                    pos=tok.pos,
                    end=self._previous_end(tok),
                )
            return FunctionCall(
                name=name, args=args, pos=tok.pos, end=self._previous_end(tok),
            )

        return Identifier(name=name, pos=tok.pos, end=tok.end)

    def _parse_prefixed(self) -> Node:
        """Parse a prefixed identifier: ``a!comp(...)``, ``ri!var``, etc."""
        tok = self._advance()  # PREFIXED_IDENTIFIER
        prefix = tok.prefix
        name = tok.name

        # a! prefix  -->  ComponentCall if followed by (
        if prefix in COMPONENT_PREFIXES:
            if self._match(TokenType.LPAREN):
                args = self._parse_args()
                return ComponentCall(
                    name=name, args=args, pos=tok.pos, end=self._previous_end(tok),
                )
            # a!something without parens -- treat as domain var
            return DomainVar(domain=prefix, name=name, pos=tok.pos, end=tok.end)

        # Other domains: ri!, local!, fv!, rule!, cons!, ...
        if self._match(TokenType.LPAREN):
            # Some domains allow callable syntax: rule!myRule()
            args = self._parse_args()
            return FunctionCall(
                name=f"{prefix}!{name}",
                args=args,
                pos=tok.pos,
                end=self._previous_end(tok),
            )

        return DomainVar(domain=prefix, name=name, pos=tok.pos, end=tok.end)

    def _parse_hash_ref(self) -> Node:
        """Parse ``#"..."`` optionally followed by ``(args)``."""
        tok = self._advance()  # HASH_REF
        content = tok.value
        is_system = content.startswith("SYSTEM_")

        if self._match(TokenType.LPAREN):
            args = self._parse_args()
            if is_system:
                return SystemCall(
                    name=content, args=args, pos=tok.pos, end=self._previous_end(tok),
                )
            return UuidCall(
                uuid=content, args=args, pos=tok.pos, end=self._previous_end(tok),
            )

        # Reference without a call (used as a value)
        if is_system:
            return SystemCall(name=content, args=[], pos=tok.pos, end=tok.end)
        return UuidCall(uuid=content, args=[], pos=tok.pos, end=tok.end)

    def _parse_list(self) -> Node:
        """Parse a list or dictionary literal."""
        brace = self._advance()  # LBRACE
        items: list[Node] = []
        entries: list[DictionaryEntry] = []
        is_dictionary = False

        while not self._match(TokenType.RBRACE, TokenType.EOF):
            if self._match(TokenType.COMMA):
                self._add_error(
                    "Empty item in literal", code="SAIL004",
                )
                self._advance()
                continue

            key_or_item = self._parse_expression()
            if self._match(TokenType.COLON):
                is_dictionary = True
                self._advance()
                if self._match(TokenType.COMMA, TokenType.RBRACE, TokenType.EOF):
                    self._add_error(
                        "Missing dictionary value", code="SAIL005",
                    )
                    value: Node = ErrorNode(
                        message="Missing dictionary value",
                        pos=self._current().pos,
                        end=self._current().end,
                    )
                else:
                    value = self._parse_expression()
                entries.append(DictionaryEntry(
                    key=key_or_item,
                    value=value,
                    pos=key_or_item.pos,
                    end=value.end,
                ))
            elif is_dictionary:
                self._add_error(
                    "Dictionary item is missing ':'", code="SAIL006",
                    pos=key_or_item.pos,
                    end_pos=key_or_item.end,
                )
            else:
                items.append(key_or_item)

            if self._match(TokenType.COMMA):
                self._advance()
            elif not self._match(TokenType.RBRACE):
                self._add_error("Expected ',' or '}' in list literal")
                break

        close = self._expect(TokenType.RBRACE, "literal")
        end = close.end or self._previous_end(brace)
        if is_dictionary:
            if items:
                self._add_error(
                    "Cannot mix list and dictionary items",
                    code="SAIL007",
                    pos=items[0].pos,
                    end_pos=items[-1].end,
                )
            return DictionaryLiteral(entries=entries, pos=brace.pos, end=end)
        return ListLiteral(items=items, pos=brace.pos, end=end)

    # ------------------------------------------------------------------
    # Argument list parsing
    # ------------------------------------------------------------------

    def _parse_args(self) -> list[Arg]:
        """Parse ``(arg, arg, name: value, ...)``.

        Handles three syntactic forms per argument:

        1. **Named argument** -- ``paramName: expression``
        2. **Variable binding** -- ``local!x: expression``
        3. **Positional argument** -- ``expression``
        """
        self._advance()  # LPAREN
        args: list[Arg] = []

        while not self._match(TokenType.RPAREN, TokenType.EOF):
            if self._match(TokenType.COMMA):
                comma = self._advance()
                self._add_error(
                    "Empty argument", comma.pos, "SAIL003", comma.end,
                )
                continue
            arg = self._parse_single_arg()
            if arg is not None:
                args.append(arg)

            if self._match(TokenType.COMMA):
                self._advance()
            elif not self._match(TokenType.RPAREN):
                self._add_error("Expected ',' or ')' in argument list")
                self._sync_to(TokenType.COMMA, TokenType.RPAREN)
                if self._match(TokenType.COMMA):
                    self._advance()

        self._expect(TokenType.RPAREN, "argument list")
        return args

    def _previous_end(self, fallback: Token) -> Optional[SourcePosition]:
        if self.pos > 0:
            return self.tokens[self.pos - 1].end
        return fallback.end

    def _parse_single_arg(self) -> Optional[Arg]:
        """Parse one argument inside a call's parentheses."""
        start = self._current().pos
        tok = self._current()

        # Named argument: identifier or quoted key, COLON, expression
        if (
            tok.type in (TokenType.IDENTIFIER, TokenType.STRING)
            and self._peek().type == TokenType.COLON
        ):
            name = tok.value
            quoted_name = tok.type == TokenType.STRING
            self._advance()  # identifier
            self._advance()  # colon
            value = self._parse_expression()
            return Arg(
                name=name,
                value=value,
                quoted_name=quoted_name,
                pos=start,
                end=value.end,
            )

        # Variable binding:  domain!var COLON expression
        if (
            tok.type == TokenType.PREFIXED_IDENTIFIER
            and self._peek().type == TokenType.COLON
            and tok.prefix in VARIABLE_DOMAINS
        ):
            full_name = f"{tok.prefix}!{tok.name}"
            self._advance()  # prefixed identifier
            self._advance()  # colon
            value = self._parse_expression()
            binding = VariableBinding(
                name=full_name, expression=value, pos=start, end=value.end,
            )
            return Arg(name=None, value=binding, pos=start, end=value.end)

        # Positional argument
        value = self._parse_expression()
        if self._match(TokenType.COLON):
            self._advance()
            mapped_value = self._parse_expression()
            return Arg(
                name=None,
                value=mapped_value,
                key=value,
                pos=start,
                end=mapped_value.end,
            )
        return Arg(name=None, value=value, pos=start, end=value.end)

    # ------------------------------------------------------------------
    # Error recovery
    # ------------------------------------------------------------------

    def _sync_to(self, *types: TokenType) -> None:
        """Skip tokens until one of *types* is found (respecting nesting)."""
        depth = 0
        while not self._match(TokenType.EOF):
            if depth == 0 and self._current().type in types:
                return
            if self._match(
                TokenType.LPAREN, TokenType.LBRACE, TokenType.LBRACKET,
            ):
                depth += 1
            elif self._match(
                TokenType.RPAREN, TokenType.RBRACE, TokenType.RBRACKET,
            ):
                if depth > 0:
                    depth -= 1
                else:
                    return
            self._advance()


# ============================================================================
# Node Visitor (pattern)
# ============================================================================

class NodeVisitor:
    """Base visitor for traversing a SAIL AST.

    Override ``visit_<NodeClassName>`` methods in subclasses to handle
    specific node types.  Unhandled types fall through to
    :meth:`generic_visit`, which recurses into all child nodes.

    Example::

        class FuncCounter(NodeVisitor):
            def __init__(self):
                self.count = 0

            def visit_FunctionCall(self, node):
                self.count += 1
                self.generic_visit(node)

        counter = FuncCounter()
        counter.visit(ast)
        print(counter.count)
    """

    def visit(self, node: Node) -> Any:
        """Dispatch *node* to the appropriate ``visit_*`` method."""
        method = f"visit_{type(node).__name__}"
        handler = getattr(self, method, self.generic_visit)
        return handler(node)

    def generic_visit(self, node: Node) -> None:
        """Default handler: recurse into every child node."""
        for child in self._iter_children(node):
            self.visit(child)

    @staticmethod
    def _iter_children(node: Node):
        """Yield every direct child :class:`Node` of *node*."""
        if isinstance(node, (FunctionCall, ComponentCall, UuidCall, SystemCall)):
            yield from node.args
        elif isinstance(node, Arg):
            if node.key is not None:
                yield node.key
            if node.value is not None:
                yield node.value
        elif isinstance(node, DotAccess):
            if node.target is not None:
                yield node.target
        elif isinstance(node, BracketAccess):
            if node.target is not None:
                yield node.target
            if node.index is not None:
                yield node.index
        elif isinstance(node, BinaryOp):
            if node.left is not None:
                yield node.left
            if node.right is not None:
                yield node.right
        elif isinstance(node, UnaryOp):
            if node.operand is not None:
                yield node.operand
        elif isinstance(node, ListLiteral):
            yield from node.items
        elif isinstance(node, DictionaryLiteral):
            yield from node.entries
        elif isinstance(node, DictionaryEntry):
            if node.key is not None:
                yield node.key
            if node.value is not None:
                yield node.value
        elif isinstance(node, VariableBinding):
            if node.expression is not None:
                yield node.expression
        elif isinstance(node, TypeCast):
            if node.expression is not None:
                yield node.expression
        elif isinstance(node, ErrorNode):
            pass  # terminal
        # Leaf nodes have no children.


# ============================================================================
# Concrete visitors for the public utility functions
# ============================================================================

class _UuidRefCollector(NodeVisitor):
    """Collects every UUID string from :class:`UuidCall` nodes."""

    def __init__(self) -> None:
        self.uuids: set[str] = set()

    def visit_UuidCall(self, node: UuidCall) -> None:
        self.uuids.add(node.uuid)
        self.generic_visit(node)


class _DomainVarCollector(NodeVisitor):
    """Collects domain variables grouped by domain prefix."""

    def __init__(self) -> None:
        self.vars: dict[str, set[str]] = {}

    def visit_DomainVar(self, node: DomainVar) -> None:
        self.vars.setdefault(node.domain, set()).add(node.name)

    def visit_VariableBinding(self, node: VariableBinding) -> None:
        domain = node.domain
        var = node.var_name
        if domain:
            self.vars.setdefault(domain, set()).add(var)
        # Also walk the bound expression
        if node.expression is not None:
            self.visit(node.expression)


# ============================================================================
# Pretty Printer
# ============================================================================

_OP_PRECEDENCE: dict[str, int] = {
    "=": 1, "<>": 1,
    "<": 2, ">": 2, "<=": 2, ">=": 2,
    "+": 3, "-": 3, "&": 3,
    "*": 4, "/": 4,
}


class _PrettyPrinter:
    """Serialises an AST back into readable SAIL source code.

    Short expressions are kept on a single line; longer ones are
    broken across multiple lines with consistent indentation.
    """

    def __init__(self, indent_size: int = 2) -> None:
        self.indent_size = indent_size

    def format(self, node: Node) -> str:
        """Return the SAIL source text for *node*."""
        return self._fmt(node, indent=0)

    # ------------------------------------------------------------------

    def _fmt(self, node: Optional[Node], indent: int) -> str:
        if node is None:
            return "null"

        # -- Leaf literals ---------------------------------------------
        if isinstance(node, NullLiteral):
            return "null"
        if isinstance(node, BoolLiteral):
            return "true" if node.value else "false"
        if isinstance(node, NumberLiteral):
            if isinstance(node.value, float) and node.value == int(node.value):
                return str(int(node.value))
            return str(node.value)
        if isinstance(node, StringLiteral):
            escaped = node.value.replace('"', '""')
            return f'"{escaped}"'
        if isinstance(node, Identifier):
            return node.name
        if isinstance(node, DomainVar):
            return f"{node.domain}!{node.name}"
        if isinstance(node, Comment):
            return f"/* {node.text} */"
        if isinstance(node, ErrorNode):
            return f"/* ERROR: {node.message} */"

        # -- Compound nodes --------------------------------------------
        if isinstance(node, DotAccess):
            return f"{self._fmt(node.target, indent)}.{node.field}"
        if isinstance(node, BracketAccess):
            return (
                f"{self._fmt(node.target, indent)}"
                f"[{self._fmt(node.index, indent)}]"
            )
        if isinstance(node, UnaryOp):
            operand = self._fmt(node.operand, indent)
            if isinstance(node.operand, BinaryOp):
                return f"{node.op}({operand})"
            return f"{node.op}{operand}"
        if isinstance(node, BinaryOp):
            left = self._fmt_binary_child(node.left, node.op, is_right=False, indent=indent)
            right = self._fmt_binary_child(node.right, node.op, is_right=True, indent=indent)
            return f"{left} {node.op} {right}"
        if isinstance(node, ListLiteral):
            return self._fmt_list(node, indent)
        if isinstance(node, DictionaryLiteral):
            content = ", ".join(
                f"{self._fmt(entry.key, indent)}: {self._fmt(entry.value, indent)}"
                for entry in node.entries
            )
            return "{" + content + "}"
        if isinstance(node, VariableBinding):
            return f"{node.name}: {self._fmt(node.expression, indent)}"
        if isinstance(node, TypeCast):
            return f"{node.type_name}({self._fmt(node.expression, indent)})"
        if isinstance(node, RecordFieldRef):
            path = ".".join(node.field_path)
            return f"recordType!{node.record_type}.{path}"
        if isinstance(node, Arg):
            val = self._fmt(node.value, indent)
            if node.key is not None:
                return f"{self._fmt(node.key, indent)}: {val}"
            if node.name is not None:
                name = (
                    '"' + node.name.replace('"', '""') + '"'
                    if node.quoted_name
                    else node.name
                )
                return f"{name}: {val}"
            return val

        # -- Calls -----------------------------------------------------
        if isinstance(node, FunctionCall):
            return self._fmt_call(node.name, node.args, indent)
        if isinstance(node, ComponentCall):
            return self._fmt_call(f"a!{node.name}", node.args, indent)
        if isinstance(node, UuidCall):
            return self._fmt_call(f'#"{node.uuid}"', node.args, indent)
        if isinstance(node, SystemCall):
            return self._fmt_call(f'#"{node.name}"', node.args, indent)

        return f"/* unknown: {type(node).__name__} */"

    # -- Helpers -------------------------------------------------------

    def _fmt_binary_child(
        self,
        child: Optional[Node],
        parent_op: str,
        *,
        is_right: bool,
        indent: int,
    ) -> str:
        """Format a child of a BinaryOp, adding parentheses when needed."""
        text = self._fmt(child, indent)
        if isinstance(child, BinaryOp):
            child_prec = _OP_PRECEDENCE.get(child.op, 0)
            parent_prec = _OP_PRECEDENCE.get(parent_op, 0)
            needs_parens = child_prec < parent_prec or (
                child_prec == parent_prec and is_right
            )
            if needs_parens:
                return f"({text})"
        return text

    def _fmt_call(self, name: str, args: list[Arg], indent: int) -> str:
        if not args:
            return f"{name}()"

        formatted = [self._fmt(a, indent + 1) for a in args]
        inline = f"{name}({', '.join(formatted)})"

        if len(inline) <= 80 and "\n" not in inline:
            return inline

        pad = " " * ((indent + 1) * self.indent_size)
        lines = ",\n".join(f"{pad}{a}" for a in formatted)
        closing_pad = " " * (indent * self.indent_size)
        return f"{name}(\n{lines}\n{closing_pad})"

    def _fmt_list(self, node: ListLiteral, indent: int) -> str:
        if not node.items:
            return "{}"

        formatted = [self._fmt(item, indent + 1) for item in node.items]
        inline = "{" + ", ".join(formatted) + "}"

        if len(inline) <= 80 and "\n" not in inline:
            return inline

        pad = " " * ((indent + 1) * self.indent_size)
        lines = ",\n".join(f"{pad}{f}" for f in formatted)
        closing_pad = " " * (indent * self.indent_size)
        return "{\n" + lines + "\n" + closing_pad + "}"


# ============================================================================
# Public API -- Utility Functions
# ============================================================================

def parse_sail(source: str) -> Node:
    """Parse SAIL source code into an AST.

    This is the primary entry point.  The parser is fault-tolerant --
    it never raises on malformed input; instead it returns a best-effort
    AST.  To inspect errors use :func:`validate_syntax` or
    :func:`parse_sail_with_context`.

    Args:
        source: SAIL expression source code.

    Returns:
        The root AST node.

    Example::

        ast = parse_sail('if(ri!flag, "yes", "no")')
    """
    tokenizer = SailTokenizer(source)
    tokens = tokenizer.tokenize()
    parser = SailParser(tokens, errors=tokenizer.errors)
    return parser.parse()


def parse_sail_with_context(
    source: str,
) -> tuple[Node, list[SailParseError], list[Comment]]:
    """Parse SAIL source and return the AST together with diagnostics.

    Args:
        source: SAIL expression source code.

    Returns:
        A three-tuple ``(ast, errors, comments)``.
    """
    tokenizer = SailTokenizer(source)
    tokens = tokenizer.tokenize()
    parser = SailParser(tokens, errors=tokenizer.errors)
    ast = parser.parse()
    return ast, parser.errors, parser.comments


def extract_uuid_refs(node: Node) -> set[str]:
    """Extract all UUID references from an AST.

    Walks the tree and collects the ``uuid`` attribute from every
    :class:`UuidCall` node.

    Args:
        node: The root AST node.

    Returns:
        A set of UUID strings.

    Example::

        >>> ast = parse_sail('#"_a-0000xxxx-..."(ri!doc)')
        >>> extract_uuid_refs(ast)
        {'_a-0000xxxx-...'}
    """
    collector = _UuidRefCollector()
    collector.visit(node)
    return collector.uuids


def extract_domain_vars(node: Node) -> dict[str, set[str]]:
    """Extract all domain variables from an AST, grouped by domain.

    Walks the tree and collects names from :class:`DomainVar` and
    :class:`VariableBinding` nodes.

    Args:
        node: The root AST node.

    Returns:
        A dict mapping domain prefixes to sets of variable names.

    Example::

        >>> ast = parse_sail('if(ri!isActive, local!name, null)')
        >>> extract_domain_vars(ast)
        {'ri': {'isActive'}, 'local': {'name'}}
    """
    collector = _DomainVarCollector()
    collector.visit(node)
    return collector.vars


def validate_syntax(source: str) -> list[SailParseError]:
    """Validate SAIL syntax and return any errors found.

    Runs the full tokenizer and parser, collecting all errors.

    Args:
        source: SAIL expression source code.

    Returns:
        A list of :class:`SailParseError` instances.  An empty list
        means the input is syntactically valid.
    """
    tokenizer = SailTokenizer(source)
    tokens = tokenizer.tokenize()
    parser = SailParser(tokens, errors=tokenizer.errors)
    parser.parse()
    return parser.errors


def pretty_print(node: Node, indent_size: int = 2) -> str:
    """Serialise an AST back to readable SAIL source code.

    Short expressions stay on one line; longer ones are broken across
    lines with consistent indentation.  Operator precedence is
    preserved via parentheses where needed.

    Args:
        node: The root AST node.
        indent_size: Spaces per indentation level (default 2).

    Returns:
        Formatted SAIL source code.
    """
    return _PrettyPrinter(indent_size=indent_size).format(node)
