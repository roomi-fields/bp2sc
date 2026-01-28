#!/usr/bin/env python3
"""Compare temporal aspects (timing, durations) between BP3 MIDI and SC transpiler output.

Extracts and compares:
  - Note-on MIDI numbers
  - Delta times (ticks between events)
  - Note durations (note_on -> note_off)
  - Tempo and ticks_per_beat
  - SC dur/stretch values
  - Total piece duration in both representations
"""

import sys
import statistics
from collections import Counter

sys.path.insert(0, '/mnt/d/Claude/BP2SC/tests')
sys.path.insert(0, '/mnt/d/Claude/BP2SC/src')

import mido
from sclang_trace import trace_scd_file, sclang_available

# ==============================================================================
# PART 1: BP3 MIDI Analysis
# ==============================================================================

print("=" * 80)
print("PART 1: BP3 Reference MIDI Analysis")
print("=" * 80)

midi_path = '/mnt/d/Claude/BP2SC/tools/ref_ruwet.mid'
mid = mido.MidiFile(midi_path)

ticks_per_beat = mid.ticks_per_beat
print(f"\nTicks per beat: {ticks_per_beat}")
print(f"Number of tracks: {len(mid.tracks)}")
print(f"MIDI type: {mid.type}")

# Collect tempo changes
tempos = []
for track in mid.tracks:
    for msg in track:
        if msg.type == 'set_tempo':
            tempos.append(msg.tempo)  # microseconds per beat
            bpm = mido.tempo2bpm(msg.tempo)
            print(f"Tempo: {msg.tempo} us/beat = {bpm:.2f} BPM")

if not tempos:
    print("No tempo event found; default = 500000 us/beat = 120 BPM")
    tempos = [500000]

tempo_us = tempos[0]  # use first tempo
seconds_per_tick = tempo_us / 1_000_000 / ticks_per_beat
seconds_per_beat = tempo_us / 1_000_000
print(f"Seconds per beat: {seconds_per_beat}")
print(f"Seconds per tick: {seconds_per_tick}")

# --- Detailed per-track dump ---
for i, track in enumerate(mid.tracks):
    print(f"\n--- Track {i}: {track.name!r} ({len(track)} messages) ---")
    for msg in track:
        print(f"  {msg}")

# --- Extract notes with delta times ---
print("\n--- Note Extraction ---")

# We'll merge all tracks into a single timeline
note_ons = []   # (absolute_tick, midi_note, velocity, track)
note_offs = []  # (absolute_tick, midi_note, track)

for tidx, track in enumerate(mid.tracks):
    abs_tick = 0
    for msg in track:
        abs_tick += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            note_ons.append((abs_tick, msg.note, msg.velocity, tidx))
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            note_offs.append((abs_tick, msg.note, tidx))

note_ons.sort(key=lambda x: x[0])
note_offs.sort(key=lambda x: x[0])

print(f"Total note_on events: {len(note_ons)}")
print(f"Total note_off events: {len(note_offs)}")

# --- Compute note durations ---
# Match each note_on with the next note_off of the same pitch
used_offs = set()
notes_with_dur = []  # (onset_tick, midi_note, duration_ticks, velocity)

for on_tick, on_note, vel, on_track in note_ons:
    best_off = None
    best_idx = None
    for j, (off_tick, off_note, off_track) in enumerate(note_offs):
        if j in used_offs:
            continue
        if off_note == on_note and off_tick >= on_tick:
            best_off = off_tick
            best_idx = j
            break
    if best_off is not None:
        dur_ticks = best_off - on_tick
        notes_with_dur.append((on_tick, on_note, dur_ticks, vel))
        used_offs.add(best_idx)
    else:
        notes_with_dur.append((on_tick, on_note, None, vel))
        print(f"  WARNING: No note_off found for note {on_note} at tick {on_tick}")

# --- Compute delta times between consecutive note_ons ---
deltas_ticks = []
for i in range(1, len(notes_with_dur)):
    delta = notes_with_dur[i][0] - notes_with_dur[i - 1][0]
    deltas_ticks.append(delta)

# --- Print each note ---
print(f"\n{'#':>4} {'Onset(tick)':>12} {'MIDI':>5} {'Dur(tick)':>10} {'Dur(s)':>8} {'Delta(tick)':>12} {'Delta(s)':>9}")
print("-" * 75)
for i, (onset, note, dur, vel) in enumerate(notes_with_dur):
    dur_s = dur * seconds_per_tick if dur is not None else None
    delta_t = deltas_ticks[i - 1] if i > 0 else None
    delta_s = delta_t * seconds_per_tick if delta_t is not None else None

    dur_str = f"{dur:>10}" if dur is not None else "       N/A"
    dur_s_str = f"{dur_s:>8.4f}" if dur_s is not None else "     N/A"
    delta_str = f"{delta_t:>12}" if delta_t is not None else "           -"
    delta_s_str = f"{delta_s:>9.4f}" if delta_s is not None else "        -"

    print(f"{i:>4} {onset:>12} {note:>5} {dur_str} {dur_s_str} {delta_str} {delta_s_str}")

