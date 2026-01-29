# BP3 AST Specification

> Formal specification of the Abstract Syntax Tree (AST) for bp2sc.
> Each node type is defined with its fields, types, invariants, and a BP3 example.

---

## Overview

The AST represents parsed BP3 grammar files as a typed tree structure. Each
production in `docs/bp3_ebnf.xml` maps to one or more AST node types defined
in `src/bp2sc/ast_nodes.py`.

```
BPFile
  +-- headers: list[Header]
  |     +-- Comment | FileRef | InitDirective
  +-- grammars: list[GrammarBlock]
        +-- mode, index, label, preamble
        +-- rules: list[Rule]
              +-- grammar_num, rule_num, weight, flags
              +-- lhs: list[LHSElement]
              +-- rhs: list[RHSElement]
```

---

## Type Aliases

```python
Header = Comment | FileRef | InitDirective

LHSElement = NonTerminal | Variable | Wildcard | ContextMarker

RHSElement = (
    Note | Rest | UndeterminedRest | Terminal | NonTerminal
    | Variable | Wildcard | Polymetric | SpecialFn | Lambda
    | HomoApply | TimeSig | Annotation | QuotedSymbol
    | Tie | ContextMarker | GotoDirective
)
```

---

## Header Nodes

### Comment

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Comment text (without the `//` prefix) |

**BP3:** `// This is a comment`
**AST:** `Comment(text="This is a comment")`

### FileRef

| Field | Type | Description |
|-------|------|-------------|
| `prefix` | `str` | File type: `"se"`, `"al"`, `"so"`, `"cs"` |
| `name` | `str` | Project name |

**Invariant:** `prefix in {"se", "al", "so", "cs"}`

**BP3:** `-se.EkDoTin`
**AST:** `FileRef(prefix="se", name="EkDoTin")`

**Note on file types** (per Bernard Bel):
- `-se.*`: Settings files (positional parameters, tempo, MIDI config)
- `-al.*`: Alphabet files — contain **both** terminal lists AND homomorphism
  mappings (BP3 renames `-ho.*` to `-al.*` on first read)
- `-so.*`: Sound-object definitions (BP3 renames `-mi.*` to `-so.*` as they
  handle more than just MIDI)
- `-cs.*`: Csound files (BP3 moves these to a Csound folder)

### InitDirective

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Raw text after `INIT:` |

**BP3:** `INIT: MIDI program 110`
**AST:** `InitDirective(text="MIDI program 110")`

---

## Weight

| Field | Type | Description |
|-------|------|-------------|
| `value` | `int` | Weight value (must be >= 0) |
| `decrement` | `int \| None` | Optional decrement for `<N-M>` format |

**Invariant:** `value >= 0`; if `decrement` is not None, `decrement > 0`

**BP3:** `<50-12>`
**AST:** `Weight(value=50, decrement=12)`

---

## Flag

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Flag identifier |
| `op` | `str` | Operator: `""`, `"="`, `"+"`, `"-"`, `">"`, `"<"` |
| `value` | `str \| None` | Operand (int or flag name) |

**Invariant:** If `op == ""`, then `value is None` (bare condition).

**BP3:** `/Ideas=20/` -> `Flag(name="Ideas", op="=", value="20")`
**BP3:** `/Ideas/` -> `Flag(name="Ideas", op="", value=None)`
**BP3:** `/NumR+1/` -> `Flag(name="NumR", op="+", value="1")`

---

## RHS Element Nodes

### Note

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Note name (e.g. `"do"`, `"sib"`, `"sa"`, `"C#"`) |
| `octave` | `int \| None` | Octave number |

**Invariant:** `name` matches one of: French solfege (`do`, `re`, `mi`, `fa`, `sol`, `la`, `si` + optional accidental), Indian sargam (`sa`, `re`, `ga`, `ma`, `pa`, `dha`, `ni`), or Anglo (`A`-`G` + optional accidental).

**BP3:** `sib4` -> `Note(name="sib", octave=4)` → MIDI 70 (French: `(4+1)*12+10`)
**BP3:** `F#3` -> `Note(name="F#", octave=3)` → MIDI 54 (Anglo: `(3+1)*12+6`)

**Octave conventions** (matching BP3 `Inits.c SetNoteNames`):
- French:  `MIDI = (octave + 1) * 12 + semitone` → `do4` = 60
- English: `MIDI = (octave + 1) * 12 + semitone` → `C4` = 60
- Indian:  `MIDI = (octave + 1) * 12 + semitone` → `sa4` = 60

**Note:** BP3 uses the same internal formula for all conventions. The naming
difference (French `do3` = English `C4`) is a display convention, not a
different MIDI mapping. See Bernard Bel's clarification.

