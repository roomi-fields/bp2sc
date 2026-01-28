#!/usr/bin/env python3
"""Comprehensive comparison of all 55 BP3 grammars.

For each grammar:
1. Transpile to SC
2. Count warnings
3. If MIDI reference exists, compare note vocabularies
4. If sclang available, trace SC output and extract notes
"""

import sys
import os
import tempfile
from pathlib import Path
from collections import Counter
import json

sys.path.insert(0, '/mnt/d/Claude/BP2SC/src')
sys.path.insert(0, '/mnt/d/Claude/BP2SC/tests')

from bp2sc.grammar.parser import parse_file
from bp2sc.sc_emitter import emit_scd_with_warnings

# Try to import optional dependencies
try:
    import mido
    MIDO_AVAILABLE = True
except ImportError:
    MIDO_AVAILABLE = False

try:
    from sclang_trace import trace_scd_content, sclang_available
    SCLANG_AVAILABLE = sclang_available()
except ImportError:
    SCLANG_AVAILABLE = False

BASE_DIR = Path('/mnt/d/Claude/BP2SC')
BP3_CTESTS = BASE_DIR / 'bp3-ctests'
TOOLS_DIR = BASE_DIR / 'tools'

# Known MIDI references
MIDI_REFS = {
    'Visser.Waves': TOOLS_DIR / 'ref_ruwet.mid',  # Actually this might not match
    'acceleration': BP3_CTESTS / 'acceleration.mid',
    'drum': BP3_CTESTS / 'drum.mid',
    'Ruwet': TOOLS_DIR / 'ref_ruwet.mid',
    'produce-all': TOOLS_DIR / 'ref_produce-all.mid',
}


def get_all_grammars() -> list[Path]:
    """Get all grammar files from bp3-ctests."""
    grammars = []
    # -gr.* files
    grammars.extend(BP3_CTESTS.glob('-gr.*'))
    # .bpgr files
    grammars.extend(BP3_CTESTS.glob('*.bpgr'))
    return sorted(grammars)


def extract_grammar_name(path: Path) -> str:
    """Extract the grammar name from path."""
    name = path.name
    if name.startswith('-gr.'):
        return name[4:]
    elif name.endswith('.bpgr'):
        return name[:-5]
    return name


def transpile_grammar(grammar_path: Path) -> dict:
    """Transpile a grammar and return results."""
    result = {
        'path': str(grammar_path),
        'name': extract_grammar_name(grammar_path),
        'parse_ok': False,
        'emit_ok': False,
        'warnings': [],
        'warning_count': 0,
        'sc_content': None,
        'error': None,
    }

    try:
        ast = parse_file(str(grammar_path))
        result['parse_ok'] = True

        sc_content, warnings = emit_scd_with_warnings(ast)
        result['emit_ok'] = True
        result['sc_content'] = sc_content
        result['warnings'] = [{'category': w.category, 'message': w.message} for w in warnings]
        result['warning_count'] = len(warnings)

    except Exception as e:
        result['error'] = str(e)

    return result


def extract_midi_notes(midi_path: Path) -> list[int]:
    """Extract note numbers from MIDI file."""
    if not MIDO_AVAILABLE:
        return []

    try:
        mid = mido.MidiFile(str(midi_path))
        notes = []
        for track in mid.tracks:
            for msg in track:
                if msg.type == 'note_on' and msg.velocity > 0:
                    notes.append(msg.note)
        return notes
    except Exception:
        return []


def trace_sc_output(sc_content: str, start_symbol: str = "S") -> list[int]:
    """Trace SC output and extract note numbers."""
    if not SCLANG_AVAILABLE:
        return []

    try:
        events = trace_scd_content(sc_content, start_symbol=start_symbol,
                                   max_events=300, timeout=30.0)
        notes = [int(e.midinote) for e in events
                 if e.type == 'note' and e.midinote is not None]
        return notes
    except Exception:
        return []


