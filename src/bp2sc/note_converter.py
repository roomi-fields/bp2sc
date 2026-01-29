"""Convert BP3 note names to MIDI note numbers.

Supports three naming conventions:
- French solfege: do, re, mi, fa, sol, la, si (+ octave)
- Indian sargam: sa, re, ga, ma, pa, dha, ni (+ octave)
- Anglo/English: C, D, E, F, G, A, B (+ optional accidental + octave)

Octave conventions (verified against BP3 MIDI output):
- French: MIDI = (octave + 1) * 12 + semitone  → do4 = 60
- English: MIDI = (octave + 1) * 12 + semitone → C4 = 60
- Indian:  MIDI = (octave + 1) * 12 + semitone → sa4 = 60

All conventions use the same formula in BP3: (octave + 1) * 12 + semitone.
Note: In music theory, French do3 = English C4, but BP3 uses unified numbering.

Note: BP3's C4key setting (default 60) can shift all mappings by
(C4key - 60) semitones. This is not handled here; callers should
apply that offset separately if needed.
"""

from __future__ import annotations

# --- French solfege (do = C) ---
_FR_BASE: dict[str, int] = {
    "do": 0, "re": 2, "mi": 4, "fa": 5,
    "sol": 7, "la": 9, "si": 11,
    # With accidentals
    "dob": -1, "do#": 1,
    "reb": 1, "re#": 3,
    "mib": 3, "mi#": 5,
    "fab": 4, "fa#": 6,
    "solb": 6, "sol#": 8,
    "lab": 8, "la#": 10,
    "sib": 10, "si#": 0,
}

# --- Indian sargam (sa = C in default tuning) ---
_INDIAN_BASE: dict[str, int] = {
    "sa": 0, "re": 2, "ga": 4, "ma": 5,
    "pa": 7, "dha": 9, "ni": 11,
}

# --- Anglo (C = 0) ---
_ANGLO_BASE: dict[str, int] = {
    "C": 0, "D": 2, "E": 4, "F": 5,
    "G": 7, "A": 9, "B": 11,
    "C#": 1, "Db": 1, "D#": 3, "Eb": 3,
    "E#": 5, "Fb": 4, "F#": 6, "Gb": 6,
    "G#": 8, "Ab": 8, "A#": 10, "Bb": 10,
    "B#": 0, "Cb": -1,
}

# Detect convention from note name
_FR_NAMES = set(_FR_BASE.keys())
_INDIAN_NAMES = set(_INDIAN_BASE.keys())
_ANGLO_NAMES = set(_ANGLO_BASE.keys())


def note_to_midi(name: str, octave: int, base_octave: int = 4) -> int:
    """Convert a note name + octave to a MIDI note number.

    Args:
        name: Note name (e.g., "do", "sa", "C", "sib", "F#")
        octave: Octave number from the BP3 file
        base_octave: Octave offset for MIDI mapping. Default 4 means
                     octave 4 = MIDI 60 (middle C).

    Returns:
        MIDI note number (0-127)
    """
    # Try French solfege first
    # All conventions use (octave + 1) * 12 in BP3: do4 = C4 = 60
    if name.lower() in _FR_BASE:
        semitone = _FR_BASE[name.lower()]
        return (octave + 1) * 12 + semitone

    # Try Indian sargam
    if name.lower() in _INDIAN_BASE:
        semitone = _INDIAN_BASE[name.lower()]
        # Indian octave numbering: in mohanam, sa6 corresponds roughly to C5 (MIDI 72)
        # BP3 Indian convention: sa4 = C4 = 60 by default
        # But in trial.mohanam, notes use octave 6-7 range
        return (octave + 1) * 12 + semitone

    # Try Anglo
    if name in _ANGLO_BASE:
        semitone = _ANGLO_BASE[name]
        return (octave + 1) * 12 + semitone

    raise ValueError(f"Unknown note name: {name!r}")


def detect_convention(names: list[str]) -> str:
    """Detect the naming convention from a list of note names.

    Returns: "french", "indian", "anglo", or "unknown"
    """
    lower_names = {n.lower() for n in names}

    # Check for distinctly French names
    french_only = {"do", "sol", "si", "sib", "fa"}
    if lower_names & french_only:
        return "french"

    # Check for distinctly Indian names
    indian_only = {"sa", "ga", "ma", "pa", "dha", "ni"}
    if lower_names & indian_only:
        return "indian"

    # Check for Anglo
    anglo_names = {n for n in names if n[0:1].isupper()}
    if anglo_names:
        return "anglo"

    return "unknown"