# --- Summary statistics ---
print("\n--- BP3 MIDI Duration Statistics ---")
durations_ticks = [d for (_, _, d, _) in notes_with_dur if d is not None]
durations_seconds = [d * seconds_per_tick for d in durations_ticks]

print(f"Number of notes: {len(notes_with_dur)}")
print(f"Unique MIDI notes: {sorted(set(n for _, n, _, _ in notes_with_dur))}")

if durations_ticks:
    print(f"\nNote durations (ticks):")
    print(f"  Min:    {min(durations_ticks)}")
    print(f"  Max:    {max(durations_ticks)}")
    print(f"  Mean:   {statistics.mean(durations_ticks):.2f}")
    print(f"  Median: {statistics.median(durations_ticks):.2f}")
    print(f"  Stdev:  {statistics.stdev(durations_ticks):.2f}" if len(durations_ticks) > 1 else "  Stdev:  N/A")

    dur_counts = Counter(durations_ticks)
    print(f"  Distribution: {dict(sorted(dur_counts.items()))}")

    print(f"\nNote durations (seconds):")
    print(f"  Min:    {min(durations_seconds):.4f}")
    print(f"  Max:    {max(durations_seconds):.4f}")
    print(f"  Mean:   {statistics.mean(durations_seconds):.4f}")
    print(f"  Median: {statistics.median(durations_seconds):.4f}")

    dur_s_counts = Counter(round(d, 4) for d in durations_seconds)
    print(f"  Distribution (s): {dict(sorted(dur_s_counts.items()))}")

print(f"\nDelta times between note onsets (ticks):")
if deltas_ticks:
    print(f"  Min:    {min(deltas_ticks)}")
    print(f"  Max:    {max(deltas_ticks)}")
    print(f"  Mean:   {statistics.mean(deltas_ticks):.2f}")
    print(f"  Median: {statistics.median(deltas_ticks):.2f}")
    delta_counts = Counter(deltas_ticks)
    print(f"  Distribution: {dict(sorted(delta_counts.items()))}")

    deltas_seconds = [d * seconds_per_tick for d in deltas_ticks]
    print(f"\nDelta times between note onsets (seconds):")
    print(f"  Min:    {min(deltas_seconds):.4f}")
    print(f"  Max:    {max(deltas_seconds):.4f}")
    print(f"  Mean:   {statistics.mean(deltas_seconds):.4f}")
    delta_s_counts = Counter(round(d, 4) for d in deltas_seconds)
    print(f"  Distribution (s): {dict(sorted(delta_s_counts.items()))}")

# Total duration
if notes_with_dur:
    last_onset = notes_with_dur[-1][0]
    last_dur = notes_with_dur[-1][2] or 0
    total_ticks = last_onset + last_dur
    total_seconds_midi = total_ticks * seconds_per_tick
    print(f"\nTotal piece duration (MIDI):")
    print(f"  Last onset tick: {last_onset}")
    print(f"  Last note dur:   {last_dur} ticks")
    print(f"  Total ticks:     {total_ticks}")
    print(f"  Total seconds:   {total_seconds_midi:.4f}")
    print(f"  Total time:      {total_seconds_midi/60:.1f} min or {total_seconds_midi:.2f} s")

# Are durations uniform?
print(f"\nAre durations uniform?")
if len(set(durations_ticks)) == 1:
    print(f"  YES - all notes have duration {durations_ticks[0]} ticks = {durations_ticks[0] * seconds_per_tick:.4f} s")
else:
    print(f"  NO - {len(set(durations_ticks))} distinct durations found")
    for d, cnt in sorted(Counter(durations_ticks).items()):
        print(f"    {d} ticks ({d * seconds_per_tick:.4f} s): {cnt} notes")

print(f"\nAre inter-onset deltas uniform?")
if len(set(deltas_ticks)) == 1:
    print(f"  YES - all deltas are {deltas_ticks[0]} ticks = {deltas_ticks[0] * seconds_per_tick:.4f} s")
else:
    print(f"  NO - {len(set(deltas_ticks))} distinct deltas found")
    for d, cnt in sorted(Counter(deltas_ticks).items()):
        print(f"    {d} ticks ({d * seconds_per_tick:.4f} s): {cnt} notes")


# ==============================================================================
# PART 2: SC Output Analysis via sclang trace
# ==============================================================================

print("\n" + "=" * 80)
print("PART 2: SuperCollider Output Analysis (sclang trace)")
print("=" * 80)

