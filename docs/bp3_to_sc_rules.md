# BP3 to SuperCollider Translation Rules

> Formal specification of the translation from BP3 AST nodes to SuperCollider
> Pattern code. Each rule maps an AST node (or pattern of nodes) to SC output.

---

## Invariants

### INV-1: No comments inside SC literals

The generated SC code MUST NEVER contain `//` comments inside array literals
`[...]`, `Pseq([...])`, `Prand([...])`, `Pwrand([...])`, or any multi-line
expression. Comments are emitted BEFORE or AFTER the containing block.

**Rationale:** SC comments inside arrays cause syntax errors at `sclang`
compile time.

### INV-2: No bare MIDI integers in Pseq

Every MIDI note number appearing in a `Pseq` or `Prand` MUST be wrapped in a
`Pbind` that provides `\instrument`, `\midinote`, and `\dur` keys.

**Rationale:** A bare integer in a `Pseq` is not a playable event in SC.
It must be wrapped in a `Pbind` to produce sound.

### INV-3: Balanced delimiters

All generated `(`, `)`, `[`, `]`, `{`, `}` MUST be balanced.

### INV-4: Finite terminal Pdefs via Pseq

Terminal sound-object Pdef definitions MUST wrap `\midinote` values in
`Pseq([midi], 1)`, never as bare scalars.

**Rationale:** `Pbind(\midinote, 60, \dur, 0.25)` with scalar values
produces an **infinite** stream of identical events in SC. The Pbind
repeats forever because scalar values never end. Using
`Pseq([60], 1)` ensures the Pbind produces exactly one event and stops,
allowing Pseq-of-Pdefs to advance to the next pattern.

### INV-5: Event.silent in pattern-level context

When a rest appears alongside `Pdef` references in a `Pseq` (i.e., in
pattern-level context where each element is a playable Event source),
it MUST be emitted as `Event.silent(0.25)`, NOT as `Rest()`.

**Rationale:** `Rest()` is a **value wrapper**, not an Event. In
pattern-level context (`Pseq([Pdef(\a), Rest(), Pdef(\b)])`), SC
attempts to query `Rest()[\midinote]` which fails with "Message 'at'
not understood". `Event.silent(dur)` creates a proper rest Event
`(dur: Rest(dur))` that works correctly in Pseq and responds to
`Pbindf` merging.

**Exception:** `Rest()` IS valid inside `Pbind` value patterns
(e.g., `Pbind(\midinote, Pseq([60, Rest(), 62]))`) where it acts as
a value marker, not a standalone Event.

### INV-6: No Rest() as Pdef body

When a rule produces no sound (e.g., rules consisting only of unsupported
special functions, or `lambda`), the Pdef body MUST be `Event.silent(0)`,
NOT `Rest()`.

**Rationale:** `Pdef(\name, Rest())` fails with "Message 'put' not
understood" because `Pdef` expects a **Pattern** (something that responds
to `asStream`), but `Rest()` is an **Event value**. `Event.silent(0)`
creates a zero-duration silent event that IS a valid Pattern.

---

## Translation Rules

### RULE file_structure

```
INPUT:  BPFile(headers, grammars)
OUTPUT:
  // header comments
  (
    SynthDef(\bp2sc_default, { ... }).add;
    TempoClock.default.tempo = BPM / 60;    // if _mm() in preamble
    // file reference comments
    // terminal Pdef definitions
    // grammar block rules
    Pdef(\StartSymbol).play;
  )
```

### RULE grammar_block_ord

```
INPUT:  GrammarBlock(mode="ORD", rules=[r1, r2, ...])
        where all rules share the same LHS symbol
OUTPUT: Pdef(\lhs, Pseq([emit(r1), emit(r2), ...], 1));
NOTES:  ORD = ordered/sequential application.
        If only 1 rule, omit the Pseq wrapper.
```

### RULE grammar_block_rnd_unweighted

```
INPUT:  GrammarBlock(mode="RND" | "LIN", rules=[r1, r2, ...])
        where no rule has a weight
OUTPUT: Pdef(\lhs, Prand([emit(r1), emit(r2), ...], 1));
NOTES:  RND and LIN both use random selection at the pattern level.
        LIN's left-to-right semantics are a property of the BP3 derivation
        process, not the resulting sound pattern.
```