**Parser note:** Anglo notes without accidentals (`C4`, `D4`) are parsed
as `NonTerminal` (not `Note`) because uppercase identifiers like `A8`, `B8`
are common nonterminal names in BP3. The emitter detects Anglo note patterns
among undefined NonTerminals and applies `note_to_midi()` instead of
sequential auto-mapping.

### Rest

| Field | Type | Description |
|-------|------|-------------|
| `determined` | `bool` | `True` for `-` (determined), `False` for `_` (undetermined) |

**BP3:** `-` -> `Rest(determined=True)`
**BP3:** `_` -> `Rest(determined=False)`

### UndeterminedRest

Represents `...` (undetermined continuation), distinct from `Rest` and `_`.

| Field | Type | Description |
|-------|------|-------------|
| (no fields) | | Marker node |

**BP3:** `...` -> `UndeterminedRest()`

### Terminal

Represents a sound-object defined in the alphabet (lowercase identifier
without production rules). Distinct from `NonTerminal`.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Terminal symbol name |

**Invariant:** `name` starts with lowercase letter; the symbol has no
production rules (it is a leaf in the grammar).

**BP3:** `ek` -> `Terminal(name="ek")` (when `ek` is in the alphabet)

**Note:** During parsing, lowercase identifiers are initially parsed as
`NonTerminal`. The distinction `Terminal` vs `NonTerminal` is resolved
during a post-parse phase by checking which symbols have production rules.
In the current implementation, this distinction is made at emit time.

### NonTerminal

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Symbol name |

**BP3:** `S` -> `NonTerminal(name="S")`
**BP3:** `Tihai` -> `NonTerminal(name="Tihai")`
**BP3:** `B"8` -> `NonTerminal(name='B"8')`

### Variable

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Variable name (without pipe delimiters) |

**BP3:** `|x|` -> `Variable(name="x")`
**BP3:** `|z31|` -> `Variable(name="z31")`

### Wildcard

| Field | Type | Description |
|-------|------|-------------|
| `index` | `int` | Wildcard number (0 for anonymous `?`) |

**Invariant:** `index >= 0`

**BP3:** `?1` -> `Wildcard(index=1)`
**BP3:** `?` -> `Wildcard(index=0)`

### Polymetric

| Field | Type | Description |
|-------|------|-------------|
| `tempo_ratio` | `int \| None` | Tempo ratio for single voice, or `None` |
| `voices` | `list[list[RHSElement]]` | One or more voice sequences |

**Invariant:** If `tempo_ratio` is not None, there is exactly one voice
(ratio mode). If `tempo_ratio` is None and `len(voices) > 1`, this is
parallel mode.

**BP3:** `{2, A B C}` -> `Polymetric(tempo_ratio=2, voices=[[NonTerminal("A"), NonTerminal("B"), NonTerminal("C")]])`
**BP3:** `{A B, C D}` -> `Polymetric(tempo_ratio=None, voices=[[NonTerminal("A"), NonTerminal("B")], [NonTerminal("C"), NonTerminal("D")]])`

### SpecialFn

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Function name (without leading `_`) |
| `args` | `list[str]` | Arguments as strings |

**BP3:** `_transpose(-2)` -> `SpecialFn(name="transpose", args=["-2"])`
**BP3:** `_striated` -> `SpecialFn(name="striated", args=[])`
**BP3:** `_mm(88.0000)` -> `SpecialFn(name="mm", args=["88.0000"])`

### Recognized SpecialFn Names