scd_path = '/mnt/d/Claude/BP2SC/output_ruwet.scd'

if not sclang_available():
    print("\nWARNING: sclang not available. Performing static analysis only.\n")
    # Fallback: static analysis of the .scd file
    with open(scd_path, 'r') as f:
        scd_content = f.read()

    print("Static analysis of .scd file (no sclang execution):")
    print("Cannot determine actual event sequence without sclang.")
    print("Skipping to comparison based on code structure analysis.")
    sc_events = None
else:
    print(f"\nsclang found. Tracing {scd_path}...")
    try:
        sc_events = trace_scd_file(scd_path, start_symbol="S", max_events=500, timeout=60.0)
        print(f"Traced {len(sc_events)} events.\n")
    except Exception as e:
        print(f"ERROR tracing: {e}")
        sc_events = None

if sc_events is not None and len(sc_events) > 0:
    print(f"{'#':>4} {'Type':>6} {'MIDI':>6} {'dur':>8} {'stretch':>8} {'eff_dur':>8}")
    print("-" * 50)

    sc_midinotes = []
    sc_durs = []
    sc_stretches = []
    sc_effective_durs = []

    for ev in sc_events:
        midi_str = f"{ev.midinote:>6.1f}" if ev.midinote is not None else "   N/A"
        dur_val = ev.dur if ev.dur is not None else 0
        stretch_val = ev.stretch if ev.stretch is not None else 1.0
        eff_dur = dur_val * stretch_val

        print(f"{ev.index:>4} {ev.type:>6} {midi_str} {dur_val:>8.4f} {stretch_val:>8.4f} {eff_dur:>8.4f}")

        if ev.type == "note" and ev.midinote is not None:
            sc_midinotes.append(ev.midinote)
        sc_durs.append(dur_val)
        sc_stretches.append(stretch_val)
        sc_effective_durs.append(eff_dur)

    # SC statistics
    print(f"\n--- SC Duration Statistics ---")
    print(f"Number of events: {len(sc_events)}")
    print(f"Note events: {sum(1 for e in sc_events if e.type == 'note')}")
    print(f"Rest events: {sum(1 for e in sc_events if e.type == 'rest')}")

    print(f"\nUnique MIDI notes: {sorted(set(sc_midinotes))}")

    if sc_durs:
        print(f"\nRaw dur values:")
        print(f"  Min:  {min(sc_durs):.4f}")
        print(f"  Max:  {max(sc_durs):.4f}")
        print(f"  Distribution: {dict(sorted(Counter(round(d, 4) for d in sc_durs).items()))}")

    if sc_stretches:
        print(f"\nStretch values:")
        print(f"  Distribution: {dict(sorted(Counter(round(s, 4) for s in sc_stretches).items()))}")

    if sc_effective_durs:
        print(f"\nEffective durations (dur * stretch):")
        print(f"  Min:  {min(sc_effective_durs):.4f}")
        print(f"  Max:  {max(sc_effective_durs):.4f}")
        print(f"  Mean: {statistics.mean(sc_effective_durs):.4f}")
        eff_counts = Counter(round(d, 4) for d in sc_effective_durs)
        print(f"  Distribution: {dict(sorted(eff_counts.items()))}")

    # Total SC duration (sum of effective durs = total time in beats)
    total_sc_beats = sum(sc_effective_durs)
    # Default SC tempo is 60 BPM (1 beat = 1 second) unless TempoClock is set
    total_sc_seconds_default = total_sc_beats  # at 60 BPM (default TempoClock)
    # If we match BP3 tempo:
    total_sc_seconds_bp3tempo = total_sc_beats * seconds_per_beat

    print(f"\nTotal SC duration (sum of effective durs): {total_sc_beats:.4f} beats")
    print(f"  At default SC tempo (60 BPM = 1 beat/s): {total_sc_seconds_default:.4f} s")
    print(f"  At BP3 tempo ({mido.tempo2bpm(tempo_us):.1f} BPM): {total_sc_seconds_bp3tempo:.4f} s")


# ==============================================================================
# PART 3: Comparison
# ==============================================================================

print("\n" + "=" * 80)
print("PART 3: Comparison BP3 MIDI vs SC Transpiler")
print("=" * 80)

# --- Note count ---
bp3_count = len(notes_with_dur)
print(f"\nNote count:")
print(f"  BP3 MIDI:  {bp3_count}")
if sc_events is not None:
    sc_count = sum(1 for e in sc_events if e.type == 'note')
    print(f"  SC output: {sc_count}")
    if bp3_count == sc_count:
        print(f"  => MATCH")
    else:
        print(f"  => MISMATCH (difference: {abs(bp3_count - sc_count)})")

