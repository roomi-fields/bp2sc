"""AST -> SuperCollider code emitter.

Traverses the BP3 AST and generates idiomatic SuperCollider Pattern code
(.scd files) using Pdef, Pbind, Pseq, Ppar, Prand, Pwrand.

See docs/bp3_to_sc_rules.md for the formal translation rules.

INVARIANTS:
  INV-1: No SC comments (//) inside array literals [...], Pseq([...]),
         Prand([...]), Pwrand([...]). Comments are emitted BEFORE or AFTER.
  INV-2: No bare MIDI integers in Pseq. Each must be wrapped in a Pbind.
  INV-3: All delimiters balanced.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from pathlib import Path

from bp2sc.ast_nodes import (
    BPFile, GrammarBlock, Rule, Weight, Flag,
    Note, Rest, NonTerminal, Variable, Wildcard,
    Polymetric, SpecialFn, Lambda, HomoApply, HomoApplyKind,
    TimeSig, Annotation, UndeterminedRest, QuotedSymbol,
    Tie, ContextMarker, GotoDirective,
    Comment, FileRef, InitDirective,
    RHSElement,
)
from bp2sc.note_converter import note_to_midi
from bp2sc.scale_map import resolve_scale
from bp2sc.alphabet_parser import (
    parse_alphabet_file, parse_alphabet_dir, AlphabetFile,
    get_homomorphism_mapping,
)
from bp2sc.sc_templates import (
    sc_header, sc_footer, sc_synthdef_default, sc_tempo,
    sc_pdef, sc_pbind, sc_pseq, sc_ppar, sc_prand, sc_pwrand,
    sc_pn, sc_rest, sc_comment, sc_play, sc_pseed, sc_pfindur,
    _sc_name, _indent,
)


@dataclass
class EmitWarning:
    """A diagnostic warning produced during SC emission."""
    category: str       # e.g. "unsupported_node", "flag_ignored"
    message: str        # human-readable description
    grammar: int | None = None   # grammar block index
    rule: int | None = None      # rule number within block

    def __str__(self) -> str:
        loc = ""
        if self.grammar is not None:
            loc += f"gram#{self.grammar}"
            if self.rule is not None:
                loc += f"[{self.rule}]"
            loc += " "
        return f"[{self.category}] {loc}{self.message}"


class SCEmitter:
    """Emit SuperCollider code from a BP3 AST."""

    def __init__(self, bp_file: BPFile, source_name: str = "unknown",
                 start_symbol: str = "S", verbose: bool = False,
                 seed: int | None = None,
                 alphabet_dir: str | None = None,
                 max_dur: float | None = None):
        self.bp = bp_file
        self.source_name = source_name
        self.start_symbol = start_symbol
        self.verbose = verbose
        self.seed = seed  # Deterministic seed for RND grammars
        self.alphabet_dir = alphabet_dir  # Directory containing -al.* files
        self.max_dur = max_dur  # Max duration in beats (anti-timeout)

        # Load alphabet files for terminal mapping and homomorphisms
        self._alphabet_files: dict[str, AlphabetFile] = {}
        self._alphabet_terminal_map: dict[str, int] = {}  # symbol -> MIDI
        self._load_alphabet_files()

        # Collect all rules indexed by LHS symbol name
        self._rules_by_lhs: dict[str, list[tuple[GrammarBlock, Rule]]] = {}
        self._collect_rules()

        # Track which symbols are defined as LHS (nonterminals with rules)
        self._defined_symbols: set[str] = set(self._rules_by_lhs.keys())

        # Track tempo
        self._tempo_bpm: float | None = None

        # Track which symbols appear in multiple blocks (need disambiguation)
        self._multi_block_symbols: set[str] = set()
        # Map symbol name -> sorted list of block indices that define it
        self._symbol_blocks: dict[str, list[int]] = {}
        self._detect_multi_block()

        # Current block being emitted (set during _emit_block)
        self._current_block: GrammarBlock | None = None

        # Pending repeat count for _repeat(N) implementation
        self._pending_repeat: int | None = None

        # Detect homomorphism labels (NonTerminals before HomoApply, no rules)
        self._homo_labels: set[str] = self._detect_homo_labels()

        # Collect terminal symbols (NonTerminals without production rules)
        # and assign them MIDI notes so they produce playable events
        self._terminal_midi: dict[str, int] = {}
        self._collect_terminals()

        # Diagnostic warnings collected during emission
        self.warnings: list[EmitWarning] = []
        self._current_rule: Rule | None = None

        # Velocity state for _rndvel support
        self._last_vel: int = 100  # Default MIDI velocity
        self._rndvel_range: int = 0  # Random velocity range (±N)

        # Timing state for _rndtime support
        self._rndtime_range: float = 0.0  # Percentage of timing variation (0-100)

        # Tie tracking for tied notes (MusicXML import)
        self._pending_tie_midi: int | None = None  # MIDI of note starting a tie

        # Pedal state tracking (MusicXML import)
        self._sustain_pedal: bool = False
        self._sostenuto_pedal: bool = False
        self._soft_pedal: bool = False

        # Current homomorphism context (set by REF, applied by MASTER/SLAVE)
        self._current_homo_label: str | None = None

        # Pre-scan for warnings on structure (before emit)
        self._prescan_warnings()

    def _load_alphabet_files(self) -> None:
        """Load alphabet files from the alphabet directory.

        Alphabet files (-al.*) contain:
        - Terminal symbol lists (simple alphabets)
        - Homomorphism definitions (note transformations)

        Also auto-detects alphabet files referenced in the BP file header.
        """
        if not self.alphabet_dir:
            # No alphabet directory specified
            return

        dir_path = Path(self.alphabet_dir)
        if not dir_path.exists():
            return

        # Load all alphabet files in the directory
        self._alphabet_files = parse_alphabet_dir(dir_path)

        # Build terminal -> MIDI mapping from alphabet files
        # Look for file references in the BP file headers to determine which alphabet to use
        for ref in self.bp.headers:
            if isinstance(ref, FileRef) and ref.prefix == "al":
                al_name = ref.name
                if al_name in self._alphabet_files:
                    af = self._alphabet_files[al_name]
                    # Map terminal names to sequential MIDI starting from 60
                    for i, term in enumerate(af.terminals):
                        if term not in self._alphabet_terminal_map:
                            # Try to parse as note name first
                            m = self._RE_ANGLO_NOTE.match(term)
                            if m:
                                self._alphabet_terminal_map[term] = note_to_midi(
                                    m.group(1) + (m.group(2) or ""),
                                    int(m.group(3))
                                )
                            else:
                                self._alphabet_terminal_map[term] = 60 + i

    def _collect_rules(self) -> None:
        """Index all rules by their LHS symbol name."""
        for block in self.bp.grammars:
            for rule in block.rules:
                for elem in rule.lhs:
                    name = self._symbol_name(elem)
                    if name:
                        if name not in self._rules_by_lhs:
                            self._rules_by_lhs[name] = []
                        self._rules_by_lhs[name].append((block, rule))

    def _detect_homo_labels(self) -> set[str]:
        """Detect homomorphism label names from HomoApply(kind=REF) nodes.

        The parser wraps homomorphism identifiers (e.g. 'mineur') in
        HomoApply(kind=REF, elements=[NonTerminal('mineur')]).
        These are not playable sounds — they tell BP3 which mapping
        from the -ho. file to use.
        """
        labels: set[str] = set()
        for block in self.bp.grammars:
            for rule in block.rules:
                for elem in rule.rhs:
                    if (isinstance(elem, HomoApply)
                            and elem.kind == HomoApplyKind.REF):
                        for inner in elem.elements:
                            if isinstance(inner, NonTerminal):
                                labels.add(inner.name)
        return labels

    # Regex for detecting Anglo note names among NonTerminals
    _RE_ANGLO_NOTE = re.compile(r'^([A-G])(#|b)?(\d)$')

    def _collect_terminals(self) -> None:
        """Find terminal symbols and assign MIDI notes for playback.

        Terminal symbols are NonTerminals that appear in RHS but have
        no production rules (e.g. 'ek', 'do', 'tin' in the Kathak
        tihai).  Each gets a unique MIDI note so the generated .scd
        actually produces sound.

        Anglo note names (C4, D#5, Bb3) that were parsed as NonTerminals
        (because the parser prioritizes NonTerminal over Anglo notes)
        are detected here and mapped to correct MIDI via note_to_midi().

        Homomorphism labels (detected by _detect_homo_labels) are
        excluded — they are not sounds.

        Alphabet mappings (from -al.* files) take precedence when loaded.
        """
        midi = 60  # start from middle C
        for block in self.bp.grammars:
            for rule in block.rules:
                for elem in self._walk_rhs_elements(rule.rhs):
                    if (isinstance(elem, NonTerminal)
                            and elem.name not in self._defined_symbols
                            and elem.name not in self._terminal_midi
                            and elem.name not in self._homo_labels):
                        # First check if alphabet mapping exists
                        if elem.name in self._alphabet_terminal_map:
                            self._terminal_midi[elem.name] = self._alphabet_terminal_map[elem.name]
                        # Then check if this is an Anglo note (C4, D#5, Bb3, etc.)
                        elif m := self._RE_ANGLO_NOTE.match(elem.name):
                            note_name = m.group(1) + (m.group(2) or "")
                            octave = int(m.group(3))
                            self._terminal_midi[elem.name] = note_to_midi(
                                note_name, octave
                            )
                        else:
                            self._terminal_midi[elem.name] = midi
                            midi += 1

    # ------------------------------------------------------------------
    # Warning / diagnostic infrastructure
    # ------------------------------------------------------------------

    def _warn(self, category: str, message: str) -> None:
        """Record a diagnostic warning with current location context."""
        gram = None
        rule_num = None
        if self._current_block is not None:
            gram = self._current_block.index
        if self._current_rule is not None:
            rule_num = self._current_rule.rule_num
        self.warnings.append(EmitWarning(category, message, gram, rule_num))

    def _prescan_warnings(self) -> None:
        """Pre-scan the AST for structural warnings before emission."""
        # Resource files referenced but not loaded
        for h in self.bp.headers:
            if isinstance(h, FileRef):
                self.warnings.append(EmitWarning(
                    "missing_resource",
                    f"-{h.prefix}.{h.name} referenced but not loaded",
                ))

    def warnings_summary(self) -> str:
        """Return a human-readable summary of all warnings."""
        if not self.warnings:
            return "No warnings."
        counts: Counter[str] = Counter(w.category for w in self.warnings)
        lines = [f"{len(self.warnings)} warning(s):"]
        for cat, n in counts.most_common():
            lines.append(f"  {cat}: {n}")
        return "\n".join(lines)

    def warnings_report(self) -> str:
        """Return a detailed listing of all warnings."""
        if not self.warnings:
            return "No warnings."
        lines = [f"=== {len(self.warnings)} warning(s) ==="]
        for w in self.warnings:
            lines.append(str(w))
        # Summary by category
        counts: Counter[str] = Counter(w.category for w in self.warnings)
        lines.append("")
        lines.append("--- Summary ---")
        for cat, n in counts.most_common():
            lines.append(f"  {cat}: {n}")
        return "\n".join(lines)

    def _walk_rhs_elements(self, elements: list) -> list:
        """Recursively yield all RHS elements (including nested ones).

        Skips contents of HomoApply(kind=REF) since those contain
        homomorphism label names, not playable sounds.
        """
        result = []
        for elem in elements:
            result.append(elem)
            if isinstance(elem, Polymetric):
                for voice in elem.voices:
                    result.extend(self._walk_rhs_elements(voice))
            elif isinstance(elem, HomoApply):
                if elem.kind != HomoApplyKind.REF:
                    result.extend(self._walk_rhs_elements(elem.elements))
        return result

    def _detect_multi_block(self) -> None:
        """Detect symbols defined in multiple grammar blocks."""
        block_for_symbol: dict[str, set[int]] = {}
        for block in self.bp.grammars:
            for rule in block.rules:
                name = self._lhs_name(rule)
                if name not in block_for_symbol:
                    block_for_symbol[name] = set()
                block_for_symbol[name].add(block.index or 0)
        for name, blocks in block_for_symbol.items():
            self._symbol_blocks[name] = sorted(blocks)
            if len(blocks) > 1:
                self._multi_block_symbols.add(name)

    def _pdef_name(self, name: str, block: GrammarBlock | None = None) -> str:
        """Get a unique Pdef name, adding block index suffix if ambiguous."""
        if name in self._multi_block_symbols and block is not None:
            return f"{name}_g{block.index}"
        return name

    def _resolve_rhs_ref(self, name: str) -> str:
        """Resolve an RHS reference to a multi-block symbol.

        When a symbol is defined in multiple blocks, the RHS reference
        must use the disambiguated name. Resolution order:
        1. If current block defines it, use current block's version
        2. Otherwise, use the first block that defines it
        """
        if name not in self._multi_block_symbols:
            return name
        blocks = self._symbol_blocks.get(name, [])
        if not blocks:
            return name
        if self._current_block is not None:
            cur_idx = self._current_block.index or 0
            if cur_idx in blocks:
                return f"{name}_g{cur_idx}"
        # Fall back to first block that defines it
        return f"{name}_g{blocks[0]}"

    def emit(self) -> str:
        """Generate complete .scd file content."""
        parts: list[str] = []

        # Header
        title = f"BP3 Grammar: {self.source_name}"
        parts.append(sc_header(title, self.source_name))

        # SynthDef
        parts.append(sc_synthdef_default())

        # Process preambles (tempo, etc.)
        for block in self.bp.grammars:
            for item in block.preamble:
                if isinstance(item, SpecialFn):
                    if item.name == "mm" and item.args:
                        try:
                            self._tempo_bpm = float(item.args[0])
                        except ValueError:
                            pass

        if self._tempo_bpm:
            parts.append(sc_tempo(self._tempo_bpm))
            parts.append("")

        # Header comments from file refs
        for h in self.bp.headers:
            if isinstance(h, FileRef):
                parts.append(sc_comment(f"BP3 reference: -{h.prefix}.{h.name}"))
            elif isinstance(h, InitDirective):
                parts.append(sc_comment(f"BP3 INIT: {h.text}"))
            elif isinstance(h, Comment) and h.text.strip():
                parts.append(sc_comment(h.text.strip()))
        parts.append("")

        # Emit flag variable initializations
        flag_init = self._emit_flag_init_block()
        if flag_init:
            parts.append(flag_init)

        # Emit Pdefs for terminal sound-objects (auto-mapped to MIDI)
        if self._terminal_midi:
            parts.append(sc_comment("--- Terminal sound-objects (customize to change sounds) ---"))
            for tname, midi in self._terminal_midi.items():
                sc_n = _sc_name(tname)
                parts.append(
                    f"Pdef(\\{sc_n}, Pbind("
                    f"\\instrument, \\bp2sc_default, "
                    f"\\midinote, Pseq([{midi}], 1), \\dur, 0.25));"
                )
            parts.append("")

        # Emit Pdefs for each grammar block
        for block in self.bp.grammars:
            parts.append(sc_comment(f"--- Subgrammar {block.index} ({block.mode}) ---"))
            if block.label:
                parts.append(sc_comment(f"Label: {block.label}"))
            parts.append("")
            parts.extend(self._emit_block(block))
            parts.append("")

        # Emit main play command
        if self.start_symbol in self._rules_by_lhs:
            parts.append(sc_comment("--- Play ---"))
            if self.max_dur is not None:
                # Wrap in Pfindur to prevent infinite loops (anti-timeout)
                sc_name = _sc_name(self.start_symbol)
                parts.append(f"Pfindur({self.max_dur}, Pdef(\\{sc_name})).play;")
            else:
                parts.append(sc_play(self.start_symbol))
        parts.append("")

        parts.append(sc_footer())
        return "\n".join(parts)

    def _emit_block(self, block: GrammarBlock) -> list[str]:
        """Emit all rules in a grammar block."""
        self._current_block = block
        parts: list[str] = []

        # Group rules by LHS symbol
        lhs_groups: dict[str, list[Rule]] = {}
        for rule in block.rules:
            name = self._lhs_name(rule)
            if name not in lhs_groups:
                lhs_groups[name] = []
            lhs_groups[name].append(rule)

        for lhs_name, rules in lhs_groups.items():
            pdef_name = self._pdef_name(lhs_name, block)
            pdef_code = self._emit_rules_for_symbol(pdef_name, rules, block)
            parts.append(pdef_code)
            parts.append("")

        return parts

    def _emit_rules_for_symbol(self, name: str, rules: list[Rule],
                                block: GrammarBlock) -> str:
        """Emit a Pdef for a symbol with one or more production rules."""
        # Filter out rules with weight 0 (disabled)
        active_rules = [r for r in rules if r.weight is None or r.weight.value > 0]
        if not active_rules:
            active_rules = rules  # keep all if all are disabled

        # Check if any rules have flags → use Prout-based flagged emission
        has_flags = any(r.flags for r in active_rules)
        if has_flags:
            return self._emit_flagged_rules(name, active_rules, block)

        # Single rule -> direct pattern
        if len(active_rules) == 1:
            pre_comments = []
            if active_rules[0].comment:
                pre_comments.append(active_rules[0].comment)

            pattern = self._emit_rhs(active_rules[0])
            comment = ""
            if pre_comments:
                comment = f"  {sc_comment(' | '.join(pre_comments))}\n"
            return comment + sc_pdef(name, pattern)

        # Multiple rules -> select based on grammar mode
        if block.mode in ("RND", "LIN"):
            return self._emit_weighted_choice(name, active_rules)
        else:
            # ORD / SUB1: sequential application
            patterns = [self._emit_rhs(r) for r in active_rules]
            if len(patterns) == 1:
                return sc_pdef(name, patterns[0])
            seq = sc_pseq(patterns)
            return sc_pdef(name, seq)

    def _emit_weighted_choice(self, name: str, rules: list[Rule]) -> str:
        """Emit a weighted random choice (Prand or Pwrand).

        If any rule has a weight decrement, delegates to
        _emit_decrement_choice() for Prout-based mutable weights.
        """
        has_decrement = any(
            r.weight and r.weight.decrement is not None for r in rules
        )
        if has_decrement:
            return self._emit_decrement_choice(name, rules)

        patterns = []
        weights = []
        has_weights = any(r.weight is not None for r in rules)

        for r in rules:
            pat = self._emit_rhs(r)
            patterns.append(pat)
            if r.weight:
                weights.append(str(r.weight.value))
            else:
                weights.append("1")

        if has_weights and any(w != "1" for w in weights):
            body = sc_pwrand(patterns, weights, "1")
        else:
            body = sc_prand(patterns, "1")

        # Wrap in Pseed for deterministic randomness if seed provided
        if self.seed is not None:
            body = sc_pseed(self.seed, body)

        return sc_pdef(name, body)

    def _emit_decrement_choice(self, name: str, rules: list[Rule]) -> str:
        """Emit a Prout-based Pdef with mutable weights for decrement rules.

        <50-12> means: initial weight 50, decrement by 12 after each use.
        Implemented as SC Prout with var declarations and weighted selection.
        """
        lines: list[str] = []
        lines.append(f"Pdef(\\{_sc_name(name)}, Prout({{ |ev|")

        # Declare weight variables
        for i, r in enumerate(rules):
            w = r.weight
            val = w.value if w else 1
            dec = w.decrement if w and w.decrement is not None else 0
            dec_comment = f"  // decrement: {dec}" if dec > 0 else ""
            lines.append(f"\tvar w{i} = {val};{dec_comment}")

        lines.append("\tinf.do {")
        lines.append(f"\t\tvar total = {' + '.join(f'w{i}' for i in range(len(rules)))};")

        # Build cumulative threshold checks
        # Weighted random selection: pick random in [0, total), check thresholds
        lines.append("\t\tvar r = total.rand;")

        cum = "0"
        for i, r in enumerate(rules):
            self._current_rule = r
            pattern = self._emit_rhs(r)
            if i == len(rules) - 1:
                # Last rule: no condition needed (else branch)
                lines.append("\t\t{")
            else:
                if i == 0:
                    lines.append(f"\t\tif(r < w0) {{")
                else:
                    cum_expr = " + ".join(f"w{j}" for j in range(i + 1))
                    lines.append(f"\t\t}} {{ if(r < ({cum_expr})) {{")

            lines.append(f"\t\t\t{pattern}.embedInStream(ev);")

            # Apply decrement if applicable
            w = r.weight
            if w and w.decrement is not None and w.decrement > 0:
                lines.append(f"\t\t\tw{i} = (w{i} - {w.decrement}).max(0);")

        # Close all if blocks
        # We have len(rules) - 1 nested if blocks to close
        for i in range(len(rules) - 1):
            lines.append("\t\t}")
        lines.append("\t}")
        lines.append("}));")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Flag-based conditional rules (Prout/embedInStream)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_flag_condition(flag: Flag) -> bool:
        """True if this flag is a guard condition (tested before -->).

        Conditions: bare name (/Ideas/), comparisons (>N, <N).
        Operations: assignments (=N), increments (+N), decrements (-N).
        """
        return flag.op in ("", ">", "<")

    @staticmethod
    def _is_flag_operation(flag: Flag) -> bool:
        """True if this flag is a side-effect operation (in RHS)."""
        return flag.op in ("=", "+", "-")

    def _emit_flag_condition(self, flag: Flag) -> str:
        """Emit a SC condition expression for a flag guard."""
        name = f"~{flag.name}"
        if flag.op == "":
            return f"({name} > 0)"
        elif flag.op == ">":
            return f"({name} > {flag.value})"
        elif flag.op == "<":
            return f"({name} < {flag.value})"
        return f"({name} > 0)"

    def _emit_flag_operation(self, flag: Flag) -> str:
        """Emit a SC statement for a flag operation."""
        name = f"~{flag.name}"
        if flag.op == "=":
            return f"{name} = {flag.value};"
        elif flag.op == "+":
            return f"{name} = {name} + {flag.value};"
        elif flag.op == "-":
            return f"{name} = {name} - {flag.value};"
        return ""

    def _collect_all_flag_names(self) -> set[str]:
        """Collect all unique flag names from all rules."""
        names: set[str] = set()
        for block in self.bp.grammars:
            for rule in block.rules:
                for f in rule.flags:
                    names.add(f.name)
        return names

    def _emit_flag_init_block(self) -> str:
        """Emit initialization for all flag variables.

        Scans for initial assignment flags (op='=') on the start symbol's
        first rule to set their initial values. All other flags default to 0.
        """
        names = sorted(self._collect_all_flag_names())
        if not names:
            return ""

        # Scan for initial values from start symbol's first rule
        init_values: dict[str, str] = {}
        if self.start_symbol in self._rules_by_lhs:
            pairs = self._rules_by_lhs[self.start_symbol]
            if pairs:
                first_rule = pairs[0][1]
                for f in first_rule.flags:
                    if f.op == "=" and f.value is not None:
                        init_values[f.name] = f.value

        lines = [sc_comment("--- Flag variables ---")]
        for n in names:
            val = init_values.get(n, "0")
            lines.append(f"~{n} = {val};")
        lines.append("")
        return "\n".join(lines)

    def _emit_flagged_rules(self, name: str, rules: list[Rule],
                            block: GrammarBlock) -> str:
        """Emit a Prout-based Pdef with if/else chains for flagged rules.

        Rules with conditions become if-guards; flag operations become
        assignments before or after the pattern is streamed.
        """
        # Separate flagged and unflagged rules
        flagged = [r for r in rules if r.flags]
        unflagged = [r for r in rules if not r.flags]

        lines: list[str] = []
        lines.append(f"Pdef(\\{_sc_name(name)}, Prout({{ |ev|")
        lines.append("\tinf.do {")

        first = True
        for r in flagged:
            self._current_rule = r
            conditions = [f for f in r.flags if self._is_flag_condition(f)]
            operations = [f for f in r.flags if self._is_flag_operation(f)]

            if conditions:
                cond_exprs = [self._emit_flag_condition(c) for c in conditions]
                cond_str = " and: { ".join(cond_exprs)
                if len(cond_exprs) > 1:
                    cond_str += " }"
                keyword = "if" if first else "} {"
                if first:
                    lines.append(f"\t\tif({cond_str}) {{")
                else:
                    lines.append(f"\t\t}} {{ if({cond_str}) {{")
                first = False
            else:
                # Operations-only rule (no guard) — emit unconditionally
                # but still within the Prout
                pass

            # Emit operations
            for op in operations:
                op_code = self._emit_flag_operation(op)
                if op_code:
                    lines.append(f"\t\t\t{op_code}")

            # Emit the rule pattern via embedInStream
            pattern = self._emit_rhs(r)
            lines.append(f"\t\t\t{pattern}.embedInStream(ev);")

        # Default fallback for unflagged rules
        if unflagged:
            if first:
                # No flagged rules had conditions — shouldn't happen, but handle
                for r in unflagged:
                    pattern = self._emit_rhs(r)
                    lines.append(f"\t\t{pattern}.embedInStream(ev);")
            else:
                lines.append("\t\t} {")
                if len(unflagged) == 1:
                    pattern = self._emit_rhs(unflagged[0])
                    lines.append(f"\t\t\t{pattern}.embedInStream(ev);")
                else:
                    # Multiple unflagged: use random selection
                    patterns = [self._emit_rhs(r) for r in unflagged]
                    inner = ", ".join(patterns)
                    lines.append(f"\t\t\t[{inner}].choose.embedInStream(ev);")
                lines.append("\t\t}")
        else:
            if not first:
                # Close last if block with a fallback silence
                lines.append("\t\t} {")
                lines.append("\t\t\tEvent.silent(0.25).embedInStream(ev);")
                lines.append("\t\t}")

        lines.append("\t}")
        lines.append("}));")
        lines.append("")
        return "\n".join(lines)

    def _strip_passthrough_rhs(self, rule: Rule) -> list[RHSElement]:
        """Strip pass-through context symbols from multi-symbol LHS rules.

        In BP3, rules like ``|o| |miny| --> |o1| |miny|`` have multi-symbol
        LHS.  Symbols beyond the first LHS element that appear unchanged in
        the RHS are *pass-through* context — they were consumed from the
        derivation string and preserved.  They must NOT be emitted as part
        of this rule's musical content, otherwise the Pdef overflows its
        time slot.

        Example::

            gram#3[47] |o| |miny| --> |o1| |miny|
                       ~~~  ~~~~~     ~~~~  ~~~~~
                       primary ctx    new   pass-through (strip)

        After stripping: RHS = [|o1|]  (only the replacement for |o|)
        """
        if len(rule.lhs) <= 1:
            return rule.rhs

        # Collect context symbol names from LHS[1:]
        context_names: list[str] = []
        for elem in rule.lhs[1:]:
            name = self._symbol_name(elem)
            if name:
                context_names.append(name)

        if not context_names:
            return rule.rhs

        # Remove matching symbols from the end of RHS
        filtered_rhs = list(rule.rhs)
        for ctx_name in reversed(context_names):
            for i in range(len(filtered_rhs) - 1, -1, -1):
                rhs_name = self._symbol_name(filtered_rhs[i])
                if rhs_name == ctx_name:
                    filtered_rhs.pop(i)
                    self._warn("context_stripped",
                               f"Pass-through '{ctx_name}' stripped "
                               f"from multi-symbol LHS rule")
                    break

        return filtered_rhs

    def _emit_rhs(self, rule: Rule) -> str:
        """Emit the RHS of a rule as a SC pattern expression.

        BP3 modifiers (_transpose, _vel, _pitchbend, etc.) are stateful:
        each modifier sets the state for all subsequent elements until
        changed again.  We walk elements left-to-right, snapshot the
        current modifier state for each real element, then group
        consecutive elements that share the same modifier state.

        INVARIANT: Comments are collected separately and emitted outside
        arrays to satisfy INV-1.
        """
        self._current_rule = rule
        elements = self._strip_passthrough_rhs(rule)

        if not elements:
            return sc_rest()

        # Check for lambda
        if len(elements) == 1 and isinstance(elements[0], Lambda):
            return sc_rest()

        # --- Phase 1: walk elements, track stateful modifiers ---
        current_mods: dict[str, str] = {}
        # Each item is (sc_code, mods_snapshot)
        # Comments are collected separately to satisfy INV-1
        items: list[tuple[str, dict[str, str]]] = []
        pre_comments: list[str] = []

        for elem in elements:
            result = self._emit_element(elem)
            if result is None:
                continue
            if isinstance(result, dict):
                # Multi-key modifier (e.g., _scale returns {scale, root})
                for key, val in result.items():
                    current_mods[key] = self._sanitize_sc_number(val)
            elif isinstance(result, tuple):
                # Modifier -- update running state
                key, val = result
                current_mods[key] = self._sanitize_sc_number(val)
            elif isinstance(result, str) and result.startswith("//"):
                # INV-1: collect comments separately, never put in arrays
                pre_comments.append(result)
            else:
                # Apply pending _repeat(N) wrapper
                if self._pending_repeat is not None:
                    result = sc_pn(result, str(self._pending_repeat))
                    self._pending_repeat = None
                items.append((result, dict(current_mods)))

        if not items:
            return sc_rest()

        # --- Phase 2: group consecutive real elements with same mods ---
        sc_parts: list[str] = []
        group_elems: list[str] = []
        group_mods: dict[str, str] | None = None

        def flush_group() -> None:
            nonlocal group_elems, group_mods
            if not group_elems:
                return
            sc_parts.append(
                self._wrap_element_group(group_elems, group_mods or {})
            )
            group_elems = []
            group_mods = None

        for code, mods in items:
            if group_mods is not None and mods == group_mods:
                group_elems.append(code)
            else:
                flush_group()
                group_elems = [code]
                group_mods = mods

        flush_group()

        # --- Phase 3: assemble final expression ---
        if not sc_parts:
            return sc_rest()
        if len(sc_parts) == 1:
            return sc_parts[0]

        return sc_pseq(sc_parts)

    def _wrap_element_group(self, elems: list[str],
                            mods: dict[str, str]) -> str:
        """Wrap a group of elements sharing the same modifier state.

        INV-2: MIDI integers are always wrapped in Pbind, never bare.
        """
        # Pre-process tied note markers
        processed_elems = []
        for e in elems:
            if e.startswith("TIE_START:"):
                # Tied note start: emit with extended legato (2.0 = sustain through next beat)
                midi = e.split(":")[1]
                processed_elems.append(
                    f"Pbind(\\instrument, \\bp2sc_default, "
                    f"\\midinote, Pseq([{midi}], 1), \\dur, 0.25, \\legato, 2.0)"
                )
            elif e == "TIE_END":
                # Tied note end: silent event (note already being held)
                processed_elems.append("Event.silent(0.25)")
            else:
                processed_elems.append(e)
        elems = processed_elems

        # Check if all non-Rest, non-Event.silent elements are MIDI note numbers
        non_rest = [e for e in elems
                    if not e.startswith("Rest") and not e.startswith("Event.silent")
                    and not e.startswith("Pbind")]
        all_midi = bool(non_rest) and all(
            self._is_midi_number(e) for e in non_rest
        )

        if all_midi and non_rest:
            # Pure MIDI notes -> Pbind with \midinote for playability (INV-2)
            seq = sc_pseq(elems)
            pairs: list[tuple[str, str]] = [("midinote", seq)]
            for k, v in mods.items():
                pairs.append((k, v))
            if not any(k == "dur" for k, _ in pairs):
                pairs.append(("dur", "0.25"))
            return sc_pbind(pairs)

        # Check if we have a mix of MIDI integers and non-MIDI elements
        has_midi = any(self._is_midi_number(e) for e in elems
                       if not e.startswith("Rest") and not e.startswith("Event.silent")
                       and not e.startswith("Pbind"))
        if has_midi:
            # Wrap bare MIDI integers in Pbind to satisfy INV-2
            # Use Pseq([n], 1) so Pbind produces exactly 1 event (not infinite)
            wrapped_elems = []
            for e in elems:
                if self._is_midi_number(e):
                    wrapped_elems.append(
                        f"Pbind(\\instrument, \\bp2sc_default, "
                        f"\\midinote, Pseq([{e}], 1), \\dur, 0.25)"
                    )
                else:
                    wrapped_elems.append(e)
            elems = wrapped_elems

        # Non-MIDI elements (Pdef refs, symbols, etc.)
        # In pattern-level Pseq, Rest() is not a valid event.
        elems = self._rest_for_pattern_ctx(elems)
        if len(elems) == 1:
            inner = elems[0]
        else:
            inner = sc_pseq(elems)

        if mods:
            mod_args = ", ".join(
                f"\\{k}, {v}" for k, v in mods.items()
            )
            return f"Pbindf({inner}, {mod_args})"
        return inner

    @staticmethod
    def _is_midi_number(s: str) -> bool:
        """Check if a string represents a valid MIDI note number (0-127)."""
        try:
            n = int(s)
            return 0 <= n <= 127
        except ValueError:
            return False

    @staticmethod
    def _sanitize_sc_number(val: str) -> str:
        """Strip leading + from positive numbers (invalid SC syntax)."""
        if val.startswith("+"):
            return val[1:]
        return val

    def _emit_element(self, elem: RHSElement) -> str | tuple[str, str] | dict[str, str] | None:
        """Emit a single RHS element.

        Returns:
            str: SC code (pattern expression or comment)
            tuple[str, str]: Single modifier (key, value)
            dict[str, str]: Multi-key modifier (e.g., scale + root)
            None: Element consumed (e.g., Lambda, consumed modifier state)
        """
        if isinstance(elem, Note):
            midi = note_to_midi(elem.name, elem.octave)
            return str(midi)

        if isinstance(elem, Rest):
            return sc_rest()

        if isinstance(elem, UndeterminedRest):
            self._warn("unsupported_node",
                       "UndeterminedRest '...' emitted as Rest()")
            return sc_rest()

        if isinstance(elem, NonTerminal):
            resolved = self._resolve_rhs_ref(elem.name)
            return f"Pdef(\\{_sc_name(resolved)})"

        if isinstance(elem, Variable):
            resolved = self._resolve_rhs_ref(elem.name)
            return f"Pdef(\\{_sc_name(resolved)})"

        if isinstance(elem, Wildcard):
            self._warn("approximation",
                       f"Wildcard ?{elem.index} emitted as Rest()")
            return sc_rest()

        if isinstance(elem, Polymetric):
            return self._emit_polymetric(elem)

        if isinstance(elem, SpecialFn):
            return self._emit_special_fn(elem)

        if isinstance(elem, Lambda):
            return None

        if isinstance(elem, HomoApply):
            return self._emit_homo(elem)

        if isinstance(elem, TimeSig):
            self._warn("time_sig_ignored",
                       f"Time signature '{elem.text}' not used for duration")
            return sc_comment(f"time sig: {elem.text}")

        if isinstance(elem, Annotation):
            return None

        if isinstance(elem, Tie):
            midi = note_to_midi(elem.note.name, elem.note.octave)
            if elem.is_start:
                # Note starting a tie (C4&): emit with extended legato
                # Track this note for potential tie end matching
                self._pending_tie_midi = midi
                # Return as special tied note marker that will be handled in _wrap_element_group
                return f"TIE_START:{midi}"
            else:
                # Note ending a tie (&C4): check if it matches pending tie
                if self._pending_tie_midi == midi:
                    self._pending_tie_midi = None
                    # This note is already being held, emit as silent
                    return "TIE_END"
                # No matching tie start, just emit the note normally
                return str(midi)

        if isinstance(elem, QuotedSymbol):
            self._warn("unsupported_node",
                       f"QuotedSymbol '{elem.text}' emitted as terminal")
            # Treat as terminal name
            if elem.text not in self._terminal_midi:
                self._terminal_midi[elem.text] = 60 + len(self._terminal_midi)
            return f"Pdef(\\{_sc_name(elem.text)})"

        if isinstance(elem, ContextMarker):
            self._warn("unsupported_node",
                       f"ContextMarker ({elem.kind}) skipped")
            return None

        if isinstance(elem, GotoDirective):
            self._warn("unsupported_fn",
                       f"_goto({elem.grammar},{elem.rule}) not implemented")
            return None

        # Unknown element type
        self._warn("unsupported_node",
                   f"Unknown element type {type(elem).__name__} skipped")
        return None

    @staticmethod
    def _rest_for_pattern_ctx(elems: list[str]) -> list[str]:
        """Replace bare Rest() with Event.silent(0.25) for pattern-level context.

        Rest() is only valid inside Pbind value patterns (e.g. \\midinote, Pseq([60, Rest()])).
        When Rest() appears alongside Pdef refs in a Pseq, it must be a proper
        rest Event, otherwise SC raises 'Message at not understood'.
        """
        return [
            "Event.silent(0.25)" if e == "Rest()" else e
            for e in elems
        ]

    def _emit_polymetric(self, poly: Polymetric) -> str:
        """Emit a polymetric expression."""
        if not poly.voices:
            return "Event.silent(0.25)"

        # Single voice with tempo ratio
        if len(poly.voices) == 1:
            voice_elems = self._emit_voice_elements(poly.voices[0])
            if not voice_elems:
                return "Event.silent(0.25)"
            # Check if all non-Rest elements are MIDI
            non_rest = [e for e in voice_elems if not e.startswith("Rest")]
            all_midi = bool(non_rest) and all(
                self._is_midi_number(e) for e in non_rest
            )
            if not all_midi:
                # Pattern context: fix Rest() and bare MIDI
                voice_elems = self._rest_for_pattern_ctx(voice_elems)
                voice_elems = self._ensure_no_bare_midi_in_seq(voice_elems)
            seq = sc_pseq(voice_elems)
            if poly.tempo_ratio is not None:
                if all_midi:
                    # Pure MIDI: wrap in Pbind for proper event generation
                    pairs: list[tuple[str, str]] = [("midinote", seq)]
                    pairs.append(("dur", "0.25"))
                    inner = sc_pbind(pairs)
                    return f"Pbindf({inner}, \\stretch, {poly.tempo_ratio}/{len(voice_elems)})"
                return f"Pbindf({seq}, \\stretch, {poly.tempo_ratio}/{len(voice_elems)})"
            return seq

        # Multiple voices -> Ppar
        voice_patterns = []
        for voice in poly.voices:
            elems = self._emit_voice_elements(voice)
            if elems:
                # Check if all elements are MIDI numbers
                non_rest = [e for e in elems if not e.startswith("Rest")]
                all_midi = bool(non_rest) and all(
                    self._is_midi_number(e) for e in non_rest
                )
                if len(elems) == 1 and not all_midi:
                    elems = self._rest_for_pattern_ctx(elems)
                    voice_patterns.append(elems[0])
                elif all_midi:
                    note_seq = sc_pseq(elems)
                    # Duration per note = total_duration / num_notes
                    ratio = poly.tempo_ratio or 1
                    dur_expr = f"{ratio} / {len(elems)}" if len(elems) > 1 else str(ratio)
                    voice_patterns.append(
                        sc_pbind([
                            ("midinote", note_seq),
                            ("dur", dur_expr)
                        ])
                    )
                else:
                    # Mixed: fix Rest(), wrap bare MIDI (INV-2) then Pseq
                    elems = self._rest_for_pattern_ctx(elems)
                    elems = self._ensure_no_bare_midi_in_seq(elems)
                    voice_patterns.append(sc_pseq(elems))
        if len(voice_patterns) == 1:
            return voice_patterns[0]
        return sc_ppar(voice_patterns)

    def _emit_voice_elements(self, voice: list[RHSElement]) -> list[str]:
        """Emit elements for a polymetric voice, filtering comments.

        Handles _retro and _rotate transformations when they appear at the
        start of a voice (e.g., {_retro A B C} or {_rotate(2) A B C}).
        """
        # Check for _retro or _rotate at the start
        do_retro = False
        rotate_amount = 0
        start_idx = 0

        for i, e in enumerate(voice):
            if isinstance(e, SpecialFn):
                if e.name.lower() == "retro":
                    do_retro = True
                    start_idx = i + 1
                elif e.name.lower() == "rotate" and e.args:
                    try:
                        rotate_amount = int(e.args[0])
                    except ValueError:
                        pass
                    start_idx = i + 1
                else:
                    # Other SpecialFn (modifier) - keep processing
                    break
            else:
                break

        # Emit elements starting from start_idx
        elems = []
        for e in voice[start_idx:]:
            result = self._emit_element(e)
            if result is not None and not isinstance(result, tuple):
                # INV-1: skip comments inside polymetric expressions
                if not result.startswith("//"):
                    elems.append(result)
            elif isinstance(result, tuple):
                # Modifiers inside voice - skip for now (applied elsewhere)
                pass

        # Apply transformations
        if do_retro and elems:
            elems = list(reversed(elems))
        if rotate_amount and elems:
            # Python rotate: negative = left, positive = right
            # BP3 _rotate(N) rotates N positions to the left
            n = rotate_amount % len(elems) if elems else 0
            elems = elems[n:] + elems[:n]

        return elems

    def _ensure_no_bare_midi_in_seq(self, elems: list[str]) -> list[str]:
        """Wrap bare MIDI integers in Pbind to satisfy INV-2.

        Only wraps if there is a mix of MIDI and non-MIDI elements.
        Pure MIDI groups are handled by _wrap_element_group.
        """
        has_midi = any(self._is_midi_number(e) for e in elems if not e.startswith("Rest"))
        has_non_midi = any(
            not self._is_midi_number(e) and not e.startswith("Rest")
            for e in elems
        )

        if has_midi and has_non_midi:
            wrapped = []
            for e in elems:
                if self._is_midi_number(e):
                    # Use Pseq([n], 1) so Pbind produces exactly 1 event
                    wrapped.append(
                        f"Pbind(\\instrument, \\bp2sc_default, "
                        f"\\midinote, Pseq([{e}], 1), \\dur, 0.25)"
                    )
                else:
                    wrapped.append(e)
            return wrapped
        return elems

    def _emit_special_fn(self, fn: SpecialFn) -> str | tuple[str, str] | None:
        """Emit a special function as SC code."""
        name = fn.name.lower()

        if name == "transpose" and fn.args:
            return ("ctranspose", fn.args[0])

        if name == "vel" and fn.args:
            try:
                vel = int(fn.args[0])
                self._last_vel = vel
                if self._rndvel_range:
                    lo = max(0, vel - self._rndvel_range)
                    hi = min(127, vel + self._rndvel_range)
                    return ("amp", f"Pwhite({round(lo/127, 3)}, {round(hi/127, 3)})")
                return ("amp", str(round(vel / 127, 3)))
            except ValueError:
                return ("amp", fn.args[0])

        if name == "mm" and fn.args:
            return sc_comment(f"tempo: {fn.args[0]} BPM")

        if name == "mm_inline" and fn.args:
            # Inline tempo marker ||N|| from MusicXML import
            # In RHS context, emit as stretch modifier relative to base tempo
            try:
                bpm = float(fn.args[0])
                # Base tempo is 60 BPM, so stretch = 60/bpm
                # e.g., ||120|| = stretch 0.5 (2x faster)
                base_tempo = 60.0
                stretch = round(base_tempo / bpm, 4)
                return ("stretch", str(stretch))
            except (ValueError, ZeroDivisionError):
                return sc_comment(f"tempo inline: {fn.args[0]} BPM")

        if name == "ins" and fn.args:
            # Sanitize instrument name for SC symbol
            arg = fn.args[0]
            sym = re.sub(r"[^a-zA-Z0-9_]", "_", arg.lower())
            if sym and sym[0].isdigit():
                sym = "inst_" + sym
            if not sym:
                sym = "bp2sc_default"
            return ("instrument", f"\\{sym}")

        if name == "pitchrange" and fn.args:
            self._warn("approximation",
                       f"_pitchrange({fn.args[0]}) emitted as comment")
            return sc_comment(f"pitchrange: {fn.args[0]}")

        if name == "pitchbend" and fn.args:
            return ("detune", fn.args[0])

        if name == "pitchcont":
            self._warn("approximation",
                       "_pitchcont emitted as comment")
            return sc_comment("pitchcont (continuous pitch)")

        if name == "striated":
            self._warn("approximation",
                       "_striated emitted as comment (time mode ignored)")
            return sc_comment("striated time mode")

        if name == "goto" and fn.args:
            self._warn("unsupported_fn",
                       f"_goto({', '.join(fn.args)}) not implemented")
            return sc_comment(f"TODO: _goto({', '.join(fn.args)})")

        if name == "failed" and fn.args:
            self._warn("unsupported_fn",
                       f"_failed({', '.join(fn.args)}) not implemented")
            return sc_comment(f"TODO: _failed({', '.join(fn.args)})")

        if name == "repeat" and fn.args:
            try:
                n = int(fn.args[0])
                self._pending_repeat = n
            except ValueError:
                self._pending_repeat = None
            return None  # consumed; wraps the next element

        if name == "destru":
            self._warn("approximation",
                       "_destru emitted as comment")
            return sc_comment("_destru (remove structural markers)")

        if name == "script" and fn.args:
            # Check for MIDI program pattern
            arg = fn.args[0]
            m = re.match(r"MIDI program (\d+)", arg)
            if m:
                return ("program", m.group(1))
            # Other _script types remain unsupported
            self._warn("unsupported_fn",
                       f"_script({' '.join(fn.args)}) not implemented")
            return sc_comment(f"TODO: _script({' '.join(fn.args)})")

        if name == "staccato" and fn.args:
            try:
                val = int(fn.args[0])
                return ("legato", str(round(val / 100, 3)))
            except ValueError:
                return ("legato", fn.args[0])

        if name == "legato" and fn.args:
            try:
                val = int(fn.args[0])
                return ("legato", str(round(val / 100, 3)))
            except ValueError:
                return ("legato", fn.args[0])

        # --- Phase 1: Easy special functions ---

        if name == "chan" and fn.args:
            return ("chan", fn.args[0])

        if name == "volume" and fn.args:
            try:
                vol = int(fn.args[0])
                self._last_vel = vol
                if self._rndvel_range:
                    lo = max(0, vol - self._rndvel_range)
                    hi = min(127, vol + self._rndvel_range)
                    return ("amp", f"Pwhite({round(lo/127, 3)}, {round(hi/127, 3)})")
                return ("amp", str(round(vol / 127, 3)))
            except ValueError:
                return ("amp", fn.args[0])

        if name == "mod" and fn.args:
            return ("detune", fn.args[0])

        if name == "rndvel" and fn.args:
            # Random velocity variation: _rndvel(N) adds ±N to velocity
            try:
                self._rndvel_range = int(fn.args[0])
            except ValueError:
                self._rndvel_range = 0
            # Recalculate amp with last velocity and new range
            if self._rndvel_range:
                lo = max(0, self._last_vel - self._rndvel_range)
                hi = min(127, self._last_vel + self._rndvel_range)
                return ("amp", f"Pwhite({round(lo/127, 3)}, {round(hi/127, 3)})")
            # Range is 0: reset to fixed velocity
            return ("amp", str(round(self._last_vel / 127, 3)))

        if name == "rndtime":
            # Random timing variation: _rndtime(N) adds ±N% variation to duration
            try:
                self._rndtime_range = float(fn.args[0]) if fn.args else 0.0
            except ValueError:
                self._rndtime_range = 0.0

            if self._rndtime_range > 0:
                # Variation of ±N% around base duration (0.25)
                base_dur = 0.25
                lo = base_dur * (1 - self._rndtime_range / 100)
                hi = base_dur * (1 + self._rndtime_range / 100)
                return ("dur", f"Pwhite({round(lo, 4)}, {round(hi, 4)})")
            # Range is 0: reset to fixed duration
            return ("dur", "0.25")

        if name == "rest":
            return sc_rest()

        if name == "velcont":
            return sc_comment("velcont (continuous velocity — SC handles natively)")

        if name == "press" and fn.args:
            # Aftertouch pressure (0-127) -> normalized 0-1
            try:
                val = int(fn.args[0])
                return ("aftertouch", str(round(val / 127, 3)))
            except ValueError:
                return ("aftertouch", fn.args[0])

        if name == "step" and fn.args:
            self._warn("approximation",
                       f"_step({fn.args[0]}) emitted as comment")
            return sc_comment(f"step: {fn.args[0]}")

        if name == "keyxpand" and fn.args:
            self._warn("approximation",
                       f"_keyxpand({fn.args[0]}) emitted as comment")
            return sc_comment(f"keyxpand: {fn.args[0]}")

        if name == "part":
            # Informational marker from MusicXML import - no warning needed
            if fn.args:
                return sc_comment(f"part: {fn.args[0]}")
            return None

        if name == "pitchstep":
            self._warn("approximation",
                       "_pitchstep emitted as comment")
            return sc_comment("pitchstep (discrete pitch)")

        # --- Phase 2: Medium special functions ---

        if name == "tempo" and fn.args:
            try:
                # _tempo(N) = relative multiplier: N× faster
                # _tempo(2) → stretch 0.5, _tempo(2/3) → stretch 1.5
                arg = fn.args[0]
                if "/" in arg:
                    parts = arg.split("/")
                    ratio = float(parts[0]) / float(parts[1])
                else:
                    ratio = float(arg)
                stretch = round(1.0 / ratio, 4)
                return ("stretch", str(stretch))
            except (ValueError, ZeroDivisionError):
                return ("stretch", fn.args[0])

        if name == "scale":
            # Resolve scale name to SC Scale/Tuning with root
            if len(fn.args) >= 2:
                result = resolve_scale(fn.args[0], fn.args[1])
            elif len(fn.args) == 1:
                result = resolve_scale(fn.args[0], "0")
            else:
                result = {"scale": "Scale.chromatic", "root": "0"}

            if result.pop("_unknown", None):
                self._warn("approximation",
                           f"_scale({', '.join(fn.args)}) unknown scale name, "
                           f"using Scale.chromatic")
            return result  # dict -> multi-modifier

        if name == "value" and len(fn.args) >= 2:
            key = fn.args[0]
            val = fn.args[1]
            return (key, val)

        if name == "retro":
            # Handled in _emit_voice_elements for polymetric context
            # Returns None to be consumed (like _repeat)
            return None

        if name == "rotate":
            # Handled in _emit_voice_elements for polymetric context
            # Returns None to be consumed (like _repeat)
            return None

        if name in ("switchon", "switchoff") and fn.args:
            self._warn("approximation",
                       f"_{name}({', '.join(fn.args)}) MIDI switch emitted as comment")
            return sc_comment(f"MIDI _{name}({', '.join(fn.args)})")

        # --- MusicXML Import: Pedal markers ---

        # Sustain pedal
        if name in ("sustainstart", "sustainstart_"):
            self._sustain_pedal = True
            return ("sustain", "1")

        if name in ("sustainstop", "sustainstop_"):
            self._sustain_pedal = False
            return ("sustain", "0")

        if name in ("sustainstopstart", "sustainstopstart_"):
            # Stop then start = remains at 1
            return ("sustain", "1")

        # Sostenuto pedal
        if name in ("sostenutostart", "sostenutostart_"):
            self._sostenuto_pedal = True
            return ("sostenuto", "1")

        if name in ("sostenutostop", "sostenutostop_"):
            self._sostenuto_pedal = False
            return ("sostenuto", "0")

        # Soft pedal (una corda)
        if name in ("softstart", "softstart_"):
            self._soft_pedal = True
            return ("softPedal", "1")

        if name in ("softstop", "softstop_"):
            self._soft_pedal = False
            return ("softPedal", "0")

        # --- MusicXML Import: Slur markers ---

        if name in ("legato_",):
            # Slur start: extended legato
            return ("legato", "1.5")

        if name in ("nolegato_",):
            # Slur end: shorter legato (slight staccato)
            return ("legato", "0.8")

        self._warn("unsupported_fn",
                   f"_{fn.name}({', '.join(fn.args)}) unknown, "
                   f"emitted as comment")
        return sc_comment(f"_{fn.name}({', '.join(fn.args)})")

    def _get_homo_mapping(self, label: str) -> dict[str, str] | None:
        """Get homomorphism mapping by label name.

        Searches alphabet files for a homomorphism section with the given name.
        Returns dict mapping source note names to target note names.
        """
        if not self._alphabet_files:
            return None
        return get_homomorphism_mapping(self._alphabet_files, label)

    def _resolve_symbol_to_midi(self, name: str, depth: int = 0) -> list[int] | None:
        """Resolve a symbol to its MIDI notes by inlining its rules.

        This is used for homomorphism application where we need actual MIDI
        notes, not Pdef references.

        Args:
            name: Symbol name to resolve
            depth: Recursion depth (to prevent infinite loops)

        Returns:
            List of MIDI notes, or None if symbol can't be resolved to notes
        """
        if depth > 10:
            return None  # Prevent infinite recursion

        # Check if it's a terminal with known MIDI
        if name in self._terminal_midi:
            return [self._terminal_midi[name]]

        # Check if it's a defined symbol with rules
        if name not in self._rules_by_lhs:
            return None

        rules = self._rules_by_lhs[name]
        if not rules:
            return None

        # Take the first rule (for deterministic resolution)
        _, rule = rules[0]
        midi_notes: list[int] = []

        for elem in rule.rhs:
            if isinstance(elem, Note):
                midi = note_to_midi(elem.name, elem.octave)
                midi_notes.append(midi)
            elif isinstance(elem, NonTerminal):
                # Recursively resolve
                sub_notes = self._resolve_symbol_to_midi(elem.name, depth + 1)
                if sub_notes:
                    midi_notes.extend(sub_notes)
            elif isinstance(elem, Variable):
                # Try to resolve variable too
                sub_notes = self._resolve_symbol_to_midi(elem.name, depth + 1)
                if sub_notes:
                    midi_notes.extend(sub_notes)
            elif isinstance(elem, Rest):
                pass  # Skip rests
            # Skip other element types (SpecialFn, etc.)

        return midi_notes if midi_notes else None

    def _apply_homo_to_midi(self, midi: int, mapping: dict[str, str]) -> int:
        """Apply homomorphism transformation to a MIDI note.

        The mapping is from note names (e.g., 'fa4') to note names (e.g., 're4').
        We convert MIDI to note name, apply transformation, convert back.
        """
        # Convert MIDI to French note name (most common in BP3 homos)
        french_names = ['do', 'dop', 're', 'rep', 'mi', 'fa',
                        'fap', 'sol', 'solp', 'la', 'lap', 'si']
        octave = (midi // 12) - 1  # MIDI 60 = do4 in French convention
        note_idx = midi % 12
        note_name = f"{french_names[note_idx]}{octave}"

        # Also try without 'p' suffix (alternate spellings)
        alt_names = {
            'dop': 'reb', 'rep': 'mib', 'fap': 'solb',
            'solp': 'lab', 'lap': 'sib'
        }

        # Check if note is in mapping
        target = mapping.get(note_name)
        if not target:
            # Try alternate name
            base = french_names[note_idx]
            if base in alt_names:
                alt_note = f"{alt_names[base]}{octave}"
                target = mapping.get(alt_note)

        if not target:
            return midi  # No transformation

        # Parse target note name back to MIDI
        target = target.strip()
        # Try French notation
        for i, fname in enumerate(french_names):
            if target.startswith(fname) and len(target) > len(fname):
                try:
                    t_oct = int(target[len(fname):])
                    return (t_oct + 1) * 12 + i
                except ValueError:
                    pass

        # Try alternate French (sib, mib, etc.)
        alt_to_idx = {'reb': 1, 'mib': 3, 'solb': 6, 'lab': 8, 'sib': 10}
        for alt, idx in alt_to_idx.items():
            if target.startswith(alt) and len(target) > len(alt):
                try:
                    t_oct = int(target[len(alt):])
                    return (t_oct + 1) * 12 + idx
                except ValueError:
                    pass

        return midi  # Couldn't parse target

    def _emit_homo(self, homo: HomoApply) -> str | None:
        """Emit a homomorphism application.

        - REF kind: homomorphism label (e.g. 'mineur') — set context for next MASTER/SLAVE
        - MASTER/SLAVE: emit the inner elements with homomorphism transformation applied
        The comment is emitted outside arrays (INV-1).
        """
        # REF = homomorphism identifier, sets context for subsequent MASTER/SLAVE
        if homo.kind == HomoApplyKind.REF:
            names = [self._symbol_name(e) or "?" for e in homo.elements]
            if names:
                self._current_homo_label = names[0]
                # Check if we have the mapping loaded
                mapping = self._get_homo_mapping(names[0])
                if mapping:
                    # We have the mapping, no warning needed
                    return None
                else:
                    self._warn("homo_not_expanded",
                               f"Homomorphism ref '{', '.join(names)}' skipped "
                               f"(-ho. file not loaded)")
            return None

        # MASTER/SLAVE: apply transformation if we have a current homo label
        mapping = None
        if self._current_homo_label:
            mapping = self._get_homo_mapping(self._current_homo_label)

        # If we have a mapping, try to resolve elements to MIDI and transform
        if mapping:
            midi_notes: list[int] = []
            can_transform = True

            for elem in homo.elements:
                if isinstance(elem, Note):
                    midi = note_to_midi(elem.name, elem.octave)
                    midi_notes.append(midi)
                elif isinstance(elem, (NonTerminal, Variable)):
                    # Try to inline this symbol's MIDI notes
                    resolved = self._resolve_symbol_to_midi(
                        elem.name if isinstance(elem, NonTerminal) else elem.name
                    )
                    if resolved:
                        midi_notes.extend(resolved)
                    else:
                        can_transform = False
                        break
                elif isinstance(elem, Rest):
                    pass  # Skip rests for now
                else:
                    can_transform = False
                    break

            if can_transform and midi_notes:
                # Apply homomorphism transformation
                transformed_midi = [
                    self._apply_homo_to_midi(m, mapping) for m in midi_notes
                ]
                # Clear the homo label (consumed)
                self._current_homo_label = None
                # Return as Pbind with transformed notes
                note_seq = sc_pseq([str(m) for m in transformed_midi])
                return sc_pbind([("midinote", note_seq), ("dur", "0.25")])

        # Fallback: emit as before (without transformation)
        inner = self._emit_voice_elements(homo.elements)

        # Clear the homo label after applying (it's consumed)
        self._current_homo_label = None

        # Fix Rest() for pattern context
        inner = self._rest_for_pattern_ctx(inner)

        if inner:
            if len(inner) == 1:
                return inner[0]
            return sc_pseq(inner)
        return "Event.silent(0.25)"

    def _lhs_name(self, rule: Rule) -> str:
        """Get the primary LHS symbol name for a rule."""
        for elem in rule.lhs:
            name = self._symbol_name(elem)
            if name:
                return name
        return f"gram{rule.grammar_num}_rule{rule.rule_num}"

    @staticmethod
    def _symbol_name(elem: RHSElement) -> str | None:
        """Get the name of a symbol element."""
        if isinstance(elem, NonTerminal):
            return elem.name
        if isinstance(elem, Variable):
            return elem.name
        return None

    @staticmethod
    def _format_flag(flag: Flag) -> str:
        """Format a flag for display."""
        if flag.op and flag.value is not None:
            return f"{flag.name}{flag.op}{flag.value}"
        return flag.name


def emit_scd(bp_file: BPFile, source_name: str = "unknown",
             start_symbol: str = "S", verbose: bool = False,
             seed: int | None = None,
             alphabet_dir: str | None = None,
             max_dur: float | None = None) -> str:
    """Convenience function to emit SC code from a parsed BP file."""
    emitter = SCEmitter(bp_file, source_name, start_symbol, verbose,
                        seed=seed, alphabet_dir=alphabet_dir, max_dur=max_dur)
    return emitter.emit()


def emit_scd_with_warnings(bp_file: BPFile, source_name: str = "unknown",
                           start_symbol: str = "S",
                           verbose: bool = False,
                           seed: int | None = None,
                           alphabet_dir: str | None = None,
                           max_dur: float | None = None
                           ) -> tuple[str, list[EmitWarning]]:
    """Emit SC code and return warnings for diagnostic purposes."""
    emitter = SCEmitter(bp_file, source_name, start_symbol, verbose,
                        seed=seed, alphabet_dir=alphabet_dir, max_dur=max_dur)
    scd = emitter.emit()
    return scd, emitter.warnings