def analyze_grammar(grammar_path: Path, trace_sc: bool = False) -> dict:
    """Full analysis of a single grammar."""
    result = transpile_grammar(grammar_path)
    name = result['name']

    # Check for MIDI reference
    midi_ref = MIDI_REFS.get(name)
    if midi_ref and midi_ref.exists():
        result['midi_ref'] = str(midi_ref)
        result['midi_notes'] = extract_midi_notes(midi_ref)
        result['midi_unique'] = sorted(set(result['midi_notes']))
    else:
        result['midi_ref'] = None
        result['midi_notes'] = []
        result['midi_unique'] = []

    # Trace SC output if requested and available
    if trace_sc and result['sc_content'] and SCLANG_AVAILABLE:
        result['sc_notes'] = trace_sc_output(result['sc_content'])
        result['sc_unique'] = sorted(set(result['sc_notes']))
    else:
        result['sc_notes'] = []
        result['sc_unique'] = []

    # Compare if both available
    if result['midi_unique'] and result['sc_unique']:
        midi_set = set(result['midi_unique'])
        sc_set = set(result['sc_unique'])
        result['sets_match'] = midi_set == sc_set
        result['only_in_midi'] = sorted(midi_set - sc_set)
        result['only_in_sc'] = sorted(sc_set - midi_set)
    else:
        result['sets_match'] = None
        result['only_in_midi'] = []
        result['only_in_sc'] = []

    return result


def categorize_warnings(warnings: list[dict]) -> dict[str, int]:
    """Categorize warnings by type."""
    counts = Counter(w['category'] for w in warnings)
    return dict(counts)


def main():
    print("=" * 80)
    print("BP3 Grammar Comprehensive Analysis")
    print("=" * 80)
    print(f"mido available: {MIDO_AVAILABLE}")
    print(f"sclang available: {SCLANG_AVAILABLE}")
    print()

    grammars = get_all_grammars()
    print(f"Found {len(grammars)} grammar files")
    print()

    # Process all grammars
    results = []
    total_warnings = 0
    warning_cats = Counter()

    for gpath in grammars:
        name = extract_grammar_name(gpath)
        # Only trace SC for grammars with MIDI refs (to save time)
        trace = name in MIDI_REFS

        result = analyze_grammar(gpath, trace_sc=trace)
        results.append(result)

        total_warnings += result['warning_count']
        for w in result['warnings']:
            warning_cats[w['category']] += 1

        # Status indicator
        status = "✓" if result['parse_ok'] and result['emit_ok'] else "✗"
        warn_str = f"({result['warning_count']} warnings)" if result['warning_count'] > 0 else ""
        midi_str = "📀" if result['midi_ref'] else ""
        match_str = ""
        if result['sets_match'] is not None:
            match_str = "🎵✓" if result['sets_match'] else "🎵✗"

        print(f"{status} {name:40} {warn_str:20} {midi_str} {match_str}")

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    parse_ok = sum(1 for r in results if r['parse_ok'])
    emit_ok = sum(1 for r in results if r['emit_ok'])
    with_midi = sum(1 for r in results if r['midi_ref'])

    print(f"Total grammars:     {len(grammars)}")
    print(f"Parse successful:   {parse_ok}/{len(grammars)}")
    print(f"Emit successful:    {emit_ok}/{len(grammars)}")
    print(f"With MIDI refs:     {with_midi}")
    print(f"Total warnings:     {total_warnings}")
    print()

    print("Warnings by category:")
    for cat, count in sorted(warning_cats.items(), key=lambda x: -x[1]):
        print(f"  {cat:25} {count:4}")

    # MIDI comparison results
    print()
    print("MIDI Comparison Results:")
    for r in results:
        if r['midi_ref']:
            name = r['name']
            if r['sets_match'] is None:
                status = "⚠️  Could not trace SC"
            elif r['sets_match']:
                status = "✅ Note sets MATCH"
            else:
                status = f"❌ MISMATCH - MIDI only: {r['only_in_midi']}, SC only: {r['only_in_sc']}"
            print(f"  {name:20} {status}")

    # Save detailed results
    output_path = BASE_DIR / 'docs' / 'grammar_analysis_results.json'
    # Simplify for JSON (remove large content)
    json_results = []
    for r in results:
        jr = {k: v for k, v in r.items() if k != 'sc_content'}
        jr['warnings'] = categorize_warnings(r['warnings'])
        json_results.append(jr)

    with open(output_path, 'w') as f:
        json.dump({
            'total_grammars': len(grammars),
            'parse_ok': parse_ok,
            'emit_ok': emit_ok,
            'total_warnings': total_warnings,
            'warning_categories': dict(warning_cats),
            'grammars': json_results,
        }, f, indent=2)

    print()
    print(f"Detailed results saved to: {output_path}")


if __name__ == '__main__':
    main()