| Name | Category | SC Mapping | Args |
|------|----------|-----------|------|
| `transpose` | Modifier | `\ctranspose, N` | `[N]` |
| `vel` | Modifier | `\amp, N/127` or `Pwhite(lo, hi)` | `[N]` |
| `volume` | Modifier | `\amp, N/127` or `Pwhite(lo, hi)` | `[N]` |
| `rndvel` | Modifier | `\amp, Pwhite(lo, hi)` | `[N]` |
| `pitchbend` | Modifier | `\detune, N` | `[N]` |
| `mod` | Modifier | `\detune, N` | `[N]` |
| `staccato` | Modifier | `\legato, N/100` | `[N]` |
| `legato` | Modifier | `\legato, N/100` | `[N]` |
| `chan` | Modifier | `\chan, N` | `[N]` |
| `tempo` | Modifier | `\stretch, 1/N` | `[N]` or `[N/M]` |
| `value` | Modifier | `\key, val` | `[key, val]` |
| `ins` | Modifier | `\instrument, \name` | `[name]` |
| `press` | Modifier | `\aftertouch, N/127` | `[N]` |
| `scale` | Modifier | `\scale/\tuning, Scale.X, \root, N` | `[name, root?]` |
| `script` | Modifier/Unsup | `\program, N` (MIDI program) or comment | `[args...]` |
| `mm` | Preamble | `TempoClock.default.tempo = N/60` | `[BPM]` |
| `repeat` | Structural | `Pn(next_element, N)` | `[N]` |
| `rest` | Literal | `Rest()` | `[]` |
| `pitchrange` | Comment | `// pitchrange: N` | `[N]` |
| `pitchcont` | Comment | `// pitchcont` | `[]` |
| `pitchstep` | Comment | `// pitchstep` | `[]` |
| `velcont` | Comment | `// velcont` | `[]` |
| `step` | Comment | `// step: N` | `[N]` |
| `keyxpand` | Comment | `// keyxpand: N` | `[N]` |
| `part` | Comment | `// part: N` | `[N]` |
| `striated` | Comment | `// striated time mode` | `[]` |
| `destru` | Comment | `// _destru` | `[]` |
| `retro` | Comment | `// retro` | `[]` |
| `switchon` | Comment | `// MIDI _switchon(args)` | `[N, M]` |
| `switchoff` | Comment | `// MIDI _switchoff(args)` | `[N, M]` |
| `goto` | Unsupported | `// TODO: _goto(gram, rule)` | `[gram, rule]` |
| `failed` | Unsupported | `// TODO: _failed(gram, rule)` | `[gram, rule]` |
| `rotate` | Unsupported | `// TODO: _rotate(N)` | `[N]` |

### GotoDirective

A specialized form of `SpecialFn` that affects derivation flow.

| Field | Type | Description |
|-------|------|-------------|
| `grammar` | `int` | Target grammar number |
| `rule` | `int` | Target rule number |

**BP3:** `_goto(2,1)` -> `GotoDirective(grammar=2, rule=1)`

**Note:** In the current implementation, `_goto` is parsed as
`SpecialFn(name="goto", args=["2", "1"])`. The `GotoDirective`
node is an optional semantic refinement.

### Lambda

No fields. Represents an empty production.

**BP3:** `lambda` -> `Lambda()`

### HomoApply

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `HomoApplyKind` | `MASTER`, `SLAVE`, or `REF` |
| `elements` | `list[RHSElement]` | Inner elements |

**BP3:** `(= Tihai)` -> `HomoApply(kind=HomoApplyKind.MASTER, elements=[NonTerminal("Tihai")])`
**BP3:** `(: Tihai)` -> `HomoApply(kind=HomoApplyKind.SLAVE, elements=[NonTerminal("Tihai")])`

### HomoApplyKind (Enum)

| Value | Description | Emitted? |
|-------|-------------|----------|
| `MASTER` | Master homomorphism `(= ...)` — defines the pattern | Yes — inner elements emitted |
| `SLAVE` | Slave homomorphism `(: ...)` — replicates the master's pattern | Yes — inner elements emitted |
| `REF` | Homomorphism name reference (e.g., `mineur`) | **No** — skipped entirely |

**Note on REF:** Homomorphism labels like `mineur` are directives that tell
BP3 which mapping from the `-ho.` file to apply. They are not playable
sounds. The emitter skips `HomoApply(kind=REF)` nodes and excludes their
contents from terminal auto-mapping. Without this, `mineur` would be
auto-mapped to MIDI 60 and produce spurious notes in the output.

### TimeSig

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Raw time signature string |

**BP3:** `4+4+4+4+4+4/4` -> `TimeSig(text="4+4+4+4+4+4/4")`

### Annotation

Bracket annotation that carries metadata.

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Annotation content (without brackets) |

**BP3:** `[Variant]` -> `Annotation(text="Variant")`
**BP3:** `[?]` -> `Annotation(text="?")`
**BP3:** `[bug fixed here]` -> `Annotation(text="bug fixed here")`

### QuotedSymbol

Single-quoted symbol, distinct from Terminal or NonTerminal.

| Field | Type | Description |
|-------|------|-------------|
| `text` | `str` | Symbol content (without quotes) |

**BP3:** `'1'` -> `QuotedSymbol(text="1")`

### Tie

Represents tied notes (legato connection between notes).

| Field | Type | Description |
|-------|------|-------------|
| `note` | `Note` | The note being tied |
| `is_start` | `bool` | `True` for start `C4&`, `False` for end `&C4` |

**BP3:** `C4&` -> `Tie(note=Note(name="C", octave=4), is_start=True)`
**BP3:** `&C4` -> `Tie(note=Note(name="C", octave=4), is_start=False)`

### ContextMarker

Represents context-sensitive grammar markers.

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `str` | `"distant"`, `"open"`, `"close"`, `"wild"`, `"left"` |
| `symbol` | `RHSElement \| None` | The referenced symbol (for `distant`) |

