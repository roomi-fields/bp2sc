# Formalism Reference

> Design rationale and source references for the formal specification of the
> bp2sc transpiler (BP3 -> SuperCollider Patterns).

---

## 1. Introduction

The bp2sc transpiler uses a three-level formal approach:

1. **EBNF Grammar** (`docs/bp3_ebnf.xml`) -- normative syntax specification
2. **Typed AST** (`docs/bp3_ast_spec.md`, `src/bp2sc/ast_nodes.py`) -- intermediate representation
3. **Translation Rules** (`docs/bp3_to_sc_rules.md`) -- syntax-directed compilation

This formalism ensures:

- **Traceability**: every BP3 construct maps to an EBNF production, an AST
  node, and a translation rule.
- **Verifiability**: each layer can be tested independently (parser tests,
  AST validation, SC syntax checking).
- **Extensibility**: adding a new BP3 construct means adding a production,
  a node type, and a translation rule.

---

## 2. EBNF Grammar (`docs/bp3_ebnf.xml`)

### Format

W3C EBNF XML based on ISO 14977, with XML elements for `<production>`,
`<rule>`, and standard EBNF operators (`|`, `*`, `+`, `?`).

### Coverage

The grammar covers all BP3 constructs observed in the `bp3-ctests` test
suite (100+ grammar files), including:

- File structure (headers, separators, mode lines)
- Production rules (`gram#N[M] LHS --> RHS`)
- Weights (`<N>`, `<N-M>`)
- Flags (`/Name=V/`, `/Name+N/`, etc.)
- Notes (French solfege, Indian sargam, Anglo)
- Polymetric expressions (`{N, elems}`, `{v1, v2}`)
- Special functions (`_transpose()`, `_vel()`, `_mm()`, etc.)
- Homomorphisms (`(= expr)`, `(: expr)`)
- Wildcards, variables, ties, context markers, annotations

### Constructs Excluded from MVP

| Construct | Syntax | Reason |
|-----------|--------|--------|
| Full homomorphism expansion | `(= X)` with alphabet mapping | Requires alphabet file parsing |
| Context-sensitive execution | `(symbol)` distant context | Requires derivation engine |
| `_goto` execution | `_goto(gram, rule)` | Requires derivation engine |
| `_failed` handling | `_failed(gram, rule)` | Requires derivation engine |
| `_script` execution | `_script(path)` | External dependency |
| Wildcard resolution | `?1` matching | Requires derivation engine |
| Alphabet file parsing | `-al.Name` | Separate file format |
| Sound-object definitions | `<<name>>` | Requires sound engine |

### Sources

- BP3 documentation: https://bolprocessor.org/
- Pattern grammars: https://bolprocessor.org/pattern-grammars/
- BP3 tutorials: https://bolprocessor.org/tutorials/
- Produce all items: https://bolprocessor.org/produce-all-items/
- Grammar control: https://bolprocessor.org/grammar-control/
- Interactive improvisation: https://bolprocessor.org/interactive-improvisation/
- Shapes in rhythm: https://bolprocessor.org/shapes-in-rhythm/
- Polymetric structure: https://bolprocessor.org/polymetric-structure/
- Tied notes: https://bolprocessor.org/tied-notes/
- Live coding: https://bolprocessor.org/live-coding/
- Harm Visser's examples: https://bolprocessor.org/harm-vissers-examples/
- bp3-ctests repository: https://github.com/bolprocessor/bp3-ctests
- ISO 14977 (EBNF): https://www.iso.org/standard/26153.html

---

## 3. AST (Intermediate Representation) (`docs/bp3_ast_spec.md`)

### Design Choices

- **Python dataclasses** for immutable, typed node definitions
- **Type unions** (`Note | Rest | NonTerminal | ...`) for variant types
- **Visitor pattern** compatibility via `isinstance` checks
- Each EBNF production maps to one or more AST node types

### Relation to Grammar

| EBNF Production | AST Node(s) |
|-----------------|-------------|
| `bp_file` | `BPFile` |
| `grammar_section` | `GrammarBlock` |
| `rule_line` | `Rule` |
| `weight` | `Weight` |
| `flag` | `Flag` |
| `note` | `Note` |
| `rest` | `Rest` |
| `nonterminal` | `NonTerminal` |
| `terminal` | `NonTerminal` (distinguished at emit time; Anglo notes detected via `[A-G][#b]?\d` pattern) |
| `variable` | `Variable` |
| `wildcard` | `Wildcard` |
| `polymetric` | `Polymetric` |
| `special_fn` | `SpecialFn` |
| `lambda` | `Lambda` |
| `homo_apply` | `HomoApply` |
| `time_sig` | `TimeSig` |
| `annotation` | `Annotation` (was `BracketComment`) |
| `comment_line` | `Comment` |
| `file_ref` | `FileRef` |
| `init_directive` | `InitDirective` |

### Sources

- Plotkin, Structural Operational Semantics (2004):
  https://homepages.inf.ed.ac.uk/gdp/publications/sos_jlap.pdf

