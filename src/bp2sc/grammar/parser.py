"""Parser for BP3 grammar files.

Uses a two-phase approach:
1. Line-oriented pre-processor that classifies lines (comments, headers,
   modes, separators, preambles, rules)
2. Per-line parser for rule internals (weight, flags, LHS --> RHS) using
   regex-based recursive descent

The Lark grammar (bp3.lark) serves as the formal reference but parsing
is done by regex for BP3's line-oriented format.

See docs/bp3_ebnf.xml for the formal EBNF specification.
See docs/bp3_ast_spec.md for the AST node definitions.
"""

from __future__ import annotations

import re
from pathlib import Path

from bp2sc.ast_nodes import (
    BPFile, GrammarBlock, Rule, Weight, Flag,
    Note, Rest, NonTerminal, Variable, Wildcard,
    Polymetric, SpecialFn, Lambda, HomoApply, HomoApplyKind,
    TimeSig, Annotation, Tie,
    Comment, FileRef, InitDirective,
    Header, RHSElement,
)


# ---------- Regex patterns ----------

RE_COMMENT = re.compile(r"^\s*//(.*)$")
RE_FILE_REF = re.compile(r"^-(\w+)\.(.+)$")
RE_INIT = re.compile(r"^\s*INIT:\s*(.+)$")
RE_MODE = re.compile(
    r"^\s*(ORD|RND|LIN|SUB1|SUB)"
    r"(?:\s*\[([^\]]*)\])?"     # optional index [1]
    r"(?:\s*\[([^\]]*)\])?"     # optional label [Effects]
    r"\s*$"
)
RE_SEPARATOR = re.compile(r"^---[-]+\s*$")
RE_PREAMBLE = re.compile(r"^\s*(_\w+\([^)]*\)[\s]*)+$|^\s*(_\w+[\s]*)+$")
RE_RULE = re.compile(r"^\s*gram#(\d+)\[(\d+)\]", re.IGNORECASE)
# Bare rule: SYMBOL --> ... (no gram# prefix)
RE_BARE_RULE = re.compile(r"^\s*([A-Z][A-Za-z0-9_'\"]*)\s+-->")

# Tokens inside rules
RE_WEIGHT = re.compile(r"<(\d+)(?:-(\d+))?>")
RE_FLAG = re.compile(r"/([^/]+)/")
RE_ARROW = re.compile(r"-->")
RE_SPECIAL_FN = re.compile(r"_([a-zA-Z]\w*)\(([^)]*)\)")
RE_SPECIAL_FN_BARE = re.compile(r"_([a-zA-Z]\w*)")  # no-parens variant
RE_POLYMETRIC_OPEN = re.compile(r"\{")
RE_POLYMETRIC_CLOSE = re.compile(r"\}")
RE_VARIABLE = re.compile(r"\|([^|]+)\|")
RE_WILDCARD = re.compile(r"\?(\d+)")
RE_HOMO_MASTER = re.compile(r"\(=\s*")
RE_HOMO_SLAVE = re.compile(r"\(:\s*")
RE_HOMO_CLOSE = re.compile(r"\)")
RE_HOMO_NAME = re.compile(r"\b(mineur|majeur|trn)\b")
RE_TIME_SIG = re.compile(r"\b(\d+(?:\+\d+)+/\d+)\b")
RE_ANNOTATION = re.compile(r"\[([^\]]*)\]")
RE_LAMBDA = re.compile(r"\blambda\b")

# Notes
RE_NOTE_FR = re.compile(r"\b(do|re|mi|fa|sol|la|si)(b|#)?(\d)\b")
RE_NOTE_INDIAN = re.compile(r"\b(sa|re|ga|ma|pa|dha|ni)(\d)\b")
RE_NOTE_ANGLO = re.compile(r"\b([A-G])(#|b)?(\d)\b")