**BP3:** `(|z13|)` -> `ContextMarker(kind="distant", symbol=Variable(name="z13"))`
**BP3:** `#({)` -> `ContextMarker(kind="open", symbol=None)`
**BP3:** `LEFT` -> `ContextMarker(kind="left", symbol=None)`

---

## Container Nodes

### Rule

| Field | Type | Description |
|-------|------|-------------|
| `grammar_num` | `int` | Grammar block number (from `gram#N`) |
| `rule_num` | `int` | Rule number within block (from `[M]`) |
| `weight` | `Weight \| None` | Optional weight |
| `flags` | `list[Flag]` | Flag conditions/operations |
| `lhs` | `list[RHSElement]` | Left-hand side symbols |
| `rhs` | `list[RHSElement]` | Right-hand side elements |
| `comment` | `str \| None` | Trailing comment |

**Invariant:** `len(lhs) >= 1` (at least one LHS symbol).

**Multi-symbol LHS:** When `len(lhs) > 1`, the rule is context-sensitive.
The first element is the primary symbol being rewritten; additional elements
are context that must be adjacent in the derivation string. Example:

```
gram#3[47] |o| |miny| --> |o1| |miny|
```

Produces: `Rule(lhs=[Variable("o"), Variable("miny")], rhs=[NonTerminal("o1"), Variable("miny")])`.
The `|miny|` on the RHS is a pass-through (preserving context). The emitter
strips pass-through symbols before emission to avoid temporal overflow
(see `docs/bp3_to_sc_rules.md` — Multi-Symbol LHS section).

### GrammarBlock

| Field | Type | Description |
|-------|------|-------------|
| `mode` | `str` | `"ORD"`, `"RND"`, `"LIN"`, `"SUB"`, `"SUB1"` |
| `index` | `int \| None` | Subgrammar number |
| `label` | `str \| None` | Optional label (e.g., `"Effects"`) |
| `preamble` | `list[SpecialFn]` | Pre-rule special functions |
| `rules` | `list[Rule]` | Production rules |

**Invariant:** `mode in {"ORD", "RND", "LIN", "SUB", "SUB1"}`

### BPFile

| Field | Type | Description |
|-------|------|-------------|
| `headers` | `list[Header]` | File headers |
| `grammars` | `list[GrammarBlock]` | Grammar blocks |

**Invariant:** `len(grammars) >= 1` for a valid grammar file.

---

## AST Construction Pipeline

```
BP3 text
  -> Line pre-processor (classify lines: header, mode, separator, preamble, rule)
  -> Lark parser (per rule line: tokenize and parse RHS/LHS)
  -> Lark Transformer (Lark tree -> AST nodes)
  -> BPFile AST
```

The pre-processor handles the line-oriented nature of BP3 files (each rule
is on its own line, separators delimit sub-grammars). Lark handles the
per-rule syntax (symbols, notes, polymetrics, special functions, etc.).

---

## Design Decisions

1. **Terminal vs NonTerminal distinction** is deferred to emit time rather
   than parse time. During parsing, lowercase identifiers are parsed as
   `NonTerminal` nodes. The emitter distinguishes terminals (symbols
   without production rules) from nonterminals by checking `_rules_by_lhs`.

2. **HomoApplyKind** uses an enum instead of raw strings to prevent typos
   and enable type checking.

3. **GotoDirective** is kept as a `SpecialFn` during parsing for simplicity.
   Semantic analysis can distinguish it if needed.

4. **Annotation** replaces `BracketComment` for bracket-delimited text
   (`[Variant]`, `[?]`) to clarify that these carry semantic metadata,
   not just comments.

5. **Preamble typing** uses `list[SpecialFn]` instead of `list[RHSElement]`
   since only special functions appear in preambles.

6. **Anglo note ambiguity** (`C4` vs NonTerminal `C4`) is resolved at emit
   time, not parse time. The parser uses NonTerminal for all uppercase
   identifiers (since `A8`, `B8`, `C8` are legitimate nonterminals in
   many BP3 grammars). The emitter then checks undefined NonTerminals
   against the Anglo note pattern `[A-G][#b]?\d` and uses `note_to_midi()`
   for those that match.

7. **HomoApply(REF) suppression** — REF nodes are silently skipped during
   emission. They represent homomorphism labels that BP3 uses to select
   a mapping from `-ho.` files. Since homomorphism expansion is not
   implemented, these nodes would produce incorrect sound if emitted.

8. **Multi-symbol LHS pass-through stripping** — When a rule has
   `len(lhs) > 1`, context symbols (LHS[1:]) that reappear in the RHS
   are pass-throughs, not additional musical content. The emitter strips
   them before emission to preserve correct time slot durations. Without
   this, `Pdef(\o)` would produce 1.0 beat instead of the expected 0.5.