### RULE grammar_block_rnd_weighted

```
INPUT:  GrammarBlock(mode="RND" | "LIN", rules=[r1, r2, ...])
        where at least one rule has a Weight
OUTPUT: Pdef(\lhs, Pwrand([emit(r1), ...], [w1, w2, ...].normalizeSum, 1));
NOTES:  Rules without explicit weights default to weight 1.
```

### RULE note_in_group

```
INPUT:  Note(name, octave) as part of a group of consecutive notes
OUTPUT: Pbind(
          \instrument, \bp2sc_default,
          \midinote, Pseq([midi1, midi2, ...], 1),
          \dur, 0.25
        )
NOTES:  Consecutive MIDI notes are grouped into a single Pbind.
        MIDI conversion via note_to_midi(name, octave).
        Satisfies INV-2.

        Octave conventions (matching BP3 Inits.c SetNoteNames):
        - French:  MIDI = (octave + 1) * 12 + semitone → do4 = 60
        - English: MIDI = (octave + 1) * 12 + semitone → C4 = 60
        - Indian:  MIDI = (octave + 1) * 12 + semitone → sa4 = 60

        BP3 uses the same internal formula for all conventions.
        The naming difference (French do3 = English C4) is a display
        convention, not a different MIDI mapping (per Bernard Bel).
```

### RULE note_single

```
INPUT:  Note(name, octave) as sole element
OUTPUT: Pbind(
          \instrument, \bp2sc_default,
          \midinote, Pseq([<midi>], 1),
          \dur, 0.25
        )
NOTES:  Even single notes use Pseq([...], 1) per INV-4 to guarantee
        finite event production.
```

### RULE rest

```
INPUT:  Rest() in value-level context (inside Pbind value pattern)
OUTPUT: Rest()

INPUT:  Rest() in pattern-level context (alongside Pdef refs in Pseq)
OUTPUT: Event.silent(0.25)
NOTES:  See INV-5. Pattern-level context = the rest appears in a Pseq
        where sibling elements are Pdef references or other Event
        sources (not MIDI values inside a Pbind).
```

### RULE undetermined_rest

```
INPUT:  UndeterminedRest()
OUTPUT: Rest()
NOTES:  Treated same as Rest for SC output. Future: could be mapped to
        a different duration or behavior.
```

### RULE nonterminal_with_rules

```
INPUT:  NonTerminal(name) where name has production rules
OUTPUT: Pdef(\name)
NOTES:  Reference to the Pdef defined by the symbol's rules.
```

### RULE terminal_sound_object

```
INPUT:  NonTerminal(name) where name has NO production rules
OUTPUT: Pdef(\name)
PRECONDITION: A Pdef(\name, Pbind(\instrument, \bp2sc_default,
              \midinote, Pseq([<midi>], 1), \dur, 0.25)) has been
              emitted in the terminal definitions section.
NOTES:  Terminals are auto-assigned MIDI notes starting from 60 (middle C).
        The midinote MUST be wrapped in Pseq([...], 1) per INV-4.
```

### RULE variable

```
INPUT:  Variable(name)
OUTPUT: Pdef(\name)
NOTES:  Variables are treated as Pdef references, same as nonterminals.
```

### RULE lambda

```
INPUT:  Lambda()
OUTPUT: (omitted from pattern)
NOTES:  Empty production = no sound. If lambda is the only element,
        the rule emits Rest().
```

### RULE polymetric_ratio

```
INPUT:  Polymetric(tempo_ratio=N, voices=[[elems]])
        where N is not None and there is exactly 1 voice
OUTPUT: Pbindf(Pseq([emit(elems)], 1), \stretch, N/len(elems))
NOTES:  The stretch factor compresses/expands the voice to fit
        N beats regardless of the number of elements.
```

### RULE polymetric_parallel

```
INPUT:  Polymetric(tempo_ratio=None, voices=[[v1], [v2], ...])
        where there are 2+ voices
OUTPUT: Ppar([emit(v1), emit(v2), ...])
NOTES:  Each voice plays simultaneously.
```

### RULE wildcard

```
INPUT:  Wildcard(index)
OUTPUT: Rest()
NOTES:  Wildcards are not compilable in the MVP.
        A comment is emitted BEFORE the containing pattern (not inside):
        // wildcard ?N (not compiled)
```