---

## 4. Translation Rules (`docs/bp3_to_sc_rules.md`)

### Paradigm

The translation uses **syntax-directed compilation**: each AST node type
has a deterministic mapping to SuperCollider code. The mapping is specified
as a set of named rules with input conditions and output templates.

### Key Invariants

1. **INV-1**: No SC comments (`//`) inside array literals
2. **INV-2**: No bare MIDI integers in Pseq (must be wrapped in Pbind)
3. **INV-3**: All delimiters balanced
4. **INV-4**: Terminal Pdefs use `Pseq([midi], 1)`, never bare scalars
5. **INV-5**: `Event.silent(0.25)` for rests in pattern-level context (not `Rest()`)
6. **INV-6**: `Event.silent(0)` for Pdef body when rule produces no sound (not `Rest()`)

### Note-to-MIDI Conversion

The conversion from note names to MIDI numbers follows BP3's internal
conventions as defined in `Inits.c SetNoteNames()`:

| Convention | Formula | Example | Source |
|-----------|---------|---------|--------|
| French    | `(octave + 1) * 12 + semitone` | `do4` = 60 | BP3 standard (same as English) |
| English   | `(octave + 1) * 12 + semitone` | `C4` = 60 | `Inits.c:459 octave--` |
| Indian    | `(octave + 1) * 12 + semitone` | `sa4` = 60 | `Inits.c:468 octave--` |

BP3's `C4key` setting (default 60) can shift all mappings by `(C4key - 60)`
semitones. This is not yet handled by the transpiler.

### Homomorphism Label Handling

Homomorphism identifiers (e.g., `mineur` in `|miny| --> mineur (= |y|)`)
are parsed as `HomoApply(kind=REF)` nodes. These are **not** playable
sounds — they select which mapping from the `-ho.` file to apply. The
emitter skips REF nodes entirely and excludes them from terminal
auto-mapping.

### Multi-Symbol LHS (Context-Sensitive Rules)

BP3 supports context-sensitive rules where the LHS has multiple symbols:

```
gram#3[47] |o| |miny| --> |o1| |miny|
```

The first LHS symbol (`|o|`) is rewritten; additional symbols (`|miny|`)
are context that must be adjacent. Context symbols reappearing in the RHS
are **pass-throughs** — they preserve the consumed context but produce no
additional sound. The emitter strips them to avoid temporal overflow
(e.g., `Pdef(\o)` producing 1.0 beat instead of the correct 0.5 beat).

### Stateful Modifiers

BP3 modifiers (`_transpose`, `_vel`, `_pitchbend`) are stateful: they
affect all subsequent elements until overridden. The translation algorithm
groups consecutive elements sharing the same modifier state and wraps each
group in a `Pbindf` with the appropriate key-value pairs.

### SC Pattern Classes Used

| SC Class | Purpose | BP3 Origin |
|----------|---------|------------|
| `Pdef` | Named pattern definition | Each grammar rule LHS |
| `Pbind` | Event pattern with key-value pairs | Note groups, terminals |
| `Pseq` | Sequential pattern | ORD mode, multi-element RHS |
| `Prand` | Random selection (uniform) | RND/LIN mode (no weights) |
| `Pwrand` | Weighted random selection | RND/LIN mode (with weights) |
| `Ppar` | Parallel patterns | Multi-voice polymetric |
| `Pbindf` | Override keys in existing pattern | Modifiers, polymetric stretch |
| `Pn` | Repeat wrapper | `_repeat(N)` function |
| `Prout` | Routine-based pattern | Flag conditions, weight decrements |
| `Rest` | Silence event | Rest, Lambda, Wildcard |

### Sources (SuperCollider)

- Streams, Patterns, Events tutorials:
  - Part 1: https://doc.sccode.org/Tutorials/Streams-Patterns-Events1.html
  - Part 2: https://doc.sccode.org/Tutorials/Streams-Patterns-Events2.html
  - Part 3: https://doc.sccode.org/Tutorials/Streams-Patterns-Events3.html
  - Part 4: https://doc.sccode.org/Tutorials/Streams-Patterns-Events4.html
  - Part 5: https://doc.sccode.org/Tutorials/Streams-Patterns-Events5.html
  - Part 6: https://doc.sccode.org/Tutorials/Streams-Patterns-Events6.html
  - Part 7: https://doc.sccode.org/Tutorials/Streams-Patterns-Events7.html
- Pdef: https://doc.sccode.org/Classes/Pdef.html
- Pbind: https://doc.sccode.org/Classes/Pbind.html
- Ppar: https://doc.sccode.org/Classes/Ppar.html
- EventPatternProxy: https://doc.sccode.org/Classes/EventPatternProxy.html
- PatternProxy: https://doc.sccode.org/Classes/PatternProxy.html
- Pbindef: https://doc.sccode.org/Classes/Pbindef.html

---

### Flag System Architecture

