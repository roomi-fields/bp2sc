"""Scale mapping for BP3 _scale() function to SuperCollider Scale/Tuning.

This module resolves BP3 scale names to SC Scale/Tuning classes with root notes.
The mapping data is loaded from data/scale_map.json.

BP3 scale names fall into three categories:
1. Key-quality scales (Cmaj, Dmin, F#min) - parsed by regex
2. Tunings (just intonation, piano, meantone_classic) - lookup table
3. Ragas (todi_ka_3, grama) - lookup table
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Load the mapping data from JSON
_DATA_FILE = Path(__file__).parent / "data" / "scale_map.json"
_SCALE_DATA: dict = {}

def _load_data() -> dict:
    """Load scale mapping data from JSON file."""
    global _SCALE_DATA
    if not _SCALE_DATA:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            _SCALE_DATA = json.load(f)
    return _SCALE_DATA


# Regex for key-quality scale names: C, D, E, F, G, A, B with optional #/b and maj/min
# Examples: Cmaj, Dmin, F#min, Bbmaj
_RE_KEY_QUALITY = re.compile(r'^([A-G])([#b]?)(?:maj|min)$', re.IGNORECASE)

# Note name to semitone offset from C
_NOTE_SEMITONES = {
    'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11
}


def _note_to_root(note: str, accidental: str) -> int:
    """Convert a note name to root offset (0-11)."""
    base = _NOTE_SEMITONES.get(note.upper(), 0)
    if accidental == '#':
        base = (base + 1) % 12
    elif accidental == 'b':
        base = (base - 1) % 12
    return base


def parse_root_arg(arg: str) -> int:
    """Parse a root argument to a semitone offset (0-11).

    Supports multiple conventions:
    - Anglo: C4, D#5, Bb3 -> note to semitone offset
    - French: dop4, rep4, mip4 -> note to semitone offset
    - Indian: sa_4, ri_4, ga_4 -> note to semitone offset
    - Numeric: 0-11 direct offset

    The octave number is ignored; only the pitch class matters.
    """
    arg = arg.strip()

    # Numeric
    if arg.isdigit() or (arg.startswith('-') and arg[1:].isdigit()):
        return int(arg) % 12

    # Anglo notation: C4, D#5, Bb3
    m = re.match(r'^([A-G])([#b]?)(\d)?$', arg, re.IGNORECASE)
    if m:
        note, accidental = m.group(1).upper(), m.group(2) or ''
        return _note_to_root(note, accidental)

    # French solfege: dop4, rep4, mip4, fap4, solp4, lap4, sip4
    # (p = dièse/sharp in BP3 convention)
    french_map = {
        'do': 0, 'dop': 1, 'dod': 1, 'dob': 11,
        're': 2, 'rep': 3, 'red': 3, 'reb': 1,
        'mi': 4, 'mip': 5, 'mid': 5, 'mib': 3,
        'fa': 5, 'fap': 6, 'fad': 6, 'fab': 4,
        'sol': 7, 'solp': 8, 'sold': 8, 'solb': 6,
        'la': 9, 'lap': 10, 'lad': 10, 'lab': 8,
        'si': 11, 'sip': 0, 'sid': 0, 'sib': 10,
    }
    # Remove trailing digit(s)
    note_part = re.sub(r'\d+$', '', arg.lower())
    if note_part in french_map:
        return french_map[note_part]

    # Indian solfege: sa_4, ri_4, ga_4, ma_4, pa_4, dha_4, ni_4
    indian_map = {
        'sa': 0, 'ri': 2, 'ga': 4, 'ma': 5, 'pa': 7, 'dha': 9, 'ni': 11
    }
    # Remove trailing _N
    note_part = re.sub(r'_\d+$', '', arg.lower())
    if note_part in indian_map:
        return indian_map[note_part]

    # Default: C = 0
    return 0


def resolve_scale(name: str, root_arg: str = "0") -> dict[str, str]:
    """Resolve a BP3 scale name to SC Scale/Tuning with root.

    Args:
        name: The scale name (e.g., "Cmaj", "just intonation", "todi_ka_4")
        root_arg: The root note argument (e.g., "C4", "0", "sa_4")

    Returns:
        A dict with keys:
        - "scale" or "tuning": The SC class (e.g., "Scale.major", "Tuning.just")
        - "root": The root offset (0-11 as string)
        - "_unknown": "true" if the scale was not recognized (optional)
    """
    data = _load_data()
    name_lower = name.lower().strip()

    # 1. Check key-quality scales (Cmaj, Dmin, F#min, etc.)
    m = _RE_KEY_QUALITY.match(name)
    if m:
        note, accidental = m.group(1).upper(), m.group(2) or ''
        root = _note_to_root(note, accidental)
        scale_type = "Scale.major" if "maj" in name.lower() else "Scale.minor"
        return {"scale": scale_type, "root": str(root)}

    # 2. Check tunings lookup
    if name_lower in data.get("tunings", {}):
        tuning = data["tunings"][name_lower]
        root = parse_root_arg(root_arg)
        return {"tuning": tuning, "root": str(root)}

    # 3. Check ragas lookup
    if name_lower in data.get("ragas", {}):
        scale = data["ragas"][name_lower]
        root = parse_root_arg(root_arg)
        return {"scale": scale, "root": str(root)}

    # 4. Fallback: chromatic with warning flag
    root = parse_root_arg(root_arg)
    return {"scale": "Scale.chromatic", "root": str(root), "_unknown": "true"}
