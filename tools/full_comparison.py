#!/usr/bin/env python3
"""Full comparison of all available BP3 MIDI files with SC transpiler output."""

import sys
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field

sys.path.insert(0, '/mnt/d/Claude/BP2SC/src')
sys.path.insert(0, '/mnt/d/Claude/BP2SC/tests')

from bp2sc.grammar.parser import parse_file
from bp2sc.sc_emitter import emit_scd_with_warnings

import mido
from sclang_trace import trace_scd_content, sclang_available

BASE_DIR = Path('/mnt/d/Claude/BP2SC')

# All available test pairs with their MIDI files
TEST_PAIRS = [
    # From new BP3 generation (v3 with note convention detection)
    {'name': 'drum', 'grammar': BASE_DIR / 'bp3-ctests/-gr.drum',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/drum.mid'},
    {'name': 'Ames', 'grammar': BASE_DIR / 'bp3-ctests/-gr.Ames',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/Ames.mid'},
    {'name': 'produce-all', 'grammar': BASE_DIR / 'bp3-ctests/produce-all.bpgr',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/produce-all.mid'},
    {'name': 'tryTimePatterns', 'grammar': BASE_DIR / 'bp3-ctests/-gr.tryTimePatterns',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/tryTimePatterns.mid'},
    {'name': 'checkNegativeContext', 'grammar': BASE_DIR / 'bp3-ctests/-gr.checkNegativeContext',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/checkNegativeContext.mid'},
    {'name': 'vina', 'grammar': BASE_DIR / 'bp3-ctests/-gr.vina',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/vina.mid'},
    {'name': 'Ruwet_test', 'grammar': BASE_DIR / 'bp3-ctests/-gr.Ruwet',
     'midi': BASE_DIR / 'tools/bolprocessor/output_midi/Ruwet_test.mid'},
    # From existing reference MIDI files
    {'name': 'Ruwet_ref', 'grammar': BASE_DIR / 'bp3-ctests/-gr.Ruwet',
     'midi': BASE_DIR / 'tools/ref_ruwet.mid'},
    {'name': 'Visser.Waves', 'grammar': BASE_DIR / 'bp3-ctests/-gr.Visser.Waves',
     'midi': BASE_DIR / 'bp3-ctests/Visser.Waves1.mid'},
]


@dataclass
class Result:
    name: str
    # BP3
    bp3_notes: list = field(default_factory=list)
    bp3_unique: list = field(default_factory=list)
    bp3_tempo: float = 120.0
    bp3_dur_dist: dict = field(default_factory=dict)
    # SC
    sc_notes: list = field(default_factory=list)
    sc_unique: list = field(default_factory=list)
    sc_dur_dist: dict = field(default_factory=dict)
    sc_warnings: int = 0
    sc_error: str = ""
    # Comparison
    match: bool = False
    only_bp3: list = field(default_factory=list)
    only_sc: list = field(default_factory=list)


def extract_midi(path: Path) -> dict:
    """Extract info from MIDI file."""
    if not path.exists() or path.stat().st_size < 100:
        return {'notes': [], 'unique': [], 'tempo': 120.0, 'durs': {}}

    try:
        mid = mido.MidiFile(str(path))
        tpb = mid.ticks_per_beat
        tempo = 500000

        notes = []
        ons = []
        offs = []

        for track in mid.tracks:
            tick = 0
            for msg in track:
                tick += msg.time
                if msg.type == 'set_tempo':
                    tempo = msg.tempo
                elif msg.type == 'note_on' and msg.velocity > 0:
                    notes.append(msg.note)
                    ons.append((tick, msg.note))
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    offs.append((tick, msg.note))

        # Calc durations
        durs = []
        used = set()
        for ot, on in sorted(ons):
            for i, (ft, fn) in enumerate(sorted(offs)):
                if i in used:
                    continue
                if fn == on and ft >= ot:
                    durs.append(round((ft - ot) / tpb, 4))
                    used.add(i)
                    break

        return {
            'notes': notes,
            'unique': sorted(set(notes)),
            'tempo': mido.tempo2bpm(tempo),
            'durs': dict(Counter(durs)),
        }
    except Exception as e:
        return {'notes': [], 'unique': [], 'tempo': 120.0, 'durs': {}, 'error': str(e)}


def trace_sc(grammar: Path, alphabet_dir: str | None = None) -> dict:
    """Parse and trace SC output."""
    if grammar is None or not grammar.exists():
        return {'notes': [], 'unique': [], 'durs': {}, 'warnings': 0, 'error': 'No grammar'}

    try:
        ast = parse_file(str(grammar))
        # Use alphabet_dir for homo loading, max_dur for timeout prevention
        # Don't use seed - BP3's random algorithm is different from SC's
        sc, warnings = emit_scd_with_warnings(
            ast,
            seed=None,  # Let sclang use its own randomness
            alphabet_dir=alphabet_dir,
            max_dur=200  # 200 beats max to prevent infinite loops
        )

        events = trace_scd_content(sc, start_symbol="S", max_events=500, timeout=60.0)

        notes = []
        durs = []
        for ev in events:
            if ev.type == 'note' and ev.midinote is not None:
                notes.append(int(ev.midinote))
            d = (ev.dur or 0) * (ev.stretch or 1.0)
            durs.append(round(d, 4))

        return {
            'notes': notes,
            'unique': sorted(set(notes)),
            'durs': dict(Counter(durs)),
            'warnings': len(warnings),
            'error': '',
        }
    except Exception as e:
        return {'notes': [], 'unique': [], 'durs': {}, 'warnings': 0, 'error': str(e)}


def compare(pair: dict) -> Result:
    """Compare one pair."""
    r = Result(name=pair['name'])

    # Determine alphabet directory (same as grammar directory)
    grammar = pair.get('grammar')
    alphabet_dir = str(grammar.parent) if grammar else None

    # BP3
    bp3 = extract_midi(pair['midi'])
    r.bp3_notes = bp3['notes']
    r.bp3_unique = bp3['unique']
    r.bp3_tempo = bp3.get('tempo', 120.0)
    r.bp3_dur_dist = bp3['durs']

    # SC
    sc = trace_sc(pair['grammar'], alphabet_dir=alphabet_dir)
    r.sc_notes = sc['notes']
    r.sc_unique = sc['unique']
    r.sc_dur_dist = sc['durs']
    r.sc_warnings = sc['warnings']
    r.sc_error = sc.get('error', '')

    # Compare
    if r.bp3_unique and r.sc_unique:
        bp3_set = set(r.bp3_unique)
        sc_set = set(r.sc_unique)
        r.match = bp3_set == sc_set
        r.only_bp3 = sorted(bp3_set - sc_set)
        r.only_sc = sorted(sc_set - bp3_set)

    return r


def note_name(n: int) -> str:
    """Convert MIDI note to name."""
    names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    return f"{names[n % 12]}{n // 12 - 1}"


def main():
    print("=" * 80)
    print("FULL BP3 vs SC TRANSPILER COMPARISON")
    print("=" * 80)
    print(f"sclang: {sclang_available()}")
    print(f"Pairs: {len(TEST_PAIRS)}")
    print()

    results = []

    for pair in TEST_PAIRS:
        print(f"Processing {pair['name']}...", end=" ", flush=True)
        r = compare(pair)
        results.append(r)

        if r.sc_error:
            print(f"⚠️ {r.sc_error[:30]}")
        elif not r.bp3_notes:
            print("⚠️ No BP3 notes")
        elif r.match:
            print("✅ MATCH")
        else:
            print(f"❌ BP3:{len(r.bp3_unique)} SC:{len(r.sc_unique)}")

    # Detailed results
    print("\n" + "=" * 80)
    print("DETAILED RESULTS")
    print("=" * 80)

    for r in results:
        print(f"\n--- {r.name} ---")
        print(f"BP3: {len(r.bp3_notes)} notes, unique: {r.bp3_unique[:10]}{'...' if len(r.bp3_unique) > 10 else ''}")
        print(f"SC:  {len(r.sc_notes)} notes, unique: {r.sc_unique[:10]}{'...' if len(r.sc_unique) > 10 else ''}")

        if r.sc_error:
            print(f"SC Error: {r.sc_error}")

        if r.match:
            print("✅ Note sets MATCH")
        elif r.bp3_unique and r.sc_unique:
            print("❌ MISMATCH")
            if r.only_bp3:
                print(f"   Only in BP3: {[f'{n}({note_name(n)})' for n in r.only_bp3[:5]]}")
            if r.only_sc:
                print(f"   Only in SC:  {[f'{n}({note_name(n)})' for n in r.only_sc[:5]]}")

        # Duration comparison
        if r.bp3_dur_dist and r.sc_dur_dist:
            bp3_d = set(r.bp3_dur_dist.keys())
            sc_d = set(r.sc_dur_dist.keys())
            if bp3_d == sc_d:
                print("✅ Duration vocab matches")
            else:
                print(f"⚠️ Duration vocab differs")
                print(f"   BP3: {sorted(bp3_d)[:5]}")
                print(f"   SC:  {sorted(sc_d)[:5]}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    valid = [r for r in results if r.bp3_notes and not r.sc_error]
    matches = [r for r in valid if r.match]

    print(f"Total pairs:        {len(results)}")
    print(f"Valid comparisons:  {len(valid)}")
    print(f"Note set matches:   {len(matches)}/{len(valid)}")
    print()

    # Classification
    print("CLASSIFICATION:")
    for r in results:
        if not r.bp3_notes:
            status = "⚠️ No BP3 data"
        elif r.sc_error:
            status = f"⚠️ SC error: {r.sc_error[:40]}"
        elif r.match:
            status = "✅ MATCH"
        else:
            status = f"❌ MISMATCH ({len(r.only_bp3)} missing, {len(r.only_sc)} extra)"
        print(f"  {r.name:20} {status}")


if __name__ == '__main__':
    main()
