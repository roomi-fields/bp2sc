#!/usr/bin/env python3
"""Compare MIDI output of SC transpiler against BP3 reference for Ruwet grammar."""

import sys
sys.path.insert(0, '/mnt/d/Claude/BP2SC/tests')
sys.path.insert(0, '/mnt/d/Claude/BP2SC/src')

# -- Step 1: Extract BP3 reference notes from MIDI --
print("=" * 60)
print("STEP 1: BP3 Reference MIDI")
print("=" * 60)

import mido

mid = mido.MidiFile('/mnt/d/Claude/BP2SC/tools/ref_ruwet.mid')
bp3_notes = []
for track in mid.tracks:
    for msg in track:
        if msg.type == 'note_on' and msg.velocity > 0:
            bp3_notes.append(msg.note)

print(f"BP3 notes ({len(bp3_notes)}): {bp3_notes[:30]}")
print(f"BP3 unique: {sorted(set(bp3_notes))}")

# -- Step 2: Extract SC notes via sclang tracer --
print()
print("=" * 60)
print("STEP 2: SC Transpiler Output")
print("=" * 60)

from sclang_trace import trace_scd_file

events = trace_scd_file('/mnt/d/Claude/BP2SC/output_ruwet.scd')
sc_notes = [int(e.midinote) for e in events if hasattr(e, 'midinote') and getattr(e, 'type', None) != 'rest']

print(f"SC notes ({len(sc_notes)}): {sc_notes[:30]}")
print(f"SC unique: {sorted(set(sc_notes))}")

# -- Step 3: Compare --
print()
print("=" * 60)
print("STEP 3: Comparison")
print("=" * 60)

bp3_set = sorted(set(bp3_notes))
sc_set = sorted(set(sc_notes))

print(f"BP3 unique notes: {bp3_set}")
print(f"SC unique notes:  {sc_set}")
print(f"Sets match: {bp3_set == sc_set}")

print()
print(f"BP3 count: {len(bp3_notes)}")
print(f"SC count:  {len(sc_notes)}")
print(f"Count match: {len(bp3_notes) == len(sc_notes)}")

# Detailed diff if sets don't match
if bp3_set != sc_set:
    only_bp3 = sorted(set(bp3_notes) - set(sc_notes))
    only_sc = sorted(set(sc_notes) - set(bp3_notes))
    if only_bp3:
        print(f"\nNotes ONLY in BP3 (missing from SC): {only_bp3}")
    if only_sc:
        print(f"\nNotes ONLY in SC (extra):            {only_sc}")

# Note: Ruwet is a RND grammar, so sequences will differ.
# We can only compare the unique note SETS and verify they match.
print()
print("NOTE: Ruwet uses a RND grammar, so note sequences will differ")
print("      between runs. Only the unique note SETS should match.")