# --- MIDI notes comparison ---
bp3_notes = [n for _, n, _, _ in notes_with_dur]
if sc_events is not None and sc_midinotes:
    print(f"\nMIDI note sequences:")
    print(f"  BP3: {bp3_notes}")
    print(f"  SC:  {[int(n) for n in sc_midinotes]}")
    if bp3_notes == [int(n) for n in sc_midinotes]:
        print(f"  => EXACT MATCH")
    else:
        # They might differ due to random choices in the grammar.
        # Compare sets and distributions instead.
        bp3_set = set(bp3_notes)
        sc_set = set(int(n) for n in sc_midinotes)
        print(f"  BP3 pitch set: {sorted(bp3_set)}")
        print(f"  SC pitch set:  {sorted(sc_set)}")
        if bp3_set == sc_set:
            print(f"  => Same pitch vocabulary (sequences differ due to stochastic grammar)")
        else:
            print(f"  => Different pitch vocabularies!")
            print(f"     Only in BP3: {sorted(bp3_set - sc_set)}")
            print(f"     Only in SC:  {sorted(sc_set - bp3_set)}")

# --- Duration comparison ---
print(f"\nDuration analysis:")
print(f"  BP3 MIDI note durations are {'UNIFORM' if len(set(durations_ticks)) == 1 else 'VARIABLE'}:")
if len(set(durations_ticks)) == 1:
    bp3_dur_s = durations_ticks[0] * seconds_per_tick
    print(f"    All notes: {durations_ticks[0]} ticks = {bp3_dur_s:.4f} s")
else:
    for d, cnt in sorted(Counter(durations_ticks).items()):
        print(f"    {d} ticks ({d * seconds_per_tick:.4f} s): {cnt} notes")

print(f"\n  BP3 MIDI inter-onset deltas are {'UNIFORM' if len(set(deltas_ticks)) == 1 else 'VARIABLE'}:")
if len(set(deltas_ticks)) == 1:
    bp3_delta_s = deltas_ticks[0] * seconds_per_tick
    print(f"    All deltas: {deltas_ticks[0]} ticks = {bp3_delta_s:.4f} s")
    print(f"    This equals {deltas_ticks[0] / ticks_per_beat:.4f} beats")
else:
    for d, cnt in sorted(Counter(deltas_ticks).items()):
        frac = d / ticks_per_beat
        print(f"    {d} ticks ({d * seconds_per_tick:.4f} s = {frac:.4f} beats): {cnt} occurrences")

if sc_events is not None and sc_effective_durs:
    print(f"\n  SC effective durations (dur * stretch):")
    for d, cnt in sorted(Counter(round(d, 4) for d in sc_effective_durs).items()):
        print(f"    {d:.4f} beats: {cnt} events")

    # Check if SC durs match BP3 inter-onset deltas
    print(f"\n  Do SC durs match BP3 inter-onset deltas?")
    if deltas_ticks:
        bp3_delta_beats = [d / ticks_per_beat for d in deltas_ticks]
        bp3_unique_delta_beats = sorted(set(round(d, 4) for d in bp3_delta_beats))
        sc_unique_eff_durs = sorted(set(round(d, 4) for d in sc_effective_durs))
        print(f"    BP3 unique delta (beats): {bp3_unique_delta_beats}")
        print(f"    SC unique eff dur (beats): {sc_unique_eff_durs}")

        if bp3_unique_delta_beats == sc_unique_eff_durs:
            print(f"    => MATCH: same duration vocabulary")
        else:
            print(f"    => Values differ. Checking ratios...")
            # Maybe there's a scaling factor
            if len(bp3_unique_delta_beats) == 1 and len(sc_unique_eff_durs) == 1:
                ratio = sc_unique_eff_durs[0] / bp3_unique_delta_beats[0]
                print(f"    Ratio SC/BP3 = {ratio:.4f}")

# --- Total duration ---
print(f"\nTotal piece duration:")
if notes_with_dur:
    print(f"  BP3 MIDI: {total_seconds_midi:.4f} s ({total_seconds_midi:.2f} s)")
if sc_events is not None and sc_effective_durs:
    print(f"  SC (at default 60 BPM):  {total_sc_seconds_default:.4f} s")
    print(f"  SC (at BP3 BPM {mido.tempo2bpm(tempo_us):.1f}): {total_sc_seconds_bp3tempo:.4f} s")

    # What tempo would make SC match BP3?
    if total_sc_beats > 0:
        needed_beat_dur = total_seconds_midi / total_sc_beats
        needed_bpm = 60.0 / needed_beat_dur
        print(f"\n  To match BP3 total duration in SC:")
        print(f"    Needed beat duration: {needed_beat_dur:.4f} s")
        print(f"    Needed BPM: {needed_bpm:.2f}")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
