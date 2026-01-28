#!/usr/bin/env python3
"""Comprehensive MIDI comparison between BP3 reference and SC transpiler output.

Compares all available evaluation files:
1. ruwet: RND grammar with homomorphisms
2. produce-all: Simple RND grammar
3. 12345678: ORD grammar with polymetric structures
"""

import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, '/mnt/d/Claude/BP2SC/tests')
sys.path.insert(0, '/mnt/d/Claude/BP2SC/src')

import mido
from sclang_trace import trace_scd_file, sclang_available

BASE_DIR = Path('/mnt/d/Claude/BP2SC')

# Define evaluation files
EVAL_FILES = [
    {
        'name': 'ruwet',
        'grammar': BASE_DIR / 'tests/golden/ruwet.bp',
        'midi_ref': BASE_DIR / 'tools/ref_ruwet.mid',
        'scd_output': BASE_DIR / 'output_ruwet.scd',
        'type': 'RND',  # stochastic - only compare note sets
    },
    {
        'name': 'produce-all',
        'grammar': BASE_DIR / 'bp3-ctests/produce-all.bpgr',
        'midi_ref': BASE_DIR / 'tools/ref_produce-all.mid',
        'scd_output': BASE_DIR / 'output_produce-all.scd',
        'type': 'RND',  # stochastic
    },
    {
        'name': '12345678',
        'grammar': BASE_DIR / 'tests/golden/12345678.bp',
        'midi_ref': None,  # No reference MIDI
        'scd_output': BASE_DIR / 'output_12345678.scd',
        'type': 'ORD',  # deterministic
    },
]


def extract_midi_notes(midi_path: Path) -> tuple[list[int], dict]:
    """Extract note events from a MIDI file.

    Returns:
        tuple: (list of MIDI note numbers, metadata dict)
    """
    mid = mido.MidiFile(str(midi_path))

    ticks_per_beat = mid.ticks_per_beat

    # Find tempo
    tempo_us = 500000  # default 120 BPM
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                tempo_us = msg.tempo
                break

    bpm = mido.tempo2bpm(tempo_us)
    seconds_per_tick = tempo_us / 1_000_000 / ticks_per_beat

    # Collect notes
    notes = []
    note_ons = []  # (abs_tick, note, velocity)
    note_offs = []  # (abs_tick, note)

    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                notes.append(msg.note)
                note_ons.append((abs_tick, msg.note, msg.velocity))
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                note_offs.append((abs_tick, msg.note))

    # Compute durations
    note_ons.sort(key=lambda x: x[0])
    note_offs.sort(key=lambda x: x[0])

    used_offs = set()
    durations = []
    for on_tick, on_note, _ in note_ons:
        for j, (off_tick, off_note) in enumerate(note_offs):
            if j in used_offs:
                continue
            if off_note == on_note and off_tick >= on_tick:
                durations.append(off_tick - on_tick)
                used_offs.add(j)
                break

    # Compute inter-onset deltas
    deltas = []
    for i in range(1, len(note_ons)):
        deltas.append(note_ons[i][0] - note_ons[i-1][0])

    metadata = {
        'ticks_per_beat': ticks_per_beat,
        'bpm': bpm,
        'tempo_us': tempo_us,
        'seconds_per_tick': seconds_per_tick,
        'note_count': len(notes),
        'unique_notes': sorted(set(notes)),
        'durations_ticks': durations,
        'deltas_ticks': deltas,
        'duration_dist': dict(Counter(durations)),
        'delta_dist': dict(Counter(deltas)),
    }

    return notes, metadata


def extract_sc_events(scd_path: Path, start_symbol: str = "S") -> tuple[list[int], dict]:
    """Extract events from SC transpiler output via sclang trace.

    Returns:
        tuple: (list of MIDI note numbers, metadata dict)
    """
    if not sclang_available():
        return [], {'error': 'sclang not available'}

    try:
        events = trace_scd_file(str(scd_path), start_symbol=start_symbol,
                               max_events=500, timeout=60.0)
    except Exception as e:
        return [], {'error': str(e)}

    notes = []
    durs = []
    stretches = []

    for ev in events:
        if ev.type == 'note' and ev.midinote is not None:
            notes.append(int(ev.midinote))
        dur_val = ev.dur if ev.dur is not None else 0
        stretch_val = ev.stretch if ev.stretch is not None else 1.0
        durs.append(dur_val)
        stretches.append(stretch_val)

    eff_durs = [d * s for d, s in zip(durs, stretches)]

    metadata = {
        'event_count': len(events),
        'note_count': len(notes),
        'rest_count': sum(1 for e in events if e.type == 'rest'),
        'unique_notes': sorted(set(notes)),
        'durs': durs,
        'stretches': stretches,
        'effective_durs': eff_durs,
        'dur_dist': dict(Counter(round(d, 4) for d in eff_durs)),
        'total_beats': sum(eff_durs),
    }

    return notes, metadata