### RULE annotation

```
INPUT:  Annotation(text)
OUTPUT: (omitted from pattern, comment emitted before pattern)
NOTES:  Annotations like [Variant], [?] are emitted as SC comments
        BEFORE the Pdef block, never inside arrays. Satisfies INV-1.
```

### RULE time_sig

```
INPUT:  TimeSig(text)
OUTPUT: (omitted from pattern, comment emitted before pattern)
NOTES:  Time signature is informational. Emitted as:
        // time sig: 4+4+4+4+4+4/4
        BEFORE the Pdef block, never inside arrays. Satisfies INV-1.
```

### RULE homo_master

```
INPUT:  HomoApply(kind=MASTER, elements=[elems])
OUTPUT: emit(elems)
NOTES:  The master defines the canonical pattern. Its elements are
        emitted directly (each element produces its Pdef reference
        or note pattern).
        A comment is emitted BEFORE the containing Pdef:
        // homo master: <element names>
```

### RULE homo_slave

```
INPUT:  HomoApply(kind=SLAVE, elements=[elems])
OUTPUT: emit(elems)
NOTES:  The slave replicates the master's structure. Since we don't
        expand homomorphisms in the MVP, the slave's elements are
        emitted identically to the master's.
```

### RULE homo_ref

```
INPUT:  HomoApply(kind=REF, elements=[name])
OUTPUT: (omitted — not a playable sound)
NOTES:  REF nodes contain homomorphism identifiers (e.g. 'mineur')
        that tell BP3 which -ho. mapping to apply. Since we don't
        implement homomorphisms, REF nodes are skipped entirely.
        They are also excluded from terminal auto-mapping.

        Previously, these were emitted as Pdef references, causing
        spurious notes (auto-mapped to MIDI 60+) in the output.
```

---

## Modifier Rules (Stateful)

Modifiers (`_transpose`, `_vel`, `_pitchbend`, `_staccato`, `_legato`)
are **stateful**: they apply to all subsequent RHS elements until
overridden by another modifier of the same type.

### Algorithm

```
1. Walk RHS elements left-to-right
2. Maintain dict current_mods = {modifier_name: value}
3. For each element:
   - If SpecialFn modifier: update current_mods[name] = value
   - If musical element (Note, NonTerminal, Variable, Terminal):
     snapshot current_mods
4. Group consecutive elements sharing the same mods snapshot
5. Wrap each group:
   - If all elements are MIDI notes:
     Pbind(\instrument, \bp2sc_default, \midinote, Pseq([...], 1),
           \dur, 0.25, \key1, val1, ...)
   - If mixed (Pdef refs + notes):
     Pbindf(Pseq([...], 1), \key1, val1, \key2, val2)
```

### RULE modifier_transpose

```
INPUT:  SpecialFn(name="transpose", args=[N])
OUTPUT: (stateful) Adds \ctranspose, N to current modifier state
```

### RULE modifier_vel

```
INPUT:  SpecialFn(name="vel", args=[N])
OUTPUT: (stateful) Adds \amp, round(N/127, 3) to current modifier state
```

### RULE modifier_pitchbend

```
INPUT:  SpecialFn(name="pitchbend", args=[N])
OUTPUT: (stateful) Adds \detune, N to current modifier state
```

### RULE modifier_staccato

```
INPUT:  SpecialFn(name="staccato", args=[N])
OUTPUT: (stateful) Adds \legato, N/100 to current modifier state
```

### RULE modifier_legato

```
INPUT:  SpecialFn(name="legato", args=[N])
OUTPUT: (stateful) Adds \legato, N/100 to current modifier state
```

---

## Non-Modifier Special Functions

### RULE fn_mm

```
INPUT:  SpecialFn(name="mm", args=[BPM])
OUTPUT: TempoClock.default.tempo = BPM / 60;
NOTES:  Emitted once at file level, not per-rule.
        If encountered in RHS: // tempo: BPM BPM
```

### RULE fn_ins

```
INPUT:  SpecialFn(name="ins", args=[name])
OUTPUT: (stateful) Adds \instrument, \<sanitized_name> to current modifier state
NOTES:  Instrument selection. The name is sanitized for SC symbol:
        - Lowercased
        - Non-alphanumeric characters replaced with _
        - Prefixed with "inst_" if starting with digit

        Examples:
        - _ins(Vina) -> \instrument, \vina
        - _ins(3) -> \instrument, \inst_3
        - _ins(Grand Piano) -> \instrument, \grand_piano

        The user must define a SynthDef with matching name.
```

