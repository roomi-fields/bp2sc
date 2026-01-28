"""Parser for BP3 settings (-se.*) files.

BP3 -se.* files are JSON documents containing project settings like:
- NoteConvention: 0=English, 1=French, 2=Indian
- Pclock/Qclock: metronome period (tempo)
- DeftVelocity: default MIDI velocity
- C4key: MIDI key number for middle C
- A4freq: tuning frequency for A4
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BP3Settings:
    """Parsed BP3 settings from a -se.* file."""
    name: str

    # Note convention: 0=English, 1=French, 2=Indian, 3=Keys, 4=Tonal
    note_convention: int = 1  # Default: French

    # Tempo: Pclock/Qclock gives period in seconds
    pclock: float = 15.0
    qclock: float = 22.0

    # MIDI defaults
    default_velocity: int = 64
    default_volume: int = 90

    # Pitch reference
    c4_key: int = 60  # MIDI note for middle C
    a4_freq: float = 440.0  # Hz

    # Time settings
    quantization: int = 10  # ms
    striated_time: bool = True

    @property
    def tempo_bpm(self) -> float:
        """Calculate tempo in BPM from Pclock/Qclock.

        Period = Pclock/Qclock seconds per beat
        BPM = 60 / period
        """
        if self.qclock == 0:
            return 60.0
        period = self.pclock / self.qclock
        if period <= 0:
            return 60.0
        return 60.0 / period

    @property
    def convention_name(self) -> str:
        """Human-readable name for note convention."""
        names = {
            0: "English (C, D, E...)",
            1: "French (do, re, mi...)",
            2: "Indian (sa, re, ga...)",
            3: "Keys",
            4: "Tonal scales",
        }
        return names.get(self.note_convention, "Unknown")


def _get_value(data: dict, key: str, default: Any = None) -> Any:
    """Extract value from BP3 settings structure."""
    if key not in data:
        return default
    entry = data[key]
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def parse_settings_file(path: str | Path) -> BP3Settings:
    """Parse a BP3 settings file.

    Args:
        path: Path to the -se.* file

    Returns:
        BP3Settings with extracted values
    """
    path = Path(path)
    name = path.name
    if name.startswith("-se."):
        name = name[4:]

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    settings = BP3Settings(name=name)

    # Note convention
    val = _get_value(data, "NoteConvention")
    if val is not None:
        try:
            settings.note_convention = int(val)
        except (ValueError, TypeError):
            pass

    # Tempo (Pclock/Qclock)
    val = _get_value(data, "Pclock")
    if val is not None:
        try:
            settings.pclock = float(val)
        except (ValueError, TypeError):
            pass

    val = _get_value(data, "Qclock")
    if val is not None:
        try:
            settings.qclock = float(val)
        except (ValueError, TypeError):
            pass

    # Velocity
    val = _get_value(data, "DeftVelocity")
    if val is not None:
        try:
            settings.default_velocity = int(val)
        except (ValueError, TypeError):
            pass

    # Volume
    val = _get_value(data, "DeftVolume")
    if val is not None:
        try:
            settings.default_volume = int(val)
        except (ValueError, TypeError):
            pass

    # C4 key
    val = _get_value(data, "C4key")
    if val is not None:
        try:
            settings.c4_key = int(val)
        except (ValueError, TypeError):
            pass

    # A4 frequency
    val = _get_value(data, "A4freq")
    if val is not None:
        try:
            settings.a4_freq = float(val)
        except (ValueError, TypeError):
            pass

    # Quantization
    val = _get_value(data, "Quantization")
    if val is not None:
        try:
            settings.quantization = int(val)
        except (ValueError, TypeError):
            pass

    # Striated time
    val = _get_value(data, "Nature_of_time")
    if val is not None:
        try:
            settings.striated_time = int(val) == 1
        except (ValueError, TypeError):
            pass

    return settings


def parse_settings_dir(dir_path: str | Path) -> dict[str, BP3Settings]:
    """Parse all -se.* files in a directory.

    Args:
        dir_path: Directory containing BP3 files

    Returns:
        Dict mapping file names (without -se. prefix) to BP3Settings
    """
    dir_path = Path(dir_path)
    results = {}

    for path in dir_path.glob("-se.*"):
        try:
            settings = parse_settings_file(path)
            results[settings.name] = settings
        except Exception:
            pass

    return results
