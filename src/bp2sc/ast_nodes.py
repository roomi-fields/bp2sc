"""AST node definitions for BP3 grammar structures.

See docs/bp3_ast_spec.md for the formal specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# --- Header nodes ---

@dataclass
class Comment:
    text: str


@dataclass
class FileRef:
    prefix: str   # "se", "al", "ho", "cs"
    name: str


@dataclass
class InitDirective:
    text: str     # raw text after "INIT:"


Header = Comment | FileRef | InitDirective


# --- Weight ---

@dataclass
class Weight:
    value: int
    decrement: int | None = None  # for <50-12>


# --- Flag ---

@dataclass
class Flag:
    name: str
    op: str = ""          # "=", "+", "-", ">", "<", or "" (bare condition)
    value: str | None = None  # int or flag name for comparison


# --- Homomorphism kind enum ---

class HomoApplyKind(Enum):
    MASTER = "master"   # (= ...) — defines the pattern
    SLAVE = "slave"     # (: ...) — replicates the master's pattern
    REF = "ref"         # named homomorphism reference


# --- RHS elements ---

@dataclass
class Note:
    name: str           # "do", "re", "sa", "fa", "sol", "la", "si", "sib", etc.
    octave: int | None = None


@dataclass
class Rest:
    """A silence marker: '-' or '_'."""
    determined: bool = True  # True for '-', False for '_'


@dataclass
class UndeterminedRest:
    """Undetermined continuation: '...' (distinct from Rest)."""
    pass


@dataclass
class NonTerminal:
    name: str           # "S", "Tihai", "P4", etc.


@dataclass
class Variable:
    name: str           # without the | delimiters


@dataclass
class Wildcard:
    index: int          # ?1, ?2, etc. (0 for anonymous ?)


@dataclass
class Polymetric:
    tempo_ratio: int | None = None
    voices: list[list[RHSElement]] = field(default_factory=list)


@dataclass
class SpecialFn:
    name: str           # "transpose", "vel", "ins", "mm", etc.
    args: list[str] = field(default_factory=list)


@dataclass
class Lambda:
    pass


@dataclass
class HomoApply:
    """Homomorphism application: (= expr) or (: expr)."""
    kind: HomoApplyKind
    elements: list[RHSElement] = field(default_factory=list)


@dataclass
class TimeSig:
    """Time signature like 4+4+4+4+4+4/4."""
    text: str


@dataclass
class Annotation:
    """Bracket annotation: [Variant], [?], [text]."""
    text: str


@dataclass
class QuotedSymbol:
    """Single-quoted symbol: '1', '2' (distinct from Terminal/NonTerminal)."""
    text: str


@dataclass
class Tie:
    """Tied note: C4& (start) or &C4 (end)."""
    note: Note
    is_start: bool  # True for start (note&), False for end (&note)


@dataclass
class ContextMarker:
    """Context-sensitive grammar marker."""
    kind: str  # "distant", "open", "close", "wild", "left"
    symbol: RHSElement | None = None


@dataclass
class GotoDirective:
    """_goto(grammar, rule) — affects derivation flow."""
    grammar: int
    rule: int


# Keep BracketComment as alias for backward compatibility during transition
BracketComment = Annotation


RHSElement = (
    Note | Rest | UndeterminedRest | NonTerminal | Variable | Wildcard
    | Polymetric | SpecialFn | Lambda | HomoApply | TimeSig | Annotation
    | QuotedSymbol | Tie | ContextMarker | GotoDirective
)


# --- Rule ---

@dataclass
class Rule:
    grammar_num: int
    rule_num: int
    weight: Weight | None = None
    flags: list[Flag] = field(default_factory=list)
    lhs: list[RHSElement] = field(default_factory=list)
    rhs: list[RHSElement] = field(default_factory=list)
    comment: str | None = None


# --- Grammar block ---

@dataclass
class GrammarBlock:
    mode: str               # "ORD", "RND", "LIN", "SUB1"
    index: int | None = None  # subgrammar number from [N]
    label: str | None = None  # optional label like "Effects"
    preamble: list[SpecialFn] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)


# --- Top-level file ---

@dataclass
class BPFile:
    headers: list[Header] = field(default_factory=list)
    grammars: list[GrammarBlock] = field(default_factory=list)