### RULE fn_chan

```
INPUT:  SpecialFn(name="chan", args=[N])
OUTPUT: \chan, N (in Pbind)
NOTES:  MIDI channel selection.
```

### RULE fn_pitchrange

```
INPUT:  SpecialFn(name="pitchrange", args=[N])
OUTPUT: // pitchrange: N
```

### RULE fn_pitchcont

```
INPUT:  SpecialFn(name="pitchcont", args=[])
OUTPUT: // pitchcont (continuous pitch)
```

### RULE fn_striated

```
INPUT:  SpecialFn(name="striated", args=[])
OUTPUT: // striated time mode
```

### RULE fn_goto

```
INPUT:  SpecialFn(name="goto", args=[gram, rule])
OUTPUT: // TODO: _goto(gram, rule)
NOTES:  Not compilable in MVP. Affects derivation flow.
```

### RULE fn_repeat

```
INPUT:  SpecialFn(name="repeat", args=[N])
OUTPUT: Pn(<next_element>, N)
NOTES:  Wraps the immediately following RHS element in Pn().
        Implemented via _pending_repeat state: when _repeat(N) is
        encountered, the emitter stores N and applies Pn() to the
        next emitted element.
```

### RULE fn_failed

```
INPUT:  SpecialFn(name="failed", args=[gram, rule])
OUTPUT: // TODO: _failed(gram, rule)
```

### RULE fn_destru

```
INPUT:  SpecialFn(name="destru", args=[])
OUTPUT: // _destru (remove structural markers)
```

### RULE fn_script

```
INPUT:  SpecialFn(name="script", args=["MIDI program N"])
OUTPUT: (stateful) Adds \program, N to current modifier state
NOTES:  MIDI program change. Pattern "MIDI program N" is detected and
        the program number is extracted. Other _script types remain
        unsupported with warning.

        Example:
        - _script(MIDI program 43) -> \program, 43
        - _script(Beep) -> // TODO: _script(Beep) + unsupported_fn warning
```

### RULE modifier_chan

```
INPUT:  SpecialFn(name="chan", args=[N])
OUTPUT: (stateful) Adds \chan, N to current modifier state
```

### RULE modifier_volume

```
INPUT:  SpecialFn(name="volume", args=[N])
OUTPUT: (stateful) Adds \amp, round(N/127, 3) to current modifier state
NOTES:  Same mapping as _vel: MIDI velocity → SC amp.
```

### RULE modifier_mod

```
INPUT:  SpecialFn(name="mod", args=[N])
OUTPUT: (stateful) Adds \detune, N to current modifier state
NOTES:  Modulation wheel mapped to detune (similar to _pitchbend).
```

### RULE modifier_rndvel

```
INPUT:  SpecialFn(name="rndvel", args=[N])
OUTPUT: (stateful) Adds \amp, Pwhite(lo, hi) to current modifier state
NOTES:  Random velocity variation. Adds ±N to the current velocity.
        Uses Pwhite for uniform random distribution between bounds.
        Interacts with _vel/_volume: the last velocity value is used
        as the center point for the random range.

        Example:
        - _vel(80) _rndvel(20) -> \amp, Pwhite(0.472, 0.787)
          (velocity 60-100 / 127)
        - _rndvel(0) -> resets to fixed velocity (disables randomization)
```

### RULE modifier_rndtime

```
INPUT:  SpecialFn(name="rndtime", args=[N])
OUTPUT: (stateful) Adds \dur, Pwhite(lo, hi) to current modifier state
NOTES:  Random timing variation (MusicXML import). Adds ±N% variation
        to the base duration (0.25). Uses Pwhite for uniform random
        distribution between bounds.

        Example:
        - _rndtime(10) -> \dur, Pwhite(0.225, 0.275)
          (±10% of base duration 0.25)
        - _rndtime(0) -> resets to fixed duration 0.25
```

### RULE modifier_tempo