# Tied notes: &C4 (tie end), C4& (tie start), or &C4& (both)
# These patterns match Anglo notes with optional & prefix/suffix
RE_TIED_NOTE_ANGLO = re.compile(r"(&)?([A-G])(#|b)?(\d)(&)?")
RE_TIED_NOTE_FR = re.compile(r"(&)?(do|re|mi|fa|sol|la|si)(b|#)?(\d)(&)?")

# Tempo inline: ||N|| where N is BPM (integer or decimal)
RE_TEMPO_INLINE = re.compile(r"\|\|(\d+(?:\.\d+)?)\|\|")

# Nonterminal: uppercase start, then letters/digits/'/"
RE_NONTERMINAL = re.compile(r"\b([A-Z][A-Za-z0-9_'\"]*)\b")

# Rest
RE_REST_DASH = re.compile(r"(?<![.\w#>])-(?![.\w>-])")
RE_REST_UNDER = re.compile(r"\b_(?![a-zA-Z])")

# Striated preamble
RE_STRIATED = re.compile(r"_striated", re.IGNORECASE)


def parse_file(path: str | Path) -> BPFile:
    """Parse a BP3 grammar file and return an AST."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_text(text)


def parse_text(text: str) -> BPFile:
    """Parse BP3 grammar text and return an AST."""
    lines = text.split("\n")
    headers: list[Header] = []
    grammars: list[GrammarBlock] = []
    current_block: GrammarBlock | None = None
    in_headers = True

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            i += 1
            continue

        # Comments (can appear anywhere)
        m = RE_COMMENT.match(stripped)
        if m:
            if in_headers:
                headers.append(Comment(m.group(1).strip()))
            i += 1
            continue

        # File references (header only)
        m = RE_FILE_REF.match(stripped)
        if m and in_headers:
            headers.append(FileRef(m.group(1), m.group(2)))
            i += 1
            continue

        # INIT directive
        m = RE_INIT.match(stripped)
        if m:
            headers.append(InitDirective(m.group(1).strip()))
            i += 1
            continue

        # Separator line
        if RE_SEPARATOR.match(stripped):
            i += 1
            continue

        # Mode line -> new grammar block
        m = RE_MODE.match(stripped)
        if m:
            in_headers = False
            mode = m.group(1)
            index_str = m.group(2)
            label = m.group(3)
            index = int(index_str) if index_str and index_str.isdigit() else None
            if label is None and index_str and not index_str.isdigit():
                label = index_str
                index = None
            current_block = GrammarBlock(mode=mode, index=index, label=label)
            grammars.append(current_block)
            i += 1
            continue

        # Preamble (special functions before rules, like _mm(88) _striated)
        if (current_block is not None
                and not RE_RULE.match(stripped)
                and not RE_BARE_RULE.match(stripped)):
            # Could be preamble items
            preamble_items = _try_parse_preamble(stripped)
            if preamble_items:
                current_block.preamble.extend(preamble_items)
                i += 1
                continue

        # Rule line
        m = RE_RULE.match(stripped)
        if m:
            in_headers = False
            if current_block is None:
                # Auto-create a block
                current_block = GrammarBlock(mode="ORD")
                grammars.append(current_block)

            rule = _parse_rule_line(stripped, int(m.group(1)), int(m.group(2)))
            current_block.rules.append(rule)
            i += 1
            continue

        # Bare rule line: SYMBOL --> ... (no gram# prefix)
        m = RE_BARE_RULE.match(stripped)
        if m:
            in_headers = False
            if current_block is None:
                current_block = GrammarBlock(mode="ORD")
                grammars.append(current_block)
            # Infer grammar_num from current block, rule_num incremental
            gram_num = current_block.index or 1
            rule_num = len(current_block.rules) + 1
            rule = _parse_bare_rule_line(stripped, gram_num, rule_num)
            current_block.rules.append(rule)
            i += 1
            continue

        # Unknown line -- skip
        i += 1

    # Auto-assign grammar block indices if not specified
    for idx, block in enumerate(grammars, 1):
        if block.index is None:
            block.index = idx

    return BPFile(headers=headers, grammars=grammars)


def _try_parse_preamble(line: str) -> list[SpecialFn]:
    """Try to parse a line as preamble items (special fns, _striated)."""
    items: list[SpecialFn] = []
    remaining = line.strip()

    while remaining:
        remaining = remaining.lstrip()
        if not remaining:
            break

        # Special function
        m = RE_SPECIAL_FN.match(remaining)
        if m:
            items.append(SpecialFn(name=m.group(1), args=_split_args(m.group(2))))
            remaining = remaining[m.end():]
            continue

        # _striated
        m = RE_STRIATED.match(remaining)
        if m:
            items.append(SpecialFn(name="striated", args=[]))
            remaining = remaining[m.end():]
            continue

        # Not a preamble line
        if not items:
            return []
        break

    return items


def _parse_rule_line(line: str, gram_num: int, rule_num: int) -> Rule:
    """Parse a single rule line into a Rule AST node."""
    # Remove the gram#N[M] prefix
    m = RE_RULE.match(line)
    rest = line[m.end():].strip()

    # Parse weight
    weight = None
    m = RE_WEIGHT.match(rest)
    if m:
        val = int(m.group(1))
        dec = int(m.group(2)) if m.group(2) else None
        weight = Weight(value=val, decrement=dec)
        rest = rest[m.end():].strip()

    # Parse flag conditions (before the arrow)
    flags: list[Flag] = []
    while rest.startswith("/"):
        m = RE_FLAG.match(rest)
        if m:
            flag = _parse_flag_expr(m.group(1).strip())
            flags.append(flag)
            rest = rest[m.end():].strip()
        else:
            break

    # Split on arrow
    arrow_m = RE_ARROW.search(rest)
    if arrow_m is None:
        # Malformed rule -- return with what we have
        return Rule(
            grammar_num=gram_num, rule_num=rule_num,
            weight=weight, flags=flags,
            lhs=[NonTerminal("?")], rhs=[]
        )

    lhs_text = rest[:arrow_m.start()].strip()
    rhs_text = rest[arrow_m.end():].strip()

    # Remove trailing inline annotations from RHS
    comment = None
    bracket_parts = list(RE_ANNOTATION.finditer(rhs_text))
    trailing_comments = []
    for bp in reversed(bracket_parts):
        if bp.end() >= len(rhs_text.rstrip()):
            trailing_comments.insert(0, bp.group(1))
            rhs_text = rhs_text[:bp.start()] + rhs_text[bp.end():]
            rhs_text = rhs_text.rstrip()
        else:
            break
    if trailing_comments:
        comment = " ".join(trailing_comments)

    # Extract flag operations from RHS text before symbol parsing
    rhs_flags, rhs_text = _extract_flags_from_text(rhs_text)
    flags.extend(rhs_flags)

    # Parse LHS and RHS
    lhs_elements = _parse_symbol_sequence(lhs_text, is_lhs=True)
    rhs_elements = _parse_symbol_sequence(rhs_text, is_lhs=False)

    return Rule(
        grammar_num=gram_num, rule_num=rule_num,
        weight=weight, flags=flags,
        lhs=lhs_elements, rhs=rhs_elements,
        comment=comment,
    )


def _parse_bare_rule_line(line: str, gram_num: int, rule_num: int) -> Rule:
    """Parse a bare rule line (no gram#N[M] prefix) like 'B --> x a'."""
    rest = line.strip()

    # Parse weight
    weight = None
    m = RE_WEIGHT.match(rest)
    if m:
        val = int(m.group(1))
        dec = int(m.group(2)) if m.group(2) else None
        weight = Weight(value=val, decrement=dec)
        rest = rest[m.end():].strip()

    # Parse flag conditions (before the arrow)
    flags: list[Flag] = []
    while rest.startswith("/"):
        m = RE_FLAG.match(rest)
        if m:
            flag = _parse_flag_expr(m.group(1).strip())
            flags.append(flag)
            rest = rest[m.end():].strip()
        else:
            break

    # Split on arrow
    arrow_m = RE_ARROW.search(rest)
    if arrow_m is None:
        return Rule(
            grammar_num=gram_num, rule_num=rule_num,
            weight=weight, flags=flags,
            lhs=[NonTerminal("?")], rhs=[]
        )

    lhs_text = rest[:arrow_m.start()].strip()
    rhs_text = rest[arrow_m.end():].strip()

    # Remove trailing inline annotations from RHS
    comment = None
    bracket_parts = list(RE_ANNOTATION.finditer(rhs_text))
    trailing_comments = []
    for bp in reversed(bracket_parts):
        if bp.end() >= len(rhs_text.rstrip()):
            trailing_comments.insert(0, bp.group(1))
            rhs_text = rhs_text[:bp.start()] + rhs_text[bp.end():]
            rhs_text = rhs_text.rstrip()
        else:
            break
    if trailing_comments:
        comment = " ".join(trailing_comments)

    # Extract flag operations from RHS text
    rhs_flags, rhs_text = _extract_flags_from_text(rhs_text)
    flags.extend(rhs_flags)

    # Parse LHS and RHS
    lhs_elements = _parse_symbol_sequence(lhs_text, is_lhs=True)
    rhs_elements = _parse_symbol_sequence(rhs_text, is_lhs=False)

    return Rule(
        grammar_num=gram_num, rule_num=rule_num,
        weight=weight, flags=flags,
        lhs=lhs_elements, rhs=rhs_elements,
        comment=comment,
    )


def _parse_flag_expr(expr: str) -> Flag:
    """Parse a flag expression like 'Ideas-1', 'NumR+1', 'Ideas=20', 'Ideas'."""
    # flag_name OP value (or flag_name OP flag_name)
    for op in ("=", "+", "-", ">", "<"):
        if op in expr:
            parts = expr.split(op, 1)
            return Flag(name=parts[0].strip(), op=op, value=parts[1].strip())
    return Flag(name=expr.strip())


def _extract_flags_from_text(text: str) -> tuple[list[Flag], str]:
    """Extract /flag/ operations from text, returning (flags, cleaned_text)."""
    flags = []
    clean = text
    for m in RE_FLAG.finditer(text):
        flag = _parse_flag_expr(m.group(1).strip())
        flags.append(flag)
    # Remove all flag patterns from text
    clean = RE_FLAG.sub("", clean).strip()
    return flags, clean


def _parse_symbol_sequence(text: str, is_lhs: bool = False) -> list[RHSElement]:
    """Parse a sequence of symbols from LHS or RHS text."""
    elements: list[RHSElement] = []
    pos = 0
    text = text.strip()

    while pos < len(text):
        # Skip whitespace
        if text[pos] in " \t":
            pos += 1
            continue

        consumed, elem = _try_parse_element(text, pos, is_lhs)
        if elem is not None:
            if isinstance(elem, list):
                elements.extend(elem)
            else:
                elements.append(elem)
            pos += consumed
        else:
            # Skip unrecognized character
            pos += 1

    return elements


def _try_parse_element(text: str, pos: int, is_lhs: bool) -> tuple[int, RHSElement | list[RHSElement] | None]:
    """Try to parse a single element starting at pos. Returns (chars consumed, element)."""
    remaining = text[pos:]

    # Flag in RHS (e.g. /Ideas=20/)
    m = RE_FLAG.match(remaining)
    if m:
        # Skip flags in the symbol stream -- they're already parsed
        return m.end(), None

    # Lambda
    m = RE_LAMBDA.match(remaining)
    if m:
        return m.end(), Lambda()

    # Tempo inline: ||N|| (MusicXML import BPM marker)
    m = RE_TEMPO_INLINE.match(remaining)
    if m:
        bpm = m.group(1)
        return m.end(), SpecialFn(name="mm_inline", args=[bpm])

    # Special function
    m = RE_SPECIAL_FN.match(remaining)
    if m:
        return m.end(), SpecialFn(name=m.group(1), args=_split_args(m.group(2)))

    # Bare special function (no parens): _striated, _pitchcont, _pitchstep, _velcont, _retro, _destru, etc.
    m = RE_SPECIAL_FN_BARE.match(remaining)
    if m and not remaining[m.end():m.end()+1] == "(":
        # Must be followed by whitespace, end-of-string, or non-alnum
        if m.end() >= len(remaining) or not remaining[m.end()].isalnum():
            return m.end(), SpecialFn(name=m.group(1), args=[])

    # Homomorphism master (= ...) or (= ...)
    m = RE_HOMO_MASTER.match(remaining)
    if m:
        close_pos = _find_matching_paren(text, pos)
        if close_pos is not None:
            inner = text[pos + m.end():close_pos].strip()
            inner_elems = _parse_symbol_sequence(inner, is_lhs=False)
            return close_pos - pos + 1, HomoApply(kind=HomoApplyKind.MASTER, elements=inner_elems)

    # Homomorphism slave (: ...) or (: ...)
    m = RE_HOMO_SLAVE.match(remaining)
    if m:
        close_pos = _find_matching_paren(text, pos)
        if close_pos is not None:
            inner = text[pos + m.end():close_pos].strip()
            inner_elems = _parse_symbol_sequence(inner, is_lhs=False)
            return close_pos - pos + 1, HomoApply(kind=HomoApplyKind.SLAVE, elements=inner_elems)

    # Polymetric expression
    if remaining.startswith("{"):
        close_pos = _find_matching_brace(text, pos)
        if close_pos is not None:
            inner = text[pos + 1:close_pos]
            poly = _parse_polymetric(inner)
            return close_pos - pos + 1, poly

    # Variable |name|
    m = RE_VARIABLE.match(remaining)
    if m:
        return m.end(), Variable(name=m.group(1))

    # Wildcard ?N
    m = RE_WILDCARD.match(remaining)
    if m:
        return m.end(), Wildcard(index=int(m.group(1)))

    # Time signature (e.g., 4+4+4+4+4+4/4)
    m = RE_TIME_SIG.match(remaining)
    if m:
        return m.end(), TimeSig(text=m.group(1))

    # Annotation [...]
    if remaining.startswith("["):
        m = RE_ANNOTATION.match(remaining)
        if m:
            return m.end(), Annotation(text=m.group(1))

    # Homomorphism name (bare word like "mineur")
    m = RE_HOMO_NAME.match(remaining)
    if m and (pos + m.end() >= len(text) or not text[pos + m.end()].isalnum()):
        return m.end(), HomoApply(kind=HomoApplyKind.REF, elements=[NonTerminal(m.group(1))])

    # Tied notes: &note (tie end), note& (tie start)
    # Check for French tied notes first (e.g., &do4, fa4&)
    m = RE_TIED_NOTE_FR.match(remaining)
    if m:
        tie_start_prefix = m.group(1)  # & before note
        note_name = m.group(2)
        if m.group(3):
            note_name += m.group(3)  # accidental
        octave = int(m.group(4))
        tie_end_suffix = m.group(5)  # & after note

        if tie_start_prefix or tie_end_suffix:
            note = Note(name=note_name, octave=octave)
            # tie_start_prefix means this note ENDS a tie (&C4)
            # tie_end_suffix means this note STARTS a tie (C4&)
            is_start = bool(tie_end_suffix)
            return m.end(), Tie(note=note, is_start=is_start)
        # No tie markers, fall through to regular note parsing

    # Notes: French solfege (always unambiguous: do4, re5, sib4, etc.)
    m = RE_NOTE_FR.match(remaining)
    if m:
        name = m.group(1)
        if m.group(2):
            name += m.group(2)
        return m.end(), Note(name=name, octave=int(m.group(3)))

    # Notes: Indian sargam (unambiguous: sa6, re6, ga6, etc.)
    m = RE_NOTE_INDIAN.match(remaining)
    if m:
        return m.end(), Note(name=m.group(1), octave=int(m.group(2)))

    # Rest: dash
    if remaining[0] == "-" and (pos == 0 or text[pos - 1] in " \t{,"):
        next_pos = pos + 1
        if next_pos >= len(text) or text[next_pos] in " \t}\n,":
            return 1, Rest(determined=True)

    # Rest: underscore (standalone)
    if remaining[0] == "_" and (pos + 1 >= len(text) or not remaining[1:2].isalpha()):
        return 1, Rest(determined=False)

    # Anglo tied notes: &C4, C4&, &C#4, C#4& etc.
    # Must be checked BEFORE NonTerminals because C4& would otherwise match as NonTerminal "C4"
    m = RE_TIED_NOTE_ANGLO.match(remaining)
    if m:
        tie_start_prefix = m.group(1)  # & before note
        note_base = m.group(2)
        accidental = m.group(3) or ""
        octave = int(m.group(4))
        tie_end_suffix = m.group(5)  # & after note

        if tie_start_prefix or tie_end_suffix:
            note = Note(name=note_base + accidental, octave=octave)
            is_start = bool(tie_end_suffix)
            return m.end(), Tie(note=note, is_start=is_start)
        # No tie markers, fall through to NonTerminal parsing

    # Nonterminal (uppercase start): A8, B"8, Tihai, P4, etc.
    # Must come BEFORE Anglo notes since most BP3 grammars use solfege
    m = RE_NONTERMINAL.match(remaining)
    if m:
        name = m.group(1)
        if name not in ("ORD", "RND", "LIN", "SUB1", "SUB", "INIT"):
            return m.end(), NonTerminal(name=name)

    # Anglo notes: only unambiguous when they have accidentals (C#4, Bb3)
    # Plain A4, C8 etc. are caught as NonTerminals above
    m = RE_NOTE_ANGLO.match(remaining)
    if m and m.group(2):  # only match if accidental present
        name = m.group(1) + m.group(2)
        return m.end(), Note(name=name, octave=int(m.group(3)))

    # Plain terminals (lowercase identifiers like 'ek', 'do', 'tin')
    m = re.match(r"[a-z][a-z0-9_'\"]*", remaining)
    if m:
        word = m.group(0)
        if word != "lambda" and word not in ("mineur", "majeur", "trn"):
            return m.end(), NonTerminal(name=word)

    return 1, None


def _parse_polymetric(inner: str) -> Polymetric:
    """Parse the content inside { ... }."""
    # Split on commas, respecting nested braces
    parts = _split_poly_commas(inner)

    if len(parts) == 0:
        return Polymetric()

    # Check if first part is a number (tempo ratio)
    first = parts[0].strip()
    ratio = None
    if re.match(r"^\d+$", first):
        ratio = int(first)
        parts = parts[1:]

    voices = []
    for part in parts:
        elems = _parse_symbol_sequence(part.strip(), is_lhs=False)
        if elems:
            voices.append(elems)

    return Polymetric(tempo_ratio=ratio, voices=voices)


def _split_poly_commas(text: str) -> list[str]:
    """Split text on commas, respecting nested braces."""
    parts = []
    depth = 0
    current = []

    for ch in text:
        if ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current))
    return parts


def _find_matching_brace(text: str, open_pos: int) -> int | None:
    """Find the matching closing brace for '{' at open_pos."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _find_matching_paren(text: str, open_pos: int) -> int | None:
    """Find the matching closing paren for '(' at open_pos."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _split_args(args_str: str) -> list[str]:
    """Split function arguments on commas."""
    if not args_str.strip():
        return []
    return [a.strip() for a in args_str.split(",")]
