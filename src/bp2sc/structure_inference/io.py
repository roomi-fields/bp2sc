"""I/O adapters for loading MIDI and MusicXML files.

Uses music21 for parsing. Install with: pip install music21
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .grouping import NoteEvent

if TYPE_CHECKING:
    from music21.stream import Score


def load_file(path: str | Path) -> list[NoteEvent]:
    """Load notes from a MIDI or MusicXML file.

    Args:
        path: Path to MIDI (.mid, .midi) or MusicXML (.xml, .mxl, .musicxml) file

    Returns:
        List of NoteEvent objects sorted by onset time

    Raises:
        ImportError: If music21 is not installed
        FileNotFoundError: If file doesn't exist
    """
    try:
        from music21 import converter
    except ImportError:
        raise ImportError(
            "music21 is required for file loading. "
            "Install with: pip install music21"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    score = converter.parse(str(path))
    return _score_to_notes(score)


def _score_to_notes(score: Score) -> list[NoteEvent]:
    """Convert a music21 Score to a list of NoteEvents.

    Args:
        score: music21 Score object

    Returns:
        List of NoteEvent objects sorted by onset time
    """
    from music21 import chord, note

    notes: list[NoteEvent] = []

    for element in score.flatten().notesAndRests:
        # Skip rests
        if isinstance(element, note.Rest):
            continue

        # Handle chords (multiple notes at same onset)
        if isinstance(element, chord.Chord):
            for pitch in element.pitches:
                notes.append(_make_note_event(
                    pitch=pitch.midi,
                    offset=element.offset,
                    duration=element.quarterLength,
                    velocity=element.volume.velocity,
                    pitch_obj=pitch,
                ))
        # Handle single notes
        elif isinstance(element, note.Note):
            notes.append(_make_note_event(
                pitch=element.pitch.midi,
                offset=element.offset,
                duration=element.quarterLength,
                velocity=element.volume.velocity,
                pitch_obj=element.pitch,
            ))

    # Sort by onset time, then by pitch (for consistent ordering)
    notes.sort(key=lambda n: (n.onset, n.pitch))

    return notes


def _make_note_event(
    pitch: int,
    offset: float,
    duration: float,
    velocity: int | None,
    pitch_obj,
) -> NoteEvent:
    """Create a NoteEvent from music21 note data."""
    # Generate note name (e.g., "C4", "F#5")
    name = pitch_obj.nameWithOctave if pitch_obj else None

    return NoteEvent(
        pitch=pitch,
        onset=float(offset),
        duration=float(duration),
        velocity=velocity if velocity is not None else 80,
        name=name,
    )


def load_midi(path: str | Path) -> list[NoteEvent]:
    """Load notes from a MIDI file.

    Convenience wrapper for load_file().
    """
    return load_file(path)


def load_musicxml(path: str | Path) -> list[NoteEvent]:
    """Load notes from a MusicXML file.

    Convenience wrapper for load_file().
    """
    return load_file(path)