```
INPUT:  SpecialFn(name="tempo", args=[N])
OUTPUT: (stateful) Adds \stretch, 1/N to current modifier state
NOTES:  Relative tempo multiplier (distinct from _mm which sets BPM).
        _tempo(2) = 2× faster → \stretch, 0.5
        _tempo(2/3) = 2/3 speed → \stretch, 1.5
        Fractions in the argument are parsed: "2/3" → ratio 0.6667.
```

### RULE modifier_value

```
INPUT:  SpecialFn(name="value", args=[key, val])
OUTPUT: (stateful) Adds \key, val to current modifier state
NOTES:  Generic key-value pair for any SC Pbind key.
        Example: _value(pan, -0.5) → \pan, -0.5
```

### RULE fn_rest

```
INPUT:  SpecialFn(name="rest", args=[])
OUTPUT: Rest()
NOTES:  Explicit rest function — same output as the '-' rest symbol.
```

### RULE fn_velcont

```
INPUT:  SpecialFn(name="velcont", args=[])
OUTPUT: // velcont (continuous velocity — SC handles natively)
NOTES:  Informational. SC Pbind already handles per-event velocity.
```

### RULE fn_press

```
INPUT:  SpecialFn(name="press", args=[N])
OUTPUT: (stateful) Adds \aftertouch, round(N/127, 3) to current modifier state
NOTES:  MIDI aftertouch pressure (0-127) normalized to 0-1.
        The user can add |aftertouch=0| to their SynthDef to use this value.

        Example:
        - _press(127) -> \aftertouch, 1.0
        - _press(64)  -> \aftertouch, 0.504
```

### RULE fn_step

```
INPUT:  SpecialFn(name="step", args=[N])
OUTPUT: // step: N
NOTES:  Informational comment.
```

### RULE fn_keyxpand

```
INPUT:  SpecialFn(name="keyxpand", args=[N])
OUTPUT: // keyxpand: N
NOTES:  Informational comment.
```

### RULE fn_part

```
INPUT:  SpecialFn(name="part", args=[N])
OUTPUT: // part: N
NOTES:  Informational comment.
```

### RULE fn_pitchstep

```
INPUT:  SpecialFn(name="pitchstep", args=[])
OUTPUT: // pitchstep (discrete pitch)
NOTES:  Informational comment.
```

### RULE fn_scale

```
INPUT:  SpecialFn(name="scale", args=[name, root_arg?])
OUTPUT: (stateful) Adds \scale or \tuning, plus \root to current modifier state
NOTES:  Scale resolution is performed via scale_map.py module which:
        1. Parses key-quality scales (Cmaj, Dmin, F#min) via regex
           - Extracts root from key name (C=0, D=2, F#=6, etc.)
           - Maps to Scale.major or Scale.minor
        2. Looks up tunings (just intonation, piano, meantone_classic, etc.)
           - Maps to Tuning.just, Tuning.et12, Tuning.mean4, etc.
           - Uses root_arg for root offset
        3. Looks up ragas (todi_ka_4, grama, etc.)
           - Maps to Scale.todi, Scale.chromatic, etc.
           - Uses root_arg for root offset
        4. Falls back to Scale.chromatic with approximation warning

        Root parsing supports:
        - Anglo: C4, D#5, Bb3 -> semitone offset (C=0, D=2, A=9)
        - French: dop4, rep4, mip4 -> semitone offset
        - Indian: sa_4, ri_4, pa_4 -> semitone offset
        - Numeric: 0-11 direct offset

        Examples:
        - _scale(Cmaj, C4) -> \scale, Scale.major, \root, 0
        - _scale(Dmin, 0)  -> \scale, Scale.minor, \root, 2
        - _scale(just intonation, A4) -> \tuning, Tuning.just, \root, 9
        - _scale(todi_ka_4, 0) -> \scale, Scale.todi, \root, 0
        - _scale(unknown, 0) -> \scale, Scale.chromatic, \root, 0 + warning
```

### RULE fn_retro

```
INPUT:  SpecialFn(name="retro", args=[])
OUTPUT: // retro (reverse sequence)
NOTES:  Sequence reversal. Emitted as informational comment.
        Future: could apply .reverse to the pattern array.
```

### RULE fn_switch

```
INPUT:  SpecialFn(name="switchon"|"switchoff", args=[N, M])
OUTPUT: // MIDI _switchon(N, M) | // MIDI _switchoff(N, M)
NOTES:  MIDI controller switch. Informational comment.
```