def compare_eval_file(ef: dict) -> dict:
    """Compare a single evaluation file pair."""
    result = {
        'name': ef['name'],
        'type': ef['type'],
        'grammar_exists': ef['grammar'].exists(),
        'midi_ref_exists': ef['midi_ref'].exists() if ef['midi_ref'] else False,
        'scd_exists': ef['scd_output'].exists(),
    }

    # Extract BP3 MIDI if available
    if ef['midi_ref'] and ef['midi_ref'].exists():
        bp3_notes, bp3_meta = extract_midi_notes(ef['midi_ref'])
        result['bp3'] = {
            'notes': bp3_notes,
            'meta': bp3_meta,
        }
    else:
        result['bp3'] = None

    # Extract SC output
    if ef['scd_output'].exists():
        sc_notes, sc_meta = extract_sc_events(ef['scd_output'])
        result['sc'] = {
            'notes': sc_notes,
            'meta': sc_meta,
        }
    else:
        result['sc'] = None

    # Compare if both available
    if result['bp3'] and result['sc'] and 'error' not in result['sc']['meta']:
        bp3_set = set(result['bp3']['notes'])
        sc_set = set(result['sc']['notes'])

        result['comparison'] = {
            'bp3_note_count': len(result['bp3']['notes']),
            'sc_note_count': len(result['sc']['notes']),
            'bp3_unique': sorted(bp3_set),
            'sc_unique': sorted(sc_set),
            'sets_match': bp3_set == sc_set,
            'only_in_bp3': sorted(bp3_set - sc_set),
            'only_in_sc': sorted(sc_set - bp3_set),
            'count_match': len(result['bp3']['notes']) == len(result['sc']['notes']),
        }

        # For RND grammars, sequence comparison is not meaningful
        if ef['type'] == 'ORD':
            result['comparison']['sequence_match'] = result['bp3']['notes'] == result['sc']['notes']

    return result


def print_report(results: list[dict]):
    """Print a formatted comparison report."""
    print("=" * 80)
    print("BP3 vs SC Transpiler MIDI Comparison Report")
    print("=" * 80)

    for r in results:
        print(f"\n{'='*60}")
        print(f"File: {r['name']} ({r['type']} grammar)")
        print(f"{'='*60}")

        print(f"Grammar:   {'OK' if r['grammar_exists'] else 'MISSING'}")
        print(f"MIDI ref:  {'OK' if r['midi_ref_exists'] else 'NONE'}")
        print(f"SC output: {'OK' if r['scd_exists'] else 'MISSING'}")

        # BP3 MIDI info
        if r['bp3']:
            bp3 = r['bp3']
            print(f"\n--- BP3 Reference MIDI ---")
            print(f"Notes: {bp3['meta']['note_count']}")
            print(f"Unique MIDI: {bp3['meta']['unique_notes']}")
            print(f"Tempo: {bp3['meta']['bpm']:.1f} BPM")
            if bp3['meta']['duration_dist']:
                dur_beats = {k/bp3['meta']['ticks_per_beat']: v
                            for k, v in bp3['meta']['duration_dist'].items()}
                print(f"Duration dist (beats): {dur_beats}")

        # SC output info
        if r['sc']:
            sc = r['sc']
            if 'error' in sc['meta']:
                print(f"\n--- SC Output (ERROR) ---")
                print(f"Error: {sc['meta']['error']}")
            else:
                print(f"\n--- SC Transpiler Output ---")
                print(f"Events: {sc['meta']['event_count']} (notes: {sc['meta']['note_count']}, rests: {sc['meta']['rest_count']})")
                print(f"Unique MIDI: {sc['meta']['unique_notes']}")
                print(f"Total beats: {sc['meta']['total_beats']:.2f}")
                print(f"Dur dist (beats): {sc['meta']['dur_dist']}")

        # Comparison
        if 'comparison' in r:
            cmp = r['comparison']
            print(f"\n--- Comparison ---")
            print(f"Note count: BP3={cmp['bp3_note_count']}, SC={cmp['sc_note_count']} -> {'MATCH' if cmp['count_match'] else 'MISMATCH'}")
            print(f"Note sets:  {'MATCH' if cmp['sets_match'] else 'MISMATCH'}")
            if not cmp['sets_match']:
                if cmp['only_in_bp3']:
                    print(f"  Only in BP3: {cmp['only_in_bp3']}")
                if cmp['only_in_sc']:
                    print(f"  Only in SC:  {cmp['only_in_sc']}")

            if 'sequence_match' in cmp:
                print(f"Sequence:   {'MATCH' if cmp['sequence_match'] else 'DIFFER (expected for RND)'}")
            else:
                print(f"Sequence:   (not compared - {r['type']} grammar is stochastic)")

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")

    total = len(results)
    with_ref = sum(1 for r in results if r['bp3'])
    sets_match = sum(1 for r in results if 'comparison' in r and r['comparison']['sets_match'])

    print(f"Total files: {total}")
    print(f"With MIDI reference: {with_ref}")
    print(f"Note sets match: {sets_match}/{with_ref}")


def main():
    print("Starting MIDI comparison...")
    print(f"sclang available: {sclang_available()}")

    results = []
    for ef in EVAL_FILES:
        print(f"\nProcessing {ef['name']}...")
        result = compare_eval_file(ef)
        results.append(result)

    print_report(results)


if __name__ == '__main__':
    main()