BP3 flags are runtime state variables that control conditional rule selection.
The transpiler maps them to SuperCollider environment variables and `Prout` patterns.

**Classification:**
- **Conditions** (`op=""`, `>`, `<`): Guard tests before `-->`. Example: `/Ideas/` → `(~Ideas > 0)`
- **Operations** (`op="="`, `+`, `-`): Side effects in RHS. Example: `/Ideas-1/` → `~Ideas = ~Ideas - 1;`

**Initialization:**
All flag names are scanned at emit time. Flags with `=` operations on the start
symbol's first rule set initial values; all others default to 0:

```supercollider
~Ideas = 20;  ~Notes = 32;  ~NumR = 0;
```

**Conditional Rule Selection:**
Rules with flag conditions are wrapped in `Prout` with `if/else` chains instead of
`Prand`/`Pwrand`. Each branch calls `.embedInStream(ev)` to stream events:

```supercollider
Pdef(\S, Prout({ |ev|
    inf.do {
        if((~Ideas > 0)) {
            ~Ideas = ~Ideas - 1;
            pattern.embedInStream(ev);
        } {
            fallbackPattern.embedInStream(ev);
        }
    }
}));
```

### Weight Decrement Architecture

BP3 weight decrements (`<50-12>`) represent weights that decrease after each use,
modeling exhaustion or preference decay. The transpiler maps these to `Prout` with
mutable variables:

```supercollider
Pdef(\S, Prout({ |ev|
    var w0 = 50;  // decrement: 12
    var w1 = 1;
    inf.do {
        var total = w0 + w1;
        var r = total.rand;
        if(r < w0) {
            rule0Pattern.embedInStream(ev);
            w0 = (w0 - 12).max(0);
        } {
            rule1Pattern.embedInStream(ev);
        }
    }
}));
```

The `.max(0)` ensures weights never go negative, maintaining valid probability
distributions.

### Scale Mapping System

BP3's `_scale()` function supports multiple scale/tuning conventions. The
transpiler uses a data-driven approach via `src/bp2sc/scale_map.py`:

**Resolution Algorithm:**
1. **Key-Quality Scales** (regex): `Cmaj`, `Dmin`, `F#min` → `Scale.major/minor` + root
2. **Tunings** (lookup): `just intonation`, `piano`, `meantone_classic` → `Tuning.X`
3. **Ragas** (lookup): `todi_ka_4`, `grama` → `Scale.todi`, `Scale.chromatic`
4. **Fallback**: Unknown names → `Scale.chromatic` + approximation warning

**Root Parsing:**
- Anglo: `C4`, `D#5`, `Bb3` → semitone offset (C=0, D=2, A=9)
- French: `dop4`, `rep4` → semitone offset
- Indian: `sa_4`, `ri_4`, `pa_4` → semitone offset
- Numeric: `0-11` direct offset

**Configuration:**
The mapping data lives in `src/bp2sc/data/scale_map.json`, allowing users to
add custom tunings/ragas without modifying Python code.

### Resource File Parsers

Two additional parsers are available for BP3 resource files:

**Alphabet Parser** (`src/bp2sc/alphabet_parser.py`):
- Parses `-al.*` files containing terminal alphabets and homomorphism definitions
- Extracts homomorphism mappings (e.g., `mineur: la4 --> fa4`)
- Returns `AlphabetFile` with `terminals` list and `homomorphisms` dict

**Settings Parser** (`src/bp2sc/settings_parser.py`):
- Parses `-se.*` JSON files containing project settings
- Extracts: `NoteConvention`, `Pclock/Qclock` (tempo), `DeftVelocity`, `C4key`, `A4freq`
- Returns `BP3Settings` with `tempo_bpm` property calculated from Pclock/Qclock

These parsers are available for manual use but not yet integrated into the main
emission pipeline.

---

## 5. Constructs Not Supported in MVP

| Construct | Syntax | Exclusion Reason | Future Direction |
|-----------|--------|-----------------|-----------------|
| Full homomorphism | `(= X)` + alphabet | Requires `-al.` file parser | Parse alphabet files, build mapping table |
| Context-sensitive rules | `(|z13|)`, `#({)`, `LEFT` | Requires derivation engine | Implement context matching in pattern selection |
| `_goto` | `_goto(gram, rule)` | Affects derivation flow | Could map to Pdef switching |
| `_failed` | `_failed(gram, rule)` | Error handling in derivation | No direct SC equivalent |
| `_script` (non-MIDI) | `_script(Beep)` | External script execution | Could invoke SC scripts |
| Wildcard resolution | `?1` matching | Pattern matching in derivation | Could pre-compute substitutions |
| Tied notes | `C4&`, `&C4` | Sustained notes across events | Map to `\legato > 1` or `\sustain` |
| Time patterns | `TIMEPATTERNS:` | Custom time grids | Map to `Ptpar` or custom tempo |

**Note:** `_script(MIDI program N)` is now supported and maps to `\program, N`.