### RULE fn_other

```
INPUT:  SpecialFn(name=other, args=[...])
OUTPUT: // _other(args)
NOTES:  Catch-all for unrecognized special functions.
```

---

## MusicXML Import Constructions

These rules handle constructions generated by Bernard's MusicXML importer
(`_musicxml.php`). They enable 100% compatibility with BP3 files produced
from MusicXML imports.

### RULE tied_note_start

```
INPUT:  Tie(note=Note, is_start=True)    (syntax: C4&, fa4&)
OUTPUT: Pbind(\instrument, \bp2sc_default, \midinote, Pseq([midi], 1),
              \dur, 0.25, \legato, 2.0)
NOTES:  A tie start (note&) indicates the note should sustain beyond its
        normal duration. Emitted with extended legato (2.0 = double duration).
        The MIDI note is tracked for matching with a subsequent tie end.
```

### RULE tied_note_end

```
INPUT:  Tie(note=Note, is_start=False)   (syntax: &C4, &fa4)
OUTPUT: Event.silent(0.25)
NOTES:  A tie end (&note) indicates continuation of a previously tied note.
        If the MIDI matches a pending tie start, the note is already being
        held, so emit a silent event to occupy the time slot without
        re-triggering the note.
```

### RULE tempo_inline

```
INPUT:  ||N|| where N is BPM
OUTPUT: (stateful) Adds \stretch, 60/N to current modifier state
NOTES:  Inline tempo marker from MusicXML import. Parsed as SpecialFn
        (name="mm_inline", args=[N]). In RHS context, emitted as stretch
        modifier relative to base tempo 60 BPM.

        Example:
        - ||120|| -> \stretch, 0.5 (2x faster)
        - ||30||  -> \stretch, 2.0 (2x slower)
```

### RULE pedal_sustain

```
INPUT:  SpecialFn(name="sustainstart_"|"sustainstart", args=[])
OUTPUT: (stateful) Adds \sustain, 1 to current modifier state

INPUT:  SpecialFn(name="sustainstop_"|"sustainstop", args=[])
OUTPUT: (stateful) Adds \sustain, 0 to current modifier state

INPUT:  SpecialFn(name="sustainstopstart_"|"sustainstopstart", args=[])
OUTPUT: (stateful) Adds \sustain, 1 to current modifier state
NOTES:  Sustain pedal markers from MusicXML import. The trailing underscore
        is optional (parser strips it). stopstart = release then press = remains on.
```

### RULE pedal_sostenuto

```
INPUT:  SpecialFn(name="sostenutostart_"|"sostenutostart", args=[])
OUTPUT: (stateful) Adds \sostenuto, 1 to current modifier state

INPUT:  SpecialFn(name="sostenutostop_"|"sostenutostop", args=[])
OUTPUT: (stateful) Adds \sostenuto, 0 to current modifier state
NOTES:  Sostenuto pedal markers from MusicXML import.
```

### RULE pedal_soft

```
INPUT:  SpecialFn(name="softstart_"|"softstart", args=[])
OUTPUT: (stateful) Adds \softPedal, 1 to current modifier state

INPUT:  SpecialFn(name="softstop_"|"softstop", args=[])
OUTPUT: (stateful) Adds \softPedal, 0 to current modifier state
NOTES:  Una corda (soft pedal) markers from MusicXML import.
```

### RULE slur_markers

```
INPUT:  SpecialFn(name="legato_", args=[])
OUTPUT: (stateful) Adds \legato, 1.5 to current modifier state

INPUT:  SpecialFn(name="nolegato_", args=[])
OUTPUT: (stateful) Adds \legato, 0.8 to current modifier state
NOTES:  Slur start/end markers from MusicXML import.
        legato_ = connected notes (extended overlap)
        nolegato_ = end of slur (slight staccato)
```

### RULE fn_part

```
INPUT:  SpecialFn(name="part", args=[N])
OUTPUT: // part: N
NOTES:  Informational marker from MusicXML import indicating the
        instrument part number. Does NOT produce any warning (pure metadata).
```

---

## Flag Rules

Flags are implemented via SC environment variables (`~flagName`) and
`Prout`-based conditional rule selection.

### Flag Classification

| Flag Op | Type | Example | SC Code |
|---------|------|---------|---------|
| `""` (bare) | Condition | `/Ideas/` | `(~Ideas > 0)` |
| `>` | Condition | `/Ideas>3/` | `(~Ideas > 3)` |
| `<` | Condition | `/Ideas<10/` | `(~Ideas < 10)` |
| `=` | Operation | `/Ideas=20/` | `~Ideas = 20;` |
| `+` | Operation | `/NumR+1/` | `~NumR = ~NumR + 1;` |
| `-` | Operation | `/Ideas-1/` | `~Ideas = ~Ideas - 1;` |

### RULE flag_initialization

```
INPUT:  All Flag nodes across the grammar
OUTPUT: ~flagName1 = <init_value>;
        ~flagName2 = 0;
        ...
NOTES:  Emitted once at file level, before all Pdefs.
        Initial values: if the start symbol's first rule has a flag
        with op="=", that value is used. Otherwise defaults to 0.
```

### RULE flagged_rules

```
INPUT:  Rules for symbol S where at least one rule has flags
OUTPUT: Pdef(\S, Prout({ |ev|
          inf.do {
            if(<condition1>) {
              <operations>;
              <pattern>.embedInStream(ev);
            } { if(<condition2>) {
              ...
            } {
              <fallback>.embedInStream(ev);
            }}
          }
        }));
NOTES:  Conditions become if-guards. Operations become assignments.
        Unflagged rules become the else/fallback branch.
        Each branch calls .embedInStream(ev) to yield events.
```

---

## Weight Decrement Rules

### RULE grammar_block_rnd_decrement

```
INPUT:  GrammarBlock(mode="RND", rules=[r1, r2, ...])
        where at least one rule has Weight(decrement=M)
OUTPUT: Pdef(\lhs, Prout({ |ev|
          var w0 = <initial_weight>;  // decrement: M
          var w1 = <weight>;
          inf.do {
            var total = w0 + w1;
            var r = total.rand;
            if(r < w0) {
              emit(r1).embedInStream(ev);
              w0 = (w0 - M).max(0);
            } {
              emit(r2).embedInStream(ev);
            }
          }
        }));
NOTES:  Mutable weight variables decrease after each use.
        .max(0) prevents negative weights.
        Rules without decrement keep static weights.
        Weighted random selection via cumulative thresholds.
```

---

## Multi-Symbol LHS (Context-Sensitive Rules)

BP3 supports context-sensitive production rules where the LHS contains
multiple symbols. For example:

```
gram#3[47] |o| |miny| --> |o1| |miny|
```

Here `|o|` is the **primary** symbol (the one being rewritten) and
`|miny|` is **context** — it must be adjacent in the derivation string
for the rule to match.

### Pass-Through Stripping

```
INPUT:  Rule with LHS = [primary, ctx1, ctx2, ...]
        and RHS containing the same context symbols
OUTPUT: RHS with context symbols REMOVED before emission
NOTES:  Context symbols on the RHS are pass-throughs: they represent
        the context that was consumed from the derivation string and
        preserved. They must NOT be emitted as part of the Pdef's
        musical content, otherwise the Pdef overflows its time slot.

        Algorithm:
        1. Identify context names from LHS[1:] (non-ContextMarker symbols)
        2. For each context name (from right to left), find and remove
           the matching symbol from the RHS

        Example:
          LHS: |o| |miny|  RHS: |o1| |miny|
          Context symbols: ["miny"]
          Stripped RHS: [|o1|]
          Pdef(\o) variant emits: Pdef(\o1) (0.5 beats, not 1.0)

        This is distinct from ContextMarker elements (e.g., (|z13|))
        which are matching conditions, not pass-through symbols.
        Rule 49: |o| (|z13|) --> |o3| — no stripping needed because
        (|z13|) is a ContextMarker, not a regular symbol.
```

---

## Multi-Block Symbol Disambiguation

When a symbol appears as LHS in multiple grammar blocks (e.g., `|y|`
defined in both block 3 and block 5), suffixes are added to both
definitions and references.

### LHS Disambiguation

```
INPUT:  Symbol "y" defined as LHS in block 3 and block 5
OUTPUT: Pdef(\y_g3, ...) and Pdef(\y_g5, ...)
NOTES:  The suffix _gN disambiguates the Pdef definitions.
```

### RHS Reference Resolution

```
INPUT:  NonTerminal("y") referenced in RHS, where "y" is a
        multi-block symbol (defined in blocks 3 and 5)
OUTPUT: Pdef(\y_gN) where N is the current block's index
NOTES:  RHS references to multi-block symbols MUST be resolved to the
        disambiguated name. The resolution algorithm:
        1. If the reference is in a block that defines the symbol,
           use that block's version (e.g., block 3 → \y_g3)
        2. Otherwise, use the first block's version as fallback
        An unresolved Pdef(\y) — without suffix — would be UNDEFINED
        in SC, causing the stream to block indefinitely waiting for
        a source to be assigned.
```

---

## Terminal Auto-Mapping

```
INPUT:  NonTerminal(name) with no production rules
OUTPUT: Pdef(\name, Pbind(
          \instrument, \bp2sc_default,
          \midinote, Pseq([<midi>], 1),
          \dur, 0.25
        ));
NOTES:  MIDI assignment depends on the terminal's name:

        1. Anglo note detection: If name matches [A-G][#b]?\d (e.g. C4,
           D#5, Bb3), the MIDI note is computed via note_to_midi().
           This handles grammars using English notation where the parser
           classifies C4/D4/E4 as NonTerminals (because uppercase
           identifiers like A8, B8 are commonly used as nonterminal
           names in BP3 grammars).

        2. Otherwise: MIDI notes assigned sequentially starting from 60.
           Order is determined by first appearance in RHS traversal.

        Exclusions:
        - Symbols with production rules (→ nonterminals, not terminals)
        - HomoApply(REF) contents (→ homomorphism labels, not sounds)

        The midinote MUST be wrapped in Pseq([...], 1) per INV-4
        to ensure each Pdef produces exactly one event per trigger.
```

---

## Summary of SC Pattern Mapping

| BP3 Mode | SC Pattern | Condition |
|----------|-----------|-----------|
| ORD | `Pseq` | Sequential |
| RND (no weights) | `Prand` | Uniform random |
| RND (weights) | `Pwrand` | Weighted random |
| RND (decrements) | `Prout` | Mutable weighted selection |
| RND/ORD (flags) | `Prout` | Conditional rule selection |
| LIN (no weights) | `Prand` | Same as RND at pattern level |
| LIN (weights) | `Pwrand` | Same as RND at pattern level |
| SUB1 | `Pseq` | Same as ORD |

## SC Pattern Classes Used

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
| `Pwhite` | Uniform random values | `_rndvel(N)` velocity variation |
| `Rest` | Silence event | Rest, Lambda, Wildcard |

## Pbind Keys Used

| Key | Purpose | BP3 Origin |
|-----|---------|------------|
| `\instrument` | SynthDef name | `_ins(name)` |
| `\midinote` | MIDI note number | Note elements |
| `\dur` | Event duration | Default 0.25, `_rndtime(N)` |
| `\amp` | Amplitude (0-1) | `_vel(N)`, `_volume(N)`, `_rndvel(N)` |
| `\ctranspose` | Chromatic transposition | `_transpose(N)` |
| `\detune` | Pitch detuning | `_pitchbend(N)`, `_mod(N)` |
| `\legato` | Note overlap ratio | `_staccato(N)`, `_legato(N)`, `_legato_`, `_nolegato_`, tied notes |
| `\stretch` | Duration multiplier | `_tempo(N)`, polymetric ratio, `\|\|N\|\|` |
| `\chan` | MIDI channel | `_chan(N)` |
| `\program` | MIDI program change | `_script(MIDI program N)` |
| `\aftertouch` | Aftertouch pressure (0-1) | `_press(N)` |
| `\scale` | SC Scale class | `_scale(name, root)` |
| `\tuning` | SC Tuning class | `_scale(tuning_name, root)` |
| `\root` | Scale root offset (0-11) | `_scale(name, root)` |
| `\sustain` | Sustain pedal (0/1) | `_sustainstart_`, `_sustainstop_` |
| `\sostenuto` | Sostenuto pedal (0/1) | `_sostenutostart_`, `_sostenutostop_` |
| `\softPedal` | Soft pedal (0/1) | `_softstart_`, `_softstop_` |
